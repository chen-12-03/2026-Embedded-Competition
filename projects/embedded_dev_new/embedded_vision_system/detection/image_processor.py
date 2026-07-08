"""
图像处理工具模块
包括：预处理、绘图等功能
"""

import cv2
import numpy as np
from .yolov8_postprocess import CLASSES


def letterbox(im, new_shape=(640, 640), color=(0, 0, 0)):
    """
    等比例缩放和填充，保持宽高比
    
    Args:
        im: 输入图像
        new_shape: 目标形状
        color: 填充颜色
    
    Returns:
        resized_im: 缩放后的图像
        ratio: 缩放比例 (width_ratio, height_ratio)
        padding: 填充量 (left, top)
    """
    shape = im.shape[:2]  # [height, width]
    
    if isinstance(new_shape, int):
        new_shape = (new_shape, new_shape)

    r = min(new_shape[0] / shape[0], new_shape[1] / shape[1])
    ratio = r, r
    new_unpad = int(round(shape[1] * r)), int(round(shape[0] * r))
    dw, dh = new_shape[1] - new_unpad[0], new_shape[0] - new_unpad[1]

    dw /= 2
    dh /= 2

    if shape[::-1] != new_unpad:
        im = cv2.resize(im, new_unpad, interpolation=cv2.INTER_LINEAR)
    
    top, bottom = int(round(dh - 0.1)), int(round(dh + 0.1))
    left, right = int(round(dw - 0.1)), int(round(dw + 0.1))
    im = cv2.copyMakeBorder(im, top, bottom, left, right,
                            cv2.BORDER_CONSTANT, value=color)
    
    return im, ratio, (left, top)


def preprocess_image(image, target_size=(640, 640)):
    """
    预处理图像用于 RKNN 推理
    
    Args:
        image: 输入图像
        target_size: 目标大小
    
    Returns:
        preprocessed_image: 预处理后的图像 [1, H, W, C]
        ratio: 缩放比例
        padding: 填充信息
    """
    # BGR -> RGB
    image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    
    # 等比例缩放
    image_rgb, ratio, padding = letterbox(image_rgb, target_size)
    
    # 增加 batch 维度
    image_rgb = np.expand_dims(image_rgb, 0)
    
    return image_rgb, ratio, padding


def draw_box_corner(draw_img, top, left, right, bottom, length=15, corner_color=(0, 255, 0)):
    """
    绘制矩形框的四个角
    
    Args:
        draw_img: 要绘制的图像
        top, left, right, bottom: 框的坐标
        length: 角的长度
        corner_color: 角的颜色
    """
    thickness = 3
    
    # Top Left
    cv2.line(draw_img, (top, left), (top + length, left), corner_color, thickness=thickness)
    cv2.line(draw_img, (top, left), (top, left + length), corner_color, thickness=thickness)
    
    # Top Right
    cv2.line(draw_img, (right, left), (right - length, left), corner_color, thickness=thickness)
    cv2.line(draw_img, (right, left), (right, left + length), corner_color, thickness=thickness)
    
    # Bottom Left
    cv2.line(draw_img, (top, bottom), (top + length, bottom), corner_color, thickness=thickness)
    cv2.line(draw_img, (top, bottom), (top, bottom - length), corner_color, thickness=thickness)
    
    # Bottom Right
    cv2.line(draw_img, (right, bottom), (right - length, bottom), corner_color, thickness=thickness)
    cv2.line(draw_img, (right, bottom), (right, bottom - length), corner_color, thickness=thickness)


def draw_label(draw_img, top, left, label_text, label_color=(255, 0, 255)):
    """
    绘制标签文本
    
    Args:
        draw_img: 要绘制的图像
        top, left: 标签位置
        label_text: 标签文本
        label_color: 标签颜色
    """
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 1
    thickness = 2
    
    labelSize = cv2.getTextSize(label_text, font, font_scale, thickness)[0]

    # 计算文本背景框位置
    if left - labelSize[1] - 3 < 0:
        # 标签在右侧放置
        box_coords = (top, left + 5, top + labelSize[0], left + labelSize[1] + 3)
        text_pos = (top, left + labelSize[1] + 3)
    else:
        # 标签在左侧放置
        box_coords = (top, left - labelSize[1] - 3, top + labelSize[0], left - 3)
        text_pos = (top, left - 3)

    # 绘制背景框
    cv2.rectangle(draw_img, box_coords[0:2], box_coords[2:4],
                  color=label_color, thickness=-1)

    # 绘制文本
    cv2.putText(draw_img, label_text, text_pos, font, font_scale,
                (0, 0, 0), thickness=thickness)


def draw_detections(image, boxes, scores, classes, ratio, padding):
    """
    在图像上绘制检测结果
    
    Args:
        image: 原始图像
        boxes: 检测框坐标 [N, 4]
        scores: 检测分数 [N]
        classes: 类别索引 [N]
        ratio: 缩放比例
        padding: 填充信息
    """
    if boxes is None or len(boxes) == 0:
        return image

    for box, score, cls_idx in zip(boxes, scores, classes):
        top, left, right, bottom = box

        # 坐标变换：从缩放空间回到原始空间
        top = int((top - padding[0]) / ratio[0])
        left = int((left - padding[1]) / ratio[1])
        right = int((right - padding[0]) / ratio[0])
        bottom = int((bottom - padding[1]) / ratio[1])

        # 确保坐标在图像范围内
        top = max(0, min(top, image.shape[1] - 1))
        left = max(0, min(left, image.shape[0] - 1))
        right = max(0, min(right, image.shape[1] - 1))
        bottom = max(0, min(bottom, image.shape[0] - 1))

        # 绘制矩形框
        cv2.rectangle(image, (top, left), (right, bottom), (255, 0, 255), 2)
        
        # 绘制框的四个角
        draw_box_corner(image, top, left, right, bottom, 15, (0, 255, 0))
        
        # 绘制标签
        class_name = CLASSES[int(cls_idx)]
        label_text = f"{class_name} {score:.2f}"
        draw_label(image, top, left, label_text, (255, 0, 255))

    return image
