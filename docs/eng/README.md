# English User Guide

English guide set for the nuclear-control multi-agent red-teaming simulator.

## Before You Start

This system is an **isolated mock environment**. It is not connected to any real
nuclear power plant system, and all variables, alarms, and system information
are abstractions based on public references.

## Guide Index

| Document | Audience | Contents |
|---|---|---|
| [`01_quickstart.md`](01_quickstart.md) | Everyone | Install, run the first scenario, and inspect results in about 5 minutes |
| [`02_running_the_system.md`](02_running_the_system.md) | Operators | Docker/local execution and normal scenario runs |
| [`03_attack_guide.md`](03_attack_guide.md) | Red-team researchers | How to interact with the simulator over HTTP, SSE, and multi-turn sessions |
| [`04_configuration_guide.md`](04_configuration_guide.md) | Everyone | `config.yaml`, guardrail toggles, STA modes, and visibility |
| [`05_result_analysis.md`](05_result_analysis.md) | Analysts | How to read `runs/{id}/`, JSONL files, and `report.md` |
| [`06_troubleshooting.md`](06_troubleshooting.md) | Operators | Common issues and fixes |
| [`07_test_scenario_catalog.md`](07_test_scenario_catalog.md) | Developers/researchers | Verification and experiment checklist |
| [`08_benchmark_replay.md`](08_benchmark_replay.md) | Red-team researchers | Replay the public **NRT-Bench** HF dataset against this simulator with **your** operator-model stack — no external redteam agent required |

## System Overview

```text
[external attack tool]--HTTP/REST--> localhost:8080
                                     |
                                     v
                           +---------------------+
                           | simulator container |
                           | - 5 operator agents |
                           | - plant simulator   |
                           | - guardrails G0-G10 |
                           | - mock human        |
                           +---------------------+
                                     |
                                     v
                           +---------------------+
                           | llm_proxy container |
                           | Anthropic/OpenAI/   |
                           | Google/Qwen allow   |
                           +---------------------+
```

For the full system description, see [`SYSTEM_DESCRIPTION.md`](../../SYSTEM_DESCRIPTION.md).
