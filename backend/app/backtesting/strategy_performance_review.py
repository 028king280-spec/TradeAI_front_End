"""
AIVOLVE Phase 4, Step 4.8 — Domain-Isolated Strategy Performance & Breakdown Review.

Reuses accepted Step 4.3, Step 4.4, Step 4.5, and Step 4.7 outputs to evaluate
strategy performance across the three strictly separated accounting domains and
canonical breakdown dimensions without modifying calculations or inventing metadata.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from app.backtesting.analytics_models import (
    BucketDomainStats,
    DomainPerformanceMetrics,
    DomainRiskMetrics,
    UNKNOWN_LABEL,
)
from app.backtesting.performance_analytics import PerformanceAnalyticsEngine
from app.backtesting.risk_analytics import RiskAnalyticsEngine
from app.backtesting.revalidation_models import (
    AccountingDomainEvaluation,
    EligibilityClassification,
    HistoricalRevalidationRunResult,
    ISOOSSplitEvaluation,
    RevalidationSignalDirection,
    RevalidationSignalRecord,
    RevalidationStatus,
)
from app.backtesting.simulation_models import AccountingUnitMode, TradeLifecycleState, TradeRecord
from app.backtesting.strategy_evidence_models import (
    BreakdownEvidenceRow,
    DomainPerformanceEvidence,
    DomainRobustnessDigest,
    EvidenceVerdict,
    StrategyReviewConfig,
)
from app.backtesting.strategy_verdict_engine import (
    classify_evidence_verdict,
    classify_sample_size,
    verdict_for_bucket_stats,
)
from app.backtesting.time_series_analytics import build_bucket_domain_stats


def clean_metadata_label(raw: Optional[str]) -> Tuple[str, bool]:
    """Preserves explicit metadata strings and returns UNKNOWN when missing/blank."""
    if raw is None:
        return UNKNOWN_LABEL, True
    text = str(raw).strip()
    if not text or text.upper() == UNKNOWN_LABEL:
        return UNKNOWN_LABEL, True
    return text, False


def is_review_eligible_run(
    run: HistoricalRevalidationRunResult,
    config: StrategyReviewConfig,
) -> bool:
    """Checks whether a Step 4.7 run is eligible for inclusion in performance evidence."""
    if run.status in (RevalidationStatus.REJECTED_DATASET_QUALITY, RevalidationStatus.GOVERNANCE_LOCKOUT):
        return False
    if run.status == RevalidationStatus.COMPLETED_RESEARCH_ONLY_PARTIAL:
        return bool(config.include_partial_research_only)
    return run.status in (RevalidationStatus.COMPLETED, RevalidationStatus.NO_ELIGIBLE_SIGNALS)


def build_signal_lookup(
    runs: Sequence[HistoricalRevalidationRunResult],
) -> Dict[str, RevalidationSignalRecord]:
    """Maps signal_id -> RevalidationSignalRecord without mutating historical records."""
    lookup: Dict[str, RevalidationSignalRecord] = {}
    for run in runs:
        for sig in run.signals:
            lookup[sig.signal_id] = sig
    return lookup


def closed_trades_for_domain(
    runs: Sequence[HistoricalRevalidationRunResult],
    domain_mode: AccountingUnitMode,
) -> List[Tuple[HistoricalRevalidationRunResult, TradeRecord]]:
    """Collects all CLOSED trades strictly within one isolated AccountingUnitMode."""
    out: List[Tuple[HistoricalRevalidationRunResult, TradeRecord]] = []
    dk = domain_mode.value
    for run in runs:
        de = run.domain_evaluations.get(dk)
        if de is None:
            continue
        for tr in de.simulation_run.trades:
            if tr.state == TradeLifecycleState.CLOSED:
                out.append((run, tr))
    return out


def _robustness_digest_from_eval(de: AccountingDomainEvaluation) -> DomainRobustnessDigest:
    rr = de.robustness_report
    mc = rr.monte_carlo_analysis
    pts_mc = mc.points_distribution
    inr_mc = mc.inr_distribution
    slip = rr.slippage_stress
    cost = rr.transaction_cost_stress

    remains_2x_slip: Optional[bool] = slip.remains_profitable_at_2x_points
    if remains_2x_slip is None:
        remains_2x_slip = slip.remains_profitable_at_2x_inr

    return DomainRobustnessDigest(
        accounting_unit_mode=de.domain_mode,
        provenance_label=de.provenance_label,
        is_synthetic_modelled=de.is_synthetic_modelled,
        overall_status=rr.status,
        slippage_status=slip.status,
        break_even_slippage_multiplier_points=slip.break_even_slippage_multiplier_points,
        break_even_slippage_multiplier_inr=slip.break_even_slippage_multiplier_inr,
        remains_profitable_at_2x_slippage=remains_2x_slip,
        transaction_cost_status=cost.status,
        break_even_cost_multiplier_inr=cost.break_even_cost_multiplier_inr,
        remains_profitable_at_2x_costs_inr=cost.remains_profitable_at_2x_inr,
        regime_robustness_status=rr.market_regime_robustness.status,
        parameter_sensitivity_status=(
            rr.parameter_sensitivity.status if rr.parameter_sensitivity is not None else rr.status
        ),
        parameter_stability=(
            rr.parameter_sensitivity.stability_classification
            if rr.parameter_sensitivity is not None
            else rr.sample_size_governance.classification  # type: ignore[arg-type]
        )
        if rr.parameter_sensitivity is not None
        else _fallback_stability(),
        oos_status=rr.out_of_sample_robustness.status,
        oos_no_lookahead_verified=rr.out_of_sample_robustness.no_lookahead_verified,
        monte_carlo_status=mc.status,
        monte_carlo_iterations=mc.config.n_iterations,
        mc_probability_positive_net_pnl=(
            pts_mc.probability_of_positive_net_pnl
            if pts_mc is not None
            else (inr_mc.probability_of_positive_net_pnl if inr_mc is not None else None)
        ),
        mc_p05_net_pnl_points=pts_mc.ending_net_pnl.p05 if pts_mc is not None else None,
        mc_p50_net_pnl_points=pts_mc.ending_net_pnl.p50 if pts_mc is not None else None,
        mc_p95_net_pnl_points=pts_mc.ending_net_pnl.p95 if pts_mc is not None else None,
        mc_p05_net_pnl_inr=inr_mc.ending_net_pnl.p05 if inr_mc is not None else None,
        mc_p50_net_pnl_inr=inr_mc.ending_net_pnl.p50 if inr_mc is not None else None,
        mc_p95_net_pnl_inr=inr_mc.ending_net_pnl.p95 if inr_mc is not None else None,
        mc_p95_max_drawdown_points=pts_mc.max_drawdown.p95 if pts_mc is not None else None,
        mc_p95_max_drawdown_inr=inr_mc.max_drawdown.p95 if inr_mc is not None else None,
        sample_size_classification=rr.sample_size_governance.classification,
    )


def _fallback_stability():
    from app.backtesting.robustness_models import StabilityClassification

    return StabilityClassification.INSUFFICIENT_DATA


def _evaluate_single_domain(
    *,
    eligible_runs: Sequence[HistoricalRevalidationRunResult],
    domain_mode: AccountingUnitMode,
    config: StrategyReviewConfig,
) -> Optional[DomainPerformanceEvidence]:
    dk = domain_mode.value
    evals: List[Tuple[HistoricalRevalidationRunResult, AccountingDomainEvaluation]] = [
        (r, r.domain_evaluations[dk])
        for r in eligible_runs
        if dk in r.domain_evaluations
    ]
    if not evals:
        return None

    active_evals = [(r, de) for r, de in evals if de.simulation_run.portfolio.trades_closed > 0]
    chosen_evals = active_evals if active_evals else evals
    first_de = chosen_evals[0][1]

    sessions_total = sum(r.summary_metrics.sessions_evaluated for r, _ in evals)
    signals_total = sum(r.summary_metrics.total_signals_evaluated for r, _ in evals)
    trades_opened = sum(de.simulation_run.portfolio.trades_opened for _, de in evals)
    trades_closed = sum(de.simulation_run.portfolio.trades_closed for _, de in evals)
    trades_rejected = sum(de.simulation_run.portfolio.trades_rejected for _, de in evals)
    freq_per_sess = round(trades_opened / sessions_total, 4) if sessions_total > 0 else 0.0
    recon_ok = all(de.simulation_run.reconciliation.reconciled for _, de in evals)

    pts_metrics: Optional[DomainPerformanceMetrics] = None
    inr_metrics: Optional[DomainPerformanceMetrics] = None
    pts_risk: Optional[DomainRiskMetrics] = None
    inr_risk: Optional[DomainRiskMetrics] = None
    max_consec_wins = 0
    max_consec_losses = 0
    avg_hold_min: Optional[float] = None
    warnings: List[str] = []

    if len(chosen_evals) == 1:
        ar = first_de.analytics_report
        ps = ar.performance_summary
        rs = ar.risk_summary
        pts_metrics = ps.points_metrics
        inr_metrics = ps.inr_metrics
        pts_risk = rs.points_risk
        inr_risk = rs.inr_risk
        max_consec_wins = ps.max_consecutive_wins
        max_consec_losses = ps.max_consecutive_losses
        avg_hold_min = ps.average_holding_duration_minutes
    else:
        # Aggregate homogeneous runs strictly within the same accounting domain via Step 4.4 engines
        all_closed: List[TradeRecord] = []
        for _r, de in chosen_evals:
            all_closed.extend(t for t in de.simulation_run.trades if t.state == TradeLifecycleState.CLOSED)
        risk_eng = RiskAnalyticsEngine()
        perf_eng = PerformanceAnalyticsEngine(risk_eng)
        starting_cap = first_de.simulation_run.portfolio.starting_capital_inr
        rs = risk_eng.evaluate_components(
            accounting_unit_mode=domain_mode,
            provenance_label=first_de.provenance_label,
            is_synthetic_modelled=first_de.is_synthetic_modelled,
            closed_trades=all_closed,
            equity_curve=(),
            starting_capital_inr=starting_cap,
            episode_prefix="STEP48",
        )
        ps = perf_eng.evaluate_trade_slice(
            closed_trades=all_closed,
            accounting_unit_mode=domain_mode,
            provenance_label=first_de.provenance_label,
            is_synthetic_modelled=first_de.is_synthetic_modelled,
            starting_capital_inr=starting_cap,
            instrument_multiplier_inr_per_point=first_de.analytics_report.performance_summary.instrument_multiplier_inr_per_point,
            instrument_multiplier_documentation=first_de.analytics_report.performance_summary.instrument_multiplier_documentation,
            slice_prefix="STEP48",
        )
        pts_metrics = ps.points_metrics
        inr_metrics = ps.inr_metrics
        pts_risk = rs.points_risk
        inr_risk = rs.inr_risk
        max_consec_wins = ps.max_consecutive_wins
        max_consec_losses = ps.max_consecutive_losses
        avg_hold_min = ps.average_holding_duration_minutes

    for _, de in evals:
        warnings.extend(de.warnings)

    is_oos_list: Tuple[ISOOSSplitEvaluation, ...] = tuple(
        de.is_oos_comparison for _, de in active_evals
    ) or (first_de.is_oos_comparison,)

    digests: Tuple[DomainRobustnessDigest, ...] = tuple(
        _robustness_digest_from_eval(de) for _, de in chosen_evals
    )

    primary_m = pts_metrics if pts_metrics is not None else inr_metrics
    net_exp = primary_m.expectancy if primary_m is not None else None
    pf = primary_m.profit_factor if primary_m is not None else None

    oos_pos: Optional[bool] = None
    if is_oos_list:
        last_oos = is_oos_list[-1]
        if last_oos.oos_closed_trades > 0:
            oos_val = (
                last_oos.oos_net_pnl_points
                if last_oos.oos_net_pnl_points is not None
                else last_oos.oos_net_pnl_inr
            )
            oos_pos = (oos_val > 0.0) if oos_val is not None else None

    survives_2x: Optional[bool] = None
    if digests:
        d0 = digests[0]
        if d0.remains_profitable_at_2x_slippage is not None or d0.remains_profitable_at_2x_costs_inr is not None:
            s_ok = True if d0.remains_profitable_at_2x_slippage is not False else False
            c_ok = True if d0.remains_profitable_at_2x_costs_inr is not False else False
            survives_2x = s_ok and c_ok

    verdict, ssc, reasons = classify_evidence_verdict(
        closed_trades=trades_closed,
        config=config,
        data_blocked=not recon_ok,
        net_expectancy=net_exp,
        profit_factor=pf,
        oos_positive=oos_pos,
        survives_2x_stress=survives_2x,
        context_label=dk,
    )

    return DomainPerformanceEvidence(
        accounting_unit_mode=domain_mode,
        provenance_label=first_de.provenance_label,
        is_synthetic_modelled=first_de.is_synthetic_modelled,
        eligible_runs_count=len(evals),
        revalidation_run_ids=tuple(r.revalidation_id for r, _ in evals),
        sessions_evaluated=sessions_total,
        total_signals=signals_total,
        trades_opened=trades_opened,
        trades_closed=trades_closed,
        trades_rejected=trades_rejected,
        trade_frequency_per_session=freq_per_sess,
        max_consecutive_wins=max_consec_wins,
        max_consecutive_losses=max_consec_losses,
        average_holding_duration_minutes=avg_hold_min,
        reconciliation_verified=recon_ok,
        instrument_multiplier_inr_per_point=first_de.analytics_report.performance_summary.instrument_multiplier_inr_per_point,
        instrument_multiplier_documentation=first_de.analytics_report.performance_summary.instrument_multiplier_documentation,
        points_metrics=pts_metrics,
        inr_metrics=inr_metrics,
        points_risk=pts_risk,
        inr_risk=inr_risk,
        is_oos_comparisons=is_oos_list,
        robustness_digests=digests,
        sample_size_classification=ssc,
        verdict=verdict,
        reasons=reasons,
        warnings=tuple(dict.fromkeys(warnings)),
    )


def review_domain_performance(
    *,
    runs: Sequence[HistoricalRevalidationRunResult],
    config: StrategyReviewConfig,
) -> Dict[str, DomainPerformanceEvidence]:
    """Reviews all three separated accounting domains over eligible Step 4.7 runs."""
    eligible_runs = [r for r in runs if is_review_eligible_run(r, config)]
    result: Dict[str, DomainPerformanceEvidence] = {}
    for um in (
        AccountingUnitMode.INDEX_POINTS_ONLY,
        AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR,
        AccountingUnitMode.SYNTHETIC_OPTION_INR_ONLY,
    ):
        ev = _evaluate_single_domain(
            eligible_runs=eligible_runs,
            domain_mode=um,
            config=config,
        )
        if ev is not None:
            result[um.value] = ev
    return result


def build_dimension_breakdown_rows(
    *,
    dimension: str,
    runs: Sequence[HistoricalRevalidationRunResult],
    signal_key_fn: Optional[Callable[[RevalidationSignalRecord], Tuple[str, bool]]],
    trade_key_fn: Callable[[TradeRecord, Optional[RevalidationSignalRecord]], Tuple[str, bool]],
    config: StrategyReviewConfig,
) -> Tuple[BreakdownEvidenceRow, ...]:
    """
    Unified, domain-isolated breakdown builder reused by regime, session, instrument,
    timeframe, direction, ICT setup, entry_reason, and exit_reason reviews.
    """
    eligible_runs = [r for r in runs if is_review_eligible_run(r, config)]
    sig_lookup = build_signal_lookup(runs)

    sig_buckets: Dict[str, List[RevalidationSignalRecord]] = defaultdict(list)
    missing_flags: Dict[str, bool] = defaultdict(bool)

    if signal_key_fn is not None:
        for r in eligible_runs:
            for sig in r.signals:
                key, is_missing = signal_key_fn(sig)
                sig_buckets[key].append(sig)
                if is_missing:
                    missing_flags[key] = True

    trade_buckets: Dict[str, Dict[str, List[TradeRecord]]] = defaultdict(lambda: defaultdict(list))
    prov_by_domain: Dict[str, str] = {}

    for um in (
        AccountingUnitMode.INDEX_POINTS_ONLY,
        AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR,
        AccountingUnitMode.SYNTHETIC_OPTION_INR_ONLY,
    ):
        dk = um.value
        for r in eligible_runs:
            de = r.domain_evaluations.get(dk)
            if de is None:
                continue
            prov_by_domain[dk] = de.provenance_label
            for tr in de.simulation_run.trades:
                if tr.state != TradeLifecycleState.CLOSED:
                    continue
                sig_rec = sig_lookup.get(tr.signal_id)
                key, is_missing = trade_key_fn(tr, sig_rec)
                trade_buckets[key][dk].append(tr)
                if is_missing:
                    missing_flags[key] = True

    all_keys = sorted(set(sig_buckets.keys()) | set(trade_buckets.keys()))
    rows: List[BreakdownEvidenceRow] = []

    for key in all_keys:
        sigs = sig_buckets.get(key, [])
        tmap = trade_buckets.get(key, {})

        buy_ce = sum(1 for s in sigs if s.signal_direction == RevalidationSignalDirection.BUY_CE)
        buy_pe = sum(1 for s in sigs if s.signal_direction == RevalidationSignalDirection.BUY_PE)
        wait_cnt = sum(1 for s in sigs if s.signal_direction == RevalidationSignalDirection.WAIT)
        nt_cnt = sum(1 for s in sigs if s.signal_direction == RevalidationSignalDirection.NO_TRADE)
        elig_cnt = sum(1 for s in sigs if s.entry_eligible)

        pts_trades = tmap.get(AccountingUnitMode.INDEX_POINTS_ONLY.value, [])
        exp_trades = tmap.get(AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR.value, [])
        syn_trades = tmap.get(AccountingUnitMode.SYNTHETIC_OPTION_INR_ONLY.value, [])

        pts_stats: Optional[BucketDomainStats] = None
        if pts_trades:
            pts_stats, _ = build_bucket_domain_stats(
                pts_trades,
                accounting_unit_mode=AccountingUnitMode.INDEX_POINTS_ONLY,
                provenance_label=prov_by_domain[AccountingUnitMode.INDEX_POINTS_ONLY.value],
            )

        exp_pts_stats: Optional[BucketDomainStats] = None
        exp_inr_stats: Optional[BucketDomainStats] = None
        if exp_trades:
            exp_pts_stats, exp_inr_stats = build_bucket_domain_stats(
                exp_trades,
                accounting_unit_mode=AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR,
                provenance_label=prov_by_domain[AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR.value],
            )

        syn_inr_stats: Optional[BucketDomainStats] = None
        if syn_trades:
            _, syn_inr_stats = build_bucket_domain_stats(
                syn_trades,
                accounting_unit_mode=AccountingUnitMode.SYNTHETIC_OPTION_INR_ONLY,
                provenance_label=prov_by_domain[AccountingUnitMode.SYNTHETIC_OPTION_INR_ONLY.value],
            )

        ref_count = len(pts_trades) or len(exp_trades) or len(syn_trades)
        ref_stats = pts_stats or exp_pts_stats or syn_inr_stats
        verdict, ssc, reasons = verdict_for_bucket_stats(
            closed_trades=ref_count,
            stats=ref_stats,
            config=config,
            label=f"{dimension}={key}",
        )

        rows.append(
            BreakdownEvidenceRow(
                dimension=dimension,  # type: ignore[arg-type]
                bucket_key=key,
                total_signals=len(sigs),
                buy_ce_count=buy_ce,
                buy_pe_count=buy_pe,
                wait_count=wait_cnt,
                no_trade_count=nt_cnt,
                eligible_signals=elig_cnt,
                closed_trades_points_domain=len(pts_trades),
                closed_trades_explicit_inr_domain=len(exp_trades),
                closed_trades_synthetic_option_domain=len(syn_trades),
                points_stats=pts_stats,
                explicit_inr_points_stats=exp_pts_stats,
                explicit_inr_stats=exp_inr_stats,
                synthetic_option_inr_stats=syn_inr_stats,
                missing_metadata_flag=bool(missing_flags.get(key, False)),
                sample_size_classification=ssc,
                verdict=verdict,
                reasons=reasons,
            )
        )

    return tuple(rows)


def review_general_dimensions(
    *,
    runs: Sequence[HistoricalRevalidationRunResult],
    config: StrategyReviewConfig,
) -> Dict[str, Tuple[BreakdownEvidenceRow, ...]]:
    """Evaluates instrument, timeframe, direction, entry_reason, and exit_reason breakdowns."""
    def _exit_reason_for_trade(tr: TradeRecord, _sig: Optional[RevalidationSignalRecord]) -> Tuple[str, bool]:
        if tr.final_exit_reason is None:
            return UNKNOWN_LABEL, True
        return clean_metadata_label(tr.final_exit_reason.value)

    def _entry_reason_for_signal(sig: RevalidationSignalRecord) -> Tuple[str, bool]:
        if not sig.entry_eligible:
            return f"{sig.signal_direction.value} ({sig.qualification_status})", False
        return f"{sig.signal_direction.value} ({sig.qualification_status})", False

    def _entry_reason_for_trade(_tr: TradeRecord, sig: Optional[RevalidationSignalRecord]) -> Tuple[str, bool]:
        if sig is None:
            return UNKNOWN_LABEL, True
        return f"{sig.signal_direction.value} ({sig.qualification_status})", False

    return {
        "instrument": build_dimension_breakdown_rows(
            dimension="instrument",
            runs=runs,
            signal_key_fn=lambda s: clean_metadata_label(s.instrument),
            trade_key_fn=lambda tr, _s: clean_metadata_label(tr.instrument),
            config=config,
        ),
        "timeframe": build_dimension_breakdown_rows(
            dimension="timeframe",
            runs=runs,
            signal_key_fn=lambda s: clean_metadata_label(s.primary_timeframe),
            trade_key_fn=lambda tr, _s: clean_metadata_label(tr.timeframe),
            config=config,
        ),
        "direction": build_dimension_breakdown_rows(
            dimension="direction",
            runs=runs,
            signal_key_fn=lambda s: clean_metadata_label(s.signal_direction.value),
            trade_key_fn=lambda tr, s: (
                clean_metadata_label(s.signal_direction.value)
                if s is not None
                else clean_metadata_label(tr.direction.value)
            ),
            config=config,
        ),
        "entry_reason": build_dimension_breakdown_rows(
            dimension="entry_reason",
            runs=runs,
            signal_key_fn=_entry_reason_for_signal,
            trade_key_fn=_entry_reason_for_trade,
            config=config,
        ),
        "exit_reason": build_dimension_breakdown_rows(
            dimension="exit_reason",
            runs=runs,
            signal_key_fn=None,
            trade_key_fn=_exit_reason_for_trade,
            config=config,
        ),
    }

