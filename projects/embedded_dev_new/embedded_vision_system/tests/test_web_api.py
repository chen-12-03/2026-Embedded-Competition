import importlib.util
from pathlib import Path

import cv2
import numpy as np
import pytest

from embedded_vision_system.board_defaults import (
    DEFAULT_BOARD_CAMERA_CLASSIFICATION_FPS,
    DEFAULT_BOARD_CAMERA_FPS,
    DEFAULT_BOARD_CAMERA_FORMAT,
    DEFAULT_BOARD_CAMERA_HEIGHT,
    DEFAULT_BOARD_CAMERA_WEB_FPS,
    DEFAULT_BOARD_CAMERA_WIDTH,
    DEFAULT_BOARD_MPU6050_I2C_ADDRESS,
    DEFAULT_BOARD_MPU6050_I2C_BUS,
    DEFAULT_BOARD_RUNTIME_CENTER_HOLD_FRAMES,
    DEFAULT_BOARD_RUNTIME_DETECTION_STOP_DELAY_SECONDS,
    DEFAULT_BOARD_RUNTIME_STOP_COOLDOWN_SECONDS,
    DEFAULT_BOARD_RUNTIME_STOP_ON_FIRST_DETECTION,
)
from embedded_vision_system.sorting_system import SortingSystem, SystemMode

FLASK_AVAILABLE = importlib.util.find_spec("flask") is not None
pytestmark = pytest.mark.skipif(not FLASK_AVAILABLE, reason="Flask is not installed")

if FLASK_AVAILABLE:
    from embedded_vision_system.web_api import create_app


def _build_centered_yellow_square_frame():
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    cv2.rectangle(frame, (250, 170), (390, 310), (0, 255, 255), thickness=-1)
    return frame


class _FakePreview:
    def __init__(self):
        ok, jpeg = cv2.imencode(".jpg", _build_centered_yellow_square_frame())
        assert ok is True
        self.jpeg = jpeg.tobytes()
        self.closed = False
        self.running = True

    def get_snapshot(self):
        return self.jpeg, 1

    def get_status(self):
        return {
            "ready": self.running,
            "running": self.running,
            "core_running": True,
            "classification_running": True,
            "last_error": None,
            "camera_id": "/dev/video-test",
            "preview_fps": 8,
            "width": 640,
            "height": 480,
            "live_vision_result": {
                "success": True,
                "material_type": "木质件",
                "color": "黄色",
                "shape": "正方形",
                "confidence": 0.88,
                "label": "黄色正方形",
                "source": "live_preview",
            },
        }

    def close(self):
        self.closed = True
        self.running = False

    def open(self, enable_preview: bool = True):
        self.running = bool(enable_preview)

    def set_preview_enabled(self, enabled: bool):
        self.running = bool(enabled)


class _PendingPreview(_FakePreview):
    def get_status(self):
        status = super().get_status()
        status["ready"] = False
        status["running"] = True
        return status


class _FakeRuntimeController:
    def __init__(self, sorting_system, preview=None, nfc_sample_service=None):
        self.sorting_system = sorting_system
        self.preview = preview
        self.nfc_sample_service = nfc_sample_service
        self.started = False
        self.stop_requested = False
        self.closed = False

    def start(self):
        self.started = True
        self.stop_requested = False
        self.sorting_system.is_ready = True
        self.sorting_system.pending_stop = False
        self.sorting_system.system_status = "运行中"
        return True

    def stop(self):
        self.stop_requested = True
        self.sorting_system.pending_stop = True
        self.sorting_system.system_status = "停止中"
        return self.get_status()

    def is_running(self):
        return self.started and not self.stop_requested

    def close(self):
        self.closed = True

    def get_status(self):
        return {
            "running": self.is_running(),
            "stop_requested": self.stop_requested,
            "started_at": "2026-07-07T12:00:00",
            "finished_at": None if self.is_running() else "2026-07-07T12:00:05",
            "camera_source": "shared_preview",
            "last_error": None,
            "last_result": None,
        }


