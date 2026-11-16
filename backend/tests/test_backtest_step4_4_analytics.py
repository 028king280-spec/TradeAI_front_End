"""
AIVOLVE Phase 4 Step 4.4 — Comprehensive Verification Suite for Backtest Analytics & Evaluation Engine.

Verifies:
1. Analytic metric calculations (win rate, profit factor, expectancy, R:R, streaks, durations, quantiles)
2. Zero-trade and non-completed run handling
3. Zero-loss profit factor & zero-loss R:R explicit unavailable handling (never inf/nan)
4. Zero-drawdown recovery factor explicit unavailable handling
5. Partial exits and unclosed open trades handling
6. Net P&L reconciliation verification & discrepancy detection
7. Drawdown calculations (equity curve, Ulcer Index, recovered & unrecovered episodes)
8. IST daily / ISO weekly / monthly / canonical session aggregation & UTC->IST boundary rollover
9. Strict three-way AccountingUnitMode segregation & mixed-domain rejection
10. Walk-forward chronology (anchored/rolling/split), purge, embargo & no-lookahead assertions
11. Insufficient-sample & zero-variance discipline (never claims false statistical significance)
12. Strategy attribution keeping missing metadata STRICTLY UNKNOWN & preserving UNAVAILABLE ICT scores
13. Reproducibility (identical report_id/report_fingerprint), Markdown rendering, & isolated SQLite persistence
14. End-to-end Step 4.3 ExecutionSimulator integration + isolated evaluation of persisted Step 4.3 DB runs
"""

from __future__ import annotations

import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
import pytest

from app.backtesting import (
    ANALYTICS_VERSION,
    AnalyticsStatus,
    BacktestAnalyticsEngine,
    BacktestAnalyticsStore,
    BacktestConfiguration,
    DEFAULT_BACKTEST_DB_PATH,
    EXECUTION_MODE,
    HistoricalDataStore,
    HistoricalExecutionSimulator,
    HistoricalMarketCalendarAdapter,
    IST_ZONE,
    MarketSessionBucket,
    MetricAvailabilityStatus,
    PerformanceAnalyticsEngine,
    RiskAnalyticsEngine,
    SignificanceStatus,
    SimulationConfiguration,
    SimulationMode,
    SimulationSignal,
    StrategyAnalyticsEngine,
    TimeSeriesAnalyticsEngine,
    TradeEvaluationMetadata,
    UNKNOWN_LABEL,
    WalkForwardEvaluator,
    WalkForwardWindowSpec,
    classify_ist_session,
    generate_walk_forward_windows,
    render_markdown_report,
)
from app.backtesting.models import ReplayPointResult, ReplayRunRecord, ReplayValidationStatus
from app.backtesting.portfolio_ledger import PortfolioLedger
from app.backtesting.simulation_models import (
    AccountingUnitMode,
    AmbiguityPolicy,
    CostBreakdown,
    CostScheduleVersion,
    EquityCurvePoint,
    ExitReason,
    FillRecord,
    GapPolicy,
    OrderSide,
    ReconciliationReport,
    SignalDirection,
    SimulationRunResult,
    SimulationStatus,
    SyntheticBSAssumptions,
    TradeLifecycleState,
    TradeRecord,
    TriggerPriceDomain,
)
from app.backtesting.trade_lifecycle import deterministic_id


# ---------------------------------------------------------------------------
# Local Isolated Test Fixtures
# ---------------------------------------------------------------------------


