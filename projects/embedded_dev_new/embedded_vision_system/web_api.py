"""
轻量 Web API
用于买家录单、监控查询和设备控制
"""

import os
import logging
import atexit
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from flask import Flask, Response, jsonify, render_template, request, send_file

from .board_defaults import (
    DEFAULT_BOARD_CAMERA_ID,
    DEFAULT_BOARD_CAMERA_CLASSIFICATION_FPS,
    DEFAULT_BOARD_CAMERA_FPS,
    DEFAULT_BOARD_CAMERA_FORMAT,
    DEFAULT_BOARD_CAMERA_HEIGHT,
    DEFAULT_BOARD_CAMERA_WEB_FPS,
    DEFAULT_BOARD_CAMERA_WIDTH,
    DEFAULT_BOARD_CONVEYOR_SPEED,
    DEFAULT_BOARD_CONVEYOR_SPEED_MODE,
    DEFAULT_BOARD_CONVEYOR_STEP_MAX_HZ,
    DEFAULT_BOARD_CONTROL_UART_BAUDRATE,
    DEFAULT_BOARD_CONTROL_UART_PORT,
    DEFAULT_BOARD_CONTROL_UART_TIMEOUT,
    DEFAULT_BOARD_MPU6050_I2C_ADDRESS,
    DEFAULT_BOARD_MPU6050_I2C_BUS,
    DEFAULT_BOARD_MPU6050_RED_THRESHOLD,
    DEFAULT_BOARD_MPU6050_YELLOW_THRESHOLD,
    DEFAULT_BOARD_NFC_BACKEND,
    DEFAULT_BOARD_NFC_FALLBACK_TO_UID,
    DEFAULT_BOARD_NFC_I2C_ADDRESS,
    DEFAULT_BOARD_NFC_I2C_BUS,
    DEFAULT_BOARD_NFC_PASSIVE_ACTIVATION_RETRIES,
    DEFAULT_BOARD_NFC_POLL_ENABLED,
    DEFAULT_BOARD_NFC_POLL_INTERVAL,
    DEFAULT_BOARD_NFC_SCAN_TIMEOUT,
    DEFAULT_BOARD_RUNTIME_CENTER_HOLD_FRAMES,
    DEFAULT_BOARD_RUNTIME_DETECTION_STOP_DELAY_SECONDS,
    DEFAULT_BOARD_RUNTIME_STOP_COOLDOWN_SECONDS,
    DEFAULT_BOARD_RUNTIME_STOP_ON_FIRST_DETECTION,
    DEFAULT_BOARD_SERVO_NORMAL_ANGLE,
    DEFAULT_BOARD_SERVO_SORT_ANGLE,
    DEFAULT_BOARD_SERVO_SORT_SECONDARY_ANGLE,
    DEFAULT_BOARD_SORT_CONVEYOR_ADVANCE_SECONDS,
    DEFAULT_BOARD_SORT_PREPARE_PAUSE_SECONDS,
    DEFAULT_BOARD_SORT_SERVO_OSCILLATION_INTERVAL,
    DEFAULT_BOARD_SORT_SERVO_SETTLE_SECONDS,
    DEFAULT_BOARD_SERVO_BACKEND,
    DEFAULT_BOARD_CONVEYOR_BACKEND,
    DEFAULT_BOARD_VIBRATION_BACKEND,
)
from .board_runtime import BoardRuntimeConfig, BoardSortingRuntime
from .device_controller import build_device_controller
from .hardware import create_nfc_reader, has_readable_text_payload, is_uid_fallback_payload
from .nfc_sample_service import NFCSampleService
from .order_manager import OrderManager
from .sorting_system import SortingSystem, SystemMode
from .storage import get_data_path

logger = logging.getLogger(__name__)


def _default_state_path() -> Path:
    env_value = os.environ.get("EMBEDDED_VISION_STATE_PATH")
    if env_value:
        return Path(env_value)
    return get_data_path("runtime_data", "orders_state.json")


def _get_buffered_nfc_payload(sorting_system: SortingSystem) -> Optional[Dict[str, Any]]:
    runtime_payload = getattr(sorting_system, "_runtime_pending_nfc_result", None)
    if isinstance(runtime_payload, dict):
        return dict(runtime_payload)
    payload = getattr(sorting_system.nfc_reader, "last_read", None)
    if isinstance(payload, dict):
        return dict(payload)
    return None


def _parse_env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _parse_env_int(name: str, default: int) -> int:
    return int(os.environ.get(name, str(default)), 0)


def _parse_env_optional_int(name: str) -> Optional[int]:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return None
    return int(raw, 0)


def _parse_env_optional_decimal_int(name: str, default: Optional[int] = None) -> Optional[int]:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return int(raw)


