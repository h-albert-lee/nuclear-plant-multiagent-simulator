"""Attack-session management."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from src.config_models import SessionConfig
from src.message_models import Message


@dataclass
class Session:
    session_id: UUID
    attacker_id: Optional[str]
    started_at_tick: int
    max_turns: int
    turns_used: int = 0
    last_activity: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    ended: bool = False
    end_reason: Optional[str] = None
    end_tick: Optional[int] = None
    channels_used: set[str] = field(default_factory=set)
    delivered_message_ids: list[UUID] = field(default_factory=list)
    # for SituationSummary delta tracking
    last_summary_at_tick: int = 0


class SessionRegistry:
    def __init__(self, cfg: SessionConfig) -> None:
        self.cfg = cfg
        self._sessions: dict[UUID, Session] = {}
        self._lock = asyncio.Lock()

    async def start(self, attacker_id: Optional[str], at_tick: int) -> Optional[Session]:
        async with self._lock:
            active = [s for s in self._sessions.values() if not s.ended]
            if len(active) >= self.cfg.max_concurrent_sessions:
                return None
            sess = Session(
                session_id=uuid4(),
                attacker_id=attacker_id,
                started_at_tick=at_tick,
                last_summary_at_tick=at_tick,
                max_turns=self.cfg.max_turns,
            )
            self._sessions[sess.session_id] = sess
            return sess

    async def get(self, session_id: UUID) -> Optional[Session]:
        async with self._lock:
            return self._sessions.get(session_id)

    async def end(self, session_id: UUID, reason: str, at_tick: int) -> Optional[Session]:
        async with self._lock:
            sess = self._sessions.get(session_id)
            if sess is None or sess.ended:
                return sess
            sess.ended = True
            sess.end_reason = reason
            sess.end_tick = at_tick
            return sess

    async def touch(self, session_id: UUID) -> None:
        async with self._lock:
            sess = self._sessions.get(session_id)
            if sess is not None:
                sess.last_activity = datetime.now(timezone.utc)

    async def all_sessions(self) -> list[Session]:
        async with self._lock:
            return list(self._sessions.values())

    async def sweep_idle(self, now: datetime, at_tick: int) -> list[Session]:
        """End sessions that have exceeded idle_timeout_seconds. Return swept sessions."""
        swept: list[Session] = []
        async with self._lock:
            for sess in self._sessions.values():
                if sess.ended:
                    continue
                idle = (now - sess.last_activity).total_seconds()
                if idle > self.cfg.idle_timeout_seconds:
                    sess.ended = True
                    sess.end_reason = "idle_timeout"
                    sess.end_tick = at_tick
                    swept.append(sess)
        return swept
