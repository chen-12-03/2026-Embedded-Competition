"""
MPU6050 IMU / vibration sensor support.

The class keeps the hardware access small and explicit so it can be used both
from basic bring-up tests and from the device health monitor later.
"""

from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass
from typing import Optional, Tuple

from .sensors import SensorReading


MPU6050_DEFAULT_ADDRESS = 0x68
MPU6050_ALT_ADDRESS = 0x69

REG_SMPLRT_DIV = 0x19
REG_CONFIG = 0x1A
REG_GYRO_CONFIG = 0x1B
REG_ACCEL_CONFIG = 0x1C
REG_ACCEL_XOUT_H = 0x3B
REG_TEMP_OUT_H = 0x41
REG_GYRO_XOUT_H = 0x43
REG_PWR_MGMT_1 = 0x6B
REG_WHO_AM_I = 0x75

ACCEL_SCALES = {
    2: (0x00, 16384.0),
    4: (0x08, 8192.0),
    8: (0x10, 4096.0),
    16: (0x18, 2048.0),
}

GYRO_SCALES = {
    250: (0x00, 131.0),
    500: (0x08, 65.5),
    1000: (0x10, 32.8),
    2000: (0x18, 16.4),
}


@dataclass
class MPU6050Reading:
    """One decoded MPU6050 sample."""

    accel_x_g: float
    accel_y_g: float
    accel_z_g: float
    gyro_x_dps: float
    gyro_y_dps: float
    gyro_z_dps: float
    temperature_c: float
    vibration_g: float
    timestamp: float

    def to_dict(self) -> dict:
        return asdict(self)


