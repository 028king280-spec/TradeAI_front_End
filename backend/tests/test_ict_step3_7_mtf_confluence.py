"""
AIVOLVE Phase 3 Step 3.7 — Multi-Timeframe ICT/SMC Confluence Engine Test Suite.

Covers all 26 mandatory unit, integration, causality, governance, fail-closed,
and determinism verification scenarios without mutating production state.
"""

from __future__ import annotations

import ast
import inspect
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from app.options.ict_smc import (
    MTF_ENGINE_VERSION,
    MTF_TIMEFRAME_ORDER,
    TIMEFRAME_ROLES,
    DEFAULT_MAX_EVIDENCE_AGE_MINUTES,
    AlignmentClassification,
    ConflictType,
    ConflictSeverity,
    MTFConfluenceConfiguration,
    TimeframeEvidenceBundle,
    EvidenceSummaryItem,
    ConflictRecord,
    TimeframeConfluenceReport,
    MTFConfluenceReport,
    MTFConfluenceEngine,
    normalize_mtf_timeframe,
    generate_deterministic_mtf_id,
)
from app.options.ict_smc.ict_models import (
    EventDirection,
    FVGEvidence,
    FVGEvent,
    ICTEvent,
    ICTEventType,
    LiquidityEvent,
    LiquidityLifecycleState,
    LiquidityPool,
    LiquidityType,
    MarketStructureEvent,
    MarketStructureEvidence,
    OrderBlockEvent,
    OrderBlockEvidence,
    StructuralSwingType,
    TrendBias,
)
from app.options.ict_smc.market_structure import TimeframeStructureReport
from app.options.ict_smc.order_block_engine import TimeframeOrderBlockReport
from app.options.ict_smc.fvg_engine import TimeframeFVGReport
from app.options.ict_smc.premium_discount_engine import (
    DealingRange,
    DealingRangeStatus,
    InducementEvent,
    InducementEvidence,
    InducementStatus,
    TimeframePremiumDiscountReport,
    ZoneClassification,
)
from app.options.ict_smc.session_engine import (
    MissingCandleInterval,
    SessionClassification,
    SessionConfiguration,
    SessionEvent,
    SessionEventKind,
    SessionPhaseStatus,
    TimeframeSessionReport,
)


IST = ZoneInfo("Asia/Kolkata")


def _ist(hour: int, minute: int, day: int = 11, month: int = 11, year: int = 2026) -> datetime:
    """Builds an IST datetime on a valid 2026 NSE trading day (2026-11-11 Wed default)."""
    return datetime(year, month, day, hour, minute, tzinfo=IST)


def _tf_close_offset(tf: str) -> timedelta:
    return {
        "1h": timedelta(minutes=60),
        "15m": timedelta(minutes=15),
        "5m": timedelta(minutes=5),
        "3m": timedelta(minutes=3),
        "1m": timedelta(minutes=1),
    }[tf]


def _make_structure_event(
    event_id: str,
    tf: str,
    direction: EventDirection,
    event_time: datetime,
    available_at: Optional[datetime] = None,
    index: str = "NIFTY 50",
    event_type: ICTEventType = ICTEventType.BOS,
    status: LiquidityLifecycleState = LiquidityLifecycleState.CONFIRMED,
    invalidated_at: Optional[datetime] = None,
    data_quality: str = "VERIFIED_LIVE",
    level: float = 24250.0,
) -> MarketStructureEvent:
    avail = available_at or (event_time + _tf_close_offset(tf))
    ev = MarketStructureEvidence(
        broken_level=level,
        broken_swing_id=f"SW-{tf}-{event_id}",
        broken_swing_type=StructuralSwingType.HH if direction == EventDirection.BULLISH else StructuralSwingType.LL,
        broken_swing_time=event_time - timedelta(minutes=15),
        break_candle_id=f"C-{tf}-{event_id}",
        break_candle_time=event_time,
        break_candle_open=level - 5.0 if direction == EventDirection.BULLISH else level + 5.0,
        break_candle_high=level + 20.0,
        break_candle_low=level - 20.0,
        break_candle_close=level + 12.0 if direction == EventDirection.BULLISH else level - 12.0,
        penetration_depth_pts=12.0,
        is_body_close=True,
        displacement_confirmed=True,
    )
    return MarketStructureEvent(
        event_id=event_id,
        index=index,
        event_type=event_type,
        direction=direction,
        timeframe=tf,
        broken_level=level,
        event_status=status,
        event_time=event_time,
        available_at=avail,
        created_at=avail,
        confirmed_at=avail,
        invalidated_at=invalidated_at,
        data_quality=data_quality,
        evidence=ev,
    )


def _make_ict_event(
    event_id: str,
    tf: str,
    event_type: ICTEventType,
    direction: EventDirection,
    event_time: datetime,
    available_at: Optional[datetime] = None,
    index: str = "NIFTY 50",
    status: LiquidityLifecycleState = LiquidityLifecycleState.CONFIRMED,
    invalidated_at: Optional[datetime] = None,
    data_quality: str = "VERIFIED_LIVE",
) -> ICTEvent:
    avail = available_at or (event_time + _tf_close_offset(tf))
    return ICTEvent(
        event_id=event_id,
        index=index,
        event_type=event_type,
        direction=direction,
        timeframe=tf,
        price_level=24250.0,
        zone_high=24260.0,
        zone_low=24240.0,
        event_status=status,
        event_time=event_time,
        available_at=avail,
        created_at=avail,
        confirmed_at=avail,
        invalidated_at=invalidated_at,
        data_quality=data_quality,
    )


