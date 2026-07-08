#!/usr/bin/env python3
"""
基础功能验证：颜色 + 形状识别网页预览

板机启动后，浏览器串行拉取最新 snapshot：
- 摄像头实时画面
- 颜色 + 形状识别框
- 当前帧 FPS 和识别数量
"""

import argparse
import logging
import time
from typing import Optional

import cv2
from flask import Flask, Response, jsonify

from embedded_vision_system.camera.camera_manager import (
    CameraManager,
    LatestFrameReader,
)
from embedded_vision_system.camera.low_latency_preview import LatestJPEGProcessor
from embedded_vision_system.detection.shape_color_classifier import (
    ShapeColorResultConverter,
    TraditionalShapeColorClassifier,
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    force=True,
)
logger = logging.getLogger("camera_shape_color_web_test")
logging.getLogger("werkzeug").setLevel(logging.WARNING)


HTML_PAGE = """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>Shape Color Preview</title>
  <style>
    body {
      margin: 0;
      padding: 24px;
      font-family: sans-serif;
      background: #101417;
      color: #f4f7fa;
    }
    .wrap {
      max-width: 1200px;
      margin: 0 auto;
    }
    h1 {
      margin-bottom: 8px;
    }
    p {
      opacity: 0.8;
    }
    img {
      width: 100%;
      max-width: 960px;
      border: 1px solid #2f3942;
      border-radius: 12px;
      background: #000;
      display: block;
    }
  </style>
</head>
<body>
  <div class="wrap">
    <h1>Shape + Color Preview</h1>
    <p>识别、JPEG 编码与网页请求已解耦，页面不会积压历史帧。</p>
    <img id="preview" alt="shape color preview">
  </div>
  <script>
    const preview = document.getElementById("preview");
    const refreshDelayMs = __REFRESH_DELAY_MS__;
    let refreshTimer = null;
    let loading = false;
    let activeController = null;
    let currentObjectUrl = null;
    const scheduleRefresh = (delayMs) => {
      clearTimeout(refreshTimer);
      refreshTimer = setTimeout(refresh, delayMs);
    };
    const refresh = async () => {
      if (document.hidden || loading) return;
      loading = true;
      activeController = new AbortController();
      const requestTimeout = setTimeout(() => activeController.abort(), 1000);
      try {
        const response = await fetch(`/snapshot?t=${Date.now()}`, {
          cache: "no-store",
          signal: activeController.signal,
        });
        if (!response.ok) throw new Error(`snapshot HTTP ${response.status}`);
        const imageBlob = await response.blob();
        const nextObjectUrl = URL.createObjectURL(imageBlob);
        const previousObjectUrl = currentObjectUrl;
        currentObjectUrl = nextObjectUrl;
        preview.src = nextObjectUrl;
        if (previousObjectUrl) URL.revokeObjectURL(previousObjectUrl);
      } catch (error) {
        if (error.name !== "AbortError") console.warn(error);
      } finally {
        clearTimeout(requestTimeout);
        activeController = null;
        loading = false;
        if (!document.hidden) scheduleRefresh(refreshDelayMs);
      }
    };
    document.addEventListener("visibilitychange", () => {
      clearTimeout(refreshTimer);
      if (document.hidden && activeController) activeController.abort();
      if (!document.hidden) refresh();
    });
    window.addEventListener("beforeunload", () => {
      if (activeController) activeController.abort();
      if (currentObjectUrl) URL.revokeObjectURL(currentObjectUrl);
    });
    refresh();
  </script>
</body>
</html>
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="颜色 + 形状识别网页预览测试")
    parser.add_argument("--camera", default="/dev/video52", help="摄像头设备路径或索引")
    parser.add_argument("--camera-fps", type=int, default=30, help="摄像头采集目标帧率")
    parser.add_argument("--fps", type=int, default=8, help="识别和网页图像生成帧率")
    parser.add_argument("--width", type=int, default=640, help="采集、识别和网页图像宽度")
    parser.add_argument("--height", type=int, default=480, help="采集、识别和网页图像高度")
    parser.add_argument(
        "--camera-format",
        choices=("YUYV", "MJPG", "NV12"),
        default="YUYV",
        help="V4L2 采集格式",
    )
    parser.add_argument("--no-gstreamer", action="store_true", help="强制使用 V4L2 回退路径")
    parser.add_argument("--host", default="0.0.0.0", help="Flask 绑定地址")
    parser.add_argument("--port", type=int, default=8082, help="Flask 监听端口")
    parser.add_argument("--jpeg-quality", type=int, default=60, help="JPEG 编码质量")
    parser.add_argument("--min-area", type=int, default=500, help="缩放后图像的最小轮廓面积")
    parser.add_argument("--max-contours", type=int, default=8, help="每种颜色最多处理的轮廓数")
    parser.add_argument("--opencv-threads", type=int, default=2, help="OpenCV 工作线程数")
    return parser


class ShapeColorWebPreview:
    """带识别叠加的板机网页预览服务。"""

    def __init__(
        self,
        camera_id: str,
        camera_fps: int,
        fps: int,
        width: int,
        height: int,
        camera_format: str,
        prefer_gstreamer: bool,
        jpeg_quality: int,
        min_area: int,
        max_contours: int,
        opencv_threads: int,
    ):
        self.camera_id = camera_id
        self.camera_fps = camera_fps
        self.fps = fps
        self.width = width
        self.height = height
        self.camera_format = camera_format
        self.prefer_gstreamer = prefer_gstreamer
        self.jpeg_quality = max(10, min(100, jpeg_quality))
        self.classifier = TraditionalShapeColorClassifier(
            min_contour_area=min_area,
            max_contours_per_color=max_contours,
        )
        self.opencv_threads = opencv_threads
        self.camera: Optional[CameraManager] = None
        self.reader: Optional[LatestFrameReader] = None
        self.jpeg_processor: Optional[LatestJPEGProcessor] = None
        self.last_log_time = 0.0

    def open(self):
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
        self.jpeg_processor = LatestJPEGProcessor(
            reader=self.reader,
            fps=self.fps,
            width=self.width,
            height=self.height,
            jpeg_quality=self.jpeg_quality,
            frame_processor=self._classify_frame,
            opencv_threads=self.opencv_threads,
        )
        self.jpeg_processor.start()
        logger.info("Camera properties: %s", self.camera.get_properties())

    def close(self):
        if self.jpeg_processor is not None:
            self.jpeg_processor.stop()
            self.jpeg_processor = None
        if self.reader is not None:
            self.reader.stop()
            self.reader = None
        if self.camera is not None:
            self.camera.release()
            self.camera = None

    def _classify_frame(self, frame):
        results = self.classifier.classify(frame)
        overlay = self.classifier.annotate_frame(frame, results)
        cv2.putText(
            overlay,
            f"Detections: {len(results)}",
            (10, 28),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (0, 255, 0),
            2,
        )

        if results:
            best = ShapeColorResultConverter.to_dict(results[0])
            now = time.monotonic()
            if now - self.last_log_time >= 1.0:
                logger.info("best_result=%s", best)
                self.last_log_time = now
        return overlay

    def get_snapshot(self):
        if self.jpeg_processor is None:
            return None, 0
        return self.jpeg_processor.get_latest_jpeg(timeout=0.8)

    def get_status(self) -> dict:
        if self.jpeg_processor is None:
            return {"ready": False, "last_error": "preview is not started"}
        return self.jpeg_processor.get_status()


def create_app(preview: ShapeColorWebPreview) -> Flask:
    app = Flask(__name__)

    @app.route("/")
    def index():
        refresh_delay_ms = max(20, int(1000 / max(1, preview.fps)))
        html = HTML_PAGE.replace("__REFRESH_DELAY_MS__", str(refresh_delay_ms))
        response = Response(html, mimetype="text/html")
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        return response

    @app.route("/snapshot")
    def snapshot():
        jpeg, sequence = preview.get_snapshot()
        if jpeg is None:
            return Response("camera frame is not ready", status=503)
        response = Response(jpeg, mimetype="image/jpeg")
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["X-Frame-Sequence"] = str(sequence)
        return response

    @app.route("/status")
    def status():
        return jsonify(preview.get_status())

    return app


def main() -> int:
    args = build_parser().parse_args()
    preview = ShapeColorWebPreview(
        camera_id=args.camera,
        camera_fps=args.camera_fps,
        fps=args.fps,
        width=args.width,
        height=args.height,
        camera_format=args.camera_format,
        prefer_gstreamer=not args.no_gstreamer,
        jpeg_quality=args.jpeg_quality,
        min_area=args.min_area,
        max_contours=args.max_contours,
        opencv_threads=args.opencv_threads,
    )

    preview.open()
    app = create_app(preview)

    logger.info("Web preview ready")
    logger.info("Board local URL: http://127.0.0.1:%s", args.port)
    logger.info(
        "LAN URL: http://%s:%s",
        args.host if args.host != "0.0.0.0" else "BOARD_IP",
        args.port,
    )

    try:
        app.run(host=args.host, port=args.port, debug=False, threaded=True)
    finally:
        preview.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
