"""
AIVOLVE Phase 4, Step 4.8 — ICT / SMC & MTF Confluence Evidence Review.

Inspects all 8 ICT/SMC & MTF pillars from frozen Phase 2 & Phase 3 replay outputs:
  1. LIQUIDITY_SWEEPS (`SSL`, `BSL`, `EQL`, `EQH`, liquidity sweep statuses)
  2. BOS
  3. CHOCH_MSS (`CHOCH`, `MSS`)
  4. ORDER_BLOCKS (`ORDER_BLOCK`)
  5. FVG_IFVG (`FVG`, `IFVG`)
  6. PREMIUM_DISCOUNT (`DEALING_RANGE` / premium-discount evidence)
  7. INDUCEMENT (`INDUCEMENT_CONFIRMED` / inducement events)
  8. MTF_CONFLUENCE (Phase 2 MTF score & alignment)

Strict governance:
- ICT score stays None (`UNAVAILABLE` / `NOT_CALIBRATED`)
- Never claims setup profitability without sufficient closed-trade evidence
- Never invents weights, scoring thresholds, or missing alignment labels (`UNKNOWN`)
- Keeps accounting domains strictly isolated per pillar and setup bucket
"""

from __future__ import annotations

import ast
from collections import Counter, defaultdict
from typing import Any, Dict, List, Literal, Optional, Sequence, Set, Tuple

from app.backtesting.analytics_models import BucketDomainStats, UNKNOWN_LABEL
from app.backtesting.revalidation_models import (
    HistoricalRevalidationRunResult,
    RevalidationSignalRecord,
)
from app.backtesting.simulation_models import AccountingUnitMode, TradeLifecycleState, TradeRecord
from app.backtesting.strategy_evidence_models import (
    BreakdownEvidenceRow,
    EvidenceVerdict,
    ICTPillarEvidenceSummary,
    ICTSMCEvidenceReviewResult,
    StrategyReviewConfig,
)
from app.backtesting.strategy_performance_review import (
    build_dimension_breakdown_rows,
    build_signal_lookup,
    clean_metadata_label,
    is_review_eligible_run,
)
from app.backtesting.strategy_verdict_engine import classify_sample_size, verdict_for_bucket_stats
from app.backtesting.time_series_analytics import build_bucket_domain_stats

PillarName = Literal[
    "LIQUIDITY_SWEEPS",
    "BOS",
    "CHOCH_MSS",
    "ORDER_BLOCKS",
    "FVG_IFVG",
    "PREMIUM_DISCOUNT",
    "INDUCEMENT",
    "MTF_CONFLUENCE",
]

PILLAR_ORDER: Tuple[PillarName, ...] = (
    "LIQUIDITY_SWEEPS",
    "BOS",
    "CHOCH_MSS",
    "ORDER_BLOCKS",
    "FVG_IFVG",
    "PREMIUM_DISCOUNT",
    "INDUCEMENT",
    "MTF_CONFLUENCE",
)


def parse_serialized_ict_event(raw: Any) -> Dict[str, Any]:
    """
    Parses persisted Phase 3 evidence strings (typically dict reprs from Step 4.7)
    safely without executing code or inventing missing attributes.
    """
    if isinstance(raw, dict):
        return dict(raw)
    if not isinstance(raw, str):
        return {"raw_text": str(raw), "event_category": UNKNOWN_LABEL}
    text = raw.strip()
    if not text:
        return {"event_category": UNKNOWN_LABEL}
    if text.startswith("{") and text.endswith("}"):
        try:
            parsed = ast.literal_eval(text)
            if isinstance(parsed, dict):
                return parsed
        except (ValueError, SyntaxError):
            pass
    return {"raw_text": text, "event_category": text}