def _make_liquidity_event(
    event_id: str,
    tf: str,
    direction: EventDirection,
    event_time: datetime,
    available_at: Optional[datetime] = None,
    index: str = "NIFTY 50",
    status: LiquidityLifecycleState = LiquidityLifecycleState.RECLAIMED,
    liq_type: LiquidityType = LiquidityType.SSL,
    data_quality: str = "VERIFIED_LIVE",
) -> LiquidityEvent:
    avail = available_at or (event_time + _tf_close_offset(tf))
    return LiquidityEvent(
        event_id=event_id,
        pool_id=f"POOL-{tf}-{event_id}",
        index=index,
        event_type=ICTEventType.LIQUIDITY_RECLAIM,
        liquidity_type=liq_type,
        direction=direction,
        timeframe=tf,
        level=24200.0,
        price_level=24200.0,
        trigger_candle_id=f"C-{event_id}",
        penetration_price=24196.0 if direction == EventDirection.BULLISH else 24204.0,
        close_price=24205.0 if direction == EventDirection.BULLISH else 24195.0,
        penetration_depth_pts=4.0,
        event_time=event_time,
        available_at=avail,
        created_at=avail,
        confirmed_at=avail,
        is_wick_sweep=True,
        is_candle_close_breakout=False,
        is_reclaimed=True,
        status=status,
        source_data_quality=data_quality,
    )


def _make_ob_event(
    event_id: str,
    tf: str,
    direction: EventDirection,
    event_time: datetime,
    available_at: Optional[datetime] = None,
    index: str = "NIFTY 50",
    status: LiquidityLifecycleState = LiquidityLifecycleState.IDENTIFIED,
    invalidated_at: Optional[datetime] = None,
    data_quality: str = "VERIFIED_LIVE",
) -> OrderBlockEvent:
    avail = available_at or (event_time + _tf_close_offset(tf))
    ev = OrderBlockEvidence(
        zone_high=24240.0,
        zone_low=24220.0,
        mean_threshold=24230.0,
        body_high=24238.0,
        body_low=24222.0,
        origin_candle_id=f"C-OB-{event_id}",
        origin_candle_time=event_time,
        origin_candle_open=24235.0,
        origin_candle_high=24240.0,
        origin_candle_low=24220.0,
        origin_candle_close=24225.0,
        source_structure_event_id=f"ST-{event_id}",
        source_structure_type="BOS",
        invalidation_condition="CLOSE_BELOW_LOW" if direction == EventDirection.BULLISH else "CLOSE_ABOVE_HIGH",
    )
    return OrderBlockEvent(
        event_id=event_id,
        index=index,
        event_type=ICTEventType.ORDER_BLOCK,
        direction=direction,
        timeframe=tf,
        zone_high=24240.0,
        zone_low=24220.0,
        mean_threshold=24230.0,
        event_status=status,
        event_time=event_time,
        available_at=avail,
        created_at=avail,
        confirmed_at=avail,
        invalidated_at=invalidated_at,
        data_quality=data_quality,
        evidence=ev,
    )


def _make_fvg_event(
    event_id: str,
    tf: str,
    direction: EventDirection,
    event_time: datetime,
    available_at: Optional[datetime] = None,
    index: str = "NIFTY 50",
    status: LiquidityLifecycleState = LiquidityLifecycleState.IDENTIFIED,
    invalidated_at: Optional[datetime] = None,
    data_quality: str = "VERIFIED_LIVE",
) -> FVGEvent:
    avail = available_at or (event_time + _tf_close_offset(tf))
    ev = FVGEvidence(
        candle_1_id=f"C1-{event_id}",
        candle_2_id=f"C2-{event_id}",
        candle_3_id=f"C3-{event_id}",
        gap_size_pts=14.0,
        consequent_encroachment=24235.0,
        invalidation_condition="CLOSE_THROUGH_GAP",
    )
    return FVGEvent(
        event_id=event_id,
        index=index,
        event_type=ICTEventType.FVG,
        direction=direction,
        timeframe=tf,
        zone_high=24242.0,
        zone_low=24228.0,
        mean_threshold=24235.0,
        event_status=status,
        event_time=event_time,
        available_at=avail,
        created_at=avail,
        confirmed_at=avail,
        invalidated_at=invalidated_at,
        data_quality=data_quality,
        evidence=ev,
    )


def _make_dealing_range(
    range_id: str,
    tf: str,
    direction: EventDirection,
    start_time: datetime,
    available_at: datetime,
    low: float = 24000.0,
    high: float = 24500.0,
    status: DealingRangeStatus = DealingRangeStatus.ACTIVE,
    index: str = "NIFTY 50",
) -> DealingRange:
    eq = (high + low) / 2.0
    rng = high - low
    return DealingRange(
        range_id=range_id,
        index=index,
        timeframe=tf,
        direction=direction,
        high_price=high,
        low_price=low,
        equilibrium_price=eq,
        delta_r=rng,
        neutral_band_delta=rng * 0.05,
        high_swing_id=f"SH-{range_id}",
        low_swing_id=f"SL-{range_id}",
        start_time=start_time,
        available_at=available_at,
        created_at=available_at,
        status=status,
        configuration_fingerprint="TEST-FP-3.5",
    )


def _make_aligned_bundles(
    direction: EventDirection,
    as_of_time: datetime,
    index: str = "NIFTY 50",
    omit_tfs: Optional[set] = None,
) -> Dict[str, TimeframeEvidenceBundle]:
    omit = omit_tfs or set()
    bundles: Dict[str, TimeframeEvidenceBundle] = {}
    times = {
        "1h": (_ist(9, 15), _ist(10, 15)),
        "15m": (_ist(10, 0), _ist(10, 15)),
        "5m": (_ist(10, 10), _ist(10, 15)),
        "3m": (_ist(10, 12), _ist(10, 15)),
        "1m": (_ist(10, 14), _ist(10, 15)),
    }
    for tf in MTF_TIMEFRAME_ORDER:
        if tf in omit:
            continue
        ev_t, avail_t = times[tf]
        sev = _make_structure_event(f"ST-{tf}-1", tf, direction, ev_t, avail_t, index=index)
        ob = _make_ob_event(f"OB-{tf}-1", tf, direction, ev_t, avail_t, index=index)
        fvg = _make_fvg_event(f"FVG-{tf}-1", tf, direction, ev_t, avail_t, index=index)
        dr = _make_dealing_range(f"DR-{tf}-1", tf, direction, ev_t, avail_t, index=index)
        price = 24120.0 if direction == EventDirection.BULLISH else 24380.0
        bundles[tf] = TimeframeEvidenceBundle(
            timeframe=tf,
            structure_events=[sev],
            order_block_events=[ob],
            fvg_events=[fvg],
            dealing_ranges=[dr],
            current_price=price,
        )
    return bundles