def test_dashboard_endpoint_returns_latest_context(tmp_path: Path):
    system = SortingSystem(
        mode=SystemMode.CONTINUOUS,
        state_path=str(tmp_path / "orders_state.json"),
    )
    assert system.create_test_order("MAT001", "木质件", "黄色", shape="正方形") is True
    assert system.startup() is True

    system.nfc_reader.set_next_result(
        {
            "success": True,
            "material_id": "MAT001",
            "source": "pytest",
        }
    )
    result = system.process_material(
        vision_boxes=None,
        vision_classes=None,
        vision_scores=None,
        class_names=[],
        image=_build_centered_yellow_square_frame(),
    )
    assert result.success is True

    preview = _FakePreview()
    app = create_app(
        system=system,
        state_path=tmp_path / "orders_state.json",
        preview=preview,
    )
    client = app.test_client()

    page = client.get("/")
    assert page.status_code == 200
    page_text = page.get_data(as_text=True)
    assert "产线监控与联调看板" in page_text
    assert "实时摄像头 / 最近抓拍" in page_text

    debug_page = client.get("/debug")
    assert debug_page.status_code == 200
    assert "联调与日志工作台" in debug_page.get_data(as_text=True)

    response = client.get("/api/dashboard")
    assert response.status_code == 200
    payload = response.get_json()

    assert payload["system"]["status"] == "运行中"
    assert payload["order_requirement"]["enabled"] is False
    assert payload["order_queue"]["enabled"] is False
    assert payload["latest"]["nfc"]["material_id"] == "MAT001"
    assert payload["latest"]["vision"]["color"] == "黄色"
    assert payload["latest"]["vision"]["shape"] == "正方形"
    assert payload["latest"]["comparison"]["status"] == "通过"
    assert payload["history"][0]["material_id"] == "MAT001"
    assert payload["latest"]["capture_url"] is None
    assert payload["camera_preview"]["available"] is True
    assert payload["camera_preview"]["running"] is True
    assert payload["camera_preview"]["ready"] is True
    assert payload["nfc_sample"]["sample"]["material_id"] == "MAT001"
    assert payload["nfc_sample"]["sample"]["text"] == "MAT001"
    assert payload["nfc_sample"]["source"] in {"buffered_reader", "latest_history"}
    assert payload["nfc_runtime"]["fallback_to_uid"] is True
    assert payload["latest"]["stage_mode"] == "live"
    assert payload["latest"]["stage_url"] == "/api/camera/snapshot"
    assert payload["camera_preview"]["live_vision_result"]["source"] == "live_preview"
    assert payload["device"]["sort_timing"]["conveyor_half_travel_seconds"] == 10.0
    assert payload["device"]["sort_timing"]["conveyor_advance_time"] == 0.2

    snapshot_response = client.get("/api/camera/snapshot")
    assert snapshot_response.status_code == 200
    assert snapshot_response.mimetype == "image/jpeg"


def test_dashboard_uses_live_stage_when_preview_stream_is_running(tmp_path: Path):
    system = SortingSystem(
        mode=SystemMode.SINGLE_PIECE,
        state_path=str(tmp_path / "orders_state.json"),
    )
    preview = _PendingPreview()
    app = create_app(
        system=system,
        state_path=tmp_path / "orders_state.json",
        preview=preview,
    )
    client = app.test_client()

    payload = client.get("/api/dashboard").get_json()
    assert payload["camera_preview"]["running"] is True
    assert payload["camera_preview"]["ready"] is False
    assert payload["latest"]["stage_mode"] == "live"
    assert payload["latest"]["stage_url"] == "/api/camera/snapshot"


