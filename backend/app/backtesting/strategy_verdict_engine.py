"""
AIVOLVE Phase 4, Step 4.8 — Deterministic Strategy Evidence Verdict Engine.

Classifies available historical research evidence (`STRONG_EVIDENCE`,
`MODERATE_EVIDENCE`, `WEAK_EVIDENCE`, `INSUFFICIENT_EVIDENCE`,
`DATA_QUALITY_BLOCKED`) strictly without auto-optimization or strategy mutation.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from app.backtesting.analytics_models import BucketDomainStats, DomainPerformanceMetrics
from app.backtesting.revalidation_models import (
    EligibilityClassification,
    HistoricalRevalidationRunResult,
    ISOOSSplitEvaluation,
    RevalidationStatus,
)
from app.backtesting.robustness_models import SampleSizeClassification
from app.backtesting.simulation_models import AccountingUnitMode
from app.backtesting.strategy_evidence_models import (
    BreakdownEvidenceRow,
    DimensionAssessment,
    DomainPerformanceEvidence,
    EvidenceVerdict,
    ICTSMCEvidenceReviewResult,
    RESEARCH_CLASSIFICATION_DISCLAIMER,
    SignalQualityReviewResult,
    StrategyReviewConfig,
    StrategyVerdictSummary,
)


def classify_sample_size(
    closed_trades_count: int,
    config: StrategyReviewConfig,
) -> SampleSizeClassification:
    """Maps closed-trade count cleanly to Step 4.5 SampleSizeClassification."""
    if closed_trades_count < config.min_trades_sufficient:
        return SampleSizeClassification.INSUFFICIENT_SAMPLE
    if closed_trades_count < config.min_trades_moderate:
        return SampleSizeClassification.LIMITED_EVIDENCE
    if closed_trades_count < config.min_trades_strong:
        return SampleSizeClassification.MODERATE_SAMPLE
    return SampleSizeClassification.LARGER_SAMPLE


def _extract_primary_perf(
    *,
    expectancy: Optional[float],
    profit_factor: Optional[float],
    oos_expectancy_positive: Optional[bool],
    survives_cost_stress: Optional[bool],
) -> Tuple[Optional[float], Optional[float], Optional[bool], Optional[bool]]:
    return expectancy, profit_factor, oos_expectancy_positive, survives_cost_stress


def classify_evidence_verdict(
    *,
    closed_trades: int,
    config: StrategyReviewConfig,
    data_blocked: bool = False,
    net_expectancy: Optional[float] = None,
    profit_factor: Optional[float] = None,
    oos_positive: Optional[bool] = None,
    survives_2x_stress: Optional[bool] = None,
    context_label: str = "evidence",
) -> Tuple[EvidenceVerdict, SampleSizeClassification, Tuple[str, ...]]:
    """
    Deterministic research verdict governance:
    - Never upgrades < min_trades_sufficient (default 30) beyond INSUFFICIENT_EVIDENCE.
    - Returns DATA_QUALITY_BLOCKED when underlying runs/data are blocked or invalid.
    """
    ssc = classify_sample_size(closed_trades, config)
    reasons: List[str] = []

    if data_blocked:
        reasons.append(f"{context_label}: underlying dataset or governance gate is blocked/rejected.")
        return EvidenceVerdict.DATA_QUALITY_BLOCKED, ssc, tuple(reasons)

    if closed_trades < config.min_trades_sufficient:
        reasons.append(
            f"{context_label}: {closed_trades} closed trade(s) < minimum sufficient threshold "
            f"({config.min_trades_sufficient}); statistical reliability cannot be claimed ({ssc.value})."
        )
        return EvidenceVerdict.INSUFFICIENT_EVIDENCE, ssc, tuple(reasons)

    if net_expectancy is None or net_expectancy <= 0.0:
        reasons.append(
            f"{context_label}: net expectancy ({net_expectancy}) is non-positive across {closed_trades} trades."
        )
        return EvidenceVerdict.WEAK_EVIDENCE, ssc, tuple(reasons)

    if profit_factor is not None and profit_factor <= 1.0:
        reasons.append(f"{context_label}: profit factor ({profit_factor:.4f}) <= 1.0.")
        return EvidenceVerdict.WEAK_EVIDENCE, ssc, tuple(reasons)

    if config.require_positive_oos_expectancy and oos_positive is False:
        reasons.append(f"{context_label}: out-of-sample expectancy degraded to non-positive.")
        return EvidenceVerdict.WEAK_EVIDENCE, ssc, tuple(reasons)

    if survives_2x_stress is False:
        reasons.append(f"{context_label}: fails 2x slippage or transaction-cost stress preservation.")
        return EvidenceVerdict.WEAK_EVIDENCE, ssc, tuple(reasons)

    if closed_trades >= config.min_trades_strong and oos_positive is True and survives_2x_stress is True:
        reasons.append(
            f"{context_label}: {closed_trades} closed trades (>= {config.min_trades_strong}), "
            f"positive expectancy ({net_expectancy:.4f}), OOS preservation, and 2x stress survival."
        )
        return EvidenceVerdict.STRONG_EVIDENCE, ssc, tuple(reasons)

    if closed_trades >= config.min_trades_moderate and oos_positive is not False:
        reasons.append(
            f"{context_label}: {closed_trades} closed trades (>= {config.min_trades_moderate}), "
            f"positive expectancy ({net_expectancy:.4f}) without OOS sign collapse."
        )
        return EvidenceVerdict.MODERATE_EVIDENCE, ssc, tuple(reasons)

    reasons.append(
        f"{context_label}: {closed_trades} closed trades ({ssc.value}) below moderate threshold "
        f"({config.min_trades_moderate}) or missing full OOS/2x stress confirmation."
    )
    return EvidenceVerdict.WEAK_EVIDENCE, ssc, tuple(reasons)


def verdict_for_bucket_stats(
    *,
    closed_trades: int,
    stats: Optional[BucketDomainStats],
    config: StrategyReviewConfig,
    label: str,
) -> Tuple[EvidenceVerdict, SampleSizeClassification, Tuple[str, ...]]:
    """Applies unified evidence verdict rules to any domain-specific BucketDomainStats."""
    if stats is None or closed_trades <= 0:
        return classify_evidence_verdict(
            closed_trades=0,
            config=config,
            context_label=label,
        )
    return classify_evidence_verdict(
        closed_trades=closed_trades,
        config=config,
        net_expectancy=stats.expectancy,
        profit_factor=stats.profit_factor,
        oos_positive=None,
        survives_2x_stress=None,
        context_label=label,
    )


def _worst_verdict(verdicts: Iterable[EvidenceVerdict]) -> EvidenceVerdict:
    rank = {
        EvidenceVerdict.DATA_QUALITY_BLOCKED: 0,
        EvidenceVerdict.INSUFFICIENT_EVIDENCE: 1,
        EvidenceVerdict.WEAK_EVIDENCE: 2,
        EvidenceVerdict.MODERATE_EVIDENCE: 3,
        EvidenceVerdict.STRONG_EVIDENCE: 4,
    }
    vals = list(verdicts)
    if not vals:
        return EvidenceVerdict.INSUFFICIENT_EVIDENCE
    return min(vals, key=lambda v: rank[v])


def _best_usable_verdict(verdicts: Iterable[EvidenceVerdict]) -> EvidenceVerdict:
    rank = {
        EvidenceVerdict.DATA_QUALITY_BLOCKED: 0,
        EvidenceVerdict.INSUFFICIENT_EVIDENCE: 1,
        EvidenceVerdict.WEAK_EVIDENCE: 2,
        EvidenceVerdict.MODERATE_EVIDENCE: 3,
        EvidenceVerdict.STRONG_EVIDENCE: 4,
    }
    vals = list(verdicts)
    if not vals:
        return EvidenceVerdict.INSUFFICIENT_EVIDENCE
    return max(vals, key=lambda v: rank[v])


def _assess_breakdown_group(
    *,
    area: str,
    rows: Sequence[BreakdownEvidenceRow],
    config: StrategyReviewConfig,
    extra_limitations: Sequence[str] = (),
) -> DimensionAssessment:
    if not rows:
        return DimensionAssessment(
            area=area,
            verdict=EvidenceVerdict.INSUFFICIENT_EVIDENCE,
            sample_size_classification=SampleSizeClassification.INSUFFICIENT_SAMPLE,
            reasons=(f"{area}: zero evaluated signals or trades present.",),
            limitations=tuple(extra_limitations),
        )
    max_trades = max(
        max(
            r.closed_trades_points_domain,
            r.closed_trades_explicit_inr_domain,
            r.closed_trades_synthetic_option_domain,
        )
        for r in rows
    )
    ssc = classify_sample_size(max_trades, config)
    non_blocked = [r.verdict for r in rows if r.verdict != EvidenceVerdict.DATA_QUALITY_BLOCKED]
    agg_verdict = _best_usable_verdict(non_blocked) if non_blocked else EvidenceVerdict.DATA_QUALITY_BLOCKED
    reasons = [f"{r.bucket_key}: signals={r.total_signals}, trades={r.closed_trades_points_domain}, verdict={r.verdict.value}" for r in rows]
    return DimensionAssessment(
        area=area,
        verdict=agg_verdict,
        sample_size_classification=ssc,
        reasons=tuple(reasons[:8]),
        limitations=tuple(extra_limitations),
    )


def evaluate_strategy_verdicts(
    *,
    runs: Sequence[HistoricalRevalidationRunResult],
    domain_evidence: Dict[str, DomainPerformanceEvidence],
    regime_rows: Sequence[BreakdownEvidenceRow],
    session_rows: Sequence[BreakdownEvidenceRow],
    instrument_rows: Sequence[BreakdownEvidenceRow],
    ict_review: ICTSMCEvidenceReviewResult,
    signal_quality: SignalQualityReviewResult,
    config: StrategyReviewConfig,
    known_limitations: Sequence[str],
) -> StrategyVerdictSummary:
    """Produces complete transparent Step 4.8 verdict summary with zero strategy mutation."""
    verified_runs = [
        r
        for r in runs
        if r.eligibility_decision.eligibility == EligibilityClassification.VERIFIED_FULL_SESSION_ELIGIBLE
        and r.status in (RevalidationStatus.COMPLETED, RevalidationStatus.NO_ELIGIBLE_SIGNALS)
    ]
    partial_runs = [
        r for r in runs if r.status == RevalidationStatus.COMPLETED_RESEARCH_ONLY_PARTIAL
    ]
    blocked_or_locked_runs = [
        r
        for r in runs
        if r.status in (RevalidationStatus.REJECTED_DATASET_QUALITY, RevalidationStatus.GOVERNANCE_LOCKOUT)
    ]

    # Genuine historical evidence anchors on INDEX_POINTS_ONLY / EXPLICIT_INR (not synthetic BS alone)
    pts_dom = domain_evidence.get(AccountingUnitMode.INDEX_POINTS_ONLY.value)
    exp_dom = domain_evidence.get(AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR.value)
    syn_dom = domain_evidence.get(AccountingUnitMode.SYNTHETIC_OPTION_INR_ONLY.value)

    primary_dom = pts_dom or exp_dom or syn_dom
    total_closed = primary_dom.trades_closed if primary_dom is not None else 0
    overall_ssc = classify_sample_size(total_closed, config)

    if not verified_runs and not (config.include_partial_research_only and partial_runs):
        overall_verdict = EvidenceVerdict.DATA_QUALITY_BLOCKED
        overall_reasons = (
            "No eligible VERIFIED or allowed PARTIAL revalidation runs were available for evaluation.",
        )
    elif primary_dom is None:
        overall_verdict = EvidenceVerdict.INSUFFICIENT_EVIDENCE
        overall_reasons = ("No closed-trade accounting domain evaluation was completed.",)
    else:
        overall_verdict = primary_dom.verdict
        if total_closed < config.min_trades_sufficient and overall_verdict in (
            EvidenceVerdict.STRONG_EVIDENCE,
            EvidenceVerdict.MODERATE_EVIDENCE,
        ):
            overall_verdict = EvidenceVerdict.INSUFFICIENT_EVIDENCE
        reasons_buf = [
            f"Evaluated {len(verified_runs)} VERIFIED run(s), {len(partial_runs)} PARTIAL research-only run(s), "
            f"and {len(blocked_or_locked_runs)} REJECTED/LOCKED run(s).",
            *primary_dom.reasons,
        ]
        if syn_dom is not None:
            reasons_buf.append(
                f"SYNTHETIC_OPTION_INR_ONLY ({syn_dom.trades_closed} trades) is research-only via Black-Scholes; "
                f"real historical options remain BLOCKED."
            )
        overall_reasons = tuple(reasons_buf)

    # Instrument-wise assessments (including blocked/locked instruments)
    inst_assessments: List[DimensionAssessment] = []
    seen_instruments = set()
    for row in instrument_rows:
        seen_instruments.add(row.bucket_key)
        inst_runs = [r for r in runs if r.config.instrument == row.bucket_key]
        all_blocked = bool(inst_runs) and all(
            r.status in (RevalidationStatus.REJECTED_DATASET_QUALITY, RevalidationStatus.GOVERNANCE_LOCKOUT)
            for r in inst_runs
        )
        v = EvidenceVerdict.DATA_QUALITY_BLOCKED if all_blocked else row.verdict
        inst_assessments.append(
            DimensionAssessment(
                area=f"Instrument:{row.bucket_key}",
                verdict=v,
                sample_size_classification=row.sample_size_classification,
                reasons=row.reasons,
                limitations=tuple(
                    r.eligibility_decision.rejection_reasons[0]
                    for r in inst_runs
                    if r.eligibility_decision.rejection_reasons
                ),
            )
        )
    for r in blocked_or_locked_runs:
        if r.config.instrument not in seen_instruments:
            seen_instruments.add(r.config.instrument)
            inst_assessments.append(
                DimensionAssessment(
                    area=f"Instrument:{r.config.instrument}",
                    verdict=EvidenceVerdict.DATA_QUALITY_BLOCKED,
                    sample_size_classification=SampleSizeClassification.INSUFFICIENT_SAMPLE,
                    reasons=(
                        f"Status={r.status.value}, Eligibility={r.eligibility_decision.eligibility.value}.",
                    ),
                    limitations=r.eligibility_decision.rejection_reasons,
                )
            )

    regime_assessment = _assess_breakdown_group(
        area="MarketRegime",
        rows=regime_rows,
        config=config,
    )
    session_assessment = _assess_breakdown_group(
        area="TradingSession",
        rows=session_rows,
        config=config,
    )
    ict_assessment = DimensionAssessment(
        area="ICT_SMC_Setup",
        verdict=ict_review.verdict,
        sample_size_classification=overall_ssc,
        reasons=ict_review.reasons,
        limitations=(
            "Phase 3 ICT/SMC confluence_score remains None (UNAVAILABLE / NOT_CALIBRATED).",
            "No ICT setup profitability is claimed without >= 30 closed trades.",
        ),
    )

    risk_reasons: List[str] = []
    if pts_dom and pts_dom.points_risk is not None:
        risk_reasons.append(
            f"INDEX_POINTS_ONLY max_dd={pts_dom.points_risk.max_drawdown:.2f} pts, "
            f"max_consec_losses={pts_dom.max_consecutive_losses}."
        )
    if exp_dom and exp_dom.inr_risk is not None:
        risk_reasons.append(
            f"INDEX_POINTS_AND_EXPLICIT_INR max_dd=INR {exp_dom.inr_risk.max_drawdown:.2f} "
            f"({exp_dom.inr_risk.max_drawdown_pct}%)."
        )
    if syn_dom and syn_dom.inr_risk is not None:
        risk_reasons.append(
            f"SYNTHETIC_OPTION_INR_ONLY (BS research-only) max_dd=INR {syn_dom.inr_risk.max_drawdown:.2f}."
        )
    if not risk_reasons:
        risk_reasons.append("No closed trades available to evaluate realized drawdown.")

    risk_assessment = DimensionAssessment(
        area="RiskAndDrawdown",
        verdict=overall_verdict if total_closed > 0 else EvidenceVerdict.INSUFFICIENT_EVIDENCE,
        sample_size_classification=overall_ssc,
        reasons=tuple(risk_reasons),
        limitations=(
            "Small-sample drawdown estimates (< 30 trades) have high tail uncertainty.",
        ),
    )

    dq_limitations = tuple(dict.fromkeys(known_limitations))
    ss_limitations = (
        f"Closed trades = {total_closed} ({overall_ssc.value}); minimum sufficient threshold = "
        f"{config.min_trades_sufficient}, moderate = {config.min_trades_moderate}, strong = {config.min_trades_strong}.",
        "Statistical significance is explicitly NOT claimed (`statistical_significance_claimed=False`).",
        f"Actionable qualification rate = {signal_quality.qualification_rate_pct:.2f}% "
        f"({signal_quality.eligible_signals}/{signal_quality.total_signals} signals).",
    )

    return StrategyVerdictSummary(
        overall_verdict=overall_verdict,
        overall_sample_size=overall_ssc,
        research_classification_disclaimer=RESEARCH_CLASSIFICATION_DISCLAIMER,
        overall_reasons=overall_reasons,
        instrument_assessments=tuple(inst_assessments),
        regime_assessment=regime_assessment,
        session_assessment=session_assessment,
        ict_smc_assessment=ict_assessment,
        risk_and_drawdown_assessment=risk_assessment,
        data_quality_limitations=dq_limitations,
        sample_size_limitations=ss_limitations,
    )

