import json
from pathlib import Path

import cv2
import numpy as np

from embedded_vision_system.board_runtime import BoardRuntimeConfig, BoardSortingRuntime
from embedded_vision_system.device_controller import ConveyorBelt, DeviceController, ServoController
from embedded_vision_system.hardware import has_readable_text_payload
from embedded_vision_system.sorting_system import SortingSystem, SystemMode


class _StaticFrameCamera:
    def __init__(self, frames):
        self.frames = [frame.copy() for frame in frames]
        self.index = 0
        self.released = False

    def read_frame(self):
        if self.index < len(self.frames):
            frame = self.frames[self.index]
            self.index += 1
        else:
            frame = self.frames[-1]
        return True, frame.copy()

    def release(self):
        self.released = True


class _QueuedNFCReader:
    def __init__(self, payloads):
        self.payloads = [dict(payload) for payload in payloads]
        self.read_count = 0

    def read(self):
        self.read_count += 1
        if self.payloads:
            return dict(self.payloads.pop(0))
        return {
            "success": False,
            "text": None,
            "error": "No NFC tag detected",
            "raw": {"mode": "pytest"},
        }


class _BufferedNFCSampleService:
    def __init__(self, snapshots):
        self.snapshots = [dict(snapshot) for snapshot in snapshots]
        self.peek_count = 0
        self.enabled = True
        self._last_snapshot = {"sample": None, "sampled_at": None, "source": "poll"}
        self._latched_snapshot = {"sample": None, "sampled_at": None, "source": None}
        self._latched_consumed = False

    def _apply_snapshot(self, snapshot):
        sample = snapshot.get("sample")
        normalized = {
            "sample": dict(sample) if isinstance(sample, dict) else sample,
            "sampled_at": snapshot.get("sampled_at"),
            "source": snapshot.get("source", "poll"),
        }
        self._last_snapshot = normalized
        payload = normalized.get("sample")
        if isinstance(payload, dict) and has_readable_text_payload(payload):
            if not self._latched_consumed:
                self._latched_snapshot = {
                    "sample": dict(payload),
                    "sampled_at": normalized.get("sampled_at"),
                    "source": normalized.get("source"),
                }
        elif self._latched_consumed:
            self._latched_snapshot = {"sample": None, "sampled_at": None, "source": None}
            self._latched_consumed = False

    def peek_result(self):
        self.peek_count += 1
        if self.snapshots:
            self._apply_snapshot(self.snapshots.pop(0))
        return {
            "sample": dict(self._last_snapshot.get("sample") or {}) or None,
            "sampled_at": self._last_snapshot.get("sampled_at"),
            "source": self._last_snapshot.get("source", "poll"),
        }

    def peek_latched_result(self):
        sample = self._latched_snapshot.get("sample")
        return {
            "sample": dict(sample) if isinstance(sample, dict) and not self._latched_consumed else None,
            "sampled_at": self._latched_snapshot.get("sampled_at") if not self._latched_consumed else None,
            "source": self._latched_snapshot.get("source") if not self._latched_consumed else None,
        }

    def mark_latched_result_consumed(self, sampled_at=None):
        current_sampled_at = self._latched_snapshot.get("sampled_at")
        if self._latched_snapshot.get("sample") is None or self._latched_consumed:
            return False
        if sampled_at and current_sampled_at and sampled_at != current_sampled_at:
            return False
        self._latched_consumed = True
        return True


class _SpyDeviceController(DeviceController):
    def __init__(self):
        super().__init__(
            servo=ServoController(response_delay=0),
            conveyor=ConveyorBelt(),
            default_conveyor_speed=55,
            sort_prepare_pause=0,
            sort_servo_settle_time=0,
            sort_conveyor_advance_time=0,
        )
        self.execute_sort_calls = 0
        self.execute_sort_entry_enabled = None

    def execute_sort(self, *args, **kwargs) -> bool:
        self.execute_sort_calls += 1
        self.execute_sort_entry_enabled = self.conveyor.enabled
        return super().execute_sort(*args, **kwargs)


