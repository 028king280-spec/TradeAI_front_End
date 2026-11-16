"""
Dedicated Step 4.3 Test Suite: Isolated Historical Execution Simulator.

Covers every Step 4.3 acceptance criterion using clearly labeled deterministic test
fixtures inside `tmp_path` plus read-only verification against Step 4.2 storage:
1. Next-bar execution & strict no-lookahead enforcement
2. Incomplete candle & missing interval rejection
3. Entry/exit fills, slippage, tick alignment & stop-loss / targets
4. Partial exits & zero double-count prevention
5. Intrabar ambiguity conservative handling & audit evidence
6. Gap handling (entry gap reject & post-entry gap stop-out)
7. Capital constraints & allocation ceilings
8. Versioned transaction cost schedules & Mode A/B separation
9. Portfolio reconciliation, equity curve, drawdown & unrealized MTM
10. Deterministic repeated replay (bit-identical output fingerprints)
11. Mode B Synthetic Black-Scholes labelling (`SYNTHETIC_MODELLED_OPTION_PNL`) & assumptions
12. Fail-closed behavior on missing data, unverified calendars, SENSEX governance lock
13. Zero imports of PaperTradingEngine / MLFeedbackEngine & persistence isolation
14. Integration with Step 4.2 ReplayRunRecord (`simulate_from_replay`, REAL_OPTION_OHLC blocked)
"""

from __future__ import annotations

import ast
from datetime import datetime, time as dt_time, timedelta
import hashlib
from pathlib import Path
from typing import Dict, List

import pandas as pd
import pytest

from app.backtesting import (
    AccountingUnitMode,
    AmbiguityPolicy,
    BacktestConfiguration,
    CostBreakdown,
    DeterministicReplayRunner,
    EquityCurvePoint,
    ExecutionSimulatorDesignSpec,
    ExitReason,
    FillRecord,
    GapPolicy,
    HistoricalDataStore,
    HistoricalExecutionSimulator,
    HistoricalMarketCalendarAdapter,
    IntrabarAmbiguityPolicy,
    OptionDataMode,
    OrderSide,
    OrderStatus,
    PortfolioLedger,
    PortfolioSummary,
    SimulationConfiguration,
    SimulationDomainMode,
    SimulationMode,
    SimulationSignal,
    SimulationStatus,
    SignalDirection,
    SyntheticBSAssumptions,
    SyntheticOptionCostConfig,
    TradeLifecycleState,
    TradeRecord,
    TriggerPriceDomain,
    UnderlyingPointsCostConfig,
    assert_exit_quantity_valid,
    compute_candle_close_ist,
    price_synthetic_bs_option,
    quantity_unit_label_for_config,
    resolve_provenance_label,
    validate_trade_transition,
)
from app.backtesting.configuration import IST_ZONE
from app.options.contract_selector import GovernanceLedger, build_canonical_approval_payload


def _cfg_for_tmp(tmp_path: Path, **overrides) -> SimulationConfiguration:
    defaults: dict = {
        "mode": SimulationMode.UNDERLYING_POINTS_ONLY,
        "monetary_accounting_enabled": False,
        "storage_db_path": str(tmp_path / "isolated_sim.db"),
    }
    if overrides.get("mode") == SimulationMode.SYNTHETIC_BS_RESEARCH:
        defaults.pop("monetary_accounting_enabled", None)
    defaults.update(overrides)
    return SimulationConfiguration(**defaults)


def _build_5m_session_bars(
    opens_closes: List[tuple[float, float, float, float]],
    *,
    day_str: str = "2026-06-15",
    instrument: str = "NIFTY 50",
    timeframe: str = "5m",
    is_complete_override: Dict[int, bool] | None = None,
) -> pd.DataFrame:
    """Builds a clearly labeled deterministic 5m test fixture starting 09:15 IST."""
    d_base = datetime.fromisoformat(f"{day_str}T09:15:00+05:30").astimezone(IST_ZONE)
    rows = []
    for idx, (o, h, l, c) in enumerate(opens_closes):
        ts = d_base + timedelta(minutes=5 * idx)
        comp = True if is_complete_override is None else is_complete_override.get(idx, True)
        rows.append(
            {
                "timestamp": ts,
                "open": float(o),
                "high": float(h),
                "low": float(l),
                "close": float(c),
                "volume": float(10_000 + idx * 100),
                "is_complete": comp,
            }
        )
    df = pd.DataFrame(rows)
    df.attrs = {
        "instrument": instrument,
        "timeframe": timeframe,
        "provider": "test_fixture",
        "dataStatus": "VERIFIED_EOD",
        "feedStatus": "VERIFIED_EOD",
        "is_mock": False,
        "is_synthetic": False,
        "ohlc_repaired": False,
    }
    return df


def _ts_5m(idx: int, day_str: str = "2026-06-15", close: bool = False) -> datetime:
    base = datetime.fromisoformat(f"{day_str}T09:15:00+05:30").astimezone(IST_ZONE)
    open_t = base + timedelta(minutes=5 * idx)
    return open_t + timedelta(minutes=5) if close else open_t


def test_next_bar_execution_and_no_lookahead_enforcement(tmp_path: Path):
    # Bar 0 [09:15..09:20]: opens at 24000, dips to 23950, closes 24020 (emits signal at 09:20).
    # Bar 1 [09:20..09:25]: opens at 24050 (must enter here, NOT at 24000 or 24020), reaches 24100.
    # Bar 2 [09:25..09:30]: closes out at EOD or target 24110.
    df = _build_5m_session_bars(
        [
            (24000.0, 24030.0, 23950.0, 24020.0),  # Signal bar closes at 09:20
            (24050.0, 24105.0, 24040.0, 24095.0),  # Next completed bar: open=24050 -> T1=24100 hit
            (24095.0, 24120.0, 24085.0, 24115.0),
        ]
    )
    sig_same = SimulationSignal(
        signal_id="SIG-NO-LOOKAHEAD",
        instrument="NIFTY 50",
        timeframe="5m",
        signal_available_at_ist=_ts_5m(0, close=True),  # 09:20:00
        direction=SignalDirection.LONG,
        trigger_domain=TriggerPriceDomain.UNDERLYING_POINTS,
        stop_loss=24010.0,
        target_1=24100.0,
        quantity_units=10,
        intraday_square_off=False,
    )
    # Also test a trailing signal emitted at Bar 2 close (09:30) with zero subsequent bars
    sig_late = SimulationSignal(
        signal_id="SIG-TRAILING-EXPIRE",
        instrument="NIFTY 50",
        timeframe="5m",
        signal_available_at_ist=_ts_5m(2, close=True),  # 09:30:00
        direction=SignalDirection.LONG,
        trigger_domain=TriggerPriceDomain.UNDERLYING_POINTS,
        stop_loss=24080.0,
        target_1=24160.0,
        quantity_units=10,
        intraday_square_off=False,
    )

    sim = HistoricalExecutionSimulator(
        config=_cfg_for_tmp(tmp_path),
        points_cost_config=UnderlyingPointsCostConfig(slippage_per_unit=0.5),
    )
    res = sim.run_simulation(
        instrument="NIFTY 50",
        timeframe="5m",
        signals=[sig_same, sig_late],
        candles_df=df,
    )
    assert res.status == SimulationStatus.COMPLETED
    assert res.reconciliation.reconciled is True

    by_sig = {t.signal_id: t for t in res.trades}
    tr_ok = by_sig["SIG-NO-LOOKAHEAD"]
    # Must enter strictly on Bar 1 open (09:20 open = 24050.0), never Bar 0 close/low
    assert tr_ok.entry_time_ist == _ts_5m(1, close=False).isoformat()
    assert tr_ok.entry_price == 24050.0
    assert tr_ok.final_exit_reason == ExitReason.TARGET_1
    assert tr_ok.gross_points == pytest.approx(24100.0 - 24050.0)
    # Two full-weight legs (1.0 entry + 1.0 exit) * 0.5 slippage = 1.0 index point; Net = 49.0 index points
    assert tr_ok.slippage_points == pytest.approx(1.0)
    assert tr_ok.net_points == pytest.approx(49.0)
    assert tr_ok.gross_pnl_inr is None
    assert tr_ok.net_pnl_inr is None
    assert tr_ok.reserved_capital_inr is None

    tr_late = by_sig["SIG-TRAILING-EXPIRE"]
    assert tr_late.state == TradeLifecycleState.CANCELLED
    assert tr_late.rejection_reason == "NO_ELIGIBLE_COMPLETED_FUTURE_BAR_AVAILABLE"


