"""
AIVOLVE Phase 4 Step 4.5 — Comprehensive Verification Suite for Backtest Robustness & Stress Testing.

Covers:
1. Module B Slippage Stress (exact linear scaling, counterfactual MTM equity curve, zero-slippage, domains)
2. Module C Transaction Cost Stress (itemized INR fees, GST rate preserved, NOT_APPLICABLE_IN_DOMAIN on points-only)
3. Module D Market Regime Robustness (explicit, causal replay, causal ADX/ATR, zero future leakage, UNKNOWN)
4. Module E Parameter Sensitivity (controlled re-simulation persist=False, precomputed runs, auto_optimization_performed=False)
5. Module F Out-of-Sample Robustness (chronological split/walk-forward, purge/embargo, lookahead fail-closed)
6. Module G Seeded Monte Carlo Resampling (bootstrap & permutation determinism, domain purity, estimate disclaimer)
7. Module H Sample Size Governance (exact boundaries 29/30/99/100/299/300, significance_claimed=False)
8. Edge cases (NO_TRADES, RUN_NOT_COMPLETED, mixed-domain rejection, corrupted candles)
9. End-to-end Orchestrator + SQLite Persistence + Isolated Copy Evaluation of Step 4.3 Persisted DB
10. AST architectural isolation (zero production paper_trading or ml_feedback_engine imports)
"""

from __future__ import annotations

import ast
import math
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import pandas as pd
import pytest

from app.backtesting import (
    DEFAULT_BACKTEST_DB_PATH,
    EXECUTION_MODE,
    IST_ZONE,
    ROBUSTNESS_VERSION,
    BacktestConfiguration,
    BacktestRobustnessEngine,
    BacktestRobustnessStore,
    HistoricalDataStore,
    HistoricalExecutionSimulator,
    HistoricalMarketCalendarAdapter,
    MarketRegimeConfig,
    MarketRegimeRobustnessEngine,
    MonteCarloConfig,
    MonteCarloEngine,
    MonteCarloMode,
    OutOfSampleRobustnessEngine,
    ParameterSensitivityEngine,
    ParameterVariationSpec,
    RobustnessRegimeBucket,
    RobustnessStatus,
    SampleSizeClassification,
    SampleSizeGovernanceConfig,
    SampleSizeGovernanceEngine,
    SimulationConfiguration,
    SimulationMode,
    SimulationSignal,
    SlippageStressConfig,
    SlippageStressEngine,
    StabilityClassification,
    TradeEvaluationMetadata,
    TransactionCostStressConfig,
    TransactionCostStressEngine,
    WalkForwardWindowSpec,
    render_robustness_markdown_report,
)
from app.backtesting.models import ReplayPointResult, ReplayRunRecord, ReplayValidationStatus
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
    PortfolioSummary,
    ReconciliationReport,
    SignalDirection,
    SimulationRunResult,
    SimulationStatus,
    SyntheticBSAssumptions,
    TradeLifecycleState,
    TradeRecord,
    TriggerPriceDomain,
)


# ---------------------------------------------------------------------------
# Local Test Helpers
# ---------------------------------------------------------------------------


def _make_cost_schedule(
    *,
    accounting_unit_mode: AccountingUnitMode,
    slippage_per_unit: float = 0.5,
    brokerage_per_order_inr: float = 20.0,
    stt_sell_rate: float = 0.000625,
    exchange_txn_rate: float = 0.0005,
    gst_rate: float = 0.18,
    sebi_turnover_rate: float = 0.000001,
    stamp_duty_buy_rate: float = 0.00003,
    multiplier: Optional[float] = None,
    multiplier_doc: Optional[str] = None,
) -> CostScheduleVersion:
    if accounting_unit_mode == AccountingUnitMode.INDEX_POINTS_ONLY:
        return CostScheduleVersion(
            cost_model_version="TEST-4.5",
            effective_date_ist="2026-06-15",
            recorded_at_utc="2026-06-15T04:00:00+00:00",
            cost_domain="UNDERLYING_POINTS_ONLY",
            slippage_unit="INDEX_POINTS",
            monetary_charges_enabled=False,
            rate_disclaimer="Index points slippage only.",
            brokerage_per_order_inr=0.0,
            stt_sell_rate=0.0,
            exchange_txn_rate=0.0,
            gst_rate=0.0,
            sebi_turnover_rate=0.0,
            stamp_duty_buy_rate=0.0,
            slippage_per_unit=slippage_per_unit,
        )
    is_synth = accounting_unit_mode == AccountingUnitMode.SYNTHETIC_OPTION_INR_ONLY
    return CostScheduleVersion(
        cost_model_version="TEST-4.5",
        effective_date_ist="2026-06-15",
        recorded_at_utc="2026-06-15T04:00:00+00:00",
        cost_domain=(
            "SYNTHETIC_OPTION_PREMIUM_RESEARCH"
            if is_synth
            else "UNDERLYING_POINTS_WITH_EXPLICIT_INR"
        ),
        slippage_unit="INR_PER_OPTION_UNIT" if is_synth else "INDEX_POINTS",
        monetary_charges_enabled=True,
        instrument_multiplier_inr_per_point=multiplier if not is_synth else None,
        instrument_multiplier_documentation=multiplier_doc if not is_synth else None,
        rate_disclaimer="Research statutory fee schedule.",
        brokerage_per_order_inr=brokerage_per_order_inr,
        stt_sell_rate=stt_sell_rate,
        exchange_txn_rate=exchange_txn_rate,
        gst_rate=gst_rate,
        sebi_turnover_rate=sebi_turnover_rate,
        stamp_duty_buy_rate=stamp_duty_buy_rate,
        slippage_per_unit=slippage_per_unit,
    )


