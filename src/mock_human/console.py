"""Mock-human approval console.

Rule-based; no UI. Listens on console.approval_request, emits console.approval_response.
Records the matched rule_id and sim-time latency on every response.
"""

from __future__ import annotations

import asyncio
import fnmatch
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

import structlog

from src.config_models import MockHumanConfig, load_yaml
from src.message_bus import (
    MessageBus,
    SOURCE_MOCK_HUMAN,
    TOPIC_CONSOLE_APPROVAL_REQUEST,
    TOPIC_CONSOLE_APPROVAL_RESPONSE,
)
from src.message_models import Message

log = structlog.get_logger(__name__)


@dataclass
class _MatchedRule:
    rule_id: str
    response: str  # "approved" | "denied"
    latency_seconds: float


class MockHumanConsole:
    """Async dispatcher. Each incoming APPROVAL_REQUEST is matched against the
    YAML rule set; the chosen response is published after a *simulated* latency.
    """

    def __init__(
        self,
        cfg: MockHumanConfig,
        *,
        bus: MessageBus,
        sim_time_scale: float = 0.1,
        approval_ledger_hook: Optional[Callable[[dict[str, Any]], "asyncio.Future | None"]] = None,
    ) -> None:
        self.cfg = cfg
        self.bus = bus
        self.sim_time_scale = sim_time_scale
        self.ledger_hook = approval_ledger_hook
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()
        rules_data = load_yaml(cfg.rule_set)
        self.default_deny_timeout = rules_data.get(
            "default_deny_timeout_seconds", cfg.default_deny_timeout_seconds
        )
        self.rules: list[dict[str, Any]] = rules_data.get("rules", [])
        # Tag rules with stable IDs for trace.
        for i, r in enumerate(self.rules):
            r.setdefault("id", f"rule-{i}")

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="mock-human")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None

    async def _run(self) -> None:
        async with self.bus.subscription(TOPIC_CONSOLE_APPROVAL_REQUEST) as q:
            while not self._stop.is_set():
                req = await q.get()
                asyncio.create_task(self._handle(req))

    async def _handle(self, req: Message) -> None:
        matched = self._match(req)
        if matched is None:
            # default-deny on timeout
            await self._sleep_sim(self.default_deny_timeout)
            response = self._make_response(req, "denied", rule_id="default-deny-timeout")
        else:
            await self._sleep_sim(matched.latency_seconds)
            response = self._make_response(req, matched.response, rule_id=matched.rule_id)
        await self.bus.publish(
            TOPIC_CONSOLE_APPROVAL_RESPONSE,
            response,
            source_module=SOURCE_MOCK_HUMAN,
        )
        if self.ledger_hook is not None:
            try:
                payload = {
                    "request_msg_id": str(req.msg_id),
                    "requesting_sender": req.sender,
                    "action_class": req.action_class,
                    "procedure_ref": req.procedure_ref,
                    "response": response.payload,
                    "matched_rule_id": (matched.rule_id if matched else "default-deny-timeout"),
                    "latency_sim_seconds": (matched.latency_seconds if matched else self.default_deny_timeout),
                }
                result = self.ledger_hook(payload)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:  # noqa: BLE001
                log.exception("mock_human_ledger_hook_failed")

    async def _sleep_sim(self, seconds: float) -> None:
        await asyncio.sleep(max(0.0, seconds * self.sim_time_scale))

    def _match(self, req: Message) -> Optional[_MatchedRule]:
        for rule in self.rules:
            cond = rule.get("condition", {})
            if not self._match_condition(cond, req):
                continue
            return _MatchedRule(
                rule_id=str(rule["id"]),
                response=str(rule.get("response", "denied")),
                latency_seconds=float(rule.get("latency_seconds", 30)),
            )
        return None

    def _match_condition(self, cond: dict[str, Any], req: Message) -> bool:
        # action_class
        ac = cond.get("action_class")
        if ac is not None:
            if isinstance(ac, list):
                if req.action_class not in ac:
                    return False
            else:
                if req.action_class != ac:
                    return False
        # procedure_ref presence
        if "procedure_ref_present" in cond:
            present = bool(req.procedure_ref)
            if present != bool(cond["procedure_ref_present"]):
                return False
        # procedure ref glob
        match = cond.get("procedure_match")
        if match:
            if not req.procedure_ref:
                return False
            patterns = match if isinstance(match, list) else [match]
            if not any(fnmatch.fnmatchcase(req.procedure_ref, p) for p in patterns):
                return False
        neg = cond.get("procedure_match_negate")
        if neg:
            patterns = neg if isinstance(neg, list) else [neg]
            if req.procedure_ref and any(fnmatch.fnmatchcase(req.procedure_ref, p) for p in patterns):
                return False
        # sta veto flag (sender supplied)
        if "sta_veto_active" in cond:
            sta_flag = "STA-VETO" in req.payload
            if sta_flag != bool(cond["sta_veto_active"]):
                return False
        if "override_reason_present" in cond:
            override_flag = "OVERRIDE-REASON" in req.payload
            if override_flag != bool(cond["override_reason_present"]):
                return False
        return True

    def _make_response(self, req: Message, payload: str, *, rule_id: str) -> Message:
        return Message(
            tick=req.tick,
            sender="Console",
            recipient=req.sender,
            type="APPROVAL_RESPONSE",
            action_type=None,
            action_class=req.action_class,
            procedure_ref=req.procedure_ref,
            target_system=req.target_system,
            payload=f"{payload}#rule={rule_id}",
            urgency="prompt",
            in_response_to=req.msg_id,
        )
