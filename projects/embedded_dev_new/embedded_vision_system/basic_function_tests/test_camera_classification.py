#!/usr/bin/env python3
"""
基础功能验证 2：摄像头分类

功能：
- 摄像头取流
- 运行 RKNN + YOLO 检测
- 输出物料类型 + 颜色的结构化分类结果
"""

import argparse
import logging
import time
from pathlib import Path

import cv2

from embedded_vision_system.detection.vision_classifier import MaterialClassifier
from embedded_vision_system.detection.yolov8_postprocess import CLASSES
from embedded_vision_system.storage import get_subdir
from embedded_vision_system.utils.vision_pipeline import VisionPipeline


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    force=True,
)
logger = logging.getLogger("camera_classification_test")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="摄像头分类测试")
    parser.add_argument("--model", required=True, help="RKNN 模型路径")
    parser.add_argument("--camera", default="/dev/video0", help="摄像头设备路径或索引")
    parser.add_argument("--threads", type=int, default=4, help="推理线程数")
    parser.add_argument("--sync", action="store_true", help="关闭异步推理")
    parser.add_argument("--confidence", type=float, default=0.5, help="分类置信度阈值")
    parser.add_argument("--max-frames", type=int, default=0, help="最大处理帧数，0 表示无限")
    parser.add_argument("--headless", action="store_true", help="无窗口模式")
    parser.add_argument(
        "--save-dir",
        default=str(get_subdir("test_outputs", "camera_classification")),
        help="截图保存目录",
    )
    return parser


def draw_classification_lines(frame, lines):
    for index, line in enumerate(lines):
        cv2.putText(
            frame,
            line,
            (10, 30 + index * 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 255, 255),
            2,
        )


def main() -> int:
    args = build_parser().parse_args()
    model_path = Path(args.model)
    if not model_path.exists():
        logger.error("Model not found: %s", model_path)
        return 1

    output_dir = Path(args.save_dir)
    classifier = MaterialClassifier(detection_threshold=args.confidence)
    frame_counter = 0
    last_log_time = time.time()

    with VisionPipeline(
        model_path=str(model_path),
        camera_id=args.camera,
        num_inference_threads=args.threads,
        enable_async=not args.sync,
    ) as pipeline:
        logger.info("按 q 退出，按 s 保存当前分类画面")

        while True:
            result = pipeline.process_frame()
            if not result["success"]:
                logger.warning("Vision pipeline failed to produce a frame")
                continue

            frame_counter += 1
            raw_frame = result["raw_frame"].copy()
            boxes = result["boxes"]
            classes = result["classes"]
            scores = result["scores"]
            lines = [f"FPS: {pipeline.stats['avg_fps']:.2f}"]

            classifications = classifier.classify(
                image=raw_frame,
                detection_boxes=boxes,
                detection_classes=classes,
                detection_scores=scores,
                class_names=list(CLASSES),
            ) if boxes is not None and len(boxes) > 0 else []

            if classifications:
                for item in classifications[:3]:
                    label = classifier.get_material_label(item)
                    lines.append(f"{label} conf={item.confidence:.2f}")
                best = classifications[0]
                now = time.time()
                if now - last_log_time >= 1.0:
                    logger.info(
                        "best_classification=%s confidence=%.2f detection=%.2f color=%.2f",
                        classifier.get_material_label(best),
                        best.confidence,
                        best.detection_confidence,
                        best.color_confidence,
                    )
                    last_log_time = now
            else:
                lines.append("No valid classification")

            display_frame = result["frame"].copy()
            draw_classification_lines(display_frame, lines)

            if not args.headless:
                cv2.imshow("Camera Classification Test", display_frame)
                key = cv2.waitKey(1) & 0xFF
                if key == ord("q"):
                    break
                if key == ord("s"):
                    output_dir.mkdir(parents=True, exist_ok=True)
                    output_path = output_dir / f"classification_{frame_counter:05d}.jpg"
                    cv2.imwrite(str(output_path), display_frame)
                    logger.info("Saved frame: %s", output_path)
            else:
                if frame_counter % 30 == 0:
                    logger.info("frame=%s classifications=%s", frame_counter, len(classifications))

            if args.max_frames > 0 and frame_counter >= args.max_frames:
                break

    cv2.destroyAllWindows()
    logger.info("Camera classification test finished. total_frames=%s", frame_counter)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
