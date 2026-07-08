#!/usr/bin/env python3
"""
高级集成示例
展示如何将视觉系统与其他模块集成
"""

import sys
import logging
from pathlib import Path
from typing import List, Dict, Any

sys.path.insert(0, str(Path(__file__).parent))
from embedded_vision_system import VisionPipeline
from embedded_vision_system.detection.yolov8_postprocess import CLASSES

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class DetectionResult:
    """
    检测结果数据类
    """
    
    def __init__(self, boxes, classes, scores, frame_id: int):
        self.boxes = boxes
        self.classes = classes
        self.scores = scores
        self.frame_id = frame_id
        self.detections = self._parse_detections()
    
    def _parse_detections(self) -> List[Dict[str, Any]]:
        """解析检测结果为易读格式"""
        detections = []
        if self.boxes is None or len(self.boxes) == 0:
            return detections
        
        for box, cls, score in zip(self.boxes, self.classes, self.scores):
            detections.append({
                'class_name': CLASSES[int(cls)],
                'class_id': int(cls),
                'confidence': float(score),
                'bbox': [float(x) for x in box],
            })
        
        return detections
    
    def get_top_detections(self, n: int = 5) -> List[Dict[str, Any]]:
        """获取置信度最高的 n 个检测"""
        sorted_dets = sorted(
            self.detections,
            key=lambda x: x['confidence'],
            reverse=True
        )
        return sorted_dets[:n]
    
    def filter_by_class(self, class_names: List[str]) -> List[Dict[str, Any]]:
        """按类别过滤检测"""
        return [
            d for d in self.detections
            if d['class_name'] in class_names
        ]
    
    def to_dict(self) -> dict:
        """转换为字典格式"""
        return {
            'frame_id': self.frame_id,
            'num_detections': len(self.detections),
            'detections': self.detections,
        }


class NFC_MockReader:
    """
    NFC 读卡器模拟类
    在实际应用中，这应该替换为真实的 NFC 读卡接口
    """
    
    def __init__(self):
        self.material_database = {
            'MAT001': {'name': '红色塑料块', 'type': 'plastic', 'color': 'red'},
            'MAT002': {'name': '蓝色塑料块', 'type': 'plastic', 'color': 'blue'},
            'MAT003': {'name': '白色纸盒', 'type': 'box', 'color': 'white'},
        }
        self.last_read = None
    
    def read(self) -> str:
        """模拟读取 NFC"""
        # 在实际应用中，这应该调用真实的 NFC 库
        # 这里简单地返回测试数据
        import time
        if time.time() % 100 < 2:  # 每 ~100 秒读取一次
            self.last_read = 'MAT001'
            return 'MAT001'
        return None
    
    def get_material_info(self, material_id: str) -> Dict[str, Any]:
        """获取物料信息"""
        return self.material_database.get(
            material_id,
            {'name': 'Unknown', 'type': 'unknown', 'color': 'unknown'}
        )


