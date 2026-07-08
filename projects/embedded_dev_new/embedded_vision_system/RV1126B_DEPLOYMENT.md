# RV1126B 部署与板端联调说明

本文档面向当前 `embedded_vision_system` 的非 ROS 版本，目标是在 `RV1126B` 开发板上完成首版赛题闭环联调。

## 1. 当前建议的板端进程划分

首版建议在板端保留 2 个 Python 入口：

1. `web_api.py`
- 提供监控查询、启停复位接口

2. 你的主处理循环脚本
- 负责摄像头采集、NFC 读卡、视觉推理、调用 `SortingSystem.process_material()`

说明：
- `SortingSystem` 已经把 NFC/视觉一致性判定、异常优先级、健康监测、历史记录串起来了
- `BoardSortingRuntime` 负责“识别到物体后停带、调用 `process_material()`、再根据 `decision.route` 恢复跑带或触发舵机”
- 你后面只需要把真实 `NFC/GPIO/ADC/RKNN` 接口替换进去
- 如果 `web_api.py` 和主处理循环分成两个进程，建议它们共用同一个状态文件路径
- 现在 `basic_function_tests` 和完整系统都会共用 `hardware/` 目录下的底层硬件模块

## 2. 建议拷贝到板端的目录

至少拷贝以下内容到板端，例如 `/userdata/embedded_vision_system/`：

```text
embedded_vision_system/
  __init__.py
  basic_function_tests/
  hardware/
  consistency_engine.py
  device_controller.py
  sorting_system.py
  web_api.py
  config.py
  camera/
  detection/
  utils/
  requirements.txt
  RV1126B_DEPLOYMENT.md
```

如果你已经有 RKNN 模型，再额外准备：

```text
rknnModel/best.rknn
```

## 3. 从当前 WSL 拷到开发板

如果板机开启了 `ssh/scp`，最省事的方式是：

```bash
ssh dev@10.100.57.145
scp -r embedded_vision_system dev@10.100.57.145:/userdata/
scp -r rknnModel dev@10.100.57.145:/userdata/
```

如果板机没有网络：

1. 在 WSL 下把目录打包
2. 拷到 U 盘或共享目录
3. 在板机上解压

打包命令示例：

```bash
tar czf embedded_vision_system.tar.gz embedded_vision_system
```

## 4. 板端 Python 环境建议

先确认板端 Python 版本：

```bash
python3 --version
```

建议准备一个独立目录后执行：

```bash
cd /userdata/embedded_vision_system
pip3 install -r requirements.txt
```

注意：
- 安装依赖时进入 `/userdata/embedded_vision_system` 没问题
- 但运行 `python3 -m embedded_vision_system...` 这类模块命令时，应站在它的上一级目录 `/userdata`

如果你准备让 Web API 和主处理循环共享订单/历史状态，且希望运行数据固定落在 TF 卡，建议统一设置：

```bash
export EMBEDDED_VISION_DATA_ROOT=/run/media/mmcblk1p1/embedded_vision_data
export EMBEDDED_VISION_STATE_PATH=/run/media/mmcblk1p1/embedded_vision_data/runtime_data/orders_state.json
```

说明：
- 代码目录可以继续放在 `/userdata/embedded_vision_system`
- 运行期数据（状态文件、截图、视频、抓拍）建议统一放在 TF 卡挂载目录 `/run/media/mmcblk1p1/embedded_vision_data`
- 按教程手册，TF 卡挂载点为 `/run/media/mmcblk1p1`
- 若未检测到 TF 卡挂载点，程序会直接拒绝启动，不再回退到其他目录

注意：
- `opencv-python` 在部分板端环境直接 `pip` 可能较重，若官方 rootfs 已带 OpenCV Python 绑定，优先复用系统版本
- `rknnlite` 或 Rockchip 提供的 RKNN Runtime 通常要按开发板官方镜像/SDK 安装，不建议在 WSL 上准备

## 5. 真实硬件替换点

### 5.1 NFC 读卡

当前默认使用：

```python
sorting_system.nfc_reader = NFC_Reader_Mock()
```

板端需要替换成你的真实类，至少提供：