def test_incomplete_candle_and_missing_interval_rejected(tmp_path: Path):
    df_incomplete = _build_5m_session_bars(
        [
            (24000.0, 24020.0, 23990.0, 24010.0),
            (24010.0, 24040.0, 24005.0, 24035.0),
        ],
        is_complete_override={1: False},
    )
    sim = HistoricalExecutionSimulator(config=_cfg_for_tmp(tmp_path))
    res_inc = sim.run_simulation(
        instrument="NIFTY 50",
        timeframe="5m",
        signals=[],
        candles_df=df_incomplete,
    )
    assert res_inc.status == SimulationStatus.FAILED_INTEGRITY
    assert res_inc.portfolio.trades_opened == 0

    # Missing 09:20 candle -> DataIntegrityAuditor fails closed before execution
    df_gap = _build_5m_session_bars(
        [
            (24000.0, 24020.0, 23990.0, 24010.0),
            (24025.0, 24050.0, 24015.0, 24045.0),
        ]
    )
    df_gap.loc[1, "timestamp"] = _ts_5m(2, close=False)  # 09:25 instead of 09:20
    res_gap = sim.run_simulation(
        instrument="NIFTY 50",
        timeframe="5m",
        signals=[],
        candles_df=df_gap,
    )
    assert res_gap.status == SimulationStatus.FAILED_INTEGRITY


def test_partial_exits_and_double_count_prevention(tmp_path: Path):
    # Bar 0: signal closes 09:20
    # Bar 1 [09:20..09:25]: enters LONG at 24000 (qty 100), stays between 23990..24035 (hits T1=24030 -> partial 50%)
    # Bar 2 [09:25..09:30]: moves cleanly 24030..24065 (hits T2=24060 -> remaining 50%, T1 CANNOT trigger again!)
    df = _build_5m_session_bars(
        [
            (23990.0, 24005.0, 23980.0, 24000.0),
            (24000.0, 24035.0, 23990.0, 24028.0),
            (24028.0, 24065.0, 24022.0, 24060.0),
        ]
    )
    sig = SimulationSignal(
        signal_id="SIG-PARTIAL-TWO-LEGS",
        instrument="NIFTY 50",
        timeframe="5m",
        signal_available_at_ist=_ts_5m(0, close=True),
        direction=SignalDirection.LONG,
        trigger_domain=TriggerPriceDomain.UNDERLYING_POINTS,
        stop_loss=23970.0,
        target_1=24030.0,
        target_2=24060.0,
        partial_exit_fraction=0.5,
        quantity_units=100,
        intraday_square_off=False,
    )
    cfg = _cfg_for_tmp(tmp_path)
    sim = HistoricalExecutionSimulator(
        config=cfg,
        points_cost_config=UnderlyingPointsCostConfig(
            slippage_per_unit=0.5,
        ),
    )
    res = sim.run_simulation(instrument="NIFTY 50", timeframe="5m", signals=[sig], candles_df=df)
    assert res.status == SimulationStatus.COMPLETED
    assert res.accounting_unit_mode == AccountingUnitMode.INDEX_POINTS_ONLY
    assert res.reconciliation.reconciled is True
    assert res.reconciliation.non_mixing_invariant_passed is True
    assert res.reconciliation.points_reconciled is True
    assert res.reconciliation.monetary_reconciled is None
    assert res.reconciliation.over_exited_trades == ()
    assert res.reconciliation.residual_reserved_capital_inr is None

    tr = res.trades[0]
    assert tr.state == TradeLifecycleState.CLOSED
    assert tr.quantity_unit_label == "PARTIAL_EXIT_SLICE_UNITS"
    assert tr.initial_quantity == 100
    assert tr.exited_quantity == 100
    assert tr.remaining_quantity == 0
    assert len(tr.fills) == 3  # 1 ENTRY + 1 PARTIAL_EXIT + 1 final EXIT
    # Gross Points = 0.5*(24030-24000) + 0.5*(24060-24000) = 15 + 30 = 45.0 INDEX_POINTS
    assert tr.gross_points == pytest.approx(45.0)
    # Weighted slippage = 0.5*1.0 (entry) + 0.5*0.5 (T1) + 0.5*0.5 (T2) = 1.0 -> Net = 44.0 INDEX_POINTS
    assert tr.slippage_points == pytest.approx(1.0)
    assert tr.net_points == pytest.approx(44.0)
    assert tr.gross_pnl_inr is None
    assert tr.net_pnl_inr is None
    assert res.portfolio.partial_exits_count == 1
    assert res.portfolio.points_unit == "INDEX_POINTS"
    assert res.portfolio.currency_unit is None
    assert res.portfolio.available_cash_inr is None
    assert res.portfolio.ending_cumulative_points == pytest.approx(44.0)

    # Direct double-exit & invalid transition guards on lifecycle helpers
    with pytest.raises(ValueError, match="Double-exit"):
        assert_exit_quantity_valid(
            trade_id="T1",
            state=TradeLifecycleState.PARTIALLY_EXITED,
            initial_quantity=100,
            exited_quantity=60,
            remaining_quantity=40,
            exit_qty=50,
        )
    with pytest.raises(ValueError, match="Invalid trade lifecycle transition"):
        validate_trade_transition(TradeLifecycleState.CLOSED, TradeLifecycleState.OPEN)


