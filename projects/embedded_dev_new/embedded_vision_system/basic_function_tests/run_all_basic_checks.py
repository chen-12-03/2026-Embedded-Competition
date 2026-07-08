#!/usr/bin/env python3
"""
基础功能测试总入口

这个脚本不直接替你跑所有硬件测试，而是做环境检查并打印推荐命令，
避免在板端没有摄像头/模型/NFC/PWM 权限时一口气失败。
"""

import logging
from pathlib import Path


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    force=True,
)
logger = logging.getLogger("run_all_basic_checks")


def main() -> int:
    root = Path(__file__).resolve().parent
    logger.info("基础功能测试目录: %s", root)
    logger.info("推荐按顺序执行以下测试：")
    logger.info("1. 摄像头显示回传:")
    logger.info("   python3 -m embedded_vision_system.basic_function_tests.test_camera_preview --camera /dev/video0")
    logger.info("   无显示器时可用网页预览:")
    logger.info("   python3 -m embedded_vision_system.basic_function_tests.test_camera_preview_web --camera /dev/video52 --host 0.0.0.0 --port 8081")
    logger.info("2. 摄像头颜色 + 形状识别:")
    logger.info("   python3 -m embedded_vision_system.basic_function_tests.test_camera_shape_color --camera /dev/video52")
    logger.info("   无显示器时可用网页识别预览:")
    logger.info("   python3 -m embedded_vision_system.basic_function_tests.test_camera_shape_color_web --camera /dev/video52 --host 0.0.0.0 --port 8082")
    logger.info("3. RKNN 摄像头分类:")
    logger.info("   python3 -m embedded_vision_system.basic_function_tests.test_camera_classification --model ./rknnModel/best.rknn --camera /dev/video0")
    logger.info("4. NFC 读取:")
    logger.info("   python3 -m embedded_vision_system.basic_function_tests.test_nfc_reader --backend mock")
    logger.info("5. STM32 UART 控制:")
    logger.info("   python3 -m embedded_vision_system.basic_function_tests.test_stm32_uart --port /dev/ttyS5 --status-only")
    logger.info("6. PWM 控制:")
    logger.info("   python3 -m embedded_vision_system.basic_function_tests.test_pwm_control --backend sysfs --chip 0 --channel 0")
    logger.info("如果板端只有部分模块接好，就先单独跑对应脚本。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