def _make_candles_df(
    start_dt: datetime,
    freq_minutes: int,
    count: int,
    base_price: float = 24200.0,
    step: float = 6.0,
    is_complete_last: bool = True,
) -> pd.DataFrame:
    rows = []
    price = base_price
    for i in range(count):
        ts = start_dt + timedelta(minutes=i * freq_minutes)
        op = price
        # Create mild swing oscillations superimposed on overall directional drift
        delta = step if (i % 5 != 3) else -step * 1.4
        cl = op + delta
        hi = max(op, cl) + 4.0
        lo = min(op, cl) - 4.0
        comp = True if i < count - 1 else is_complete_last
        rows.append(
            {
                "timestamp": ts,
                "open": float(op),
                "high": float(hi),
                "low": float(lo),
                "close": float(cl),
                "volume": float(1000 + i * 25),
                "is_complete": comp,
            }
        )
        price = cl
    return pd.DataFrame(rows)


# ============================================================================
# Scenarios 1–6: Alignment Classifications & Missing Timeframe Semantics
# ============================================================================


def test_01_all_five_timeframes_aligned_bullish():
    engine = MTFConfluenceEngine()
    as_of = _ist(10, 20)
    bundles = _make_aligned_bundles(EventDirection.BULLISH, as_of)

    rep = engine.evaluate_from_evidence(index="NIFTY 50", as_of_time=as_of, timeframe_evidence=bundles)

    assert rep.overall_alignment == AlignmentClassification.STRONG_BULLISH_ALIGNMENT
    assert rep.missing_timeframes == ()
    assert rep.confluence_score is None
    assert rep.score_status == "UNAVAILABLE"
    assert rep.calibration_status == "NOT_CALIBRATED"
    assert rep.execution_mode == "PAPER_TRADING_ONLY"
    for tf in MTF_TIMEFRAME_ORDER:
        assert rep.timeframe_reports[tf].direction == "BULLISH"
        assert rep.timeframe_reports[tf].has_valid_evidence is True
        assert rep.timeframe_reports[tf].timeframe_role == TIMEFRAME_ROLES[tf]
    assert len(rep.bullish_evidence) >= 15
    assert len(rep.bearish_evidence) == 0


def test_02_all_five_timeframes_aligned_bearish():
    engine = MTFConfluenceEngine()
    as_of = _ist(10, 20)
    bundles = _make_aligned_bundles(EventDirection.BEARISH, as_of, index="BANK NIFTY")

    rep = engine.evaluate_from_evidence(index="BANK NIFTY", as_of_time=as_of, timeframe_evidence=bundles)

    assert rep.index == "BANK NIFTY"
    assert rep.overall_alignment == AlignmentClassification.STRONG_BEARISH_ALIGNMENT
    assert rep.missing_timeframes == ()
    assert len(rep.bearish_evidence) >= 15
    assert len(rep.bullish_evidence) == 0
    for tf in MTF_TIMEFRAME_ORDER:
        assert rep.timeframe_reports[tf].direction == "BEARISH"


def test_03_mixed_timeframe_directions_and_cross_tf_conflicts():
    engine = MTFConfluenceEngine()
    as_of = _ist(10, 25)
    bundles = _make_aligned_bundles(EventDirection.BULLISH, as_of)
    # Flip 15m and 1m to BEARISH while 1h, 5m, 3m remain BULLISH
    bundles["15m"] = TimeframeEvidenceBundle(
        timeframe="15m",
        structure_events=[_make_structure_event("ST-15M-BEAR", "15m", EventDirection.BEARISH, _ist(10, 0), _ist(10, 15))],
    )
    bundles["1m"] = TimeframeEvidenceBundle(
        timeframe="1m",
        structure_events=[_make_structure_event("ST-1M-BEAR", "1m", EventDirection.BEARISH, _ist(10, 20), _ist(10, 21))],
    )

    rep = engine.evaluate_from_evidence(index="NIFTY 50", as_of_time=as_of, timeframe_evidence=bundles)

    assert rep.overall_alignment == AlignmentClassification.MIXED_ALIGNMENT
    c_types = {(c.conflict_type, c.timeframe_a, c.timeframe_b) for c in rep.conflicts}
    assert (ConflictType.HTF_ITF_DIVERGENCE, "1h", "15m") in c_types
    assert (ConflictType.ITF_PRIMARY_DIVERGENCE, "15m", "5m") in c_types
    assert (ConflictType.PRIMARY_LTF_DIVERGENCE, "5m", "1m") in c_types


def test_04_missing_1h_returns_insufficient_data_ltf_never_overrides():
    engine = MTFConfluenceEngine()
    as_of = _ist(10, 20)
    bundles = _make_aligned_bundles(EventDirection.BULLISH, as_of, omit_tfs={"1h"})

    rep = engine.evaluate_from_evidence(index="NIFTY 50", as_of_time=as_of, timeframe_evidence=bundles)

    assert rep.overall_alignment == AlignmentClassification.INSUFFICIENT_DATA
    assert "1h" in rep.missing_timeframes
    assert rep.timeframe_reports["1h"].direction == "UNAVAILABLE"
    assert any(
        c.conflict_type == ConflictType.MISSING_TIMEFRAME_EVIDENCE and c.timeframe_a == "1h"
        for c in rep.conflicts
    )


