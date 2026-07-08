"""
传统视觉形状 + 颜色识别模块

适用于固定机位、固定背景、有限颜色和有限形状的首版场景：
- 颜色：红 / 黄 / 蓝 / 绿 / 紫
- 形状：正方形 / 长方形 / 三角形 / 圆锥形
- 材质：固定木质件
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from ..order_manager import normalize_color, normalize_material_type, normalize_shape

logger = logging.getLogger(__name__)


DEFAULT_MATERIAL_TYPE = "木质件"

COLOR_MASK_RANGES = {
    "红色": [
        (np.array([0, 90, 80]), np.array([10, 255, 255])),
        (np.array([170, 90, 80]), np.array([180, 255, 255])),
    ],
    "黄色": [
        (np.array([18, 80, 80]), np.array([40, 255, 255])),
    ],
    "绿色": [
        (np.array([40, 70, 70]), np.array([90, 255, 255])),
    ],
    "蓝色": [
        (np.array([95, 70, 70]), np.array([135, 255, 255])),
    ],
    "紫色": [
        (np.array([130, 70, 60]), np.array([165, 255, 255])),
    ],
}

DISPLAY_COLORS = {
    "红色": (0, 0, 255),
    "黄色": (0, 215, 255),
    "绿色": (0, 200, 0),
    "蓝色": (255, 0, 0),
    "紫色": (255, 0, 255),
}


@dataclass
class ShapeColorClassificationResult:
    """受控场景下的结构化识别结果。"""

    material_type: Optional[str] = DEFAULT_MATERIAL_TYPE
    color: Optional[str] = None
    shape: Optional[str] = None
    confidence: float = 0.0
    color_confidence: float = 0.0
    shape_confidence: float = 0.0
    success: bool = False
    bbox: Optional[Tuple[int, int, int, int]] = None
    contour_area: float = 0.0
    vertex_count: int = 0
    details: str = ""


class TraditionalShapeColorClassifier:
    """
    面向当前赛题样品的传统视觉识别器。

    识别策略：
    1. 先按 HSV 对受控颜色做掩膜。
    2. 对每个颜色掩膜提取轮廓。
    3. 使用多边形近似判断三角形 / 正方形 / 长方形 / 圆锥形。
    """

    def __init__(
        self,
        min_contour_area: int = 2000,
        polygon_epsilon_ratio: float = 0.04,
        square_ratio_tolerance: float = 0.18,
        min_color_confidence: float = 0.35,
        max_contours_per_color: int = 12,
    ):
        self.min_contour_area = min_contour_area
        self.polygon_epsilon_ratio = polygon_epsilon_ratio
        self.square_ratio_tolerance = square_ratio_tolerance
        self.min_color_confidence = min_color_confidence
        self.max_contours_per_color = max(1, max_contours_per_color)
        self.kernel = np.ones((5, 5), dtype=np.uint8)

    def classify(self, image: np.ndarray) -> List[ShapeColorClassificationResult]:
        """对单帧图像进行颜色 + 形状识别。"""
        if image is None or image.size == 0:
            return []

        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        results: List[ShapeColorClassificationResult] = []

        for color_name, ranges in COLOR_MASK_RANGES.items():
            mask = self._build_color_mask(hsv, ranges)
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            # Noisy frames can contain hundreds of tiny contours. Only the
            # largest viable candidates may represent the demonstration item.
            candidates = [
                (float(cv2.contourArea(contour)), contour)
                for contour in contours
            ]
            candidates = [
                candidate
                for candidate in candidates
                if candidate[0] >= self.min_contour_area
            ]
            candidates.sort(key=lambda candidate: candidate[0], reverse=True)

            for contour_area, contour in candidates[:self.max_contours_per_color]:

                shape_name, shape_confidence, vertex_count = self._classify_shape(contour)
                if shape_name is None:
                    continue

                x, y, w, h = cv2.boundingRect(contour)
                color_confidence = self._estimate_color_confidence(mask, contour, x, y, w, h)
                if color_confidence < self.min_color_confidence:
                    continue

                confidence = min(1.0, shape_confidence * 0.55 + color_confidence * 0.45)
                result = ShapeColorClassificationResult(
                    material_type=DEFAULT_MATERIAL_TYPE,
                    color=color_name,
                    shape=shape_name,
                    confidence=confidence,
                    color_confidence=color_confidence,
                    shape_confidence=shape_confidence,
                    success=True,
                    bbox=(x, y, x + w, y + h),
                    contour_area=contour_area,
                    vertex_count=vertex_count,
                    details=(
                        f"{color_name}{shape_name} "
                        f"area={contour_area:.0f} "
                        f"shape_conf={shape_confidence:.2f} "
                        f"color_conf={color_confidence:.2f}"
                    ),
                )
                results.append(result)

        return sorted(
            results,
            key=lambda item: (item.confidence, item.contour_area),
            reverse=True,
        )

    def annotate_frame(
        self,
        frame: np.ndarray,
        results: List[ShapeColorClassificationResult],
        top_k: int = 3,
    ) -> np.ndarray:
        """在画面上叠加识别框和标签。"""
        annotated = frame.copy()
        for result in results[:top_k]:
            if result.bbox is None:
                continue

            left, top, right, bottom = result.bbox
            display_color = DISPLAY_COLORS.get(result.color or "", (0, 255, 0))
            cv2.rectangle(annotated, (left, top), (right, bottom), display_color, 2)
            cv2.putText(
                annotated,
                self.get_display_label(result),
                (left, max(24, top - 8)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                display_color,
                2,
            )
        return annotated

    def get_display_label(self, result: ShapeColorClassificationResult) -> str:
        if result.color is None or result.shape is None:
            return "未知物料"
        return f"{result.color}{result.shape}"

    def classify_best(self, image: np.ndarray) -> Optional[ShapeColorClassificationResult]:
        results = self.classify(image)
        return results[0] if results else None

    def _build_color_mask(
        self,
        hsv_image: np.ndarray,
        ranges: List[Tuple[np.ndarray, np.ndarray]],
    ) -> np.ndarray:
        mask = np.zeros(hsv_image.shape[:2], dtype=np.uint8)
        for lower, upper in ranges:
            mask = cv2.bitwise_or(mask, cv2.inRange(hsv_image, lower, upper))

        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, self.kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, self.kernel)
        return mask

    def _classify_shape(self, contour: np.ndarray) -> Tuple[Optional[str], float, int]:
        perimeter = cv2.arcLength(contour, True)
        if perimeter <= 0:
            return None, 0.0, 0

        approx = cv2.approxPolyDP(
            contour,
            self.polygon_epsilon_ratio * perimeter,
            True,
        )
        vertices = len(approx)

        if vertices == 3:
            return "三角形", 0.95, vertices

        if vertices == 4:
            return self._classify_quadrilateral(contour, approx)

        cone_confidence = self._estimate_cone_confidence(contour)
        if cone_confidence >= 0.72:
            return "圆锥形", cone_confidence, vertices

        return None, 0.0, vertices

    def _estimate_cone_confidence(self, contour: np.ndarray) -> float:
        """用轮廓宽度变化判断是否接近圆锥侧视轮廓。"""
        x, y, w, h = cv2.boundingRect(contour)
        if w <= 0 or h <= 0:
            return 0.0

        contour_mask = np.zeros((h, w), dtype=np.uint8)
        shifted = contour - np.array([[[x, y]]], dtype=contour.dtype)
        cv2.drawContours(contour_mask, [shifted], -1, 255, thickness=-1)

        widths: List[int] = []
        sample_rows = np.linspace(0, h - 1, num=min(h, 16), dtype=int)
        for row in sample_rows:
            columns = np.flatnonzero(contour_mask[row])
            if columns.size == 0:
                continue
            widths.append(int(columns[-1] - columns[0] + 1))

        if len(widths) < 6:
            return 0.0

        top_band = widths[: max(2, len(widths) // 4)]
        bottom_band = widths[-max(2, len(widths) // 4):]
        top_width = float(sum(top_band)) / float(len(top_band))
        bottom_width = float(sum(bottom_band)) / float(len(bottom_band))
        if bottom_width <= 0.0 or top_width >= bottom_width:
            return 0.0

        area = float(cv2.contourArea(contour))
        bbox_area = float(max(w * h, 1))
        fill_ratio = area / bbox_area
        taper_ratio = 1.0 - (top_width / bottom_width)

        confidence = 0.58 * taper_ratio + 0.42 * fill_ratio
        return float(max(0.0, min(0.95, confidence)))

    def _classify_quadrilateral(
        self,
        contour: np.ndarray,
        approx: np.ndarray,
    ) -> Tuple[Optional[str], float, int]:
        rect = cv2.minAreaRect(contour)
        rect_width, rect_height = rect[1]
        if rect_width <= 0 or rect_height <= 0:
            return None, 0.0, 4

        short_side = max(min(float(rect_width), float(rect_height)), 1e-6)
        long_side = max(float(rect_width), float(rect_height))
        rotated_aspect_ratio = long_side / short_side

        points = approx.reshape(-1, 2).astype(np.float32)
        side_lengths = []
        for index in range(4):
            start = points[index]
            end = points[(index + 1) % 4]
            side_lengths.append(float(np.linalg.norm(end - start)))

        shortest_edge = max(min(side_lengths), 1e-6)
        longest_edge = max(side_lengths)
        side_ratio = longest_edge / shortest_edge

        contour_area = float(cv2.contourArea(contour))
        rect_area = max(float(rect_width) * float(rect_height), 1.0)
        fill_ratio = contour_area / rect_area

        square_aspect_limit = 1.0 + self.square_ratio_tolerance * 1.5
        square_side_limit = 1.0 + self.square_ratio_tolerance * 1.8
        rectangle_limit = 1.0 + self.square_ratio_tolerance * 2.4

        if (
            rotated_aspect_ratio <= square_aspect_limit
            and side_ratio <= square_side_limit
            and fill_ratio >= 0.72
        ):
            aspect_score = 1.0 - min(
                1.0,
                (rotated_aspect_ratio - 1.0) / max(square_aspect_limit - 1.0, 1e-6),
            )
            side_score = 1.0 - min(
                1.0,
                (side_ratio - 1.0) / max(square_side_limit - 1.0, 1e-6),
            )
            fill_score = min(1.0, max(0.0, (fill_ratio - 0.72) / 0.28))
            confidence = 0.45 * aspect_score + 0.35 * side_score + 0.20 * fill_score
            return "正方形", float(max(0.72, min(0.97, confidence))), 4

        elongated_ratio = max(rotated_aspect_ratio, side_ratio)
        if elongated_ratio < rectangle_limit and fill_ratio >= 0.76:
            confidence = 0.55 + fill_ratio * 0.15 + max(0.0, rectangle_limit - elongated_ratio) * 0.35
            return "正方形", float(max(0.70, min(0.92, confidence))), 4

        confidence = 0.62 + min(0.35, (elongated_ratio - 1.0) * 0.5)
        return "长方形", float(max(0.75, min(0.97, confidence))), 4

    def _estimate_color_confidence(
        self,
        color_mask: np.ndarray,
        contour: np.ndarray,
        x: int,
        y: int,
        w: int,
        h: int,
    ) -> float:
        del contour
        bbox_area = max(w * h, 1)
        color_pixels = cv2.countNonZero(color_mask[y:y + h, x:x + w])
        if color_pixels == 0:
            return 0.0
        return float(color_pixels) / float(bbox_area)


class ShapeColorResultConverter:
    """将传统视觉结果转换为主流程可消费的结构。"""

    @staticmethod
    def to_dict(result: ShapeColorClassificationResult) -> Dict:
        material_type = normalize_material_type(result.material_type) or DEFAULT_MATERIAL_TYPE
        color = normalize_color(result.color)
        shape = normalize_shape(result.shape)
        label = f"{color}{shape}" if color and shape else None
        return {
            "success": result.success,
            "material_type": material_type,
            "color": color,
            "shape": shape,
            "confidence": result.confidence,
            "label": label,
            "bbox": result.bbox,
            "color_confidence": result.color_confidence,
            "shape_confidence": result.shape_confidence,
            "contour_area": result.contour_area,
            "vertex_count": result.vertex_count,
            "details": result.details,
        }

    @staticmethod
    def from_dict(data: Dict) -> ShapeColorClassificationResult:
        return ShapeColorClassificationResult(
            material_type=normalize_material_type(data.get("material_type")) or DEFAULT_MATERIAL_TYPE,
            color=normalize_color(data.get("color")),
            shape=normalize_shape(data.get("shape")),
            confidence=float(data.get("confidence", 0.0)),
            color_confidence=float(data.get("color_confidence", 0.0)),
            shape_confidence=float(data.get("shape_confidence", 0.0)),
            success=bool(data.get("success", False)),
            bbox=data.get("bbox"),
            contour_area=float(data.get("contour_area", 0.0)),
            vertex_count=int(data.get("vertex_count", 0)),
            details=str(data.get("details", "")),
        )


__all__ = [
    "DEFAULT_MATERIAL_TYPE",
    "ShapeColorClassificationResult",
    "TraditionalShapeColorClassifier",
    "ShapeColorResultConverter",
]