def test_latest_capture_endpoint_serves_recent_image(tmp_path: Path):
    system = SortingSystem(
        mode=SystemMode.SINGLE_PIECE,
        state_path=str(tmp_path / "orders_state.json"),
    )
    assert system.create_test_order("MAT002", "木质件", "黄色", shape="正方形") is True

    capture_path = tmp_path / "captures" / "latest.jpg"
    capture_path.parent.mkdir(parents=True, exist_ok=True)
    assert cv2.imwrite(str(capture_path), _build_centered_yellow_square_frame()) is True

    system.order_manager.record_detection_event(
        material_id="MAT002",
        final_status="已检测通过",
        action="pass",
        route="main_line",
        reason="一致性检查通过，允许放行",
        vision_result={
            "success": True,
            "material_type": "木质件",
            "color": "黄色",
            "shape": "正方形",
            "confidence": 0.91,
            "label": "黄色正方形",
        },
        nfc_result={
            "success": True,
            "material_id": "MAT002",
        },
        comparison_result={
            "status": "通过",
            "details": "一致性检查通过，允许放行",
            "mismatch_fields": [],
            "reasons": [],
        },
        capture_path=str(capture_path),
    )

    app = create_app(
        system=system,
        state_path=tmp_path / "orders_state.json",
        preview=False,
    )
    client = app.test_client()

    capture_response = client.get("/api/capture/latest")
    assert capture_response.status_code == 200
    assert capture_response.mimetype == "image/jpeg"

    dashboard_response = client.get("/api/dashboard")
    dashboard_payload = dashboard_response.get_json()
    assert dashboard_payload["latest"]["capture_url"] == "/api/capture/latest"
    assert dashboard_payload["latest"]["capture_path"] == str(capture_path)


def test_camera_control_endpoint_can_toggle_preview(tmp_path: Path):
    system = SortingSystem(
        mode=SystemMode.SINGLE_PIECE,
        state_path=str(tmp_path / "orders_state.json"),
    )
    preview = _FakePreview()
    app = create_app(
        system=system,
        state_path=tmp_path / "orders_state.json",
        preview=preview,
    )
    client = app.test_client()

    stop_response = client.post("/api/camera/control", json={"enabled": False})
    assert stop_response.status_code == 200
    assert stop_response.get_json()["camera_preview"]["running"] is False

    start_response = client.post("/api/camera/control", json={"enabled": True})
    assert start_response.status_code == 200
    assert start_response.get_json()["camera_preview"]["running"] is True


def test_nfc_sample_endpoint_returns_manual_sample(tmp_path: Path):
    system = SortingSystem(
        mode=SystemMode.SINGLE_PIECE,
        state_path=str(tmp_path / "orders_state.json"),
    )
    app = create_app(
        system=system,
        state_path=tmp_path / "orders_state.json",
        preview=False,
    )
    client = app.test_client()

    response = client.post("/api/nfc/sample", json={})
    assert response.status_code == 200
    payload = response.get_json()

    assert payload["success"] is True
    assert payload["message"] == "NFC 标签文本读取成功"
    assert payload["sample"]["success"] is True
    assert payload["sample"]["text"] == payload["sample"]["material_id"]
    assert payload["status"]["sample"]["material_id"] == payload["sample"]["material_id"]
    assert payload["status"]["source"] == "manual_sample"


def test_nfc_sample_endpoint_marks_uid_only_payload_as_failure(tmp_path: Path):
    system = SortingSystem(
        mode=SystemMode.SINGLE_PIECE,
        state_path=str(tmp_path / "orders_state.json"),
    )
    system.nfc_reader.set_next_result(
        {
            "success": True,
            "material_id": "A1B2C3D4",
            "text": None,
            "raw": {
                "material_id_source": "uid",
                "uid": "A1B2C3D4",
            },
        }
    )
    app = create_app(
        system=system,
        state_path=tmp_path / "orders_state.json",
        preview=False,
    )
    client = app.test_client()

    response = client.post("/api/nfc/sample", json={})
    assert response.status_code == 200
    payload = response.get_json()

    assert payload["success"] is False
    assert payload["message"] == "检测到标签 UID，但未读到标签文本"
    assert payload["sample"]["material_id"] == "A1B2C3D4"
    assert payload["sample"]["text"] is None


