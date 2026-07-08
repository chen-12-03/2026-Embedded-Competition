#!/usr/bin/env python3
"""
基础功能验证 4：PWM 控制

支持：
- 舵机角度扫动
- 占空比渐变

适合先做单独 PWM 验证，再接入 DeviceController。
"""

import argparse
import logging
import time

from embedded_vision_system.basic_function_tests.hardware_backends import (
    SoftwarePWMGPIOBackend,
    angle_to_duty_cycle_ns,
    create_gpio_output,
    create_pwm_backend,
    percent_to_duty_cycle_ns,
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    force=True,
)
logger = logging.getLogger("pwm_control_test")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PWM 控制测试")
    parser.add_argument("--backend", choices=["mock", "sysfs", "gpio"], default="mock", help="PWM 后端")
    parser.add_argument("--gpio-backend", choices=["mock", "sysfs"], default="sysfs", help="GPIO 输出后端")
    parser.add_argument("--chip", type=int, default=0, help="PWM chip 编号")
    parser.add_argument("--channel", type=int, default=0, help="PWM channel 编号")
    parser.add_argument("--gpio", type=int, default=None, help="软件 PWM 输出 GPIO 编号")
    parser.add_argument("--enable-gpio", type=int, default=None, help="软件 PWM 的可选使能 GPIO 编号")
    parser.add_argument("--mode", choices=["servo", "duty", "both"], default="both", help="测试模式")
    parser.add_argument("--period-ns", type=int, default=20_000_000, help="PWM 周期，默认 20ms")
    parser.add_argument("--hold", type=float, default=1.0, help="每一步保持时间")
    parser.add_argument("--angles", nargs="*", type=float, default=[0, 45, 90, 135, 180, 90], help="servo 模式角度序列")
    parser.add_argument("--duties", nargs="*", type=float, default=[10, 30, 50, 70, 90, 0], help="duty 模式占空比序列")
    return parser


def run_servo_sequence(backend, period_ns: int, angles, hold: float):
    logger.info("Starting servo sweep test")
    backend.set_period_ns(period_ns)
    backend.enable()
    for angle in angles:
        duty_ns = angle_to_duty_cycle_ns(angle=angle, period_ns=period_ns)
        backend.set_duty_cycle_ns(duty_ns)
        logger.info("servo angle=%.1f duty_ns=%s", angle, duty_ns)
        time.sleep(hold)


def run_duty_sequence(backend, period_ns: int, duties, hold: float):
    logger.info("Starting duty cycle test")
    backend.set_period_ns(period_ns)
    backend.enable()
    for duty_percent in duties:
        duty_ns = percent_to_duty_cycle_ns(duty_percent, period_ns=period_ns)
        backend.set_duty_cycle_ns(duty_ns)
        logger.info("duty_percent=%.1f duty_ns=%s", duty_percent, duty_ns)
        time.sleep(hold)


def main() -> int:
    args = build_parser().parse_args()
    if args.backend == "gpio":
        backend = SoftwarePWMGPIOBackend(
            signal_gpio=create_gpio_output(args.gpio_backend, args.gpio),
            enable_gpio=create_gpio_output(args.gpio_backend, args.enable_gpio) if args.enable_gpio is not None else None,
        )
    else:
        backend = create_pwm_backend(args.backend, chip=args.chip, channel=args.channel)

    try:
        if args.mode in ("servo", "both"):
            run_servo_sequence(backend, args.period_ns, args.angles, args.hold)
        if args.mode in ("duty", "both"):
            run_duty_sequence(backend, args.period_ns, args.duties, args.hold)
    finally:
        backend.disable()
        backend.cleanup()

    logger.info("PWM control test finished")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