class _HealthTripDeviceController(_SpyDeviceController):
    def __init__(self, overall="red"):
        super().__init__()
        self.overall = overall
        self.health_calls = 0

    def monitor_health(self):
        self.health_calls += 1
        self.alert_latched = True
        self.conveyor.stop()
        self.is_running = False
        self.health_status = self.overall
        self.last_health_snapshot = {
            "overall": self.overall,
            "sampled_at": 1750000000.0,
            "vibration": {
                "value": 0.3 if self.overall == "yellow" else 0.8,
                "level": self.overall,
                "average": 0.2,
                "sampled_at": 1750000000.0,
            },
            "current": {
                "value": 0.6,
                "level": "green",
                "average": 0.6,
                "sampled_at": 1750000000.0,
            },
            "alert_latched": True,
            "reasons": ["设备红色故障" if self.overall == "red" else "设备黄色告警"],
            "stopped": True,
        }
        return dict(self.last_health_snapshot)


class _StaticResultClassifier:
    def __init__(self, result):
        self.result = {
            "material_type": "木质件",
            "color": None,
            "shape": None,
            "confidence": 0.0,
            "color_confidence": 0.0,
            "shape_confidence": 0.0,
            "success": False,
            "bbox": None,
            "contour_area": 0.0,
            "vertex_count": 0,
            "details": "",
            **dict(result),
        }

    def classify_best(self, _frame):
        return type("_Result", (), self.result)()


def _build_centered_yellow_square_frame():
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    cv2.rectangle(frame, (250, 170), (390, 310), (0, 255, 255), thickness=-1)
    return frame


def _build_left_yellow_square_frame():
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    cv2.rectangle(frame, (30, 170), (170, 310), (0, 255, 255), thickness=-1)
    return frame


def test_execute_sort_restores_conveyor_after_pause():
    controller = DeviceController(
        servo=ServoController(response_delay=0),
        conveyor=ConveyorBelt(),
        default_conveyor_speed=55,
        sort_prepare_pause=0,
        sort_servo_settle_time=0,
        sort_conveyor_advance_time=0,
    )

    assert controller.start(skip_check=True, speed=55) is True
    assert controller.pause_conveyor() is True
    assert controller.conveyor.enabled is False

    assert controller.execute_sort(hold_time=0) is True
    assert controller.conveyor.enabled is True
    assert controller.conveyor.current_speed == 55
    assert controller.servo.get_current_angle() == controller.servo.normal_angle


def test_execute_sort_reports_runtime_timing_configuration():
    controller = DeviceController(
        sort_prepare_pause=0.3,
        sort_servo_settle_time=0.4,
        sort_conveyor_advance_time=0.8,
    )

    assert controller.get_sort_timing() == {
        "prepare_pause": 0.3,
        "servo_settle_time": 0.4,
        "conveyor_advance_time": 0.8,
        "conveyor_half_travel_seconds": 10.0,
    }


def test_execute_sort_moves_servo_first_and_holds_until_item_passes(monkeypatch):
    events = []
    clock = {"value": 0.0}

    class _SpyServo:
        def __init__(self):
            self.normal_angle = 90
            self.sort_angle = 45
            self.current_angle = self.normal_angle

        def normal_position(self):
            events.append("servo_normal")
            self.current_angle = self.normal_angle
            return True

        def sort_position(self):
            events.append("servo_sort")
            self.current_angle = self.sort_angle
            return True

        def set_angle(self, angle):
            events.append(f"servo_angle:{int(angle)}")
            self.current_angle = int(angle)
            return True

        def get_current_angle(self):
            return self.current_angle

    class _SpyConveyor:
        def __init__(self):
            self.current_speed = 55
            self.enabled = True

        def start(self, speed=0):
            events.append(f"conveyor_start:{speed}")
            self.current_speed = speed
            self.enabled = speed > 0
            return True

        def stop(self):
            events.append("conveyor_stop")
            self.current_speed = 0
            self.enabled = False
            return True

        def get_status(self):
            return {
                "state": "运行" if self.enabled else "停止",
                "speed": self.current_speed,
                "enabled": self.enabled,
            }

    def fake_sleep(seconds):
        events.append(f"sleep:{float(seconds):g}")
        clock["value"] += float(seconds)

    monkeypatch.setattr("embedded_vision_system.device_controller.time.sleep", fake_sleep)
    monkeypatch.setattr("embedded_vision_system.device_controller.time.monotonic", lambda: clock["value"])

    controller = DeviceController(
        servo=_SpyServo(),
        conveyor=_SpyConveyor(),
        default_conveyor_speed=55,
        sort_prepare_pause=0.1,
        sort_servo_settle_time=0.2,
        sort_servo_secondary_angle=20,
        sort_servo_oscillation_interval=0.5,
        sort_conveyor_advance_time=1.2,
    )
    controller.is_running = True
    controller.last_running_speed = 55

    assert controller.execute_sort() is True
    assert events == [
        "conveyor_stop",
        "sleep:0.1",
        "servo_sort",
        "sleep:0.2",
        "conveyor_start:55",
        "sleep:0.5",
        "servo_angle:20",
        "sleep:0.5",
        "servo_angle:45",
        "sleep:0.2",
        "servo_normal",
    ]


