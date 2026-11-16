"""
AIVOLVE Phase 4 Step 4.4 — Strategy & Setup Attribution Analytics Engine.

Groups closed-trade performance across explicit metadata dimensions:
- ict_smc_setup
- direction
- timeframe
- market_regime
- session
- entry_reason
- exit_reason

Strict governance guarantees:
- Missing metadata NEVER inferred or backfilled from timestamps or trade direction (`UNKNOWN`).
- Does NOT introduce calibrated ICT/SMC scores (`ict_score_status='UNAVAILABLE'`,
  `ict_calibration_status='NOT_CALIBRATED'`).
- Reuses `build_bucket_domain_stats` and enforces AccountingUnitMode purity.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from app.backtesting.analytics_models import (
    StrategyAnalyticsResult,
    StrategyBreakdownBucket,
    TradeEvaluationMetadata,
    UNKNOWN_LABEL,
    validate_run_domain_integrity,
)
from app.backtesting.models import ReplayPointResult, ReplayRunRecord
from app.backtesting.risk_analytics import sort_closed_trades
from app.backtesting.simulation_models import AccountingUnitMode, SimulationRunResult, SimulationSignal, TradeRecord
from app.backtesting.time_series_analytics import build_bucket_domain_stats


def _clean_label(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped if stripped else None


@dataclass(frozen=True)
class _ResolvedTradeLabels:
    ict_smc_setup: str
    direction: str
    timeframe: str
    market_regime: str
    session: str
    entry_reason: str
    exit_reason: str


def _extract_session_from_replay(rpt: Optional[ReplayPointResult]) -> Optional[str]:
    if rpt is None or not isinstance(rpt.report, dict):
        return None
    sess_ctx = rpt.report.get("session_context")
    if isinstance(sess_ctx, dict):
        for key in ("current_session", "session_phase", "session"):
            lbl = _clean_label(sess_ctx.get(key))
            if lbl:
                return lbl
    return _clean_label(rpt.report.get("session"))


def _extract_regime_from_replay(rpt: Optional[ReplayPointResult]) -> Optional[str]:
    if rpt is None or not isinstance(rpt.report, dict):
        return None
    return _clean_label(rpt.report.get("market_regime"))


def _resolve_labels_for_trade(
    trade: TradeRecord,
    meta: Optional[TradeEvaluationMetadata],
    sig: Optional[SimulationSignal],
    rpt: Optional[ReplayPointResult],
) -> _ResolvedTradeLabels:
    ict_setup = (
        _clean_label(meta.ict_smc_setup if meta else None)
        or _clean_label(rpt.overall_alignment if rpt else None)
        or UNKNOWN_LABEL
    )
    market_regime = (
        _clean_label(meta.market_regime if meta else None)
        or _extract_regime_from_replay(rpt)
        or UNKNOWN_LABEL
    )
    session = (
        _clean_label(meta.session if meta else None)
        or _extract_session_from_replay(rpt)
        or UNKNOWN_LABEL
    )
    entry_reason = (
        _clean_label(meta.entry_reason if meta else None)
        or _clean_label(sig.notes if sig else None)
        or UNKNOWN_LABEL
    )
    exit_reason = _clean_label(trade.final_exit_reason.value if trade.final_exit_reason else None) or UNKNOWN_LABEL

    return _ResolvedTradeLabels(
        ict_smc_setup=ict_setup,
        direction=trade.direction.value,
        timeframe=trade.timeframe,
        market_regime=market_regime,
        session=session,
        entry_reason=entry_reason,
        exit_reason=exit_reason,
    )


def _aggregate_strategy_dimension(
    labeled_trades: Sequence[Tuple[TradeRecord, _ResolvedTradeLabels]],
    *,
    dimension: str,
    accounting_unit_mode: AccountingUnitMode,
    provenance_label: str,
) -> Tuple[StrategyBreakdownBucket, ...]:
    grouped: Dict[str, List[TradeRecord]] = defaultdict(list)
    for trade, labels in labeled_trades:
        cat = getattr(labels, dimension)
        grouped[cat].append(trade)

    buckets: List[StrategyBreakdownBucket] = []
    for cat in sorted(grouped.keys()):
        group = grouped[cat]
        pts_stats, inr_stats = build_bucket_domain_stats(
            group,
            accounting_unit_mode=accounting_unit_mode,
            provenance_label=provenance_label,
        )
        buckets.append(
            StrategyBreakdownBucket(
                dimension=dimension,  # type: ignore[arg-type]
                category=cat,
                accounting_unit_mode=accounting_unit_mode,
                provenance_label=provenance_label,
                trades_count=len(group),
                points_stats=pts_stats,
                inr_stats=inr_stats,
            )
        )
    return tuple(buckets)


class StrategyAnalyticsEngine:
    """Stateless deterministic engine grouping trade performance without fabricating missing tags."""

    def evaluate_run(
        self,
        run: SimulationRunResult,
        *,
        trade_metadata: Optional[Dict[str, TradeEvaluationMetadata]] = None,
        signals: Optional[Sequence[SimulationSignal]] = None,
        replay_run: Optional[ReplayRunRecord] = None,
    ) -> StrategyAnalyticsResult:
        """Evaluates closed trades across explicit setup, direction, timeframe, regime, session, and exit dimensions."""
        validate_run_domain_integrity(run)
        closed = sort_closed_trades(run.trades)

        sig_by_id: Dict[str, SimulationSignal] = {s.signal_id: s for s in (signals or ())}
        rpt_by_id: Dict[str, ReplayPointResult] = {}
        ict_score_status = "UNAVAILABLE"
        ict_calibration_status = "NOT_CALIBRATED"

        if replay_run is not None:
            for pt in replay_run.points:
                if (
                    pt.confluence_score is not None
                    or pt.score_status != "UNAVAILABLE"
                    or pt.calibration_status != "NOT_CALIBRATED"
                ):
                    raise ValueError(
                        "GOVERNANCE_VIOLATION: Frozen Phase 3 replay must preserve UNAVAILABLE / NOT_CALIBRATED ICT score status."
                    )
                rpt_by_id[pt.report_id] = pt

        meta_map = trade_metadata or {}
        labeled: List[Tuple[TradeRecord, _ResolvedTradeLabels]] = []
        unknown_counts: Dict[str, int] = {
            "ict_smc_setup": 0,
            "market_regime": 0,
            "session": 0,
            "entry_reason": 0,
            "exit_reason": 0,
        }

        for t in closed:
            meta = meta_map.get(t.trade_id) or meta_map.get(t.signal_id)
            sig = sig_by_id.get(t.signal_id)
            rpt = rpt_by_id.get(sig.source_report_id) if (sig and sig.source_report_id) else None
            labels = _resolve_labels_for_trade(t, meta=meta, sig=sig, rpt=rpt)
            labeled.append((t, labels))
            for dim_key in unknown_counts:
                if getattr(labels, dim_key) == UNKNOWN_LABEL:
                    unknown_counts[dim_key] += 1

        um = run.accounting_unit_mode
        prov = run.provenance_label

        return StrategyAnalyticsResult(
            accounting_unit_mode=um,
            provenance_label=prov,
            is_synthetic_modelled=run.is_synthetic_modelled,
            total_closed_trades=len(closed),
            ict_score_status=ict_score_status,
            ict_calibration_status=ict_calibration_status,
            by_ict_setup=_aggregate_strategy_dimension(
                labeled, dimension="ict_smc_setup", accounting_unit_mode=um, provenance_label=prov
            ),
            by_direction=_aggregate_strategy_dimension(
                labeled, dimension="direction", accounting_unit_mode=um, provenance_label=prov
            ),
            by_timeframe=_aggregate_strategy_dimension(
                labeled, dimension="timeframe", accounting_unit_mode=um, provenance_label=prov
            ),
            by_market_regime=_aggregate_strategy_dimension(
                labeled, dimension="market_regime", accounting_unit_mode=um, provenance_label=prov
            ),
            by_session=_aggregate_strategy_dimension(
                labeled, dimension="session", accounting_unit_mode=um, provenance_label=prov
            ),
            by_entry_reason=_aggregate_strategy_dimension(
                labeled, dimension="entry_reason", accounting_unit_mode=um, provenance_label=prov
            ),
            by_exit_reason=_aggregate_strategy_dimension(
                labeled, dimension="exit_reason", accounting_unit_mode=um, provenance_label=prov
            ),
            unknown_metadata_counts=unknown_counts,
        )

