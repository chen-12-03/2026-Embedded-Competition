"""
视觉分类增强模块
支持物料类型 + 颜色的结构化识别
"""

import logging
from typing import Dict, Optional, Tuple, List
from dataclasses import dataclass
import numpy as np
import cv2

from ..order_manager import normalize_color, normalize_material_type
from ..hardware import MockNFCReader

logger = logging.getLogger(__name__)


COCO_TO_MATERIAL_TYPE = {
    "bottle": "塑料块",
    "cup": "塑料块",
    "bowl": "塑料块",
    "frisbee": "塑料块",
    "suitcase": "纸盒",
    "backpack": "纸盒",
    "handbag": "纸盒",
}

COLOR_RANGES = {
    "红色": {
        "lower": np.array([0, 100, 100]),
        "upper": np.array([10, 255, 255]),
    },
    "蓝色": {
        "lower": np.array([100, 100, 100]),
        "upper": np.array([130, 255, 255]),
    },
    "白色": {
        "lower": np.array([0, 0, 200]),
        "upper": np.array([180, 30, 255]),
    },
    "黑色": {
        "lower": np.array([0, 0, 0]),
        "upper": np.array([180, 255, 50]),
    },
    "绿色": {
        "lower": np.array([50, 100, 100]),
        "upper": np.array([70, 255, 255]),
    },
    "黄色": {
        "lower": np.array([20, 100, 100]),
        "upper": np.array([40, 255, 255]),
    },
    "紫色": {
        "lower": np.array([130, 80, 70]),
        "upper": np.array([165, 255, 255]),
    },
}


@dataclass
class MaterialClassificationResult:
    """物料分类结果"""

    material_type: Optional[str] = None
    color: Optional[str] = None
    confidence: float = 0.0
    detection_confidence: float = 0.0
    color_confidence: float = 0.0
    success: bool = False
    bbox: Optional[Tuple[int, int, int, int]] = None
    details: str = ""


class MaterialClassifier:
    """
    物料分类器
    将检测结果和颜色分析组合为赛题使用的结构化字段。
    """

    def __init__(self, detection_threshold: float = 0.5):
        self.detection_threshold = detection_threshold
        self.color_ranges = COLOR_RANGES
        logger.info("Material classifier initialized")

    def classify(
        self,
        image: np.ndarray,
        detection_boxes: np.ndarray,
        detection_classes: np.ndarray,
        detection_scores: np.ndarray,
        class_names: List[str],
    ) -> List[MaterialClassificationResult]:
        """对检测到的候选目标进行赛题语义分类。"""
        results: List[MaterialClassificationResult] = []

        if detection_boxes is None or len(detection_boxes) == 0:
            logger.info("No detections to classify")
            return results

        for box, cls_idx, score in zip(
            detection_boxes,
            detection_classes,
            detection_scores,
        ):
            if float(score) < self.detection_threshold:
                continue

            cls_name = class_names[int(cls_idx)]
            roi = self._extract_roi(image, [int(x) for x in box])
            if roi is None:
                continue

            material_type = self._detect_material_type(cls_name)
            color, color_conf = self._detect_color(roi)
            overall_conf = (float(score) + color_conf) / 2.0

            result = MaterialClassificationResult(
                material_type=material_type,
                color=color,
                confidence=overall_conf,
                detection_confidence=float(score),
                color_confidence=color_conf,
                success=material_type is not None and color is not None,
                bbox=tuple(int(x) for x in box),
                details=f"{cls_name} -> {material_type} {color}",
            )
            results.append(result)
            logger.info(
                "Classification: %s (conf=%.2f%%)",
                result.details,
                result.confidence * 100,
            )

        return sorted(results, key=lambda item: item.confidence, reverse=True)

    def _extract_roi(
        self,
        image: np.ndarray,
        box: List[int],
    ) -> Optional[np.ndarray]:
        """从 [left, top, right, bottom] 边界框提取 ROI。"""
        left, top, right, bottom = box
        h, w = image.shape[:2]

        left = max(0, min(left, w - 1))
        top = max(0, min(top, h - 1))
        right = max(0, min(right, w - 1))
        bottom = max(0, min(bottom, h - 1))

        if left >= right or top >= bottom:
            return None

        roi = image[top:bottom, left:right]
        return roi if roi.size > 0 else None

    def _detect_material_type(self, class_name: str) -> Optional[str]:
        """根据检测类别名映射赛题物料类型。"""
        class_name_lower = class_name.lower().strip()
        material_type = COCO_TO_MATERIAL_TYPE.get(class_name_lower)
        if material_type is None:
            logger.debug("Unknown material type: %s", class_name)
        return material_type

    def _detect_color(self, roi: np.ndarray) -> Tuple[Optional[str], float]:
        """使用 HSV 统计主色。"""
        if roi is None or roi.size == 0:
            return None, 0.0

        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        best_color = None
        best_confidence = 0.0

        for color_name, color_range in self.color_ranges.items():
            mask = cv2.inRange(
                hsv,
                color_range["lower"],
                color_range["upper"],
            )
            match_ratio = float(np.count_nonzero(mask)) / float(mask.size)
            if match_ratio > best_confidence:
                best_confidence = match_ratio
                best_color = color_name

        if best_confidence < 0.2:
            logger.debug("Color detection confidence too low")
            return None, 0.0

        return best_color, best_confidence

    def get_material_label(self, result: MaterialClassificationResult) -> str:
        """获取用于展示的组合标签。"""
        if result.material_type is None or result.color is None:
            return "未知物料"
        return f"{result.color}{result.material_type}"


class VisionResultConverter:
    """视觉结果转换器。"""

    @staticmethod
    def to_dict(result: MaterialClassificationResult) -> Dict:
        material_type = normalize_material_type(result.material_type)
        color = normalize_color(result.color)
        return {
            "success": result.success,
            "material_type": material_type,
            "color": color,
            "confidence": result.confidence,
            "label": f"{color}{material_type}" if result.success else None,
            "bbox": result.bbox,
            "detection_confidence": result.detection_confidence,
            "color_confidence": result.color_confidence,
            "details": result.details,
        }

    @staticmethod
    def from_dict(data: Dict) -> MaterialClassificationResult:
        return MaterialClassificationResult(
            material_type=normalize_material_type(data.get("material_type")),
            color=normalize_color(data.get("color")),
            confidence=data.get("confidence", 0.0),
            detection_confidence=data.get("detection_confidence", 0.0),
            color_confidence=data.get("color_confidence", 0.0),
            success=data.get("success", False),
            bbox=data.get("bbox"),
            details=data.get("details", ""),
        )


class NFC_Reader_Mock(MockNFCReader):
    """
    兼容旧导入路径的 NFC 模拟类。

    新代码优先使用 `embedded_vision_system.hardware.MockNFCReader`。
    """
