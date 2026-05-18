"""GuardrailStack — wires enabled guardrails together; runs each message through them in order."""

from __future__ import annotations

from collections import defaultdict
from typing import Optional

import structlog

from src.config_models import GuardrailsConfig
from src.enums import STAMode
from src.guardrails.base import (
    AllowVerdict,
    BlockVerdict,
    Guardrail,
    GuardrailContext,
    ModifyVerdict,
)
from src.guardrails.g0_baseline import G0Baseline
from src.guardrails.g1_classifier import G1ActionClassifier
from src.guardrails.g2_policy import G2PolicyGate
from src.guardrails.g3_two_person import G3TwoPersonIntegrity
from src.guardrails.g4_sta_veto import G4STAVetoChannel
from src.guardrails.g5_provenance import G5InputProvenance
from src.guardrails.g6_procedure import G6ProcedureGrounding
from src.guardrails.g7_disclosure import G7MandatoryDisclosure
from src.guardrails.g8_bypass_lock import G8HardcodedBypassLock
from src.guardrails.g9_rate_limit import G9RateLimit
from src.guardrails.g10_doc_lock import G10ProcedureDocLock
from src.message_models import GuardrailVerdict, Message
from src.plant_state import PlantState

log = structlog.get_logger(__name__)


class GuardrailStack:
    def __init__(
        self,
        cfg: GuardrailsConfig,
        *,
        sta_mode: STAMode,
        signature_allowlist: dict[str, list[str]],
    ) -> None:
        self.cfg = cfg
        all_guardrails: dict[str, Guardrail] = {
            "G0": G0Baseline(),
            "G1": G1ActionClassifier(),
            "G2": G2PolicyGate(cfg.g2_policy_table),
            "G3": G3TwoPersonIntegrity(cfg.g3_approval_window_ticks),
            "G4": G4STAVetoChannel(sta_mode),
            "G5": G5InputProvenance(signature_allowlist),
            "G6": G6ProcedureGrounding(),
            "G7": G7MandatoryDisclosure(),
            "G8": G8HardcodedBypassLock(),
            "G9": G9RateLimit(cfg.g9_rate_cap),
            "G10": G10ProcedureDocLock(),
        }
        ordered_enabled: list[Guardrail] = []
        # If G0 alone enabled → baseline ablation.
        if cfg.enabled == ["G0"]:
            ordered_enabled = [all_guardrails["G0"]]
        else:
            # Fixed evaluation order: provenance → classifier → policy → procedure →
            # disclosure → two-person → STA → bypass → rate-limit → doc-lock
            order = ["G5", "G1", "G2", "G6", "G7", "G3", "G4", "G8", "G9", "G10"]
            for gid in order:
                if gid in cfg.enabled:
                    ordered_enabled.append(all_guardrails[gid])
        self.guardrails: list[Guardrail] = ordered_enabled

        self.ctx_template: dict = {
            "approval_ledger": defaultdict(list),
            "sta_vetoes": {},
            "sta_overrides": {},
            "rate_counts": {},
        }

    def new_context(self, tick: int, plant: PlantState, *, persistent: GuardrailContext | None = None) -> GuardrailContext:
        if persistent is not None:
            persistent.tick = tick
            persistent.plant = plant
            persistent.rate_counts = {}  # per-tick reset
            return persistent
        return GuardrailContext(
            tick=tick,
            plant=plant,
            approval_ledger=defaultdict(list),
            sta_vetoes={},
            sta_overrides={},
            rate_counts={},
        )

    async def process(
        self,
        msg: Message,
        ctx: GuardrailContext,
    ) -> tuple[Optional[Message], list[GuardrailVerdict]]:
        """Pipe `msg` through each enabled guardrail.

        Returns (final_msg_or_None_if_blocked, list_of_verdicts).
        """
        verdicts: list[GuardrailVerdict] = []
        current = msg
        for g in self.guardrails:
            v = await g.process(current, ctx)
            if isinstance(v, AllowVerdict):
                verdicts.append(GuardrailVerdict(guardrail_id=g.id, decision="allow", reason=v.reason))
                current = v.message
            elif isinstance(v, ModifyVerdict):
                verdicts.append(GuardrailVerdict(guardrail_id=g.id, decision="modify", reason=v.reason))
                current = v.new_message
            elif isinstance(v, BlockVerdict):
                verdicts.append(GuardrailVerdict(
                    guardrail_id=g.id,
                    decision="block",
                    reason=v.reason,
                    block_category=v.block_category,
                ))
                return None, verdicts
        return current, verdicts
