#!/usr/bin/env python3
"""
板端连续分拣启动入口。

示例：
python3 -m embedded_vision_system.run_board_sorting \
  --camera /dev/video52 \
  --nfc-backend pn532_i2c \
  --nfc-i2c-bus 4 \
  --nfc-i2c-address 0x24 \
  --servo-backend stm32_uart \
  --conveyor-backend stm32_uart \
  --control-uart-port /dev/ttyS5 \
  --conveyor-speed-mode hz \
  --conveyor-speed 60 \
  --servo-sort-angle 45 \
  --servo-sort-secondary-angle 20 \
  --stop-on-first-detection 1 \
  --detection-stop-delay-seconds 1.0 \
  --stop-cooldown-seconds 3.0 \
  --sort-servo-oscillation-interval 0.5 \
  --sort-conveyor-advance-time 10
"""

from __future__ import annotations

import argparse
import logging

from .board_defaults import (
    DEFAULT_BOARD_CAMERA_ID,
    DEFAULT_BOARD_CAMERA_FPS,
    DEFAULT_BOARD_CAMERA_FORMAT,
    DEFAULT_BOARD_CAMERA_HEIGHT,
    DEFAULT_BOARD_CAMERA_WIDTH,
    DEFAULT_BOARD_CONVEYOR_BACKEND,
    DEFAULT_BOARD_CONVEYOR_HALF_TRAVEL_SECONDS,
    DEFAULT_BOARD_CONVEYOR_SPEED,
    DEFAULT_BOARD_CONVEYOR_SPEED_MODE,
    DEFAULT_BOARD_CONVEYOR_STEP_MAX_HZ,
    DEFAULT_BOARD_CONTROL_UART_BAUDRATE,
    DEFAULT_BOARD_CONTROL_UART_PORT,
    DEFAULT_BOARD_CONTROL_UART_TIMEOUT,
    DEFAULT_BOARD_MPU6050_I2C_ADDRESS,
    DEFAULT_BOARD_MPU6050_I2C_BUS,
    DEFAULT_BOARD_MPU6050_RED_THRESHOLD,
    DEFAULT_BOARD_MPU6050_YELLOW_THRESHOLD,
    DEFAULT_BOARD_NFC_BACKEND,
    DEFAULT_BOARD_NFC_I2C_ADDRESS,
    DEFAULT_BOARD_NFC_I2C_BUS,
    DEFAULT_BOARD_NFC_SCAN_TIMEOUT,
    DEFAULT_BOARD_RUNTIME_CENTER_HOLD_FRAMES,
    DEFAULT_BOARD_RUNTIME_DETECTION_STOP_DELAY_SECONDS,
    DEFAULT_BOARD_RUNTIME_STOP_COOLDOWN_SECONDS,
    DEFAULT_BOARD_RUNTIME_STOP_ON_FIRST_DETECTION,
    DEFAULT_BOARD_SERVO_NORMAL_ANGLE,
    DEFAULT_BOARD_SERVO_SORT_ANGLE,
    DEFAULT_BOARD_SERVO_SORT_SECONDARY_ANGLE,
    DEFAULT_BOARD_SORT_CONVEYOR_ADVANCE_SECONDS,
    DEFAULT_BOARD_SORT_PREPARE_PAUSE_SECONDS,
    DEFAULT_BOARD_SORT_SERVO_OSCILLATION_INTERVAL,
    DEFAULT_BOARD_SORT_SERVO_SETTLE_SECONDS,
    DEFAULT_BOARD_SERVO_BACKEND,
    DEFAULT_BOARD_VIBRATION_BACKEND,
)
from .board_runtime import BoardRuntimeConfig, BoardSortingRuntime
from .device_controller import build_device_controller
from .hardware import create_nfc_reader
from .sorting_system import SortingSystem, SystemMode


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    force=True,
)
logger = logging.getLogger("board_sorting_runtime")


def parse_int(value: str) -> int:
    return int(value, 0)


