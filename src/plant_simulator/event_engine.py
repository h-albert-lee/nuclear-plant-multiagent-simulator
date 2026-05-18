"""Scenario event engine.

Reads a YAML scenario file and applies scheduled events (disturbances)
to the plant state at the configured tick.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import structlog

from src.config_models import load_yaml
from src.plant_state import AlarmState, PlantState, SystemState

log = structlog.get_logger(__name__)


class EventEngine:
    """Applies scenario-driven disturbances at specific ticks."""

    def __init__(self, scenario_path: str | Path) -> None:
        data = load_yaml(scenario_path)
        self.scenario_id: str = data.get("scenario_id", "unknown")
        self.duration_ticks: int = int(data.get("duration_ticks", 2000))
        self.initial_state: dict[str, Any] = data.get("initial_state", {})
        self.events: list[dict[str, Any]] = data.get("events", [])
        self.action_effects: list[dict[str, Any]] = data.get("action_effects", [])

    # ── initial state ────────────────────────────────────────────────────
    def apply_initial_state(self, state: PlantState) -> None:
        vars_init = self.initial_state.get("vars", {})
        for k, v in vars_init.items():
            state.vars[k] = float(v)
        systems_init = self.initial_state.get("systems", {})
        for sys_id, fields in systems_init.items():
            if sys_id in state.systems:
                for k, v in fields.items():
                    setattr(state.systems[sys_id], k, v)
        procs = self.initial_state.get("procedures", {})
        if "active" in procs:
            state.procedures.active = procs["active"]
        if "step" in procs:
            state.procedures.step = int(procs["step"])

    # ── tick events ──────────────────────────────────────────────────────
    def apply_tick_events(self, state: PlantState) -> list[dict[str, Any]]:
        """Apply any events scheduled for `state.tick`. Returns applied events for logging."""
        applied: list[dict[str, Any]] = []
        for ev in self.events:
            if int(ev.get("tick", -1)) != state.tick:
                continue
            applied.append(ev)
            self._apply_event_effect(state, ev.get("effect", {}))
            log.info("scenario_event_applied", scenario=self.scenario_id,
                     event_type=ev.get("type"), at_tick=ev.get("tick"))
        return applied

    def _apply_event_effect(self, state: PlantState, effect: dict[str, Any]) -> None:
        # vars
        for var_id, value in effect.get("vars", {}).items():
            if isinstance(value, (int, float)):
                state.vars[var_id] = float(value)
        # systems
        for sys_id, fields in effect.get("systems", {}).items():
            if sys_id not in state.systems:
                state.systems[sys_id] = SystemState(
                    sys_id=sys_id, classification="non_safety_A"
                )
            for k, v in fields.items():
                setattr(state.systems[sys_id], k, v)
        # alarms
        for alarm_id, fields in effect.get("alarms", {}).items():
            if alarm_id in state.alarms:
                a = state.alarms[alarm_id]
                for k, v in fields.items():
                    setattr(a, k, v)
                if "state" in fields and fields["state"] == "active":
                    a.since_tick = state.tick
            else:
                state.alarms[alarm_id] = AlarmState(
                    alarm_id=alarm_id,
                    state=fields.get("state", "active"),
                    since_tick=state.tick,
                    severity=fields.get("severity", "warning"),
                    was_critical=fields.get("was_critical", False),
                    suppress_policy=fields.get("suppress_policy", "allowed"),
                    setpoint_tier=fields.get("setpoint_tier", "n/a"),
                    description=fields.get("description", ""),
                )
        # procedures
        procs = effect.get("procedures")
        if procs:
            if "active" in procs:
                state.procedures.active = procs["active"]
            if "step" in procs:
                state.procedures.step = int(procs["step"])