def test_intrabar_ambiguity_conservative_policies(tmp_path: Path):
    # Bar 0: closes at 09:20
    # Bar 1: enters SHORT at 24100 (SL=24130, T1=24050) -> clean hold
    # Bar 2: spikes BOTH UP to 24140 (>= SL 24130) AND DOWN to 24040 (<= T1 24050) -> INTRABAR_AMBIGUOUS
    df = _build_5m_session_bars(
        [
            (24090.0, 24105.0, 24085.0, 24100.0),
            (24100.0, 24115.0, 24075.0, 24090.0),
            (24090.0, 24140.0, 24040.0, 24120.0),
        ]
    )
    sig = SimulationSignal(
        signal_id="SIG-AMBIG-SHORT",
        instrument="NIFTY 50",
        timeframe="5m",
        signal_available_at_ist=_ts_5m(0, close=True),
        direction=SignalDirection.SHORT,
        trigger_domain=TriggerPriceDomain.UNDERLYING_POINTS,
        stop_loss=24130.0,
        target_1=24050.0,
        quantity_units=20,
        intraday_square_off=False,
    )

    sim_sl = HistoricalExecutionSimulator(
        config=_cfg_for_tmp(
            tmp_path,
            ambiguity_policy=AmbiguityPolicy.CONSERVATIVE_SL_FIRST_WITH_AMBIGUOUS_TAG,
        ),
        points_cost_config=UnderlyingPointsCostConfig(slippage_per_unit=0.0),
    )
    res_sl = sim_sl.run_simulation(instrument="NIFTY 50", timeframe="5m", signals=[sig], candles_df=df)
    tr_sl = res_sl.trades[0]
    assert tr_sl.final_exit_reason == ExitReason.INTRABAR_AMBIGUOUS_SL
    assert tr_sl.intrabar_ambiguous_count == 1
    assert tr_sl.ambiguity_events[0].resolved_fill_price == pytest.approx(24130.0)
    assert "INTRABAR_AMBIGUOUS" in tr_sl.ambiguity_events[0].resolution_note
    assert tr_sl.gross_points == pytest.approx(24100.0 - 24130.0)  # -30.0 index points conservative loss
    assert tr_sl.gross_pnl_inr is None
    assert res_sl.portfolio.winning_trades == 0
    assert res_sl.portfolio.intrabar_ambiguous_count == 1

    # Policy MARK_AMBIGUOUS_WORST_CASE settles at worst bar extreme (24140 vs SL 24130 -> 24140)
    sim_worst = HistoricalExecutionSimulator(
        config=_cfg_for_tmp(
            tmp_path,
            ambiguity_policy=AmbiguityPolicy.MARK_AMBIGUOUS_WORST_CASE,
            storage_db_path=str(tmp_path / "isolated_sim_worst.db"),
        ),
        points_cost_config=UnderlyingPointsCostConfig(slippage_per_unit=0.0),
    )
    res_worst = sim_worst.run_simulation(instrument="NIFTY 50", timeframe="5m", signals=[sig], candles_df=df)
    tr_worst = res_worst.trades[0]
    assert tr_worst.final_exit_reason == ExitReason.INTRABAR_AMBIGUOUS_WORST_CASE
    assert tr_worst.gross_points == pytest.approx(24100.0 - 24140.0)  # -40.0 index points worst case
    assert tr_worst.gross_pnl_inr is None


def test_gap_handling_and_capital_constraints(tmp_path: Path):
    # Test 1: Post-entry bar opens gapped below SL -> exits conservatively at gap open (NOT SL)
    # Bar 0: signal closes 09:20
    # Bar 1: enters LONG at 24000, SL=23980, T1=24050
    # Bar 2: opens gapped down at 23950 -> fills GAP_STOP_OUT at 23950
    df = _build_5m_session_bars(
        [
            (23995.0, 24005.0, 23990.0, 24000.0),
            (24000.0, 24020.0, 23985.0, 24010.0),
            (23950.0, 23990.0, 23940.0, 23975.0),
        ]
    )
    sig_gap = SimulationSignal(
        signal_id="SIG-GAP-SL",
        instrument="NIFTY 50",
        timeframe="5m",
        signal_available_at_ist=_ts_5m(0, close=True),
        direction=SignalDirection.LONG,
        trigger_domain=TriggerPriceDomain.UNDERLYING_POINTS,
        stop_loss=23980.0,
        target_1=24050.0,
        quantity_units=10,
        intraday_square_off=False,
    )
    # Test 2: Entry zone gap rejection
    sig_zone_rej = SimulationSignal(
        signal_id="SIG-ZONE-REJ",
        instrument="NIFTY 50",
        timeframe="5m",
        signal_available_at_ist=_ts_5m(0, close=True),
        direction=SignalDirection.LONG,
        trigger_domain=TriggerPriceDomain.UNDERLYING_POINTS,
        stop_loss=23950.0,
        target_1=24060.0,
        entry_zone_min=23980.0,
        entry_zone_max=23995.0,  # Bar 1 open 24000 exceeds zone max -> REJECT_ENTRY_ON_GAP
        quantity_units=10,
        intraday_square_off=False,
    )
    # Test 3: Capital ceiling rejection (require reserve > available / allocation limit)
    sig_too_big = SimulationSignal(
        signal_id="SIG-CAP-REJ",
        instrument="NIFTY 50",
        timeframe="5m",
        signal_available_at_ist=_ts_5m(0, close=True),
        direction=SignalDirection.LONG,
        trigger_domain=TriggerPriceDomain.UNDERLYING_POINTS,
        stop_loss=23980.0,
        target_1=24050.0,
        quantity_units=10_000,  # Reserve = 0.15 * 24000 * 10000 = 36M > 2M
        intraday_square_off=False,
    )

    sim = HistoricalExecutionSimulator(
        config=_cfg_for_tmp(
            tmp_path,
            monetary_accounting_enabled=True,
            starting_capital_inr=2_000_000.0,
            instrument_multiplier_inr_per_point=1.0,
            instrument_multiplier_documentation="1 unit = 1 underlying index point at INR 1.00 per point (unit-notional margin check)",
            mode_a_margin_fraction=0.15,
            max_capital_fraction_per_trade=0.50,
            gap_policy=GapPolicy.REJECT_ENTRY_ON_GAP,
            allow_overlapping_positions=True,
        ),
        points_cost_config=UnderlyingPointsCostConfig(slippage_per_unit=0.0),
    )
    res = sim.run_simulation(
        instrument="NIFTY 50",
        timeframe="5m",
        signals=[sig_gap, sig_zone_rej, sig_too_big],
        candles_df=df,
    )
    assert res.reconciliation.reconciled is True
    assert res.reconciliation.non_mixing_invariant_passed is True
    assert res.accounting_unit_mode == AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR
    by_id = {t.signal_id: t for t in res.trades}

    assert by_id["SIG-GAP-SL"].final_exit_reason == ExitReason.GAP_STOP_OUT
    assert by_id["SIG-GAP-SL"].gross_points == pytest.approx(23950.0 - 24000.0)
    assert by_id["SIG-GAP-SL"].gross_pnl_inr == pytest.approx((23950.0 - 24000.0) * 10.0 * 1.0)

    assert by_id["SIG-ZONE-REJ"].state == TradeLifecycleState.REJECTED
    assert "GAP_REJECTED" in str(by_id["SIG-ZONE-REJ"].rejection_reason)

    assert by_id["SIG-CAP-REJ"].state == TradeLifecycleState.REJECTED
    assert "CAPITAL_ALLOCATION_LIMIT" in str(by_id["SIG-CAP-REJ"].rejection_reason)


