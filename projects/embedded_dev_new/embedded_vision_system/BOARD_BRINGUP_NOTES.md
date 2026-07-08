# 板机联调记录

快速切换新设备时，建议先看 `DEVICE_SWITCH_QUICK_GUIDE.md`。

## 1. NFC

板机可用命令：

```bash
cd /userdata
sudo embedded_vision_system/.venv/bin/python3 -m embedded_vision_system.basic_function_tests.test_nfc_reader \
  --backend pn532_i2c \
  --i2c-bus 4 \
  --i2c-address 0x24 \
  --scan-timeout 3.0 \
  --passive-activation-retries 0x02 \
  --count 5 \
  --interval 0.5 \
  --json
```

当前确认：

- `i2c-0` 作为当前 NFC 接入总线
- `0x24` 地址可用
- `firmware` 读取正常

### 1.1 WebUI 启动时要复用同一组 NFC 参数

`basic_function_tests.test_nfc_reader` 的命令行参数不会自动传给 `web_api.py`。
现在这块板机已经把常用硬件配置固化到代码默认值里，而且 `web_api` 已经直接托管完整主流程，直接启动即可：

```bash
cd /userdata
sudo embedded_vision_system/.venv/bin/python3 -m embedded_vision_system.web_api
```

当前已固化到代码里的板机参数包括：

- 摄像头：`/dev/video52`
- 摄像头采集帧率：`30fps`
- Web 预览帧率：`8fps`
- 实时分类帧率：`6fps`
- 摄像头采集分辨率：`640x480`
- 摄像头像素格式：`MJPG`
- 视觉停带触发：`检测到物体后继续运行 1.0s 再停`
- 防重复停带冷却：`恢复跑带后 3.0s 内不再触发停带`
- NFC：`pn532_i2c`、`I2C bus 4`、地址默认 `0x24`
- NFC 轮询：开启，间隔 `0.5s`
- NFC 持续采样：主流程运行时也保持常开，不再暂停
- NFC 文本锁存：`一旦读到有效文本，会保持到下一次完整判定结束后再释放`
- 判定基准：`系统直接把 NFC 文本解析成颜色/形状/类型，与视觉结果做一致性比对`
- NFC UID 回退：关闭
- 振动传感器：`mpu6050`、`I2C bus 3`、地址 `0x68`
- 振动黄色告警阈值：`0.18g`
- 振动红色告警阈值：`0.35g`
- 振动保护策略：`黄色或红色告警都会立即停机并锁存`
- 当前电流读数仅用于展示，不参与故障停机或锁存判定
- 控制串口：`/dev/ttyS5 @ 115200`
- 上位机停电机策略：`显式发送 STEP=0 + ENABLE=0`，不再只依赖 STOP
- 传送带速度模式：`hz`
- 传送带默认速度：`60`

如果你后面确实要临时覆盖状态文件路径，才额外导出：

```bash
export EMBEDDED_VISION_STATE_PATH=/run/media/mmcblk1p1/embedded_vision_data/runtime_data/orders_state.json
```

### 1.1.1 MPU6050 接线

当前代码默认把 `MPU6050` 作为板机振动异常输入接入完整系统，接线建议如下：

- `MPU6050 VCC -> 3V3`
- `MPU6050 GND -> GND`
- `MPU6050 SDA -> 板端 I2C SDA`
- `MPU6050 SCL -> 板端 I2C SCL`
- `MPU6050 AD0 -> GND`，固定地址为 `0x68`

说明：

- 当前这块板机默认改为：`PN532 -> i2c-4 / 0x24`，`MPU6050 -> i2c-3 / 0x68`
- `MPU6050` 现在不再复用 `PN532` 的那组总线
- 如果后面更换接线，请重新用 `i2cdetect -y 3` / `i2cdetect -y 4` 确认

### 1.2 板机上优先检查的三件事

先确认 WebUI 进程是不是最新代码、是不是带了正确环境变量、是不是和主流程指向同一个共享状态文件：

```bash
cd /userdata
ps -ef | grep -E "embedded_vision_system.web_api|run_board_sorting" | grep -v grep
```

如果已经拿到 `web_api` 进程号，继续看实际工作目录和环境变量：

```bash
WEB_PID=$(ps -ef | grep -E "embedded_vision_system.web_api" | grep -v grep | awk 'NR==1 {print $2}')
readlink -f /proc/$WEB_PID/cwd
tr '\0' '\n' </proc/$WEB_PID/environ | grep '^EMBEDDED_VISION_'
```

重点确认以下环境变量是否真的出现在进程环境里：

