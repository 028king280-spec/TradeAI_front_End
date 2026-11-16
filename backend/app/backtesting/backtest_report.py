"""
AIVOLVE Phase 4 Step 4.4 — Backtest Report Orchestrator, Isolated Analytics Store & Markdown Renderer.

Consumes persisted Step 4.3 `SimulationRunResult` artifacts (and optional Step 4.2
`ReplayRunRecord`) to assemble reproducible `BacktestAnalyticsReport` objects strictly in
`PAPER_TRADING_ONLY` mode inside isolated backtesting storage.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Literal, Optional, Sequence, Tuple

from app.backtesting.analytics_models import (
    ANALYTICS_VERSION,
    AccountingModeSection,
    AnalyticsStatus,
    BacktestAnalyticsReport,
    DEFAULT_MIN_TRADES_FOR_SIGNIFICANCE,
    DatasetProvenanceSection,
    PerformanceSummaryAnalytics,
    ReproducibilityMetadata,
    RiskSummaryAnalytics,
    RunConfigurationSection,
    StrategyAnalyticsResult,
    TimeSeriesAnalyticsResult,
    TradeDistributionSummary,
    TradeEvaluationMetadata,
    WalkForwardResult,
    WalkForwardWindowSpec,
    domain_has_inr,
    domain_has_points,
    validate_run_domain_integrity,
)
from app.backtesting.configuration import (
    BacktestConfiguration,
    DEFAULT_BACKTEST_DB_PATH,
    EXECUTION_MODE,
    assert_isolated_backtest_path,
)
from app.backtesting.cost_model import COST_MODEL_VERSION
from app.backtesting.data_store import HistoricalDataStore
from app.backtesting.models import ReplayRunRecord
from app.backtesting.performance_analytics import PerformanceAnalyticsEngine
from app.backtesting.risk_analytics import RiskAnalyticsEngine
from app.backtesting.simulation_models import (
    AccountingUnitMode,
    SimulationRunResult,
    SimulationSignal,
    SimulationStatus,
)
from app.backtesting.strategy_analytics import StrategyAnalyticsEngine
from app.backtesting.time_series_analytics import TimeSeriesAnalyticsEngine
from app.backtesting.trade_lifecycle import deterministic_id
from app.backtesting.walk_forward import WalkForwardEvaluator


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def compute_report_fingerprint(payload: Dict[str, Any]) -> str:
    """Computes deterministic 32-char upper-hex SHA-256 fingerprint over structured report sections."""
    digest = hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()[:32].upper()
    return digest


class BacktestAnalyticsStore:
    """Isolated SQLite persistence for Step 4.4 `BacktestAnalyticsReport` artifacts."""

    def __init__(
        self,
        db_path: Optional[Path | str] = None,
        *,
        config: Optional[BacktestConfiguration] = None,
    ) -> None:
        cfg = config or BacktestConfiguration()
        raw_path = db_path if db_path is not None else cfg.storage_db_path
        self.db_path = assert_isolated_backtest_path(raw_path or DEFAULT_BACKTEST_DB_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS analytics_reports (
                    report_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    report_fingerprint TEXT NOT NULL,
                    analytics_version TEXT NOT NULL,
                    accounting_unit_mode TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    instrument TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    historical_date_range TEXT NOT NULL,
                    status TEXT NOT NULL,
                    is_synthetic_modelled INTEGER NOT NULL,
                    report_json TEXT NOT NULL,
                    created_at_utc TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_analytics_reports_run_id
                ON analytics_reports (run_id, created_at_utc)
                """
            )

    def save_report(self, report: BacktestAnalyticsReport) -> None:
        assert_isolated_backtest_path(self.db_path)
        cfg = report.run_configuration_and_fingerprint
        prov = report.dataset_provenance
        acct = report.accounting_mode
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO analytics_reports (
                    report_id, run_id, report_fingerprint, analytics_version,
                    accounting_unit_mode, mode, instrument, timeframe,
                    historical_date_range, status, is_synthetic_modelled,
                    report_json, created_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report.report_id,
                    cfg.run_id,
                    report.report_fingerprint,
                    report.analytics_version,
                    acct.accounting_unit_mode.value,
                    cfg.mode.value,
                    cfg.instrument,
                    cfg.timeframe,
                    prov.historical_date_range,
                    report.status.value,
                    1 if prov.is_synthetic_modelled else 0,
                    report.model_dump_json(),
                    report.created_at_utc.isoformat(),
                ),
            )

    def get_report(self, report_id: str) -> Optional[BacktestAnalyticsReport]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT report_json FROM analytics_reports WHERE report_id = ?",
                (report_id,),
            ).fetchone()
            if not row:
                return None
            return BacktestAnalyticsReport.model_validate_json(str(row["report_json"]))

    def list_reports(self, *, run_id: Optional[str] = None) -> List[Dict[str, Any]]:
        query = (
            "SELECT report_id, run_id, report_fingerprint, analytics_version, "
            "accounting_unit_mode, mode, instrument, timeframe, historical_date_range, "
            "status, is_synthetic_modelled, created_at_utc FROM analytics_reports"
        )
        params: Tuple[Any, ...] = ()
        if run_id is not None:
            query += " WHERE run_id = ?"
            params = (run_id,)
        query += " ORDER BY created_at_utc DESC, report_id ASC"
        with self._conn() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]


