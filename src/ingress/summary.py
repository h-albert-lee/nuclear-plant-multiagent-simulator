"""SituationSummary builder.

Black-box vs white-box redaction is centralized here so ingress/api.py and
ingress/sse.py both reuse the same logic.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional
from uuid import UUID

from src.config_models import AttackInterfaceConfig
from src.enums import OPERATOR_ROLES, AttackVisibility
from src.message_models import GuardrailVerdict, Message
from src.plant_state import PlantState


def build_situation_summary(
    *,
    at_tick: int,
    turns_since_last_summary: int,
    visibility: AttackVisibility,
    plant: PlantState,
    plant_state_delta: Optional[dict[str, Any]],
    last_message_delivered: Optional[bool],
    last_message_blocked_by_verdict: Optional[GuardrailVerdict],
    triggered_messages: list[Message],
    bus_messages_since: list[Message],
    guardrail_verdicts_since: list[dict[str, Any]],
    mock_human_responses_since: list[dict[str, Any]],
    blackbox_payload_excerpt_chars: int,
) -> dict[str, Any]:
    triggered_summary = [
        _format_triggered_msg(m, visibility, blackbox_payload_excerpt_chars)
        for m in triggered_messages
    ]

    summary: dict[str, Any] = {
        "at_tick": at_tick,
        "turns_since_last_summary": turns_since_last_summary,
        "last_message_delivered": last_message_delivered,
        "last_message_blocked_by": (
            last_message_blocked_by_verdict.guardrail_id if last_message_blocked_by_verdict else None
        ),
        "triggered_agent_messages": triggered_summary,
        "plant_op_state": plant.op_state,
        "active_alarm_count": sum(1 for a in plant.alarms.values() if a.state == "active"),
        "safety_function_compromised": plant.safety_functions.compromised(),
        "procedure_in_progress": _procedure_category(plant.procedures.active),
        # white-box only
        "plant_state_delta": None,
        "full_message_trace": [],
        "guardrail_decisions": [],
        "mock_human_responses": [],
    }
    if visibility == "white":
        summary["plant_state_delta"] = plant_state_delta
        summary["full_message_trace"] = [m.model_dump(mode="json") for m in bus_messages_since]
        summary["guardrail_decisions"] = guardrail_verdicts_since
        summary["mock_human_responses"] = mock_human_responses_since
        summary["procedure_in_progress"] = plant.procedures.active
        if last_message_blocked_by_verdict is not None:
            summary["last_message_blocked_by"] = {
                "guardrail_id": last_message_blocked_by_verdict.guardrail_id,
                "reason": last_message_blocked_by_verdict.reason,
                "block_category": last_message_blocked_by_verdict.block_category,
            }
    return summary


def _format_triggered_msg(m: Message, visibility: AttackVisibility, excerpt_chars: int) -> dict[str, Any]:
    base: dict[str, Any] = {
        "sender": m.sender,
        "type": m.type,
        "action_type": m.action_type,
        "procedure_ref": m.procedure_ref,
        "target_system": m.target_system,
    }
    if visibility == "white":
        base["payload_excerpt"] = m.payload
    else:
        base["payload_excerpt"] = m.payload[:excerpt_chars]
    return base


def _procedure_category(active: Optional[str]) -> Optional[str]:
    if not active:
        return None
    for prefix in ("EOP", "AOP", "NOP", "STP", "MMP-SAP"):
        if active.startswith(prefix):
            return prefix
    return None


def diff_plant_state(prev: PlantState, cur: PlantState) -> dict[str, Any]:
    """Compute a small delta dict for white-box summaries."""
    var_delta = {
        k: cur.vars[k] for k in cur.vars
        if k not in prev.vars or abs(cur.vars[k] - prev.vars.get(k, 0.0)) > 1e-6
    }
    alarm_delta = {
        aid: cur.alarms[aid].model_dump(mode="json")
        for aid in cur.alarms
        if aid not in prev.alarms or prev.alarms[aid].state != cur.alarms[aid].state
    }
    sys_delta = {
        sid: cur.systems[sid].model_dump(mode="json")
        for sid in cur.systems
        if sid not in prev.systems
        or prev.systems[sid].status != cur.systems[sid].status
        or prev.systems[sid].safety_logic_active != cur.systems[sid].safety_logic_active
    }
    csf_delta = {
        f: getattr(cur.safety_functions, f)
        for f in type(cur.safety_functions).model_fields
        if getattr(prev.safety_functions, f) != getattr(cur.safety_functions, f)
    }
    proc_delta = None
    if prev.procedures != cur.procedures:
        proc_delta = cur.procedures.model_dump(mode="json")
    return {
        "vars": var_delta,
        "alarms": alarm_delta,
        "systems": sys_delta,
        "safety_functions": csf_delta,
        "procedures": proc_delta,
    }
