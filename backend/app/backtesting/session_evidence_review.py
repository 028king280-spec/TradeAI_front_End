"""
AIVOLVE Phase 4, Step 4.8 — Trading Session Evidence Review.

Evaluates signal and domain-isolated closed-trade performance across IST market
session buckets (`OPENING`, `MORNING`, `MIDDAY`, `AFTERNOON`, `CLOSING`),
preserving missing labels strictly as `UNKNOWN` and reporting Step 4.6
session-completeness exclusions cleanly without fabricating data.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

from app.backtesting.analytics_models import (
    UNKNOWN_LABEL,
    classify_ist_session,
    parse_ist_datetime,
)
from app.backtesting.revalidation_models import (
    HistoricalRevalidationRunResult,
    RevalidationSignalRecord,
)
from app.backtesting.simulation_models import TradeRecord
from app.backtesting.strategy_evidence_models import (
    BreakdownEvidenceRow,
    StrategyReviewConfig,
)
from app.backtesting.strategy_performance_review import (
    build_dimension_breakdown_rows,
    clean_metadata_label,
    is_review_eligible_run,
)


def _session_key_for_signal(sig: RevalidationSignalRecord) -> Tuple[str, bool]:
    label, missing = clean_metadata_label(sig.session_bucket)
    if not missing:
        return label, False
    return UNKNOWN_LABEL, True


def _session_key_for_trade(
    tr: TradeRecord,
    sig: Optional[RevalidationSignalRecord],
) -> Tuple[str, bool]:
    if sig is not None:
        label, missing = clean_metadata_label(sig.session_bucket)
        if not missing:
            return label, False
        return UNKNOWN_LABEL, True
    raw_ts = tr.entry_time_ist or tr.signal_available_at_ist
    if not raw_ts:
        return UNKNOWN_LABEL, True
    try:
        dt_ist = parse_ist_datetime(raw_ts, "trade_session_ts")
        return classify_ist_session(dt_ist).value, True
    except Exception:
        return UNKNOWN_LABEL, True


def review_session_evidence(
    *,
    runs: Sequence[HistoricalRevalidationRunResult],
    config: StrategyReviewConfig,
) -> Tuple[Tuple[BreakdownEvidenceRow, ...], Dict[str, int]]:
    """
    Produces domain-isolated `trading_session` breakdown rows plus summary counts of
    sessions evaluated vs incomplete sessions excluded by Step 4.7 dataset gates.
    """
    rows = build_dimension_breakdown_rows(
        dimension="trading_session",
        runs=runs,
        signal_key_fn=_session_key_for_signal,
        trade_key_fn=_session_key_for_trade,
        config=config,
    )

    sessions_evaluated = 0
    excluded_sessions = 0
    eligible_runs_count = 0
    for r in runs:
        if not is_review_eligible_run(r, config):
            continue
        eligible_runs_count += 1
        sessions_evaluated += int(r.summary_metrics.sessions_evaluated)
        excluded_sessions += len(r.eligibility_decision.excluded_incomplete_sessions)

    session_coverage_summary: Dict[str, int] = {
        "eligible_runs_count": eligible_runs_count,
        "sessions_evaluated_total": sessions_evaluated,
        "excluded_incomplete_sessions_total": excluded_sessions,
    }
    return rows, session_coverage_summary

