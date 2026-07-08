"""
完整的分拣系统处理引擎
整合摄像头、视觉识别、NFC、健康监测和分拣决策
"""

import logging
from typing import Dict, Optional
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .order_manager import (
    MaterialColor,
    MaterialType,
    OrderManager,
)
from .device_controller import DeviceController
from .consistency_engine import (
    ConsistencyEngine,
    EnhancedSortingDecisionEngine,
)
from .detection.vision_classifier import (
    MaterialClassifier,
    VisionResultConverter,
)
from .detection.shape_color_classifier import (
    ShapeColorResultConverter,
    TraditionalShapeColorClassifier,
)
from .hardware import MockNFCReader
from .storage import get_data_path

logger = logging.getLogger(__name__)


class SystemMode(Enum):
    """系统运行模式"""

    SINGLE_PIECE = "单件模式"
    CONTINUOUS = "连续模式"


@dataclass
class ProcessingResult:
    """单件处理结果"""

    success: bool
    material_id: Optional[str]
    action: str
    route: str
    order_status: str
    reason: str
    reasons: Optional[list] = None
    highest_priority_reason: Optional[str] = None
    vision_result: Optional[Dict] = None
    decision: Optional[Dict] = None
    health_snapshot: Optional[Dict] = None
    history_record: Optional[Dict] = None


