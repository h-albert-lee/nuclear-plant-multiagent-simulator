"""G0 — Baseline. No-op pass-through; for ablation 'no guardrails' comparison."""

from __future__ import annotations

from src.guardrails.base import Guardrail, GuardrailContext, Verdict, allow
from src.message_models import Message


class G0Baseline(Guardrail):
    id = "G0"

    async def process(self, msg: Message, ctx: GuardrailContext) -> Verdict:
        return allow(msg, reason="baseline-noop")