def test_process_material_side_bin_leaves_actuation_to_runtime(tmp_path: Path):
    system = SortingSystem(
        mode=SystemMode.CONTINUOUS,
        state_path=str(tmp_path / "orders_state.json"),
    )
    spy_controller = _SpyDeviceController()
    system.device_controller = spy_controller
    system.is_ready = True
    system.system_status = "运行中"
    system.nfc_reader.set_next_result({"success": True, "material_id": "MAT404"})

    result = system.process_material(
        vision_boxes=None,
        vision_classes=None,
        vision_scores=None,
        class_names=[],
        image=_build_centered_yellow_square_frame(),
    )

    assert result.route == "side_bin"
    assert spy_controller.execute_sort_calls == 0
    history = system.list_history()
    assert len(history) == 1
    assert history[0]["route"] == "side_bin"


def test_process_material_can_pass_with_nfc_text_without_order(tmp_path: Path):
    system = SortingSystem(
        mode=SystemMode.CONTINUOUS,
        state_path=str(tmp_path / "orders_state.json"),
    )
    spy_controller = _SpyDeviceController()
    system.device_controller = spy_controller
    system.is_ready = True
    system.system_status = "运行中"
    system.nfc_reader.set_next_result(
        {
            "success": False,
            "text": "黄色正方形",
            "error": "Unable to decode material_id from tag",
            "raw": {"material_id_source": "tag_payload"},
        }
    )

    result = system.process_material(
        vision_boxes=None,
        vision_classes=None,
        vision_scores=None,
        class_names=[],
        image=_build_centered_yellow_square_frame(),
    )

    assert result.route == "main_line"
    assert result.order_status == "DETECTED_PASS"
    assert result.reason == "一致性检查通过，放行"
    assert spy_controller.execute_sort_calls == 0
    history = system.list_history()
    assert len(history) == 1
    assert history[0]["route"] == "main_line"
    assert history[0]["nfc_snapshot"]["text"] == "黄色正方形"


