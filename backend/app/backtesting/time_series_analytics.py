"""
AIVOLVE Phase 4 Step 4.4 — IST Time-Series Analytics Engine.

Aggregates closed trades strictly in Asia/Kolkata (IST) across daily, ISO weekly,
monthly, and canonical NSE/BSE session buckets, plus normalized IST equity curves.
Exports shared `build_bucket_domain_stats` reused by strategy analytics.
"""

from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from app.backtesting.analytics_models import (
    BucketDomainStats,
    DrawdownTimelinePoint,
    EquityCurveSnapshot,
    MarketSessionBucket,
    MetricAvailabilityStatus,
    TimeBucketPerformance,
    TimeSeriesAnalyticsResult,
    UNKNOWN_LABEL,
    classify_ist_session,
    domain_has_inr,
    domain_has_points,
    parse_ist_datetime,
    validate_run_domain_integrity,
)
from app.backtesting.risk_analytics import RiskAnalyticsEngine, is_clean_winner, sort_closed_trades
from app.backtesting.simulation_models import (
    AccountingUnitMode,
    OrderSide,
    SimulationRunResult,
    TradeLifecycleState,
    TradeRecord,
)

_SESSION_BOUNDS_LABEL: Dict[str, Tuple[str, str]] = {
    MarketSessionBucket.OPENING.value: ("09:15 IST", "09:45 IST"),
    MarketSessionBucket.MORNING.value: ("09:45 IST", "11:30 IST"),
    MarketSessionBucket.MIDDAY.value: ("11:30 IST", "13:30 IST"),
    MarketSessionBucket.AFTERNOON.value: ("13:30 IST", "14:45 IST"),
    MarketSessionBucket.CLOSING.value: ("14:45 IST", "15:30 IST"),
    MarketSessionBucket.OUTSIDE_REGULAR_SESSION.value: ("OUTSIDE", "OUTSIDE"),
    MarketSessionBucket.UNKNOWN.value: (UNKNOWN_LABEL, UNKNOWN_LABEL),
}

_SESSION_ORDER: Dict[str, int] = {
    MarketSessionBucket.OPENING.value: 0,
    MarketSessionBucket.MORNING.value: 1,
    MarketSessionBucket.MIDDAY.value: 2,
    MarketSessionBucket.AFTERNOON.value: 3,
    MarketSessionBucket.CLOSING.value: 4,
    MarketSessionBucket.OUTSIDE_REGULAR_SESSION.value: 5,
    MarketSessionBucket.UNKNOWN.value: 6,
}


def _single_domain_bucket_stats(
    trades: Sequence[TradeRecord],
    *,
    unit_label: str,
    provenance_label: str,
    gross_getter: Callable[[TradeRecord], float],
    cost_getter: Callable[[TradeRecord], float],
    net_getter: Callable[[TradeRecord], float],
) -> BucketDomainStats:
    n = len(trades)
    gross = sum(gross_getter(t) for t in trades)
    costs = sum(cost_getter(t) for t in trades)
    nets = [net_getter(t) for t in trades]
    net = sum(nets)

    winners = sum(1 for t, nv in zip(trades, nets) if is_clean_winner(t, nv))
    losers = n - winners
    pos_sum = sum(v for v in nets if v > 0.0)
    neg_abs_sum = abs(sum(v for v in nets if v < 0.0))

    if n == 0:
        win_rate = None
        expectancy = None
        pf = None
        pf_status = MetricAvailabilityStatus.NO_CLOSED_TRADES
    else:
        win_rate = winners / n
        expectancy = net / n
        if neg_abs_sum <= 0.0:
            pf = None
            pf_status = MetricAvailabilityStatus.ZERO_LOSS_UNDEFINED
        else:
            pf = pos_sum / neg_abs_sum
            pf_status = MetricAvailabilityStatus.AVAILABLE

    return BucketDomainStats(
        unit_label=unit_label,  # type: ignore[arg-type]
        provenance_label=provenance_label,
        winning_trades=winners,
        losing_trades=losers,
        win_rate=win_rate,
        gross_pnl=gross,
        total_costs=costs,
        net_pnl=net,
        expectancy=expectancy,
        profit_factor=pf,
        profit_factor_status=pf_status,
    )