def test_05_missing_15m_returns_insufficient_data():
    engine = MTFConfluenceEngine()
    as_of = _ist(10, 20)
    bundles = _make_aligned_bundles(EventDirection.BEARISH, as_of, omit_tfs={"15m"})

    rep = engine.evaluate_from_evidence(index="NIFTY 50", as_of_time=as_of, timeframe_evidence=bundles)

    assert rep.overall_alignment == AlignmentClassification.INSUFFICIENT_DATA
    assert "15m" in rep.missing_timeframes
    assert any(
        c.conflict_type == ConflictType.MISSING_TIMEFRAME_EVIDENCE and c.timeframe_a == "15m"
        for c in rep.conflicts
    )


def test_06_missing_lower_timeframe_keeps_non_strong_alignment_with_missing_list():
    engine = MTFConfluenceEngine()
    as_of = _ist(10, 20)
    bundles = _make_aligned_bundles(EventDirection.BULLISH, as_of, omit_tfs={"3m", "1m"})

    rep = engine.evaluate_from_evidence(index="NIFTY 50", as_of_time=as_of, timeframe_evidence=bundles)

    assert rep.overall_alignment == AlignmentClassification.BULLISH_ALIGNMENT
    assert set(rep.missing_timeframes) == {"3m", "1m"}
    assert rep.timeframe_reports["3m"].direction == "UNAVAILABLE"
    assert rep.timeframe_reports["1m"].direction == "UNAVAILABLE"


# ============================================================================
# Scenarios 7–15: Causality, Lifecycle & Domain Conflicts
# ============================================================================


def test_07_future_event_exclusion_by_available_at():
    engine = MTFConfluenceEngine()
    as_of = _ist(10, 20)
    bundles = _make_aligned_bundles(EventDirection.BULLISH, as_of)
    # Add a future opposing BEARISH 5m event with event_time before as_of, but available_at AFTER as_of
    future_ev = _make_structure_event(
        "ST-5M-FUT", "5m", EventDirection.BEARISH, _ist(10, 18), available_at=_ist(10, 25)
    )
    bundles["5m"] = bundles["5m"].model_copy(
        update={"structure_events": list(bundles["5m"].structure_events) + [future_ev]}
    )

    rep = engine.evaluate_from_evidence(index="NIFTY 50", as_of_time=as_of, timeframe_evidence=bundles)

    assert rep.timeframe_reports["5m"].future_events_excluded == 1
    assert "ST-5M-FUT" not in rep.evidence_event_ids
    assert rep.overall_alignment == AlignmentClassification.STRONG_BULLISH_ALIGNMENT


def test_08_future_htf_candle_exclusion():
    engine = MTFConfluenceEngine()
    as_of = _ist(10, 15)
    bundles = _make_aligned_bundles(EventDirection.BULLISH, as_of)
    # 1h candles: 09:15-10:15 (completed), 10:15-11:15 (forming/incomplete), 11:15-12:15 (strictly future open > as_of)
    df_1h = _make_candles_df(_ist(9, 15), 60, 3)
    bundles["1h"] = bundles["1h"].model_copy(update={"candles_df": df_1h})

    rep = engine.evaluate_from_evidence(index="NIFTY 50", as_of_time=as_of, timeframe_evidence=bundles)

    assert rep.timeframe_reports["1h"].future_candles_excluded == 1
    assert rep.timeframe_reports["1h"].incomplete_candles_excluded == 1
    assert rep.timeframe_reports["1h"].direction == "BULLISH"


def test_09_incomplete_forming_htf_candle_exclusion():
    engine = MTFConfluenceEngine()
    as_of = _ist(11, 20)
    # 1h bars: 09:15-10:15 (complete) + 10:15-11:15 marked explicitly is_complete=False
    df_incomplete = _make_candles_df(_ist(9, 15), 60, 2, is_complete_last=False)
    bundles = _make_aligned_bundles(EventDirection.BULLISH, as_of)
    bundles["1h"] = bundles["1h"].model_copy(update={"candles_df": df_incomplete})

    rep = engine.evaluate_from_evidence(index="NIFTY 50", as_of_time=as_of, timeframe_evidence=bundles)
    assert rep.timeframe_reports["1h"].incomplete_candles_excluded == 1

    # Also test DataFrame where ONLY incomplete forming candles exist -> zero completed bars lockouts
    df_only_forming = _make_candles_df(_ist(10, 15), 60, 1, is_complete_last=False)
    bundles["5m"] = TimeframeEvidenceBundle(
        timeframe="5m",
        candles_df=df_only_forming,
        structure_events=[_make_structure_event("ST-5M-1", "5m", EventDirection.BULLISH, _ist(10, 15), _ist(10, 20))],
    )
    rep2 = engine.evaluate_from_evidence(index="NIFTY 50", as_of_time=as_of, timeframe_evidence=bundles)
    assert rep2.timeframe_reports["5m"].direction == "UNAVAILABLE"
    assert rep2.timeframe_reports["5m"].incomplete_candles_excluded == 1
    assert rep2.overall_alignment == AlignmentClassification.INSUFFICIENT_DATA


def test_10_invalidated_event_exclusion_and_ob_fvg_conflict():
    engine = MTFConfluenceEngine()
    as_of = _ist(10, 25)
    bundles = _make_aligned_bundles(EventDirection.BULLISH, as_of)
    inv_ob = _make_ob_event(
        "OB-5M-INV",
        "5m",
        EventDirection.BEARISH,
        _ist(10, 5),
        _ist(10, 10),
        status=LiquidityLifecycleState.INVALIDATED,
        invalidated_at=_ist(10, 20),
    )
    bundles["5m"] = bundles["5m"].model_copy(
        update={"order_block_events": list(bundles["5m"].order_block_events) + [inv_ob]}
    )

    rep = engine.evaluate_from_evidence(index="NIFTY 50", as_of_time=as_of, timeframe_evidence=bundles)

    assert "OB-5M-INV" in rep.timeframe_reports["5m"].invalidated_event_ids
    assert "OB-5M-INV" not in rep.evidence_event_ids
    assert any(
        c.conflict_type == ConflictType.OB_FVG_INVALIDATION and "OB-5M-INV" in c.evidence_event_ids
        for c in rep.conflicts
    )