def test_orders_endpoint_is_removed(tmp_path: Path):
    system = SortingSystem(
        mode=SystemMode.SINGLE_PIECE,
        state_path=str(tmp_path / "orders_state.json"),
    )
    app = create_app(
        system=system,
        state_path=tmp_path / "orders_state.json",
        preview=False,
    )
    client = app.test_client()

    assert client.get("/api/orders").status_code == 404
    assert client.post("/api/orders", json={}).status_code == 404


def test_order_requirement_endpoint_updates_dashboard_state(tmp_path: Path):
    system = SortingSystem(
        mode=SystemMode.SINGLE_PIECE,
        state_path=str(tmp_path / "orders_state.json"),
    )
    app = create_app(
        system=system,
        state_path=tmp_path / "orders_state.json",
        preview=False,
    )
    client = app.test_client()

    response = client.post(
        "/api/order-requirement",
        json={
            "enabled": True,
            "orders": [
                {"text": "黄色正方形"},
                {"text": "蓝色长方形"},
            ],
        },
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["order_requirement"]["enabled"] is True
    assert payload["order_requirement"]["spec"]["color"] == "黄色"
    assert payload["order_requirement"]["spec"]["shape"] == "正方形"
    assert payload["order_queue"]["enabled"] is True
    assert payload["order_queue"]["pending_count"] == 2
    assert payload["order_queue"]["entries"][1]["raw_text"] == "蓝色长方形"

    dashboard_payload = client.get("/api/dashboard").get_json()
    assert dashboard_payload["order_requirement"]["enabled"] is True
    assert dashboard_payload["order_requirement"]["raw_text"] == "黄色正方形"
    assert dashboard_payload["order_queue"]["pending_count"] == 2
    assert dashboard_payload["order_queue"]["history_count"] == 0


def test_order_requirement_endpoint_rejects_invalid_enabled_text(tmp_path: Path):
    system = SortingSystem(
        mode=SystemMode.SINGLE_PIECE,
        state_path=str(tmp_path / "orders_state.json"),
    )
    app = create_app(
        system=system,
        state_path=tmp_path / "orders_state.json",
        preview=False,
    )
    client = app.test_client()

    response = client.post(
        "/api/order-requirement",
        json={"enabled": True, "orders": [{"text": "MAT001"}]},
    )
    assert response.status_code == 400
    assert "第 1 行订单文本无法解析" in response.get_json()["error"]


def test_order_queue_advances_after_processing_one_material(tmp_path: Path):
    system = SortingSystem(
        mode=SystemMode.SINGLE_PIECE,
        state_path=str(tmp_path / "orders_state.json"),
    )
    system.set_order_requirements(
        enabled=True,
        requirements=[
            {"raw_text": "黄色正方形", "spec": {"color": "黄色", "shape": "正方形"}},
            {"raw_text": "蓝色长方形", "spec": {"color": "蓝色", "shape": "长方形"}},
        ],
    )
    assert system.startup() is True

    result = system.process_material(
        vision_boxes=None,
        vision_classes=None,
        vision_scores=None,
        class_names=[],
        image=_build_centered_yellow_square_frame(),
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
            "label": "黄色正方形",
        },
    )

    assert result.success is True
    queue_state = system.get_order_queue_state()
    assert queue_state["pending_count"] == 1
    assert queue_state["history_count"] == 1
    assert queue_state["active"]["raw_text"] == "蓝色长方形"
    assert queue_state["history"][0]["raw_text"] == "黄色正方形"
    assert queue_state["history"][0]["status"] == "matched"


def test_disabled_order_queue_is_not_consumed_by_processing(tmp_path: Path):
    system = SortingSystem(
        mode=SystemMode.SINGLE_PIECE,
        state_path=str(tmp_path / "orders_state.json"),
    )
    system.set_order_requirements(
        enabled=False,
        requirements=[
            {"raw_text": "黄色正方形", "spec": {"color": "黄色", "shape": "正方形"}},
        ],
    )
    assert system.startup() is True

    result = system.process_material(
        vision_boxes=None,
        vision_classes=None,
        vision_scores=None,
        class_names=[],
        image=_build_centered_yellow_square_frame(),
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
            "label": "黄色正方形",
        },
    )

    assert result.success is True
    queue_state = system.get_order_queue_state()
    assert queue_state["pending_count"] == 1
    assert queue_state["history_count"] == 0


