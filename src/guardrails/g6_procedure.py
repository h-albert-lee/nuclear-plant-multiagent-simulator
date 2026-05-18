"""G6 — Procedure Grounding.

L3+ ACTION must reference a known procedure_ref (NOP/AOP/EOP/STP/MMP-SAP).
"""

from __future__ import annotations

from src.guardrails.base import Guardrail, GuardrailContext, Verdict, allow, block
from src.message_models import Message

VALID_PROC_PREFIXES = ("NOP-", "AOP-", "EOP-", "STP-", "MMP-SAP-")


class G6ProcedureGrounding(Guardrail):
    id = "G6"

    async def process(self, msg: Message, ctx: GuardrailContext) -> Verdict:
        if msg.type != "ACTION":
            return allow(msg, reason="g6-noop-non-action")
        if msg.action_class not in ("L3", "L4"):
            return allow(msg, reason="g6-not-required")
        ref = msg.procedure_ref or ""
        if not ref:
            return block(msg, reason="g6-procedure-ref-missing", category="procedure-grounding")
        if not any(ref.startswith(p) for p in VALID_PROC_PREFIXES):
            return block(msg, reason=f"g6-procedure-ref-unknown ({ref})", category="procedure-grounding")
        return allow(msg, reason=f"g6-procedure-grounded ({ref})")
