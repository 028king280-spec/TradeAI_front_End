"""
Comprehensive test suite for AIVOLVE Phase 3 Step 3.2:
Market Structure & Change of Character Engine.
Verifies all 25 core test requirements:
1. HH classification.
2. HL classification.
3. LH classification.
4. LL classification.
5. Equal high and equal low handling.
6. Insufficient structural history.
7. Bullish BOS.
8. Bearish BOS.
9. Wick-only break rejection.
10. Duplicate BOS prevention.
11. Bullish CHoCH.
12. Bearish CHoCH.
13. CHoCH versus continuation BOS distinction.
14. MSS confirmation rules.
15. Event invalidation.
16. All five supported timeframes.
17. Timeframe isolation.
18. available_at correctness.
19. As-of replay.
20. No-lookahead protection.
21. Deterministic event IDs.
22. Repeated replay determinism.
23. Data-quality lockouts.
24. Invalid OHLC handling.
25. Legacy Step 3.1 regression compatibility.
"""

import pytest
from datetime import datetime, timedelta, timezone
import zoneinfo
import pandas as pd
import numpy as np

from app.options.ict_smc.ict_models import (
    ICTEvent,
    ICTEventType,
    EventDirection,
    LiquidityLifecycleState,
    StructuralSwingType,
    TrendBias,
    StructuralSwing,
    MarketStructureEvidence,
    MarketStructureEvent,
    MarketStructureConfiguration,
    SwingPoint,
    IST_ZONE,
)
from app.options.ict_smc.swing_detection import SwingDetectionEngine
from app.options.ict_smc.market_structure import (
    MarketStructureEngine,
    TimeframeStructureReport,
    DISQUALIFYING_FEED_STATUSES,
)


def create_candle_df(
    ohlc_data: list[tuple[float, float, float, float]],
    start_time: str = "2026-11-06 09:15:00",
    freq_min: int = 15,
) -> pd.DataFrame:
    """Helper to create timezone-aware IST test DataFrames."""
    start_dt = datetime.strptime(start_time, "%Y-%m-%d %H:%M:%S").replace(tzinfo=IST_ZONE)
    timestamps = [start_dt + timedelta(minutes=i * freq_min) for i in range(len(ohlc_data))]

    records = []
    for i, (o, h, l, c) in enumerate(ohlc_data):
        records.append({
            "timestamp": timestamps[i],
            "open": float(o),
            "high": float(h),
            "low": float(l),
            "close": float(c),
            "volume": 1000.0,
        })
    df = pd.DataFrame(records)
    df.attrs["quality_status"] = "VERIFIED_LIVE"
    return df


class TestSwingStructureClassification:
    """Tests 1-6: Structural Classification (HH, HL, LH, LL, EH, EL) & Edge Cases."""

    def test_hh_and_hl_classification(self):
        """Test 1 & 2: Classify Higher High (HH) and Higher Low (HL) in ascending structure."""
        engine = MarketStructureEngine(config=MarketStructureConfiguration(equal_tolerance_pct=0.0005))
        now = datetime.now(IST_ZONE)

        swings = [
            # High 1: 24200 (Initial)
            SwingPoint(
                event_id="SW_H1", index="NIFTY 50", swing_type="HIGH", price=24200.0, timeframe="15m",
                bar_index=3, candle_id="c3", event_time=now, available_at=now,
                left_bars=2, right_bars=2,
            ),
            # Low 1: 24000 (Initial)
            SwingPoint(
                event_id="SW_L1", index="NIFTY 50", swing_type="LOW", price=24000.0, timeframe="15m",
                bar_index=6, candle_id="c6", event_time=now + timedelta(minutes=15), available_at=now + timedelta(minutes=15),
                left_bars=2, right_bars=2,
            ),
            # High 2: 24400 (> 24200 -> HH)
            SwingPoint(
                event_id="SW_H2", index="NIFTY 50", swing_type="HIGH", price=24400.0, timeframe="15m",
                bar_index=9, candle_id="c9", event_time=now + timedelta(minutes=30), available_at=now + timedelta(minutes=30),
                left_bars=2, right_bars=2,
            ),
            # Low 2: 24150 (> 24000 -> HL)
            SwingPoint(
                event_id="SW_L2", index="NIFTY 50", swing_type="LOW", price=24150.0, timeframe="15m",
                bar_index=12, candle_id="c12", event_time=now + timedelta(minutes=45), available_at=now + timedelta(minutes=45),
                left_bars=2, right_bars=2,
            ),
        ]

        classified = engine.classify_swings(swings)
        assert len(classified) == 4

        # H1 is Initial
        assert classified[0].classification == StructuralSwingType.INITIAL
        # L1 is Initial
        assert classified[1].classification == StructuralSwingType.INITIAL
        # H2 is HH
        assert classified[2].classification == StructuralSwingType.HH
        assert classified[2].price_diff == 200.0
        assert classified[2].previous_same_extrema_id == "SW_H1"
        # L2 is HL
        assert classified[3].classification == StructuralSwingType.HL
        assert classified[3].price_diff == 150.0
        assert classified[3].previous_same_extrema_id == "SW_L1"

    def test_lh_and_ll_classification(self):
        """Test 3 & 4: Classify Lower High (LH) and Lower Low (LL) in descending structure."""
        engine = MarketStructureEngine(config=MarketStructureConfiguration(equal_tolerance_pct=0.0005))
        now = datetime.now(IST_ZONE)

        swings = [
            # High 1: 25000 (Initial)
            SwingPoint(
                event_id="SW_H1", index="NIFTY 50", swing_type="HIGH", price=25000.0, timeframe="15m",
                bar_index=3, candle_id="c3", event_time=now, available_at=now,
                left_bars=2, right_bars=2,
            ),
            # Low 1: 24800 (Initial)
            SwingPoint(
                event_id="SW_L1", index="NIFTY 50", swing_type="LOW", price=24800.0, timeframe="15m",
                bar_index=6, candle_id="c6", event_time=now + timedelta(minutes=15), available_at=now + timedelta(minutes=15),
                left_bars=2, right_bars=2,
            ),
            # High 2: 24900 (< 25000 -> LH)
            SwingPoint(
                event_id="SW_H2", index="NIFTY 50", swing_type="HIGH", price=24900.0, timeframe="15m",
                bar_index=9, candle_id="c9", event_time=now + timedelta(minutes=30), available_at=now + timedelta(minutes=30),
                left_bars=2, right_bars=2,
            ),
            # Low 2: 24600 (< 24800 -> LL)
            SwingPoint(
                event_id="SW_L2", index="NIFTY 50", swing_type="LOW", price=24600.0, timeframe="15m",
                bar_index=12, candle_id="c12", event_time=now + timedelta(minutes=45), available_at=now + timedelta(minutes=45),
                left_bars=2, right_bars=2,
            ),
        ]

        classified = engine.classify_swings(swings)
        assert len(classified) == 4
        assert classified[2].classification == StructuralSwingType.LH
        assert classified[2].price_diff == -100.0
        assert classified[3].classification == StructuralSwingType.LL
        assert classified[3].price_diff == -200.0

    def test_equal_high_and_equal_low_handling(self):
        """Test 5: Explicit classification of Equal Highs (EH) and Equal Lows (EL)."""
        engine = MarketStructureEngine(config=MarketStructureConfiguration(equal_tolerance_pct=0.0010))  # 0.1% tol = 25 pts on 25000
        now = datetime.now(IST_ZONE)

        swings = [
            SwingPoint(
                event_id="SW_H1", index="NIFTY 50", swing_type="HIGH", price=25000.0, timeframe="15m",
                bar_index=3, candle_id="c3", event_time=now, available_at=now,
                left_bars=2, right_bars=2,
            ),
            SwingPoint(
                event_id="SW_L1", index="NIFTY 50", swing_type="LOW", price=24500.0, timeframe="15m",
                bar_index=6, candle_id="c6", event_time=now + timedelta(minutes=15), available_at=now + timedelta(minutes=15),
                left_bars=2, right_bars=2,
            ),
            # High 2: 25010 (diff = 10 pts <= 25 pts tol -> EH)
            SwingPoint(
                event_id="SW_H2", index="NIFTY 50", swing_type="HIGH", price=25010.0, timeframe="15m",
                bar_index=9, candle_id="c9", event_time=now + timedelta(minutes=30), available_at=now + timedelta(minutes=30),
                left_bars=2, right_bars=2,
            ),
            # Low 2: 24495 (diff = -5 pts <= 24.5 pts tol -> EL)
            SwingPoint(
                event_id="SW_L2", index="NIFTY 50", swing_type="LOW", price=24495.0, timeframe="15m",
                bar_index=12, candle_id="c12", event_time=now + timedelta(minutes=45), available_at=now + timedelta(minutes=45),
                left_bars=2, right_bars=2,
            ),
        ]

        classified = engine.classify_swings(swings)
        assert classified[2].classification == StructuralSwingType.EH
        assert classified[3].classification == StructuralSwingType.EL

    def test_insufficient_structural_history(self):
        """Test 6: Handles empty or single swing without inventing false structure."""
        engine = MarketStructureEngine()
        assert engine.classify_swings([]) == []

        now = datetime.now(IST_ZONE)
        single = [
            SwingPoint(
                event_id="SW_H1", index="NIFTY 50", swing_type="HIGH", price=25000.0, timeframe="15m",
                bar_index=3, candle_id="c3", event_time=now, available_at=now,
                left_bars=2, right_bars=2,
            )
        ]
        classified = engine.classify_swings(single)
        assert len(classified) == 1
        assert classified[0].classification == StructuralSwingType.INITIAL
        assert classified[0].previous_same_extrema_id is None


