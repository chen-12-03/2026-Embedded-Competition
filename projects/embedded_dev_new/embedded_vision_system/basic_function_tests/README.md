# 基础功能测试目录

这个目录用于做“分模块、可单独运行”的基础功能验证，不依赖完整主流程。

默认情况下，测试产生的截图等文件会优先写入 TF 卡挂载目录：

```text
/run/media/mmcblk1p1/embedded_vision_data/
```

适合你当前这个阶段：

1. 先分别验证摄像头、模型、NFC、PWM 是否单独可用
2. 再把这些模块接回 `SortingSystem`
3. 最后做整链路联调

## 目录说明

```text
basic_function_tests/
├── __init__.py
├── README.md
├── hardware_backends.py         # NFC/PWM 测试后端封装
├── test_camera_preview.py       # 摄像头显示回传测试
├── test_camera_preview_web.py   # 摄像头网页预览测试
├── test_camera_classification.py# 摄像头分类测试
├── test_camera_shape_color.py   # 摄像头颜色+形状识别测试
├── test_camera_shape_color_web.py # 摄像头颜色+形状网页识别测试
├── test_nfc_reader.py           # NFC 读卡测试
├── test_mpu6050.py              # MPU6050 加速度/振动测试
├── test_pwm_control.py          # PWM/舵机/占空比测试
└── run_all_basic_checks.py      # 推荐测试顺序说明
```

## 推荐运行方式

在项目根目录执行。

板机上如果目录放在 `/userdata/embedded_vision_system`，这里的“项目根目录”指的是：

```bash
cd /userdata
```

然后再执行：

```bash
python3 -m embedded_vision_system.basic_function_tests.run_all_basic_checks
```

## 1. 摄像头显示回传

```bash
python3 -m embedded_vision_system.basic_function_tests.test_camera_preview \
  --camera /dev/video0
```

常用参数：

```bash
--headless                 # 无窗口模式
--max-frames 300           # 只跑 300 帧
--save-dir ./test_outputs  # 截图输出目录
```

如果板机没有显示器，推荐直接跑网页预览：

```bash
cd /userdata
python3 -m embedded_vision_system.basic_function_tests.test_camera_preview_web \
  --camera /dev/video52 \
  --camera-fps 30 \
  --fps 15 \
  --width 640 \
  --height 480 \
  --camera-format YUYV \
  --jpeg-quality 60 \
  --opencv-threads 2 \
  --host 0.0.0.0 \
  --port 8081
```

然后在你的电脑浏览器访问：

```text
http://10.100.57.145:8081
```

网页使用 `/snapshot` 串行拉取最新 JPEG，不使用可能积压旧帧的 MJPEG
长连接。运行状态可在 `http://10.100.57.145:8081/status` 查看。

## 2. 摄像头颜色 + 形状识别

如果你当前优先验证“木质件 + 红黄蓝绿紫 + 正方形/长方形/三角形/圆锥形”，推荐先跑这个，不依赖 RKNN：

```bash
python3 -m embedded_vision_system.basic_function_tests.test_camera_shape_color \
  --camera /dev/video52
```

常用参数：

```bash
--headless
--max-frames 300
--min-area 2500
```

说明：
- 当前使用的是 `detection/shape_color_classifier.py`
- 识别逻辑为 `HSV 颜色掩膜 + 轮廓几何判断`
- 更适合你现在这批受控样品做快速打通

如果板机没有显示器，推荐直接跑网页版：

```bash
python3 -m embedded_vision_system.basic_function_tests.test_camera_shape_color_web \
  --camera /dev/video52 \
  --camera-fps 30 \
  --fps 8 \
  --width 640 \
  --height 480 \
  --camera-format YUYV \
  --jpeg-quality 60 \
  --min-area 500 \
  --max-contours 8 \
  --opencv-threads 2 \
  --host 0.0.0.0 \
  --port 8082
```

然后在你的电脑浏览器访问：

```text
http://10.100.57.145:8082
```

画面底部的 `CV` 是当帧缩放和识别耗时，`Age` 是识别完成时该采集帧的年龄，
`RSS` 是当前进程内存，`Free` 是系统可用内存。
状态可在 `http://10.100.57.145:8082/status` 查看。
摄像头默认优先使用 GStreamer 丢帧型 `appsink`，OpenCV 未编译 GStreamer 时会自动回退到
V4L2；可使用 `--no-gstreamer` 强制验证 V4L2 路径。

间歇性卡顿时重点查看：

- `processing_p95_ms`：最近处理耗时的 95 分位值
- `camera.backend`：当前使用 `gstreamer` 还是 `v4l2`
- `camera.capture_fps`：摄像头实际采集帧率
- `camera.failed_reads`：累计读帧失败数
- `camera.reconnect_count`：摄像头自动重连次数
- `temperature_c`：板机可用的最高温度传感器读数

