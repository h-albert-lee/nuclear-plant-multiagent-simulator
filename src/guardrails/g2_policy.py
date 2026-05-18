"""G2 — Policy Gate (sender × action_class lookup)."""

from __future__ import annotations

from pathlib import Path

from src.config_models import load_yaml
from src.guardrails.base import Guardrail, GuardrailContext, Verdict, allow, block
from src.message_models import Message


class G2PolicyGate(Guardrail):
    id = "G2"

    def __init__(self, policy_table_path: str | Path) -> None:
        data = load_yaml(policy_table_path)
        self.matrix: dict[str, dict[str, str]] = data.get("matrix", {})

    async def process(self, msg: Message, ctx: GuardrailContext) -> Verdict:
        if msg.type != "ACTION":
            return allow(msg, reason="g2-noop-non-action")
        sender = msg.sender
        klass = msg.action_class
        policy = self.matrix.get(sender, {}).get(klass)
        if policy is None:
            return block(msg, reason=f"no-policy ({sender}/{klass})", category="missing-policy")
        if policy == "allow" or policy == "allow_with_post_report":
            return allow(msg, reason=f"g2-{policy}")
        if policy == "approve_only" or policy == "deny_only":
            return allow(msg, reason=f"g2-{policy}-passes-down")  # consumer side enforces
        return block(msg, reason=f"g2-block ({sender}/{klass}→{policy})", category="policy-violation")
