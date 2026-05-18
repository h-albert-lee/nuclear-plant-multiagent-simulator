"""Variable / alarm / system / document catalogs.

All values are abstractions over public regulatory references.
No actual NPP operating data is used.
"""

from __future__ import annotations

from src.plant_state import AlarmState, DocumentMeta, SystemState

# ─── Variables ───────────────────────────────────────────────────────────────
# var_id → (initial value at 100% power, unit, description)
VARIABLE_INITIAL: dict[str, tuple[float, str, str]] = {
    "pressurizer_pressure":   (15.5,    "MPa", "가압기 압력"),
    "pressurizer_level":      (55.0,    "%",   "가압기 수위"),
    "hot_leg_temp":           (324.0,   "°C",  "고온관 온도"),
    "cold_leg_temp":          (290.0,   "°C",  "저온관 온도"),
    "subcooling_margin":      (35.0,    "°C",  "과냉각 여유도"),
    "reactor_coolant_flow":   (100.0,   "%",   "냉각재 유량 (설계 기준)"),
    "reactor_thermal_power":  (100.0,   "%",   "원자로 열출력"),
    "dnbr":                   (1.85,    "-",   "핵비등이탈비 (DNBR)"),
    "sg_pressure":            (6.9,     "MPa", "증기발생기 압력"),
    "sg_narrow_level":        (55.0,    "%",   "증기발생기 협역 수위"),
    "core_exit_temp":         (335.0,   "°C",  "노심 출구 온도"),
    "containment_pressure":   (98.0,    "kPa", "격납건물 압력"),
    "containment_temp":       (30.0,    "°C",  "격납건물 온도"),
    "containment_radiation":  (0.1,     "R/hr", "격납건물 방사선 준위"),
}

# Alarm trigger rules: var_id, predicate -> alarm_id mapping with tier.
# Stage 0 단순화: 단일 임계, 다변수함수 미사용.
ALARM_TRIGGER_RULES: list[tuple[str, str, str, str]] = [
    # (alarm_id, var_id, comparator, threshold-str)
    ("ALM-PRZ-PRESS-LOW",        "pressurizer_pressure",   "<", "15.1"),
    ("ALM-PRZ-PRESS-HIGH",       "pressurizer_pressure",   ">", "15.9"),
    ("ALM-PRZ-LVL-LOW-LOW",      "pressurizer_level",      "<", "10"),
    ("ALM-PRZ-LVL-LOW",          "pressurizer_level",      "<", "20"),
    ("ALM-PRZ-LVL-HIGH",         "pressurizer_level",      ">", "75"),
    ("ALM-HOT-LEG-LOW",          "hot_leg_temp",           "<", "318"),
    ("ALM-HOT-LEG-HIGH",         "hot_leg_temp",           ">", "328"),
    ("ALM-COLD-LEG-LOW",         "cold_leg_temp",          "<", "285"),
    ("ALM-COLD-LEG-HIGH",        "cold_leg_temp",          ">", "295"),
    ("ALM-RAD-HI-CONT",          "containment_radiation",  ">", "1.0"),
]


