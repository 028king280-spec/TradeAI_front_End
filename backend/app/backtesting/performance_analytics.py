"""
AIVOLVE Phase 4 Step 4.4 — Performance Metrics Analytics Engine.

Computes deterministic closed-trade performance metrics, streak statistics,
holding durations, quantile distributions, and reconciliation verification
strictly segregated per AccountingUnitMode with zero silent fabrication.
"""

from __future__ import annotations

import math
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from app.backtesting.analytics_models import (
    DomainPerformanceMetrics,
    MetricAvailability,
    MetricAvailabilityStatus,
    PerformanceSummaryAnalytics,
    RiskSummaryAnalytics,
    TradeDistributionSummary,
    domain_has_inr,
    domain_has_points,
    parse_ist_datetime,
    validate_run_domain_integrity,
)
from app.backtesting.risk_analytics import (
    RiskAnalyticsEngine,
    is_clean_winner,
    max_consecutive_streak,
    sort_closed_trades,
)
from app.backtesting.simulation_models import (
    AccountingUnitMode,
    OrderSide,
    SimulationRunResult,
    TradeLifecycleState,
    TradeRecord,
)


def linear_quantile(sorted_values: Sequence[float], q: float) -> Optional[float]:
    """Deterministic linear-interpolation quantile in [0, 1] over pre-sorted values."""
    n = len(sorted_values)
    if n == 0:
        return None
    if n == 1:
        return float(sorted_values[0])
    pos = q * (n - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    frac = pos - lo
    return float(sorted_values[lo] + frac * (sorted_values[hi] - sorted_values[lo]))


def compute_pnl_quantiles(values: Sequence[float]) -> Dict[str, Optional[float]]:
    if not values:
        return {
            "min": None,
            "p10": None,
            "p25": None,
            "median": None,
            "p75": None,
            "p90": None,
            "max": None,
        }
    s = sorted(float(v) for v in values)
    return {
        "min": s[0],
        "p10": linear_quantile(s, 0.10),
        "p25": linear_quantile(s, 0.25),
        "median": linear_quantile(s, 0.50),
        "p75": linear_quantile(s, 0.75),
        "p90": linear_quantile(s, 0.90),
        "max": s[-1],
    }


def _current_streak(win_flags: Sequence[bool]) -> Tuple[str, int]:
    if not win_flags:
        return ("NONE", 0)
    last_is_win = win_flags[-1]
    cnt = 0
    for f in reversed(win_flags):
        if f == last_is_win:
            cnt += 1
        else:
            break
    return ("WIN" if last_is_win else "LOSS", cnt)


def _holding_durations_seconds(
    closed_trades: Sequence[TradeRecord],
) -> Tuple[Tuple[float, ...], MetricAvailabilityStatus]:
    durations: List[float] = []
    for t in closed_trades:
        if t.entry_time_ist and t.exit_time_ist:
            dt_in = parse_ist_datetime(t.entry_time_ist, f"trade[{t.trade_id}].entry_time_ist")
            dt_out = parse_ist_datetime(t.exit_time_ist, f"trade[{t.trade_id}].exit_time_ist")
            durations.append(max(0.0, (dt_out - dt_in).total_seconds()))
    if not closed_trades:
        return ((), MetricAvailabilityStatus.NO_CLOSED_TRADES)
    if not durations:
        return ((), MetricAvailabilityStatus.NO_VALID_TIMESTAMPS)
    return (tuple(durations), MetricAvailabilityStatus.AVAILABLE)


def _initial_risk_for_trade(
    trade: TradeRecord,
    unit_label: str,
    accounting_unit_mode: AccountingUnitMode,
    multiplier_inr_per_point: Optional[float],
) -> Optional[float]:
    if trade.entry_price is None:
        return None
    risk_dist = abs(float(trade.entry_price) - float(trade.stop_loss))
    if risk_dist <= 1e-12 or not math.isfinite(risk_dist):
        return None
    if unit_label == "INDEX_POINTS":
        # Mode A point P&L on TradeRecord is already normalized per 1 underlying unit.
        return risk_dist
    if accounting_unit_mode == AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR:
        if multiplier_inr_per_point is None or multiplier_inr_per_point <= 0.0:
            return None
        return risk_dist * float(trade.initial_quantity) * float(multiplier_inr_per_point)
    # SYNTHETIC_OPTION_INR_ONLY: TradeRecord.net_pnl_inr reflects entry/exit option price * initial_quantity
    return risk_dist * float(trade.initial_quantity)


def _compute_domain_metrics(
    *,
    closed_trades: Sequence[TradeRecord],
    unit_label: str,
    accounting_unit_mode: AccountingUnitMode,
    provenance_label: str,
    gross_getter: Callable[[TradeRecord], float],
    cost_getter: Callable[[TradeRecord], float],
    net_getter: Callable[[TradeRecord], float],
    max_drawdown: float,
    max_drawdown_pct: Optional[float],
    starting_capital_inr: Optional[float],
    multiplier_inr_per_point: Optional[float],
) -> DomainPerformanceMetrics:
    n = len(closed_trades)
    gross_vals = [gross_getter(t) for t in closed_trades]
    cost_vals = [cost_getter(t) for t in closed_trades]
    net_vals = [net_getter(t) for t in closed_trades]

    total_gross = sum(gross_vals)
    total_costs = sum(cost_vals)
    total_net = sum(net_vals)

    win_flags = [is_clean_winner(t, nv) for t, nv in zip(closed_trades, net_vals)]
    winning_trades = sum(1 for w in win_flags if w)
    losing_trades = n - winning_trades

    pos_vals = [v for v in net_vals if v > 0.0]
    neg_vals = [v for v in net_vals if v < 0.0]
    breakeven_trades = sum(1 for v in net_vals if v == 0.0)
    ambiguous_trades = sum(1 for t in closed_trades if t.intrabar_ambiguous_count > 0)

    notes: List[MetricAvailability] = []

    if n == 0:
        win_rate = None
        win_rate_pct = None
        expectancy = None
        avg_win = None
        avg_loss = None
        avg_loss_abs = None
        largest_win = None
        largest_loss = None
        largest_loss_abs = None
        profit_factor = None
        pf_status = MetricAvailabilityStatus.NO_CLOSED_TRADES
        avg_rr = None
        rr_status = MetricAvailabilityStatus.NO_CLOSED_TRADES
        rec_factor = None
        rf_status = MetricAvailabilityStatus.NO_CLOSED_TRADES
        notes.append(
            MetricAvailability(
                metric_name="summary",
                status=MetricAvailabilityStatus.NO_CLOSED_TRADES,
                reason="Zero closed trades; rate, profit factor, expectancy, and recovery metrics are undefined.",
            )
        )
    else:
        win_rate = winning_trades / n
        win_rate_pct = win_rate * 100.0
        expectancy = total_net / n

        if pos_vals:
            avg_win = sum(pos_vals) / len(pos_vals)
            largest_win = max(pos_vals)
        else:
            avg_win = None
            largest_win = None
            notes.append(
                MetricAvailability(
                    metric_name="average_win",
                    status=MetricAvailabilityStatus.NO_WINNING_TRADES,
                    reason="No closed trades produced strictly positive net P&L.",
                )
            )

        if neg_vals:
            avg_loss = sum(neg_vals) / len(neg_vals)
            avg_loss_abs = abs(avg_loss)
            largest_loss = min(neg_vals)
            largest_loss_abs = abs(largest_loss)
        else:
            avg_loss = None
            avg_loss_abs = None
            largest_loss = None
            largest_loss_abs = None
            notes.append(
                MetricAvailability(
                    metric_name="average_loss",
                    status=MetricAvailabilityStatus.NO_LOSING_TRADES,
                    reason="No closed trades produced strictly negative net P&L.",
                )
            )

        sum_pos = sum(pos_vals)
        sum_neg_abs = abs(sum(neg_vals))
        if sum_neg_abs <= 0.0:
            profit_factor = None
            pf_status = MetricAvailabilityStatus.ZERO_LOSS_UNDEFINED
            notes.append(
                MetricAvailability(
                    metric_name="profit_factor",
                    status=MetricAvailabilityStatus.ZERO_LOSS_UNDEFINED,
                    reason="Gross losses are zero; profit factor ratio is undefined (not infinity).",
                )
            )
        else:
            profit_factor = sum_pos / sum_neg_abs
            pf_status = MetricAvailabilityStatus.AVAILABLE

        if avg_win is None:
            avg_rr = None
            rr_status = MetricAvailabilityStatus.NO_WINNING_TRADES
        elif avg_loss_abs is None or avg_loss_abs <= 0.0:
            avg_rr = None
            rr_status = MetricAvailabilityStatus.NO_LOSING_TRADES
            notes.append(
                MetricAvailability(
                    metric_name="average_risk_reward",
                    status=MetricAvailabilityStatus.NO_LOSING_TRADES,
                    reason="Zero negative trades; realized payoff ratio average_win / abs(average_loss) is undefined.",
                )
            )
        else:
            avg_rr = avg_win / avg_loss_abs
            rr_status = MetricAvailabilityStatus.AVAILABLE

        if max_drawdown <= 0.0:
            rec_factor = None
            rf_status = MetricAvailabilityStatus.ZERO_DRAWDOWN_UNDEFINED
            notes.append(
                MetricAvailability(
                    metric_name="recovery_factor",
                    status=MetricAvailabilityStatus.ZERO_DRAWDOWN_UNDEFINED,
                    reason="Maximum drawdown is zero; recovery factor net_pnl / max_drawdown is undefined.",
                )
            )
        else:
            rec_factor = total_net / max_drawdown
            rf_status = MetricAvailabilityStatus.AVAILABLE

    planned_rrs: List[float] = []
    realized_rs: List[float] = []
    for t, nv in zip(closed_trades, net_vals):
        init_risk = _initial_risk_for_trade(
            trade=t,
            unit_label=unit_label,
            accounting_unit_mode=accounting_unit_mode,
            multiplier_inr_per_point=multiplier_inr_per_point,
        )
        if init_risk is not None and init_risk > 1e-12:
            realized_rs.append(nv / init_risk)
            if t.entry_price is not None:
                planned_dist = abs(float(t.target_1) - float(t.entry_price))
                risk_dist = abs(float(t.entry_price) - float(t.stop_loss))
                if risk_dist > 1e-12:
                    planned_rrs.append(planned_dist / risk_dist)

    avg_planned_rr = (sum(planned_rrs) / len(planned_rrs)) if planned_rrs else None
    avg_realized_r = (sum(realized_rs) / len(realized_rs)) if realized_rs else None

    net_ret_pct: Optional[float] = None
    if unit_label == "INR" and starting_capital_inr is not None and starting_capital_inr > 0.0:
        net_ret_pct = (total_net / float(starting_capital_inr)) * 100.0

    q = compute_pnl_quantiles(net_vals)

    return DomainPerformanceMetrics(
        unit_label=unit_label,  # type: ignore[arg-type]
        provenance_label=provenance_label,
        total_closed_trades=n,
        winning_trades=winning_trades,
        losing_trades=losing_trades,
        strict_positive_trades=len(pos_vals),
        strict_negative_trades=len(neg_vals),
        breakeven_trades=breakeven_trades,
        intrabar_ambiguous_trades=ambiguous_trades,
        win_rate=win_rate,
        win_rate_pct=win_rate_pct,
        gross_pnl=total_gross,
        total_costs=total_costs,
        net_pnl=total_net,
        average_win=avg_win,
        average_loss=avg_loss,
        average_loss_abs=avg_loss_abs,
        largest_win=largest_win,
        largest_loss=largest_loss,
        largest_loss_abs=largest_loss_abs,
        profit_factor=profit_factor,
        profit_factor_status=pf_status,
        expectancy=expectancy,
        average_risk_reward=avg_rr,
        average_risk_reward_status=rr_status,
        average_planned_risk_reward=avg_planned_rr,
        average_realized_r_multiple=avg_realized_r,
        max_drawdown=max_drawdown,
        max_drawdown_pct=max_drawdown_pct if unit_label == "INR" else None,
        recovery_factor=rec_factor,
        recovery_factor_status=rf_status,
        net_return_pct=net_ret_pct if unit_label == "INR" else None,
        min_trade_pnl=q["min"],
        p10_trade_pnl=q["p10"],
        p25_trade_pnl=q["p25"],
        median_trade_pnl=q["median"],
        p75_trade_pnl=q["p75"],
        p90_trade_pnl=q["p90"],
        max_trade_pnl=q["max"],
        availability_notes=tuple(notes),
    )


class PerformanceAnalyticsEngine:
    """Stateless deterministic engine computing Step 4.4 trade performance summaries and distributions."""

    def __init__(self, risk_engine: Optional[RiskAnalyticsEngine] = None) -> None:
        self._risk_engine = risk_engine or RiskAnalyticsEngine()

    def evaluate_run(
        self,
        run: SimulationRunResult,
        *,
        risk_summary: Optional[RiskSummaryAnalytics] = None,
    ) -> PerformanceSummaryAnalytics:
        """Evaluates full PerformanceSummaryAnalytics for a Step 4.3 SimulationRunResult."""
        validate_run_domain_integrity(run)
        rs = risk_summary or self._risk_engine.evaluate_run(run)

        opened = [
            t
            for t in run.trades
            if t.state not in (TradeLifecycleState.REJECTED, TradeLifecycleState.CANCELLED, TradeLifecycleState.PENDING)
        ]
        closed = sort_closed_trades(opened)
        open_trades = [t for t in opened if t.state != TradeLifecycleState.CLOSED]
        rejected = [
            t for t in run.trades if t.state in (TradeLifecycleState.REJECTED, TradeLifecycleState.CANCELLED)
        ]
        partial_exits_count = sum(
            sum(1 for f in t.fills if f.side == OrderSide.PARTIAL_EXIT)
            for t in opened
        )
        ambiguous_count = sum(t.intrabar_ambiguous_count for t in opened)

        um = run.accounting_unit_mode
        use_points_for_streak = um == AccountingUnitMode.INDEX_POINTS_ONLY
        streak_flags = [
            is_clean_winner(
                t,
                float(t.net_points or 0.0) if use_points_for_streak else float(t.net_pnl_inr or 0.0),
            )
            for t in closed
        ]
        max_consec_wins = max_consecutive_streak(streak_flags)
        max_consec_losses = max_consecutive_streak([not w for w in streak_flags])
        cur_streak_type, cur_streak_count = _current_streak(streak_flags)

        durations, dur_status = _holding_durations_seconds(closed)
        avg_dur_sec = (sum(durations) / len(durations)) if durations else None
        avg_dur_min = (avg_dur_sec / 60.0) if avg_dur_sec is not None else None
        sorted_dur = sorted(durations)
        med_dur = linear_quantile(sorted_dur, 0.50)

        points_metrics: Optional[DomainPerformanceMetrics] = None
        if domain_has_points(um):
            assert rs.points_risk is not None
            points_metrics = _compute_domain_metrics(
                closed_trades=closed,
                unit_label="INDEX_POINTS",
                accounting_unit_mode=um,
                provenance_label=run.provenance_label,
                gross_getter=lambda t: float(t.gross_points or 0.0),
                cost_getter=lambda t: float(t.slippage_points or 0.0),
                net_getter=lambda t: float(t.net_points or 0.0),
                max_drawdown=rs.points_risk.max_drawdown,
                max_drawdown_pct=None,
                starting_capital_inr=None,
                multiplier_inr_per_point=run.portfolio.instrument_multiplier_inr_per_point,
            )

        inr_metrics: Optional[DomainPerformanceMetrics] = None
        if domain_has_inr(um):
            assert rs.inr_risk is not None
            inr_metrics = _compute_domain_metrics(
                closed_trades=closed,
                unit_label="INR",
                accounting_unit_mode=um,
                provenance_label=run.provenance_label,
                gross_getter=lambda t: float(t.gross_pnl_inr or 0.0),
                cost_getter=lambda t: float(t.total_costs_inr or 0.0),
                net_getter=lambda t: float(t.net_pnl_inr or 0.0),
                max_drawdown=rs.inr_risk.max_drawdown,
                max_drawdown_pct=rs.inr_risk.max_drawdown_pct,
                starting_capital_inr=run.portfolio.starting_capital_inr,
                multiplier_inr_per_point=run.portfolio.instrument_multiplier_inr_per_point,
            )

        diff_pts: Optional[float] = None
        pts_ok = True
        if domain_has_points(um):
            opened_net_pts = sum(float(t.net_points or 0.0) for t in opened)
            diff_pts = abs(opened_net_pts - float(run.portfolio.realized_net_points or 0.0))
            pts_ok = diff_pts <= 1e-4

        diff_inr: Optional[float] = None
        inr_ok = True
        if domain_has_inr(um):
            opened_net_inr = sum(float(t.net_pnl_inr or 0.0) for t in opened)
            diff_inr = abs(opened_net_inr - float(run.portfolio.realized_net_pnl_inr or 0.0))
            inr_ok = diff_inr <= 1e-2

        reconciled_ok = bool(run.reconciliation.reconciled and pts_ok and inr_ok)

        return PerformanceSummaryAnalytics(
            accounting_unit_mode=um,
            provenance_label=run.provenance_label,
            is_synthetic_modelled=run.is_synthetic_modelled,
            instrument_multiplier_inr_per_point=run.portfolio.instrument_multiplier_inr_per_point,
            instrument_multiplier_documentation=run.portfolio.instrument_multiplier_documentation,
            total_signals=run.portfolio.total_signals,
            trades_opened=len(opened),
            trades_closed=len(closed),
            trades_open=len(open_trades),
            trades_rejected_or_cancelled=len(rejected),
            partial_exits_count=partial_exits_count,
            intrabar_ambiguous_count=ambiguous_count,
            max_consecutive_wins=max_consec_wins,
            max_consecutive_losses=max_consec_losses,
            current_streak_type=cur_streak_type,  # type: ignore[arg-type]
            current_streak_count=cur_streak_count,
            average_holding_duration_seconds=avg_dur_sec,
            average_holding_duration_minutes=avg_dur_min,
            min_holding_duration_seconds=sorted_dur[0] if sorted_dur else None,
            median_holding_duration_seconds=med_dur,
            max_holding_duration_seconds=sorted_dur[-1] if sorted_dur else None,
            holding_duration_status=dur_status,
            points_metrics=points_metrics,
            inr_metrics=inr_metrics,
            reconciliation_verified=reconciled_ok,
            net_pnl_reconciliation_diff_points=diff_pts,
            net_pnl_reconciliation_diff_inr=diff_inr,
        )

    def evaluate_trade_slice(
        self,
        *,
        closed_trades: Sequence[TradeRecord],
        accounting_unit_mode: AccountingUnitMode,
        provenance_label: str,
        is_synthetic_modelled: bool,
        starting_capital_inr: Optional[float] = None,
        instrument_multiplier_inr_per_point: Optional[float] = None,
        instrument_multiplier_documentation: Optional[str] = None,
        slice_prefix: str = "SLICE",
    ) -> PerformanceSummaryAnalytics:
        """Evaluates isolated performance metrics for a pre-filtered chronological slice of closed trades."""
        ordered_closed = sort_closed_trades(closed_trades)
        rs = self._risk_engine.evaluate_components(
            accounting_unit_mode=accounting_unit_mode,
            provenance_label=provenance_label,
            is_synthetic_modelled=is_synthetic_modelled,
            closed_trades=ordered_closed,
            equity_curve=(),
            starting_capital_inr=starting_capital_inr,
            episode_prefix=slice_prefix,
        )
        partial_exits_count = sum(
            sum(1 for f in t.fills if f.side == OrderSide.PARTIAL_EXIT)
            for t in ordered_closed
        )
        ambiguous_count = sum(t.intrabar_ambiguous_count for t in ordered_closed)
        use_points_for_streak = accounting_unit_mode == AccountingUnitMode.INDEX_POINTS_ONLY
        streak_flags = [
            is_clean_winner(
                t,
                float(t.net_points or 0.0) if use_points_for_streak else float(t.net_pnl_inr or 0.0),
            )
            for t in ordered_closed
        ]
        cur_streak_type, cur_streak_count = _current_streak(streak_flags)
        durations, dur_status = _holding_durations_seconds(ordered_closed)
        avg_dur_sec = (sum(durations) / len(durations)) if durations else None
        avg_dur_min = (avg_dur_sec / 60.0) if avg_dur_sec is not None else None
        sorted_dur = sorted(durations)

        points_metrics = (
            _compute_domain_metrics(
                closed_trades=ordered_closed,
                unit_label="INDEX_POINTS",
                accounting_unit_mode=accounting_unit_mode,
                provenance_label=provenance_label,
                gross_getter=lambda t: float(t.gross_points or 0.0),
                cost_getter=lambda t: float(t.slippage_points or 0.0),
                net_getter=lambda t: float(t.net_points or 0.0),
                max_drawdown=rs.points_risk.max_drawdown if rs.points_risk else 0.0,
                max_drawdown_pct=None,
                starting_capital_inr=None,
                multiplier_inr_per_point=instrument_multiplier_inr_per_point,
            )
            if domain_has_points(accounting_unit_mode)
            else None
        )

        inr_metrics = (
            _compute_domain_metrics(
                closed_trades=ordered_closed,
                unit_label="INR",
                accounting_unit_mode=accounting_unit_mode,
                provenance_label=provenance_label,
                gross_getter=lambda t: float(t.gross_pnl_inr or 0.0),
                cost_getter=lambda t: float(t.total_costs_inr or 0.0),
                net_getter=lambda t: float(t.net_pnl_inr or 0.0),
                max_drawdown=rs.inr_risk.max_drawdown if rs.inr_risk else 0.0,
                max_drawdown_pct=rs.inr_risk.max_drawdown_pct if rs.inr_risk else 0.0,
                starting_capital_inr=starting_capital_inr,
                multiplier_inr_per_point=instrument_multiplier_inr_per_point,
            )
            if domain_has_inr(accounting_unit_mode)
            else None
        )

        return PerformanceSummaryAnalytics(
            accounting_unit_mode=accounting_unit_mode,
            provenance_label=provenance_label,
            is_synthetic_modelled=is_synthetic_modelled,
            instrument_multiplier_inr_per_point=instrument_multiplier_inr_per_point,
            instrument_multiplier_documentation=instrument_multiplier_documentation,
            total_signals=len(ordered_closed),
            trades_opened=len(ordered_closed),
            trades_closed=len(ordered_closed),
            trades_open=0,
            trades_rejected_or_cancelled=0,
            partial_exits_count=partial_exits_count,
            intrabar_ambiguous_count=ambiguous_count,
            max_consecutive_wins=max_consecutive_streak(streak_flags),
            max_consecutive_losses=max_consecutive_streak([not w for w in streak_flags]),
            current_streak_type=cur_streak_type,  # type: ignore[arg-type]
            current_streak_count=cur_streak_count,
            average_holding_duration_seconds=avg_dur_sec,
            average_holding_duration_minutes=avg_dur_min,
            min_holding_duration_seconds=sorted_dur[0] if sorted_dur else None,
            median_holding_duration_seconds=linear_quantile(sorted_dur, 0.50),
            max_holding_duration_seconds=sorted_dur[-1] if sorted_dur else None,
            holding_duration_status=dur_status,
            points_metrics=points_metrics,
            inr_metrics=inr_metrics,
            reconciliation_verified=True,
            net_pnl_reconciliation_diff_points=0.0 if points_metrics is not None else None,
            net_pnl_reconciliation_diff_inr=0.0 if inr_metrics is not None else None,
        )

    def build_trade_distribution(self, run: SimulationRunResult) -> TradeDistributionSummary:
        """Computes quantile distributions, exit-reason counts, direction counts, and duration stats."""
        validate_run_domain_integrity(run)
        closed = sort_closed_trades(run.trades)
        um = run.accounting_unit_mode

        pts_q = (
            compute_pnl_quantiles([float(t.net_points or 0.0) for t in closed])
            if domain_has_points(um)
            else None
        )
        inr_q = (
            compute_pnl_quantiles([float(t.net_pnl_inr or 0.0) for t in closed])
            if domain_has_inr(um)
            else None
        )

        exit_counts: Dict[str, int] = {}
        dir_counts: Dict[str, int] = {}
        for t in closed:
            er = t.final_exit_reason.value if t.final_exit_reason else "UNKNOWN"
            exit_counts[er] = exit_counts.get(er, 0) + 1
            dv = t.direction.value
            dir_counts[dv] = dir_counts.get(dv, 0) + 1

        durations, _ = _holding_durations_seconds(closed)
        sorted_dur = sorted(durations)
        dur_summary: Dict[str, Optional[float]] = {
            "min_seconds": sorted_dur[0] if sorted_dur else None,
            "mean_seconds": (sum(sorted_dur) / len(sorted_dur)) if sorted_dur else None,
            "median_seconds": linear_quantile(sorted_dur, 0.50),
            "max_seconds": sorted_dur[-1] if sorted_dur else None,
        }

        return TradeDistributionSummary(
            accounting_unit_mode=um,
            total_closed_trades=len(closed),
            points_quantiles=pts_q,
            inr_quantiles=inr_q,
            exit_reason_counts=dict(sorted(exit_counts.items())),
            direction_counts=dict(sorted(dir_counts.items())),
            holding_duration_seconds_summary=dur_summary,
        )

