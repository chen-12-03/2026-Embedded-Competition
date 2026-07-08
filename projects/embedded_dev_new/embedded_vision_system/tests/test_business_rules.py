"""
业务规则测试
这些测试不依赖摄像头或 RKNN，适合在开发机做快速校验
"""

import types

from embedded_vision_system.consistency_engine import (
    ComparisonStatus,
    ConsistencyEngine,
    EnhancedSortingDecisionEngine,
)
from embedded_vision_system.device_controller import DeviceController, build_device_controller
from embedded_vision_system.hardware import extract_material_id_from_payload, extract_text_from_payload
from embedded_vision_system.hardware import MockGPIOOutput, SoftwarePWMGPIOBackend
from embedded_vision_system.hardware.mpu6050 import (
    MPU6050,
    MPU6050VibrationSensor,
    REG_ACCEL_XOUT_H,
    REG_WHO_AM_I,
)
from embedded_vision_system.hardware.nfc import BasePN532Transport, PN532I2CTransport, PN532NFCReader
from embedded_vision_system.order_manager import (
    normalize_color,
    normalize_material_type,
    normalize_shape,
)


def test_normalization_helpers():
    assert normalize_material_type("wood") == "木质件"
    assert normalize_material_type("plastic") == "塑料块"
    assert normalize_material_type("纸盒") == "纸盒"
    assert normalize_color("blue") == "蓝色"
    assert normalize_color("purple") == "紫色"
    assert normalize_color("红色") == "红色"
    assert normalize_shape("square") == "正方形"
    assert normalize_shape("cone") == "圆锥形"
    assert normalize_shape("三角形") == "三角形"


def test_material_id_can_be_extracted_from_json_payload():
    payload = b"\x03en{\"material_id\":\"MAT888\"}\x00\x00"
    assert extract_material_id_from_payload(payload) == "MAT888"
    assert extract_text_from_payload(payload) == '{"material_id":"MAT888"}'


def test_material_id_can_be_extracted_from_plain_text_payload():
    payload = b"\x04enMAT777\xff\xff"
    assert extract_material_id_from_payload(payload) == "MAT777"
    assert extract_text_from_payload(payload) == "MAT777"


def test_ndef_text_payload_can_be_extracted():
    payload = bytes.fromhex("0310D1010C5402656E48656C6C6F204E4643FE")
    assert extract_text_from_payload(payload) == "Hello NFC"


class _DummyPN532Transport(BasePN532Transport):
    interface = "mock"

    def wait_ready(self, timeout: float) -> bool:
        del timeout
        return True

    def write_frame(self, frame: bytes) -> None:
        del frame

    def read_data(self, size: int) -> bytes:
        raise AssertionError(f"unexpected transport read: {size}")


def test_official_mifare_flow_reads_material_id_from_block4_series():
    reader = PN532NFCReader(transport=_DummyPN532Transport())

    reader._mifare_authenticate = lambda target_number, block, uid, key: (  # type: ignore[method-assign]
        target_number == 1 and block == 4 and uid == b"\x01\x02\x03\x04" and key == b"\xFF" * 6
    )

    block_payloads = {
        4: b"MAT001".ljust(16, b"\x00"),
        5: b"".ljust(16, b"\x00"),
        6: b"".ljust(16, b"\x00"),
        7: b"".ljust(16, b"\x00"),
    }
    reader._mifare_read_block = lambda target_number, block: block_payloads.get(block)  # type: ignore[method-assign]

    tag_data = reader._read_tag_data_from_target(
        {"target_number": 1, "uid_length": 4, "uid": b"\x01\x02\x03\x04"}
    )
    assert tag_data["material_id"] == "MAT001"
    assert tag_data["text"] == "MAT001"