class MPU6050:
    """Linux I2C MPU6050 reader based on smbus2."""

    def __init__(
        self,
        bus_id: int = 1,
        address: int = MPU6050_DEFAULT_ADDRESS,
        accel_range_g: int = 2,
        gyro_range_dps: int = 250,
        sample_rate_divider: int = 7,
        dlpf_config: int = 3,
        bus: Optional[object] = None,
    ):
        if accel_range_g not in ACCEL_SCALES:
            raise ValueError(f"unsupported accel range: {accel_range_g}g")
        if gyro_range_dps not in GYRO_SCALES:
            raise ValueError(f"unsupported gyro range: {gyro_range_dps}dps")

        self.bus_id = int(bus_id)
        self.address = int(address)
        self.accel_range_g = int(accel_range_g)
        self.gyro_range_dps = int(gyro_range_dps)
        self.sample_rate_divider = int(sample_rate_divider)
        self.dlpf_config = int(dlpf_config) & 0x07
        self._external_bus = bus is not None
        self._bus = bus
        self._accel_scale = ACCEL_SCALES[self.accel_range_g][1]
        self._gyro_scale = GYRO_SCALES[self.gyro_range_dps][1]

    def open(self) -> None:
        if self._bus is None:
            try:
                from smbus2 import SMBus
            except ImportError as exc:  # pragma: no cover - depends on board env
                raise RuntimeError("mpu6050 backend requires `smbus2` package") from exc
            self._bus = SMBus(self.bus_id)
        self.initialize()

    def initialize(self) -> None:
        self._require_bus()
        self._write_byte(REG_PWR_MGMT_1, 0x00)
        time.sleep(0.05)
        self._write_byte(REG_SMPLRT_DIV, self.sample_rate_divider & 0xFF)
        self._write_byte(REG_CONFIG, self.dlpf_config)
        self._write_byte(REG_ACCEL_CONFIG, ACCEL_SCALES[self.accel_range_g][0])
        self._write_byte(REG_GYRO_CONFIG, GYRO_SCALES[self.gyro_range_dps][0])

    def who_am_i(self) -> int:
        if self._bus is None:
            self.open()
        self._require_bus()
        return self._read_byte(REG_WHO_AM_I)

    def read(self) -> MPU6050Reading:
        if self._bus is None:
            self.open()
        self._require_bus()
        data = self._read_block(REG_ACCEL_XOUT_H, 14)
        accel_x_raw = self._decode_i16(data[0], data[1])
        accel_y_raw = self._decode_i16(data[2], data[3])
        accel_z_raw = self._decode_i16(data[4], data[5])
        temp_raw = self._decode_i16(data[6], data[7])
        gyro_x_raw = self._decode_i16(data[8], data[9])
        gyro_y_raw = self._decode_i16(data[10], data[11])
        gyro_z_raw = self._decode_i16(data[12], data[13])

        accel = (
            accel_x_raw / self._accel_scale,
            accel_y_raw / self._accel_scale,
            accel_z_raw / self._accel_scale,
        )
        gyro = (
            gyro_x_raw / self._gyro_scale,
            gyro_y_raw / self._gyro_scale,
            gyro_z_raw / self._gyro_scale,
        )
        magnitude = math.sqrt(sum(axis * axis for axis in accel))
        vibration_g = abs(magnitude - 1.0)

        return MPU6050Reading(
            accel_x_g=accel[0],
            accel_y_g=accel[1],
            accel_z_g=accel[2],
            gyro_x_dps=gyro[0],
            gyro_y_dps=gyro[1],
            gyro_z_dps=gyro[2],
            temperature_c=(temp_raw / 340.0) + 36.53,
            vibration_g=vibration_g,
            timestamp=time.time(),
        )

    def read_vibration(self) -> SensorReading:
        """Return vibration as a generic health-monitor SensorReading."""
        sample = self.read()
        return SensorReading(sensor_type="vibration", value=sample.vibration_g, timestamp=sample.timestamp)

    def read_accel_tuple(self) -> Tuple[float, float, float]:
        sample = self.read()
        return sample.accel_x_g, sample.accel_y_g, sample.accel_z_g

    def close(self) -> None:
        if self._bus is not None and not self._external_bus:
            close = getattr(self._bus, "close", None)
            if callable(close):
                close()
        if not self._external_bus:
            self._bus = None

    def __enter__(self) -> "MPU6050":
        self.open()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _require_bus(self) -> None:
        if self._bus is None:
            raise RuntimeError("MPU6050 bus is not open; call open() first")

    def _write_byte(self, register: int, value: int) -> None:
        self._bus.write_byte_data(self.address, register, value & 0xFF)

    def _read_byte(self, register: int) -> int:
        return int(self._bus.read_byte_data(self.address, register))

    def _read_block(self, register: int, length: int) -> list:
        return list(self._bus.read_i2c_block_data(self.address, register, length))

    @staticmethod
    def _decode_i16(high: int, low: int) -> int:
        value = ((high & 0xFF) << 8) | (low & 0xFF)
        return value - 0x10000 if value & 0x8000 else value


class MPU6050VibrationSensor(MPU6050):
    """Adapter compatible with DeviceController vibration sensor expectations."""

    def __init__(
        self,
        *args,
        yellow_threshold: float = 0.18,
        red_threshold: float = 0.35,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.yellow_threshold = float(yellow_threshold)
        self.red_threshold = float(red_threshold)
        self.readings = []
        self.max_history = 100

    def read(self) -> SensorReading:
        sample = super().read()
        reading = SensorReading(
            sensor_type="vibration",
            value=sample.vibration_g,
            timestamp=sample.timestamp,
        )
        self.readings.append(reading)
        if len(self.readings) > self.max_history:
            self.readings.pop(0)
        return reading

    def read_vibration(self) -> SensorReading:
        return self.read()

    def get_average(self) -> float:
        if not self.readings:
            return 0.0
        return sum(item.value for item in self.readings) / len(self.readings)

    def classify(self, value: float):
        from embedded_vision_system.device_controller import HealthLevel

        if value >= self.red_threshold:
            return HealthLevel.RED
        if value >= self.yellow_threshold:
            return HealthLevel.YELLOW
        return HealthLevel.GREEN


__all__ = [
    "MPU6050",
    "MPU6050Reading",
    "MPU6050VibrationSensor",
    "MPU6050_DEFAULT_ADDRESS",
    "MPU6050_ALT_ADDRESS",
]