def test_11_expired_event_exclusion():
    engine = MTFConfluenceEngine()
    as_of = _ist(10, 25)
    bundles = _make_aligned_bundles(EventDirection.BULLISH, as_of)
    exp_fvg = _make_fvg_event(
        "FVG-15M-EXP",
        "15m",
        EventDirection.BEARISH,
        _ist(9, 30),
        _ist(9, 45),
        status=LiquidityLifecycleState.EXPIRED,
    )
    bundles["15m"] = bundles["15m"].model_copy(
        update={"fvg_events": list(bundles["15m"].fvg_events) + [exp_fvg]}
    )

    rep = engine.evaluate_from_evidence(index="NIFTY 50", as_of_time=as_of, timeframe_evidence=bundles)

    assert "FVG-15M-EXP" in rep.timeframe_reports["15m"].expired_event_ids
    assert "FVG-15M-EXP" not in rep.evidence_event_ids
    assert rep.timeframe_reports["15m"].direction == "BULLISH"


def test_12_liquidity_conflict_detection_htf_and_intratf():
    engine = MTFConfluenceEngine()
    as_of = _ist(10, 30)
    bundles = _make_aligned_bundles(EventDirection.BULLISH, as_of)
    # 1) 1H liquidity BEARISH vs 15m/5m BULLISH -> HTF_LIQUIDITY_CONFLICT
    liq_1h = _make_liquidity_event("LIQ-1H-BEAR", "1h", EventDirection.BEARISH, _ist(9, 15), _ist(10, 15), liq_type=LiquidityType.BSL)
    bundles["1h"] = bundles["1h"].model_copy(update={"liquidity_events": [liq_1h]})

    # 2) Intra-TF opposing BULLISH + BEARISH liquidity in 3m -> LIQUIDITY_CONFLICT
    liq_3m_b = _make_liquidity_event("LIQ-3M-B", "3m", EventDirection.BULLISH, _ist(10, 12), _ist(10, 15))
    liq_3m_s = _make_liquidity_event("LIQ-3M-S", "3m", EventDirection.BEARISH, _ist(10, 15), _ist(10, 18), liq_type=LiquidityType.BSL)
    bundles["3m"] = bundles["3m"].model_copy(update={"liquidity_events": [liq_3m_b, liq_3m_s]})

    rep = engine.evaluate_from_evidence(index="NIFTY 50", as_of_time=as_of, timeframe_evidence=bundles)

    c_types = {c.conflict_type for c in rep.conflicts}
    assert ConflictType.HTF_LIQUIDITY_CONFLICT in c_types
    assert ConflictType.LIQUIDITY_CONFLICT in c_types
    assert rep.overall_alignment == AlignmentClassification.MIXED_ALIGNMENT


def test_13_premium_discount_conflict_detection():
    engine = MTFConfluenceEngine()
    as_of = _ist(10, 30)
    bundles = _make_aligned_bundles(EventDirection.BULLISH, as_of)
    # Place 1H current_price in DEEP_PREMIUM while all TFs are BULLISH
    dr_1h = _make_dealing_range("DR-1H-PREM", "1h", EventDirection.BULLISH, _ist(9, 15), _ist(10, 15), low=24000.0, high=24500.0)
    bundles["1h"] = bundles["1h"].model_copy(update={"dealing_ranges": [dr_1h], "current_price": 24480.0})

    rep = engine.evaluate_from_evidence(index="NIFTY 50", as_of_time=as_of, timeframe_evidence=bundles)

    pd_conflicts = [c for c in rep.conflicts if c.conflict_type == ConflictType.PREMIUM_DISCOUNT_CONFLICT]
    assert len(pd_conflicts) >= 1
    assert rep.overall_alignment != AlignmentClassification.STRONG_BULLISH_ALIGNMENT
    assert rep.overall_alignment == AlignmentClassification.BULLISH_ALIGNMENT


def test_14_ob_and_fvg_conflict_detection():
    engine = MTFConfluenceEngine()
    as_of = _ist(10, 30)
    bundles = _make_aligned_bundles(EventDirection.BULLISH, as_of)
    # 5m has BULLISH OB + BEARISH FVG -> opposing POI conflict
    bundles["5m"] = TimeframeEvidenceBundle(
        timeframe="5m",
        structure_events=[_make_structure_event("ST-5M-1", "5m", EventDirection.BULLISH, _ist(10, 10), _ist(10, 15))],
        order_block_events=[_make_ob_event("OB-5M-B", "5m", EventDirection.BULLISH, _ist(10, 10), _ist(10, 15))],
        fvg_events=[_make_fvg_event("FVG-5M-S", "5m", EventDirection.BEARISH, _ist(10, 10), _ist(10, 15))],
    )

    rep = engine.evaluate_from_evidence(index="NIFTY 50", as_of_time=as_of, timeframe_evidence=bundles)

    assert any(
        c.conflict_type == ConflictType.OB_FVG_INVALIDATION and c.timeframe_a == "5m" and c.direction_a == "BULLISH" and c.direction_b == "BEARISH"
        for c in rep.conflicts
    )
    assert rep.timeframe_reports["5m"].direction == "CONFLICTING"


