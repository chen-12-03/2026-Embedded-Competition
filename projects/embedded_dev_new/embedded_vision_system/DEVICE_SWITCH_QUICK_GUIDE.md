# 换设备快速联调手册

这份文档面向当前 `embedded_vision_system` 项目，目标是：

- 从 `WSL` 端快速同步代码到新板机
- 在 `SSH` 端快速完成基础验证
- 直接启动 `WebUI`、`NFC`、`UART -> STM32` 控制链

如果只想先把系统跑起来，优先看：

1. `第 1 节：WSL 端常用命令`
2. `第 2 节：SSH 端常用命令`
3. `第 3 节：新设备必改参数`

更详细的背景说明可继续看：

- `BOARD_BRINGUP_NOTES.md`
- `RV1126B_DEPLOYMENT.md`
- `../上位机控制协议.md`

## 0. 约定

本文档默认：

- 开发机是 `WSL`
- 板机代码目录是 `/userdata/embedded_vision_system`
- 板机运行模块命令时，当前目录应为 `/userdata`
- `WebUI` 端口是 `8080`
- 摄像头设备是 `/dev/video52`
- `NFC` 使用 `PN532 I2C`
- 电机和舵机通过 `UART` 发给 `STM32`

重要提醒：

- `python -m embedded_vision_system.xxx` 这类命令，必须站在 `/userdata` 跑，不要站在 `/userdata/embedded_vision_system` 跑
- `web_api.py` 读取的是环境变量，不会继承测试脚本的命令行参数
- 用 `sudo` 启动 `WebUI` 时，优先使用 `sudo -E`，否则环境变量可能被清掉
- 当前板机默认相机参数已经固定为 `640x480 + MJPG + 30fps`
- 当前 UI / 完整主流程默认传送带速度已经下调为 `60 stepHz`
- 当前 NFC 持续采样在线，主流程运行时不会再暂停轮询
- 当前 NFC 文本会锁存到下一次完整判定结束，避免标签短暂离开时被空采样冲掉
- 当前系统直接用 NFC 文本里的颜色/形状/类型和视觉结果做一致性比对
- 当前视觉链路默认策略是“检测到物体后继续运行 1.0s 再停带”
- 当前恢复跑带后的防重复停带冷却时间是 `3.0s`
- 当前异常拨料舵机角度区间是 `45° <-> 20°`
- 当前 MPU6050 默认阈值已放宽为：黄色 `0.18g`、红色 `0.35g`
- 当前电流读数只做界面展示，不参与异常停机和故障锁存

## 1. WSL 端常用命令

### 1.1 配置目标板机变量

先在 `WSL` 里设置目标板机：

```bash
export BOARD_USER=dev
export BOARD_HOST=10.100.57.145
export BOARD_ROOT=/userdata
```

连接测试：

```bash
ssh $BOARD_USER@$BOARD_HOST
```

### 1.2 本地快速检查

同步前建议先做一轮最小检查：

```bash
cd /home/chen1/projects/embedded_dev_new
python3 -m py_compile \
  embedded_vision_system/web_api.py \
  embedded_vision_system/run_board_sorting.py \
  embedded_vision_system/device_controller.py \
  embedded_vision_system/hardware/stm32_uart.py
```

```bash
cd /home/chen1/projects/embedded_dev_new
pytest -q \
  embedded_vision_system/tests/test_business_rules.py \
  embedded_vision_system/tests/test_stm32_uart.py \
  embedded_vision_system/tests/test_board_runtime.py
```

### 1.3 同步代码到板机

推荐用 `rsync`，速度快，也方便反复覆盖：

```bash
cd /home/chen1/projects/embedded_dev_new
rsync -avz --delete \
  --exclude '.venv/' \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  embedded_vision_system/ \
  $BOARD_USER@$BOARD_HOST:$BOARD_ROOT/embedded_vision_system/
```

如果板端还需要模型：

```bash
cd /home/chen1/projects/embedded_dev_new
rsync -avz --delete \
  rknnModel/ \
  $BOARD_USER@$BOARD_HOST:$BOARD_ROOT/rknnModel/
```

如果要把协议文档也一起带过去：

```bash
cd /home/chen1/projects/embedded_dev_new
scp 上位机控制协议.md $BOARD_USER@$BOARD_HOST:$BOARD_ROOT/
```

### 1.4 常用远程执行

不想先手动 `ssh` 进去时，可直接远程执行：

