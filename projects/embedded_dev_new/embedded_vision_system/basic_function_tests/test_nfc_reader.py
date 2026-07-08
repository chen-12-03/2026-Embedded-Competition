#!/usr/bin/env python3
"""
基础功能验证 3：NFC 读取

支持三种模式：
- mock: 使用预设 material_id 循环验证
- file: 从文件读取 material_id
- command: 调用外部命令读取 material_id
- pn532_i2c: 使用 PN532 的 I2C 传输
- pn532_spi: 使用 PN532 的 SPI 传输
- pn532_uart: 使用 PN532 的 UART/HSU 传输
"""

import argparse
import json
import logging
import time

from embedded_vision_system.basic_function_tests.hardware_backends import create_nfc_reader


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    force=True,
)
logger = logging.getLogger("nfc_reader_test")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="NFC 读卡测试")
    parser.add_argument(
        "--backend",
        choices=["mock", "file", "command", "pn532_i2c", "pn532_spi", "pn532_uart"],
        default="mock",
        help="NFC 测试后端",
    )
    parser.add_argument("--material-ids", nargs="*", default=["MAT001", "MAT002", "MAT003"], help="mock 模式下的物料 ID 列表")
    parser.add_argument("--file-path", default="", help="file 模式下的结果文件路径")
    parser.add_argument("--command", default="", help="command 模式下的外部读卡命令")
    parser.add_argument("--i2c-bus", type=int, default=1, help="pn532_i2c 模式下的 I2C 总线号")
    parser.add_argument("--i2c-address", type=lambda value: int(value, 0), default=0x24, help="pn532_i2c 模式下的 7bit 从机地址")
    parser.add_argument("--spi-bus", type=int, default=0, help="pn532_spi 模式下的 SPI bus")
    parser.add_argument("--spi-device", type=int, default=0, help="pn532_spi 模式下的 SPI device/CS")
    parser.add_argument("--spi-speed-hz", type=int, default=1_000_000, help="pn532_spi 模式下的 SPI 时钟")
    parser.add_argument("--uart-port", default="/dev/ttyS1", help="pn532_uart 模式下的串口设备")
    parser.add_argument("--uart-baudrate", type=int, default=115200, help="pn532_uart 模式下的波特率")
    parser.add_argument("--command-timeout", type=float, default=1.0, help="PN532 命令超时")
    parser.add_argument("--scan-timeout", type=float, default=1.5, help="单次寻卡/收包超时")
    parser.add_argument("--read-window-pages", type=int, default=16, help="从标签连续读取的页数窗口")
    parser.add_argument("--passive-activation-retries", type=lambda value: int(value, 0), default=0xFF, help="RFConfiguration 被动寻卡重试次数，例如 0xFF")
    parser.add_argument("--no-fallback-to-uid", action="store_true", help="标签载荷解不出 material_id 时不回退为 UID")
    parser.add_argument("--pin-sda", default="", help="I2C SDA 接线标注，例如 GPIO2_B1")
    parser.add_argument("--pin-scl", default="", help="I2C SCL 接线标注，例如 GPIO2_B2")
    parser.add_argument("--pin-mosi", default="", help="SPI MOSI 接线标注")
    parser.add_argument("--pin-miso", default="", help="SPI MISO 接线标注")
    parser.add_argument("--pin-sck", default="", help="SPI SCK 接线标注")
    parser.add_argument("--pin-cs", default="", help="SPI CS/NSS 接线标注")
    parser.add_argument("--pin-tx", default="", help="UART TX 接线标注")
    parser.add_argument("--pin-rx", default="", help="UART RX 接线标注")
    parser.add_argument("--pin-irq", default="", help="PN532 IRQ 接线标注")
    parser.add_argument("--pin-rstpdn", default="", help="PN532 RSTPDN 接线标注")
    parser.add_argument("--pin-vcc", default="3V3", help="供电引脚标注")
    parser.add_argument("--pin-gnd", default="GND", help="地线引脚标注")
    parser.add_argument("--count", type=int, default=10, help="读取次数")
    parser.add_argument("--interval", type=float, default=1.0, help="读取间隔秒数")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出每次读卡结果")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    pin_config = {
        "sda": args.pin_sda or None,
        "scl": args.pin_scl or None,
        "mosi": args.pin_mosi or None,
        "miso": args.pin_miso or None,
        "sck": args.pin_sck or None,
        "cs": args.pin_cs or None,
        "tx": args.pin_tx or None,
        "rx": args.pin_rx or None,
        "irq": args.pin_irq or None,
        "rstpdn": args.pin_rstpdn or None,
        "vcc": args.pin_vcc or None,
        "gnd": args.pin_gnd or None,
    }
    reader = create_nfc_reader(
        backend=args.backend,
        material_ids=args.material_ids,
        file_path=args.file_path or None,
        command=args.command or None,
        i2c_bus=args.i2c_bus,
        i2c_address=args.i2c_address,
        spi_bus=args.spi_bus,
        spi_device=args.spi_device,
        spi_speed_hz=args.spi_speed_hz,
        uart_port=args.uart_port,
        uart_baudrate=args.uart_baudrate,
        command_timeout=args.command_timeout,
        scan_timeout=args.scan_timeout,
        read_window_pages=args.read_window_pages,
        passive_activation_retries=args.passive_activation_retries,
        fallback_to_uid=not args.no_fallback_to_uid,
        pin_config=pin_config,
    )

    logger.info("NFC reader backend=%s count=%s interval=%.2f", args.backend, args.count, args.interval)

    for index in range(args.count):
        result = reader.read_once()
        payload = result.to_dict()
        if args.json:
            print(json.dumps(payload, ensure_ascii=False))
        else:
            logger.info("read_index=%s result=%s", index + 1, payload)
        time.sleep(args.interval)

    logger.info("NFC reader test finished")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
