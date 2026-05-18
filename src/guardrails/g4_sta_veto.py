"""G4 — STA Veto Channel.

VETO msg from STA suspends the referenced ACTION until a matching SRO OVERRIDE
(with override_reason in payload) arrives. If STA mode is STA-C, OVERRIDE is
disallowed and the ACTION stays blocked permanently.
"""

from __future__ import annotations

from src.enums import STAMode
from src.guardrails.base import Guardrail, GuardrailContext, Verdict, allow, block
from src.message_models import Message


class G4STAVetoChannel(Guardrail):
    id = "G4"

    def __init__(self, sta_mode: STAMode = "STA-B") -> None:
        self.sta_mode = sta_mode

    async def process(self, msg: Message, ctx: GuardrailContext) -> Verdict:
        if msg.type == "VETO":
            if self.sta_mode == "STA-A" or self.sta_mode == "STA-Off":
                return block(msg, reason=f"g4-veto-disallowed-in-{self.sta_mode}", category="sta-mode")
            ref = str(msg.in_response_to) if msg.in_response_to else ""
            ctx.sta_vetoes[ref] = msg
            return allow(msg, reason="g4-veto-recorded")

        if msg.type == "OVERRIDE":
            if self.sta_mode == "STA-C":
                return block(msg, reason="g4-override-forbidden-in-STA-C", category="sta-mode")
            if not msg.payload.strip():
                return block(msg, reason="g4-override-missing-reason", category="missing-override-reason")
            ref = str(msg.in_response_to) if msg.in_response_to else ""
            ctx.sta_overrides[ref] = msg
            # release the veto
            if ref in ctx.sta_vetoes:
                del ctx.sta_vetoes[ref]
            return allow(msg, reason="g4-override-recorded")

        if msg.type == "ACTION":
            ref = str(msg.msg_id)
            if ref in ctx.sta_vetoes and ref not in ctx.sta_overrides:
                return block(msg, reason="g4-sta-vetoed", category="sta-veto")

        return allow(msg, reason="g4-passthrough")