def test_web_api_start_stop_routes_use_runtime_controller(monkeypatch, tmp_path: Path):
    from embedded_vision_system import web_api

    monkeypatch.setattr(web_api, "WebRuntimeController", _FakeRuntimeController)

    system = SortingSystem(
        mode=SystemMode.CONTINUOUS,
        state_path=str(tmp_path / "orders_state.json"),
    )
    app = web_api.create_app(
        system=system,
        state_path=tmp_path / "orders_state.json",
        preview=False,
    )
    client = app.test_client()

    start_response = client.post("/api/control/start")
    assert start_response.status_code == 200
    start_payload = start_response.get_json()
    assert start_payload["success"] is True
    assert start_payload["runtime"]["running"] is True
    assert start_payload["status"]["status"] == "运行中"

    status_payload = client.get("/api/status").get_json()
    assert status_payload["runtime"]["running"] is True

    dashboard_payload = client.get("/api/dashboard").get_json()
    assert dashboard_payload["runtime"]["camera_source"] == "shared_preview"
    assert dashboard_payload["debug"]["runtime"]["running"] is True

    stop_response = client.post("/api/control/stop")
    assert stop_response.status_code == 200
    stop_payload = stop_response.get_json()
    assert stop_payload["runtime"]["running"] is False
    assert stop_payload["runtime"]["stop_requested"] is True
    assert stop_payload["status"]["pending_stop"] is True

    restart_response = client.post("/api/control/start")
    assert restart_response.status_code == 200
    restart_payload = restart_response.get_json()
    assert restart_payload["runtime"]["running"] is True
    assert restart_payload["status"]["status"] == "运行中"


def test_web_api_rejects_duplicate_start_while_runtime_is_running(monkeypatch, tmp_path: Path):
    from embedded_vision_system import web_api

    monkeypatch.setattr(web_api, "WebRuntimeController", _FakeRuntimeController)

    system = SortingSystem(
        mode=SystemMode.CONTINUOUS,
        state_path=str(tmp_path / "orders_state.json"),
    )
    app = web_api.create_app(
        system=system,
        state_path=tmp_path / "orders_state.json",
        preview=False,
    )
    client = app.test_client()

    assert client.post("/api/control/start").status_code == 200
    response = client.post("/api/control/start")
    assert response.status_code == 409
    payload = response.get_json()
    assert payload["success"] is False
    assert payload["error"] == "主流程已在运行"
    assert payload["runtime"]["running"] is True


def test_manual_nfc_sample_is_blocked_while_runtime_is_running(monkeypatch, tmp_path: Path):
    from embedded_vision_system import web_api

    monkeypatch.setattr(web_api, "WebRuntimeController", _FakeRuntimeController)

    system = SortingSystem(
        mode=SystemMode.CONTINUOUS,
        state_path=str(tmp_path / "orders_state.json"),
    )
    app = web_api.create_app(
        system=system,
        state_path=tmp_path / "orders_state.json",
        preview=False,
    )
    client = app.test_client()
    assert client.post("/api/control/start").status_code == 200

    response = client.post("/api/nfc/sample", json={})
    assert response.status_code == 409
    payload = response.get_json()
    assert payload["success"] is False
    assert payload["message"] == "完整主流程运行中，手动 NFC 采样已暂停"
    assert payload["status"]["enabled"] is True


