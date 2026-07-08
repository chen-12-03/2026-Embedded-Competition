"""轻量摄像头预览与实时识别服务。"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Optional

from ..board_defaults import (
    DEFAULT_BOARD_CAMERA_CLASSIFICATION_FPS,
    DEFAULT_BOARD_CAMERA_FPS,
    DEFAULT_BOARD_CAMERA_FORMAT,
    DEFAULT_BOARD_CAMERA_HEIGHT,
    DEFAULT_BOARD_CAMERA_ID,
    DEFAULT_BOARD_CAMERA_WEB_FPS,
    DEFAULT_BOARD_CAMERA_WIDTH,
)
from .camera_manager import CameraManager, LatestFrameReader
from .low_latency_preview import LatestJPEGProcessor
from ..detection.shape_color_classifier import (
    ShapeColorResultConverter,
    TraditionalShapeColorClassifier,
)

logger = logging.getLogger(__name__)


class CameraWebPreviewService:
    """为 Web API 提供可开关的预览流和持续运行的实时识别。"""

    def __init__(
        self,
        camera_id: str = DEFAULT_BOARD_CAMERA_ID,
        camera_fps: int = DEFAULT_BOARD_CAMERA_FPS,
        fps: int = DEFAULT_BOARD_CAMERA_WEB_FPS,
        width: int = DEFAULT_BOARD_CAMERA_WIDTH,
        height: int = DEFAULT_BOARD_CAMERA_HEIGHT,
        camera_format: str = DEFAULT_BOARD_CAMERA_FORMAT,
        prefer_gstreamer: bool = True,
        jpeg_quality: int = 60,
        opencv_threads: int = 2,
        enable_classification: bool = True,
        classification_fps: int = DEFAULT_BOARD_CAMERA_CLASSIFICATION_FPS,
        min_contour_area: int = 500,
        max_contours: int = 8,
    ):
        self.camera_id = camera_id
        self.camera_fps = camera_fps
        self.fps = max(1, fps)
        self.width = width
        self.height = height
        self.camera_format = camera_format
        self.prefer_gstreamer = prefer_gstreamer
        self.jpeg_quality = max(10, min(100, jpeg_quality))
        self.opencv_threads = max(1, opencv_threads)
        self.enable_classification = bool(enable_classification)
        self.classification_fps = max(1, classification_fps)
        self.classifier = (
            TraditionalShapeColorClassifier(
                min_contour_area=min_contour_area,
                max_contours_per_color=max_contours,
            )
            if self.enable_classification
            else None
        )

        self.camera: Optional[CameraManager] = None
        self.reader: Optional[LatestFrameReader] = None
        self.jpeg_processor: Optional[LatestJPEGProcessor] = None
        self._classification_thread: Optional[threading.Thread] = None
        self._classification_stop_event = threading.Event()
        self._open_error: Optional[str] = None
        self._result_lock = threading.Lock()
        self._latest_vision_result = None
        self._latest_vision_at: Optional[str] = None
        self._latest_detection_count = 0

    def _ensure_core_started(self):
        if self.camera is not None and self.reader is not None:
            return

        self.camera = CameraManager(
            camera_id=self.camera_id,
            fps=self.camera_fps,
            width=self.width,
            height=self.height,
            pixel_format=self.camera_format,
            prefer_gstreamer=self.prefer_gstreamer,
        )
        self.reader = LatestFrameReader(self.camera, reconnect_after_failures=3)
        self.reader.start()
        self._start_classification_loop()
        self._open_error = None
        logger.info("Camera preview core started: %s", self.camera.get_properties())

    def _start_preview_stream(self):
        if self.jpeg_processor is not None:
            return
        if self.reader is None:
            self._ensure_core_started()

        self.jpeg_processor = LatestJPEGProcessor(
            reader=self.reader,
            fps=self.fps,
            width=self.width,
            height=self.height,
            jpeg_quality=self.jpeg_quality,
            opencv_threads=self.opencv_threads,
        )
        self.jpeg_processor.start()
        logger.info("Camera preview stream enabled")

    def _stop_preview_stream(self):
        if self.jpeg_processor is not None:
            self.jpeg_processor.stop()
            self.jpeg_processor = None
            logger.info("Camera preview stream disabled")

    def _start_classification_loop(self):
        if self.classifier is None:
            return
        if self._classification_thread is not None and self._classification_thread.is_alive():
            return

        self._classification_stop_event.clear()
        self._classification_thread = threading.Thread(
            target=self._classification_loop,
            name="camera-live-classifier",
            daemon=True,
        )
        self._classification_thread.start()

    def _classification_loop(self):
        after_sequence = -1
        frame_interval = 1.0 / float(self.classification_fps)
        next_frame_time = time.monotonic()

        while not self._classification_stop_event.is_set():
            remaining = next_frame_time - time.monotonic()
            if remaining > 0 and self._classification_stop_event.wait(remaining):
                break

            reader = self.reader
            if reader is None:
                break

            success, frame, sequence, _ = reader.read_latest(
                after_sequence=after_sequence,
                timeout=1.0,
            )
            if not success or frame is None:
                next_frame_time = max(next_frame_time + frame_interval, time.monotonic())
                continue

            after_sequence = sequence
            if frame.shape[1] != self.width or frame.shape[0] != self.height:
                import cv2

                working_frame = cv2.resize(
                    frame,
                    (self.width, self.height),
                    interpolation=cv2.INTER_AREA,
                )
            else:
                working_frame = frame

            try:
                results = self.classifier.classify(working_frame)
            except Exception as exc:
                logger.exception("Live preview classification failed")
                self._open_error = str(exc)
                next_frame_time = max(next_frame_time + frame_interval, time.monotonic())
                continue

            best_result = (
                ShapeColorResultConverter.to_dict(results[0])
                if results
                else {
                    "success": False,
                    "details": "实时预览未识别到目标",
                }
            )
            best_result["source"] = "live_preview"
            detected_at = datetime.now().isoformat()

            with self._result_lock:
                self._latest_vision_result = dict(best_result)
                self._latest_vision_at = detected_at
                self._latest_detection_count = len(results)

            next_frame_time = max(next_frame_time + frame_interval, time.monotonic())

    def open(self, enable_preview: bool = True):
        try:
            self._ensure_core_started()
            if enable_preview:
                self._start_preview_stream()
            self._open_error = None
        except Exception as exc:
            self._open_error = str(exc)
            logger.exception("Failed to start camera preview service")
            self.close()
            raise

    def set_preview_enabled(self, enabled: bool):
        if enabled:
            self.open(enable_preview=True)
            return

        self._ensure_core_started()
        self._stop_preview_stream()

    def close(self):
        self._stop_preview_stream()

        self._classification_stop_event.set()
        if self._classification_thread is not None:
            self._classification_thread.join(timeout=2.0)
            self._classification_thread = None

        if self.reader is not None:
            self.reader.stop()
            self.reader = None
        if self.camera is not None:
            self.camera.release()
            self.camera = None

        with self._result_lock:
            self._latest_vision_result = None
            self._latest_vision_at = None
            self._latest_detection_count = 0

    def is_running(self) -> bool:
        return self.jpeg_processor is not None

    def is_processing(self) -> bool:
        return self.reader is not None

    def get_snapshot(self):
        if self.jpeg_processor is None:
            return None, 0
        return self.jpeg_processor.get_latest_jpeg(timeout=0.8)

    def get_latest_vision_result(self):
        with self._result_lock:
            if self._latest_vision_result is None:
                return None
            payload = dict(self._latest_vision_result)
            payload["detected_at"] = self._latest_vision_at
            payload["detection_count"] = self._latest_detection_count
            return payload

    def get_status(self) -> dict:
        live_vision_result = self.get_latest_vision_result()
        preview_running = self.jpeg_processor is not None
        core_running = self.reader is not None
        classification_running = (
            self._classification_thread is not None and self._classification_thread.is_alive()
        )

        if self.jpeg_processor is None:
            reader_status = self.reader.get_status() if self.reader is not None else None
            return {
                "ready": False,
                "running": False,
                "core_running": core_running,
                "classification_running": classification_running,
                "last_error": self._open_error,
                "camera_id": self.camera_id,
                "requested_fps": self.camera_fps,
                "preview_fps": self.fps,
                "width": self.width,
                "height": self.height,
                "camera_format": self.camera_format,
                "classification_enabled": self.enable_classification,
                "live_vision_result": live_vision_result,
                "camera": reader_status,
            }

        status = self.jpeg_processor.get_status()
        status.update(
            {
                "running": preview_running,
                "core_running": core_running,
                "classification_running": classification_running,
                "last_error": self._open_error,
                "camera_id": self.camera_id,
                "requested_fps": self.camera_fps,
                "preview_fps": self.fps,
                "camera_format": self.camera_format,
                "classification_enabled": self.enable_classification,
                "live_vision_result": live_vision_result,
            }
        )
        return status
