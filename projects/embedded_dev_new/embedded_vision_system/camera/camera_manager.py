"""
摄像头管理模块
支持实时视频采集
"""

import logging
import subprocess
import sys
import threading
import time
from collections import deque
from typing import Deque, Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)


def _opencv_has_gstreamer() -> bool:
    try:
        return any(
            "GStreamer" in line and "YES" in line.upper()
            for line in cv2.getBuildInformation().splitlines()
        )
    except Exception:
        return False


def _decode_fourcc(value: float) -> str:
    integer_value = int(value)
    if integer_value <= 0:
        return ""
    return "".join(chr((integer_value >> (8 * index)) & 0xFF) for index in range(4))


class CameraManager:
    """
    摄像头管理器
    """
    
    def __init__(
        self,
        camera_id: str = "/dev/video0",
        fps: int = 30,
        width: Optional[int] = None,
        height: Optional[int] = None,
        pixel_format: Optional[str] = None,
        prefer_gstreamer: bool = True,
    ):
        """
        初始化摄像头
        
        Args:
            camera_id: 摄像头设备路径或索引
                      - 整数：/dev/videoN 索引 (例如 0 表示 /dev/video0)
                      - 字符串：设备路径 (例如 "/dev/video52")
            fps: 帧率
            width: 采集宽度，None 表示使用设备默认值
            height: 采集高度，None 表示使用设备默认值
            pixel_format: V4L2 像素格式，例如 YUYV、MJPG 或 NV12
            prefer_gstreamer: 优先使用可丢旧帧的 GStreamer appsink
        """
        self.camera_id = camera_id
        self.fps = fps
        self.requested_width = width
        self.requested_height = height
        self.pixel_format = pixel_format.upper() if pixel_format else None
        self.prefer_gstreamer = prefer_gstreamer
        self.cap = None
        self.frame_width = 0
        self.frame_height = 0
        self.frame_count = 0
        self.actual_fps = 0.0
        self.actual_pixel_format = ""
        self.backend = "uninitialized"
        self.gstreamer_pipeline: Optional[str] = None
        self._gstreamer_disabled = False
        
        self._initialize_camera()

    def _build_gstreamer_pipeline(self) -> Optional[str]:
        if not isinstance(self.camera_id, str) or not self.camera_id.startswith("/dev/video"):
            return None

        caps = []
        if self.requested_width:
            caps.append(f"width={int(self.requested_width)}")
        if self.requested_height:
            caps.append(f"height={int(self.requested_height)}")
        if self.fps > 0:
            caps.append(f"framerate={int(self.fps)}/1")

        gst_format = {
            "YUYV": "YUY2",
            "YUY2": "YUY2",
            "NV12": "NV12",
        }.get(self.pixel_format or "")
        if gst_format:
            caps.insert(0, f"format={gst_format}")

        if self.pixel_format in {"MJPG", "MJPEG"}:
            source_caps = "image/jpeg"
            decoder = "jpegdec ! "
        else:
            source_caps = "video/x-raw"
            decoder = ""

        caps_text = ",".join(caps)
        caps_filter = f"{source_caps},{caps_text}" if caps_text else source_caps
        return (
            f"v4l2src device={self.camera_id} ! "
            f"{caps_filter} ! "
            f"{decoder}videoconvert ! video/x-raw,format=BGR ! "
            "appsink drop=true max-buffers=1 sync=false"
        )

    def _open_gstreamer(self) -> bool:
        if self._gstreamer_disabled or not self.prefer_gstreamer:
            return False
        if not _opencv_has_gstreamer():
            logger.info("OpenCV was built without GStreamer; using V4L2 fallback")
            return False

        pipeline = self._build_gstreamer_pipeline()
        if pipeline is None:
            return False
        if not self._probe_gstreamer_pipeline(pipeline):
            logger.warning("GStreamer first-frame probe failed; using V4L2 fallback")
            return False

        capture_parameters = []
        open_timeout_property = getattr(cv2, "CAP_PROP_OPEN_TIMEOUT_MSEC", None)
        read_timeout_property = getattr(cv2, "CAP_PROP_READ_TIMEOUT_MSEC", None)
        if open_timeout_property is not None:
            capture_parameters.extend((open_timeout_property, 3000))
        if read_timeout_property is not None:
            capture_parameters.extend((read_timeout_property, 1000))

        try:
            cap = (
                cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER, capture_parameters)
                if capture_parameters
                else cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)
            )
        except Exception:
            logger.info("OpenCV does not accept GStreamer timeout parameters")
            cap = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)
        if not cap.isOpened():
            cap.release()
            logger.warning("Failed to open GStreamer camera pipeline; using V4L2 fallback")
            return False

        self.cap = cap
        self.backend = "gstreamer"
        self.gstreamer_pipeline = pipeline
        return True

    @staticmethod
    def _probe_gstreamer_pipeline(pipeline: str) -> bool:
        probe_code = (
            "import cv2, sys; "
            "cap = cv2.VideoCapture(sys.argv[1], cv2.CAP_GSTREAMER); "
            "ok, frame = cap.read() if cap.isOpened() else (False, None); "
            "cap.release(); "
            "raise SystemExit(0 if ok and frame is not None else 1)"
        )
        try:
            result = subprocess.run(
                [sys.executable, "-c", probe_code, pipeline],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=4.0,
                check=False,
            )
            return result.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False

    def _open_v4l2(self):
        camera_source = self.camera_id if isinstance(self.camera_id, str) else int(self.camera_id)
        self.gstreamer_pipeline = None
        if isinstance(camera_source, str) and hasattr(cv2, "CAP_V4L2"):
            self.cap = cv2.VideoCapture(camera_source, cv2.CAP_V4L2)
            self.backend = "v4l2"
        else:
            self.cap = cv2.VideoCapture(camera_source)
            self.backend = "opencv-default"

        if not self.cap.isOpened():
            raise RuntimeError(f"Failed to open camera: {self.camera_id}")

        format_configured = None
        if self.pixel_format:
            v4l2_format = "YUYV" if self.pixel_format == "YUY2" else self.pixel_format
            fourcc = cv2.VideoWriter_fourcc(*v4l2_format[:4])
            format_configured = self.cap.set(cv2.CAP_PROP_FOURCC, fourcc)
        width_configured = (
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, float(self.requested_width))
            if self.requested_width
            else None
        )
        height_configured = (
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, float(self.requested_height))
            if self.requested_height
            else None
        )
        fps_configured = self.cap.set(cv2.CAP_PROP_FPS, float(self.fps))
        buffer_configured = self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        logger.info(
            "V4L2 camera configuration: format=%s width=%s height=%s fps=%s buffer=%s",
            format_configured,
            width_configured,
            height_configured,
            fps_configured,
            buffer_configured,
        )
    
    def _initialize_camera(self):
        """初始化摄像头"""
        try:
            if not self._open_gstreamer():
                self._open_v4l2()
            
            # 获取摄像头属性
            self.frame_width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            self.frame_height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            self.actual_fps = float(self.cap.get(cv2.CAP_PROP_FPS))
            self.actual_pixel_format = _decode_fourcc(self.cap.get(cv2.CAP_PROP_FOURCC))
            
            logger.info(
                f"Camera initialized: {self.camera_id} "
                f"({self.frame_width}x{self.frame_height}, "
                f"requested_fps={self.fps}, actual_fps={self.actual_fps:.2f}, "
                f"pixel_format={self.actual_pixel_format or 'unknown'}, "
                f"backend={self.backend})"
            )
            if self.gstreamer_pipeline:
                logger.info("GStreamer pipeline: %s", self.gstreamer_pipeline)
        
        except Exception as e:
            logger.error(f"Failed to initialize camera: {e}")
            raise
    
    def read_frame(self) -> Tuple[bool, Optional[np.ndarray]]:
        """
        读取一帧
        
        Returns:
            (success, frame) - success 表示是否读取成功，frame 为 BGR 图像
        """
        if self.cap is None:
            logger.warning("Camera not initialized")
            return False, None
        
        try:
            ret, frame = self.cap.read()
            if ret:
                self.frame_count += 1
                return True, frame
            else:
                logger.warning("Failed to read frame from camera")
                return False, None
        
        except Exception as e:
            logger.error(f"Error reading frame: {e}")
            return False, None
    
    def get_properties(self) -> dict:
        """
        获取摄像头属性
        
        Returns:
            属性字典
        """
        if self.cap is None:
            return {}
        
        properties = {
            'frame_width': self.frame_width,
            'frame_height': self.frame_height,
            'fps': self.actual_fps,
            'requested_fps': self.fps,
            'requested_width': self.requested_width,
            'requested_height': self.requested_height,
            'requested_pixel_format': self.pixel_format,
            'pixel_format': self.actual_pixel_format,
            'backend': self.backend,
            'gstreamer_pipeline': self.gstreamer_pipeline,
            'frame_count': self.frame_count,
            'camera_id': self.camera_id,
        }
        
        # 尝试获取其他属性
        try:
            properties['brightness'] = self.cap.get(cv2.CAP_PROP_BRIGHTNESS)
            properties['contrast'] = self.cap.get(cv2.CAP_PROP_CONTRAST)
            properties['saturation'] = self.cap.get(cv2.CAP_PROP_SATURATION)
        except Exception as e:
            logger.debug(f"Could not read all properties: {e}")
        
        return properties
    
    def release(self):
        """释放摄像头资源"""
        if self.cap is not None:
            self.cap.release()
            self.cap = None
            logger.info(f"Camera released. Total frames: {self.frame_count}")

    def reopen(self):
        """释放并重新打开摄像头，用于从驱动短暂断帧中恢复。"""
        if self.backend == "gstreamer":
            logger.warning("GStreamer capture stalled; switching to V4L2 fallback")
            self._gstreamer_disabled = True
        self.release()
        self._initialize_camera()
    
    def __enter__(self):
        """上下文管理器入口"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.release()


class LatestFrameReader:
    """持续采集摄像头画面，且只保留最新一帧。"""

    def __init__(self, camera: CameraManager, reconnect_after_failures: int = 10):
        self.camera = camera
        self.reconnect_after_failures = max(1, reconnect_after_failures)
        self._condition = threading.Condition()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._latest_frame: Optional[np.ndarray] = None
        self._sequence = 0
        self._capture_time = 0.0
        self._capture_fps = 0.0
        self._capture_timestamps: Deque[float] = deque()
        self._failed_reads = 0
        self._consecutive_failures = 0
        self._reconnect_count = 0

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._capture_loop,
            name="camera-latest-frame",
            daemon=True,
        )
        self._thread.start()

    def _capture_loop(self):
        while not self._stop_event.is_set():
            success, frame = self.camera.read_frame()
            if not success or frame is None:
                with self._condition:
                    self._failed_reads += 1
                    self._consecutive_failures += 1
                    should_reconnect = (
                        self._consecutive_failures >= self.reconnect_after_failures
                    )

                if should_reconnect and not self._stop_event.is_set():
                    logger.warning(
                        "Camera failed %s consecutive reads; reopening %s",
                        self._consecutive_failures,
                        self.camera.camera_id,
                    )
                    try:
                        self.camera.reopen()
                        with self._condition:
                            self._reconnect_count += 1
                            self._consecutive_failures = 0
                    except Exception:
                        logger.exception("Failed to reopen camera")
                    if self._stop_event.wait(0.5):
                        break

                if not self._stop_event.is_set():
                    time.sleep(0.02)
                continue

            with self._condition:
                now = time.monotonic()
                self._latest_frame = frame
                self._sequence += 1
                self._capture_time = now
                self._consecutive_failures = 0
                self._capture_timestamps.append(now)
                cutoff = now - 1.0
                while (
                    len(self._capture_timestamps) > 1
                    and self._capture_timestamps[0] < cutoff
                ):
                    self._capture_timestamps.popleft()
                if len(self._capture_timestamps) > 1:
                    elapsed = self._capture_timestamps[-1] - self._capture_timestamps[0]
                    self._capture_fps = (
                        (len(self._capture_timestamps) - 1) / elapsed
                        if elapsed > 0
                        else 0.0
                    )
                self._condition.notify_all()

        with self._condition:
            self._condition.notify_all()

    def read_latest(
        self,
        after_sequence: int = -1,
        timeout: float = 1.0,
    ) -> Tuple[bool, Optional[np.ndarray], int, float]:
        """等待新帧并返回只读引用，避免复制完整采集帧。"""
        deadline = time.monotonic() + max(0.0, timeout)
        with self._condition:
            while (
                (self._latest_frame is None or self._sequence <= after_sequence)
                and not self._stop_event.is_set()
            ):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(remaining)

            if self._latest_frame is None or self._sequence <= after_sequence:
                return False, None, self._sequence, self._capture_time

            return (
                True,
                self._latest_frame,
                self._sequence,
                self._capture_time,
            )

    def get_status(self) -> dict:
        with self._condition:
            capture_age_ms = (
                max(0.0, (time.monotonic() - self._capture_time) * 1000.0)
                if self._capture_time > 0
                else None
            )
            return {
                "capture_sequence": self._sequence,
                "capture_fps": self._capture_fps,
                "capture_age_ms": capture_age_ms,
                "backend": self.camera.backend,
                "frame_width": self.camera.frame_width,
                "frame_height": self.camera.frame_height,
                "device_fps": self.camera.actual_fps,
                "pixel_format": self.camera.actual_pixel_format,
                "failed_reads": self._failed_reads,
                "consecutive_failures": self._consecutive_failures,
                "reconnect_count": self._reconnect_count,
                "thread_alive": self._thread is not None and self._thread.is_alive(),
            }

    def stop(self):
        self._stop_event.set()
        with self._condition:
            self._condition.notify_all()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            if self._thread.is_alive():
                logger.warning("Camera capture thread did not stop within timeout")
            self._thread = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()


class FrameRateTracker:
    """计算最近时间窗口的实时帧率。"""

    def __init__(self, window_seconds: float = 1.0):
        self.window_seconds = max(0.2, window_seconds)
        self._timestamps: Deque[float] = deque()

    def tick(self, timestamp: Optional[float] = None) -> float:
        now = time.monotonic() if timestamp is None else timestamp
        self._timestamps.append(now)
        cutoff = now - self.window_seconds
        while len(self._timestamps) > 1 and self._timestamps[0] < cutoff:
            self._timestamps.popleft()

        if len(self._timestamps) < 2:
            return 0.0

        elapsed = self._timestamps[-1] - self._timestamps[0]
        return (len(self._timestamps) - 1) / elapsed if elapsed > 0 else 0.0


class FrameBuffer:
    """
    帧缓冲区
    用于摄像头采集和处理解耦
    """
    
    def __init__(self, max_size: int = 5):
        """
        初始化帧缓冲区
        
        Args:
            max_size: 缓冲区最大帧数
        """
        self.max_size = max_size
        self.buffer = []
        self.current_index = 0
    
    def push(self, frame: np.ndarray):
        """
        添加帧到缓冲区
        
        Args:
            frame: 输入帧
        """
        if len(self.buffer) < self.max_size:
            self.buffer.append(frame)
        else:
            self.buffer[self.current_index % self.max_size] = frame
        
        self.current_index += 1
    
    def get_latest(self) -> Optional[np.ndarray]:
        """获取最新的帧"""
        if len(self.buffer) == 0:
            return None
        return self.buffer[-1]
    
    def get_by_index(self, index: int) -> Optional[np.ndarray]:
        """根据索引获取帧"""
        if 0 <= index < len(self.buffer):
            return self.buffer[index]
        return None
    
    def clear(self):
        """清空缓冲区"""
        self.buffer.clear()
        self.current_index = 0
    
    def size(self) -> int:
        """获取缓冲区中的帧数"""
        return len(self.buffer)