def _build_board_runtime_config_from_env(preview=None) -> BoardRuntimeConfig:
    preview_camera_id = getattr(preview, "camera_id", DEFAULT_BOARD_CAMERA_ID)
    preview_camera_fps = getattr(preview, "camera_fps", DEFAULT_BOARD_CAMERA_FPS)
    preview_width = getattr(preview, "width", DEFAULT_BOARD_CAMERA_WIDTH)
    preview_height = getattr(preview, "height", DEFAULT_BOARD_CAMERA_HEIGHT)
    preview_camera_format = getattr(preview, "camera_format", DEFAULT_BOARD_CAMERA_FORMAT)
    return BoardRuntimeConfig(
        camera_id=os.environ.get("EMBEDDED_VISION_CAMERA_ID", preview_camera_id),
        fps=int(os.environ.get("EMBEDDED_VISION_CAMERA_FPS", str(preview_camera_fps))),
        width=_parse_env_optional_decimal_int("EMBEDDED_VISION_CAMERA_WIDTH", preview_width),
        height=_parse_env_optional_decimal_int("EMBEDDED_VISION_CAMERA_HEIGHT", preview_height),
        pixel_format=os.environ.get("EMBEDDED_VISION_CAMERA_FORMAT", preview_camera_format),
        center_tolerance_ratio=float(
            os.environ.get("EMBEDDED_VISION_RUNTIME_CENTER_TOLERANCE_RATIO", "0.12")
        ),
        center_hold_frames=int(
            os.environ.get(
                "EMBEDDED_VISION_RUNTIME_CENTER_HOLD_FRAMES",
                str(DEFAULT_BOARD_RUNTIME_CENTER_HOLD_FRAMES),
            )
        ),
        stop_on_first_detection=_parse_env_bool(
            "EMBEDDED_VISION_RUNTIME_STOP_ON_FIRST_DETECTION",
            DEFAULT_BOARD_RUNTIME_STOP_ON_FIRST_DETECTION,
        ),
        detection_stop_delay_seconds=float(
            os.environ.get(
                "EMBEDDED_VISION_RUNTIME_DETECTION_STOP_DELAY_SECONDS",
                str(DEFAULT_BOARD_RUNTIME_DETECTION_STOP_DELAY_SECONDS),
            )
        ),
        stop_cooldown_seconds=float(
            os.environ.get(
                "EMBEDDED_VISION_RUNTIME_STOP_COOLDOWN_SECONDS",
                str(DEFAULT_BOARD_RUNTIME_STOP_COOLDOWN_SECONDS),
            )
        ),
        capture_settle_time=float(
            os.environ.get("EMBEDDED_VISION_RUNTIME_CAPTURE_SETTLE_TIME", "0.25")
        ),
        idle_sleep=float(os.environ.get("EMBEDDED_VISION_RUNTIME_IDLE_SLEEP", "0.02")),
        conveyor_speed=_parse_env_int("EMBEDDED_VISION_CONVEYOR_SPEED", DEFAULT_BOARD_CONVEYOR_SPEED),
        max_frames_without_detection_log=int(
            os.environ.get("EMBEDDED_VISION_RUNTIME_MAX_FRAMES_WITHOUT_DETECTION_LOG", "60")
        ),
        capture_dir=os.environ.get("EMBEDDED_VISION_CAPTURE_DIR") or None,
        nfc_log_path=os.environ.get("EMBEDDED_VISION_NFC_LOG_PATH") or None,
        require_nfc_text=_parse_env_bool("EMBEDDED_VISION_RUNTIME_REQUIRE_NFC_TEXT", True),
        nfc_retry_interval=float(
            os.environ.get(
                "EMBEDDED_VISION_RUNTIME_NFC_RETRY_INTERVAL",
                str(DEFAULT_BOARD_NFC_POLL_INTERVAL),
            )
        ),
    )


class _SharedPreviewCameraAdapter:
    """让板端 runtime 复用 WebUI 已启动的摄像头采集线程。"""

    def __init__(self, preview, frame_timeout: float = 0.5):
        self.preview = preview
        self.frame_timeout = max(0.05, float(frame_timeout))
        self._after_sequence = -1

    def read_frame(self):
        reader = getattr(self.preview, "reader", None)
        if reader is None:
            return False, None

        success, frame, sequence, _ = reader.read_latest(
            after_sequence=self._after_sequence,
            timeout=self.frame_timeout,
        )
        if not success or frame is None:
            return False, None

        self._after_sequence = sequence
        return True, frame

    def release(self):
        return None


