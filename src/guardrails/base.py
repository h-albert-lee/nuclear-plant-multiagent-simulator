"""Guardrail base interface.

Each guardrail receives a Message + plant snapshot + side-channel context
(approval state, STA veto ledger, etc.) and returns one of:

  - AllowVerdict(message)         : passes through (possibly mutated)
  - ModifyVerdict(new_message)    : transforms (e.g. G7 → ESCALATE conversion)
  - BlockVerdict(reason, category): drops the message and records the reason
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from src.enums import GuardrailId
from src.message_models import Message
from src.plant_state import PlantState


@dataclass
class GuardrailContext:
    """Shared, mutable state across guardrail invocations within a tick."""

    tick: int
    plant: PlantState
    # G3: who has approved which (target_system, action_class) recently.
    # value = list of (tick, sender) tuples.
    approval_ledger: dict[tuple[str, str], list[tuple[int, str]]]
    # G4: which msg_ids are currently vetoed by STA → release-on-OVERRIDE.
    sta_vetoes: dict[str, "Message"]
    sta_overrides: dict[str, "Message"]
    # G9: per-sender ACTION counts for current tick.
    rate_counts: dict[str, int]


@dataclass
class AllowVerdict:
    message: Message
    reason: str = ""


@dataclass
class ModifyVerdict:
    new_message: Message
    reason: str


@dataclass
class BlockVerdict:
    reason: str
    block_category: str
    original_message: Message


Verdict = AllowVerdict | ModifyVerdict | BlockVerdict


class Guardrail(ABC):
    """Abstract guardrail. Pure-function ideal; some need ctx for cross-message state."""

    id: GuardrailId
    enabled: bool = True

    @abstractmethod
    async def process(self, msg: Message, ctx: GuardrailContext) -> Verdict:
        raise NotImplementedError

    def __repr__(self) -> str:
        return f"<Guardrail {self.id} enabled={self.enabled}>"


def allow(msg: Message, reason: str = "") -> AllowVerdict:
    return AllowVerdict(message=msg, reason=reason)


def block(msg: Message, reason: str, category: str) -> BlockVerdict:
    return BlockVerdict(reason=reason, block_category=category, original_message=msg)


def modify(new_msg: Message, reason: str) -> ModifyVerdict:
    return ModifyVerdict(new_message=new_msg, reason=reason)