def _make_trade(
    *,
    idx: int,
    entry_time_ist: str,
    exit_time_ist: Optional[str],
    signal_available_at_ist: Optional[str] = None,
    accounting_unit_mode: AccountingUnitMode = AccountingUnitMode.INDEX_POINTS_ONLY,
    mode: SimulationMode = SimulationMode.UNDERLYING_POINTS_ONLY,
    direction: SignalDirection = SignalDirection.LONG,
    gross_points: Optional[float] = None,
    slippage_points: Optional[float] = None,
    gross_pnl_inr: Optional[float] = None,
    brokerage_inr_total: float = 0.0,
    stt_inr_total: float = 0.0,
    exchange_inr_total: float = 0.0,
    gst_rate: float = 0.18,
    sebi_inr_total: float = 0.0,
    stamp_inr_total: float = 0.0,
    slippage_cost_inr_total: float = 0.0,
    slippage_per_unit: float = 0.5,
    entry_price: float = 24000.0,
    stop_loss: float = 23980.0,
    target_1: float = 24040.0,
    quantity: int = 1,
    multiplier: Optional[float] = None,
    multiplier_doc: Optional[str] = None,
    state: TradeLifecycleState = TradeLifecycleState.CLOSED,
    final_exit_reason: Optional[ExitReason] = ExitReason.TARGET_1,
) -> TradeRecord:
    has_pts = accounting_unit_mode != AccountingUnitMode.SYNTHETIC_OPTION_INR_ONLY
    has_inr = accounting_unit_mode != AccountingUnitMode.INDEX_POINTS_ONLY
    is_synth = accounting_unit_mode == AccountingUnitMode.SYNTHETIC_OPTION_INR_ONLY
    prov = (
        "SYNTHETIC_MODELLED_OPTION_PNL"
        if is_synth
        else ("INDEX_POINTS_AND_EXPLICIT_INR" if has_inr else "UNDERLYING_POINTS_ONLY")
    )
    qty_lbl = (
        "SYNTHETIC_OPTION_UNITS"
        if is_synth
        else ("SPECIFIED_INDEX_MULTIPLIER_UNITS" if has_inr else "PARTIAL_EXIT_SLICE_UNITS")
    )
    sig_ts = signal_available_at_ist or entry_time_ist
    trade_id = f"TRD-{idx:04d}"
    signal_id = f"SIG-{idx:04d}"
    cost_domain = (
        "SYNTHETIC_OPTION_PREMIUM_RESEARCH"
        if is_synth
        else ("UNDERLYING_POINTS_WITH_EXPLICIT_INR" if has_inr else "UNDERLYING_POINTS_ONLY")
    )
    cost_unit = "INR" if has_inr else "INDEX_POINTS"

    gst_total = round((brokerage_inr_total + exchange_inr_total) * gst_rate, 6)
    bs_total = round(
        brokerage_inr_total + stt_inr_total + exchange_inr_total + gst_total + sebi_inr_total + stamp_inr_total,
        6,
    )
    costs_inr_total = round(bs_total + slippage_cost_inr_total, 6)

    slip_pts = float(slippage_points or 0.0) if has_pts else None
    g_pts = float(gross_points or 0.0) if has_pts else None
    n_pts = round((g_pts or 0.0) - (slip_pts or 0.0), 6) if has_pts else None

    g_inr = float(gross_pnl_inr or 0.0) if has_inr else None
    n_inr = round((g_inr or 0.0) - costs_inr_total, 6) if has_inr else None

    fills: List[FillRecord] = []
    if state == TradeLifecycleState.CLOSED and exit_time_ist is not None:
        leg_slip_pts = (slip_pts or 0.0) / 2.0 if has_pts else None

        def _leg_cb(is_exit: bool) -> CostBreakdown:
            if not has_inr:
                return CostBreakdown(
                    cost_model_version="TEST-4.5",
                    effective_date_ist="2026-06-15",
                    cost_domain=cost_domain,
                    cost_unit=cost_unit,
                    slippage_points_leg=leg_slip_pts,
                )
            b = brokerage_inr_total / 2.0
            st = stt_inr_total if is_exit else 0.0
            ex = exchange_inr_total / 2.0
            g = round((b + ex) * gst_rate, 6)
            sb = sebi_inr_total / 2.0
            sp = stamp_inr_total if not is_exit else 0.0
            sl = slippage_cost_inr_total / 2.0
            bs = round(b + st + ex + g + sb + sp, 6)
            return CostBreakdown(
                cost_model_version="TEST-4.5",
                effective_date_ist="2026-06-15",
                cost_domain=cost_domain,
                cost_unit=cost_unit,
                slippage_points_leg=leg_slip_pts if has_pts else None,
                turnover_inr=100000.0,
                buy_turnover_inr=0.0 if is_exit else 100000.0,
                sell_turnover_inr=100000.0 if is_exit else 0.0,
                brokerage_inr=b,
                stt_inr=st,
                exchange_txn_charges_inr=ex,
                gst_inr=g,
                sebi_charges_inr=sb,
                stamp_duty_inr=sp,
                slippage_cost_inr=sl,
                brokerage_and_statutory_inr=bs,
                total_costs_inr=round(bs + sl, 6),
            )

        entry_cb = _leg_cb(False)
        exit_cb = _leg_cb(True)
        exit_px = round(entry_price + ((g_pts or 0.0) if has_pts else ((g_inr or 0.0) / max(1, quantity))), 4)
        fills.append(
            FillRecord(
                fill_id=f"FIL-{idx:04d}-1",
                order_id=f"ORD-{idx:04d}-1",
                trade_id=trade_id,
                signal_id=signal_id,
                side=OrderSide.ENTRY,
                mode=mode,
                accounting_unit_mode=accounting_unit_mode,
                provenance_label=prov,
                bar_open_ist=entry_time_ist,
                bar_close_ist=entry_time_ist,
                executed_at_ist=entry_time_ist,
                quantity=quantity,
                raw_reference_price=entry_price,
                slippage_per_unit=slippage_per_unit,
                effective_fill_price=entry_price + slippage_per_unit,
                underlying_spot_at_fill=24000.0,
                gross_points_leg=0.0 if has_pts else None,
                slippage_points_leg=leg_slip_pts,
                net_points_impact_leg=-(leg_slip_pts or 0.0) if has_pts else None,
                gross_pnl_inr_leg=0.0 if has_inr else None,
                net_pnl_inr_impact_leg=-(entry_cb.total_costs_inr or 0.0) if has_inr else None,
                costs=entry_cb,
            )
        )
        fills.append(
            FillRecord(
                fill_id=f"FIL-{idx:04d}-2",
                order_id=f"ORD-{idx:04d}-2",
                trade_id=trade_id,
                signal_id=signal_id,
                side=OrderSide.EXIT,
                mode=mode,
                accounting_unit_mode=accounting_unit_mode,
                provenance_label=prov,
                bar_open_ist=exit_time_ist,
                bar_close_ist=exit_time_ist,
                executed_at_ist=exit_time_ist,
                quantity=quantity,
                raw_reference_price=max(0.05, exit_px),
                slippage_per_unit=slippage_per_unit,
                effective_fill_price=max(0.05, exit_px - slippage_per_unit),
                underlying_spot_at_fill=24000.0,
                gross_points_leg=g_pts,
                slippage_points_leg=leg_slip_pts,
                net_points_impact_leg=(g_pts - (leg_slip_pts or 0.0)) if has_pts and g_pts is not None else None,
                gross_pnl_inr_leg=g_inr,
                net_pnl_inr_impact_leg=((g_inr or 0.0) - (exit_cb.total_costs_inr or 0.0)) if has_inr else None,
                costs=exit_cb,
                exit_reason=final_exit_reason,
            )
        )

    return TradeRecord(
        trade_id=trade_id,
        signal_id=signal_id,
        instrument="NIFTY 50",
        timeframe="5m",
        mode=mode,
        accounting_unit_mode=accounting_unit_mode,
        provenance_label=prov,
        is_synthetic_modelled=is_synth,
        quantity_unit_label=qty_lbl,  # type: ignore[arg-type]
        instrument_multiplier_inr_per_point=multiplier,
        instrument_multiplier_documentation=multiplier_doc,
        direction=direction,
        state=state,
        signal_available_at_ist=sig_ts,
        entry_time_ist=entry_time_ist if fills else None,
        exit_time_ist=exit_time_ist if fills else None,
        entry_price=entry_price if fills else None,
        initial_quantity=quantity,
        exited_quantity=quantity if fills else 0,
        remaining_quantity=0,
        stop_loss=stop_loss,
        target_1=target_1,
        target_2=None,
        gross_points=g_pts,
        slippage_points=slip_pts,
        net_points=n_pts,
        unrealized_points=0.0 if has_pts else None,
        reserved_capital_inr=0.0 if has_inr else None,
        gross_pnl_inr=g_inr,
        total_brokerage_and_statutory_inr=bs_total if has_inr else None,
        total_slippage_cost_inr=slippage_cost_inr_total if has_inr else None,
        total_costs_inr=costs_inr_total if has_inr else None,
        net_pnl_inr=n_inr,
        unrealized_pnl_inr=0.0 if has_inr else None,
        fills=tuple(fills),
        final_exit_reason=final_exit_reason if fills else None,
    )