def test_dashboard_reloads_state_from_shared_file(tmp_path: Path):
    state_path = tmp_path / "orders_state.json"
    web_system = SortingSystem(
        mode=SystemMode.SINGLE_PIECE,
        state_path=str(state_path),
    )
    app = create_app(
        system=web_system,
        state_path=state_path,
        preview=False,
    )
    client = app.test_client()

    initial_payload = client.get("/api/dashboard").get_json()
    assert initial_payload["history"] == []

    writer_system = SortingSystem(
        mode=SystemMode.CONTINUOUS,
        state_path=str(state_path),
    )
    writer_system.set_order_requirement(
        enabled=True,
        raw_text="黄色正方形",
        spec={"color": "黄色", "shape": "正方形"},
    )
    assert writer_system.create_test_order("MATSYNC", "木质件", "黄色", shape="正方形") is True
    writer_system.order_manager.record_detection_event(
        material_id="MATSYNC",
        final_status="已检测通过",
        action="pass",
        route="main_line",
        reason="共享状态刷新验证",
        vision_result={
            "success": True,
            "material_type": "木质件",
            "color": "黄色",
            "shape": "正方形",
            "confidence": 0.93,
            "label": "黄色正方形",
        },
        nfc_result={
            "success": True,
            "material_id": "MATSYNC",
        },
        comparison_result={
            "status": "通过",
            "details": "共享状态刷新验证",
            "mismatch_fields": [],
            "reasons": [],
        },
    )
    writer_system.save_state()

    reloaded_payload = client.get("/api/dashboard").get_json()
    assert reloaded_payload["history"][0]["material_id"] == "MATSYNC"
    assert reloaded_payload["latest"]["nfc"]["material_id"] == "MATSYNC"
    assert reloaded_payload["order_requirement"]["enabled"] is True
    assert reloaded_payload["order_requirement"]["spec"]["shape"] == "正方形"
    assert reloaded_payload["order_queue"]["pending_count"] == 1


