"""In-process asyncio pub/sub broker.

Single source-of-truth for *all* inter-module messaging. Logging backend
hooks here to record everything. Enforces one-way ingress: only the ingress
module can publish messages with sender ∈ {CH-A, CH-B, CH-C, CH-D}.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Awaitable, Callable, Optional

import structlog

from src.enums import INGRESS_SENDERS
from src.message_models import BusEvent, Message

log = structlog.get_logger(__name__)

# Module identity strings used as `source_module` when publishing.
SOURCE_INGRESS = "ingress"
SOURCE_AGENT_PREFIX = "agent."          # agent.SRO / agent.RO / ...
SOURCE_PLANT = "plant"
SOURCE_ORCHESTRATOR = "orchestrator"
SOURCE_GUARDRAIL = "guardrail"
SOURCE_MOCK_HUMAN = "mock_human"
SOURCE_SYSTEM = "system"

# Topic constants
TOPIC_AGENT_OUTBOUND = "agent.outbound"
TOPIC_SYSTEM_TICK = "system.tick"
TOPIC_SYSTEM_STATE_UPDATE = "system.state_update"
TOPIC_CONSOLE_APPROVAL_REQUEST = "console.approval_request"
TOPIC_CONSOLE_APPROVAL_RESPONSE = "console.approval_response"
TOPIC_LOG_TRACE = "log.trace"


def agent_inbox(role: str) -> str:
    return f"agent.{role}.inbox"


def channel_inbox(channel: str) -> str:
    return f"channel.{channel}.inbox"


class IngressImpersonation(RuntimeError):
    """Raised when a non-ingress module publishes a message claiming to come
    from one of the ingress channels. Hard fail — system invariant violation."""


HookFn = Callable[[str, Message], Awaitable[None]]


class MessageBus:
    """In-process asyncio pub/sub broker.

    Subscribers each get their own asyncio.Queue. Publish fans out to all
    queues subscribed to the given topic, plus an optional set of *global hooks*
    (used by the logging backend so every message is captured regardless of
    which topic it travelled on).
    """

    def __init__(self) -> None:
        self._subs: dict[str, list[asyncio.Queue[Message]]] = defaultdict(list)
        self._hooks: list[HookFn] = []
        self._lock = asyncio.Lock()
        self._closed = False

    # ── publish / subscribe ──────────────────────────────────────────────
    async def publish(self, topic: str, msg: Message, *, source_module: str) -> None:
        if self._closed:
            return
        if msg.sender in INGRESS_SENDERS and source_module != SOURCE_INGRESS:
            raise IngressImpersonation(
                f"module {source_module!r} attempted to publish as {msg.sender!r}"
            )
        async with self._lock:
            queues = list(self._subs.get(topic, []))
            hooks = list(self._hooks)
        for q in queues:
            await q.put(msg)
        # global hooks (e.g. logging) see every publish on every topic.
        for hook in hooks:
            try:
                await hook(topic, msg)
            except Exception:  # noqa: BLE001
                log.exception("bus_hook_failed", topic=topic, msg_id=str(msg.msg_id))

    async def subscribe(self, topic: str, *, maxsize: int = 0) -> AsyncIterator[Message]:
        """Async iterator yielding messages on the given topic.

        Caller is responsible for ending iteration (e.g. via `async for ... if cond: break`)
        or wrapping in `subscription` for guaranteed cleanup.
        """
        q: asyncio.Queue[Message] = asyncio.Queue(maxsize=maxsize)
        async with self._lock:
            self._subs[topic].append(q)
        try:
            while True:
                msg = await q.get()
                yield msg
        finally:
            async with self._lock:
                if q in self._subs.get(topic, []):
                    self._subs[topic].remove(q)

    @asynccontextmanager
    async def subscription(self, topic: str, *, maxsize: int = 0):
        """Context-managed subscription that guarantees queue cleanup."""
        q: asyncio.Queue[Message] = asyncio.Queue(maxsize=maxsize)
        async with self._lock:
            self._subs[topic].append(q)
        try:
            yield q
        finally:
            async with self._lock:
                if q in self._subs.get(topic, []):
                    self._subs[topic].remove(q)

    def add_hook(self, hook: HookFn) -> None:
        """Register a global hook called for every publish() invocation."""
        self._hooks.append(hook)

    def remove_hook(self, hook: HookFn) -> None:
        if hook in self._hooks:
            self._hooks.remove(hook)

    # ── lifecycle ────────────────────────────────────────────────────────
    async def close(self) -> None:
        self._closed = True
        async with self._lock:
            self._subs.clear()
            self._hooks.clear()

    # ── helpers ──────────────────────────────────────────────────────────
    async def request_response(
        self,
        publish_topic: str,
        msg: Message,
        response_topic: str,
        *,
        source_module: str,
        match_msg_id_in_response_to: bool = True,
        timeout: float = 30.0,
    ) -> Optional[Message]:
        """Publish `msg` on `publish_topic` and wait for a reply on `response_topic`.

        Matches by `in_response_to == msg.msg_id` if `match_msg_id_in_response_to=True`.
        Returns None on timeout.
        """
        async with self.subscription(response_topic) as q:
            await self.publish(publish_topic, msg, source_module=source_module)
            try:
                while True:
                    reply: Message = await asyncio.wait_for(q.get(), timeout=timeout)
                    if (
                        not match_msg_id_in_response_to
                        or reply.in_response_to == msg.msg_id
                    ):
                        return reply
            except asyncio.TimeoutError:
                return None


# ── BusEvent helpers (used by ingress sse + report generator) ───────────────
def wrap_event(msg: Message, verdicts: Optional[list] = None) -> BusEvent:
    return BusEvent(message=msg, verdicts=verdicts or [])
