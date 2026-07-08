"""
订单管理模块
管理物料订单、状态流转和单件历史记录
"""

import json
import logging
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Union
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class OrderStatus(Enum):
    """订单状态"""

    CREATED = "已创建"
    DETECTED_PASS = "已检测通过"
    DETECTION_ANOMALY = "检测异常"
    WAITING_MANUAL = "待人工处理"


class MaterialType(Enum):
    """物料类型"""

    WOOD = "木质件"
    PLASTIC = "塑料块"
    BOX = "纸盒"


class MaterialColor(Enum):
    """物料颜色枚举"""

    RED = "红色"
    BLUE = "蓝色"
    WHITE = "白色"
    BLACK = "黑色"
    GREEN = "绿色"
    YELLOW = "黄色"
    PURPLE = "紫色"
    UNKNOWN = "未知"


MATERIAL_TYPE_ALIASES = {
    "wood": MaterialType.WOOD.value,
    "wooden": MaterialType.WOOD.value,
    "木头": MaterialType.WOOD.value,
    "木块": MaterialType.WOOD.value,
    "木质件": MaterialType.WOOD.value,
    "plastic": MaterialType.PLASTIC.value,
    "塑料": MaterialType.PLASTIC.value,
    "塑料块": MaterialType.PLASTIC.value,
    "box": MaterialType.BOX.value,
    "纸盒": MaterialType.BOX.value,
    "carton": MaterialType.BOX.value,
}

SHAPE_ALIASES = {
    "square": "正方形",
    "正方形": "正方形",
    "方形": "正方形",
    "rectangle": "长方形",
    "rect": "长方形",
    "长方形": "长方形",
    "矩形": "长方形",
    "triangle": "三角形",
    "三角形": "三角形",
    "cone": "圆锥形",
    "conical": "圆锥形",
    "圆锥形": "圆锥形",
    "锥形": "圆锥形",
}

COLOR_ALIASES = {
    "red": MaterialColor.RED.value,
    "红色": MaterialColor.RED.value,
    "blue": MaterialColor.BLUE.value,
    "蓝色": MaterialColor.BLUE.value,
    "white": MaterialColor.WHITE.value,
    "白色": MaterialColor.WHITE.value,
    "black": MaterialColor.BLACK.value,
    "黑色": MaterialColor.BLACK.value,
    "green": MaterialColor.GREEN.value,
    "绿色": MaterialColor.GREEN.value,
    "yellow": MaterialColor.YELLOW.value,
    "黄色": MaterialColor.YELLOW.value,
    "purple": MaterialColor.PURPLE.value,
    "violet": MaterialColor.PURPLE.value,
    "紫色": MaterialColor.PURPLE.value,
    "unknown": MaterialColor.UNKNOWN.value,
    "未知": MaterialColor.UNKNOWN.value,
}


def normalize_material_type(value: Optional[Union[str, MaterialType]]) -> Optional[str]:
    """统一物料类型表示为中文值。"""
    if value is None:
        return None
    if isinstance(value, MaterialType):
        return value.value
    return MATERIAL_TYPE_ALIASES.get(str(value).strip().lower()) or MATERIAL_TYPE_ALIASES.get(str(value).strip())


def normalize_color(value: Optional[Union[str, MaterialColor]]) -> Optional[str]:
    """统一颜色表示为中文值。"""
    if value is None:
        return None
    if isinstance(value, MaterialColor):
        return value.value
    return COLOR_ALIASES.get(str(value).strip().lower()) or COLOR_ALIASES.get(str(value).strip())


def normalize_shape(value: Optional[str]) -> Optional[str]:
    """统一形状表示为中文值。"""
    if value is None:
        return None
    raw_value = str(value).strip()
    return SHAPE_ALIASES.get(raw_value.lower()) or SHAPE_ALIASES.get(raw_value)


def parse_order_status(value: Union[str, OrderStatus]) -> OrderStatus:
    """将字符串或枚举解析为订单状态。"""
    if isinstance(value, OrderStatus):
        return value
    for status in OrderStatus:
        if value in (status.name, status.value):
            return status
    raise ValueError(f"Unknown order status: {value}")


@dataclass
class MaterialSpec:
    """物料规格"""

    material_type: MaterialType
    color: MaterialColor
    shape: Optional[str] = None
    size: Optional[str] = None
    batch: Optional[str] = None
    remark: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            "material_type": self.material_type.value,
            "color": self.color.value,
            "shape": normalize_shape(self.shape),
            "size": self.size,
            "batch": self.batch,
            "remark": self.remark,
        }


