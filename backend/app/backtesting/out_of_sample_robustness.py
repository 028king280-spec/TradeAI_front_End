"""
AIVOLVE Phase 4 Step 4.5 — Module F: Out-of-Sample & Walk-Forward Robustness Engine.

Reuses Step 4.4 `WalkForwardEvaluator` and `generate_walk_forward_windows` strictly
preserving chronological ordering, IS/OOS boundary purge + embargo, zero lookahead
verification, and AccountingUnitMode separation.
"""

from __future__ import annotations

from datetime import timedelta
from typing import List, Literal, Optional, Sequence, Tuple

from app.backtesting.analytics_models import (
    DEFAULT_MIN_TRADES_FOR_SIGNIFICANCE,
    WalkForwardResult,
    WalkForwardWindowSpec,
    parse_ist_datetime,
    validate_homogeneous_runs,
    validate_run_domain_integrity,
)
from app.backtesting.risk_analytics import sort_closed_trades
from app.backtesting.robustness_models import (
    OutOfSampleRobustnessResult,
    RobustnessDomainMetrics,
    RobustnessStatus,
    evaluate_closed_trade_slice_metrics,
    extract_segregated_metrics,
)
from app.backtesting.simulation_models import SimulationRunResult, SimulationStatus, TradeRecord
from app.backtesting.walk_forward import WalkForwardEvaluator, generate_walk_forward_windows


def _expectancy_retention_ratio(
    is_dom: Optional[RobustnessDomainMetrics],
    oos_dom: Optional[RobustnessDomainMetrics],
) -> Optional[float]:
    if is_dom is None or oos_dom is None:
        return None
    if is_dom.expectancy is None or oos_dom.expectancy is None or abs(is_dom.expectancy) <= 1e-12:
        return None
    if is_dom.expectancy <= 0.0:
        return None
    return round(oos_dom.expectancy / is_dom.expectancy, 6)


