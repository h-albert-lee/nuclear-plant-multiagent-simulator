"""FastAPI app — ingress + attack session + SSE."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

import structlog
from fastapi import Body, FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sse_starlette.sse import EventSourceResponse

from src.config_models import AttackInterfaceConfig
from src.enums import AttackVisibility, CHANNELS, Urgency, RecipientRole
from src.ingress.session import Session, SessionRegistry
from src.ingress.summary import build_situation_summary, diff_plant_state
from src.message_bus import (
    SOURCE_INGRESS,
    TOPIC_AGENT_OUTBOUND,
    MessageBus,
    channel_inbox,
)
from src.message_models import GuardrailVerdict, Message, Provenance

log = structlog.get_logger(__name__)


class IngressRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    payload: str
    claimed_sender: Optional[str] = None
    signature: Optional[str] = None
    urgency: Urgency = "routine"
    recipient: RecipientRole = "SRO"


class IngressResponse(BaseModel):
    msg_id: UUID
    received_at_tick: int
    delivered_to_bus: bool
    guardrail_decisions: list[dict] = Field(default_factory=list)


class SessionStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    attacker_id: Optional[str] = None
    max_turns: int = 10
    initial_observation_requested: bool = True


class SessionStartResponse(BaseModel):
    session_id: UUID
    started_at_tick: int
    visibility: AttackVisibility
    max_turns: int
    initial_summary: dict


class SessionTurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    channel: str
    message: IngressRequest


class SessionTurnResponse(BaseModel):
    msg_id: UUID
    received_at_tick: int
    delivered_to_bus: bool
    turn: int
    turns_remaining: int
    situation_summary: dict
    session_ended: bool


class SessionEndResponse(BaseModel):
    session_id: UUID
    ended_at_tick: int
    final_summary: dict
    turns_used: int


class RunInfoResponse(BaseModel):
    run_id: str
    current_tick: int
    status: str


class IngressAppContext:
    """Stateful shared context for the FastAPI app. Plant state, current tick,
    and the message bus are all owned by orchestrator and passed in by reference.
    """

    def __init__(
        self,
        *,
        run_id: str,
        cfg: AttackInterfaceConfig,
        bus: MessageBus,
        plant_state_getter,
        get_current_tick,
        sessions: SessionRegistry,
        logging_backend: Optional[Any] = None,
    ) -> None:
        self.run_id = run_id
        self.cfg = cfg
        self.bus = bus
        self.plant_state_getter = plant_state_getter
        self.get_current_tick = get_current_tick
        self.sessions = sessions
        self.logging_backend = logging_backend
        self.status = "running"
        self.stopped = asyncio.Event()
        # SSE recent buffers (per session and global trace)
        self.global_event_buffer: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=10000)
        # for session SituationSummary delta tracking we keep per-session buffers
        self.session_buffers: dict[UUID, list[dict[str, Any]]] = {}
        self.last_plant_snapshot_per_session: dict[UUID, Any] = {}

    async def request_stop(self) -> None:
        self.status = "stopped"
        self.stopped.set()


def build_app(ctx: IngressAppContext) -> FastAPI:
    app = FastAPI(title="nuclear-redteam-sim ingress", version="0.1.0")

    # ── helpers ──────────────────────────────────────────────────────────
    def visibility_white() -> bool:
        return ctx.cfg.visibility == "white"

    async def deliver_message_to_bus(channel: str, body: IngressRequest) -> tuple[UUID, int]:
        if channel not in CHANNELS:
            raise HTTPException(status_code=404, detail=f"unknown channel {channel}")
        if channel not in ctx.cfg.enabled_channels:
            raise HTTPException(status_code=403, detail=f"channel disabled {channel}")
        tick = ctx.get_current_tick()
        msg = Message(
            tick=tick,
            sender=channel,  # type: ignore[arg-type]
            recipient=body.recipient,
            type="REPORT",  # raw ingress is informational; agent decides what to do
            payload=body.payload,
            urgency=body.urgency,
            provenance=Provenance(
                claimed_sender=body.claimed_sender,
                signature=body.signature,
                verified="unverified",
            ),
        )
        await ctx.bus.publish(channel_inbox(channel), msg, source_module=SOURCE_INGRESS)
        if ctx.logging_backend is not None:
            await ctx.logging_backend.record_ingress(
                channel=channel,
                raw_request=body.model_dump(mode="json"),
                msg_id=str(msg.msg_id),
                accepted=True,
            )
        return msg.msg_id, tick

    # ── raw ingress (stateless) ──────────────────────────────────────────
    @app.post("/ingress/{channel}/message", response_model=IngressResponse)
    async def post_ingress(channel: str, body: IngressRequest) -> IngressResponse:
        msg_id, tick = await deliver_message_to_bus(channel, body)
        return IngressResponse(msg_id=msg_id, received_at_tick=tick, delivered_to_bus=True)

    # ── run-level ────────────────────────────────────────────────────────
    @app.get("/run/info", response_model=RunInfoResponse)
    async def run_info() -> RunInfoResponse:
        return RunInfoResponse(
            run_id=ctx.run_id, current_tick=ctx.get_current_tick(), status=ctx.status,
        )

    @app.get("/run/state")
    async def run_state() -> dict:
        if not visibility_white():
            raise HTTPException(status_code=404, detail="state-not-exposed-in-blackbox")
        return ctx.plant_state_getter().model_dump(mode="json")

    @app.get("/run/trace")
    async def run_trace(since_tick: int = 0) -> dict:
        if not visibility_white():
            raise HTTPException(status_code=404, detail="trace-not-exposed-in-blackbox")
        # polling: drain recent events buffer up to a cap
        events: list[dict[str, Any]] = []
        while not ctx.global_event_buffer.empty() and len(events) < 5000:
            ev = ctx.global_event_buffer.get_nowait()
            if ev.get("tick", 0) >= since_tick:
                events.append(ev)
        return {"events": events}

    @app.get("/run/trace/stream")
    async def run_trace_stream(request: Request):
        if not visibility_white():
            raise HTTPException(status_code=404, detail="trace-not-exposed-in-blackbox")

        async def event_generator():
            while True:
                if await request.is_disconnected():
                    break
                try:
                    ev = await asyncio.wait_for(ctx.global_event_buffer.get(), timeout=1.0)
                    yield {"event": ev.get("event", "message"), "data": json.dumps(ev, default=str)}
                except asyncio.TimeoutError:
                    yield {"event": "heartbeat", "data": json.dumps({"tick": ctx.get_current_tick()})}
                if ctx.stopped.is_set():
                    yield {"event": "run_ended", "data": json.dumps({"tick": ctx.get_current_tick()})}
                    break

        return EventSourceResponse(event_generator())

    @app.post("/run/stop")
    async def run_stop() -> dict:
        await ctx.request_stop()
        return {"stopped": True}

    @app.post("/run/reconfigure")
    async def run_reconfigure(body: dict = Body(default_factory=dict)) -> dict:
        orch = getattr(ctx, "orchestrator", None)
        if orch is None:
            raise HTTPException(status_code=503, detail="orchestrator-not-attached")
        return await orch.reconfigure(
            guardrails_enabled=body.get("guardrails_enabled"),
            sta_mode=body.get("sta_mode"),
            scenario=body.get("scenario"),
        )

    # ── attack sessions ──────────────────────────────────────────────────
    @app.post("/attack/session/start", response_model=SessionStartResponse)
    async def session_start(body: SessionStartRequest) -> SessionStartResponse:
        tick = ctx.get_current_tick()
        sess = await ctx.sessions.start(body.attacker_id, tick)
        if sess is None:
            raise HTTPException(status_code=409, detail="max-concurrent-sessions-reached")
        plant = ctx.plant_state_getter()
        ctx.last_plant_snapshot_per_session[sess.session_id] = plant.snapshot()
        initial = build_situation_summary(
            at_tick=tick,
            turns_since_last_summary=0,
            visibility=ctx.cfg.visibility,
            plant=plant,
            plant_state_delta=None,
            last_message_delivered=None,
            last_message_blocked_by_verdict=None,
            triggered_messages=[],
            bus_messages_since=[],
            guardrail_verdicts_since=[],
            mock_human_responses_since=[],
            blackbox_payload_excerpt_chars=ctx.cfg.session.blackbox_payload_excerpt_chars,
        )
        if ctx.logging_backend is not None:
            await ctx.logging_backend.record_session({
                "tick": tick, "session_id": str(sess.session_id),
                "event": "start", "attacker_id": body.attacker_id,
                "max_turns": sess.max_turns, "visibility": ctx.cfg.visibility,
                "initial_summary": initial,
            })
        return SessionStartResponse(
            session_id=sess.session_id, started_at_tick=tick,
            visibility=ctx.cfg.visibility, max_turns=sess.max_turns,
            initial_summary=initial,
        )

    @app.post("/attack/session/{session_id}/turn", response_model=SessionTurnResponse)
    async def session_turn(session_id: UUID, body: SessionTurnRequest) -> SessionTurnResponse:
        sess = await ctx.sessions.get(session_id)
        if sess is None:
            raise HTTPException(status_code=404, detail="session-not-found")
        if sess.ended:
            raise HTTPException(status_code=409, detail=f"session-ended:{sess.end_reason}")
        if sess.turns_used >= sess.max_turns:
            await ctx.sessions.end(sess.session_id, "max_turns_reached", ctx.get_current_tick())
            raise HTTPException(status_code=409, detail="max-turns-reached")

        msg_id, tick = await deliver_message_to_bus(body.channel, body.message)
        await ctx.sessions.touch(sess.session_id)
        sess.turns_used += 1
        sess.delivered_message_ids.append(msg_id)
        sess.channels_used.add(body.channel)

        # build summary using current plant + (white-box) delta since last summary
        plant = ctx.plant_state_getter()
        prev_snapshot = ctx.last_plant_snapshot_per_session.get(sess.session_id)
        delta = diff_plant_state(prev_snapshot, plant) if (prev_snapshot is not None and visibility_white()) else None
        ctx.last_plant_snapshot_per_session[sess.session_id] = plant.snapshot()

        # session_buffers stores events between summary calls
        events_since = ctx.session_buffers.pop(sess.session_id, [])
        triggered_msgs: list[Message] = []
        guardrail_decisions: list[dict[str, Any]] = []
        approvals: list[dict[str, Any]] = []
        for ev in events_since:
            if ev.get("event") == "message":
                m = Message.model_validate(ev["msg"])
                triggered_msgs.append(m)
            elif ev.get("event") == "guardrail":
                guardrail_decisions.append(ev)
            elif ev.get("event") == "approval":
                approvals.append(ev)
        # also reset per-session plant snapshot anchor
        sess.last_summary_at_tick = tick

        summary = build_situation_summary(
            at_tick=tick,
            turns_since_last_summary=1,
            visibility=ctx.cfg.visibility,
            plant=plant,
            plant_state_delta=delta,
            last_message_delivered=True,
            last_message_blocked_by_verdict=None,
            triggered_messages=triggered_msgs,
            bus_messages_since=triggered_msgs,
            guardrail_verdicts_since=guardrail_decisions,
            mock_human_responses_since=approvals,
            blackbox_payload_excerpt_chars=ctx.cfg.session.blackbox_payload_excerpt_chars,
        )
        ended = sess.turns_used >= sess.max_turns
        if ended:
            await ctx.sessions.end(sess.session_id, "max_turns_reached", tick)

        if ctx.logging_backend is not None:
            await ctx.logging_backend.record_session({
                "tick": tick, "session_id": str(sess.session_id),
                "event": "turn", "turn": sess.turns_used, "channel": body.channel,
                "request": body.message.model_dump(mode="json"),
                "msg_id": str(msg_id),
                "situation_summary_given": summary,
            })
        return SessionTurnResponse(
            msg_id=msg_id, received_at_tick=tick, delivered_to_bus=True,
            turn=sess.turns_used, turns_remaining=max(0, sess.max_turns - sess.turns_used),
            situation_summary=summary, session_ended=ended,
        )

    @app.post("/attack/session/{session_id}/end", response_model=SessionEndResponse)
    async def session_end(session_id: UUID) -> SessionEndResponse:
        sess = await ctx.sessions.get(session_id)
        if sess is None:
            raise HTTPException(status_code=404, detail="session-not-found")
        tick = ctx.get_current_tick()
        if not sess.ended:
            await ctx.sessions.end(sess.session_id, "self_ended", tick)
        plant = ctx.plant_state_getter()
        final = build_situation_summary(
            at_tick=tick, turns_since_last_summary=0, visibility=ctx.cfg.visibility,
            plant=plant, plant_state_delta=None,
            last_message_delivered=None, last_message_blocked_by_verdict=None,
            triggered_messages=[], bus_messages_since=[],
            guardrail_verdicts_since=[], mock_human_responses_since=[],
            blackbox_payload_excerpt_chars=ctx.cfg.session.blackbox_payload_excerpt_chars,
        )
        if ctx.logging_backend is not None:
            await ctx.logging_backend.record_session({
                "tick": tick, "session_id": str(sess.session_id),
                "event": "end", "reason": sess.end_reason or "self_ended",
                "turns_used": sess.turns_used, "final_summary": final,
            })
        return SessionEndResponse(
            session_id=sess.session_id, ended_at_tick=tick,
            final_summary=final, turns_used=sess.turns_used,
        )

    @app.get("/attack/session/{session_id}/stream")
    async def session_stream(session_id: UUID, request: Request):
        sess = await ctx.sessions.get(session_id)
        if sess is None:
            raise HTTPException(status_code=404, detail="session-not-found")

        async def event_generator():
            while True:
                if await request.is_disconnected() or sess.ended:
                    break
                # drain events for this session (best-effort: SSE reuses global buffer
                # since per-session delta tracking is also done in session_buffers).
                buf = ctx.session_buffers.get(session_id, [])
                if buf:
                    ctx.session_buffers[session_id] = []
                    for ev in buf:
                        if ctx.cfg.visibility == "black" and ev.get("event") in ("plant_state",):
                            continue
                        yield {"event": ev.get("event", "message"), "data": json.dumps(ev, default=str)}
                else:
                    await asyncio.sleep(0.5)
                    yield {"event": "heartbeat", "data": json.dumps({"tick": ctx.get_current_tick()})}
                if ctx.stopped.is_set():
                    yield {"event": "run_ended", "data": json.dumps({"tick": ctx.get_current_tick()})}
                    break

        return EventSourceResponse(event_generator())

    return app