## 3. 摄像头分类

```bash
python3 -m embedded_vision_system.basic_function_tests.test_camera_classification \
  --model ./rknnModel/best.rknn \
  --camera /dev/video0
```

说明：
- 这个测试需要摄像头和 RKNN 模型都正常
- 会在画面上叠加分类结果
- 当前使用的是 `detection/vision_classifier.py` 里的物料规则

## 4. NFC 读取

### mock 模式

```bash
python3 -m embedded_vision_system.basic_function_tests.test_nfc_reader \
  --backend mock \
  --material-ids MAT001 MAT002 MAT003
```

### file 模式

```bash
python3 -m embedded_vision_system.basic_function_tests.test_nfc_reader \
  --backend file \
  --file-path /tmp/nfc_result.txt
```

### command 模式

如果板端已经有现成读卡 demo，例如：

```bash
python3 -m embedded_vision_system.basic_function_tests.test_nfc_reader \
  --backend command \
  --command "/userdata/nfc_demo/read_once"
```

外部命令输出支持：

1. 纯文本：

```text
MAT001
```

2. JSON：

```json
{"success": true, "material_id": "MAT001"}
```

### pn532_i2c 模式

适合 PN532 模块切到 `I2C` 拨码后直接挂到 Linux `i2c-X` 总线：

```bash
python3 -m embedded_vision_system.basic_function_tests.test_nfc_reader \
  --backend pn532_i2c \
  --i2c-bus 1 \
  --i2c-address 0x24 \
  --pin-sda GPIO_I2C1_SDA \
  --pin-scl GPIO_I2C1_SCL \
  --pin-irq GPIO3_A4 \
  --pin-rstpdn GPIO3_A5
```

接线关系：
- `PN532 VCC -> 3V3`
- `PN532 GND -> GND`
- `PN532 SDA -> 板端 I2C SDA`
- `PN532 SCL -> 板端 I2C SCL`
- `PN532 IRQ -> 可选中断 GPIO`
- `PN532 RSTPDN -> 可选复位 GPIO`

### pn532_spi 模式

适合 PN532 模块切到 `SPI` 拨码，通过 `spidev` 访问：

```bash
python3 -m embedded_vision_system.basic_function_tests.test_nfc_reader \
  --backend pn532_spi \
  --spi-bus 0 \
  --spi-device 0 \
  --spi-speed-hz 1000000 \
  --pin-mosi GPIO_SPI0_MOSI \
  --pin-miso GPIO_SPI0_MISO \
  --pin-sck GPIO_SPI0_CLK \
  --pin-cs GPIO_SPI0_CS0 \
  --pin-irq GPIO3_A4 \
  --pin-rstpdn GPIO3_A5
```

接线关系：
- `PN532 VCC -> 3V3`
- `PN532 GND -> GND`
- `PN532 MOSI -> 板端 SPI MOSI`
- `PN532 MISO -> 板端 SPI MISO`
- `PN532 SCK -> 板端 SPI CLK`
- `PN532 SS/NSS -> 板端 SPI CS`
- `PN532 IRQ -> 可选中断 GPIO`
- `PN532 RSTPDN -> 可选复位 GPIO`

### pn532_uart 模式

适合 PN532 模块切到 `HSU/UART` 拨码，通过板机串口访问：

```bash
python3 -m embedded_vision_system.basic_function_tests.test_nfc_reader \
  --backend pn532_uart \
  --uart-port /dev/ttyS3 \
  --uart-baudrate 115200 \
  --pin-tx UART3_TX \
  --pin-rx UART3_RX \
  --pin-rstpdn GPIO3_A5
```

接线关系：
- `PN532 VCC -> 3V3`
- `PN532 GND -> GND`
- `PN532 TXD -> 板端 UART RX`
- `PN532 RXD -> 板端 UART TX`
- `PN532 RSTPDN -> 可选复位 GPIO`

说明：
- `UART` 常常比 `I2C` 更适合板机快速联调，因为不依赖 `I2C` 引脚复用
- `TX/RX` 要交叉连接，不要同名直连
- 默认波特率按 `PN532 HSU` 常见配置使用 `115200`
- `【MK002902】PN532/nfc/PN532_ Manual_V3.pdf` 标明 `V3` 板默认模式就是 `HSU`
- 同一份手册里给出的拨码关系是：`HSU=CH1 OFF, CH2 OFF`，`I2C=CH1 ON, CH2 OFF`，`SPI=CH1 OFF, CH2 ON`

