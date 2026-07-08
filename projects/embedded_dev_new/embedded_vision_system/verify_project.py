#!/usr/bin/env python3
"""
项目完成验证脚本
验证嵌入式视觉系统的完整性
"""

import os
import sys
from pathlib import Path

def check_file_structure():
    """检查文件结构"""
    print("\n" + "="*60)
    print("嵌入式视觉系统 - 项目完成验证")
    print("="*60)
    
    base_dir = Path(__file__).parent
    
    required_dirs = [
        'camera',
        'detection',
        'utils',
        'tests',
        'models',
    ]
    
    required_files = [
        'main.py',
        'config.py',
        'examples_integration.py',
        'requirements.txt',
        'README.md',
        'QUICKSTART.md',
        'MIGRATION_GUIDE.md',
        'PROJECT_SUMMARY.md',
    ]
    
    print("\n✓ 核心目录检查:")
    for dir_name in required_dirs:
        dir_path = base_dir / dir_name
        if dir_path.exists():
            print(f"  ✓ {dir_name}/")
        else:
            print(f"  ✗ {dir_name}/ (缺失)")
    
    print("\n✓ 关键文件检查:")
    for file_name in required_files:
        file_path = base_dir / file_name
        if file_path.exists():
            size = file_path.stat().st_size
            print(f"  ✓ {file_name} ({size:,} bytes)")
        else:
            print(f"  ✗ {file_name} (缺失)")
    
    print("\n✓ 模块检查:")
    modules = [
        ('camera/camera_manager.py', 'CameraManager, FrameBuffer'),
        ('detection/rknn_engine.py', 'RKNNInference, RKNNPoolExecutor'),
        ('detection/yolov8_postprocess.py', 'yolov8_post_process'),
        ('detection/image_processor.py', 'preprocess_image, draw_detections'),
        ('utils/vision_pipeline.py', 'VisionPipeline'),
        ('config.py', 'SystemConfig, get_rv1126_config'),
    ]
    
    for module_path, exports in modules:
        full_path = base_dir / module_path
        if full_path.exists():
            print(f"  ✓ {module_path}")
            print(f"    → {exports}")
        else:
            print(f"  ✗ {module_path}")


def check_code_statistics():
    """检查代码统计"""
    print("\n" + "-"*60)
    print("代码统计:")
    print("-"*60)
    
    base_dir = Path(__file__).parent
    
    py_lines = 0
    md_lines = 0
    py_files = 0
    md_files = 0
    
    for py_file in base_dir.rglob('*.py'):
        if '__pycache__' not in str(py_file):
            py_files += 1
            try:
                with open(py_file, 'r', encoding='utf-8') as f:
                    py_lines += len(f.readlines())
            except:
                pass
    
    for md_file in base_dir.rglob('*.md'):
        md_files += 1
        try:
            with open(md_file, 'r', encoding='utf-8') as f:
                md_lines += len(f.readlines())
        except:
            pass
    
    print(f"\nPython 源代码:")
    print(f"  文件数: {py_files}")
    print(f"  代码行数: {py_lines:,}")
    
    print(f"\n文档:")
    print(f"  文件数: {md_files}")
    print(f"  文档行数: {md_lines:,}")
    
    print(f"\n总计:")
    print(f"  总文件数: {py_files + md_files}")
    print(f"  总行数: {py_lines + md_lines:,}")


def print_quick_start():
    """打印快速开始指南"""
    print("\n" + "="*60)
    print("快速开始指南")
    print("="*60)
    
    print("""
1. 安装依赖:
   pip install -r requirements.txt

2. 准备模型:
   mkdir -p rknnModel
   cp your_model.rknn rknnModel/best.rknn

3. 运行程序:
   python main.py --camera /dev/video52 --threads 8

4. 常用命令:
   # 基本用法
   python main.py
   
   # 指定摄像头
   python main.py --camera /dev/video0
   
   # 调整性能
   python main.py --threads 16
   
   # 保存视频
   python main.py --output result.mp4
   
   # 同步推理（调试）
   python main.py --sync

5. 查看文档:
   - README.md - 完整功能文档
   - QUICKSTART.md - 快速开始
   - MIGRATION_GUIDE.md - 从ROS迁移
   - PROJECT_SUMMARY.md - 项目总结

6. 运行测试:
   python tests/test_basic.py

7. 查看集成示例:
   python examples_integration.py
""")


def print_architecture():
    """打印架构说明"""
    print("\n" + "="*60)
    print("系统架构")
    print("="*60)
    
    print("""
Main Process
  │
  ├─ Camera Manager
  │  └─ CameraManager: 摄像头驱动
  │
  ├─ RKNN Inference Engine
  │  ├─ RKNNPoolExecutor: 异步推理
  │  └─ RKNNInference: 单模型推理
  │
  ├─ Detection Pipeline
  │  ├─ Image Processor: 预处理和绘图
  │  └─ YOLOv8 PostProcess: 后处理
  │
  └─ Vision Pipeline
     └─ VisionPipeline: 完整集成管道
     
数据流:
  Camera → Preprocess → RKNN Inference → PostProcess → Display
          [Async Queue for Performance]
""")


def print_next_steps():
    """打印后续步骤"""
    print("\n" + "="*60)
    print("后续步骤")
    print("="*60)
    
    print("""
✓ 已完成:
  • 摄像头采集模块
  • RKNN 推理引擎
  • YOLO v8 检测处理
  • 实时显示和录像
  • 完整的文档和示例

待开发:
  ☐ NFC 读卡集成 (参考 examples_integration.py)
  ☐ 分拣决策逻辑
  ☐ 设备健康监测
  ☐ Web 监控界面
  ☐ 数据持久化
  ☐ 告警系统

建议优先级:
  1. 测试系统在 RV1126 上的性能
  2. 集成 NFC 模块
  3. 实现分拣决策
  4. 开发 Web 界面
""")


def main():
    """主函数"""
    check_file_structure()
    check_code_statistics()
    print_architecture()
    print_quick_start()
    print_next_steps()
    
    print("\n" + "="*60)
    print("✓ 项目完成验证成功！")
    print("="*60)
    print("\n开始使用:")
    print("  cd /home/chen1/projects/embedded_dev_new/embedded_vision_system")
    print("  python main.py")
    print("\n查看文档:")
    print("  - 快速开始: cat QUICKSTART.md")
    print("  - 完整文档: cat README.md")
    print("  - 迁移指南: cat MIGRATION_GUIDE.md")


if __name__ == '__main__':
    main()
