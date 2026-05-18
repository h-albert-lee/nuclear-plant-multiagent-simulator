# Quickstart - First Run in 5 Minutes

## Prerequisites

- Python 3.11 or newer, or Docker 24+
- Optional: at least one LLM API key, only required when using real LLM calls.
  Mock mode does not require keys.

## Option A - Local + Mock LLM

This is the fastest path and requires no API key.

```bash
cd nuclear-redteam-sim
make install              # create virtualenv and install dependencies
make smoke                # run normal_baseline for 50 ticks with mock operators
```

During the run, the console prints logs such as `orchestrator_start`,
`agent.SRO`, and `guardrail`.

After the run finishes:

```bash
ls runs/                  # find the new run_id directory
cat runs/<id>/report.md   # human-readable report
```

Check these items first in section 1 of `report.md`:

- **One-line result**: number of compromised safety functions, authority
  violations, and attack sessions.
- **Termination reason**: `max_ticks` is expected for a normal smoke run.

## Option B - Docker + Real LLM

```bash
cp .env.example .env
# Edit .env and set keys such as ANTHROPIC_API_KEY=sk-...
make build                # build simulator and llm_proxy images
make up                   # docker compose up -d
make logs                 # tail simulator container logs
```

`make logs` shows LLM call activity and per-tick state changes.

Stop the stack:

```bash
make down
```

`runs/<id>/` is mounted on the host, so run artifacts remain after containers
stop.

## Review the First Run Quickly

```bash
ID=$(ls -t runs/ | head -1)
cat runs/$ID/report.md | head -40
```

Key sections in `report.md`:

- Section 1, Summary: one-line run result.
- Section 3, Guardrail Activity: how often each `G_i` fired and whether it
  allowed or blocked messages.
- Section 4, Plant Trajectory: final state of the six CSFs.
- Section 5, Authority Violations / Bypass Attempts: meaningful policy events.
- Section 6, Notable Events: SCRAM, EOP entry, CSF degradation/loss, and other
  important events.

## Next Steps

- To attach an attack tool, read [`03_attack_guide.md`](03_attack_guide.md).
- To disable guardrails and compare behavior, read
  [`04_configuration_guide.md`](04_configuration_guide.md).
- To parse raw JSONL directly, read [`05_result_analysis.md`](05_result_analysis.md).
