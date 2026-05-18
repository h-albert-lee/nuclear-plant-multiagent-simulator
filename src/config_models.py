"""Configuration schema."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field

from src.enums import AttackVisibility, LLMProvider, STAMode


class RunConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = "auto"  # "auto" → generate UUID at runtime
    max_ticks: int = 2000
    tick_seconds: int = 30
    scenario: str = "scenarios/normal_baseline.yaml"
    seed: int = 42
    sim_time_scale: float = 0.1
    """Wall-time scale for mock_human latency. 1.0 = real, 0.1 = 10x faster."""


class AgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = "claude-haiku-4-5"
    temperature: float = 0.2
    max_tokens: int = 1024
    provider: LLMProvider = "anthropic"
    mode: Optional[STAMode] = None  # STA-only field
    extra_prompt_path: Optional[str] = None


class AgentsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sro: AgentConfig
    ro: AgentConfig
    to: AgentConfig
    sta: AgentConfig
    ao: AgentConfig


class GuardrailsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: list[str] = Field(default_factory=lambda: ["G2", "G4", "G6", "G7", "G8", "G10"])
    g1_classifier_model: str = "claude-haiku-4-5"
    g1_classifier_provider: LLMProvider = "anthropic"
    g2_policy_table: str = "configs/policy_matrix.yaml"
    g3_approval_window_ticks: int = 3
    g9_rate_cap: int = 5


class SessionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_turns: int = 10
    max_concurrent_sessions: int = 1
    idle_timeout_seconds: int = 600
    blackbox_payload_excerpt_chars: int = 80


class TraceStreamConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    heartbeat_every_ticks: int = 1


class AttackInterfaceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    visibility: AttackVisibility = "black"
    enabled_channels: list[str] = Field(
        default_factory=lambda: ["CH-A", "CH-B", "CH-C", "CH-D"]
    )
    port: int = 8080
    signature_allowlist: dict[str, list[str]] = Field(default_factory=dict)
    session: SessionConfig = Field(default_factory=SessionConfig)
    trace_stream: TraceStreamConfig = Field(default_factory=TraceStreamConfig)


class MockHumanConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_set: str = "configs/mock_human_default.yaml"
    default_deny_timeout_seconds: int = 180


class LoggingArtifactsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    messages: bool = True
    guardrail: bool = True
    plant_state: bool = True
    ingress: bool = True
    approvals: bool = True
    attack_sessions: bool = True
    agent_thoughts: bool = True
    safety_function_timeline: bool = True


class LoggingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    output_dir: str = "runs"
    backends: list[str] = Field(default_factory=lambda: ["jsonl"])
    artifacts: LoggingArtifactsConfig = Field(default_factory=LoggingArtifactsConfig)
    agent_thoughts_dedup_prompts: bool = True
    fsync_each_line: bool = False


class ReportConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    auto_generate_on_run_end: bool = True
    formats: list[str] = Field(default_factory=lambda: ["json", "md"])
    include_full_message_payloads_in_md: bool = False


class LLMProxyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = "http://llm_proxy:9000"
    timeout_seconds: float = 60.0


class AppConfig(BaseModel):
    """Root configuration loaded from configs/config.yaml."""

    model_config = ConfigDict(extra="forbid")

    run: RunConfig = Field(default_factory=RunConfig)
    agents: AgentsConfig
    guardrails: GuardrailsConfig = Field(default_factory=GuardrailsConfig)
    attack_interface: AttackInterfaceConfig = Field(default_factory=AttackInterfaceConfig)
    mock_human: MockHumanConfig = Field(default_factory=MockHumanConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    report: ReportConfig = Field(default_factory=ReportConfig)
    llm_proxy: LLMProxyConfig = Field(default_factory=LLMProxyConfig)

    @classmethod
    def load(cls, path: str | Path) -> "AppConfig":
        with open(path, "rt", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return cls.model_validate(data)


def load_yaml(path: str | Path) -> dict:
    """Generic YAML loader used by scenario / policy_matrix / mock_human rules."""
    with open(path, "rt", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
