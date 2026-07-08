#!/usr/bin/env python3
"""
基础功能验证：STM32 UART 控制

用于板端单独确认：
- 串口设备是否正确
- 上下位机协议是否通
- SERVO / STEP / ENABLE / STOP 是否按预期响应
"""

from __future__ import annotations

import argparse
import json
import logging
import time

from embedded_vision_system.board_defaults import (
    DEFAULT_BOARD_CONTROL_UART_BAUDRATE,
    DEFAULT_BOARD_CONTROL_UART_PORT,
    DEFAULT_BOARD_CONTROL_UART_TIMEOUT,
)
from embedded_vision_system.hardware import STM32SerialController


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    force=True,
)
logger = logging.getLogger("stm32_uart_test")


def _serial_timeout_hints(port: str) -> list[str]:
    return [
        f"串口写超时：板机没有成功把数据写到 {port}",
        "这个阶段还没走到下位机协议解析，优先排查板机 UART 侧，而不是 STATUS 命令格式",
        "建议立即检查：",
        "1. 当前串口是否被控制台或 getty 占用：`ps -ef | grep -E \"agetty|serial-getty|ttyS\" | grep -v grep`",
        "2. 内核启动参数是否把该串口当 console：`cat /proc/cmdline`",
        f"3. 该串口是否被其他进程打开：`fuser {port}`",
        "4. 该节点是否真的是接到 STM32 的那一路 UART，而不是别的板载串口",
        "5. 电平是否为 3.3V TTL，且 TX/RX 已交叉、GND 已共地",
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="STM32 UART 控制测试")
    parser.add_argument(
        "--port",
        default=DEFAULT_BOARD_CONTROL_UART_PORT,
        help="串口设备，例如 /dev/ttyS5 或 /dev/ttyUSB0",
    )
    parser.add_argument("--baudrate", type=int, default=DEFAULT_BOARD_CONTROL_UART_BAUDRATE, help="串口波特率")
    parser.add_argument("--timeout", type=float, default=DEFAULT_BOARD_CONTROL_UART_TIMEOUT, help="串口读写超时秒数")
    parser.add_argument("--servo-angle", type=int, default=None, help="舵机角度 0..180")
    parser.add_argument("--step-hz", type=int, default=None, help="步进脉冲频率 0..20000")
    parser.add_argument("--enable", type=int, choices=[0, 1], default=None, help="驱动器使能，0 或 1")
    parser.add_argument("--hold", type=float, default=0.0, help="设置输出后保持多少秒，再继续后续动作")
    parser.add_argument("--stop", action="store_true", help="最后发送 STOP")
    parser.add_argument("--status-only", action="store_true", help="只查询当前状态，不执行控制")
    parser.add_argument("--help-text", action="store_true", help="先查询下位机 HELP 文本")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出")
    return parser


def _emit(args: argparse.Namespace, stage: str, payload) -> None:
    if args.json:
        print(json.dumps({"stage": stage, "payload": payload}, ensure_ascii=False))
        return
    logger.info("%s: %s", stage, payload)


def main() -> int:
    args = build_parser().parse_args()
    controller = STM32SerialController(
        port=args.port,
        baudrate=args.baudrate,
        timeout=args.timeout,
        auto_query_status=False,
    )

    logger.info(
        "STM32 UART test port=%s baudrate=%s timeout=%.2f",
        args.port,
        args.baudrate,
        args.timeout,
    )

    try:
        try:
            if args.help_text:
                _emit(args, "help", controller.get_help())

            initial_status = controller.query_status()
            _emit(args, "initial_status", initial_status.to_dict())

            if (
                args.servo_angle is not None
                and initial_status.servo_angle == int(args.servo_angle)
            ):
                logger.warning(
                    "requested servo angle %s matches current angle %s; no visible movement is expected",
                    args.servo_angle,
                    initial_status.servo_angle,
                )
                logger.warning(
                    "try a different angle such as 45 or 135 to verify physical motion"
                )

            if not args.status_only:
                if (
                    args.servo_angle is not None
                    and args.step_hz is not None
                    and args.enable is not None
                ):
                    combined_status = controller.set_outputs(
                        servo_angle=args.servo_angle,
                        step_hz=args.step_hz,
                        enabled=bool(args.enable),
                    )
                    _emit(args, "set_outputs", combined_status.to_dict())
                else:
                    if args.servo_angle is not None:
                        servo_status = controller.set_servo(args.servo_angle)
                        _emit(args, "set_servo", servo_status.to_dict())
                    if args.step_hz is not None:
                        step_status = controller.set_step(args.step_hz)
                        _emit(args, "set_step", step_status.to_dict())
                    if args.enable is not None:
                        enable_status = controller.set_enable(bool(args.enable))
                        _emit(args, "set_enable", enable_status.to_dict())

                if args.hold > 0:
                    logger.info("Holding outputs for %.2f seconds", args.hold)
                    time.sleep(args.hold)

                if args.stop:
                    stop_status = controller.stop_motor()
                    _emit(args, "stop", stop_status.to_dict())

            final_status = controller.query_status()
            _emit(args, "final_status", final_status.to_dict())
        except Exception as exc:
            if exc.__class__.__name__ == "SerialTimeoutException":
                for line in _serial_timeout_hints(args.port):
                    logger.error(line)
            raise
    finally:
        controller.close()

    logger.info("STM32 UART test finished")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
