"""Plant simulator smoke test."""

from __future__ import annotations

from pathlib import Path

from src.plant_simulator import PlantSimulator


def test_normal_baseline_stable_for_100_ticks():
    sim = PlantSimulator(str(Path("scenarios/normal_baseline.yaml")), seed=42)
    for _ in range(100):
        sim.tick()
    s = sim.state
    assert s.tick == 100
    # all 6 safety functions intact in normal baseline
    from src.plant_state import SafetyFunctions
    for f in SafetyFunctions.model_fields:
        assert getattr(s.safety_functions, f) == "intact", f"{f} degraded under baseline"
    assert s.op_state == "normal"


def test_scram_changes_state():
    sim = PlantSimulator(str(Path("scenarios/normal_baseline.yaml")), seed=42)
    sim.tick()
    from src.message_models import Message
    msg = Message(tick=sim.state.tick, sender="SRO", recipient="broadcast",
                  type="ACTION", action_type="scram", procedure_ref="AOP-3",
                  payload="manual scram")
    sim.apply_action(msg)
    assert sim.state.systems["RPS"].status == "tripped"
    assert sim.state.alarms["ALM-SCRAM"].state == "active"
    # subsequent ticks should drive power down
    for _ in range(5):
        sim.tick()
    assert sim.state.vars["reactor_thermal_power"] < 100.0
