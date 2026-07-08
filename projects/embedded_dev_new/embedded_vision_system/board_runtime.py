"""
板端连续分拣运行器。

职责：
- 控制传送带连续运行
- 识别物体进入视野中心后停带
- 抓拍图片并调用 NFC + 视觉一致性判断
- 根据判定结果控制舵机分拣
- 将 NFC 读卡结果写入日志
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import cv2

from .board_defaults import (
    DEFAULT_BOARD_CAMERA_ID,
    DEFAULT_BOARD_CAMERA_FPS,
    DEFAULT_BOARD_CAMERA_FORMAT,
    DEFAULT_BOARD_CAMERA_HEIGHT,
    DEFAULT_BOARD_CAMERA_WIDTH,
    DEFAULT_BOARD_CONVEYOR_SPEED,
    DEFAULT_BOARD_NFC_POLL_INTERVAL,
    DEFAULT_BOARD_RUNTIME_CENTER_HOLD_FRAMES,
    DEFAULT_BOARD_RUNTIME_DETECTION_STOP_DELAY_SECONDS,
    DEFAULT_BOARD_RUNTIME_STOP_COOLDOWN_SECONDS,
    DEFAULT_BOARD_RUNTIME_STOP_ON_FIRST_DETECTION,
)
from .camera.camera_manager import CameraManager
from .detection.shape_color_classifier import (
    ShapeColorResultConverter,
    TraditionalShapeColorClassifier,
)
from .hardware import has_readable_text_payload
from .nfc_sample_service import NFCSampleService
from .sorting_system import SortingSystem
from .storage import get_data_path, get_subdir

logger = logging.getLogger(__name__)


@dataclass
class BoardRuntimeConfig:
    """板端连续运行配置。"""

    camera_id: str = DEFAULT_BOARD_CAMERA_ID
    fps: int = DEFAULT_BOARD_CAMERA_FPS
    width: Optional[int] = DEFAULT_BOARD_CAMERA_WIDTH
    height: Optional[int] = DEFAULT_BOARD_CAMERA_HEIGHT
    pixel_format: Optional[str] = DEFAULT_BOARD_CAMERA_FORMAT
    center_tolerance_ratio: float = 0.12
    center_hold_frames: int = DEFAULT_BOARD_RUNTIME_CENTER_HOLD_FRAMES
    stop_on_first_detection: bool = DEFAULT_BOARD_RUNTIME_STOP_ON_FIRST_DETECTION
    detection_stop_delay_seconds: float = DEFAULT_BOARD_RUNTIME_DETECTION_STOP_DELAY_SECONDS
    stop_cooldown_seconds: float = DEFAULT_BOARD_RUNTIME_STOP_COOLDOWN_SECONDS
    capture_settle_time: float = 0.25
    idle_sleep: float = 0.02
    conveyor_speed: int = DEFAULT_BOARD_CONVEYOR_SPEED
    max_frames_without_detection_log: int = 60
    capture_dir: Optional[str] = None
    nfc_log_path: Optional[str] = None
    require_nfc_text: bool = True
    nfc_retry_interval: float = DEFAULT_BOARD_NFC_POLL_INTERVAL


class BoardSortingRuntime:
    """板端连续分拣状态机。"""

    def __init__(
        self,
        system: SortingSystem,
        camera: Optional[CameraManager] = None,
        classifier: Optional[TraditionalShapeColorClassifier] = None,
        config: Optional[BoardRuntimeConfig] = None,
        nfc_sample_service: Optional[NFCSampleService] = None,
    ):
        self.system = system
        self.config = config or BoardRuntimeConfig()
        self.nfc_sample_service = nfc_sample_service
        self.camera = camera or CameraManager(
            camera_id=self.config.camera_id,
            fps=self.config.fps,
            width=self.config.width,
            height=self.config.height,
            pixel_format=self.config.pixel_format,
        )
        self.classifier = classifier or TraditionalShapeColorClassifier()
        self.capture_dir = (
            Path(self.config.capture_dir)
            if self.config.capture_dir
            else get_subdir("captures", "board_runtime")
        )
        self.nfc_log_path = (
            Path(self.config.nfc_log_path)
            if self.config.nfc_log_path
            else get_data_path("logs", "nfc_reads.jsonl")
        )

        self._centered_streak = 0
        self._frames_since_detection_log = 0
        self._processed_items = 0
        self._last_consumed_nfc_sample_at: Optional[str] = None
        self._selected_nfc_sample_at: Optional[str] = None
        self._stop_cooldown_until_monotonic = 0.0

    def startup(self) -> bool:
        """启动系统和传送带。"""
        ready = self.system.startup()
        if not ready:
            return False

        if self.system.device_controller.conveyor.current_speed != self.config.conveyor_speed:
            self.system.device_controller.resume_conveyor(speed=self.config.conveyor_speed)
        return True

    def shutdown(self) -> None:
        self.system.shutdown()
        if hasattr(self.camera, "release"):
            self.camera.release()

    def run(
        self,
        max_items: int = 0,
        max_frames: int = 0,
    ) -> Dict[str, Any]:
        """
        连续运行主循环。

        Args:
            max_items: 最多处理件数，0 表示无限
            max_frames: 最多读取帧数，0 表示无限
        """
        if not self.system.is_ready and not self.startup():
            return {
                "success": False,
                "reason": "系统启动失败",
                "processed_items": 0,
            }

        total_frames = 0
        try:
            while self.system.is_ready:
                if max_items > 0 and self._processed_items >= max_items:
                    break
                if max_frames > 0 and total_frames >= max_frames:
                    break
                if self.system.pending_stop:
                    logger.info("Stop requested while runtime is idle, shutting down")
                    self.system.shutdown()
                    break
                if not self._monitor_health_or_stop():
                    break

                success, frame = self.camera.read_frame()
                if not success or frame is None:
                    time.sleep(self.config.idle_sleep)
                    continue

                total_frames += 1
                candidate = self._detect_candidate(frame)
                if candidate is None:
                    self._centered_streak = 0
                    self._frames_since_detection_log += 1
                    if self._frames_since_detection_log >= self.config.max_frames_without_detection_log:
                        logger.info(
                            "Waiting for object %s...",
                            "detection" if self.config.stop_on_first_detection else "entering center zone",
                        )
                        self._frames_since_detection_log = 0
                    continue

                self._frames_since_detection_log = 0
                if self._is_stop_cooldown_active():
                    self._centered_streak = 0
                    continue

                if self.config.stop_on_first_detection:
                    self._centered_streak = 0
                    processed = self._handle_detected_item(frame, candidate, stop_reason="first_detected")
                    if processed:
                        self._processed_items += 1
                    continue

                if not self._is_candidate_centered(candidate, frame.shape[1]):
                    self._centered_streak = 0
                    continue

                self._centered_streak += 1
                if self._centered_streak < self.config.center_hold_frames:
                    continue

                self._centered_streak = 0
                processed = self._handle_detected_item(frame, candidate, stop_reason="centered")
                if processed:
                    self._processed_items += 1

            return {
                "success": True,
                "processed_items": self._processed_items,
                "total_frames": total_frames,
                "system_status": self.system.get_system_status(),
            }
        finally:
            if self.system.is_ready:
                self.system.save_state()

    def _detect_candidate(self, frame) -> Optional[Dict[str, Any]]:
        result = self.classifier.classify_best(frame)
        if result is None:
            return None
        return ShapeColorResultConverter.to_dict(result)

    def _is_candidate_centered(self, candidate: Dict[str, Any], frame_width: int) -> bool:
        bbox = candidate.get("bbox")
        if not bbox or len(bbox) != 4:
            return False

        left, _, right, _ = bbox
        object_center_x = (float(left) + float(right)) / 2.0
        frame_center_x = float(frame_width) / 2.0
        tolerance = float(frame_width) * self.config.center_tolerance_ratio
        centered = abs(object_center_x - frame_center_x) <= tolerance
        if centered:
            logger.info(
                "Object centered: label=%s center_x=%.1f frame_center=%.1f tolerance=%.1f",
                candidate.get("label"),
                object_center_x,
                frame_center_x,
                tolerance,
            )
        return centered

    def _handle_detected_item(self, frame, candidate: Dict[str, Any], stop_reason: str) -> bool:
        observed_nfc_results: list[Dict[str, Any]] = []
        nfc_wait_baseline = self._capture_nfc_wait_baseline_snapshot()
        nfc_wait_baseline_sample_at = nfc_wait_baseline.get("sampled_at") if nfc_wait_baseline else None
        self._append_observed_nfc_snapshot(
            observed_nfc_results,
            payload=(nfc_wait_baseline or {}).get("sample"),
            source=(nfc_wait_baseline or {}).get("source") or "pre_stop_snapshot",
            sampled_at=(nfc_wait_baseline or {}).get("sampled_at"),
        )
        delay_seconds = max(0.0, float(self.config.detection_stop_delay_seconds))
        if delay_seconds > 0:
            logger.info(
                "Object detected (%s), waiting %.2fs before pausing conveyor",
                stop_reason,
                delay_seconds,
            )
            if not self._sleep_until_or_stop(delay_seconds):
                return False

        logger.info("Object detected (%s), pausing conveyor", stop_reason)
        self.system.device_controller.pause_conveyor()
        time.sleep(self.config.capture_settle_time)
        self.system.system_status = "等待NFC文本"
        self.system._runtime_pending_nfc_result = None

        capture_success, capture_frame = self.camera.read_frame()
        if not capture_success or capture_frame is None:
            logger.warning("Failed to refresh capture frame, using previous frame")
            capture_frame = frame

        capture_candidate = self._detect_candidate(capture_frame) or candidate
        stopped_vision_result = dict(capture_candidate) if isinstance(capture_candidate, dict) else None
        nfc_result = self._wait_for_readable_nfc_text(
            baseline_sample_at=nfc_wait_baseline_sample_at,
            observed_nfc_results=observed_nfc_results,
        )
        if nfc_result is None:
            self.system._runtime_pending_nfc_result = None
            return False

        capture_path = self._save_capture(capture_frame, capture_candidate)
        runtime_context = {
            "stop_reason": stop_reason,
            "order_requirement": self.system.get_order_requirement(),
            "stopped_vision_result": stopped_vision_result,
            "selected_nfc_result": dict(nfc_result),
            "observed_nfc_results": observed_nfc_results,
            "detection_stop_delay_seconds": delay_seconds,
        }
        try:
            result = self.system.process_material(
                vision_boxes=None,
                vision_classes=None,
                vision_scores=None,
                class_names=[],
                image=capture_frame,
                capture_path=str(capture_path),
                nfc_result=nfc_result,
                vision_result=stopped_vision_result,
                runtime_context=runtime_context,
            )
        finally:
            self._consume_selected_nfc_sample()
        self.system._runtime_pending_nfc_result = None
        self._append_nfc_log(result)

        logger.info(
            "Processed item: material_id=%s route=%s reason=%s",
            result.material_id,
            result.route,
            result.reason,
        )

        if not self.system.is_ready:
            return False
        self.system.system_status = "运行中"

        if result.route == "side_bin":
            sort_ok = self.system.device_controller.execute_sort()
            if not sort_ok and not self.system.device_controller.conveyor.enabled:
                logger.warning("Sort action failed, resuming conveyor as fallback")
                self.system.device_controller.resume_conveyor(speed=self.config.conveyor_speed)
        elif result.route == "main_line":
            self.system.device_controller.resume_conveyor(speed=self.config.conveyor_speed)
        elif not self.system.device_controller.conveyor.enabled:
            self.system.device_controller.resume_conveyor(speed=self.config.conveyor_speed)
        self._arm_stop_cooldown()
        return True

    def _wait_for_readable_nfc_text(
        self,
        baseline_sample_at: Optional[str] = None,
        observed_nfc_results: Optional[list[Dict[str, Any]]] = None,
    ) -> Optional[Dict[str, Any]]:
        self._selected_nfc_sample_at = None
        if self.nfc_sample_service is not None and getattr(self.nfc_sample_service, "enabled", True):
            return self._wait_for_readable_nfc_text_from_service(
                baseline_sample_at=baseline_sample_at,
                observed_nfc_results=observed_nfc_results,
            )

        if not self.config.require_nfc_text:
            payload = self.system.nfc_reader.read()
            self.system._runtime_pending_nfc_result = dict(payload)
            self._append_observed_nfc_snapshot(
                observed_nfc_results,
                payload=payload,
                source="direct_read",
                sampled_at=None,
            )
            return payload

        retry_interval = max(0.05, float(self.config.nfc_retry_interval))
        while self.system.is_ready:
            if self.system.pending_stop:
                logger.info("Stop requested while waiting for NFC text, shutting down")
                self.system.shutdown()
                return None
            if not self._monitor_health_or_stop():
                return None

            payload = self.system.nfc_reader.read()
            self.system._runtime_pending_nfc_result = dict(payload)
            self._append_observed_nfc_snapshot(
                observed_nfc_results,
                payload=payload,
                source="direct_read",
                sampled_at=None,
            )
            if has_readable_text_payload(payload):
                logger.info("Readable NFC text acquired, continuing process flow")
                return payload

            logger.info(
                "Waiting for readable NFC text before resuming conveyor: success=%s error=%s",
                payload.get("success"),
                payload.get("error"),
            )
            if self.system.pending_stop or not self.system.is_ready:
                break
            time.sleep(retry_interval)

        return None

    def _wait_for_readable_nfc_text_from_service(
        self,
        baseline_sample_at: Optional[str] = None,
        observed_nfc_results: Optional[list[Dict[str, Any]]] = None,
    ) -> Optional[Dict[str, Any]]:
        retry_interval = max(0.05, float(self.config.nfc_retry_interval))
        last_observed_sample_at: Optional[str] = None

        while self.system.is_ready:
            if self.system.pending_stop:
                logger.info("Stop requested while waiting for NFC text, shutting down")
                self.system.shutdown()
                return None
            if not self._monitor_health_or_stop():
                return None

            latched_snapshot = self._peek_latched_nfc_snapshot()
            latched_payload = latched_snapshot.get("sample") if latched_snapshot else None
            latched_sampled_at = latched_snapshot.get("sampled_at") if latched_snapshot else None
            if (
                isinstance(latched_payload, dict)
                and has_readable_text_payload(latched_payload)
                and latched_sampled_at != self._last_consumed_nfc_sample_at
            ):
                self.system._runtime_pending_nfc_result = dict(latched_payload)
                self._selected_nfc_sample_at = latched_sampled_at
                self._append_observed_nfc_snapshot(
                    observed_nfc_results,
                    payload=latched_payload,
                    source=latched_snapshot.get("source") or "latched_readable",
                    sampled_at=latched_sampled_at,
                )
                logger.info("Readable NFC text acquired from latched polling buffer, continuing process flow")
                return latched_payload

            snapshot = self.nfc_sample_service.peek_result()
            payload = snapshot.get("sample")
            sampled_at = snapshot.get("sampled_at")

            if isinstance(payload, dict):
                self.system._runtime_pending_nfc_result = dict(payload)
                self._append_observed_nfc_snapshot(
                    observed_nfc_results,
                    payload=payload,
                    source=snapshot.get("source") or "poll",
                    sampled_at=sampled_at,
                )

            is_new_sample = (
                bool(sampled_at)
                and sampled_at != self._last_consumed_nfc_sample_at
                and sampled_at != baseline_sample_at
            )
            if is_new_sample and isinstance(payload, dict) and has_readable_text_payload(payload):
                self._selected_nfc_sample_at = sampled_at
                logger.info("Readable NFC text acquired from continuous polling, continuing process flow")
                return payload

            if sampled_at and sampled_at != last_observed_sample_at and isinstance(payload, dict):
                logger.info(
                    "Waiting for readable NFC text from continuous polling: success=%s error=%s source=%s",
                    payload.get("success"),
                    payload.get("error"),
                    snapshot.get("source"),
                )
                last_observed_sample_at = sampled_at

            if self.system.pending_stop or not self.system.is_ready:
                break
            time.sleep(retry_interval)

        return None

    def _capture_nfc_wait_baseline_snapshot(self) -> Optional[Dict[str, Any]]:
        if self.nfc_sample_service is None or not getattr(self.nfc_sample_service, "enabled", True):
            return None

        latched_snapshot = self._peek_latched_nfc_snapshot()
        if latched_snapshot is not None:
            payload = latched_snapshot.get("sample")
            if isinstance(payload, dict):
                self.system._runtime_pending_nfc_result = dict(payload)
            return latched_snapshot

        snapshot = self.nfc_sample_service.peek_result()
        payload = snapshot.get("sample")
        if isinstance(payload, dict):
            self.system._runtime_pending_nfc_result = dict(payload)
        return {
            "sample": dict(payload) if isinstance(payload, dict) else None,
            "sampled_at": snapshot.get("sampled_at"),
            "source": snapshot.get("source"),
        }

    def _peek_latched_nfc_snapshot(self) -> Optional[Dict[str, Any]]:
        if self.nfc_sample_service is None:
            return None
        peek_latched = getattr(self.nfc_sample_service, "peek_latched_result", None)
        if not callable(peek_latched):
            return None
        snapshot = peek_latched()
        if not isinstance(snapshot, dict):
            return None
        payload = snapshot.get("sample")
        return {
            "sample": dict(payload) if isinstance(payload, dict) else None,
            "sampled_at": snapshot.get("sampled_at"),
            "source": snapshot.get("source"),
        }

    def _consume_selected_nfc_sample(self) -> None:
        selected_sample_at = self._selected_nfc_sample_at
        self._selected_nfc_sample_at = None
        if selected_sample_at is None:
            return
        self._last_consumed_nfc_sample_at = selected_sample_at
        if self.nfc_sample_service is None:
            return
        consume = getattr(self.nfc_sample_service, "mark_latched_result_consumed", None)
        if callable(consume):
            consume(sampled_at=selected_sample_at)

    def _is_stop_cooldown_active(self) -> bool:
        if self.config.stop_cooldown_seconds <= 0:
            return False
        return time.monotonic() < self._stop_cooldown_until_monotonic

    def _arm_stop_cooldown(self) -> None:
        if self.config.stop_cooldown_seconds <= 0:
            self._stop_cooldown_until_monotonic = 0.0
            return
        if not getattr(self.system.device_controller.conveyor, "enabled", False):
            return
        self._stop_cooldown_until_monotonic = (
            time.monotonic() + float(self.config.stop_cooldown_seconds)
        )

    def _sleep_until_or_stop(self, duration_seconds: float) -> bool:
        end_time = time.monotonic() + max(0.0, float(duration_seconds))
        while self.system.is_ready:
            if self.system.pending_stop:
                logger.info("Stop requested while waiting before conveyor pause, shutting down")
                self.system.shutdown()
                return False
            if not self._monitor_health_or_stop():
                return False

            remaining = end_time - time.monotonic()
            if remaining <= 0:
                return True
            time.sleep(min(0.05, remaining))
        return False

    def _monitor_health_or_stop(self) -> bool:
        health_snapshot = self.system.monitor_device_health()
        if not health_snapshot.get("stopped"):
            return True

        overall = health_snapshot.get("overall")
        if overall == "red":
            self.system.system_status = "故障停机"
            logger.error(
                "Runtime stopped by device health monitor: overall=%s reasons=%s",
                overall,
                health_snapshot.get("reasons"),
            )
        else:
            self.system.system_status = "告警停机"
            logger.warning(
                "Runtime stopped by device health monitor: overall=%s reasons=%s",
                overall,
                health_snapshot.get("reasons"),
            )
        stop_reason = (
            "设备红色故障，已自动停机保护"
            if overall == "red"
            else "设备黄色告警，已自动停机保护"
        )
        history = self.system.order_manager.record_detection_event(
            material_id=None,
            final_status="待人工处理",
            action="stop",
            route="hold",
            reason=stop_reason,
            anomaly_reasons=health_snapshot.get("reasons"),
            vision_result=None,
            nfc_result=None,
            comparison_result=None,
            health_snapshot=health_snapshot,
            capture_path=None,
            runtime_context={"stop_reason": "device_health_monitor"},
        )
        self.system.is_ready = False
        self.system.pending_stop = False
        self.system.current_material_id = None
        self.system.last_processing_result = {
            "success": False,
            "action": "stop",
            "route": "hold",
            "order_status": "WAITING_MANUAL",
            "reason": stop_reason,
            "reasons": health_snapshot.get("reasons"),
            "health_snapshot": health_snapshot,
            "history_record": history.to_dict(),
        }
        self.system.save_state()
        return False

    def _save_capture(self, frame, candidate: Dict[str, Any]) -> Path:
        self.capture_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        label = self._ascii_label(candidate.get("label") or "unknown")
        output_path = self.capture_dir / f"{timestamp}_{label}.jpg"
        cv2.imwrite(str(output_path), frame)
        return output_path

    def _append_nfc_log(self, result) -> None:
        self.nfc_log_path.parent.mkdir(parents=True, exist_ok=True)
        history_record = result.history_record or {}
        payload = {
            "timestamp": datetime.now().isoformat(),
            "material_id": result.material_id,
            "nfc_result": history_record.get("nfc_snapshot"),
            "vision_result": result.vision_result,
            "runtime_context": history_record.get("runtime_context"),
            "decision": {
                "action": result.action,
                "route": result.route,
                "order_status": result.order_status,
                "reason": result.reason,
                "reasons": result.reasons or [],
            },
            "capture_path": history_record.get("capture_path"),
        }
        with self.nfc_log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    @staticmethod
    def _append_observed_nfc_snapshot(
        observed_nfc_results: Optional[list[Dict[str, Any]]],
        payload: Optional[Dict[str, Any]],
        source: Optional[str],
        sampled_at: Optional[str],
    ) -> None:
        if observed_nfc_results is None or not isinstance(payload, dict):
            return

        normalized = {
            "sample": dict(payload),
            "source": source,
            "sampled_at": sampled_at,
        }
        if observed_nfc_results and observed_nfc_results[-1] == normalized:
            return
        observed_nfc_results.append(normalized)

    @staticmethod
    def _ascii_label(raw_label: str) -> str:
        safe = []
        for char in raw_label:
            if char.isascii() and (char.isalnum() or char in {"-", "_"}):
                safe.append(char)
            elif char.isspace():
                safe.append("_")
        normalized = "".join(safe).strip("_")
        return normalized or "item"
