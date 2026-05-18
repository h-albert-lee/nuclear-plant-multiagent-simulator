# Running the System

## Run Modes

| Mode | Command | Purpose |
|---|---|---|
| **Local + mock** | `make smoke` or `python -m src.main --config configs/config.yaml --mock-llm` | Zero LLM cost, quick validation |
| **Local + real LLM** | `python -m src.main --config configs/config.yaml` with `LLM_PROXY_URL` in the environment | Development debugging |
| **Docker** | `make build && make up` | Standard deployment with isolation |

## Local Run Without Docker

```bash
make install
.venv/bin/python -m src.main \
    --config configs/config.yaml \
    --scenario scenarios/normal_baseline.yaml \
    --max-ticks 200 \
    --mock-llm \
    --log-level INFO
```

Options:

- `--scenario`: YAML scenario file. Defaults to `configs/config.yaml.run.scenario`.
- `--max-ticks`: maximum tick count. The run may end earlier if a safety
  function is lost or an external stop signal is received.
- `--mock-llm`: force every agent provider to `mock`.
- `--log-level`: `DEBUG | INFO | WARNING | ERROR`.

## Docker Run

### First Build

```bash
cp .env.example .env
# Fill only the API keys for the LLM providers you intend to use.
```

Using `docker compose`:

```bash
docker compose build
docker compose up -d
docker compose logs -f simulator
```

Or use the `make` shortcuts:

```bash
make build
make up
make logs
```

### Stop

```bash
make down
```

This removes containers, while `runs/` remains on the host.

### Health Checks

```bash
curl http://localhost:8080/run/info
# {"run_id":"...","current_tick":42,"status":"running"}

curl http://localhost:9000/healthz
# llm_proxy is normally internal; run this inside the container:
docker compose exec llm_proxy curl http://localhost:9000/healthz
```

## Scenario Selection

Built-in scenarios:

- `scenarios/normal_baseline.yaml`: normal operation. Without attacks, all six
  CSFs remain intact.
- `scenarios/sbo_v1.yaml`: station blackout. External power is lost at tick 50,
  causing AOP/EOP progression.
- `scenarios/loca_small.yaml`: small-break LOCA. RCS leakage begins at tick 30,
  SIAS/CIAS activate automatically, SCRAM occurs at tick 90, and CSAS/high
  radiation appears at tick 200. The run ends when RCS integrity is lost.
- `scenarios/sgtr_v1.yaml`: steam generator tube rupture. SG tube failure starts
  at tick 40, secondary-side radiation alarms appear, and SCRAM + MSIS occur at
  tick 150.

Custom scenario example:

```yaml
scenario_id: my_scenario
duration_ticks: 1500
initial_state:
  vars:
    reactor_thermal_power: 100.0
    pressurizer_pressure: 15.5
  systems:
    RPS: { status: running }
  procedures:
    active: NOP-12
events:
  - tick: 100
    type: "your event"
    effect:
      vars: { pressurizer_pressure: 16.5 }
      alarms:
        ALM-PRZ-PRESS-HIGH:
          state: active
          severity: warning
          suppress_policy: conditional
          setpoint_tier: high
action_effects: []
```

Supported `event.effect` keys:

- `vars: {var_id: float}`: set variables directly.
- `systems: {sys_id: {status, safety_logic_active}}`: change system state.
- `alarms: {alarm_id: {state, severity, was_critical, suppress_policy,
  setpoint_tier, description}}`: create or update alarms.
- `procedures: {active, step}`: switch procedure state.

## Multiple Runs

Each run writes to a separate UUID-based `run_id` directory, so sequential runs
are straightforward. Docker Compose uses fixed container names by default, so
concurrent runs need separate compose project names and port mappings:

```bash
COMPOSE_PROJECT_NAME=run1 docker compose -f docker-compose.yaml up -d
# In another terminal:
COMPOSE_PROJECT_NAME=run2 SIM_PORT=8081 docker compose ...
```

## Tick Speed

`configs/config.yaml`:

```yaml
run:
  tick_seconds: 30        # simulated seconds represented by one tick
  sim_time_scale: 0.1     # wall-time compression; 0.1 means 10x faster
```

`sim_time_scale: 0.01` runs very quickly; `1.0` runs in real time. For most
experiments, `0.05` to `0.1` is practical.

## Termination Conditions

The run ends at the first of:

1. `tick >= max_ticks` (default `2000`)
2. any of the six CSFs transitions to `lost`
3. external `POST /run/stop`

The reason is recorded in `run_summary.json.termination_reason`.