- `EMBEDDED_VISION_NFC_BACKEND=pn532_i2c`
- `EMBEDDED_VISION_NFC_I2C_BUS=4`
- `EMBEDDED_VISION_NFC_I2C_ADDRESS=0x24`
- `EMBEDDED_VISION_NFC_FALLBACK_TO_UID=0`
- `EMBEDDED_VISION_STATE_PATH=/run/media/mmcblk1p1/embedded_vision_data/runtime_data/orders_state.json`

注意：

- 如果用 `sudo embedded_vision_system/.venv/bin/python3 ...`，很多板机环境会清掉前面 `export` 的变量
- 启动 `web_api` 时要优先用 `sudo -E ...`

再直接看 WebUI 当前接口实际返回的运行态，而不是只看页面：

```bash
curl -s http://127.0.0.1:8080/api/dashboard | python3 -m json.tool
curl -s http://127.0.0.1:8080/api/nfc/status | python3 -m json.tool
```

重点观察：

- `nfc_runtime.configured_backend`
- `nfc_runtime.fallback_to_uid`
- `nfc_sample.source`
- `nfc_sample.sample.success`
- `nfc_sample.sample.text`
- `nfc_sample.sample.raw.material_id_source`
- `debug.state_path`

如果页面显示 success，但 `curl` 看到的是旧字段或没有 `nfc_runtime.fallback_to_uid` / `nfc_sample.sample.text`，优先怀疑板机实际跑的不是最新代码。

### 1.3 板机单独验证 MPU6050

先单独读 `MPU6050`，确认硬件和总线无误：

```bash
cd /userdata
sudo embedded_vision_system/.venv/bin/python3 -m embedded_vision_system.basic_function_tests.test_mpu6050 \
  --i2c-bus 3 \
  --i2c-address 0x68 \
  --count 20 \
  --interval 0.2 \
  --json
```

正常情况下：

- `WHO_AM_I` 应返回 `0x68` 或 `0x69`
- 静止放置时，`vibration_g` 应接近 `0`
- 明显晃动时，`vibration_g` 会升高

## 2. 视觉

板机可用命令：

```bash
cd /userdata
source /userdata/embedded_vision_system/.venv/bin/activate
python -m embedded_vision_system.basic_function_tests.test_camera_shape_color_web \
  --camera /dev/video52 \
  --host 0.0.0.0 \
  --port 8082
```

## 3. PWM

### 3.1 当前板机状态

板机当前可见：

```bash
ls /sys/class/pwm
```

当前测试结果：

- `pwmchip0`
- `pwmchip1`
- `pwmchip2`

每个 `pwmchip` 当前都只有 `1` 个通道，即 `channel 0`。

### 3.2 当前已确认的 PWM 引脚

通过板机 `pinmux` 已确认：

- `pin 20 (gpio0-20)` -> `20e00000.pwm`
- `pin 22 (gpio0-22)` -> `20e20000.pwm`

按 Rockchip GPIO 编号换算：

- `gpio0-20` = `GPIO0_C4`
- `gpio0-22` = `GPIO0_C6`

结合硬件设计文档当前可明确确认：

- `GPIO0_C6` 在文档中标注为 `PWM_DSI`

文档位置：

- `进阶篇之-ELF-RV1126B开发板硬件设计教程.pdf`
- `GPIO0_C6 / PWM_DSI`

### 3.3 舵机接线

- `PWM 信号线` -> 一路 PWM 输出引脚
- `GND` -> 板机 GND
- `VCC` -> 独立 `5V`
- 舵机电源地与板机地必须共地

注意：

- 不要直接从板机 IO 给舵机供电
- 只把 `PWM 信号` 接到板机

### 3.4 传送带接线

如果你的驱动板支持：

- `PWM/EN` 单路调速输入

则可以：

- `PWM 信号` -> 驱动板 `PWM/EN`
- `GND` -> 驱动板 GND

如果你的传送带驱动器是标准步进驱动器，例如：

- `STEP/PUL`
- `DIR`
- `ENA`

现在推荐改为：

- 板机通过 `UART` 向 `STM32` 发控制协议
- `STM32` 输出 `SERVO PWM`、`STEP`、`ENABLE`
- `DIR` 固定到目标方向电平

板机侧新增后端名：

- `servo-backend stm32_uart`
- `conveyor-backend stm32_uart`

对应环境变量：

