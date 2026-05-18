# Troubleshooting

## Installation and Environment

### `python: command not found`

On macOS, `python3` may exist while `python` does not. Use `.venv/bin/python`
or `python3`:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m src.main --config configs/config.yaml --mock-llm
```

`make install` expects the virtualenv workflow used by this repository. If it
does not create what you need, create `.venv` manually and install with
`.venv/bin/python -m pip install -e ".[dev]"`.

### Pydantic v1 Compatibility Errors

The simulator requires Pydantic v2.

```bash
.venv/bin/python -c "import pydantic; print(pydantic.VERSION)"
```

Use version 2.5 or newer.

### Python Version Too Low

Python 3.11+ is required.

### `httpx` Cannot Reach the Internet in Local Debugging

For real LLM calls in local mode, run `llm_proxy` separately:

```bash
cd llm_proxy
ANTHROPIC_API_KEY=sk-... uvicorn llm_proxy.proxy:app --port 9000
```

Or bypass LLM calls with `--mock-llm`.

## Runtime Issues

### Container Exits Immediately

Check:

```bash
docker compose logs simulator
docker compose logs llm_proxy
```

Common causes:

- invalid `config.yaml`, reported by Pydantic
- `llm_proxy` missing an API key, for example `missing-key:ANTHROPIC_API_KEY`
- scenario path not found

### Health Check Fails

```bash
docker compose ps
docker compose logs simulator
```

The simulator health check calls `GET /run/info`. The startup grace period
prevents early boot from being marked unhealthy.

### `RuntimeError: ingress impersonation`

This is intentional fail-fast behavior. Some code path attempted to publish a
message as `CH-A/B/C/D` without going through the ingress module.

## Attack Interface Issues

### `409 Conflict: max-concurrent-sessions-reached`

An active session already exists. Either end it:

```bash
curl -X POST http://localhost:8080/attack/session/<id>/end
```

or increase `attack_interface.session.max_concurrent_sessions`.

### `404 Not Found` on `/run/state`

Expected in black-box mode. Enable white-box mode:

```yaml
attack_interface:
  visibility: white
```

### `409 Conflict: session-ended`

The session already ended due to max turns, idle timeout, or run termination.
Start a new session.

### `403 Forbidden`

Usually one of:

- the channel is not in `enabled_channels`
- the proxy failed because a required LLM key is missing

## Guardrail and Policy Debugging

### Why Was My Message Blocked?

Search `guardrail.jsonl` for the message ID:

```bash
ID=$(ls -t runs/ | head -1)
grep "your_msg_id" runs/$ID/guardrail.jsonl | jq
```

### G2 Blocks Unexpectedly

Check `configs/policy_matrix.yaml`. RO/TO/AO are configured to block L3+
actions; those should come through SRO approval paths.

### G6 Blocks Missing `procedure_ref`

L3+ actions require `procedure_ref`. If agents often omit it, adjust the role
prompt in `configs/prompts/{role}.txt`.

### G8 Blocks at Code Level

Forbidden alarm suppress/bypass, safety system bypass, and alarm bypass are
hard blocked. This is intended.

### Ablation Results Do Not Differ

Check each run's `config.json` or
`report.json.configuration_summary.enabled_guardrails`. If they match, the
ablation did not actually change.

## Plant Simulation Behavior

### Normal Baseline Compromises a Safety Function

Some alarm thresholds are close to normal ranges. With long runs or different
seeds, drift can trigger alarms. The test suite verifies seed 42 for 100 ticks.
If this occurs often, adjust `_RESTORE_RATE` in
`src/plant_simulator/physics.py` or change the seed.

### Alarm Appears or Does Not Appear Unexpectedly

Check `ALARM_TRIGGER_RULES` in `src/plant_simulator/catalogs.py`.

### Power Does Not Drop After SCRAM

Confirm that the message has `type="ACTION"` and `action_type="scram"`. The
decay curve also requires `RPS.status == "tripped"` during `physics_step`.

## LLM Call Issues

### `error:HTTPStatusError`

Inspect `agent_thoughts.jsonl`. Common causes:

- expired API key
- provider rate limit
- missing provider allowlist entry in `llm_proxy`

If an LLM call fails, the simulator falls back to mock behavior for that call
and records `provider: "mock"` in `agent_thoughts.jsonl`.

### Token Cost Is Too High

```yaml
agents:
  sro: { max_tokens: 512 }
  ro:  { max_tokens: 512 }
logging:
  artifacts:
    agent_thoughts: false
```

## Output and Logging

### `runs/{id}/` Is Empty

Check whether `logging.artifacts.<name>` is set to `false`. Also verify the
Docker volume mount with:

```bash
docker compose config
```

### `report.md` Is Missing

Check `report.auto_generate_on_run_end`. Manual regeneration:

```bash
python -m src.report --run-dir runs/<id>/
```

If generation failed, look for `report_generation_failed` in the logs.

### `manifest.json` sha256 Mismatch

The run artifacts may have been modified after finalization, or fsync may have
been insufficient. Set `logging.fsync_each_line: true` if stronger durability is
needed.

## Isolation Checks

```bash
# 1. simulator should not reach the public internet
docker compose exec simulator python -c "import urllib.request; urllib.request.urlopen('https://google.com', timeout=3)"

# 2. simulator should reach llm_proxy
docker compose exec simulator python -c "import urllib.request; print(urllib.request.urlopen('http://llm_proxy:9000/healthz', timeout=3).read())"

# 3. simulator should not call LLM APIs directly
docker compose exec simulator python -c "import urllib.request; urllib.request.urlopen('https://api.anthropic.com', timeout=3)"
```

If isolation fails, inspect `docker-compose.yaml`, especially
`networks.nuclear_sim_net.internal: true`.

## Deeper Debugging

```bash
.venv/bin/python -m src.main --config configs/config.yaml --mock-llm --log-level DEBUG 2>&1 | tee debug.log
```

Component-focused searches:

```bash
grep "guardrail" debug.log
grep "ingress" debug.log
grep "mock_human" debug.log
```

## Help References

- System description: [`SYSTEM_DESCRIPTION.md`](../../SYSTEM_DESCRIPTION.md)
- Code structure: module docstrings under `src/`
- Tests as usage examples: `tests/`
