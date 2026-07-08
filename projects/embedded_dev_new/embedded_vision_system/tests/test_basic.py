#!/usr/bin/env python3
"""
单元测试示例
测试各个模块的基本功能
"""

import sys
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_camera_manager():
    """测试摄像头管理器"""
    logger.info("Testing CameraManager...")
    try:
        from embedded_vision_system import CameraManager
        
        # 注意：这个测试需要实际的摄像头设备
        # 在没有摄像头的环境中会失败
        try:
            camera = CameraManager(camera_id=0)
            props = camera.get_properties()
            logger.info(f"Camera properties: {props}")
            camera.release()
            logger.info("✓ CameraManager test passed")
        except RuntimeError as e:
            logger.warning(f"Camera not available: {e}")
            logger.info("✓ CameraManager test skipped (no camera)")
    
    except Exception as e:
        logger.error(f"✗ CameraManager test failed: {e}")
        return False
    
    return True


def test_yolov8_postprocess():
    """测试 YOLO 后处理模块"""
    logger.info("Testing YOLOv8 postprocess...")
    try:
        from embedded_vision_system.detection.yolov8_postprocess import (
            filter_boxes, nms_boxes, CLASSES
        )
        import numpy as np
        
        # 创建虚拟数据
        boxes = np.array([
            [100, 100, 200, 200],
            [150, 150, 250, 250],
        ])
        box_confidences = np.array([0.9, 0.7])
        box_class_probs = np.zeros((2, 80))
        box_class_probs[0, 0] = 0.95  # 类别 0，置信度 0.95
        box_class_probs[1, 1] = 0.85  # 类别 1，置信度 0.85
        
        # 测试过滤
        filtered_boxes, classes, scores = filter_boxes(
            boxes, box_confidences, box_class_probs
        )
        
        logger.info(f"Filtered boxes shape: {filtered_boxes.shape}")
        logger.info(f"Classes: {classes}")
        logger.info(f"Scores: {scores}")
        
        # 测试 NMS
        if len(filtered_boxes) > 0:
            keep_indices = nms_boxes(filtered_boxes, scores)
            logger.info(f"NMS kept indices: {keep_indices}")
        
        logger.info(f"Class names sample: {CLASSES[:5]}")
        logger.info("✓ YOLOv8 postprocess test passed")
    
    except Exception as e:
        logger.error(f"✗ YOLOv8 postprocess test failed: {e}")
        return False
    
    return True


def test_image_processor():
    """测试图像处理模块"""
    logger.info("Testing image processor...")
    try:
        from embedded_vision_system.detection.image_processor import (
            letterbox, preprocess_image, draw_detections
        )
        import cv2
        import numpy as np
        
        # 创建虚拟图像
        dummy_image = np.zeros((480, 640, 3), dtype=np.uint8)
        
        # 测试 letterbox
        resized, ratio, padding = letterbox(dummy_image, (640, 640))
        logger.info(f"Letterbox output shape: {resized.shape}")
        logger.info(f"Ratio: {ratio}, Padding: {padding}")
        
        # 测试预处理
        preprocessed, ratio, padding = preprocess_image(dummy_image)
        logger.info(f"Preprocessed shape: {preprocessed.shape}")
        
        # 测试绘图
        dummy_boxes = np.array([[100, 100, 200, 200]])
        dummy_classes = np.array([0])
        dummy_scores = np.array([0.9])
        
        drawn = draw_detections(
            dummy_image.copy(),
            dummy_boxes,
            dummy_scores,
            dummy_classes,
            ratio,
            padding
        )
        logger.info(f"Drew detections on image shape: {drawn.shape}")
        logger.info("✓ Image processor test passed")
    
    except Exception as e:
        logger.error(f"✗ Image processor test failed: {e}")
        return False
    
    return True


def test_frame_buffer():
    """测试帧缓冲区"""
    logger.info("Testing FrameBuffer...")
    try:
        from embedded_vision_system import FrameBuffer
        import numpy as np
        
        buffer = FrameBuffer(max_size=3)
        
        # 添加帧
        for i in range(5):
            frame = np.ones((480, 640, 3), dtype=np.uint8) * i
            buffer.push(frame)
        
        logger.info(f"Buffer size: {buffer.size()}")
        logger.info(f"Latest frame sum: {buffer.get_latest().sum()}")
        
        logger.info("✓ FrameBuffer test passed")
    
    except Exception as e:
        logger.error(f"✗ FrameBuffer test failed: {e}")
        return False
    
    return True


def test_imports():
    """测试模块导入"""
    logger.info("Testing module imports...")
    try:
        from embedded_vision_system import (
            CameraManager,
            FrameBuffer,
            RKNNInference,
            RKNNPoolExecutor,
            VisionPipeline,
        )
        logger.info("✓ All modules imported successfully")
    
    except Exception as e:
        logger.error(f"✗ Import test failed: {e}")
        return False
    
    return True


def main():
    """运行所有测试"""
    logger.info("=" * 50)
    logger.info("Running embedded_vision_system tests")
    logger.info("=" * 50)
    
    tests = [
        test_imports,
        test_yolov8_postprocess,
        test_image_processor,
        test_frame_buffer,
        test_camera_manager,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            if test():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            logger.error(f"Test execution failed: {e}")
            failed += 1
    
    logger.info("=" * 50)
    logger.info(f"Test results: {passed} passed, {failed} failed")
    logger.info("=" * 50)
    
    return failed == 0


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
