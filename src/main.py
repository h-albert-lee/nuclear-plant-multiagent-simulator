"""CLI entrypoint — `python -m src.main --config configs/config.yaml`."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

import structlog

from src.config_models import AppConfig
from src.orchestrator import Orchestrator


def _setup_logging(level: str) -> None:
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO),
                        stream=sys.stdout, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.dev.ConsoleRenderer(colors=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level.upper(), logging.INFO)),
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="nrt-sim", description="Nuclear red-team simulator")
    p.add_argument("--config", required=True, help="Path to YAML config")
    p.add_argument("--scenario", default=None, help="Override scenario file")
    p.add_argument("--max-ticks", type=int, default=None, help="Override max ticks")
    p.add_argument("--mock-llm", action="store_true", help="Force all agents to use mock provider")
    p.add_argument("--log-level", default=os.environ.get("LOG_LEVEL", "INFO"))
    return p.parse_args(argv)


def cli_entry() -> None:
    args = parse_args()
    _setup_logging(args.log_level)
    cfg = AppConfig.load(args.config)
    orchestrator = Orchestrator(
        cfg,
        override_scenario=args.scenario,
        override_max_ticks=args.max_ticks,
        force_mock_llm=args.mock_llm,
    )
    try:
        asyncio.run(orchestrator.run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    cli_entry()