@dataclass
class Order:
    """订单对象"""

    material_id: str
    material_spec: MaterialSpec
    status: OrderStatus = OrderStatus.CREATED
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    detected_at: Optional[datetime] = None

    nfc_result: Optional[Dict] = None
    vision_result: Optional[Dict] = None
    comparison_result: Optional[Dict] = None
    health_snapshot: Optional[Dict] = None

    sortable: bool = False
    route: str = "main_line"
    detection_notes: str = ""
    anomaly_reasons: List[str] = field(default_factory=list)
    capture_path: Optional[str] = None

    def to_order_params(self) -> Dict:
        """输出用于比对的结构化订单参数。"""
        params = self.material_spec.to_dict()
        params["status"] = self.status.value
        return params

    def to_dict(self) -> Dict:
        """转换为可序列化字典。"""
        return {
            "material_id": self.material_id,
            "material_spec": self.material_spec.to_dict(),
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "detected_at": self.detected_at.isoformat() if self.detected_at else None,
            "nfc_result": self.nfc_result,
            "vision_result": self.vision_result,
            "comparison_result": self.comparison_result,
            "health_snapshot": self.health_snapshot,
            "sortable": self.sortable,
            "route": self.route,
            "detection_notes": self.detection_notes,
            "anomaly_reasons": list(self.anomaly_reasons),
            "capture_path": self.capture_path,
        }


@dataclass
class HistoryRecord:
    """单件历史记录"""

    material_id: Optional[str]
    checked_at: datetime
    final_status: str
    action: str
    route: str
    reason: str
    anomaly_reasons: List[str] = field(default_factory=list)
    order_snapshot: Optional[Dict] = None
    vision_snapshot: Optional[Dict] = None
    nfc_snapshot: Optional[Dict] = None
    comparison_snapshot: Optional[Dict] = None
    health_snapshot: Optional[Dict] = None
    capture_path: Optional[str] = None
    runtime_context: Optional[Dict] = None

    def to_dict(self) -> Dict:
        return {
            "material_id": self.material_id,
            "checked_at": self.checked_at.isoformat(),
            "final_status": self.final_status,
            "action": self.action,
            "route": self.route,
            "reason": self.reason,
            "anomaly_reasons": list(self.anomaly_reasons),
            "order_snapshot": self.order_snapshot,
            "vision_snapshot": self.vision_snapshot,
            "nfc_snapshot": self.nfc_snapshot,
            "comparison_snapshot": self.comparison_snapshot,
            "health_snapshot": self.health_snapshot,
            "capture_path": self.capture_path,
            "runtime_context": self.runtime_context,
        }