def test_pn532_initialization_matches_official_flow():
    reader = PN532NFCReader(transport=_DummyPN532Transport())
    calls = []

    def fake_call(command, data=b"", response_timeout=None):
        del response_timeout
        calls.append((command, bytes(data)))
        if command == 0x02:
            return bytes([0x32, 0x01, 0x06, 0x07])
        if command == 0x14:
            return bytes([0x15])
        if command == 0x32:
            return bytes([0x33])
        raise AssertionError(f"unexpected command: {command:#x}")

    reader._call_function = fake_call  # type: ignore[method-assign]

    reader._ensure_initialized()

    assert calls == [
        (0x02, b""),
        (0x14, bytes([0x01, 0x14, 0x01])),
        (0x32, bytes([0x05, 0xFF, 0x01, 0xFF])),
    ]
    assert reader._firmware_info == {
        "chip": 0x32,
        "version": 0x01,
        "revision": 0x06,
        "support": 0x07,
    }


class _FakeI2CMsg:
    def __init__(self, direction: str, address: int, payload):
        self.direction = direction
        self.address = address
        self.payload = bytearray(payload)

    def __bytes__(self):
        return bytes(self.payload)


class _FakeSMBus:
    queued_reads = []
    instances = []

    def __init__(self, bus_id: int):
        self.bus_id = bus_id
        self.writes = []
        self.reads = [bytes(item) for item in self.__class__.queued_reads]
        self.__class__.instances.append(self)

    def i2c_rdwr(self, msg):
        if msg.direction == "write":
            self.writes.append(bytes(msg.payload))
            return
        if not self.reads:
            raise AssertionError("unexpected I2C read with empty queue")
        payload = self.reads.pop(0)
        msg.payload[:] = payload[: len(msg.payload)]

    def close(self):
        return None


def _fake_i2c_msg_module():
    return types.SimpleNamespace(
        read=lambda address, length: _FakeI2CMsg("read", address, b"\x00" * length),
        write=lambda address, payload: _FakeI2CMsg("write", address, bytes(payload)),
    )


def test_pn532_i2c_transport_writes_frame_without_extra_prefix(monkeypatch):
    _FakeSMBus.instances = []
    _FakeSMBus.queued_reads = [b"\x00", b"\x00", b"\x00"]
    monkeypatch.setitem(
        __import__("sys").modules,
        "smbus2",
        types.SimpleNamespace(SMBus=_FakeSMBus, i2c_msg=_fake_i2c_msg_module()),
    )

    transport = PN532I2CTransport(bus_id=4, address=0x24)
    frame = b"\x00\x00\xFF\x02\xFE\xD4\x02\x2A\x00"
    transport.write_frame(frame)

    assert _FakeSMBus.instances
    assert _FakeSMBus.instances[0].writes[-1] == frame


def test_pn532_i2c_transport_reads_full_response_frame(monkeypatch):
    response_frame = bytes([
        0x00, 0x00, 0xFF, 0x06, 0xFA,
        0xD5, 0x03, 0x32, 0x01, 0x06, 0x07,
        0xE8, 0x00,
    ])
    padded_read = bytes([0x01]) + response_frame + bytes(64 - len(response_frame))

    _FakeSMBus.instances = []
    _FakeSMBus.queued_reads = [
        b"\x00",
        b"\x00",
        b"\x00",
        padded_read,
    ]
    monkeypatch.setitem(
        __import__("sys").modules,
        "smbus2",
        types.SimpleNamespace(SMBus=_FakeSMBus, i2c_msg=_fake_i2c_msg_module()),
    )

    transport = PN532I2CTransport(bus_id=4, address=0x24)
    assert transport.read_full_response(0x02) == response_frame


class _FakeMPU6050Bus:
    def __init__(self):
        self.writes = []

    def write_byte_data(self, address, register, value):
        self.writes.append((address, register, value))

    def read_byte_data(self, address, register):
        assert address == 0x68
        assert register == 0x75
        return 0x68

    def read_i2c_block_data(self, address, register, length):
        assert address == 0x68
        assert register == 0x3B
        assert length == 14
        return [
            0x00,
            0x00,
            0x00,
            0x00,
            0x40,
            0x00,
            0x00,
            0x00,
            0x00,
            0x00,
            0x00,
            0x00,
            0x00,
            0x00,
        ]