def test_mode_b_synthetic_bs_labelling_costs_and_reconciliation(tmp_path: Path):
    # Spot rallies from 24000 -> 24180; synthetic 24000 CE rises cleanly & closes out
    df = _build_5m_session_bars(
        [
            (23990.0, 24005.0, 23985.0, 24000.0),
            (24000.0, 24120.0, 23995.0, 24110.0),
            (24110.0, 24200.0, 24105.0, 24190.0),
        ]
    )
    exp_dt = datetime.fromisoformat("2026-06-25T15:30:00+05:30").astimezone(IST_ZONE)
    assumptions = SyntheticBSAssumptions(
        option_type="CE",
        strike_price=24000.0,
        expiry_datetime_ist=exp_dt,
        implied_volatility=0.16,
        risk_free_rate=0.065,
        lot_size=65,
        lots=2,  # 130 qty so partial exit splits strictly 1 lot (65) + 1 lot (65)
    )
    entry_est = price_synthetic_bs_option(
        spot=24000.0,
        strike=24000.0,
        valuation_time_ist=_ts_5m(1, close=False),
        expiry_datetime_ist=exp_dt,
        risk_free_rate=0.065,
        dividend_yield=0.0,
        implied_volatility=0.16,
        option_type="CE",
    )
    sig_bs = SimulationSignal(
        signal_id="SIG-SYNTH-BS",
        instrument="NIFTY 50",
        timeframe="5m",
        signal_available_at_ist=_ts_5m(0, close=True),
        direction=SignalDirection.LONG,
        trigger_domain=TriggerPriceDomain.SYNTHETIC_OPTION_PREMIUM,
        stop_loss=max(0.5, round(entry_est - 50.0, 2)),
        target_1=round(entry_est + 35.0, 2),
        target_2=round(entry_est + 85.0, 2),
        partial_exit_fraction=0.5,
        quantity_units=130,
        synthetic_bs_assumptions=assumptions,
    )

    sim = HistoricalExecutionSimulator(
        config=_cfg_for_tmp(
            tmp_path,
            mode=SimulationMode.SYNTHETIC_BS_RESEARCH,
            starting_capital_inr=500_000.0,
            max_capital_fraction_per_trade=0.50,
        ),
        option_cost_config=SyntheticOptionCostConfig(
            brokerage_per_order=20.0,
            stt_sell_rate=0.001,
            exchange_txn_rate=0.0005,
            gst_rate=0.18,
            sebi_turnover_rate=0.000001,
            stamp_duty_buy_rate=0.00003,
            slippage_per_unit=0.5,
        ),
    )
    res1 = sim.run_simulation(instrument="NIFTY 50", timeframe="5m", signals=[sig_bs], candles_df=df)
    res2 = sim.run_simulation(instrument="NIFTY 50", timeframe="5m", signals=[sig_bs], candles_df=df, persist=False)

    assert res1.status == SimulationStatus.COMPLETED
    assert res1.accounting_unit_mode == AccountingUnitMode.SYNTHETIC_OPTION_INR_ONLY
    assert res1.provenance_label == "SYNTHETIC_MODELLED_OPTION_PNL"
    assert res1.is_synthetic_modelled is True
    assert res1.portfolio.provenance_label == "SYNTHETIC_MODELLED_OPTION_PNL"
    assert res1.portfolio.points_unit is None
    assert res1.portfolio.realized_net_points is None
    assert res1.portfolio.currency_unit == "INR"
    assert res1.cost_schedule.cost_domain == "SYNTHETIC_OPTION_PREMIUM_RESEARCH"
    assert res1.reconciliation.reconciled is True
    assert res1.reconciliation.non_mixing_invariant_passed is True

    # Deterministic repeated replay verification
    assert res1.run_id == res2.run_id
    assert res1.output_fingerprint == res2.output_fingerprint
    assert res1.portfolio == res2.portfolio

    tr = res1.trades[0]
    assert tr.is_synthetic_modelled is True
    assert tr.provenance_label == "SYNTHETIC_MODELLED_OPTION_PNL"
    assert tr.synthetic_bs_assumptions == assumptions
    assert tr.gross_points is None
    assert tr.slippage_points is None
    assert tr.net_points is None
    assert tr.option_premium_points_per_unit is not None
    assert tr.total_brokerage_and_statutory_inr > 0.0
    assert tr.total_slippage_cost_inr > 0.0
    assert tr.state == TradeLifecycleState.CLOSED
    # Verify itemized Indian option fees appeared cleanly
    assert sum(f.costs.stt_inr for f in tr.fills if f.costs.stt_inr is not None) > 0.0
    assert sum(f.costs.stamp_duty_inr for f in tr.fills if f.costs.stamp_duty_inr is not None) > 0.0
    assert sum(f.costs.gst_inr for f in tr.fills if f.costs.gst_inr is not None) > 0.0


