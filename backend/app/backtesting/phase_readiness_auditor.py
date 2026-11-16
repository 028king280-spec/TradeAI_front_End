"""
AIVOLVE Phase 4, Step 4.9 — Cross-Phase Readiness Audit Assembler.

Collects read-only readiness audits across Phase 1, Phase 2, Phase 3, Phase 4 (Steps 4.2-4.8),
and Governance/Persistence Safety into a single unified defect register and phase summary.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Sequence, Tuple

from app.backtesting.backtesting_readiness import audit_phase4_backtesting_readiness
from app.backtesting.configuration import DEFAULT_BACKTEST_DB_PATH
from app.backtesting.intelligence_readiness import (
    audit_phase2_intelligence_readiness,
    audit_phase3_ict_smc_readiness,
)
from app.backtesting.market_data_readiness import (
    audit_market_data_readiness,
    collect_live_feed_probe,
)
from app.backtesting.readiness_models import (
    DEFAULT_OBSERVATION_SESSION_DATE,
    DefectRegisterEntry,
    LiveFeedObservationProbe,
    PhaseAuditResult,
)
from app.backtesting.revalidation_models import ProtectedHashCheckRecord
from app.backtesting.risk_governance_readiness import audit_risk_governance_readiness
from app.backtesting.strategy_evidence_models import StrategyEvidenceReviewReport


@dataclass(frozen=True)
class CrossPhaseAuditBundle:
    """Consolidated bottom-up audit outputs across Phases 1-4 and Governance."""

    probe: LiveFeedObservationProbe
    phase_audits: Tuple[PhaseAuditResult, ...]
    defect_register: Tuple[DefectRegisterEntry, ...]
    protected_hash_checks: Tuple[ProtectedHashCheckRecord, ...]
    protected_hashes_all_matched: bool
    isolation_verified: bool
    phase4_context: Dict[str, object]


class PhaseReadinessAuditor:
    """Executes all Phase 1-4 and Governance audits deterministically."""

    def run_all(
        self,
        db_path: Path | str = DEFAULT_BACKTEST_DB_PATH,
        observation_session_date: str = DEFAULT_OBSERVATION_SESSION_DATE,
        probe: Optional[LiveFeedObservationProbe] = None,
        resolved_defect_ids: Optional[Sequence[str]] = None,
        latest_review: Optional[StrategyEvidenceReviewReport] = None,
        protected_baselines: Optional[Dict[str, Tuple[Path, str]]] = None,
    ) -> CrossPhaseAuditBundle:
        eff_probe = probe or collect_live_feed_probe(observation_session_date)

        p1_audit, p1_defects = audit_market_data_readiness(
            probe=eff_probe,
            resolved_defect_ids=resolved_defect_ids,
        )
        p2_audit = audit_phase2_intelligence_readiness(probe=eff_probe)
        p3_audit = audit_phase3_ict_smc_readiness()
        p4_audit, p4_defects, p4_ctx = audit_phase4_backtesting_readiness(
            db_path=db_path,
            latest_review=latest_review,
        )
        gov_audit, hash_checks, gov_safe, gov_defects = audit_risk_governance_readiness(
            db_path=db_path,
            protected_baselines=protected_baselines,
        )

        severity_order = {"P0": 0, "P1": 1, "P2": 2}
        all_defects = tuple(
            sorted(
                (*p1_defects, *p4_defects, *gov_defects),
                key=lambda d: (severity_order.get(d.severity.value, 9), d.defect_id),
            )
        )

        return CrossPhaseAuditBundle(
            probe=eff_probe,
            phase_audits=(p1_audit, p2_audit, p3_audit, p4_audit, gov_audit),
            defect_register=all_defects,
            protected_hash_checks=hash_checks,
            protected_hashes_all_matched=all(h.matched for h in hash_checks),
            isolation_verified=gov_safe,
            phase4_context=p4_ctx,
        )

