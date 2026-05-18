# Result Analysis - Reading `runs/{id}/`

## Output Directory Structure

After a run, `runs/{run_id}/` contains:

```text
runs/{run_id}/
├── manifest.json
├── config.json
├── messages.jsonl
├── guardrail.jsonl
├── plant_state.jsonl
├── ingress.jsonl
├── approvals.jsonl
├── attack_sessions.jsonl
├── agent_thoughts.jsonl
├── agent_thoughts_prompts/
│   └── {sha256}.txt
├── safety_function_timeline.jsonl
├── run_summary.json
├── report.json
└── report.md
```

Purpose of the main artifacts:

- `manifest.json`: artifact list, sha256, line counts, and schema versions.
- `config.json`: full runtime config snapshot.
- `messages.jsonl`: canonical message bus event log.
- `guardrail.jsonl`: per-guardrail decisions.
- `plant_state.jsonl`: per-tick plant snapshots.
- `ingress.jsonl`: external ingress request trace.
- `approvals.jsonl`: mock-human responses.
- `attack_sessions.jsonl`: session lifecycle and returned summaries.
- `agent_thoughts.jsonl`: LLM call trace.
- `safety_function_timeline.jsonl`: CSF state transitions.
- `report.json` / `report.md`: derived analysis.

## Quick Review

```bash
ID=$(ls -t runs/ | head -1)
cat runs/$ID/report.md
```

Check section 1 first:

- number of compromised safety functions, normally `0/6` for a benign run
- authority violation count
- attack session count

## The 9 Sections in `report.json`

```python
import json
r = json.load(open(f"runs/{ID}/report.json"))

r["metadata"]
r["configuration_summary"]
r["attack_summary"]
r["guardrail_summary"]
r["plant_trajectory"]
r["agent_message_stats"]
r["violations"]
r["notable_events"]
r["reproducibility"]
```

They cover run metadata, configuration, attacks, guardrail activity, plant
trajectory, agent message statistics, violations, notable events, and
reproducibility hashes.

## Parsing Raw JSONL

JSONL uses one JSON object per line.

```python
import json

def read_jsonl(path):
    with open(path, "rt", encoding="utf-8") as f:
        for line in f:
            yield json.loads(line)

for ev in read_jsonl(f"runs/{ID}/messages.jsonl"):
    msg = ev["msg"]
    if msg["type"] == "ACTION":
        print(msg["tick"], msg["sender"], msg["action_type"], msg["action_class"])
```

Count guardrail block reasons:

```python
from collections import Counter

counter = Counter()
for ev in read_jsonl(f"runs/{ID}/guardrail.jsonl"):
    if ev["decision"] == "block":
        counter[(ev["guardrail_id"], ev["block_category"])] += 1
print(counter.most_common(10))
```

## Important JSONL Schemas

### `messages.jsonl`

```json
{
  "ts": "2026-05-17T14:38:01.123Z",
  "tick": 142,
  "topic": "agent.outbound",
  "msg": {
    "msg_id": "uuid",
    "tick": 142,
    "sender": "SRO",
    "recipient": "RO",
    "type": "ACTION",
    "action_type": "control",
    "action_class": "L2",
    "procedure_ref": "NOP-12",
    "target_system": "Main-Feedwater",
    "payload": "reduce_flow:50",
    "urgency": "routine",
    "provenance": {"verified": "unverified"},
    "in_response_to": null
  }
}
```

### `guardrail.jsonl`

```json
{
  "ts": "...",
  "tick": 142,
  "msg_id": "uuid",
  "guardrail_id": "G2",
  "decision": "allow",
  "reason": "g2-allow",
  "block_category": null
}
```

`decision` is one of `allow`, `modify`, or `block`. `block_category` is
populated for blocked messages.

### `plant_state.jsonl`

```json
{
  "ts": "...",
  "tick": 142,
  "state": {
    "tick": 142,
    "op_state": "normal",
    "vars": {},
    "alarms": {},
    "systems": {},
    "procedures": {"active": "NOP-12", "step": 0},
    "safety_functions": {},
    "documents": {}
  }
}
```

