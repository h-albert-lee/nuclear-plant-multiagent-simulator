"""LLM allowlist forwarding proxy.

Sole purpose: take `/v1/{provider}/{...path}` requests from the simulator,
verify path against the per-provider allowlist, inject API key from env,
forward to the real provider, and return the response. Keys never reach the
simulator container.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import httpx
import yaml
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse


def _load_allowlist() -> dict[str, dict[str, Any]]:
    path = Path("/app/llm_proxy/allowlist.yaml")
    if not path.exists():
        path = Path(__file__).parent / "allowlist.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data.get("providers", {})


PROVIDERS = _load_allowlist()


def _path_allowed(allowed_patterns: list[str], path: str) -> bool:
    for p in allowed_patterns:
        if p.startswith("^") or p.endswith("$") or any(c in p for c in r".+*?[]()|"):
            if re.fullmatch(p, path):
                return True
        else:
            if path == p:
                return True
    return False


app = FastAPI(title="nuclear-redteam-sim LLM proxy", version="0.1.0")


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "providers": ",".join(PROVIDERS.keys())}


@app.api_route("/v1/{provider}/{path:path}", methods=["GET", "POST"])
async def forward(provider: str, path: str, request: Request) -> Response:
    provider_cfg = PROVIDERS.get(provider)
    if provider_cfg is None:
        raise HTTPException(status_code=404, detail=f"unknown-provider:{provider}")
    full_path = "/" + path
    if not _path_allowed(provider_cfg.get("allowed_paths", []), full_path):
        raise HTTPException(status_code=403, detail=f"path-not-allowed:{full_path}")

    headers = {k: v for k, v in request.headers.items()
               if k.lower() not in ("host", "content-length", "authorization", "x-api-key")}
    api_key = os.environ.get(provider_cfg.get("auth_env", ""), "")
    if not api_key:
        raise HTTPException(status_code=502, detail=f"missing-key:{provider_cfg.get('auth_env')}")
    auth_header = provider_cfg.get("auth_header")
    auth_query = provider_cfg.get("auth_query_param")
    if auth_header:
        prefix = provider_cfg.get("auth_prefix", "")
        headers[auth_header] = f"{prefix}{api_key}"
    for k, v in provider_cfg.get("extra_headers", {}).items():
        headers[k] = v

    url = provider_cfg["base_url"].rstrip("/") + full_path
    params = dict(request.query_params)
    if auth_query:
        params[auth_query] = api_key

    body = await request.body()
    async with httpx.AsyncClient(timeout=120.0) as client:
        upstream = await client.request(
            request.method, url, headers=headers, params=params, content=body,
        )
    # Pass through status + content. Strip hop-by-hop headers.
    resp_headers = {
        k: v for k, v in upstream.headers.items()
        if k.lower() not in ("content-encoding", "transfer-encoding", "connection")
    }
    return Response(content=upstream.content, status_code=upstream.status_code,
                    headers=resp_headers, media_type=upstream.headers.get("content-type"))
