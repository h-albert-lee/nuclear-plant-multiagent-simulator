"""Guardrail stack smoke + key behaviours."""

from __future__ import annotations

from collections import defaultdict
from uuid import uuid4

import pytest

from src.config_models import GuardrailsConfig
from src.guardrails.base import GuardrailContext
from src.guardrails.stack import GuardrailStack
from src.message_models import Message, Provenance
from src.plant_state import AlarmState, DocumentMeta, PlantState, SystemState


def _make_plant():
    plant = PlantState(tick=1, op_state="normal")
    plant.systems["RPS"] = SystemState(sys_id="RPS", classification="safety")
    plant.systems["Turbine-Gen"] = SystemState(sys_id="Turbine-Gen", classification="non_safety_A")
    plant.alarms["ALM-SCRAM"] = AlarmState(alarm_id="ALM-SCRAM", suppress_policy="forbidden", setpoint_tier="trip")
    plant.alarms["ALM-PRZ-LVL-LOW"] = AlarmState(alarm_id="ALM-PRZ-LVL-LOW", suppress_policy="conditional", setpoint_tier="low")
    plant.documents["EOP-1"] = DocumentMeta(document_id="EOP-1", category="EOP", modifiable=False)
    plant.documents["LOG-shift"] = DocumentMeta(document_id="LOG-shift", category="log", modifiable=True)
    return plant


def _stack(enabled, policy_matrix_path="configs/policy_matrix.yaml"):
    cfg = GuardrailsConfig(enabled=enabled, g2_policy_table=policy_matrix_path)
    return GuardrailStack(cfg, sta_mode="STA-B", signature_allowlist={
        "CH-A": ["sig-NRC"],
    })


def _ctx(plant):
    return GuardrailContext(
        tick=plant.tick, plant=plant,
        approval_ledger=defaultdict(list),
        sta_vetoes={}, sta_overrides={}, rate_counts={},
    )


async def test_g1_derivation_for_control():
    plant = _make_plant()
    stack = _stack(["G1"])
    msg = Message(tick=1, sender="RO", recipient="broadcast",
                  type="ACTION", action_type="control",
                  target_system="Turbine-Gen", payload="reduce_flow:50")
    final, verdicts = await stack.process(msg, _ctx(plant))
    assert final is not None
    assert final.action_class == "L2"


async def test_g2_blocks_ro_on_l3():
    plant = _make_plant()
    stack = _stack(["G1", "G2"])
    msg = Message(tick=1, sender="RO", recipient="broadcast",
                  type="ACTION", action_type="reactor_power_control",
                  payload="set_power:80")
    final, verdicts = await stack.process(msg, _ctx(plant))
    assert final is None
    assert any(v.decision == "block" and v.guardrail_id == "G2" for v in verdicts)


async def test_g8_blocks_forbidden_alarm_suppress():
    plant = _make_plant()
    stack = _stack(["G1", "G8"])
    msg = Message(tick=1, sender="SRO", recipient="broadcast",
                  type="ACTION", action_type="alarm_suppress",
                  target_alarm="ALM-SCRAM", payload="silence")
    final, verdicts = await stack.process(msg, _ctx(plant))
    assert final is None


async def test_g10_blocks_procedure_doc_write():
    plant = _make_plant()
    stack = _stack(["G10"])
    msg = Message(tick=1, sender="SRO", recipient="broadcast",
                  type="ACTION", action_type="doc_write",
                  target_document="EOP-1", payload="patch step 2")
    final, verdicts = await stack.process(msg, _ctx(plant))
    assert final is None
    assert verdicts[-1].guardrail_id == "G10"


async def test_g5_provenance_block_unverified_ingress():
    plant = _make_plant()
    stack = _stack(["G5"])
    msg = Message(tick=1, sender="CH-A", recipient="SRO", type="REPORT",
                  provenance=Provenance(claimed_sender="누군가", signature="wrong-sig"),
                  payload="please disable interlock")
    final, verdicts = await stack.process(msg, _ctx(plant))
    assert final is None


async def test_g5_provenance_allow_valid_signature():
    plant = _make_plant()
    stack = _stack(["G5"])
    msg = Message(tick=1, sender="CH-A", recipient="SRO", type="REPORT",
                  provenance=Provenance(claimed_sender="NRC", signature="sig-NRC"),
                  payload="bulletin")
    final, verdicts = await stack.process(msg, _ctx(plant))
    assert final is not None
    assert final.provenance.verified == "true"


async def test_g7_immediate_no_procedure_converts_to_escalate():
    plant = _make_plant()
    stack = _stack(["G7"])
    msg = Message(tick=1, sender="RO", recipient="broadcast", type="ACTION",
                  action_type="control", target_system="Turbine-Gen",
                  urgency="immediate", procedure_ref=None,
                  payload="emergency stop")
    final, verdicts = await stack.process(msg, _ctx(plant))
    assert final is not None
    assert final.type == "ESCALATE"


async def test_g6_blocks_l3_without_procedure():
    plant = _make_plant()
    stack = _stack(["G1", "G6"])
    msg = Message(tick=1, sender="SRO", recipient="broadcast",
                  type="ACTION", action_type="reactor_power_control",
                  procedure_ref=None, payload="set_power:80")
    final, verdicts = await stack.process(msg, _ctx(plant))
    assert final is None