def _build_run(
    *,
    run_id: str,
    trades: Sequence[TradeRecord],
    accounting_unit_mode: AccountingUnitMode = AccountingUnitMode.INDEX_POINTS_ONLY,
    mode: SimulationMode = SimulationMode.UNDERLYING_POINTS_ONLY,
    status: SimulationStatus = SimulationStatus.COMPLETED,
    starting_capital_inr: Optional[float] = None,
    multiplier: Optional[float] = None,
    multiplier_doc: Optional[str] = None,
    slippage_per_unit: float = 0.5,
    brokerage_per_order_inr: float = 20.0,
    equity_points_series: Optional[Sequence[Tuple[str, float]]] = None,
    equity_inr_series: Optional[Sequence[Tuple[str, float]]] = None,
) -> SimulationRunResult:
    has_pts = accounting_unit_mode != AccountingUnitMode.SYNTHETIC_OPTION_INR_ONLY
    has_inr = accounting_unit_mode != AccountingUnitMode.INDEX_POINTS_ONLY
    is_synth = accounting_unit_mode == AccountingUnitMode.SYNTHETIC_OPTION_INR_ONLY
    prov = (
        "SYNTHETIC_MODELLED_OPTION_PNL"
        if is_synth
        else ("INDEX_POINTS_AND_EXPLICIT_INR" if has_inr else "UNDERLYING_POINTS_ONLY")
    )
    sched = _make_cost_schedule(
        accounting_unit_mode=accounting_unit_mode,
        slippage_per_unit=slippage_per_unit,
        brokerage_per_order_inr=brokerage_per_order_inr,
        multiplier=multiplier,
        multiplier_doc=multiplier_doc,
    )

    closed = [t for t in trades if t.state == TradeLifecycleState.CLOSED]
    gross_pts = sum(float(t.gross_points or 0.0) for t in closed) if has_pts else None
    slip_pts = sum(float(t.slippage_points or 0.0) for t in closed) if has_pts else None
    net_pts = sum(float(t.net_points or 0.0) for t in closed) if has_pts else None

    gross_inr = sum(float(t.gross_pnl_inr or 0.0) for t in closed) if has_inr else None
    bs_inr = sum(float(t.total_brokerage_and_statutory_inr or 0.0) for t in closed) if has_inr else None
    slip_inr = sum(float(t.total_slippage_cost_inr or 0.0) for t in closed) if has_inr else None
    tot_costs_inr = sum(float(t.total_costs_inr or 0.0) for t in closed) if has_inr else None
    net_inr = sum(float(t.net_pnl_inr or 0.0) for t in closed) if has_inr else None
    brok_inr = sum(float(f.costs.brokerage_inr or 0.0) for t in closed for f in t.fills) if has_inr else None
    stat_inr = ((bs_inr or 0.0) - (brok_inr or 0.0)) if has_inr else None

    wins = sum(
        1
        for t in closed
        if ((float(t.net_points or 0.0) if accounting_unit_mode == AccountingUnitMode.INDEX_POINTS_ONLY else float(t.net_pnl_inr or 0.0)) > 0.0)
    )
    losses = len(closed) - wins

    curve: List[EquityCurvePoint] = []
    if equity_points_series or equity_inr_series:
        rows = equity_inr_series if has_inr and equity_inr_series else (equity_points_series or ())
        peak_pts = 0.0
        peak_inr = float(starting_capital_inr or 0.0)
        for i, (ts, val) in enumerate(rows):
            eq_p = float(equity_points_series[i][1]) if (has_pts and equity_points_series) else (0.0 if has_pts else None)
            eq_i = float(equity_inr_series[i][1]) if (has_inr and equity_inr_series) else None
            if has_pts and eq_p is not None:
                peak_pts = max(peak_pts, eq_p)
                dd_p = max(0.0, peak_pts - eq_p)
            else:
                dd_p = None
            if has_inr and eq_i is not None:
                peak_inr = max(peak_inr, eq_i)
                dd_i = max(0.0, peak_inr - eq_i)
                dd_pct = (dd_i / peak_inr * 100.0) if peak_inr > 0 else 0.0
            else:
                dd_i = None
                dd_pct = None
            curve.append(
                EquityCurvePoint(
                    timestamp_ist=ts,
                    accounting_unit_mode=accounting_unit_mode,
                    realized_gross_points=eq_p,
                    total_slippage_points=0.0 if has_pts else None,
                    realized_net_points=eq_p,
                    unrealized_points=0.0 if has_pts else None,
                    cumulative_equity_points=eq_p,
                    drawdown_points=dd_p,
                    available_cash_inr=eq_i,
                    reserved_capital_inr=0.0 if has_inr else None,
                    realized_gross_pnl_inr=((eq_i - (starting_capital_inr or 0.0)) if eq_i is not None else None),
                    realized_net_pnl_inr=((eq_i - (starting_capital_inr or 0.0)) if eq_i is not None else None),
                    unrealized_pnl_inr=0.0 if has_inr else None,
                    total_costs_inr=0.0 if has_inr else None,
                    total_equity_inr=eq_i,
                    drawdown_inr=dd_i,
                    drawdown_pct=dd_pct,
                    open_trades_count=0,
                )
            )

    end_eq_inr = ((starting_capital_inr or 0.0) + (net_inr or 0.0)) if has_inr else None
    ret_pct = ((net_inr or 0.0) / float(starting_capital_inr) * 100.0) if (has_inr and starting_capital_inr) else None
    summary = PortfolioSummary(
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
        ending_cumulative_points=net_pts,
        max_drawdown_points=0.0 if has_pts else None,
        currency_unit="INR" if has_inr else None,
        starting_capital_inr=starting_capital_inr if has_inr else None,
        available_cash_inr=end_eq_inr,
        reserved_capital_inr=0.0 if has_inr else None,
        ending_equity_inr=end_eq_inr,
        realized_gross_pnl_inr=gross_inr,
        unrealized_pnl_inr=0.0 if has_inr else None,
        total_brokerage_inr=brok_inr,
        total_statutory_charges_inr=stat_inr,
        total_brokerage_and_statutory_inr=bs_inr,
        total_slippage_cost_inr=slip_inr,
        total_costs_inr=tot_costs_inr,
        realized_net_pnl_inr=net_inr,
        net_return_pct=ret_pct,
        max_drawdown_inr=0.0 if has_inr else None,
        max_drawdown_pct=0.0 if has_inr else None,
        total_signals=len(trades),
        trades_opened=len(trades),
        trades_closed=len(closed),
        trades_rejected=0,
        partial_exits_count=0,
        intrabar_ambiguous_count=0,
        winning_trades=wins,
        losing_trades=losses,
    )
    recon = ReconciliationReport(
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
        open_trades_remaining=0,
    )
    return SimulationRunResult(
        run_id=run_id,
        output_fingerprint=f"FP-{run_id}",
        status=status,
        execution_mode=EXECUTION_MODE,
        mode=mode,
        accounting_unit_mode=accounting_unit_mode,
        provenance_label=prov,
        is_synthetic_modelled=is_synth,
        instrument="NIFTY 50",
        timeframe="5m",
        historical_date_range="2026-06-15..2026-06-19",
        dataset_fingerprint="DS-TEST-4.5",
        calendar_fingerprint="CAL-TEST-4.5",
        simulator_version="4.3.0",
        cost_schedule=sched,
        ambiguity_policy=AmbiguityPolicy.CONSERVATIVE_SL_FIRST_WITH_AMBIGUOUS_TAG,
        gap_policy=GapPolicy.ADVERSE_OPEN_FILL,
        portfolio=summary,
        reconciliation=recon,
        equity_curve=tuple(curve),
        trades=tuple(trades),
        orders=(),
        created_at_utc=datetime(2026, 6, 20, 6, 0, tzinfo=timezone.utc),
    )


def _make_ohlcv_bars_5m(trading_dates: Sequence[str], mode_profile: str = "mixed") -> pd.DataFrame:
    """Builds 100% calendar-valid 5m IST session bars across specified trading dates."""
    rows = []
    price = 24000.0
    for day_idx, day_str in enumerate(trading_dates):
        base_dt = datetime.fromisoformat(f"{day_str}T09:15:00+05:30")
        for bar_i in range(75):  # full 09:15..15:25 5m session (75 bars)
            ts = base_dt + timedelta(minutes=5 * bar_i)
            if mode_profile == "trending" or (mode_profile == "mixed" and day_idx == 0):
                drift = 4.0
                rng_w = 5.0
            elif mode_profile == "high_vol" or (mode_profile == "mixed" and day_idx == 1):
                drift = 2.0 if bar_i % 2 == 0 else -1.5
                rng_w = 25.0
            elif mode_profile == "low_vol" or (mode_profile == "mixed" and day_idx == 2):
                drift = 0.1 if bar_i % 2 == 0 else -0.1
                rng_w = 1.0
            else:
                drift = 1.0 if bar_i % 2 == 0 else -1.0
                rng_w = 4.0
            o = price
            c = max(100.0, o + drift)
            h = max(o, c) + rng_w
            l = max(50.0, min(o, c) - rng_w)
            rows.append(
                {
                    "timestamp": ts,
                    "open": round(o, 2),
                    "high": round(h, 2),
                    "low": round(l, 2),
                    "close": round(c, 2),
                    "volume": 1000.0 + bar_i,
                    "is_complete": 1,
                }
            )
            price = c
    df = pd.DataFrame(rows)
    df.attrs.update({"instrument": "NIFTY 50", "timeframe": "5m"})
    return df


# ---------------------------------------------------------------------------
# 1. Slippage Stress Tests
# ---------------------------------------------------------------------------