def build_bucket_domain_stats(
    trades: Sequence[TradeRecord],
    *,
    accounting_unit_mode: AccountingUnitMode,
    provenance_label: str,
) -> Tuple[Optional[BucketDomainStats], Optional[BucketDomainStats]]:
    """Builds strictly segregated `(points_stats, inr_stats)` for any group of closed trades."""
    pts = (
        _single_domain_bucket_stats(
            trades,
            unit_label="INDEX_POINTS",
            provenance_label=provenance_label,
            gross_getter=lambda t: float(t.gross_points or 0.0),
            cost_getter=lambda t: float(t.slippage_points or 0.0),
            net_getter=lambda t: float(t.net_points or 0.0),
        )
        if domain_has_points(accounting_unit_mode)
        else None
    )
    inr = (
        _single_domain_bucket_stats(
            trades,
            unit_label="INR",
            provenance_label=provenance_label,
            gross_getter=lambda t: float(t.gross_pnl_inr or 0.0),
            cost_getter=lambda t: float(t.total_costs_inr or 0.0),
            net_getter=lambda t: float(t.net_pnl_inr or 0.0),
        )
        if domain_has_inr(accounting_unit_mode)
        else None
    )
    return pts, inr


def _bucket_trade_counts(trades: Sequence[TradeRecord]) -> Tuple[int, int]:
    partial_exits = sum(
        sum(1 for f in t.fills if f.side == OrderSide.PARTIAL_EXIT)
        for t in trades
    )
    ambiguous = sum(t.intrabar_ambiguous_count for t in trades)
    return partial_exits, ambiguous


def _iso_week_key_and_bounds(d_ist: date) -> Tuple[str, str, str]:
    iso_year, iso_week, _ = d_ist.isocalendar()
    key = f"{iso_year:04d}-W{iso_week:02d}"
    monday = d_ist - timedelta(days=d_ist.weekday())
    sunday = monday + timedelta(days=6)
    return key, monday.isoformat(), sunday.isoformat()


def _month_key_and_bounds(d_ist: date) -> Tuple[str, str, str]:
    key = f"{d_ist.year:04d}-{d_ist.month:02d}"
    last_day = calendar.monthrange(d_ist.year, d_ist.month)[1]
    start = date(d_ist.year, d_ist.month, 1).isoformat()
    end = date(d_ist.year, d_ist.month, last_day).isoformat()
    return key, start, end


def _aggregate_time_buckets(
    closed_trades: Sequence[TradeRecord],
    *,
    bucket_type: str,
    accounting_unit_mode: AccountingUnitMode,
    provenance_label: str,
    key_fn: Callable[[TradeRecord], Tuple[str, str, str]],
    sort_key_fn: Optional[Callable[[str], object]] = None,
) -> Tuple[TimeBucketPerformance, ...]:
    grouped: Dict[str, List[TradeRecord]] = defaultdict(list)
    bounds: Dict[str, Tuple[str, str]] = {}
    for t in closed_trades:
        key, p_start, p_end = key_fn(t)
        grouped[key].append(t)
        bounds[key] = (p_start, p_end)

    keys = sorted(grouped.keys(), key=sort_key_fn) if sort_key_fn else sorted(grouped.keys())
    rows: List[TimeBucketPerformance] = []
    for k in keys:
        group = grouped[k]
        partial_exits, ambiguous = _bucket_trade_counts(group)
        pts_stats, inr_stats = build_bucket_domain_stats(
            group,
            accounting_unit_mode=accounting_unit_mode,
            provenance_label=provenance_label,
        )
        p_start, p_end = bounds[k]
        rows.append(
            TimeBucketPerformance(
                bucket_type=bucket_type,  # type: ignore[arg-type]
                bucket_key=k,
                period_start_ist=p_start,
                period_end_ist=p_end,
                accounting_unit_mode=accounting_unit_mode,
                provenance_label=provenance_label,
                trades_count=len(group),
                partial_exits_count=partial_exits,
                ambiguous_trades_count=ambiguous,
                points_stats=pts_stats,
                inr_stats=inr_stats,
            )
        )
    return tuple(rows)


def _exit_dt_ist(trade: TradeRecord) -> datetime:
    ts = trade.exit_time_ist or trade.entry_time_ist or trade.signal_available_at_ist
    return parse_ist_datetime(ts, f"trade[{trade.trade_id}].exit_time_ist")


def _session_key_and_bounds(trade: TradeRecord) -> Tuple[str, str, str]:
    if not trade.entry_time_ist:
        s_val = MarketSessionBucket.UNKNOWN.value
    else:
        dt_in = parse_ist_datetime(trade.entry_time_ist, f"trade[{trade.trade_id}].entry_time_ist")
        s_val = classify_ist_session(dt_in).value
    bounds = _SESSION_BOUNDS_LABEL[s_val]
    return s_val, bounds[0], bounds[1]


