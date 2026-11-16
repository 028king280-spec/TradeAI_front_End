"""
AIVOLVE Phase 4, Step 4.8 — Strategy Evidence Review Orchestrator, Isolated Store & 17-Section Report.

Coordinates:
- Performance review (three isolated accounting domains)
- Regime, Session, Instrument, Timeframe, Direction, Entry Reason & Exit Reason breakdowns
- 8-pillar ICT/SMC & MTF confluence review (`UNAVAILABLE / NOT_CALIBRATED`)
- Signal quality, action funnel & chronological no-lookahead verification
- Governance verdicts, 6-file protected persistence SHA-256 verification, and isolated SQLite persistence
- Deterministic 17-section Markdown report rendering
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.backtesting.analytics_models import BucketDomainStats
from app.backtesting.configuration import (
    BacktestConfiguration,
    DEFAULT_BACKTEST_DATA_DIR,
    DEFAULT_BACKTEST_DB_PATH,
    EXECUTION_MODE,
    assert_isolated_backtest_path,
)
from app.backtesting.data_store import HistoricalDataStore
from app.backtesting.ict_smc_evidence_review import (
    review_ict_setup_breakdown,
    review_ict_smc_evidence,
)
from app.backtesting.regime_evidence_review import review_regime_evidence
from app.backtesting.revalidation_models import (
    DatasetTimeframeEligibility,
    HistoricalRevalidationRunResult,
    ProtectedHashCheckRecord,
)
from app.backtesting.revalidation_report import (
    PROTECTED_PERSISTENCE_BASELINES,
    build_18_combination_eligibility_matrix,
    verify_protected_persistence_hashes,
)
from app.backtesting.session_evidence_review import review_session_evidence
from app.backtesting.signal_quality_review import review_signal_quality
from app.backtesting.strategy_evidence_models import (
    BreakdownEvidenceRow,
    DomainPerformanceEvidence,
    EvidenceVerdict,
    RESEARCH_CLASSIFICATION_DISCLAIMER,
    STRATEGY_EVIDENCE_ENGINE_VERSION,
    StrategyEvidenceReviewReport,
    StrategyReviewConfig,
    deterministic_evidence_hash,
)
from app.backtesting.strategy_performance_review import (
    review_domain_performance,
    review_general_dimensions,
)
from app.backtesting.strategy_verdict_engine import evaluate_strategy_verdicts


def _fmt_opt(val: Optional[float], digits: int = 2) -> str:
    if val is None:
        return "N/A"
    return f"{val:.{digits}f}"


class StrategyEvidenceStore:
    """Strictly isolated SQLite persistence for Step 4.8 strategy evidence reviews."""

    def __init__(self, db_path: Path | str = DEFAULT_BACKTEST_DB_PATH) -> None:
        resolved = assert_isolated_backtest_path(Path(db_path))
        resolved.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = resolved
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS step4_8_strategy_reviews (
                    review_id TEXT PRIMARY KEY,
                    review_fingerprint TEXT NOT NULL,
                    overall_verdict TEXT NOT NULL,
                    sample_size_classification TEXT NOT NULL,
                    execution_mode TEXT NOT NULL,
                    created_at_utc TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    markdown_text TEXT NOT NULL
                );
                """
            )

    def load_step4_7_runs(
        self,
        revalidation_ids: Optional[Sequence[str]] = None,
    ) -> Tuple[HistoricalRevalidationRunResult, ...]:
        """Reads persisted Step 4.7 runs cleanly in deterministic chronological creation order."""
        with self._connect() as conn:
            tbl = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='step4_7_revalidation_runs'"
            ).fetchone()
            if tbl is None:
                return ()
            if revalidation_ids:
                placeholders = ",".join("?" for _ in revalidation_ids)
                rows = conn.execute(
                    f"SELECT payload_json FROM step4_7_revalidation_runs "
                    f"WHERE revalidation_id IN ({placeholders}) ORDER BY created_at_utc ASC, revalidation_id ASC",
                    tuple(revalidation_ids),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT payload_json FROM step4_7_revalidation_runs ORDER BY created_at_utc ASC, revalidation_id ASC"
                ).fetchall()
        return tuple(HistoricalRevalidationRunResult.model_validate_json(r["payload_json"]) for r in rows)

    def save_review(self, report: StrategyEvidenceReviewReport, markdown_text: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO step4_8_strategy_reviews (
                    review_id, review_fingerprint, overall_verdict,
                    sample_size_classification, execution_mode,
                    created_at_utc, payload_json, markdown_text
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report.review_id,
                    report.review_fingerprint,
                    report.verdict_summary.overall_verdict.value,
                    report.verdict_summary.overall_sample_size.value,
                    report.execution_mode,
                    report.created_at_utc,
                    report.model_dump_json(),
                    markdown_text,
                ),
            )

    def get_review(self, review_id: str) -> Optional[Tuple[StrategyEvidenceReviewReport, str]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json, markdown_text FROM step4_8_strategy_reviews WHERE review_id = ?",
                (review_id,),
            ).fetchone()
            if row is None:
                return None
            return StrategyEvidenceReviewReport.model_validate_json(row["payload_json"]), row["markdown_text"]