def test_mode_separation_missing_data_calendar_and_sensex_lock(tmp_path: Path):
    df = _build_5m_session_bars(
        [
            (24000.0, 24020.0, 23990.0, 24010.0),
            (24010.0, 24030.0, 24005.0, 24025.0),
        ]
    )
    exp_dt = datetime.fromisoformat("2026-06-25T15:30:00+05:30").astimezone(IST_ZONE)
    bs_assump = SyntheticBSAssumptions(
        option_type="CE",
        strike_price=24000.0,
        expiry_datetime_ist=exp_dt,
        implied_volatility=0.16,
        risk_free_rate=0.065,
        lot_size=65,
        lots=1,
    )
    sig_bs = SimulationSignal(
        signal_id="SIG-MODE-B-ONLY",
        instrument="NIFTY 50",
        timeframe="5m",
        signal_available_at_ist=_ts_5m(0, close=True),
        direction=SignalDirection.LONG,
        trigger_domain=TriggerPriceDomain.SYNTHETIC_OPTION_PREMIUM,
        stop_loss=50.0,
        target_1=120.0,
        quantity_units=65,
        synthetic_bs_assumptions=bs_assump,
    )

    # 1. Mixing Mode B signal into Mode A simulator must fail closed (`LOCKED_OUT`)
    sim_a = HistoricalExecutionSimulator(config=_cfg_for_tmp(tmp_path, mode=SimulationMode.UNDERLYING_POINTS_ONLY))
    res_mix = sim_a.run_simulation(instrument="NIFTY 50", timeframe="5m", signals=[sig_bs], candles_df=df)
    assert res_mix.status == SimulationStatus.LOCKED_OUT
    assert any("MODE_ISOLATION_VIOLATION" in r for r in res_mix.failure_reasons)

    # 2. Cost config domain mismatch raises immediately
    with pytest.raises(ValueError, match="Mode isolation violation"):
        HistoricalExecutionSimulator(
            config=_cfg_for_tmp(tmp_path, mode=SimulationMode.UNDERLYING_POINTS_ONLY),
            option_cost_config=SyntheticOptionCostConfig(),
        )

    # 3. Missing isolated store data fails closed (`BLOCKED`, zero fabricated candles)
    res_missing = sim_a.run_simulation(instrument="BANK NIFTY", timeframe="3m", signals=[])
    assert res_missing.status == SimulationStatus.BLOCKED
    assert any("MISSING_HISTORICAL_DATA" in r for r in res_missing.failure_reasons)

    # 4. Unverified calendar year (2027) fails closed (`LOCKED_OUT`)
    df_2027 = _build_5m_session_bars(
        [
            (24000.0, 24020.0, 23990.0, 24010.0),
            (24010.0, 24030.0, 24005.0, 24025.0),
        ],
        day_str="2027-06-15",
    )
    res_cal = sim_a.run_simulation(instrument="NIFTY 50", timeframe="5m", signals=[], candles_df=df_2027)
    assert res_cal.status == SimulationStatus.LOCKED_OUT
    assert any("2027" in r for r in res_cal.failure_reasons)

    # 5. SENSEX locked out by default governance
    res_sx_locked = sim_a.run_simulation(
        instrument="SENSEX",
        timeframe="5m",
        signals=[],
        candles_df=_build_5m_session_bars(
            [(79000.0, 79040.0, 78980.0, 79020.0), (79020.0, 79050.0, 79010.0, 79040.0)],
            instrument="SENSEX",
        ),
    )
    assert res_sx_locked.status == SimulationStatus.GOVERNANCE_LOCKOUT


def test_step4_2_replay_integration_and_isolation_guarantees(tmp_path: Path):
    # Verify isolated persistence round-trip AND blocking REAL_OPTION_OHLC in simulate_from_replay
    from cryptography.hazmat.primitives.asymmetric import ed25519
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    cal = HistoricalMarketCalendarAdapter()
    bt_cfg = BacktestConfiguration(storage_db_path=str(tmp_path / "iso_42_43.db"), sensex_governance_approved=False)
    store = HistoricalDataStore(config=bt_cfg)

    # Verify AST isolation across all app/backtesting/*.py (zero paper_trading / ml_feedback_engine)
    pkg_dir = Path(__file__).resolve().parents[1] / "app" / "backtesting"
    for py_file in pkg_dir.glob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert "paper_trading" not in node.module
                assert "ml_feedback_engine" not in node.module
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    assert "paper_trading" not in alias.name
                    assert "ml_feedback_engine" not in alias.name

    # Run Step 4.2 real fixture replay + Step 4.3 Mode A execution simulation + REAL_OPTION_OHLC block
    as_of = datetime(2026, 6, 19, 14, 0, tzinfo=IST_ZONE)
    from tests.test_backtest_step4_2_foundation import _fixture_5tf_candles

    candles_5tf = _fixture_5tf_candles(cal, as_of, instrument="NIFTY 50")
    runner = DeterministicReplayRunner(config=bt_cfg, data_store=store, calendar_adapter=cal)
    replay = runner.run_replay(
        instrument="NIFTY 50",
        replay_times=[as_of - timedelta(minutes=30), as_of],
        candles_by_timeframe=candles_5tf,
    )

    sim_b = HistoricalExecutionSimulator(
        config=_cfg_for_tmp(
            tmp_path,
            mode=SimulationMode.SYNTHETIC_BS_RESEARCH,
            storage_db_path=str(tmp_path / "iso_42_43.db"),
        ),
        backtest_config=bt_cfg,
        data_store=store,
        calendar_adapter=cal,
    )
    spec_real_blocked = ExecutionSimulatorDesignSpec(
        simulation_domain=SimulationDomainMode.OPTIONS_PREMIUM_SIMULATION,
        option_data_mode=OptionDataMode.REAL_OPTION_OHLC,
        intrabar_ambiguity_policy=IntrabarAmbiguityPolicy.CONSERVATIVE_SL_FIRST_WITH_AMBIGUOUS_TAG,
    )
    blocked_out = sim_b.simulate_from_replay(replay, spec_real_blocked, candles_df=candles_5tf["5m"])
    assert blocked_out["status"] == SimulationStatus.BLOCKED.value
    assert "REAL_OPTION_OHLC_UNAVAILABLE" in blocked_out["failure_reasons"][0]

    sim_a = HistoricalExecutionSimulator(
        config=_cfg_for_tmp(
            tmp_path,
            mode=SimulationMode.UNDERLYING_POINTS_ONLY,
            storage_db_path=str(tmp_path / "iso_42_43.db"),
        ),
        backtest_config=bt_cfg,
        data_store=store,
        calendar_adapter=cal,
    )
    spec_a = ExecutionSimulatorDesignSpec(
        simulation_domain=SimulationDomainMode.UNDERLYING_POINTS_ONLY,
        option_data_mode=None,
    )
    sim_out = sim_a.simulate_from_replay(
        replay,
        spec_a,
        timeframe="5m",
        candles_df=candles_5tf["5m"],
        persist=True,
    )
    assert sim_out["status"] == SimulationStatus.COMPLETED.value
    assert sim_out["provenance_label"] == "UNDERLYING_INDEX_POINTS_ONLY"
    assert sim_out["reconciliation"]["reconciled"] is True
    loaded = store.get_simulation_run(sim_out["run_id"])
    assert loaded is not None
    assert loaded.output_fingerprint == sim_out["output_fingerprint"]

    # SENSEX authorized ONLY via temp isolated governance ledger
    iso_ledger_path = tmp_path / "sensex_step43_ledger.db"
    ledger = GovernanceLedger(db_path=str(iso_ledger_path))
    priv = ed25519.Ed25519PrivateKey.generate()
    pub_hex = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
    ledger.register_authority(
        key_id="TEST-STEP43-AUTH",
        authority_name="Test Step 4.3 Authority",
        public_key_hex=pub_hex,
        authorized_indices=["SENSEX"],
        valid_from="2026-01-01",
        valid_until="2027-12-31",
    )
    doc_hash = hashlib.sha256(b"STEP43_SENSEX_TEST").hexdigest()
    payload = build_canonical_approval_payload(
        approval_id="APPR-43-01",
        document_id="DOC-43-01",
        approval_reference="QRC-STEP43-SX",
        document_sha256=doc_hash,
        ratifying_authority="TEST AUTH",
        authorized_indices=["SENSEX"],
        min_oi_floor=10000,
        min_volume_floor=5000,
        max_spread_pct_ceiling=0.05,
        effective_date="2026-01-01",
        expiry_date="2027-12-31",
    )
    ledger.record_verified_approval(
        approval_reference="QRC-STEP43-SX",
        approval_id="APPR-43-01",
        approved_by="TEST AUTH",
        authorized_indices=["SENSEX"],
        key_id="TEST-STEP43-AUTH",
        min_oi_floor=10000,
        min_volume_floor=5000,
        max_spread_pct_ceiling=0.05,
        effective_date="2026-01-01",
        expiry_date="2027-12-31",
        approval_evidence={
            "document_id": "DOC-43-01",
            "document_sha256": doc_hash,
            "digital_signature": priv.sign(payload).hex(),
            "ratified_by": "TEST AUTH",
            "effective_date": "2026-01-01",
            "expiry_date": "2027-12-31",
        },
        doc_id="DOC-43-01",
        recomputed_hash=doc_hash,
    )
    sim_sx = HistoricalExecutionSimulator(
        config=_cfg_for_tmp(
            tmp_path,
            mode=SimulationMode.UNDERLYING_POINTS_ONLY,
            sensex_governance_approved=True,
            governance_ledger_path=str(iso_ledger_path),
            storage_db_path=str(tmp_path / "iso_42_43.db"),
        ),
        backtest_config=BacktestConfiguration(
            storage_db_path=str(tmp_path / "iso_42_43.db"),
            governance_ledger_path=str(iso_ledger_path),
            sensex_governance_approved=True,
        ),
        data_store=store,
        calendar_adapter=cal,
    )
    sx_df = _build_5m_session_bars(
        [(79000.0, 79040.0, 78980.0, 79020.0), (79020.0, 79080.0, 79010.0, 79075.0)],
        instrument="SENSEX",
    )
    res_sx = sim_sx.run_simulation(instrument="SENSEX", timeframe="5m", signals=[], candles_df=sx_df, persist=False)
    assert res_sx.status == SimulationStatus.COMPLETED


