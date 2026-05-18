"""Attack session lifecycle."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from src.config_models import SessionConfig
from src.ingress.session import SessionRegistry


async def test_concurrent_session_limit():
    reg = SessionRegistry(SessionConfig(max_concurrent_sessions=1, max_turns=10))
    a = await reg.start(attacker_id="a", at_tick=1)
    b = await reg.start(attacker_id="b", at_tick=1)
    assert a is not None
    assert b is None


async def test_max_turns_terminates():
    reg = SessionRegistry(SessionConfig(max_concurrent_sessions=2, max_turns=3))
    s = await reg.start("x", at_tick=1)
    assert s is not None
    s.turns_used = 3
    # Caller (the API handler) is responsible for ending — here we model that:
    await reg.end(s.session_id, "max_turns_reached", at_tick=2)
    sess = await reg.get(s.session_id)
    assert sess and sess.ended and sess.end_reason == "max_turns_reached"


async def test_idle_sweep():
    reg = SessionRegistry(SessionConfig(idle_timeout_seconds=0, max_turns=10))
    s = await reg.start("x", at_tick=1)
    assert s is not None
    # make sess look "old"
    s.last_activity = datetime(2000, 1, 1, tzinfo=timezone.utc)
    swept = await reg.sweep_idle(datetime.now(timezone.utc), at_tick=2)
    assert any(x.session_id == s.session_id for x in swept)