class StrategyPerformanceEvidenceEngine:
    """
    Additive Step 4.8 Strategy Performance & Evidence Review orchestrator.

    Evaluates accepted Step 4.4 / 4.5 / 4.6 / 4.7 outputs across all isolated accounting domains
    without modifying any strategy parameter, signal threshold, or frozen Phase 1-3 engine.
    """

    def __init__(
        self,
        *,
        review_config: Optional[StrategyReviewConfig] = None,
        backtest_config: Optional[BacktestConfiguration] = None,
        evidence_store: Optional[StrategyEvidenceStore] = None,
        data_store: Optional[HistoricalDataStore] = None,
    ) -> None:
        self.review_config = review_config or StrategyReviewConfig()
        resolved_db = (
            Path(self.review_config.storage_db_path)
            if self.review_config.storage_db_path is not None
            else DEFAULT_BACKTEST_DB_PATH
        )
        self.backtest_config = backtest_config or BacktestConfiguration(storage_db_path=str(resolved_db))
        self.evidence_store = evidence_store or StrategyEvidenceStore(db_path=self.backtest_config.storage_db_path)
        self.data_store = data_store or HistoricalDataStore(config=self.backtest_config)

    def review_from_store(
        self,
        *,
        revalidation_ids: Optional[Sequence[str]] = None,
        test_results_summary: Optional[Dict[str, Any]] = None,
        protected_baselines: Optional[Dict[str, Tuple[Path, str]]] = None,
        persist: bool = True,
        created_at_utc: Optional[datetime] = None,
    ) -> StrategyEvidenceReviewReport:
        runs = self.evidence_store.load_step4_7_runs(revalidation_ids=revalidation_ids)
        return self.review_from_runs(
            runs=runs,
            test_results_summary=test_results_summary,
            protected_baselines=protected_baselines,
            persist=persist,
            created_at_utc=created_at_utc,
        )

    def review_from_runs(
        self,
        *,
        runs: Sequence[HistoricalRevalidationRunResult],
        dataset_eligibility_matrix: Optional[Tuple[DatasetTimeframeEligibility, ...]] = None,
        test_results_summary: Optional[Dict[str, Any]] = None,
        protected_baselines: Optional[Dict[str, Tuple[Path, str]]] = None,
        persist: bool = True,
        created_at_utc: Optional[datetime] = None,
    ) -> StrategyEvidenceReviewReport:
        now_utc = (created_at_utc or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
        matrix = (
            dataset_eligibility_matrix
            if dataset_eligibility_matrix is not None
            else build_18_combination_eligibility_matrix(
                backtest_config=self.backtest_config,
                data_store=self.data_store,
            )
        )

        # 1. Domain-isolated performance & robustness digest
        domain_ev = review_domain_performance(runs=runs, config=self.review_config)

        # 2. Canonical strategy breakdowns
        general_dims = review_general_dimensions(runs=runs, config=self.review_config)
        regime_rows, causal_regime_verified = review_regime_evidence(runs=runs, config=self.review_config)
        session_rows, session_cov = review_session_evidence(runs=runs, config=self.review_config)
        ict_setup_rows = review_ict_setup_breakdown(runs=runs, config=self.review_config)

        # 3. 8-Pillar ICT/SMC & MTF review + signal quality review
        ict_review = review_ict_smc_evidence(runs=runs, config=self.review_config)
        sig_quality = review_signal_quality(runs=runs, config=self.review_config)

        # 4. Protected persistence SHA-256 verification
        hash_checks = verify_protected_persistence_hashes(protected_baselines or PROTECTED_PERSISTENCE_BASELINES)
        hashes_ok = all(h.matched for h in hash_checks)

        # 5. Collect explicit data quality & governance limitations without hiding gaps
        limits: List[str] = []
        partial_pairs = [
            f"{m.instrument} {m.timeframe} ({len(m.incomplete_sessions_excluded)} incomplete / {len(m.complete_sessions)} complete sessions)"
            for m in matrix
            if m.quality_status.value == "PARTIAL"
        ]
        if partial_pairs:
            limits.append(
                "Step 4.6 PARTIAL datasets cannot support full-session performance claims: "
                + "; ".join(partial_pairs[:8])
                + ("..." if len(partial_pairs) > 8 else "")
            )
        if session_cov["excluded_incomplete_sessions_total"] > 0:
            limits.append(
                f"Step 4.7 excluded {session_cov['excluded_incomplete_sessions_total']} incomplete/exceptional session(s) across evaluated runs "
                "(e.g., frozen Phase 1 market_calendar / FVG boundary on NIFTY 50 15m 2026-09-16 and post-2026-09-21 PARTIAL closing bars)."
            )
        limits.append(
            "Actual historical option OHLC/bid-ask/OI data remains BLOCKED; all SYNTHETIC_OPTION_INR_ONLY results use "
            "SYNTHETIC_MODELLED_OPTION_PNL (causal Black-Scholes approximations) and must never be presented as actual historical option fills."
        )
        limits.append(
            "SENSEX remains governance-locked across all backtesting layers per Step 4.2/4.6/4.7 rules."
        )
        limits.append(
            "Phase 3 ICT/SMC score remains UNAVAILABLE / NOT_CALIBRATED; Phase 2 MTF weights remain frozen and unchanged."
        )
        if not causal_regime_verified:
            limits.append("At least one eligible run lacked verified causal Step 4.5 regime indicator provenance or had zero trades.")
        if not hashes_ok:
            limits.append("CRITICAL: One or more protected production/governance/ML persistence SHA-256 checks failed.")

        for r in runs:
            for note in r.known_limitations:
                if "PARTIAL" in note or "excluded" in note.lower() or "LOCK" in note:
                    limits.append(f"[{r.revalidation_id}] {note}")
        dedup_limits = tuple(dict.fromkeys(limits))

        # 6. Governance Verdict Engine
        verdict_summary = evaluate_strategy_verdicts(
            runs=runs,
            domain_evidence=domain_ev,
            regime_rows=regime_rows,
            session_rows=session_rows,
            instrument_rows=general_dims["instrument"],
            ict_review=ict_review,
            signal_quality=sig_quality,
            config=self.review_config,
            known_limitations=dedup_limits,
        )

        # Deterministic run metadata summaries
        runs_summary: List[Dict[str, Any]] = []
        for r in runs:
            closed_by_dom = {dk: de.simulation_run.portfolio.trades_closed for dk, de in r.domain_evaluations.items()}
            runs_summary.append(
                {
                    "revalidation_id": r.revalidation_id,
                    "instrument": r.config.instrument,
                    "primary_timeframe": r.config.primary_timeframe,
                    "additional_timeframes": list(r.config.replay_timeframes),
                    "status": r.status.value,
                    "eligibility": r.eligibility_decision.eligibility.value,
                    "dataset_quality": r.eligibility_decision.overall_quality_status.value,
                    "dataset_fingerprint": r.eligibility_decision.composite_dataset_fingerprint,
                    "sessions_evaluated": r.summary_metrics.sessions_evaluated,
                    "excluded_incomplete_sessions": len(r.eligibility_decision.excluded_incomplete_sessions),
                    "total_signals": r.summary_metrics.total_signals_evaluated,
                    "eligible_signals": r.summary_metrics.eligible_signals_count,
                    "closed_trades_by_domain": closed_by_dom,
                    "run_fingerprint": r.run_fingerprint,
                }
            )

        data_sources = {
            "isolated_backtest_db_path": str(self.backtest_config.storage_db_path),
            "step4_7_runs_total": len(runs),
            "step4_7_runs_ids": [r.revalidation_id for r in runs],
            "step4_6_dataset_pairs_checked": len(matrix),
            "causal_regime_verified": causal_regime_verified,
            "session_coverage": session_cov,
        }
        isolation_evidence = {
            "isolated_backtest_db_path": str(self.backtest_config.storage_db_path),
            "production_db_untouched": all(h.matched for h in hash_checks if h.label == "aivolve_trading.db"),
            "governance_ledger_untouched": all(h.matched for h in hash_checks if h.label == "governance_ledger.db"),
            "paper_and_ml_artifacts_untouched": all(
                h.matched for h in hash_checks if h.label not in ("aivolve_trading.db", "governance_ledger.db")
            ),
            "all_6_protected_hashes_matched": hashes_ok,
            "sensex_governance_locked": True,
            "actual_historical_options_status": "BLOCKED",
            "execution_mode": EXECUTION_MODE,
        }

        fp_payload = {
            "version": STRATEGY_EVIDENCE_ENGINE_VERSION,
            "config": self.review_config.model_dump(mode="json"),
            "runs": [r.run_fingerprint for r in runs],
            "domain_verdicts": {k: v.verdict.value for k, v in domain_ev.items()},
            "overall_verdict": verdict_summary.overall_verdict.value,
            "signal_total": sig_quality.total_signals,
            "hashes": [h.observed_sha256 for h in hash_checks],
        }
        rep_fp = deterministic_evidence_hash(fp_payload)
        review_id = f"STE48-REVIEW-{rep_fp[:14]}"

        report = StrategyEvidenceReviewReport(
            review_id=review_id,
            review_fingerprint=rep_fp,
            config=self.review_config,
            data_sources=data_sources,
            dataset_eligibility_matrix=matrix,
            revalidation_runs_summary=tuple(runs_summary),
            domain_evidence=domain_ev,
            regime_evidence=regime_rows,
            session_evidence=session_rows,
            instrument_evidence=general_dims["instrument"],
            timeframe_evidence=general_dims["timeframe"],
            direction_evidence=general_dims["direction"],
            ict_setup_evidence=ict_setup_rows,
            entry_reason_evidence=general_dims["entry_reason"],
            exit_reason_evidence=general_dims["exit_reason"],
            ict_smc_evidence=ict_review,
            signal_quality=sig_quality,
            verdict_summary=verdict_summary,
            known_limitations=dedup_limits,
            test_results_summary=dict(test_results_summary or {}),
            protected_hash_checks=hash_checks,
            production_isolation_evidence=isolation_evidence,
            created_at_utc=now_utc,
        )

        if persist:
            md = render_strategy_evidence_markdown(report)
            self.evidence_store.save_review(report, md)
        return report

    def write_markdown_report(
        self,
        report: StrategyEvidenceReviewReport,
        output_path: Optional[Path | str] = None,
    ) -> Path:
        target = Path(output_path) if output_path is not None else (DEFAULT_BACKTEST_DATA_DIR / "step4_8_strategy_evidence_report.md")
        resolved = assert_isolated_backtest_path(target)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(render_strategy_evidence_markdown(report), encoding="utf-8")
        return resolved


def _format_bucket_stats_cell(stats: Optional[BucketDomainStats], closed_count: Optional[int] = None) -> str:
    n = closed_count if closed_count is not None else ((stats.winning_trades + stats.losing_trades) if stats is not None else 0)
    if stats is None or n == 0:
        return "0 trades"
    wr_txt = f"{stats.win_rate * 100.0:.2f}%" if stats.win_rate is not None else "N/A"
    return (
        f"n={n} | Net={stats.net_pnl:.2f} | WR={wr_txt} | "
        f"PF={_fmt_opt(stats.profit_factor)} | Exp={_fmt_opt(stats.expectancy)}"
    )


def _render_breakdown_table(rows: Sequence[BreakdownEvidenceRow], first_col: str) -> List[str]:
    if not rows:
        return ["_No rows observed for this dimension._", ""]
    lines = [
        f"| {first_col} | Signals | Eligible | BUY_CE | BUY_PE | WAIT | NO_TRADE | Missing Meta | INDEX_POINTS_ONLY | INDEX_POINTS_AND_EXPLICIT_INR (INR) | SYNTHETIC_OPTION_INR_ONLY (Modelled BS) | Sample | Verdict |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        lines.append(
            f"| {r.bucket_key} | {r.total_signals} | {r.eligible_signals} | {r.buy_ce_count} | {r.buy_pe_count} | "
            f"{r.wait_count} | {r.no_trade_count} | {r.missing_metadata_flag} | "
            f"{_format_bucket_stats_cell(r.points_stats, r.closed_trades_points_domain)} | "
            f"{_format_bucket_stats_cell(r.explicit_inr_stats, r.closed_trades_explicit_inr_domain)} | "
            f"{_format_bucket_stats_cell(r.synthetic_option_inr_stats, r.closed_trades_synthetic_option_domain)} | "
            f"{r.sample_size_classification.value} | {r.verdict.value} |"
        )
    lines.append("")
    return lines


def render_strategy_evidence_markdown(report: StrategyEvidenceReviewReport) -> str:
    """Renders a deterministic 17-section Step 4.8 Strategy Performance & Evidence Review report."""
    lines: List[str] = []
    vs = report.verdict_summary

    # 1. Executive Summary & Evidence Verdict
    lines.append(f"# AIVOLVE Phase 4 — Step 4.8 Strategy Performance & Evidence Review (`{report.review_id}`)")
    lines.append("")
    lines.append("## 1. Executive Summary & Evidence Verdict")
    lines.append(f"- **Execution Mode:** `{report.execution_mode}`")
    lines.append(f"- **Engine Version:** `{report.review_version}`")
    lines.append(f"- **Review Fingerprint:** `{report.review_fingerprint}`")
    lines.append(f"- **Overall Evidence Verdict:** **{vs.overall_verdict.value}**")
    lines.append(f"- **Overall Sample Size Classification:** `{vs.overall_sample_size.value}`")
    lines.append(f"- **Statistical Significance Claimed:** `{vs.statistical_significance_claimed}`")
    lines.append(f"- **Auto Optimization Performed:** `{vs.auto_optimization_performed}` | **Strategy Parameters Modified:** `{vs.strategy_parameters_modified}`")
    lines.append(f"- **Disclaimer:** {report.research_classification_disclaimer}")
    lines.append("- **Key Verdict Reasons:**")
    for reason in vs.overall_reasons:
        lines.append(f"  - {reason}")
    lines.append("")

    # 2. Data Sources & Step 4.6 Eligibility Matrix
    lines.append("## 2. Data Sources & Step 4.6 Eligibility Matrix")
    lines.append(f"- **Isolated Backtest DB:** `{report.data_sources.get('isolated_backtest_db_path', 'N/A')}`")
    lines.append(f"- **Step 4.7 Runs Evaluated:** `{report.data_sources.get('step4_7_runs_total', 0)}`")
    lines.append("")
    lines.append("| Instrument | Timeframe | Quality | Eligibility | Complete Sessions | Incomplete Excluded | Total Bars |")
    lines.append("| --- | --- | --- | --- | ---: | ---: | ---: |")
    for m in report.dataset_eligibility_matrix:
        lines.append(
            f"| {m.instrument} | {m.timeframe} | {m.quality_status.value} | {m.eligibility.value} | "
            f"{len(m.complete_sessions)} | {len(m.incomplete_sessions_excluded)} | {m.total_bars} |"
        )
    lines.append("")

    # 3. Revalidation Runs Reviewed
    lines.append("## 3. Step 4.7 Revalidation Runs Reviewed")
    lines.append("| Revalidation ID | Instrument | Primary TF | MTF Stack | Status | Eligibility | Sessions Eval | Excl Sessions | Signals | Eligible | Closed (Pts / ExpINR / SynBS) |")
    lines.append("| --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |")
    for rs in report.revalidation_runs_summary:
        cb = rs.get("closed_trades_by_domain", {})
        closed_txt = (
            f"{cb.get('INDEX_POINTS_ONLY', 0)} / "
            f"{cb.get('INDEX_POINTS_AND_EXPLICIT_INR', 0)} / "
            f"{cb.get('SYNTHETIC_OPTION_INR_ONLY', 0)}"
        )
        lines.append(
            f"| {rs['revalidation_id']} | {rs['instrument']} | {rs['primary_timeframe']} | "
            f"{','.join(rs.get('additional_timeframes', [])) or '-'} | {rs['status']} | {rs['eligibility']} | "
            f"{rs['sessions_evaluated']} | {rs['excluded_incomplete_sessions']} | {rs['total_signals']} | "
            f"{rs['eligible_signals']} | {closed_txt} |"
        )
    lines.append("")

    # 4. Domain-Isolated Performance Overview
    lines.append("## 4. Domain-Isolated Performance Overview (Never Combined Across Domains)")
    lines.append("| Accounting Domain | Provenance | Synthetic | Actual Hist Options | Closed Trades | Win Rate % | Net PnL | Profit Factor | Expectancy | Max DD | Sample Size | Verdict |")
    lines.append("| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |")
    for dk, dev in report.domain_evidence.items():
        if dev.accounting_unit_mode.value == "INDEX_POINTS_ONLY" and dev.points_metrics and dev.points_risk:
            m, rk = dev.points_metrics, dev.points_risk
            unit_sfx = " pts"
        elif dev.inr_metrics and dev.inr_risk:
            m, rk = dev.inr_metrics, dev.inr_risk
            unit_sfx = " INR"
        else:
            m, rk, unit_sfx = None, None, ""
        wr = f"{_fmt_opt(m.win_rate_pct)}%" if m and m.win_rate_pct is not None else "N/A"
        net = f"{_fmt_opt(m.net_pnl)}{unit_sfx}" if m and m.net_pnl is not None else "N/A"
        pf = _fmt_opt(m.profit_factor) if m else "N/A"
        exp = f"{_fmt_opt(m.expectancy)}{unit_sfx}" if m and m.expectancy is not None else "N/A"
        dd = f"{_fmt_opt(rk.max_drawdown)}{unit_sfx}" if rk and rk.max_drawdown is not None else "N/A"
        lines.append(
            f"| {dk} | {dev.provenance_label} | {dev.is_synthetic_modelled} | {dev.actual_historical_options_status} | "
            f"{dev.trades_closed} | {wr} | {net} | {pf} | {exp} | {dd} | "
            f"{dev.sample_size_classification.value} | {dev.verdict.value} |"
        )
    lines.append("")

    # 5. Detailed Accounting Domain Metrics, Costs, Slippage & Drawdown
    lines.append("## 5. Detailed Domain Metrics, Transaction Costs, Slippage & Drawdown")
    for dk, dev in report.domain_evidence.items():
        lines.append(f"### 5.{list(report.domain_evidence.keys()).index(dk) + 1} `{dk}` (`{dev.provenance_label}`)")
        lines.append(
            f"- Eligible Runs: `{dev.eligible_runs_count}` (`{', '.join(dev.revalidation_run_ids)}`) | "
            f"Sessions: `{dev.sessions_evaluated}` | Signals: `{dev.total_signals}` | "
            f"Closed Trades: `{dev.trades_closed}` | Freq/Session: `{dev.trade_frequency_per_session:.4f}`"
        )
        lines.append(
            f"- Consecutive Wins/Losses: `{dev.max_consecutive_wins}` / `{dev.max_consecutive_losses}` | "
            f"Avg Hold (min): `{_fmt_opt(dev.average_holding_duration_minutes)}` | Ledger Reconciled: `{dev.reconciliation_verified}`"
        )
        if dev.points_metrics and dev.points_risk:
            pm, pr = dev.points_metrics, dev.points_risk
            lines.append(
                f"- **Index Points:** Gross={_fmt_opt(pm.gross_pnl)} | Total Slippage/Costs={_fmt_opt(pm.total_costs)} | "
                f"Net={_fmt_opt(pm.net_pnl)} | AvgWin={_fmt_opt(pm.average_win)} | AvgLoss={_fmt_opt(pm.average_loss)} | "
                f"R:R={_fmt_opt(pm.average_risk_reward)} | PF={_fmt_opt(pm.profit_factor)} | Expectancy={_fmt_opt(pm.expectancy)} | "
                f"MaxDD={_fmt_opt(pr.max_drawdown)} | Recovery={_fmt_opt(pr.recovery_factor)}"
            )
        if dev.inr_metrics and dev.inr_risk:
            im, ir = dev.inr_metrics, dev.inr_risk
            lines.append(
                f"- **INR ({'SYNTHETIC BS RESEARCH ONLY' if dev.is_synthetic_modelled else 'EXPLICIT MULTIPLIER'}):** "
                f"Gross={_fmt_opt(im.gross_pnl)} | Total Slippage/Costs={_fmt_opt(im.total_costs)} | "
                f"Net={_fmt_opt(im.net_pnl)} ({_fmt_opt(im.net_return_pct)}%) | AvgWin={_fmt_opt(im.average_win)} | "
                f"AvgLoss={_fmt_opt(im.average_loss)} | R:R={_fmt_opt(im.average_risk_reward)} | PF={_fmt_opt(im.profit_factor)} | "
                f"Expectancy={_fmt_opt(im.expectancy)} | MaxDD={_fmt_opt(ir.max_drawdown)} ({_fmt_opt(ir.max_drawdown_pct)}%) | "
                f"Recovery={_fmt_opt(ir.recovery_factor)}"
            )
        lines.append(f"- Verdict: `{dev.verdict.value}` ({'; '.join(dev.reasons)})")
        lines.append("")

    # 6. Chronological IS/OOS & Robustness
    lines.append("## 6. Chronological IS / OOS Split & Step 4.5 Robustness Digests")
    for dk, dev in report.domain_evidence.items():
        lines.append(f"### `{dk}`")
        if dev.is_oos_comparisons:
            for iso in dev.is_oos_comparisons:
                is_pnl = iso.is_net_pnl_points if iso.is_net_pnl_points is not None else iso.is_net_pnl_inr
                oos_pnl = iso.oos_net_pnl_points if iso.oos_net_pnl_points is not None else iso.oos_net_pnl_inr
                lines.append(
                    f"- IS/OOS Split (`{iso.is_period or 'N/A'}` vs `{iso.oos_period or 'N/A'}`, "
                    f"NoLookahead=`{iso.no_lookahead_verified}`): "
                    f"IS trades={iso.is_closed_trades}, OOS trades={iso.oos_closed_trades}, "
                    f"IS Net={_fmt_opt(is_pnl)}, OOS Net={_fmt_opt(oos_pnl)}"
                )
        for dg in dev.robustness_digests:
            lines.append(
                f"- Step 4.5 Digest: Overall=`{dg.overall_status.value}`, Slippage=`{dg.slippage_status.value}`, "
                f"Cost=`{dg.transaction_cost_status.value}`, Regime=`{dg.regime_robustness_status.value}`, "
                f"OOS=`{dg.oos_status.value}` (no_lookahead=`{dg.oos_no_lookahead_verified}`), "
                f"MC=`{dg.monte_carlo_status.value}` ({dg.monte_carlo_iterations} iters, P(>0)={_fmt_opt(dg.mc_probability_positive_net_pnl, 4)}), "
                f"AutoOpt=`{dg.auto_optimization_performed}`"
            )
        lines.append("")

    # 7. Market Regime Performance
    lines.append("## 7. Market Regime Breakdown")
    lines.extend(_render_breakdown_table(report.regime_evidence, "Market Regime"))

    # 8. Trading Session Performance
    lines.append("## 8. Trading Session Breakdown")
    cov = report.data_sources.get("session_coverage", {})
    lines.append(
        f"- Sessions Evaluated Total: `{cov.get('sessions_evaluated_total', 0)}` | "
        f"Excluded Incomplete Sessions: `{cov.get('excluded_incomplete_sessions_total', 0)}`"
    )
    lines.append("")
    lines.extend(_render_breakdown_table(report.session_evidence, "Trading Session"))

    # 9. Instrument Performance
    lines.append("## 9. Instrument Breakdown & SENSEX Governance Lockout")
    lines.extend(_render_breakdown_table(report.instrument_evidence, "Instrument"))

    # 10. Timeframe Performance
    lines.append("## 10. Timeframe Breakdown")
    lines.extend(_render_breakdown_table(report.timeframe_evidence, "Timeframe"))

    # 11. Direction, Entry & Exit Reasons
    lines.append("## 11. Direction, Entry Reason & Exit Reason Analysis")
    lines.append("### 11.1 Direction")
    lines.extend(_render_breakdown_table(report.direction_evidence, "Direction"))
    lines.append("### 11.2 Entry Reason")
    lines.extend(_render_breakdown_table(report.entry_reason_evidence, "Entry Reason"))
    lines.append("### 11.3 Exit Reason")
    lines.extend(_render_breakdown_table(report.exit_reason_evidence, "Exit Reason"))

    # 12. ICT/SMC & MTF 8-Pillar Evidence
    ict = report.ict_smc_evidence
    lines.append("## 12. ICT / SMC & MTF Confluence 8-Pillar Evidence")
    lines.append(
        f"- **ICT Score:** `{ict.ict_score}` (`{ict.ict_score_status} / {ict.ict_calibration_status}`) | "
        f"**Weights/Thresholds Invented:** `{ict.weights_or_thresholds_invented}`"
    )
    lines.append(
        f"- Signals Inspected: `{ict.total_signals_inspected}` | Eligible Signals: `{ict.total_eligible_signals_inspected}` | "
        f"Verdict: `{ict.verdict.value}`"
    )
    lines.append("")
    lines.append("| Pillar | Events Observed | Bullish | Bearish | Conflicts | Signals Present | Eligible Signals | Closed Trades | Points Stats | Explicit INR Stats | Synthetic BS INR Stats | Sample | Verdict |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | --- | --- |")
    for p in ict.pillars:
        lines.append(
            f"| {p.pillar_name} | {p.events_observed_count} | {p.bullish_events_count} | {p.bearish_events_count} | "
            f"{p.conflicts_observed_count} | {p.signals_present_count} | {p.eligible_signals_present_count} | "
            f"{p.closed_trades_count} | {_format_bucket_stats_cell(p.points_stats, p.closed_trades_count)} | "
            f"{_format_bucket_stats_cell(p.explicit_inr_stats, p.closed_trades_count)} | "
            f"{_format_bucket_stats_cell(p.synthetic_option_inr_stats, p.closed_trades_count)} | "
            f"{p.sample_size_classification.value} | {p.verdict.value} |"
        )
    lines.append("")

    # 13. ICT Setup Alignment & Conflict Profile
    lines.append("## 13. ICT / SMC Setup Alignment & Conflict Profile")
    lines.append(f"- **Alignment Distribution:** `{ict.alignment_distribution}`")
    lines.append(f"- **Conflict Distribution:** `{ict.conflict_type_distribution}`")
    lines.append("")
    lines.extend(_render_breakdown_table(report.ict_setup_evidence, "Phase 3 Alignment"))

    # 14. Signal Quality & Chronological No-Lookahead Audit
    sq = report.signal_quality
    lines.append("## 14. Signal Quality Funnel, NO_TRADE Frequency & Chronology Audit")
    lines.append(f"- Total Signals: `{sq.total_signals}` | Action Distribution: `{sq.action_distribution}`")
    lines.append(
        f"- Eligible: `{sq.eligible_signals}` (`{sq.qualification_rate_pct:.2f}%`) | "
        f"NO_TRADE Rate: `{sq.no_trade_rate_pct:.2f}%` | WAIT Rate: `{sq.wait_rate_pct:.2f}%`"
    )
    lines.append(f"- Executed Points Trades: `{sq.executed_trades_count_points}` | Unexecuted Eligible Signals: `{sq.unexecuted_eligible_signals_count}`")
    lines.append(f"- Chronological No-Lookahead Verified: `{sq.chronological_no_lookahead_verified}` (Violations: `{sq.chronology_violations_count}`)")
    lines.append(f"- Missing Metadata Counts: `{sq.missing_metadata_counts}`")
    lines.append(f"- Rejection Reasons: `{sq.rejection_reason_distribution}`")
    lines.append("")

    # 15. Strategy Verdict Summary & Dimension Assessments
    lines.append("## 15. Strategy Verdict Summary & Per-Dimension Assessments")
    assessments = [
        *vs.instrument_assessments,
        vs.regime_assessment,
        vs.session_assessment,
        vs.ict_smc_assessment,
        vs.risk_and_drawdown_assessment,
    ]
    lines.append("| Assessment Area | Verdict | Sample Size | Stat. Sig. Claimed | Key Reasons |")
    lines.append("| --- | --- | --- | --- | --- |")
    for a in assessments:
        lines.append(
            f"| {a.area} | {a.verdict.value} | {a.sample_size_classification.value} | "
            f"{a.statistical_significance_claimed} | {'; '.join(a.reasons[:2])} |"
        )
    lines.append("")

    # 16. Known Data Quality & Sample-Size Limitations
    lines.append("## 16. Known Data Quality & Sample-Size Limitations")
    for lim in vs.data_quality_limitations:
        lines.append(f"- [Data Quality] {lim}")
    for lim in vs.sample_size_limitations:
        lines.append(f"- [Sample Size] {lim}")
    lines.append("")

    # 17. Persistence Isolation, Protected Hashes & Test Verification
    lines.append("## 17. Persistence Isolation, Protected 6-File SHA-256 Hashes & Test Summary")
    lines.append(f"- Isolation Summary: `{report.production_isolation_evidence}`")
    lines.append(f"- Automated Test Results Summary: `{report.test_results_summary}`")
    lines.append("")
    lines.append("| Protected File | Exists | SHA-256 Matched | Observed SHA-256 |")
    lines.append("| --- | --- | --- | --- |")
    for hc in report.protected_hash_checks:
        lines.append(f"| {hc.label} | {hc.exists} | {hc.matched} | `{hc.observed_sha256}` |")
    lines.append("")
    return "\n".join(lines)