class BacktestAnalyticsEngine:
    """Orchestrates Step 4.4 quantitative backtest evaluation over Step 4.3 simulation runs."""

    def __init__(
        self,
        *,
        data_store: Optional[HistoricalDataStore] = None,
        analytics_store: Optional[BacktestAnalyticsStore] = None,
        risk_engine: Optional[RiskAnalyticsEngine] = None,
        performance_engine: Optional[PerformanceAnalyticsEngine] = None,
        time_series_engine: Optional[TimeSeriesAnalyticsEngine] = None,
        walk_forward_evaluator: Optional[WalkForwardEvaluator] = None,
        strategy_engine: Optional[StrategyAnalyticsEngine] = None,
    ) -> None:
        self.data_store = data_store
        self.analytics_store = analytics_store
        self.risk_engine = risk_engine or RiskAnalyticsEngine()
        self.performance_engine = performance_engine or PerformanceAnalyticsEngine(self.risk_engine)
        self.time_series_engine = time_series_engine or TimeSeriesAnalyticsEngine(self.risk_engine)
        self.walk_forward_evaluator = walk_forward_evaluator or WalkForwardEvaluator(self.performance_engine)
        self.strategy_engine = strategy_engine or StrategyAnalyticsEngine()

    def evaluate_simulation_run(
        self,
        run: SimulationRunResult,
        *,
        replay_run: Optional[ReplayRunRecord] = None,
        signals: Optional[Sequence[SimulationSignal]] = None,
        trade_metadata: Optional[Dict[str, TradeEvaluationMetadata]] = None,
        walk_forward_windows: Optional[Sequence[WalkForwardWindowSpec]] = None,
        walk_forward_scheme: Literal[
            "ANCHORED_EXPANDING", "ROLLING", "EXPLICIT_WINDOWS", "IS_OOS_SPLIT"
        ] = "EXPLICIT_WINDOWS",
        min_trades_for_significance: int = DEFAULT_MIN_TRADES_FOR_SIGNIFICANCE,
        persist: bool = False,
        created_at_utc: Optional[datetime] = None,
    ) -> BacktestAnalyticsReport:
        """Evaluates an immutable Step 4.3 SimulationRunResult and produces a reproducible report."""
        if run.execution_mode != EXECUTION_MODE:
            raise ValueError(
                f"EXECUTION_POLICY_VIOLATION: expected '{EXECUTION_MODE}', got '{run.execution_mode}'."
            )
        validate_run_domain_integrity(run)

        risk_summary: RiskSummaryAnalytics = self.risk_engine.evaluate_run(run)
        perf_summary: PerformanceSummaryAnalytics = self.performance_engine.evaluate_run(
            run, risk_summary=risk_summary
        )
        ts_result: TimeSeriesAnalyticsResult = self.time_series_engine.evaluate_run(
            run, drawdown_timeline=risk_summary.drawdown_timeline
        )
        dist_summary: TradeDistributionSummary = self.performance_engine.build_trade_distribution(run)
        strat_result: StrategyAnalyticsResult = self.strategy_engine.evaluate_run(
            run,
            trade_metadata=trade_metadata,
            signals=signals,
            replay_run=replay_run,
        )

        wf_result: Optional[WalkForwardResult] = None
        extra_warnings: List[str] = []
        if walk_forward_windows:
            if run.status == SimulationStatus.COMPLETED:
                wf_result = self.walk_forward_evaluator.evaluate_run(
                    run,
                    walk_forward_windows,
                    window_scheme=walk_forward_scheme,
                    min_trades_for_significance=min_trades_for_significance,
                )
            else:
                extra_warnings.append(
                    f"WALK_FORWARD_SKIPPED: simulation run status is {run.status.value} (requires COMPLETED)."
                )

        if run.status != SimulationStatus.COMPLETED:
            overall_status = AnalyticsStatus.RUN_NOT_COMPLETED
        elif perf_summary.trades_closed == 0:
            overall_status = AnalyticsStatus.NO_TRADES
        else:
            overall_status = AnalyticsStatus.COMPLETED

        um = run.accounting_unit_mode
        prov_warnings: List[str] = []
        if run.is_synthetic_modelled:
            prov_warnings.append(
                "SYNTHETIC_MODELLED_OPTION_PNL: Black-Scholes theoretical option approximation over OHLCV; "
                "NOT actual exchange option-chain ticks or bid/ask spreads."
            )
        if um == AccountingUnitMode.INDEX_POINTS_ONLY:
            prov_warnings.append(
                "INDEX_POINTS_ONLY: monetary INR cash/return metrics are excluded; index points are never converted to rupees."
            )
        elif um == AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR:
            prov_warnings.append(
                f"INDEX_POINTS_AND_EXPLICIT_INR: monetary INR computed using explicit multiplier "
                f"{run.portfolio.instrument_multiplier_inr_per_point} ({run.portfolio.instrument_multiplier_documentation})."
            )

        dq_warnings: List[str] = list(prov_warnings)
        dq_warnings.extend(extra_warnings)
        if run.failure_reasons:
            dq_warnings.extend(f"RUN_FAILURE_REASON: {r}" for r in run.failure_reasons)
        if perf_summary.intrabar_ambiguous_count > 0:
            dq_warnings.append(
                f"INTRABAR_AMBIGUITY_COUNT={perf_summary.intrabar_ambiguous_count}: same-bar SL/Target collisions "
                f"resolved conservatively under {run.ambiguity_policy.value}."
            )
        if perf_summary.trades_open > 0:
            dq_warnings.append(
                f"OPEN_TRADES_EXCLUDED={perf_summary.trades_open}: unclosed open trades excluded from closed-trade ratios."
            )
        if not perf_summary.reconciliation_verified:
            dq_warnings.append(
                "RECONCILIATION_WARNING: Step 4.3 net P&L reconciliation check reported discrepancies."
            )
        if not ts_result.reconciliation_matches_totals:
            dq_warnings.append(
                "TIME_SERIES_RECONCILIATION_WARNING: bucket totals differ from closed-trade net P&L."
            )
        if replay_run is not None and strat_result.unknown_metadata_counts.get("market_regime", 0) > 0:
            dq_warnings.append(
                "MISSING_METADATA_UNINFERRED: market_regime/setup fields absent from explicit metadata kept as UNKNOWN."
            )

        stat_limits: List[str] = [
            f"RESEARCH_ONLY_EVALUATION: execution_mode={EXECUTION_MODE}; historical OHLCV replay without live L2 orderbook impact."
        ]
        if perf_summary.trades_closed < min_trades_for_significance:
            stat_limits.append(
                f"INSUFFICIENT_SAMPLE: closed_trades={perf_summary.trades_closed} < threshold={min_trades_for_significance}; "
                "metrics are descriptive only and do NOT support statistical significance claims."
            )
        if wf_result is not None and not wf_result.statistical_significance_claimed:
            stat_limits.append(
                f"WALK_FORWARD_DESCRIPTIVE_ONLY: OOS status={wf_result.aggregate_oos_significance_status.value}; "
                "no live generalization significance claimed."
            )

        run_cfg_section = RunConfigurationSection(
            run_id=run.run_id,
            run_output_fingerprint=run.output_fingerprint,
            run_status=run.status,
            execution_mode=EXECUTION_MODE,
            mode=run.mode,
            instrument=run.instrument,
            timeframe=run.timeframe,
            simulator_version=run.simulator_version,
            cost_model_version=COST_MODEL_VERSION,
            cost_schedule=run.cost_schedule,
            ambiguity_policy=run.ambiguity_policy.value,
            gap_policy=run.gap_policy.value,
        )
        prov_section = DatasetProvenanceSection(
            dataset_fingerprint=run.dataset_fingerprint,
            calendar_fingerprint=run.calendar_fingerprint,
            historical_date_range=run.historical_date_range,
            replay_run_id=run.replay_run_id,
            provenance_label=run.provenance_label,
            is_synthetic_modelled=run.is_synthetic_modelled,
            instrument_multiplier_inr_per_point=run.portfolio.instrument_multiplier_inr_per_point,
            instrument_multiplier_documentation=run.portfolio.instrument_multiplier_documentation,
            provenance_warnings=tuple(dict.fromkeys(prov_warnings)),
        )
        acct_section = AccountingModeSection(
            accounting_unit_mode=um,
            monetary_accounting_enabled=domain_has_inr(um),
            points_unit="INDEX_POINTS" if domain_has_points(um) else None,
            currency_unit="INR" if domain_has_inr(um) else None,
        )

        fp_payload = {
            "analytics_version": ANALYTICS_VERSION,
            "execution_mode": EXECUTION_MODE,
            "status": overall_status.value,
            "run_configuration_and_fingerprint": run_cfg_section.model_dump(mode="json"),
            "dataset_provenance": prov_section.model_dump(mode="json"),
            "accounting_mode": acct_section.model_dump(mode="json"),
            "performance_summary": perf_summary.model_dump(mode="json"),
            "risk_summary": risk_summary.model_dump(mode="json"),
            "time_based_breakdown": ts_result.model_dump(mode="json"),
            "trade_distribution": dist_summary.model_dump(mode="json"),
            "walk_forward_results": wf_result.model_dump(mode="json") if wf_result is not None else None,
            "strategy_breakdown": strat_result.model_dump(mode="json"),
            "data_quality_warnings": tuple(dict.fromkeys(dq_warnings)),
            "statistical_limitations": tuple(dict.fromkeys(stat_limits)),
        }
        report_fp = compute_report_fingerprint(fp_payload)
        report_id = deterministic_id("RPT", report_fp)

        repro = ReproducibilityMetadata(
            analytics_version=ANALYTICS_VERSION,
            timezone_name="Asia/Kolkata",
            execution_mode=EXECUTION_MODE,
            run_id=run.run_id,
            run_output_fingerprint=run.output_fingerprint,
            dataset_fingerprint=run.dataset_fingerprint,
            calendar_fingerprint=run.calendar_fingerprint,
            replay_run_id=run.replay_run_id,
            report_fingerprint=report_fp,
        )

        report = BacktestAnalyticsReport(
            report_id=report_id,
            report_fingerprint=report_fp,
            analytics_version=ANALYTICS_VERSION,
            execution_mode=EXECUTION_MODE,
            status=overall_status,
            run_configuration_and_fingerprint=run_cfg_section,
            dataset_provenance=prov_section,
            accounting_mode=acct_section,
            performance_summary=perf_summary,
            risk_summary=risk_summary,
            time_based_breakdown=ts_result,
            trade_distribution=dist_summary,
            walk_forward_results=wf_result,
            strategy_breakdown=strat_result,
            data_quality_warnings=tuple(dict.fromkeys(dq_warnings)),
            statistical_limitations=tuple(dict.fromkeys(stat_limits)),
            reproducibility_metadata=repro,
            created_at_utc=created_at_utc or datetime.now(timezone.utc),
        )

        if persist:
            if self.analytics_store is None:
                raise ValueError("Cannot persist report without an initialized analytics_store.")
            self.analytics_store.save_report(report)

        return report

    def evaluate_stored_run(
        self,
        run_id: str,
        *,
        replay_run: Optional[ReplayRunRecord] = None,
        signals: Optional[Sequence[SimulationSignal]] = None,
        trade_metadata: Optional[Dict[str, TradeEvaluationMetadata]] = None,
        walk_forward_windows: Optional[Sequence[WalkForwardWindowSpec]] = None,
        walk_forward_scheme: Literal[
            "ANCHORED_EXPANDING", "ROLLING", "EXPLICIT_WINDOWS", "IS_OOS_SPLIT"
        ] = "EXPLICIT_WINDOWS",
        min_trades_for_significance: int = DEFAULT_MIN_TRADES_FOR_SIGNIFICANCE,
        persist: bool = False,
        created_at_utc: Optional[datetime] = None,
    ) -> BacktestAnalyticsReport:
        """Loads a persisted Step 4.3 run (and linked Step 4.2 replay if present) from isolated store."""
        if self.data_store is None:
            raise ValueError("data_store must be configured to evaluate a stored simulation run.")
        run = self.data_store.get_simulation_run(run_id)
        if run is None:
            raise KeyError(f"Simulation run '{run_id}' not found in isolated backtest store.")
        linked_replay = replay_run
        if linked_replay is None and run.replay_run_id:
            linked_replay = self.data_store.get_replay_run(run.replay_run_id)
        return self.evaluate_simulation_run(
            run,
            replay_run=linked_replay,
            signals=signals,
            trade_metadata=trade_metadata,
            walk_forward_windows=walk_forward_windows,
            walk_forward_scheme=walk_forward_scheme,
            min_trades_for_significance=min_trades_for_significance,
            persist=persist,
            created_at_utc=created_at_utc,
        )


