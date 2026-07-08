"""
共享 PWM 硬件接口
"""

from __future__ import annotations

import time
from pathlib import Path


def angle_to_duty_cycle_ns(
    angle: float,
    period_ns: int = 20_000_000,
    min_pulse_ns: int = 1_000_000,
    max_pulse_ns: int = 2_000_000,
) -> int:
    """将舵机角度映射为占空比。"""
    clamped = max(0.0, min(180.0, float(angle)))
    pulse_range = max_pulse_ns - min_pulse_ns
    pulse_width = min_pulse_ns + int((clamped / 180.0) * pulse_range)
    return min(pulse_width, period_ns)


def percent_to_duty_cycle_ns(percent: float, period_ns: int) -> int:
    """将百分比映射为占空比。"""
    clamped = max(0.0, min(100.0, float(percent)))
    return int(period_ns * (clamped / 100.0))


class BasePWMBackend:
    """PWM 后端基础接口。"""

    def enable(self):
        raise NotImplementedError

    def disable(self):
        raise NotImplementedError

    def set_period_ns(self, period_ns: int):
        raise NotImplementedError

    def set_duty_cycle_ns(self, duty_cycle_ns: int):
        raise NotImplementedError

    def cleanup(self):
        pass


class MockPWMBackend(BasePWMBackend):
    """打印型/内存型 PWM 模拟后端。"""

    def __init__(self):
        self.enabled = False
        self.period_ns = 20_000_000
        self.duty_cycle_ns = 0

    def enable(self):
        self.enabled = True

    def disable(self):
        self.enabled = False

    def set_period_ns(self, period_ns: int):
        self.period_ns = period_ns

    def set_duty_cycle_ns(self, duty_cycle_ns: int):
        self.duty_cycle_ns = duty_cycle_ns


class SysfsPWMBackend(BasePWMBackend):
    """Linux sysfs PWM 后端。"""

    def __init__(self, chip: int, channel: int):
        self.chip = chip
        self.channel = channel
        self.base_path = Path(f"/sys/class/pwm/pwmchip{chip}")
        self.channel_path = self.base_path / f"pwm{channel}"
        self._export_if_needed()

    def _export_if_needed(self):
        if self.channel_path.exists():
            return
        (self.base_path / "export").write_text(str(self.channel), encoding="utf-8")
        for _ in range(20):
            if self.channel_path.exists():
                return
            time.sleep(0.05)
        raise RuntimeError(f"Failed to export PWM channel: chip={self.chip}, channel={self.channel}")

    def _write(self, name: str, value: str):
        (self.channel_path / name).write_text(value, encoding="utf-8")

    def enable(self):
        self._write("enable", "1")

    def disable(self):
        self._write("enable", "0")

    def set_period_ns(self, period_ns: int):
        self._write("period", str(period_ns))

    def set_duty_cycle_ns(self, duty_cycle_ns: int):
        self._write("duty_cycle", str(duty_cycle_ns))

    def cleanup(self):
        try:
            self.disable()
        except Exception:
            pass


def create_pwm_backend(backend: str, chip: int, channel: int) -> BasePWMBackend:
    """创建共享 PWM backend。"""
    if backend == "mock":
        return MockPWMBackend()
    if backend == "sysfs":
        return SysfsPWMBackend(chip=chip, channel=channel)
    raise ValueError(f"Unsupported PWM backend: {backend}")


class ServoPWMController:
    """共享舵机控制器。"""

    def __init__(
        self,
        backend: BasePWMBackend | None = None,
        gpio_pin: int = 17,
        pwm_freq: int = 50,
        period_ns: int = 20_000_000,
        response_delay: float = 0.1,
        normal_angle: int = 0,
        sort_angle: int = 90,
    ):
        self.backend = backend or MockPWMBackend()
        self.gpio_pin = gpio_pin
        self.pwm_freq = pwm_freq
        self.period_ns = period_ns
        self.response_delay = response_delay
        self.normal_angle = int(normal_angle)
        self.sort_angle = int(sort_angle)
        self.current_angle = self.normal_angle

    def set_angle(self, angle: int) -> bool:
        if not (0 <= angle <= 180):
            return False
        duty_ns = angle_to_duty_cycle_ns(angle, period_ns=self.period_ns)
        self.backend.set_period_ns(self.period_ns)
        self.backend.enable()
        self.backend.set_duty_cycle_ns(duty_ns)
        self.current_angle = int(angle)
        time.sleep(self.response_delay)
        return True

    def normal_position(self) -> bool:
        return self.set_angle(self.normal_angle)

    def sort_position(self) -> bool:
        return self.set_angle(self.sort_angle)

    def get_current_angle(self) -> int:
        return self.current_angle

    def cleanup(self):
        self.backend.disable()
        self.backend.cleanup()


class ConveyorPWMController:
    """共享传送带 PWM 控制器。"""

    def __init__(
        self,
        backend: BasePWMBackend | None = None,
        pwm_pin: int = 27,
        speed_range: tuple = (0, 100),
        period_ns: int = 20_000_000,
    ):
        self.backend = backend or MockPWMBackend()
        self.pwm_pin = pwm_pin
        self.speed_range = speed_range
        self.period_ns = period_ns
        self.current_speed = 0
        self.enabled = False

    def start(self, speed: int = 50) -> bool:
        return self.set_speed(speed)

    def stop(self) -> bool:
        self.current_speed = 0
        self.enabled = False
        self.backend.set_period_ns(self.period_ns)
        self.backend.set_duty_cycle_ns(0)
        self.backend.disable()
        return True

    def set_speed(self, speed: int) -> bool:
        if not (self.speed_range[0] <= speed <= self.speed_range[1]):
            return False
        duty_ns = percent_to_duty_cycle_ns(speed, period_ns=self.period_ns)
        self.backend.set_period_ns(self.period_ns)
        if speed > 0:
            self.backend.enable()
            self.enabled = True
        else:
            self.backend.disable()
            self.enabled = False
        self.backend.set_duty_cycle_ns(duty_ns)
        self.current_speed = int(speed)
        return True

    def get_status(self) -> dict:
        return {
            "enabled": self.enabled,
            "speed": self.current_speed,
        }

    def cleanup(self):
        self.stop()
        self.backend.cleanup()