- `EMBEDDED_VISION_SERVO_BACKEND=stm32_uart`
- `EMBEDDED_VISION_CONVEYOR_BACKEND=stm32_uart`
- `EMBEDDED_VISION_CONTROL_UART_PORT=/dev/ttyS5`
- `EMBEDDED_VISION_CONTROL_UART_BAUDRATE=115200`
- `EMBEDDED_VISION_CONTROL_UART_TIMEOUT=1.0`
- `EMBEDDED_VISION_CONVEYOR_SPEED_MODE=hz`
- `EMBEDDED_VISION_CONVEYOR_STEP_MAX_HZ=60`
- `EMBEDDED_VISION_SERVO_NORMAL_ANGLE=90`
- `EMBEDDED_VISION_SERVO_SORT_ANGLE=45`
- `EMBEDDED_VISION_SERVO_SORT_SECONDARY_ANGLE=20`
- `EMBEDDED_VISION_RUNTIME_STOP_ON_FIRST_DETECTION=1`
- `EMBEDDED_VISION_RUNTIME_DETECTION_STOP_DELAY_SECONDS=1.0`
- `EMBEDDED_VISION_RUNTIME_STOP_COOLDOWN_SECONDS=3.0`
- `EMBEDDED_VISION_SORT_PREPARE_PAUSE=0.0`
- `EMBEDDED_VISION_SORT_SERVO_SETTLE_TIME=0.2`
- `EMBEDDED_VISION_SORT_SERVO_OSCILLATION_INTERVAL=0.5`
- `EMBEDDED_VISION_SORT_CONVEYOR_ADVANCE_TIME=10.0`

当前板机经验标定：

- UI / 完整主流程当前默认全速已经调整为 `60 stepHz`
- `100 stepHz` 连续运行 `10s`，物料大约走完传送带半程
- 当前推荐逻辑：舵机常态 `90°`，异常件在 `45°` 和 `20°` 之间摆动
- 识别到异常后，舵机会先切到 `45°`，然后每 `0.5s` 在 `45° <-> 20°` 之间切换
- 当前视觉链路默认策略：画面里一旦检测到物体，会继续运行 `1.0s` 后停带，等待 NFC 读到标签文本后再继续
- 当前系统不再使用订单库；只要 NFC 文本能解析出 `颜色/形状/类型`，就会直接拿它和视觉结果比对，一致即放行
- 为避免同一物料反复触发，传送带每次恢复运行后会有 `3.0s` 的停带冷却时间
- 整个异常摆动过程会持续约 `10s`
- 这个数据可作为 `SORT_CONVEYOR_ADVANCE_TIME` 的调参参考
- 由于默认带速已经降到 `60 stepHz`，如果发现异常件还没完全通过拨料位舵机就回正，优先把 `EMBEDDED_VISION_SORT_CONVEYOR_ADVANCE_TIME` 调大
- 如果物块还没完全通过拨料位置就提前回正，优先增大 `EMBEDDED_VISION_SORT_CONVEYOR_ADVANCE_TIME`
- 如果舵机回正太晚影响后续物料，优先减小 `EMBEDDED_VISION_SORT_CONVEYOR_ADVANCE_TIME`

### 3.4.1 UART 最小联调命令

如果只是先验证上位机到 `STM32` 的串口协议，不要一开始就跑完整分拣流程，先单独跑：

只查状态：

```bash
cd /userdata
embedded_vision_system/.venv/bin/python3 -m embedded_vision_system.basic_function_tests.test_stm32_uart \
  --port /dev/ttyS5 \
  --status-only
```

只测舵机：

```bash
cd /userdata
embedded_vision_system/.venv/bin/python3 -m embedded_vision_system.basic_function_tests.test_stm32_uart \
  --port /dev/ttyS5 \
  --servo-angle 45
```

注意：

- 当前下位机上电默认角度就是 `SERVO=90`
- 如果发的仍然是 `--servo-angle 90`，日志会显示成功，但舵机不会有可见动作

只测步进和使能，保持 3 秒后停止：

```bash
cd /userdata
embedded_vision_system/.venv/bin/python3 -m embedded_vision_system.basic_function_tests.test_stm32_uart \
  --port /dev/ttyS5 \
  --step-hz 100 \
  --enable 1 \
  --hold 3 \
  --stop
```

一次同时设置舵机、步进、电机使能：

```bash
cd /userdata
embedded_vision_system/.venv/bin/python3 -m embedded_vision_system.basic_function_tests.test_stm32_uart \
  --port /dev/ttyS5 \
  --servo-angle 45 \
  --step-hz 100 \
  --enable 1 \
  --hold 2 \
  --stop
```

### 3.5 PWM 基础测试

先查 `pwmchip` 和设备节点对应关系：

```bash
for p in /sys/class/pwm/pwmchip*; do
  echo "== $p =="
  readlink -f "$p/device/of_node"
done
```