class OrderManager:
    """订单管理器"""

    def __init__(self):
        self.orders: Dict[str, Order] = {}
        self.order_history: List[HistoryRecord] = []
        self.order_queue_enabled: bool = False
        self.order_queue_updated_at: Optional[str] = None
        self.order_requirement_queue: List[Dict] = []
        self.order_requirement_history: List[Dict] = []
        self._order_requirement_sequence: int = 0
        self.active_order_requirement: Dict[str, Optional[Union[str, Dict, bool]]] = {
            "enabled": False,
            "raw_text": "",
            "spec": None,
            "updated_at": None,
        }
        self._sync_legacy_active_order_requirement()

    def _next_order_requirement_id(self) -> str:
        self._order_requirement_sequence += 1
        return f"REQ-{self._order_requirement_sequence:04d}"

    def _copy_order_requirement_entry(self, entry: Dict) -> Dict:
        return {
            "id": entry.get("id"),
            "raw_text": entry.get("raw_text") or "",
            "spec": dict(entry.get("spec")) if isinstance(entry.get("spec"), dict) else None,
            "status": entry.get("status") or "pending",
            "created_at": entry.get("created_at"),
            "updated_at": entry.get("updated_at"),
            "completed_at": entry.get("completed_at"),
            "last_result": (
                dict(entry.get("last_result"))
                if isinstance(entry.get("last_result"), dict)
                else None
            ),
        }

    def _decorate_order_requirement_entry(self, entry: Dict, *, index: int) -> Dict:
        return {
            **self._copy_order_requirement_entry(entry),
            "position": index + 1,
            "is_active": index == 0,
            "summary": self.describe_order_requirement(
                raw_text=entry.get("raw_text"),
                spec=entry.get("spec"),
            ),
        }

    def _get_active_order_requirement_entry(self) -> Optional[Dict]:
        if not self.order_requirement_queue:
            return None
        return self.order_requirement_queue[0]

    def _sync_legacy_active_order_requirement(self) -> None:
        active_entry = self._get_active_order_requirement_entry()
        active_spec = (
            dict(active_entry.get("spec"))
            if isinstance(active_entry, dict) and isinstance(active_entry.get("spec"), dict)
            else None
        )
        self.active_order_requirement = {
            "enabled": bool(self.order_queue_enabled and active_entry is not None),
            "queue_enabled": bool(self.order_queue_enabled),
            "raw_text": active_entry.get("raw_text") if isinstance(active_entry, dict) else "",
            "spec": active_spec,
            "updated_at": (
                active_entry.get("updated_at")
                if isinstance(active_entry, dict)
                else self.order_queue_updated_at
            ),
            "entry_id": active_entry.get("id") if isinstance(active_entry, dict) else None,
            "pending_count": len(self.order_requirement_queue),
            "history_count": len(self.order_requirement_history),
            "exhausted": bool(self.order_queue_enabled and not self.order_requirement_queue),
        }

    def describe_order_requirement(
        self,
        *,
        raw_text: Optional[str],
        spec: Optional[Dict],
    ) -> str:
        if raw_text:
            return str(raw_text).strip()
        if not isinstance(spec, dict):
            return "--"
        parts = [
            spec.get("color"),
            spec.get("shape"),
            spec.get("material_type"),
        ]
        normalized_parts = [str(item).strip() for item in parts if item]
        return " ".join(normalized_parts) if normalized_parts else "--"

    def replace_order_requirements(
        self,
        *,
        enabled: bool,
        requirements: List[Dict],
    ) -> Dict:
        now = datetime.now().isoformat()
        queue: List[Dict] = []
        for item in requirements:
            raw_text = (item.get("raw_text") or "").strip()
            spec = dict(item.get("spec")) if isinstance(item.get("spec"), dict) else None
            if not raw_text:
                continue
            queue.append(
                {
                    "id": self._next_order_requirement_id(),
                    "raw_text": raw_text,
                    "spec": spec,
                    "status": "pending",
                    "created_at": now,
                    "updated_at": now,
                    "completed_at": None,
                    "last_result": None,
                }
            )

        self.order_queue_enabled = bool(enabled)
        self.order_queue_updated_at = now
        self.order_requirement_queue = queue
        self._sync_legacy_active_order_requirement()
        return self.get_order_queue_state()

    def get_order_queue_state(self) -> Dict:
        active_entry = self._get_active_order_requirement_entry()
        return {
            "enabled": bool(self.order_queue_enabled),
            "updated_at": self.order_queue_updated_at,
            "pending_count": len(self.order_requirement_queue),
            "history_count": len(self.order_requirement_history),
            "exhausted": bool(self.order_queue_enabled and not self.order_requirement_queue),
            "active": (
                self._decorate_order_requirement_entry(active_entry, index=0)
                if isinstance(active_entry, dict)
                else None
            ),
            "entries": [
                self._decorate_order_requirement_entry(entry, index=index)
                for index, entry in enumerate(self.order_requirement_queue)
            ],
            "history": [
                self._copy_order_requirement_entry(entry)
                for entry in reversed(self.order_requirement_history)
            ],
        }

    def complete_active_order_requirement(
        self,
        *,
        decision: Optional[Dict],
        nfc_result: Optional[Dict] = None,
        vision_result: Optional[Dict] = None,
        material_id: Optional[str] = None,
    ) -> Optional[Dict]:
        if not self.order_requirement_queue:
            return None

        active_entry = self.order_requirement_queue.pop(0)
        now = datetime.now().isoformat()
        comparison = (decision or {}).get("comparison") or {}
        status = "matched"
        if comparison.get("status") in {"异常", "NFC异常", "无识别结果", "低置信度"}:
            status = "anomaly"
        elif (decision or {}).get("requires_manual_review"):
            status = "manual"
        elif (decision or {}).get("route") == "side_bin":
            status = "anomaly"

        completed_entry = {
            **self._copy_order_requirement_entry(active_entry),
            "status": status,
            "updated_at": now,
            "completed_at": now,
            "last_result": {
                "material_id": material_id,
                "action": (decision or {}).get("action"),
                "route": (decision or {}).get("route"),
                "order_status": (decision or {}).get("order_status"),
                "reason": (decision or {}).get("reason"),
                "comparison_status": comparison.get("status"),
                "nfc_text": (nfc_result or {}).get("text"),
                "vision_label": (
                    (vision_result or {}).get("label")
                    or self.describe_order_requirement(
                        raw_text=None,
                        spec=vision_result if isinstance(vision_result, dict) else None,
                    )
                ),
            },
        }
        self.order_requirement_history.append(completed_entry)
        self.order_queue_updated_at = now
        self._sync_legacy_active_order_requirement()
        return self._copy_order_requirement_entry(completed_entry)

    def create_order(
        self,
        material_id: str,
        material_type: MaterialType,
        color: MaterialColor,
        shape: Optional[str] = None,
        size: Optional[str] = None,
        batch: Optional[str] = None,
        remark: Optional[str] = None,
    ) -> Order:
        """创建订单。"""
        if material_id in self.orders:
            logger.warning("Material ID %s already exists", material_id)
            return self.orders[material_id]

        spec = MaterialSpec(
            material_type=material_type,
            color=color,
            shape=shape,
            size=size,
            batch=batch,
            remark=remark,
        )
        order = Order(material_id=material_id, material_spec=spec)
        self.orders[material_id] = order

        logger.info(
            "Order created: %s - %s %s",
            material_id,
            material_type.value,
            color.value,
        )
        return order

    def get_order(self, material_id: Optional[str]) -> Optional[Order]:
        """获取订单。"""
        if material_id is None:
            return None
        return self.orders.get(material_id)

    def list_orders(self) -> List[Dict]:
        """列出全部订单。"""
        return [order.to_dict() for order in self.orders.values()]

    def update_order_status(
        self,
        material_id: str,
        status: Union[str, OrderStatus],
        notes: str = "",
        anomaly_reasons: Optional[List[str]] = None,
        sortable: Optional[bool] = None,
        route: Optional[str] = None,
        health_snapshot: Optional[Dict] = None,
        capture_path: Optional[str] = None,
    ) -> bool:
        """更新订单状态。"""
        order = self.get_order(material_id)
        if not order:
            logger.warning("Order not found: %s", material_id)
            return False

        resolved_status = parse_order_status(status)
        old_status = order.status

        order.status = resolved_status
        order.updated_at = datetime.now()
        order.detected_at = datetime.now()
        order.detection_notes = notes
        order.anomaly_reasons = list(anomaly_reasons or [])
        if sortable is not None:
            order.sortable = sortable
        if route is not None:
            order.route = route
        if health_snapshot is not None:
            order.health_snapshot = health_snapshot
        if capture_path is not None:
            order.capture_path = capture_path

        logger.info(
            "Order status updated: %s %s -> %s",
            material_id,
            old_status.value,
            resolved_status.value,
        )
        return True

    def set_nfc_result(self, material_id: str, result: Optional[Dict]) -> bool:
        order = self.get_order(material_id)
        if not order:
            return False
        order.nfc_result = result
        order.updated_at = datetime.now()
        return True

    def set_vision_result(self, material_id: str, result: Optional[Dict]) -> bool:
        order = self.get_order(material_id)
        if not order:
            return False
        order.vision_result = result
        order.updated_at = datetime.now()
        return True

    def set_comparison_result(self, material_id: str, result: Optional[Dict]) -> bool:
        order = self.get_order(material_id)
        if not order:
            return False
        order.comparison_result = result
        order.updated_at = datetime.now()
        return True

    def mark_for_sorting(self, material_id: str, reason: str = "") -> bool:
        order = self.get_order(material_id)
        if not order:
            return False
        order.sortable = True
        if reason:
            order.detection_notes = reason
        order.updated_at = datetime.now()
        logger.info("Material %s marked for sorting: %s", material_id, reason)
        return True

    def record_detection_event(
        self,
        material_id: Optional[str],
        final_status: Union[str, OrderStatus],
        action: str,
        route: str,
        reason: str,
        anomaly_reasons: Optional[List[str]] = None,
        vision_result: Optional[Dict] = None,
        nfc_result: Optional[Dict] = None,
        comparison_result: Optional[Dict] = None,
        health_snapshot: Optional[Dict] = None,
        capture_path: Optional[str] = None,
        runtime_context: Optional[Dict] = None,
    ) -> HistoryRecord:
        """记录单件处理历史。"""
        order = self.get_order(material_id)
        resolved_status = parse_order_status(final_status).value

        if order:
            self.update_order_status(
                material_id=order.material_id,
                status=resolved_status,
                notes=reason,
                anomaly_reasons=anomaly_reasons,
                sortable=(route == "side_bin"),
                route=route,
                health_snapshot=health_snapshot,
                capture_path=capture_path,
            )
            self.set_nfc_result(order.material_id, nfc_result)
            self.set_vision_result(order.material_id, vision_result)
            self.set_comparison_result(order.material_id, comparison_result)

        record = HistoryRecord(
            material_id=material_id,
            checked_at=datetime.now(),
            final_status=resolved_status,
            action=action,
            route=route,
            reason=reason,
            anomaly_reasons=list(anomaly_reasons or []),
            order_snapshot=order.to_dict() if order else None,
            vision_snapshot=vision_result,
            nfc_snapshot=nfc_result,
            comparison_snapshot=comparison_result,
            health_snapshot=health_snapshot,
            capture_path=capture_path,
            runtime_context=runtime_context,
        )
        self.order_history.append(record)
        return record

    def set_active_order_requirement(
        self,
        *,
        enabled: bool,
        raw_text: Optional[str],
        spec: Optional[Dict],
    ) -> Dict:
        self.replace_order_requirements(
            enabled=enabled,
            requirements=[
                {
                    "raw_text": raw_text,
                    "spec": spec,
                }
            ] if (raw_text or spec) else [],
        )
        return self.get_active_order_requirement()

    def get_active_order_requirement(self) -> Dict:
        self._sync_legacy_active_order_requirement()
        return {
            "enabled": bool(self.active_order_requirement.get("enabled", False)),
            "queue_enabled": bool(self.active_order_requirement.get("queue_enabled", False)),
            "raw_text": self.active_order_requirement.get("raw_text") or "",
            "spec": (
                dict(self.active_order_requirement.get("spec"))
                if isinstance(self.active_order_requirement.get("spec"), dict)
                else None
            ),
            "updated_at": self.active_order_requirement.get("updated_at"),
            "entry_id": self.active_order_requirement.get("entry_id"),
            "pending_count": int(self.active_order_requirement.get("pending_count", 0)),
            "history_count": int(self.active_order_requirement.get("history_count", 0)),
            "exhausted": bool(self.active_order_requirement.get("exhausted", False)),
        }

    def list_history(self) -> List[Dict]:
        """列出历史记录。"""
        return [record.to_dict() for record in self.order_history]

    def get_pending_orders(self) -> List[Order]:
        return [order for order in self.orders.values() if order.status == OrderStatus.CREATED]

    def get_anomaly_orders(self) -> List[Order]:
        return [
            order
            for order in self.orders.values()
            if order.status == OrderStatus.DETECTION_ANOMALY
        ]

    def get_waiting_manual_orders(self) -> List[Order]:
        return [
            order
            for order in self.orders.values()
            if order.status == OrderStatus.WAITING_MANUAL
        ]

    def get_passed_orders(self) -> List[Order]:
        return [
            order
            for order in self.orders.values()
            if order.status == OrderStatus.DETECTED_PASS
        ]

    def get_statistics(self) -> Dict:
        return {
            "total_orders": len(self.orders),
            "pending": len(self.get_pending_orders()),
            "passed": len(self.get_passed_orders()),
            "anomaly": len(self.get_anomaly_orders()),
            "waiting_manual": len(self.get_waiting_manual_orders()),
            "history_count": len(self.order_history),
        }

    def to_dict(self, material_id: str) -> Optional[Dict]:
        order = self.get_order(material_id)
        return order.to_dict() if order else None

    def save_to_file(self, filepath: Union[str, Path]) -> None:
        """保存订单和历史到 JSON 文件。"""
        target = Path(filepath)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "orders": self.list_orders(),
            "history": self.list_history(),
            "active_order_requirement": self.get_active_order_requirement(),
            "order_requirement_enabled": self.order_queue_enabled,
            "order_requirement_updated_at": self.order_queue_updated_at,
            "order_requirement_queue": [
                self._copy_order_requirement_entry(entry)
                for entry in self.order_requirement_queue
            ],
            "order_requirement_history": [
                self._copy_order_requirement_entry(entry)
                for entry in self.order_requirement_history
            ],
            "order_requirement_sequence": self._order_requirement_sequence,
        }
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load_from_file(cls, filepath: Union[str, Path]) -> "OrderManager":
        """从 JSON 文件恢复订单和历史。"""
        manager = cls()
        source = Path(filepath)
        if not source.exists():
            return manager

        payload = json.loads(source.read_text(encoding="utf-8"))
        queue_entries = payload.get("order_requirement_queue")
        if isinstance(queue_entries, list):
            manager.order_queue_enabled = bool(payload.get("order_requirement_enabled", False))
            manager.order_queue_updated_at = payload.get("order_requirement_updated_at")
            manager.order_requirement_queue = [
                manager._copy_order_requirement_entry(entry)
                for entry in queue_entries
                if isinstance(entry, dict)
            ]
            manager.order_requirement_history = [
                manager._copy_order_requirement_entry(entry)
                for entry in payload.get("order_requirement_history", [])
                if isinstance(entry, dict)
            ]
            manager._order_requirement_sequence = int(payload.get("order_requirement_sequence", 0))
            if manager._order_requirement_sequence <= 0:
                known_ids = manager.order_requirement_queue + manager.order_requirement_history
                max_seq = 0
                for entry in known_ids:
                    entry_id = str(entry.get("id") or "")
                    if entry_id.startswith("REQ-") and entry_id[4:].isdigit():
                        max_seq = max(max_seq, int(entry_id[4:]))
                manager._order_requirement_sequence = max_seq
            manager._sync_legacy_active_order_requirement()
        else:
            requirement = payload.get("active_order_requirement")
            if isinstance(requirement, dict):
                manager.set_active_order_requirement(
                    enabled=bool(requirement.get("queue_enabled", requirement.get("enabled", False))),
                    raw_text=requirement.get("raw_text"),
                    spec=(
                        dict(requirement.get("spec"))
                        if isinstance(requirement.get("spec"), dict)
                        else None
                    ),
                )
        for order_data in payload.get("orders", []):
            spec_data = order_data["material_spec"]
            material_type = MaterialType(normalize_material_type(spec_data["material_type"]))
            color = MaterialColor(normalize_color(spec_data["color"]))
            order = manager.create_order(
                material_id=order_data["material_id"],
                material_type=material_type,
                color=color,
                shape=normalize_shape(spec_data.get("shape")),
                size=spec_data.get("size"),
                batch=spec_data.get("batch"),
                remark=spec_data.get("remark"),
            )
            order.status = parse_order_status(order_data["status"])
            order.created_at = datetime.fromisoformat(order_data["created_at"])
            order.updated_at = datetime.fromisoformat(order_data["updated_at"])
            order.detected_at = (
                datetime.fromisoformat(order_data["detected_at"])
                if order_data.get("detected_at")
                else None
            )
            order.nfc_result = order_data.get("nfc_result")
            order.vision_result = order_data.get("vision_result")
            order.comparison_result = order_data.get("comparison_result")
            order.health_snapshot = order_data.get("health_snapshot")
            order.sortable = order_data.get("sortable", False)
            order.route = order_data.get("route", "main_line")
            order.detection_notes = order_data.get("detection_notes", "")
            order.anomaly_reasons = list(order_data.get("anomaly_reasons", []))
            order.capture_path = order_data.get("capture_path")

        for record_data in payload.get("history", []):
            manager.order_history.append(
                HistoryRecord(
                    material_id=record_data.get("material_id"),
                    checked_at=datetime.fromisoformat(record_data["checked_at"]),
                    final_status=record_data["final_status"],
                    action=record_data["action"],
                    route=record_data["route"],
                    reason=record_data["reason"],
                    anomaly_reasons=list(record_data.get("anomaly_reasons", [])),
                    order_snapshot=record_data.get("order_snapshot"),
                    vision_snapshot=record_data.get("vision_snapshot"),
                    nfc_snapshot=record_data.get("nfc_snapshot"),
                    comparison_snapshot=record_data.get("comparison_snapshot"),
                    health_snapshot=record_data.get("health_snapshot"),
                    capture_path=record_data.get("capture_path"),
                    runtime_context=record_data.get("runtime_context"),
                )
            )
        return manager


__all__ = [
    "OrderManager",
    "Order",
    "OrderStatus",
    "MaterialType",
    "MaterialColor",
    "MaterialSpec",
    "HistoryRecord",
    "normalize_material_type",
    "normalize_color",
    "normalize_shape",
    "parse_order_status",
]