def _make_trade(
    *,
    idx: int,
    entry_time_ist: str,
    exit_time_ist: Optional[str],
    signal_available_at_ist: Optional[str] = None,
    gross_points: Optional[float] = None,
    slippage_points: Optional[float] = None,
    net_points: Optional[float] = None,
    gross_pnl_inr: Optional[float] = None,
    total_costs_inr: Optional[float] = None,
    net_pnl_inr: Optional[float] = None,
    accounting_unit_mode: AccountingUnitMode = AccountingUnitMode.INDEX_POINTS_ONLY,
    mode: SimulationMode = SimulationMode.UNDERLYING_POINTS_ONLY,
    direction: SignalDirection = SignalDirection.LONG,
    timeframe: str = "5m",
    entry_price: float = 24000.0,
    stop_loss: float = 23980.0,
    target_1: float = 24040.0,
    initial_quantity: int = 1,
    exited_quantity: Optional[int] = None,
    remaining_quantity: int = 0,
    state: TradeLifecycleState = TradeLifecycleState.CLOSED,
    partial_exit: bool = False,
    intrabar_ambiguous_count: int = 0,
    final_exit_reason: Optional[ExitReason] = ExitReason.TARGET_1,
    multiplier: Optional[float] = None,
    multiplier_doc: Optional[str] = None,
) -> TradeRecord:
    trade_id = f"TRD-{idx:04d}"
    signal_id = f"SIG-{idx:04d}"
    sig_ts = signal_available_at_ist or entry_time_ist
    is_synth = accounting_unit_mode == AccountingUnitMode.SYNTHETIC_OPTION_INR_ONLY
    prov = (
        "SYNTHETIC_MODELLED_OPTION_PNL"
        if is_synth
        else ("INDEX_POINTS_AND_EXPLICIT_INR" if multiplier is not None else "UNDERLYING_POINTS_ONLY")
    )
    qty_label = (
        "SYNTHETIC_OPTION_UNITS"
        if is_synth
        else ("SPECIFIED_INDEX_MULTIPLIER_UNITS" if multiplier else "PARTIAL_EXIT_SLICE_UNITS")
    )

    ex_qty = exited_quantity if exited_quantity is not None else (initial_quantity if state == TradeLifecycleState.CLOSED else 0)
    fills: List[FillRecord] = []
    if state in (TradeLifecycleState.CLOSED, TradeLifecycleState.PARTIALLY_EXITED, TradeLifecycleState.OPEN):
        has_pts_fill = accounting_unit_mode != AccountingUnitMode.SYNTHETIC_OPTION_INR_ONLY
        has_inr_fill = accounting_unit_mode != AccountingUnitMode.INDEX_POINTS_ONLY
        cost_domain = (
            "SYNTHETIC_OPTION_PREMIUM_RESEARCH"
            if is_synth
            else ("UNDERLYING_POINTS_WITH_EXPLICIT_INR" if has_inr_fill else "UNDERLYING_POINTS_ONLY")
        )
        cost_unit = "INR" if has_inr_fill else "INDEX_POINTS"
        cb_entry = CostBreakdown(
            cost_model_version="TEST-COSTS",
            effective_date_ist="2026-11-11",
            cost_domain=cost_domain,
            cost_unit=cost_unit,
            slippage_points_leg=((slippage_points or 0.0) / 2.0) if not has_inr_fill else None,
            turnover_inr=0.0 if has_inr_fill else None,
            buy_turnover_inr=0.0 if has_inr_fill else None,
            sell_turnover_inr=0.0 if has_inr_fill else None,
            brokerage_inr=0.0 if has_inr_fill else None,
            stt_inr=0.0 if has_inr_fill else None,
            exchange_txn_charges_inr=0.0 if has_inr_fill else None,
            gst_inr=0.0 if has_inr_fill else None,
            sebi_charges_inr=0.0 if has_inr_fill else None,
            stamp_duty_inr=0.0 if has_inr_fill else None,
            slippage_cost_inr=((total_costs_inr or 0.0) / 2.0) if has_inr_fill else None,
            brokerage_and_statutory_inr=0.0 if has_inr_fill else None,
            total_costs_inr=((total_costs_inr or 0.0) / 2.0) if has_inr_fill else None,
        )

        def _mk_fill(leg_no: int, side: OrderSide, ts_fill: str, qty: int, px: float, exit_rsn: Optional[ExitReason]) -> FillRecord:
            return FillRecord(
                fill_id=f"FILL-{idx:04d}-{leg_no}",
                order_id=f"ORD-{idx:04d}-{leg_no}",
                trade_id=trade_id,
                signal_id=signal_id,
                side=side,
                mode=mode,
                accounting_unit_mode=accounting_unit_mode,
                provenance_label=prov,
                bar_open_ist=ts_fill,
                bar_close_ist=ts_fill,
                executed_at_ist=ts_fill,
                quantity=max(1, qty),
                raw_reference_price=px,
                slippage_per_unit=0.5,
                effective_fill_price=px,
                underlying_spot_at_fill=24000.0,
                gross_points_leg=(gross_points or 0.0) if (has_pts_fill and side == OrderSide.EXIT) else (0.0 if has_pts_fill else None),
                slippage_points_leg=((slippage_points or 0.0) / 2.0) if has_pts_fill else None,
                net_points_impact_leg=(net_points or 0.0) if (has_pts_fill and side == OrderSide.EXIT) else (0.0 if has_pts_fill else None),
                gross_pnl_inr_leg=(gross_pnl_inr or 0.0) if (has_inr_fill and side == OrderSide.EXIT) else (0.0 if has_inr_fill else None),
                net_pnl_inr_impact_leg=(net_pnl_inr or 0.0) if (has_inr_fill and side == OrderSide.EXIT) else (0.0 if has_inr_fill else None),
                costs=cb_entry,
                exit_reason=exit_rsn,
                is_intrabar_ambiguous=intrabar_ambiguous_count > 0 if side == OrderSide.EXIT else False,
                ambiguity_evidence=None,
            )

        fills.append(_mk_fill(1, OrderSide.ENTRY, entry_time_ist, initial_quantity, entry_price, None))
        if partial_exit:
            fills.append(
                _mk_fill(
                    2,
                    OrderSide.PARTIAL_EXIT,
                    exit_time_ist or entry_time_ist,
                    max(1, initial_quantity // 2) if initial_quantity > 1 else 1,
                    target_1,
                    ExitReason.TARGET_1,
                )
            )
        if state == TradeLifecycleState.CLOSED and exit_time_ist is not None:
            fills.append(_mk_fill(3, OrderSide.EXIT, exit_time_ist, max(1, ex_qty), target_1, final_exit_reason))

    has_pts = accounting_unit_mode != AccountingUnitMode.SYNTHETIC_OPTION_INR_ONLY
    has_inr = accounting_unit_mode != AccountingUnitMode.INDEX_POINTS_ONLY

    return TradeRecord(
        trade_id=trade_id,
        signal_id=signal_id,
        instrument="NIFTY 50",
        timeframe=timeframe,
        mode=mode,
        accounting_unit_mode=accounting_unit_mode,
        provenance_label=prov,
        is_synthetic_modelled=is_synth,
        quantity_unit_label=qty_label,
        instrument_multiplier_inr_per_point=multiplier,
        instrument_multiplier_documentation=multiplier_doc,
        direction=direction,
        state=state,
        signal_available_at_ist=sig_ts,
        entry_time_ist=entry_time_ist,
        exit_time_ist=exit_time_ist,
        entry_price=entry_price,
        initial_quantity=initial_quantity,
        exited_quantity=ex_qty,
        remaining_quantity=remaining_quantity,
        stop_loss=stop_loss,
        target_1=target_1,
        target_2=None,
        target_1_executed=partial_exit or (final_exit_reason == ExitReason.TARGET_1),
        target_2_executed=final_exit_reason == ExitReason.TARGET_2,
        gross_points=gross_points if has_pts else None,
        slippage_points=slippage_points if has_pts else None,
        net_points=net_points if has_pts else None,
        unrealized_points=0.0 if has_pts else None,
        option_premium_points_per_unit=(net_pnl_inr / max(1, initial_quantity)) if is_synth else None,
        reserved_capital_inr=0.0 if has_inr else None,
        gross_pnl_inr=gross_pnl_inr if has_inr else None,
        total_brokerage_and_statutory_inr=0.0 if has_inr else None,
        total_slippage_cost_inr=total_costs_inr if has_inr else None,
        total_costs_inr=total_costs_inr if has_inr else None,
        net_pnl_inr=net_pnl_inr if has_inr else None,
        unrealized_pnl_inr=0.0 if has_inr else None,
        intrabar_ambiguous_count=intrabar_ambiguous_count,
        ambiguity_events=(),
        fills=tuple(fills),
        final_exit_reason=final_exit_reason,
    )


def _build_run(
    *,
    run_id: str = "SIM-TESTRUN0000001",
    trades: Tuple[TradeRecord, ...] = (),
    equity_points_series: Optional[List[Tuple[str, float]]] = None,
    equity_inr_series: Optional[List[Tuple[str, float]]] = None,
    accounting_unit_mode: AccountingUnitMode = AccountingUnitMode.INDEX_POINTS_ONLY,
    mode: SimulationMode = SimulationMode.UNDERLYING_POINTS_ONLY,
    starting_capital_inr: Optional[float] = None,
    multiplier: Optional[float] = None,
    multiplier_doc: Optional[str] = None,
    status: SimulationStatus = SimulationStatus.COMPLETED,
    failure_reasons: Tuple[str, ...] = (),
    override_realized_net_points: Optional[float] = None,
    override_realized_net_inr: Optional[float] = None,
    total_signals: Optional[int] = None,
    replay_run_id: Optional[str] = None,
) -> SimulationRunResult:
    has_pts = accounting_unit_mode != AccountingUnitMode.SYNTHETIC_OPTION_INR_ONLY
    has_inr = accounting_unit_mode != AccountingUnitMode.INDEX_POINTS_ONLY
    is_synth = accounting_unit_mode == AccountingUnitMode.SYNTHETIC_OPTION_INR_ONLY
    prov = (
        "SYNTHETIC_MODELLED_OPTION_PNL"
        if is_synth
        else ("INDEX_POINTS_AND_EXPLICIT_INR" if multiplier else "UNDERLYING_POINTS_ONLY")
    )

    opened = [t for t in trades if t.state not in (TradeLifecycleState.REJECTED, TradeLifecycleState.CANCELLED, TradeLifecycleState.PENDING)]
    closed = [t for t in opened if t.state == TradeLifecycleState.CLOSED]

    gross_pts = sum(float(t.gross_points or 0.0) for t in opened) if has_pts else None
    slip_pts = sum(float(t.slippage_points or 0.0) for t in opened) if has_pts else None
    net_pts = (
        override_realized_net_points
        if (override_realized_net_points is not None and has_pts)
        else (sum(float(t.net_points or 0.0) for t in opened) if has_pts else None)
    )

    gross_inr = sum(float(t.gross_pnl_inr or 0.0) for t in opened) if has_inr else None
    cost_inr = sum(float(t.total_costs_inr or 0.0) for t in opened) if has_inr else None
    net_inr = (
        override_realized_net_inr
        if (override_realized_net_inr is not None and has_inr)
        else (sum(float(t.net_pnl_inr or 0.0) for t in opened) if has_inr else None)
    )

    # Build chronological equity curve
    curve: List[EquityCurvePoint] = []
    timestamps: List[str] = []
    if equity_points_series:
        timestamps = [ts for ts, _ in equity_points_series]
    elif equity_inr_series:
        timestamps = [ts for ts, _ in equity_inr_series]

    pts_map = {ts: v for ts, v in (equity_points_series or [])}
    inr_map = {ts: v for ts, v in (equity_inr_series or [])}

    peak_p = 0.0
    peak_i = float(starting_capital_inr) if starting_capital_inr else 0.0
    max_dd_p = 0.0
    max_dd_i = 0.0
    max_dd_pct = 0.0
    for ts in timestamps:
        dd_p = None
        ep = pts_map.get(ts) if has_pts else None
        if has_pts:
            ep = float(ep if ep is not None else 0.0)
            peak_p = max(peak_p, ep)
            dd_p = max(0.0, peak_p - ep)
            max_dd_p = max(max_dd_p, dd_p)

        dd_i = None
        dd_pct = None
        ei = inr_map.get(ts) if has_inr else None
        if has_inr:
            ei = float(ei if ei is not None else peak_i)
            peak_i = max(peak_i, ei)
            dd_i = max(0.0, peak_i - ei)
            dd_pct = (dd_i / peak_i * 100.0) if peak_i > 0.0 else 0.0
            max_dd_i = max(max_dd_i, dd_i)
            max_dd_pct = max(max_dd_pct, dd_pct)

        curve.append(
            EquityCurvePoint(
                timestamp_ist=ts,
                accounting_unit_mode=accounting_unit_mode,
                realized_gross_points=gross_pts if has_pts else None,
                total_slippage_points=slip_pts if has_pts else None,
                realized_net_points=net_pts if has_pts else None,
                unrealized_points=0.0 if has_pts else None,
                cumulative_equity_points=ep if has_pts else None,
                drawdown_points=dd_p if has_pts else None,
                available_cash_inr=ei if has_inr else None,
                reserved_capital_inr=0.0 if has_inr else None,
                realized_gross_pnl_inr=gross_inr if has_inr else None,
                realized_net_pnl_inr=net_inr if has_inr else None,
                unrealized_pnl_inr=0.0 if has_inr else None,
                total_costs_inr=cost_inr if has_inr else None,
                total_equity_inr=ei if has_inr else None,
                drawdown_inr=dd_i if has_inr else None,
                drawdown_pct=dd_pct if has_inr else None,
                open_trades_count=0,
            )
        )

    use_pts = accounting_unit_mode == AccountingUnitMode.INDEX_POINTS_ONLY
    winners = sum(
        1
        for t in closed
        if (float(t.net_points or 0.0) if use_pts else float(t.net_pnl_inr or 0.0)) > 0.0
        and t.intrabar_ambiguous_count == 0
    )
    losers = len(closed) - winners

    from app.backtesting.portfolio_ledger import PortfolioSummary  # local import cleanly inside test helper

    cap = float(starting_capital_inr) if (has_inr and starting_capital_inr) else None
    ending_eq_inr = (cap + float(net_inr or 0.0)) if (has_inr and cap is not None) else None

    portfolio = PortfolioSummary(
        mode=mode,
        accounting_unit_mode=accounting_unit_mode,
        provenance_label=prov,
        is_synthetic_modelled=is_synth,
        monetary_accounting_enabled=has_inr,
        instrument_multiplier_inr_per_point=multiplier,
        instrument_multiplier_documentation=multiplier_doc,
        points_unit="INDEX_POINTS" if has_pts else None,
        realized_gross_points=gross_pts,
        total_slippage_points=slip_pts,
        realized_net_points=net_pts,
        unrealized_points=0.0 if has_pts else None,
        ending_cumulative_points=net_pts if has_pts else None,
        max_drawdown_points=max_dd_p if has_pts else None,
        currency_unit="INR" if has_inr else None,
        starting_capital_inr=cap,
        available_cash_inr=ending_eq_inr,
        reserved_capital_inr=0.0 if has_inr else None,
        ending_equity_inr=ending_eq_inr,
        realized_gross_pnl_inr=gross_inr,
        unrealized_pnl_inr=0.0 if has_inr else None,
        total_brokerage_inr=0.0 if has_inr else None,
        total_statutory_charges_inr=0.0 if has_inr else None,
        total_brokerage_and_statutory_inr=0.0 if has_inr else None,
        total_slippage_cost_inr=cost_inr,
        total_costs_inr=cost_inr,
        realized_net_pnl_inr=net_inr,
        net_return_pct=((float(net_inr or 0.0) / cap) * 100.0) if (has_inr and cap) else None,
        max_drawdown_inr=max_dd_i if has_inr else None,
        max_drawdown_pct=max_dd_pct if has_inr else None,
        total_signals=total_signals if total_signals is not None else len(trades),
        trades_opened=len(opened),
        trades_closed=len(closed),
        trades_rejected=sum(1 for t in trades if t.state in (TradeLifecycleState.REJECTED, TradeLifecycleState.CANCELLED)),
        partial_exits_count=sum(sum(1 for f in t.fills if f.side == OrderSide.PARTIAL_EXIT) for t in opened),
        intrabar_ambiguous_count=sum(t.intrabar_ambiguous_count for t in opened),
        winning_trades=winners,
        losing_trades=losers,
    )

    reconciliation = ReconciliationReport(
        reconciled=True,
        accounting_unit_mode=accounting_unit_mode,
        non_mixing_invariant_passed=True,
        points_reconciled=True if has_pts else None,
        points_net_identity_diff=0.0 if has_pts else None,
        points_trade_sum_gross_diff=0.0 if has_pts else None,
        points_trade_sum_slip_diff=0.0 if has_pts else None,
        points_trade_sum_net_diff=0.0 if has_pts else None,
        monetary_reconciled=True if has_inr else None,
        cash_conservation_diff_inr=0.0 if has_inr else None,
        net_pnl_identity_diff_inr=0.0 if has_inr else None,
        trade_sum_gross_diff_inr=0.0 if has_inr else None,
        trade_sum_cost_diff_inr=0.0 if has_inr else None,
        trade_sum_net_diff_inr=0.0 if has_inr else None,
        residual_reserved_capital_inr=0.0 if has_inr else None,
        open_trades_remaining=len([t for t in opened if t.state != TradeLifecycleState.CLOSED]),
        over_exited_trades=(),
        duplicate_fill_ids_detected=False,
        duplicate_order_ids_detected=False,
        failed_checks=(),
    )

    cost_sched = CostScheduleVersion(
        cost_model_version="TEST-COSTS-2026.1",
        effective_date_ist="2026-11-11",
        recorded_at_utc="2026-06-22T10:00:00+00:00",
        cost_domain=(
            "SYNTHETIC_OPTION_PREMIUM_RESEARCH"
            if is_synth
            else ("UNDERLYING_POINTS_WITH_EXPLICIT_INR" if multiplier else "UNDERLYING_POINTS_ONLY")
        ),
        slippage_unit="INR_PER_OPTION_UNIT" if is_synth else "INDEX_POINTS",
        monetary_charges_enabled=has_inr,
        instrument_multiplier_inr_per_point=multiplier,
        instrument_multiplier_documentation=multiplier_doc,
        rate_disclaimer="Isolated test cost schedule.",
        brokerage_per_order_inr=0.0,
        stt_sell_rate=0.0,
        exchange_txn_rate=0.0,
        gst_rate=0.0,
        sebi_turnover_rate=0.0,
        stamp_duty_buy_rate=0.0,
        slippage_per_unit=0.5,
    )

    return SimulationRunResult(
        run_id=run_id,
        output_fingerprint=deterministic_id("FP", run_id, len(trades)),
        status=status,
        execution_mode=EXECUTION_MODE,
        mode=mode,
        accounting_unit_mode=accounting_unit_mode,
        provenance_label=prov,
        is_synthetic_modelled=is_synth,
        instrument="NIFTY 50",
        timeframe="5m",
        historical_date_range="2026-06-15 to 2026-06-22",
        dataset_fingerprint="DATASETFP0001",
        calendar_fingerprint="CALENDARFP0001",
        replay_run_id=replay_run_id,
        simulator_version="4.3.1",
        cost_schedule=cost_sched,
        ambiguity_policy=AmbiguityPolicy.CONSERVATIVE_SL_FIRST_WITH_AMBIGUOUS_TAG,
        gap_policy=GapPolicy.ADVERSE_OPEN_FILL,
        portfolio=portfolio,
        reconciliation=reconciliation,
        equity_curve=tuple(curve),
        trades=trades,
        orders=(),
        failure_reasons=failure_reasons,
        created_at_utc=datetime(2026, 6, 22, 10, 0, tzinfo=timezone.utc),
    )


# ---------------------------------------------------------------------------
# 1. Exact Metric Formulas & Analytic Verification
# ---------------------------------------------------------------------------


def test_analytic_performance_metrics_exact_formulas() -> None:
    trades = (
        _make_trade(
            idx=1,
            entry_time_ist="2026-06-15T09:20:00+05:30",
            exit_time_ist="2026-06-15T09:35:00+05:30",
            gross_points=26.0,
            slippage_points=1.0,
            net_points=25.0,
            entry_price=24000.0,
            stop_loss=23980.0,
            target_1=24040.0,
        ),
        _make_trade(
            idx=2,
            entry_time_ist="2026-06-15T10:00:00+05:30",
            exit_time_ist="2026-06-15T10:25:00+05:30",
            gross_points=-9.0,
            slippage_points=1.0,
            net_points=-10.0,
            entry_price=24010.0,
            stop_loss=23990.0,
            target_1=24050.0,
            final_exit_reason=ExitReason.STOP_LOSS,
        ),
        _make_trade(
            idx=3,
            entry_time_ist="2026-06-15T11:45:00+05:30",
            exit_time_ist="2026-06-15T12:15:00+05:30",
            gross_points=16.0,
            slippage_points=1.0,
            net_points=15.0,
            entry_price=24020.0,
            stop_loss=24000.0,
            target_1=24060.0,
        ),
        _make_trade(
            idx=4,
            entry_time_ist="2026-06-15T13:50:00+05:30",
            exit_time_ist="2026-06-15T14:20:00+05:30",
            gross_points=-4.0,
            slippage_points=1.0,
            net_points=-5.0,
            entry_price=24030.0,
            stop_loss=24010.0,
            target_1=24070.0,
            final_exit_reason=ExitReason.STOP_LOSS,
        ),
    )
    curve = [
        ("2026-06-15T09:20:00+05:30", 0.0),
        ("2026-06-15T09:35:00+05:30", 25.0),
        ("2026-06-15T10:25:00+05:30", 15.0),  # dd = 10.0
        ("2026-06-15T12:15:00+05:30", 30.0),
        ("2026-06-15T14:20:00+05:30", 25.0),  # dd = 5.0
    ]
    run = _build_run(trades=trades, equity_points_series=curve)
    report = BacktestAnalyticsEngine().evaluate_simulation_run(run)

    perf = report.performance_summary
    pm = perf.points_metrics
    assert pm is not None
    assert perf.inr_metrics is None
    assert perf.reconciliation_verified is True
    assert perf.max_consecutive_wins == 1
    assert perf.max_consecutive_losses == 1
    assert perf.current_streak_type == "LOSS"
    assert perf.current_streak_count == 1
    # Durations: 15m, 25m, 30m, 30m => mean 25m = 1500s
    assert perf.average_holding_duration_seconds == pytest.approx(1500.0)
    assert perf.average_holding_duration_minutes == pytest.approx(25.0)
    assert perf.median_holding_duration_seconds == pytest.approx(1650.0)

    assert pm.total_closed_trades == 4
    assert pm.winning_trades == 2
    assert pm.losing_trades == 2
    assert pm.win_rate == pytest.approx(0.5)
    assert pm.win_rate_pct == pytest.approx(50.0)
    assert pm.gross_pnl == pytest.approx(29.0)
    assert pm.total_costs == pytest.approx(4.0)
    assert pm.net_pnl == pytest.approx(25.0)
    assert pm.average_win == pytest.approx(20.0)
    assert pm.average_loss == pytest.approx(-7.5)
    assert pm.average_loss_abs == pytest.approx(7.5)
    assert pm.largest_win == pytest.approx(25.0)
    assert pm.largest_loss == pytest.approx(-10.0)
    assert pm.profit_factor == pytest.approx(40.0 / 15.0)
    assert pm.profit_factor_status == MetricAvailabilityStatus.AVAILABLE
    assert pm.expectancy == pytest.approx(6.25)
    # Expectancy consistency: win_rate * avg_win + loss_rate * avg_loss
    assert pm.expectancy == pytest.approx(pm.win_rate * pm.average_win + (1.0 - pm.win_rate) * pm.average_loss)
    assert pm.average_risk_reward == pytest.approx(20.0 / 7.5)
    assert pm.average_planned_risk_reward == pytest.approx(2.0)  # 40 / 20
    assert pm.average_realized_r_multiple == pytest.approx((1.25 - 0.5 + 0.75 - 0.25) / 4.0)
    assert pm.max_drawdown == pytest.approx(10.0)
    assert pm.recovery_factor == pytest.approx(25.0 / 10.0)
    assert pm.recovery_factor_status == MetricAvailabilityStatus.AVAILABLE


# ---------------------------------------------------------------------------
# 2, 3, 4. Edge-Case / Zero-Denominator Tests (No inf/nan or fabrication)
# ---------------------------------------------------------------------------


def test_zero_trades_and_non_completed_runs_handled_safely() -> None:
    empty_run = _build_run(run_id="SIM-EMPTY001", trades=(), equity_points_series=[])
    rep = BacktestAnalyticsEngine().evaluate_simulation_run(empty_run)
    assert rep.status == AnalyticsStatus.NO_TRADES
    pm = rep.performance_summary.points_metrics
    assert pm is not None
    assert pm.total_closed_trades == 0
    assert pm.win_rate is None
    assert pm.profit_factor is None
    assert pm.profit_factor_status == MetricAvailabilityStatus.NO_CLOSED_TRADES
    assert pm.recovery_factor is None
    assert pm.recovery_factor_status == MetricAvailabilityStatus.NO_CLOSED_TRADES
    assert pm.expectancy is None

    failed_run = _build_run(
        run_id="SIM-FAIL001",
        trades=(),
        status=SimulationStatus.FAILED_INTEGRITY,
        failure_reasons=("DATA_INTEGRITY_FAILED",),
    )
    rep_fail = BacktestAnalyticsEngine().evaluate_simulation_run(failed_run)
    assert rep_fail.status == AnalyticsStatus.RUN_NOT_COMPLETED
    assert any("DATA_INTEGRITY_FAILED" in w for w in rep_fail.data_quality_warnings)


def test_zero_loss_profit_factor_and_zero_drawdown_recovery_factor() -> None:
    # Monotonically winning trades with zero drawdown -> both ratios strictly None with explicit reasons
    trades = (
        _make_trade(
            idx=1,
            entry_time_ist="2026-06-15T09:20:00+05:30",
            exit_time_ist="2026-06-15T09:40:00+05:30",
            gross_points=12.0,
            slippage_points=1.0,
            net_points=11.0,
        ),
        _make_trade(
            idx=2,
            entry_time_ist="2026-06-15T10:15:00+05:30",
            exit_time_ist="2026-06-15T10:35:00+05:30",
            gross_points=15.0,
            slippage_points=1.0,
            net_points=14.0,
        ),
    )
    curve = [
        ("2026-06-15T09:20:00+05:30", 0.0),
        ("2026-06-15T09:40:00+05:30", 11.0),
        ("2026-06-15T10:35:00+05:30", 25.0),
    ]
    run = _build_run(trades=trades, equity_points_series=curve)
    rep = BacktestAnalyticsEngine().evaluate_simulation_run(run)
    pm = rep.performance_summary.points_metrics
    rk = rep.risk_summary.points_risk
    assert pm is not None and rk is not None
    assert pm.profit_factor is None
    assert pm.profit_factor_status == MetricAvailabilityStatus.ZERO_LOSS_UNDEFINED
    assert pm.average_risk_reward is None
    assert pm.average_risk_reward_status == MetricAvailabilityStatus.NO_LOSING_TRADES
    assert pm.largest_loss is None
    assert rk.max_drawdown == 0.0
    assert rk.recovery_factor is None
    assert rk.recovery_factor_status == MetricAvailabilityStatus.ZERO_DRAWDOWN_UNDEFINED
    assert rk.episodes_count == 0
    assert rk.is_currently_in_drawdown is False


# ---------------------------------------------------------------------------
# 5, 6. Partial Exits & Net P&L Reconciliation Verification
# ---------------------------------------------------------------------------


def test_partial_exits_and_reconciliation_verification() -> None:
    trades = (
        _make_trade(
            idx=1,
            entry_time_ist="2026-06-16T09:30:00+05:30",
            exit_time_ist="2026-06-16T10:15:00+05:30",
            gross_points=30.0,
            slippage_points=2.0,
            net_points=28.0,
            initial_quantity=2,
            partial_exit=True,
            final_exit_reason=ExitReason.TARGET_2,
        ),
        _make_trade(
            idx=2,
            entry_time_ist="2026-06-16T11:00:00+05:30",
            exit_time_ist=None,
            gross_points=5.0,
            slippage_points=0.5,
            net_points=4.5,
            initial_quantity=2,
            exited_quantity=1,
            remaining_quantity=1,
            state=TradeLifecycleState.PARTIALLY_EXITED,
            partial_exit=True,
            final_exit_reason=None,
        ),
    )
    run_ok = _build_run(trades=trades, equity_points_series=[("2026-06-16T15:25:00+05:30", 32.5)])
    rep_ok = BacktestAnalyticsEngine().evaluate_simulation_run(run_ok)
    assert rep_ok.performance_summary.trades_closed == 1
    assert rep_ok.performance_summary.trades_open == 1
    assert rep_ok.performance_summary.partial_exits_count == 2
    assert rep_ok.performance_summary.reconciliation_verified is True
    assert rep_ok.performance_summary.net_pnl_reconciliation_diff_points == pytest.approx(0.0)
    assert any("OPEN_TRADES_EXCLUDED=1" in w for w in rep_ok.data_quality_warnings)

    # Discrepancy detection when portfolio summary disagrees with trade records
    run_bad = _build_run(
        trades=(trades[0],),
        equity_points_series=[("2026-06-16T10:15:00+05:30", 28.0)],
        override_realized_net_points=999.0,
    )
    rep_bad = BacktestAnalyticsEngine().evaluate_simulation_run(run_bad)
    assert rep_bad.performance_summary.reconciliation_verified is False
    assert any("RECONCILIATION_WARNING" in w for w in rep_bad.data_quality_warnings)


# ---------------------------------------------------------------------------
# 7. Drawdown Episodes, Ulcer Index & Unrecovered Tail Episode
# ---------------------------------------------------------------------------


def test_drawdown_episodes_recovered_and_unrecovered_with_ulcer_index() -> None:
    trades = (
        _make_trade(
            idx=1,
            entry_time_ist="2026-06-17T09:20:00+05:30",
            exit_time_ist="2026-06-17T09:50:00+05:30",
            gross_points=-19.0,
            slippage_points=1.0,
            net_points=-20.0,
            final_exit_reason=ExitReason.STOP_LOSS,
        ),
        _make_trade(
            idx=2,
            entry_time_ist="2026-06-17T10:00:00+05:30",
            exit_time_ist="2026-06-17T11:00:00+05:30",
            gross_points=31.0,
            slippage_points=1.0,
            net_points=30.0,
            intrabar_ambiguous_count=1,
        ),
    )
    curve = [
        ("2026-06-17T09:20:00+05:30", 10.0),   # Peak 10
        ("2026-06-17T09:35:00+05:30", 2.0),    # DD 8
        ("2026-06-17T09:50:00+05:30", -10.0),  # Trough -10 -> DD 20
        ("2026-06-17T10:20:00+05:30", 12.0),   # Recovered! Episode 1 closed at new peak 12
        ("2026-06-17T11:00:00+05:30", 6.0),    # Unrecovered DD 6 -> Episode 2 open
    ]
    run = _build_run(trades=trades, equity_points_series=curve)
    risk = RiskAnalyticsEngine().evaluate_run(run).points_risk
    assert risk is not None
    assert risk.max_drawdown == pytest.approx(20.0)
    assert risk.episodes_count == 2
    ep1, ep2 = risk.episodes
    assert ep1.recovered is True
    assert ep1.peak_time_ist == "2026-06-17T09:20:00+05:30"
    assert ep1.trough_time_ist == "2026-06-17T09:50:00+05:30"
    assert ep1.recovery_time_ist == "2026-06-17T10:20:00+05:30"
    assert ep1.duration_bars == 3
    assert ep1.duration_seconds == pytest.approx(3600.0)

    assert ep2.recovered is False
    assert ep2.recovery_time_ist is None
    assert ep2.max_drawdown == pytest.approx(6.0)
    assert risk.is_currently_in_drawdown is True
    assert risk.current_drawdown == pytest.approx(6.0)
    # Conservative Step 4.3 rule: trade 2 was ambiguous so winning_trades=0, losing_trades=2 => streak=2
    assert risk.max_consecutive_losses == 2
    expected_ulcer = ((0.0**2 + 8.0**2 + 20.0**2 + 0.0**2 + 6.0**2) / 5.0) ** 0.5
    assert risk.ulcer_index_points == pytest.approx(expected_ulcer)
    assert risk.ulcer_index_pct is None


# ---------------------------------------------------------------------------
# 8. IST Time-Series Bucketing & UTC Offset Conversion
# ---------------------------------------------------------------------------


def test_ist_time_series_aggregation_with_utc_conversion() -> None:
    # Check UTC -> IST rollover across midnight, month boundary, week boundary, and IST sessions:
    # Trade 1: UTC 2026-06-19T04:00:00Z = IST 2026-06-19 09:30 (OPENING), exits 10:00 IST (MORNING)
    # Trade 2: UTC 2026-06-19T18:40:00Z = IST 2026-06-20 00:10 (day rollover to 2026-06-20!)
    # Trade 3: IST 2026-07-02T14:50:00+05:30 (CLOSING, next month 2026-07 and next week)
    trades = (
        _make_trade(
            idx=1,
            entry_time_ist="2026-06-19T04:00:00Z",  # 09:30 IST -> OPENING
            exit_time_ist="2026-06-19T04:30:00Z",   # 10:00 IST -> 2026-06-19
            gross_points=11.0,
            slippage_points=1.0,
            net_points=10.0,
        ),
        _make_trade(
            idx=2,
            entry_time_ist="2026-06-19T18:35:00Z",  # 2026-06-20 00:05 IST -> OUTSIDE_REGULAR_SESSION
            exit_time_ist="2026-06-19T18:40:00Z",   # 2026-06-20 00:10 IST -> 2026-06-20
            gross_points=-4.0,
            slippage_points=1.0,
            net_points=-5.0,
            final_exit_reason=ExitReason.STOP_LOSS,
        ),
        _make_trade(
            idx=3,
            entry_time_ist="2026-07-02T14:50:00+05:30",  # CLOSING
            exit_time_ist="2026-07-02T15:10:00+05:30",   # 2026-07-02
            gross_points=21.0,
            slippage_points=1.0,
            net_points=20.0,
        ),
    )
    run = _build_run(
        trades=trades,
        equity_points_series=[("2026-06-19T04:00:00Z", 0.0), ("2026-07-02T15:10:00+05:30", 25.0)],
    )
    ts = TimeSeriesAnalyticsEngine().evaluate_run(run)

    assert ts.timezone_name == "Asia/Kolkata"
    assert ts.reconciliation_matches_totals is True
    daily_keys = [b.bucket_key for b in ts.daily]
    assert daily_keys == ["2026-06-19", "2026-06-20", "2026-07-02"]
    assert [b.bucket_key for b in ts.monthly] == ["2026-06", "2026-07"]
    assert len(ts.weekly) == 2
    session_keys = [b.bucket_key for b in ts.session_wise]
    assert session_keys == [
        MarketSessionBucket.OPENING.value,
        MarketSessionBucket.CLOSING.value,
        MarketSessionBucket.OUTSIDE_REGULAR_SESSION.value,
    ]
    assert ts.equity_curve[0].date_ist == "2026-06-19"
    assert ts.equity_curve[0].session_ist == MarketSessionBucket.OPENING
    assert classify_ist_session(datetime(2026, 6, 19, 15, 30, tzinfo=IST_ZONE)) == MarketSessionBucket.CLOSING


# ---------------------------------------------------------------------------
# 9. Three-Way Accounting Domain Segregation & Mixed-Domain Rejection
# ---------------------------------------------------------------------------


def test_accounting_mode_segregation_and_mixed_domain_rejection() -> None:
    # Case A: Monetary Mode A (INDEX_POINTS_AND_EXPLICIT_INR)
    mult = 75.0
    doc = "NSE NIFTY 50 standard lot multiplier = 75 INR per index point"
    t_mon = (
        _make_trade(
            idx=1,
            entry_time_ist="2026-06-18T09:20:00+05:30",
            exit_time_ist="2026-06-18T10:00:00+05:30",
            gross_points=21.0,
            slippage_points=1.0,
            net_points=20.0,
            gross_pnl_inr=21.0 * 75.0,
            total_costs_inr=75.0,
            net_pnl_inr=20.0 * 75.0,
            accounting_unit_mode=AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR,
            multiplier=mult,
            multiplier_doc=doc,
        ),
    )
    run_mon = _build_run(
        run_id="SIM-MON001",
        trades=t_mon,
        equity_points_series=[("2026-06-18T10:00:00+05:30", 20.0)],
        equity_inr_series=[("2026-06-18T10:00:00+05:30", 500000.0 + 1500.0)],
        accounting_unit_mode=AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR,
        starting_capital_inr=500000.0,
        multiplier=mult,
        multiplier_doc=doc,
    )
    rep_mon = BacktestAnalyticsEngine().evaluate_simulation_run(run_mon)
    assert rep_mon.performance_summary.points_metrics is not None
    assert rep_mon.performance_summary.inr_metrics is not None
    assert rep_mon.performance_summary.points_metrics.max_drawdown_pct is None
    assert rep_mon.performance_summary.inr_metrics.net_pnl == pytest.approx(1500.0)
    assert rep_mon.performance_summary.inr_metrics.net_return_pct == pytest.approx(0.3)

    # Case B: Mode B (SYNTHETIC_OPTION_INR_ONLY)
    t_opt = (
        _make_trade(
            idx=2,
            entry_time_ist="2026-06-18T11:00:00+05:30",
            exit_time_ist="2026-06-18T12:00:00+05:30",
            gross_pnl_inr=2200.0,
            total_costs_inr=200.0,
            net_pnl_inr=2000.0,
            accounting_unit_mode=AccountingUnitMode.SYNTHETIC_OPTION_INR_ONLY,
            mode=SimulationMode.SYNTHETIC_BS_RESEARCH,
            entry_price=120.0,
            stop_loss=90.0,
            target_1=180.0,
            initial_quantity=75,
        ),
    )
    run_opt = _build_run(
        run_id="SIM-OPT001",
        trades=t_opt,
        equity_inr_series=[("2026-06-18T12:00:00+05:30", 502000.0)],
        accounting_unit_mode=AccountingUnitMode.SYNTHETIC_OPTION_INR_ONLY,
        mode=SimulationMode.SYNTHETIC_BS_RESEARCH,
        starting_capital_inr=500000.0,
    )
    rep_opt = BacktestAnalyticsEngine().evaluate_simulation_run(run_opt)
    assert rep_opt.performance_summary.points_metrics is None
    assert rep_opt.performance_summary.inr_metrics is not None
    assert rep_opt.dataset_provenance.is_synthetic_modelled is True
    assert rep_opt.dataset_provenance.provenance_label == "SYNTHETIC_MODELLED_OPTION_PNL"
    assert any("SYNTHETIC_MODELLED_OPTION_PNL" in w for w in rep_opt.data_quality_warnings)

    # Mixed-domain walk-forward pair must fail closed
    run_pts = _build_run(run_id="SIM-PTS001", trades=())
    spec = WalkForwardWindowSpec(
        window_id="WF-MIX",
        is_start_ist="2026-06-15T09:15:00+05:30",
        is_end_ist="2026-06-17T15:30:00+05:30",
        oos_start_ist="2026-06-18T09:15:00+05:30",
        oos_end_ist="2026-06-19T15:30:00+05:30",
    )
    with pytest.raises(ValueError, match="MIXED_DOMAIN_ANALYTICS_FORBIDDEN"):
        WalkForwardEvaluator().evaluate_run_pairs([(spec, run_pts, run_opt)])


# ---------------------------------------------------------------------------
# 10, 11. Walk-Forward Chronology, Purge/Embargo, No-Lookahead & Sample Discipline
# ---------------------------------------------------------------------------


def test_walk_forward_purge_embargo_and_no_lookahead_assertions() -> None:
    # Lookahead window rejected at schema level
    with pytest.raises(ValueError, match="WALK_FORWARD_LOOKAHEAD_VIOLATION"):
        WalkForwardWindowSpec(
            window_id="BAD",
            is_start_ist="2026-06-15T09:15:00+05:30",
            is_end_ist="2026-06-18T15:30:00+05:30",
            oos_start_ist="2026-06-18T09:15:00+05:30",  # before is_end!
            oos_end_ist="2026-06-20T15:30:00+05:30",
        )

    wins = generate_walk_forward_windows(
        start_ist="2026-06-01T09:15:00+05:30",
        end_ist="2026-06-22T09:15:00+05:30",
        scheme="ANCHORED_EXPANDING",
        is_duration=timedelta(days=7),
        oos_duration=timedelta(days=7),
        purge_duration_seconds=3600.0,
        embargo_duration_seconds=1800.0,
    )
    assert len(wins) == 2

    # Trades testing purge & embargo inside fold 1 [Jun 01..Jun 08) IS, [Jun 08..Jun 15) OOS
    trades = (
        # Valid clean IS trade
        _make_trade(
            idx=1,
            entry_time_ist="2026-06-02T10:00:00+05:30",
            exit_time_ist="2026-06-02T11:00:00+05:30",
            gross_points=21.0,
            slippage_points=1.0,
            net_points=20.0,
        ),
        # Boundary-overlapping IS trade -> PURGED (exits within 1h purge window before 09:15 Jun 08)
        _make_trade(
            idx=2,
            entry_time_ist="2026-06-08T08:00:00+05:30",
            exit_time_ist="2026-06-08T09:30:00+05:30",
            gross_points=-50.0,
            slippage_points=1.0,
            net_points=-51.0,
        ),
        # Pre-embargo OOS trade (enters within 30m embargo after 09:15 Jun 08) -> EMBARGOED
        _make_trade(
            idx=3,
            entry_time_ist="2026-06-08T09:20:00+05:30",
            exit_time_ist="2026-06-08T10:00:00+05:30",
            gross_points=99.0,
            slippage_points=1.0,
            net_points=98.0,
        ),
        # Clean OOS trade
        _make_trade(
            idx=4,
            entry_time_ist="2026-06-10T10:00:00+05:30",
            exit_time_ist="2026-06-10T11:00:00+05:30",
            gross_points=11.0,
            slippage_points=1.0,
            net_points=10.0,
        ),
    )
    run = _build_run(trades=trades, equity_points_series=[("2026-06-10T11:00:00+05:30", 77.0)])
    wf = WalkForwardEvaluator().evaluate_run(run, (wins[0],), window_scheme="ANCHORED_EXPANDING")

    assert wf.chronological_only is True
    assert wf.shuffling_used is False
    assert wf.no_lookahead_verified is True
    assert wf.total_purged_is_trades == 1
    assert wf.total_embargoed_oos_trades == 1
    assert wf.windows[0].purged_is_trade_ids == ("TRD-0002",)
    assert wf.windows[0].embargoed_oos_trade_ids == ("TRD-0003",)
    assert wf.windows[0].is_trades_count == 1
    assert wf.windows[0].oos_trades_count == 1
    assert wf.windows[0].oos_degradation_ratio_points == pytest.approx(10.0 / 20.0)
    assert wf.aggregate_oos_significance_status == SignificanceStatus.INSUFFICIENT_SAMPLE
    assert wf.statistical_significance_claimed is False

    # Lookahead leak across IS/OOS pair must raise
    bad_oos_run = _build_run(
        run_id="SIM-OOSBAD",
        trades=(
            _make_trade(
                idx=9,
                signal_available_at_ist="2026-06-07T14:00:00+05:30",
                entry_time_ist="2026-06-07T14:05:00+05:30",  # strictly inside IS!
                exit_time_ist="2026-06-07T14:30:00+05:30",
                gross_points=10.0,
                slippage_points=0.0,
                net_points=10.0,
            ),
        ),
    )
    is_run = _build_run(run_id="SIM-ISOK", trades=(trades[0],))
    with pytest.raises(ValueError, match="WALK_FORWARD_LOOKAHEAD_VIOLATION"):
        WalkForwardEvaluator().evaluate_run_pairs([(wins[0], is_run, bad_oos_run)])


def test_zero_variance_statistical_significance_discipline() -> None:
    # 35 identical trades => n >= 30, ZERO_VARIANCE, never significance claimed
    identical_trades = tuple(
        _make_trade(
            idx=i + 1,
            entry_time_ist=f"2026-06-18T10:{(i % 50):02d}:00+05:30",
            exit_time_ist=f"2026-06-18T10:{(i % 50) + 5:02d}:00+05:30",
            gross_points=11.0,
            slippage_points=1.0,
            net_points=10.0,
        )
        for i in range(35)
    )
    spec = WalkForwardWindowSpec(
        window_id="WF-ZV",
        is_start_ist="2026-06-01T09:15:00+05:30",
        is_end_ist="2026-06-10T15:30:00+05:30",
        oos_start_ist="2026-06-11T09:15:00+05:30",
        oos_end_ist="2026-06-25T15:30:00+05:30",
    )
    run = _build_run(trades=identical_trades)
    wf = WalkForwardEvaluator().evaluate_run(run, (spec,))
    assert wf.aggregate_oos_significance_status == SignificanceStatus.ZERO_VARIANCE
    assert wf.oos_t_stat_points is None
    assert wf.statistical_significance_claimed is False


# ---------------------------------------------------------------------------
# 12. Strategy Attribution UNKNOWN Metadata & No Score Calibration
# ---------------------------------------------------------------------------


def test_strategy_analytics_keeps_missing_metadata_unknown_and_preserves_scores() -> None:
    trades = (
        _make_trade(
            idx=1,
            entry_time_ist="2026-06-19T09:30:00+05:30",
            exit_time_ist="2026-06-19T10:00:00+05:30",
            gross_points=16.0,
            slippage_points=1.0,
            net_points=15.0,
        ),
        _make_trade(
            idx=2,
            entry_time_ist="2026-06-19T14:00:00+05:30",
            exit_time_ist="2026-06-19T14:30:00+05:30",
            gross_points=-9.0,
            slippage_points=1.0,
            net_points=-10.0,
            direction=SignalDirection.SHORT,
            timeframe="15m",
            entry_price=24000.0,
            stop_loss=24020.0,
            target_1=23960.0,
            final_exit_reason=ExitReason.STOP_LOSS,
        ),
    )
    run = _build_run(trades=trades)
    strat_plain = StrategyAnalyticsEngine().evaluate_run(run)
    assert strat_plain.ict_score_status == "UNAVAILABLE"
    assert strat_plain.ict_calibration_status == "NOT_CALIBRATED"
    # Missing setup/regime/session/entry_reason MUST NOT be inferred from timestamps
    assert [b.category for b in strat_plain.by_ict_setup] == [UNKNOWN_LABEL]
    assert [b.category for b in strat_plain.by_market_regime] == [UNKNOWN_LABEL]
    assert [b.category for b in strat_plain.by_session] == [UNKNOWN_LABEL]
    assert [b.category for b in strat_plain.by_entry_reason] == [UNKNOWN_LABEL]
    assert strat_plain.unknown_metadata_counts["ict_smc_setup"] == 2
    assert strat_plain.unknown_metadata_counts["session"] == 2

    # Explicit metadata & linked uncalibrated ReplayPointResult populated cleanly
    replay_pt = ReplayPointResult(
        as_of_time_ist="2026-06-19T09:25:00+05:30",
        report_id="MTF-RPT-1",
        overall_alignment="BULLISH_ALIGNED",
        data_quality_status="VERIFIED_EOD",
        score_status="UNAVAILABLE",
        calibration_status="NOT_CALIBRATED",
        confluence_score=None,
        report={"session_context": {"current_session": "OPENING"}},
    )
    replay_rec = ReplayRunRecord(
        run_id="RPL-TEST01",
        instrument="NIFTY 50",
        timeframes=("5m",),
        start_date_ist="2026-06-19",
        end_date_ist="2026-06-19",
        historical_date_range="2026-06-19..2026-06-19",
        data_source="isolated_backtest_store",
        dataset_fingerprint="DS1",
        engine_version="3.7",
        configuration_version="4.2",
        calendar_source="exchange_calendar",
        calendar_fingerprint="CAL1",
        replay_timestamps_ist=("2026-06-19T09:25:00+05:30",),
        output_fingerprint="OFP1",
        validation_status=ReplayValidationStatus.VALIDATED,
        point_count=1,
        points=(replay_pt,),
        created_at_utc=datetime(2026, 6, 19, 10, 0, tzinfo=timezone.utc),
    )
    sig1 = SimulationSignal(
        signal_id="SIG-0001",
        instrument="NIFTY 50",
        timeframe="5m",
        signal_available_at_ist=datetime(2026, 6, 19, 9, 25, tzinfo=IST_ZONE),
        direction=SignalDirection.LONG,
        trigger_domain=TriggerPriceDomain.UNDERLYING_POINTS,
        stop_loss=23980.0,
        target_1=24040.0,
        quantity_units=1,
        source_report_id="MTF-RPT-1",
    )
    meta = {
        "TRD-0002": TradeEvaluationMetadata(
            ict_smc_setup="BEARISH_OB_FVG",
            market_regime="TRENDING_DOWN",
            entry_reason="CHOCH_RETEST",
        )
    }
    strat_rich = StrategyAnalyticsEngine().evaluate_run(
        run,
        trade_metadata=meta,
        signals=[sig1],
        replay_run=replay_rec,
    )
    setups = {b.category for b in strat_rich.by_ict_setup}
    assert setups == {"BULLISH_ALIGNED", "BEARISH_OB_FVG"}
    assert strat_rich.ict_score_status == "UNAVAILABLE"
    assert strat_rich.ict_calibration_status == "NOT_CALIBRATED"

    # Reject calibrated/scored Phase 3 tampering
    bad_replay = replay_rec.model_copy(
        update={"points": (replay_pt.model_copy(update={"confluence_score": 82.5}),)}
    )
    with pytest.raises(ValueError, match="GOVERNANCE_VIOLATION"):
        StrategyAnalyticsEngine().evaluate_run(run, replay_run=bad_replay)


# ---------------------------------------------------------------------------
# 13. Determinism, Markdown Rendering & Isolated Persistence Round-Trip
# ---------------------------------------------------------------------------


def test_determinism_markdown_and_isolated_store_round_trip(tmp_path: Path) -> None:
    trades = (
        _make_trade(
            idx=1,
            entry_time_ist="2026-06-19T09:30:00+05:30",
            exit_time_ist="2026-06-19T10:15:00+05:30",
            gross_points=21.0,
            slippage_points=1.0,
            net_points=20.0,
        ),
    )
    run = _build_run(trades=trades, equity_points_series=[("2026-06-19T10:15:00+05:30", 20.0)])

    db_file = tmp_path / "isolated_backtest_analytics.db"
    store = BacktestAnalyticsStore(db_path=db_file)
    engine = BacktestAnalyticsEngine(analytics_store=store)

    r1 = engine.evaluate_simulation_run(run, persist=True)
    r2 = engine.evaluate_simulation_run(run, persist=False)

    assert r1.report_id == r2.report_id
    assert r1.report_fingerprint == r2.report_fingerprint
    assert r1.reproducibility_metadata.report_fingerprint == r1.report_fingerprint

    loaded = store.get_report(r1.report_id)
    assert loaded is not None
    assert loaded.report_fingerprint == r1.report_fingerprint
    assert loaded.performance_summary == r1.performance_summary
    rows = store.list_reports(run_id=run.run_id)
    assert len(rows) == 1
    assert rows[0]["report_id"] == r1.report_id

    md = render_markdown_report(r1)
    assert EXECUTION_MODE in md
    assert r1.report_id in md
    assert "Index Points Domain" in md

    # Must reject protected filenames
    with pytest.raises(PermissionError, match="ISOLATION VIOLATION"):
        BacktestAnalyticsStore(db_path=tmp_path / "aivolve_trading.db")


# ---------------------------------------------------------------------------
# 14. End-to-End Step 4.3 Simulator Integration & Persisted Run Verification
# ---------------------------------------------------------------------------


def test_end_to_end_simulator_and_persisted_backtest_runs(tmp_path: Path) -> None:
    # Fresh Step 4.3 deterministic simulator -> Step 4.4 analytics pipeline in isolated temp store
    cfg = BacktestConfiguration(
        storage_db_path=str(tmp_path / "step44_e2e_backtest.db"),
        sensex_governance_approved=False,
    )
    cal = HistoricalMarketCalendarAdapter()
    store = HistoricalDataStore(config=cfg)

    bars: List[Dict[str, object]] = []
    t0 = datetime(2026, 6, 19, 9, 15, tzinfo=IST_ZONE)
    prev_close = 24000.0
    for i in range(75):
        dt = t0 + timedelta(minutes=5 * i)
        o = prev_close
        c = prev_close + (5.0 if i < 12 else 0.5)
        h = max(o, c) + 2.0
        lo = min(o, c) - 2.0
        bars.append(
            {
                "timestamp": dt,
                "open": o,
                "high": h,
                "low": lo,
                "close": c,
                "volume": 10000 + i * 100,
            }
        )
        prev_close = c
    df = pd.DataFrame(bars)
    store.save_candles(
        df,
        instrument="NIFTY 50",
        timeframe="5m",
        calendar_adapter=cal,
        requested_from_ist=t0,
        requested_to_ist=t0 + timedelta(minutes=5 * 74),
        strict_missing_intervals=True,
    )

    sig = SimulationSignal(
        signal_id="SIG-E2E-1",
        instrument="NIFTY 50",
        timeframe="5m",
        signal_available_at_ist=t0 + timedelta(minutes=10),
        direction=SignalDirection.LONG,
        trigger_domain=TriggerPriceDomain.UNDERLYING_POINTS,
        stop_loss=23980.0,
        target_1=24028.0,
        target_2=24048.0,
        quantity_units=2,
    )
    sim = HistoricalExecutionSimulator(
        data_store=store,
        calendar_adapter=cal,
        backtest_config=cfg,
        config=SimulationConfiguration(
            mode=SimulationMode.UNDERLYING_POINTS_ONLY,
            monetary_accounting_enabled=False,
            storage_db_path=cfg.storage_db_path,
        ),
    )
    sim_res = sim.run_simulation(
        instrument="NIFTY 50",
        timeframe="5m",
        signals=[sig],
        persist=True,
    )

    analytics_store = BacktestAnalyticsStore(config=cfg)
    analytics_engine = BacktestAnalyticsEngine(data_store=store, analytics_store=analytics_store)
    report = analytics_engine.evaluate_stored_run(sim_res.run_id, signals=[sig], persist=True)
    assert report.execution_mode == EXECUTION_MODE
    assert report.status == AnalyticsStatus.COMPLETED
    assert report.performance_summary.reconciliation_verified is True
    assert report.performance_summary.points_metrics is not None
    assert report.performance_summary.inr_metrics is None

    # If persisted Step 4.3 foundation DB exists in repo, validate read-only via temp copy
    if DEFAULT_BACKTEST_DB_PATH.exists():
        copy_db = tmp_path / "backtest_foundation_copy.db"
        shutil.copy2(DEFAULT_BACKTEST_DB_PATH, copy_db)
        copy_store = HistoricalDataStore(db_path=copy_db)
        copy_analytics_store = BacktestAnalyticsStore(db_path=copy_db)
        copy_engine = BacktestAnalyticsEngine(data_store=copy_store, analytics_store=copy_analytics_store)
        runs = copy_store.list_simulation_runs()
        assert len(runs) >= 1
        for row in runs:
            r = copy_engine.evaluate_stored_run(row["run_id"], persist=True)
            assert r.execution_mode == EXECUTION_MODE
            assert r.performance_summary.reconciliation_verified is True
            assert copy_analytics_store.get_report(r.report_id) is not None


def test_walk_forward_rolling_split_multiplier_mismatch_and_inr_ulcer() -> None:
    rolling = generate_walk_forward_windows(
        start_ist="2026-06-01T09:15:00+05:30",
        end_ist="2026-06-22T09:15:00+05:30",
        scheme="ROLLING",
        is_duration=timedelta(days=7),
        oos_duration=timedelta(days=7),
        step_duration=timedelta(days=7),
    )
    assert len(rolling) == 2
    assert rolling[1].is_start_ist > rolling[0].is_start_ist

    split = generate_walk_forward_windows(
        start_ist="2026-06-01T09:15:00+05:30",
        end_ist="2026-06-11T09:15:00+05:30",
        scheme="IS_OOS_SPLIT",
        is_ratio=0.7,
    )
    assert len(split) == 1

    # Out-of-order window sequence must fail closed
    empty_run = _build_run(run_id="SIM-ORD", trades=())
    with pytest.raises(ValueError, match="WALK_FORWARD_CHRONOLOGY_VIOLATION"):
        WalkForwardEvaluator().evaluate_run(empty_run, [rolling[1], rolling[0]])

    # Mixed explicit multipliers across monetary Mode A runs must fail closed
    r_m75 = _build_run(
        run_id="SIM-M75",
        trades=(),
        accounting_unit_mode=AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR,
        starting_capital_inr=100000.0,
        multiplier=75.0,
        multiplier_doc="NIFTY 50 75 INR per point lot",
    )
    r_m30 = _build_run(
        run_id="SIM-M30",
        trades=(),
        accounting_unit_mode=AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR,
        starting_capital_inr=100000.0,
        multiplier=30.0,
        multiplier_doc="BANK NIFTY 30 INR per point lot",
    )
    with pytest.raises(ValueError, match="MIXED_DOMAIN_ANALYTICS_FORBIDDEN"):
        WalkForwardEvaluator().evaluate_run_pairs([(split[0], r_m75, r_m30)])

    # Verify INR risk domain populates ulcer_index_pct and forbids ulcer_index_points
    t_opt = _make_trade(
        idx=1,
        entry_time_ist="2026-06-18T10:00:00+05:30",
        exit_time_ist="2026-06-18T10:30:00+05:30",
        gross_pnl_inr=-4500.0,
        total_costs_inr=500.0,
        net_pnl_inr=-5000.0,
        accounting_unit_mode=AccountingUnitMode.SYNTHETIC_OPTION_INR_ONLY,
        mode=SimulationMode.SYNTHETIC_BS_RESEARCH,
        entry_price=120.0,
        stop_loss=90.0,
        target_1=180.0,
        initial_quantity=75,
        final_exit_reason=ExitReason.STOP_LOSS,
    )
    r_opt = _build_run(
        run_id="SIM-INRULCER",
        trades=(t_opt,),
        equity_inr_series=[
            ("2026-06-18T10:00:00+05:30", 100000.0),
            ("2026-06-18T10:15:00+05:30", 98000.0),
            ("2026-06-18T10:30:00+05:30", 95000.0),
        ],
        accounting_unit_mode=AccountingUnitMode.SYNTHETIC_OPTION_INR_ONLY,
        mode=SimulationMode.SYNTHETIC_BS_RESEARCH,
        starting_capital_inr=100000.0,
    )
    rk_inr = RiskAnalyticsEngine().evaluate_run(r_opt).inr_risk
    assert rk_inr is not None
    assert rk_inr.ulcer_index_points is None
    assert rk_inr.ulcer_index_pct == pytest.approx(((0.0**2 + 2.0**2 + 5.0**2) / 3.0) ** 0.5)
    assert rk_inr.recovery_factor == pytest.approx(-1.0)

