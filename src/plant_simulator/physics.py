"""Rule-based plant dynamics — Stage 0 simplification.

We do NOT model thermohydraulics. Instead:
- Variables drift toward *mode-dependent* setpoints. The mode is derived from
  plant state: normal / SBO / LOCA / SGTR. A scenario event drives state into
  the new mode (e.g., trips RCS-Pipe, activates ALM-ESFAS-SIAS), and physics
  thereafter moves variables toward the mode-appropriate equilibrium.
- A small set of cross-coupling rules captures qualitative behaviour:
  * decay heat continues after SCRAM (Way-Wigner approximation)
  * hot leg / core exit temp follow reactor thermal power
  * subcooling margin follows saturation Tsat(p) − Thot
  * DNBR drops with power excursion
- All rates are tuned so a 30s tick produces visible-but-not-explosive change.
"""

from __future__ import annotations

import math
import random
from typing import Literal

from src.plant_state import PlantState

OperatingMode = Literal["normal", "sbo", "loca", "sgtr"]

# Per-mode drift targets. Variables not listed retain their normal target.
_MODE_TARGETS: dict[OperatingMode, dict[str, float]] = {
    "normal": {
        "pressurizer_pressure":   15.5,
        "pressurizer_level":      55.0,
        "hot_leg_temp":           324.0,
        "cold_leg_temp":          290.0,
        "subcooling_margin":      35.0,
        "reactor_coolant_flow":   100.0,
        "reactor_thermal_power":  100.0,
        "dnbr":                   1.85,
        "sg_pressure":            6.9,
        "sg_narrow_level":        55.0,
        "core_exit_temp":         335.0,
        "containment_pressure":   98.0,
        "containment_temp":       30.0,
        "containment_radiation":  0.1,
    },
    # Station Black-Out: turbine + main feedwater lost, RCS coolable via AFWS.
    "sbo": {
        "reactor_coolant_flow":   55.0,
        "sg_pressure":            7.3,
        "sg_narrow_level":        40.0,
        "containment_temp":       35.0,
    },
    # LOCA: rapid RCS depressurization, PRZ level loss, containment loading.
    "loca": {
        "pressurizer_pressure":    4.0,
        "pressurizer_level":       8.0,
        "reactor_coolant_flow":   70.0,
        "subcooling_margin":        0.0,
        "containment_pressure":   260.0,
        "containment_temp":        85.0,
        "containment_radiation":    5.0,
        "sg_pressure":              6.6,
        "sg_narrow_level":         40.0,
    },
    # SGTR: primary→secondary leak, slow PRZ depressurization, SG filling.
    "sgtr": {
        "pressurizer_pressure":   12.5,
        "pressurizer_level":      28.0,
        "sg_narrow_level":        85.0,
        "sg_pressure":             7.2,
        "containment_radiation":   0.1,  # containment intact; radioactivity goes via MSS
    },
}

# Mode-specific drift rates — LOCA is fast, SGTR is slow.
_MODE_RESTORE_RATE: dict[OperatingMode, float] = {
    "normal": 0.05,
    "sbo": 0.05,
    "loca": 0.15,
    "sgtr": 0.04,
}


def detect_mode(state: PlantState) -> OperatingMode:
    """Identify the dominant accident mode from current state.

    Priority: LOCA > SGTR > SBO > normal. The simulator drives system status
    and procedure activation in the scenario event; physics reads them back.
    """
    sys = state.systems

    # LOCA: any RCS pressure-boundary system tripped, OR ESFAS-SIAS active.
    rcs_breached = any(
        (sys.get(sid) is not None and sys[sid].status == "tripped")
        for sid in ("RCS-Pipe", "RPV", "Pressurizer", "RCP")
    )
    sias_active = state.alarms.get("ALM-ESFAS-SIAS") and state.alarms["ALM-ESFAS-SIAS"].state == "active"
    if rcs_breached or sias_active:
        return "loca"

    # SGTR: SG tripped with radiation alarms on the secondary side.
    sg_breach = sys.get("SG") is not None and sys["SG"].status == "tripped"
    sg_rad = state.alarms.get("ALM-RAD-HI-SG")
    mss_rad = state.alarms.get("ALM-RAD-HI-MSS")
    sg_rad_active = (sg_rad and sg_rad.state == "active") or (mss_rad and mss_rad.state == "active")
    if sg_breach or sg_rad_active:
        return "sgtr"

    # SBO: turbine + main feedwater lost simultaneously.
    mfw = sys.get("MFWS") or sys.get("Main-Feedwater")
    tg = sys.get("Turbine-Gen") or sys.get("Turbine")
    if mfw and tg and mfw.status in ("tripped", "standby") and tg.status in ("tripped", "standby"):
        return "sbo"

    return "normal"


def physics_step(state: PlantState, rng: random.Random) -> None:
    """One tick of variable evolution."""
    mode = detect_mode(state)

    # SCRAM dynamics first: drive thermal power down on decay curve.
    if state.systems.get("RPS") and state.systems["RPS"].status == "tripped":
        cur = state.vars.get("reactor_thermal_power", 100.0)
        state.vars["reactor_thermal_power"] = max(6.0, cur - 0.15 * cur)

    # Build the active target map: start with normal, overlay mode-specific.
    targets = dict(_MODE_TARGETS["normal"])
    if mode != "normal":
        targets.update(_MODE_TARGETS[mode])
    restore = _MODE_RESTORE_RATE[mode]

    # Restorative drift toward the mode targets.
    rps_tripped = (state.systems.get("RPS") is not None
                   and state.systems["RPS"].status == "tripped")
    for var, target in targets.items():
        cur = state.vars.get(var, target)
        if var == "reactor_thermal_power" and rps_tripped:
            continue
        delta = (target - cur) * restore
        # tiny noise scaled to magnitude (keeps narrow-band alarms from chattering)
        delta += rng.uniform(-0.005, 0.005) * (abs(target) if target else 1.0)
        state.vars[var] = cur + delta

    # Coupled rules.
    power = state.vars.get("reactor_thermal_power", 100.0)
    state.vars["hot_leg_temp"] = 290.0 + (power / 100.0) * 34.0 + rng.uniform(-0.5, 0.5)
    state.vars["core_exit_temp"] = state.vars["hot_leg_temp"] + 11.0
    state.vars["subcooling_margin"] = max(
        0.0,
        _saturation_margin(state.vars.get("pressurizer_pressure", 15.5))
        - state.vars["hot_leg_temp"],
    )
    if power > 0:
        state.vars["dnbr"] = max(0.5, 1.85 * (100.0 / max(power, 1.0)))


def _saturation_margin(pressure_mpa: float) -> float:
    """Rough Tsat(p) curve for the working range; deg C.

    Antoine-ish fit; for 6–17 MPa range this is adequate for the sim.
    """
    try:
        return 311.0 + 6.0 * math.log(max(pressure_mpa, 0.1))
    except ValueError:
        return 311.0