#### 舵机测试

```bash
cd /userdata
sudo embedded_vision_system/.venv/bin/python3 -m embedded_vision_system.basic_function_tests.test_pwm_control \
  --backend sysfs \
  --chip <舵机chip> \
  --channel 0 \
  --mode servo \
  --hold 1
```

#### 传送带 PWM 测试

```bash
cd /userdata
sudo embedded_vision_system/.venv/bin/python3 -m embedded_vision_system.basic_function_tests.test_pwm_control \
  --backend sysfs \
  --chip <传送带chip> \
  --channel 0 \
  --mode duty \
  --duties 0 20 40 60 80 0 \
  --hold 1
```

### 3.6 GPIO 软件 PWM 方案

如果板载硬件 PWM 已被系统占用，可改用：

- 舵机：`1 路 GPIO 软件 PWM`
- 传送带：`1 路 GPIO 软件 PWM + 1 路 EN GPIO`

#### 舵机 GPIO 软件 PWM 测试

```bash
cd /userdata
sudo embedded_vision_system/.venv/bin/python3 -m embedded_vision_system.basic_function_tests.test_pwm_control \
  --backend gpio \
  --gpio-backend sysfs \
  --gpio <舵机GPIO编号> \
  --mode servo \
  --angles 45 90 45 90 \
  --hold 1
```

#### 传送带 GPIO 软件 PWM 测试

```bash
cd /userdata
sudo embedded_vision_system/.venv/bin/python3 -m embedded_vision_system.basic_function_tests.test_pwm_control \
  --backend gpio \
  --gpio-backend sysfs \
  --gpio <传送带PWM_GPIO编号> \
  --enable-gpio <传送带EN_GPIO编号> \
  --mode duty \
  --duties 0 20 40 60 80 0 \
  --hold 1
```

### 3.7 接入主流程

确认舵机和传送带的 `chip` 后，可直接运行：

```bash
cd /userdata
sudo embedded_vision_system/.venv/bin/python3 -m embedded_vision_system.run_board_sorting \
  --camera /dev/video52 \
  --nfc-backend pn532_i2c \
  --nfc-i2c-bus 4 \
  --nfc-i2c-address 0x24 \
  --servo-backend sysfs \
  --servo-chip <舵机chip> \
  --servo-channel 0 \
  --conveyor-backend sysfs \
  --conveyor-chip <传送带chip> \
  --conveyor-channel 0
```

如果使用 GPIO 软件 PWM，则运行：

```bash
cd /userdata
sudo embedded_vision_system/.venv/bin/python3 -m embedded_vision_system.run_board_sorting \
  --camera /dev/video52 \
  --nfc-backend pn532_i2c \
  --nfc-i2c-bus 4 \
  --nfc-i2c-address 0x24 \
  --gpio-backend sysfs \
  --servo-backend gpio \
  --servo-gpio <舵机GPIO编号> \
  --conveyor-backend gpio \
  --conveyor-pwm-gpio <传送带PWM_GPIO编号> \
  --conveyor-enable-gpio <传送带EN_GPIO编号>
```

如果舵机和电机都改由 `STM32` 输出，则运行：

```bash
cd /userdata
sudo embedded_vision_system/.venv/bin/python3 -m embedded_vision_system.run_board_sorting \
  --camera /dev/video52 \
  --nfc-backend pn532_i2c \
  --nfc-i2c-bus 4 \
  --nfc-i2c-address 0x24 \
  --servo-backend stm32_uart \
  --conveyor-backend stm32_uart \
  --control-uart-port /dev/ttyS5 \
  --control-uart-baudrate 115200 \
  --control-uart-timeout 1.0 \
  --conveyor-speed-mode hz \
  --conveyor-step-max-hz 60 \
  --conveyor-speed 60 \
  --servo-normal-angle 90 \
  --servo-sort-angle 45 \
  --servo-sort-secondary-angle 20 \
  --stop-on-first-detection 1 \
  --stop-cooldown-seconds 3.0 \
  --sort-prepare-pause 0.0 \
  --sort-servo-settle-time 0.2 \
  --sort-servo-oscillation-interval 0.5 \
  --sort-conveyor-advance-time 10.0
```

现在推荐的板机运行方式就是只启动这一条命令；`WebUI` 和完整主流程已经是同一个系统。
`run_board_sorting` 仍可保留给纯命令行烟雾测试，但正常联调不需要再单独起一个主流程进程。

```bash
cd /userdata
sudo embedded_vision_system/.venv/bin/python3 -m embedded_vision_system.web_api
```