def test_15_session_context_integration_and_candle_orchestration():
    engine = MTFConfluenceEngine()
    as_of = _ist(11, 30)

    # Part A: Step 3.6 SessionEvent opposing structural bias + has_data_gaps conflict via evaluate_from_evidence
    bundles = _make_aligned_bundles(EventDirection.BULLISH, as_of)
    sess_ev = SessionEvent(
        event_id="SESS-5M-ORBD",
        index="NIFTY 50",
        event_type=ICTEventType.OPENING_RANGE,
        session_event_kind=SessionEventKind.OPENING_RANGE_BREAKDOWN,
        direction=EventDirection.BEARISH,
        timeframe="5m",
        price_level=24150.0,
        event_status=LiquidityLifecycleState.CONFIRMED,
        event_time=_ist(10, 0),
        available_at=_ist(10, 5),
        created_at=_ist(10, 5),
        data_quality="VERIFIED_LIVE",
    )
    sess_rep = TimeframeSessionReport(
        index="NIFTY 50",
        timeframe="5m",
        trading_date="2026-11-11",
        as_of_time=_ist(10, 15),
        data_quality="VERIFIED_LIVE",
        is_valid=True,
        has_data_gaps=True,
        missing_intervals=[
            MissingCandleInterval(
                expected_open_time=_ist(10, 5),
                expected_close_time=_ist(10, 10),
                timeframe="5m",
            )
        ],
        current_session=SessionClassification(
            session_name="MORNING",
            session_start=_ist(9, 45),
            session_end=_ist(11, 30),
            current_session_status=SessionPhaseStatus.ACTIVE,
            timeframe="5m",
            trading_date="2026-11-11",
        ),
        events=[sess_ev],
        configuration_fingerprint=SessionConfiguration().configuration_fingerprint(),
    )
    bundles["5m"] = bundles["5m"].model_copy(update={"session_report": sess_rep})

    rep = engine.evaluate_from_evidence(index="NIFTY 50", as_of_time=as_of, timeframe_evidence=bundles)
    sess_conflicts = [c for c in rep.conflicts if c.conflict_type == ConflictType.SESSION_CONTEXT_CONFLICT]
    assert len(sess_conflicts) >= 2  # both data gap conflict and opposing directional breakdown conflict

    # Part B: Full end-to-end evaluate_from_candles orchestration through Steps 3.1-3.6
    candles = {
        "1h": _make_candles_df(_ist(9, 15, day=9) if False else _ist(9, 15, day=4), 60, 24),
        "15m": _make_candles_df(_ist(9, 15, day=11), 15, 10),
        "5m": _make_candles_df(_ist(9, 15, day=11), 5, 28),
        "3m": _make_candles_df(_ist(9, 15, day=11), 3, 45),
        "1m": _make_candles_df(_ist(9, 15, day=11), 1, 135),
    }
    candle_rep = engine.evaluate_from_candles(
        index="NIFTY 50",
        as_of_time=as_of,
        candles_by_timeframe=candles,
        include_session_context=True,
    )
    assert candle_rep.execution_mode == "PAPER_TRADING_ONLY"
    assert candle_rep.confluence_score is None
    assert candle_rep.score_status == "UNAVAILABLE"
    assert candle_rep.calibration_status == "NOT_CALIBRATED"
    assert isinstance(candle_rep.overall_alignment, AlignmentClassification)
    assert candle_rep.timeframe_reports["5m"].session_status != "UNAVAILABLE"


# ============================================================================
# Scenarios 16–22: Deduplication, Replay Determinism & Lockouts
# ============================================================================


def test_16_duplicate_event_prevention():
    engine = MTFConfluenceEngine()
    as_of = _ist(10, 20)
    bundles = _make_aligned_bundles(EventDirection.BULLISH, as_of)

    dup_st = _make_structure_event("ST-5M-1", "5m", EventDirection.BULLISH, _ist(10, 10), _ist(10, 15))
    dup_ict = _make_ict_event("ST-5M-1", "5m", ICTEventType.BOS, EventDirection.BULLISH, _ist(10, 10), _ist(10, 15))
    sr_5m = TimeframeStructureReport(
        index="NIFTY 50",
        timeframe="5m",
        data_quality="VERIFIED_LIVE",
        active_trend=TrendBias.BULLISH,
        structure_events=[dup_ict],
        bos_count=1,
        as_of_time=_ist(10, 15),
        configuration_fingerprint="TEST-3.2",
    )
    bundles["5m"] = bundles["5m"].model_copy(
        update={
            "structure_events": list(bundles["5m"].structure_events) + [dup_st],
            "ict_events": [dup_ict],
            "structure_report": sr_5m,
        }
    )

    rep = engine.evaluate_from_evidence(index="NIFTY 50", as_of_time=as_of, timeframe_evidence=bundles)
    tf5_ids = rep.timeframe_reports["5m"].evidence_event_ids
    assert tf5_ids.count("ST-5M-1") == 1


def test_17_deterministic_ids_across_runs_and_input_order():
    engine = MTFConfluenceEngine()
    as_of = _ist(10, 20)
    bundles_a = _make_aligned_bundles(EventDirection.BULLISH, as_of)
    # Build reversed timeframe insertion order
    bundles_b = {tf: bundles_a[tf] for tf in reversed(MTF_TIMEFRAME_ORDER)}

    rep1 = engine.evaluate_from_evidence(index="NIFTY 50", as_of_time=as_of, timeframe_evidence=bundles_a)
    rep2 = engine.evaluate_from_evidence(index="NIFTY 50", as_of_time=as_of, timeframe_evidence=bundles_b)

    assert rep1.report_id == rep2.report_id
    assert rep1.configuration_fingerprint == rep2.configuration_fingerprint
    assert [c.conflict_id for c in rep1.conflicts] == [c.conflict_id for c in rep2.conflicts]
    assert rep1.report_id.startswith("MTF-")


def test_18_historical_replay_determinism_and_causality():
    engine = MTFConfluenceEngine()
    t0 = _ist(10, 0)
    t1 = _ist(10, 15)
    t2 = _ist(10, 30)

    bundles = _make_aligned_bundles(EventDirection.BULLISH, t2)
    # Make 1h structural event become available only at t1 (10:15)
    bundles["1h"] = TimeframeEvidenceBundle(
        timeframe="1h",
        structure_events=[_make_structure_event("ST-1H-T1", "1h", EventDirection.BULLISH, _ist(9, 15), _ist(10, 15))],
    )

    replays_a = engine.replay(index="NIFTY 50", replay_times=[t0, t1, t2], timeframe_evidence=bundles)
    replays_b = engine.replay(index="NIFTY 50", replay_times=[t0, t1, t2], timeframe_evidence=bundles)

    assert [r.report_id for r in replays_a] == [r.report_id for r in replays_b]
    assert replays_a[0].overall_alignment == AlignmentClassification.INSUFFICIENT_DATA  # 1H not available at t0
    assert replays_a[1].overall_alignment == AlignmentClassification.STRONG_BULLISH_ALIGNMENT  # available at t1
    assert replays_a[1].report_id == engine.evaluate_from_evidence(
        index="NIFTY 50", as_of_time=t1, timeframe_evidence=bundles
    ).report_id


