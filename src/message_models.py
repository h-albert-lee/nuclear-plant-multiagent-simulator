"""Structured message protocol.

All inter-module communication flows through Message objects on the bus.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from src.enums import (
    ActionClass,
    ActionType,
    MessageType,
    ProvVerified,
    RecipientRole,
    SenderRole,
    Urgency,
)


class Provenance(BaseModel):
    """Provenance claim attached to an ingress message. Forgeable — the attack surface."""

    claimed_sender: Optional[str] = None
    signature: Optional[str] = None
    verified: ProvVerified = "unverified"


class Message(BaseModel):
    """Single structured message on the bus.

    `type=ACTION` requires `action_type` set; `action_class` is filled by G1
    or by the agent at construction.
    """

    model_config = ConfigDict(frozen=False, extra="forbid")

    msg_id: UUID = Field(default_factory=uuid4)
    tick: int
    sender: SenderRole
    recipient: RecipientRole
    type: MessageType
    action_type: Optional[ActionType] = None
    action_class: ActionClass = "N/A"
    procedure_ref: Optional[str] = None
    target_system: Optional[str] = None
    target_alarm: Optional[str] = None
    target_document: Optional[str] = None
    payload: str = ""
    urgency: Urgency = "routine"
    provenance: Provenance = Field(default_factory=Provenance)
    in_response_to: Optional[UUID] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class GuardrailVerdict(BaseModel):
    """Per-guardrail decision attached as side-channel metadata on a bus message."""

    guardrail_id: str
    decision: str  # "allow" | "modify" | "block"
    reason: str = ""
    block_category: Optional[str] = None  # for analytics


class BusEvent(BaseModel):
    """Wrapper used by the message bus to fan out a message together with
    any guardrail verdicts that have been recorded for it so far."""

    message: Message
    verdicts: list[GuardrailVerdict] = Field(default_factory=list)
