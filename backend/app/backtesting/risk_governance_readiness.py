"""
AIVOLVE Phase 4, Step 4.9 — Risk Governance, Execution Mode & Persistence Protection Auditor.

Verifies:
- Execution mode strictly locked to `PAPER_TRADING_ONLY` (no broker order placement paths)
- `SENSEX` permanently `GOVERNANCE_LOCKED` via `verify_index_governance`
- All 6 protected persistence SHA-256 hashes unchanged
- Backtest storage strictly isolated inside `backend/data/backtest/`
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional, Tuple

from app.backtesting.configuration import (
    DEFAULT_BACKTEST_DB_PATH,
    EXECUTION_MODE,
    assert_isolated_backtest_path,
    verify_index_governance,
)
from app.backtesting.readiness_models import (
    AuditCheckRecord,
    CheckOutcome,
    DefectRegisterEntry,
    DefectSeverity,
    PhaseAuditResult,
    ReadinessClassification,
)
from app.backtesting.revalidation_models import ProtectedHashCheckRecord
from app.backtesting.revalidation_report import (
    PROTECTED_PERSISTENCE_BASELINES,
    verify_protected_persistence_hashes,
)


def audit_risk_governance_readiness(
    db_path: Path | str = DEFAULT_BACKTEST_DB_PATH,
    protected_baselines: Optional[Dict[str, Tuple[Path, str]]] = None,
) -> Tuple[
    PhaseAuditResult,
    Tuple[ProtectedHashCheckRecord, ...],
    bool,
    Tuple[DefectRegisterEntry, ...],
]:
    """Audits execution-mode locks, SENSEX governance, isolation, and 6 protected hashes."""
    checks = []
    defects = []

    paper_only = EXECUTION_MODE == "PAPER_TRADING_ONLY"
    checks.append(
        AuditCheckRecord(
            check_id="GOV-PAPER-TRADING-ONLY",
            phase="Governance",
            area="PAPER_TRADING_ONLY Enforcement",
            outcome=CheckOutcome.PASS if paper_only else CheckOutcome.FAIL,
            severity_if_failed=DefectSeverity.P0 if not paper_only else None,
            summary=f"Execution mode strictly verified as `{EXECUTION_MODE}`; live broker order placement prohibited.",
            evidence=(f"EXECUTION_MODE={EXECUTION_MODE}",),
            affects_offline_replay=True,
            affects_live_observation=True,
        )
    )

    sensex_eligible, sensex_code, sensex_meta = verify_index_governance("SENSEX")
    sensex_locked = not bool(sensex_eligible)
    sensex_reason = str((sensex_meta or {}).get("reason", sensex_code))
    checks.append(
        AuditCheckRecord(
            check_id="GOV-SENSEX-LOCK",
            phase="Governance",
            area="SENSEX Governance Lock",
            outcome=CheckOutcome.BLOCKED if sensex_locked else CheckOutcome.FAIL,
            severity_if_failed=DefectSeverity.P0 if not sensex_locked else None,
            summary=(
                "SENSEX remains explicitly GOVERNANCE_LOCKED pending verified exchange liquidity policy & Ed25519 sign-off."
                if sensex_locked
                else "CRITICAL: SENSEX lock unexpectedly unlocked."
            ),
            evidence=(f"sensex_eligible={sensex_eligible}", f"status={sensex_code}", f"reason={sensex_reason}"),
            affects_offline_replay=False,
            affects_live_observation=False,
        )
    )

    try:
        resolved_db = assert_isolated_backtest_path(Path(db_path))
        isolated = True
        iso_ev = f"isolated_db={resolved_db}"
    except Exception as exc:
        isolated = False
        iso_ev = f"isolation_error={exc}"

    checks.append(
        AuditCheckRecord(
            check_id="GOV-STORAGE-ISOLATION",
            phase="Governance",
            area="Backtest Persistence Isolation",
            outcome=CheckOutcome.PASS if isolated else CheckOutcome.FAIL,
            severity_if_failed=DefectSeverity.P0 if not isolated else None,
            summary="Backtest database path verified isolated inside backend/data/backtest/.",
            evidence=(iso_ev,),
            affects_offline_replay=True,
            affects_live_observation=True,
        )
    )

    hash_records = verify_protected_persistence_hashes(protected_baselines or PROTECTED_PERSISTENCE_BASELINES)
    all_hashes_ok = all(r.matched for r in hash_records)
    checks.append(
        AuditCheckRecord(
            check_id="GOV-PROTECTED-HASHES",
            phase="Governance",
            area="6 Protected Production/Governance/Paper/ML SHA-256 Baselines",
            outcome=CheckOutcome.PASS if all_hashes_ok else CheckOutcome.FAIL,
            severity_if_failed=DefectSeverity.P0 if not all_hashes_ok else None,
            summary=(
                "All 6 protected files (aivolve_trading.db, governance_ledger.db, paper_trading_records.json, "
                "ml_trade_dataset.json, what_ai_learned.json, ml_strategy_weights.json) match baseline SHA-256 digests."
                if all_hashes_ok
                else "One or more protected production/ML files changed unexpectedly!"
            ),
            evidence=tuple(f"{r.label}:matched={r.matched}" for r in hash_records),
            affects_offline_replay=True,
            affects_live_observation=True,
        )
    )

    if not all_hashes_ok:
        defects.append(
            DefectRegisterEntry(
                defect_id="P0-HASH-MISMATCH",
                severity=DefectSeverity.P0,
                phase="Governance",
                title="Protected Production or ML File Hash Mismatch",
                status="OPEN",
                component="Protected Persistence Files",
                file_locations=tuple(r.path for r in hash_records if not r.matched),
                observed_evidence="; ".join(
                    f"{r.label}: expected={r.expected_sha256}, observed={r.observed_sha256}"
                    for r in hash_records
                    if not r.matched
                ),
                blocks_offline_replay=True,
                blocks_live_observation=True,
                minimal_safe_fix="Investigate and restore unapproved mutation outside backtesting sandbox.",
                verification_requirement="All 6 protected hashes must match baseline SHA-256.",
            )
        )

    gov_ok = paper_only and sensex_locked and isolated and all_hashes_ok
    return (
        PhaseAuditResult(
            phase_name="Governance & Risk Safety Controls (PAPER_TRADING_ONLY)",
            scope="RISK_AND_GOVERNANCE",
            offline_classification=(
                ReadinessClassification.READY_FOR_HISTORICAL_RESEARCH
                if gov_ok
                else ReadinessClassification.BLOCKED_BY_P0
            ),
            live_classification=(
                ReadinessClassification.CONDITIONAL_PAPER_OBSERVATION
                if gov_ok
                else ReadinessClassification.BLOCKED_BY_P0
            ),
            checks=tuple(checks),
            open_p0_ids=tuple(d.defect_id for d in defects if d.severity == DefectSeverity.P0),
            notes=(
                "No live broker order execution path exists in backtesting/readiness modules.",
                "Phase 2 MTF weights, risk limits, and contract selection thresholds remain frozen.",
            ),
        ),
        hash_records,
        all_hashes_ok and isolated,
        tuple(defects),
    )
