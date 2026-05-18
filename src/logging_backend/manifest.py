"""Manifest builder/finalizer."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


class Artifact(BaseModel):
    path: str
    kind: str
    schema_version: str = "1.0"
    sha256: Optional[str] = None
    bytes: Optional[int] = None
    line_count: Optional[int] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    description: str = ""


class Manifest(BaseModel):
    run_id: str
    simulator_version: str = "1.2"
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    ended_at: Optional[datetime] = None
    artifacts: list[Artifact] = Field(default_factory=list)


def _sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _line_count(path: Path) -> int:
    n = 0
    with open(path, "rb") as f:
        for _ in f:
            n += 1
    return n


def finalize_manifest(run_dir: Path, *, simulator_version: str = "1.2") -> Manifest:
    """Walk runs/{run_id}/ and produce a finalized manifest.json with checksums."""
    manifest_path = run_dir / "manifest.json"
    if manifest_path.exists():
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest = Manifest.model_validate(data)
    else:
        manifest = Manifest(run_id=run_dir.name, simulator_version=simulator_version)

    by_path: dict[str, Artifact] = {a.path: a for a in manifest.artifacts}

    file_kinds = {
        "config.json": "config",
        "messages.jsonl": "messages",
        "guardrail.jsonl": "guardrail",
        "plant_state.jsonl": "plant_state",
        "ingress.jsonl": "ingress",
        "approvals.jsonl": "approvals",
        "attack_sessions.jsonl": "attack_sessions",
        "agent_thoughts.jsonl": "agent_thoughts",
        "safety_function_timeline.jsonl": "safety_function_timeline",
        "run_summary.json": "run_summary",
        "report.json": "report_json",
        "report.md": "report_md",
    }
    for fname, kind in file_kinds.items():
        fpath = run_dir / fname
        if not fpath.exists():
            continue
        size = fpath.stat().st_size
        sha = _sha256_of_file(fpath)
        line_count = _line_count(fpath) if fname.endswith(".jsonl") else None
        if fname in by_path:
            art = by_path[fname]
            art.sha256 = sha
            art.bytes = size
            art.line_count = line_count
            art.kind = kind
        else:
            manifest.artifacts.append(Artifact(
                path=fname, kind=kind,
                sha256=sha, bytes=size, line_count=line_count,
                description=fname,
            ))

    manifest.ended_at = datetime.now(timezone.utc)
    manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    return manifest