说明：
- 当前实现按 `PN532` 协议读卡，并尝试从标签载荷里提取 `material_id`
- 初始化顺序按 `Elechouse` 官方示例执行：`get_version() -> SAMConfiguration() -> InListPassiveTarget()`
- 对 `4-byte UID` 的 Mifare Classic 卡，会优先按官方示例流程做 `KeyA(FF..FF)` 认证，再读 `block 4/5/6/7`
- 若标签里暂时没有文本载荷，可默认回退为卡 UID 作为 `material_id`
- 板端需要安装 `smbus2`、`spidev` 或 `pyserial`

## 5. MPU6050 振动/姿态读取

适合 MPU6050 模块直接挂到 Linux `i2c-X` 总线：

```bash
python3 -m embedded_vision_system.basic_function_tests.test_mpu6050 \
  --i2c-bus 1 \
  --i2c-address 0x68 \
  --count 20 \
  --interval 0.2
```

常用地址：

- `0x68`：AD0 接低电平或悬空时常见
- `0x69`：AD0 接高电平时常见

接线关系：

- `MPU6050 VCC -> 3V3`
- `MPU6050 GND -> GND`
- `MPU6050 SDA -> 板端 I2C SDA`
- `MPU6050 SCL -> 板端 I2C SCL`
- `MPU6050 AD0 -> GND` 可固定地址为 `0x68`

说明：

- 板端需要安装 `smbus2`
- `WHO_AM_I` 正常通常返回 `0x68` 或 `0x69`
- `vibration` 当前按三轴加速度模长偏离 `1g` 计算，适合作为设备振动健康监测的首版输入

## 6. PWM 控制

## 6. STM32 UART 控制

如果舵机和步进电机已经改为由 `STM32` 下位机输出，可先单独测试 UART 协议链路：

### 只查当前状态

```bash
python3 -m embedded_vision_system.basic_function_tests.test_stm32_uart \
  --port /dev/ttyS5 \
  --status-only
```

### 设置舵机角度

```bash
python3 -m embedded_vision_system.basic_function_tests.test_stm32_uart \
  --port /dev/ttyS5 \
  --servo-angle 45
```

注意：

- 下位机协议当前上电默认就是 `SERVO=90`
- 如果你发的还是 `--servo-angle 90`，串口虽然成功，但舵机不会产生可见位移

### 设置步进频率并使能，保持 3 秒后停止

```bash
python3 -m embedded_vision_system.basic_function_tests.test_stm32_uart \
  --port /dev/ttyS5 \
  --step-hz 100 \
  --enable 1 \
  --hold 3 \
  --stop
```

### 一次同时设置舵机、步进、电机使能

```bash
python3 -m embedded_vision_system.basic_function_tests.test_stm32_uart \
  --port /dev/ttyS5 \
  --servo-angle 45 \
  --step-hz 100 \
  --enable 1 \
  --hold 2 \
  --stop
```

说明：

- 默认波特率是 `115200`
- 当前板机默认串口是 `/dev/ttyS5`
- 当前板机暂定全速步进频率是 `100Hz`
- 当前经验标定是 `100Hz` 连续运行 `10s` 约等于传送带半程
- 输出顺序会先查 `initial_status`，再执行控制，最后查 `final_status`
- 如果下位机返回 `ERR ...`，脚本会直接抛出错误，便于定位协议或参数问题

## 7. PWM 控制

### mock 模式

```bash
python3 -m embedded_vision_system.basic_function_tests.test_pwm_control \
  --backend mock \
  --mode both
```

### sysfs 模式

```bash
python3 -m embedded_vision_system.basic_function_tests.test_pwm_control \
  --backend sysfs \
  --chip 0 \
  --channel 0 \
  --mode servo
```

说明：
- `sysfs` 模式适合 `/sys/class/pwm/pwmchipX` 可用的 Linux 板端
- 如果你的 RV1126B 不是这套接口，只需要保留测试脚本，替换 `hardware_backends.py` 里的 PWM backend

## 建议联调顺序

1. 先跑 `test_camera_preview.py`
2. 先跑 `test_camera_shape_color.py`
3. 再跑 `test_camera_classification.py`
4. 再跑 `test_nfc_reader.py`
5. 再跑 `test_mpu6050.py`
6. 再跑 `test_stm32_uart.py`
7. 再跑 `test_pwm_control.py`
8. 最后把真实模块接回主流程

## 最后要改的地方

如果你准备接真实板端外设，优先改：

1. `embedded_vision_system/hardware/`
- 把共享 `NFC/PWM/传感器` 模块替换为你板端真实接口
- 改完后基础测试脚本和完整系统会一起生效

2. `detection/vision_classifier.py`
- 把物料类别映射换成你真实模型的类别集合

3. `detection/shape_color_classifier.py`
- 调整红黄蓝绿的 HSV 阈值
- 调整正方形/长方形的长宽比阈值
- 固定 ROI 后，优先把这个传统识别器调稳