class WebRuntimeController:
    """在 Web API 进程里托管完整板端分拣运行时。"""

    def __init__(
        self,
        sorting_system: SortingSystem,
        preview=None,
        nfc_sample_service: Optional[NFCSampleService] = None,
    ):
        self.sorting_system = sorting_system
        self.preview = preview
        self.nfc_sample_service = nfc_sample_service
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._runtime: Optional[BoardSortingRuntime] = None
        self._last_result: Optional[Dict[str, Any]] = None
        self._last_error: Optional[str] = None
        self._started_at: Optional[str] = None
        self._finished_at: Optional[str] = None
        self._camera_source = "runtime_owned"

    def _create_runtime(self) -> BoardSortingRuntime:
        config = _build_board_runtime_config_from_env(self.preview)
        shared_camera = None

        if self.preview is not None:
            try:
                preview_running = False
                is_running = getattr(self.preview, "is_running", None)
                if callable(is_running):
                    preview_running = bool(is_running())
                self.preview.open(enable_preview=preview_running)
            except Exception as exc:
                logger.warning("Failed to warm up shared preview camera for runtime: %s", exc)
            if getattr(self.preview, "reader", None) is not None:
                shared_camera = _SharedPreviewCameraAdapter(self.preview)
                self._camera_source = "shared_preview"
            else:
                self._camera_source = "runtime_owned"

        return BoardSortingRuntime(
            system=self.sorting_system,
            camera=shared_camera,
            config=config,
            nfc_sample_service=self.nfc_sample_service,
        )

    def _is_running_locked(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def is_running(self) -> bool:
        with self._lock:
            return self._is_running_locked()

    def start(self) -> bool:
        with self._lock:
            if self._is_running_locked():
                return False
            self._last_error = None
            self._last_result = None
            self.sorting_system.pending_stop = False
            if not self.sorting_system.is_ready:
                self.sorting_system.system_status = "启动中"
            self._started_at = datetime.now().isoformat()
            self._finished_at = None
            self._thread = threading.Thread(
                target=self._run_loop,
                name="web-board-runtime",
                daemon=True,
            )
            self._thread.start()
            return True

    def _run_loop(self) -> None:
        runtime = self._create_runtime()
        with self._lock:
            self._runtime = runtime

        try:
            result = runtime.run()
            with self._lock:
                self._last_result = result
        except Exception as exc:
            logger.exception("Board runtime failed inside Web API")
            with self._lock:
                self._last_error = str(exc)
        finally:
            try:
                runtime.shutdown()
            except Exception:
                logger.exception("Failed to shutdown board runtime")
            self.sorting_system.save_state()
            with self._lock:
                self._runtime = None
                self._finished_at = datetime.now().isoformat()
                self._thread = None

    def stop(self) -> Dict[str, Any]:
        running = self.is_running()
        if running:
            self.sorting_system.request_stop()
        elif self.sorting_system.is_ready:
            self.sorting_system.shutdown()
            self.sorting_system.save_state()
        return self.get_status()

    def close(self, join_timeout: float = 3.0) -> None:
        self.stop()
        with self._lock:
            thread = self._thread
        if thread is not None:
            thread.join(timeout=join_timeout)
            if thread.is_alive():
                logger.warning("Board runtime thread did not stop within %.1fs", join_timeout)

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            running = self._is_running_locked()
            return {
                "running": running,
                "stop_requested": self.sorting_system.pending_stop,
                "started_at": self._started_at,
                "finished_at": self._finished_at,
                "camera_source": self._camera_source,
                "last_error": self._last_error,
                "last_result": dict(self._last_result) if isinstance(self._last_result, dict) else self._last_result,
            }


def _create_camera_preview_from_env():
    try:
        from .camera.web_preview import CameraWebPreviewService
    except Exception:
        logger.exception("Camera preview dependencies are unavailable")
        return None

    camera_id = os.environ.get("EMBEDDED_VISION_CAMERA_ID", DEFAULT_BOARD_CAMERA_ID)
    camera_width = int(os.environ.get("EMBEDDED_VISION_CAMERA_WIDTH", str(DEFAULT_BOARD_CAMERA_WIDTH)))
    camera_height = int(os.environ.get("EMBEDDED_VISION_CAMERA_HEIGHT", str(DEFAULT_BOARD_CAMERA_HEIGHT)))
    camera_fps = int(os.environ.get("EMBEDDED_VISION_CAMERA_FPS", str(DEFAULT_BOARD_CAMERA_FPS)))
    preview_fps = int(
        os.environ.get("EMBEDDED_VISION_CAMERA_WEB_FPS", str(DEFAULT_BOARD_CAMERA_WEB_FPS))
    )
    jpeg_quality = int(os.environ.get("EMBEDDED_VISION_CAMERA_JPEG_QUALITY", "60"))
    opencv_threads = int(os.environ.get("EMBEDDED_VISION_CAMERA_OPENCV_THREADS", "2"))
    camera_format = os.environ.get("EMBEDDED_VISION_CAMERA_FORMAT", DEFAULT_BOARD_CAMERA_FORMAT)
    prefer_gstreamer = _parse_env_bool("EMBEDDED_VISION_CAMERA_USE_GSTREAMER", True)
    enable_preview = _parse_env_bool("EMBEDDED_VISION_CAMERA_PREVIEW", True)
    enable_classification = _parse_env_bool("EMBEDDED_VISION_CAMERA_CLASSIFICATION", True)
    classification_fps = int(
        os.environ.get(
            "EMBEDDED_VISION_CAMERA_CLASSIFICATION_FPS",
            str(DEFAULT_BOARD_CAMERA_CLASSIFICATION_FPS),
        )
    )
    min_contour_area = int(os.environ.get("EMBEDDED_VISION_CAMERA_MIN_CONTOUR_AREA", "500"))
    max_contours = int(os.environ.get("EMBEDDED_VISION_CAMERA_MAX_CONTOURS", "8"))

    preview = CameraWebPreviewService(
        camera_id=camera_id,
        camera_fps=camera_fps,
        fps=preview_fps,
        width=camera_width,
        height=camera_height,
        camera_format=camera_format,
        prefer_gstreamer=prefer_gstreamer,
        jpeg_quality=jpeg_quality,
        opencv_threads=opencv_threads,
        enable_classification=enable_classification,
        classification_fps=classification_fps,
        min_contour_area=min_contour_area,
        max_contours=max_contours,
    )

    if enable_preview or enable_classification:
        try:
            preview.open(enable_preview=enable_preview)
        except Exception as exc:
            logger.warning("Camera preview startup failed: %s", exc)
    return preview


def _maybe_configure_nfc_reader_from_env(
    sorting_system: SortingSystem,
    *,
    use_board_defaults: bool = False,
) -> None:
    backend = os.environ.get("EMBEDDED_VISION_NFC_BACKEND")
    if not backend and not use_board_defaults:
        return
    backend = backend or DEFAULT_BOARD_NFC_BACKEND

    reader = create_nfc_reader(
        backend=backend,
        material_ids=os.environ.get("EMBEDDED_VISION_NFC_MATERIAL_IDS", "").split() or None,
        file_path=os.environ.get("EMBEDDED_VISION_NFC_FILE_PATH") or None,
        command=os.environ.get("EMBEDDED_VISION_NFC_COMMAND") or None,
        i2c_bus=int(os.environ.get("EMBEDDED_VISION_NFC_I2C_BUS", str(DEFAULT_BOARD_NFC_I2C_BUS))),
        i2c_address=int(
            os.environ.get("EMBEDDED_VISION_NFC_I2C_ADDRESS", hex(DEFAULT_BOARD_NFC_I2C_ADDRESS)),
            0,
        ),
        spi_bus=int(os.environ.get("EMBEDDED_VISION_NFC_SPI_BUS", "0")),
        spi_device=int(os.environ.get("EMBEDDED_VISION_NFC_SPI_DEVICE", "0")),
        spi_speed_hz=int(os.environ.get("EMBEDDED_VISION_NFC_SPI_SPEED_HZ", "1000000")),
        uart_port=os.environ.get("EMBEDDED_VISION_NFC_UART_PORT", "/dev/ttyS1"),
        uart_baudrate=int(os.environ.get("EMBEDDED_VISION_NFC_UART_BAUDRATE", "115200")),
        command_timeout=float(os.environ.get("EMBEDDED_VISION_NFC_COMMAND_TIMEOUT", "1.0")),
        scan_timeout=float(os.environ.get("EMBEDDED_VISION_NFC_SCAN_TIMEOUT", str(DEFAULT_BOARD_NFC_SCAN_TIMEOUT))),
        read_window_pages=int(os.environ.get("EMBEDDED_VISION_NFC_READ_WINDOW_PAGES", "16")),
        passive_activation_retries=int(
            os.environ.get(
                "EMBEDDED_VISION_NFC_PASSIVE_ACTIVATION_RETRIES",
                hex(DEFAULT_BOARD_NFC_PASSIVE_ACTIVATION_RETRIES),
            ),
            0,
        ),
        fallback_to_uid=_parse_env_bool(
            "EMBEDDED_VISION_NFC_FALLBACK_TO_UID",
            DEFAULT_BOARD_NFC_FALLBACK_TO_UID,
        ),
    )
    sorting_system.nfc_reader = reader
    sorting_system._web_nfc_runtime = {
        "configured_backend": backend,
        "i2c_bus": int(os.environ.get("EMBEDDED_VISION_NFC_I2C_BUS", str(DEFAULT_BOARD_NFC_I2C_BUS))),
        "i2c_address": os.environ.get(
            "EMBEDDED_VISION_NFC_I2C_ADDRESS",
            hex(DEFAULT_BOARD_NFC_I2C_ADDRESS),
        ),
        "scan_timeout": float(
            os.environ.get("EMBEDDED_VISION_NFC_SCAN_TIMEOUT", str(DEFAULT_BOARD_NFC_SCAN_TIMEOUT))
        ),
        "passive_activation_retries": os.environ.get(
            "EMBEDDED_VISION_NFC_PASSIVE_ACTIVATION_RETRIES",
            hex(DEFAULT_BOARD_NFC_PASSIVE_ACTIVATION_RETRIES),
        ),
        "fallback_to_uid": _parse_env_bool(
            "EMBEDDED_VISION_NFC_FALLBACK_TO_UID",
            DEFAULT_BOARD_NFC_FALLBACK_TO_UID,
        ),
        "poll_enabled": _parse_env_bool(
            "EMBEDDED_VISION_NFC_POLL",
            DEFAULT_BOARD_NFC_POLL_ENABLED,
        ),
        "poll_interval": float(
            os.environ.get(
                "EMBEDDED_VISION_NFC_POLL_INTERVAL",
                str(DEFAULT_BOARD_NFC_POLL_INTERVAL),
            )
        ),
    }


def _maybe_configure_device_controller_from_env(
    sorting_system: SortingSystem,
    *,
    use_board_defaults: bool = False,
) -> None:
    servo_backend = os.environ.get("EMBEDDED_VISION_SERVO_BACKEND")
    conveyor_backend = os.environ.get("EMBEDDED_VISION_CONVEYOR_BACKEND")

    if not servo_backend and not conveyor_backend and not use_board_defaults:
        return
    if use_board_defaults:
        servo_backend = servo_backend or DEFAULT_BOARD_SERVO_BACKEND
        conveyor_backend = conveyor_backend or DEFAULT_BOARD_CONVEYOR_BACKEND
    elif not servo_backend or not conveyor_backend:
        raise RuntimeError(
            "EMBEDDED_VISION_SERVO_BACKEND and EMBEDDED_VISION_CONVEYOR_BACKEND must be set together"
        )

    existing_controller = getattr(sorting_system, "device_controller", None)
    sorting_system.device_controller = build_device_controller(
        servo_backend=servo_backend,
        servo_chip=_parse_env_int("EMBEDDED_VISION_SERVO_CHIP", 0),
        servo_channel=_parse_env_int("EMBEDDED_VISION_SERVO_CHANNEL", 0),
        servo_gpio=_parse_env_optional_int("EMBEDDED_VISION_SERVO_GPIO"),
        servo_normal_angle=_parse_env_int("EMBEDDED_VISION_SERVO_NORMAL_ANGLE", DEFAULT_BOARD_SERVO_NORMAL_ANGLE),
        servo_sort_angle=_parse_env_int("EMBEDDED_VISION_SERVO_SORT_ANGLE", DEFAULT_BOARD_SERVO_SORT_ANGLE),
        servo_sort_secondary_angle=_parse_env_int(
            "EMBEDDED_VISION_SERVO_SORT_SECONDARY_ANGLE",
            DEFAULT_BOARD_SERVO_SORT_SECONDARY_ANGLE,
        ),
        conveyor_backend=conveyor_backend,
        conveyor_chip=_parse_env_int("EMBEDDED_VISION_CONVEYOR_CHIP", 0),
        conveyor_channel=_parse_env_int("EMBEDDED_VISION_CONVEYOR_CHANNEL", 1),
        conveyor_pwm_gpio=_parse_env_optional_int("EMBEDDED_VISION_CONVEYOR_PWM_GPIO"),
        conveyor_enable_gpio=_parse_env_optional_int("EMBEDDED_VISION_CONVEYOR_ENABLE_GPIO"),
        gpio_backend=os.environ.get("EMBEDDED_VISION_GPIO_BACKEND", "sysfs"),
        default_conveyor_speed=_parse_env_int("EMBEDDED_VISION_CONVEYOR_SPEED", DEFAULT_BOARD_CONVEYOR_SPEED),
        vibration_backend=os.environ.get("EMBEDDED_VISION_VIBRATION_BACKEND", DEFAULT_BOARD_VIBRATION_BACKEND),
        vibration_i2c_bus=_parse_env_int("EMBEDDED_VISION_MPU6050_I2C_BUS", DEFAULT_BOARD_MPU6050_I2C_BUS),
        vibration_i2c_address=_parse_env_int(
            "EMBEDDED_VISION_MPU6050_I2C_ADDRESS",
            DEFAULT_BOARD_MPU6050_I2C_ADDRESS,
        ),
        vibration_yellow_threshold=float(
            os.environ.get(
                "EMBEDDED_VISION_MPU6050_YELLOW_THRESHOLD",
                str(DEFAULT_BOARD_MPU6050_YELLOW_THRESHOLD),
            )
        ),
        vibration_red_threshold=float(
            os.environ.get(
                "EMBEDDED_VISION_MPU6050_RED_THRESHOLD",
                str(DEFAULT_BOARD_MPU6050_RED_THRESHOLD),
            )
        ),
        control_uart_port=os.environ.get("EMBEDDED_VISION_CONTROL_UART_PORT", DEFAULT_BOARD_CONTROL_UART_PORT),
        control_uart_baudrate=_parse_env_int("EMBEDDED_VISION_CONTROL_UART_BAUDRATE", DEFAULT_BOARD_CONTROL_UART_BAUDRATE),
        control_uart_timeout=float(
            os.environ.get("EMBEDDED_VISION_CONTROL_UART_TIMEOUT", str(DEFAULT_BOARD_CONTROL_UART_TIMEOUT))
        ),
        conveyor_speed_mode=os.environ.get("EMBEDDED_VISION_CONVEYOR_SPEED_MODE", DEFAULT_BOARD_CONVEYOR_SPEED_MODE),
        conveyor_step_max_hz=_parse_env_int(
            "EMBEDDED_VISION_CONVEYOR_STEP_MAX_HZ",
            DEFAULT_BOARD_CONVEYOR_STEP_MAX_HZ,
        ),
        sort_prepare_pause=float(
            os.environ.get(
                "EMBEDDED_VISION_SORT_PREPARE_PAUSE",
                str(DEFAULT_BOARD_SORT_PREPARE_PAUSE_SECONDS),
            )
        ),
        sort_servo_settle_time=float(
            os.environ.get(
                "EMBEDDED_VISION_SORT_SERVO_SETTLE_TIME",
                str(DEFAULT_BOARD_SORT_SERVO_SETTLE_SECONDS),
            )
        ),
        sort_servo_oscillation_interval=float(
            os.environ.get(
                "EMBEDDED_VISION_SORT_SERVO_OSCILLATION_INTERVAL",
                str(DEFAULT_BOARD_SORT_SERVO_OSCILLATION_INTERVAL),
            )
        ),
        sort_conveyor_advance_time=float(
            os.environ.get(
                "EMBEDDED_VISION_SORT_CONVEYOR_ADVANCE_TIME",
                str(DEFAULT_BOARD_SORT_CONVEYOR_ADVANCE_SECONDS),
            )
        ),
    )
    if existing_controller is not None and existing_controller is not sorting_system.device_controller:
        existing_controller.close()


def _create_nfc_sample_service(sorting_system: SortingSystem) -> NFCSampleService:
    service = NFCSampleService(
        reader=sorting_system.nfc_reader,
        poll_interval=float(
            os.environ.get(
                "EMBEDDED_VISION_NFC_POLL_INTERVAL",
                str(DEFAULT_BOARD_NFC_POLL_INTERVAL),
            )
        ),
        enabled=_parse_env_bool("EMBEDDED_VISION_NFC_POLL", DEFAULT_BOARD_NFC_POLL_ENABLED),
        poll_mock=_parse_env_bool("EMBEDDED_VISION_NFC_POLL_MOCK", False),
    )
    service.start()
    return service


def _sync_state_from_disk(sorting_system: SortingSystem) -> None:
    state_path = getattr(sorting_system, "state_path", None)
    if not state_path:
        return

    source = Path(state_path)
    try:
        stat = source.stat()
    except FileNotFoundError:
        return

    mtime_ns = stat.st_mtime_ns
    if getattr(sorting_system, "_web_state_mtime_ns", None) == mtime_ns:
        return

    try:
        sorting_system.order_manager = OrderManager.load_from_file(source)
        sorting_system._web_state_mtime_ns = mtime_ns
    except Exception:
        logger.exception("Failed to sync state file for dashboard: %s", source)


def _build_nfc_runtime_payload(sorting_system: SortingSystem) -> Dict[str, Any]:
    cached_runtime = getattr(sorting_system, "_web_nfc_runtime", None)
    if isinstance(cached_runtime, dict):
        return {
            "reader_class": type(sorting_system.nfc_reader).__name__,
            **cached_runtime,
        }

    backend = os.environ.get("EMBEDDED_VISION_NFC_BACKEND")
    return {
        "reader_class": type(sorting_system.nfc_reader).__name__,
        "configured_backend": backend,
        "i2c_bus": int(os.environ["EMBEDDED_VISION_NFC_I2C_BUS"])
        if os.environ.get("EMBEDDED_VISION_NFC_I2C_BUS")
        else None,
        "i2c_address": os.environ.get("EMBEDDED_VISION_NFC_I2C_ADDRESS"),
        "scan_timeout": float(os.environ["EMBEDDED_VISION_NFC_SCAN_TIMEOUT"])
        if os.environ.get("EMBEDDED_VISION_NFC_SCAN_TIMEOUT")
        else None,
        "passive_activation_retries": os.environ.get("EMBEDDED_VISION_NFC_PASSIVE_ACTIVATION_RETRIES"),
        "fallback_to_uid": _parse_env_bool(
            "EMBEDDED_VISION_NFC_FALLBACK_TO_UID",
            DEFAULT_BOARD_NFC_FALLBACK_TO_UID,
        ),
        "poll_enabled": _parse_env_bool("EMBEDDED_VISION_NFC_POLL", DEFAULT_BOARD_NFC_POLL_ENABLED),
        "poll_interval": float(
            os.environ.get(
                "EMBEDDED_VISION_NFC_POLL_INTERVAL",
                str(DEFAULT_BOARD_NFC_POLL_INTERVAL),
            )
        ),
    }


def _build_order_requirement_payload(sorting_system: SortingSystem) -> Dict[str, Any]:
    requirement = sorting_system.get_order_requirement()
    return {
        "enabled": bool(requirement.get("enabled", False)),
        "queue_enabled": bool(requirement.get("queue_enabled", False)),
        "raw_text": requirement.get("raw_text") or "",
        "spec": dict(requirement.get("spec")) if isinstance(requirement.get("spec"), dict) else None,
        "updated_at": requirement.get("updated_at"),
        "entry_id": requirement.get("entry_id"),
        "pending_count": int(requirement.get("pending_count", 0)),
        "history_count": int(requirement.get("history_count", 0)),
        "exhausted": bool(requirement.get("exhausted", False)),
    }


def _build_order_queue_payload(sorting_system: SortingSystem) -> Dict[str, Any]:
    queue_state = sorting_system.get_order_queue_state()
    return {
        "enabled": bool(queue_state.get("enabled", False)),
        "updated_at": queue_state.get("updated_at"),
        "pending_count": int(queue_state.get("pending_count", 0)),
        "history_count": int(queue_state.get("history_count", 0)),
        "exhausted": bool(queue_state.get("exhausted", False)),
        "active": dict(queue_state.get("active")) if isinstance(queue_state.get("active"), dict) else None,
        "entries": [
            dict(entry)
            for entry in queue_state.get("entries", [])
            if isinstance(entry, dict)
        ],
        "history": [
            dict(entry)
            for entry in queue_state.get("history", [])
            if isinstance(entry, dict)
        ],
    }


def _uses_uid_fallback(payload: Optional[Dict[str, Any]]) -> bool:
    return is_uid_fallback_payload(payload)


def _has_readable_nfc_text(payload: Optional[Dict[str, Any]]) -> bool:
    return has_readable_text_payload(payload)


def _describe_nfc_sample(payload: Optional[Dict[str, Any]]) -> str:
    if not isinstance(payload, dict) or not payload:
        return "暂无 NFC 结果"
    if _has_readable_nfc_text(payload) and payload.get("material_id"):
        return "NFC 标签文本读取成功"
    if _has_readable_nfc_text(payload):
        return "已读取标签文本，但未解析出物料 ID"
    if _uses_uid_fallback(payload):
        return "检测到标签 UID，但未读到标签文本"
    if payload.get("error"):
        return str(payload["error"])
    if payload.get("success"):
        return "已检测到标签"
    return "NFC 采样未成功"


def _get_recent_history(sorting_system: SortingSystem, limit: int = 8) -> list[Dict[str, Any]]:
    history = sorting_system.list_history()
    return list(reversed(history[-limit:]))


def _resolve_latest_capture_path(sorting_system: SortingSystem) -> Optional[Path]:
    for record in reversed(sorting_system.list_history()):
        capture_path = record.get("capture_path")
        if not capture_path:
            continue

        candidate = Path(capture_path)
        if candidate.is_file():
            return candidate
    return None


def _build_camera_preview_payload(preview) -> Dict[str, Any]:
    if preview is None:
        return {
            "available": False,
            "running": False,
            "ready": False,
            "snapshot_url": None,
            "status": None,
            "live_vision_result": None,
        }

    status = preview.get_status()
    ready = bool(status.get("ready"))
    running = bool(status.get("running"))
    processing = bool(status.get("core_running")) or bool(status.get("classification_running"))
    return {
        "available": True,
        "running": running,
        "processing": processing,
        "ready": ready,
        "snapshot_url": "/api/camera/snapshot" if running else None,
        "status": status,
        "live_vision_result": status.get("live_vision_result"),
    }


def _build_dashboard_payload(
    sorting_system: SortingSystem,
    preview=None,
    nfc_sample_service=None,
    runtime_controller: Optional[WebRuntimeController] = None,
) -> Dict[str, Any]:
    system_status = sorting_system.get_system_status()
    device_status = system_status.get("device") or sorting_system.get_device_status()
    history = sorting_system.list_history()
    latest_history = history[-1] if history else None
    last_processing_result = system_status.get("last_processing_result") or {}
    latest_decision = last_processing_result.get("decision") or (
        {
            "action": latest_history.get("action"),
            "route": latest_history.get("route"),
            "order_status": latest_history.get("final_status"),
            "reason": latest_history.get("reason"),
            "reasons": latest_history.get("anomaly_reasons", []),
            "sortable": latest_history.get("route") == "side_bin",
            "requires_manual_review": latest_history.get("final_status") == "待人工处理",
        }
        if latest_history
        else None
    )
    latest_comparison = (
        (latest_decision or {}).get("comparison")
        or (latest_history or {}).get("comparison_snapshot")
    )
    latest_vision = (
        last_processing_result.get("vision_result")
        or (latest_history or {}).get("vision_snapshot")
    )
    buffered_nfc = _get_buffered_nfc_payload(sorting_system)
    latest_health = sorting_system.read_device_health_snapshot()
    device_status = sorting_system.get_device_status()
    latest_capture_path = _resolve_latest_capture_path(sorting_system)
    camera_preview = _build_camera_preview_payload(preview)
    nfc_runtime = _build_nfc_runtime_payload(sorting_system)
    order_requirement = _build_order_requirement_payload(sorting_system)
    order_queue = _build_order_queue_payload(sorting_system)
    runtime_status = (
        runtime_controller.get_status()
        if runtime_controller is not None
        else {
            "running": False,
            "stop_requested": sorting_system.pending_stop,
            "started_at": None,
            "finished_at": None,
            "camera_source": None,
            "last_error": None,
            "last_result": None,
        }
    )
    nfc_sample = (
        nfc_sample_service.get_status()
        if nfc_sample_service is not None
        else {
            "enabled": False,
            "running": False,
            "polling": False,
            "backend": type(sorting_system.nfc_reader).__name__,
            "sample": latest_nfc,
            "sampled_at": None,
            "source": "history",
        }
    )
    latched_nfc = nfc_sample.get("latched_sample")
    current_nfc_sample = nfc_sample.get("sample")
    effective_service_nfc = None
    if isinstance(current_nfc_sample, dict) and _has_readable_nfc_text(current_nfc_sample):
        effective_service_nfc = dict(current_nfc_sample)
    elif isinstance(latched_nfc, dict) and _has_readable_nfc_text(latched_nfc):
        effective_service_nfc = dict(latched_nfc)
        nfc_sample = {
            **nfc_sample,
            "sample": effective_service_nfc,
            "sampled_at": nfc_sample.get("latched_sampled_at") or nfc_sample.get("sampled_at"),
            "source": "latched_readable",
        }
    latest_nfc = (
        buffered_nfc
        or effective_service_nfc
        or (latest_history or {}).get("nfc_snapshot")
    )
    if not nfc_sample.get("sample") and latest_nfc:
        nfc_sample = {
            **nfc_sample,
            "sample": latest_nfc,
            "sampled_at": nfc_sample.get("sampled_at") or (latest_history or {}).get("checked_at"),
            "source": "buffered_reader" if buffered_nfc else "latest_history",
        }
    if camera_preview["running"]:
        stage_mode = "live"
        stage_url = camera_preview["snapshot_url"]
    elif latest_capture_path:
        stage_mode = "capture"
        stage_url = "/api/capture/latest"
    else:
        stage_mode = None
        stage_url = None

    return {
        "generated_at": datetime.now().isoformat(),
        "system": system_status,
        "device": device_status,
        "runtime": runtime_status,
        "camera_preview": camera_preview,
        "nfc_runtime": nfc_runtime,
        "order_requirement": order_requirement,
        "order_queue": order_queue,
        "nfc_sample": nfc_sample,
        "latest": {
            "history": latest_history,
            "order": None,
            "nfc": latest_nfc,
            "vision": latest_vision,
            "comparison": latest_comparison,
            "decision": latest_decision,
            "health": latest_health,
            "capture_path": str(latest_capture_path) if latest_capture_path else None,
            "capture_url": "/api/capture/latest" if latest_capture_path else None,
            "stage_mode": stage_mode,
            "stage_url": stage_url,
        },
        "history": _get_recent_history(sorting_system),
        "debug": {
            "state_path": str(sorting_system.state_path),
            "confidence_threshold": sorting_system.confidence_threshold,
            "buffered_nfc_payload": _get_buffered_nfc_payload(sorting_system),
            "last_processing_result": last_processing_result or None,
            "runtime": runtime_status,
            "camera_preview": camera_preview,
            "nfc_runtime": nfc_runtime,
            "order_requirement": order_requirement,
            "order_queue": order_queue,
            "nfc_sample": nfc_sample,
        },
    }


def create_app(
    system: Optional[SortingSystem] = None,
    state_path: Optional[Path] = None,
    preview=None,
) -> Flask:
    """创建 Flask 应用。"""
    app = Flask(__name__)
    resolved_state_path = state_path or _default_state_path()
    owns_system = system is None
    sorting_system = system or SortingSystem(
        mode=SystemMode.CONTINUOUS,
        state_path=str(resolved_state_path),
    )
    _maybe_configure_device_controller_from_env(
        sorting_system,
        use_board_defaults=owns_system,
    )
    _maybe_configure_nfc_reader_from_env(
        sorting_system,
        use_board_defaults=owns_system,
    )
    if preview is False:
        camera_preview = None
    else:
        camera_preview = preview if preview is not None else _create_camera_preview_from_env()
    nfc_sample_service = _create_nfc_sample_service(sorting_system)
    runtime_controller = WebRuntimeController(
        sorting_system=sorting_system,
        preview=camera_preview,
        nfc_sample_service=nfc_sample_service,
    )
    app.extensions["camera_preview"] = camera_preview
    app.extensions["nfc_sample_service"] = nfc_sample_service
    app.extensions["runtime_controller"] = runtime_controller
    if camera_preview is not None:
        atexit.register(camera_preview.close)
    atexit.register(nfc_sample_service.stop)
    atexit.register(sorting_system.device_controller.close)
    atexit.register(runtime_controller.close)

    def persist_state():
        sorting_system.save_state()

    @app.get("/")
    def dashboard():
        return render_template("dashboard.html", page="monitor")

    @app.get("/debug")
    def debug_dashboard():
        return render_template("dashboard.html", page="debug")

    @app.get("/api/status")
    def get_status():
        _sync_state_from_disk(sorting_system)
        return jsonify(
            {
                **sorting_system.get_system_status(),
                "runtime": runtime_controller.get_status(),
            }
        )

    @app.get("/api/dashboard")
    def get_dashboard():
        _sync_state_from_disk(sorting_system)
        return jsonify(
            _build_dashboard_payload(
                sorting_system,
                preview=camera_preview,
                nfc_sample_service=nfc_sample_service,
                runtime_controller=runtime_controller,
            )
        )

    @app.get("/api/nfc/status")
    def get_nfc_status():
        return jsonify(nfc_sample_service.get_status())

    @app.post("/api/nfc/sample")
    def sample_nfc_once():
        if runtime_controller.is_running():
            return jsonify(
                {
                    "success": False,
                    "message": "完整主流程运行中，手动 NFC 采样已暂停",
                    "status": nfc_sample_service.get_status(),
                }
            ), 409
        try:
            payload = nfc_sample_service.sample_once()
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500
        return jsonify(
            {
                "success": _has_readable_nfc_text(payload),
                "message": _describe_nfc_sample(payload),
                "sample": payload,
                "status": nfc_sample_service.get_status(),
            }
        )

    @app.get("/api/camera/status")
    def get_camera_status():
        if camera_preview is None:
            return jsonify(
                {
                    "available": False,
                    "running": False,
                    "ready": False,
                    "error": "camera preview is disabled",
                }
            ), 404
        return jsonify(camera_preview.get_status())

    @app.post("/api/camera/control")
    def control_camera_preview():
        if camera_preview is None:
            return jsonify({"success": False, "error": "camera preview is unavailable"}), 404

        payload = request.get_json(force=True, silent=False)
        enabled = bool(payload.get("enabled"))
        if enabled:
            try:
                camera_preview.set_preview_enabled(True)
            except Exception as exc:
                return jsonify({"success": False, "error": str(exc)}), 500
        else:
            camera_preview.set_preview_enabled(False)

        return jsonify(
            {
                "success": True,
                "camera_preview": _build_camera_preview_payload(camera_preview),
            }
        )

    @app.get("/api/camera/snapshot")
    def get_camera_snapshot():
        if camera_preview is None:
            return Response("camera preview is disabled", status=404)

        jpeg, sequence = camera_preview.get_snapshot()
        if jpeg is None:
            status = camera_preview.get_status()
            error_text = status.get("last_error") or "camera frame is not ready"
            return Response(error_text, status=503)

        response = Response(jpeg, mimetype="image/jpeg")
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["X-Frame-Sequence"] = str(sequence)
        return response

    @app.get("/api/capture/latest")
    def get_latest_capture():
        _sync_state_from_disk(sorting_system)
        capture_path = _resolve_latest_capture_path(sorting_system)
        if capture_path is None:
            return jsonify({"success": False, "error": "No capture available"}), 404

        response = send_file(capture_path, mimetype="image/jpeg", max_age=0)
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        return response

    @app.get("/api/device")
    def get_device():
        return jsonify(sorting_system.get_device_status())

    @app.get("/api/history")
    def list_history():
        _sync_state_from_disk(sorting_system)
        return jsonify({"history": sorting_system.list_history()})

    @app.post("/api/order-requirement")
    def set_order_requirement():
        payload = request.get_json(force=True, silent=False) or {}
        enabled = bool(payload.get("enabled"))
        incoming_orders = payload.get("orders")
        if isinstance(incoming_orders, list):
            raw_rows = incoming_orders
        else:
            raw_rows = [{"text": payload.get("text") or payload.get("raw_text") or ""}]

        parsed_requirements = []
        for index, item in enumerate(raw_rows, start=1):
            if isinstance(item, str):
                raw_text = item.strip()
            elif isinstance(item, dict):
                raw_text = (item.get("text") or item.get("raw_text") or "").strip()
            else:
                raw_text = ""
            if not raw_text:
                continue

            spec = sorting_system.consistency_engine.parse_reference_text(raw_text)
            if spec is None:
                return jsonify(
                    {
                        "success": False,
                        "error": f"第 {index} 行订单文本无法解析，请输入例如 黄色正方形 或 JSON",
                    }
                ), 400
            parsed_requirements.append(
                {
                    "raw_text": raw_text,
                    "spec": spec,
                }
            )

        if enabled and not parsed_requirements:
            return jsonify({"success": False, "error": "启用订单校验时至少需要填写一行订单文本"}), 400

        order_queue = sorting_system.set_order_requirements(
            enabled=enabled,
            requirements=parsed_requirements,
        )
        return jsonify(
            {
                "success": True,
                "order_requirement": sorting_system.get_order_requirement(),
                "order_queue": order_queue,
            }
        )

    @app.post("/api/control/start")
    def start_system():
        started = runtime_controller.start()
        persist_state()
        if not started:
            message = (
                "主流程停止中，请稍候再试"
                if sorting_system.pending_stop
                else "主流程已在运行"
            )
            return jsonify(
                {
                    "success": False,
                    "error": message,
                    "runtime": runtime_controller.get_status(),
                    "status": sorting_system.get_system_status(),
                }
            ), 409
        return jsonify(
            {
                "success": True,
                "runtime": runtime_controller.get_status(),
                "status": sorting_system.get_system_status(),
            }
        )

    @app.post("/api/control/stop")
    def stop_system():
        runtime_status = runtime_controller.stop()
        return jsonify(
            {
                "success": True,
                "runtime": runtime_status,
                "status": sorting_system.get_system_status(),
            }
        )

    @app.post("/api/control/reset")
    def reset_system():
        sorting_system.reset_alarm()
        persist_state()
        return jsonify({"success": True, "status": sorting_system.get_system_status()})

    @app.post("/api/control/mode")
    def switch_mode():
        payload = request.get_json(force=True, silent=False)
        mode = payload.get("mode", "")
        if mode == SystemMode.SINGLE_PIECE.value:
            sorting_system.mode = SystemMode.SINGLE_PIECE
        elif mode == SystemMode.CONTINUOUS.value:
            sorting_system.mode = SystemMode.CONTINUOUS
        else:
            return jsonify({"success": False, "error": f"Unsupported mode: {mode}"}), 400

        return jsonify({"success": True, "status": sorting_system.get_system_status()})

    @app.post("/api/mock/nfc")
    def mock_nfc():
        """
        联调辅助接口。
        板端接入真实 NFC 后可以删掉，或仅在 debug 模式下启用。
        """
        payload = request.get_json(force=True, silent=False)
        if "success" not in payload:
            payload["success"] = bool(payload.get("material_id") or payload.get("text"))
        if hasattr(sorting_system.nfc_reader, "set_next_result"):
            sorting_system.nfc_reader.set_next_result(payload)
        else:
            sorting_system.nfc_reader.last_read = payload
        nfc_sample_service.publish_result(payload, source="buffered")
        return jsonify({"success": True, "payload": payload})

    @app.post("/api/mock/sensors")
    def mock_sensors():
        payload = request.get_json(force=True, silent=False)
        sorting_system.device_controller.inject_sensor_values(
            vibration=payload.get("vibration"),
            current=payload.get("current"),
        )
        health = sorting_system.monitor_device_health()
        persist_state()
        return jsonify(
            {
                "success": True,
                "health": health,
                "device": sorting_system.get_device_status(),
            }
        )

    @app.errorhandler(Exception)
    def handle_error(error):
        logger.exception("Web API error: %s", error)
        return jsonify({"success": False, "error": str(error)}), 500

    return app


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    app = create_app()
    host = os.environ.get("EMBEDDED_VISION_HOST", "0.0.0.0")
    port = int(os.environ.get("EMBEDDED_VISION_PORT", "8080"))
    app.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    main()
