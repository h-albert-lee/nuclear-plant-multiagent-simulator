"""Centralized Literal enums used across the simulation.

Kept in a single module so message_models, plant_state, config_models, and
guardrails import a single source of truth.
"""

from __future__ import annotations

from typing import Literal

# ─── Senders / Recipients ─────────────────────────────────────────────────────
SenderRole = Literal[
    "SRO", "RO", "TO", "STA", "AO",
    "Console",
    "CH-A", "CH-B", "CH-C", "CH-D",
    "System",
]

RecipientRole = Literal[
    "SRO", "RO", "TO", "STA", "AO",
    "Console",
    "broadcast",
]

OPERATOR_ROLES: tuple[str, ...] = ("SRO", "RO", "TO", "STA", "AO")
INGRESS_SENDERS: frozenset[str] = frozenset({"CH-A", "CH-B", "CH-C", "CH-D"})
CHANNELS: tuple[str, ...] = ("CH-A", "CH-B", "CH-C", "CH-D")

# ─── Message types ────────────────────────────────────────────────────────────
MessageType = Literal[
    "ACTION",
    "REPORT",
    "QUERY",
    "ESCALATE",
    "APPROVAL_REQUEST",
    "APPROVAL_RESPONSE",
    "VETO",
    "OVERRIDE",
]

# ─── Action taxonomy ──────────────────────────────────────────────────────────
ActionType = Literal[
    # docs
    "doc_read",
    "doc_summary",
    "doc_write",
    # monitoring
    "monitor",
    # control (system classification × plant_op_state matrix)
    "control",
    # specials (fixed authority levels)
    "reactor_power_control",
    "scram",
    "system_isolation",
    "alarm_acknowledge",
    "alarm_suppress",
    "alarm_bypass",
    "system_bypass",
    "emergency_declaration",
]

ActionClass = Literal["L1", "L2", "L2.5", "L3", "L4", "L5", "DENY", "N/A"]

Urgency = Literal["routine", "prompt", "immediate"]
ProvVerified = Literal["true", "false", "unverified"]

# ─── Plant ───────────────────────────────────────────────────────────────────
PlantOpState = Literal["normal", "abnormal", "emergency"]

AlarmRuntimeState = Literal["active", "ack", "suppressed", "bypassed", "cleared"]
AlarmSeverity = Literal["info", "warning", "critical"]
SuppressPolicy = Literal["forbidden", "conditional", "allowed"]
SetpointTier = Literal["low_low", "low", "high", "high_high", "trip", "n/a"]

SystemStatus = Literal["running", "standby", "tripped", "isolated"]
SystemClassification = Literal["non_safety_A", "non_safety_B", "safety"]

SafetyFunctionState = Literal["intact", "degraded", "lost"]

ProcedureCategory = Literal["NOP", "AOP", "EOP", "STP", "MMP-SAP"]
DocumentCategory = Literal[
    "NOP", "AOP", "EOP", "STP", "MMP-SAP",
    "log", "report", "summary",
]

# ─── Attack interface ─────────────────────────────────────────────────────────
AttackVisibility = Literal["black", "white"]

# ─── STA modes ────────────────────────────────────────────────────────────────
STAMode = Literal["STA-A", "STA-B", "STA-C", "STA-Off"]

# ─── Guardrail IDs ────────────────────────────────────────────────────────────
GuardrailId = Literal[
    "G0", "G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8", "G9", "G10",
]

# ─── Decision outcomes ────────────────────────────────────────────────────────
GuardrailDecision = Literal["allow", "modify", "block"]

# ─── LLM provider ─────────────────────────────────────────────────────────────
LLMProvider = Literal["anthropic", "openai", "google", "dashscope", "mock"]
