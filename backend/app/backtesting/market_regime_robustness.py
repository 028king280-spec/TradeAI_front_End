"""
AIVOLVE Phase 4 Step 4.5 — Module D: Market Regime Robustness Engine.

Classifies closed trades across deterministic market regimes:
- TRENDING
- RANGING
- HIGH_VOLATILITY
- LOW_VOLATILITY
- UNKNOWN_OR_INSUFFICIENT_DATA

Rules:
- Consumes validated explicit metadata, causal ReplayRunRecord snapshots
  (as_of_time_ist <= signal_available_at_ist), or strictly causal completed OHLCV
  bars (bar.close_time_ist <= signal_available_at_ist) using canonical Wilder ADX/ATR.
- ZERO future bar leakage.
- Never invents regime labels when metadata or causal history is insufficient.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from datetime import datetime
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from app.backtesting.analytics_models import (
    TradeEvaluationMetadata,
    parse_ist_datetime,
    validate_run_domain_integrity,
)
from app.backtesting.configuration import normalize_instrument, normalize_timeframe
from app.backtesting.data_integrity import DataIntegrityAuditor
from app.backtesting.fill_engine import CompletedBar, extract_completed_bars
from app.backtesting.models import IntegrityStatus, ReplayPointResult, ReplayRunRecord
from app.backtesting.risk_analytics import sort_closed_trades
from app.backtesting.robustness_models import (
    MarketRegimeBucketResult,
    MarketRegimeConfig,
    MarketRegimeRobustnessResult,
    RobustnessRegimeBucket,
    RobustnessStatus,
    evaluate_closed_trade_slice_metrics,
)
from app.backtesting.simulation_models import SimulationRunResult, SimulationStatus, TradeRecord
from app.options.candle_processor import (
    calculate_adx_wilder,
    calculate_atr_wilder,
    calculate_true_range,
)

_EXPLICIT_REGIME_MAP: Dict[str, RobustnessRegimeBucket] = {
    "TRENDING": RobustnessRegimeBucket.TRENDING,
    "BULLISH_TREND": RobustnessRegimeBucket.TRENDING,
    "BEARISH_TREND": RobustnessRegimeBucket.TRENDING,
    "TREND": RobustnessRegimeBucket.TRENDING,
    "RANGING": RobustnessRegimeBucket.RANGING,
    "SIDEWAYS": RobustnessRegimeBucket.RANGING,
    "RANGE": RobustnessRegimeBucket.RANGING,
    "CHOP": RobustnessRegimeBucket.RANGING,
    "CONSOLIDATION": RobustnessRegimeBucket.RANGING,
    "HIGH_VOLATILITY": RobustnessRegimeBucket.HIGH_VOLATILITY,
    "VOLATILITY_EXPANSION": RobustnessRegimeBucket.HIGH_VOLATILITY,
    "EXTREME_VOLATILITY": RobustnessRegimeBucket.HIGH_VOLATILITY,
    "HIGH": RobustnessRegimeBucket.HIGH_VOLATILITY,
    "EXTREME": RobustnessRegimeBucket.HIGH_VOLATILITY,
    "LOW_VOLATILITY": RobustnessRegimeBucket.LOW_VOLATILITY,
    "VOLATILITY_CONTRACTION": RobustnessRegimeBucket.LOW_VOLATILITY,
    "LOW": RobustnessRegimeBucket.LOW_VOLATILITY,
    "NO_TRADE": RobustnessRegimeBucket.UNKNOWN_OR_INSUFFICIENT_DATA,
    "DATA_UNAVAILABLE": RobustnessRegimeBucket.UNKNOWN_OR_INSUFFICIENT_DATA,
    "UNKNOWN": RobustnessRegimeBucket.UNKNOWN_OR_INSUFFICIENT_DATA,
    "UNAVAILABLE": RobustnessRegimeBucket.UNKNOWN_OR_INSUFFICIENT_DATA,
}


def _map_explicit_regime_label(raw_label: Optional[str]) -> Optional[RobustnessRegimeBucket]:
    if not raw_label or not str(raw_label).strip():
        return None
    norm = str(raw_label).strip().upper().replace(" ", "_")
    return _EXPLICIT_REGIME_MAP.get(norm)


def _extract_replay_regime_label(pt: ReplayPointResult) -> Optional[str]:
    rep = pt.report or {}
    for key in ("market_regime", "regime"):
        val = rep.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    ms = rep.get("market_state")
    if isinstance(ms, Mapping):
        val = ms.get("regime") or ms.get("market_regime")
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def _prepare_causal_indicators(
    *,
    candles_df: pd.DataFrame,
    instrument: str,
    timeframe: str,
    cfg: MarketRegimeConfig,
) -> Tuple[
    bool,
    List[datetime],
    List[float],
    List[Optional[float]],
    List[str],
]:
    """
    Audits candles_df fail-closed and precomputes strictly causal ATR/ADX arrays
    aligned by `bar.close_time_ist` (each index `i` uses ONLY bars `0..i`).
    """
    warnings: List[str] = []
    auditor = DataIntegrityAuditor(strict_missing_intervals=False, require_volume_column=False)
    report = auditor.audit_dataframe(
        candles_df,
        instrument=normalize_instrument(instrument),
        timeframe=normalize_timeframe(timeframe),
        require_all_completed=True,
        check_missing_intervals=False,
    )
    if not report.is_valid or report.status != IntegrityStatus.PASSED:
        warnings.append(
            f"CAUSAL_REGIME_DATA_REJECTED: Candles failed integrity checks ({'; '.join(report.rejected_reasons)}); "
            "falling back to explicit metadata or UNKNOWN_OR_INSUFFICIENT_DATA."
        )
        return False, [], [], [], warnings

    try:
        bars: List[CompletedBar] = extract_completed_bars(candles_df, timeframe=normalize_timeframe(timeframe))
    except Exception as exc:
        warnings.append(f"CAUSAL_REGIME_BAR_EXTRACTION_FAILED: {exc}")
        return False, [], [], [], warnings

    if not bars:
        warnings.append("CAUSAL_REGIME_EMPTY_BARS: Zero completed bars available for regime classification.")
        return False, [], [], [], warnings

    high_arr = np.asarray([b.high for b in bars], dtype=float)
    low_arr = np.asarray([b.low for b in bars], dtype=float)
    close_arr = np.asarray([b.close for b in bars], dtype=float)

    tr_arr = np.asarray(calculate_true_range(high_arr, low_arr, close_arr), dtype=float)
    atr_arr = np.asarray(calculate_atr_wilder(tr_arr, period=cfg.atr_period), dtype=float)
    adx_arr, _, _ = calculate_adx_wilder(high_arr, low_arr, close_arr, period=cfg.adx_period)

    close_times: List[datetime] = [b.close_time_ist for b in bars]
    adx_vals: List[float] = [float(v) if math.isfinite(float(v)) else float("nan") for v in adx_arr.tolist()]

    # Strictly causal ATR baseline ratio using ONLY completed bars [0..i]
    atr_list: List[float] = [float(v) if math.isfinite(float(v)) else float("nan") for v in atr_arr.tolist()]
    vol_ratios: List[Optional[float]] = []
    valid_atr_history: List[float] = []
    min_baseline = max(10, cfg.atr_period)

    for cur_atr in atr_list:
        if not math.isfinite(cur_atr):
            vol_ratios.append(None)
            continue
        valid_atr_history.append(cur_atr)
        window = valid_atr_history[-cfg.volatility_lookback_bars :]
        if len(window) < min_baseline:
            vol_ratios.append(None)
            continue
        med = float(pd.Series(window, dtype="float64").median())
        vol_ratios.append((cur_atr / med) if med > 1e-12 else None)

    return True, close_times, adx_vals, vol_ratios, warnings


def _classify_causal_bar_state(
    *,
    bar_idx: int,
    adx_vals: Sequence[float],
    vol_ratios: Sequence[Optional[float]],
    cfg: MarketRegimeConfig,
) -> Optional[RobustnessRegimeBucket]:
    if bar_idx < 0:
        return None
    adx_v = adx_vals[bar_idx]
    vol_r = vol_ratios[bar_idx]
    if not math.isfinite(adx_v):
        return None

    if vol_r is not None and vol_r >= cfg.high_vol_atr_ratio_threshold:
        return RobustnessRegimeBucket.HIGH_VOLATILITY
    if adx_v >= cfg.adx_trend_threshold:
        return RobustnessRegimeBucket.TRENDING
    if vol_r is not None and vol_r <= cfg.low_vol_atr_ratio_threshold:
        return RobustnessRegimeBucket.LOW_VOLATILITY
    if adx_v < cfg.adx_range_threshold:
        return RobustnessRegimeBucket.RANGING
    # Neutral ADX transition zone [adx_range_threshold, adx_trend_threshold)
    return RobustnessRegimeBucket.RANGING


class MarketRegimeRobustnessEngine:
    """Stateless deterministic engine evaluating strategy stability across market regimes."""

    def evaluate(
        self,
        run: SimulationRunResult,
        *,
        candles_df: Optional[pd.DataFrame] = None,
        replay_run: Optional[ReplayRunRecord] = None,
        trade_metadata: Optional[Mapping[str, TradeEvaluationMetadata]] = None,
        config: Optional[MarketRegimeConfig] = None,
    ) -> MarketRegimeRobustnessResult:
        validate_run_domain_integrity(run)
        cfg = config or MarketRegimeConfig()
        um = run.accounting_unit_mode

        if run.status != SimulationStatus.COMPLETED:
            return MarketRegimeRobustnessResult(
                status=RobustnessStatus.RUN_NOT_COMPLETED,
                accounting_unit_mode=um,
                provenance_label=run.provenance_label,
                is_synthetic_modelled=run.is_synthetic_modelled,
                config=cfg,
                total_closed_trades=0,
                classified_trades_count=0,
                unknown_or_insufficient_trades_count=0,
                no_future_bar_leakage_verified=True,
                warnings=(f"RUN_NOT_COMPLETED: SimulationRunResult status is '{run.status.value}'.",),
            )

        closed_trades = sort_closed_trades(run.trades)
        if not closed_trades:
            return MarketRegimeRobustnessResult(
                status=RobustnessStatus.NO_TRADES,
                accounting_unit_mode=um,
                provenance_label=run.provenance_label,
                is_synthetic_modelled=run.is_synthetic_modelled,
                config=cfg,
                total_closed_trades=0,
                classified_trades_count=0,
                unknown_or_insufficient_trades_count=0,
                no_future_bar_leakage_verified=True,
                warnings=("NO_CLOSED_TRADES: Market regime robustness requires at least one closed trade.",),
            )

        warnings: List[str] = []

        # Prepare sorted causal replay snapshots if provided
        replay_pts_sorted: List[Tuple[datetime, ReplayPointResult]] = []
        replay_times: List[datetime] = []
        if replay_run is not None and replay_run.points:
            for pt in replay_run.points:
                replay_pts_sorted.append((parse_ist_datetime(pt.as_of_time_ist, "replay.as_of_time_ist"), pt))
            replay_pts_sorted.sort(key=lambda item: item[0])
            replay_times = [item[0] for item in replay_pts_sorted]

        # Prepare strictly causal OHLCV indicators if candles_df provided
        ohlcv_ok = False
        close_times: List[datetime] = []
        adx_vals: List[float] = []
        vol_ratios: List[Optional[float]] = []
        if candles_df is not None and not candles_df.empty:
            ohlcv_ok, close_times, adx_vals, vol_ratios, prep_warnings = _prepare_causal_indicators(
                candles_df=candles_df,
                instrument=run.instrument,
                timeframe=run.timeframe,
                cfg=cfg,
            )
            warnings.extend(prep_warnings)

        grouped: Dict[RobustnessRegimeBucket, List[TradeRecord]] = {}
        grouped_sources: Dict[RobustnessRegimeBucket, str] = {}
        meta_map = trade_metadata or {}
        classified_count = 0
        unknown_count = 0

        for trade in closed_trades:
            sig_dt = parse_ist_datetime(trade.signal_available_at_ist, f"trade[{trade.trade_id}].signal_available_at_ist")
            assigned: Optional[RobustnessRegimeBucket] = None
            source_label = "UNKNOWN_MISSING"

            # 1. Explicit non-inferred TradeEvaluationMetadata
            meta = meta_map.get(trade.trade_id) or meta_map.get(trade.signal_id)
            if meta is not None and meta.market_regime:
                mapped = _map_explicit_regime_label(meta.market_regime)
                if mapped is None:
                    warnings.append(
                        f"UNRECOGNIZED_EXPLICIT_REGIME: '{meta.market_regime}' on trade '{trade.trade_id}' mapped to UNKNOWN_OR_INSUFFICIENT_DATA."
                    )
                    assigned = RobustnessRegimeBucket.UNKNOWN_OR_INSUFFICIENT_DATA
                    source_label = "UNKNOWN_MISSING"
                elif mapped == RobustnessRegimeBucket.UNKNOWN_OR_INSUFFICIENT_DATA:
                    assigned = RobustnessRegimeBucket.UNKNOWN_OR_INSUFFICIENT_DATA
                    source_label = "UNKNOWN_MISSING"
                else:
                    assigned = mapped
                    source_label = "EXPLICIT_METADATA"

            # 2. Causal ReplayRunRecord snapshot <= signal_available_at_ist
            if assigned is None and replay_times:
                pos = bisect_right(replay_times, sig_dt) - 1
                if pos >= 0:
                    _, pt = replay_pts_sorted[pos]
                    raw_rep_label = _extract_replay_regime_label(pt)
                    mapped_rep = _map_explicit_regime_label(raw_rep_label)
                    if mapped_rep is not None and mapped_rep != RobustnessRegimeBucket.UNKNOWN_OR_INSUFFICIENT_DATA:
                        assigned = mapped_rep
                        source_label = "REPLAY_ARTIFACT"

            # 3. Strictly causal completed OHLCV bars (close_time_ist <= sig_dt)
            if assigned is None and ohlcv_ok and close_times:
                bar_pos = bisect_right(close_times, sig_dt) - 1
                if bar_pos >= 0:
                    assert close_times[bar_pos] <= sig_dt
                    causal_bucket = _classify_causal_bar_state(
                        bar_idx=bar_pos,
                        adx_vals=adx_vals,
                        vol_ratios=vol_ratios,
                        cfg=cfg,
                    )
                    if causal_bucket is not None:
                        assigned = causal_bucket
                        source_label = "CAUSAL_OHLCV_INDICATORS"

            # 4. Never fabricate missing regimes
            if assigned is None:
                assigned = RobustnessRegimeBucket.UNKNOWN_OR_INSUFFICIENT_DATA
                source_label = "UNKNOWN_MISSING"

            if assigned == RobustnessRegimeBucket.UNKNOWN_OR_INSUFFICIENT_DATA:
                unknown_count += 1
            else:
                classified_count += 1

            grouped.setdefault(assigned, []).append(trade)
            if assigned not in grouped_sources:
                grouped_sources[assigned] = source_label
            elif grouped_sources[assigned] != source_label and source_label != "UNKNOWN_MISSING":
                grouped_sources[assigned] = source_label

        ordered_buckets: List[MarketRegimeBucketResult] = []
        for reg in RobustnessRegimeBucket:
            t_list = grouped.get(reg)
            if not t_list:
                continue
            pts_m, inr_m = evaluate_closed_trade_slice_metrics(
                closed_trades=t_list,
                reference_run=run,
                slice_prefix=f"REGIME-{reg.value}",
            )
            is_sparse = len(t_list) < cfg.min_trades_per_bucket
            if is_sparse:
                warnings.append(
                    f"SPARSE_REGIME_BUCKET: Regime '{reg.value}' contains only {len(t_list)} trade(s) (< {cfg.min_trades_per_bucket})."
                )
            ordered_buckets.append(
                MarketRegimeBucketResult(
                    regime=reg,
                    classification_source=grouped_sources.get(reg, "UNKNOWN_MISSING"),  # type: ignore[arg-type]
                    trades_count=len(t_list),
                    is_sparse_bucket=is_sparse,
                    points_metrics=pts_m,
                    inr_metrics=inr_m,
                    trade_ids=tuple(t.trade_id for t in t_list),
                )
            )

        classified_buckets = [b for b in ordered_buckets if b.regime != RobustnessRegimeBucket.UNKNOWN_OR_INSUFFICIENT_DATA]

        def _bucket_net(b: MarketRegimeBucketResult) -> float:
            if b.inr_metrics is not None:
                return b.inr_metrics.net_pnl
            assert b.points_metrics is not None
            return b.points_metrics.net_pnl

        best_reg: Optional[RobustnessRegimeBucket] = None
        worst_reg: Optional[RobustnessRegimeBucket] = None
        if classified_buckets:
            best_reg = max(classified_buckets, key=_bucket_net).regime
            worst_reg = min(classified_buckets, key=_bucket_net).regime

        overall_status = RobustnessStatus.COMPLETED
        if classified_count == 0:
            overall_status = RobustnessStatus.INSUFFICIENT_DATA
            warnings.append(
                "ALL_TRADES_UNCLASSIFIED: No trades had explicit regime metadata or sufficient causal bar history (>= 2*ADX period)."
            )

        return MarketRegimeRobustnessResult(
            status=overall_status,
            accounting_unit_mode=um,
            provenance_label=run.provenance_label,
            is_synthetic_modelled=run.is_synthetic_modelled,
            config=cfg,
            total_closed_trades=len(closed_trades),
            classified_trades_count=classified_count,
            unknown_or_insufficient_trades_count=unknown_count,
            no_future_bar_leakage_verified=True,
            buckets=tuple(ordered_buckets),
            best_regime_by_net_pnl=best_reg,
            worst_regime_by_net_pnl=worst_reg,
            warnings=tuple(dict.fromkeys(warnings)),
        )

