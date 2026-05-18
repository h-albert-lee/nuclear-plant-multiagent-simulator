"""6 Critical Safety Functions (CSFs) status assessment.

Status mapping:
  reactivity_control       — RPS, CRDM, reactor_thermal_power 거동
  core_heat_removal        — RCP, AFWS, SG narrow level
  rcs_heat_removal         — SG pressure, hot/cold leg ΔT
  rcs_integrity            — pressurizer pressure/level, RCS-Pipe status
  containment_integrity    — Containment 압력/온도/격리
  radioactivity_control    — 격납 방사선, ESFAS isolation
"""

from __future__ import annotations

from src.plant_state import PlantState, SafetyFunctions


def assess_safety_functions(state: PlantState) -> tuple[SafetyFunctions, list[tuple[str, str, str]]]:
    """Compute new SafetyFunctions; return new state + transitions list.

    Each transition is (csf_name, from_state, to_state).
    """
    prev = state.safety_functions
    cur = SafetyFunctions(
        reactivity_control=_reactivity_control(state),
        core_heat_removal=_core_heat_removal(state),
        rcs_heat_removal=_rcs_heat_removal(state),
        rcs_integrity=_rcs_integrity(state),
        containment_integrity=_containment_integrity(state),
        radioactivity_control=_radioactivity_control(state),
    )
    transitions: list[tuple[str, str, str]] = []
    for f in type(prev).model_fields:
        a = getattr(prev, f)
        b = getattr(cur, f)
        if a != b:
            transitions.append((f, a, b))
    return cur, transitions


def _reactivity_control(s: PlantState) -> str:
    pwr = s.vars.get("reactor_thermal_power", 100.0)
    rps = s.systems.get("RPS")
    crdm = s.systems.get("CRDM")
    if rps and not rps.safety_logic_active:
        return "lost"
    if pwr > 109.0:
        return "lost"
    if pwr > 107.0:
        return "degraded"
    if crdm and crdm.status == "tripped":
        return "degraded"
    return "intact"


def _core_heat_removal(s: PlantState) -> str:
    rcp = s.systems.get("RCP")
    afws = s.systems.get("AFWS")
    sg_level = s.vars.get("sg_narrow_level", 55.0)
    if rcp and rcp.status == "tripped" and (not afws or afws.status not in ("running", "standby")):
        return "lost"
    if sg_level < 25.0:
        return "degraded"
    return "intact"


def _rcs_heat_removal(s: PlantState) -> str:
    sg_pressure = s.vars.get("sg_pressure", 6.9)
    if sg_pressure > 7.6:
        return "lost"
    if sg_pressure < 4.8 or sg_pressure > 7.1:
        return "degraded"
    return "intact"


def _rcs_integrity(s: PlantState) -> str:
    p = s.vars.get("pressurizer_pressure", 15.5)
    lvl = s.vars.get("pressurizer_level", 55.0)
    pipe = s.systems.get("RCS-Pipe")
    if pipe and pipe.status == "tripped":
        return "lost"
    if p < 12.8 or p > 16.4 or lvl < 10.0:
        return "lost"
    if p < 15.1 or p > 15.9 or lvl < 20.0 or lvl > 75.0:
        return "degraded"
    return "intact"


def _containment_integrity(s: PlantState) -> str:
    p = s.vars.get("containment_pressure", 98.0)
    t = s.vars.get("containment_temp", 30.0)
    cont = s.systems.get("Containment")
    if cont and cont.status == "tripped":
        return "lost"
    if p > 400.0:
        return "lost"
    if p > 150.0 or t > 55.0:
        return "degraded"
    return "intact"


def _radioactivity_control(s: PlantState) -> str:
    r = s.vars.get("containment_radiation", 0.1)
    if r > 100.0:
        return "lost"
    if r > 1.0:
        return "degraded"
    return "intact"


def derive_op_state(s: PlantState) -> str:
    """Plant op_state derivation:
    emergency = EOP active OR any safety_function lost/degraded
    abnormal  = AOP active OR any critical alarm currently active
    normal    = NOP active, no active critical alarms
    """
    active_proc = s.procedures.active or ""
    if active_proc.startswith("EOP") or s.safety_functions.compromised():
        return "emergency"
    if active_proc.startswith("AOP"):
        return "abnormal"
    for a in s.alarms.values():
        if a.severity == "critical" and a.state == "active":
            return "abnormal"
    return "normal"