### `attack_sessions.jsonl`

Events are `start`, `turn`, and `end`.

```json
{
  "ts": "...",
  "tick": 100,
  "session_id": "uuid",
  "event": "start",
  "attacker_id": "redteam-1",
  "max_turns": 10,
  "visibility": "black",
  "initial_summary": {}
}
```

```json
{
  "ts": "...",
  "tick": 142,
  "session_id": "uuid",
  "event": "turn",
  "turn": 1,
  "channel": "CH-A",
  "request": {"payload": "...", "claimed_sender": "..."},
  "msg_id": "uuid",
  "situation_summary_given": {}
}
```

### `agent_thoughts.jsonl`

```json
{
  "ts": "...",
  "tick": 142,
  "agent_role": "SRO",
  "llm_model": "claude-opus-4-7",
  "provider": "anthropic",
  "temperature": 0.2,
  "input_prompt_sha256": "abc123...",
  "input_prompt_excerpt": "<<SYSTEM>>...",
  "output_raw": "{\"messages\":[...]}",
  "parsed_messages": ["msg_id_1", "msg_id_2"],
  "tokens_in": 1234,
  "tokens_out": 234
}
```

Full prompt bodies are stored in `agent_thoughts_prompts/{sha256}.txt` with
deduplication.

### `safety_function_timeline.jsonl`

```json
{
  "ts": "...",
  "tick": 285,
  "csf": "rcs_integrity",
  "from": "intact",
  "to": "degraded",
  "cause_msg_id": null
}
```

## Common Analysis Questions

Authority violations:

```python
r = json.load(open(f"runs/{ID}/report.json"))
print(len(r["violations"]["authority_violations"]))
```

Most active blocking guardrails:

```python
for gid, st in r["guardrail_summary"]["per_guardrail"].items():
    print(gid, st["decisions"].get("block", 0), "/", st["invocations"])
```

Channel distribution:

```python
print(r["attack_summary"]["channel_distribution"])
```

SCRAM timing:

```python
for ev in r["notable_events"]:
    if ev["kind"] == "SCRAM":
        print(ev)
```

STA VETO override rate:

```python
v = r["agent_message_stats"]["sta_vetos"]
o = r["agent_message_stats"]["sro_overrides"]
print(f"override rate = {o}/{v}")
```

Compare guardrail ablations:

```python
import os, json
results = []
for run_id in os.listdir("runs"):
    p = f"runs/{run_id}/report.json"
    if not os.path.exists(p):
        continue
    r = json.load(open(p))
    results.append({
        "run_id": run_id,
        "guardrails": r["configuration_summary"]["enabled_guardrails"],
        "sta_mode": r["configuration_summary"]["sta_mode"],
        "scenario": r["configuration_summary"]["scenario"],
        "success": r["attack_summary"]["successful_attack_count"],
        "violations": len(r["violations"]["authority_violations"]),
        "csfs_lost": sum(1 for v in r["plant_trajectory"]["safety_function_final"].values() if v == "lost"),
    })
```

## Regenerate Reports

```bash
python -m src.report --run-dir runs/<id>/
python -m src.report --run-id <id>
python -m src.report --run-dir runs/<id>/ --formats json,md
```

Raw JSONL is canonical, so reports can always be regenerated.

## External Analysis Tools

Use:

1. `manifest.json` for integrity verification
2. `report.json` for headline statistics
3. JSONL files for detailed analysis

## Integrity Check

```bash
python -c "
import json, hashlib
m = json.load(open('runs/$ID/manifest.json'))
for art in m['artifacts']:
    p = f'runs/$ID/{art[\"path\"]}'
    h = hashlib.sha256(open(p, 'rb').read()).hexdigest()
    ok = h == art['sha256']
    print(art['path'], 'OK' if ok else 'CORRUPT')
"
```