def _buckets_conserve_net(
    buckets: Sequence[TimeBucketPerformance],
    *,
    expected_points: Optional[float],
    expected_inr: Optional[float],
) -> bool:
    if expected_points is not None:
        s_pts = sum(float(b.points_stats.net_pnl) for b in buckets if b.points_stats is not None)
        if abs(s_pts - expected_points) > 1e-4:
            return False
    if expected_inr is not None:
        s_inr = sum(float(b.inr_stats.net_pnl) for b in buckets if b.inr_stats is not None)
        if abs(s_inr - expected_inr) > 1e-2:
            return False
    return True


class TimeSeriesAnalyticsEngine:
    """Stateless deterministic IST time-series aggregator and curve normalizer."""

    def __init__(self, risk_engine: Optional[RiskAnalyticsEngine] = None) -> None:
        self._risk_engine = risk_engine or RiskAnalyticsEngine()

    def evaluate_run(
        self,
        run: SimulationRunResult,
        *,
        drawdown_timeline: Optional[Tuple[DrawdownTimelinePoint, ...]] = None,
    ) -> TimeSeriesAnalyticsResult:
        """Produces daily/weekly/monthly/session IST aggregations and normalized equity snapshots."""
        validate_run_domain_integrity(run)
        um = run.accounting_unit_mode
        closed = sort_closed_trades(run.trades)
        unclosed_count = sum(
            1
            for t in run.trades
            if t.state not in (TradeLifecycleState.CLOSED, TradeLifecycleState.REJECTED, TradeLifecycleState.CANCELLED)
        )

        daily = _aggregate_time_buckets(
            closed,
            bucket_type="DAILY",
            accounting_unit_mode=um,
            provenance_label=run.provenance_label,
            key_fn=lambda t: (
                _exit_dt_ist(t).date().isoformat(),
                _exit_dt_ist(t).date().isoformat(),
                _exit_dt_ist(t).date().isoformat(),
            ),
        )
        weekly = _aggregate_time_buckets(
            closed,
            bucket_type="WEEKLY",
            accounting_unit_mode=um,
            provenance_label=run.provenance_label,
            key_fn=lambda t: _iso_week_key_and_bounds(_exit_dt_ist(t).date()),
        )
        monthly = _aggregate_time_buckets(
            closed,
            bucket_type="MONTHLY",
            accounting_unit_mode=um,
            provenance_label=run.provenance_label,
            key_fn=lambda t: _month_key_and_bounds(_exit_dt_ist(t).date()),
        )
        session_wise = _aggregate_time_buckets(
            closed,
            bucket_type="SESSION",
            accounting_unit_mode=um,
            provenance_label=run.provenance_label,
            key_fn=_session_key_and_bounds,
            sort_key_fn=lambda k: (_SESSION_ORDER.get(k, 99), k),
        )

        dd_timeline = (
            drawdown_timeline
            if drawdown_timeline is not None
            else self._risk_engine.evaluate_run(run).drawdown_timeline
        )

        has_pts = domain_has_points(um)
        has_inr = domain_has_inr(um)
        sorted_curve = sorted(
            run.equity_curve,
            key=lambda p: parse_ist_datetime(p.timestamp_ist, "equity_curve.timestamp_ist"),
        )
        eq_snapshots = tuple(
            EquityCurveSnapshot(
                timestamp_ist=(dt_ist := parse_ist_datetime(pt.timestamp_ist, "equity_curve.timestamp_ist")).isoformat(),
                date_ist=dt_ist.date().isoformat(),
                session_ist=classify_ist_session(dt_ist),
                accounting_unit_mode=um,
                equity_points=pt.cumulative_equity_points if has_pts else None,
                drawdown_points=pt.drawdown_points if has_pts else None,
                total_equity_inr=pt.total_equity_inr if has_inr else None,
                drawdown_inr=pt.drawdown_inr if has_inr else None,
                drawdown_pct=pt.drawdown_pct if has_inr else None,
                open_trades_count=pt.open_trades_count,
            )
            for pt in sorted_curve
        )

        exp_pts = sum(float(t.net_points or 0.0) for t in closed) if has_pts else None
        exp_inr = sum(float(t.net_pnl_inr or 0.0) for t in closed) if has_inr else None
        matches = all(
            _buckets_conserve_net(b, expected_points=exp_pts, expected_inr=exp_inr)
            for b in (daily, weekly, monthly, session_wise)
        )

        return TimeSeriesAnalyticsResult(
            accounting_unit_mode=um,
            provenance_label=run.provenance_label,
            is_synthetic_modelled=run.is_synthetic_modelled,
            daily=daily,
            weekly=weekly,
            monthly=monthly,
            session_wise=session_wise,
            drawdown_timeline=dd_timeline,
            equity_curve=eq_snapshots,
            total_closed_trades_aggregated=len(closed),
            unclosed_trades_excluded_count=unclosed_count,
            reconciliation_matches_totals=matches,
        )

