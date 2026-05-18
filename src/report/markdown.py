"""Markdown rendering of the structured report."""

from __future__ import annotations

from typing import Any


def render_markdown(report: dict[str, Any]) -> str:
    out: list[str] = []
    meta = report["metadata"]
    cfg = report["configuration_summary"]
    atk = report["attack_summary"]
    grd = report["guardrail_summary"]
    plant = report["plant_trajectory"]
    msgs = report["agent_message_stats"]
    vio = report["violations"]
    notable = report["notable_events"]
    repr_ = report["reproducibility"]

    out.append(f"# Run Report — {report['run_id']}\n")
    out.append(
        f"_Simulator v{report['simulator_version']} · Generated {report['generated_at']}_\n"
    )

    out.append("\n## 1. 요약\n")
    out.append(f"- **Run**: `{report['run_id']}`")
    out.append(f"- **Scenario**: `{cfg.get('scenario')}`")
    out.append(f"- **종료 사유**: `{meta.get('termination_reason')}`")
    out.append(f"- **지속**: tick {meta.get('start_tick')} → {meta.get('end_tick')} ({meta.get('duration_ticks')} ticks)")
    out.append(f"- **가드레일**: {', '.join(cfg.get('enabled_guardrails', []))}")
    out.append(f"- **STA mode**: {cfg.get('sta_mode')}")
    out.append(f"- **Visibility**: {cfg.get('visibility')}")
    compromised = sum(1 for v in plant.get("safety_function_final", {}).values() if v != "intact")
    out.append(
        f"- **결과 한 줄**: 안전기능 {compromised}/6 손상, "
        f"권한위반 {len(vio.get('authority_violations', []))}건, "
        f"어택 세션 {atk.get('total_sessions', 0)}개"
    )

    out.append("\n## 2. 어택 활동\n")
    out.append(f"- 총 세션: {atk.get('total_sessions', 0)}")
    out.append(f"- 총 턴: {atk.get('total_turns', 0)}")
    out.append(f"- 단발 ingress: {atk.get('raw_ingress_count', 0)}")
    chan = atk.get("channel_distribution", {})
    if chan:
        out.append(f"- 채널 분포: " + ", ".join(f"{k}={v}" for k, v in chan.items()))
    if atk.get("sessions"):
        out.append("\n| session_id | turns | channels | outcome |")
        out.append("|---|---|---|---|")
        for s in atk["sessions"]:
            out.append(
                f"| {s['session_id']} | {s['turns_used']} | "
                f"{','.join(s['channels_used'])} | {s.get('final_outcome', '?')} |"
            )

    out.append("\n## 3. 가드레일 활동\n")
    per_g = grd.get("per_guardrail", {})
    if per_g:
        out.append("| G | invocations | allow | modify | block | top block reason |")
        out.append("|---|---|---|---|---|---|")
        for gid, st in sorted(per_g.items()):
            dec = st["decisions"]
            reasons = st["block_reasons"]
            top_reason = max(reasons.items(), key=lambda kv: kv[1])[0] if reasons else "-"
            out.append(
                f"| {gid} | {st['invocations']} | {dec.get('allow', 0)} | "
                f"{dec.get('modify', 0)} | {dec.get('block', 0)} | {top_reason} |"
            )

    out.append("\n## 4. Plant Trajectory\n")
    out.append("**6 Critical Safety Functions (최종 상태)**\n")
    for csf, s in plant.get("safety_function_final", {}).items():
        out.append(f"- `{csf}`: **{s}**")
    out.append("\n**op_state transitions**:")
    for t in plant.get("op_state_transitions", []):
        out.append(f"- tick {t['tick']}: {t.get('from')} → {t['to']}")
    out.append("\n**CSF transitions**:")
    for t in plant.get("safety_function_transitions", []):
        out.append(f"- tick {t['tick']}: `{t['csf']}` {t['from']} → {t['to']}")
    out.append(f"\n알람 활성 이벤트 누적 카운트: {plant.get('alarm_event_count', 0)}")

    out.append("\n## 5. 권한 위반 / Bypass 시도\n")
    av = vio.get("authority_violations", [])
    if av:
        out.append("### Authority violations")
        for v in av:
            out.append(f"- tick {v['tick']} | {v['sender']} | {v['description']}")
    bp = vio.get("bypass_attempts", [])
    if bp:
        out.append("\n### Bypass attempts")
        for v in bp:
            out.append(f"- tick {v['tick']} | {v['sender']} | {v['description']}")
    if not av and not bp:
        out.append("- _(none)_")

    out.append("\n## 6. Notable Events\n")
    if notable:
        for ev in notable:
            out.append(f"- tick {ev['tick']} | **{ev['kind']}** — {ev['description']}")
    else:
        out.append("- _(none)_")

    out.append("\n## 7. Agent Message Statistics\n")
    out.append(f"- 총 메시지: {msgs.get('total_messages', 0)}")
    out.append("- sender × type:")
    out.append(f"  - by sender: `{msgs.get('by_sender', {})}`")
    out.append(f"  - by type: `{msgs.get('by_type', {})}`")
    out.append(f"  - by action_class: `{msgs.get('by_action_class', {})}`")
    out.append(f"  - by action_type: `{msgs.get('by_action_type', {})}`")
    out.append(f"- approval_requests={msgs.get('approval_requests', 0)}, "
               f"grants={msgs.get('approval_grants', 0)}, denials={msgs.get('approval_denials', 0)}")
    out.append(f"- STA vetos={msgs.get('sta_vetos', 0)}, SRO overrides={msgs.get('sro_overrides', 0)}")

    out.append("\n## 8. Reproducibility\n")
    out.append(f"- simulator_version: {repr_.get('simulator_version')}")
    out.append(f"- seed: {repr_.get('seed')}")
    out.append(f"- config_sha256: `{repr_.get('config_sha256')}`")
    out.append(f"- scenario_file_sha256: `{repr_.get('scenario_file_sha256')}`")
    out.append(f"- code_revision: `{repr_.get('code_revision')}`")

    return "\n".join(out) + "\n"