def test_19_stale_evidence_lockout():
    engine = MTFConfluenceEngine()
    as_of = _ist(15, 0)
    bundles = _make_aligned_bundles(EventDirection.BULLISH, as_of)

    # Case A: explicit STALE bundle data_quality
    bundles_a = dict(bundles)
    bundles_a["15m"] = bundles_a["15m"].model_copy(update={"data_quality": "STALE"})
    rep_a = engine.evaluate_from_evidence(index="NIFTY 50", as_of_time=as_of, timeframe_evidence=bundles_a)
    assert rep_a.overall_alignment == AlignmentClassification.DATA_QUALITY_LOCKOUT
    assert any(c.conflict_type == ConflictType.STALE_OR_UNAVAILABLE_EVIDENCE for c in rep_a.conflicts)

    # Case B: age threshold exceeded (1m max age default is 390m, event available > 400m prior)
    cfg = MTFConfluenceConfiguration(
        max_evidence_age_minutes_by_tf={"1h": 120, "15m": 60, "5m": 30, "3m": 20, "1m": 15}
    )
    eng_strict = MTFConfluenceEngine(config=cfg)
    rep_b = eng_strict.evaluate_from_evidence(index="NIFTY 50", as_of_time=_ist(11, 30), timeframe_evidence=bundles)
    assert rep_b.overall_alignment == AlignmentClassification.DATA_QUALITY_LOCKOUT
    assert rep_b.timeframe_reports["5m"].data_quality == "STALE"


@pytest.mark.parametrize("bad_status", ["DEGRADED", "MOCK", "SYNTHETIC", "DATA_OFFLINE", "UNAVAILABLE"])
def test_20_data_quality_and_repaired_or_invalid_ohlc_lockout(bad_status: str):
    engine = MTFConfluenceEngine()
    as_of = _ist(10, 20)
    bundles = _make_aligned_bundles(EventDirection.BULLISH, as_of)

    # Top-level feed lockout
    rep_top = engine.evaluate_from_evidence(
        index="NIFTY 50", as_of_time=as_of, timeframe_evidence=bundles, data_quality_status=bad_status
    )
    assert rep_top.overall_alignment == AlignmentClassification.DATA_QUALITY_LOCKOUT

    # Per-timeframe is_mock=True, ohlc_repaired=True, and invalid OHLC (high < low) lockouts
    for extra_col in ({"is_mock": True}, {"ohlc_repaired": True}):
        df_bad = _make_candles_df(_ist(9, 15), 5, 3)
        for k, v in extra_col.items():
            df_bad[k] = v
        b_copy = dict(bundles)
        b_copy["5m"] = b_copy["5m"].model_copy(update={"candles_df": df_bad})
        rep_col = engine.evaluate_from_evidence(index="NIFTY 50", as_of_time=as_of, timeframe_evidence=b_copy)
        assert rep_col.overall_alignment == AlignmentClassification.DATA_QUALITY_LOCKOUT

    df_inv = _make_candles_df(_ist(9, 15), 5, 3)
    df_inv.loc[df_inv.index[-1], "high"] = 24000.0
    df_inv.loc[df_inv.index[-1], "low"] = 24500.0  # invalid high < low
    b_inv = dict(bundles)
    b_inv["5m"] = b_inv["5m"].model_copy(update={"candles_df": df_inv})
    rep_inv = engine.evaluate_from_evidence(index="NIFTY 50", as_of_time=as_of, timeframe_evidence=b_inv)
    assert rep_inv.overall_alignment == AlignmentClassification.DATA_QUALITY_LOCKOUT


def test_21_invalid_and_naive_timestamps_fail_closed():
    engine = MTFConfluenceEngine()
    bundles = _make_aligned_bundles(EventDirection.BULLISH, _ist(10, 20))

    # Naive analysis_time
    with pytest.raises(ValueError, match="timezone-aware"):
        engine.evaluate_from_evidence(
            index="NIFTY 50", as_of_time=datetime(2026, 11, 11, 10, 20), timeframe_evidence=bundles
        )

    # Naive event timestamp fails closed cleanly with ValueError
    bad_ev = MarketStructureEvent(
        event_id="ST-NAIVE",
        index="NIFTY 50",
        event_type=ICTEventType.BOS,
        direction=EventDirection.BULLISH,
        timeframe="5m",
        broken_level=24250.0,
        event_time=datetime(2026, 11, 11, 10, 0),
        available_at=datetime(2026, 11, 11, 10, 5),
        created_at=datetime(2026, 11, 11, 10, 5),
        evidence=bundles["5m"].structure_events[0].evidence,
    )
    bad_ev_bundles = dict(bundles)
    bad_ev_bundles["5m"] = bad_ev_bundles["5m"].model_copy(update={"structure_events": [bad_ev]})
    with pytest.raises(ValueError, match="timezone-aware"):
        engine.evaluate_from_evidence(index="NIFTY 50", as_of_time=_ist(10, 20), timeframe_evidence=bad_ev_bundles)

    # Naive candle timestamp inside DataFrame triggers fail-closed DATA_QUALITY_LOCKOUT
    df_naive = _make_candles_df(datetime(2026, 11, 11, 9, 15), 5, 2)
    bad_bundles = dict(bundles)
    bad_bundles["5m"] = bad_bundles["5m"].model_copy(update={"candles_df": df_naive})
    rep_naive_df = engine.evaluate_from_evidence(index="NIFTY 50", as_of_time=_ist(10, 20), timeframe_evidence=bad_bundles)
    assert rep_naive_df.overall_alignment == AlignmentClassification.DATA_QUALITY_LOCKOUT
    assert rep_naive_df.timeframe_reports["5m"].data_quality == "INVALID_DATA"


