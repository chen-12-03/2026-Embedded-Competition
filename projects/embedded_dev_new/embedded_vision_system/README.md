# 嵌入式视觉系统 (Embedded Vision System)

基于 RV1126 开发板的独立原材料分拣系统，使用 RKNN 加速推理框架，并补齐了订单、比对、分拣、健康监测和轻量 Web API。

## 核心特性

- ✅ **无 ROS 依赖** - 独立运行，不需要 ROS 环境
- ✅ **YOLO v8 检测** - 使用 RKNN 加速的 YOLOv8 目标检测
- ✅ **异步推理** - 线程池并行处理，提高帧率
- ✅ **实时处理** - 支持实时摄像头输入
- ✅ **订单/NFC/视觉一致性比对** - 对齐赛题闭环
- ✅ **设备健康监测** - 支持绿/黄/红三级告警和红色停机保护
- ✅ **轻量 Web API** - 支持录单、监控查询、启停和复位
- ✅ **共享硬件层** - 基础测试与完整系统共用底层 NFC/PWM/传感器代码
- ✅ **可扩展架构** - 易于替换为真实 NFC、GPIO、ADC 模块

## 项目结构

```
embedded_vision_system/
├── camera/                      # 摄像头管理模块
│   ├── __init__.py
│   └── camera_manager.py        # 摄像头管理类
├── detection/                   # 目标检测模块
│   ├── __init__.py
│   ├── rknn_engine.py          # RKNN 推理引擎
│   ├── yolov8_postprocess.py   # YOLO 后处理
│   └── image_processor.py      # 图像处理工具
├── hardware/                    # 共享硬件接口层
├── basic_function_tests/        # 分模块基础功能测试脚本
├── utils/                       # 工具模块
│   ├── __init__.py
│   └── vision_pipeline.py      # 完整的视觉管道
├── tests/                       # 测试模块
├── main.py                      # 主程序
├── web_api.py                   # 轻量 Web API
├── RV1126B_DEPLOYMENT.md        # 板端部署与联调说明
├── requirements.txt             # Python 依赖
└── README.md                    # 本文件
```

## 安装

### 1. 环境要求

- Python 3.7+
- RV1126 开发板（或支持 RKNN 的其他开发板）
- RKNN 库已安装

### 2. 依赖安装

```bash
pip install -r requirements.txt
```

### 3. 模型文件准备

将训练好的 RKNN 模型放在 `rknnModel/` 目录下：

```bash
mkdir -p rknnModel
# 将模型文件复制到此目录
cp your_model.rknn rknnModel/best.rknn
```

## 使用

### 基本用法

```bash
python main.py --model ./rknnModel/best.rknn --camera /dev/video52
```

### 启动 Web API

```bash
python -m embedded_vision_system.web_api
```

默认情况下，运行期数据会优先写入 TF 卡挂载目录 `/run/media/mmcblk1p1/embedded_vision_data`。
如果需要手动指定，可设置：

```bash
export EMBEDDED_VISION_DATA_ROOT=/run/media/mmcblk1p1/embedded_vision_data
```

注意：
- 程序现在要求 TF 卡已经挂载
- 若未检测到 `/run/media/mmcblk*`，系统会直接拒绝启动，不再回退到 `/tmp` 或其他目录

### 运行基础功能测试

```bash
python -m embedded_vision_system.basic_function_tests.run_all_basic_checks
```

### 命令行参数

| 参数 | 默认值 | 说明 |
|-----|-------|------|
| `--model` | `./rknnModel/best.rknn` | RKNN 模型文件路径 |
| `--camera` | `/dev/video52` | 摄像头设备路径 |
| `--threads` | `8` | 推理线程数 |
| `--sync` | 无 | 使用同步推理（默认异步） |
| `--output` | 无 | 保存输出视频文件路径 |

### 示例

#### 异步推理（推荐用于实时处理）
```bash
python main.py --camera /dev/video0 --threads 8
```

#### 同步推理（单线程）
```bash
python main.py --camera /dev/video0 --sync
```

#### 保存检测结果视频
```bash
python main.py --camera /dev/video0 --output output.mp4
```

说明：
- `--output output.mp4` 这类相对路径会自动保存到统一数据目录下的 `videos/`
- 在板机插好 TF 卡时，实际路径会落到 `/run/media/mmcblk1p1/embedded_vision_data/videos/`

## API 使用示例

### 1. 使用 VisionPipeline

```python
from embedded_vision_system import VisionPipeline

# 初始化管道
with VisionPipeline(
    model_path='./rknnModel/best.rknn',
    camera_id='/dev/video52',
    num_inference_threads=8,
    enable_async=True
) as pipeline:
    
    # 处理帧
    result = pipeline.process_frame()
    
    if result['success']:
        frame = result['frame']
        boxes = result['boxes']
        classes = result['classes']
        scores = result['scores']
        
        # 处理检测结果
        for box, cls, score in zip(boxes, classes, scores):
            print(f"Detected: {CLASSES[cls]} with score {score:.2f}")
```

