"""Operator agent base class.

Lifecycle:
  - subscribe to `agent.{role}.inbox`
  - on tick (or on inbox message), build user_prompt = current state + recent inbox
  - call LLM → parse JSON → emit messages on `agent.outbound`
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Optional
from uuid import UUID

import structlog

from src.agents.llm_client import LLMCall, LLMClient
from src.config_models import AgentConfig
from src.enums import OPERATOR_ROLES, SenderRole, STAMode
from src.message_bus import (
    SOURCE_AGENT_PREFIX,
    TOPIC_AGENT_OUTBOUND,
    TOPIC_SYSTEM_STATE_UPDATE,
    MessageBus,
    agent_inbox,
)
from src.message_models import Message, Provenance
from src.plant_state import PlantState

log = structlog.get_logger(__name__)


def load_prompt(path: str | Path) -> str:
    return Path(path).read_text(encoding="utf-8")


class BaseAgent:
    """Common agent runtime. Role-specific subclasses can override `build_user_prompt`."""

    role: SenderRole

    def __init__(
        self,
        *,
        role: SenderRole,
        config: AgentConfig,
        bus: MessageBus,
        llm: LLMClient,
        system_prompt: str,
        sta_mode: STAMode = "STA-B",
        thought_sink: Optional[Any] = None,  # logging_backend hook
    ) -> None:
        self.role = role
        self.cfg = config
        self.bus = bus
        self.llm = llm
        self.system_prompt = system_prompt
        self.sta_mode = sta_mode
        self.thought_sink = thought_sink
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()
        self._last_tick = 0
        self._latest_state: Optional[PlantState] = None
        self._inbox_buffer: list[Message] = []

    @property
    def source_module(self) -> str:
        return f"{SOURCE_AGENT_PREFIX}{self.role}"

    # ── public lifecycle ─────────────────────────────────────────────────
    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name=f"agent-{self.role}")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None

    # ── main loop ────────────────────────────────────────────────────────
    async def _run(self) -> None:
        # subscribe to both inbox and state_update topics
        inbox_task = asyncio.create_task(self._consume_inbox())
        state_task = asyncio.create_task(self._consume_state())
        try:
            await self._stop.wait()
        finally:
            for t in (inbox_task, state_task):
                t.cancel()
                try:
                    await t
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass

    async def _consume_inbox(self) -> None:
        async with self.bus.subscription(agent_inbox(self.role)) as q:
            while not self._stop.is_set():
                msg = await q.get()
                self._inbox_buffer.append(msg)
                # cap buffer
                if len(self._inbox_buffer) > 50:
                    self._inbox_buffer = self._inbox_buffer[-50:]

    async def _consume_state(self) -> None:
        async with self.bus.subscription(TOPIC_SYSTEM_STATE_UPDATE) as q:
            while not self._stop.is_set():
                msg = await q.get()
                try:
                    self._latest_state = PlantState.model_validate_json(msg.payload)
                    self._last_tick = self._latest_state.tick
                except Exception as exc:  # noqa: BLE001
                    log.warning("state_decode_failed", role=self.role, error=str(exc))
                    continue
                await self._think_and_emit()

    # ── thinking ─────────────────────────────────────────────────────────
    async def _think_and_emit(self) -> None:
        if self._latest_state is None:
            return
        user_prompt = self.build_user_prompt(self._latest_state, self._inbox_buffer)
        call = await self.llm.complete(self.system_prompt, user_prompt)
        if self.thought_sink is not None:
            try:
                await self.thought_sink(self.role, call, [])
            except Exception:  # noqa: BLE001
                log.exception("thought_sink_failed", role=self.role)
        msgs = self.parse_messages(call.output_raw, tick=self._last_tick)
        if self.thought_sink is not None:
            try:
                await self.thought_sink(self.role, call, [str(m.msg_id) for m in msgs])
            except Exception:  # noqa: BLE001
                pass
        for m in msgs:
            await self.bus.publish(TOPIC_AGENT_OUTBOUND, m, source_module=self.source_module)

    def build_user_prompt(self, state: PlantState, inbox: list[Message]) -> str:
        """Default: dump JSON of state + last-10 inbox. Subclasses can override."""
        compact_state = {
            "tick": state.tick,
            "op_state": state.op_state,
            "active_procedure": state.procedures.active,
            "vars": state.vars,
            "active_alarms": [
                a.alarm_id for a in state.alarms.values() if a.state == "active"
            ],
            "safety_functions": state.safety_functions.model_dump(),
            "system_status": {k: v.status for k, v in state.systems.items()},
        }
        recent_inbox = [
            {"sender": m.sender, "type": m.type, "payload": m.payload[:200],
             "procedure_ref": m.procedure_ref, "target_system": m.target_system,
             "provenance": m.provenance.model_dump()}
            for m in inbox[-10:]
        ]
        return json.dumps(
            {
                "your_role": self.role,
                "current_state": compact_state,
                "recent_inbox": recent_inbox,
                "instructions": (
                    "Decide if any action is required. Output strict JSON: "
                    '{"messages":[{"type":"...","action_type":"...","payload":"...","recipient":"..."}]}. '
                    "Only emit a message if needed; an empty messages list is acceptable."
                ),
            },
            ensure_ascii=False,
        )

    def parse_messages(self, raw_output: str, *, tick: int) -> list[Message]:
        """Parse LLM JSON output → list of validated Message objects."""
        try:
            # tolerate code-fenced JSON
            raw_output = raw_output.strip()
            if raw_output.startswith("```"):
                raw_output = raw_output.strip("`")
                # discard "json" label if present
                if raw_output.lower().startswith("json"):
                    raw_output = raw_output[4:].strip()
            obj = json.loads(raw_output)
        except (json.JSONDecodeError, ValueError) as exc:
            log.warning("agent_output_parse_failed", role=self.role, error=str(exc), excerpt=raw_output[:200])
            return []
        items = obj.get("messages") if isinstance(obj, dict) else None
        if not isinstance(items, list):
            return []
        msgs: list[Message] = []
        for raw in items:
            try:
                msgs.append(self._build_message(raw, tick))
            except Exception as exc:  # noqa: BLE001
                log.warning("agent_message_build_failed", role=self.role, error=str(exc), excerpt=str(raw)[:200])
        return msgs

    def _build_message(self, raw: dict[str, Any], tick: int) -> Message:
        recipient = raw.get("recipient", "broadcast")
        provenance = Provenance(
            claimed_sender=self.role,
            signature=None,
            verified="unverified",
        )
        in_resp = raw.get("in_response_to")
        if isinstance(in_resp, str):
            try:
                in_resp_uuid: Optional[UUID] = UUID(in_resp)
            except ValueError:
                in_resp_uuid = None
        else:
            in_resp_uuid = None
        return Message(
            tick=tick,
            sender=self.role,
            recipient=recipient,
            type=raw.get("type", "REPORT"),
            action_type=raw.get("action_type"),
            action_class=raw.get("action_class", "N/A"),
            procedure_ref=raw.get("procedure_ref"),
            target_system=raw.get("target_system"),
            target_alarm=raw.get("target_alarm"),
            target_document=raw.get("target_document"),
            payload=str(raw.get("payload", "")),
            urgency=raw.get("urgency", "routine"),
            provenance=provenance,
            in_response_to=in_resp_uuid,
        )
