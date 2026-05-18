"""G10 — Procedure Document Lock.

doc_write on a procedure-category document (NOP/AOP/EOP/STP/MMP-SAP) is
forbidden regardless of operator role.
"""

from __future__ import annotations

from src.guardrails.base import Guardrail, GuardrailContext, Verdict, allow, block
from src.message_models import Message

PROCEDURE_CATEGORIES = {"NOP", "AOP", "EOP", "STP", "MMP-SAP"}


class G10ProcedureDocLock(Guardrail):
    id = "G10"

    async def process(self, msg: Message, ctx: GuardrailContext) -> Verdict:
        if msg.type != "ACTION":
            return allow(msg, reason="g10-noop-non-action")
        if msg.action_type != "doc_write":
            return allow(msg, reason="g10-not-doc-write")
        if not msg.target_document:
            return block(msg, reason="g10-doc-write-without-target", category="missing-target-doc")
        doc = ctx.plant.documents.get(msg.target_document)
        if doc is None:
            return block(msg, reason=f"g10-unknown-document ({msg.target_document})",
                         category="unknown-document")
        if doc.category in PROCEDURE_CATEGORIES or not doc.modifiable:
            return block(
                msg,
                reason=f"g10-procedure-doc-modification-forbidden ({doc.document_id}/{doc.category})",
                category="procedure-doc-lock",
            )
        return allow(msg, reason=f"g10-modifiable-doc ({doc.document_id})")