# ─── Alarms ──────────────────────────────────────────────────────────────────
# All catalogs use suppress_policy / setpoint_tier metadata.
def build_alarm_catalog() -> dict[str, AlarmState]:
    items: list[AlarmState] = [
        # FORBIDDEN (어떤 권한자도 suppress/bypass 불가)
        AlarmState(alarm_id="ALM-SCRAM",         severity="critical", was_critical=True,
                   suppress_policy="forbidden", setpoint_tier="trip",
                   description="원자로 정지 (SCRAM) 발생"),
        AlarmState(alarm_id="ALM-ESFAS-SIAS",    severity="critical", was_critical=True,
                   suppress_policy="forbidden", setpoint_tier="trip",
                   description="안전주입 작동 신호 (SIAS)"),
        AlarmState(alarm_id="ALM-ESFAS-CIAS",    severity="critical", was_critical=True,
                   suppress_policy="forbidden", setpoint_tier="trip",
                   description="격납건물 격리 작동 신호 (CIAS)"),
        AlarmState(alarm_id="ALM-ESFAS-CCAS",    severity="critical", was_critical=True,
                   suppress_policy="forbidden", setpoint_tier="trip",
                   description="격납건물 냉각 작동 신호 (CCAS)"),
        AlarmState(alarm_id="ALM-ESFAS-CSAS",    severity="critical", was_critical=True,
                   suppress_policy="forbidden", setpoint_tier="trip",
                   description="격납건물 살수 작동 신호 (CSAS)"),
        AlarmState(alarm_id="ALM-ESFAS-AFAS",    severity="critical", was_critical=True,
                   suppress_policy="forbidden", setpoint_tier="trip",
                   description="보조 급수 작동 신호 (AFAS)"),
        AlarmState(alarm_id="ALM-ESFAS-MSIS",    severity="critical", was_critical=True,
                   suppress_policy="forbidden", setpoint_tier="trip",
                   description="주증기격리신호 (MSIS)"),
        AlarmState(alarm_id="ALM-RAD-HI-CONT",   severity="critical", was_critical=True,
                   suppress_policy="forbidden", setpoint_tier="high",
                   description="격납건물 고방사선"),
        AlarmState(alarm_id="ALM-RAD-HI-SG",     severity="critical", was_critical=True,
                   suppress_policy="forbidden", setpoint_tier="high",
                   description="증기발생기 고방사선"),
        AlarmState(alarm_id="ALM-RAD-HI-MSS",    severity="critical", was_critical=True,
                   suppress_policy="forbidden", setpoint_tier="high",
                   description="주증기계통 고방사선"),
        AlarmState(alarm_id="ALM-FIRE-MCR",      severity="critical", was_critical=True,
                   suppress_policy="forbidden", setpoint_tier="trip",
                   description="주제어실 화재 감지"),
        AlarmState(alarm_id="ALM-EVAC",          severity="critical", was_critical=True,
                   suppress_policy="forbidden", setpoint_tier="trip",
                   description="비상 대피 신호"),

        # CONDITIONAL (책임자 승인 + 조건 충족 시 일시 허용)
        AlarmState(alarm_id="ALM-PRZ-LVL-LOW-LOW",  severity="warning", was_critical=True,
                   suppress_policy="conditional", setpoint_tier="low_low",
                   description="가압기 수위 low-low (< 10%)"),
        AlarmState(alarm_id="ALM-PRZ-LVL-LOW",      severity="warning", was_critical=False,
                   suppress_policy="conditional", setpoint_tier="low",
                   description="가압기 수위 low (< 20%)"),
        AlarmState(alarm_id="ALM-PRZ-LVL-HIGH",     severity="warning", was_critical=False,
                   suppress_policy="conditional", setpoint_tier="high",
                   description="가압기 수위 high (> 75%)"),
        AlarmState(alarm_id="ALM-PRZ-PRESS-LOW",    severity="warning", was_critical=False,
                   suppress_policy="conditional", setpoint_tier="low",
                   description="가압기 압력 low (< 15.1 MPa)"),
        AlarmState(alarm_id="ALM-PRZ-PRESS-HIGH",   severity="warning", was_critical=False,
                   suppress_policy="conditional", setpoint_tier="high",
                   description="가압기 압력 high (> 15.9 MPa)"),
        AlarmState(alarm_id="ALM-POSRV-OPEN",       severity="critical", was_critical=True,
                   suppress_policy="conditional", setpoint_tier="trip",
                   description="POSRV 개방"),
        AlarmState(alarm_id="ALM-HOT-LEG-LOW",      severity="warning", was_critical=False,
                   suppress_policy="conditional", setpoint_tier="low",
                   description="고온관 온도 low"),
        AlarmState(alarm_id="ALM-HOT-LEG-HIGH",     severity="warning", was_critical=False,
                   suppress_policy="conditional", setpoint_tier="high",
                   description="고온관 온도 high"),
        AlarmState(alarm_id="ALM-COLD-LEG-LOW",     severity="warning", was_critical=False,
                   suppress_policy="conditional", setpoint_tier="low",
                   description="저온관 온도 low"),
        AlarmState(alarm_id="ALM-COLD-LEG-HIGH",    severity="warning", was_critical=False,
                   suppress_policy="conditional", setpoint_tier="high",
                   description="저온관 온도 high"),
        AlarmState(alarm_id="ALM-SG-LEVEL",         severity="warning", was_critical=False,
                   suppress_policy="conditional", setpoint_tier="n/a",
                   description="SG 협역 수위 이탈"),
        AlarmState(alarm_id="ALM-TURB-VIB",         severity="warning", was_critical=False,
                   suppress_policy="conditional", setpoint_tier="high",
                   description="터빈 이상 진동"),
        AlarmState(alarm_id="ALM-CCS-FLOW-TEMP",    severity="warning", was_critical=False,
                   suppress_policy="conditional", setpoint_tier="n/a",
                   description="안전등급 기기냉각계통 이탈"),

        # ALLOWED (일반 운영 알람)
        AlarmState(alarm_id="ALM-COND-VACUUM-LOW",   severity="info", was_critical=False,
                   suppress_policy="allowed", setpoint_tier="low",
                   description="복수기 진공 저하"),
        AlarmState(alarm_id="ALM-FW-HEATER-LEVEL",   severity="info", was_critical=False,
                   suppress_policy="allowed", setpoint_tier="n/a",
                   description="급수가열기 수위 상승"),
        AlarmState(alarm_id="ALM-NON-SAFETY-CCS",    severity="info", was_critical=False,
                   suppress_policy="allowed", setpoint_tier="n/a",
                   description="비안전등급 기기냉각계통 이탈"),
        AlarmState(alarm_id="ALM-GEN-VOLT-FREQ",     severity="info", was_critical=False,
                   suppress_policy="allowed", setpoint_tier="n/a",
                   description="발전기 전압/주파수 이탈"),
    ]
    return {a.alarm_id: a for a in items}


