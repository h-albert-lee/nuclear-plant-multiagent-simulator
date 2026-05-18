"""LOCA / SGTR scenario smoke tests.

We don't validate exact thermohydraulic numbers (this is Stage 0); we verify
the qualitative behaviour:
  - LOCA drives RCS pressure and pressurizer level down, containment pressure up
  - SGTR drives SG narrow level up and triggers secondary radiation alarms
  - the right safety functions get marked degraded/lost
"""

from __future__ import annotations

from pathlib import Path

from src.plant_simulator import PlantSimulator
from src.plant_simulator.physics import detect_mode


def _run(sim: PlantSimulator, n: int):
    for _ in range(n):
        sim.tick()


def test_loca_small_drives_correct_dynamics():
    sim = PlantSimulator(str(Path("scenarios/loca_small.yaml")), seed=42)
    _run(sim, 250)  # well past CSAS at tick 200

    # RCS depressurized
    assert sim.state.vars["pressurizer_pressure"] < 10.0
    # Pressurizer level dropped
    assert sim.state.vars["pressurizer_level"] < 30.0
    # Containment loaded
    assert sim.state.vars["containment_pressure"] > 140.0
    # Containment radiation rising
    assert sim.state.vars["containment_radiation"] > 1.0
    # ESFAS signals all forbidden
    for aid in ("ALM-ESFAS-SIAS", "ALM-ESFAS-CIAS", "ALM-ESFAS-CSAS", "ALM-SCRAM"):
        assert sim.state.alarms[aid].state == "active", f"{aid} should be active"
    # RPS tripped
    assert sim.state.systems["RPS"].status == "tripped"
    # safety functions degraded — at minimum RCS integrity
    assert sim.state.safety_functions.rcs_integrity in ("degraded", "lost")
    # mode detected as LOCA
    assert detect_mode(sim.state) == "loca"


def test_sgtr_drives_correct_dynamics():
    sim = PlantSimulator(str(Path("scenarios/sgtr_v1.yaml")), seed=42)
    _run(sim, 220)

    # Secondary radiation alarms active
    assert sim.state.alarms["ALM-RAD-HI-SG"].state == "active"
    assert sim.state.alarms["ALM-RAD-HI-MSS"].state == "active"
    # PRZ depress slower than LOCA — should be below 14 but above 10
    assert 10.0 < sim.state.vars["pressurizer_pressure"] < 14.5
    # SG narrow level rising toward 85%
    assert sim.state.vars["sg_narrow_level"] > 65.0
    # Containment intact (radiation contained)
    assert sim.state.vars["containment_radiation"] < 0.5
    # Reactor scrammed, MSS isolated
    assert sim.state.systems["RPS"].status == "tripped"
    assert sim.state.systems["MSS"].status == "isolated"
    # mode detected as SGTR
    assert detect_mode(sim.state) == "sgtr"


def test_loca_detection_via_alarm_only():
    """detect_mode should pick LOCA even if RCS-Pipe status isn't tripped
    (e.g., because the event only set ESFAS signals)."""
    sim = PlantSimulator(str(Path("scenarios/normal_baseline.yaml")), seed=42)
    sim.tick()
    sim.state.alarms["ALM-ESFAS-SIAS"].state = "active"
    assert detect_mode(sim.state) == "loca"


def test_sgtr_detection_via_alarm_only():
    sim = PlantSimulator(str(Path("scenarios/normal_baseline.yaml")), seed=42)
    sim.tick()
    sim.state.alarms["ALM-RAD-HI-MSS"].state = "active"
    assert detect_mode(sim.state) == "sgtr"


def test_normal_baseline_mode_remains_normal():
    sim = PlantSimulator(str(Path("scenarios/normal_baseline.yaml")), seed=42)
    _run(sim, 100)
    assert detect_mode(sim.state) == "normal"
