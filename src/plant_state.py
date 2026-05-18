"""Plant state schema.

A single PlantState instance is owned by plant_simulator and *copied* into
bus messages / log events. Never mutated by guardrails or agents.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from src.enums import (
    AlarmRuntimeState,
    AlarmSeverity,
    DocumentCategory,
    PlantOpState,
    SafetyFunctionState,
    SetpointTier,
    SuppressPolicy,
    SystemClassification,
    SystemStatus,
)


class AlarmState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    alarm_id: str
    state: AlarmRuntimeState = "cleared"
    since_tick: int = 0
    severity: AlarmSeverity = "info"
    was_critical: bool = False
    suppress_policy: SuppressPolicy = "allowed"
    setpoint_tier: SetpointTier = "n/a"
    description: str = ""


class SystemState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sys_id: str
    status: SystemStatus = "standby"
    classification: SystemClassification
    safety_logic_active: bool = True
    description: str = ""


class ProcedureState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active: Optional[str] = None  # e.g. "NOP-12"
    step: int = 0


class SafetyFunctions(BaseModel):
    """6 CSFs (Critical Safety Functions, SPDS 표기 기준)."""

    model_config = ConfigDict(extra="forbid")

    reactivity_control: SafetyFunctionState = "intact"
    core_heat_removal: SafetyFunctionState = "intact"
    rcs_heat_removal: SafetyFunctionState = "intact"
    rcs_integrity: SafetyFunctionState = "intact"
    containment_integrity: SafetyFunctionState = "intact"
    radioactivity_control: SafetyFunctionState = "intact"

    def compromised(self) -> bool:
        return any(getattr(self, f) != "intact" for f in type(self).model_fields)

    def lost_any(self) -> bool:
        return any(getattr(self, f) == "lost" for f in type(self).model_fields)


class DocumentMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    category: DocumentCategory
    modifiable: bool


class PlantState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tick: int = 0
    op_state: PlantOpState = "normal"
    vars: dict[str, float] = Field(default_factory=dict)
    alarms: dict[str, AlarmState] = Field(default_factory=dict)
    systems: dict[str, SystemState] = Field(default_factory=dict)
    procedures: ProcedureState = Field(default_factory=ProcedureState)
    safety_functions: SafetyFunctions = Field(default_factory=SafetyFunctions)
    documents: dict[str, DocumentMeta] = Field(default_factory=dict)

    def snapshot(self) -> "PlantState":
        """Deep copy of current state for trace logging."""
        return PlantState.model_validate(self.model_dump())
