"""
共享硬件模块

这一层给“基础功能测试脚本”和“完整系统”共同复用。
"""

from .nfc import (
    NFCReadResult,
    BaseNFCReader,
    MockNFCReader,
    FileNFCReader,
    CommandNFCReader,
    PN532PinConfig,
    PN532I2CTransport,
    PN532SPITransport,
    PN532UARTTransport,
    PN532NFCReader,
    extract_text_from_payload,
    extract_material_id_from_payload,
    has_readable_text_payload,
    is_uid_fallback_payload,
    create_nfc_reader,
)
from .pwm import (
    BasePWMBackend,
    MockPWMBackend,
    SysfsPWMBackend,
    ServoPWMController,
    ConveyorPWMController,
    create_pwm_backend,
    angle_to_duty_cycle_ns,
    percent_to_duty_cycle_ns,
)
from .gpio import (
    BaseGPIOOutput,
    MockGPIOOutput,
    SysfsGPIOOutput,
    create_gpio_output,
    SoftwarePWMGPIOBackend,
)
from .stm32_uart import (
    STM32ControlStatus,
    STM32SerialController,
    STM32ServoController,
    STM32StepperConveyorController,
)
from .sensors import (
    SensorReading,
    MockVibrationSensor,
    MockCurrentSensor,
)
from .mpu6050 import (
    MPU6050,
    MPU6050Reading,
    MPU6050VibrationSensor,
    MPU6050_DEFAULT_ADDRESS,
    MPU6050_ALT_ADDRESS,
)

__all__ = [
    "NFCReadResult",
    "BaseNFCReader",
    "MockNFCReader",
    "FileNFCReader",
    "CommandNFCReader",
    "PN532PinConfig",
    "PN532I2CTransport",
    "PN532SPITransport",
    "PN532UARTTransport",
    "PN532NFCReader",
    "extract_text_from_payload",
    "extract_material_id_from_payload",
    "has_readable_text_payload",
    "is_uid_fallback_payload",
    "create_nfc_reader",
    "BasePWMBackend",
    "MockPWMBackend",
    "SysfsPWMBackend",
    "ServoPWMController",
    "ConveyorPWMController",
    "create_pwm_backend",
    "angle_to_duty_cycle_ns",
    "percent_to_duty_cycle_ns",
    "BaseGPIOOutput",
    "MockGPIOOutput",
    "SysfsGPIOOutput",
    "create_gpio_output",
    "SoftwarePWMGPIOBackend",
    "STM32ControlStatus",
    "STM32SerialController",
    "STM32ServoController",
    "STM32StepperConveyorController",
    "SensorReading",
    "MockVibrationSensor",
    "MockCurrentSensor",
    "MPU6050",
    "MPU6050Reading",
    "MPU6050VibrationSensor",
    "MPU6050_DEFAULT_ADDRESS",
    "MPU6050_ALT_ADDRESS",
]
