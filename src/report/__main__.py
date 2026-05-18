"""CLI: regenerate report from raw JSONL.

  python -m src.report --run-id <id>
  python -m src.report --run-dir runs/<id>/
"""

from __future__ import annotations

import argparse
from pathlib import Path

from src.report.generator import ReportGenerator


def cli_entry() -> None:
    p = argparse.ArgumentParser(prog="nrt-report")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--run-id", help="Resolve under ./runs/{run_id}/")
    g.add_argument("--run-dir", help="Path to a runs/{run_id}/ directory")
    p.add_argument("--formats", default="json,md", help="Comma-separated: json,md")
    args = p.parse_args()
    run_dir = Path(args.run_dir) if args.run_dir else Path("runs") / args.run_id
    if not run_dir.exists():
        raise SystemExit(f"run-dir not found: {run_dir}")
    formats = [f.strip() for f in args.formats.split(",") if f.strip()]
    ReportGenerator(run_dir, formats=formats).write()
    print(f"wrote: {run_dir/'report.json'} {run_dir/'report.md'}")


if __name__ == "__main__":
    cli_entry()
