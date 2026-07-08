"""
一致性比对引擎
比对 NFC 标签文本与视觉识别结果，并输出分拣决策
"""

import json
import logging
import re
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from enum import Enum

from .hardware import has_readable_text_payload
from .order_manager import (
    COLOR_ALIASES,
    MATERIAL_TYPE_ALIASES,
    SHAPE_ALIASES,
    normalize_color,
    normalize_material_type,
    normalize_shape,
)

logger = logging.getLogger(__name__)


class ComparisonStatus(Enum):
    """比对结果状态"""

    PASS = "通过"
    ANOMALY = "异常"
    NO_VISION_RESULT = "无识别结果"
    LOW_CONFIDENCE = "低置信度"
    NO_REFERENCE = "无比对目标"
    NFC_ERROR = "NFC异常"


REASON_PRIORITIES = {
    "设备红色故障": 1,
    "缺少比对目标": 2,
    "视觉识别失败": 3,
    "类型不一致": 4,
    "形状不一致": 4,
    "颜色不一致": 5,
    "设备黄色告警": 6,
    "低置信度": 6,
    "NFC异常或无标签": 2,
}


@dataclass
class ComparisonResult:
    """比对结果"""

    status: ComparisonStatus
    material_id: Optional[str] = None
    vision_result: Optional[Dict] = None
    order_params: Optional[Dict] = None
    details: str = ""
    sortable: bool = False
    reasons: List[str] = field(default_factory=list)
    highest_priority_reason: Optional[str] = None
    mismatch_fields: List[str] = field(default_factory=list)
    reference_source: Optional[str] = None
    requires_manual_review: bool = False
    priority: int = 99
    nfc_params: Optional[Dict] = None
    order_requirement: Optional[Dict] = None

    def to_dict(self) -> Dict:
        return {
            "status": self.status.value,
            "material_id": self.material_id,
            "vision_result": self.vision_result,
            "order_params": self.order_params,
            "details": self.details,
            "sortable": self.sortable,
            "reasons": list(self.reasons),
            "highest_priority_reason": self.highest_priority_reason,
            "mismatch_fields": list(self.mismatch_fields),
            "reference_source": self.reference_source,
            "requires_manual_review": self.requires_manual_review,
            "priority": self.priority,
            "nfc_params": self.nfc_params,
            "order_requirement": self.order_requirement,
        }