def test_slippage_stress_points_and_synthetic_option_inr() -> None:
    # Gross = +20 + 20 = 40 pts; baseline slip = 10 + 10 = 20 pts -> net = 20 pts; breakeven = 40/20 = 2.0x
    t1 = _make_trade(
        idx=1,
        entry_time_ist="2026-06-15T09:20:00+05:30",
        exit_time_ist="2026-06-15T09:40:00+05:30",
        gross_points=20.0,
        slippage_points=10.0,
        slippage_per_unit=5.0,
    )
    t2 = _make_trade(
        idx=2,
        entry_time_ist="2026-06-16T09:20:00+05:30",
        exit_time_ist="2026-06-16T09:40:00+05:30",
        gross_points=20.0,
        slippage_points=10.0,
        slippage_per_unit=5.0,
    )
    run_pts = _build_run(
        run_id="SIM-SLIP-PTS",
        trades=(t1, t2),
        slippage_per_unit=5.0,
        equity_points_series=[
            ("2026-06-15T09:20:00+05:30", -5.0),
            ("2026-06-15T09:40:00+05:30", 10.0),
            ("2026-06-16T09:20:00+05:30", 5.0),
            ("2026-06-16T09:40:00+05:30", 20.0),
        ],
    )
    res_pts = SlippageStressEngine().evaluate(run_pts)
    assert res_pts.status == RobustnessStatus.COMPLETED
    assert res_pts.accounting_unit_mode == AccountingUnitMode.INDEX_POINTS_ONLY
    assert res_pts.baseline_gross_pnl_points == pytest.approx(40.0)
    assert res_pts.baseline_net_pnl_points == pytest.approx(20.0)
    assert res_pts.break_even_slippage_multiplier_points == pytest.approx(2.0)
    assert res_pts.break_even_slippage_multiplier_inr is None
    assert res_pts.remains_profitable_at_2x_points is False
    assert res_pts.remains_profitable_at_3x_points is False

    by_m = {s.multiplier: s for s in res_pts.scenarios}
    assert by_m[1.0].is_baseline is True
    assert by_m[1.0].inr_metrics is None
    assert by_m[1.0].points_metrics is not None
    assert by_m[1.0].points_metrics.max_drawdown_pct is None
    assert by_m[1.0].points_metrics.net_pnl == pytest.approx(20.0)
    assert by_m[1.5].points_metrics.net_pnl == pytest.approx(10.0)
    assert by_m[1.5].net_pnl_delta_points_vs_baseline == pytest.approx(-10.0)
    assert by_m[1.5].net_pnl_retention_ratio_points == pytest.approx(0.5)
    assert by_m[2.0].points_metrics.net_pnl == pytest.approx(0.0)
    assert by_m[3.0].points_metrics.net_pnl == pytest.approx(-20.0)
    # Equity curve drawdown should expand strictly under 3x stress (entry slippage hits before exit!)
    assert by_m[3.0].points_metrics.max_drawdown > by_m[1.0].points_metrics.max_drawdown

    # Zero-slippage edge case
    t_zero = _make_trade(
        idx=3,
        entry_time_ist="2026-06-15T09:20:00+05:30",
        exit_time_ist="2026-06-15T09:40:00+05:30",
        gross_points=25.0,
        slippage_points=0.0,
        slippage_per_unit=0.0,
    )
    run_zero = _build_run(run_id="SIM-SLIP-ZERO", trades=(t_zero,), slippage_per_unit=0.0)
    res_zero = SlippageStressEngine().evaluate(run_zero)
    assert res_zero.break_even_slippage_multiplier_points is None
    assert any("ZERO_BASELINE_SLIPPAGE" in w for w in res_zero.warnings)

    # Mode B SYNTHETIC_OPTION_INR_ONLY keeps statutory charges untouched when scaling slippage
    t_opt = _make_trade(
        idx=4,
        entry_time_ist="2026-06-15T09:20:00+05:30",
        exit_time_ist="2026-06-15T09:40:00+05:30",
        accounting_unit_mode=AccountingUnitMode.SYNTHETIC_OPTION_INR_ONLY,
        mode=SimulationMode.SYNTHETIC_BS_RESEARCH,
        gross_pnl_inr=3000.0,
        brokerage_inr_total=40.0,
        stt_inr_total=100.0,
        exchange_inr_total=100.0,
        slippage_cost_inr_total=500.0,
        slippage_per_unit=0.5,
        quantity=100,
    )
    run_opt = _build_run(
        run_id="SIM-SLIP-OPT",
        trades=(t_opt,),
        accounting_unit_mode=AccountingUnitMode.SYNTHETIC_OPTION_INR_ONLY,
        mode=SimulationMode.SYNTHETIC_BS_RESEARCH,
        starting_capital_inr=100000.0,
    )
    res_opt = SlippageStressEngine().evaluate(run_opt)
    assert res_opt.is_synthetic_modelled is True
    assert res_opt.provenance_label == "SYNTHETIC_MODELLED_OPTION_PNL"
    opt_by_m = {s.multiplier: s for s in res_opt.scenarios}
    assert opt_by_m[1.0].points_metrics is None
    assert opt_by_m[2.0].total_slippage_cost_inr == pytest.approx(1000.0)
    # Statutory + brokerage delta must be 0 when scaling slippage: delta net = -500 INR
    assert opt_by_m[2.0].net_pnl_delta_inr_vs_baseline == pytest.approx(-500.0)


# ---------------------------------------------------------------------------
# 2. Transaction Cost Stress Tests
# ---------------------------------------------------------------------------


def test_transaction_cost_stress_domain_isolation_and_breakdown() -> None:
    # INDEX_POINTS_ONLY must fail safely with NOT_APPLICABLE_IN_DOMAIN (never invent statutory INR rates)
    t_pts = _make_trade(
        idx=1,
        entry_time_ist="2026-06-15T09:20:00+05:30",
        exit_time_ist="2026-06-15T09:40:00+05:30",
        gross_points=30.0,
        slippage_points=2.0,
    )
    run_pts = _build_run(run_id="SIM-TC-PTS", trades=(t_pts,))
    res_pts = TransactionCostStressEngine().evaluate(run_pts)
    assert res_pts.status == RobustnessStatus.NOT_APPLICABLE_IN_DOMAIN
    assert res_pts.monetary_charges_applicable is False
    assert res_pts.gst_rate_preserved is None
    assert res_pts.scenarios == ()
    assert any("NOT_APPLICABLE_IN_DOMAIN" in w for w in res_pts.warnings)

    # INDEX_POINTS_AND_EXPLICIT_INR scales non-slippage fees cleanly while preserving gst_rate & slippage
    t_mon = _make_trade(
        idx=2,
        entry_time_ist="2026-06-15T09:20:00+05:30",
        exit_time_ist="2026-06-15T09:40:00+05:30",
        accounting_unit_mode=AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR,
        mode=SimulationMode.UNDERLYING_POINTS_ONLY,
        gross_points=40.0,
        slippage_points=1.0,
        gross_pnl_inr=3000.0,
        brokerage_inr_total=40.0,
        stt_inr_total=200.0,
        exchange_inr_total=60.0,
        gst_rate=0.18,
        sebi_inr_total=2.0,
        stamp_inr_total=8.0,
        slippage_cost_inr_total=75.0,
        quantity=75,
        multiplier=75.0,
        multiplier_doc="NIFTY 50 explicit lot multiplier = 75",
    )
    # Baseline bs_inr = 40 + 200 + 60 + 0.18*(40+60)=18 + 2 + 8 = 328.0 INR
    # Baseline slip_inr = 75.0 INR -> Net = 3000 - 328 - 75 = 2597.0 INR
    run_mon = _build_run(
        run_id="SIM-TC-MON",
        trades=(t_mon,),
        accounting_unit_mode=AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR,
        mode=SimulationMode.UNDERLYING_POINTS_ONLY,
        starting_capital_inr=200000.0,
        multiplier=75.0,
        multiplier_doc="NIFTY 50 explicit lot multiplier = 75",
    )
    res_mon = TransactionCostStressEngine().evaluate(run_mon)
    assert res_mon.status == RobustnessStatus.COMPLETED
    assert res_mon.monetary_charges_applicable is True
    assert res_mon.gst_rate_preserved == pytest.approx(0.18)

    scens = {s.multiplier: s for s in res_mon.scenarios}
    assert scens[1.0].cost_components is not None
    assert scens[1.0].cost_components.brokerage_inr == pytest.approx(40.0)
    assert scens[1.0].cost_components.gst_inr == pytest.approx(18.0)
    assert scens[1.0].cost_components.total_brokerage_and_statutory_inr == pytest.approx(328.0)
    assert scens[1.0].cost_components.slippage_cost_inr == pytest.approx(75.0)
    assert scens[2.0].cost_components is not None
    assert scens[2.0].cost_components.brokerage_inr == pytest.approx(80.0)
    assert scens[2.0].cost_components.stt_inr == pytest.approx(400.0)
    assert scens[2.0].cost_components.gst_inr == pytest.approx(36.0)
    assert scens[2.0].cost_components.slippage_cost_inr == pytest.approx(75.0)
    assert scens[2.0].net_pnl_delta_inr_vs_baseline == pytest.approx(-328.0)
    assert scens[2.0].points_metrics is not None
    assert scens[2.0].points_metrics.net_pnl == pytest.approx(39.0)
    assert res_mon.break_even_cost_multiplier_inr == pytest.approx((2597.0 + 328.0) / 328.0, abs=1e-4)