class SortingDecisionEngine:
    """
    分拣决策引擎
    根据视觉检测结果、NFC 信息和订单参数进行决策
    """
    
    def __init__(self):
        self.decisions = []
    
    def make_decision(
        self,
        detection_result: DetectionResult,
        nfc_material_id: str = None,
        order_params: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        做出分拣决策
        
        Args:
            detection_result: 视觉检测结果
            nfc_material_id: NFC 读取的物料 ID
            order_params: 订单参数
        
        Returns:
            决策结果字典
        """
        decision = {
            'frame_id': detection_result.frame_id,
            'status': 'PASS',  # PASS 或 REJECT
            'reason': 'Normal',
            'confidence': 1.0,
        }
        
        # 如果没有检测到物体
        if len(detection_result.detections) == 0:
            decision['status'] = 'UNKNOWN'
            decision['reason'] = 'No object detected'
            decision['confidence'] = 0.0
            return decision
        
        # 获取最高置信度的检测
        top_detection = detection_result.get_top_detections(1)[0]
        detected_class = top_detection['class_name']
        confidence = top_detection['confidence']
        
        # 检查置信度
        if confidence < 0.5:
            decision['status'] = 'REJECT'
            decision['reason'] = 'Low confidence'
            decision['confidence'] = confidence
            return decision
        
        # 如果有 NFC 信息，进行对比（示例逻辑）
        if nfc_material_id:
            nfc_reader = NFC_MockReader()
            material_info = nfc_reader.get_material_info(nfc_material_id)
            
            # 简单的一致性检查
            if material_info['type'] == 'plastic' and 'plastic' not in detected_class.lower():
                decision['status'] = 'REJECT'
                decision['reason'] = f'NFC says {material_info["type"]}, detected {detected_class}'
            elif material_info['type'] == 'box' and 'box' not in detected_class.lower():
                decision['status'] = 'REJECT'
                decision['reason'] = f'NFC says {material_info["type"]}, detected {detected_class}'
        
        # 检查订单参数
        if order_params:
            expected_type = order_params.get('expected_type')
            if expected_type and expected_type not in detected_class.lower():
                decision['status'] = 'REJECT'
                decision['reason'] = f'Order expects {expected_type}, detected {detected_class}'
        
        decision['confidence'] = confidence
        return decision


def example_single_frame_analysis():
    """
    示例 1：单帧分析
    展示如何分析单个检测帧
    """
    logger.info("\n" + "="*50)
    logger.info("Example 1: Single Frame Analysis")
    logger.info("="*50)
    
    # 模拟检测结果
    import numpy as np
    
    boxes = np.array([
        [100, 100, 200, 200],  # 框 1
        [300, 150, 400, 300],  # 框 2
    ])
    classes = np.array([0, 5])  # 类别索引
    scores = np.array([0.95, 0.87])
    
    result = DetectionResult(boxes, classes, scores, frame_id=1)
    
    logger.info(f"Total detections: {len(result.detections)}")
    logger.info("Top 5 detections:")
    for det in result.get_top_detections(5):
        logger.info(
            f"  - {det['class_name']}: {det['confidence']:.2%} "
            f"at {det['bbox']}"
        )
    
    # 转换为 JSON 格式
    import json
    logger.info(f"Result as JSON:\n{json.dumps(result.to_dict(), indent=2)}")


def example_material_sorting():
    """
    示例 2：物料分拣
    展示如何基于检测结果进行物料分拣
    """
    logger.info("\n" + "="*50)
    logger.info("Example 2: Material Sorting")
    logger.info("="*50)
    
    import numpy as np
    
    # 模拟检测结果
    boxes = np.array([[100, 100, 200, 200]])
    classes = np.array([0])  # person（错误的检测）
    scores = np.array([0.85])
    
    detection = DetectionResult(boxes, classes, scores, frame_id=5)
    
    # 初始化分拣引擎
    engine = SortingDecisionEngine()
    
    # 场景 1：仅基于视觉检测
    decision = engine.make_decision(detection)
    logger.info(f"Decision 1 (vision only): {decision}")
    
    # 场景 2：结合 NFC 信息
    decision = engine.make_decision(
        detection,
        nfc_material_id='MAT001',
    )
    logger.info(f"Decision 2 (with NFC): {decision}")
    
    # 场景 3：结合订单参数
    order_params = {'expected_type': 'plastic'}
    decision = engine.make_decision(
        detection,
        order_params=order_params
    )
    logger.info(f"Decision 3 (with order): {decision}")


def example_class_filtering():
    """
    示例 3：类别过滤
    展示如何按物料类型进行过滤
    """
    logger.info("\n" + "="*50)
    logger.info("Example 3: Class Filtering")
    logger.info("="*50)
    
    import numpy as np
    
    # 模拟混合检测结果
    boxes = np.array([
        [100, 100, 200, 200],
        [300, 150, 400, 300],
        [150, 300, 250, 400],
    ])
    classes = np.array([45, 47, 50])  # bottle, sandwich, bowl
    scores = np.array([0.92, 0.88, 0.85])
    
    detection = DetectionResult(boxes, classes, scores, frame_id=10)
    
    logger.info(f"All detections ({len(detection.detections)}):")
    for det in detection.detections:
        logger.info(f"  - {det['class_name']}: {det['confidence']:.2%}")
    
    # 按类别过滤
    food_items = detection.filter_by_class(['bottle', 'sandwich', 'bowl'])
    logger.info(f"\nFiltered food items ({len(food_items)}):")
    for item in food_items:
        logger.info(f"  - {item['class_name']}: {item['confidence']:.2%}")


def main():
    """运行所有示例"""
    logger.info("Embedded Vision System - Integration Examples")
    
    try:
        example_single_frame_analysis()
        example_material_sorting()
        example_class_filtering()
        
        logger.info("\n" + "="*50)
        logger.info("All examples completed successfully!")
        logger.info("="*50)
    
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
