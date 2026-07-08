# 快速开始指南

本指南将帮助你在 5 分钟内启动嵌入式视觉系统。

## 前置条件

- RV1126 开发板（或支持 RKNN 的其他设备）
- Python 3.7+
- RKNN 模型文件 (`.rknn`)

## 1. 准备模型文件

```bash
# 创建模型目录
mkdir -p ~/embedded_dev_new/embedded_vision_system/rknnModel

# 将你的 RKNN 模型复制到此目录
cp your_model.rknn ~/embedded_dev_new/embedded_vision_system/rknnModel/best.rknn
```

## 2. 安装依赖

```bash
cd ~/embedded_dev_new/embedded_vision_system

# 安装 Python 包
pip install -r requirements.txt

# 如果还没有安装 rknnlite，请参考 RV1126 官方文档
```

## 3. 运行程序

### 基本用法

```bash
cd ~/embedded_dev_new/embedded_vision_system

# 使用默认参数运行
python main.py

# 按 'q' 键退出
```

### 常用命令

```bash
# 使用特定摄像头
python main.py --camera /dev/video0

# 调整推理线程数（提高性能）
python main.py --threads 16

# 使用同步推理（调试用）
python main.py --sync

# 保存输出视频
python main.py --output result.mp4

# 组合选项
python main.py --camera /dev/video0 --threads 8 --output result.mp4
```

## 4. 查看输出

程序会在窗口中显示：
- 实时摄像头画面
- 检测框（紫色）
- 框的四个角（绿色）
- 类别标签和置信度
- 帧率和检测数量

## 5. 性能监控

程序每 30 帧输出一次统计信息：

```
[Frame 150] FPS: 23.5, Detections: 45, Inference: 45.2ms
[Frame 180] FPS: 24.1, Detections: 48, Inference: 44.8ms
```

**关键指标**：
- **FPS**: 帧率（越高越好）
- **Detections**: 每帧检测物体数
- **Inference**: 推理时间（越短越好）

## 6. 故障排除

### 摄像头无法打开

```bash
# 查看可用的摄像头
ls -la /dev/video*

# 尝试其他摄像头
python main.py --camera /dev/video0
python main.py --camera 0  # 直接使用索引
```

### 模型加载失败

```bash
# 检查模型文件
ls -la rknnModel/

# 验证文件大小（通常 > 10 MB）
file rknnModel/best.rknn

# 确保 rknnlite 已安装
python -c "from rknnlite.api import RKNNLite; print('OK')"
```

### 帧率过低

```bash
# 增加推理线程数
python main.py --threads 16

# 检查系统负载
top

# 尝试同步推理（诊断用）
python main.py --sync
```

## 7. 高级用法

### 在代码中使用

```python
from embedded_vision_system import VisionPipeline
import cv2

# 初始化管道
pipeline = VisionPipeline(
    model_path='./rknnModel/best.rknn',
    camera_id='/dev/video52',
    num_inference_threads=8,
    enable_async=True
)

try:
    while True:
        # 处理一帧
        result = pipeline.process_frame()
        
        if result['success']:
            frame = result['frame']
            boxes = result['boxes']
            classes = result['classes']
            scores = result['scores']
            
            # 显示
            cv2.imshow('Detection', frame)
            
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
finally:
    cv2.destroyAllWindows()
    pipeline.release()
```

### 获取检测结果

```python
from examples_integration import DetectionResult

# 创建检测结果对象
result = DetectionResult(boxes, classes, scores, frame_id=1)

# 获取所有检测
for det in result.detections:
    print(f"{det['class_name']}: {det['confidence']:.2%}")

# 按置信度排序
top_5 = result.get_top_detections(5)

# 按类别过滤
people = result.filter_by_class(['person'])

# 转换为 JSON
import json
print(json.dumps(result.to_dict(), indent=2))
```

## 8. 测试系统

```bash
# 运行单元测试
cd ~/embedded_dev_new/embedded_vision_system
python tests/test_basic.py

# 运行集成示例
python examples_integration.py
```

## 9. 下一步

- 📖 阅读 [README.md](README.md) 了解更多功能
- 🔧 查看 [MIGRATION_GUIDE.md](MIGRATION_GUIDE.md) 了解从 ROS 的迁移
- 🚀 参考 [examples_integration.py](examples_integration.py) 集成其他模块
- 📝 查看 [API 文档](README.md#api-使用示例)

## 常见配置

### 低功耗模式（Raspberry Pi 等）

```bash
python main.py --threads 2 --sync
```

### 高性能模式（多核处理器）

```bash
python main.py --threads 16 --camera /dev/video0
```

### 视频保存模式

```bash
python main.py --output detection_result.mp4 --threads 8
```

### 开发调试模式

```bash
# 启用详细日志
export LOG_LEVEL=DEBUG
python main.py --sync
```

## 快速检查清单

- [ ] 模型文件在 `rknnModel/best.rknn`
- [ ] 依赖已安装: `pip install -r requirements.txt`
- [ ] 摄像头已连接: `ls /dev/video*`
- [ ] 可以运行: `python main.py`
- [ ] 看到实时画面和检测框
- [ ] FPS > 15
- [ ] 按 'q' 可以退出

## 获取帮助

1. **查看日志**: 程序会输出详细的日志信息
2. **运行测试**: `python tests/test_basic.py`
3. **检查配置**: 确保摄像头和模型路径正确
4. **查看源代码**: 代码中有详细的注释

## 下一阶段

### 集成 NFC

```python
from examples_integration import NFC_MockReader

nfc = NFC_MockReader()
material_info = nfc.get_material_info('MAT001')
```

### 集成分拣逻辑

```python
from examples_integration import SortingDecisionEngine

engine = SortingDecisionEngine()
decision = engine.make_decision(detection_result, nfc_id, order_params)
```

### 集成 Web 服务

参考 [README.md](README.md#与-web-服务集成)

---

**更多问题？** 查看 [README.md](README.md) 中的故障排除部分。