```bash
ssh $BOARD_USER@$BOARD_HOST 'cd /userdata && ls'
```

```bash
ssh $BOARD_USER@$BOARD_HOST 'cd /userdata && ps -ef | grep -E "embedded_vision_system.web_api|run_board_sorting" | grep -v grep'
```

## 2. SSH 端常用命令

### 2.1 进入正确目录

```bash
cd /userdata
```

确认代码目录存在：

```bash
ls /userdata/embedded_vision_system
```

确认实际导入的是板机上的这份代码：

```bash
cd /userdata
embedded_vision_system/.venv/bin/python3 -c "import embedded_vision_system; print(embedded_vision_system.__file__)"
```

### 2.2 首次准备虚拟环境

如果新板机还没有 `.venv`，可以先建：

```bash
cd /userdata/embedded_vision_system
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
```

注意：

- 某些板端 OpenCV / RKNN 依赖不一定适合直接 `pip`
- 如果镜像已带系统版依赖，优先复用系统环境

### 2.3 NFC 单独验证

这条命令是当前最稳定的 NFC 自检命令：

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

如果这条命令都读不到卡，先不要怀疑 `WebUI`，先查：

- 接线
- `I2C bus`
- `I2C address`
- `PN532` 供电
- 如果你当前板机扫描到的地址不是 `0x24`，这里的地址也要按实际扫描结果改

### 2.4 启动 WebUI

这是当前推荐的启动方式。现在 `WebUI` 已经直接托管完整主流程，不需要再额外启动一个独立的 `run_board_sorting`：

```bash
cd /userdata
sudo embedded_vision_system/.venv/bin/python3 -m embedded_vision_system.web_api
```

启动后访问：

```text
http://板机IP:8080/
```

### 2.5 纯命令行烟雾测试

如果你临时不需要网页，只想在板机上跑一个纯命令行的连续分拣烟雾测试，再单独使用：

```bash
cd /userdata
sudo embedded_vision_system/.venv/bin/python3 -m embedded_vision_system.run_board_sorting
```

### 2.6 查看运行中的进程

```bash
cd /userdata
ps -ef | grep -E "embedded_vision_system.web_api|run_board_sorting" | grep -v grep
```

### 2.7 停止进程

```bash
pkill -f embedded_vision_system.web_api
```

```bash
pkill -f embedded_vision_system.run_board_sorting
```

## 3. 新设备必改参数

换一块新板时，优先改这几项：

### 3.1 网络

- `BOARD_USER`
- `BOARD_HOST`

### 3.2 摄像头

- `--camera /dev/video52`

如果新板上摄像头节点不同，先查：

```bash
ls /dev/video*
```

### 3.3 NFC

- `EMBEDDED_VISION_NFC_I2C_BUS`
- `EMBEDDED_VISION_NFC_I2C_ADDRESS`
- `EMBEDDED_VISION_NFC_SCAN_TIMEOUT`
- `EMBEDDED_VISION_NFC_PASSIVE_ACTIVATION_RETRIES`

### 3.4 STM32 串口

- `EMBEDDED_VISION_CONTROL_UART_PORT`
- `EMBEDDED_VISION_CONTROL_UART_BAUDRATE`
- `EMBEDDED_VISION_CONTROL_UART_TIMEOUT`
- `EMBEDDED_VISION_CONVEYOR_SPEED`
- `EMBEDDED_VISION_CONVEYOR_STEP_MAX_HZ`
- `EMBEDDED_VISION_RUNTIME_STOP_ON_FIRST_DETECTION`
- `EMBEDDED_VISION_RUNTIME_DETECTION_STOP_DELAY_SECONDS`
- `EMBEDDED_VISION_RUNTIME_STOP_COOLDOWN_SECONDS`
- `EMBEDDED_VISION_SORT_PREPARE_PAUSE`
- `EMBEDDED_VISION_SORT_SERVO_SETTLE_TIME`
- `EMBEDDED_VISION_SORT_CONVEYOR_ADVANCE_TIME`

当前已知联调基准：

- UI / 完整主流程当前默认全速为 `60 stepHz`
- 默认视觉停带策略是“检测到物体后继续运行 1.0s 再停带”
- 默认防重复停带冷却时间是 `3.0s`
- 默认异常拨料角度区间是 `45° <-> 20°`
- `100 stepHz` 运行 `10s` 约等于传送带半程
- 新设备如果舵机拨料太早，优先调大 `EMBEDDED_VISION_SORT_CONVEYOR_ADVANCE_TIME`
- 新设备如果舵机拨料太晚，优先调小 `EMBEDDED_VISION_SORT_CONVEYOR_ADVANCE_TIME`

