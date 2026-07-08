#!/usr/bin/env python3
"""
基础功能验证 1：摄像头显示回传

功能：
- 打开指定摄像头
- 实时显示画面
- 终端输出帧率与分辨率
- 支持保存截图
"""

import argparse
import logging
import time
from pathlib import Path

import cv2

from embedded_vision_system.camera.camera_manager import CameraManager
from embedded_vision_system.storage import get_subdir


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    force=True,
)
logger = logging.getLogger("camera_preview_test")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="摄像头显示回传测试")
    parser.add_argument("--camera", default="/dev/video0", help="摄像头设备路径或索引")
    parser.add_argument("--fps", type=int, default=30, help="目标帧率")
    parser.add_argument(
        "--save-dir",
        default=str(get_subdir("test_outputs", "camera_preview")),
        help="截图保存目录",
    )
    parser.add_argument("--max-frames", type=int, default=0, help="最大处理帧数，0 表示无限")
    parser.add_argument("--headless", action="store_true", help="无窗口模式，仅打印日志并可保存截图")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    save_dir = Path(args.save_dir)

    frame_counter = 0
    window_name = "Camera Preview Test"
    start_time = time.time()

    with CameraManager(camera_id=args.camera, fps=args.fps) as camera:
        logger.info("Camera properties: %s", camera.get_properties())
        logger.info("按 q 退出，按 s 保存截图")

        while True:
            ret, frame = camera.read_frame()
            if not ret or frame is None:
                logger.error("Failed to read frame from camera")
                return 1

            frame_counter += 1
            elapsed = time.time() - start_time
            current_fps = frame_counter / elapsed if elapsed > 0 else 0.0

            overlay = frame.copy()
            cv2.putText(
                overlay,
                f"Frames: {frame_counter}  FPS: {current_fps:.2f}",
                (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 255, 0),
                2,
            )

            if not args.headless:
                cv2.imshow(window_name, overlay)
                key = cv2.waitKey(1) & 0xFF
                if key == ord("q"):
                    break
                if key == ord("s"):
                    save_dir.mkdir(parents=True, exist_ok=True)
                    output_path = save_dir / f"snapshot_{frame_counter:05d}.jpg"
                    cv2.imwrite(str(output_path), frame)
                    logger.info("Saved snapshot: %s", output_path)
            else:
                if frame_counter % 30 == 0:
                    logger.info("frame=%s fps=%.2f", frame_counter, current_fps)

            if args.max_frames > 0 and frame_counter >= args.max_frames:
                break

    cv2.destroyAllWindows()
    logger.info("Camera preview test finished. total_frames=%s", frame_counter)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
