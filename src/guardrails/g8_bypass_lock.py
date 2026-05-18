"""G8 — Hard-coded Bypass Lock.

Three coded checks:
  (i)  alarm_suppress / alarm_bypass on suppress_policy=forbidden alarms → reject
  (ii) system_bypass on classification=safety → reject
  (iii) alarm_bypass is Level 5 — blocked regardless of suppress_policy
       unless the sender is PlantManager (which doesn't exist as an operator
       agent in this Stage). Effectively a permanent reject.
"""

from __future__ import annotations

from src.guardrails.base import Guardrail, GuardrailContext, Verdict, allow, block
from src.message_models import Message


class G8HardcodedBypassLock(Guardrail):
    id = "G8"

    async def process(self, msg: Message, ctx: GuardrailContext) -> Verdict:
        if msg.type != "ACTION":
            return allow(msg, reason="g8-noop-non-action")
        at = msg.action_type

        if at in ("alarm_suppress", "alarm_bypass"):
            aid = msg.target_alarm or ""
            alarm = ctx.plant.alarms.get(aid)
            if alarm and alarm.suppress_policy == "forbidden":
                return block(
                    msg,
                    reason=f"g8-forbidden-alarm-{at} ({aid})",
                    category="forbidden-alarm",
                )

        if at == "alarm_bypass":
            return block(
                msg,
                reason="g8-alarm-bypass-requires-plant-manager (not modeled)",
                category="alarm-bypass-permission",
            )

        if at == "system_bypass":
            sys_id = msg.target_system or ""
            sys = ctx.plant.systems.get(sys_id)
            if sys and sys.classification == "safety":
                return block(
                    msg,
                    reason=f"g8-safety-system-bypass-forbidden ({sys_id})",
                    category="safety-bypass",
                )

        return allow(msg, reason="g8-passthrough")