class ConsistencyEngine:
    """一致性比对引擎。"""

    def __init__(self, confidence_threshold: float = 0.5):
        self.confidence_threshold = confidence_threshold
        logger.info(
            "Consistency engine initialized (conf_threshold=%s)",
            confidence_threshold,
        )

    def compare(
        self,
        material_id: Optional[str],
        nfc_result: Optional[Dict],
        vision_result: Optional[Dict],
        order_params: Optional[Dict],
    ) -> ComparisonResult:
        """执行一致性比对。"""
        order_requirement = self._normalize_order_requirement(order_params)
        nfc_text_ready = has_readable_text_payload(nfc_result)
        if nfc_result is None or (not nfc_result.get("success", False) and not nfc_text_ready):
            return self._result(
                status=ComparisonStatus.NFC_ERROR,
                material_id=material_id,
                details="NFC读卡异常或无标签",
                sortable=True,
                reasons=["NFC异常或无标签"],
                order_requirement=order_requirement,
            )

        nfc_params = self._extract_reference_params_from_nfc_text(nfc_result)
        if order_requirement is not None and order_requirement.get("enabled"):
            return self._compare_with_order_requirement(
                material_id=material_id,
                nfc_result=nfc_result,
                nfc_params=nfc_params,
                vision_result=vision_result,
                order_requirement=order_requirement,
            )

        reference_params, reference_source = self._resolve_reference_params(
            nfc_result=nfc_result,
            order_params=order_params,
        )

        if reference_params is None:
            return self._result(
                status=ComparisonStatus.NO_REFERENCE,
                material_id=material_id,
                order_params=order_params,
                details="NFC 文本里没有可比对的颜色/形状/类型信息",
                sortable=True,
                requires_manual_review=True,
                reasons=["缺少比对目标"],
                nfc_params=nfc_params,
            )

        if vision_result is None or not vision_result.get("success", False):
            return self._result(
                status=ComparisonStatus.NO_VISION_RESULT,
                material_id=material_id,
                order_params=reference_params,
                details="视觉识别失败",
                sortable=True,
                requires_manual_review=True,
                reasons=["视觉识别失败"],
                reference_source=reference_source,
                nfc_params=nfc_params,
            )

        confidence = float(vision_result.get("confidence", 0.0))
        if confidence < self.confidence_threshold:
            return self._result(
                status=ComparisonStatus.LOW_CONFIDENCE,
                material_id=material_id,
                vision_result=vision_result,
                order_params=reference_params,
                details=f"置信度不足：{confidence:.2%} < {self.confidence_threshold:.2%}",
                sortable=True,
                requires_manual_review=True,
                reasons=["低置信度"],
                reference_source=reference_source,
                nfc_params=nfc_params,
            )

        mismatch_fields, reasons = self._compare_specs(vision_result, reference_params)
        if reasons:
            return self._result(
                status=ComparisonStatus.ANOMALY,
                material_id=material_id,
                vision_result=vision_result,
                order_params=reference_params,
                details="视觉识别结果与 NFC 文本不一致",
                sortable=True,
                mismatch_fields=mismatch_fields,
                reasons=reasons,
                reference_source=reference_source,
                nfc_params=nfc_params,
            )

        return self._result(
            status=ComparisonStatus.PASS,
            material_id=material_id,
            vision_result=vision_result,
            order_params=reference_params,
            details="NFC 文本与视觉识别一致，允许放行",
            reference_source=reference_source,
            nfc_params=nfc_params,
        )

    def parse_reference_text(self, text: Optional[str]) -> Optional[Dict]:
        if not isinstance(text, str) or not text.strip():
            return None
        cleaned = text.strip()
        parsed = self._extract_reference_params_from_json_text(cleaned)
        if parsed:
            return parsed
        return self._extract_reference_params_from_free_text(cleaned)

    def normalize_compare_text(self, text: Optional[str]) -> str:
        if not isinstance(text, str):
            return ""

        normalized = text.strip().lower()
        normalized = re.sub(r"[\u200b-\u200f\ufeff]", "", normalized)
        return "".join(char for char in normalized if char.isalnum())

    def _compare_specs(self, vision_result: Dict, order_params: Dict) -> tuple[List[str], List[str]]:
        """逐项比对类型、颜色和形状。"""
        mismatch_fields: List[str] = []
        reasons: List[str] = []

        vision_type = normalize_material_type(vision_result.get("material_type"))
        vision_color = normalize_color(vision_result.get("color"))
        vision_shape = normalize_shape(vision_result.get("shape"))
        order_type = normalize_material_type(order_params.get("material_type"))
        order_color = normalize_color(order_params.get("color"))
        order_shape = normalize_shape(order_params.get("shape"))

        if order_type is not None and vision_type != order_type:
            mismatch_fields.append("material_type")
            reasons.append("类型不一致")
        if order_color is not None and vision_color != order_color:
            mismatch_fields.append("color")
            reasons.append("颜色不一致")
        if order_shape is not None and "shape" in vision_result and vision_shape != order_shape:
            mismatch_fields.append("shape")
            reasons.append("形状不一致")

        return mismatch_fields, reasons

    def _resolve_reference_params(
        self,
        nfc_result: Optional[Dict],
        order_params: Optional[Dict],
    ) -> tuple[Optional[Dict], Optional[str]]:
        del order_params
        nfc_text_params = self._extract_reference_params_from_nfc_text(nfc_result)
        if nfc_text_params:
            return nfc_text_params, "nfc_text"

        return None, None

    def _extract_reference_params_from_nfc_text(
        self,
        nfc_result: Optional[Dict],
    ) -> Optional[Dict]:
        if not isinstance(nfc_result, dict):
            return None
        raw_text = nfc_result.get("text")
        return self.parse_reference_text(raw_text)

    def _extract_reference_params_from_json_text(self, text: str) -> Optional[Dict]:
        candidate = text.strip()
        parsed_payload = None
        try:
            parsed_payload = json.loads(candidate)
        except json.JSONDecodeError:
            start = candidate.find("{")
            end = candidate.rfind("}")
            if start >= 0 and end > start:
                try:
                    parsed_payload = json.loads(candidate[start:end + 1])
                except json.JSONDecodeError:
                    parsed_payload = None
        if not isinstance(parsed_payload, dict):
            return None

        spec = self._build_reference_spec(
            material_type=parsed_payload.get("material_type")
            or parsed_payload.get("type")
            or parsed_payload.get("material"),
            color=parsed_payload.get("color"),
            shape=parsed_payload.get("shape"),
        )
        if spec:
            return spec

        label = parsed_payload.get("label") or parsed_payload.get("text") or parsed_payload.get("name")
        if isinstance(label, str):
            return self._extract_reference_params_from_free_text(label)
        return None

    def _extract_reference_params_from_free_text(self, text: str) -> Optional[Dict]:
        material_type = self._find_alias_in_text(text, MATERIAL_TYPE_ALIASES, normalize_material_type)
        color = self._find_alias_in_text(text, COLOR_ALIASES, normalize_color)
        shape = self._find_alias_in_text(text, SHAPE_ALIASES, normalize_shape)
        return self._build_reference_spec(
            material_type=material_type,
            color=color,
            shape=shape,
        )

    def _find_alias_in_text(self, text: str, mapping: Dict[str, str], normalizer) -> Optional[str]:
        lowered = text.lower()
        for alias in sorted(mapping.keys(), key=len, reverse=True):
            alias_text = str(alias).strip()
            if not alias_text:
                continue
            if alias_text.lower() in lowered:
                return normalizer(mapping[alias_text])
        return None

    def _build_reference_spec(
        self,
        material_type: Optional[str] = None,
        color: Optional[str] = None,
        shape: Optional[str] = None,
    ) -> Optional[Dict]:
        spec = {
            "material_type": normalize_material_type(material_type),
            "color": normalize_color(color),
            "shape": normalize_shape(shape),
        }
        if not any(spec.values()):
            return None
        return spec

    def _result(
        self,
        status: ComparisonStatus,
        material_id: Optional[str] = None,
        vision_result: Optional[Dict] = None,
        order_params: Optional[Dict] = None,
        details: str = "",
        sortable: bool = False,
        reasons: Optional[List[str]] = None,
        mismatch_fields: Optional[List[str]] = None,
        reference_source: Optional[str] = None,
        requires_manual_review: bool = False,
        nfc_params: Optional[Dict] = None,
        order_requirement: Optional[Dict] = None,
    ) -> ComparisonResult:
        reason_list = list(reasons or [])
        highest_priority_reason, priority = self._resolve_priority(reason_list)
        return ComparisonResult(
            status=status,
            material_id=material_id,
            vision_result=vision_result,
            order_params=order_params,
            details=details,
            sortable=sortable,
            reasons=reason_list,
            highest_priority_reason=highest_priority_reason,
            mismatch_fields=list(mismatch_fields or []),
            reference_source=reference_source,
            requires_manual_review=requires_manual_review,
            priority=priority,
            nfc_params=dict(nfc_params) if isinstance(nfc_params, dict) else None,
            order_requirement=dict(order_requirement) if isinstance(order_requirement, dict) else None,
        )

    def _normalize_order_requirement(self, order_params: Optional[Dict]) -> Optional[Dict]:
        if not isinstance(order_params, dict):
            return None

        if "enabled" in order_params or "spec" in order_params or "raw_text" in order_params:
            normalized_spec = order_params.get("spec")
            return {
                "enabled": bool(order_params.get("enabled", False)),
                "raw_text": order_params.get("raw_text") or "",
                "spec": dict(normalized_spec) if isinstance(normalized_spec, dict) else None,
                "updated_at": order_params.get("updated_at"),
            }

        return {
            "enabled": True,
            "raw_text": "",
            "spec": dict(order_params),
            "updated_at": None,
        }

    def _compare_with_order_requirement(
        self,
        *,
        material_id: Optional[str],
        nfc_result: Optional[Dict],
        nfc_params: Optional[Dict],
        vision_result: Optional[Dict],
        order_requirement: Dict,
    ) -> ComparisonResult:
        order_spec = order_requirement.get("spec")
        order_text = order_requirement.get("raw_text") or ""
        normalized_order_text = self.normalize_compare_text(order_text)
        nfc_text = nfc_result.get("text") if isinstance(nfc_result, dict) else ""
        normalized_nfc_text = self.normalize_compare_text(nfc_text)

        if not normalized_order_text:
            return self._result(
                status=ComparisonStatus.NO_REFERENCE,
                material_id=material_id,
                details="订单输入为空，无法执行订单校验",
                sortable=True,
                requires_manual_review=True,
                reasons=["缺少比对目标"],
                reference_source="order",
                nfc_params=nfc_params,
                order_requirement=order_requirement,
            )

        if not normalized_nfc_text:
            return self._result(
                status=ComparisonStatus.NO_REFERENCE,
                material_id=material_id,
                order_params=order_spec,
                details="NFC 文本为空，无法执行订单文本校验",
                sortable=True,
                requires_manual_review=True,
                reasons=["缺少比对目标"],
                reference_source="order",
                nfc_params=nfc_params,
                order_requirement=order_requirement,
            )

        if not isinstance(order_spec, dict) or not any(order_spec.values()):
            return self._result(
                status=ComparisonStatus.NO_REFERENCE,
                material_id=material_id,
                details="订单文本里没有可用于视觉校验的颜色/形状/类型信息",
                sortable=True,
                requires_manual_review=True,
                reasons=["缺少比对目标"],
                reference_source="order",
                nfc_params=nfc_params,
                order_requirement=order_requirement,
            )

        if vision_result is None or not vision_result.get("success", False):
            return self._result(
                status=ComparisonStatus.NO_VISION_RESULT,
                material_id=material_id,
                order_params=order_spec,
                details="视觉识别失败",
                sortable=True,
                requires_manual_review=True,
                reasons=["视觉识别失败"],
                reference_source="order",
                nfc_params=nfc_params,
                order_requirement=order_requirement,
            )

        confidence = float(vision_result.get("confidence", 0.0))
        if confidence < self.confidence_threshold:
            return self._result(
                status=ComparisonStatus.LOW_CONFIDENCE,
                material_id=material_id,
                vision_result=vision_result,
                order_params=order_spec,
                details=f"置信度不足：{confidence:.2%} < {self.confidence_threshold:.2%}",
                sortable=True,
                requires_manual_review=True,
                reasons=["低置信度"],
                reference_source="order",
                nfc_params=nfc_params,
                order_requirement=order_requirement,
            )

        mismatch_fields: List[str] = []
        reasons: List[str] = []

        if normalized_order_text != normalized_nfc_text:
            reasons.append("订单与NFC文本不一致")

        order_vision_mismatch, order_vision_reasons = self._compare_reference_to_observed(
            observed_spec=vision_result,
            reference_spec=order_spec,
            reason_prefix="订单与视觉",
        )
        mismatch_fields.extend(order_vision_mismatch)
        reasons.extend(order_vision_reasons)

        if isinstance(nfc_params, dict) and any(nfc_params.values()):
            nfc_vision_mismatch, nfc_vision_reasons = self._compare_reference_to_observed(
                observed_spec=vision_result,
                reference_spec=nfc_params,
                reason_prefix="NFC与视觉",
            )
            mismatch_fields.extend(nfc_vision_mismatch)
            reasons.extend(nfc_vision_reasons)

        if reasons:
            return self._result(
                status=ComparisonStatus.ANOMALY,
                material_id=material_id,
                vision_result=vision_result,
                order_params=order_spec,
                details="订单、NFC 文本与视觉识别不一致",
                sortable=True,
                mismatch_fields=sorted(set(mismatch_fields)),
                reasons=list(dict.fromkeys(reasons)),
                reference_source="order",
                nfc_params=nfc_params,
                order_requirement=order_requirement,
            )

        return self._result(
            status=ComparisonStatus.PASS,
            material_id=material_id,
            vision_result=vision_result,
            order_params=order_spec,
            details="订单、NFC 文本与视觉识别一致，允许放行",
            reference_source="order",
            nfc_params=nfc_params,
            order_requirement=order_requirement,
        )

    def _compare_reference_to_observed(
        self,
        *,
        observed_spec: Dict,
        reference_spec: Dict,
        reason_prefix: str,
    ) -> tuple[List[str], List[str]]:
        mismatch_fields: List[str] = []
        reasons: List[str] = []

        observed_type = normalize_material_type(observed_spec.get("material_type"))
        observed_color = normalize_color(observed_spec.get("color"))
        observed_shape = normalize_shape(observed_spec.get("shape"))
        reference_type = normalize_material_type(reference_spec.get("material_type"))
        reference_color = normalize_color(reference_spec.get("color"))
        reference_shape = normalize_shape(reference_spec.get("shape"))

        if reference_type is not None and observed_type != reference_type:
            mismatch_fields.append("material_type")
            reasons.append(f"{reason_prefix}类型不一致")
        if reference_color is not None and observed_color != reference_color:
            mismatch_fields.append("color")
            reasons.append(f"{reason_prefix}颜色不一致")
        if reference_shape is not None and observed_shape != reference_shape:
            mismatch_fields.append("shape")
            reasons.append(f"{reason_prefix}形状不一致")

        return mismatch_fields, reasons

    def _resolve_priority(self, reasons: List[str]) -> tuple[Optional[str], int]:
        if not reasons:
            return None, 99
        ranked = sorted(
            ((REASON_PRIORITIES.get(reason, 99), reason) for reason in reasons),
            key=lambda item: item[0],
        )
        return ranked[0][1], ranked[0][0]

    def reset_processed(self, material_id: str) -> bool:
        del material_id
        return False

    def reset_all(self):
        logger.info("Processed-material reset ignored because order dedup is disabled")

    def get_processed_count(self) -> int:
        return 0