如需确认串口节点：

```bash
ls /dev/ttyS* /dev/ttyUSB* /dev/ttyACM* 2>/dev/null
```

### 3.5 运行期状态文件

- `EMBEDDED_VISION_STATE_PATH`

如果 `WebUI` 和主流程分两个进程跑，这个路径必须一致。

建议统一使用：

```bash
/run/media/mmcblk1p1/embedded_vision_data/runtime_data/orders_state.json
```

## 4. 常用排查命令

### 4.1 查 WebUI 实际工作目录

```bash
WEB_PID=$(ps -ef | grep -E "embedded_vision_system.web_api" | grep -v grep | awk 'NR==1 {print $2}')
readlink -f /proc/$WEB_PID/cwd
```

### 4.2 查 WebUI 实际环境变量

```bash
WEB_PID=$(ps -ef | grep -E "embedded_vision_system.web_api" | grep -v grep | awk 'NR==1 {print $2}')
tr '\0' '\n' </proc/$WEB_PID/environ | grep '^EMBEDDED_VISION_'
```

重点看：

- `EMBEDDED_VISION_NFC_BACKEND`
- `EMBEDDED_VISION_NFC_I2C_BUS`
- `EMBEDDED_VISION_NFC_I2C_ADDRESS`
- `EMBEDDED_VISION_NFC_FALLBACK_TO_UID`
- `EMBEDDED_VISION_STATE_PATH`
- `EMBEDDED_VISION_SERVO_BACKEND`
- `EMBEDDED_VISION_CONVEYOR_BACKEND`
- `EMBEDDED_VISION_CONTROL_UART_PORT`

### 4.3 直接看接口返回，而不是只看页面

```bash
curl -s http://127.0.0.1:8080/api/dashboard | python3 -m json.tool
```

```bash
curl -s http://127.0.0.1:8080/api/nfc/status | python3 -m json.tool
```

重点看：

- `debug.state_path`
- `nfc_runtime.configured_backend`
- `nfc_runtime.fallback_to_uid`
- `nfc_sample.source`
- `nfc_sample.sample.success`
- `nfc_sample.sample.text`

### 4.4 快速判断是不是旧代码

如果页面显示异常，但接口字段里看不到这些内容：

- `nfc_runtime`
- `fallback_to_uid`
- `sample.text`

优先怀疑：

- 板机实际运行的不是最新同步代码
- 启动时没带环境变量
- 当前目录不对，导入到了别的 `embedded_vision_system`

## 5. 推荐操作顺序

换新设备时，建议按这个顺序走：

1. `WSL` 端 `py_compile + pytest`
2. `WSL` 端 `rsync` 同步代码
3. `SSH` 端跑 `NFC` 单独测试
4. `SSH` 端确认串口节点存在
5. `SSH` 端启动 `WebUI`
6. `curl /api/dashboard` 看运行态
7. 如果只做命令行烟雾测试，再单独启动 `run_board_sorting`

## 6. 现阶段最常用的命令清单

如果你只想看最常敲的命令，可以直接抄这里。

`WSL`：

```bash
cd /home/chen1/projects/embedded_dev_new
rsync -avz --delete --exclude '.venv/' --exclude '__pycache__/' --exclude '*.pyc' embedded_vision_system/ dev@10.100.57.145:/userdata/embedded_vision_system/
```

```bash
cd /home/chen1/projects/embedded_dev_new
pytest -q embedded_vision_system/tests/test_business_rules.py embedded_vision_system/tests/test_stm32_uart.py embedded_vision_system/tests/test_board_runtime.py
```

`SSH`：

```bash
cd /userdata
ps -ef | grep -E "embedded_vision_system.web_api|run_board_sorting" | grep -v grep
```

```bash
curl -s http://127.0.0.1:8080/api/dashboard | python3 -m json.tool
```

```bash
curl -s http://127.0.0.1:8080/api/nfc/status | python3 -m json.tool
```

```bash
cd /userdata
sudo embedded_vision_system/.venv/bin/python3 -m embedded_vision_system.web_api
```

```bash
cd /userdata
sudo embedded_vision_system/.venv/bin/python3 -m embedded_vision_system.run_board_sorting
```
上面第二条仅在你刻意做无 WebUI 的命令行烟雾测试时使用。
