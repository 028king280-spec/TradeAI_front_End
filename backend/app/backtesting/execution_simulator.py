"""
AIVOLVE Phase 4 Step 4.3 — Isolated Event-Driven Historical Execution Simulator.

Consumes verified Step 4.2 OHLCV datasets, DataIntegrityAuditor, HistoricalMarketCalendarAdapter,
and ReplayRunRecord artifacts strictly in PAPER_TRADING_ONLY mode with:
- Next completed bar execution (`open[t_{k+1}]` strictly after signal close `t_k`)
- Strict Mode A (`UNDERLYING_POINTS_ONLY`) vs Mode B (`SYNTHETIC_BS_RESEARCH`) separation
- Conservative intrabar ambiguity policies with audit evidence
- Versioned itemized transaction cost & slippage accounting
- Double-entry portfolio ledger, equity curve, drawdown, and reconciliation checks
- Deterministic run IDs & output fingerprints persisted strictly in isolated backtest DB
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, time as dt_time, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd

from app.backtesting.calendar_adapter import (
    CalendarUnavailableError,
    HistoricalMarketCalendarAdapter,
)
from app.backtesting.configuration import (
    BacktestConfiguration,
    IST_ZONE,
    normalize_instrument,
    normalize_timeframe,
    verify_index_governance,
)
from app.backtesting.cost_model import (
    SyntheticOptionCostConfig,
    UnderlyingPointsCostConfig,
    VersionedCostCalculator,
)
from app.backtesting.data_integrity import (
    DataIntegrityAuditor,
    compute_dataset_fingerprint,
)
from app.backtesting.data_store import HistoricalDataStore
from app.backtesting.fill_engine import (
    CompletedBar,
    apply_adverse_slippage_and_tick,
    evaluate_entry_candidate_on_bar,
    evaluate_exit_triggers_on_bar,
    extract_completed_bars,
    mark_to_market_price_on_bar,
    price_synthetic_bs_option,
)
from app.backtesting.models import (
    CalendarStatus,
    ExecutionSimulatorDesignSpec,
    IntegrityStatus,
    ReplayRunRecord,
)
from app.backtesting.portfolio_ledger import PortfolioLedger
from app.backtesting.position_manager import (
    MutableTradePosition,
    compute_partial_exit_quantity,
    compute_required_capital_reserve,
    quantity_unit_label_for_config,
    validate_signal_for_mode,
)
from app.backtesting.simulation_models import (
    AccountingUnitMode,
    AmbiguityPolicy,
    CostScheduleVersion,
    ExitReason,
    FillRecord,
    GapPolicy,
    OrderRecord,
    OrderSide,
    OrderStatus,
    PortfolioSummary,
    ReconciliationReport,
    SignalDirection,
    SimulationConfiguration,
    SimulationMode,
    SimulationRunResult,
    SimulationSignal,
    SimulationStatus,
    SyntheticBSAssumptions,
    TradeLifecycleState,
    TradeRecord,
    TriggerPriceDomain,
)
from app.backtesting.trade_lifecycle import deterministic_id, validate_trade_transition


PROVENANCE_BY_MODE: Dict[SimulationMode, str] = {
    SimulationMode.UNDERLYING_POINTS_ONLY: "UNDERLYING_INDEX_POINTS_ONLY",
    SimulationMode.SYNTHETIC_BS_RESEARCH: "SYNTHETIC_MODELLED_OPTION_PNL",
}


def resolve_provenance_label(config: SimulationConfiguration) -> str:
    um = config.accounting_unit_mode
    if um == AccountingUnitMode.INDEX_POINTS_ONLY:
        return "UNDERLYING_INDEX_POINTS_ONLY"
    if um == AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR:
        return "UNDERLYING_INDEX_POINTS_WITH_EXPLICIT_INR_MULTIPLIER"
    return "SYNTHETIC_MODELLED_OPTION_PNL"


def build_signals_from_replay_run(
    replay_run: ReplayRunRecord,
    *,
    candles_df: pd.DataFrame,
    timeframe: str,
    mode: SimulationMode,
    stop_loss_points: float,
    target_1_points: float,
    target_2_points: Optional[float] = None,
    quantity_units: int = 1,
    ce_assumptions: Optional[SyntheticBSAssumptions] = None,
    pe_assumptions: Optional[SyntheticBSAssumptions] = None,
    intraday_square_off: bool = True,
) -> List[SimulationSignal]:
    """
    Deterministic bridge adapter translating Step 4.2 MTF alignment points
    (`BULLISH_ALIGNMENT` / `BEARISH_ALIGNMENT`) into explicit rule-parameterized
    `SimulationSignal` inputs without embedding strategy heuristics inside Phase 3.
    """
    norm_tf = normalize_timeframe(timeframe)
    bars = extract_completed_bars(candles_df, timeframe=norm_tf)
    bar_by_close = {b.close_time_ist: b for b in bars}
    signals: List[SimulationSignal] = []

    for pt in replay_run.points:
        align = pt.overall_alignment
        if align not in ("BULLISH_ALIGNMENT", "BEARISH_ALIGNMENT"):
            continue
        as_of_ist = datetime.fromisoformat(pt.as_of_time_ist).astimezone(IST_ZONE)
        # Reference spot strictly from latest completed candle closed <= as_of_ist
        eligible_closed = [b for b in bars if b.close_time_ist <= as_of_ist]
        if not eligible_closed:
            continue
        ref_bar = bar_by_close.get(as_of_ist, eligible_closed[-1])
        spot_ref = float(ref_bar.close)

        if mode == SimulationMode.UNDERLYING_POINTS_ONLY:
            is_bull = align == "BULLISH_ALIGNMENT"
            sl = spot_ref - stop_loss_points if is_bull else spot_ref + stop_loss_points
            t1 = spot_ref + target_1_points if is_bull else spot_ref - target_1_points
            t2 = (
                (spot_ref + target_2_points if is_bull else spot_ref - target_2_points)
                if target_2_points is not None
                else None
            )
            signals.append(
                SimulationSignal(
                    signal_id=f"SIG-{pt.report_id}",
                    instrument=replay_run.instrument,
                    timeframe=norm_tf,
                    signal_available_at_ist=as_of_ist,
                    direction=SignalDirection.LONG if is_bull else SignalDirection.SHORT,
                    trigger_domain=TriggerPriceDomain.UNDERLYING_POINTS,
                    stop_loss=round(sl, 4),
                    target_1=round(t1, 4),
                    target_2=round(t2, 4) if t2 is not None else None,
                    quantity_units=quantity_units,
                    intraday_square_off=intraday_square_off,
                    source_report_id=pt.report_id,
                    notes=f"Step 4.2 alignment={align}",
                )
            )
        else:
            assumptions = ce_assumptions if align == "BULLISH_ALIGNMENT" else pe_assumptions
            if assumptions is None:
                continue
            exp_ist = assumptions.expiry_datetime_ist.astimezone(IST_ZONE)
            if exp_ist <= as_of_ist:
                continue
            prem_ref = price_synthetic_bs_option(
                spot=spot_ref,
                strike=assumptions.strike_price,
                valuation_time_ist=as_of_ist,
                expiry_datetime_ist=exp_ist,
                risk_free_rate=assumptions.risk_free_rate,
                dividend_yield=assumptions.dividend_yield,
                implied_volatility=assumptions.implied_volatility,
                option_type=assumptions.option_type,
            )
            sl_p = max(0.05, round(prem_ref - stop_loss_points, 2))
            t1_p = round(prem_ref + target_1_points, 2)
            t2_p = round(prem_ref + target_2_points, 2) if target_2_points is not None else None
            signals.append(
                SimulationSignal(
                    signal_id=f"SIG-{pt.report_id}",
                    instrument=replay_run.instrument,
                    timeframe=norm_tf,
                    signal_available_at_ist=as_of_ist,
                    direction=SignalDirection.LONG,
                    trigger_domain=TriggerPriceDomain.SYNTHETIC_OPTION_PREMIUM,
                    stop_loss=sl_p,
                    target_1=t1_p,
                    target_2=t2_p,
                    quantity_units=assumptions.lot_size * assumptions.lots,
                    intraday_square_off=intraday_square_off,
                    synthetic_bs_assumptions=assumptions,
                    source_report_id=pt.report_id,
                    notes=f"Step 4.2 alignment={align} -> synthetic BS {assumptions.option_type}",
                )
            )
    return signals


class HistoricalExecutionSimulator:
    """
    Isolated, deterministic, event-driven Step 4.3 historical execution simulator.
    """

    def __init__(
        self,
        *,
        config: SimulationConfiguration,
        backtest_config: Optional[BacktestConfiguration] = None,
        data_store: Optional[HistoricalDataStore] = None,
        calendar_adapter: Optional[HistoricalMarketCalendarAdapter] = None,
        points_cost_config: Optional[UnderlyingPointsCostConfig] = None,
        option_cost_config: Optional[SyntheticOptionCostConfig] = None,
    ) -> None:
        self.config = config
        self.backtest_config = backtest_config or BacktestConfiguration(
            sensex_governance_approved=config.sensex_governance_approved,
            **(
                {"storage_db_path": config.storage_db_path}
                if config.storage_db_path is not None
                else {}
            ),
            **(
                {"governance_ledger_path": config.governance_ledger_path}
                if config.governance_ledger_path is not None
                else {}
            ),
        )
        self.calendar_adapter = calendar_adapter or HistoricalMarketCalendarAdapter()
        self.data_store = data_store or HistoricalDataStore(config=self.backtest_config)
        self.auditor = DataIntegrityAuditor(
            calendar_adapter=self.calendar_adapter,
            market_open_hhmm=self.backtest_config.market_open_hhmm,
            market_close_hhmm=self.backtest_config.market_close_hhmm,
            strict_missing_intervals=self.backtest_config.strict_missing_intervals,
            require_volume_column=self.backtest_config.require_volume_column,
        )
        # Enforce strict cost schedule isolation and points vs currency boundary
        self.cost_calculator = VersionedCostCalculator(
            mode=config.mode,
            points_cost_config=points_cost_config,
            option_cost_config=option_cost_config,
            monetary_accounting_enabled=config.effective_monetary_accounting_enabled,
            instrument_multiplier_inr_per_point=config.instrument_multiplier_inr_per_point,
            instrument_multiplier_documentation=config.instrument_multiplier_documentation,
        )

    def _make_ledger(self) -> PortfolioLedger:
        return PortfolioLedger(
            mode=self.config.mode,
            accounting_unit_mode=self.config.accounting_unit_mode,
            provenance_label=resolve_provenance_label(self.config),
            starting_capital_inr=self.config.effective_starting_capital_inr,
            instrument_multiplier_inr_per_point=self.config.instrument_multiplier_inr_per_point,
            instrument_multiplier_documentation=self.config.instrument_multiplier_documentation,
        )

    def _build_rejected_trade_record(
        self,
        *,
        trade_id: str,
        sig: SimulationSignal,
        instrument: str,
        timeframe: str,
        state: TradeLifecycleState,
        rejection_reason: str,
    ) -> TradeRecord:
        um = self.config.accounting_unit_mode
        prov = resolve_provenance_label(self.config)
        is_pts = um in (AccountingUnitMode.INDEX_POINTS_ONLY, AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR)
        is_inr = um in (AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR, AccountingUnitMode.SYNTHETIC_OPTION_INR_ONLY)
        return TradeRecord(
            trade_id=trade_id,
            signal_id=sig.signal_id,
            instrument=instrument,
            timeframe=timeframe,
            mode=self.config.mode,
            accounting_unit_mode=um,
            provenance_label=prov,
            is_synthetic_modelled=(self.config.mode == SimulationMode.SYNTHETIC_BS_RESEARCH),
            quantity_unit_label=quantity_unit_label_for_config(self.config),  # type: ignore[arg-type]
            instrument_multiplier_inr_per_point=self.config.instrument_multiplier_inr_per_point,
            instrument_multiplier_documentation=self.config.instrument_multiplier_documentation,
            direction=sig.direction,
            state=state,
            signal_available_at_ist=sig.signal_available_at_ist.astimezone(IST_ZONE).isoformat(),
            initial_quantity=sig.quantity_units,
            remaining_quantity=0,
            stop_loss=sig.stop_loss,
            target_1=sig.target_1,
            target_2=sig.target_2,
            gross_points=0.0 if is_pts else None,
            slippage_points=0.0 if is_pts else None,
            net_points=0.0 if is_pts else None,
            unrealized_points=0.0 if is_pts else None,
            reserved_capital_inr=0.0 if is_inr else None,
            gross_pnl_inr=0.0 if is_inr else None,
            total_brokerage_and_statutory_inr=0.0 if is_inr else None,
            total_slippage_cost_inr=0.0 if is_inr else None,
            total_costs_inr=0.0 if is_inr else None,
            net_pnl_inr=0.0 if is_inr else None,
            unrealized_pnl_inr=0.0 if is_inr else None,
            synthetic_bs_assumptions=sig.synthetic_bs_assumptions,
            rejection_reason=rejection_reason,
        )

    def _build_locked_result(
        self,
        *,
        status: SimulationStatus,
        instrument: str,
        timeframe: str,
        reasons: Sequence[str],
        dataset_fingerprint: str = "",
        calendar_fingerprint: str = "",
        date_range: str = "",
        replay_run_id: Optional[str] = None,
        persist: bool = True,
    ) -> SimulationRunResult:
        prov = resolve_provenance_label(self.config)
        sched = self.cost_calculator.schedule_version()
        ledger = self._make_ledger()
        summary = ledger.summarize(total_signals=0, trades=[])
        recon = ledger.reconcile([])
        fp_payload = {
            "status": status.value,
            "mode": self.config.mode.value,
            "accounting_unit_mode": self.config.accounting_unit_mode.value,
            "instrument": instrument,
            "timeframe": timeframe,
            "reasons": list(reasons),
            "dataset_fingerprint": dataset_fingerprint,
            "calendar_fingerprint": calendar_fingerprint,
        }
        out_fp = hashlib.sha256(
            json.dumps(fp_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:32].upper()
        run_id = deterministic_id("SIM", out_fp, self.config.simulator_version)
        res = SimulationRunResult(
            run_id=run_id,
            output_fingerprint=out_fp,
            status=status,
            mode=self.config.mode,
            accounting_unit_mode=self.config.accounting_unit_mode,
            provenance_label=prov,
            is_synthetic_modelled=(self.config.mode == SimulationMode.SYNTHETIC_BS_RESEARCH),
            instrument=instrument,
            timeframe=timeframe,
            historical_date_range=date_range,
            dataset_fingerprint=dataset_fingerprint,
            calendar_fingerprint=calendar_fingerprint,
            replay_run_id=replay_run_id,
            simulator_version=self.config.simulator_version,
            cost_schedule=sched,
            ambiguity_policy=self.config.ambiguity_policy,
            gap_policy=self.config.gap_policy,
            portfolio=summary,
            reconciliation=recon,
            failure_reasons=tuple(dict.fromkeys(reasons)),
            created_at_utc=datetime.now(timezone.utc),
        )
        if persist:
            self.data_store.save_simulation_run(res)
        return res

    def _validate_calendar_dates(self, dates: Sequence[Any]) -> List[str]:
        """Validates unique IST dates against HistoricalMarketCalendarAdapter."""
        cal_errors: List[str] = []
        seen_dates = set()
        for d in dates:
            if d in seen_dates:
                continue
            seen_dates.add(d)
            try:
                cal_res = self.calendar_adapter.validate_date(d)
                if cal_res.status != CalendarStatus.TRADING_DAY or not cal_res.is_valid:
                    cal_errors.append(f"{d.isoformat()}: {cal_res.reason}")
            except CalendarUnavailableError as exc:
                cal_errors.append(f"{d.isoformat()}: {exc}")
        return cal_errors

    def run_simulation(
        self,
        *,
        instrument: str,
        timeframe: str,
        signals: Sequence[SimulationSignal],
        start_time_ist: Optional[datetime] = None,
        end_time_ist: Optional[datetime] = None,
        candles_df: Optional[pd.DataFrame] = None,
        replay_run_id: Optional[str] = None,
        persist: bool = True,
    ) -> SimulationRunResult:
        """
        Executes chronological event-driven simulation over verified historical bars.
        Fails closed cleanly on unsupported index, SENSEX lockout, unverified calendar,
        corrupted/incomplete candles, or missing data.
        """
        norm_inst = normalize_instrument(instrument)
        norm_tf = normalize_timeframe(timeframe)
        prov = resolve_provenance_label(self.config)
        cal_fp = self.calendar_adapter.calendar_fingerprint()

        # 1. Governance check (SENSEX fail-closed unless cryptographically authorized + opted in)
        eval_date = (end_time_ist or datetime.now(IST_ZONE)).astimezone(IST_ZONE).date()
        gov_ok, gov_status, gov_info = verify_index_governance(
            norm_inst,
            sensex_governance_approved=self.config.sensex_governance_approved,
            governance_db_path=self.backtest_config.governance_ledger_path,
            evaluation_date=eval_date,
        )
        if not gov_ok:
            return self._build_locked_result(
                status=SimulationStatus.GOVERNANCE_LOCKOUT,
                instrument=norm_inst,
                timeframe=norm_tf,
                reasons=[f"{gov_status}: {gov_info.get('reason')}"],
                calendar_fingerprint=cal_fp,
                replay_run_id=replay_run_id,
                persist=persist,
            )

        # 2. Acquire verified OHLCV data (no silent timeframe fallback, no synthetic generation)
        if candles_df is None:
            loaded_df = self.data_store.load_candles(
                norm_inst,
                norm_tf,
                start_time_ist=start_time_ist,
                end_time_ist=end_time_ist,
            )
        else:
            loaded_df = candles_df

        if loaded_df is None or loaded_df.empty:
            return self._build_locked_result(
                status=SimulationStatus.BLOCKED,
                instrument=norm_inst,
                timeframe=norm_tf,
                reasons=[
                    f"MISSING_HISTORICAL_DATA: No verified '{norm_tf}' candles available for '{norm_inst}'."
                ],
                calendar_fingerprint=cal_fp,
                replay_run_id=replay_run_id,
                persist=persist,
            )

        # 2b. Verify exchange trading calendar for parseable IST bar dates before
        # DataIntegrityAuditor so unverified/non-trading calendar dates fail closed
        # cleanly with LOCKED_OUT consistently with DeterministicReplayRunner.
        if isinstance(loaded_df, pd.DataFrame) and "timestamp" in loaded_df.columns:
            parsed_pre_ts: List[datetime] = []
            parsed_pre_dates: List[Any] = []
            for raw_ts in loaded_df["timestamp"]:
                try:
                    ts_obj = pd.to_datetime(raw_ts) if isinstance(raw_ts, str) else raw_ts
                    py_dt = ts_obj.to_pydatetime() if isinstance(ts_obj, pd.Timestamp) else ts_obj
                    if getattr(py_dt, "tzinfo", None) is not None and py_dt.tzinfo.utcoffset(py_dt) is not None:
                        ist_dt = py_dt.astimezone(IST_ZONE)
                        parsed_pre_ts.append(ist_dt)
                        parsed_pre_dates.append(ist_dt.date())
                except Exception:
                    # Leave malformed timestamps for DataIntegrityAuditor -> FAILED_INTEGRITY
                    continue

            pre_cal_errors = self._validate_calendar_dates(parsed_pre_dates)
            if pre_cal_errors:
                pre_date_range = (
                    f"{min(parsed_pre_dates).isoformat()}..{max(parsed_pre_dates).isoformat()}"
                    if parsed_pre_dates
                    else ""
                )
                pre_ds_fp = ""
                if len(parsed_pre_ts) == len(loaded_df):
                    try:
                        pre_ds_fp = compute_dataset_fingerprint(
                            loaded_df,
                            instrument=norm_inst,
                            timeframe=norm_tf,
                            timestamps_ist=parsed_pre_ts,
                        )
                    except Exception:
                        pre_ds_fp = ""
                return self._build_locked_result(
                    status=SimulationStatus.LOCKED_OUT,
                    instrument=norm_inst,
                    timeframe=norm_tf,
                    reasons=pre_cal_errors,
                    dataset_fingerprint=pre_ds_fp,
                    calendar_fingerprint=cal_fp,
                    date_range=pre_date_range,
                    replay_run_id=replay_run_id,
                    persist=persist,
                )

        # 3. Run strict DataIntegrityAuditor over full simulation dataset
        audit_report = self.auditor.audit_dataframe(
            loaded_df,
            instrument=norm_inst,
            timeframe=norm_tf,
            require_all_completed=True,
            check_missing_intervals=True,
        )
        if not audit_report.is_valid or audit_report.status != IntegrityStatus.PASSED:
            return self._build_locked_result(
                status=SimulationStatus.FAILED_INTEGRITY,
                instrument=norm_inst,
                timeframe=norm_tf,
                reasons=list(audit_report.rejected_reasons),
                dataset_fingerprint=audit_report.dataset_fingerprint,
                calendar_fingerprint=cal_fp,
                replay_run_id=replay_run_id,
                persist=persist,
            )

        try:
            bars: List[CompletedBar] = extract_completed_bars(
                loaded_df,
                timeframe=norm_tf,
                market_close_hhmm=self.backtest_config.market_close_hhmm,
            )
        except Exception as exc:
            return self._build_locked_result(
                status=SimulationStatus.FAILED_INTEGRITY,
                instrument=norm_inst,
                timeframe=norm_tf,
                reasons=[f"COMPLETED_BAR_EXTRACTION_FAILED: {exc}"],
                dataset_fingerprint=audit_report.dataset_fingerprint,
                calendar_fingerprint=cal_fp,
                replay_run_id=replay_run_id,
                persist=persist,
            )

        if not bars:
            return self._build_locked_result(
                status=SimulationStatus.BLOCKED,
                instrument=norm_inst,
                timeframe=norm_tf,
                reasons=["ZERO_COMPLETED_BARS_EXTRACTED"],
                calendar_fingerprint=cal_fp,
                replay_run_id=replay_run_id,
                persist=persist,
            )

        date_range = f"{bars[0].open_time_ist.date().isoformat()}..{bars[-1].open_time_ist.date().isoformat()}"

        # 4. Verify exchange trading calendar for all extracted bar dates
        cal_errors = self._validate_calendar_dates([b.open_time_ist.date() for b in bars])

        if cal_errors:
            return self._build_locked_result(
                status=SimulationStatus.LOCKED_OUT,
                instrument=norm_inst,
                timeframe=norm_tf,
                reasons=cal_errors,
                dataset_fingerprint=audit_report.dataset_fingerprint,
                calendar_fingerprint=cal_fp,
                date_range=date_range,
                replay_run_id=replay_run_id,
                persist=persist,
            )

        # 5. Pre-validate signals deterministically & fail closed if ANY mixed-mode violation appears
        sorted_signals = sorted(
            signals,
            key=lambda s: (s.signal_available_at_ist.astimezone(IST_ZONE), s.signal_id),
        )
        mode_violations: List[str] = []
        for sig in sorted_signals:
            err = validate_signal_for_mode(
                sig,
                mode=self.config.mode,
                expected_instrument=norm_inst,
                expected_timeframe=norm_tf,
            )
            if err is not None:
                mode_violations.append(f"{sig.signal_id}: {err}")
        if mode_violations:
            return self._build_locked_result(
                status=SimulationStatus.LOCKED_OUT,
                instrument=norm_inst,
                timeframe=norm_tf,
                reasons=mode_violations,
                dataset_fingerprint=audit_report.dataset_fingerprint,
                calendar_fingerprint=cal_fp,
                date_range=date_range,
                replay_run_id=replay_run_id,
                persist=persist,
            )

        # 6. Execute event-driven chronological simulation loop
        sq_h, sq_m = (int(p) for p in self.config.square_off_time_hhmm.split(":"))
        square_off_t = dt_time(sq_h, sq_m)
        um = self.config.accounting_unit_mode
        is_pts_domain = um in (
            AccountingUnitMode.INDEX_POINTS_ONLY,
            AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR,
        )
        is_mon_domain = self.config.effective_monetary_accounting_enabled
        qty_unit_lbl = quantity_unit_label_for_config(self.config)
        ledger = self._make_ledger()

        pending_wait: Dict[str, int] = {s.signal_id: 0 for s in sorted_signals}
        pending_signals: List[SimulationSignal] = list(sorted_signals)
        open_trades: List[MutableTradePosition] = []
        settled_rejected_trades: List[TradeRecord] = []
        closed_trades: List[TradeRecord] = []
        leg_counter = 0

        def next_leg_seq() -> int:
            nonlocal leg_counter
            leg_counter += 1
            return leg_counter

        def make_trade_id(sig: SimulationSignal) -> str:
            return deterministic_id("TRD", sig.signal_id, sig.signal_available_at_ist.isoformat(), self.config.mode.value)

        for bar_idx, bar in enumerate(bars):
            is_last_session_bar = (
                bar_idx == len(bars) - 1
                or bars[bar_idx + 1].open_time_ist.date() > bar.open_time_ist.date()
            )
            is_last_dataset_bar = bar_idx == len(bars) - 1

            # 6a. Evaluate pending entry signals whose available_at <= bar.open_time_ist (STRICT NO-LOOKAHEAD)
            still_pending: List[SimulationSignal] = []
            for sig in pending_signals:
                sig_ist = sig.signal_available_at_ist.astimezone(IST_ZONE)
                if bar.open_time_ist < sig_ist:
                    still_pending.append(sig)
                    continue

                t_id = make_trade_id(sig)
                if (not self.config.allow_overlapping_positions) and open_trades:
                    o_id = deterministic_id("ORD", t_id, "ENTRY_REJ", next_leg_seq())
                    rej_msg = "OVERLAPPING_POSITION_REJECTED"
                    ledger.all_orders.append(
                        OrderRecord(
                            order_id=o_id,
                            trade_id=t_id,
                            signal_id=sig.signal_id,
                            instrument=norm_inst,
                            timeframe=norm_tf,
                            mode=self.config.mode,
                            provenance_label=prov,
                            side=OrderSide.ENTRY,
                            direction=sig.direction,
                            quantity=sig.quantity_units,
                            status=OrderStatus.REJECTED,
                            signal_available_at_ist=sig_ist.isoformat(),
                            eligible_from_bar_open_ist=bar.open_time_ist.isoformat(),
                            limit_min=sig.entry_zone_min,
                            limit_max=sig.entry_zone_max,
                            rejection_reason=rej_msg,
                        )
                    )
                    settled_rejected_trades.append(
                        self._build_rejected_trade_record(
                            trade_id=t_id,
                            sig=sig,
                            instrument=norm_inst,
                            timeframe=norm_tf,
                            state=TradeLifecycleState.REJECTED,
                            rejection_reason=rej_msg,
                        )
                    )
                    continue

                should_enter, raw_entry, fail_reason = evaluate_entry_candidate_on_bar(
                    bar=bar,
                    signal=sig,
                    gap_policy=self.config.gap_policy,
                )
                if not should_enter:
                    reason_str = str(fail_reason or "ENTRY_CONDITIONS_NOT_MET")
                    if reason_str.startswith("WAIT:"):
                        pending_wait[sig.signal_id] += 1
                        if pending_wait[sig.signal_id] < sig.max_entry_wait_bars:
                            still_pending.append(sig)
                            continue
                        term_status = OrderStatus.EXPIRED
                        term_state = TradeLifecycleState.CANCELLED
                        final_rej = f"ENTRY_WAIT_EXPIRED:{reason_str}"
                    else:
                        term_status = OrderStatus.REJECTED
                        term_state = TradeLifecycleState.REJECTED
                        final_rej = reason_str

                    o_id = deterministic_id("ORD", t_id, "ENTRY_FAIL", next_leg_seq())
                    ledger.all_orders.append(
                        OrderRecord(
                            order_id=o_id,
                            trade_id=t_id,
                            signal_id=sig.signal_id,
                            instrument=norm_inst,
                            timeframe=norm_tf,
                            mode=self.config.mode,
                            provenance_label=prov,
                            side=OrderSide.ENTRY,
                            direction=sig.direction,
                            quantity=sig.quantity_units,
                            status=term_status,
                            signal_available_at_ist=sig_ist.isoformat(),
                            eligible_from_bar_open_ist=bar.open_time_ist.isoformat(),
                            limit_min=sig.entry_zone_min,
                            limit_max=sig.entry_zone_max,
                            rejection_reason=final_rej,
                        )
                    )
                    settled_rejected_trades.append(
                        self._build_rejected_trade_record(
                            trade_id=t_id,
                            sig=sig,
                            instrument=norm_inst,
                            timeframe=norm_tf,
                            state=term_state,
                            rejection_reason=final_rej,
                        )
                    )
                    continue

                assert raw_entry is not None
                eff_tick = (
                    sig.synthetic_bs_assumptions.tick_size
                    if sig.synthetic_bs_assumptions is not None
                    else self.config.tick_size
                )
                is_buy_entry = self.cost_calculator.is_buy_action(
                    direction=sig.direction,
                    side=OrderSide.ENTRY,
                )
                eff_entry_px, real_entry_slip = apply_adverse_slippage_and_tick(
                    raw_price=raw_entry,
                    slippage_per_unit=self.cost_calculator.slippage_per_unit,
                    is_buy=is_buy_entry,
                    tick_size=eff_tick,
                    enforce_tick_rounding=self.config.enforce_tick_rounding,
                )
                entry_costs = self.cost_calculator.calculate_leg_costs(
                    raw_reference_price=raw_entry,
                    quantity=sig.quantity_units,
                    initial_quantity=sig.quantity_units,
                    direction=sig.direction,
                    side=OrderSide.ENTRY,
                    slippage_applied_per_unit=real_entry_slip,
                )
                req_reserve_inr = compute_required_capital_reserve(
                    raw_entry_price=raw_entry,
                    quantity=sig.quantity_units,
                    config=self.config,
                )
                afford_ok, afford_reason = ledger.can_afford_entry(
                    required_reserve_inr=req_reserve_inr,
                    entry_costs_inr=entry_costs.total_costs_inr,
                    max_fraction=self.config.max_capital_fraction_per_trade,
                )
                if not afford_ok:
                    o_id = deterministic_id("ORD", t_id, "ENTRY_CAP_REJ", next_leg_seq())
                    ledger.all_orders.append(
                        OrderRecord(
                            order_id=o_id,
                            trade_id=t_id,
                            signal_id=sig.signal_id,
                            instrument=norm_inst,
                            timeframe=norm_tf,
                            mode=self.config.mode,
                            provenance_label=prov,
                            side=OrderSide.ENTRY,
                            direction=sig.direction,
                            quantity=sig.quantity_units,
                            status=OrderStatus.REJECTED,
                            signal_available_at_ist=sig_ist.isoformat(),
                            eligible_from_bar_open_ist=bar.open_time_ist.isoformat(),
                            limit_min=sig.entry_zone_min,
                            limit_max=sig.entry_zone_max,
                            rejection_reason=afford_reason,
                        )
                    )
                    settled_rejected_trades.append(
                        self._build_rejected_trade_record(
                            trade_id=t_id,
                            sig=sig,
                            instrument=norm_inst,
                            timeframe=norm_tf,
                            state=TradeLifecycleState.REJECTED,
                            rejection_reason=str(afford_reason),
                        )
                    )
                    continue

                seq = next_leg_seq()
                o_id = deterministic_id("ORD", t_id, "ENTRY", seq)
                f_id = deterministic_id("FIL", t_id, "ENTRY", seq)
                entry_ord = OrderRecord(
                    order_id=o_id,
                    trade_id=t_id,
                    signal_id=sig.signal_id,
                    instrument=norm_inst,
                    timeframe=norm_tf,
                    mode=self.config.mode,
                    provenance_label=prov,
                    side=OrderSide.ENTRY,
                    direction=sig.direction,
                    quantity=sig.quantity_units,
                    status=OrderStatus.FILLED,
                    signal_available_at_ist=sig_ist.isoformat(),
                    eligible_from_bar_open_ist=bar.open_time_ist.isoformat(),
                    executed_at_ist=bar.open_time_ist.isoformat(),
                    limit_min=sig.entry_zone_min,
                    limit_max=sig.entry_zone_max,
                )
                entry_fill = FillRecord(
                    fill_id=f_id,
                    order_id=o_id,
                    trade_id=t_id,
                    signal_id=sig.signal_id,
                    side=OrderSide.ENTRY,
                    mode=self.config.mode,
                    accounting_unit_mode=um,
                    provenance_label=prov,
                    bar_open_ist=bar.open_time_ist.isoformat(),
                    bar_close_ist=bar.close_time_ist.isoformat(),
                    executed_at_ist=bar.open_time_ist.isoformat(),
                    quantity=sig.quantity_units,
                    raw_reference_price=round(raw_entry, 6),
                    slippage_per_unit=real_entry_slip,
                    effective_fill_price=eff_entry_px,
                    underlying_spot_at_fill=bar.open,
                    gross_points_leg=0.0 if is_pts_domain else None,
                    slippage_points_leg=entry_costs.slippage_points_leg if is_pts_domain else None,
                    net_points_impact_leg=(
                        round(-(entry_costs.slippage_points_leg or 0.0), 6) if is_pts_domain else None
                    ),
                    gross_pnl_inr_leg=0.0 if is_mon_domain else None,
                    net_pnl_inr_impact_leg=(
                        round(-(entry_costs.total_costs_inr or 0.0), 4) if is_mon_domain else None
                    ),
                    costs=entry_costs,
                )
                validate_trade_transition(TradeLifecycleState.PENDING, TradeLifecycleState.OPEN)
                pos = MutableTradePosition(
                    trade_id=t_id,
                    signal=sig,
                    mode=self.config.mode,
                    accounting_unit_mode=um,
                    provenance_label=prov,
                    quantity_unit_label=qty_unit_lbl,
                    entry_bar_index=bar_idx,
                    entry_time_ist=bar.open_time_ist.isoformat(),
                    entry_price=round(raw_entry, 6),
                    initial_quantity=sig.quantity_units,
                    remaining_quantity=sig.quantity_units,
                    instrument_multiplier_inr_per_point=self.config.instrument_multiplier_inr_per_point,
                    instrument_multiplier_documentation=self.config.instrument_multiplier_documentation,
                    reserved_capital_inr=req_reserve_inr,
                )
                pos.record_entry_fill(entry_fill)
                ledger.all_orders.append(entry_ord)
                ledger.record_entry(required_reserve_inr=req_reserve_inr, entry_fill=entry_fill)
                open_trades.append(pos)

            pending_signals = still_pending

            # 6b. Evaluate open trades on current completed bar
            still_open: List[MutableTradePosition] = []
            for trade in open_trades:
                exit_legs = evaluate_exit_triggers_on_bar(
                    trade_id=trade.trade_id,
                    bar=bar,
                    is_entry_bar=(trade.entry_bar_index == bar_idx),
                    signal=trade.signal,
                    remaining_qty=trade.remaining_quantity,
                    target_1_already_executed=trade.target_1_executed,
                    ambiguity_policy=self.config.ambiguity_policy,
                    square_off_time=square_off_t,
                    is_last_bar_of_session=is_last_session_bar,
                    is_last_bar_of_dataset=is_last_dataset_bar,
                )
                for leg in exit_legs:
                    if trade.remaining_quantity <= 0:
                        break
                    if leg.exit_fraction_type == "PARTIAL":
                        exit_qty = compute_partial_exit_quantity(
                            initial_quantity=trade.initial_quantity,
                            remaining_quantity=trade.remaining_quantity,
                            fraction=trade.signal.partial_exit_fraction,
                            signal=trade.signal,
                        )
                    else:
                        exit_qty = trade.remaining_quantity

                    order_side = (
                        OrderSide.EXIT
                        if exit_qty >= trade.remaining_quantity
                        else OrderSide.PARTIAL_EXIT
                    )
                    eff_tick = (
                        trade.signal.synthetic_bs_assumptions.tick_size
                        if trade.signal.synthetic_bs_assumptions is not None
                        else self.config.tick_size
                    )
                    is_buy_exit = self.cost_calculator.is_buy_action(
                        direction=trade.signal.direction,
                        side=order_side,
                    )
                    eff_exit_px, real_exit_slip = apply_adverse_slippage_and_tick(
                        raw_price=leg.raw_exit_price,
                        slippage_per_unit=self.cost_calculator.slippage_per_unit,
                        is_buy=is_buy_exit,
                        tick_size=eff_tick,
                        enforce_tick_rounding=self.config.enforce_tick_rounding,
                    )
                    exit_costs = self.cost_calculator.calculate_leg_costs(
                        raw_reference_price=leg.raw_exit_price,
                        quantity=exit_qty,
                        initial_quantity=trade.initial_quantity,
                        direction=trade.signal.direction,
                        side=order_side,
                        slippage_applied_per_unit=real_exit_slip,
                    )
                    delta_pts = (
                        (leg.raw_exit_price - trade.entry_price)
                        if trade.signal.direction == SignalDirection.LONG
                        else (trade.entry_price - leg.raw_exit_price)
                    )
                    gross_pts_leg: Optional[float] = None
                    slip_pts_leg: Optional[float] = None
                    net_pts_leg: Optional[float] = None
                    if is_pts_domain:
                        leg_weight = float(exit_qty) / float(trade.initial_quantity)
                        gross_pts_leg = round(delta_pts * leg_weight, 6)
                        slip_pts_leg = exit_costs.slippage_points_leg
                        net_pts_leg = round(gross_pts_leg - (slip_pts_leg or 0.0), 6)

                    gross_inr_leg: Optional[float] = None
                    net_inr_leg: Optional[float] = None
                    if is_mon_domain:
                        assert self.cost_calculator.inr_multiplier is not None
                        gross_inr_leg = round(
                            delta_pts * exit_qty * float(self.cost_calculator.inr_multiplier),
                            4,
                        )
                        net_inr_leg = round(gross_inr_leg - (exit_costs.total_costs_inr or 0.0), 4)

                    seq = next_leg_seq()
                    o_id = deterministic_id("ORD", trade.trade_id, order_side.value, seq)
                    f_id = deterministic_id("FIL", trade.trade_id, order_side.value, seq)

                    exec_ts_iso = (
                        bar.open_time_ist.isoformat()
                        if leg.exit_reason in (ExitReason.GAP_STOP_OUT, ExitReason.GAP_TARGET)
                        else bar.close_time_ist.isoformat()
                    )
                    exit_ord = OrderRecord(
                        order_id=o_id,
                        trade_id=trade.trade_id,
                        signal_id=trade.signal.signal_id,
                        instrument=norm_inst,
                        timeframe=norm_tf,
                        mode=self.config.mode,
                        provenance_label=prov,
                        side=order_side,
                        direction=trade.signal.direction,
                        quantity=exit_qty,
                        status=OrderStatus.FILLED,
                        signal_available_at_ist=trade.signal.signal_available_at_ist.isoformat(),
                        eligible_from_bar_open_ist=bar.open_time_ist.isoformat(),
                        executed_at_ist=exec_ts_iso,
                    )
                    exit_fill = FillRecord(
                        fill_id=f_id,
                        order_id=o_id,
                        trade_id=trade.trade_id,
                        signal_id=trade.signal.signal_id,
                        side=order_side,
                        mode=self.config.mode,
                        accounting_unit_mode=um,
                        provenance_label=prov,
                        bar_open_ist=bar.open_time_ist.isoformat(),
                        bar_close_ist=bar.close_time_ist.isoformat(),
                        executed_at_ist=exec_ts_iso,
                        quantity=exit_qty,
                        raw_reference_price=round(leg.raw_exit_price, 6),
                        slippage_per_unit=real_exit_slip,
                        effective_fill_price=eff_exit_px,
                        underlying_spot_at_fill=bar.open
                        if leg.exit_reason in (ExitReason.GAP_STOP_OUT, ExitReason.GAP_TARGET)
                        else bar.close,
                        gross_points_leg=gross_pts_leg,
                        slippage_points_leg=slip_pts_leg,
                        net_points_impact_leg=net_pts_leg,
                        gross_pnl_inr_leg=gross_inr_leg,
                        net_pnl_inr_impact_leg=net_inr_leg,
                        costs=exit_costs,
                        exit_reason=leg.exit_reason,
                        is_intrabar_ambiguous=leg.is_intrabar_ambiguous,
                        ambiguity_evidence=leg.ambiguity_evidence,
                    )
                    released_inr = trade.apply_exit_fill(
                        fill=exit_fill,
                        exit_qty=exit_qty,
                        exit_reason=leg.exit_reason,
                    )
                    ledger.all_orders.append(exit_ord)
                    ledger.record_exit(released_reserve_inr=released_inr, exit_fill=exit_fill)

                if trade.state == TradeLifecycleState.CLOSED:
                    closed_trades.append(trade.to_record())
                else:
                    mtm_px = mark_to_market_price_on_bar(bar=bar, signal=trade.signal)
                    trade.update_mark_to_market(
                        current_price=mtm_px,
                        inr_multiplier=self.cost_calculator.inr_multiplier,
                    )
                    still_open.append(trade)

            open_trades = still_open
            ledger.record_bar_snapshot(
                timestamp_ist=bar.close_time_ist.isoformat(),
                open_trades=open_trades,
            )

        # 6c. Expire unentered trailing signals whose signal_available_at fell after final bar
        for rem_sig in pending_signals:
            sig_ist = rem_sig.signal_available_at_ist.astimezone(IST_ZONE)
            t_id = make_trade_id(rem_sig)
            o_id = deterministic_id("ORD", t_id, "EXPIRED", next_leg_seq())
            rej_msg = "NO_ELIGIBLE_COMPLETED_FUTURE_BAR_AVAILABLE"
            ledger.all_orders.append(
                OrderRecord(
                    order_id=o_id,
                    trade_id=t_id,
                    signal_id=rem_sig.signal_id,
                    instrument=norm_inst,
                    timeframe=norm_tf,
                    mode=self.config.mode,
                    provenance_label=prov,
                    side=OrderSide.ENTRY,
                    direction=rem_sig.direction,
                    quantity=rem_sig.quantity_units,
                    status=OrderStatus.EXPIRED,
                    signal_available_at_ist=sig_ist.isoformat(),
                    rejection_reason=rej_msg,
                )
            )
            settled_rejected_trades.append(
                self._build_rejected_trade_record(
                    trade_id=t_id,
                    sig=rem_sig,
                    instrument=norm_inst,
                    timeframe=norm_tf,
                    state=TradeLifecycleState.CANCELLED,
                    rejection_reason=rej_msg,
                )
            )

        remaining_open_records = [t.to_record() for t in open_trades]
        all_trades = tuple(closed_trades + remaining_open_records + settled_rejected_trades)
        summary = ledger.summarize(total_signals=len(sorted_signals), trades=all_trades)
        reconciliation = ledger.reconcile(all_trades)

        if not reconciliation.reconciled:
            raise RuntimeError(
                f"PORTFOLIO_RECONCILIATION_FAILED: {'; '.join(reconciliation.failed_checks)}"
            )

        sched_ver = self.cost_calculator.schedule_version()
        det_payload = {
            "instrument": norm_inst,
            "timeframe": norm_tf,
            "mode": self.config.mode.value,
            "accounting_unit_mode": um.value,
            "provenance_label": prov,
            "simulator_version": self.config.simulator_version,
            "cost_model_version": sched_ver.cost_model_version,
            "dataset_fingerprint": audit_report.dataset_fingerprint,
            "calendar_fingerprint": cal_fp,
            "replay_run_id": replay_run_id,
            "ambiguity_policy": self.config.ambiguity_policy.value,
            "gap_policy": self.config.gap_policy.value,
            "portfolio": summary.model_dump(mode="json"),
            "trades": [t.model_dump(mode="json") for t in all_trades],
            "orders": [o.model_dump(mode="json") for o in ledger.all_orders],
            "equity_curve": [e.model_dump(mode="json") for e in ledger.equity_curve],
        }
        out_fp = hashlib.sha256(
            json.dumps(det_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:32].upper()
        run_id = deterministic_id("SIM", out_fp, norm_inst, norm_tf)

        result = SimulationRunResult(
            run_id=run_id,
            output_fingerprint=out_fp,
            status=SimulationStatus.COMPLETED,
            mode=self.config.mode,
            accounting_unit_mode=um,
            provenance_label=prov,
            is_synthetic_modelled=(self.config.mode == SimulationMode.SYNTHETIC_BS_RESEARCH),
            instrument=norm_inst,
            timeframe=norm_tf,
            historical_date_range=date_range,
            dataset_fingerprint=audit_report.dataset_fingerprint,
            calendar_fingerprint=cal_fp,
            replay_run_id=replay_run_id,
            simulator_version=self.config.simulator_version,
            cost_schedule=sched_ver,
            ambiguity_policy=self.config.ambiguity_policy,
            gap_policy=self.config.gap_policy,
            portfolio=summary,
            reconciliation=reconciliation,
            equity_curve=tuple(ledger.equity_curve),
            trades=all_trades,
            orders=tuple(ledger.all_orders),
            failure_reasons=(),
            created_at_utc=datetime.now(timezone.utc),
        )
        if persist:
            self.data_store.save_simulation_run(result)
        return result

    def simulate_from_replay(
        self,
        replay_run: ReplayRunRecord,
        design_spec: ExecutionSimulatorDesignSpec,
        *,
        timeframe: str = "5m",
        stop_loss_points: float = 25.0,
        target_1_points: float = 40.0,
        target_2_points: Optional[float] = 75.0,
        quantity_units: int = 1,
        ce_assumptions: Optional[SyntheticBSAssumptions] = None,
        pe_assumptions: Optional[SyntheticBSAssumptions] = None,
        candles_df: Optional[pd.DataFrame] = None,
        persist: bool = True,
    ) -> Dict[str, Any]:
        """
        Implements Step 4.2 `FutureExecutionSimulatorProtocol.simulate_from_replay`.
        Enforces strict prohibition of `REAL_OPTION_OHLC` because verified historical
        option bid/ask & expired-contract OHLC data are unavailable.
        """
        if self.config.mode == SimulationMode.UNDERLYING_POINTS_ONLY:
            if design_spec.simulation_domain.value != "UNDERLYING_POINTS_ONLY":
                return self._build_locked_result(
                    status=SimulationStatus.LOCKED_OUT,
                    instrument=replay_run.instrument,
                    timeframe=normalize_timeframe(timeframe),
                    reasons=["DESIGN_SPEC_DOMAIN_MISMATCH: expected UNDERLYING_POINTS_ONLY."],
                    replay_run_id=replay_run.run_id,
                    persist=persist,
                ).model_dump(mode="json")
        else:
            if design_spec.option_data_mode is None:
                return self._build_locked_result(
                    status=SimulationStatus.LOCKED_OUT,
                    instrument=replay_run.instrument,
                    timeframe=normalize_timeframe(timeframe),
                    reasons=["OPTION_DATA_MODE_REQUIRED_FOR_SYNTHETIC_BS"],
                    replay_run_id=replay_run.run_id,
                    persist=persist,
                ).model_dump(mode="json")
            if design_spec.option_data_mode.value == "REAL_OPTION_OHLC":
                return self._build_locked_result(
                    status=SimulationStatus.BLOCKED,
                    instrument=replay_run.instrument,
                    timeframe=normalize_timeframe(timeframe),
                    reasons=[
                        "REAL_OPTION_OHLC_UNAVAILABLE: Historical option bid/ask and expired-contract OHLC datasets are not available."
                    ],
                    replay_run_id=replay_run.run_id,
                    persist=persist,
                ).model_dump(mode="json")

        norm_tf = normalize_timeframe(timeframe)
        source_df = (
            candles_df
            if candles_df is not None
            else self.data_store.load_candles(replay_run.instrument, norm_tf)
        )
        if source_df is None or source_df.empty:
            return self._build_locked_result(
                status=SimulationStatus.BLOCKED,
                instrument=replay_run.instrument,
                timeframe=norm_tf,
                reasons=[f"MISSING_HISTORICAL_DATA: No stored '{norm_tf}' bars for {replay_run.instrument}."],
                replay_run_id=replay_run.run_id,
                persist=persist,
            ).model_dump(mode="json")

        signals = build_signals_from_replay_run(
            replay_run,
            candles_df=source_df,
            timeframe=norm_tf,
            mode=self.config.mode,
            stop_loss_points=stop_loss_points,
            target_1_points=target_1_points,
            target_2_points=target_2_points,
            quantity_units=quantity_units,
            ce_assumptions=ce_assumptions,
            pe_assumptions=pe_assumptions,
        )
        res = self.run_simulation(
            instrument=replay_run.instrument,
            timeframe=norm_tf,
            signals=signals,
            candles_df=source_df,
            replay_run_id=replay_run.run_id,
            persist=persist,
        )
        return res.model_dump(mode="json")