# ---------------------------------------------------------------------------
# 3. Market Regime Robustness Tests (Zero Future Leakage + Explicit + Unknown)
# ---------------------------------------------------------------------------


def test_market_regime_causality_no_future_leakage_and_unknown_handling() -> None:
    df_base = _make_ohlcv_bars_5m(["2026-06-15", "2026-06-16", "2026-06-17"], mode_profile="mixed")
    # Signal 1 sits well after warm-up on trending day 2026-06-15 (bar ~50)
    t_trend = _make_trade(
        idx=1,
        signal_available_at_ist="2026-06-15T13:30:00+05:30",
        entry_time_ist="2026-06-15T13:30:00+05:30",
        exit_time_ist="2026-06-15T14:00:00+05:30",
        gross_points=30.0,
        slippage_points=2.0,
    )
    # Signal 2 sits on high-vol day 2026-06-16 (bar ~50)
    t_high_vol = _make_trade(
        idx=2,
        signal_available_at_ist="2026-06-16T13:30:00+05:30",
        entry_time_ist="2026-06-16T13:30:00+05:30",
        exit_time_ist="2026-06-16T14:00:00+05:30",
        gross_points=-10.0,
        slippage_points=2.0,
    )
    # Signal 3 sits BEFORE any sufficient history (bar 1 of day 1) -> MUST map to UNKNOWN_OR_INSUFFICIENT_DATA
    t_early = _make_trade(
        idx=3,
        signal_available_at_ist="2026-06-15T09:20:00+05:30",
        entry_time_ist="2026-06-15T09:20:00+05:30",
        exit_time_ist="2026-06-15T09:30:00+05:30",
        gross_points=5.0,
        slippage_points=1.0,
    )
    run = _build_run(run_id="SIM-REG", trades=(t_trend, t_high_vol, t_early))

    engine = MarketRegimeRobustnessEngine()
    res_clean = engine.evaluate(run, candles_df=df_base)
    assert res_clean.status == RobustnessStatus.COMPLETED
    assert res_clean.no_future_bar_leakage_verified is True

    by_reg = {b.regime: b for b in res_clean.buckets}
    assert RobustnessRegimeBucket.TRENDING in by_reg
    assert by_reg[RobustnessRegimeBucket.TRENDING].classification_source == "CAUSAL_OHLCV_INDICATORS"
    assert RobustnessRegimeBucket.UNKNOWN_OR_INSUFFICIENT_DATA in by_reg
    assert "TRD-0003" in by_reg[RobustnessRegimeBucket.UNKNOWN_OR_INSUFFICIENT_DATA].trade_ids

    # Anti-lookahead proof: massively alter ALL future bars AFTER 2026-06-15T13:30:00+05:30 on a copy
    # Classification of TRD-0001 and TRD-0003 MUST remain bit-for-bit identical!
    cutoff = datetime.fromisoformat("2026-06-15T13:35:00+05:30")
    df_future_shocked = df_base.copy()
    mask_future = pd.to_datetime(df_future_shocked["timestamp"]) >= cutoff
    df_future_shocked.loc[mask_future, "high"] = df_future_shocked.loc[mask_future, "high"] * 1.5
    df_future_shocked.loc[mask_future, "close"] = df_future_shocked.loc[mask_future, "close"] * 1.4
    df_future_shocked.attrs.update({"instrument": "NIFTY 50", "timeframe": "5m"})

    res_shocked = engine.evaluate(
        _build_run(run_id="SIM-REG-SUB", trades=(t_trend, t_early)),
        candles_df=df_future_shocked,
    )
    shocked_map = {tid: b.regime for b in res_shocked.buckets for tid in b.trade_ids}
    clean_map = {tid: b.regime for b in res_clean.buckets for tid in b.trade_ids}
    assert shocked_map["TRD-0001"] == clean_map["TRD-0001"]
    assert shocked_map["TRD-0003"] == RobustnessRegimeBucket.UNKNOWN_OR_INSUFFICIENT_DATA

    # Explicit metadata & Replay artifact priority + unrecognized label -> UNKNOWN
    res_meta = engine.evaluate(
        run,
        trade_metadata={
            "TRD-0001": TradeEvaluationMetadata(market_regime="SIDEWAYS"),
            "TRD-0002": TradeEvaluationMetadata(market_regime="WEIRD_UNRECOGNIZED"),
        },
        replay_run=ReplayRunRecord(
            run_id="REP-REG",
            instrument="NIFTY 50",
            timeframes=("5m",),
            start_date_ist="2026-06-15",
            end_date_ist="2026-06-17",
            historical_date_range="2026-06-15..2026-06-17",
            data_source="TEST",
            dataset_fingerprint="DS",
            engine_version="3.7.0",
            configuration_version="4.2.0",
            calendar_source="TEST",
            calendar_fingerprint="CAL",
            replay_timestamps_ist=("2026-06-15T09:20:00+05:30",),
            output_fingerprint="OUT",
            validation_status=ReplayValidationStatus.VALIDATED,
            point_count=1,
            points=(
                ReplayPointResult(
                    as_of_time_ist="2026-06-15T09:20:00+05:30",
                    report_id="R-1",
                    overall_alignment="ALIGNED",
                    data_quality_status="VALID",
                    score_status="UNAVAILABLE",
                    calibration_status="NOT_CALIBRATED",
                    report={"market_regime": "LOW_VOLATILITY"},
                ),
            ),
            created_at_utc=datetime(2026, 6, 20, tzinfo=timezone.utc),
        ),
    )
    meta_map = {tid: b.regime for b in res_meta.buckets for tid in b.trade_ids}
    assert meta_map["TRD-0001"] == RobustnessRegimeBucket.RANGING
    assert meta_map["TRD-0002"] == RobustnessRegimeBucket.UNKNOWN_OR_INSUFFICIENT_DATA
    assert meta_map["TRD-0003"] == RobustnessRegimeBucket.LOW_VOLATILITY


# ---------------------------------------------------------------------------
# 4. Parameter Sensitivity Tests (Controlled Re-Sim + Anti-Optimization)
# ---------------------------------------------------------------------------