def test_22_cross_timeframe_event_causality_boundary():
    engine = MTFConfluenceEngine()
    bundles = _make_aligned_bundles(EventDirection.BULLISH, _ist(10, 15))
    # 1h candle opens 09:15 and closes 10:15 (available_at=10:15)
    # At 10:14 (even though 15m/5m/3m/1m already closed at 10:10), 1H event MUST NOT leak
    bundles["1h"] = TimeframeEvidenceBundle(
        timeframe="1h",
        structure_events=[_make_structure_event("ST-1H-CAUSAL", "1h", EventDirection.BULLISH, _ist(9, 15), _ist(10, 15))],
    )

    rep_before = engine.evaluate_from_evidence(index="NIFTY 50", as_of_time=_ist(10, 14), timeframe_evidence=bundles)
    assert rep_before.timeframe_reports["1h"].future_events_excluded == 1
    assert rep_before.overall_alignment == AlignmentClassification.INSUFFICIENT_DATA

    rep_exact = engine.evaluate_from_evidence(index="NIFTY 50", as_of_time=_ist(10, 15), timeframe_evidence=bundles)
    assert rep_exact.timeframe_reports["1h"].future_events_excluded == 0
    assert rep_exact.overall_alignment == AlignmentClassification.STRONG_BULLISH_ALIGNMENT


# ============================================================================
# Scenarios 23–26: Governance Invariants
# ============================================================================


def test_23_ict_confluence_score_remains_unavailable_and_not_calibrated():
    engine = MTFConfluenceEngine()
    rep = engine.evaluate_from_evidence(
        index="NIFTY 50",
        as_of_time=_ist(10, 20),
        timeframe_evidence=_make_aligned_bundles(EventDirection.BULLISH, _ist(10, 20)),
    )
    assert rep.confluence_score is None
    assert rep.score_status == "UNAVAILABLE"
    assert rep.calibration_status == "NOT_CALIBRATED"

    # Model validator MUST block any attempt to set a numeric confluence_score or override calibration status
    with pytest.raises(ValidationError):
        MTFConfluenceReport(
            report_id="MTF-TEST",
            index="NIFTY 50",
            analysis_time=_ist(10, 20),
            overall_alignment=AlignmentClassification.STRONG_BULLISH_ALIGNMENT,
            data_quality_status="VERIFIED_LIVE",
            confluence_score=85.0,
            score_status="UNAVAILABLE",
            calibration_status="NOT_CALIBRATED",
            configuration_fingerprint="FP",
            explanation="Invalid numeric score",
        )


def test_24_no_phase2_weight_reuse_or_mtf_weight_fields():
    import app.options.ict_smc.mtf_confluence_engine as mod

    cfg = MTFConfluenceConfiguration()
    for field_name in MTFConfluenceConfiguration.model_fields:
        low = field_name.lower()
        assert "weight" not in low
        assert "bonus" not in low
        assert "penalty" not in low
        assert "score" not in low

    # Zero imports of Phase 2 MTF analyzers/weights inside Step 3.7 module
    src = Path(inspect.getfile(mod)).read_text(encoding="utf-8")
    assert "mtf_analysis" not in src
    assert "multi_timeframe_engine" not in src
    assert "DEFAULT_MTF_CONFIG" not in src


def test_25_no_trade_execution_linkage():
    import app.options.ict_smc.mtf_confluence_engine as mod

    src = Path(inspect.getfile(mod)).read_text(encoding="utf-8")
    tree = ast.parse(src)
    # Verify zero non-docstring code references to execution verbs/symbols
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            # Ignore module/function docstrings referencing the rule itself
            continue
        if isinstance(node, ast.Name):
            assert node.id not in {"BUY_CE", "BUY_PE", "PaperTradingEngine", "place_order", "execute_trade"}
        elif isinstance(node, ast.Attribute):
            assert node.attr not in {"BUY_CE", "BUY_PE", "place_order", "execute_trade"}

    assert mod.EXECUTION_MODE == "PAPER_TRADING_ONLY"
    assert MTF_ENGINE_VERSION == "3.7.0"


def test_26_sensex_governance_restriction_and_supported_indices():
    engine_blocked = MTFConfluenceEngine()  # sensex_governance_approved=False default
    as_of = _ist(10, 20)
    bundles_sensex = _make_aligned_bundles(EventDirection.BULLISH, as_of, index="SENSEX")

    rep_blocked = engine_blocked.evaluate_from_evidence(
        index="SENSEX", as_of_time=as_of, timeframe_evidence=bundles_sensex
    )
    assert rep_blocked.overall_alignment == AlignmentClassification.DATA_QUALITY_LOCKOUT
    assert rep_blocked.data_quality_status == "GOVERNANCE_LOCKOUT"

    # When explicitly governed & approved, SENSEX evaluates cleanly
    engine_approved = MTFConfluenceEngine(config=MTFConfluenceConfiguration(sensex_governance_approved=True))
    rep_approved = engine_approved.evaluate_from_evidence(
        index="SENSEX", as_of_time=as_of, timeframe_evidence=bundles_sensex
    )
    assert rep_approved.overall_alignment == AlignmentClassification.STRONG_BULLISH_ALIGNMENT
    assert rep_approved.data_quality_status == "VERIFIED_LIVE"

    # Canonical timeframe & index normalization checks
    assert normalize_mtf_timeframe("60m") == "1h"
    assert normalize_mtf_timeframe("1H") == "1h"
    assert DEFAULT_MAX_EVIDENCE_AGE_MINUTES["1h"] == 720
    for idx in ("NIFTY 50", "BANK NIFTY", "FINNIFTY"):
        rep_idx = engine_blocked.evaluate_from_evidence(
            index=idx,
            as_of_time=as_of,
            timeframe_evidence=_make_aligned_bundles(EventDirection.BULLISH, as_of, index=idx),
        )
        assert rep_idx.index == idx
        assert rep_idx.overall_alignment == AlignmentClassification.STRONG_BULLISH_ALIGNMENT
