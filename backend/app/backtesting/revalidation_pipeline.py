"""
AIVOLVE Phase 4, Step 4.7 — Historical Revalidation Pipeline & Isolated Store
Orchestrates Dataset Quality Gate -> Chronological Phase 2/3 Replay -> Step 4.3
Execution Simulation (3 isolated domains) -> Step 4.4 Analytics -> Step 4.5 Robustness.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

import pandas as pd

from app.backtesting.analytics_models import (
    BacktestAnalyticsReport,
    TradeEvaluationMetadata,
    WalkForwardWindowSpec,
)
from app.backtesting.backtest_report import (
    BacktestAnalyticsEngine,
    BacktestAnalyticsStore,
)
from app.backtesting.configuration import (
    BacktestConfiguration,
    DEFAULT_BACKTEST_DATA_DIR,
    EXECUTION_MODE,
    IST_ZONE,
    assert_isolated_backtest_path,
    normalize_instrument,
    normalize_timeframe,
)
from app.backtesting.data_store import HistoricalDataStore
from app.backtesting.execution_simulator import (
    HistoricalExecutionSimulator,
    price_synthetic_bs_option,
    resolve_provenance_label,
)
from app.backtesting.historical_revalidation import (
    DatasetEligibilityGate,
    HistoricalSignalRevalidator,
)
from app.backtesting.revalidation_models import (
    AccountingDomainEvaluation,
    AccountingDomainRunSpec,
    BreakdownBucketMetrics,
    DatasetEligibilityDecision,
    HistoricalRevalidationRunResult,
    ISOOSSplitEvaluation,
    RevalidationConfig,
    RevalidationSignalDirection,
    RevalidationSignalRecord,
    RevalidationStatus,
    RevalidationSummaryMetrics,
    deterministic_reval_hash,
)
from app.backtesting.robustness_models import (
    BacktestRobustnessReport,
    MonteCarloConfig,
    ParameterVariationSpec,
)
from app.backtesting.robustness_report import (
    BacktestRobustnessEngine,
    BacktestRobustnessStore,
)
from app.backtesting.simulation_models import (
    AccountingUnitMode,
    SignalDirection,
    SimulationConfiguration,
    SimulationMode,
    SimulationRunResult,
    SimulationSignal,
    SyntheticBSAssumptions,
    TradeLifecycleState,
    TradeRecord,
    TriggerPriceDomain,
)


SYNTHETIC_DEFAULT_LOT_SIZES: Dict[str, int] = {
    "NIFTY 50": 75,
    "BANK NIFTY": 30,
    "FINNIFTY": 65,
}


def default_accounting_domain_specs(
    *,
    starting_capital_inr: float = 2_000_000.0,
    instrument_multiplier_inr_per_point: float = 75.0,
    instrument_multiplier_documentation: str = (
        "Research-only NSE index lot multiplier for Step 4.7 MODE_A_WITH_EXPLICIT_INR_MULTIPLIER"
    ),
) -> Tuple[AccountingDomainRunSpec, ...]:
    """Builds the 3 strictly separated accounting domain specs required by Step 4.7."""
    return (
        AccountingDomainRunSpec(
            domain_mode=AccountingUnitMode.INDEX_POINTS_ONLY,
        ),
        AccountingDomainRunSpec(
            domain_mode=AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR,
            starting_capital_inr=starting_capital_inr,
            instrument_multiplier_inr_per_point=instrument_multiplier_inr_per_point,
            instrument_multiplier_documentation=instrument_multiplier_documentation,
            mode_a_margin_fraction=0.15,
        ),
        AccountingDomainRunSpec(
            domain_mode=AccountingUnitMode.SYNTHETIC_OPTION_INR_ONLY,
            starting_capital_inr=starting_capital_inr,
            synthetic_iv=0.18,
            synthetic_risk_free_rate=0.065,
            synthetic_lots=1,
            synthetic_strike_step=50,
        ),
    )


class HistoricalRevalidationStore:
    """Isolated SQLite persistence for Step 4.7 runs, signals, and audit reports under backend/data/backtest/."""

    def __init__(self, db_path: Optional[Path | str] = None) -> None:
        cfg = BacktestConfiguration()
        raw_path = Path(db_path) if db_path is not None else Path(cfg.storage_db_path)
        self.db_path = assert_isolated_backtest_path(raw_path)
        allowed_root = DEFAULT_BACKTEST_DATA_DIR.resolve()
        if allowed_root not in self.db_path.parents and self.db_path != allowed_root:
            raise ValueError(
                f"ISOLATION VIOLATION: Step 4.7 store path '{self.db_path}' must reside inside '{allowed_root}'."
            )
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
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
                CREATE TABLE IF NOT EXISTS step4_7_revalidation_runs (
                    revalidation_id TEXT PRIMARY KEY,
                    instrument TEXT NOT NULL,
                    primary_timeframe TEXT NOT NULL,
                    status TEXT NOT NULL,
                    eligibility_classification TEXT NOT NULL,
                    dataset_fingerprint TEXT NOT NULL,
                    config_fingerprint TEXT NOT NULL,
                    run_fingerprint TEXT NOT NULL,
                    execution_mode TEXT NOT NULL,
                    created_at_utc TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS step4_7_revalidation_signals (
                    signal_id TEXT NOT NULL,
                    revalidation_id TEXT NOT NULL,
                    as_of_time_ist TEXT NOT NULL,
                    instrument TEXT NOT NULL,
                    signal_direction TEXT NOT NULL,
                    market_regime TEXT NOT NULL,
                    entry_eligible INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    PRIMARY KEY (revalidation_id, signal_id)
                );
                CREATE TABLE IF NOT EXISTS step4_7_audit_reports (
                    report_id TEXT PRIMARY KEY,
                    report_fingerprint TEXT NOT NULL,
                    verdict TEXT NOT NULL,
                    execution_mode TEXT NOT NULL,
                    created_at_utc TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    markdown_text TEXT NOT NULL
                );
                """
            )

    def save_revalidation_run(self, result: HistoricalRevalidationRunResult) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO step4_7_revalidation_runs (
                    revalidation_id, instrument, primary_timeframe, status,
                    eligibility_classification, dataset_fingerprint, config_fingerprint,
                    run_fingerprint, execution_mode, created_at_utc, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result.revalidation_id,
                    result.config.instrument,
                    result.config.primary_timeframe,
                    result.status.value,
                    result.eligibility_decision.eligibility.value,
                    result.eligibility_decision.composite_dataset_fingerprint,
                    deterministic_reval_hash(result.config.model_dump(mode="json")),
                    result.run_fingerprint,
                    result.execution_mode,
                    result.created_at_utc,
                    result.model_dump_json(),
                ),
            )
            conn.execute(
                "DELETE FROM step4_7_revalidation_signals WHERE revalidation_id = ?",
                (result.revalidation_id,),
            )
            conn.executemany(
                """
                INSERT INTO step4_7_revalidation_signals (
                    signal_id, revalidation_id, as_of_time_ist, instrument,
                    signal_direction, market_regime, entry_eligible, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        s.signal_id,
                        result.revalidation_id,
                        s.as_of_time_ist,
                        s.instrument,
                        s.signal_direction.value,
                        s.market_regime,
                        1 if s.entry_eligible else 0,
                        s.model_dump_json(),
                    )
                    for s in result.signals
                ],
            )

    def get_revalidation_run(self, revalidation_id: str) -> Optional[HistoricalRevalidationRunResult]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM step4_7_revalidation_runs WHERE revalidation_id = ?",
                (revalidation_id,),
            ).fetchone()
            if row is None:
                return None
            return HistoricalRevalidationRunResult.model_validate_json(row["payload_json"])

    def save_audit_report(self, report_id: str, report_fp: str, verdict: str, created_at_utc: str, payload_json: str, markdown_text: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO step4_7_audit_reports (
                    report_id, report_fingerprint, verdict, execution_mode,
                    created_at_utc, payload_json, markdown_text
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report_id,
                    report_fp,
                    verdict,
                    EXECUTION_MODE,
                    created_at_utc,
                    payload_json,
                    markdown_text,
                ),
            )


def _compute_causal_expiry_ist(as_of_ist: datetime) -> datetime:
    """Deterministically picks the next weekly expiry strictly after `as_of_ist` (research-only BS)."""
    d = as_of_ist.astimezone(IST_ZONE).date()
    days_ahead = (3 - d.weekday()) % 7  # Thursday = 3
    if days_ahead == 0:
        cand = datetime(d.year, d.month, d.day, 15, 30, tzinfo=IST_ZONE)
        if cand <= as_of_ist:
            days_ahead = 7
    target_date = d + timedelta(days=days_ahead)
    return datetime(target_date.year, target_date.month, target_date.day, 15, 30, tzinfo=IST_ZONE)


def build_domain_simulation_signals(
    signal_records: Sequence[RevalidationSignalRecord],
    *,
    domain_spec: AccountingDomainRunSpec,
    config: RevalidationConfig,
) -> List[SimulationSignal]:
    """
    Translates strictly eligible `BUY_CE` / `BUY_PE` records into Step 4.3 `SimulationSignal`s.
    `WAIT` and `NO_TRADE` records are NEVER converted into execution intents.
    """
    sim_signals: List[SimulationSignal] = []
    norm_tf = normalize_timeframe(config.primary_timeframe)

    for rec in signal_records:
        if not rec.entry_eligible or rec.signal_direction not in (
            RevalidationSignalDirection.BUY_CE,
            RevalidationSignalDirection.BUY_PE,
        ):
            continue
        assert rec.stop_loss is not None and rec.target_1 is not None
        as_of_ist = datetime.fromisoformat(rec.as_of_time_ist).astimezone(IST_ZONE)
        is_ce = rec.signal_direction == RevalidationSignalDirection.BUY_CE

        if domain_spec.domain_mode in (
            AccountingUnitMode.INDEX_POINTS_ONLY,
            AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR,
        ):
            sim_signals.append(
                SimulationSignal(
                    signal_id=rec.signal_id,
                    instrument=rec.instrument,
                    timeframe=norm_tf,
                    signal_available_at_ist=as_of_ist,
                    direction=SignalDirection.LONG if is_ce else SignalDirection.SHORT,
                    trigger_domain=TriggerPriceDomain.UNDERLYING_POINTS,
                    stop_loss=round(float(rec.stop_loss), 4),
                    target_1=round(float(rec.target_1), 4),
                    target_2=round(float(rec.target_2), 4) if rec.target_2 is not None else None,
                    partial_exit_fraction=config.partial_exit_fraction,
                    quantity_units=domain_spec.quantity_units_points,
                    max_entry_wait_bars=config.max_entry_wait_bars,
                    intraday_square_off=config.intraday_square_off,
                    source_report_id=rec.source_replay_report_id,
                    notes=f"Step 4.7 {rec.signal_direction.value} regime={rec.market_regime}",
                )
            )
        else:
            step = float(domain_spec.synthetic_strike_step)
            strike = round(rec.spot_reference / step) * step
            exp_ist = _compute_causal_expiry_ist(as_of_ist)
            lot_size = SYNTHETIC_DEFAULT_LOT_SIZES.get(rec.instrument, 50)
            opt_type = "CE" if is_ce else "PE"
            assumptions = SyntheticBSAssumptions(
                option_type=opt_type,
                strike_price=float(strike),
                expiry_datetime_ist=exp_ist,
                risk_free_rate=domain_spec.synthetic_risk_free_rate,
                implied_volatility=domain_spec.synthetic_iv,
                lot_size=lot_size,
                lots=domain_spec.synthetic_lots,
            )
            prem_ref = price_synthetic_bs_option(
                spot=rec.spot_reference,
                strike=assumptions.strike_price,
                valuation_time_ist=as_of_ist,
                expiry_datetime_ist=exp_ist,
                risk_free_rate=assumptions.risk_free_rate,
                dividend_yield=assumptions.dividend_yield,
                implied_volatility=assumptions.implied_volatility,
                option_type=opt_type,
            )
            entry_spot = float(rec.entry_price or rec.spot_reference)
            spot_risk = abs(entry_spot - float(rec.stop_loss))
            # Causal synthetic premium risk (~0.5 delta scaling bounded to finite positive option levels)
            opt_risk = max(2.0, min(prem_ref * 0.45, spot_risk * 0.5))
            rr = float(rec.reward_risk_ratio or 1.5)
            sl_p = max(0.05, round(prem_ref - opt_risk, 2))
            if sl_p >= prem_ref:
                sl_p = max(0.05, round(prem_ref * 0.8, 2))
            t1_p = round(max(sl_p + 1.0, prem_ref + opt_risk * max(1.0, rr)), 2)
            t2_p = round(t1_p + opt_risk * 1.0, 2)
            sim_signals.append(
                SimulationSignal(
                    signal_id=rec.signal_id,
                    instrument=rec.instrument,
                    timeframe=norm_tf,
                    signal_available_at_ist=as_of_ist,
                    direction=SignalDirection.LONG,
                    trigger_domain=TriggerPriceDomain.SYNTHETIC_OPTION_PREMIUM,
                    stop_loss=sl_p,
                    target_1=t1_p,
                    target_2=t2_p,
                    partial_exit_fraction=config.partial_exit_fraction,
                    quantity_units=lot_size * domain_spec.synthetic_lots,
                    max_entry_wait_bars=config.max_entry_wait_bars,
                    intraday_square_off=config.intraday_square_off,
                    synthetic_bs_assumptions=assumptions,
                    source_report_id=rec.source_replay_report_id,
                    notes=f"Step 4.7 SYNTHETIC_BS_{opt_type} regime={rec.market_regime}",
                )
            )

    return sim_signals


def _build_simulation_config(
    domain_spec: AccountingDomainRunSpec,
    reval_config: RevalidationConfig,
) -> SimulationConfiguration:
    if domain_spec.domain_mode == AccountingUnitMode.INDEX_POINTS_ONLY:
        return SimulationConfiguration(
            mode=SimulationMode.UNDERLYING_POINTS_ONLY,
            monetary_accounting_enabled=False,
            square_off_time_hhmm=reval_config.square_off_time_hhmm,
            sensex_governance_approved=reval_config.sensex_governance_approved,
            storage_db_path=reval_config.storage_db_path,
            governance_ledger_path=reval_config.governance_ledger_path,
        )
    if domain_spec.domain_mode == AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR:
        return SimulationConfiguration(
            mode=SimulationMode.UNDERLYING_POINTS_ONLY,
            monetary_accounting_enabled=True,
            starting_capital_inr=domain_spec.starting_capital_inr,
            instrument_multiplier_inr_per_point=domain_spec.instrument_multiplier_inr_per_point,
            instrument_multiplier_documentation=domain_spec.instrument_multiplier_documentation,
            mode_a_margin_fraction=domain_spec.mode_a_margin_fraction or 0.15,
            square_off_time_hhmm=reval_config.square_off_time_hhmm,
            sensex_governance_approved=reval_config.sensex_governance_approved,
            storage_db_path=reval_config.storage_db_path,
            governance_ledger_path=reval_config.governance_ledger_path,
        )
    return SimulationConfiguration(
        mode=SimulationMode.SYNTHETIC_BS_RESEARCH,
        monetary_accounting_enabled=True,
        starting_capital_inr=domain_spec.starting_capital_inr or 1_000_000.0,
        square_off_time_hhmm=reval_config.square_off_time_hhmm,
        sensex_governance_approved=reval_config.sensex_governance_approved,
        storage_db_path=reval_config.storage_db_path,
        governance_ledger_path=reval_config.governance_ledger_path,
    )


def _trade_realized_points(tr: TradeRecord) -> float:
    return float(tr.net_points or 0.0)


def _trade_realized_inr(tr: TradeRecord) -> float:
    return float(tr.net_pnl_inr or 0.0)


def _is_closed_trade(tr: TradeRecord) -> bool:
    return tr.state == TradeLifecycleState.CLOSED


def _build_is_oos_split(
    *,
    domain_mode: AccountingUnitMode,
    signal_records: Sequence[RevalidationSignalRecord],
    sim_run: SimulationRunResult,
    is_ratio: float,
) -> Tuple[ISOOSSplitEvaluation, Tuple[WalkForwardWindowSpec, ...]]:
    """
    Strictly chronological In-Sample vs Out-of-Sample evaluation based on
    unique evaluated timestamps (zero shuffling, zero future data leakage).
    """
    if not signal_records:
        return (
            ISOOSSplitEvaluation(
                accounting_unit_mode=domain_mode,
                is_signals_count=0,
                oos_signals_count=0,
                is_closed_trades=0,
                oos_closed_trades=0,
                no_lookahead_verified=True,
                notes=("Zero replay signals available for IS/OOS chronological split.",),
            ),
            (),
        )

    times = sorted(datetime.fromisoformat(s.as_of_time_ist).astimezone(IST_ZONE) for s in signal_records)
    if len(times) < 2 or times[0] == times[-1]:
        return (
            ISOOSSplitEvaluation(
                accounting_unit_mode=domain_mode,
                is_signals_count=len(signal_records),
                oos_signals_count=0,
                is_closed_trades=len([t for t in sim_run.trades if _is_closed_trade(t)]),
                oos_closed_trades=0,
                no_lookahead_verified=True,
                notes=("Insufficient chronological span for IS/OOS split.",),
            ),
            (),
        )

    split_idx = max(1, min(len(times) - 1, int(round(len(times) * is_ratio))))
    split_dt = times[split_idx]
    is_start = times[0] - timedelta(seconds=1)
    oos_end = times[-1] + timedelta(minutes=60)

    is_sigs = [s for s in signal_records if datetime.fromisoformat(s.as_of_time_ist).astimezone(IST_ZONE) < split_dt]
    oos_sigs = [s for s in signal_records if datetime.fromisoformat(s.as_of_time_ist).astimezone(IST_ZONE) >= split_dt]

    is_sig_ids = {s.signal_id for s in is_sigs}
    oos_sig_ids = {s.signal_id for s in oos_sigs}
    closed_trades = [t for t in sim_run.trades if _is_closed_trade(t)]
    is_trades = [t for t in closed_trades if t.signal_id in is_sig_ids]
    oos_trades = [t for t in closed_trades if t.signal_id in oos_sig_ids]

    def _agg(trades: List[TradeRecord]) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        if not trades:
            return None, None, None
        is_pts = domain_mode in (AccountingUnitMode.INDEX_POINTS_ONLY, AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR)
        is_inr = domain_mode in (AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR, AccountingUnitMode.SYNTHETIC_OPTION_INR_ONLY)
        wins = sum(
            1
            for t in trades
            if ((_trade_realized_points(t) if is_pts else _trade_realized_inr(t)) > 0.0)
        )
        wr = round(100.0 * wins / len(trades), 2)
        pts_sum = round(sum(_trade_realized_points(t) for t in trades), 4) if is_pts else None
        inr_sum = round(sum(_trade_realized_inr(t) for t in trades), 2) if is_inr else None
        return wr, pts_sum, inr_sum

    is_wr, is_pts, is_inr = _agg(is_trades)
    oos_wr, oos_pts, oos_inr = _agg(oos_trades)

    wf_spec = WalkForwardWindowSpec(
        window_id="WF-IS-OOS-1",
        is_start_ist=is_start,
        is_end_ist=split_dt,
        oos_start_ist=split_dt,
        oos_end_ist=oos_end,
    )
    split_eval = ISOOSSplitEvaluation(
        accounting_unit_mode=domain_mode,
        split_boundary_ist=split_dt.isoformat(),
        is_period=f"{times[0].isoformat()}..{times[split_idx - 1].isoformat()}",
        oos_period=f"{times[split_idx].isoformat()}..{times[-1].isoformat()}",
        is_signals_count=len(is_sigs),
        oos_signals_count=len(oos_sigs),
        is_closed_trades=len(is_trades),
        oos_closed_trades=len(oos_trades),
        is_win_rate_pct=is_wr,
        oos_win_rate_pct=oos_wr,
        is_net_pnl_points=is_pts,
        oos_net_pnl_points=oos_pts,
        is_net_pnl_inr=is_inr,
        oos_net_pnl_inr=oos_inr,
        no_lookahead_verified=True,
        notes=(
            "Strict chronological split by point-in-time signal availability without shuffling.",
        ),
    )
    return split_eval, (wf_spec,)


def _compute_dimension_breakdown(
    *,
    dimension: str,
    signal_records: Sequence[RevalidationSignalRecord],
    reference_sim: Optional[SimulationRunResult],
) -> Tuple[BreakdownBucketMetrics, ...]:
    if not signal_records:
        return ()
    closed_by_sig: Dict[str, TradeRecord] = {}
    um: Optional[AccountingUnitMode] = None
    if reference_sim is not None:
        um = reference_sim.portfolio.accounting_unit_mode
        closed_by_sig = {t.signal_id: t for t in reference_sim.trades if _is_closed_trade(t)}

    grouped: Dict[str, List[RevalidationSignalRecord]] = {}
    for rec in signal_records:
        if dimension == "market_regime":
            key = rec.market_regime
        elif dimension == "session_bucket":
            key = rec.session_bucket
        elif dimension == "signal_direction":
            key = rec.signal_direction.value
        else:
            key = rec.instrument
        grouped.setdefault(key, []).append(rec)

    buckets: List[BreakdownBucketMetrics] = []
    for key in sorted(grouped.keys()):
        items = grouped[key]
        trades = [closed_by_sig[s.signal_id] for s in items if s.signal_id in closed_by_sig]
        is_pts = um in (AccountingUnitMode.INDEX_POINTS_ONLY, AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR)
        is_inr = um in (AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR, AccountingUnitMode.SYNTHETIC_OPTION_INR_ONLY)
        wins = 0
        losses = 0
        for tr in trades:
            metric = _trade_realized_points(tr) if is_pts else _trade_realized_inr(tr)
            if metric > 0:
                wins += 1
            elif metric < 0:
                losses += 1
        wr = round(100.0 * wins / len(trades), 2) if trades else None
        pts = round(sum(_trade_realized_points(t) for t in trades), 4) if (trades and is_pts) else None
        inr = round(sum(_trade_realized_inr(t) for t in trades), 2) if (trades and is_inr) else None
        buckets.append(
            BreakdownBucketMetrics(
                dimension=dimension,
                bucket_key=key,
                total_signals=len(items),
                buy_ce_count=sum(1 for s in items if s.signal_direction == RevalidationSignalDirection.BUY_CE),
                buy_pe_count=sum(1 for s in items if s.signal_direction == RevalidationSignalDirection.BUY_PE),
                wait_count=sum(1 for s in items if s.signal_direction == RevalidationSignalDirection.WAIT),
                no_trade_count=sum(1 for s in items if s.signal_direction == RevalidationSignalDirection.NO_TRADE),
                eligible_signals=sum(1 for s in items if s.entry_eligible),
                closed_trades=len(trades),
                wins=wins,
                losses=losses,
                win_rate_pct=wr,
                net_pnl_points=pts,
                net_pnl_inr=inr,
            )
        )
    return tuple(buckets)


class HistoricalRevalidationPipeline:
    """
    Master Step 4.7 Historical Backtest Revalidation Engine.
    Strictly PAPER_TRADING_ONLY. Zero automatic optimization. Zero live execution.
    """

    def __init__(
        self,
        *,
        backtest_config: Optional[BacktestConfiguration] = None,
        data_store: Optional[HistoricalDataStore] = None,
        reval_store: Optional[HistoricalRevalidationStore] = None,
    ) -> None:
        self.backtest_config = backtest_config or BacktestConfiguration()
        self.data_store = data_store or HistoricalDataStore(config=self.backtest_config)
        self.reval_store = reval_store or HistoricalRevalidationStore(db_path=self.backtest_config.storage_db_path)
        self.quality_gate = DatasetEligibilityGate(
            backtest_config=self.backtest_config,
            data_store=self.data_store,
        )
        self.signal_revalidator = HistoricalSignalRevalidator(
            backtest_config=self.backtest_config,
            data_store=self.data_store,
        )
        self.analytics_engine = BacktestAnalyticsEngine(
            data_store=self.data_store,
            analytics_store=BacktestAnalyticsStore(db_path=self.backtest_config.storage_db_path),
        )
        self.robustness_engine = BacktestRobustnessEngine(
            data_store=self.data_store,
            robustness_store=BacktestRobustnessStore(db_path=self.backtest_config.storage_db_path),
        )

    def run_revalidation(
        self,
        config: RevalidationConfig,
        *,
        domain_specs: Optional[Sequence[AccountingDomainRunSpec]] = None,
        candles_by_timeframe_override: Optional[Dict[str, pd.DataFrame]] = None,
        persist: bool = True,
        created_at_utc: Optional[datetime] = None,
    ) -> HistoricalRevalidationRunResult:
        """Executes end-to-end Step 4.7 historical revalidation across separated domains."""
        now_utc = (created_at_utc or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
        specs = tuple(domain_specs) if domain_specs is not None else default_accounting_domain_specs()

        eligibility, filtered_candles = self.quality_gate.evaluate_revalidation_eligibility(
            config, candles_by_timeframe_override=candles_by_timeframe_override
        )
        cfg_fp = deterministic_reval_hash(config.model_dump(mode="json"))

        if not eligibility.eligible_for_replay:
            status = (
                RevalidationStatus.GOVERNANCE_LOCKOUT
                if eligibility.eligibility.value == "GOVERNANCE_LOCKED"
                else RevalidationStatus.REJECTED_DATASET_QUALITY
            )
            empty_summary = RevalidationSummaryMetrics(
                sessions_evaluated=0,
                replay_timestamps_count=0,
                total_signals_evaluated=0,
                action_distribution={"BUY_CE": 0, "BUY_PE": 0, "WAIT": 0, "NO_TRADE": 0},
                trade_frequency_per_session=0.0,
                no_trade_frequency_pct=0.0,
                wait_frequency_pct=0.0,
                eligible_signals_count=0,
                ineligible_signals_count=0,
                rejection_reason_distribution={r: 1 for r in eligibility.rejection_reasons},
                market_regime_distribution={},
                entry_reason_distribution={},
                exit_reason_distribution={},
            )
            run_fp = deterministic_reval_hash([cfg_fp, eligibility.composite_dataset_fingerprint, status.value])
            reval_id = f"REVALRUN-{run_fp[:14]}"
            result = HistoricalRevalidationRunResult(
                revalidation_id=reval_id,
                run_fingerprint=run_fp,
                status=status,
                config=config,
                eligibility_decision=eligibility,
                summary_metrics=empty_summary,
                known_limitations=eligibility.rejection_reasons,
                created_at_utc=now_utc,
            )
            if persist:
                self.reval_store.save_revalidation_run(result)
            return result

        # Chronological point-in-time Phase 2 + Phase 3 replay evaluation
        replay_run, signal_records = self.signal_revalidator.evaluate_chronological_signals(
            config=config,
            eligibility=eligibility,
            candles_by_timeframe=filtered_candles,
            persist_replay_run=persist,
        )

        norm_primary = normalize_timeframe(config.primary_timeframe)
        primary_df = filtered_candles[norm_primary]

        # Build TradeEvaluationMetadata for Step 4.4 & Step 4.5 enrichment
        trade_meta: Dict[str, TradeEvaluationMetadata] = {
            rec.signal_id: TradeEvaluationMetadata(
                ict_smc_setup=rec.phase3_alignment,
                market_regime=rec.market_regime,
                session=rec.session_bucket,
                entry_reason=f"{rec.signal_direction.value} ({rec.qualification_status})",
            )
            for rec in signal_records
            if rec.entry_eligible
        }

        sim_bt_cfg = BacktestConfiguration(
            storage_db_path=config.storage_db_path or self.backtest_config.storage_db_path,
            governance_ledger_path=config.governance_ledger_path or self.backtest_config.governance_ledger_path,
            sensex_governance_approved=config.sensex_governance_approved,
            strict_missing_intervals=not eligibility.research_only_flag,
        )

        # Controlled non-optimized parameter sensitivity perturbations (preserves all geometry)
        param_variations = (
            ParameterVariationSpec(
                variation_id="WAIT_1_BAR",
                label="Max entry wait = 1 bar",
                parameter_name="max_entry_wait_bars",
                override_value=1,
                notes="Controlled execution sensitivity check (not optimized).",
            ),
            ParameterVariationSpec(
                variation_id="PARTIAL_33PCT",
                label="Partial T1 exit = 33%",
                parameter_name="partial_exit_fraction",
                override_value=0.33,
                notes="Controlled target scaling sensitivity check (not optimized).",
            ),
        )

        domain_evals: Dict[str, AccountingDomainEvaluation] = {}
        reference_sim: Optional[SimulationRunResult] = None
        exit_reason_counter: Counter[str] = Counter()

        for spec in specs:
            if not spec.enabled:
                continue
            sim_cfg = _build_simulation_config(spec, config)
            sim_signals = build_domain_simulation_signals(
                signal_records, domain_spec=spec, config=config
            )
            simulator = HistoricalExecutionSimulator(
                config=sim_cfg,
                backtest_config=sim_bt_cfg,
                data_store=self.data_store,
                calendar_adapter=self.quality_gate.calendar,
            )
            sim_run = simulator.run_simulation(
                instrument=normalize_instrument(config.instrument),
                timeframe=norm_primary,
                signals=sim_signals,
                candles_df=primary_df,
                replay_run_id=replay_run.run_id,
                persist=persist,
            )

            is_oos_eval, wf_windows = _build_is_oos_split(
                domain_mode=spec.domain_mode,
                signal_records=signal_records,
                sim_run=sim_run,
                is_ratio=config.is_ratio,
            )

            analytics_rep: BacktestAnalyticsReport = self.analytics_engine.evaluate_simulation_run(
                sim_run,
                replay_run=replay_run,
                signals=sim_signals,
                trade_metadata=trade_meta,
                walk_forward_windows=wf_windows if wf_windows else None,
                walk_forward_scheme="IS_OOS_SPLIT",
                persist=persist,
            )
            robustness_rep: BacktestRobustnessReport = self.robustness_engine.evaluate_simulation_run(
                sim_run,
                candles_df=primary_df,
                replay_run=replay_run,
                signals=sim_signals,
                trade_metadata=trade_meta,
                parameter_variations=param_variations if sim_signals else None,
                base_sim_config=sim_cfg,
                walk_forward_windows=wf_windows if wf_windows else None,
                walk_forward_scheme="IS_OOS_SPLIT",
                is_ratio=config.is_ratio,
                monte_carlo_config=MonteCarloConfig(
                    n_iterations=config.monte_carlo_simulations,
                    seed=config.monte_carlo_seed,
                ),
                persist=persist,
            )

            if reference_sim is None:
                reference_sim = sim_run
                for tr in sim_run.trades:
                    if tr.final_exit_reason is not None:
                        exit_reason_counter[tr.final_exit_reason.value] += 1

            warnings = list(robustness_rep.warnings)
            if eligibility.research_only_flag:
                warnings.append(
                    "PARTIAL_RESEARCH_ONLY: Run includes excluded incomplete sessions; full-session claims prohibited."
                )
            if spec.domain_mode == AccountingUnitMode.SYNTHETIC_OPTION_INR_ONLY:
                warnings.append(
                    "SYNTHETIC_OPTION_INR_ONLY: Modelled via Black-Scholes research assumptions; real historical option execution remains BLOCKED."
                )

            domain_evals[spec.domain_mode.value] = AccountingDomainEvaluation(
                domain_mode=spec.domain_mode,
                provenance_label=resolve_provenance_label(sim_cfg),
                is_synthetic_modelled=(spec.domain_mode == AccountingUnitMode.SYNTHETIC_OPTION_INR_ONLY),
                simulation_run=sim_run,
                analytics_report=analytics_rep,
                robustness_report=robustness_rep,
                is_oos_comparison=is_oos_eval,
                sample_size_classification=robustness_rep.sample_size_governance.classification,
                warnings=tuple(dict.fromkeys(warnings)),
            )

        action_counter: Counter[str] = Counter(s.signal_direction.value for s in signal_records)
        rej_counter: Counter[str] = Counter()
        regime_counter: Counter[str] = Counter(s.market_regime for s in signal_records)
        entry_reason_counter: Counter[str] = Counter()

        for rec in signal_records:
            for r in rec.rejection_reasons:
                rej_counter[r] += 1
            if rec.entry_eligible:
                entry_reason_counter[f"{rec.signal_direction.value}:{rec.market_regime}"] += 1

        total_sigs = len(signal_records)
        sessions_count = len(eligibility.common_complete_sessions)
        eligible_count = sum(1 for s in signal_records if s.entry_eligible)
        action_dist = {
            "BUY_CE": int(action_counter.get("BUY_CE", 0)),
            "BUY_PE": int(action_counter.get("BUY_PE", 0)),
            "WAIT": int(action_counter.get("WAIT", 0)),
            "NO_TRADE": int(action_counter.get("NO_TRADE", 0)),
        }
        summary_metrics = RevalidationSummaryMetrics(
            sessions_evaluated=sessions_count,
            replay_timestamps_count=total_sigs,
            total_signals_evaluated=total_sigs,
            action_distribution=action_dist,
            trade_frequency_per_session=round(eligible_count / max(1, sessions_count), 4),
            no_trade_frequency_pct=round(100.0 * action_dist["NO_TRADE"] / max(1, total_sigs), 2),
            wait_frequency_pct=round(100.0 * action_dist["WAIT"] / max(1, total_sigs), 2),
            eligible_signals_count=eligible_count,
            ineligible_signals_count=total_sigs - eligible_count,
            rejection_reason_distribution=dict(rej_counter.most_common()),
            market_regime_distribution=dict(regime_counter.most_common()),
            entry_reason_distribution=dict(entry_reason_counter.most_common()),
            exit_reason_distribution=dict(exit_reason_counter.most_common()),
        )

        if eligibility.research_only_flag:
            final_status = RevalidationStatus.COMPLETED_RESEARCH_ONLY_PARTIAL
        elif eligible_count == 0:
            final_status = RevalidationStatus.NO_ELIGIBLE_SIGNALS
        else:
            final_status = RevalidationStatus.COMPLETED

        limitations = [
            "Historical option OHLC and bid/ask chains remain UNAVAILABLE on Angel One SmartAPI; actual historical options execution is BLOCKED.",
            "Phase 3 ICT/SMC confluence_score remains None (UNAVAILABLE / NOT_CALIBRATED).",
            "Option-chain PCR/OI sentiment and live VIX feed are absent in historical index OHLCV replay; neutral baseline VIX and absent option chain were applied consistently without future data.",
        ]
        if eligibility.research_only_flag:
            limitations.append(
                f"PARTIAL dataset mode used strictly for restricted research ({len(eligibility.excluded_incomplete_sessions)} incomplete session(s) excluded)."
            )

        run_fp = deterministic_reval_hash(
            [
                cfg_fp,
                eligibility.composite_dataset_fingerprint,
                replay_run.run_id,
                [s.signal_id for s in signal_records],
                sorted(domain_evals.keys()),
            ]
        )
        reval_id = f"REVALRUN-{run_fp[:14]}"
        result = HistoricalRevalidationRunResult(
            revalidation_id=reval_id,
            run_fingerprint=run_fp,
            status=final_status,
            config=config,
            eligibility_decision=eligibility,
            replay_run_id=replay_run.run_id,
            evaluated_start_ist=signal_records[0].as_of_time_ist if signal_records else None,
            evaluated_end_ist=signal_records[-1].as_of_time_ist if signal_records else None,
            signals=signal_records,
            summary_metrics=summary_metrics,
            domain_evaluations=domain_evals,
            regime_breakdown=_compute_dimension_breakdown(
                dimension="market_regime", signal_records=signal_records, reference_sim=reference_sim
            ),
            session_breakdown=_compute_dimension_breakdown(
                dimension="session_bucket", signal_records=signal_records, reference_sim=reference_sim
            ),
            direction_breakdown=_compute_dimension_breakdown(
                dimension="signal_direction", signal_records=signal_records, reference_sim=reference_sim
            ),
            known_limitations=tuple(limitations),
            created_at_utc=now_utc,
        )
        if persist:
            self.reval_store.save_revalidation_run(result)
        return result
