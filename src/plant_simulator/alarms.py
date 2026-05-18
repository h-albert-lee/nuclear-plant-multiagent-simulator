"""Alarm step: variable threshold check → alarm activation/clear."""

from __future__ import annotations

from typing import Callable

from src.plant_simulator.catalogs import ALARM_TRIGGER_RULES
from src.plant_state import PlantState


def _comparator(op: str) -> Callable[[float, float], bool]:
    if op == "<":
        return lambda a, b: a < b
    if op == ">":
        return lambda a, b: a > b
    if op == "<=":
        return lambda a, b: a <= b
    if op == ">=":
        return lambda a, b: a >= b
    raise ValueError(f"unknown comparator {op}")


def alarm_step(state: PlantState) -> list[str]:
    """Check threshold rules. Returns list of alarm_ids that just transitioned active."""
    transitioned: list[str] = []
    for alarm_id, var_id, op, thr_str in ALARM_TRIGGER_RULES:
        if alarm_id not in state.alarms:
            continue
        thr = float(thr_str)
        val = state.vars.get(var_id)
        if val is None:
            continue
        condition_met = _comparator(op)(val, thr)
        cur = state.alarms[alarm_id]
        # bypassed = logic disabled, don't reactivate. suppressed = logic alive but display off.
        if condition_met:
            if cur.state in ("cleared", "ack"):
                cur.state = "active"
                cur.since_tick = state.tick
                transitioned.append(alarm_id)
            # if suppressed: keep silent but track 'active' under the hood
            elif cur.state == "suppressed":
                # Suppress hides display, logic stays alive; leave state="suppressed"
                # but record the violation timestamp.
                cur.since_tick = state.tick if cur.since_tick == 0 else cur.since_tick
        else:
            if cur.state in ("active", "ack"):
                cur.state = "cleared"
                cur.since_tick = state.tick
    return transitioned