def test_parameter_sensitivity_resimulation_and_anti_optimization_guardrails(tmp_path: Path) -> None:
    df = _make_ohlcv_bars_5m(["2026-06-15"], mode_profile="trending")
    # Extract candle window on monotonic rising trend so controlled SL/Target changes are clean
    sig = SimulationSignal(
        signal_id="SIG-PS-01",
        instrument="NIFTY 50",
        timeframe="5m",
        signal_available_at_ist=datetime.fromisoformat("2026-06-15T09:25:00+05:30"),
        direction=SignalDirection.LONG,
        trigger_domain=TriggerPriceDomain.UNDERLYING_POINTS,
        stop_loss=23950.0,
        target_1=24050.0,
        target_2=24110.0,
        partial_exit_fraction=0.5,
        quantity_units=75,
        max_entry_wait_bars=3,
    )
    sim_cfg = SimulationConfiguration(
        mode=SimulationMode.UNDERLYING_POINTS_ONLY,
        monetary_accounting_enabled=False,
        require_verified_data_store=False,
        storage_db_path=str(tmp_path / "isolated.db"),
    )
    base_sim = HistoricalExecutionSimulator(config=sim_cfg)
    base_run = base_sim.run_simulation(
        instrument="NIFTY 50",
        timeframe="5m",
        signals=[sig],
        candles_df=df,
        persist=False,
    )
    assert base_run.status == SimulationStatus.COMPLETED

    variations = [
        ParameterVariationSpec(
            variation_id="SL_085",
            label="Tighter Stop Loss 0.85x",
            parameter_name="stop_loss",
            factor=0.85,
        ),
        ParameterVariationSpec(
            variation_id="SL_115",
            label="Wider Stop Loss 1.15x",
            parameter_name="stop_loss",
            factor=1.15,
        ),
        ParameterVariationSpec(
            variation_id="T1_090",
            label="Closer Target 1 0.90x",
            parameter_name="target_1",
            factor=0.90,
        ),
        ParameterVariationSpec(
            variation_id="WAIT_5",
            label="Max Entry Wait 5 Bars",
            parameter_name="max_entry_wait_bars",
            override_value=5,
        ),
    ]
    ps_res = ParameterSensitivityEngine().evaluate_controlled_variations(
        baseline_run=base_run,
        variations=variations,
        signals=[sig],
        candles_df=df,
        base_sim_config=sim_cfg,
    )
    assert ps_res.status == RobustnessStatus.COMPLETED
    assert ps_res.evaluation_mode == "CONTROLLED_RESIMULATION"
    assert ps_res.auto_optimization_performed is False
    assert ps_res.best_parameter_selected is None
    assert ps_res.strategy_config_modified is False
    assert ps_res.variants_evaluated == 5  # Baseline + 4 variations
    assert base_sim.data_store.list_simulation_runs() == []  # persist=False guaranteed zero run persisted

    # Detect UNSTABLE when a variant flips profitability sign
    t_win = _make_trade(
        idx=1,
        entry_time_ist="2026-06-15T09:20:00+05:30",
        exit_time_ist="2026-06-15T09:40:00+05:30",
        gross_points=20.0,
        slippage_points=2.0,
    )
    t_lose = _make_trade(
        idx=2,
        entry_time_ist="2026-06-15T09:20:00+05:30",
        exit_time_ist="2026-06-15T09:40:00+05:30",
        gross_points=-20.0,
        slippage_points=2.0,
        final_exit_reason=ExitReason.STOP_LOSS,
    )
    pre_res = ParameterSensitivityEngine().evaluate_precomputed_runs(
        baseline_run=_build_run(run_id="SIM-BASE", trades=(t_win,)),
        variant_runs=[
            (
                ParameterVariationSpec(
                    variation_id="FLIP",
                    label="Flipped Variant",
                    parameter_name="stop_loss",
                    factor=0.5,
                ),
                _build_run(run_id="SIM-FLIP", trades=(t_lose,)),
            )
        ],
    )
    assert pre_res.stability_classification == StabilityClassification.UNSTABLE
    assert pre_res.sign_flips_vs_baseline_count == 1
    assert pre_res.auto_optimization_performed is False
    assert pre_res.best_parameter_selected is None

    # Mixed domain variant must fail closed
    run_inr = _build_run(
        run_id="SIM-INR",
        trades=(t_win.model_copy(update={"accounting_unit_mode": AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR, "mode": SimulationMode.UNDERLYING_POINTS_ONLY, "provenance_label": "INDEX_POINTS_AND_EXPLICIT_INR", "quantity_unit_label": "SPECIFIED_INDEX_MULTIPLIER_UNITS", "instrument_multiplier_inr_per_point": 75.0, "instrument_multiplier_documentation": "NIFTY 75 INR per point lot", "reserved_capital_inr": 0.0, "gross_pnl_inr": 1500.0, "total_brokerage_and_statutory_inr": 0.0, "total_slippage_cost_inr": 150.0, "total_costs_inr": 150.0, "net_pnl_inr": 1350.0, "unrealized_pnl_inr": 0.0, "fills": ()}),),
        accounting_unit_mode=AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR,
        starting_capital_inr=100000.0,
        multiplier=75.0,
        multiplier_doc="NIFTY 75 INR per point lot",
    )
    with pytest.raises(ValueError, match="MIXED_DOMAIN_ANALYTICS_FORBIDDEN"):
        ParameterSensitivityEngine().evaluate_precomputed_runs(
            baseline_run=_build_run(run_id="SIM-PTS-MIX", trades=(t_win,)),
            variant_runs=[
                (
                    ParameterVariationSpec(
                        variation_id="MIX",
                        label="Mixed",
                        parameter_name="stop_loss",
                        factor=1.1,
                    ),
                    run_inr,
                )
            ],
        )


# ---------------------------------------------------------------------------
# 5. Out-of-Sample Chronological Robustness Tests
# ---------------------------------------------------------------------------


def test_out_of_sample_chronological_purge_embargo_and_no_lookahead() -> None:
    trades = [
        _make_trade(
            idx=1,
            entry_time_ist="2026-06-15T10:00:00+05:30",
            exit_time_ist="2026-06-15T10:30:00+05:30",
            gross_points=22.0,
            slippage_points=2.0,
        ),
        _make_trade(
            idx=2,
            entry_time_ist="2026-06-16T10:00:00+05:30",
            exit_time_ist="2026-06-16T11:00:00+05:30",
            gross_points=12.0,
            slippage_points=2.0,
        ),
        # Overlaps IS/OOS boundary at 2026-06-17T12:00:00+05:30 -> purged when purge=3600s
        _make_trade(
            idx=3,
            entry_time_ist="2026-06-17T11:30:00+05:30",
            exit_time_ist="2026-06-17T12:30:00+05:30",
            gross_points=10.0,
            slippage_points=2.0,
        ),
        # Inside embargo window [12:00, 13:00] -> embargoed
        _make_trade(
            idx=4,
            signal_available_at_ist="2026-06-17T12:15:00+05:30",
            entry_time_ist="2026-06-17T12:20:00+05:30",
            exit_time_ist="2026-06-17T12:50:00+05:30",
            gross_points=18.0,
            slippage_points=2.0,
        ),
        # Valid OOS trades
        _make_trade(
            idx=5,
            signal_available_at_ist="2026-06-18T10:00:00+05:30",
            entry_time_ist="2026-06-18T10:05:00+05:30",
            exit_time_ist="2026-06-18T10:40:00+05:30",
            gross_points=14.0,
            slippage_points=2.0,
        ),
        _make_trade(
            idx=6,
            signal_available_at_ist="2026-06-19T10:00:00+05:30",
            entry_time_ist="2026-06-19T10:05:00+05:30",
            exit_time_ist="2026-06-19T10:40:00+05:30",
            gross_points=8.0,
            slippage_points=2.0,
        ),
    ]
    run = _build_run(run_id="SIM-OOS", trades=trades)
    win = WalkForwardWindowSpec(
        window_id="WF-01",
        is_start_ist=datetime.fromisoformat("2026-06-15T09:15:00+05:30"),
        is_end_ist=datetime.fromisoformat("2026-06-17T12:00:00+05:30"),
        oos_start_ist=datetime.fromisoformat("2026-06-17T12:00:00+05:30"),
        oos_end_ist=datetime.fromisoformat("2026-06-19T15:30:00+05:30"),
        purge_duration_seconds=3600.0,
        embargo_duration_seconds=3600.0,
    )
    oos_res = OutOfSampleRobustnessEngine().evaluate_run(run, windows=[win])
    assert oos_res.status == RobustnessStatus.COMPLETED
    assert oos_res.no_lookahead_verified is True
    assert oos_res.statistical_significance_claimed is False
    assert oos_res.total_is_trades == 2
    assert oos_res.total_oos_trades == 2
    assert oos_res.is_aggregate_points is not None
    assert oos_res.oos_aggregate_points is not None
    assert oos_res.is_aggregate_points.net_pnl == pytest.approx(30.0)   # 20 + 10
    assert oos_res.oos_aggregate_points.net_pnl == pytest.approx(18.0)  # 12 + 6
    assert oos_res.oos_expectancy_retention_ratio_points == pytest.approx(9.0 / 15.0)
    assert oos_res.positive_oos_windows_ratio_points == pytest.approx(1.0)

    # Explicit lookahead violation must fail closed
    t_future_sig = _make_trade(
        idx=10,
        signal_available_at_ist="2026-06-16T10:00:00+05:30",
        entry_time_ist="2026-06-18T10:00:00+05:30",
        exit_time_ist="2026-06-18T10:30:00+05:30",
        gross_points=10.0,
        slippage_points=1.0,
    )
    with pytest.raises(ValueError, match="WALK_FORWARD_LOOKAHEAD_VIOLATION"):
        OutOfSampleRobustnessEngine().evaluate_run_pairs(
            [(win, _build_run(run_id="SIM-IS", trades=[trades[0]]), _build_run(run_id="SIM-BAD-OOS", trades=[t_future_sig]))]
        )


