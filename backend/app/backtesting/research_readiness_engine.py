"""
AIVOLVE Phase 4, Step 4.9 — Research Readiness Engine & Isolated SQLite Store.

Computes bottom-up readiness classifications without manual overrides or P0 bypassing,
separates Offline Historical Replay from Live Paper Observation, persists immutable snapshots
strictly inside `backend/data/backtest/backtest_foundation.db`, and drives Step 4.9 report generation.
"""

from __future__ import annotations

from contextlib import contextmanager
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence, Tuple

from app.backtesting.configuration import (
    DEFAULT_BACKTEST_DB_PATH,
    SUPPORTED_INDICES,
    assert_isolated_backtest_path,
)
from app.backtesting.paper_observation_gate import PaperObservationGate
from app.backtesting.phase_readiness_auditor import CrossPhaseAuditBundle, PhaseReadinessAuditor
from app.backtesting.readiness_models import (
    DefectSeverity,
    ICT_SCORE_GOVERNANCE_STATUS,
    InstrumentReadinessDecision,
    LiveFeedObservationProbe,
    ReadinessClassification,
    ResearchReadinessConfig,
    ResearchReadinessReport,
    deterministic_readiness_hash,
)
from app.backtesting.revalidation_models import EligibilityClassification
from app.backtesting.strategy_evidence_models import StrategyEvidenceReviewReport