```python
class RealNFCReader:
    def read(self) -> dict:
        return {
            "success": True,
            "material_id": "MAT001"
        }
```

### 5.2 舵机/传送带/GPIO

当前 `device_controller.py` 是模拟实现，建议你在 RV1126B 上：

1. 保留 `DeviceController` 业务层
2. 替换 `ServoController` 内部的 `set_angle()`
3. 替换 `ConveyorBelt.start()/stop()/set_speed()`

如果你已经有底层驱动库，可以直接在这几个方法里改成真实调用。

### 5.3 电流/振动采样

当前传感器类提供了健康等级逻辑，你只需要把 `read()` 的随机值替换成真实采样值：

```python
value = your_adc_read()
return SensorReading(sensor_type="current", value=float(value))
```

### 5.4 自检

`DeviceController` 支持注册真实自检回调：

```python
system.device_controller.set_component_check("nfc", your_nfc_check)
system.device_controller.set_component_check("network", your_network_check)
```

回调返回格式：

```python
ComponentCheck(ok=True, message="NFC 模块在线")
```

## 6. 建议的板端联调顺序

### 第一步：只通 Web 和订单流

先启动：

```bash
cd /userdata
python3 -m embedded_vision_system.web_api
```

然后在局域网浏览器或 Postman 里验证：

1. `POST /api/control/start`
2. `POST /api/control/stop`
3. `GET /api/dashboard`
4. `GET /api/status`

这样可以先确认“设备启停 + 看板查询 + 状态查询”通路正常。

在接主流程前，建议先跑一遍基础功能测试目录：

```bash
cd /userdata
python3 -m embedded_vision_system.basic_function_tests.run_all_basic_checks
```

### 第二步：接通真实 NFC

目标：
- 能稳定拿到 `material_id`
- NFC 失败时能进入 `检测异常`

建议先单独打印 `read()` 结果，不要一上来就和视觉一起联。

### 第三步：接通摄像头 + RKNN

先单跑你原有的视觉主循环，确认：

1. 摄像头可打开
2. RKNN 模型能加载
3. 输出的 `vision_result` 字段为：

```json
{
  "success": true,
  "material_type": "塑料块",
  "color": "红色",
  "confidence": 0.91
}
```

重点：
- 现在系统内部已经统一使用中文字段值
- 不要再返回 `plastic/box/red/blue` 这种英文业务值

### 第四步：接通分拣机构

先做一个最小动作验证：

1. 手动调用 `execute_sort()`
2. 确认舵机拨料
3. 确认复位
4. 再把它接回 `BoardSortingRuntime` 对 `process_material()` 决策结果的执行逻辑

### 第五步：接通健康监测

建议联调顺序：

1. 先验证绿色常态
2. 人为抬高阈值模拟黄色告警
3. 再模拟红色故障，确认系统自动停机并需要手动复位

## 7. 板端最小验证清单

验收首版时，建议至少验证下面 8 条：

1. 上电后默认待机，未启动前传送带不运行
2. 自检失败时无法启动，并能看到失败原因
3. NFC 文本可解析 + 视觉匹配时，物料放行
4. 无标签或读卡失败时，物料进入异常区
5. NFC 文本无法解析出颜色/形状/类型时，物料拨到侧边区并状态为 `待人工处理`
6. 类型或颜色不一致时，物料拨到异常区
7. 低置信度或视觉失败时，物料拨到侧边区并等待人工处理
8. 振动/电流触发红色故障时，设备立即停机

## 8. 你接下来最可能要改的两个文件

如果你准备开始接真实板端外设，优先改：

1. `embedded_vision_system/device_controller.py`
- 接 GPIO/PWM/ADC/停机保护

2. `embedded_vision_system/detection/vision_classifier.py`
- 根据你的真实训练类别，替换 `COCO_TO_MATERIAL_TYPE`

如果你要我下一步继续帮你，我建议直接做这两件事之一：

1. 把你的 `RV1126B` 真实外设接口名告诉我，我继续替你把 `device_controller.py` 改成可直接上板的版本
2. 把你的模型真实类别列表告诉我，我把 `vision_classifier.py` 的映射规则改成最终赛题版
