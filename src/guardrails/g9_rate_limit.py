"""G9 — Rate Limit. Per-sender ACTION count cap per tick."""

from __future__ import annotations

from src.guardrails.base import Guardrail, GuardrailContext, Verdict, allow, block
from src.message_models import Message


class G9RateLimit(Guardrail):
    id = "G9"

    def __init__(self, cap_per_tick: int = 5) -> None:
        self.cap = cap_per_tick

    async def process(self, msg: Message, ctx: GuardrailContext) -> Verdict:
        if msg.type != "ACTION":
            return allow(msg, reason="g9-noop-non-action")
        cur = ctx.rate_counts.get(msg.sender, 0)
        if cur >= self.cap:
            return block(msg, reason=f"g9-rate-cap-exceeded ({msg.sender} > {self.cap}/tick)",
                         category="rate-limit")
        ctx.rate_counts[msg.sender] = cur + 1
        return allow(msg, reason=f"g9-within-cap ({cur + 1}/{self.cap})")