def test_short_direction_mtm_drawdown_and_reconciliation_mismatch(tmp_path: Path):
    # Bar 0: signal SHORT at bar 0 close (09:20) -> SL=24120, T1=23980, T2=23940
    # Bar 1: opens 24050 (short fills with adverse downward slippage: <= 24050), highs 24080 (adverse MTM drawdown), closes 24070
    # Bar 2: lows 23930 -> hits T1 & T2 cleanly for short
    df = _build_5m_session_bars(
        [
            (24060.0, 24070.0, 24040.0, 24050.0),
            (24050.0, 24085.0, 24040.0, 24075.0),
            (24075.0, 24080.0, 23930.0, 23935.0),
        ]
    )
    sig_short = SimulationSignal(
        signal_id="SIG-SHORT-1",
        instrument="NIFTY 50",
        timeframe="5m",
        signal_available_at_ist=_ts_5m(0, close=True),
        direction=SignalDirection.SHORT,
        trigger_domain=TriggerPriceDomain.UNDERLYING_POINTS,
        stop_loss=24120.0,
        target_1=23980.0,
        target_2=23940.0,
        partial_exit_fraction=0.5,
        quantity_units=100,
    )
    sim = HistoricalExecutionSimulator(
        config=_cfg_for_tmp(tmp_path, mode=SimulationMode.UNDERLYING_POINTS_ONLY),
        points_cost_config=UnderlyingPointsCostConfig(slippage_per_unit=1.0),
    )
    res = sim.run_simulation(instrument="NIFTY 50", timeframe="5m", signals=[sig_short], candles_df=df)
    assert res.status == SimulationStatus.COMPLETED
    assert res.accounting_unit_mode == AccountingUnitMode.INDEX_POINTS_ONLY
    assert res.reconciliation.reconciled is True
    assert res.reconciliation.non_mixing_invariant_passed is True
    assert len(res.trades) == 1
    tr = res.trades[0]
    assert tr.direction == SignalDirection.SHORT
    assert tr.state == TradeLifecycleState.CLOSED
    # Short entry stores raw price (24050.0) for non-double-counted gross points,
    # while FillRecord.effective_fill_price applies adverse slippage (24049.0 entry, 23981.0 & 23941.0 exits)
    assert tr.entry_price == 24050.0
    assert tr.fills[0].effective_fill_price == 24049.0
    assert tr.fills[1].effective_fill_price == 23981.0
    assert tr.fills[2].effective_fill_price == 23941.0
    # 0.5*(24050 - 23980) + 0.5*(24050 - 23940) = 35 + 55 = 90.0 INDEX_POINTS
    assert tr.gross_points == pytest.approx(90.0)
    # 1.0*1.0 (entry) + 1.0*0.5 (T1) + 1.0*0.5 (T2) = 2.0 INDEX_POINTS slippage -> Net = 88.0
    assert tr.slippage_points == pytest.approx(2.0)
    assert tr.net_points == pytest.approx(88.0)
    assert tr.gross_pnl_inr is None
    assert tr.net_pnl_inr is None
    # Bar 1 ended with adverse MTM points drawdown before bar 2 profited
    assert res.portfolio.max_drawdown_points > 0.0
    assert res.portfolio.max_drawdown_inr is None
    assert res.portfolio.max_drawdown_pct is None
    assert res.equity_curve[1].unrealized_points < 0.0
    assert res.equity_curve[1].unrealized_pnl_inr is None
    assert res.equity_curve[2].unrealized_points == 0.0

    # Portfolio reconciliation mismatch fail-closed verification (Monetary Mode A cash conservation)
    ledger = PortfolioLedger(
        mode=SimulationMode.UNDERLYING_POINTS_ONLY,
        accounting_unit_mode=AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR,
        provenance_label="UNDERLYING_INDEX_POINTS_WITH_EXPLICIT_INR_MULTIPLIER",
        starting_capital_inr=100_000.0,
        instrument_multiplier_inr_per_point=65.0,
        instrument_multiplier_documentation="1 unit = 1 NIFTY 50 lot (INR 65 per index point).",
    )
    ledger.available_cash_inr = 99_500.0  # unaccounted INR cash leak
    bad_recon = ledger.reconcile([])
    assert bad_recon.reconciled is False
    assert any("CASH_CONSERVATION_MISMATCH_INR" in f for f in bad_recon.failed_checks)