def test_mpu6050_decodes_level_stationary_sample():
    bus = _FakeMPU6050Bus()
    sensor = MPU6050(bus=bus)
    sensor.open()

    assert sensor.who_am_i() == 0x68
    reading = sensor.read()

    assert reading.accel_x_g == 0
    assert reading.accel_y_g == 0
    assert reading.accel_z_g == 1
    assert reading.vibration_g == 0
    assert bus.writes[0] == (0x68, 0x6B, 0x00)


def test_mpu6050_vibration_adapter_records_average():
    sensor = MPU6050VibrationSensor(bus=_FakeMPU6050Bus())
    sensor.open()

    reading = sensor.read()

    assert reading.sensor_type == "vibration"
    assert reading.value == 0
    assert sensor.get_average() == 0


def test_mpu6050_can_lazy_open_via_smbus2(monkeypatch):
    class _FakeSMBusForMPU:
        def __init__(self, bus_id):
            self.bus_id = bus_id
            self.writes = []

        def write_byte_data(self, address, register, value):
            self.writes.append((address, register, value))

        def read_byte_data(self, address, register):
            assert address == 0x68
            assert register == REG_WHO_AM_I
            return 0x68

        def read_i2c_block_data(self, address, register, length):
            assert address == 0x68
            assert register == REG_ACCEL_XOUT_H
            assert length == 14
            return [
                0x00, 0x00,
                0x00, 0x00,
                0x40, 0x00,
                0x00, 0x00,
                0x00, 0x00,
                0x00, 0x00,
                0x00, 0x00,
            ]

        def close(self):
            return None

    monkeypatch.setitem(
        __import__("sys").modules,
        "smbus2",
        types.SimpleNamespace(SMBus=_FakeSMBusForMPU),
    )
    sensor = MPU6050(bus_id=4, address=0x68)

    assert sensor.who_am_i() == 0x68
    reading = sensor.read()

    assert reading.accel_z_g == 1
    assert reading.vibration_g == 0


def test_build_device_controller_can_use_mpu6050_vibration_backend(monkeypatch):
    class _FakeSMBusForMPU:
        def __init__(self, bus_id):
            self.bus_id = bus_id

        def write_byte_data(self, address, register, value):
            return None

        def read_byte_data(self, address, register):
            return 0x68

        def read_i2c_block_data(self, address, register, length):
            return [
                0x00, 0x00,
                0x00, 0x00,
                0x40, 0x00,
                0x00, 0x00,
                0x00, 0x00,
                0x00, 0x00,
                0x00, 0x00,
            ]

        def close(self):
            return None

    monkeypatch.setitem(
        __import__("sys").modules,
        "smbus2",
        types.SimpleNamespace(SMBus=_FakeSMBusForMPU),
    )
    controller = build_device_controller(
        servo_backend="mock",
        conveyor_backend="mock",
        vibration_backend="mpu6050",
        vibration_i2c_bus=4,
        vibration_i2c_address=0x68,
    )
    controller.inject_sensor_values(current=1.2)

    health = controller.monitor_health()

    assert health["overall"] == "green"
    assert health["vibration"]["value"] == 0
    assert controller.get_device_status()["vibration_backend"] == "MPU6050VibrationSensor"


def test_software_pwm_backend_controls_enable_gpio():
    signal = MockGPIOOutput()
    enable = MockGPIOOutput()
    backend = SoftwarePWMGPIOBackend(signal_gpio=signal, enable_gpio=enable)
    try:
        backend.set_period_ns(20_000_000)
        backend.set_duty_cycle_ns(1_500_000)
        backend.enable()
        assert enable.value == 1
        backend.disable()
        assert enable.value == 0
        assert signal.value == 0
    finally:
        backend.cleanup()