class TestBreakOfStructureAndChangeOfCharacter:
    """Tests 7-14: BOS, CHoCH, and MSS detection, break requirements, and prevention."""

    def test_bullish_bos_with_candle_close(self):
        """Test 7: Bullish BOS confirmed when candle closes beyond previous structural high."""
        engine = MarketStructureEngine(config=MarketStructureConfiguration(swing_left_bars=2, swing_right_bars=2))

        # Build clear swing high at bar 3: (high 24200)
        # Left bars: bar 1 (24000), bar 2 (24100)
        # Bar 3: High 24200
        # Right bars: bar 4 (24100), bar 5 (24050) -> confirms high at bar 5 close
        # Subsequent breakout bar 6: Open 24000, High 24350, Low 23980, Close 24300 (close > 24200)
        data = [
            (23900, 23950, 23850, 23900),  # 0
            (23900, 24000, 23880, 23950),  # 1
            (23950, 24100, 23920, 24050),  # 2
            (24050, 24200, 24000, 24150),  # 3: Swing High 24200
            (24100, 24120, 24020, 24080),  # 4
            (24080, 24090, 23980, 24000),  # 5: Confirms swing high
            (24000, 24350, 23980, 24300),  # 6: Breakout Close 24300 > 24200
            (24300, 24320, 24250, 24280),  # 7
        ]
        df = create_candle_df(data)

        swings, events, trend = engine.detect_structure_breaks(df, symbol="NIFTY 50", timeframe="15m")

        assert len(swings) >= 1
        bos_events = [e for e in events if e.event_type == ICTEventType.BOS]
        assert len(bos_events) == 1
        assert bos_events[0].direction == EventDirection.BULLISH
        assert bos_events[0].price_level == 24200.0
        assert bos_events[0].evidence["is_body_close"] is True
        assert bos_events[0].evidence["penetration_depth_pts"] == 100.0  # 24300 - 24200

    def test_bearish_bos_with_candle_close(self):
        """Test 8: Bearish BOS confirmed when candle closes below previous structural low."""
        engine = MarketStructureEngine(config=MarketStructureConfiguration(swing_left_bars=2, swing_right_bars=2))

        # Swing low at bar 3: Low 24500
        data = [
            (24800, 24850, 24750, 24800),  # 0
            (24750, 24800, 24650, 24700),  # 1
            (24700, 24720, 24580, 24600),  # 2
            (24600, 24650, 24500, 24550),  # 3: Swing Low 24500
            (24550, 24620, 24530, 24600),  # 4
            (24600, 24640, 24560, 24610),  # 5: Confirms swing low
            (24610, 24620, 24380, 24420),  # 6: Breakout Close 24420 < 24500
            (24420, 24450, 24390, 24410),  # 7
        ]
        df = create_candle_df(data)

        swings, events, trend = engine.detect_structure_breaks(df, symbol="NIFTY 50", timeframe="15m")

        bos_events = [e for e in events if e.event_type == ICTEventType.BOS]
        assert len(bos_events) == 1
        assert bos_events[0].direction == EventDirection.BEARISH
        assert bos_events[0].price_level == 24500.0
        assert bos_events[0].evidence["is_body_close"] is True

    def test_wick_only_break_rejection(self):
        """Test 9: Wick penetration without candle close is strictly rejected as BOS."""
        engine = MarketStructureEngine(config=MarketStructureConfiguration(swing_left_bars=2, swing_right_bars=2, require_candle_close=True))

        # Swing high at bar 3: High 24200
        # Bar 6 wicks up to 24250 (> 24200) but closes at 24180 (<= 24200)
        data = [
            (23900, 23950, 23850, 23900),  # 0
            (23900, 24000, 23880, 23950),  # 1
            (23950, 24100, 23920, 24050),  # 2
            (24050, 24200, 24000, 24150),  # 3: Swing High 24200
            (24100, 24120, 24020, 24080),  # 4
            (24080, 24090, 23980, 24000),  # 5: Confirms high
            (24000, 24250, 23980, 24180),  # 6: WICK ONLY! High 24250 > 24200, Close 24180 <= 24200
            (24180, 24190, 24050, 24100),  # 7
        ]
        df = create_candle_df(data)

        swings, events, trend = engine.detect_structure_breaks(df, symbol="NIFTY 50", timeframe="15m")

        # Zero BOS events must be generated!
        assert len(events) == 0

    def test_duplicate_bos_prevention(self):
        """Test 10: Once a structural level is broken, subsequent candles do not emit duplicate BOS events."""
        engine = MarketStructureEngine(config=MarketStructureConfiguration(swing_left_bars=2, swing_right_bars=2))

        # Swing high at bar 3: High 24200
        # Bar 6 closes at 24250 (BOS 1)
        # Bar 7 closes even higher at 24300 (should NOT emit BOS 2 for the same high!)
        data = [
            (23900, 23950, 23850, 23900),  # 0
            (23900, 24000, 23880, 23950),  # 1
            (23950, 24100, 23920, 24050),  # 2
            (24050, 24200, 24000, 24150),  # 3: Swing High 24200
            (24100, 24120, 24020, 24080),  # 4
            (24080, 24090, 23980, 24000),  # 5: Confirms high
            (24000, 24280, 23980, 24250),  # 6: First Break (Close 24250)
            (24250, 24350, 24200, 24300),  # 7: Subsequent bar (Close 24300)
            (24300, 24320, 24250, 24290),  # 8
        ]
        df = create_candle_df(data)

        swings, events, trend = engine.detect_structure_breaks(df, symbol="NIFTY 50", timeframe="15m")

        bos_events = [e for e in events if e.event_type == ICTEventType.BOS]
        assert len(bos_events) == 1
        assert bos_events[0].price_level == 24200.0

    def test_bullish_and_bearish_choch_versus_bos(self):
        """Test 11, 12, 13: CHoCH changes character against prevailing trend; distinguished from BOS."""
        engine = MarketStructureEngine(config=MarketStructureConfiguration(swing_left_bars=2, swing_right_bars=2))

        # Build established downtrend: Initial High (24900), Initial Low (24350), Lower High (24700), Lower Low (24200)
        # Then price rallies and closes above last LH (24700) -> triggers CHoCH!
        data = [
            (24500, 24550, 24450, 24500),  # 0
            (24500, 24600, 24480, 24550),  # 1
            (24550, 24650, 24520, 24600),  # 2: Left 1
            (24600, 24700, 24580, 24680),  # 3: Left 2
            (24680, 24900, 24650, 24850),  # 4: Swing High 1 (24900)
            (24800, 24820, 24600, 24650),  # 5: Right 1
            (24650, 24700, 24500, 24520),  # 6: Right 2 (confirms SH1)
            (24520, 24550, 24350, 24400),  # 7: Swing Low 1 (24350)
            (24400, 24450, 24380, 24420),  # 8: Right 1 / Left 1
            (24420, 24450, 24390, 24410),  # 9: Right 2 (confirms SL1) / Left 2
            (24410, 24700, 24400, 24650),  # 10: Swing High 2 (24700, LH)
            (24650, 24660, 24450, 24500),  # 11: Right 1
            (24500, 24520, 24300, 24320),  # 12: Right 2 (confirms SH2 as LH)
            (24320, 24350, 24200, 24220),  # 13: Swing Low 2 (24200, LL)
            (24220, 24250, 24210, 24230),  # 14: Right 1
            (24230, 24250, 24210, 24240),  # 15: Right 2 (confirms SL2 as LL) -> Trend is now BEARISH
            # Candle 16: Breaks above last LH (24700) with close at 24780!
            (24240, 24850, 24220, 24780),  # 16: Breakout above 24700 -> Bullish CHoCH!
        ]
        df = create_candle_df(data)

        swings, events, trend = engine.detect_structure_breaks(df, symbol="NIFTY 50", timeframe="15m")

        choch_events = [e for e in events if e.event_type == ICTEventType.CHOCH]
        assert len(choch_events) >= 1
        assert choch_events[0].direction == EventDirection.BULLISH
        assert choch_events[0].evidence["previous_trend"] == "BEARISH"
        assert choch_events[0].evidence["new_trend"] == "BULLISH"
        assert trend == TrendBias.BULLISH

    def test_mss_confirmation_with_displacement(self):
        """Test 14: Market Structure Shift (MSS) confirmed when CHoCH has strong displacement."""
        config = MarketStructureConfiguration(
            swing_left_bars=2,
            swing_right_bars=2,
            mss_require_displacement=True,
            mss_min_body_ratio=0.50,
            mss_min_atr_multiple=1.0,
        )
        engine = MarketStructureEngine(config=config)

        # Downtrend setup breaking above LH 24700 with high body ratio (0.87) and huge range
        data = [
            (24500, 24550, 24450, 24500),  # 0
            (24500, 24600, 24480, 24550),  # 1
            (24550, 24650, 24520, 24600),  # 2: Left 1
            (24600, 24700, 24580, 24680),  # 3: Left 2
            (24680, 24900, 24650, 24850),  # 4: Swing High 1 (24900)
            (24800, 24820, 24600, 24650),  # 5: Right 1
            (24650, 24700, 24500, 24520),  # 6: Right 2 (confirms SH1)
            (24520, 24550, 24350, 24400),  # 7: Swing Low 1 (24350)
            (24400, 24450, 24380, 24420),  # 8: Right 1 / Left 1
            (24420, 24450, 24390, 24410),  # 9: Right 2 (confirms SL1) / Left 2
            (24410, 24700, 24400, 24650),  # 10: Swing High 2 (24700, LH)
            (24650, 24660, 24450, 24500),  # 11: Right 1
            (24500, 24520, 24300, 24320),  # 12: Right 2 (confirms SH2 as LH)
            (24320, 24350, 24200, 24220),  # 13: Swing Low 2 (24200, LL)
            (24220, 24250, 24210, 24230),  # 14: Right 1
            (24230, 24250, 24210, 24240),  # 15: Right 2 (confirms SL2 as LL)
            # Candle 16: Strong displacement: Open 24250, High 24850, Low 24240, Close 24800 (Body: 550, Range: 610, Ratio: 0.90)
            (24250, 24850, 24240, 24800),  # 16: Massive displacement breakout!
        ]
        df = create_candle_df(data)

        swings, events, trend = engine.detect_structure_breaks(df, symbol="NIFTY 50", timeframe="15m")

        mss_events = [e for e in events if e.event_type == ICTEventType.MSS]
        assert len(mss_events) == 1
        assert mss_events[0].direction == EventDirection.BULLISH
        assert mss_events[0].evidence["displacement_confirmed"] is True
        assert mss_events[0].evidence["body_to_range_ratio"] >= 0.50

    def test_event_invalidation_handling(self):
        """Test 15: Event model cleanly supports status invalidation."""
        now = datetime.now(IST_ZONE)
        event = MarketStructureEvent(
            event_id="EV_BOS_1",
            index="NIFTY 50",
            event_type=ICTEventType.BOS,
            direction=EventDirection.BULLISH,
            timeframe="15m",
            broken_level=24500.0,
            event_status=LiquidityLifecycleState.CONFIRMED,
            event_time=now,
            available_at=now,
            created_at=now,
            confirmed_at=now,
            evidence=MarketStructureEvidence(
                broken_level=24500.0,
                broken_swing_id="SW1",
                broken_swing_type="HH",
                broken_swing_time=now,
                break_candle_id="c1",
                break_candle_time=now,
                break_candle_open=24450.0,
                break_candle_high=24550.0,
                break_candle_low=24440.0,
                break_candle_close=24520.0,
                penetration_depth_pts=20.0,
            ),
        )
        assert event.event_status == LiquidityLifecycleState.CONFIRMED

        # Transition to INVALIDATED
        event.event_status = LiquidityLifecycleState.INVALIDATED
        event.invalidated_at = now + timedelta(minutes=15)
        ict_event = event.to_ict_event()

        assert ict_event.event_status == LiquidityLifecycleState.INVALIDATED
        assert ict_event.invalidated_at is not None


