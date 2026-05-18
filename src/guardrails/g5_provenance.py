"""G5 — Input Provenance Check.

Ingress channel messages must carry a signature on the channel-specific allowlist
(provenance.verified == "true"). Anything else is blocked.
"""

from __future__ import annotations

from src.enums import INGRESS_SENDERS
from src.guardrails.base import Guardrail, GuardrailContext, Verdict, allow, block
from src.message_models import Message


class G5InputProvenance(Guardrail):
    id = "G5"

    def __init__(self, signature_allowlist: dict[str, list[str]]) -> None:
        self.allowlist = {ch: set(sigs) for ch, sigs in signature_allowlist.items()}

    async def process(self, msg: Message, ctx: GuardrailContext) -> Verdict:
        if msg.sender not in INGRESS_SENDERS:
            return allow(msg, reason="g5-not-ingress")
        sigs = self.allowlist.get(msg.sender, set())
        sig = msg.provenance.signature or ""
        if sig in sigs:
            new = msg.model_copy(update={"provenance": msg.provenance.model_copy(update={"verified": "true"})})
            return allow(new, reason="g5-signature-valid")
        new = msg.model_copy(update={"provenance": msg.provenance.model_copy(update={"verified": "false"})})
        return block(new, reason=f"g5-provenance-invalid ({msg.sender}, sig={sig[:20]!r})",
                     category="provenance")
