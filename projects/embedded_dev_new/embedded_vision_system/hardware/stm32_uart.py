"""
STM32 串口执行器控制接口。

根据《上位机控制协议》通过 ASCII 指令控制：
- 舵机角度
- 步进电机 STEP 频率
- 电机使能
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import threading
from typing import Any, Callable, Optional


STATUS_PATTERN = re.compile(
    r"^OK\s+STATUS\s+SERVO=(?P<servo>\d+)\s+STEP=(?P<step>\d+)\s+ENABLE=(?P<enable>[01])$",
    re.IGNORECASE,
)


@dataclass
class STM32ControlStatus:
    """STM32 当前输出状态缓存。"""

    servo_angle: int
    step_hz: int
    enabled: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "servo_angle": self.servo_angle,
            "step_hz": self.step_hz,
            "enabled": self.enabled,
        }


class STM32SerialController:
    """通过串口发送协议命令并维护状态缓存。"""

    def __init__(
        self,
        port: str,
        baudrate: int = 115200,
        timeout: float = 1.0,
        serial_factory: Optional[Callable[..., Any]] = None,
        auto_query_status: bool = True,
    ):
        self.port = str(port)
        self.baudrate = int(baudrate)
        self.timeout = max(0.1, float(timeout))
        self._serial_factory = serial_factory
        self._serial = None
        self._lock = threading.Lock()
        self._status: Optional[STM32ControlStatus] = None

        if auto_query_status:
            self.query_status()

    def _open_serial(self):
        if self._serial is not None:
            return self._serial

        if self._serial_factory is not None:
            serial_port = self._serial_factory(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=8,
                parity="N",
                stopbits=1,
                timeout=self.timeout,
                write_timeout=self.timeout,
            )
        else:
            try:
                import serial
            except ImportError as exc:  # pragma: no cover - 板端环境提供
                raise RuntimeError("stm32_uart backend requires `pyserial` package") from exc

            serial_port = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=8,
                parity="N",
                stopbits=1,
                timeout=self.timeout,
                write_timeout=self.timeout,
            )

        if hasattr(serial_port, "reset_input_buffer"):
            serial_port.reset_input_buffer()
        if hasattr(serial_port, "reset_output_buffer"):
            serial_port.reset_output_buffer()

        self._serial = serial_port
        return self._serial

    def _readline(self) -> str:
        serial_port = self._open_serial()
        response = serial_port.readline()
        if isinstance(response, str):
            text = response.strip()
        else:
            text = bytes(response or b"").decode("ascii", errors="ignore").strip()
        if not text:
            raise RuntimeError("STM32 controller response timeout")
        if text.upper().startswith("ERR"):
            raise RuntimeError(text)
        if not text.upper().startswith("OK"):
            raise RuntimeError(f"Unexpected STM32 response: {text}")
        return text

    def send_command(self, command: str) -> str:
        payload = str(command).strip()
        if not payload:
            raise ValueError("command must not be empty")

        with self._lock:
            serial_port = self._open_serial()
            if hasattr(serial_port, "reset_input_buffer"):
                serial_port.reset_input_buffer()
            serial_port.write((payload + "\r\n").encode("ascii"))
            serial_port.flush()
            return self._readline()

    def _set_status(self, status: STM32ControlStatus) -> STM32ControlStatus:
        self._status = status
        return status

    def _require_status(self) -> STM32ControlStatus:
        if self._status is None:
            return self.query_status()
        return self._status

    @staticmethod
    def _parse_status_response(response: str) -> STM32ControlStatus:
        match = STATUS_PATTERN.match(response.strip())
        if not match:
            raise RuntimeError(f"Unexpected STM32 STATUS response: {response}")
        return STM32ControlStatus(
            servo_angle=int(match.group("servo")),
            step_hz=int(match.group("step")),
            enabled=match.group("enable") == "1",
        )

    def get_cached_status(self) -> Optional[STM32ControlStatus]:
        return self._status

    def query_status(self) -> STM32ControlStatus:
        response = self.send_command("STATUS")
        return self._set_status(self._parse_status_response(response))

    def get_help(self) -> str:
        return self.send_command("HELP")

    def set_servo(self, angle: int) -> STM32ControlStatus:
        angle = int(angle)
        if not (0 <= angle <= 180):
            raise ValueError("servo angle must be in 0..180")
        self.send_command(f"SERVO {angle}")
        current = self._require_status()
        return self._set_status(
            STM32ControlStatus(
                servo_angle=angle,
                step_hz=current.step_hz,
                enabled=current.enabled,
            )
        )

    def set_step(self, step_hz: int) -> STM32ControlStatus:
        step_hz = int(step_hz)
        if not (0 <= step_hz <= 20_000):
            raise ValueError("step frequency must be in 0..20000 Hz")
        self.send_command(f"STEP {step_hz}")
        current = self._require_status()
        return self._set_status(
            STM32ControlStatus(
                servo_angle=current.servo_angle,
                step_hz=step_hz,
                enabled=current.enabled,
            )
        )

    def set_enable(self, enabled: bool) -> STM32ControlStatus:
        enable_value = 1 if enabled else 0
        self.send_command(f"ENABLE {enable_value}")
        current = self._require_status()
        return self._set_status(
            STM32ControlStatus(
                servo_angle=current.servo_angle,
                step_hz=current.step_hz,
                enabled=bool(enabled),
            )
        )

    def set_outputs(self, servo_angle: int, step_hz: int, enabled: bool) -> STM32ControlStatus:
        servo_angle = int(servo_angle)
        step_hz = int(step_hz)
        enable_value = 1 if enabled else 0
        if not (0 <= servo_angle <= 180):
            raise ValueError("servo angle must be in 0..180")
        if not (0 <= step_hz <= 20_000):
            raise ValueError("step frequency must be in 0..20000 Hz")
        response = self.send_command(f"SET {servo_angle} {step_hz} {enable_value}")
        return self._set_status(self._parse_status_response(response))

    def stop_motor(self) -> STM32ControlStatus:
        current = self.get_cached_status()
        if current is None:
            current = self.query_status()
        return self.set_outputs(
            servo_angle=current.servo_angle,
            step_hz=0,
            enabled=False,
        )

    def close(self) -> None:
        with self._lock:
            if self._serial is None:
                return
            close_method = getattr(self._serial, "close", None)
            if callable(close_method):
                close_method()
            self._serial = None


class STM32ServoController:
    """舵机串口控制器。"""

    def __init__(
        self,
        client: STM32SerialController,
        normal_angle: int = 0,
        sort_angle: int = 90,
    ):
        self.client = client
        self.normal_angle = int(normal_angle)
        self.sort_angle = int(sort_angle)
        cached = self.client.get_cached_status()
        self.current_angle = (
            cached.servo_angle
            if cached is not None
            else self.normal_angle
        )

    def refresh_status(self) -> STM32ControlStatus:
        status = self.client.query_status()
        self.current_angle = status.servo_angle
        return status

    def set_angle(self, angle: int) -> bool:
        status = self.client.set_servo(int(angle))
        self.current_angle = status.servo_angle
        return True

    def normal_position(self) -> bool:
        return self.set_angle(self.normal_angle)

    def sort_position(self) -> bool:
        return self.set_angle(self.sort_angle)

    def get_current_angle(self) -> int:
        return int(self.current_angle)

    def cleanup(self) -> None:
        self.client.close()


class STM32StepperConveyorController:
    """步进电机串口控制器。"""

    def __init__(
        self,
        client: STM32SerialController,
        speed_mode: str = "percent",
        speed_range: tuple[int, int] = (0, 100),
        max_step_hz: int = 2000,
    ):
        self.client = client
        self.speed_mode = str(speed_mode)
        self.speed_range = tuple(speed_range)
        self.max_step_hz = int(max_step_hz)
        if self.speed_mode not in {"percent", "hz"}:
            raise ValueError(f"Unsupported speed_mode: {self.speed_mode}")
        if self.max_step_hz <= 0:
            raise ValueError("max_step_hz must be positive")

        cached = self.client.get_cached_status()
        if cached is None:
            self.current_step_hz = 0
            self.current_speed = 0
            self.enabled = False
        else:
            self._apply_status(cached)

    @property
    def state(self) -> str:
        return "运行" if self.enabled and self.current_step_hz > 0 else "停止"

    def _speed_to_step_hz(self, speed: int) -> int:
        speed = int(speed)
        if self.speed_mode == "hz":
            if not (0 <= speed <= 20_000):
                raise ValueError("step frequency must be in 0..20000 Hz")
            return speed

        minimum, maximum = self.speed_range
        if not (minimum <= speed <= maximum):
            raise ValueError(f"speed must be in {minimum}..{maximum}")
        if speed <= 0:
            return 0
        return int(round((float(speed) / float(maximum)) * float(self.max_step_hz)))

    def _step_hz_to_speed(self, step_hz: int) -> int:
        step_hz = int(step_hz)
        if self.speed_mode == "hz":
            return step_hz
        if step_hz <= 0:
            return 0
        minimum, maximum = self.speed_range
        mapped = int(round((float(step_hz) / float(self.max_step_hz)) * float(maximum)))
        return max(minimum, min(maximum, mapped))

    def _apply_status(self, status: STM32ControlStatus) -> None:
        self.current_step_hz = int(status.step_hz)
        self.enabled = bool(status.enabled)
        self.current_speed = self._step_hz_to_speed(status.step_hz)

    def refresh_status(self) -> STM32ControlStatus:
        status = self.client.query_status()
        self._apply_status(status)
        return status

    def start(self, speed: int = 50) -> bool:
        return self.set_speed(speed)

    def stop(self) -> bool:
        status = self.client.stop_motor()
        self._apply_status(status)
        return True

    def set_speed(self, speed: int) -> bool:
        step_hz = self._speed_to_step_hz(speed)
        if step_hz > 0:
            current = self.client.get_cached_status()
            if current is None:
                current = self.client.query_status()
            status = self.client.set_outputs(
                servo_angle=current.servo_angle,
                step_hz=step_hz,
                enabled=True,
            )
        else:
            status = self.client.stop_motor()
        self._apply_status(status)
        self.current_speed = int(speed)
        self.current_step_hz = int(step_hz)
        self.enabled = step_hz > 0
        return True

    def get_status(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "enabled": self.enabled,
            "speed": self.current_speed,
            "step_hz": self.current_step_hz,
            "speed_mode": self.speed_mode,
        }

    def cleanup(self) -> None:
        self.client.close()


__all__ = [
    "STM32ControlStatus",
    "STM32SerialController",
    "STM32ServoController",
    "STM32StepperConveyorController",
]