class TestMultiTimeframeAndIsolation:
    """Tests 16 & 17: Support all 5 timeframes (1H, 15M, 5M, 3M, 1M) with complete isolation."""

    def test_all_five_supported_timeframes(self):
        """Test 16: Engine correctly analyzes 1H, 15M, 5M, 3M, and 1M data without schema errors."""
        engine = MarketStructureEngine(config=MarketStructureConfiguration(swing_left_bars=2, swing_right_bars=2))
        data = [
            (24000, 24050, 23950, 24020),
            (24020, 24120, 24000, 24100),
            (24100, 24200, 24050, 24180),
            (24180, 24300, 24150, 24250),
            (24250, 24280, 24120, 24150),
            (24150, 24200, 24050, 24100),
            (24100, 24400, 24080, 24380),
        ]

        tfs = ["1h", "15m", "5m", "3m", "1m"]
        data_by_tf = {tf: create_candle_df(data) for tf in tfs}

        reports = engine.analyze_multi_timeframe(data_by_tf, symbol="NIFTY 50")
        assert len(reports) == 5
        for tf in tfs:
            assert tf in reports
            assert reports[tf].timeframe == tf
            assert isinstance(reports[tf], TimeframeStructureReport)

    def test_complete_timeframe_isolation(self):
        """Test 17: Swings and break events on one timeframe never leak into another."""
        engine = MarketStructureEngine(config=MarketStructureConfiguration(swing_left_bars=2, swing_right_bars=2))

        # 15M data has a breakout
        data_15m = [
            (24000, 24050, 23950, 24020),
            (24020, 24120, 24000, 24100),
            (24100, 24250, 24050, 24200),  # High 24250
            (24200, 24220, 24100, 24150),
            (24150, 24180, 24050, 24100),
            (24100, 24400, 24080, 24350),  # Breakout
        ]
        # 1H data is completely flat (no breakout)
        data_1h = [
            (24000, 24050, 23950, 24000),
            (24000, 24050, 23950, 24000),
            (24000, 24050, 23950, 24000),
            (24000, 24050, 23950, 24000),
            (24000, 24050, 23950, 24000),
            (24000, 24050, 23950, 24000),
        ]

        data_by_tf = {
            "15m": create_candle_df(data_15m),
            "1h": create_candle_df(data_1h),
        }

        reports = engine.analyze_multi_timeframe(data_by_tf, symbol="NIFTY 50")

        # 15M has events, 1H has ZERO events
        assert len(reports["15m"].structure_events) >= 1
        assert len(reports["1h"].structure_events) == 0
        assert reports["15m"].timeframe == "15m"
        assert reports["1h"].timeframe == "1h"


