"""
视觉管道模块
整合摄像头、检测、后处理的完整流程
"""

import logging
import time
from typing import Optional, Dict, Any

import numpy as np

from ..camera.camera_manager import CameraManager
from ..detection.rknn_engine import RKNNPoolExecutor, simple_inference
from ..detection.yolov8_postprocess import yolov8_post_process
from ..detection.image_processor import preprocess_image, draw_detections

logger = logging.getLogger(__name__)


class VisionPipeline:
    """
    视觉处理管道
    """
    
    def __init__(
        self,
        model_path: str,
        camera_id: str = "/dev/video0",
        num_inference_threads: int = 4,
        enable_async: bool = True
    ):
        """
        初始化视觉管道
        
        Args:
            model_path: RKNN 模型文件路径
            camera_id: 摄像头设备 ID
            num_inference_threads: 推理线程数
            enable_async: 是否启用异步推理
        """
        self.model_path = model_path
        self.camera_id = camera_id
        self.enable_async = enable_async
        
        # 初始化摄像头
        try:
            self.camera = CameraManager(camera_id=camera_id)
        except Exception as e:
            logger.error(f"Failed to initialize camera: {e}")
            raise
        
        # 初始化推理引擎
        try:
            if enable_async:
                self.inference_engine = RKNNPoolExecutor(
                    model_path=model_path,
                    num_threads=num_inference_threads
                )
            else:
                # 简单的单线程推理
                from ..detection.rknn_engine import RKNNInference
                self.inference_engine = RKNNInference(model_path=model_path)
        except Exception as e:
            logger.error(f"Failed to initialize inference engine: {e}")
            self.camera.release()
            raise
        
        # 性能统计
        self.stats = {
            'total_frames': 0,
            'processed_frames': 0,
            'avg_fps': 0.0,
            'inference_time': 0.0,
            'total_detections': 0
        }
        
        self.start_time = time.time()
        self.frame_times = []
    
    def _inference_function(self, rknn_model, image_data):
        """
        推理包装函数（用于异步推理）
        
        Args:
            rknn_model: RKNN 模型实例
            image_data: 输入图像数据
        
        Returns:
            (image, boxes, classes, scores)
        """
        inference_start = time.time()
        
        # 推理
        outputs = rknn_model.inference(image_data)
        
        # 后处理
        boxes, classes, scores = yolov8_post_process(outputs)
        
        inference_time = time.time() - inference_start
        self.stats['inference_time'] = inference_time
        
        return (image_data, boxes, classes, scores)
    
    def process_frame(self) -> Dict[str, Any]:
        """
        处理单帧
        
        Returns:
            处理结果字典 {
                'success': bool,
                'raw_frame': np.ndarray,
                'frame': np.ndarray,
                'boxes': np.ndarray or None,
                'classes': np.ndarray or None,
                'scores': np.ndarray or None,
                'metadata': dict
            }
        """
        # 读取摄像头帧
        ret, frame = self.camera.read_frame()
        if not ret or frame is None:
            return {
                'success': False,
                'raw_frame': None,
                'frame': None,
                'boxes': None,
                'classes': None,
                'scores': None,
                'metadata': {}
            }
        
        self.stats['total_frames'] += 1
        
        # 预处理
        preprocessed_image, ratio, padding = preprocess_image(frame)
        
        # 推理（同步或异步）
        if self.enable_async:
            # 异步推理
            self.inference_engine.submit_task(
                preprocessed_image,
                self._inference_function
            )
            
            result_data, success = self.inference_engine.get_result()
            if not success or result_data is None:
                boxes, classes, scores = None, None, None
            else:
                _, boxes, classes, scores = result_data
        else:
            # 同步推理
            inference_start = time.time()
            outputs = self.inference_engine.inference(preprocessed_image)
            boxes, classes, scores = yolov8_post_process(outputs)
            self.stats['inference_time'] = time.time() - inference_start
        
        # 统计检测结果
        if boxes is not None:
            self.stats['total_detections'] += len(boxes)
        
        # 绘制检测框
        if boxes is not None:
            frame_with_boxes = draw_detections(
                frame.copy(), boxes, scores, classes, ratio, padding
            )
        else:
            frame_with_boxes = frame
        
        self.stats['processed_frames'] += 1
        
        # 计算 FPS
        self.frame_times.append(time.time())
        if len(self.frame_times) > 30:  # 保持最近 30 帧
            self.frame_times.pop(0)
            elapsed = self.frame_times[-1] - self.frame_times[0]
            if elapsed > 0:
                self.stats['avg_fps'] = len(self.frame_times) / elapsed
        
        return {
            'success': True,
            'raw_frame': frame,
            'frame': frame_with_boxes,
            'boxes': boxes,
            'classes': classes,
            'scores': scores,
            'metadata': {
                'frame_id': self.stats['total_frames'],
                'num_detections': len(boxes) if boxes is not None else 0,
                'ratio': ratio,
                'padding': padding,
                'camera_props': self.camera.get_properties()
            }
        }
    
    def release(self):
        """释放所有资源"""
        if hasattr(self, 'camera') and self.camera is not None:
            self.camera.release()
        
        if hasattr(self, 'inference_engine'):
            if hasattr(self.inference_engine, 'release'):
                self.inference_engine.release()
        
        # 输出统计信息
        total_time = time.time() - self.start_time
        logger.info(
            f"\n=== Vision Pipeline Statistics ===\n"
            f"Total frames: {self.stats['total_frames']}\n"
            f"Processed frames: {self.stats['processed_frames']}\n"
            f"Average FPS: {self.stats['avg_fps']:.2f}\n"
            f"Total detections: {self.stats['total_detections']}\n"
            f"Average inference time: {self.stats['inference_time']*1000:.2f}ms\n"
            f"Total time: {total_time:.2f}s"
        )
    
    def __enter__(self):
        """上下文管理器入口"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.release()
