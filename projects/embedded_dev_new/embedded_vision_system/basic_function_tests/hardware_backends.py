"""
基础功能测试硬件后端兼容层

这里不再维护独立实现，而是直接复用 `embedded_vision_system.hardware`。
这样基础验证脚本和完整系统共享同一套底层代码。
"""

from embedded_vision_system.hardware import (
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
    extract_material_id_from_payload,
    BasePWMBackend,
    MockPWMBackend,
    SysfsPWMBackend,
    create_nfc_reader,
    create_pwm_backend,
    angle_to_duty_cycle_ns,
    percent_to_duty_cycle_ns,
    BaseGPIOOutput,
    MockGPIOOutput,
    SysfsGPIOOutput,
    create_gpio_output,
    SoftwarePWMGPIOBackend,
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
    "extract_material_id_from_payload",
    "BasePWMBackend",
    "MockPWMBackend",
    "SysfsPWMBackend",
    "create_nfc_reader",
    "create_pwm_backend",
    "angle_to_duty_cycle_ns",
    "percent_to_duty_cycle_ns",
    "BaseGPIOOutput",
    "MockGPIOOutput",
    "SysfsGPIOOutput",
    "create_gpio_output",
    "SoftwarePWMGPIOBackend",
]
