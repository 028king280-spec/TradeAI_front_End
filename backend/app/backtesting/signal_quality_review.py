"""
AIVOLVE Phase 4, Step 4.8 — Signal Quality & Chronological No-Lookahead Review.

Audits BUY_CE / BUY_PE / WAIT / NO_TRADE frequencies, entry eligibility funnel,
rejection reasons, entry/exit reason distributions, missing metadata counts, and
chronological timestamp ordering across eligible Step 4.7 runs.
"""

from __future__ import annotations

from collections import Counter
from typing import Dict, List, Optional, Sequence

from app.backtesting.analytics_models import UNKNOWN_LABEL, parse_ist_datetime
from app.backtesting.revalidation_models import (
    HistoricalRevalidationRunResult,
    RevalidationSignalDirection,
)
from app.backtesting.simulation_models import AccountingUnitMode, TradeLifecycleState
from app.backtesting.strategy_evidence_models import (
    EvidenceVerdict,
    SignalQualityReviewResult,
    StrategyReviewConfig,
)
from app.backtesting.strategy_performance_review import (
    build_signal_lookup,
    clean_metadata_label,
    is_review_eligible_run,
)


def review_signal_quality(
    *,
    runs: Sequence[HistoricalRevalidationRunResult],
    config: StrategyReviewConfig,
) -> SignalQualityReviewResult:
    """Evaluates signal action mix, missing metadata, eligibility funnel, and strict chronology."""
    eligible_runs = [r for r in runs if is_review_eligible_run(r, config)]
    sig_lookup = build_signal_lookup(eligible_runs)

    action_counts: Counter[str] = Counter()
    rejection_counts: Counter[str] = Counter()
    entry_reason_counts: Counter[str] = Counter()
    exit_reason_counts: Counter[str] = Counter()
    missing_counts: Counter[str] = Counter()

    total_signals = 0
    eligible_signals = 0
    ineligible_signals = 0
    chronology_violations = 0

    executed_pts_signal_ids = set()
    closed_pts_trades = 0

    for run in eligible_runs:
        prev_dt = None
        for sig in run.signals:
            total_signals += 1
            action_counts[sig.signal_direction.value] += 1

            # Missing metadata checks (never fabricated)
            _, miss_reg = clean_metadata_label(sig.market_regime)
            _, miss_sess = clean_metadata_label(sig.session_bucket)
            _, miss_align = clean_metadata_label(sig.phase3_alignment)
            _, miss_qual = clean_metadata_label(sig.qualification_status)
            if miss_reg:
                missing_counts["market_regime"] += 1
            if miss_sess:
                missing_counts["session_bucket"] += 1
            if miss_align:
                missing_counts["phase3_alignment"] += 1
            if miss_qual:
                missing_counts["qualification_status"] += 1

            # Chronological ordering & no-lookahead verification
            try:
                cur_dt = parse_ist_datetime(sig.as_of_time_ist, "as_of_time_ist")
                if prev_dt is not None and cur_dt < prev_dt:
                    chronology_violations += 1
                prev_dt = cur_dt
            except Exception:
                chronology_violations += 1

            entry_lbl = f"{sig.signal_direction.value} ({sig.qualification_status})"
            entry_reason_counts[entry_lbl] += 1

            if sig.entry_eligible:
                eligible_signals += 1
            else:
                ineligible_signals += 1
                if sig.rejection_reasons:
                    for rr in sig.rejection_reasons:
                        lbl, _ = clean_metadata_label(rr)
                        rejection_counts[lbl] += 1
                else:
                    rejection_counts[UNKNOWN_LABEL] += 1

        pts_eval = run.domain_evaluations.get(AccountingUnitMode.INDEX_POINTS_ONLY.value)
        if pts_eval is not None:
            for tr in pts_eval.simulation_run.trades:
                executed_pts_signal_ids.add(tr.signal_id)
                if tr.state == TradeLifecycleState.CLOSED:
                    closed_pts_trades += 1
                    ex_lbl = tr.final_exit_reason.value if tr.final_exit_reason is not None else UNKNOWN_LABEL
                    exit_reason_counts[ex_lbl] += 1

                # Trade cannot open earlier than signal availability timestamp
                # (Next-bar open starts at bar N close == signal_available_at_ist; strict < indicates lookahead)
                if tr.entry_time_ist:
                    try:
                        entry_dt = parse_ist_datetime(tr.entry_time_ist, "entry_time_ist")
                        avail_dt = parse_ist_datetime(tr.signal_available_at_ist, "signal_available_at_ist")
                        if entry_dt < avail_dt:
                            chronology_violations += 1
                    except Exception:
                        chronology_violations += 1

    # Count eligible signals that did not execute a simulated trade
    eligible_ids = {s.signal_id for r in eligible_runs for s in r.signals if s.entry_eligible}
    unexecuted_eligible = len(eligible_ids - executed_pts_signal_ids)

    qual_pct = (eligible_signals / total_signals * 100.0) if total_signals > 0 else 0.0
    nt_pct = (
        action_counts.get(RevalidationSignalDirection.NO_TRADE.value, 0) / total_signals * 100.0
        if total_signals > 0
        else 0.0
    )
    wait_pct = (
        action_counts.get(RevalidationSignalDirection.WAIT.value, 0) / total_signals * 100.0
        if total_signals > 0
        else 0.0
    )

    chron_ok = total_signals > 0 and chronology_violations == 0

    reasons: List[str] = []
    if total_signals == 0:
        verdict = EvidenceVerdict.DATA_QUALITY_BLOCKED
        reasons.append("No signals found across eligible Step 4.7 revalidation runs.")
    elif chronology_violations > 0:
        verdict = EvidenceVerdict.DATA_QUALITY_BLOCKED
        reasons.append(f"Detected {chronology_violations} chronological or lookahead violations in signal/trade timestamps.")
    elif closed_pts_trades < config.min_trades_sufficient:
        verdict = EvidenceVerdict.INSUFFICIENT_EVIDENCE
        reasons.append(
            f"Evaluated {total_signals} signals ({eligible_signals} eligible, {qual_pct:.2f}% qualification rate); "
            f"only {closed_pts_trades} executed closed trades (< {config.min_trades_sufficient})."
        )
    else:
        verdict = EvidenceVerdict.MODERATE_EVIDENCE
        reasons.append(
            f"Evaluated {total_signals} signals cleanly with 0 chronological violations and {closed_pts_trades} closed trades."
        )

    return SignalQualityReviewResult(
        total_signals=total_signals,
        action_distribution=dict(sorted(action_counts.items())),
        eligible_signals=eligible_signals,
        ineligible_signals=ineligible_signals,
        qualification_rate_pct=round(qual_pct, 4),
        no_trade_rate_pct=round(nt_pct, 4),
        wait_rate_pct=round(wait_pct, 4),
        rejection_reason_distribution=dict(sorted(rejection_counts.items())),
        entry_reason_distribution=dict(sorted(entry_reason_counts.items())),
        exit_reason_distribution=dict(sorted(exit_reason_counts.items())),
        missing_metadata_counts=dict(sorted(missing_counts.items())),
        executed_trades_count_points=len(executed_pts_signal_ids),
        unexecuted_eligible_signals_count=unexecuted_eligible,
        chronological_no_lookahead_verified=chron_ok,
        chronology_violations_count=chronology_violations,
        verdict=verdict,
        reasons=tuple(reasons),
    )

