"""Deterministic action-class derivation."""

from __future__ import annotations

import pytest

from src.guardrails.derivation import derive_action_class
from src.plant_state import AlarmState, DocumentMeta, SystemState


# ── documents ────────────────────────────────────────────────────────────────
def test_doc_read_is_l1():
    assert derive_action_class("doc_read",
                               target_system=None, target_alarm=None,
                               target_document=DocumentMeta(document_id="LOG-shift", category="log", modifiable=True),
                               plant_op_state="normal") == "L1"


def test_doc_write_on_procedure_is_deny():
    eop = DocumentMeta(document_id="EOP-1", category="EOP", modifiable=False)
    assert derive_action_class("doc_write",
                               target_system=None, target_alarm=None,
                               target_document=eop, plant_op_state="normal") == "DENY"


def test_doc_write_on_modifiable_doc_is_l1():
    log = DocumentMeta(document_id="LOG-shift", category="log", modifiable=True)
    assert derive_action_class("doc_write",
                               target_system=None, target_alarm=None,
                               target_document=log, plant_op_state="normal") == "L1"


# ── alarms ───────────────────────────────────────────────────────────────────
def test_alarm_acknowledge_is_l1():
    a = AlarmState(alarm_id="ALM-X", suppress_policy="forbidden", setpoint_tier="trip")
    assert derive_action_class("alarm_acknowledge",
                               target_system=None, target_alarm=a,
                               target_document=None, plant_op_state="normal") == "L1"


def test_alarm_suppress_forbidden_is_deny():
    a = AlarmState(alarm_id="ALM-SCRAM", suppress_policy="forbidden", setpoint_tier="trip")
    assert derive_action_class("alarm_suppress",
                               target_system=None, target_alarm=a,
                               target_document=None, plant_op_state="normal") == "DENY"


def test_alarm_suppress_conditional_is_l4():
    a = AlarmState(alarm_id="ALM-PRZ-LVL-LOW", suppress_policy="conditional", setpoint_tier="low")
    assert derive_action_class("alarm_suppress",
                               target_system=None, target_alarm=a,
                               target_document=None, plant_op_state="normal") == "L4"


def test_alarm_bypass_allowed_is_l5():
    a = AlarmState(alarm_id="ALM-COND-VACUUM-LOW", suppress_policy="allowed", setpoint_tier="low")
    assert derive_action_class("alarm_bypass",
                               target_system=None, target_alarm=a,
                               target_document=None, plant_op_state="normal") == "L5"


# ── systems ──────────────────────────────────────────────────────────────────
def test_system_bypass_on_safety_is_deny():
    s = SystemState(sys_id="RPS", classification="safety")
    assert derive_action_class("system_bypass",
                               target_system=s, target_alarm=None,
                               target_document=None, plant_op_state="normal") == "DENY"


def test_system_isolation_is_l4():
    s = SystemState(sys_id="SIS", classification="safety")
    assert derive_action_class("system_isolation",
                               target_system=s, target_alarm=None,
                               target_document=None, plant_op_state="normal") == "L4"


def test_scram_is_l4():
    assert derive_action_class("scram", target_system=None, target_alarm=None,
                               target_document=None, plant_op_state="abnormal") == "L4"


def test_reactor_power_control_is_l3():
    assert derive_action_class("reactor_power_control", target_system=None,
                               target_alarm=None, target_document=None,
                               plant_op_state="normal") == "L3"


def test_emergency_declaration_is_l5():
    assert derive_action_class("emergency_declaration", target_system=None,
                               target_alarm=None, target_document=None,
                               plant_op_state="abnormal") == "L5"


# ── control matrix ───────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "classification,op_state,expected",
    [
        ("non_safety_A", "normal",    "L2"),
        ("non_safety_A", "abnormal",  "L3"),
        ("non_safety_A", "emergency", "L3"),
        ("non_safety_B", "normal",    "L2.5"),
        ("non_safety_B", "abnormal",  "L3"),
        ("non_safety_B", "emergency", "L4"),
        ("safety",       "normal",    "L3"),
        ("safety",       "abnormal",  "L3"),
        ("safety",       "emergency", "L4"),
    ],
)
def test_control_matrix(classification, op_state, expected):
    s = SystemState(sys_id="X", classification=classification)
    assert derive_action_class("control", target_system=s, target_alarm=None,
                               target_document=None, plant_op_state=op_state) == expected
