"""Instantiate the 5-role operator team from AppConfig."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from src.agents.base import BaseAgent, load_prompt
from src.agents.llm_client import LLMClient
from src.config_models import AgentsConfig, LLMProxyConfig
from src.enums import OPERATOR_ROLES, STAMode
from src.message_bus import MessageBus

ROLE_PROMPT_FILES = {
    "SRO": "configs/prompts/sro.txt",
    "RO": "configs/prompts/ro.txt",
    "TO": "configs/prompts/to.txt",
    "STA": "configs/prompts/sta.txt",
    "AO": "configs/prompts/ao.txt",
}


def build_team(
    cfg: AgentsConfig,
    proxy: LLMProxyConfig,
    *,
    bus: MessageBus,
    sta_mode: STAMode,
    prompt_root: str | Path = ".",
    thought_sink: Optional[Any] = None,
) -> list[BaseAgent]:
    agents: list[BaseAgent] = []
    role_configs = {
        "SRO": cfg.sro, "RO": cfg.ro, "TO": cfg.to, "STA": cfg.sta, "AO": cfg.ao,
    }
    for role in OPERATOR_ROLES:
        ac = role_configs[role]
        if role == "STA" and sta_mode == "STA-Off":
            continue
        llm = LLMClient(
            proxy_url=proxy.url,
            provider=ac.provider,
            model=ac.model,
            temperature=ac.temperature,
            max_tokens=ac.max_tokens,
            timeout=proxy.timeout_seconds,
        )
        prompt_path = Path(prompt_root) / ROLE_PROMPT_FILES[role]
        system_prompt = load_prompt(prompt_path)
        if ac.extra_prompt_path:
            extra = load_prompt(Path(prompt_root) / ac.extra_prompt_path)
            system_prompt = system_prompt + "\n\n" + extra
        agents.append(BaseAgent(
            role=role,
            config=ac,
            bus=bus,
            llm=llm,
            system_prompt=system_prompt,
            sta_mode=sta_mode,
            thought_sink=thought_sink,
        ))
    return agents