# ---------------------------------------------------------------------------
# 6. Seeded Monte Carlo Tests (Determinism, Modes, Domain Segregation)
# ---------------------------------------------------------------------------


def test_monte_carlo_seed_determinism_bootstrap_vs_permutation_and_domains() -> None:
    pnls = [25.0, -10.0, 15.0, -12.0, 30.0, -5.0, 10.0, -8.0]
    trades = [
        _make_trade(
            idx=i + 1,
            entry_time_ist=f"2026-06-15T{9 + (i // 3):02d}:{(20 + i * 5) % 60:02d}:00+05:30",
            exit_time_ist=f"2026-06-15T{9 + (i // 3):02d}:{(22 + i * 5) % 60:02d}:00+05:30",
            gross_points=p + 1.0,
            slippage_points=1.0,
            final_exit_reason=ExitReason.TARGET_1 if p > 0 else ExitReason.STOP_LOSS,
        )
        for i, p in enumerate(pnls)
    ]
    run_pts = _build_run(run_id="SIM-MC-PTS", trades=trades)

    mc = MonteCarloEngine()
    r1 = mc.evaluate(run_pts, MonteCarloConfig(seed=123, n_iterations=250, mode=MonteCarloMode.BOOTSTRAP_WITH_REPLACEMENT))
    r2 = mc.evaluate(run_pts, MonteCarloConfig(seed=123, n_iterations=250, mode=MonteCarloMode.BOOTSTRAP_WITH_REPLACEMENT))
    r3 = mc.evaluate(run_pts, MonteCarloConfig(seed=999, n_iterations=250, mode=MonteCarloMode.BOOTSTRAP_WITH_REPLACEMENT))

    assert r1.status == RobustnessStatus.COMPLETED
    assert r1.is_estimate_not_prediction is True
    assert r1.statistical_significance_claimed is False
    assert r1.inr_distribution is None
    assert r1.points_distribution is not None
    assert r1.points_distribution.max_drawdown_pct is None
    assert r1.model_dump() == r2.model_dump()
    assert r1.points_distribution.max_drawdown.p50 != r3.points_distribution.max_drawdown.p50 or (
        r1.points_distribution.ending_net_pnl.mean != r3.points_distribution.ending_net_pnl.mean
    )

    # Permutation without replacement preserves exact observed terminal net P&L while varying sequence DD
    perm = mc.evaluate(
        run_pts,
        MonteCarloConfig(seed=123, n_iterations=200, mode=MonteCarloMode.PERMUTATION_WITHOUT_REPLACEMENT),
    )
    assert perm.points_distribution is not None
    assert perm.points_distribution.ending_net_pnl.min == pytest.approx(sum(pnls))
    assert perm.points_distribution.ending_net_pnl.max == pytest.approx(sum(pnls))
    assert perm.points_distribution.max_drawdown.max >= perm.points_distribution.max_drawdown.min
    assert any("PERMUTATION_INVARIANT_ENDING_PNL" in w for w in perm.warnings)

    # Small sample < min_trades_required returns INSUFFICIENT_DATA
    tiny_run = _build_run(run_id="SIM-MC-TINY", trades=trades[:3])
    res_tiny = mc.evaluate(tiny_run, MonteCarloConfig(seed=42, n_iterations=50, min_trades_required=5))
    assert res_tiny.status == RobustnessStatus.INSUFFICIENT_DATA


# ---------------------------------------------------------------------------
# 7. Sample Size Governance Tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("trade_count", "expected_cls", "expected_status"),
    [
        (0, SampleSizeClassification.INSUFFICIENT_SAMPLE, RobustnessStatus.NO_TRADES),
        (29, SampleSizeClassification.INSUFFICIENT_SAMPLE, RobustnessStatus.INSUFFICIENT_DATA),
        (30, SampleSizeClassification.LIMITED_EVIDENCE, RobustnessStatus.COMPLETED),
        (99, SampleSizeClassification.LIMITED_EVIDENCE, RobustnessStatus.COMPLETED),
        (100, SampleSizeClassification.MODERATE_SAMPLE, RobustnessStatus.COMPLETED),
        (299, SampleSizeClassification.MODERATE_SAMPLE, RobustnessStatus.COMPLETED),
        (300, SampleSizeClassification.LARGER_SAMPLE, RobustnessStatus.COMPLETED),
    ],
)
def test_sample_size_governance_thresholds(
    trade_count: int,
    expected_cls: SampleSizeClassification,
    expected_status: RobustnessStatus,
) -> None:
    base_dt = datetime.fromisoformat("2026-06-15T09:15:00+05:30")
    trades = [
        _make_trade(
            idx=i + 1,
            entry_time_ist=(base_dt + timedelta(minutes=i)).isoformat(),
            exit_time_ist=(base_dt + timedelta(minutes=i, seconds=30)).isoformat(),
            gross_points=5.0,
            slippage_points=1.0,
        )
        for i in range(trade_count)
    ]
    run = _build_run(run_id=f"SIM-SS-{trade_count}", trades=trades)
    res = SampleSizeGovernanceEngine().evaluate(run)
    assert res.classification == expected_cls
    assert res.status == expected_status
    assert res.closed_trades_count == trade_count
    assert res.statistical_significance_claimed is False


def test_sample_size_config_rejects_non_ascending_thresholds() -> None:
    with pytest.raises(ValueError, match="insufficient_below < limited_below < moderate_below"):
        SampleSizeGovernanceConfig(insufficient_below=50, limited_below=40, moderate_below=200)


# ---------------------------------------------------------------------------
# 8. Zero Trades / Incomplete Run / Invalid Data Fail-Closed Tests
# ---------------------------------------------------------------------------


def test_fail_closed_empty_and_non_completed_runs_and_corrupt_candles() -> None:
    blocked_run = _build_run(run_id="SIM-BLK", trades=(), status=SimulationStatus.BLOCKED)
    empty_run = _build_run(run_id="SIM-EMP", trades=(), status=SimulationStatus.COMPLETED)

    for eng in (
        SlippageStressEngine(),
        TransactionCostStressEngine(),
        MarketRegimeRobustnessEngine(),
        OutOfSampleRobustnessEngine(),
        MonteCarloEngine(),
        SampleSizeGovernanceEngine(),
    ):
        assert eng.evaluate(blocked_run).status == RobustnessStatus.RUN_NOT_COMPLETED
        res_empty = eng.evaluate(empty_run)
        assert res_empty.status in (RobustnessStatus.NO_TRADES, RobustnessStatus.NOT_APPLICABLE_IN_DOMAIN)

    # Corrupted mock-flagged candles in MarketRegimeRobustnessEngine fail closed (no fabricated labels)
    bad_df = _make_ohlcv_bars_5m(["2026-06-15"])
    bad_df.attrs["is_mock"] = True
    t1 = _make_trade(
        idx=1,
        entry_time_ist="2026-06-15T13:30:00+05:30",
        exit_time_ist="2026-06-15T14:00:00+05:30",
        gross_points=10.0,
        slippage_points=1.0,
    )
    bad_reg = MarketRegimeRobustnessEngine().evaluate(_build_run(run_id="SIM-BAD-DF", trades=(t1,)), candles_df=bad_df)
    assert bad_reg.status == RobustnessStatus.INSUFFICIENT_DATA
    assert bad_reg.unknown_or_insufficient_trades_count == 1
    assert any("CAUSAL_REGIME_DATA_REJECTED" in w for w in bad_reg.warnings)