class EnhancedSortingDecisionEngine:
    """增强的分拣决策引擎。"""

    def __init__(self, consistency_engine: ConsistencyEngine):
        self.consistency_engine = consistency_engine
        self.decision_history = []

    def make_decision(
        self,
        material_id: Optional[str],
        nfc_result: Optional[Dict],
        vision_result: Optional[Dict],
        order_params: Optional[Dict],
    ) -> Dict:
        comparison = self.consistency_engine.compare(
            material_id=material_id,
            nfc_result=nfc_result,
            vision_result=vision_result,
            order_params=order_params,
        )
        decision = self._decide_action(comparison)
        decision["comparison"] = comparison.to_dict()

        self.decision_history.append(
            {
                "material_id": material_id,
                "decision": decision,
                "comparison": comparison.to_dict(),
            }
        )
        return decision

    def _decide_action(self, comparison: ComparisonResult) -> Dict:
        if comparison.status == ComparisonStatus.PASS:
            return {
                "action": "pass",
                "route": "main_line",
                "reason": "一致性检查通过，放行",
                "reasons": comparison.reasons,
                "highest_priority_reason": comparison.highest_priority_reason,
                "order_status": "DETECTED_PASS",
                "sortable": False,
                "requires_manual_review": False,
                "priority": comparison.priority,
            }

        if comparison.status == ComparisonStatus.ANOMALY:
            return {
                "action": "sort",
                "route": "side_bin",
                "reason": "一致性检查异常，拨入异常区",
                "reasons": comparison.reasons,
                "highest_priority_reason": comparison.highest_priority_reason,
                "order_status": "DETECTION_ANOMALY",
                "sortable": True,
                "requires_manual_review": False,
                "priority": comparison.priority,
            }

        if comparison.status == ComparisonStatus.NFC_ERROR:
            return {
                "action": "sort",
                "route": "side_bin",
                "reason": "NFC异常或无标签，直接分拣",
                "reasons": comparison.reasons,
                "highest_priority_reason": comparison.highest_priority_reason,
                "order_status": "DETECTION_ANOMALY",
                "sortable": True,
                "requires_manual_review": False,
                "priority": comparison.priority,
            }

        if comparison.status in [
            ComparisonStatus.NO_REFERENCE,
            ComparisonStatus.NO_VISION_RESULT,
            ComparisonStatus.LOW_CONFIDENCE,
        ]:
            return {
                "action": "sort",
                "route": "side_bin",
                "reason": comparison.details,
                "reasons": comparison.reasons,
                "highest_priority_reason": comparison.highest_priority_reason,
                "order_status": "WAITING_MANUAL",
                "sortable": True,
                "requires_manual_review": True,
                "priority": comparison.priority,
            }

        return {
            "action": "sort",
            "route": "side_bin",
            "reason": "未知情况，拨入侧边区等待人工处理",
            "reasons": ["未知异常"],
            "highest_priority_reason": "未知异常",
            "order_status": "WAITING_MANUAL",
            "sortable": True,
            "requires_manual_review": True,
            "priority": 99,
        }

    def get_decision_stats(self) -> Dict:
        if not self.decision_history:
            return {"total": 0, "pass": 0, "sort": 0, "manual": 0}

        manual_count = sum(
            1
            for item in self.decision_history
            if item["decision"].get("requires_manual_review")
        )
        return {
            "total": len(self.decision_history),
            "pass": sum(
                1 for item in self.decision_history if item["decision"]["action"] == "pass"
            ),
            "sort": sum(
                1 for item in self.decision_history if item["decision"]["action"] == "sort"
            ),
            "manual": manual_count,
        }