def _fmt_num(val: Optional[float], *, suffix: str = "", digits: int = 4) -> str:
    if val is None:
        return "UNAVAILABLE"
    return f"{val:.{digits}f}{suffix}"


def _render_domain_block(title: str, m: Any, risk: Any, unit_suffix: str) -> List[str]:
    lines = [f"### {title} ({m.unit_label})", ""]
    lines.append(f"- **Provenance:** `{m.provenance_label}`")
    lines.append(
        f"- **Trades (Closed / Clean Win / Loss):** {m.total_closed_trades} / {m.winning_trades} / {m.losing_trades}"
    )
    lines.append(f"- **Win Rate:** {_fmt_num(m.win_rate_pct, suffix='%', digits=2)}")
    lines.append(
        f"- **Gross P&L / Costs / Net P&L:** {_fmt_num(m.gross_pnl, suffix=unit_suffix)} / "
        f"{_fmt_num(m.total_costs, suffix=unit_suffix)} / {_fmt_num(m.net_pnl, suffix=unit_suffix)}"
    )
    lines.append(f"- **Expectancy:** {_fmt_num(m.expectancy, suffix=unit_suffix)}")
    lines.append(
        f"- **Profit Factor:** {_fmt_num(m.profit_factor)} (`{m.profit_factor_status.value}`)"
    )
    lines.append(
        f"- **Avg Win / Avg Loss:** {_fmt_num(m.average_win, suffix=unit_suffix)} / "
        f"{_fmt_num(m.average_loss, suffix=unit_suffix)}"
    )
    lines.append(
        f"- **Largest Win / Largest Loss:** {_fmt_num(m.largest_win, suffix=unit_suffix)} / "
        f"{_fmt_num(m.largest_loss, suffix=unit_suffix)}"
    )
    lines.append(
        f"- **Payoff R:R / Planned R:R / Realized R:** {_fmt_num(m.average_risk_reward)} (`{m.average_risk_reward_status.value}`) / "
        f"{_fmt_num(m.average_planned_risk_reward)} / {_fmt_num(m.average_realized_r_multiple)}"
    )
    lines.append(f"- **Max Drawdown:** {_fmt_num(risk.max_drawdown, suffix=unit_suffix)}")
    if risk.max_drawdown_pct is not None:
        lines.append(f"- **Max Drawdown %:** {_fmt_num(risk.max_drawdown_pct, suffix='%', digits=2)}")
    lines.append(
        f"- **Recovery Factor:** {_fmt_num(risk.recovery_factor)} (`{risk.recovery_factor_status.value}`)"
    )
    if risk.ulcer_index_points is not None:
        lines.append(f"- **Ulcer Index (Points):** {_fmt_num(risk.ulcer_index_points, suffix=' pts')}")
    if risk.ulcer_index_pct is not None:
        lines.append(f"- **Ulcer Index (%):** {_fmt_num(risk.ulcer_index_pct, suffix='%')}")
    lines.append("")
    return lines