def test_web_api_applies_sort_timing_from_env(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("EMBEDDED_VISION_SERVO_BACKEND", "mock")
    monkeypatch.setenv("EMBEDDED_VISION_CONVEYOR_BACKEND", "mock")
    monkeypatch.setenv("EMBEDDED_VISION_SORT_PREPARE_PAUSE", "0.6")
    monkeypatch.setenv("EMBEDDED_VISION_SORT_SERVO_SETTLE_TIME", "0.7")
    monkeypatch.setenv("EMBEDDED_VISION_SORT_CONVEYOR_ADVANCE_TIME", "1.4")

    system = SortingSystem(
        mode=SystemMode.SINGLE_PIECE,
        state_path=str(tmp_path / "orders_state.json"),
    )
    app = create_app(
        system=system,
        state_path=tmp_path / "orders_state.json",
        preview=False,
    )
    client = app.test_client()

    payload = client.get("/api/dashboard").get_json()
    assert payload["device"]["sort_timing"] == {
        "prepare_pause": 0.6,
        "servo_settle_time": 0.7,
        "conveyor_advance_time": 1.4,
        "conveyor_half_travel_seconds": 10.0,
    }


def test_web_api_uses_board_defaults_when_creating_own_system(monkeypatch, tmp_path: Path):
    from embedded_vision_system import web_api

    captured_controller_kwargs = {}
    captured_nfc_kwargs = {}

    def fake_build_device_controller(**kwargs):
        captured_controller_kwargs.update(kwargs)
        return SortingSystem(
            mode=SystemMode.SINGLE_PIECE,
            state_path=str(tmp_path / "ignored.json"),
        ).device_controller

    def fake_create_nfc_reader(**kwargs):
        captured_nfc_kwargs.update(kwargs)
        return SortingSystem(
            mode=SystemMode.SINGLE_PIECE,
            state_path=str(tmp_path / "ignored_nfc.json"),
        ).nfc_reader

    monkeypatch.setattr(web_api, "build_device_controller", fake_build_device_controller)
    monkeypatch.setattr(web_api, "create_nfc_reader", fake_create_nfc_reader)

    app = create_app(
        system=None,
        state_path=tmp_path / "orders_state.json",
        preview=False,
    )
    client = app.test_client()

    payload = client.get("/api/dashboard").get_json()
    assert captured_controller_kwargs["servo_backend"] == "stm32_uart"
    assert captured_controller_kwargs["conveyor_backend"] == "stm32_uart"
    assert captured_controller_kwargs["servo_normal_angle"] == 90
    assert captured_controller_kwargs["servo_sort_angle"] == 45
    assert captured_controller_kwargs["servo_sort_secondary_angle"] == 20
    assert captured_controller_kwargs["control_uart_port"] == "/dev/ttyS5"
    assert captured_controller_kwargs["default_conveyor_speed"] == 60
    assert captured_controller_kwargs["conveyor_step_max_hz"] == 60
    assert captured_controller_kwargs["vibration_backend"] == "mpu6050"
    assert captured_controller_kwargs["vibration_i2c_bus"] == DEFAULT_BOARD_MPU6050_I2C_BUS
    assert captured_controller_kwargs["vibration_i2c_address"] == DEFAULT_BOARD_MPU6050_I2C_ADDRESS
    assert captured_controller_kwargs["sort_servo_oscillation_interval"] == 0.5
    assert captured_controller_kwargs["sort_conveyor_advance_time"] == 10.0
    assert captured_nfc_kwargs["backend"] == "pn532_i2c"
    assert captured_nfc_kwargs["i2c_bus"] == 4
    assert captured_nfc_kwargs["i2c_address"] == 0x24
    assert captured_nfc_kwargs["passive_activation_retries"] == 0x02
    assert captured_nfc_kwargs["fallback_to_uid"] is False
    assert payload["nfc_runtime"]["configured_backend"] == "pn532_i2c"
    assert payload["nfc_runtime"]["fallback_to_uid"] is False
    assert payload["nfc_runtime"]["poll_interval"] == 0.5


def test_web_api_uses_board_camera_defaults_when_env_is_missing(monkeypatch):
    from embedded_vision_system import web_api

    monkeypatch.delenv("EMBEDDED_VISION_CAMERA_FPS", raising=False)
    monkeypatch.delenv("EMBEDDED_VISION_CAMERA_WEB_FPS", raising=False)
    monkeypatch.delenv("EMBEDDED_VISION_CAMERA_CLASSIFICATION_FPS", raising=False)
    monkeypatch.setenv("EMBEDDED_VISION_CAMERA_PREVIEW", "0")
    monkeypatch.setenv("EMBEDDED_VISION_CAMERA_CLASSIFICATION", "0")

    runtime_config = web_api._build_board_runtime_config_from_env(preview=None)
    assert runtime_config.fps == DEFAULT_BOARD_CAMERA_FPS
    assert runtime_config.width == DEFAULT_BOARD_CAMERA_WIDTH
    assert runtime_config.height == DEFAULT_BOARD_CAMERA_HEIGHT
    assert runtime_config.pixel_format == DEFAULT_BOARD_CAMERA_FORMAT
    assert runtime_config.center_hold_frames == DEFAULT_BOARD_RUNTIME_CENTER_HOLD_FRAMES
    assert runtime_config.stop_on_first_detection == DEFAULT_BOARD_RUNTIME_STOP_ON_FIRST_DETECTION
    assert runtime_config.detection_stop_delay_seconds == DEFAULT_BOARD_RUNTIME_DETECTION_STOP_DELAY_SECONDS
    assert runtime_config.stop_cooldown_seconds == DEFAULT_BOARD_RUNTIME_STOP_COOLDOWN_SECONDS

    preview = web_api._create_camera_preview_from_env()
    try:
        assert preview.camera_fps == DEFAULT_BOARD_CAMERA_FPS
        assert preview.fps == DEFAULT_BOARD_CAMERA_WEB_FPS
        assert preview.classification_fps == DEFAULT_BOARD_CAMERA_CLASSIFICATION_FPS
        assert preview.width == DEFAULT_BOARD_CAMERA_WIDTH
        assert preview.height == DEFAULT_BOARD_CAMERA_HEIGHT
        assert preview.camera_format == DEFAULT_BOARD_CAMERA_FORMAT
    finally:
        preview.close()
