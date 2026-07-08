#!/usr/bin/env python3
"""
基础功能验证：摄像头颜色 + 形状识别

适用于当前受控演示场景：
- 颜色：红 / 黄 / 蓝 / 绿 / 紫
- 形状：正方形 / 长方形 / 三角形 / 圆锥形
- 材质：木质件
"""

import argparse
import logging
import time
from pathlib import Path

import cv2

from embedded_vision_system.camera.camera_manager import CameraManager
from embedded_vision_system.detection.shape_color_classifier import (
    ShapeColorResultConverter,
    TraditionalShapeColorClassifier,
)
from embedded_vision_system.storage import get_subdir


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    force=True,
)
logger = logging.getLogger("camera_shape_color_test")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="摄像头颜色 + 形状识别测试")
    parser.add_argument("--camera", default="/dev/video52", help="摄像头设备路径或索引")
    parser.add_argument("--fps", type=int, default=30, help="目标帧率")
    parser.add_argument("--max-frames", type=int, default=0, help="最大处理帧数，0 表示无限")
    parser.add_argument("--min-area", type=int, default=2000, help="最小轮廓面积阈值")
    parser.add_argument("--headless", action="store_true", help="无窗口模式")
    parser.add_argument(
        "--save-dir",
        default=str(get_subdir("test_outputs", "camera_shape_color")),
        help="截图保存目录",
    )
    return parser


def draw_lines(frame, lines):
    for index, line in enumerate(lines):
        cv2.putText(
            frame,
            line,
            (10, 30 + index * 28),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 255, 255),
            2,
        )


def main() -> int:
    args = build_parser().parse_args()
    output_dir = Path(args.save_dir)
    classifier = TraditionalShapeColorClassifier(min_contour_area=args.min_area)

    frame_counter = 0
    start_time = time.time()
    last_log_time = 0.0

    with CameraManager(camera_id=args.camera, fps=args.fps) as camera:
        logger.info("按 q 退出，按 s 保存当前识别画面")

        while True:
            success, frame = camera.read_frame()
            if not success or frame is None:
                logger.warning("Failed to read frame from camera")
                time.sleep(0.05)
                continue

            frame_counter += 1
            elapsed = time.time() - start_time
            fps = frame_counter / elapsed if elapsed > 0 else 0.0

            results = classifier.classify(frame)
            annotated = classifier.annotate_frame(frame, results)

            lines = [f"FPS: {fps:.2f}", f"Detections: {len(results)}"]
            if results:
                best = results[0]
                best_dict = ShapeColorResultConverter.to_dict(best)
                lines.append(f"Best: {best_dict['label']} conf={best.confidence:.2f}")
                now = time.time()
                if now - last_log_time >= 1.0:
                    logger.info("best_result=%s", best_dict)
                    last_log_time = now
            else:
                lines.append("Best: none")

            draw_lines(annotated, lines)

            if not args.headless:
                cv2.imshow("Camera Shape Color Test", annotated)
                key = cv2.waitKey(1) & 0xFF
                if key == ord("q"):
                    break
                if key == ord("s"):
                    output_dir.mkdir(parents=True, exist_ok=True)
                    output_path = output_dir / f"shape_color_{frame_counter:05d}.jpg"
                    cv2.imwrite(str(output_path), annotated)
                    logger.info("Saved frame: %s", output_path)
            else:
                if frame_counter % 30 == 0:
                    logger.info("frame=%s results=%s fps=%.2f", frame_counter, len(results), fps)

            if args.max_frames > 0 and frame_counter >= args.max_frames:
                break

    cv2.destroyAllWindows()
    logger.info("Camera shape/color test finished. total_frames=%s", frame_counter)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