def test_points_only_strictly_reports_index_points_and_invariant_to_quantity_units(tmp_path: Path):
    """
    UNDERLYING_POINTS_ONLY default (`INDEX_POINTS_ONLY`) MUST report pure 1x index points,
    NEVER scale points by `quantity_units`, NEVER treat points as rupees, and keep all
    monetary / percentage-return fields strictly `None`.
    """
    df = _build_5m_session_bars(
        [
            (23990.0, 24005.0, 23980.0, 24000.0),
            (24000.0, 24035.0, 23990.0, 24028.0),
            (24028.0, 24065.0, 24022.0, 24060.0),
        ]
    )

    def _run_with_qty(qty: int, db_name: str):
        sig = SimulationSignal(
            signal_id=f"SIG-INV-{qty}",
            instrument="NIFTY 50",
            timeframe="5m",
            signal_available_at_ist=_ts_5m(0, close=True),
            direction=SignalDirection.LONG,
            trigger_domain=TriggerPriceDomain.UNDERLYING_POINTS,
            stop_loss=23980.0,
            target_1=24030.0,
            target_2=24060.0,
            partial_exit_fraction=0.5,
            quantity_units=qty,
            intraday_square_off=False,
        )
        db_path = str(tmp_path / db_name)
        sim = HistoricalExecutionSimulator(
            config=_cfg_for_tmp(tmp_path, storage_db_path=db_path),
            points_cost_config=UnderlyingPointsCostConfig(slippage_per_unit=0.5),
        )
        return sim.run_simulation(instrument="NIFTY 50", timeframe="5m", signals=[sig], candles_df=df), db_path

    res_10, db_10 = _run_with_qty(10, "inv_10.db")
    res_750, _ = _run_with_qty(750, "inv_750.db")

    for res in (res_10, res_750):
        assert res.status == SimulationStatus.COMPLETED
        assert res.accounting_unit_mode == AccountingUnitMode.INDEX_POINTS_ONLY
        assert res.provenance_label == "UNDERLYING_INDEX_POINTS_ONLY"
        assert res.reconciliation.reconciled is True
        assert res.reconciliation.non_mixing_invariant_passed is True
        p = res.portfolio
        assert p.monetary_accounting_enabled is False
        assert p.points_unit == "INDEX_POINTS"
        assert p.realized_gross_points == pytest.approx(45.0)
        assert p.total_slippage_points == pytest.approx(1.0)
        assert p.realized_net_points == pytest.approx(44.0)
        assert p.ending_cumulative_points == pytest.approx(44.0)
        assert p.currency_unit is None
        assert p.starting_capital_inr is None
        assert p.available_cash_inr is None
        assert p.reserved_capital_inr is None
        assert p.ending_equity_inr is None
        assert p.realized_gross_pnl_inr is None
        assert p.total_brokerage_inr is None
        assert p.total_costs_inr is None
        assert p.realized_net_pnl_inr is None
        assert p.net_return_pct is None
        assert p.max_drawdown_inr is None
        assert p.max_drawdown_pct is None
        assert res.trades[0].quantity_unit_label == "PARTIAL_EXIT_SLICE_UNITS"

    # Changing signal quantity_units MUST NOT alter any index-point P&L or equity curve point
    assert res_10.portfolio.realized_net_points == res_750.portfolio.realized_net_points
    assert res_10.portfolio.max_drawdown_points == res_750.portfolio.max_drawdown_points
    assert [e.cumulative_equity_points for e in res_10.equity_curve] == [
        e.cumulative_equity_points for e in res_750.equity_curve
    ]

    # Verify SQLite isolated summary table stores unit-segregated NULL INR columns cleanly
    rows = HistoricalDataStore(db_path=db_10).list_simulation_runs()
    assert len(rows) == 1
    assert rows[0]["accounting_unit_mode"] == "INDEX_POINTS_ONLY"
    assert rows[0]["points_unit"] == "INDEX_POINTS"
    assert rows[0]["realized_net_points"] == pytest.approx(44.0)
    assert rows[0]["currency_unit"] is None
    assert rows[0]["realized_net_pnl_inr"] is None
    assert rows[0]["total_costs_inr"] is None


def test_detect_and_reject_points_currency_mixing(tmp_path: Path):
    """Explicit guard suite verifying accidental mixing of index points and INR fails closed."""
    # 1. Currency parameters disallowed in pure INDEX_POINTS_ONLY
    with pytest.raises(ValueError, match="CURRENCY_DISALLOWED_IN_POINTS_ONLY"):
        SimulationConfiguration(
            mode=SimulationMode.UNDERLYING_POINTS_ONLY,
            starting_capital_inr=100_000.0,
        )
    with pytest.raises(ValueError, match="CURRENCY_DISALLOWED_IN_POINTS_ONLY"):
        SimulationConfiguration(
            mode=SimulationMode.UNDERLYING_POINTS_ONLY,
            instrument_multiplier_inr_per_point=65.0,
        )
    with pytest.raises(ValueError, match="CURRENCY_DISALLOWED_IN_POINTS_ONLY"):
        SimulationConfiguration(
            mode=SimulationMode.UNDERLYING_POINTS_ONLY,
            mode_a_margin_fraction=0.15,
        )

    # 2. Monetary Mode A opt-in requires explicit multiplier + >=10 char documentation + capital
    with pytest.raises(ValueError, match="EXPLICIT_MULTIPLIER_REQUIRED"):
        SimulationConfiguration(
            mode=SimulationMode.UNDERLYING_POINTS_ONLY,
            monetary_accounting_enabled=True,
            starting_capital_inr=500_000.0,
            instrument_multiplier_documentation="Missing numeric multiplier should fail",
        )
    with pytest.raises(ValueError, match="MULTIPLIER_DOCUMENTATION_REQUIRED"):
        SimulationConfiguration(
            mode=SimulationMode.UNDERLYING_POINTS_ONLY,
            monetary_accounting_enabled=True,
            starting_capital_inr=500_000.0,
            instrument_multiplier_inr_per_point=65.0,
            instrument_multiplier_documentation="short",
        )
    with pytest.raises(ValueError, match="STARTING_CAPITAL_INR_REQUIRED"):
        SimulationConfiguration(
            mode=SimulationMode.UNDERLYING_POINTS_ONLY,
            monetary_accounting_enabled=True,
            instrument_multiplier_inr_per_point=65.0,
            instrument_multiplier_documentation="1 unit = 1 NIFTY 50 lot (INR 65 per point)",
        )

    # 3. INR brokerage or statutory tax rates forbidden in pure INDEX_POINTS_ONLY cost calculator
    with pytest.raises(ValueError, match="MODE_MIXING_POINTS_AND_CURRENCY"):
        HistoricalExecutionSimulator(
            config=_cfg_for_tmp(tmp_path),
            points_cost_config=UnderlyingPointsCostConfig(brokerage_per_order=20.0),
        )
    with pytest.raises(ValueError, match="MODE_MIXING_POINTS_AND_CURRENCY"):
        HistoricalExecutionSimulator(
            config=_cfg_for_tmp(tmp_path),
            points_cost_config=UnderlyingPointsCostConfig(stt_sell_rate=0.001),
        )

    # 4. Schema-level model validators detect INR values injected into INDEX_POINTS objects
    with pytest.raises(ValueError, match="MODE_MIXING_POINTS_AND_CURRENCY"):
        CostBreakdown(
            cost_model_version="TEST",
            effective_date_ist="2026-06-15",
            cost_domain="UNDERLYING_POINTS_ONLY",
            cost_unit="INDEX_POINTS",
            slippage_points_leg=0.5,
            brokerage_inr=20.0,
        )

    with pytest.raises(ValueError, match="MODE_MIXING_POINTS_AND_CURRENCY"):
        PortfolioSummary(
            mode=SimulationMode.UNDERLYING_POINTS_ONLY,
            accounting_unit_mode=AccountingUnitMode.INDEX_POINTS_ONLY,
            provenance_label="UNDERLYING_INDEX_POINTS_ONLY",
            is_synthetic_modelled=False,
            monetary_accounting_enabled=False,
            points_unit="INDEX_POINTS",
            realized_gross_points=10.0,
            total_slippage_points=1.0,
            realized_net_points=9.0,
            unrealized_points=0.0,
            ending_cumulative_points=9.0,
            max_drawdown_points=0.0,
            realized_net_pnl_inr=900.0,  # forbidden currency leak!
            total_signals=1,
            trades_opened=1,
            trades_closed=1,
            trades_rejected=0,
            partial_exits_count=0,
            intrabar_ambiguous_count=0,
            winning_trades=1,
            losing_trades=0,
        )

    with pytest.raises(ValueError, match="MODE_MIXING_POINTS_AND_CURRENCY"):
        EquityCurvePoint(
            timestamp_ist="2026-06-15T09:20:00+05:30",
            accounting_unit_mode=AccountingUnitMode.INDEX_POINTS_ONLY,
            open_trades_count=0,
            realized_gross_points=10.0,
            total_slippage_points=1.0,
            realized_net_points=9.0,
            unrealized_points=0.0,
            cumulative_equity_points=9.0,
            drawdown_points=0.0,
            available_cash_inr=500_000.0,  # forbidden currency leak!
        )

    # 5. Runtime PortfolioLedger audit catches tampered currency state inside INDEX_POINTS_ONLY
    tampered_ledger = PortfolioLedger(
        mode=SimulationMode.UNDERLYING_POINTS_ONLY,
        accounting_unit_mode=AccountingUnitMode.INDEX_POINTS_ONLY,
        provenance_label="UNDERLYING_INDEX_POINTS_ONLY",
    )
    tampered_ledger.available_cash_inr = 50_000.0
    recon_tampered = tampered_ledger.reconcile([])
    assert recon_tampered.reconciled is False
    assert recon_tampered.non_mixing_invariant_passed is False
    assert "POINTS_ONLY_MONETARY_LEAKAGE_IN_LEDGER" in recon_tampered.failed_checks

    tampered_b = PortfolioLedger(
        mode=SimulationMode.SYNTHETIC_BS_RESEARCH,
        accounting_unit_mode=AccountingUnitMode.SYNTHETIC_OPTION_INR_ONLY,
        provenance_label="SYNTHETIC_MODELLED_OPTION_PNL",
        starting_capital_inr=500_000.0,
    )
    tampered_b.realized_net_points = 15.0  # forbidden index-point leak inside Mode B!
    recon_tampered_b = tampered_b.reconcile([])
    assert recon_tampered_b.reconciled is False
    assert recon_tampered_b.non_mixing_invariant_passed is False
    assert "OPTION_INR_INDEX_POINTS_LEAKAGE_IN_LEDGER" in recon_tampered_b.failed_checks