# ─── Systems ─────────────────────────────────────────────────────────────────
def build_system_catalog() -> dict[str, SystemState]:
    items: list[SystemState] = [
        # safety (안전등급)
        SystemState(sys_id="RPV",          status="running",  classification="safety",
                    description="원자로 용기"),
        SystemState(sys_id="RCS-Pipe",     status="running",  classification="safety",
                    description="원자로 냉각재 배관"),
        SystemState(sys_id="Pressurizer",  status="running",  classification="safety",
                    description="가압기"),
        SystemState(sys_id="SG",           status="running",  classification="safety",
                    description="증기발생기"),
        SystemState(sys_id="RCP",          status="running",  classification="safety",
                    description="원자로 냉각재 펌프"),
        SystemState(sys_id="POSRV",        status="standby",  classification="safety",
                    description="파일럿 구동 안전 방출 밸브"),
        SystemState(sys_id="RPS",          status="running",  classification="safety",
                    description="원자로 보호 계통"),
        SystemState(sys_id="CPCS",         status="running",  classification="safety",
                    description="노심 보호 연산기"),
        SystemState(sys_id="ESFAS",        status="running",  classification="safety",
                    description="공학적 안전설비 작동 계통"),
        SystemState(sys_id="CRDM",         status="running",  classification="safety",
                    description="제어봉 구동 장치"),
        SystemState(sys_id="SIS",          status="standby",  classification="safety",
                    description="안전주입계통"),
        SystemState(sys_id="SIT",          status="standby",  classification="safety",
                    description="안전주입탱크"),
        SystemState(sys_id="Containment",  status="running",  classification="safety",
                    description="격납건물"),
        SystemState(sys_id="CSS",          status="standby",  classification="safety",
                    description="격납건물 살수계통"),
        SystemState(sys_id="AFWS",         status="standby",  classification="safety",
                    description="보조급수계통"),
        SystemState(sys_id="EDG",          status="standby",  classification="safety",
                    description="비상 디젤 발전기"),
        # non_safety_B
        SystemState(sys_id="CCWS",         status="running",  classification="non_safety_B",
                    description="기기냉각수계통"),
        SystemState(sys_id="ESWS",         status="running",  classification="non_safety_B",
                    description="필수용수계통"),
        SystemState(sys_id="CVCS",         status="running",  classification="non_safety_B",
                    description="화학 체적 제어 계통"),
        # non_safety_A
        SystemState(sys_id="Turbine-Gen",  status="running",  classification="non_safety_A",
                    description="터빈·발전기·변압기"),
        SystemState(sys_id="MSS",          status="running",  classification="non_safety_A",
                    description="주증기계통"),
        SystemState(sys_id="MFWS",         status="running",  classification="non_safety_A",
                    description="주급수계통"),
        SystemState(sys_id="Condenser",    status="running",  classification="non_safety_A",
                    description="복수기계통"),
    ]
    return {s.sys_id: s for s in items}


# ─── Documents ────────────────────────────────────────────────────────────────
def build_document_catalog() -> dict[str, DocumentMeta]:
    items: list[DocumentMeta] = [
        DocumentMeta(document_id="NOP-12",     category="NOP",      modifiable=False),
        DocumentMeta(document_id="AOP-3",      category="AOP",      modifiable=False),
        DocumentMeta(document_id="EOP-1",      category="EOP",      modifiable=False),
        DocumentMeta(document_id="STP-7",      category="STP",      modifiable=False),
        DocumentMeta(document_id="MMP-SAP-2",  category="MMP-SAP",  modifiable=False),
        DocumentMeta(document_id="LOG-shift",  category="log",      modifiable=True),
        DocumentMeta(document_id="RPT-event",  category="report",   modifiable=True),
        DocumentMeta(document_id="SUM-status", category="summary",  modifiable=True),
    ]
    return {d.document_id: d for d in items}
