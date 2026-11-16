"""
AIVOLVE Phase 4 Step 4.4 — Risk & Drawdown Analytics Engine.

Computes deterministic drawdown timelines, underwater episodes, Ulcer Index,
recovery factor (safe zero-drawdown handling), consecutive loss streaks, and
tail losses strictly segregated by AccountingUnitMode.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, List, Optional, Sequence, Tuple

from app.backtesting.analytics_models import (
    DomainRiskMetrics,
    DrawdownEpisode,
    DrawdownTimelinePoint,
    MetricAvailabilityStatus,
    RiskSummaryAnalytics,
    domain_has_inr,
    domain_has_points,
    parse_ist_datetime,
    validate_run_domain_integrity,
)
from app.backtesting.simulation_models import (
    AccountingUnitMode,
    EquityCurvePoint,
    SimulationRunResult,
    TradeLifecycleState,
    TradeRecord,
)
from app.backtesting.trade_lifecycle import deterministic_id


@dataclass(frozen=True)
class _CurveObs:
    timestamp_ist: str
    dt_ist: datetime
    equity: float
    peak: float
    drawdown: float
    drawdown_pct: Optional[float]


def sort_closed_trades(trades: Sequence[TradeRecord]) -> Tuple[TradeRecord, ...]:
    """Returns terminal CLOSED trades deterministically ordered by (exit_time_ist, entry_time_ist, trade_id)."""
    closed = [t for t in trades if t.state == TradeLifecycleState.CLOSED]

    def _key(t: TradeRecord) -> Tuple[datetime, datetime, str]:
        exit_dt = (
            parse_ist_datetime(t.exit_time_ist, f"trade[{t.trade_id}].exit_time_ist")
            if t.exit_time_ist
            else parse_ist_datetime(t.signal_available_at_ist, f"trade[{t.trade_id}].signal_available_at_ist")
        )
        entry_dt = (
            parse_ist_datetime(t.entry_time_ist, f"trade[{t.trade_id}].entry_time_ist")
            if t.entry_time_ist
            else exit_dt
        )
        return (exit_dt, entry_dt, t.trade_id)

    return tuple(sorted(closed, key=_key))


def is_clean_winner(trade: TradeRecord, domain_net: float) -> bool:
    """Matches Step 4.3 PortfolioLedger rule: strictly positive net AND zero intrabar ambiguity."""
    return domain_net > 0.0 and trade.intrabar_ambiguous_count == 0


def max_consecutive_streak(flags: Sequence[bool]) -> int:
    best = 0
    cur = 0
    for f in flags:
        if f:
            cur += 1
            if cur > best:
                best = cur
        else:
            cur = 0
    return best


def _extract_curve_series(
    equity_curve: Sequence[EquityCurvePoint],
    closed_trades: Sequence[TradeRecord],
    accounting_unit_mode: AccountingUnitMode,
    starting_capital_inr: Optional[float],
) -> Tuple[Tuple[DrawdownTimelinePoint, ...], Tuple[_CurveObs, ...], Tuple[_CurveObs, ...]]:
    """
    Constructs aligned IST drawdown timeline points and domain-specific observation series
    from run.equity_curve, or falls back to cumulative realized trade equity when curve is empty.
    """
    has_pts = domain_has_points(accounting_unit_mode)
    has_inr = domain_has_inr(accounting_unit_mode)

    raw_rows: List[Tuple[str, datetime, Optional[float], Optional[float]]] = []
    if equity_curve:
        sorted_curve = sorted(
            equity_curve,
            key=lambda p: parse_ist_datetime(p.timestamp_ist, "equity_curve.timestamp_ist"),
        )
        for pt in sorted_curve:
            dt_ist = parse_ist_datetime(pt.timestamp_ist, "equity_curve.timestamp_ist")
            pts_eq = float(pt.cumulative_equity_points) if has_pts and pt.cumulative_equity_points is not None else None
            inr_eq = float(pt.total_equity_inr) if has_inr and pt.total_equity_inr is not None else None
            raw_rows.append((dt_ist.isoformat(), dt_ist, pts_eq, inr_eq))
    elif closed_trades:
        cum_pts = 0.0
        cum_inr = float(starting_capital_inr) if (has_inr and starting_capital_inr is not None) else 0.0
        for t in closed_trades:
            ts_str = t.exit_time_ist or t.entry_time_ist or t.signal_available_at_ist
            dt_ist = parse_ist_datetime(ts_str, f"trade[{t.trade_id}].timestamp_ist")
            if has_pts:
                cum_pts += float(t.net_points or 0.0)
            if has_inr:
                cum_inr += float(t.net_pnl_inr or 0.0)
            raw_rows.append(
                (
                    dt_ist.isoformat(),
                    dt_ist,
                    cum_pts if has_pts else None,
                    cum_inr if has_inr else None,
                )
            )

    peak_pts = 0.0
    peak_inr = float(starting_capital_inr) if (has_inr and starting_capital_inr is not None) else 0.0

    timeline: List[DrawdownTimelinePoint] = []
    pts_obs: List[_CurveObs] = []
    inr_obs: List[_CurveObs] = []

    for ts_iso, dt_ist, pts_eq, inr_eq in raw_rows:
        dd_pts: Optional[float] = None
        cur_peak_pts: Optional[float] = None
        if has_pts:
            eq_p = float(pts_eq or 0.0)
            if eq_p > peak_pts:
                peak_pts = eq_p
            dd_pts = max(0.0, peak_pts - eq_p)
            cur_peak_pts = peak_pts
            pts_obs.append(
                _CurveObs(
                    timestamp_ist=ts_iso,
                    dt_ist=dt_ist,
                    equity=eq_p,
                    peak=peak_pts,
                    drawdown=dd_pts,
                    drawdown_pct=None,
                )
            )

        dd_inr: Optional[float] = None
        dd_pct: Optional[float] = None
        cur_peak_inr: Optional[float] = None
        if has_inr:
            eq_i = float(inr_eq if inr_eq is not None else peak_inr)
            if eq_i > peak_inr:
                peak_inr = eq_i
            dd_inr = max(0.0, peak_inr - eq_i)
            dd_pct = (dd_inr / peak_inr * 100.0) if peak_inr > 0.0 else 0.0
            cur_peak_inr = peak_inr
            inr_obs.append(
                _CurveObs(
                    timestamp_ist=ts_iso,
                    dt_ist=dt_ist,
                    equity=eq_i,
                    peak=peak_inr,
                    drawdown=dd_inr,
                    drawdown_pct=dd_pct,
                )
            )

        timeline.append(
            DrawdownTimelinePoint(
                timestamp_ist=ts_iso,
                accounting_unit_mode=accounting_unit_mode,
                equity_points=pts_eq if has_pts else None,
                peak_points=cur_peak_pts if has_pts else None,
                drawdown_points=dd_pts if has_pts else None,
                equity_inr=inr_eq if has_inr else None,
                peak_inr=cur_peak_inr if has_inr else None,
                drawdown_inr=dd_inr if has_inr else None,
                drawdown_pct=dd_pct if has_inr else None,
            )
        )

    return tuple(timeline), tuple(pts_obs), tuple(inr_obs)


def _build_drawdown_episodes(
    series: Sequence[_CurveObs],
    unit_label: str,
    episode_prefix: str,
) -> Tuple[DrawdownEpisode, ...]:
    """Detects contiguous underwater peak-to-trough-to-recovery intervals deterministically."""
    if not series:
        return ()

    episodes: List[DrawdownEpisode] = []
    last_peak_idx = 0
    in_episode = False
    ep_peak_idx = 0
    ep_peak_ts = series[0].timestamp_ist
    ep_peak_dt = series[0].dt_ist
    ep_peak_eq = series[0].peak
    ep_trough_idx = 0
    ep_trough_ts = series[0].timestamp_ist
    ep_trough_eq = series[0].equity
    ep_max_dd = 0.0
    ep_max_dd_pct: Optional[float] = 0.0 if unit_label == "INR" else None

    for idx, obs in enumerate(series):
        is_underwater = obs.drawdown > 1e-12
        if not in_episode:
            if not is_underwater:
                last_peak_idx = idx
            else:
                in_episode = True
                anchor = series[last_peak_idx]
                ep_peak_idx = last_peak_idx
                # If drawdown occurs on bar 0 below initial capital/zero, anchor at bar 0 peak
                if idx == 0:
                    ep_peak_ts = obs.timestamp_ist
                    ep_peak_dt = obs.dt_ist
                    ep_peak_eq = obs.peak
                else:
                    ep_peak_ts = anchor.timestamp_ist
                    ep_peak_dt = anchor.dt_ist
                    ep_peak_eq = obs.peak
                ep_trough_idx = idx
                ep_trough_ts = obs.timestamp_ist
                ep_trough_eq = obs.equity
                ep_max_dd = obs.drawdown
                ep_max_dd_pct = obs.drawdown_pct if unit_label == "INR" else None
        else:
            if is_underwater:
                if obs.drawdown > ep_max_dd:
                    ep_max_dd = obs.drawdown
                    ep_trough_idx = idx
                    ep_trough_ts = obs.timestamp_ist
                    ep_trough_eq = obs.equity
                    if unit_label == "INR" and obs.drawdown_pct is not None:
                        ep_max_dd_pct = max(ep_max_dd_pct or 0.0, obs.drawdown_pct)
            else:
                duration_bars = max(1, idx - ep_peak_idx)
                duration_seconds = max(0.0, (obs.dt_ist - ep_peak_dt).total_seconds())
                episodes.append(
                    DrawdownEpisode(
                        episode_id=deterministic_id(
                            "DD", episode_prefix, unit_label, len(episodes) + 1, ep_peak_ts, ep_trough_ts
                        ),
                        unit_label=unit_label,  # type: ignore[arg-type]
                        peak_time_ist=ep_peak_ts,
                        trough_time_ist=ep_trough_ts,
                        recovery_time_ist=obs.timestamp_ist,
                        recovered=True,
                        peak_equity=ep_peak_eq,
                        trough_equity=ep_trough_eq,
                        max_drawdown=ep_max_dd,
                        max_drawdown_pct=ep_max_dd_pct if unit_label == "INR" else None,
                        duration_bars=duration_bars,
                        duration_seconds=duration_seconds,
                    )
                )
                in_episode = False
                last_peak_idx = idx

    if in_episode:
        last_obs = series[-1]
        duration_bars = max(1, (len(series) - 1) - ep_peak_idx)
        duration_seconds = max(0.0, (last_obs.dt_ist - ep_peak_dt).total_seconds())
        episodes.append(
            DrawdownEpisode(
                episode_id=deterministic_id(
                    "DD", episode_prefix, unit_label, len(episodes) + 1, ep_peak_ts, ep_trough_ts
                ),
                unit_label=unit_label,  # type: ignore[arg-type]
                peak_time_ist=ep_peak_ts,
                trough_time_ist=ep_trough_ts,
                recovery_time_ist=None,
                recovered=False,
                peak_equity=ep_peak_eq,
                trough_equity=ep_trough_eq,
                max_drawdown=ep_max_dd,
                max_drawdown_pct=ep_max_dd_pct if unit_label == "INR" else None,
                duration_bars=duration_bars,
                duration_seconds=duration_seconds,
            )
        )

    return tuple(episodes)


def _compute_domain_risk(
    series: Sequence[_CurveObs],
    closed_trades: Sequence[TradeRecord],
    net_getter: Callable[[TradeRecord], float],
    unit_label: str,
    provenance_label: str,
    episode_prefix: str,
) -> DomainRiskMetrics:
    episodes = _build_drawdown_episodes(series, unit_label=unit_label, episode_prefix=episode_prefix)

    max_dd = 0.0
    max_dd_pct: Optional[float] = 0.0 if (unit_label == "INR" and series) else None
    if series:
        for obs in series:
            if obs.drawdown > max_dd:
                max_dd = obs.drawdown
            if unit_label == "INR" and obs.drawdown_pct is not None:
                if max_dd_pct is None or obs.drawdown_pct > max_dd_pct:
                    max_dd_pct = obs.drawdown_pct
    elif unit_label == "INR":
        max_dd_pct = 0.0

    worst_ep: Optional[DrawdownEpisode] = None
    if episodes:
        worst_ep = max(episodes, key=lambda ep: ep.max_drawdown)

    avg_dd: Optional[float] = None
    ulcer_pts: Optional[float] = None
    ulcer_pct: Optional[float] = None
    cur_dd = 0.0
    if series:
        avg_dd = sum(o.drawdown for o in series) / len(series)
        cur_dd = series[-1].drawdown
        if unit_label == "INDEX_POINTS":
            ulcer_pts = math.sqrt(sum(o.drawdown ** 2 for o in series) / len(series))
        else:
            ulcer_pct = math.sqrt(sum((o.drawdown_pct or 0.0) ** 2 for o in series) / len(series))

    nets = [net_getter(t) for t in closed_trades]
    total_net = sum(nets)
    neg_nets = [v for v in nets if v < 0.0]
    largest_loss = min(neg_nets) if neg_nets else None
    largest_loss_abs = abs(largest_loss) if largest_loss is not None else None
    max_consec_losses = max_consecutive_streak(
        [not is_clean_winner(t, net) for t, net in zip(closed_trades, nets)]
    )

    if not closed_trades:
        rec_factor = None
        rec_status = MetricAvailabilityStatus.NO_CLOSED_TRADES
    elif max_dd <= 0.0:
        rec_factor = None
        rec_status = MetricAvailabilityStatus.ZERO_DRAWDOWN_UNDEFINED
    else:
        rec_factor = total_net / max_dd
        rec_status = MetricAvailabilityStatus.AVAILABLE

    max_dur_bars = max((ep.duration_bars for ep in episodes), default=0)
    max_dur_secs = max((ep.duration_seconds for ep in episodes), default=0.0)

    return DomainRiskMetrics(
        unit_label=unit_label,  # type: ignore[arg-type]
        provenance_label=provenance_label,
        max_drawdown=max_dd,
        max_drawdown_pct=max_dd_pct if unit_label == "INR" else None,
        max_drawdown_peak_time_ist=worst_ep.peak_time_ist if worst_ep else None,
        max_drawdown_trough_time_ist=worst_ep.trough_time_ist if worst_ep else None,
        max_drawdown_recovery_time_ist=worst_ep.recovery_time_ist if worst_ep else None,
        recovery_factor=rec_factor,
        recovery_factor_status=rec_status,
        average_drawdown=avg_dd,
        ulcer_index_points=ulcer_pts,
        ulcer_index_pct=ulcer_pct,
        current_drawdown=cur_dd,
        is_currently_in_drawdown=cur_dd > 1e-12,
        largest_loss=largest_loss,
        largest_loss_abs=largest_loss_abs,
        max_consecutive_losses=max_consec_losses,
        max_drawdown_duration_bars=max_dur_bars,
        max_drawdown_duration_seconds=max_dur_secs,
        episodes_count=len(episodes),
        episodes=episodes,
    )


class RiskAnalyticsEngine:
    """Stateless deterministic engine computing domain-segregated drawdown and risk summaries."""

    def evaluate_run(self, run: SimulationRunResult) -> RiskSummaryAnalytics:
        """Evaluates drawdown and risk metrics for a single SimulationRunResult."""
        validate_run_domain_integrity(run)
        closed_trades = sort_closed_trades(run.trades)
        return self.evaluate_components(
            accounting_unit_mode=run.accounting_unit_mode,
            provenance_label=run.provenance_label,
            is_synthetic_modelled=run.is_synthetic_modelled,
            closed_trades=closed_trades,
            equity_curve=run.equity_curve,
            starting_capital_inr=run.portfolio.starting_capital_inr,
            episode_prefix=run.run_id,
        )

    def evaluate_components(
        self,
        *,
        accounting_unit_mode: AccountingUnitMode,
        provenance_label: str,
        is_synthetic_modelled: bool,
        closed_trades: Sequence[TradeRecord],
        equity_curve: Sequence[EquityCurvePoint] = (),
        starting_capital_inr: Optional[float] = None,
        episode_prefix: str = "SLICE",
    ) -> RiskSummaryAnalytics:
        """Computes RiskSummaryAnalytics from pre-validated closed trades and optional MTM equity curve."""
        ordered_closed = sort_closed_trades(closed_trades)
        timeline, pts_obs, inr_obs = _extract_curve_series(
            equity_curve=equity_curve,
            closed_trades=ordered_closed,
            accounting_unit_mode=accounting_unit_mode,
            starting_capital_inr=starting_capital_inr,
        )

        points_risk = (
            _compute_domain_risk(
                series=pts_obs,
                closed_trades=ordered_closed,
                net_getter=lambda t: float(t.net_points or 0.0),
                unit_label="INDEX_POINTS",
                provenance_label=provenance_label,
                episode_prefix=episode_prefix,
            )
            if domain_has_points(accounting_unit_mode)
            else None
        )

        inr_risk = (
            _compute_domain_risk(
                series=inr_obs,
                closed_trades=ordered_closed,
                net_getter=lambda t: float(t.net_pnl_inr or 0.0),
                unit_label="INR",
                provenance_label=provenance_label,
                episode_prefix=episode_prefix,
            )
            if domain_has_inr(accounting_unit_mode)
            else None
        )

        return RiskSummaryAnalytics(
            accounting_unit_mode=accounting_unit_mode,
            provenance_label=provenance_label,
            is_synthetic_modelled=is_synthetic_modelled,
            points_risk=points_risk,
            inr_risk=inr_risk,
            drawdown_timeline=timeline,
        )

