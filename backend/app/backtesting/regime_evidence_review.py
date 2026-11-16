"""
AIVOLVE Phase 4, Step 4.8 — Market Regime Evidence Review.

Evaluates signal and domain-isolated closed-trade performance broken down by
Phase 2 `market_regime` (missing/blank preserved strictly as `UNKNOWN`) and
confirms Step 4.5 causal regime no-future-bar-leakage status.
"""

from __future__ import annotations

from typing import Optional, Sequence, Tuple

from app.backtesting.analytics_models import UNKNOWN_LABEL
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


def _regime_key_for_signal(sig: RevalidationSignalRecord) -> Tuple[str, bool]:
    return clean_metadata_label(sig.market_regime)


def _regime_key_for_trade(
    _tr: TradeRecord,
    sig: Optional[RevalidationSignalRecord],
) -> Tuple[str, bool]:
    if sig is None:
        return UNKNOWN_LABEL, True
    return clean_metadata_label(sig.market_regime)


def review_regime_evidence(
    *,
    runs: Sequence[HistoricalRevalidationRunResult],
    config: StrategyReviewConfig,
) -> Tuple[Tuple[BreakdownEvidenceRow, ...], bool]:
    """
    Produces domain-isolated breakdown rows for `market_regime` and returns whether
    all eligible Step 4.5 regime evaluations verified causal no-future-bar leakage.
    """
    rows = build_dimension_breakdown_rows(
        dimension="market_regime",
        runs=runs,
        signal_key_fn=_regime_key_for_signal,
        trade_key_fn=_regime_key_for_trade,
        config=config,
    )

    causal_checks = []
    for run in runs:
        if not is_review_eligible_run(run, config):
            continue
        for de in run.domain_evaluations.values():
            causal_checks.append(bool(de.robustness_report.market_regime_robustness.no_future_bar_leakage_verified))

    all_causal_verified = bool(causal_checks) and all(causal_checks)
    return rows, all_causal_verified

