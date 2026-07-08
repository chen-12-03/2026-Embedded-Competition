"""
STM32 串口控制器测试。
"""

from embedded_vision_system.device_controller import DeviceController, build_device_controller
from embedded_vision_system.hardware import (
    STM32SerialController,
    STM32ServoController,
    STM32StepperConveyorController,
)


class _FakeSerial:
    def __init__(self, responses):
        self.responses = [
            item if isinstance(item, bytes) else str(item).encode("ascii")
            for item in responses
        ]
        self.writes = []
        self.flush_count = 0
        self.input_reset_count = 0
        self.output_reset_count = 0
        self.closed = False

    def reset_input_buffer(self):
        self.input_reset_count += 1

    def reset_output_buffer(self):
        self.output_reset_count += 1

    def write(self, payload: bytes):
        self.writes.append(bytes(payload))
        return len(payload)

    def flush(self):
        self.flush_count += 1

    def readline(self):
        if not self.responses:
            return b""
        return self.responses.pop(0)

    def close(self):
        self.closed = True


def test_stm32_serial_controller_queries_status():
    fake_serial = _FakeSerial(
        [
            b"OK STATUS SERVO=90 STEP=1000 ENABLE=1\r\n",
        ]
    )
    controller = STM32SerialController(
        port="/dev/ttyS1",
        serial_factory=lambda **kwargs: fake_serial,
        auto_query_status=False,
    )

    status = controller.query_status()

    assert fake_serial.writes == [b"STATUS\r\n"]
    assert status.servo_angle == 90
    assert status.step_hz == 1000
    assert status.enabled is True


def test_stm32_conveyor_percent_mapping_and_stop():
    fake_serial = _FakeSerial(
        [
            b"OK STATUS SERVO=90 STEP=0 ENABLE=0\r\n",
            b"OK STATUS SERVO=90 STEP=1000 ENABLE=1\r\n",
            b"OK STATUS SERVO=90 STEP=0 ENABLE=0\r\n",
        ]
    )
    controller = STM32SerialController(
        port="/dev/ttyS1",
        serial_factory=lambda **kwargs: fake_serial,
    )
    conveyor = STM32StepperConveyorController(
        client=controller,
        speed_mode="percent",
        max_step_hz=2000,
    )

    assert conveyor.start(50) is True
    assert conveyor.current_speed == 50
    assert conveyor.current_step_hz == 1000
    assert conveyor.enabled is True
    assert conveyor.get_status()["state"] == "运行"

    assert conveyor.stop() is True
    assert conveyor.current_speed == 0
    assert conveyor.current_step_hz == 0
    assert conveyor.enabled is False
    assert conveyor.get_status()["state"] == "停止"
    assert fake_serial.writes == [
        b"STATUS\r\n",
        b"SET 90 1000 1\r\n",
        b"SET 90 0 0\r\n",
    ]


def test_device_controller_startup_check_catches_component_errors():
    controller = DeviceController()
    controller.set_component_check("boom", lambda: 1 / 0)

    result = controller.startup_check()

    assert result["boom"]["ok"] is False
    assert "ZeroDivisionError" in result["boom"]["message"]


def test_build_device_controller_supports_stm32_uart_backend():
    fake_serial = _FakeSerial(
        [
            b"OK SERVO=0\r\n",
            b"OK STATUS SERVO=0 STEP=0 ENABLE=0\r\n",
            b"OK STATUS SERVO=0 STEP=1000 ENABLE=1\r\n",
            b"OK STATUS SERVO=0 STEP=0 ENABLE=0\r\n",
            b"OK SERVO=0\r\n",
        ]
    )
    controller = build_device_controller(
        servo_backend="stm32_uart",
        conveyor_backend="stm32_uart",
        servo_normal_angle=0,
        servo_sort_angle=90,
        default_conveyor_speed=50,
        conveyor_speed_mode="percent",
        conveyor_step_max_hz=2000,
        sort_prepare_pause=0.3,
        sort_servo_settle_time=0.4,
        sort_conveyor_advance_time=0.8,
        serial_factory=lambda **kwargs: fake_serial,
    )

    assert isinstance(controller.servo, STM32ServoController)
    assert isinstance(controller.conveyor, STM32StepperConveyorController)
    assert controller.get_sort_timing()["conveyor_advance_time"] == 0.8
    assert controller.start(skip_check=True, speed=50) is True
    assert controller.conveyor.current_step_hz == 1000
    assert controller.conveyor.enabled is True

    assert controller.stop() is True
    assert controller.conveyor.current_step_hz == 0
    assert controller.conveyor.enabled is False
    assert fake_serial.writes == [
        b"SERVO 0\r\n",
        b"STATUS\r\n",
        b"SET 0 1000 1\r\n",
        b"SET 0 0 0\r\n",
        b"SERVO 0\r\n",
    ]


def test_stm32_conveyor_start_preserves_current_servo_angle():
    fake_serial = _FakeSerial(
        [
            b"OK STATUS SERVO=45 STEP=0 ENABLE=0\r\n",
            b"OK STATUS SERVO=45 STEP=100 ENABLE=1\r\n",
        ]
    )
    controller = STM32SerialController(
        port="/dev/ttyS1",
        serial_factory=lambda **kwargs: fake_serial,
    )
    conveyor = STM32StepperConveyorController(
        client=controller,
        speed_mode="hz",
        max_step_hz=100,
    )

    assert conveyor.start(100) is True
    assert conveyor.current_speed == 100
    assert conveyor.current_step_hz == 100
    assert conveyor.enabled is True
    assert fake_serial.writes == [
        b"STATUS\r\n",
        b"SET 45 100 1\r\n",
    ]