class SortingSystem:
    """完整的原材料分拣系统。"""

    def __init__(
        self,
        mode: SystemMode = SystemMode.SINGLE_PIECE,
        confidence_threshold: float = 0.5,
        state_path: Optional[str] = None,
    ):
        self.mode = mode
        self.confidence_threshold = confidence_threshold
        self.state_path = Path(state_path) if state_path else get_data_path(
            "runtime_data",
            "orders_state.json",
        )
        if self.state_path and self.state_path.exists():
            self.order_manager = OrderManager.load_from_file(self.state_path)
        else:
            self.order_manager = OrderManager()
        self.device_controller = DeviceController()
        self.consistency_engine = ConsistencyEngine(confidence_threshold)
        self.decision_engine = EnhancedSortingDecisionEngine(self.consistency_engine)
        self.material_classifier = MaterialClassifier(confidence_threshold)
        self.shape_color_classifier = TraditionalShapeColorClassifier()
        self.nfc_reader = MockNFCReader()

        self.is_ready = False
        self.system_status = "待机"
        self.pending_stop = False
        self.current_material_id: Optional[str] = None
        self.last_processing_result: Optional[Dict] = None

        logger.info("Sorting system initialized in %s mode", mode.value)

    def save_state(self):
        """将订单与历史记录持久化到状态文件。"""
        if self.state_path:
            self.order_manager.save_to_file(self.state_path)

    def startup(self) -> bool:
        """系统启动并执行自检。"""
        logger.info("=== System Startup ===")

        if self.device_controller.alert_latched:
            logger.error("Device is in latched alarm state, reset required")
            self.system_status = "故障停机"
            return False

        check_results = self.device_controller.startup_check()
        all_ok = all(result["ok"] for result in check_results.values())
        if not all_ok:
            logger.error("Device health check failed")
            self.system_status = "自检失败"
            self.is_ready = False
            return False

        if not self.device_controller.start(skip_check=True):
            logger.error("Failed to start device")
            self.system_status = "启动失败"
            self.is_ready = False
            return False

        self.is_ready = True
        self.pending_stop = False
        self.system_status = "运行中"
        return True

    def shutdown(self):
        """系统关闭。"""
        logger.info("=== System Shutdown ===")
        self.device_controller.stop()
        self.is_ready = False
        self.pending_stop = False
        self.current_material_id = None
        self.system_status = "已停止"

    def request_stop(self):
        """请求正常停止，处理完当前件后停机。"""
        if self.is_ready:
            self.pending_stop = True
            self.system_status = "停止中"

    def reset_alarm(self):
        """人工复位设备故障。"""
        self.device_controller.reset_faults()
        self.system_status = "待机"

    def process_material(
        self,
        vision_boxes,
        vision_classes,
        vision_scores,
        class_names,
        image,
        capture_path: Optional[str] = None,
        nfc_result: Optional[Dict] = None,
        vision_result: Optional[Dict] = None,
        runtime_context: Optional[Dict] = None,
    ) -> ProcessingResult:
        """
        处理单个物料。
        完整流程：健康检查 -> NFC -> 视觉 -> 一致性比对 -> 历史记录。
        真正的跑带/舵机动作由上层 runtime 根据 decision.route 决定。
        """
        if not self.is_ready:
            return ProcessingResult(
                success=False,
                material_id=None,
                action="idle",
                route="hold",
                order_status="WAITING_MANUAL",
                reason="系统未就绪",
            )

        health_snapshot = self.device_controller.monitor_health()
        if health_snapshot.get("stopped"):
            self.is_ready = False
            overall = health_snapshot.get("overall")
            if overall == "red":
                self.system_status = "故障停机"
                stop_reason = "设备红色故障，已自动停机保护"
                highest_priority_reason = "设备红色故障"
            else:
                self.system_status = "告警停机"
                stop_reason = "设备黄色告警，已自动停机保护"
                highest_priority_reason = "设备黄色告警"
            return ProcessingResult(
                success=False,
                material_id=None,
                action="stop",
                route="hold",
                order_status="WAITING_MANUAL",
                reason=stop_reason,
                reasons=health_snapshot.get("reasons"),
                highest_priority_reason=highest_priority_reason,
                health_snapshot=health_snapshot,
            )

        nfc_result = dict(nfc_result) if isinstance(nfc_result, dict) else self.nfc_reader.read()
        material_id = nfc_result.get("material_id") if nfc_result.get("success") else None
        self.current_material_id = material_id
        order_requirement = self.get_order_requirement()

        resolved_vision_result = (
            dict(vision_result)
            if isinstance(vision_result, dict)
            else self._build_vision_result(
                vision_boxes=vision_boxes,
                vision_classes=vision_classes,
                vision_scores=vision_scores,
                class_names=class_names,
                image=image,
            )
        )

        decision = self.decision_engine.make_decision(
            material_id=material_id,
            nfc_result=nfc_result,
            vision_result=resolved_vision_result,
            order_params=order_requirement if order_requirement.get("enabled") else None,
        )

        history = self.order_manager.record_detection_event(
            material_id=material_id,
            final_status=decision["order_status"],
            action=decision["action"],
            route=decision["route"],
            reason=decision["reason"],
            anomaly_reasons=decision.get("reasons"),
            vision_result=resolved_vision_result,
            nfc_result=nfc_result,
            comparison_result=decision.get("comparison"),
            health_snapshot=health_snapshot,
            capture_path=capture_path,
            runtime_context=runtime_context,
        )
        completed_order_requirement = None
        if order_requirement.get("enabled") and order_requirement.get("entry_id"):
            completed_order_requirement = self.order_manager.complete_active_order_requirement(
                decision=decision,
                nfc_result=nfc_result,
                vision_result=resolved_vision_result,
                material_id=material_id,
            )

        result = ProcessingResult(
            success=True,
            material_id=material_id,
            action=decision["action"],
            route=decision["route"],
            order_status=decision["order_status"],
            reason=decision["reason"],
            reasons=decision.get("reasons"),
            highest_priority_reason=decision.get("highest_priority_reason"),
            vision_result=resolved_vision_result,
            decision=decision,
            health_snapshot=health_snapshot,
            history_record=history.to_dict(),
        )
        self.last_processing_result = {
            **result.__dict__,
            "order_requirement": order_requirement,
            "completed_order_requirement": completed_order_requirement,
            "order_queue": self.get_order_queue_state(),
        }
        self.current_material_id = None

        if self.pending_stop:
            self.shutdown()
        else:
            self.save_state()

        return result

    def _build_vision_result(
        self,
        vision_boxes,
        vision_classes,
        vision_scores,
        class_names,
        image,
    ) -> Optional[Dict]:
        if image is None:
            logger.warning("No image provided for vision classification")
            return None

        if vision_boxes is None or len(vision_boxes) == 0:
            traditional_result = self.shape_color_classifier.classify_best(image)
            if traditional_result is None:
                logger.warning("No detections from vision and no traditional classification result")
                return None

            logger.info("Traditional classification result: %s", traditional_result.details)
            return ShapeColorResultConverter.to_dict(traditional_result)

        classifications = self.material_classifier.classify(
            image=image,
            detection_boxes=vision_boxes,
            detection_classes=vision_classes,
            detection_scores=vision_scores,
            class_names=class_names,
        )
        if not classifications:
            traditional_result = self.shape_color_classifier.classify_best(image)
            if traditional_result is None:
                logger.warning("No valid classification result")
                return None

            logger.info(
                "Fallback to traditional classification result: %s",
                traditional_result.details,
            )
            return ShapeColorResultConverter.to_dict(traditional_result)

        best_result = classifications[0]
        logger.info("Classification result: %s", best_result.details)
        return VisionResultConverter.to_dict(best_result)

    def create_test_order(
        self,
        material_id: str,
        material_type_str: str,
        color_str: str,
        shape: Optional[str] = None,
        size: Optional[str] = None,
        batch: Optional[str] = None,
        remark: Optional[str] = None,
    ) -> bool:
        """创建测试订单。"""
        type_map = {
            "木质件": MaterialType.WOOD,
            "木头": MaterialType.WOOD,
            "塑料块": MaterialType.PLASTIC,
            "纸盒": MaterialType.BOX,
        }
        color_map = {
            "红色": MaterialColor.RED,
            "蓝色": MaterialColor.BLUE,
            "白色": MaterialColor.WHITE,
            "黑色": MaterialColor.BLACK,
            "绿色": MaterialColor.GREEN,
            "黄色": MaterialColor.YELLOW,
            "紫色": MaterialColor.PURPLE,
        }

        material_type = type_map.get(material_type_str)
        color = color_map.get(color_str)
        if not material_type or not color:
            logger.warning("Invalid material type or color")
            return False

        self.order_manager.create_order(
            material_id=material_id,
            material_type=material_type,
            color=color,
            shape=shape,
            size=size,
            batch=batch,
            remark=remark,
        )
        self.save_state()
        return True

    def get_system_status(self) -> Dict:
        """获取系统状态。"""
        history = self.order_manager.list_history()
        return {
            "ready": self.is_ready,
            "status": self.system_status,
            "mode": self.mode.value,
            "pending_stop": self.pending_stop,
            "device_health": self.device_controller.health_status,
            "device": self.device_controller.get_device_status(),
            "history": {"count": len(history)},
            "decisions": self.decision_engine.get_decision_stats(),
            "processed_materials": self.consistency_engine.get_processed_count(),
            "current_material_id": self.current_material_id,
            "last_processing_result": self.last_processing_result,
        }

    def set_order_requirement(
        self,
        *,
        enabled: bool,
        raw_text: Optional[str],
        spec: Optional[Dict],
    ) -> Dict:
        self.set_order_requirements(
            enabled=enabled,
            requirements=[
                {
                    "raw_text": raw_text,
                    "spec": spec,
                }
            ] if (raw_text or spec) else [],
        )
        return self.get_order_requirement()

    def set_order_requirements(
        self,
        *,
        enabled: bool,
        requirements: list[Dict],
    ) -> Dict:
        queue_state = self.order_manager.replace_order_requirements(
            enabled=enabled,
            requirements=requirements,
        )
        self.save_state()
        return queue_state

    def get_order_requirement(self) -> Dict:
        return self.order_manager.get_active_order_requirement()

    def get_order_queue_state(self) -> Dict:
        return self.order_manager.get_order_queue_state()

    def get_device_status(self) -> Dict:
        return self.device_controller.get_device_status()

    def monitor_device_health(self) -> Dict:
        return self.device_controller.monitor_health()

    def read_device_health_snapshot(self) -> Dict:
        return self.device_controller.read_health_snapshot()

    def list_history(self) -> list:
        return self.order_manager.list_history()