class ResearchReadinessStore:
    """Strictly isolated SQLite persistence for Step 4.9 research readiness snapshots."""

    def __init__(self, db_path: Path | str = DEFAULT_BACKTEST_DB_PATH) -> None:
        resolved = assert_isolated_backtest_path(Path(db_path))
        resolved.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = resolved
        self._init_schema()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        try:
            conn.row_factory = sqlite3.Row
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS step4_9_readiness_reports (
                    readiness_id TEXT PRIMARY KEY,
                    report_fingerprint TEXT NOT NULL,
                    overall_classification TEXT NOT NULL,
                    offline_classification TEXT NOT NULL,
                    live_classification TEXT NOT NULL,
                    strategy_evidence_classification TEXT NOT NULL,
                    open_p0_count INTEGER NOT NULL,
                    open_p1_count INTEGER NOT NULL,
                    open_p2_count INTEGER NOT NULL,
                    generated_at_utc TEXT NOT NULL,
                    report_json TEXT NOT NULL
                );
                """
            )

    def save_report(self, report: ResearchReadinessReport) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO step4_9_readiness_reports (
                    readiness_id, report_fingerprint, overall_classification,
                    offline_classification, live_classification,
                    strategy_evidence_classification, open_p0_count,
                    open_p1_count, open_p2_count, generated_at_utc, report_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report.readiness_id,
                    report.report_fingerprint,
                    report.overall_classification.value,
                    report.offline_historical_replay_classification.value,
                    report.live_market_observation_classification.value,
                    report.strategy_evidence_classification.value,
                    report.open_p0_count,
                    report.open_p1_count,
                    report.open_p2_count,
                    report.generated_at_utc,
                    report.model_dump_json(),
                ),
            )

    def load_report(self, readiness_id: str) -> Optional[ResearchReadinessReport]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT report_json FROM step4_9_readiness_reports WHERE readiness_id = ?",
                (readiness_id,),
            ).fetchone()
        if row is None:
            return None
        return ResearchReadinessReport.model_validate_json(row["report_json"])

    def load_latest_report(self) -> Optional[ResearchReadinessReport]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT report_json FROM step4_9_readiness_reports ORDER BY generated_at_utc DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        return ResearchReadinessReport.model_validate_json(row["report_json"])


class ResearchReadinessEngine:
    """
    Step 4.9 Final Research Readiness Gate & Market Observation Preparation Engine.

    All classifications are derived strictly bottom-up from underlying checks.
    """

    def __init__(
        self,
        config: Optional[ResearchReadinessConfig] = None,
        db_path: Path | str = DEFAULT_BACKTEST_DB_PATH,
    ) -> None:
        self.config = config or ResearchReadinessConfig()
        self.db_path = assert_isolated_backtest_path(Path(db_path))

    def _derive_instrument_decisions(
        self,
        bundle: CrossPhaseAuditBundle,
        live_class: ReadinessClassification,
        evidence_class: ReadinessClassification,
    ) -> Tuple[InstrumentReadinessDecision, ...]:
        matrix = bundle.phase4_context.get("matrix", ())
        decisions: List[InstrumentReadinessDecision] = []

        for idx in SUPPORTED_INDICES:
            rows = [r for r in matrix if r.instrument == idx]
            verified_tfs = tuple(
                r.timeframe
                for r in rows
                if r.eligibility == EligibilityClassification.VERIFIED_FULL_SESSION_ELIGIBLE
            )
            partial_tfs = tuple(
                r.timeframe
                for r in rows
                if r.eligibility == EligibilityClassification.PARTIAL_RESEARCH_ONLY
            )

            if idx == "SENSEX":
                decisions.append(
                    InstrumentReadinessDecision(
                        instrument="SENSEX",
                        historical_replay_classification=ReadinessClassification.GOVERNANCE_LOCKED,
                        live_observation_classification=ReadinessClassification.GOVERNANCE_LOCKED,
                        evidence_classification=ReadinessClassification.GOVERNANCE_LOCKED,
                        verified_timeframes=verified_tfs,
                        partial_timeframes=partial_tfs,
                        governance_locked=True,
                        blocking_reasons=(
                            "SENSEX remains permanently GOVERNANCE_LOCKED pending exchange liquidity policy & Ed25519 sign-off.",
                        ),
                    )
                )
                continue

            hist_cls = (
                ReadinessClassification.READY_FOR_OFFLINE_REPLAY
                if verified_tfs and bundle.isolation_verified and bundle.protected_hashes_all_matched
                else ReadinessClassification.INSUFFICIENT_EVIDENCE
            )
            blocking = []
            if live_class == ReadinessClassification.BLOCKED_BY_P0:
                blocking.append("Blocked by open Phase 1 live-data P0 defect(s) or closed/unauthenticated stream.")
            if evidence_class == ReadinessClassification.INSUFFICIENT_EVIDENCE:
                blocking.append("Strategy closed-trade sample remains insufficient (< 30 trades).")

            decisions.append(
                InstrumentReadinessDecision(
                    instrument=idx,
                    historical_replay_classification=hist_cls,
                    live_observation_classification=live_class,
                    evidence_classification=evidence_class,
                    verified_timeframes=verified_tfs,
                    partial_timeframes=partial_tfs,
                    governance_locked=False,
                    blocking_reasons=tuple(blocking),
                )
            )
        return tuple(decisions)

    def evaluate(
        self,
        probe: Optional[LiveFeedObservationProbe] = None,
        resolved_defect_ids: Optional[Sequence[str]] = None,
        latest_review: Optional[StrategyEvidenceReviewReport] = None,
        protected_baselines: Optional[Dict[str, Tuple[Path, str]]] = None,
        persist: bool = True,
    ) -> ResearchReadinessReport:
        auditor = PhaseReadinessAuditor()
        bundle = auditor.run_all(
            db_path=self.db_path,
            observation_session_date=self.config.observation_session_date,
            probe=probe,
            resolved_defect_ids=resolved_defect_ids,
            latest_review=latest_review,
            protected_baselines=protected_baselines,
        )

        open_p0 = [d for d in bundle.defect_register if d.severity == DefectSeverity.P0 and d.status == "OPEN"]
        open_p1 = [d for d in bundle.defect_register if d.severity == DefectSeverity.P1 and d.status == "OPEN"]
        open_p2 = [d for d in bundle.defect_register if d.severity == DefectSeverity.P2 and d.status == "OPEN"]

        p4_ctx = bundle.phase4_context
        offline_replay_ok = (
            int(p4_ctx.get("verified_count", 0)) > 0
            and int(p4_ctx.get("reval_run_count", 0)) > 0
            and bundle.isolation_verified
            and bundle.protected_hashes_all_matched
            and not any(d.blocks_offline_replay for d in open_p0)
        )
        offline_class = (
            ReadinessClassification.READY_FOR_OFFLINE_REPLAY
            if offline_replay_ok
            else ReadinessClassification.BLOCKED_BY_P0
        )

        # Live paper observation track classification (strictly fail-closed)
        live_p0_blockers = [d for d in open_p0 if d.blocks_live_observation]
        p = bundle.probe
        if (
            live_p0_blockers
            or not p.exchange_open
            or not p.rest_authenticated
            or not p.websocket_connected
            or p.usable_verified_ticks <= 0
        ):
            live_class = ReadinessClassification.BLOCKED_BY_P0
        else:
            live_class = ReadinessClassification.CONDITIONAL_PAPER_OBSERVATION

        evidence_class = p4_ctx["strategy_evidence_classification"]

        # Overall platform classification: cannot report READY if open P0 exists!
        if open_p0:
            overall_class = ReadinessClassification.BLOCKED_BY_P0
        elif evidence_class == ReadinessClassification.INSUFFICIENT_EVIDENCE:
            overall_class = (
                ReadinessClassification.CONDITIONAL_PAPER_OBSERVATION
                if live_class == ReadinessClassification.CONDITIONAL_PAPER_OBSERVATION
                else ReadinessClassification.READY_FOR_HISTORICAL_RESEARCH
            )
        else:
            overall_class = live_class

        obs_plan = PaperObservationGate().build_plan(
            probe=p,
            defect_register=bundle.defect_register,
            offline_classification=offline_class,
            target_session_date=self.config.observation_session_date,
        )

        instrument_decisions = self._derive_instrument_decisions(
            bundle=bundle,
            live_class=live_class,
            evidence_class=evidence_class,
        )

        review = p4_ctx.get("review")
        review_id = review.review_id if review is not None else None
        ready_summary = (
            f"Offline Historical Research / Replay: {offline_class.value} ({p4_ctx['verified_count']} verified matrix cells, {p4_ctx['reval_run_count']} Step 4.7 runs).",
            f"Live Market Observation (13 Nov 2026): {live_class.value} (open P0={len(open_p0)}, exchange_open={p.exchange_open}, ws_connected={p.websocket_connected}, usable_ticks={p.usable_verified_ticks}).",
            f"Strategy Proof / Sample Depth: {evidence_class.value} ({p4_ctx['closed_trade_count_total']} closed trades, Step 4.8 review={review_id}).",
            f"ICT/SMC Predictive Score: {ICT_SCORE_GOVERNANCE_STATUS}.",
            "SENSEX Index Scope: GOVERNANCE_LOCKED.",
        )

        if open_p0:
            final_rec = (
                "HOLD LIVE OBSERVATION OPENING: Historical offline research replay is verified "
                "(READY_FOR_OFFLINE_REPLAY), and Strategy Evidence remains INSUFFICIENT_EVIDENCE "
                "(5 closed synthetic-BS trades). Live market observation for Friday 13 Nov 2026 is "
                "BLOCKED_BY_P0 until authorized Phase 1 fixes resolve open P0 defects (P0-1..P0-5) "
                "and live WebSocket streams verified usable ticks during an open NSE session under "
                "PAPER_TRADING_ONLY."
            )
        else:
            final_rec = (
                f"CONDITIONAL PAPER OBSERVATION PERMITTED under PAPER_TRADING_ONLY for {self.config.observation_session_date} "
                "while Strategy Evidence remains INSUFFICIENT_EVIDENCE until >= 30 genuine closed trades are collected."
            )

        fp_payload = {
            "version": self.config.readiness_version,
            "observation_session_date": self.config.observation_session_date,
            "overall": overall_class.value,
            "offline": offline_class.value,
            "live": live_class.value,
            "evidence": evidence_class.value,
            "defects": [(d.defect_id, d.severity.value, d.status) for d in bundle.defect_register],
            "probe": p.model_dump(),
            "hashes": [(h.label, h.matched, h.observed_sha256) for h in bundle.protected_hash_checks],
            "review_id": review_id,
        }
        report_fingerprint = deterministic_readiness_hash(fp_payload)
        readiness_id = f"STE49-GATE-{report_fingerprint[:14]}"
        generated_at = datetime.now(timezone.utc).isoformat()

        report = ResearchReadinessReport(
            readiness_id=readiness_id,
            report_fingerprint=report_fingerprint,
            generated_at_utc=generated_at,
            overall_classification=overall_class,
            offline_historical_replay_classification=offline_class,
            live_market_observation_classification=live_class,
            strategy_evidence_classification=evidence_class,
            phase_audits=bundle.phase_audits,
            instrument_decisions=instrument_decisions,
            defect_register=bundle.defect_register,
            open_p0_count=len(open_p0),
            open_p1_count=len(open_p1),
            open_p2_count=len(open_p2),
            step4_8_review_id=review_id,
            step4_7_run_count=int(p4_ctx.get("reval_run_count", 0)),
            closed_trade_count_total=int(p4_ctx.get("closed_trade_count_total", 0)),
            verified_matrix_combinations=int(p4_ctx.get("verified_count", 0)),
            partial_matrix_combinations=int(p4_ctx.get("partial_count", 0)),
            locked_matrix_combinations=int(p4_ctx.get("locked_count", 0)),
            missing_options_history_status=str(p4_ctx.get("options_capability_status", "OPTION_HISTORY_BLOCKED")),
            probe_snapshot=p,
            observation_plan=obs_plan,
            protected_hash_checks=bundle.protected_hash_checks,
            protected_hashes_all_matched=bundle.protected_hashes_all_matched,
            isolation_verified=bundle.isolation_verified,
            ready_conditions_summary=ready_summary,
            final_recommendation=final_rec,
        )

        if persist:
            ResearchReadinessStore(self.db_path).save_report(report)

        return report