def test_board_runtime_processes_centered_item_and_logs_nfc(tmp_path: Path):
    frame = _build_centered_yellow_square_frame()
    camera = _StaticFrameCamera([frame, frame, frame])

    system = SortingSystem(
        mode=SystemMode.CONTINUOUS,
        state_path=str(tmp_path / "orders_state.json"),
    )
    assert system.create_test_order("MAT001", "木质件", "黄色", shape="正方形") is True
    system.nfc_reader.set_next_result(
        {
            "success": True,
            "material_id": "MAT001",
            "text": "黄色正方形",
            "raw": {"material_id_source": "tag_payload"},
        }
    )

    runtime = BoardSortingRuntime(
        system=system,
        camera=camera,
        config=BoardRuntimeConfig(
            conveyor_speed=45,
            center_hold_frames=2,
            detection_stop_delay_seconds=0.0,
            capture_settle_time=0.0,
            capture_dir=str(tmp_path / "captures"),
            nfc_log_path=str(tmp_path / "logs" / "nfc.jsonl"),
        ),
    )

    result = runtime.run(max_items=1, max_frames=5)

    assert result["success"] is True
    assert result["processed_items"] == 1
    assert system.is_ready is True
    assert system.device_controller.conveyor.enabled is True
    assert system.device_controller.conveyor.current_speed == 45

    history = system.list_history()
    assert len(history) == 1
    record = history[0]
    assert record["material_id"] == "MAT001"
    assert record["route"] == "main_line"
    assert record["nfc_snapshot"]["material_id"] == "MAT001"
    assert record["nfc_snapshot"]["text"] == "黄色正方形"
    assert record["vision_snapshot"]["color"] == "黄色"
    assert record["vision_snapshot"]["shape"] == "正方形"
    assert record["runtime_context"]["stopped_vision_result"]["shape"] == "正方形"
    assert record["runtime_context"]["selected_nfc_result"]["text"] == "黄色正方形"

    captures = list((tmp_path / "captures").glob("*.jpg"))
    assert len(captures) == 1

    lines = (tmp_path / "logs" / "nfc.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["material_id"] == "MAT001"
    assert payload["nfc_result"]["material_id"] == "MAT001"
    assert payload["runtime_context"]["selected_nfc_result"]["text"] == "黄色正方形"
    assert payload["decision"]["route"] == "main_line"

    runtime.shutdown()
    assert camera.released is True


def test_board_runtime_stops_on_first_detected_item_even_if_not_centered(tmp_path: Path):
    frame = _build_left_yellow_square_frame()
    camera = _StaticFrameCamera([frame, frame, frame])

    system = SortingSystem(
        mode=SystemMode.CONTINUOUS,
        state_path=str(tmp_path / "orders_state.json"),
    )
    assert system.create_test_order("MATLEFT", "木质件", "黄色", shape="正方形") is True
    system.nfc_reader.set_next_result(
        {
            "success": True,
            "material_id": "MATLEFT",
            "text": "黄色正方形",
            "raw": {"material_id_source": "tag_payload"},
        }
    )

    runtime = BoardSortingRuntime(
        system=system,
        camera=camera,
        config=BoardRuntimeConfig(
            conveyor_speed=45,
            center_tolerance_ratio=0.01,
            center_hold_frames=99,
            stop_on_first_detection=True,
            detection_stop_delay_seconds=0.0,
            capture_settle_time=0.0,
            capture_dir=str(tmp_path / "captures"),
            nfc_log_path=str(tmp_path / "logs" / "nfc.jsonl"),
        ),
    )

    result = runtime.run(max_items=1, max_frames=5)

    assert result["success"] is True
    assert result["processed_items"] == 1
    history = system.list_history()
    assert len(history) == 1
    assert history[0]["material_id"] == "MATLEFT"

    runtime.shutdown()
    assert camera.released is True


def test_board_runtime_executes_sort_after_side_bin_decision(tmp_path: Path):
    frame = _build_centered_yellow_square_frame()
    camera = _StaticFrameCamera([frame, frame, frame])

    system = SortingSystem(
        mode=SystemMode.CONTINUOUS,
        state_path=str(tmp_path / "orders_state.json"),
    )
    spy_controller = _SpyDeviceController()
    system.device_controller = spy_controller
    system.nfc_reader.set_next_result({"success": True, "material_id": "MAT404"})

    runtime = BoardSortingRuntime(
        system=system,
        camera=camera,
        config=BoardRuntimeConfig(
            conveyor_speed=55,
            center_hold_frames=2,
            detection_stop_delay_seconds=0.0,
            capture_settle_time=0.0,
            capture_dir=str(tmp_path / "captures"),
            nfc_log_path=str(tmp_path / "logs" / "nfc.jsonl"),
        ),
    )

    result = runtime.run(max_items=1, max_frames=5)

    assert result["success"] is True
    assert result["processed_items"] == 1
    assert spy_controller.execute_sort_calls == 1
    assert spy_controller.execute_sort_entry_enabled is False
    assert spy_controller.conveyor.enabled is True
    assert spy_controller.conveyor.current_speed == 55
    assert spy_controller.servo.get_current_angle() == spy_controller.servo.normal_angle

    history = system.list_history()
    assert len(history) == 1
    assert history[0]["route"] == "side_bin"

    runtime.shutdown()
    assert camera.released is True


def test_board_runtime_waits_for_readable_nfc_text_before_resuming(tmp_path: Path):
    frame = _build_centered_yellow_square_frame()
    camera = _StaticFrameCamera([frame, frame, frame, frame])

    system = SortingSystem(
        mode=SystemMode.CONTINUOUS,
        state_path=str(tmp_path / "orders_state.json"),
    )
    assert system.create_test_order("MATTXT", "木质件", "黄色", shape="正方形") is True
    queued_reader = _QueuedNFCReader(
        [
            {
                "success": False,
                "text": None,
                "error": "No NFC tag detected",
                "raw": {"mode": "pytest"},
            },
            {
                "success": True,
                "material_id": "A1B2C3D4",
                "text": None,
                "raw": {"material_id_source": "uid", "uid": "A1B2C3D4"},
            },
            {
                "success": True,
                "material_id": "MATTXT",
                "text": "MATTXT",
                "raw": {"material_id_source": "tag_payload"},
            },
        ]
    )
    system.nfc_reader = queued_reader

    runtime = BoardSortingRuntime(
        system=system,
        camera=camera,
        config=BoardRuntimeConfig(
            conveyor_speed=45,
            center_hold_frames=2,
            detection_stop_delay_seconds=0.0,
            capture_settle_time=0.0,
            nfc_retry_interval=0.0,
            capture_dir=str(tmp_path / "captures"),
            nfc_log_path=str(tmp_path / "logs" / "nfc.jsonl"),
        ),
    )

    result = runtime.run(max_items=1, max_frames=5)

    assert result["success"] is True
    assert result["processed_items"] == 1
    assert queued_reader.read_count == 3
    assert system.is_ready is True
    assert system.system_status == "运行中"
    assert getattr(system, "_runtime_pending_nfc_result", None) is None
    assert system.device_controller.conveyor.enabled is True
    assert system.device_controller.conveyor.current_speed == 45

    history = system.list_history()
    assert len(history) == 1
    assert history[0]["material_id"] == "MATTXT"
    assert history[0]["nfc_snapshot"]["text"] == "MATTXT"

    runtime.shutdown()
    assert camera.released is True


def test_board_runtime_uses_continuous_nfc_polling_buffer(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("embedded_vision_system.board_runtime.time.sleep", lambda _seconds: None)

    frame = _build_centered_yellow_square_frame()
    camera = _StaticFrameCamera([frame, frame, frame])

    system = SortingSystem(
        mode=SystemMode.CONTINUOUS,
        state_path=str(tmp_path / "orders_state.json"),
    )
    assert system.create_test_order("MATBUF", "木质件", "黄色", shape="正方形") is True

    nfc_sample_service = _BufferedNFCSampleService(
        [
            {
                "sample": {
                    "success": True,
                    "material_id": "MATOLD",
                    "text": "MATOLD",
                    "raw": {"material_id_source": "tag_payload"},
                },
                "sampled_at": "2026-07-08T10:00:00",
                "source": "poll",
            },
            {
                "sample": {
                    "success": False,
                    "text": None,
                    "error": "No NFC tag detected",
                    "raw": {"mode": "pytest"},
                },
                "sampled_at": "2026-07-08T10:00:01",
                "source": "poll",
            },
            {
                "sample": {
                    "success": True,
                    "material_id": "MATBUF",
                    "text": "MATBUF",
                    "raw": {"material_id_source": "tag_payload"},
                },
                "sampled_at": "2026-07-08T10:00:02",
                "source": "poll",
            },
        ]
    )

    runtime = BoardSortingRuntime(
        system=system,
        camera=camera,
        config=BoardRuntimeConfig(
            conveyor_speed=45,
            center_hold_frames=1,
            detection_stop_delay_seconds=0.0,
            capture_settle_time=0.0,
            nfc_retry_interval=0.0,
            capture_dir=str(tmp_path / "captures"),
            nfc_log_path=str(tmp_path / "logs" / "nfc.jsonl"),
        ),
        nfc_sample_service=nfc_sample_service,
    )
    runtime._last_consumed_nfc_sample_at = "2026-07-08T10:00:00"

    result = runtime.run(max_items=1, max_frames=5)

    assert result["success"] is True
    assert result["processed_items"] == 1
    assert nfc_sample_service.peek_count >= 2

    history = system.list_history()
    assert len(history) == 1
    assert history[0]["material_id"] == "MATBUF"
    assert history[0]["nfc_snapshot"]["text"] == "MATBUF"
    assert [item["sample"].get("text") for item in history[0]["runtime_context"]["observed_nfc_results"]] == [
        "MATOLD",
        None,
        "MATBUF",
    ]

    runtime.shutdown()
    assert camera.released is True


def test_board_runtime_uses_stopped_vision_snapshot_for_comparison(tmp_path: Path):
    frame = _build_centered_yellow_square_frame()
    camera = _StaticFrameCamera([frame, frame, frame])

    system = SortingSystem(
        mode=SystemMode.CONTINUOUS,
        state_path=str(tmp_path / "orders_state.json"),
    )
    system.is_ready = True
    system.system_status = "运行中"
    system.shape_color_classifier.classify_best = lambda _image: (_ for _ in ()).throw(
        AssertionError("process_material should use the frozen stopped vision result")
    )
    system.nfc_reader = _QueuedNFCReader(
        [
            {
                "success": True,
                "material_id": "MATFROZEN",
                "text": "黄色正方形",
                "raw": {"material_id_source": "tag_payload"},
            }
        ]
    )

    runtime = BoardSortingRuntime(
        system=system,
        camera=camera,
        classifier=_StaticResultClassifier(
            {
                "success": True,
                "material_type": "木质件",
                "color": "黄色",
                "shape": "正方形",
                "confidence": 0.91,
                "label": "黄色正方形",
                "details": "frozen-stop-vision",
            }
        ),
        config=BoardRuntimeConfig(
            conveyor_speed=45,
            center_hold_frames=1,
            detection_stop_delay_seconds=0.0,
            capture_settle_time=0.0,
            nfc_retry_interval=0.0,
            capture_dir=str(tmp_path / "captures"),
            nfc_log_path=str(tmp_path / "logs" / "nfc.jsonl"),
        ),
    )

    result = runtime.run(max_items=1, max_frames=5)

    assert result["success"] is True
    history = system.list_history()
    assert len(history) == 1
    assert history[0]["vision_snapshot"]["details"] == "frozen-stop-vision"
    assert history[0]["runtime_context"]["stopped_vision_result"]["details"] == "frozen-stop-vision"


def test_board_runtime_consumes_latched_nfc_text_even_after_following_empty_samples(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("embedded_vision_system.board_runtime.time.sleep", lambda _seconds: None)

    frame = _build_centered_yellow_square_frame()
    camera = _StaticFrameCamera([frame, frame, frame])

    system = SortingSystem(
        mode=SystemMode.CONTINUOUS,
        state_path=str(tmp_path / "orders_state.json"),
    )
    assert system.create_test_order("MATLATCH", "木质件", "黄色", shape="正方形") is True

    nfc_sample_service = _BufferedNFCSampleService(
        [
            {
                "sample": {
                    "success": True,
                    "material_id": "MATLATCH",
                    "text": "MATLATCH",
                    "raw": {"material_id_source": "tag_payload"},
                },
                "sampled_at": "2026-07-08T11:00:00",
                "source": "poll",
            },
            {
                "sample": {
                    "success": False,
                    "text": None,
                    "error": "No NFC tag detected",
                    "raw": {"mode": "pytest"},
                },
                "sampled_at": "2026-07-08T11:00:01",
                "source": "poll",
            },
        ]
    )

    runtime = BoardSortingRuntime(
        system=system,
        camera=camera,
        config=BoardRuntimeConfig(
            conveyor_speed=45,
            center_hold_frames=1,
            detection_stop_delay_seconds=0.0,
            capture_settle_time=0.0,
            nfc_retry_interval=0.0,
            capture_dir=str(tmp_path / "captures"),
            nfc_log_path=str(tmp_path / "logs" / "nfc.jsonl"),
        ),
        nfc_sample_service=nfc_sample_service,
    )

    result = runtime.run(max_items=1, max_frames=4)

    assert result["success"] is True
    assert result["processed_items"] == 1

    history = system.list_history()
    assert len(history) == 1
    assert history[0]["material_id"] == "MATLATCH"
    assert history[0]["nfc_snapshot"]["text"] == "MATLATCH"
    assert nfc_sample_service.peek_latched_result()["sample"] is None

    runtime.shutdown()
    assert camera.released is True


def test_board_runtime_stop_cooldown_blocks_immediate_retrigger(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("embedded_vision_system.board_runtime.time.sleep", lambda _seconds: None)
    monkeypatch.setattr("embedded_vision_system.board_runtime.time.monotonic", lambda: 100.0)

    frame = _build_centered_yellow_square_frame()
    camera = _StaticFrameCamera([frame, frame, frame, frame, frame, frame])

    system = SortingSystem(
        mode=SystemMode.CONTINUOUS,
        state_path=str(tmp_path / "orders_state.json"),
    )
    assert system.create_test_order("MATCOOL", "木质件", "黄色", shape="正方形") is True
    system.nfc_reader = _QueuedNFCReader(
        [
            {
                "success": True,
                "material_id": "MATCOOL",
                "text": "黄色正方形",
                "raw": {"material_id_source": "tag_payload"},
            },
            {
                "success": True,
                "material_id": "MATCOOL",
                "text": "黄色正方形",
                "raw": {"material_id_source": "tag_payload"},
            },
        ]
    )

    runtime = BoardSortingRuntime(
        system=system,
        camera=camera,
        config=BoardRuntimeConfig(
            conveyor_speed=45,
            center_hold_frames=1,
            stop_on_first_detection=True,
            detection_stop_delay_seconds=0.0,
            stop_cooldown_seconds=30.0,
            capture_settle_time=0.0,
            nfc_retry_interval=0.0,
            capture_dir=str(tmp_path / "captures"),
            nfc_log_path=str(tmp_path / "logs" / "nfc.jsonl"),
        ),
    )

    result = runtime.run(max_items=2, max_frames=6)

    assert result["success"] is True
    assert result["processed_items"] == 1
    assert system.nfc_reader.read_count == 1
    assert len(system.list_history()) == 1

    runtime.shutdown()
    assert camera.released is True


def test_board_runtime_waits_1p0s_before_pausing_after_detection(monkeypatch, tmp_path: Path):
    frame = _build_centered_yellow_square_frame()
    camera = _StaticFrameCamera([frame, frame, frame])

    clock = {"value": 0.0}
    pause_times = []

    def fake_sleep(seconds):
        clock["value"] += float(seconds)

    monkeypatch.setattr("embedded_vision_system.board_runtime.time.sleep", fake_sleep)
    monkeypatch.setattr("embedded_vision_system.board_runtime.time.monotonic", lambda: clock["value"])

    class _PauseSpyDeviceController(_SpyDeviceController):
        def pause_conveyor(self) -> bool:
            pause_times.append(round(clock["value"], 3))
            return super().pause_conveyor()

    system = SortingSystem(
        mode=SystemMode.CONTINUOUS,
        state_path=str(tmp_path / "orders_state.json"),
    )
    assert system.create_test_order("MATDELAY", "木质件", "黄色", shape="正方形") is True
    system.device_controller = _PauseSpyDeviceController()
    system.nfc_reader.set_next_result(
        {
            "success": True,
            "material_id": "MATDELAY",
            "text": "黄色正方形",
            "raw": {"material_id_source": "tag_payload"},
        }
    )

    runtime = BoardSortingRuntime(
        system=system,
        camera=camera,
        config=BoardRuntimeConfig(
            conveyor_speed=45,
            center_hold_frames=1,
            stop_on_first_detection=True,
            detection_stop_delay_seconds=1.0,
            capture_settle_time=0.0,
            nfc_retry_interval=0.0,
            capture_dir=str(tmp_path / "captures"),
            nfc_log_path=str(tmp_path / "logs" / "nfc.jsonl"),
        ),
    )

    result = runtime.run(max_items=1, max_frames=5)

    assert result["success"] is True
    assert result["processed_items"] == 1
    assert pause_times == [1.0]

    runtime.shutdown()
    assert camera.released is True


def test_board_runtime_stops_immediately_when_health_monitor_reports_red(tmp_path: Path):
    frame = _build_centered_yellow_square_frame()
    camera = _StaticFrameCamera([frame, frame, frame])

    system = SortingSystem(
        mode=SystemMode.CONTINUOUS,
        state_path=str(tmp_path / "orders_state.json"),
    )
    system.device_controller = _HealthTripDeviceController(overall="red")
    system.is_ready = True
    system.system_status = "运行中"

    runtime = BoardSortingRuntime(
        system=system,
        camera=camera,
        config=BoardRuntimeConfig(
            conveyor_speed=45,
            detection_stop_delay_seconds=0.0,
            capture_settle_time=0.0,
            nfc_retry_interval=0.0,
            capture_dir=str(tmp_path / "captures"),
            nfc_log_path=str(tmp_path / "logs" / "nfc.jsonl"),
        ),
    )

    result = runtime.run(max_items=1, max_frames=3)

    assert result["success"] is True
    assert result["processed_items"] == 0
    assert system.is_ready is False
    assert system.system_status == "故障停机"
    assert system.device_controller.health_calls >= 1
    assert system.device_controller.conveyor.enabled is False
    assert system.last_processing_result["health_snapshot"]["overall"] == "red"
    assert system.last_processing_result["reason"] == "设备红色故障，已自动停机保护"
    history = system.list_history()
    assert history[-1]["action"] == "stop"
    assert history[-1]["reason"] == "设备红色故障，已自动停机保护"
    assert history[-1]["anomaly_reasons"] == ["设备红色故障"]

    runtime.shutdown()
    assert camera.released is True
