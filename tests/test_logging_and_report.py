"""Logging backend + report generator end-to-end."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.config_models import LoggingArtifactsConfig, LoggingConfig
from src.logging_backend.backend import LoggingBackend
from src.logging_backend.manifest import finalize_manifest
from src.report.generator import ReportGenerator


async def test_logging_writes_files_and_manifest(tmp_path: Path):
    run_dir = tmp_path / "run-1"
    cfg = LoggingConfig(output_dir=str(tmp_path), artifacts=LoggingArtifactsConfig())
    lb = LoggingBackend(run_id="run-1", run_dir=run_dir, cfg=cfg,
                        app_config_snapshot={"hello": "world"})
    await lb.record_ingress("CH-A", {"payload": "x"}, "msg-1", True, "ok")
    await lb.record_approval({"request_msg_id": "m", "response": "approved", "matched_rule_id": "r"})
    await lb.record_session({"event": "start", "session_id": "s1", "tick": 1})
    await lb.record_csf_transition(2, "rcs_integrity", "intact", "degraded")
    summary = {"run_id": "run-1", "end_tick": 5, "termination_reason": "max_ticks",
               "safety_functions_final": {"reactivity_control": "intact",
                                          "core_heat_removal": "intact",
                                          "rcs_heat_removal": "intact",
                                          "rcs_integrity": "degraded",
                                          "containment_integrity": "intact",
                                          "radioactivity_control": "intact"},
               "simulator_version": "1.2"}
    manifest = await lb.finalize(summary)
    assert (run_dir / "manifest.json").exists()
    assert manifest.run_id == "run-1"
    # all expected jsonl files exist
    for fname in ("ingress.jsonl", "approvals.jsonl", "attack_sessions.jsonl", "safety_function_timeline.jsonl"):
        assert (run_dir / fname).exists()
    # report generation from raw data
    report = ReportGenerator(run_dir).write()
    assert report["run_id"] == "run-1"
    assert (run_dir / "report.json").exists()
    assert (run_dir / "report.md").exists()
    # md mentions the CSF transition
    md = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "rcs_integrity" in md
