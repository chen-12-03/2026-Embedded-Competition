import cv2
import numpy as np

from embedded_vision_system.detection.shape_color_classifier import TraditionalShapeColorClassifier


def _build_yellow_polygon_frame(points):
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    cv2.fillConvexPoly(frame, np.array(points, dtype=np.int32), (0, 255, 255))
    return frame


def test_classifier_prefers_square_for_perspective_skewed_square():
    classifier = TraditionalShapeColorClassifier(min_contour_area=500)
    frame = _build_yellow_polygon_frame(
        [
            (220, 170),
            (390, 205),
            (355, 335),
            (185, 300),
        ]
    )

    result = classifier.classify_best(frame)

    assert result is not None
    assert result.color == "黄色"
    assert result.shape == "正方形"


def test_classifier_keeps_clearly_elongated_rectangle_as_rectangle():
    classifier = TraditionalShapeColorClassifier(min_contour_area=500)
    frame = _build_yellow_polygon_frame(
        [
            (190, 180),
            (450, 180),
            (450, 310),
            (190, 310),
        ]
    )

    result = classifier.classify_best(frame)

    assert result is not None
    assert result.color == "黄色"
    assert result.shape == "长方形"
