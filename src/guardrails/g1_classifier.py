"""G1 — Action Classifier.

Fills `action_class` on ACTION messages using deterministic derivation.
If `action_type` is missing on an ACTION message, this is a malformed message;
we mark `action_class = "N/A"` and let downstream G2/G6 handle the block.
LLM fallback for action_type inference is out of scope for Stage 0 (the
honest signal is whether the agent emitted a structured message at all).
"""

from __future__ import annotations

from src.guardrails.base import Guardrail, GuardrailContext, Verdict, modify
from src.guardrails.derivation import derive_action_class
from src.message_models import Message


class G1ActionClassifier(Guardrail):
    id = "G1"

    async def process(self, msg: Message, ctx: GuardrailContext) -> Verdict:
        if msg.type != "ACTION":
            return modify(msg, reason="g1-noop-non-action")
        target_sys = ctx.plant.systems.get(msg.target_system) if msg.target_system else None
        target_alarm = ctx.plant.alarms.get(msg.target_alarm) if msg.target_alarm else None
        target_doc = ctx.plant.documents.get(msg.target_document) if msg.target_document else None
        derived = derive_action_class(
            msg.action_type,
            target_system=target_sys,
            target_alarm=target_alarm,
            target_document=target_doc,
            plant_op_state=ctx.plant.op_state,
        )
        if derived == msg.action_class:
            return modify(msg, reason="g1-class-unchanged")
        new = msg.model_copy(update={"action_class": derived})
        return modify(new, reason=f"g1-derived:{derived}")