def test_consistency_pass_with_mixed_value_styles():
    engine = ConsistencyEngine(confidence_threshold=0.5)
    result = engine.compare(
        material_id="MAT001",
        nfc_result={"success": True, "text": '{"material_type":"塑料块","color":"红色"}'},
        vision_result={
            "success": True,
            "material_type": "plastic",
            "color": "red",
            "confidence": 0.95,
        },
        order_params=None,
    )
    assert result.status == ComparisonStatus.PASS


def test_unstructured_nfc_text_goes_to_manual_review_side_bin():
    engine = ConsistencyEngine(confidence_threshold=0.5)
    decision_engine = EnhancedSortingDecisionEngine(engine)
    decision = decision_engine.make_decision(
        material_id="MAT404",
        nfc_result={"success": True, "text": "MAT404"},
        vision_result={
            "success": True,
            "material_type": "塑料块",
            "color": "红色",
            "confidence": 0.95,
        },
        order_params=None,
    )
    assert decision["order_status"] == "WAITING_MANUAL"
    assert decision["route"] == "side_bin"
    assert decision["requires_manual_review"] is True


def test_nfc_text_and_vision_can_pass_without_order():
    engine = ConsistencyEngine(confidence_threshold=0.5)
    result = engine.compare(
        material_id=None,
        nfc_result={
            "success": False,
            "text": "黄色正方形",
            "error": "Unable to decode material_id from tag",
            "raw": {"material_id_source": "tag_payload"},
        },
        vision_result={
            "success": True,
            "material_type": "木质件",
            "color": "黄色",
            "shape": "正方形",
            "confidence": 0.93,
        },
        order_params=None,
    )
    assert result.status == ComparisonStatus.PASS
    assert result.reference_source == "nfc_text"


def test_nfc_text_shape_mismatch_is_reported_without_order():
    engine = ConsistencyEngine(confidence_threshold=0.5)
    result = engine.compare(
        material_id=None,
        nfc_result={
            "success": True,
            "text": '{"color":"黄色","shape":"长方形"}',
        },
        vision_result={
            "success": True,
            "material_type": "木质件",
            "color": "黄色",
            "shape": "正方形",
            "confidence": 0.91,
        },
        order_params=None,
    )
    assert result.status == ComparisonStatus.ANOMALY
    assert "形状不一致" in result.reasons


def test_order_requirement_passes_when_order_nfc_and_vision_all_match():
    engine = ConsistencyEngine(confidence_threshold=0.5)
    result = engine.compare(
        material_id=None,
        nfc_result={
            "success": True,
            "text": "黄色正方形",
        },
        vision_result={
            "success": True,
            "material_type": "木质件",
            "color": "黄色",
            "shape": "正方形",
            "confidence": 0.93,
        },
        order_params={
            "enabled": True,
            "raw_text": "黄色正方形",
            "spec": {"color": "黄色", "shape": "正方形"},
        },
    )
    assert result.status == ComparisonStatus.PASS
    assert result.reference_source == "order"
    assert result.order_requirement["enabled"] is True


def test_order_requirement_reports_anomaly_when_nfc_differs_from_order():
    engine = ConsistencyEngine(confidence_threshold=0.5)
    result = engine.compare(
        material_id=None,
        nfc_result={
            "success": True,
            "text": "蓝色，正方形",
        },
        vision_result={
            "success": True,
            "material_type": "木质件",
            "color": "蓝色",
            "shape": "正方形",
            "confidence": 0.93,
        },
        order_params={
            "enabled": True,
            "raw_text": "黄色正方形",
            "spec": {"color": "黄色", "shape": "正方形"},
        },
    )
    assert result.status == ComparisonStatus.ANOMALY
    assert "订单与NFC文本不一致" in result.reasons