def map_event_to_pillar(ev: Dict[str, Any]) -> Optional[PillarName]:
    """Maps a parsed Phase 3 evidence or conflict record to one of the 8 ICT pillars."""
    cat = str(ev.get("event_category") or ev.get("conflict_type") or "").upper()
    src = str(ev.get("source_module") or "").upper()
    summary = str(ev.get("summary") or ev.get("raw_text") or "").upper()
    combined = f"{cat} {src} {summary}"

    if any(tok in cat for tok in ("SSL", "BSL", "EQL", "EQH", "LIQUIDITY", "SWEEP")) or "LIQUIDITY" in src:
        return "LIQUIDITY_SWEEPS"
    if cat == "BOS" or " BOS" in combined or "BREAK OF STRUCTURE" in combined:
        return "BOS"
    if any(tok in cat for tok in ("CHOCH", "MSS")) or "CHOCH" in combined or "MARKET STRUCTURE SHIFT" in combined:
        return "CHOCH_MSS"
    if "ORDER_BLOCK" in cat or cat == "OB" or "OB_" in cat or "ORDERBLOCK" in src or "ORDER BLOCK" in combined:
        return "ORDER_BLOCKS"
    if "IFVG" in cat or "FVG" in cat or "FAIR VALUE GAP" in combined:
        return "FVG_IFVG"
    if "DEALING_RANGE" in cat or "PREMIUM" in cat or "DISCOUNT" in cat or "PREMIUM" in combined or "DISCOUNT" in combined:
        return "PREMIUM_DISCOUNT"
    if "INDUCEMENT" in cat or "INDUCEMENT" in src or "IDM" in cat:
        return "INDUCEMENT"
    if any(tok in combined for tok in ("MTF", "CONFLUENCE", "CROSS_TIMEFRAME", "HTF_ITF")):
        return "MTF_CONFLUENCE"
    return None


def review_ict_setup_breakdown(
    *,
    runs: Sequence[HistoricalRevalidationRunResult],
    config: StrategyReviewConfig,
) -> Tuple[BreakdownEvidenceRow, ...]:
    """Evaluates signal and closed-trade evidence grouped by Phase 3 alignment setup label."""

    def _setup_for_signal(sig: RevalidationSignalRecord) -> Tuple[str, bool]:
        return clean_metadata_label(sig.phase3_alignment)

    def _setup_for_trade(_tr: TradeRecord, sig: Optional[RevalidationSignalRecord]) -> Tuple[str, bool]:
        if sig is None:
            return UNKNOWN_LABEL, True
        return clean_metadata_label(sig.phase3_alignment)

    return build_dimension_breakdown_rows(
        dimension="ict_smc_setup",
        runs=runs,
        signal_key_fn=_setup_for_signal,
        trade_key_fn=_setup_for_trade,
        config=config,
    )