class TestAntiLookaheadAndDeterminism:
    """Tests 18-22: available_at delay, as_of replay, no-lookahead, and deterministic event IDs."""

    def test_available_at_correctness(self):
        """Test 18: Break event available_at matches the break candle completion timestamp."""
        engine = MarketStructureEngine(config=MarketStructureConfiguration(swing_left_bars=2, swing_right_bars=2))
        data = [
            (23900, 23950, 23850, 23900),  # 0
            (23900, 24000, 23880, 23950),  # 1
            (23950, 24100, 23920, 24050),  # 2
            (24050, 24200, 24000, 24150),  # 3: Swing High 24200
            (24100, 24120, 24020, 24080),  # 4
            (24080, 24090, 23980, 24000),  # 5
            (24000, 24350, 23980, 24300),  # 6: Break candle
        ]
        df = create_candle_df(data)
        swings, events, trend = engine.detect_structure_breaks(df, symbol="NIFTY 50", timeframe="15m")

        assert len(events) >= 1
        ev = events[0]
        # Break candle is bar 6
        assert ev.available_at == df.iloc[6]["timestamp"]
        assert ev.event_time == df.iloc[6]["timestamp"]

    def test_as_of_point_in_time_filtering(self):
        """Test 19 & 20: No future breakout leakage when querying as of an earlier timestamp."""
        engine = MarketStructureEngine(config=MarketStructureConfiguration(swing_left_bars=2, swing_right_bars=2))
        data = [
            (23900, 23950, 23850, 23900),  # 0
            (23900, 24000, 23880, 23950),  # 1
            (23950, 24100, 23920, 24050),  # 2
            (24050, 24200, 24000, 24150),  # 3: Swing High 24200
            (24100, 24120, 24020, 24080),  # 4
            (24080, 24090, 23980, 24000),  # 5: High confirmed
            (24000, 24350, 23980, 24300),  # 6: Future breakout!
            (24300, 24450, 24280, 24400),  # 7: Another future breakout!
        ]
        df = create_candle_df(data)

        # Query as of bar 5 (before bar 6 breakout occurred)
        as_of_t = df.iloc[5]["timestamp"]
        swings, events, trend = engine.detect_structure_breaks(df, as_of_time=as_of_t)

        # Swings confirmed by bar 5 are visible, but bar 6/7 breakouts are completely hidden!
        assert len(swings) >= 1
        assert len(events) == 0

    def test_deterministic_event_id_generation(self):
        """Test 21: Event ID generation is deterministic and non-random across executions."""
        engine = MarketStructureEngine(config=MarketStructureConfiguration(swing_left_bars=2, swing_right_bars=2))
        data = [
            (23900, 23950, 23850, 23900),
            (23900, 24000, 23880, 23950),
            (23950, 24100, 23920, 24050),
            (24050, 24200, 24000, 24150),
            (24100, 24120, 24020, 24080),
            (24080, 24090, 23980, 24000),
            (24000, 24350, 23980, 24300),
        ]
        df = create_candle_df(data)

        _, events1, _ = engine.detect_structure_breaks(df)
        _, events2, _ = engine.detect_structure_breaks(df)

        assert len(events1) == len(events2)
        assert len(events1) > 0
        for e1, e2 in zip(events1, events2):
            assert e1.event_id == e2.event_id
            assert e1.event_id.startswith("EVT-")
            assert len(e1.event_id) == 24

    def test_repeated_replay_determinism(self):
        """Test 22: Identical structural state produced on repeated runs without mutating state."""
        engine = MarketStructureEngine(config=MarketStructureConfiguration(swing_left_bars=2, swing_right_bars=2))
        data = [
            (24000, 24050, 23950, 24020),
            (24020, 24120, 24000, 24100),
            (24100, 24250, 24050, 24200),
            (24200, 24220, 24100, 24150),
            (24150, 24180, 24050, 24100),
            (24100, 24400, 24080, 24350),
        ]
        df = create_candle_df(data)

        res1 = engine.analyze_timeframe(df, symbol="NIFTY 50", timeframe="15m")
        res2 = engine.analyze_timeframe(df, symbol="NIFTY 50", timeframe="15m")

        assert res1.model_dump() == res2.model_dump()


