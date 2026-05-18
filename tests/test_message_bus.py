"""Message bus: pub/sub + ingress impersonation enforcement."""

from __future__ import annotations

import asyncio

import pytest

from src.message_bus import (
    SOURCE_AGENT_PREFIX,
    SOURCE_INGRESS,
    IngressImpersonation,
    MessageBus,
)
from src.message_models import Message


async def _publish(bus, sender, source):
    msg = Message(tick=1, sender=sender, recipient="broadcast", type="REPORT", payload="x")
    await bus.publish("agent.outbound", msg, source_module=source)
    return msg


async def test_basic_pub_sub():
    bus = MessageBus()
    received: list[Message] = []
    async with bus.subscription("agent.outbound") as q:
        await _publish(bus, "RO", SOURCE_AGENT_PREFIX + "RO")
        msg = await asyncio.wait_for(q.get(), timeout=1.0)
        received.append(msg)
    assert received and received[0].sender == "RO"


async def test_ingress_impersonation_blocked():
    bus = MessageBus()
    with pytest.raises(IngressImpersonation):
        await _publish(bus, "CH-A", SOURCE_AGENT_PREFIX + "RO")


async def test_ingress_module_can_publish_ingress():
    bus = MessageBus()
    await _publish(bus, "CH-A", SOURCE_INGRESS)  # should not raise


async def test_hooks_called_on_publish():
    bus = MessageBus()
    seen: list[tuple[str, str]] = []

    async def hook(topic: str, msg: Message):
        seen.append((topic, msg.payload))

    bus.add_hook(hook)
    await _publish(bus, "SRO", SOURCE_AGENT_PREFIX + "SRO")
    await asyncio.sleep(0)  # let hook run
    assert ("agent.outbound", "x") in seen
