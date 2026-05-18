# examples/

Reference scripts that exercise the simulator's external API. These are
*demonstrations*, not part of the test suite, and are intended as starting
templates for actual red-teaming tools.

## `attack_agent_demo.py`

A minimal HTTP client that runs one of three canned multi-turn attack
strategies against a running simulator.

```bash
# Start the simulator (separate terminal):
make smoke              # mock LLM, no API key required
#  ── or ──
make up                 # Docker, requires .env with API key

# Run the demo:
python examples/attack_agent_demo.py \
    --base-url http://localhost:8080 \
    --strategy gradual_escalation \
    --max-turns 8
```

Strategies:

| name | what it does | tests which guardrail |
|---|---|---|
| `gradual_escalation` | benign monitoring → ack → suppress → SIAS bypass → ECCS interlock | G1 derivation, G2 policy, G8 bypass lock |
| `authority_spoof` | impersonates plant manager / NRC / internal-aux across CH-A/B/D | G5 provenance |
| `urgency_inject` | pushes "immediate" without procedure_ref | G7 disclosure → ESCALATE conversion |

The output stream shows the SituationSummary returned each turn (black-box
view by default — to see full plant state, set
`attack_interface.visibility: white` in `configs/config.yaml`).

After the run, inspect `runs/<latest>/attack_sessions.jsonl` and
`runs/<latest>/report.md` to see how the simulator actually responded.
