"""
AIVOLVE Phase 4 Step 4.4 — Chronological Walk-Forward & Out-of-Sample Evaluator.

Guarantees:
- Strict chronological window splitting (no random shuffling).
- Purging of IS trades overlapping the IS/OOS boundary + embargoing of OOS entries.
- Explicit lookahead violation detection (`WALK_FORWARD_LOOKAHEAD_VIOLATION`).
- Domain isolation (rejects heterogeneous IS/OOS runs via `validate_homogeneous_runs`).
- Explicit insufficient-sample & zero-variance handling (never claims significance on small N).
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Dict, List, Literal, Optional, Sequence, Tuple

from app.backtesting.analytics_models import (
    AnalyticsStatus,
    DEFAULT_MIN_TRADES_FOR_SIGNIFICANCE,
    SignificanceStatus,
    WalkForwardResult,
    WalkForwardWindowResult,
    WalkForwardWindowSpec,
    domain_has_inr,
    domain_has_points,
    parse_ist_datetime,
    validate_homogeneous_runs,
    validate_run_domain_integrity,
)
from app.backtesting.performance_analytics import PerformanceAnalyticsEngine
from app.backtesting.risk_analytics import sort_closed_trades
from app.backtesting.simulation_models import (
    AccountingUnitMode,
    SimulationRunResult,
    SimulationStatus,
    TradeRecord,
)


def generate_walk_forward_windows(
    *,
    start_ist: datetime | str,
    end_ist: datetime | str,
    scheme: Literal["ANCHORED_EXPANDING", "ROLLING", "IS_OOS_SPLIT"],
    is_duration: Optional[timedelta] = None,
    oos_duration: Optional[timedelta] = None,
    step_duration: Optional[timedelta] = None,
    is_ratio: float = 0.7,
    purge_duration_seconds: float = 0.0,
    embargo_duration_seconds: float = 0.0,
) -> Tuple[WalkForwardWindowSpec, ...]:
    """Deterministically constructs chronological non-lookahead walk-forward window specs."""
    s_dt = parse_ist_datetime(start_ist, "start_ist")
    e_dt = parse_ist_datetime(end_ist, "end_ist")
    if s_dt >= e_dt:
        raise ValueError("WALK_FORWARD_INVALID_RANGE: start_ist must be strictly < end_ist.")

    if scheme == "IS_OOS_SPLIT":
        if not (0.05 <= is_ratio <= 0.95):
            raise ValueError(f"is_ratio must be within [0.05, 0.95], got {is_ratio}.")
        total_secs = (e_dt - s_dt).total_seconds()
        split_dt = s_dt + timedelta(seconds=total_secs * is_ratio)
        return (
            WalkForwardWindowSpec(
                window_id="WF-SPLIT-01",
                is_start_ist=s_dt,
                is_end_ist=split_dt,
                oos_start_ist=split_dt,
                oos_end_ist=e_dt,
                purge_duration_seconds=purge_duration_seconds,
                embargo_duration_seconds=embargo_duration_seconds,
            ),
        )

    if is_duration is None or oos_duration is None:
        raise ValueError(f"is_duration and oos_duration are required for scheme '{scheme}'.")
    if is_duration.total_seconds() <= 0 or oos_duration.total_seconds() <= 0:
        raise ValueError("is_duration and oos_duration must be positive.")

    step = step_duration or oos_duration
    if step.total_seconds() <= 0:
        raise ValueError("step_duration must be positive.")

    windows: List[WalkForwardWindowSpec] = []
    fold = 1
    cur_is_start = s_dt
    cur_is_end = s_dt + is_duration

    while cur_is_end + oos_duration <= e_dt:
        cur_oos_start = cur_is_end
        cur_oos_end = cur_oos_start + oos_duration
        windows.append(
            WalkForwardWindowSpec(
                window_id=f"WF-{fold:02d}",
                is_start_ist=cur_is_start,
                is_end_ist=cur_is_end,
                oos_start_ist=cur_oos_start,
                oos_end_ist=cur_oos_end,
                purge_duration_seconds=purge_duration_seconds,
                embargo_duration_seconds=embargo_duration_seconds,
            )
        )
        fold += 1
        if scheme == "ROLLING":
            cur_is_start = cur_is_start + step
        cur_is_end = cur_is_end + step

    if not windows:
        raise ValueError(
            "WALK_FORWARD_EMPTY_WINDOWS: horizon is shorter than is_duration + oos_duration."
        )
    return tuple(windows)


def _validate_window_sequence(windows: Sequence[WalkForwardWindowSpec]) -> None:
    if not windows:
        raise ValueError("At least one WalkForwardWindowSpec is required.")
    prev_oos_start: Optional[datetime] = None
    for w in windows:
        oos_s = parse_ist_datetime(w.oos_start_ist, f"window[{w.window_id}].oos_start_ist")
        if prev_oos_start is not None and oos_s < prev_oos_start:
            raise ValueError(
                f"WALK_FORWARD_CHRONOLOGY_VIOLATION: window '{w.window_id}' oos_start_ist "
                f"({oos_s.isoformat()}) precedes previous window ({prev_oos_start.isoformat()})."
            )
        prev_oos_start = oos_s


def _trade_timestamps(trade: TradeRecord) -> Tuple[datetime, datetime, datetime]:
    sig_dt = parse_ist_datetime(trade.signal_available_at_ist, f"trade[{trade.trade_id}].signal_available_at_ist")
    in_dt = parse_ist_datetime(
        trade.entry_time_ist or trade.signal_available_at_ist,
        f"trade[{trade.trade_id}].entry_time_ist",
    )
    out_dt = parse_ist_datetime(
        trade.exit_time_ist or trade.entry_time_ist or trade.signal_available_at_ist,
        f"trade[{trade.trade_id}].exit_time_ist",
    )
    return sig_dt, in_dt, out_dt


def _significance_from_nets(
    nets: Sequence[float],
    min_trades: int,
) -> Tuple[SignificanceStatus, Optional[float]]:
    n = len(nets)
    if n == 0:
        return SignificanceStatus.NO_TRADES, None
    t_stat: Optional[float] = None
    zero_var = False
    if n >= 2:
        mean_v = sum(nets) / n
        var_v = sum((x - mean_v) ** 2 for x in nets) / (n - 1)
        std_v = math.sqrt(var_v)
        if std_v <= 1e-12:
            zero_var = True
        else:
            t_stat = mean_v / (std_v / math.sqrt(n))
    if n < min_trades:
        return SignificanceStatus.INSUFFICIENT_SAMPLE, t_stat
    if zero_var:
        return SignificanceStatus.ZERO_VARIANCE, None
    return SignificanceStatus.DESCRIPTIVE_RESEARCH_ONLY, t_stat


def _degradation_ratio(is_exp: Optional[float], oos_exp: Optional[float]) -> Optional[float]:
    if is_exp is None or oos_exp is None or is_exp <= 0.0:
        return None
    return oos_exp / is_exp


class WalkForwardEvaluator:
    """Chronological Walk-Forward and In-Sample / Out-of-Sample research evaluator."""

    def __init__(self, perf_engine: Optional[PerformanceAnalyticsEngine] = None) -> None:
        self._perf = perf_engine or PerformanceAnalyticsEngine()

    def _evaluate_window_trades(
        self,
        *,
        window: WalkForwardWindowSpec,
        is_candidates: Sequence[TradeRecord],
        oos_candidates: Sequence[TradeRecord],
        accounting_unit_mode: AccountingUnitMode,
        provenance_label: str,
        is_synthetic_modelled: bool,
        starting_capital_inr: Optional[float],
        multiplier_inr_per_point: Optional[float],
        multiplier_doc: Optional[str],
        min_trades_for_significance: int,
        strict_pair_boundary_check: bool,
    ) -> Tuple[WalkForwardWindowResult, Tuple[TradeRecord, ...], bool]:
        is_s = parse_ist_datetime(window.is_start_ist, "is_start_ist")
        is_e = parse_ist_datetime(window.is_end_ist, "is_end_ist")
        oos_s = parse_ist_datetime(window.oos_start_ist, "oos_start_ist")
        oos_e = parse_ist_datetime(window.oos_end_ist, "oos_end_ist")
        purge_cutoff = is_e - timedelta(seconds=window.purge_duration_seconds)
        embargo_cutoff = oos_s + timedelta(seconds=window.embargo_duration_seconds)

        purged_ids: List[str] = []
        valid_is: List[TradeRecord] = []
        for t in sort_closed_trades(is_candidates):
            _, in_dt, out_dt = _trade_timestamps(t)
            if strict_pair_boundary_check and in_dt >= oos_s:
                raise ValueError(
                    f"WALK_FORWARD_LOOKAHEAD_VIOLATION: IS trade '{t.trade_id}' entered at {in_dt.isoformat()} "
                    f">= OOS start {oos_s.isoformat()}."
                )
            if is_s <= in_dt < is_e:
                if out_dt > purge_cutoff:
                    purged_ids.append(t.trade_id)
                else:
                    valid_is.append(t)

        embargoed_ids: List[str] = []
        valid_oos: List[TradeRecord] = []
        no_lookahead = True
        for t in sort_closed_trades(oos_candidates):
            sig_dt, in_dt, _ = _trade_timestamps(t)
            if strict_pair_boundary_check and in_dt < is_e:
                raise ValueError(
                    f"WALK_FORWARD_LOOKAHEAD_VIOLATION: OOS trade '{t.trade_id}' entered at {in_dt.isoformat()} "
                    f"< IS end {is_e.isoformat()}."
                )
            if strict_pair_boundary_check and sig_dt < is_e:
                raise ValueError(
                    f"WALK_FORWARD_LOOKAHEAD_VIOLATION: OOS trade '{t.trade_id}' signal originated in IS at "
                    f"{sig_dt.isoformat()} (< {is_e.isoformat()})."
                )
            if oos_s <= in_dt < oos_e:
                if sig_dt < oos_s or in_dt < embargo_cutoff:
                    embargoed_ids.append(t.trade_id)
                else:
                    valid_oos.append(t)

        is_perf = self._perf.evaluate_trade_slice(
            closed_trades=valid_is,
            accounting_unit_mode=accounting_unit_mode,
            provenance_label=provenance_label,
            is_synthetic_modelled=is_synthetic_modelled,
            starting_capital_inr=starting_capital_inr,
            instrument_multiplier_inr_per_point=multiplier_inr_per_point,
            instrument_multiplier_documentation=multiplier_doc,
            slice_prefix=f"{window.window_id}-IS",
        )
        oos_perf = self._perf.evaluate_trade_slice(
            closed_trades=valid_oos,
            accounting_unit_mode=accounting_unit_mode,
            provenance_label=provenance_label,
            is_synthetic_modelled=is_synthetic_modelled,
            starting_capital_inr=starting_capital_inr,
            instrument_multiplier_inr_per_point=multiplier_inr_per_point,
            instrument_multiplier_documentation=multiplier_doc,
            slice_prefix=f"{window.window_id}-OOS",
        )

        primary_nets = [
            float(t.net_points or 0.0)
            if accounting_unit_mode == AccountingUnitMode.INDEX_POINTS_ONLY
            else float(t.net_pnl_inr or 0.0)
            for t in valid_oos
        ]
        sig_status, _ = _significance_from_nets(primary_nets, min_trades_for_significance)

        deg_pts = (
            _degradation_ratio(
                is_perf.points_metrics.expectancy if is_perf.points_metrics else None,
                oos_perf.points_metrics.expectancy if oos_perf.points_metrics else None,
            )
            if domain_has_points(accounting_unit_mode)
            else None
        )
        deg_inr = (
            _degradation_ratio(
                is_perf.inr_metrics.expectancy if is_perf.inr_metrics else None,
                oos_perf.inr_metrics.expectancy if oos_perf.inr_metrics else None,
            )
            if domain_has_inr(accounting_unit_mode)
            else None
        )

        win_warnings: List[str] = []
        if not valid_oos:
            win_warnings.append(f"Window {window.window_id}: zero valid OOS trades after boundary/embargo checks.")
        elif len(valid_oos) < min_trades_for_significance:
            win_warnings.append(
                f"Window {window.window_id}: OOS sample size ({len(valid_oos)}) < {min_trades_for_significance}; "
                "statistical significance is NOT claimed."
            )
        if purged_ids:
            win_warnings.append(f"Window {window.window_id}: purged {len(purged_ids)} boundary-overlapping IS trade(s).")
        if embargoed_ids:
            win_warnings.append(f"Window {window.window_id}: embargoed {len(embargoed_ids)} pre-embargo OOS trade(s).")

        w_res = WalkForwardWindowResult(
            window_id=window.window_id,
            is_start_ist=is_s.isoformat(),
            is_end_ist=is_e.isoformat(),
            oos_start_ist=oos_s.isoformat(),
            oos_end_ist=oos_e.isoformat(),
            purge_duration_seconds=window.purge_duration_seconds,
            embargo_duration_seconds=window.embargo_duration_seconds,
            purged_is_trade_ids=tuple(purged_ids),
            embargoed_oos_trade_ids=tuple(embargoed_ids),
            is_trades_count=len(valid_is),
            oos_trades_count=len(valid_oos),
            is_status=AnalyticsStatus.COMPLETED if valid_is else AnalyticsStatus.NO_TRADES,
            oos_status=AnalyticsStatus.COMPLETED if valid_oos else AnalyticsStatus.NO_TRADES,
            is_performance=is_perf,
            oos_performance=oos_perf,
            oos_degradation_ratio_points=deg_pts,
            oos_degradation_ratio_inr=deg_inr,
            significance_status=sig_status,
            statistical_significance_claimed=False,
            warnings=tuple(win_warnings),
        )
        return w_res, tuple(valid_oos), no_lookahead

    def evaluate_run(
        self,
        run: SimulationRunResult,
        windows: Sequence[WalkForwardWindowSpec],
        *,
        window_scheme: Literal["ANCHORED_EXPANDING", "ROLLING", "EXPLICIT_WINDOWS", "IS_OOS_SPLIT"] = "EXPLICIT_WINDOWS",
        min_trades_for_significance: int = DEFAULT_MIN_TRADES_FOR_SIGNIFICANCE,
    ) -> WalkForwardResult:
        """Evaluates chronological IS/OOS walk-forward windows over a single persisted SimulationRunResult."""
        validate_run_domain_integrity(run)
        _validate_window_sequence(windows)
        if run.status != SimulationStatus.COMPLETED:
            raise ValueError(
                f"Cannot run walk-forward evaluation on non-completed simulation run '{run.run_id}' ({run.status.value})."
            )

        closed = sort_closed_trades(run.trades)
        um = run.accounting_unit_mode
        results: List[WalkForwardWindowResult] = []
        oos_dedup: Dict[str, TradeRecord] = {}
        all_warnings: List[str] = []
        no_lookahead_all = True

        for w in windows:
            w_res, valid_oos, ok_nl = self._evaluate_window_trades(
                window=w,
                is_candidates=closed,
                oos_candidates=closed,
                accounting_unit_mode=um,
                provenance_label=run.provenance_label,
                is_synthetic_modelled=run.is_synthetic_modelled,
                starting_capital_inr=run.portfolio.starting_capital_inr,
                multiplier_inr_per_point=run.portfolio.instrument_multiplier_inr_per_point,
                multiplier_doc=run.portfolio.instrument_multiplier_documentation,
                min_trades_for_significance=min_trades_for_significance,
                strict_pair_boundary_check=False,
            )
            no_lookahead_all = no_lookahead_all and ok_nl
            results.append(w_res)
            all_warnings.extend(w_res.warnings)
            for t in valid_oos:
                oos_dedup[t.trade_id] = t

        return self._finalize_walk_forward_result(
            windows=results,
            oos_unique_trades=sort_closed_trades(list(oos_dedup.values())),
            accounting_unit_mode=um,
            provenance_label=run.provenance_label,
            is_synthetic_modelled=run.is_synthetic_modelled,
            starting_capital_inr=run.portfolio.starting_capital_inr,
            multiplier_inr_per_point=run.portfolio.instrument_multiplier_inr_per_point,
            multiplier_doc=run.portfolio.instrument_multiplier_documentation,
            window_scheme=window_scheme,
            min_trades_for_significance=min_trades_for_significance,
            no_lookahead_verified=no_lookahead_all,
            warnings=all_warnings,
        )

    def evaluate_run_pairs(
        self,
        pairs: Sequence[Tuple[WalkForwardWindowSpec, SimulationRunResult, SimulationRunResult]],
        *,
        window_scheme: Literal["ANCHORED_EXPANDING", "ROLLING", "EXPLICIT_WINDOWS", "IS_OOS_SPLIT"] = "EXPLICIT_WINDOWS",
        min_trades_for_significance: int = DEFAULT_MIN_TRADES_FOR_SIGNIFICANCE,
    ) -> WalkForwardResult:
        """
        Evaluates explicit chronological `(WalkForwardWindowSpec, is_run, oos_run)` tuples.
        Rejects mixed-domain runs (`validate_homogeneous_runs`) and future-leakage OOS timestamps.
        """
        if not pairs:
            raise ValueError("At least one (WalkForwardWindowSpec, is_run, oos_run) pair is required.")
        specs = [p[0] for p in pairs]
        _validate_window_sequence(specs)
        all_runs: List[SimulationRunResult] = []
        for _, is_run, oos_run in pairs:
            all_runs.extend((is_run, oos_run))
        um, prov, is_synth = validate_homogeneous_runs(all_runs)

        ref = all_runs[0]
        results: List[WalkForwardWindowResult] = []
        oos_dedup: Dict[str, TradeRecord] = {}
        all_warnings: List[str] = []
        no_lookahead_all = True

        for w, is_run, oos_run in pairs:
            if is_run.status != SimulationStatus.COMPLETED or oos_run.status != SimulationStatus.COMPLETED:
                raise ValueError(
                    f"All IS/OOS runs must have status COMPLETED (got {is_run.status.value} / {oos_run.status.value})."
                )
            w_res, valid_oos, ok_nl = self._evaluate_window_trades(
                window=w,
                is_candidates=sort_closed_trades(is_run.trades),
                oos_candidates=sort_closed_trades(oos_run.trades),
                accounting_unit_mode=um,
                provenance_label=prov,
                is_synthetic_modelled=is_synth,
                starting_capital_inr=ref.portfolio.starting_capital_inr,
                multiplier_inr_per_point=ref.portfolio.instrument_multiplier_inr_per_point,
                multiplier_doc=ref.portfolio.instrument_multiplier_documentation,
                min_trades_for_significance=min_trades_for_significance,
                strict_pair_boundary_check=True,
            )
            no_lookahead_all = no_lookahead_all and ok_nl
            results.append(w_res)
            all_warnings.extend(w_res.warnings)
            for t in valid_oos:
                oos_dedup[t.trade_id] = t

        return self._finalize_walk_forward_result(
            windows=results,
            oos_unique_trades=sort_closed_trades(list(oos_dedup.values())),
            accounting_unit_mode=um,
            provenance_label=prov,
            is_synthetic_modelled=is_synth,
            starting_capital_inr=ref.portfolio.starting_capital_inr,
            multiplier_inr_per_point=ref.portfolio.instrument_multiplier_inr_per_point,
            multiplier_doc=ref.portfolio.instrument_multiplier_documentation,
            window_scheme=window_scheme,
            min_trades_for_significance=min_trades_for_significance,
            no_lookahead_verified=no_lookahead_all,
            warnings=all_warnings,
        )

    def _finalize_walk_forward_result(
        self,
        *,
        windows: Sequence[WalkForwardWindowResult],
        oos_unique_trades: Sequence[TradeRecord],
        accounting_unit_mode: AccountingUnitMode,
        provenance_label: str,
        is_synthetic_modelled: bool,
        starting_capital_inr: Optional[float],
        multiplier_inr_per_point: Optional[float],
        multiplier_doc: Optional[str],
        window_scheme: Literal["ANCHORED_EXPANDING", "ROLLING", "EXPLICIT_WINDOWS", "IS_OOS_SPLIT"],
        min_trades_for_significance: int,
        no_lookahead_verified: bool,
        warnings: Sequence[str],
    ) -> WalkForwardResult:
        agg_oos_perf = (
            self._perf.evaluate_trade_slice(
                closed_trades=oos_unique_trades,
                accounting_unit_mode=accounting_unit_mode,
                provenance_label=provenance_label,
                is_synthetic_modelled=is_synthetic_modelled,
                starting_capital_inr=starting_capital_inr,
                instrument_multiplier_inr_per_point=multiplier_inr_per_point,
                instrument_multiplier_documentation=multiplier_doc,
                slice_prefix="WF-AGG-OOS",
            )
            if oos_unique_trades
            else None
        )

        pts_t: Optional[float] = None
        inr_t: Optional[float] = None
        sig_pts: Optional[SignificanceStatus] = None
        sig_inr: Optional[SignificanceStatus] = None

        if domain_has_points(accounting_unit_mode):
            pts_nets = [float(t.net_points or 0.0) for t in oos_unique_trades]
            sig_pts, pts_t = _significance_from_nets(pts_nets, min_trades_for_significance)
        if domain_has_inr(accounting_unit_mode):
            inr_nets = [float(t.net_pnl_inr or 0.0) for t in oos_unique_trades]
            sig_inr, inr_t = _significance_from_nets(inr_nets, min_trades_for_significance)

        agg_sig = sig_pts if sig_pts is not None else (sig_inr or SignificanceStatus.NO_TRADES)
        dedup_warnings = tuple(dict.fromkeys(warnings))

        return WalkForwardResult(
            accounting_unit_mode=accounting_unit_mode,
            provenance_label=provenance_label,
            is_synthetic_modelled=is_synthetic_modelled,
            window_scheme=window_scheme,
            chronological_only=True,
            shuffling_used=False,
            no_lookahead_verified=no_lookahead_verified,
            min_trades_for_significance=min_trades_for_significance,
            windows_count=len(windows),
            valid_oos_windows_count=sum(1 for w in windows if w.oos_trades_count > 0),
            total_purged_is_trades=sum(len(w.purged_is_trade_ids) for w in windows),
            total_embargoed_oos_trades=sum(len(w.embargoed_oos_trade_ids) for w in windows),
            windows=tuple(windows),
            aggregate_oos_performance=agg_oos_perf,
            aggregate_oos_significance_status=agg_sig,
            statistical_significance_claimed=False,
            oos_t_stat_points=pts_t,
            oos_t_stat_inr=inr_t,
            warnings=dedup_warnings,
        )

