"""LLM client wrapper — routes all calls through llm_proxy.

Supports anthropic / openai / google / dashscope providers. Also includes a
`mock` provider that returns canned structured JSON output so the simulator
can run end-to-end without LLM costs / network.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from dataclasses import dataclass
from typing import Any

import httpx
import structlog

from src.enums import LLMProvider

log = structlog.get_logger(__name__)


@dataclass
class LLMCall:
    role: str
    model: str
    provider: LLMProvider
    temperature: float
    max_tokens: int
    input_prompt: str
    output_raw: str
    tokens_in: int = 0
    tokens_out: int = 0

    @property
    def prompt_sha256(self) -> str:
        return hashlib.sha256(self.input_prompt.encode("utf-8")).hexdigest()


class LLMClient:
    """Async wrapper. All providers proxied through llm_proxy URL except mock."""

    def __init__(
        self,
        *,
        proxy_url: str,
        provider: LLMProvider,
        model: str,
        temperature: float,
        max_tokens: int,
        timeout: float = 60.0,
    ) -> None:
        self.proxy_url = proxy_url.rstrip("/")
        self.provider = provider
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "LLMClient":
        if self.provider != "mock":
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ── main entry ───────────────────────────────────────────────────────
    async def complete(self, system_prompt: str, user_prompt: str) -> LLMCall:
        full_input = f"<<SYSTEM>>\n{system_prompt}\n<<USER>>\n{user_prompt}"
        if self.provider == "mock":
            return self._mock_call(full_input, user_prompt)
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        try:
            if self.provider == "anthropic":
                return await self._anthropic(system_prompt, user_prompt, full_input)
            if self.provider == "openai":
                return await self._openai(system_prompt, user_prompt, full_input)
            if self.provider == "google":
                return await self._google(system_prompt, user_prompt, full_input)
            if self.provider == "dashscope":
                return await self._dashscope(system_prompt, user_prompt, full_input)
        except Exception as exc:  # noqa: BLE001
            log.exception("llm_call_failed", provider=self.provider, model=self.model, error=str(exc))
            # Fall through to mock so the sim doesn't crash on LLM outage.
            return self._mock_call(full_input, user_prompt, fallback_reason=f"error:{type(exc).__name__}")
        return self._mock_call(full_input, user_prompt, fallback_reason="unknown-provider")

    # ── providers ────────────────────────────────────────────────────────
    async def _anthropic(self, system: str, user: str, full: str) -> LLMCall:
        url = f"{self.proxy_url}/v1/anthropic/v1/messages"
        body = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        assert self._client is not None
        r = await self._client.post(url, json=body)
        r.raise_for_status()
        data = r.json()
        content_parts = data.get("content", [])
        text = "".join(p.get("text", "") for p in content_parts if p.get("type") == "text")
        usage = data.get("usage", {})
        return LLMCall(
            role="", model=self.model, provider="anthropic",
            temperature=self.temperature, max_tokens=self.max_tokens,
            input_prompt=full, output_raw=text,
            tokens_in=usage.get("input_tokens", 0),
            tokens_out=usage.get("output_tokens", 0),
        )

    async def _openai(self, system: str, user: str, full: str) -> LLMCall:
        url = f"{self.proxy_url}/v1/openai/v1/chat/completions"
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        # gpt-5.x and newer require `max_completion_tokens`; older models accept `max_tokens`.
        # We send the new param universally — recent gpt-4o variants also accept it.
        body["max_completion_tokens"] = self.max_tokens
        # gpt-5.x reasoning models reject custom temperature; only set when supported.
        if not self.model.startswith("gpt-5"):
            body["temperature"] = self.temperature
        assert self._client is not None
        r = await self._client.post(url, json=body)
        r.raise_for_status()
        data = r.json()
        choice = data["choices"][0]
        text = choice["message"]["content"]
        usage = data.get("usage", {})
        return LLMCall(
            role="", model=self.model, provider="openai",
            temperature=self.temperature, max_tokens=self.max_tokens,
            input_prompt=full, output_raw=text,
            tokens_in=usage.get("prompt_tokens", 0),
            tokens_out=usage.get("completion_tokens", 0),
        )

    async def _google(self, system: str, user: str, full: str) -> LLMCall:
        url = f"{self.proxy_url}/v1/google/v1beta/models/{self.model}:generateContent"
        body = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"parts": [{"text": user}]}],
            "generationConfig": {
                "temperature": self.temperature,
                "maxOutputTokens": self.max_tokens,
            },
        }
        assert self._client is not None
        r = await self._client.post(url, json=body)
        r.raise_for_status()
        data = r.json()
        text = ""
        for cand in data.get("candidates", []):
            for part in cand.get("content", {}).get("parts", []):
                text += part.get("text", "")
        return LLMCall(
            role="", model=self.model, provider="google",
            temperature=self.temperature, max_tokens=self.max_tokens,
            input_prompt=full, output_raw=text,
        )

    async def _dashscope(self, system: str, user: str, full: str) -> LLMCall:
        url = f"{self.proxy_url}/v1/dashscope/api/v1/services/aigc/text-generation/generation"
        body = {
            "model": self.model,
            "input": {
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ]
            },
            "parameters": {
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                "result_format": "message",
            },
        }
        assert self._client is not None
        r = await self._client.post(url, json=body)
        r.raise_for_status()
        data = r.json()
        out = data.get("output", {})
        choices = out.get("choices") or []
        text = ""
        if choices:
            text = choices[0].get("message", {}).get("content", "")
        else:
            text = out.get("text", "")
        return LLMCall(
            role="", model=self.model, provider="dashscope",
            temperature=self.temperature, max_tokens=self.max_tokens,
            input_prompt=full, output_raw=text,
        )

    # ── mock ─────────────────────────────────────────────────────────────
    def _mock_call(self, full_input: str, user_prompt: str, fallback_reason: str = "mock") -> LLMCall:
        """Returns a deterministic, role-aware JSON message envelope.

        Designed so the orchestrator can verify end-to-end flow without LLMs.
        The agent base parses this output via parse_messages().
        """
        # decide role from system_prompt hint
        role_match = re.search(r"You are the\s+(\w+)", full_input)
        role = role_match.group(1) if role_match else "RO"

        # Choose a sensible no-op message: REPORT on current state.
        out: list[dict[str, Any]] = []
        if "alarm is active" in user_prompt.lower() or "scram" in user_prompt.lower():
            out.append({
                "type": "ESCALATE",
                "recipient": "Console",
                "payload": "Alarm review requested",
                "urgency": "prompt",
            })
        else:
            out.append({
                "type": "REPORT",
                "recipient": "SRO" if role != "SRO" else "broadcast",
                "payload": f"{role} routine status report.",
                "urgency": "routine",
            })
        text = json.dumps({"messages": out})
        return LLMCall(
            role=role, model=self.model, provider="mock",
            temperature=self.temperature, max_tokens=self.max_tokens,
            input_prompt=full_input, output_raw=text, tokens_in=0, tokens_out=0,
        )
