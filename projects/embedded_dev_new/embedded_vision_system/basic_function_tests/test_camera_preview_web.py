#!/usr/bin/env python3
"""
基础功能验证：摄像头网页预览

适用于板机没有显示器的场景：
- 板机端后台始终只保留最新 JPEG
- 浏览器串行拉取 snapshot，避免 MJPEG 长连接积压旧帧
"""

import argparse
import logging
from typing import Optional

from flask import Flask, Response, jsonify

from embedded_vision_system.camera.camera_manager import (
    CameraManager,
    LatestFrameReader,
)
from embedded_vision_system.camera.low_latency_preview import LatestJPEGProcessor


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    force=True,
)
logger = logging.getLogger("camera_preview_web_test")
logging.getLogger("werkzeug").setLevel(logging.WARNING)


HTML_PAGE = """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>Camera Preview</title>
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
    <h1>Camera Preview</h1>
    <p>页面只拉取板机最新帧，不缓冲历史画面。</p>
    <img id="preview" alt="camera preview">
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
    parser = argparse.ArgumentParser(description="摄像头网页预览测试")
    parser.add_argument("--camera", default="/dev/video52", help="摄像头设备路径或索引")
    parser.add_argument("--camera-fps", type=int, default=30, help="摄像头采集目标帧率")
    parser.add_argument("--fps", type=int, default=15, help="网页图像生成目标帧率")
    parser.add_argument("--width", type=int, default=640, help="采集和网页图像宽度")
    parser.add_argument("--height", type=int, default=480, help="采集和网页图像高度")
    parser.add_argument(
        "--camera-format",
        choices=("YUYV", "MJPG", "NV12"),
        default="YUYV",
        help="V4L2 采集格式",
    )
    parser.add_argument("--no-gstreamer", action="store_true", help="强制使用 V4L2 回退路径")
    parser.add_argument("--host", default="0.0.0.0", help="Flask 绑定地址")
    parser.add_argument("--port", type=int, default=8081, help="Flask 监听端口")
    parser.add_argument("--jpeg-quality", type=int, default=60, help="JPEG 编码质量")
    parser.add_argument("--opencv-threads", type=int, default=2, help="OpenCV 工作线程数")
    return parser


class CameraWebPreview:
    """板机端网页预览服务。"""

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
        self.opencv_threads = opencv_threads
        self.camera: Optional[CameraManager] = None
        self.reader: Optional[LatestFrameReader] = None
        self.jpeg_processor: Optional[LatestJPEGProcessor] = None

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

    def get_snapshot(self):
        if self.jpeg_processor is None:
            return None, 0
        return self.jpeg_processor.get_latest_jpeg(timeout=0.8)

    def get_status(self) -> dict:
        if self.jpeg_processor is None:
            return {"ready": False, "last_error": "preview is not started"}
        return self.jpeg_processor.get_status()


def create_app(preview: CameraWebPreview) -> Flask:
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
    preview = CameraWebPreview(
        camera_id=args.camera,
        camera_fps=args.camera_fps,
        fps=args.fps,
        width=args.width,
        height=args.height,
        camera_format=args.camera_format,
        prefer_gstreamer=not args.no_gstreamer,
        jpeg_quality=args.jpeg_quality,
        opencv_threads=args.opencv_threads,
    )

    preview.open()
    app = create_app(preview)

    logger.info("Web preview ready")
    logger.info("Board local URL: http://127.0.0.1:%s", args.port)
    logger.info("LAN URL: http://%s:%s", args.host if args.host != "0.0.0.0" else "BOARD_IP", args.port)

    try:
        app.run(host=args.host, port=args.port, debug=False, threaded=True)
    finally:
        preview.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
