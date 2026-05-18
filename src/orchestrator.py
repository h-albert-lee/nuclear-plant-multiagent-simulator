"""Orchestrator — run lifecycle, tick loop, component wiring."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

import structlog
import uvicorn

from src.agents.base import BaseAgent
from src.agents.factory import build_team
from src.config_models import AppConfig
from src.enums import OPERATOR_ROLES, STAMode
from src.guardrails.base import GuardrailContext
from src.guardrails.stack import GuardrailStack
from src.ingress.api import IngressAppContext, build_app
from src.ingress.session import SessionRegistry
from src.logging_backend.backend import LoggingBackend
from src.message_bus import (
    SOURCE_GUARDRAIL,
    SOURCE_ORCHESTRATOR,
    SOURCE_PLANT,
    TOPIC_AGENT_OUTBOUND,
    TOPIC_CONSOLE_APPROVAL_REQUEST,
    TOPIC_LOG_TRACE,
    TOPIC_SYSTEM_STATE_UPDATE,
    TOPIC_SYSTEM_TICK,
    MessageBus,
    agent_inbox,
)
from src.message_models import GuardrailVerdict, Message
from src.mock_human.console import MockHumanConsole
from src.plant_simulator import PlantSimulator
from src.plant_state import PlantState

log = structlog.get_logger(__name__)


class Orchestrator:
    def __init__(self, app_cfg: AppConfig, *, override_scenario: Optional[str] = None,
                 override_max_ticks: Optional[int] = None,
                 force_mock_llm: bool = False) -> None:
        self.cfg = app_cfg
        if override_scenario:
            self.cfg.run.scenario = override_scenario
        if override_max_ticks is not None:
            self.cfg.run.max_ticks = override_max_ticks
        if force_mock_llm:
            for role in ("sro", "ro", "to", "sta", "ao"):
                setattr(getattr(self.cfg.agents, role), "provider", "mock")
        self.run_id = self.cfg.run.run_id if self.cfg.run.run_id != "auto" else str(uuid4())
        self.run_dir = Path(self.cfg.logging.output_dir) / self.run_id

        self.bus = MessageBus()
        self.sessions = SessionRegistry(self.cfg.attack_interface.session)
        self.logging = LoggingBackend(
            run_id=self.run_id,
            run_dir=self.run_dir,
            cfg=self.cfg.logging,
            app_config_snapshot=self.cfg.model_dump(mode="json"),
        )
        self.bus.add_hook(self.logging.bus_hook)
        # also feed session buffers from bus
        self.bus.add_hook(self._session_event_hook)

        self.plant = PlantSimulator(self.cfg.run.scenario, seed=self.cfg.run.seed)
        self.sta_mode: STAMode = self.cfg.agents.sta.mode or "STA-B"
        self.guardrails = GuardrailStack(
            self.cfg.guardrails,
            sta_mode=self.sta_mode,
            signature_allowlist=self.cfg.attack_interface.signature_allowlist,
        )
        # persistent context across ticks for approval ledger / sta state
        self._gctx = GuardrailContext(
            tick=0, plant=self.plant.state,
            approval_ledger={}, sta_vetoes={}, sta_overrides={}, rate_counts={},
        )

        self.mock_human = MockHumanConsole(
            self.cfg.mock_human, bus=self.bus,
            sim_time_scale=self.cfg.run.sim_time_scale,
            approval_ledger_hook=self.logging.record_approval,
        )

        self.agents: list[BaseAgent] = build_team(
            self.cfg.agents, self.cfg.llm_proxy,
            bus=self.bus, sta_mode=self.sta_mode,
            prompt_root=".",
            thought_sink=self.logging.record_thought,
        )

        self.ingress_ctx = IngressAppContext(
            run_id=self.run_id,
            cfg=self.cfg.attack_interface,
            bus=self.bus,
            plant_state_getter=lambda: self.plant.state,
            get_current_tick=lambda: self.plant.state.tick,
            sessions=self.sessions,
            logging_backend=self.logging,
        )
        self.ingress_app = build_app(self.ingress_ctx)

        self._termination_reason: str = ""
        self._server: Optional[uvicorn.Server] = None
        self._server_task: Optional[asyncio.Task] = None

    # ── session event hook ───────────────────────────────────────────────
    async def _session_event_hook(self, topic: str, msg: Message) -> None:
        # Stash every published message into per-session buffers for SituationSummary.
        event = {
            "event": "message",
            "tick": msg.tick,
            "topic": topic,
            "msg": msg.model_dump(mode="json"),
        }
        # global SSE buffer (white-box)
        if self.ingress_ctx.global_event_buffer.full():
            try:
                _ = self.ingress_ctx.global_event_buffer.get_nowait()
            except asyncio.QueueEmpty:
                pass
        try:
            self.ingress_ctx.global_event_buffer.put_nowait(event)
        except asyncio.QueueFull:
            pass
        # per-session buffers
        for sess in await self.sessions.all_sessions():
            if sess.ended:
                continue
            self.ingress_ctx.session_buffers.setdefault(sess.session_id, []).append(event)

    # ── server ───────────────────────────────────────────────────────────
    async def _start_server(self) -> None:
        config = uvicorn.Config(
            self.ingress_app,
            host="0.0.0.0",
            port=self.cfg.attack_interface.port,
            log_level="warning",
            access_log=False,
            loop="asyncio",
            lifespan="off",
        )
        self._server = uvicorn.Server(config)
        self._server_task = asyncio.create_task(self._server.serve(), name="ingress-uvicorn")
        # wait until server starts
        for _ in range(50):
            if self._server.started:
                break
            await asyncio.sleep(0.1)

    async def _stop_server(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._server_task is not None:
            try:
                await asyncio.wait_for(self._server_task, timeout=5.0)
            except (asyncio.TimeoutError, Exception):  # noqa: BLE001
                pass

    # ── run lifecycle ────────────────────────────────────────────────────
    async def run(self) -> None:
        log.info("orchestrator_start", run_id=self.run_id, scenario=self.cfg.run.scenario,
                 sta_mode=self.sta_mode, visibility=self.cfg.attack_interface.visibility)
        await self._start_server()
        self.mock_human.start()
        for a in self.agents:
            a.start()
        try:
            await self._tick_loop()
        finally:
            await self._shutdown()
        log.info("orchestrator_done", run_id=self.run_id, termination_reason=self._termination_reason)

    async def _tick_loop(self) -> None:
        max_ticks = self.cfg.run.max_ticks
        tick_seconds = self.cfg.run.tick_seconds
        sim_scale = self.cfg.run.sim_time_scale
        for _ in range(max_ticks):
            if self.ingress_ctx.stopped.is_set():
                self._termination_reason = "external_stop"
                break
            await self._do_tick()
            if self.plant.state.safety_functions.lost_any():
                self._termination_reason = "safety_function_lost"
                break
            await asyncio.sleep(max(0.01, tick_seconds * sim_scale))
        if not self._termination_reason:
            self._termination_reason = "max_ticks"

    async def _do_tick(self) -> None:
        alarm_trans, csf_trans, _scenario_events = self.plant.tick()
        state = self.plant.snapshot()
        # publish state update
        state_msg = Message(
            tick=state.tick, sender="System", recipient="broadcast",
            type="REPORT", payload=state.model_dump_json(),
        )
        await self.bus.publish(TOPIC_SYSTEM_STATE_UPDATE, state_msg, source_module=SOURCE_PLANT)
        # plant_state.jsonl
        await self.logging.record_plant_state(state)
        # CSF transitions
        for csf, fr, to in csf_trans:
            await self.logging.record_csf_transition(state.tick, csf, fr, to)
        # collect outbound messages from agents for a fraction of a wall-second
        outbound = await self._collect_outbound(timeout=max(0.05, self.cfg.run.tick_seconds * self.cfg.run.sim_time_scale * 0.8))
        # update guardrail ctx
        self._gctx.tick = state.tick
        self._gctx.plant = state
        self._gctx.rate_counts = {}
        for msg in outbound:
            await self._route_message(msg)

    async def _collect_outbound(self, *, timeout: float) -> list[Message]:
        msgs: list[Message] = []
        async with self.bus.subscription(TOPIC_AGENT_OUTBOUND) as q:
            try:
                while True:
                    msg = await asyncio.wait_for(q.get(), timeout=timeout)
                    msgs.append(msg)
                    timeout = 0.02  # drain quickly after first
            except asyncio.TimeoutError:
                pass
        return msgs

    async def _route_message(self, msg: Message) -> None:
        final, verdicts = await self.guardrails.process(msg, self._gctx)
        await self.logging.record_guardrail(self._gctx.tick, str(msg.msg_id), verdicts)
        if final is None:
            return
        # APPROVAL_REQUEST → console
        if final.type == "APPROVAL_REQUEST":
            await self.bus.publish(TOPIC_CONSOLE_APPROVAL_REQUEST, final, source_module=SOURCE_GUARDRAIL)
            return
        # ACTION at L3+ requires human approval through console
        if final.type == "ACTION" and final.action_class in ("L3", "L4"):
            approval_req = final.model_copy(update={"type": "APPROVAL_REQUEST"})
            await self.bus.publish(TOPIC_CONSOLE_APPROVAL_REQUEST, approval_req, source_module=SOURCE_GUARDRAIL)
            response = await self._await_response(approval_req.msg_id, timeout=self.cfg.mock_human.default_deny_timeout_seconds * self.cfg.run.sim_time_scale + 5.0)
            if response is None or not response.payload.startswith("approved"):
                # denied — record but don't apply
                return
        # ACTION L1/L2/L2.5 or approved L3+ → apply to plant + fan-out to inbox
        if final.type == "ACTION":
            self.plant.apply_action(final)
        # deliver to recipient inbox
        if final.recipient in OPERATOR_ROLES:
            await self.bus.publish(agent_inbox(final.recipient), final, source_module=SOURCE_ORCHESTRATOR)
        elif final.recipient == "broadcast":
            for role in OPERATOR_ROLES:
                await self.bus.publish(agent_inbox(role), final, source_module=SOURCE_ORCHESTRATOR)

    async def _await_response(self, request_msg_id, *, timeout: float) -> Optional[Message]:
        async with self.bus.subscription("console.approval_response") as q:
            try:
                while True:
                    resp = await asyncio.wait_for(q.get(), timeout=timeout)
                    if resp.in_response_to == request_msg_id:
                        return resp
            except asyncio.TimeoutError:
                return None

    # ── shutdown ─────────────────────────────────────────────────────────
    async def _shutdown(self) -> None:
        await self.mock_human.stop()
        await asyncio.gather(*(a.stop() for a in self.agents), return_exceptions=True)
        for a in self.agents:
            await a.llm.aclose()
        # final session sweep
        tick = self.plant.state.tick
        for sess in await self.sessions.all_sessions():
            if not sess.ended:
                await self.sessions.end(sess.session_id, "run_terminated", tick)
                await self.logging.record_session({
                    "tick": tick, "session_id": str(sess.session_id),
                    "event": "end", "reason": "run_terminated",
                    "turns_used": sess.turns_used,
                })
        run_summary = self._build_run_summary()
        await self.logging.finalize(run_summary)
        await self._stop_server()
        await self.bus.close()
        if self.cfg.report.auto_generate_on_run_end:
            try:
                from src.report.generator import ReportGenerator
                ReportGenerator(self.run_dir, formats=self.cfg.report.formats).write()
            except Exception:  # noqa: BLE001
                log.exception("report_generation_failed")

    def _build_run_summary(self) -> dict[str, Any]:
        s = self.plant.state
        return {
            "run_id": self.run_id,
            "started_at": None,  # filled by manifest
            "ended_at": datetime.now(timezone.utc).isoformat(),
            "start_tick": 0,
            "end_tick": s.tick,
            "termination_reason": self._termination_reason,
            "safety_functions_final": s.safety_functions.model_dump(),
            "simulator_version": "1.2",
        }
