"""
配置模块
用于管理视觉系统的各种配置参数
"""

from dataclasses import dataclass
from typing import Optional
import json
from pathlib import Path

from .storage import ensure_managed_path


@dataclass
class CameraConfig:
    """摄像头配置"""
    device_id: str = "/dev/video52"
    width: int = 1280
    height: int = 720
    fps: int = 30
    brightness: int = 0
    contrast: int = 0
    saturation: int = 0


@dataclass
class DetectionConfig:
    """检测配置"""
    model_path: str = "./rknnModel/best.rknn"
    obj_threshold: float = 0.25
    nms_threshold: float = 0.45
    input_size: int = 640
    num_threads: int = 8
    enable_async: bool = True


@dataclass
class DisplayConfig:
    """显示配置"""
    window_name: str = "Object Detection"
    display_fps: bool = True
    display_detections: bool = True
    fullscreen: bool = False
    font_size: float = 0.7
    line_width: int = 2
    corner_length: int = 15


@dataclass
class OutputConfig:
    """输出配置"""
    save_video: bool = False
    video_path: Optional[str] = None
    save_frames: bool = False
    frames_dir: Optional[str] = None
    save_results_json: bool = False
    results_json_path: Optional[str] = None


@dataclass
class PerformanceConfig:
    """性能配置"""
    max_frame_queue_size: int = 10
    inference_timeout: float = 5.0
    enable_profiling: bool = False
    profile_output_dir: Optional[str] = None


@dataclass
class SystemConfig:
    """系统总体配置"""
    camera: CameraConfig
    detection: DetectionConfig
    display: DisplayConfig
    output: OutputConfig
    performance: PerformanceConfig
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            'camera': self.camera.__dict__,
            'detection': self.detection.__dict__,
            'display': self.display.__dict__,
            'output': self.output.__dict__,
            'performance': self.performance.__dict__,
        }
    
    def save_to_file(self, filepath: str):
        """保存配置到文件"""
        managed_path = ensure_managed_path(filepath, "configs")
        with open(managed_path, 'w') as f:
            json.dump(self.to_dict(), f, indent=2)
    
    @classmethod
    def load_from_file(cls, filepath: str) -> 'SystemConfig':
        """从文件加载配置"""
        managed_path = ensure_managed_path(filepath, "configs", create_parent=False)
        with open(managed_path, 'r') as f:
            data = json.load(f)
        
        return cls(
            camera=CameraConfig(**data['camera']),
            detection=DetectionConfig(**data['detection']),
            display=DisplayConfig(**data['display']),
            output=OutputConfig(**data['output']),
            performance=PerformanceConfig(**data['performance']),
        )
    
    @classmethod
    def create_default(cls) -> 'SystemConfig':
        """创建默认配置"""
        return cls(
            camera=CameraConfig(),
            detection=DetectionConfig(),
            display=DisplayConfig(),
            output=OutputConfig(),
            performance=PerformanceConfig(),
        )


# 预设配置

def get_rv1126_config() -> SystemConfig:
    """RV1126 开发板推荐配置"""
    config = SystemConfig.create_default()
    config.camera.device_id = "/dev/video52"
    config.detection.num_threads = 8
    config.performance.inference_timeout = 10.0
    return config


def get_raspberry_pi_config() -> SystemConfig:
    """树莓派低功耗配置"""
    config = SystemConfig.create_default()
    config.camera.fps = 15
    config.detection.num_threads = 2
    config.detection.enable_async = False
    config.performance.max_frame_queue_size = 2
    return config


def get_high_performance_config() -> SystemConfig:
    """高性能配置"""
    config = SystemConfig.create_default()
    config.detection.num_threads = 16
    config.performance.max_frame_queue_size = 30
    config.output.save_video = False
    return config


def get_debug_config() -> SystemConfig:
    """调试配置"""
    config = SystemConfig.create_default()
    config.detection.enable_async = False
    config.display.display_fps = True
    config.display.display_detections = True
    config.performance.enable_profiling = True
    return config


# 使用示例
if __name__ == '__main__':
    # 创建默认配置
    config = SystemConfig.create_default()
    print("Default config:")
    print(json.dumps(config.to_dict(), indent=2))
    
    # 保存配置
    config.save_to_file('config.json')
    print("\nConfig saved to config.json")
    
    # 加载配置
    loaded_config = SystemConfig.load_from_file('config.json')
    print("Config loaded successfully")
    
    # 使用预设配置
    rv1126_config = get_rv1126_config()
    print("\nRV1126 config:")
    print(json.dumps(rv1126_config.to_dict(), indent=2))