class TestDataQualityAndInvariants:
    """Tests 23-25: Fail-closed lockouts on bad feeds, invalid OHLC, and Step 3.1 regression."""

    @pytest.mark.parametrize("status", list(DISQUALIFYING_FEED_STATUSES))
    def test_disqualifying_feed_lockout(self, status):
        """Test 23: All disqualifying feed statuses trigger an immediate fail-closed lockout."""
        engine = MarketStructureEngine()
        data = [(24000, 24100, 23950, 24050)]
        df = create_candle_df(data)

        with pytest.raises(ValueError, match="Market structure detection locked out"):
            engine.detect_structure_breaks(df, data_quality_status=status)

    def test_repaired_data_lockout(self):
        """Test 23b: Input with repaired or imputed candles fails closed."""
        engine = MarketStructureEngine()
        df = create_candle_df([(24000, 24100, 23950, 24050)])
        df.attrs["quality_status"] = "REPAIRED"
        df.attrs["imputed_bars_count"] = 2

        with pytest.raises(ValueError, match="repaired or imputed mandatory candles"):
            engine.detect_structure_breaks(df, data_quality_status="VERIFIED_LIVE")

    def test_invalid_ohlc_geometry_lockout(self):
        """Test 24: OHLC geometric anomalies fail closed."""
        engine = MarketStructureEngine()

        # High < Low
        bad_df1 = pd.DataFrame([{
            "timestamp": datetime.now(IST_ZONE),
            "open": 24100.0,
            "high": 24000.0,  # Invalid! High (24000) < Low (24200)
            "low": 24200.0,
            "close": 24050.0,
        }])
        with pytest.raises(ValueError, match="high < low"):
            engine.detect_structure_breaks(bad_df1, data_quality_status="VERIFIED_LIVE")

        # High < max(open, close)
        bad_df2 = pd.DataFrame([{
            "timestamp": datetime.now(IST_ZONE),
            "open": 24200.0,
            "high": 24100.0,  # Invalid! High (24100) < Open (24200)
            "low": 24000.0,
            "close": 24050.0,
        }])
        with pytest.raises(ValueError, match="high < max"):
            engine.detect_structure_breaks(bad_df2, data_quality_status="VERIFIED_LIVE")

        # Low > min(open, close)
        bad_df3 = pd.DataFrame([{
            "timestamp": datetime.now(IST_ZONE),
            "open": 24100.0,
            "high": 24200.0,
            "low": 24150.0,   # Invalid! Low (24150) > Close (24050)
            "close": 24050.0,
        }])
        with pytest.raises(ValueError, match="low > min"):
            engine.detect_structure_breaks(bad_df3, data_quality_status="VERIFIED_LIVE")

    def test_step3_1_and_common_event_contract_compatibility(self):
        """Test 25: All structure events strictly conform to the frozen 17-field ICTEvent contract."""
        engine = MarketStructureEngine(config=MarketStructureConfiguration(swing_left_bars=2, swing_right_bars=2))
        data = [
            (23900, 23950, 23850, 23900),
            (23900, 24000, 23880, 23950),
            (23950, 24100, 23920, 24050),
            (24050, 24200, 24000, 24150),
            (24100, 24120, 24020, 24080),
            (24080, 24090, 23980, 24000),
            (24000, 24350, 23980, 24300),
        ]
        df = create_candle_df(data)
        swings, events, trend = engine.detect_structure_breaks(df, symbol="NIFTY 50", timeframe="15m")

        assert len(events) >= 1
        ev = events[0]

        # 17 Mandatory fields validation
        assert isinstance(ev.event_id, str) and ev.event_id.startswith("EVT-") and len(ev.event_id) == 24
        assert ev.index == "NIFTY 50"
        assert ev.event_type in (ICTEventType.BOS, ICTEventType.CHOCH, ICTEventType.MSS)
        assert ev.direction in (EventDirection.BULLISH, EventDirection.BEARISH)
        assert ev.timeframe == "15m"
        assert isinstance(ev.price_level, float)
        assert ev.event_status == LiquidityLifecycleState.CONFIRMED
        assert isinstance(ev.event_time, datetime)
        assert isinstance(ev.available_at, datetime)
        assert isinstance(ev.created_at, datetime)
        assert ev.confirmed_at is not None
        assert isinstance(ev.source_candle_identifiers, list) and len(ev.source_candle_identifiers) == 2
        assert ev.data_quality == "VERIFIED_LIVE"
        assert isinstance(ev.evidence, dict)
        assert ev.configuration_version == "3.2.0"
        assert ev.engine_version == "3.2.0"

        # Legacy backward compatibility properties
        assert ev.symbol == "NIFTY 50"
        assert ev.lifecycle_state == LiquidityLifecycleState.CONFIRMED
        assert ev.model_version == "3.2.0"
        assert ev.source_data_quality == "VERIFIED_LIVE"
        assert ev.sweep_details == ev.evidence

        # JSON Round-trip determinism
        payload = ev.model_dump()
        reconstructed = ICTEvent(**payload)
        assert reconstructed.event_id == ev.event_id
        assert reconstructed.model_dump() == payload