def test_order_requirement_ignores_punctuation_when_comparing_order_and_nfc_text():
    engine = ConsistencyEngine(confidence_threshold=0.5)
    result = engine.compare(
        material_id=None,
        nfc_result={
            "success": True,
            "text": "黄色，正方形",
        },
        vision_result={
            "success": True,
            "material_type": "木质件",
            "color": "黄色",
            "shape": "正方形",
            "confidence": 0.93,
        },
        order_params={
            "enabled": True,
            "raw_text": "黄色 正方形",
            "spec": {"color": "黄色", "shape": "正方形"},
        },
    )
    assert result.status == ComparisonStatus.PASS


def test_order_requirement_ignores_zero_width_and_fullwidth_spacing_in_text_compare():
    engine = ConsistencyEngine(confidence_threshold=0.5)
    result = engine.compare(
        material_id=None,
        nfc_result={
            "success": True,
            "text": "黄色\u200b，正方形",
        },
        vision_result={
            "success": True,
            "material_type": "木质件",
            "color": "黄色",
            "shape": "正方形",
            "confidence": 0.93,
        },
        order_params={
            "enabled": True,
            "raw_text": "黄色　正方形",
            "spec": {"color": "黄色", "shape": "正方形"},
        },
    )
    assert result.status == ComparisonStatus.PASS


def test_missing_order_and_unstructured_nfc_text_reports_no_reference():
    engine = ConsistencyEngine(confidence_threshold=0.5)
    result = engine.compare(
        material_id=None,
        nfc_result={
            "success": True,
            "text": "Hello NFC",
        },
        vision_result={
            "success": True,
            "material_type": "木质件",
            "color": "黄色",
            "shape": "正方形",
            "confidence": 0.93,
        },
        order_params=None,
    )
    assert result.status == ComparisonStatus.NO_REFERENCE


def test_device_red_health_triggers_alarm_stop():
    controller = DeviceController()
    controller.start(skip_check=True)
    controller.inject_sensor_values(vibration=0.8, current=3.0)
    health = controller.monitor_health()
    assert health["overall"] == "red"
    assert controller.alert_latched is True
    assert controller.is_running is False


def test_device_yellow_health_triggers_protective_stop():
    controller = DeviceController()
    controller.start(skip_check=True)
    controller.inject_sensor_values(vibration=0.5, current=1.2)

    health = controller.monitor_health()

    assert health["overall"] == "yellow"
    assert health["stopped"] is True
    assert controller.alert_latched is True
    assert controller.is_running is False


def test_current_reading_is_monitor_only_and_does_not_trigger_fault():
    controller = DeviceController()
    controller.start(skip_check=True)
    controller.inject_sensor_values(vibration=0.03, current=3.0)

    health = controller.monitor_health()

    assert health["overall"] == "green"
    assert health["current"]["value"] == 3.0
    assert health["current"]["level"] == "monitor_only"
    assert health["current"]["fault_enabled"] is False
    assert health["stopped"] is False
    assert controller.alert_latched is False
    assert controller.is_running is True


def test_passive_health_snapshot_does_not_latch_alarm():
    controller = DeviceController()
    controller.start(skip_check=True)
    controller.inject_sensor_values(vibration=0.8, current=3.0)

    health = controller.read_health_snapshot()

    assert health["overall"] == "red"
    assert controller.alert_latched is False
    assert controller.is_running is True
    assert "sampled_at" in health


def test_shape_mismatch_is_reported():
    engine = ConsistencyEngine(confidence_threshold=0.5)
    result = engine.compare(
        material_id="WOOD001",
        nfc_result={"success": True, "text": '{"color":"蓝色","shape":"正方形","material_type":"木质件"}'},
        vision_result={
            "success": True,
            "material_type": "木质件",
            "color": "蓝色",
            "shape": "三角形",
            "confidence": 0.91,
        },
        order_params=None,
    )
    assert result.status == ComparisonStatus.ANOMALY
    assert "形状不一致" in result.reasons