def review_ict_smc_evidence(
    *,
    runs: Sequence[HistoricalRevalidationRunResult],
    config: StrategyReviewConfig,
) -> ICTSMCEvidenceReviewResult:
    """
    Reviews all 8 ICT/SMC & MTF pillars across eligible Step 4.7 signals and linked closed trades,
    keeping `ict_score=None` (`UNAVAILABLE / NOT_CALIBRATED`) and never inventing thresholds/weights.
    """
    eligible_runs = [r for r in runs if is_review_eligible_run(r, config)]
    sig_lookup = build_signal_lookup(eligible_runs)

    alignment_counts: Counter[str] = Counter()
    conflict_type_counts: Counter[str] = Counter()
    pillar_events_count: Counter[PillarName] = Counter()
    pillar_bullish_count: Counter[PillarName] = Counter()
    pillar_bearish_count: Counter[PillarName] = Counter()
    pillar_conflict_count: Counter[PillarName] = Counter()
    pillar_signal_ids: Dict[PillarName, Set[str]] = defaultdict(set)
    pillar_eligible_signal_ids: Dict[PillarName, Set[str]] = defaultdict(set)
    pillar_statuses: Dict[PillarName, Counter[str]] = defaultdict(Counter)

    total_signals = 0
    total_eligible = 0

    for run in eligible_runs:
        for sig in run.signals:
            total_signals += 1
            if sig.entry_eligible:
                total_eligible += 1
            align_lbl, _ = clean_metadata_label(sig.phase3_alignment)
            alignment_counts[align_lbl] += 1

            # Phase 2 MTF confluence presence on every evaluated replay point when numeric score exists
            if sig.phase2_confluence_score is not None:
                pillar_events_count["MTF_CONFLUENCE"] += 1
                pillar_signal_ids["MTF_CONFLUENCE"].add(sig.signal_id)
                if sig.entry_eligible:
                    pillar_eligible_signal_ids["MTF_CONFLUENCE"].add(sig.signal_id)
                bias = (sig.phase2_directional_bias or "").upper()
                if "BULL" in bias:
                    pillar_bullish_count["MTF_CONFLUENCE"] += 1
                elif "BEAR" in bias:
                    pillar_bearish_count["MTF_CONFLUENCE"] += 1
                pillar_statuses["MTF_CONFLUENCE"][bias or UNKNOWN_LABEL] += 1

            for side_tag, ev_list in (("BULLISH", sig.phase3_bullish_evidence), ("BEARISH", sig.phase3_bearish_evidence)):
                for raw_ev in ev_list:
                    parsed = parse_serialized_ict_event(raw_ev)
                    pillar = map_event_to_pillar(parsed)
                    if pillar is None:
                        continue
                    pillar_events_count[pillar] += 1
                    pillar_signal_ids[pillar].add(sig.signal_id)
                    if sig.entry_eligible:
                        pillar_eligible_signal_ids[pillar].add(sig.signal_id)
                    if side_tag == "BULLISH":
                        pillar_bullish_count[pillar] += 1
                    else:
                        pillar_bearish_count[pillar] += 1
                    status_lbl = str(parsed.get("status") or UNKNOWN_LABEL)
                    pillar_statuses[pillar][status_lbl] += 1

            for raw_cf in sig.phase3_conflicts:
                parsed_cf = parse_serialized_ict_event(raw_cf)
                cf_type = str(
                    parsed_cf.get("conflict_type")
                    or parsed_cf.get("event_category")
                    or parsed_cf.get("raw_text")
                    or UNKNOWN_LABEL
                )
                conflict_type_counts[cf_type] += 1
                pillar = map_event_to_pillar(parsed_cf)
                if pillar is not None:
                    pillar_conflict_count[pillar] += 1

    # Link CLOSED trades cleanly per isolated accounting domain by signal_id
    trades_by_domain_pillar: Dict[PillarName, Dict[str, List[TradeRecord]]] = defaultdict(lambda: defaultdict(list))
    prov_by_domain: Dict[str, str] = {}

    for run in eligible_runs:
        for dk, de in run.domain_evaluations.items():
            prov_by_domain.setdefault(dk, de.provenance_label)
            for tr in de.simulation_run.trades:
                if tr.state != TradeLifecycleState.CLOSED:
                    continue
                sig = sig_lookup.get(tr.signal_id)
                if sig is None:
                    continue
                present_pillars = {
                    p for p in PILLAR_ORDER if sig.signal_id in pillar_signal_ids[p]
                }
                for p in present_pillars:
                    trades_by_domain_pillar[p][dk].append(tr)

    pillar_summaries: List[ICTPillarEvidenceSummary] = []
    for pillar in PILLAR_ORDER:
        pts_list = trades_by_domain_pillar[pillar].get(AccountingUnitMode.INDEX_POINTS_ONLY.value, [])
        exp_list = trades_by_domain_pillar[pillar].get(AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR.value, [])
        syn_list = trades_by_domain_pillar[pillar].get(AccountingUnitMode.SYNTHETIC_OPTION_INR_ONLY.value, [])

        pts_stats, _ = (
            build_bucket_domain_stats(
                pts_list,
                accounting_unit_mode=AccountingUnitMode.INDEX_POINTS_ONLY,
                provenance_label=prov_by_domain.get(AccountingUnitMode.INDEX_POINTS_ONLY.value, "BACKTEST_REVALIDATION"),
            )
            if pts_list
            else (None, None)
        )
        _, exp_inr_stats = (
            build_bucket_domain_stats(
                exp_list,
                accounting_unit_mode=AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR,
                provenance_label=prov_by_domain.get(
                    AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR.value, "BACKTEST_REVALIDATION"
                ),
            )
            if exp_list
            else (None, None)
        )
        _, syn_inr_stats = (
            build_bucket_domain_stats(
                syn_list,
                accounting_unit_mode=AccountingUnitMode.SYNTHETIC_OPTION_INR_ONLY,
                provenance_label=prov_by_domain.get(
                    AccountingUnitMode.SYNTHETIC_OPTION_INR_ONLY.value, "SYNTHETIC_MODELLED_OPTION_PNL"
                ),
            )
            if syn_list
            else (None, None)
        )

        closed_cnt = len(pts_list) if pts_list else len(exp_list)
        verdict, ssc, reasons = verdict_for_bucket_stats(
            stats=pts_stats or exp_inr_stats,
            closed_trades=closed_cnt,
            config=config,
            label=f"pillar={pillar}",
        )
        if pillar == "MTF_CONFLUENCE" and total_signals > 0:
            reasons = reasons + (
                "Phase 2 MTF confluence weights remain frozen; Step 4.8 does not alter or reweight MTF scoring.",
            )

        pillar_summaries.append(
            ICTPillarEvidenceSummary(
                pillar_name=pillar,
                events_observed_count=int(pillar_events_count[pillar]),
                bullish_events_count=int(pillar_bullish_count[pillar]),
                bearish_events_count=int(pillar_bearish_count[pillar]),
                conflicts_observed_count=int(pillar_conflict_count[pillar]),
                signals_present_count=len(pillar_signal_ids[pillar]),
                eligible_signals_present_count=len(pillar_eligible_signal_ids[pillar]),
                status_breakdown=dict(sorted(pillar_statuses[pillar].items())),
                closed_trades_count=closed_cnt,
                points_stats=pts_stats,
                explicit_inr_stats=exp_inr_stats,
                synthetic_option_inr_stats=syn_inr_stats,
                sample_size_classification=ssc,
                verdict=verdict,
                reasons=reasons,
            )
        )

    max_closed = max((p.closed_trades_count for p in pillar_summaries), default=0)
    if total_signals == 0:
        agg_verdict = EvidenceVerdict.DATA_QUALITY_BLOCKED
        agg_reasons = ("No eligible Step 4.7 signals available to audit ICT/SMC evidence.",)
    elif max_closed < config.min_trades_sufficient:
        agg_verdict = EvidenceVerdict.INSUFFICIENT_EVIDENCE
        agg_reasons = (
            f"Maximum closed trades linked to any ICT/SMC pillar is {max_closed} (< {config.min_trades_sufficient}); "
            "ICT score remains UNAVAILABLE / NOT_CALIBRATED and no setup profitability is claimed.",
        )
    else:
        agg_verdict = EvidenceVerdict.WEAK_EVIDENCE
        agg_reasons = (
            "ICT/SMC pillar audit completed with ICT score preserved as UNAVAILABLE / NOT_CALIBRATED; "
            "requires out-of-sample attribution beyond raw descriptive pillar counts before calibration.",
        )

    return ICTSMCEvidenceReviewResult(
        total_signals_inspected=total_signals,
        total_eligible_signals_inspected=total_eligible,
        alignment_distribution=dict(sorted(alignment_counts.items())),
        conflict_type_distribution=dict(sorted(conflict_type_counts.items())),
        pillars=tuple(pillar_summaries),
        verdict=agg_verdict,
        reasons=agg_reasons,
    )

