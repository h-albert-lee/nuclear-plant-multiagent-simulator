"""G3 — Two-Person Integrity.

L3+ ACTION requires another sender's APPROVAL_RESPONSE: approved on the same
target_system within `approval_window_ticks` of the originating ACTION.
"""

from __future__ import annotations

from src.guardrails.base import Guardrail, GuardrailContext, Verdict, allow, block
from src.message_models import Message


class G3TwoPersonIntegrity(Guardrail):
    id = "G3"

    def __init__(self, approval_window_ticks: int = 3) -> None:
        self.window = approval_window_ticks

    async def process(self, msg: Message, ctx: GuardrailContext) -> Verdict:
        if msg.type == "APPROVAL_RESPONSE" and msg.payload.startswith("approved"):
            key = (msg.target_system or "", msg.action_class)
            ctx.approval_ledger.setdefault(key, []).append((ctx.tick, msg.sender))
            return allow(msg, reason="g3-ledger-recorded")
        if msg.type != "ACTION":
            return allow(msg, reason="g3-noop-non-action")
        if msg.action_class not in ("L3", "L4"):
            return allow(msg, reason="g3-not-required")

        key = (msg.target_system or "", msg.action_class)
        entries = ctx.approval_ledger.get(key, [])
        recent = [(t, s) for (t, s) in entries if (ctx.tick - t) <= self.window and s != msg.sender]
        if recent:
            return allow(msg, reason=f"g3-approval-present({recent[-1][1]})")
        return block(
            msg,
            reason=f"g3-no-second-approver (target={msg.target_system}, class={msg.action_class})",
            category="two-person-missing",
        )