# ---------------------------------------------------------------------------
# 9. End-to-End Orchestrator, Deterministic Fingerprints, Store Isolation & Persisted Step 4.3 Runs
# ---------------------------------------------------------------------------


def test_orchestrator_reproducibility_markdown_isolated_store_and_real_step4_3_db(tmp_path: Path) -> None:
    # Store path isolation check must reject production DB paths
    with pytest.raises(PermissionError, match="ISOLATION VIOLATION"):
        BacktestRobustnessStore(db_path=tmp_path / "aivolve_trading.db")
    with pytest.raises(PermissionError, match="ISOLATION VIOLATION"):
        BacktestRobustnessStore(db_path=tmp_path / "governance_ledger.db")

    df = _make_ohlcv_bars_5m(["2026-06-15", "2026-06-16", "2026-06-17"], mode_profile="mixed")
    trades = [
        _make_trade(
            idx=1,
            signal_available_at_ist="2026-06-15T13:30:00+05:30",
            entry_time_ist="2026-06-15T13:30:00+05:30",
            exit_time_ist="2026-06-15T14:00:00+05:30",
            accounting_unit_mode=AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR,
            gross_points=30.0,
            slippage_points=1.0,
            gross_pnl_inr=2250.0,
            brokerage_inr_total=40.0,
            stt_inr_total=150.0,
            exchange_inr_total=50.0,
            sebi_inr_total=2.0,
            stamp_inr_total=6.0,
            slippage_cost_inr_total=75.0,
            quantity=75,
            multiplier=75.0,
            multiplier_doc="NIFTY 50 75 INR per point lot",
        ),
        _make_trade(
            idx=2,
            signal_available_at_ist="2026-06-16T13:30:00+05:30",
            entry_time_ist="2026-06-16T13:30:00+05:30",
            exit_time_ist="2026-06-16T14:00:00+05:30",
            accounting_unit_mode=AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR,
            gross_points=20.0,
            slippage_points=1.0,
            gross_pnl_inr=1500.0,
            brokerage_inr_total=40.0,
            stt_inr_total=120.0,
            exchange_inr_total=40.0,
            sebi_inr_total=2.0,
            stamp_inr_total=5.0,
            slippage_cost_inr_total=75.0,
            quantity=75,
            multiplier=75.0,
            multiplier_doc="NIFTY 50 75 INR per point lot",
        ),
        _make_trade(
            idx=3,
            signal_available_at_ist="2026-06-17T13:30:00+05:30",
            entry_time_ist="2026-06-17T13:30:00+05:30",
            exit_time_ist="2026-06-17T14:00:00+05:30",
            accounting_unit_mode=AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR,
            gross_points=-12.0,
            slippage_points=1.0,
            gross_pnl_inr=-900.0,
            brokerage_inr_total=40.0,
            stt_inr_total=100.0,
            exchange_inr_total=30.0,
            sebi_inr_total=1.5,
            stamp_inr_total=4.0,
            slippage_cost_inr_total=75.0,
            quantity=75,
            multiplier=75.0,
            multiplier_doc="NIFTY 50 75 INR per point lot",
            final_exit_reason=ExitReason.STOP_LOSS,
        ),
        _make_trade(
            idx=4,
            signal_available_at_ist="2026-06-17T14:20:00+05:30",
            entry_time_ist="2026-06-17T14:20:00+05:30",
            exit_time_ist="2026-06-17T14:50:00+05:30",
            accounting_unit_mode=AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR,
            gross_points=18.0,
            slippage_points=1.0,
            gross_pnl_inr=1350.0,
            brokerage_inr_total=40.0,
            stt_inr_total=110.0,
            exchange_inr_total=35.0,
            sebi_inr_total=1.5,
            stamp_inr_total=4.5,
            slippage_cost_inr_total=75.0,
            quantity=75,
            multiplier=75.0,
            multiplier_doc="NIFTY 50 75 INR per point lot",
        ),
        _make_trade(
            idx=5,
            signal_available_at_ist="2026-06-17T15:00:00+05:30",
            entry_time_ist="2026-06-17T15:00:00+05:30",
            exit_time_ist="2026-06-17T15:20:00+05:30",
            accounting_unit_mode=AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR,
            gross_points=16.0,
            slippage_points=1.0,
            gross_pnl_inr=1200.0,
            brokerage_inr_total=40.0,
            stt_inr_total=105.0,
            exchange_inr_total=35.0,
            sebi_inr_total=1.5,
            stamp_inr_total=4.5,
            slippage_cost_inr_total=75.0,
            quantity=75,
            multiplier=75.0,
            multiplier_doc="NIFTY 50 75 INR per point lot",
        ),
    ]
    run = _build_run(
        run_id="SIM-E2E-45",
        trades=trades,
        accounting_unit_mode=AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR,
        starting_capital_inr=250000.0,
        multiplier=75.0,
        multiplier_doc="NIFTY 50 75 INR per point lot",
    )

    store_path = tmp_path / "backtest_robust_store.db"
    rb_store = BacktestRobustnessStore(db_path=store_path)
    engine = BacktestRobustnessEngine(robustness_store=rb_store)

    r_a = engine.evaluate_simulation_run(
        run,
        candles_df=df,
        persist=True,
        created_at_utc=datetime(2026, 6, 20, 8, 0, tzinfo=timezone.utc),
    )
    r_b = engine.evaluate_simulation_run(
        run,
        candles_df=df,
        persist=False,
        created_at_utc=datetime(2026, 6, 20, 12, 0, tzinfo=timezone.utc),
    )
    assert r_a.report_id == r_b.report_id
    assert r_a.report_fingerprint == r_b.report_fingerprint
    assert r_a.configuration_fingerprint == r_b.configuration_fingerprint
    assert r_a.execution_mode == EXECUTION_MODE
    assert r_a.statistical_significance_claimed is False
    assert r_a.sample_size_governance.classification == SampleSizeClassification.INSUFFICIENT_SAMPLE

    loaded = rb_store.get_report(r_a.report_id)
    assert loaded is not None
    assert loaded.report_fingerprint == r_a.report_fingerprint
    assert len(rb_store.list_reports(run_id=run.run_id)) == 1

    md = render_robustness_markdown_report(r_a)
    assert r_a.report_id in md
    assert "INDEX_POINTS_AND_EXPLICIT_INR" in md
    assert "Sample Size Governance" in md

    # Read-only copy verification against all persisted Step 4.3 simulation runs
    if DEFAULT_BACKTEST_DB_PATH.exists():
        copy_db = tmp_path / "backtest_foundation_copy.db"
        shutil.copy2(DEFAULT_BACKTEST_DB_PATH, copy_db)
        copy_ds = HistoricalDataStore(config=BacktestConfiguration(storage_db_path=str(copy_db)))
        copy_rb_store = BacktestRobustnessStore(db_path=copy_db)
        copy_eng = BacktestRobustnessEngine(data_store=copy_ds, robustness_store=copy_rb_store)
        sim_runs = copy_ds.list_simulation_runs()
        assert len(sim_runs) >= 1
        for row in sim_runs:
            rep = copy_eng.evaluate_stored_run(row["run_id"], persist=True)
            assert rep.execution_mode == EXECUTION_MODE
            assert rep.statistical_significance_claimed is False
            assert copy_rb_store.get_report(rep.report_id) is not None


# ---------------------------------------------------------------------------
# 10. Architectural Isolation AST Test
# ---------------------------------------------------------------------------


def test_step4_5_modules_never_import_production_paper_or_ml() -> None:
    backtesting_dir = Path(__file__).resolve().parents[1] / "app" / "backtesting"
    py_files = sorted(backtesting_dir.glob("*.py"))
    assert len(py_files) >= 15

    forbidden = ("paper_trading", "ml_feedback_engine")
    violations: List[str] = []
    for path in py_files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if any(tok in alias.name for tok in forbidden):
                        violations.append(f"{path.name}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if any(tok in mod for tok in forbidden):
                    violations.append(f"{path.name}: from {mod} import ...")
    assert not violations, f"Isolation violation detected: {violations}"

