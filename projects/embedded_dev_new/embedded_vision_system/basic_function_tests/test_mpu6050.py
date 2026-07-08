#!/usr/bin/env python3
"""
基础功能验证：MPU6050 读取

用于板端单独确认 I2C 总线、地址和三轴加速度/陀螺仪数据。
"""

import argparse
import json
import logging
import time

from embedded_vision_system.board_defaults import (
    DEFAULT_BOARD_MPU6050_I2C_ADDRESS,
    DEFAULT_BOARD_MPU6050_I2C_BUS,
)
from embedded_vision_system.hardware import MPU6050


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    force=True,
)
logger = logging.getLogger("mpu6050_test")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MPU6050 I2C 读取测试")
    parser.add_argument(
        "--i2c-bus",
        type=int,
        default=DEFAULT_BOARD_MPU6050_I2C_BUS,
        help="Linux I2C 总线号，例如 /dev/i2c-4",
    )
    parser.add_argument(
        "--i2c-address",
        type=lambda value: int(value, 0),
        default=DEFAULT_BOARD_MPU6050_I2C_ADDRESS,
        help="MPU6050 7bit 地址，常见为 0x68 或 0x69",
    )
    parser.add_argument("--accel-range-g", type=int, choices=[2, 4, 8, 16], default=2, help="加速度量程")
    parser.add_argument("--gyro-range-dps", type=int, choices=[250, 500, 1000, 2000], default=250, help="陀螺仪量程")
    parser.add_argument("--sample-rate-divider", type=int, default=7, help="采样率分频寄存器值")
    parser.add_argument("--dlpf-config", type=int, default=3, help="低通滤波配置 0..7")
    parser.add_argument("--count", type=int, default=20, help="读取次数")
    parser.add_argument("--interval", type=float, default=0.2, help="读取间隔秒数")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出每次读数")
    return parser


def main() -> int:
    args = build_parser().parse_args()

    logger.info(
        "MPU6050 bus=%s address=0x%02x count=%s interval=%.2f",
        args.i2c_bus,
        args.i2c_address,
        args.count,
        args.interval,
    )

    with MPU6050(
        bus_id=args.i2c_bus,
        address=args.i2c_address,
        accel_range_g=args.accel_range_g,
        gyro_range_dps=args.gyro_range_dps,
        sample_rate_divider=args.sample_rate_divider,
        dlpf_config=args.dlpf_config,
    ) as sensor:
        who_am_i = sensor.who_am_i()
        if who_am_i not in (0x68, 0x69):
            logger.warning("unexpected WHO_AM_I=0x%02x; check address, wiring, or chip variant", who_am_i)
        else:
            logger.info("WHO_AM_I=0x%02x", who_am_i)

        for index in range(args.count):
            reading = sensor.read()
            payload = reading.to_dict()
            payload["index"] = index + 1
            if args.json:
                print(json.dumps(payload, ensure_ascii=False))
            else:
                logger.info(
                    "sample=%s accel=(%.3f, %.3f, %.3f)g gyro=(%.2f, %.2f, %.2f)dps temp=%.2fC vibration=%.4fg",
                    index + 1,
                    reading.accel_x_g,
                    reading.accel_y_g,
                    reading.accel_z_g,
                    reading.gyro_x_dps,
                    reading.gyro_y_dps,
                    reading.gyro_z_dps,
                    reading.temperature_c,
                    reading.vibration_g,
                )
            time.sleep(args.interval)

    logger.info("MPU6050 test finished")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