def render_markdown_report(report: BacktestAnalyticsReport) -> str:
    """Renders a structured human-readable research report strictly preserving unit & provenance clarity."""
    cfg = report.run_configuration_and_fingerprint
    prov = report.dataset_provenance
    acct = report.accounting_mode
    perf = report.performance_summary
    risk = report.risk_summary

    lines: List[str] = [
        f"# Backtest Analytics Report — {report.report_id}",
        "",
        f"- **Execution Mode:** `{report.execution_mode}` (Research & Evaluation Only)",
        f"- **Status:** `{report.status.value}` | **Analytics Version:** `{report.analytics_version}`",
        f"- **Instrument / Timeframe / Range:** `{cfg.instrument}` / `{cfg.timeframe}` / `{prov.historical_date_range}`",
        f"- **Simulation Mode / Accounting Domain:** `{cfg.mode.value}` / `{acct.accounting_unit_mode.value}`",
        f"- **Provenance:** `{prov.provenance_label}` (Synthetic Modelled: `{prov.is_synthetic_modelled}`)",
        f"- **Run ID / Output Fingerprint:** `{cfg.run_id}` / `{cfg.run_output_fingerprint}`",
        f"- **Report Fingerprint:** `{report.report_fingerprint}`",
        "",
        "## Trade & Holding Overview",
        "",
        f"- Signals: {perf.total_signals} | Opened: {perf.trades_opened} | Closed: {perf.trades_closed} | "
        f"Open: {perf.trades_open} | Rejected/Cancelled: {perf.trades_rejected_or_cancelled}",
        f"- Partial Exits: {perf.partial_exits_count} | Intrabar Ambiguous: {perf.intrabar_ambiguous_count} | "
        f"Reconciliation Verified: `{perf.reconciliation_verified}`",
        f"- Consecutive Wins / Losses: {perf.max_consecutive_wins} / {perf.max_consecutive_losses} "
        f"(Current: {perf.current_streak_type} x{perf.current_streak_count})",
        f"- Mean Holding Duration (min): {_fmt_num(perf.average_holding_duration_minutes, digits=2)} "
        f"(`{perf.holding_duration_status.value}`)",
        "",
        "## Performance & Risk Summary",
        "",
    ]

    if perf.points_metrics is not None and risk.points_risk is not None:
        lines.extend(_render_domain_block("Index Points Domain", perf.points_metrics, risk.points_risk, " pts"))
    if perf.inr_metrics is not None and risk.inr_risk is not None:
        inr_title = (
            "Synthetic Modelled Option INR Domain"
            if prov.is_synthetic_modelled
            else "Explicit Multiplier Monetary INR Domain"
        )
        lines.extend(_render_domain_block(inr_title, perf.inr_metrics, risk.inr_risk, " INR"))

    ts = report.time_based_breakdown
    lines.extend(
        [
            "## IST Time-Based Summary",
            "",
            f"- Daily Buckets: {len(ts.daily)} | Weekly: {len(ts.weekly)} | Monthly: {len(ts.monthly)} | "
            f"Sessions: {len(ts.session_wise)} | Totals Conserved: `{ts.reconciliation_matches_totals}`",
            "",
        ]
    )

    if report.walk_forward_results is not None:
        wf = report.walk_forward_results
        lines.extend(
            [
                "## Walk-Forward & Out-of-Sample Evaluation",
                "",
                f"- Scheme: `{wf.window_scheme}` | Windows: {wf.windows_count} (Valid OOS: {wf.valid_oos_windows_count}) | "
                f"Chronological Only: `{wf.chronological_only}` | No Lookahead Verified: `{wf.no_lookahead_verified}`",
                f"- Purged IS Trades: {wf.total_purged_is_trades} | Embargoed OOS Trades: {wf.total_embargoed_oos_trades}",
                f"- Aggregate OOS Significance Status: `{wf.aggregate_oos_significance_status.value}` "
                f"(Significance Claimed: `{wf.statistical_significance_claimed}`)",
                "",
            ]
        )

    sb = report.strategy_breakdown
    lines.extend(
        [
            "## Strategy & Setup Attribution",
            "",
            f"- ICT Score Status: `{sb.ict_score_status}` | Calibration Status: `{sb.ict_calibration_status}`",
            f"- Unknown Metadata Counts: `{sb.unknown_metadata_counts}`",
            "",
        ]
    )

    if report.data_quality_warnings or report.statistical_limitations:
        lines.extend(["## Warnings & Limitations", ""])
        for w in report.data_quality_warnings:
            lines.append(f"- [DATA_QUALITY] {w}")
        for s in report.statistical_limitations:
            lines.append(f"- [STATISTICAL] {s}")
        lines.append("")

    return "\n".join(lines)

