"""Plant simulator package.

Public surface: PlantSimulator class — tick step, action application, state snapshot.
"""

from __future__ import annotations

import random
from typing import Any

import structlog

from src.message_models import Message
from src.plant_simulator.alarms import alarm_step
from src.plant_simulator.catalogs import (
    VARIABLE_INITIAL,
    build_alarm_catalog,
    build_document_catalog,
    build_system_catalog,
)
from src.plant_simulator.event_engine import EventEngine
from src.plant_simulator.physics import physics_step
from src.plant_simulator.safety_functions import (
    assess_safety_functions,
    derive_op_state,
)
from src.plant_state import (
    AlarmState,  # noqa: F401  (re-exported for callers)
    PlantState,
    ProcedureState,
)

log = structlog.get_logger(__name__)


class PlantSimulator:
    """Owns the canonical PlantState. Steps physics / alarms / safety functions per tick.

    Applies ACTION messages from operator agents through a dispatch table.
    """

    def __init__(self, scenario_path: str, *, seed: int = 42) -> None:
        self.event_engine = EventEngine(scenario_path)
        self.rng = random.Random(seed)
        self.state = self._init_state()
        self.event_engine.apply_initial_state(self.state)

    # ── init ─────────────────────────────────────────────────────────────
    def _init_state(self) -> PlantState:
        state = PlantState(
            tick=0,
            op_state="normal",
            vars={k: v[0] for k, v in VARIABLE_INITIAL.items()},
            alarms=build_alarm_catalog(),
            systems=build_system_catalog(),
            procedures=ProcedureState(active="NOP-12", step=0),
            documents=build_document_catalog(),
        )
        for a in state.alarms.values():
            a.state = "cleared"
        return state

    # ── tick step ────────────────────────────────────────────────────────
    def tick(self) -> tuple[list[str], list[tuple[str, str, str]], list[dict[str, Any]]]:
        """Advance one tick. Returns (alarm_transitions, csf_transitions, scenario_events)."""
        self.state.tick += 1
        scenario_events = self.event_engine.apply_tick_events(self.state)
        physics_step(self.state, self.rng)
        alarm_transitions = alarm_step(self.state)
        new_csfs, csf_transitions = assess_safety_functions(self.state)
        self.state.safety_functions = new_csfs
        self.state.op_state = derive_op_state(self.state)  # type: ignore[assignment]
        return alarm_transitions, csf_transitions, scenario_events

    def snapshot(self) -> PlantState:
        return self.state.snapshot()

    # ── apply ACTION → state ─────────────────────────────────────────────
    def apply_action(self, msg: Message) -> None:
        """Apply an authorized ACTION message's effect to plant state.

        Minimal effects — purpose is observable state changes, not thermohydraulics.
        """
        if msg.type != "ACTION":
            return
        at = msg.action_type
        if at == "scram":
            rps = self.state.systems.get("RPS")
            if rps:
                rps.status = "tripped"
            scram = self.state.alarms.get("ALM-SCRAM")
            if scram:
                scram.state = "active"
                scram.since_tick = self.state.tick
            self.state.procedures.active = "AOP-3"
            self.state.procedures.step = 0
            log.info("action_scram", msg_id=str(msg.msg_id))

        elif at == "system_isolation":
            sys_id = msg.target_system
            if sys_id and sys_id in self.state.systems:
                self.state.systems[sys_id].status = "isolated"
                log.info("action_isolation", sys_id=sys_id, msg_id=str(msg.msg_id))

        elif at == "system_bypass":
            sys_id = msg.target_system
            if sys_id and sys_id in self.state.systems:
                self.state.systems[sys_id].safety_logic_active = False
                log.warning("action_system_bypass", sys_id=sys_id, msg_id=str(msg.msg_id))

        elif at == "alarm_acknowledge":
            aid = msg.target_alarm
            if aid and aid in self.state.alarms:
                if self.state.alarms[aid].state == "active":
                    self.state.alarms[aid].state = "ack"

        elif at == "alarm_suppress":
            aid = msg.target_alarm
            if aid and aid in self.state.alarms:
                self.state.alarms[aid].state = "suppressed"

        elif at == "alarm_bypass":
            aid = msg.target_alarm
            if aid and aid in self.state.alarms:
                self.state.alarms[aid].state = "bypassed"

        elif at == "reactor_power_control":
            try:
                if msg.payload.startswith("set_power:"):
                    target = float(msg.payload.split(":", 1)[1])
                    cur = self.state.vars.get("reactor_thermal_power", 100.0)
                    self.state.vars["reactor_thermal_power"] = cur + 0.4 * (target - cur)
            except Exception:  # noqa: BLE001
                pass

        elif at == "control":
            sys_id = msg.target_system
            if sys_id and sys_id in self.state.systems:
                if msg.payload == "stop":
                    self.state.systems[sys_id].status = "standby"
                elif msg.payload == "start":
                    self.state.systems[sys_id].status = "running"

        elif at == "doc_write":
            # modifiable docs aren't persisted in state at Stage 0; trace captures intent.
            pass

        elif at == "emergency_declaration":
            self.state.procedures.active = "EOP-1"
            self.state.procedures.step = 0
            log.warning("action_emergency_declaration", msg_id=str(msg.msg_id))
