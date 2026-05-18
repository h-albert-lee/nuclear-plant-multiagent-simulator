"""Action-class derivation matrix.

Deterministic lookup: given (action_type, target_system, target_alarm,
target_document, plant_op_state) → ActionClass.
"""

from __future__ import annotations

from typing import Optional

from src.enums import ActionClass, ActionType, PlantOpState
from src.plant_state import AlarmState, DocumentMeta, SystemState

CONTROL_LEVEL_MATRIX: dict[str, dict[PlantOpState, ActionClass]] = {
    "non_safety_A": {"normal": "L2",   "abnormal": "L3", "emergency": "L3"},
    "non_safety_B": {"normal": "L2.5", "abnormal": "L3", "emergency": "L4"},
    "safety":       {"normal": "L3",   "abnormal": "L3", "emergency": "L4"},
}


def derive_action_class(
    action_type: Optional[ActionType],
    *,
    target_system: Optional[SystemState],
    target_alarm: Optional[AlarmState],
    target_document: Optional[DocumentMeta],
    plant_op_state: PlantOpState,
) -> ActionClass:
    if action_type is None:
        return "N/A"

    # ── documents ─────────────────────────────────────────────────────────
    if action_type in ("doc_read", "doc_summary"):
        return "L1"
    if action_type == "doc_write":
        if target_document is None:
            return "DENY"
        return "L1" if target_document.modifiable else "DENY"

    # ── monitoring ────────────────────────────────────────────────────────
    if action_type == "monitor":
        return "L1"

    # ── alarms ────────────────────────────────────────────────────────────
    if action_type == "alarm_acknowledge":
        return "L1"
    if action_type == "alarm_suppress":
        if target_alarm is None:
            return "DENY"
        if target_alarm.suppress_policy == "forbidden":
            return "DENY"
        return "L4"
    if action_type == "alarm_bypass":
        if target_alarm is None:
            return "DENY"
        if target_alarm.suppress_policy == "forbidden":
            return "DENY"
        return "L5"

    # ── systems ───────────────────────────────────────────────────────────
    if action_type == "scram":
        return "L4"
    if action_type == "system_isolation":
        return "L4"
    if action_type == "system_bypass":
        if target_system is None:
            return "DENY"
        if target_system.classification == "safety":
            return "DENY"  # G8 코드 차단 동작 의도 명시
        return "L5"
    if action_type == "reactor_power_control":
        return "L3"
    if action_type == "emergency_declaration":
        return "L5"

    # ── general control matrix ────────────────────────────────────────────
    if action_type == "control":
        if target_system is None:
            return "DENY"
        return CONTROL_LEVEL_MATRIX[target_system.classification][plant_op_state]

    return "N/A"
