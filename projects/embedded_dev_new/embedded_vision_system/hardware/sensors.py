"""
共享传感器接口
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Optional


@dataclass
class SensorReading:
    """传感器读数。"""

    sensor_type: str
    value: float
    timestamp: float = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = time.time()


class _BaseMockAnalogSensor:
    """共享模拟传感器基础类。"""

    def __init__(self, sensor_type: str):
        self.sensor_type = sensor_type
        self.readings = []
        self.max_history = 100
        self._next_value: Optional[float] = None

    def inject(self, value: float):
        self._next_value = float(value)

    def _record(self, value: float) -> SensorReading:
        reading = SensorReading(sensor_type=self.sensor_type, value=float(value))
        self.readings.append(reading)
        if len(self.readings) > self.max_history:
            self.readings.pop(0)
        return reading

    def get_average(self) -> float:
        if not self.readings:
            return 0.0
        return sum(item.value for item in self.readings) / len(self.readings)


class MockVibrationSensor(_BaseMockAnalogSensor):
    """共享模拟振动传感器。"""

    def __init__(self, adc_channel: int = 0, yellow_threshold: float = 0.45, red_threshold: float = 0.65):
        super().__init__(sensor_type="vibration")
        self.adc_channel = adc_channel
        self.yellow_threshold = yellow_threshold
        self.red_threshold = red_threshold

    def read(self) -> SensorReading:
        value = self._next_value if self._next_value is not None else random.uniform(0.10, 0.35)
        self._next_value = None
        return self._record(value)


class MockCurrentSensor(_BaseMockAnalogSensor):
    """共享模拟电流传感器。"""

    def __init__(
        self,
        adc_channel: int = 1,
        normal_range: tuple = (0.5, 2.0),
        yellow_margin: float = 0.25,
        red_margin: float = 0.5,
    ):
        super().__init__(sensor_type="current")
        self.adc_channel = adc_channel
        self.normal_range = normal_range
        self.yellow_margin = yellow_margin
        self.red_margin = red_margin

    def read(self) -> SensorReading:
        value = (
            self._next_value
            if self._next_value is not None
            else random.uniform(self.normal_range[0], self.normal_range[1])
        )
        self._next_value = None
        return self._record(value)
