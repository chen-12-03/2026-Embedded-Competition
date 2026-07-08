"""低延迟网页预览处理器。

摄像头采集、图像处理和网页请求解耦：后台只保留最新的 JPEG，
浏览器取图较慢时不会累积旧帧。
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional, Tuple

import cv2
import numpy as np

from .camera_manager import FrameRateTracker, LatestFrameReader

logger = logging.getLogger(__name__)

FrameProcessor = Callable[[np.ndarray], np.ndarray]


def _read_linux_memory_mb(path: str, key: str) -> Optional[float]:
    try:
        with open(path, "r", encoding="ascii") as memory_file:
            for line in memory_file:
                if line.startswith(key):
                    value_kb = float(line.split()[1])
                    return value_kb / 1024.0
    except (OSError, ValueError, IndexError):
        return None
    return None


def _read_max_temperature_c() -> Optional[float]:
    temperatures = []
    for temperature_path in Path("/sys/class/thermal").glob("thermal_zone*/temp"):
        try:
            value = float(temperature_path.read_text(encoding="ascii").strip())
            temperatures.append(value / 1000.0 if value > 1000 else value)
        except (OSError, ValueError):
            continue
    return max(temperatures) if temperatures else None


def _percentile_95(values) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int((len(ordered) - 1) * 0.95))
    return float(ordered[index])


class LatestJPEGProcessor:
    """按固定频率处理最新摄像头帧并缓存一张 JPEG。"""

    def __init__(
        self,
        reader: LatestFrameReader,
        fps: int = 10,
        width: int = 640,
        height: int = 360,
        jpeg_quality: int = 60,
        frame_processor: Optional[FrameProcessor] = None,
        opencv_threads: int = 2,
    ):
        self.reader = reader
        self.fps = max(1, fps)
        self.width = max(1, width)
        self.height = max(1, height)
        self.jpeg_quality = max(10, min(100, jpeg_quality))
        self.frame_processor = frame_processor
        self.opencv_threads = max(1, opencv_threads)

        try:
            cv2.setNumThreads(self.opencv_threads)
            if hasattr(cv2, "ocl"):
                cv2.ocl.setUseOpenCL(False)
        except Exception:
            logger.warning("Could not configure OpenCV worker threads", exc_info=True)

        self._condition = threading.Condition()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._latest_jpeg: Optional[bytes] = None
        self._output_sequence = 0
        self._source_sequence = -1
        self._last_error: Optional[str] = None
        self._memory_status = {
            "process_rss_mb": None,
            "available_memory_mb": None,
            "rss_growth_mb": None,
        }
        self._initial_rss_mb: Optional[float] = None
        self._last_memory_check = 0.0
        self._processing_times = deque(maxlen=120)
        self._jpeg_times = deque(maxlen=120)
        self._last_processing_ms = 0.0
        self._last_jpeg_ms = 0.0
        self._measured_fps = 0.0
        self._frame_timeouts = 0

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._processing_loop,
            name="camera-latest-jpeg",
            daemon=True,
        )
        self._thread.start()

    def _processing_loop(self):
        frame_interval = 1.0 / self.fps
        next_frame_time = time.monotonic()
        fps_tracker = FrameRateTracker(window_seconds=1.0)
        encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality]

        while not self._stop_event.is_set():
            remaining = next_frame_time - time.monotonic()
            if remaining > 0 and self._stop_event.wait(remaining):
                break

            success, frame, source_sequence, capture_time = self.reader.read_latest(
                after_sequence=self._source_sequence,
                timeout=1.0,
            )
            if not success or frame is None:
                with self._condition:
                    self._frame_timeouts += 1
                self._set_error("camera frame timeout")
                next_frame_time = max(
                    next_frame_time + frame_interval,
                    time.monotonic(),
                )
                continue

            started_at = time.monotonic()
            try:
                if frame.shape[1] == self.width and frame.shape[0] == self.height:
                    resized = frame
                else:
                    resized = cv2.resize(
                        frame,
                        (self.width, self.height),
                        interpolation=cv2.INTER_AREA,
                    )
                output = (
                    self.frame_processor(resized)
                    if self.frame_processor is not None
                    else resized.copy()
                )
                cv_elapsed_ms = (time.monotonic() - started_at) * 1000.0
                now = time.monotonic()
                measured_fps = fps_tracker.tick(now)
                capture_age_ms = max(0.0, (now - capture_time) * 1000.0)
                memory_status = self._get_memory_status(now)
                self._draw_metrics(
                    output,
                    measured_fps,
                    cv_elapsed_ms,
                    capture_age_ms,
                    memory_status,
                )

                jpeg_started_at = time.monotonic()
                encoded, jpeg = cv2.imencode(".jpg", output, encode_params)
                if not encoded:
                    raise RuntimeError("JPEG encoding failed")
                jpeg_elapsed_ms = (time.monotonic() - jpeg_started_at) * 1000.0
            except Exception as exc:
                logger.exception("Failed to process camera frame")
                self._set_error(str(exc))
                next_frame_time = max(
                    next_frame_time + frame_interval,
                    time.monotonic(),
                )
                continue

            with self._condition:
                self._latest_jpeg = jpeg.tobytes()
                self._source_sequence = source_sequence
                self._output_sequence += 1
                self._last_error = None
                self._last_processing_ms = cv_elapsed_ms
                self._last_jpeg_ms = jpeg_elapsed_ms
                self._measured_fps = measured_fps
                self._processing_times.append(cv_elapsed_ms)
                self._jpeg_times.append(jpeg_elapsed_ms)
                self._condition.notify_all()

            next_frame_time = max(
                next_frame_time + frame_interval,
                time.monotonic(),
            )

        with self._condition:
            self._condition.notify_all()

    @staticmethod
    def _draw_metrics(
        frame: np.ndarray,
        fps: float,
        cv_elapsed_ms: float,
        capture_age_ms: float,
        memory_status: dict,
    ):
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        performance_text = (
            f"{timestamp} FPS:{fps:.1f} "
            f"CV:{cv_elapsed_ms:.0f}ms Age:{capture_age_ms:.0f}ms"
        )
        rss_mb = memory_status.get("process_rss_mb")
        available_mb = memory_status.get("available_memory_mb")
        memory_text = (
            f"RSS:{rss_mb:.0f}MB Free:{available_mb:.0f}MB"
            if rss_mb is not None and available_mb is not None
            else "RSS/Free: unavailable"
        )
        for text, y_position in (
            (performance_text, frame.shape[0] - 32),
            (memory_text, frame.shape[0] - 10),
        ):
            cv2.putText(
                frame,
                text,
                (10, y_position),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.48,
                (0, 0, 0),
                3,
            )
            cv2.putText(
                frame,
                text,
                (10, y_position),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.48,
                (255, 255, 255),
                1,
            )

    def _get_memory_status(self, now: Optional[float] = None, force: bool = False) -> dict:
        check_time = time.monotonic() if now is None else now
        if force or check_time - self._last_memory_check >= 2.0:
            rss_mb = _read_linux_memory_mb("/proc/self/status", "VmRSS:")
            available_mb = _read_linux_memory_mb("/proc/meminfo", "MemAvailable:")
            if self._initial_rss_mb is None and rss_mb is not None:
                self._initial_rss_mb = rss_mb
            growth_mb = (
                rss_mb - self._initial_rss_mb
                if rss_mb is not None and self._initial_rss_mb is not None
                else None
            )
            self._memory_status = {
                "process_rss_mb": rss_mb,
                "available_memory_mb": available_mb,
                "rss_growth_mb": growth_mb,
            }
            self._last_memory_check = check_time
        return self._memory_status.copy()

    def _set_error(self, message: str):
        with self._condition:
            self._last_error = message
            self._condition.notify_all()

    def get_latest_jpeg(self, timeout: float = 2.0) -> Tuple[Optional[bytes], int]:
        """返回最新 JPEG；首帧未就绪时最多等待 timeout 秒。"""
        deadline = time.monotonic() + max(0.0, timeout)
        with self._condition:
            while self._latest_jpeg is None and not self._stop_event.is_set():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(remaining)
            return self._latest_jpeg, self._output_sequence

    def get_status(self) -> dict:
        memory_status = self._get_memory_status(force=True)
        try:
            load_average_1m = os.getloadavg()[0]
        except OSError:
            load_average_1m = None
        temperature_c = _read_max_temperature_c()
        camera_status = self.reader.get_status()
        with self._condition:
            return {
                "ready": self._latest_jpeg is not None,
                "output_sequence": self._output_sequence,
                "source_sequence": self._source_sequence,
                "last_error": self._last_error,
                "fps": self.fps,
                "width": self.width,
                "height": self.height,
                "jpeg_quality": self.jpeg_quality,
                "opencv_threads": self.opencv_threads,
                "measured_fps": self._measured_fps,
                "processing_last_ms": self._last_processing_ms,
                "processing_p95_ms": _percentile_95(self._processing_times),
                "jpeg_last_ms": self._last_jpeg_ms,
                "jpeg_p95_ms": _percentile_95(self._jpeg_times),
                "frame_timeouts": self._frame_timeouts,
                "load_average_1m": load_average_1m,
                "temperature_c": temperature_c,
                "camera": camera_status,
                **memory_status,
            }

    def stop(self):
        self._stop_event.set()
        with self._condition:
            self._condition.notify_all()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            if self._thread.is_alive():
                logger.warning("JPEG processing thread did not stop within timeout")
            self._thread = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()


__all__ = ["FrameProcessor", "LatestJPEGProcessor"]