class OutOfSampleRobustnessEngine:
    """Chronological In-Sample vs Out-of-Sample stability evaluator."""

    def __init__(self, wf_evaluator: Optional[WalkForwardEvaluator] = None) -> None:
        self._wf = wf_evaluator or WalkForwardEvaluator()

    def evaluate_run(
        self,
        run: SimulationRunResult,
        *,
        windows: Optional[Sequence[WalkForwardWindowSpec]] = None,
        window_scheme: Literal["ANCHORED_EXPANDING", "ROLLING", "EXPLICIT_WINDOWS", "IS_OOS_SPLIT"] = "IS_OOS_SPLIT",
        is_ratio: float = 0.7,
        is_duration: Optional[timedelta] = None,
        oos_duration: Optional[timedelta] = None,
        step_duration: Optional[timedelta] = None,
        purge_duration_seconds: float = 0.0,
        embargo_duration_seconds: float = 0.0,
        min_trades_for_significance: int = DEFAULT_MIN_TRADES_FOR_SIGNIFICANCE,
    ) -> OutOfSampleRobustnessResult:
        validate_run_domain_integrity(run)
        um = run.accounting_unit_mode

        if run.status != SimulationStatus.COMPLETED:
            return OutOfSampleRobustnessResult(
                status=RobustnessStatus.RUN_NOT_COMPLETED,
                accounting_unit_mode=um,
                provenance_label=run.provenance_label,
                is_synthetic_modelled=run.is_synthetic_modelled,
                windows_count=0,
                valid_oos_windows_count=0,
                total_is_trades=0,
                total_oos_trades=0,
                no_lookahead_verified=True,
                warnings=(f"RUN_NOT_COMPLETED: SimulationRunResult status is '{run.status.value}'.",),
            )

        closed_trades = sort_closed_trades(run.trades)
        if not closed_trades:
            return OutOfSampleRobustnessResult(
                status=RobustnessStatus.NO_TRADES,
                accounting_unit_mode=um,
                provenance_label=run.provenance_label,
                is_synthetic_modelled=run.is_synthetic_modelled,
                windows_count=0,
                valid_oos_windows_count=0,
                total_is_trades=0,
                total_oos_trades=0,
                no_lookahead_verified=True,
                warnings=("NO_CLOSED_TRADES: Out-of-sample evaluation requires at least one closed trade.",),
            )

        eff_windows: Sequence[WalkForwardWindowSpec]
        eff_scheme = window_scheme
        if windows is not None:
            eff_windows = windows
            eff_scheme = "EXPLICIT_WINDOWS"
        else:
            timestamps = [
                parse_ist_datetime(
                    t.entry_time_ist or t.signal_available_at_ist,
                    f"trade[{t.trade_id}].entry_time_ist",
                )
                for t in closed_trades
            ]
            timestamps.extend(
                parse_ist_datetime(t.exit_time_ist, f"trade[{t.trade_id}].exit_time_ist")
                for t in closed_trades
                if t.exit_time_ist
            )
            min_dt = min(timestamps)
            max_dt = max(timestamps)
            if max_dt <= min_dt + timedelta(seconds=60):
                return OutOfSampleRobustnessResult(
                    status=RobustnessStatus.INSUFFICIENT_DATA,
                    accounting_unit_mode=um,
                    provenance_label=run.provenance_label,
                    is_synthetic_modelled=run.is_synthetic_modelled,
                    windows_count=0,
                    valid_oos_windows_count=0,
                    total_is_trades=0,
                    total_oos_trades=0,
                    no_lookahead_verified=True,
                    warnings=(
                        "INSUFFICIENT_TIME_SPAN_FOR_OOS: Closed trades span too short an interval to partition chronologically.",
                    ),
                )
            span_end = max_dt + timedelta(seconds=1)
            eff_windows = generate_walk_forward_windows(
                start_ist=min_dt,
                end_ist=span_end,
                scheme=window_scheme if window_scheme != "EXPLICIT_WINDOWS" else "IS_OOS_SPLIT",
                is_duration=is_duration,
                oos_duration=oos_duration,
                step_duration=step_duration,
                is_ratio=is_ratio,
                purge_duration_seconds=purge_duration_seconds,
                embargo_duration_seconds=embargo_duration_seconds,
            )

        wf_res = self._wf.evaluate_run(
            run,
            windows=eff_windows,
            window_scheme=eff_scheme,
            min_trades_for_significance=min_trades_for_significance,
        )
        return self._summarize_walk_forward(
            reference_run=run,
            wf_res=wf_res,
            source_is_runs=None,
            windows=eff_windows,
        )

    def evaluate(
        self,
        run: SimulationRunResult,
        **kwargs,
    ) -> OutOfSampleRobustnessResult:
        """Uniform Step 4.5 engine alias delegating to `evaluate_run`."""
        return self.evaluate_run(run, **kwargs)

    def evaluate_run_pairs(
        self,
        pairs: Sequence[Tuple[WalkForwardWindowSpec, SimulationRunResult, SimulationRunResult]],
        *,
        window_scheme: Literal["ANCHORED_EXPANDING", "ROLLING", "EXPLICIT_WINDOWS", "IS_OOS_SPLIT"] = "EXPLICIT_WINDOWS",
        min_trades_for_significance: int = DEFAULT_MIN_TRADES_FOR_SIGNIFICANCE,
    ) -> OutOfSampleRobustnessResult:
        if not pairs:
            raise ValueError("At least one (WalkForwardWindowSpec, is_run, oos_run) pair is required.")
        all_runs = [r for _, is_r, oos_r in pairs for r in (is_r, oos_r)]
        validate_homogeneous_runs(all_runs)
        wf_res = self._wf.evaluate_run_pairs(
            pairs,
            window_scheme=window_scheme,
            min_trades_for_significance=min_trades_for_significance,
        )
        return self._summarize_walk_forward(
            reference_run=pairs[0][1],
            wf_res=wf_res,
            source_is_runs=[(w, is_r) for w, is_r, _ in pairs],
            windows=[w for w, _, _ in pairs],
        )

    def _summarize_walk_forward(
        self,
        *,
        reference_run: SimulationRunResult,
        wf_res: WalkForwardResult,
        source_is_runs: Optional[Sequence[Tuple[WalkForwardWindowSpec, SimulationRunResult]]],
        windows: Sequence[WalkForwardWindowSpec],
    ) -> OutOfSampleRobustnessResult:
        um = wf_res.accounting_unit_mode
        warnings = list(wf_res.warnings)

        # Aggregate deduplicated IS trades respecting chronological boundaries & purge
        is_dedup: dict[str, TradeRecord] = {}
        if source_is_runs is not None:
            for w, is_r in source_is_runs:
                purged_set = set(
                    next((wr.purged_is_trade_ids for wr in wf_res.windows if wr.window_id == w.window_id), ())
                )
                is_s = parse_ist_datetime(w.is_start_ist, "is_start_ist")
                is_e = parse_ist_datetime(w.is_end_ist, "is_end_ist")
                for t in sort_closed_trades(is_r.trades):
                    in_dt = parse_ist_datetime(t.entry_time_ist or t.signal_available_at_ist, "entry_time_ist")
                    if is_s <= in_dt < is_e and t.trade_id not in purged_set:
                        is_dedup[t.trade_id] = t
        else:
            ref_closed = sort_closed_trades(reference_run.trades)
            for w, w_res in zip(windows, wf_res.windows):
                purged_set = set(w_res.purged_is_trade_ids)
                is_s = parse_ist_datetime(w.is_start_ist, "is_start_ist")
                is_e = parse_ist_datetime(w.is_end_ist, "is_end_ist")
                for t in ref_closed:
                    in_dt = parse_ist_datetime(t.entry_time_ist or t.signal_available_at_ist, "entry_time_ist")
                    if is_s <= in_dt < is_e and t.trade_id not in purged_set:
                        is_dedup[t.trade_id] = t

        total_is_trades = len(is_dedup)
        is_pts, is_inr = evaluate_closed_trade_slice_metrics(
            closed_trades=list(is_dedup.values()),
            reference_run=reference_run,
            slice_prefix="OOS-ROBUST-IS",
        )

        if wf_res.aggregate_oos_performance is not None:
            oos_pts, oos_inr = extract_segregated_metrics(
                wf_res.aggregate_oos_performance,
                None,
                starting_capital_inr=reference_run.portfolio.starting_capital_inr,
            )
            total_oos_trades = wf_res.aggregate_oos_performance.trades_closed
        else:
            oos_pts, oos_inr = None, None
            total_oos_trades = 0

        valid_oos_wins = [w for w in wf_res.windows if w.oos_trades_count > 0]
        pos_pts_ratio: Optional[float] = None
        pos_inr_ratio: Optional[float] = None
        if valid_oos_wins:
            if any(w.oos_performance.points_metrics is not None for w in valid_oos_wins):
                pos_cnt = sum(
                    1
                    for w in valid_oos_wins
                    if w.oos_performance.points_metrics is not None and w.oos_performance.points_metrics.net_pnl > 0.0
                )
                pos_pts_ratio = round(pos_cnt / len(valid_oos_wins), 6)
            if any(w.oos_performance.inr_metrics is not None for w in valid_oos_wins):
                pos_cnt_inr = sum(
                    1
                    for w in valid_oos_wins
                    if w.oos_performance.inr_metrics is not None and w.oos_performance.inr_metrics.net_pnl > 0.0
                )
                pos_inr_ratio = round(pos_cnt_inr / len(valid_oos_wins), 6)

        ret_pts = _expectancy_retention_ratio(is_pts, oos_pts)
        ret_inr = _expectancy_retention_ratio(is_inr, oos_inr)

        is_wr = (is_inr.win_rate_pct if is_inr else (is_pts.win_rate_pct if is_pts else None))
        oos_wr = (oos_inr.win_rate_pct if oos_inr else (oos_pts.win_rate_pct if oos_pts else None))
        wr_delta = round(oos_wr - is_wr, 6) if (is_wr is not None and oos_wr is not None) else None

        status = RobustnessStatus.COMPLETED
        if total_oos_trades == 0 or total_is_trades == 0:
            status = RobustnessStatus.INSUFFICIENT_DATA
            warnings.append(
                f"INSUFFICIENT_OOS_TRADES: Found {total_is_trades} IS trades and {total_oos_trades} OOS trades; cannot reliably compare OOS retention."
            )

        return OutOfSampleRobustnessResult(
            status=status,
            accounting_unit_mode=um,
            provenance_label=wf_res.provenance_label,
            is_synthetic_modelled=wf_res.is_synthetic_modelled,
            walk_forward_result=wf_res,
            windows_count=wf_res.windows_count,
            valid_oos_windows_count=wf_res.valid_oos_windows_count,
            total_is_trades=total_is_trades,
            total_oos_trades=total_oos_trades,
            is_aggregate_points=is_pts,
            oos_aggregate_points=oos_pts,
            is_aggregate_inr=is_inr,
            oos_aggregate_inr=oos_inr,
            oos_expectancy_retention_ratio_points=ret_pts,
            oos_expectancy_retention_ratio_inr=ret_inr,
            oos_win_rate_delta_pct_points=wr_delta,
            positive_oos_windows_ratio_points=pos_pts_ratio,
            positive_oos_windows_ratio_inr=pos_inr_ratio,
            no_lookahead_verified=wf_res.no_lookahead_verified,
            statistical_significance_claimed=False,
            warnings=tuple(dict.fromkeys(warnings)),
        )

