"""
AIVOLVE Phase 4 Step 4.5 — Module I: Backtest Robustness Report Orchestrator & Store.

Combines Modules B–H into an immutable, reproducible `BacktestRobustnessReport`,
persists reports strictly inside isolated SQLite (`backend/data/backtest/`),
and renders human-readable domain-segregated Markdown audit reports.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple

import pandas as pd

from app.backtesting.analytics_models import (
    AccountingModeSection,
    DatasetProvenanceSection,
    RunConfigurationSection,
    TradeEvaluationMetadata,
    WalkForwardWindowSpec,
    domain_has_inr,
    domain_has_points,
    validate_run_domain_integrity,
)
from app.backtesting.backtest_report import compute_report_fingerprint
from app.backtesting.configuration import (
    DEFAULT_BACKTEST_DB_PATH,
    EXECUTION_MODE,
    assert_isolated_backtest_path,
)
from app.backtesting.cost_model import COST_MODEL_VERSION
from app.backtesting.data_store import HistoricalDataStore
from app.backtesting.market_regime_robustness import MarketRegimeRobustnessEngine
from app.backtesting.models import ReplayRunRecord
from app.backtesting.monte_carlo_analysis import MonteCarloEngine
from app.backtesting.out_of_sample_robustness import OutOfSampleRobustnessEngine
from app.backtesting.parameter_sensitivity import ParameterSensitivityEngine
from app.backtesting.risk_analytics import sort_closed_trades
from app.backtesting.robustness_models import (
    BacktestRobustnessReport,
    MarketRegimeConfig,
    MarketRegimeRobustnessResult,
    MonteCarloConfig,
    MonteCarloResult,
    OutOfSampleRobustnessResult,
    ParameterSensitivityResult,
    ParameterVariationSpec,
    ROBUSTNESS_VERSION,
    RobustnessDomainMetrics,
    RobustnessReproducibilityMetadata,
    RobustnessStatus,
    SampleSizeGovernanceConfig,
    SampleSizeGovernanceResult,
    SlippageStressConfig,
    SlippageStressResult,
    TransactionCostStressConfig,
    TransactionCostStressResult,
)
from app.backtesting.sample_size_governance import SampleSizeGovernanceEngine
from app.backtesting.simulation_models import (
    AccountingUnitMode,
    SimulationConfiguration,
    SimulationRunResult,
    SimulationSignal,
    SimulationStatus,
)
from app.backtesting.slippage_stress import SlippageStressEngine
from app.backtesting.transaction_cost_stress import TransactionCostStressEngine
from app.backtesting.trade_lifecycle import deterministic_id


class BacktestRobustnessStore:
    """SQLite persistence store for Step 4.5 robustness reports strictly inside isolated storage."""

    def __init__(self, db_path: str | Path = DEFAULT_BACKTEST_DB_PATH) -> None:
        resolved = Path(db_path).resolve()
        assert_isolated_backtest_path(resolved)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = resolved
        self._init_schema()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS robustness_reports (
                    report_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    report_fingerprint TEXT NOT NULL,
                    configuration_fingerprint TEXT NOT NULL,
                    robustness_version TEXT NOT NULL,
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
                "CREATE INDEX IF NOT EXISTS idx_robustness_reports_run_id ON robustness_reports (run_id)"
            )
            conn.commit()

    def save_report(self, report: BacktestRobustnessReport) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO robustness_reports (
                    report_id, run_id, report_fingerprint, configuration_fingerprint,
                    robustness_version, accounting_unit_mode, mode, instrument, timeframe,
                    historical_date_range, status, is_synthetic_modelled,
                    report_json, created_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report.report_id,
                    report.run_configuration.run_id,
                    report.report_fingerprint,
                    report.configuration_fingerprint,
                    report.robustness_version,
                    report.accounting_mode.accounting_unit_mode.value,
                    report.run_configuration.mode.value,
                    report.run_configuration.instrument,
                    report.run_configuration.timeframe,
                    report.dataset_provenance.historical_date_range,
                    report.status.value,
                    1 if report.dataset_provenance.is_synthetic_modelled else 0,
                    report.model_dump_json(),
                    report.created_at_utc.astimezone(timezone.utc).isoformat(),
                ),
            )
            conn.commit()

    def get_report(self, report_id: str) -> Optional[BacktestRobustnessReport]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT report_json FROM robustness_reports WHERE report_id = ?",
                (report_id,),
            ).fetchone()
            if not row:
                return None
            return BacktestRobustnessReport.model_validate_json(str(row["report_json"]))

    def list_reports(self, *, run_id: Optional[str] = None) -> List[Dict[str, Any]]:
        query = (
            "SELECT report_id, run_id, report_fingerprint, configuration_fingerprint, "
            "robustness_version, accounting_unit_mode, mode, instrument, timeframe, "
            "historical_date_range, status, is_synthetic_modelled, created_at_utc "
            "FROM robustness_reports"
        )
        params: Tuple[Any, ...] = ()
        if run_id is not None:
            query += " WHERE run_id = ?"
            params = (run_id,)
        query += " ORDER BY created_at_utc DESC, report_id ASC"
        with self._conn() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]


class BacktestRobustnessEngine:
    """Orchestrates Modules B–H into an immutable Step 4.5 robustness report."""

    def __init__(
        self,
        *,
        data_store: Optional[HistoricalDataStore] = None,
        robustness_store: Optional[BacktestRobustnessStore] = None,
        slippage_engine: Optional[SlippageStressEngine] = None,
        transaction_cost_engine: Optional[TransactionCostStressEngine] = None,
        regime_engine: Optional[MarketRegimeRobustnessEngine] = None,
        parameter_engine: Optional[ParameterSensitivityEngine] = None,
        oos_engine: Optional[OutOfSampleRobustnessEngine] = None,
        monte_carlo_engine: Optional[MonteCarloEngine] = None,
        sample_size_engine: Optional[SampleSizeGovernanceEngine] = None,
    ) -> None:
        self.data_store = data_store
        self.robustness_store = robustness_store
        self.slippage_engine = slippage_engine or SlippageStressEngine()
        self.transaction_cost_engine = transaction_cost_engine or TransactionCostStressEngine()
        self.regime_engine = regime_engine or MarketRegimeRobustnessEngine()
        self.parameter_engine = parameter_engine or ParameterSensitivityEngine()
        self.oos_engine = oos_engine or OutOfSampleRobustnessEngine()
        self.monte_carlo_engine = monte_carlo_engine or MonteCarloEngine()
        self.sample_size_engine = sample_size_engine or SampleSizeGovernanceEngine()

    def evaluate_simulation_run(
        self,
        run: SimulationRunResult,
        *,
        candles_df: Optional[pd.DataFrame] = None,
        replay_run: Optional[ReplayRunRecord] = None,
        signals: Optional[Sequence[SimulationSignal]] = None,
        trade_metadata: Optional[Dict[str, TradeEvaluationMetadata]] = None,
        slippage_config: Optional[SlippageStressConfig] = None,
        transaction_cost_config: Optional[TransactionCostStressConfig] = None,
        regime_config: Optional[MarketRegimeConfig] = None,
        parameter_variations: Optional[Sequence[ParameterVariationSpec]] = None,
        precomputed_parameter_runs: Optional[Sequence[Tuple[ParameterVariationSpec, SimulationRunResult]]] = None,
        base_sim_config: Optional[SimulationConfiguration] = None,
        walk_forward_windows: Optional[Sequence[WalkForwardWindowSpec]] = None,
        walk_forward_scheme: Literal[
            "ANCHORED_EXPANDING", "ROLLING", "EXPLICIT_WINDOWS", "IS_OOS_SPLIT"
        ] = "IS_OOS_SPLIT",
        is_ratio: float = 0.7,
        is_duration: Optional[timedelta] = None,
        oos_duration: Optional[timedelta] = None,
        step_duration: Optional[timedelta] = None,
        purge_duration_seconds: float = 0.0,
        embargo_duration_seconds: float = 0.0,
        monte_carlo_config: Optional[MonteCarloConfig] = None,
        sample_size_config: Optional[SampleSizeGovernanceConfig] = None,
        persist: bool = False,
        created_at_utc: Optional[datetime] = None,
    ) -> BacktestRobustnessReport:
        if run.execution_mode != EXECUTION_MODE:
            raise ValueError(
                f"EXECUTION_POLICY_VIOLATION: expected '{EXECUTION_MODE}', got '{run.execution_mode}'."
            )
        validate_run_domain_integrity(run)

        eff_slip_cfg = slippage_config or SlippageStressConfig()
        eff_cost_cfg = transaction_cost_config or TransactionCostStressConfig()
        eff_reg_cfg = regime_config or MarketRegimeConfig()
        eff_mc_cfg = monte_carlo_config or MonteCarloConfig()
        eff_ss_cfg = sample_size_config or SampleSizeGovernanceConfig()

        eff_candles = candles_df
        if eff_candles is None and self.data_store is not None:
            loaded = self.data_store.load_candles(run.instrument, run.timeframe)
            if loaded is not None and not loaded.empty:
                eff_candles = loaded

        eff_replay = replay_run
        if eff_replay is None and run.replay_run_id and self.data_store is not None:
            eff_replay = self.data_store.get_replay_run(run.replay_run_id)

        slip_res: SlippageStressResult = self.slippage_engine.evaluate(run, config=eff_slip_cfg)
        cost_res: TransactionCostStressResult = self.transaction_cost_engine.evaluate(
            run, config=eff_cost_cfg
        )
        reg_res: MarketRegimeRobustnessResult = self.regime_engine.evaluate(
            run,
            candles_df=eff_candles,
            replay_run=eff_replay,
            trade_metadata=trade_metadata,
            config=eff_reg_cfg,
        )

        param_res: ParameterSensitivityResult
        if precomputed_parameter_runs is not None:
            param_res = self.parameter_engine.evaluate_precomputed_runs(
                baseline_run=run,
                variant_runs=precomputed_parameter_runs,
            )
        else:
            param_res = self.parameter_engine.evaluate_controlled_variations(
                baseline_run=run,
                variations=parameter_variations or (),
                signals=signals,
                candles_df=eff_candles,
                base_sim_config=base_sim_config,
            )

        oos_res: OutOfSampleRobustnessResult = self.oos_engine.evaluate_run(
            run,
            windows=walk_forward_windows,
            window_scheme=walk_forward_scheme,
            is_ratio=is_ratio,
            is_duration=is_duration,
            oos_duration=oos_duration,
            step_duration=step_duration,
            purge_duration_seconds=purge_duration_seconds,
            embargo_duration_seconds=embargo_duration_seconds,
        )
        mc_res: MonteCarloResult = self.monte_carlo_engine.evaluate(run, config=eff_mc_cfg)
        ss_res: SampleSizeGovernanceResult = self.sample_size_engine.evaluate(run, config=eff_ss_cfg)

        um = run.accounting_unit_mode
        prov_warnings: List[str] = []
        if run.is_synthetic_modelled:
            prov_warnings.append(
                "SYNTHETIC_MODELLED_OPTION_PNL: Stress results use synthetic Black-Scholes option estimates over OHLCV, not exchange option-chain ticks."
            )
        if um == AccountingUnitMode.INDEX_POINTS_ONLY:
            prov_warnings.append(
                "INDEX_POINTS_ONLY: Underlying index points are never converted to rupees; statutory INR transaction cost scaling is NOT_APPLICABLE_IN_DOMAIN."
            )
        elif um == AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR:
            prov_warnings.append(
                f"INDEX_POINTS_AND_EXPLICIT_INR: Monetary stress uses documented multiplier {run.portfolio.instrument_multiplier_inr_per_point} ({run.portfolio.instrument_multiplier_documentation})."
            )

        closed_cnt = len(sort_closed_trades(run.trades))
        if run.status != SimulationStatus.COMPLETED:
            overall_status = RobustnessStatus.RUN_NOT_COMPLETED
        elif closed_cnt == 0:
            overall_status = RobustnessStatus.NO_TRADES
        else:
            overall_status = RobustnessStatus.COMPLETED

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

        warnings: List[str] = list(prov_warnings)
        for mod_warn in (
            slip_res.warnings,
            cost_res.warnings,
            reg_res.warnings,
            param_res.warnings,
            oos_res.warnings,
            mc_res.warnings,
        ):
            warnings.extend(mod_warn)
        dedup_warnings = tuple(dict.fromkeys(warnings))

        limitations = tuple(
            dict.fromkeys(
                [
                    f"RESEARCH_VALIDATION_ONLY: execution_mode={EXECUTION_MODE}; robustness metrics evaluate historical stability and NEVER justify live order execution.",
                    *slip_res.assumptions,
                    *cost_res.assumptions,
                    *mc_res.limitations,
                    *ss_res.limitations,
                ]
            )
        )

        cfg_payload = {
            "robustness_version": ROBUSTNESS_VERSION,
            "run_output_fingerprint": run.output_fingerprint,
            "slippage_config": eff_slip_cfg.model_dump(mode="json"),
            "transaction_cost_config": eff_cost_cfg.model_dump(mode="json"),
            "regime_config": eff_reg_cfg.model_dump(mode="json"),
            "parameter_variations": [v.model_dump(mode="json") for v in (parameter_variations or ())],
            "precomputed_param_run_ids": [
                (v.variation_id, vr.run_id, vr.output_fingerprint)
                for v, vr in (precomputed_parameter_runs or ())
            ],
            "walk_forward_scheme": walk_forward_scheme,
            "walk_forward_windows": [w.model_dump(mode="json") for w in (walk_forward_windows or ())],
            "is_ratio": is_ratio,
            "is_duration_seconds": is_duration.total_seconds() if is_duration else None,
            "oos_duration_seconds": oos_duration.total_seconds() if oos_duration else None,
            "step_duration_seconds": step_duration.total_seconds() if step_duration else None,
            "purge_duration_seconds": purge_duration_seconds,
            "embargo_duration_seconds": embargo_duration_seconds,
            "monte_carlo_config": eff_mc_cfg.model_dump(mode="json"),
            "sample_size_config": eff_ss_cfg.model_dump(mode="json"),
        }
        cfg_fp = compute_report_fingerprint(cfg_payload)

        fp_payload = {
            "robustness_version": ROBUSTNESS_VERSION,
            "execution_mode": EXECUTION_MODE,
            "status": overall_status.value,
            "configuration_fingerprint": cfg_fp,
            "run_configuration": run_cfg_section.model_dump(mode="json"),
            "dataset_provenance": prov_section.model_dump(mode="json"),
            "accounting_mode": acct_section.model_dump(mode="json"),
            "slippage_stress": slip_res.model_dump(mode="json"),
            "transaction_cost_stress": cost_res.model_dump(mode="json"),
            "market_regime_robustness": reg_res.model_dump(mode="json"),
            "parameter_sensitivity": param_res.model_dump(mode="json"),
            "out_of_sample_robustness": oos_res.model_dump(mode="json"),
            "monte_carlo_analysis": mc_res.model_dump(mode="json"),
            "sample_size_governance": ss_res.model_dump(mode="json"),
            "warnings": dedup_warnings,
            "limitations": limitations,
        }
        report_fp = compute_report_fingerprint(fp_payload)
        report_id = deterministic_id("ROBUST", report_fp)

        repro = RobustnessReproducibilityMetadata(
            robustness_version=ROBUSTNESS_VERSION,
            execution_mode=EXECUTION_MODE,
            run_id=run.run_id,
            run_output_fingerprint=run.output_fingerprint,
            dataset_fingerprint=run.dataset_fingerprint,
            calendar_fingerprint=run.calendar_fingerprint,
            replay_run_id=run.replay_run_id,
            configuration_fingerprint=cfg_fp,
            report_fingerprint=report_fp,
        )

        report = BacktestRobustnessReport(
            report_id=report_id,
            report_fingerprint=report_fp,
            configuration_fingerprint=cfg_fp,
            robustness_version=ROBUSTNESS_VERSION,
            execution_mode=EXECUTION_MODE,
            status=overall_status,
            run_configuration=run_cfg_section,
            dataset_provenance=prov_section,
            accounting_mode=acct_section,
            slippage_stress=slip_res,
            transaction_cost_stress=cost_res,
            market_regime_robustness=reg_res,
            parameter_sensitivity=param_res,
            out_of_sample_robustness=oos_res,
            monte_carlo_analysis=mc_res,
            sample_size_governance=ss_res,
            statistical_significance_claimed=False,
            warnings=dedup_warnings,
            limitations=limitations,
            reproducibility_metadata=repro,
            created_at_utc=created_at_utc or datetime.now(timezone.utc),
        )

        if persist:
            if self.robustness_store is None:
                raise ValueError("Cannot persist robustness report without an initialized robustness_store.")
            self.robustness_store.save_report(report)

        return report

    def evaluate_stored_run(
        self,
        run_id: str,
        *,
        candles_df: Optional[pd.DataFrame] = None,
        replay_run: Optional[ReplayRunRecord] = None,
        signals: Optional[Sequence[SimulationSignal]] = None,
        trade_metadata: Optional[Dict[str, TradeEvaluationMetadata]] = None,
        slippage_config: Optional[SlippageStressConfig] = None,
        transaction_cost_config: Optional[TransactionCostStressConfig] = None,
        regime_config: Optional[MarketRegimeConfig] = None,
        parameter_variations: Optional[Sequence[ParameterVariationSpec]] = None,
        precomputed_parameter_runs: Optional[Sequence[Tuple[ParameterVariationSpec, SimulationRunResult]]] = None,
        base_sim_config: Optional[SimulationConfiguration] = None,
        walk_forward_windows: Optional[Sequence[WalkForwardWindowSpec]] = None,
        walk_forward_scheme: Literal[
            "ANCHORED_EXPANDING", "ROLLING", "EXPLICIT_WINDOWS", "IS_OOS_SPLIT"
        ] = "IS_OOS_SPLIT",
        is_ratio: float = 0.7,
        is_duration: Optional[timedelta] = None,
        oos_duration: Optional[timedelta] = None,
        step_duration: Optional[timedelta] = None,
        purge_duration_seconds: float = 0.0,
        embargo_duration_seconds: float = 0.0,
        monte_carlo_config: Optional[MonteCarloConfig] = None,
        sample_size_config: Optional[SampleSizeGovernanceConfig] = None,
        persist: bool = False,
        created_at_utc: Optional[datetime] = None,
    ) -> BacktestRobustnessReport:
        if self.data_store is None:
            raise ValueError("data_store must be configured to evaluate a stored simulation run.")
        run = self.data_store.get_simulation_run(run_id)
        if run is None:
            raise KeyError(f"Simulation run '{run_id}' not found in isolated backtest store.")
        return self.evaluate_simulation_run(
            run,
            candles_df=candles_df,
            replay_run=replay_run,
            signals=signals,
            trade_metadata=trade_metadata,
            slippage_config=slippage_config,
            transaction_cost_config=transaction_cost_config,
            regime_config=regime_config,
            parameter_variations=parameter_variations,
            precomputed_parameter_runs=precomputed_parameter_runs,
            base_sim_config=base_sim_config,
            walk_forward_windows=walk_forward_windows,
            walk_forward_scheme=walk_forward_scheme,
            is_ratio=is_ratio,
            is_duration=is_duration,
            oos_duration=oos_duration,
            step_duration=step_duration,
            purge_duration_seconds=purge_duration_seconds,
            embargo_duration_seconds=embargo_duration_seconds,
            monte_carlo_config=monte_carlo_config,
            sample_size_config=sample_size_config,
            persist=persist,
            created_at_utc=created_at_utc,
        )


def _fmt_opt(val: Optional[float], *, suffix: str = "", digits: int = 4) -> str:
    if val is None:
        return "UNAVAILABLE"
    return f"{val:.{digits}f}{suffix}"


def _fmt_dom_line(label: str, dom: Optional[RobustnessDomainMetrics], suffix: str) -> str:
    if dom is None:
        return f"- **{label}:** UNAVAILABLE"
    return (
        f"- **{label} ({dom.unit_label}):** net={dom.net_pnl:.4f}{suffix}, "
        f"gross={dom.gross_pnl:.4f}{suffix}, costs={dom.total_costs:.4f}{suffix}, "
        f"max_dd={dom.max_drawdown:.4f}{suffix}, pf={_fmt_opt(dom.profit_factor)}"
    )


def render_robustness_markdown_report(report: BacktestRobustnessReport) -> str:
    """Renders an institutional audit Markdown report strictly preserving AccountingUnitMode separation."""
    lines: List[str] = [
        f"# AIVOLVE Step 4.5 Robustness Report — `{report.report_id}`",
        "",
        f"- **Execution Policy:** `{report.execution_mode}`",
        f"- **Status:** `{report.status.value}`",
        f"- **Instrument / Timeframe:** `{report.run_configuration.instrument}` / `{report.run_configuration.timeframe}`",
        f"- **Date Range (IST):** `{report.dataset_provenance.historical_date_range}`",
        f"- **Accounting Mode:** `{report.accounting_mode.accounting_unit_mode.value}`",
        f"- **Provenance Label:** `{report.dataset_provenance.provenance_label}` (synthetic={report.dataset_provenance.is_synthetic_modelled})",
        f"- **Run ID / Output FP:** `{report.run_configuration.run_id}` / `{report.run_configuration.run_output_fingerprint}`",
        f"- **Report FP / Config FP:** `{report.report_fingerprint}` / `{report.configuration_fingerprint}`",
        f"- **Statistical Significance Claimed:** `{report.statistical_significance_claimed}`",
        "",
        "## 1. Sample Size Governance",
        f"- **Classification:** `{report.sample_size_governance.classification.value}` ({report.sample_size_governance.closed_trades_count} closed trades)",
        f"- **Summary:** {report.sample_size_governance.explanation}",
        "",
        "## 2. Slippage Stress",
        f"- **Status:** `{report.slippage_stress.status.value}`",
        f"- **Break-Even Slippage Mult (Points / INR):** `{_fmt_opt(report.slippage_stress.break_even_slippage_multiplier_points, suffix='x')}` / `{_fmt_opt(report.slippage_stress.break_even_slippage_multiplier_inr, suffix='x')}`",
    ]
    for s in report.slippage_stress.scenarios:
        lines.append(f"  - `{s.multiplier:.2f}x` (`{s.effective_slippage_per_unit:.4f}`):")
        if s.points_metrics is not None:
            lines.append("    " + _fmt_dom_line("Points", s.points_metrics, " pts"))
        if s.inr_metrics is not None:
            lines.append("    " + _fmt_dom_line("Monetary", s.inr_metrics, " INR"))

    lines.extend(["", "## 3. Transaction Cost Stress"])
    lines.append(f"- **Status:** `{report.transaction_cost_stress.status.value}` (applicable={report.transaction_cost_stress.monetary_charges_applicable})")
    if report.transaction_cost_stress.scenarios:
        lines.append(
            f"- **Break-Even Fee Mult (INR):** `{_fmt_opt(report.transaction_cost_stress.break_even_cost_multiplier_inr, suffix='x')}`"
        )
        for s in report.transaction_cost_stress.scenarios:
            c = s.cost_components
            assert s.inr_metrics is not None and c is not None
            lines.append(
                f"  - `{s.multiplier:.2f}x`: net={s.inr_metrics.net_pnl:.2f} INR, "
                f"brok={c.brokerage_inr:.2f}, stt={c.stt_inr:.2f}, exch={c.exchange_txn_charges_inr:.2f}, "
                f"gst={c.gst_inr:.2f}, sebi={c.sebi_charges_inr:.2f}, stamp={c.stamp_duty_inr:.2f}"
            )

    lines.extend(["", "## 4. Market Regime Robustness"])
    lines.append(
        f"- **Status:** `{report.market_regime_robustness.status.value}` "
        f"(classified={report.market_regime_robustness.classified_trades_count}, "
        f"unknown={report.market_regime_robustness.unknown_or_insufficient_trades_count}, "
        f"no_future_leakage={report.market_regime_robustness.no_future_bar_leakage_verified})"
    )
    for b in report.market_regime_robustness.buckets:
        lines.append(f"  - `{b.regime.value}` (`{b.classification_source}`, trades={b.trades_count}, sparse={b.is_sparse_bucket}):")
        if b.points_metrics is not None:
            lines.append("    " + _fmt_dom_line("Points", b.points_metrics, " pts"))
        if b.inr_metrics is not None:
            lines.append("    " + _fmt_dom_line("Monetary", b.inr_metrics, " INR"))

    lines.extend(["", "## 5. Parameter Sensitivity"])
    if report.parameter_sensitivity is not None:
        ps = report.parameter_sensitivity
        lines.append(
            f"- **Status / Mode:** `{ps.status.value}` / `{ps.evaluation_mode}` | "
            f"**Stability:** `{ps.stability_classification.value}` | "
            f"**Auto-Optimization Performed:** `{ps.auto_optimization_performed}` | "
            f"**Best Selected:** `{ps.best_parameter_selected}`"
        )
        for v in ps.variants:
            lines.append(f"  - `{v.variation_id}` ({v.label}, {v.parameter_name}={v.parameter_value_description}):")
            if v.points_metrics is not None:
                lines.append("    " + _fmt_dom_line("Points", v.points_metrics, " pts"))
            if v.inr_metrics is not None:
                lines.append("    " + _fmt_dom_line("Monetary", v.inr_metrics, " INR"))

    lines.extend(["", "## 6. Out-of-Sample Chronological Robustness"])
    oos = report.out_of_sample_robustness
    lines.append(
        f"- **Status:** `{oos.status.value}` | **Windows (Valid OOS / Total):** `{oos.valid_oos_windows_count}/{oos.windows_count}` | "
        f"**IS Trades:** `{oos.total_is_trades}` | **OOS Trades:** `{oos.total_oos_trades}` | **No Lookahead:** `{oos.no_lookahead_verified}`"
    )
    if oos.is_aggregate_points is not None or oos.oos_aggregate_points is not None:
        lines.append("  " + _fmt_dom_line("IS Aggregate", oos.is_aggregate_points, " pts"))
        lines.append("  " + _fmt_dom_line("OOS Aggregate", oos.oos_aggregate_points, " pts"))
    if oos.is_aggregate_inr is not None or oos.oos_aggregate_inr is not None:
        lines.append("  " + _fmt_dom_line("IS Aggregate", oos.is_aggregate_inr, " INR"))
        lines.append("  " + _fmt_dom_line("OOS Aggregate", oos.oos_aggregate_inr, " INR"))

    lines.extend(["", "## 7. Monte Carlo Trade-Sequence Resampling (Descriptive Estimate Only)"])
    mc = report.monte_carlo_analysis
    lines.append(
        f"- **Status / Mode / Seed / Iterations:** `{mc.status.value}` / `{mc.config.mode.value}` / `{mc.config.seed}` / `{mc.config.n_iterations}` "
        f"(is_estimate_not_prediction={mc.is_estimate_not_prediction})"
    )
    if mc.points_distribution is not None:
        d = mc.points_distribution
        lines.append(
            f"- **Points DD (obs/p50/p95/max):** `{d.max_drawdown.observed:.2f}` / `{d.max_drawdown.p50:.2f}` / `{d.max_drawdown.p95:.2f}` / `{d.max_drawdown.max:.2f} pts`"
        )
        lines.append(
            f"- **Points Net P&L (obs/p05/p50/p95):** `{d.ending_net_pnl.observed:.2f}` / `{d.ending_net_pnl.p05:.2f}` / `{d.ending_net_pnl.p50:.2f}` / `{d.ending_net_pnl.p95:.2f} pts`"
        )
    if mc.inr_distribution is not None:
        d = mc.inr_distribution
        lines.append(
            f"- **INR DD (obs/p50/p95/max):** `{d.max_drawdown.observed:.2f}` / `{d.max_drawdown.p50:.2f}` / `{d.max_drawdown.p95:.2f}` / `{d.max_drawdown.max:.2f} INR`"
        )
        lines.append(
            f"- **INR Net P&L (obs/p05/p50/p95):** `{d.ending_net_pnl.observed:.2f}` / `{d.ending_net_pnl.p05:.2f}` / `{d.ending_net_pnl.p50:.2f}` / `{d.ending_net_pnl.p95:.2f} INR`"
        )

    if report.warnings:
        lines.extend(["", "## 8. Warnings"])
        for w in report.warnings:
            lines.append(f"- {w}")
    if report.limitations:
        lines.extend(["", "## 9. Limitations & Governance Disclaimers"])
        for lim in report.limitations:
            lines.append(f"- {lim}")

    return "\n".join(lines)

