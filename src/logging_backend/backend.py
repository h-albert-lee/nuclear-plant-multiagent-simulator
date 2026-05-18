"""Logging backend — writes 10 JSONL files + manifest."""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import structlog

from src.agents.llm_client import LLMCall
from src.config_models import LoggingConfig
from src.logging_backend.manifest import Manifest, finalize_manifest
from src.message_bus import MessageBus
from src.message_models import GuardrailVerdict, Message
from src.plant_state import PlantState

log = structlog.get_logger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JsonlWriter:
    def __init__(self, path: Path, *, fsync_each_line: bool = False) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._fp = open(path, "a", buffering=1, encoding="utf-8")  # line-buffered
        self._fsync = fsync_each_line
        self._lock = asyncio.Lock()

    async def write(self, obj: dict[str, Any]) -> None:
        line = json.dumps(obj, default=str, ensure_ascii=False)
        async with self._lock:
            self._fp.write(line + "\n")
            if self._fsync:
                self._fp.flush()
                os.fsync(self._fp.fileno())

    def close(self) -> None:
        try:
            self._fp.flush()
            os.fsync(self._fp.fileno())
        except OSError:
            pass
        self._fp.close()


class LoggingBackend:
    """Owns the runs/{run_id}/ directory and all JSONL writers.

    Wire `bus.add_hook(self.bus_hook)` so every published message lands in
    messages.jsonl. Other writers are invoked via dedicated record_*() methods.
    """

    def __init__(self, run_id: str, run_dir: Path, cfg: LoggingConfig, app_config_snapshot: dict[str, Any]) -> None:
        self.run_id = run_id
        self.run_dir = run_dir
        self.cfg = cfg
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.config_path = self.run_dir / "config.json"
        self.config_path.write_text(json.dumps(app_config_snapshot, indent=2, default=str), encoding="utf-8")
        self._writers: dict[str, JsonlWriter] = {}
        if cfg.artifacts.messages:
            self._writers["messages"] = JsonlWriter(self.run_dir / "messages.jsonl", fsync_each_line=cfg.fsync_each_line)
        if cfg.artifacts.guardrail:
            self._writers["guardrail"] = JsonlWriter(self.run_dir / "guardrail.jsonl", fsync_each_line=cfg.fsync_each_line)
        if cfg.artifacts.plant_state:
            self._writers["plant_state"] = JsonlWriter(self.run_dir / "plant_state.jsonl", fsync_each_line=cfg.fsync_each_line)
        if cfg.artifacts.ingress:
            self._writers["ingress"] = JsonlWriter(self.run_dir / "ingress.jsonl", fsync_each_line=cfg.fsync_each_line)
        if cfg.artifacts.approvals:
            self._writers["approvals"] = JsonlWriter(self.run_dir / "approvals.jsonl", fsync_each_line=cfg.fsync_each_line)
        if cfg.artifacts.attack_sessions:
            self._writers["attack_sessions"] = JsonlWriter(self.run_dir / "attack_sessions.jsonl", fsync_each_line=cfg.fsync_each_line)
        if cfg.artifacts.agent_thoughts:
            self._writers["agent_thoughts"] = JsonlWriter(self.run_dir / "agent_thoughts.jsonl", fsync_each_line=cfg.fsync_each_line)
            self.prompt_dir = self.run_dir / "agent_thoughts_prompts"
            self.prompt_dir.mkdir(parents=True, exist_ok=True)
        if cfg.artifacts.safety_function_timeline:
            self._writers["safety_function_timeline"] = JsonlWriter(
                self.run_dir / "safety_function_timeline.jsonl",
                fsync_each_line=cfg.fsync_each_line,
            )

    # ── bus hook ─────────────────────────────────────────────────────────
    async def bus_hook(self, topic: str, msg: Message) -> None:
        w = self._writers.get("messages")
        if w is None:
            return
        await w.write({
            "ts": _now(),
            "tick": msg.tick,
            "topic": topic,
            "msg": msg.model_dump(mode="json"),
        })

    # ── dedicated recorders ──────────────────────────────────────────────
    async def record_guardrail(self, tick: int, msg_id: str, verdicts: list[GuardrailVerdict]) -> None:
        w = self._writers.get("guardrail")
        if w is None:
            return
        for v in verdicts:
            await w.write({
                "ts": _now(),
                "tick": tick,
                "msg_id": msg_id,
                "guardrail_id": v.guardrail_id,
                "decision": v.decision,
                "reason": v.reason,
                "block_category": v.block_category,
            })

    async def record_plant_state(self, state: PlantState) -> None:
        w = self._writers.get("plant_state")
        if w is None:
            return
        await w.write({
            "ts": _now(),
            "tick": state.tick,
            "state": state.model_dump(mode="json"),
        })

    async def record_ingress(self, channel: str, raw_request: dict[str, Any], msg_id: str, accepted: bool, reason: str = "") -> None:
        w = self._writers.get("ingress")
        if w is None:
            return
        await w.write({
            "ts": _now(),
            "channel": channel,
            "raw_request": raw_request,
            "produced_msg_id": msg_id,
            "accepted": accepted,
            "reason": reason,
        })

    async def record_approval(self, payload: dict[str, Any]) -> None:
        w = self._writers.get("approvals")
        if w is None:
            return
        await w.write({"ts": _now(), **payload})

    async def record_session(self, payload: dict[str, Any]) -> None:
        w = self._writers.get("attack_sessions")
        if w is None:
            return
        await w.write({"ts": _now(), **payload})

    async def record_thought(self, role: str, call: LLMCall, parsed_msg_ids: list[str]) -> None:
        w = self._writers.get("agent_thoughts")
        if w is None:
            return
        prompt_sha = call.prompt_sha256
        if self.cfg.agent_thoughts_dedup_prompts:
            prompt_file = getattr(self, "prompt_dir", None)
            if prompt_file is not None:
                target = prompt_file / f"{prompt_sha}.txt"
                if not target.exists():
                    target.write_text(call.input_prompt, encoding="utf-8")
        await w.write({
            "ts": _now(),
            "agent_role": role,
            "llm_model": call.model,
            "provider": call.provider,
            "temperature": call.temperature,
            "input_prompt_sha256": prompt_sha,
            "input_prompt_excerpt": call.input_prompt[:200],
            "output_raw": call.output_raw[:4000],
            "parsed_messages": parsed_msg_ids,
            "tokens_in": call.tokens_in,
            "tokens_out": call.tokens_out,
        })

    async def record_csf_transition(self, tick: int, csf: str, from_state: str, to_state: str, cause_msg_id: Optional[str] = None) -> None:
        w = self._writers.get("safety_function_timeline")
        if w is None:
            return
        await w.write({
            "ts": _now(),
            "tick": tick,
            "csf": csf,
            "from": from_state,
            "to": to_state,
            "cause_msg_id": cause_msg_id,
        })

    # ── lifecycle ────────────────────────────────────────────────────────
    async def finalize(self, run_summary: dict[str, Any]) -> Manifest:
        (self.run_dir / "run_summary.json").write_text(
            json.dumps(run_summary, indent=2, default=str), encoding="utf-8"
        )
        for w in self._writers.values():
            w.close()
        return finalize_manifest(self.run_dir)