### 2. 使用 CameraManager

```python
from embedded_vision_system import CameraManager

# 初始化摄像头
with CameraManager(camera_id='/dev/video0') as camera:
    while True:
        ret, frame = camera.read_frame()
        if ret:
            # 处理帧
            pass
        else:
            break
```

### 3. 使用 RKNNPoolExecutor

```python
from embedded_vision_system import RKNNPoolExecutor

# 初始化推理池
pool = RKNNPoolExecutor(
    model_path='./rknnModel/best.rknn',
    num_threads=8
)

# 定义推理函数
def inference_func(rknn_model, image_data):
    outputs = rknn_model.inference(image_data)
    return outputs

# 提交任务
pool.submit_task(image_data, inference_func)

# 获取结果
result, success = pool.get_result()

pool.release()
```

## 检测框架

### 支持的物体类别

系统使用 COCO 数据集的 80 个类别。常见类别包括：

- **交通工具**: car, truck, bus, bicycle, motorbike, train, boat, aeroplane
- **人物**: person
- **动物**: dog, cat, bird, horse, sheep, cow, elephant, bear, zebra, giraffe
- **日用品**: bottle, cup, fork, knife, spoon, bowl, banana, apple, sandwich, orange
- **家具**: chair, sofa, bed, dining table, toilet, potted plant

### 检测配置

编辑 `detection/yolov8_postprocess.py` 中的参数：

```python
OBJ_THRESH = 0.25   # 对象置信度阈值
NMS_THRESH = 0.45   # NMS 阈值
IMG_SIZE = 640      # 输入图像大小
```

## 性能优化

### 1. 异步推理

启用异步推理以获得最佳帧率：

```bash
python main.py --threads 8  # 默认异步
```

### 2. 线程数调整

根据硬件性能调整线程数：

```bash
python main.py --threads 4   # 低功耗设备
python main.py --threads 16  # 高性能设备
```

### 3. 帧率监控

程序每 30 帧输出一次统计信息：

```
[Frame 150] FPS: 23.5, Detections: 45, Inference: 45.2ms
```

## 与其他模块集成

### 与 NFC 读卡模块集成

```python
from embedded_vision_system import VisionPipeline
from nfc_reader import NFCReader  # 你的 NFC 模块

with VisionPipeline(...) as pipeline:
    nfc = NFCReader()
    
    while True:
        # 获取检测结果
        result = pipeline.process_frame()
        boxes = result['boxes']
        
        # 读取 NFC
        nfc_id = nfc.read()
        
        # 比对结果
        compare_results(boxes, nfc_id)
```

### 与 Web 服务集成

```python
from flask import Flask
from embedded_vision_system import VisionPipeline

app = Flask(__name__)
pipeline = VisionPipeline(...)

@app.route('/detect')
def detect():
    result = pipeline.process_frame()
    return {
        'detections': result['boxes'].tolist(),
        'classes': result['classes'].tolist(),
        'scores': result['scores'].tolist()
    }

if __name__ == '__main__':
    app.run(host='0.0.0.0')
```

## 故障排除

### 问题：摄像头无法打开

**症状**: `Failed to open camera`

**解决方案**:
- 检查设备路径: `ls -la /dev/video*`
- 验证权限: `sudo chmod 666 /dev/video*`
- 尝试其他设备: `--camera 0` 或 `--camera 1`

### 问题：RKNN 模型加载失败

**症状**: `Failed to load RKNN model`

**解决方案**:
- 检查模型文件是否存在
- 验证模型格式正确性
- 确认 rknnlite 库已正确安装

### 问题：帧率过低

**症状**: `FPS: 2.5`

**解决方案**:
- 增加推理线程数: `--threads 16`
- 启用异步推理（默认启用）
- 检查系统负载: `top`

## 扩展开发

### 自定义后处理

修改 `detection/yolov8_postprocess.py` 中的 `draw_detections()` 函数:

```python
def draw_detections(image, boxes, scores, classes, ratio, padding):
    # 你的自定义绘图逻辑
    pass
```

### 自定义推理函数

定义你的推理函数并传递给管道:

```python
def my_inference_func(rknn_model, image_data):
    # 自定义推理逻辑
    outputs = rknn_model.inference(image_data)
    return process_outputs(outputs)
```

## 许可证

MIT License

## 联系方式

如有问题，请提交 Issue 或 Pull Request。

## 相关资源

- [RV1126 开发板文档](http://wiki.rockchip.com.cn/display/H6/RV1126+Developer+Guide)
- [RKNN 工具链](https://github.com/rockchip-linux/rknn-toolkit2)
- [YOLOv8 官方文档](https://docs.ultralytics.com/)