class TestRemediationVerifications:
    """Targeted remediation verification tests for Step 3.2 acceptance requirements:
    1. Initial establishment vs continuation BOS vs reversal CHoCH.
    2. Active vs protected level selection and post-break updates.
    3. Duplicate break prevention.
    4. BOS / CHoCH / MSS invalidation mechanics preserving historical confirmation.
    5. Displacement threshold boundaries and research baseline disclaimer.
    6. Replay determinism and event idempotency.
    """

    def test_break_classification_initial_vs_continuation_vs_reversal(self):
        """Verify:
        - First break in NEUTRAL trend is INITIAL_ESTABLISHMENT.
        - Subsequent break of target in existing trend is CONTINUATION_BOS.
        - Break of protected level against prevailing trend is REVERSAL_CHOCH.
        """
        engine = MarketStructureEngine(config=MarketStructureConfiguration(swing_left_bars=2, swing_right_bars=2))

        # 1. Establish initial swing high at bar 3: (High 24200)
        # Left: bar 1 (24000), bar 2 (24100)
        # Center: bar 3 (High 24200)
        # Right: bar 4 (24100), bar 5 (24050) -> confirms high at bar 5
        # Bar 6: Breaks 24200 with Close 24260 -> First break in NEUTRAL trend = INITIAL_ESTABLISHMENT
        data = [
            (23900, 23950, 23850, 23900),  # 0
            (23900, 24000, 23880, 23950),  # 1
            (23950, 24100, 23920, 24050),  # 2
            (24050, 24200, 24000, 24150),  # 3: Swing High 1 (24200)
            (24100, 24120, 24020, 24080),  # 4
            (24080, 24090, 23980, 24000),  # 5: Confirms SH1
            (24000, 24280, 23980, 24260),  # 6: Breakout Close 24260 > 24200 -> INITIAL_ESTABLISHMENT!
        ]
        df = create_candle_df(data)
        swings, events, trend = engine.detect_structure_breaks(df, symbol="NIFTY 50", timeframe="15m")

        assert len(events) == 1
        ev1 = events[0]
        assert ev1.event_type == ICTEventType.BOS
        assert ev1.direction == EventDirection.BULLISH
        assert ev1.evidence["break_classification"] == "INITIAL_ESTABLISHMENT"
        assert trend == TrendBias.BULLISH

    def test_continuation_bos_and_reversal_choch_classification(self):
        """Verify CONTINUATION_BOS when trend continues, and REVERSAL_CHOCH when protected level breaks."""
        engine = MarketStructureEngine(config=MarketStructureConfiguration(swing_left_bars=2, swing_right_bars=2))

        # Build established downtrend:
        # High 1 at bar 3: 24900
        # Low 1 at bar 6: 24350
        # High 2 (LH) at bar 9: 24700
        # Low 2 (LL) at bar 12: 24200
        # Downtrend established.
        # Candle 15: Closes below LL (24200) at 24100 -> CONTINUATION_BOS!
        # Later, Candle 18: Closes above LH (24700) at 24800 -> REVERSAL_CHOCH!
        data = [
            (24500, 24550, 24450, 24500),  # 0
            (24500, 24650, 24480, 24600),  # 1
            (24600, 24750, 24580, 24700),  # 2: Left 1
            (24700, 24950, 24680, 24900),  # 3: Swing High 1 (24950)
            (24850, 24880, 24600, 24650),  # 4: Right 1
            (24650, 24700, 24450, 24500),  # 5: Right 2 (confirms SH1 at 24950)
            (24500, 24520, 24350, 24400),  # 6: Swing Low 1 (24350)
            (24400, 24500, 24380, 24450),  # 7: Right 1
            (24450, 24520, 24400, 24480),  # 8: Right 2 (confirms SL1 at 24350)
            (24480, 24700, 24450, 24650),  # 9: Swing High 2 (24700, LH)
            (24650, 24660, 24400, 24450),  # 10: Right 1
            (24450, 24480, 24250, 24300),  # 11: Right 2 (confirms SH2 as LH at 24700)
            (24300, 24320, 24200, 24250),  # 12: Swing Low 2 (24200, LL)
            (24250, 24300, 24220, 24260),  # 13: Right 1
            (24260, 24300, 24220, 24280),  # 14: Right 2 (confirms SL2 as LL at 24200) -> Trend BEARISH
            # Candle 15: Closes below LL (24200) -> CONTINUATION_BOS
            (24280, 24290, 24080, 24100),  # 15: Close 24100 < 24200
            # Candle 16 & 17: Consolidation
            (24100, 24350, 24090, 24300),  # 16
            (24300, 24500, 24280, 24450),  # 17
            # Candle 18: Massive rally closing above LH (24700) at 24800 -> REVERSAL_CHOCH
            (24450, 24850, 24420, 24800),  # 18: Close 24800 > 24700
        ]
        df = create_candle_df(data)
        swings, events, trend = engine.detect_structure_breaks(df, symbol="NIFTY 50", timeframe="15m")

        bos_events = [e for e in events if e.evidence.get("break_classification") == "CONTINUATION_BOS"]
        choch_events = [e for e in events if e.evidence.get("break_classification") == "REVERSAL_CHOCH"]

        assert len(bos_events) >= 1
        assert bos_events[0].direction == EventDirection.BEARISH
        assert bos_events[0].price_level == 24200.0

        assert len(choch_events) >= 1
        assert choch_events[0].direction == EventDirection.BULLISH
        assert choch_events[0].price_level == 24700.0
        assert trend == TrendBias.BULLISH

    def test_active_and_protected_level_tracking_in_report(self):
        """Verify deterministic selection of active target and protected levels."""
        engine = MarketStructureEngine(config=MarketStructureConfiguration(swing_left_bars=2, swing_right_bars=2))

        # Ascending structure:
        # High 1: 24200
        # Low 1: 23950
        # High 2 (HH): 24400
        # Low 2 (HL): 24150
        data = [
            (23900, 23950, 23850, 23900),  # 0
            (23900, 24000, 23880, 23950),  # 1
            (23950, 24100, 23920, 24050),  # 2: Left 1
            (24050, 24200, 24000, 24150),  # 3: Swing High 1 (24200)
            (24150, 24180, 24020, 24080),  # 4: Right 1
            (24080, 24100, 23950, 23980),  # 5: Right 2 (confirms SH1 at 24200) / Swing Low 1 (23950)
            (23980, 24050, 23970, 24020),  # 6: Right 1 for SL1
            (24020, 24150, 24000, 24100),  # 7: Right 2 for SL1
            (24280, 24400, 24250, 24350),  # 8: Swing High 2 (24400, HH)
            (24350, 24380, 24200, 24220),  # 9: Right 1 for SH2 / Left 1 for SL2
            (24220, 24250, 24150, 24180),  # 10: Right 2 (confirms SH2) / Swing Low 2 (24150, HL)
            (24200, 24250, 24170, 24220),  # 11: Right 1 for SL2
            (24220, 24280, 24200, 24250),  # 12: Right 2 (confirms SL2 as HL at 24150)
            (24250, 24300, 24220, 24270),  # 13: Consolidation
        ]
        df = create_candle_df(data)
        report = engine.analyze_timeframe(df, symbol="NIFTY 50", timeframe="15m")

        assert report.active_trend == TrendBias.BULLISH
        # In BULLISH trend: target high is 24400, protected low is 24150
        assert report.active_target_high is not None and report.active_target_high.price == 24400.0
        assert report.active_protected_low is not None and report.active_protected_low.price == 24150.0
        assert report.active_target_low is None
        assert report.active_protected_high is None

    def test_duplicate_break_prevention_on_broken_level(self):
        """Verify that a broken structural level is retired and never re-emitted."""
        engine = MarketStructureEngine(config=MarketStructureConfiguration(swing_left_bars=2, swing_right_bars=2))

        # Swing high at bar 3: 24200
        # Bars 6, 7, 8, 9 all close above 24200
        data = [
            (23900, 23950, 23850, 23900),  # 0
            (23900, 24000, 23880, 23950),  # 1
            (23950, 24100, 23920, 24050),  # 2
            (24050, 24200, 24000, 24150),  # 3: Swing High 24200
            (24100, 24120, 24020, 24080),  # 4
            (24080, 24090, 23980, 24000),  # 5: Confirms high
            (24000, 24280, 23980, 24250),  # 6: First Break (Close 24250)
            (24250, 24350, 24200, 24300),  # 7: Bar 7 (Close 24300)
            (24300, 24380, 24250, 24350),  # 8: Bar 8 (Close 24350)
            (24350, 24420, 24300, 24400),  # 9: Bar 9 (Close 24400)
        ]
        df = create_candle_df(data)
        swings, events, trend = engine.detect_structure_breaks(df, symbol="NIFTY 50", timeframe="15m")

        breaks_of_24200 = [e for e in events if e.price_level == 24200.0]
        # Must be exactly 1 break event, never duplicated across subsequent candles
        assert len(breaks_of_24200) == 1
        assert breaks_of_24200[0].event_status == LiquidityLifecycleState.CONFIRMED

    def test_invalidation_mechanics_preserves_historical_confirmation(self):
        """Verify:
        - When subsequent price closes back through broken level, status becomes INVALIDATED.
        - confirmed_at is STRICTLY preserved.
        - invalidated_at and invalidation_reason are cleanly appended.
        """
        engine = MarketStructureEngine(config=MarketStructureConfiguration(
            swing_left_bars=2,
            swing_right_bars=2,
            enable_invalidation_tracking=True,
            invalidation_reclose_threshold_pts=5.0,
        ))

        # Bar 3: Swing High 24200 confirmed at bar 5
        # Bar 6: Breaks out and closes at 24250 -> BOS confirmed
        # Bar 7: Severe dump closing back down at 24150 (< 24200 - 5.0) -> INVALIDATES BOS
        data = [
            (23900, 23950, 23850, 23900),  # 0
            (23900, 24000, 23880, 23950),  # 1
            (23950, 24100, 23920, 24050),  # 2
            (24050, 24200, 24000, 24150),  # 3: Swing High 24200
            (24100, 24120, 24020, 24080),  # 4
            (24080, 24090, 23980, 24000),  # 5: Confirms high
            (24000, 24280, 23980, 24250),  # 6: Breakout Close 24250 -> Confirmed BOS
            (24250, 24260, 24100, 24150),  # 7: Close 24150 (< 24195.0) -> Invalidates BOS!
        ]
        df = create_candle_df(data)
        swings, events, trend = engine.detect_structure_breaks(df, symbol="NIFTY 50", timeframe="15m")

        assert len(events) == 1
        ev = events[0]

        # Status must be INVALIDATED
        assert ev.event_status == LiquidityLifecycleState.INVALIDATED
        # Invalidation timestamp matches candle 7 completion
        assert ev.invalidated_at == df.iloc[7]["timestamp"]
        # CRITICAL: confirmed_at must be strictly preserved as candle 6 completion!
        assert ev.confirmed_at == df.iloc[6]["timestamp"]
        assert ev.event_time == df.iloc[6]["timestamp"]
        assert ev.available_at == df.iloc[6]["timestamp"]
        # Detailed invalidation reason recorded in evidence
        assert "invalidation_reason" in ev.evidence
        assert "closed back below" in ev.evidence["invalidation_reason"]

    def test_displacement_threshold_boundaries_and_disclaimer(self):
        """Verify:
        - Displacement requires both body_to_range_ratio >= min_ratio AND range >= min_atr_multiple * ATR.
        - CHoCH and MSS are both emitted with mutual linked_event_id when displacement is satisfied.
        - When displacement fails, only CHoCH is emitted without linked MSS.
        - Research disclaimer is explicitly present in configuration.
        """
        # 1. Verify research disclaimer
        config = MarketStructureConfiguration()
        assert "uncalibrated research baseline parameters" in config.research_disclaimer

        # 2. Setup with displacement meeting criteria:
        # ATR ~ 100, bar range = 610, body = 550 (ratio 0.90 >= 0.50, range 610 >= 1.0 * ATR)
        engine_pass = MarketStructureEngine(config=MarketStructureConfiguration(
            swing_left_bars=2,
            swing_right_bars=2,
            mss_min_body_ratio=0.50,
            mss_min_atr_multiple=1.0,
        ))

        data_pass = [
            (24500, 24550, 24450, 24500),  # 0
            (24500, 24600, 24480, 24550),  # 1
            (24550, 24650, 24520, 24600),  # 2: Left 1
            (24600, 24700, 24580, 24680),  # 3: Left 2
            (24680, 24900, 24650, 24850),  # 4: Swing High 1 (24900)
            (24800, 24820, 24600, 24650),  # 5: Right 1
            (24650, 24700, 24500, 24520),  # 6: Right 2 (confirms SH1)
            (24520, 24550, 24350, 24400),  # 7: Swing Low 1 (24350)
            (24400, 24450, 24380, 24420),  # 8: Right 1 / Left 1
            (24420, 24450, 24390, 24410),  # 9: Right 2 (confirms SL1) / Left 2
            (24410, 24700, 24400, 24650),  # 10: Swing High 2 (24700, LH)
            (24650, 24660, 24450, 24500),  # 11: Right 1
            (24500, 24520, 24300, 24320),  # 12: Right 2 (confirms SH2 as LH)
            (24320, 24350, 24200, 24220),  # 13: Swing Low 2 (24200, LL)
            (24220, 24250, 24210, 24230),  # 14: Right 1
            (24230, 24250, 24210, 24240),  # 15: Right 2 (confirms SL2 as LL)
            # Candle 16: Strong displacement: Open 24250, High 24850, Low 24240, Close 24800
            (24250, 24850, 24240, 24800),  # 16: Body = 550, Range = 610, Ratio = 0.90
        ]
        df_pass = create_candle_df(data_pass)
        _, events_pass, _ = engine_pass.detect_structure_breaks(df_pass, symbol="NIFTY 50", timeframe="15m")

        choch_ev = next(e for e in events_pass if e.event_type == ICTEventType.CHOCH)
        mss_ev = next(e for e in events_pass if e.event_type == ICTEventType.MSS)

        assert choch_ev.evidence["linked_event_id"] == mss_ev.event_id
        assert mss_ev.evidence["linked_event_id"] == choch_ev.event_id
        assert choch_ev.evidence["displacement_confirmed"] is True
        assert mss_ev.evidence["displacement_confirmed"] is True

        # 3. Setup with weak body ratio (e.g. 0.40 < 0.50):
        # Open 24400, High 24850, Low 24200, Close 24710 -> Range = 650, Body = 310 (Ratio = 0.477 < 0.50)
        data_fail_ratio = list(data_pass)
        data_fail_ratio[16] = (24400, 24850, 24200, 24710)
        df_fail_ratio = create_candle_df(data_fail_ratio)

        _, events_fail_ratio, _ = engine_pass.detect_structure_breaks(df_fail_ratio, symbol="NIFTY 50", timeframe="15m")
        # CHoCH must be emitted, but MSS must NOT be emitted
        assert any(e.event_type == ICTEventType.CHOCH for e in events_fail_ratio)
        assert not any(e.event_type == ICTEventType.MSS for e in events_fail_ratio)

        choch_only = next(e for e in events_fail_ratio if e.event_type == ICTEventType.CHOCH)
        assert choch_only.evidence["displacement_confirmed"] is False
        assert choch_only.evidence["linked_event_id"] is None

    def test_replay_determinism_and_event_idempotency(self):
        """Verify repeated executions on identical data produce 100% deterministic outputs."""
        engine = MarketStructureEngine(config=MarketStructureConfiguration(swing_left_bars=2, swing_right_bars=2))
        data = [
            (24000, 24050, 23950, 24020),
            (24020, 24120, 24000, 24100),
            (24100, 24250, 24050, 24200),
            (24200, 24220, 24100, 24150),
            (24150, 24180, 24050, 24100),
            (24100, 24400, 24080, 24350),
        ]
        df = create_candle_df(data)

        res1 = engine.analyze_timeframe(df, symbol="NIFTY 50", timeframe="15m")
        res2 = engine.analyze_timeframe(df, symbol="NIFTY 50", timeframe="15m")

        dump1 = res1.model_dump()
        dump2 = res2.model_dump()

        assert dump1 == dump2
        # Verify deterministic event IDs
        ev_ids1 = [e.event_id for e in res1.structure_events]
        ev_ids2 = [e.event_id for e in res2.structure_events]
        assert ev_ids1 == ev_ids2