def parse_bool_flag(value: str) -> bool:
    return str(value).strip().lower() not in {"0", "false", "no", "off"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="板端连续分拣运行器")
    parser.add_argument("--camera", default=DEFAULT_BOARD_CAMERA_ID, help="摄像头设备路径或索引")
    parser.add_argument("--fps", type=int, default=DEFAULT_BOARD_CAMERA_FPS, help="摄像头目标帧率")
    parser.add_argument("--width", type=int, default=DEFAULT_BOARD_CAMERA_WIDTH, help="摄像头采集宽度")
    parser.add_argument("--height", type=int, default=DEFAULT_BOARD_CAMERA_HEIGHT, help="摄像头采集高度")
    parser.add_argument(
        "--camera-format",
        choices=("YUYV", "MJPG", "NV12"),
        default=DEFAULT_BOARD_CAMERA_FORMAT,
        help="摄像头像素格式，当前板机默认使用 MJPG 以提高实际采集帧率",
    )
    parser.add_argument("--state-path", default=None, help="运行状态与历史记录文件路径")
    parser.add_argument("--confidence-threshold", type=float, default=0.5, help="一致性最低置信度")
    parser.add_argument(
        "--conveyor-speed",
        type=int,
        default=DEFAULT_BOARD_CONVEYOR_SPEED,
        help="传送带运行速度；当前板机默认按 hz 解释，60 表示当前 UI 系统默认全速 STEP 频率",
    )
    parser.add_argument("--center-tolerance-ratio", type=float, default=0.12, help="目标中心容差比例")
    parser.add_argument(
        "--center-hold-frames",
        type=int,
        default=DEFAULT_BOARD_RUNTIME_CENTER_HOLD_FRAMES,
        help="当关闭首次检测即停时，目标进入中心区后连续多少帧满足条件才停带",
    )
    parser.add_argument(
        "--stop-on-first-detection",
        type=parse_bool_flag,
        default=DEFAULT_BOARD_RUNTIME_STOP_ON_FIRST_DETECTION,
        help="是否在画面中一旦检测到物体就立刻停带；当前板机默认开启",
    )
    parser.add_argument(
        "--detection-stop-delay-seconds",
        type=float,
        default=DEFAULT_BOARD_RUNTIME_DETECTION_STOP_DELAY_SECONDS,
        help="视觉检测触发后，传送带继续运行多久再停下；当前板机默认 1.0s",
    )
    parser.add_argument(
        "--stop-cooldown-seconds",
        type=float,
        default=DEFAULT_BOARD_RUNTIME_STOP_COOLDOWN_SECONDS,
        help="每次恢复跑带后，多少秒内忽略再次停带，避免同一物料反复触发",
    )
    parser.add_argument("--capture-settle-time", type=float, default=0.25, help="停带后抓拍前稳定等待时间")
    parser.add_argument("--capture-dir", default=None, help="抓拍图片保存目录")
    parser.add_argument("--nfc-log-path", default=None, help="NFC 日志 jsonl 路径")
    parser.add_argument("--max-items", type=int, default=0, help="最多处理多少件，0 为无限")
    parser.add_argument("--max-frames", type=int, default=0, help="最多处理多少帧，0 为无限")

    parser.add_argument(
        "--nfc-backend",
        choices=["mock", "file", "command", "pn532_i2c", "pn532_spi", "pn532_uart"],
        default=DEFAULT_BOARD_NFC_BACKEND,
        help="NFC 后端，默认使用 I2C",
    )
    parser.add_argument("--nfc-file-path", default=None, help="file 模式下的 material_id 文件")
    parser.add_argument("--nfc-command", default=None, help="command 模式下的读卡命令")
    parser.add_argument("--nfc-i2c-bus", type=int, default=DEFAULT_BOARD_NFC_I2C_BUS, help="PN532 I2C bus")
    parser.add_argument(
        "--nfc-i2c-address",
        type=parse_int,
        default=DEFAULT_BOARD_NFC_I2C_ADDRESS,
        help="PN532 I2C 地址，例如 0x24",
    )
    parser.add_argument("--nfc-scan-timeout", type=float, default=DEFAULT_BOARD_NFC_SCAN_TIMEOUT, help="NFC 扫描超时")
    parser.add_argument("--nfc-read-window-pages", type=int, default=16, help="NFC 连续读页数")

    parser.add_argument(
        "--vibration-backend",
        choices=["mock", "mpu6050"],
        default=DEFAULT_BOARD_VIBRATION_BACKEND,
        help="振动传感器后端，当前板机默认使用 mpu6050",
    )
    parser.add_argument(
        "--mpu6050-i2c-bus",
        type=int,
        default=DEFAULT_BOARD_MPU6050_I2C_BUS,
        help="MPU6050 I2C bus，当前板机默认使用 i2c-3",
    )
    parser.add_argument(
        "--mpu6050-i2c-address",
        type=parse_int,
        default=DEFAULT_BOARD_MPU6050_I2C_ADDRESS,
        help="MPU6050 I2C 地址，例如 0x68",
    )
    parser.add_argument(
        "--mpu6050-yellow-threshold",
        type=float,
        default=DEFAULT_BOARD_MPU6050_YELLOW_THRESHOLD,
        help="MPU6050 振动黄色告警阈值",
    )
    parser.add_argument(
        "--mpu6050-red-threshold",
        type=float,
        default=DEFAULT_BOARD_MPU6050_RED_THRESHOLD,
        help="MPU6050 振动红色告警阈值",
    )

    parser.add_argument("--gpio-backend", choices=["mock", "sysfs"], default="sysfs", help="GPIO 输出后端")
    parser.add_argument(
        "--servo-backend",
        choices=["mock", "sysfs", "gpio", "stm32_uart"],
        default=DEFAULT_BOARD_SERVO_BACKEND,
        help="舵机输出后端",
    )
    parser.add_argument("--servo-chip", type=int, default=0, help="舵机 PWM chip")
    parser.add_argument("--servo-channel", type=int, default=0, help="舵机 PWM channel")
    parser.add_argument("--servo-gpio", type=int, default=None, help="舵机软件 PWM GPIO 编号")
    parser.add_argument(
        "--servo-normal-angle",
        type=int,
        default=DEFAULT_BOARD_SERVO_NORMAL_ANGLE,
        help="舵机放行角度，当前板机默认 90°",
    )
    parser.add_argument(
        "--servo-sort-angle",
        type=int,
        default=DEFAULT_BOARD_SERVO_SORT_ANGLE,
        help="舵机异常拨料主角度，当前板机默认 45°",
    )
    parser.add_argument(
        "--servo-sort-secondary-angle",
        type=int,
        default=DEFAULT_BOARD_SERVO_SORT_SECONDARY_ANGLE,
        help="舵机异常拨料副角度，当前板机默认 20°",
    )
    parser.add_argument(
        "--sort-prepare-pause",
        type=float,
        default=DEFAULT_BOARD_SORT_PREPARE_PAUSE_SECONDS,
        help="NFC/视觉判定完成后，重新启动传送带前的额外等待时间",
    )
    parser.add_argument(
        "--sort-servo-settle-time",
        type=float,
        default=DEFAULT_BOARD_SORT_SERVO_SETTLE_SECONDS,
        help="舵机切到异常拨料角度后的稳定等待时间",
    )
    parser.add_argument(
        "--sort-servo-oscillation-interval",
        type=float,
        default=DEFAULT_BOARD_SORT_SERVO_OSCILLATION_INTERVAL,
        help="异常拨料时两个角度之间的切换间隔，当前板机默认 0.5s",
    )
    parser.add_argument(
        "--sort-conveyor-advance-time",
        type=float,
        default=DEFAULT_BOARD_SORT_CONVEYOR_ADVANCE_SECONDS,
        help=(
            "异常件恢复跑带后，舵机在异常角度区间内持续摆动的总时间；"
            "当前板机历史标定里 100Hz 下 "
            f"{DEFAULT_BOARD_CONVEYOR_HALF_TRAVEL_SECONDS:g}s 约等于半程，可据此调参，"
            f"默认 {DEFAULT_BOARD_SORT_CONVEYOR_ADVANCE_SECONDS:.1f}s"
        ),
    )

    parser.add_argument(
        "--conveyor-backend",
        choices=["mock", "sysfs", "gpio", "stm32_uart"],
        default=DEFAULT_BOARD_CONVEYOR_BACKEND,
        help="传送带输出后端",
    )
    parser.add_argument("--conveyor-chip", type=int, default=0, help="传送带 PWM chip")
    parser.add_argument("--conveyor-channel", type=int, default=1, help="传送带 PWM channel")
    parser.add_argument("--conveyor-pwm-gpio", type=int, default=None, help="传送带软件 PWM GPIO 编号")
    parser.add_argument("--conveyor-enable-gpio", type=int, default=None, help="传送带使能 GPIO 编号")
    parser.add_argument(
        "--control-uart-port",
        default=DEFAULT_BOARD_CONTROL_UART_PORT,
        help="STM32 控制串口，例如 /dev/ttyS5",
    )
    parser.add_argument(
        "--control-uart-baudrate",
        type=int,
        default=DEFAULT_BOARD_CONTROL_UART_BAUDRATE,
        help="STM32 控制串口波特率",
    )
    parser.add_argument(
        "--control-uart-timeout",
        type=float,
        default=DEFAULT_BOARD_CONTROL_UART_TIMEOUT,
        help="STM32 控制串口读写超时",
    )
    parser.add_argument(
        "--conveyor-speed-mode",
        choices=["percent", "hz"],
        default=DEFAULT_BOARD_CONVEYOR_SPEED_MODE,
        help="stm32_uart 传送带速度解释方式",
    )
    parser.add_argument(
        "--conveyor-step-max-hz",
        type=int,
        default=DEFAULT_BOARD_CONVEYOR_STEP_MAX_HZ,
        help="stm32_uart 百分比模式下映射到的最大 STEP 频率；当前 UI 系统默认全速为 60Hz",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()

    system = SortingSystem(
        mode=SystemMode.CONTINUOUS,
        confidence_threshold=args.confidence_threshold,
        state_path=args.state_path,
    )
    system.device_controller = build_device_controller(
        servo_backend=args.servo_backend,
        servo_chip=args.servo_chip,
        servo_channel=args.servo_channel,
        servo_gpio=args.servo_gpio,
        servo_normal_angle=args.servo_normal_angle,
        servo_sort_angle=args.servo_sort_angle,
        servo_sort_secondary_angle=args.servo_sort_secondary_angle,
        conveyor_backend=args.conveyor_backend,
        conveyor_chip=args.conveyor_chip,
        conveyor_channel=args.conveyor_channel,
        conveyor_pwm_gpio=args.conveyor_pwm_gpio,
        conveyor_enable_gpio=args.conveyor_enable_gpio,
        gpio_backend=args.gpio_backend,
        default_conveyor_speed=args.conveyor_speed,
        vibration_backend=args.vibration_backend,
        vibration_i2c_bus=args.mpu6050_i2c_bus,
        vibration_i2c_address=args.mpu6050_i2c_address,
        vibration_yellow_threshold=args.mpu6050_yellow_threshold,
        vibration_red_threshold=args.mpu6050_red_threshold,
        control_uart_port=args.control_uart_port,
        control_uart_baudrate=args.control_uart_baudrate,
        control_uart_timeout=args.control_uart_timeout,
        conveyor_speed_mode=args.conveyor_speed_mode,
        conveyor_step_max_hz=args.conveyor_step_max_hz,
        sort_prepare_pause=args.sort_prepare_pause,
        sort_servo_settle_time=args.sort_servo_settle_time,
        sort_servo_oscillation_interval=args.sort_servo_oscillation_interval,
        sort_conveyor_advance_time=args.sort_conveyor_advance_time,
    )
    system.nfc_reader = create_nfc_reader(
        backend=args.nfc_backend,
        file_path=args.nfc_file_path,
        command=args.nfc_command,
        i2c_bus=args.nfc_i2c_bus,
        i2c_address=args.nfc_i2c_address,
        scan_timeout=args.nfc_scan_timeout,
        read_window_pages=args.nfc_read_window_pages,
    )

    runtime = BoardSortingRuntime(
        system=system,
        config=BoardRuntimeConfig(
            camera_id=args.camera,
            fps=args.fps,
            width=args.width,
            height=args.height,
            pixel_format=args.camera_format,
            center_tolerance_ratio=args.center_tolerance_ratio,
            center_hold_frames=args.center_hold_frames,
            stop_on_first_detection=args.stop_on_first_detection,
            detection_stop_delay_seconds=args.detection_stop_delay_seconds,
            stop_cooldown_seconds=args.stop_cooldown_seconds,
            capture_settle_time=args.capture_settle_time,
            conveyor_speed=args.conveyor_speed,
            capture_dir=args.capture_dir,
            nfc_log_path=args.nfc_log_path,
        ),
    )

    try:
        result = runtime.run(
            max_items=args.max_items,
            max_frames=args.max_frames,
        )
        logger.info("Runtime finished: %s", result)
        return 0 if result.get("success") else 1
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        return 130
    finally:
        runtime.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