def test_mode_a_explicit_documented_inr_multiplier_separate_reporting(tmp_path: Path):
    """
    When Mode A explicitly opts into monetary accounting with a documented INR multiplier
    and explicit `starting_capital_inr`, BOTH `INDEX_POINTS` and `INR` metrics are reported
    and reconciled separately without ever conflating points and rupees.
    """
    df = _build_5m_session_bars(
        [
            (23990.0, 24005.0, 23980.0, 24000.0),
            (24000.0, 24035.0, 23990.0, 24028.0),
            (24028.0, 24065.0, 24022.0, 24060.0),
        ]
    )
    sig = SimulationSignal(
        signal_id="SIG-EXPLICIT-MULT",
        instrument="NIFTY 50",
        timeframe="5m",
        signal_available_at_ist=_ts_5m(0, close=True),
        direction=SignalDirection.LONG,
        trigger_domain=TriggerPriceDomain.UNDERLYING_POINTS,
        stop_loss=23980.0,
        target_1=24030.0,
        target_2=24060.0,
        partial_exit_fraction=0.5,
        quantity_units=2,  # 2 NIFTY 50 lots @ 65 units/point per explicit documentation
        intraday_square_off=False,
    )
    doc = "1 unit = 1 NIFTY 50 contract (INR 65 per index point multiplier)"
    cfg = _cfg_for_tmp(
        tmp_path,
        monetary_accounting_enabled=True,
        starting_capital_inr=1_000_000.0,
        instrument_multiplier_inr_per_point=65.0,
        instrument_multiplier_documentation=doc,
        mode_a_margin_fraction=0.15,
        max_capital_fraction_per_trade=0.90,
    )
    sim = HistoricalExecutionSimulator(
        config=cfg,
        points_cost_config=UnderlyingPointsCostConfig(
            brokerage_per_order=20.0,
            slippage_per_unit=0.5,
        ),
    )
    res = sim.run_simulation(instrument="NIFTY 50", timeframe="5m", signals=[sig], candles_df=df)
    assert res.status == SimulationStatus.COMPLETED
    assert res.accounting_unit_mode == AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR
    assert res.provenance_label == "UNDERLYING_INDEX_POINTS_WITH_EXPLICIT_INR_MULTIPLIER"
    assert res.reconciliation.reconciled is True
    assert res.reconciliation.non_mixing_invariant_passed is True
    assert res.reconciliation.points_reconciled is True
    assert res.reconciliation.monetary_reconciled is True

    tr = res.trades[0]
    assert tr.quantity_unit_label == "SPECIFIED_INDEX_MULTIPLIER_UNITS"
    # Separately labelled index points: 0.5*30 + 0.5*60 = 45.0 gross, 1.0 slippage, 44.0 net
    assert tr.gross_points == pytest.approx(45.0)
    assert tr.slippage_points == pytest.approx(1.0)
    assert tr.net_points == pytest.approx(44.0)
    # Separately labelled INR: 45.0 * 2 * 65 = 5850.0 gross INR;
    # brokerage = 3 * 20 = 60.0 INR; slippage_inr = (2 + 1 + 1) * 0.5 * 65 = 130.0 INR -> net = 5660.0 INR
    assert tr.gross_pnl_inr == pytest.approx(5850.0)
    assert tr.total_brokerage_and_statutory_inr == pytest.approx(60.0)
    assert tr.total_slippage_cost_inr == pytest.approx(130.0)
    assert tr.total_costs_inr == pytest.approx(190.0)
    assert tr.net_pnl_inr == pytest.approx(5660.0)

    p = res.portfolio
    assert p.points_unit == "INDEX_POINTS"
    assert p.realized_net_points == pytest.approx(44.0)
    assert p.currency_unit == "INR"
    assert p.instrument_multiplier_inr_per_point == pytest.approx(65.0)
    assert p.instrument_multiplier_documentation == doc
    assert p.starting_capital_inr == pytest.approx(1_000_000.0)
    assert p.realized_net_pnl_inr == pytest.approx(5660.0)
    assert p.available_cash_inr == pytest.approx(1_005_660.0)
    assert p.reserved_capital_inr == pytest.approx(0.0)
    assert p.net_return_pct == pytest.approx(0.566)


