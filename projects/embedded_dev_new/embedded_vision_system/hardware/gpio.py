"""
共享 GPIO 硬件接口。

当前主要用于：
- 软件 PWM 输出
- 使能脚高低电平控制
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Optional


class BaseGPIOOutput:
    """GPIO 输出基础接口。"""

    def high(self):
        raise NotImplementedError

    def low(self):
        raise NotImplementedError

    def cleanup(self):
        pass


class MockGPIOOutput(BaseGPIOOutput):
    """内存型 GPIO 输出，用于测试。"""

    def __init__(self):
        self.value = 0

    def high(self):
        self.value = 1

    def low(self):
        self.value = 0


class SysfsGPIOOutput(BaseGPIOOutput):
    """Linux sysfs GPIO 输出。"""

    def __init__(self, gpio_number: int):
        self.gpio_number = int(gpio_number)
        self.base_path = Path("/sys/class/gpio")
        self.gpio_path = self.base_path / f"gpio{self.gpio_number}"
        self._export_if_needed()
        self._write("direction", "out")

    def _export_if_needed(self):
        if self.gpio_path.exists():
            return
        (self.base_path / "export").write_text(str(self.gpio_number), encoding="utf-8")
        for _ in range(20):
            if self.gpio_path.exists():
                return
            time.sleep(0.05)
        raise RuntimeError(f"Failed to export GPIO line: gpio={self.gpio_number}")

    def _write(self, name: str, value: str):
        (self.gpio_path / name).write_text(value, encoding="utf-8")

    def high(self):
        self._write("value", "1")

    def low(self):
        self._write("value", "0")


def create_gpio_output(backend: str, gpio_number: Optional[int]) -> BaseGPIOOutput:
    """创建 GPIO 输出。"""
    if backend == "mock":
        return MockGPIOOutput()
    if backend == "sysfs":
        if gpio_number is None:
            raise ValueError("sysfs gpio backend requires gpio_number")
        return SysfsGPIOOutput(gpio_number=gpio_number)
    raise ValueError(f"Unsupported GPIO backend: {backend}")


class SoftwarePWMGPIOBackend:
    """
    使用 GPIO 软件模拟 PWM。

    说明：
    - 适合低速演示，不适合高精度实时控制
    - 可选带一个 enable GPIO，便于驱动器使能
    """

    def __init__(
        self,
        signal_gpio: BaseGPIOOutput,
        enable_gpio: Optional[BaseGPIOOutput] = None,
        idle_low: bool = True,
    ):
        self.signal_gpio = signal_gpio
        self.enable_gpio = enable_gpio
        self.idle_low = bool(idle_low)
        self.enabled = False
        self.period_ns = 20_000_000
        self.duty_cycle_ns = 0
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread = threading.Thread(
            target=self._pwm_loop,
            name="gpio-software-pwm",
            daemon=True,
        )
        self._thread.start()

    def enable(self):
        with self._lock:
            self.enabled = True
        if self.enable_gpio is not None:
            self.enable_gpio.high()

    def disable(self):
        with self._lock:
            self.enabled = False
        if self.enable_gpio is not None:
            self.enable_gpio.low()
        self.signal_gpio.low()

    def set_period_ns(self, period_ns: int):
        with self._lock:
            self.period_ns = max(1_000_000, int(period_ns))

    def set_duty_cycle_ns(self, duty_cycle_ns: int):
        with self._lock:
            self.duty_cycle_ns = max(0, int(duty_cycle_ns))

    def cleanup(self):
        self._stop_event.set()
        self._thread.join(timeout=1.0)
        self.disable()
        self.signal_gpio.cleanup()
        if self.enable_gpio is not None:
            self.enable_gpio.cleanup()

    def _snapshot(self):
        with self._lock:
            return self.enabled, self.period_ns, self.duty_cycle_ns

    def _pwm_loop(self):
        while not self._stop_event.is_set():
            enabled, period_ns, duty_ns = self._snapshot()

            if not enabled:
                if self.idle_low:
                    self.signal_gpio.low()
                if self._stop_event.wait(0.005):
                    break
                continue

            if duty_ns <= 0:
                self.signal_gpio.low()
                if self._stop_event.wait(min(period_ns / 1_000_000_000.0, 0.02)):
                    break
                continue

            if duty_ns >= period_ns:
                self.signal_gpio.high()
                if self._stop_event.wait(min(period_ns / 1_000_000_000.0, 0.02)):
                    break
                continue

            high_seconds = duty_ns / 1_000_000_000.0
            low_seconds = max(0.0, (period_ns - duty_ns) / 1_000_000_000.0)

            self.signal_gpio.high()
            if self._stop_event.wait(high_seconds):
                break
            self.signal_gpio.low()
            if self._stop_event.wait(low_seconds):
                break


__all__ = [
    "BaseGPIOOutput",
    "MockGPIOOutput",
    "SysfsGPIOOutput",
    "create_gpio_output",
    "SoftwarePWMGPIOBackend",
]
