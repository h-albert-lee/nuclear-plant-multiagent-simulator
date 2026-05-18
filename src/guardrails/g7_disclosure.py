"""G7 — Mandatory Disclosure.

If an agent emits an `urgency=immediate` message *without* a procedure_ref,
the assumption is that the agent is acting in surprise/panic — convert to
ESCALATE so a human can take over.
"""

from __future__ import annotations

from src.enums import OPERATOR_ROLES
from src.guardrails.base import Guardrail, GuardrailContext, Verdict, allow, modify
from src.message_models import Message


class G7MandatoryDisclosure(Guardrail):
    id = "G7"

    async def process(self, msg: Message, ctx: GuardrailContext) -> Verdict:
        if msg.sender not in OPERATOR_ROLES:
            return allow(msg, reason="g7-not-operator")
        if msg.urgency != "immediate":
            return allow(msg, reason="g7-not-immediate")
        if msg.procedure_ref:
            return allow(msg, reason="g7-has-procedure")
        new = msg.model_copy(update={"type": "ESCALATE", "recipient": "Console"})
        return modify(new, reason="g7-immediate-without-procedure→escalate")
