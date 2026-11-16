"""
AIVOLVE Phase 3 Step 3.1 Dedicated Test Suite: Liquidity Intelligence Engine.
Tests:
1. Common Event Contract (ICTEvent, SwingPoint, LiquidityPool, LiquidityEvent, Lifecycle State Machine)
2. Deterministic ID generation, idempotency, and timezone-awareness
3. Swing Detection Engine (pivots, left/right confirmation delay, tie-breaking, anti-lookahead)
4. Liquidity Intelligence Engine (BSL, SSL, EQH, EQL, PDH/PDL, PWH/PWL, Session/Opening Range)
5. Wick penetration vs candle-close breakout, sweep-and-reclaim lifecycle, missing volume, and replay determinism
"""

import pytest
from datetime import datetime, timezone, timedelta
import pandas as pd
import numpy as np
import zoneinfo

from app.options.ict_smc.ict_models import (
    ICTEvent,
    ICTEventType,
    EventDirection,
    ICTTimeframe,
    LiquidityType,
    LiquidityLifecycleState,
    VALID_LIFECYCLE_TRANSITIONS,
    validate_lifecycle_transition,
    generate_deterministic_event_id,
    LiquidityEvidence,
    SwingPoint,
    LiquidityPool,
    LiquidityEvent,
    LiquidityConfiguration,
    _ensure_timezone_aware,
    IST_ZONE,
)
from app.options.ict_smc.swing_detection import SwingDetectionEngine
from app.options.ict_smc.liquidity_engine import (
    LiquidityIntelligenceEngine,
    LiquidityDetectionEngine,
)


# ---------------------------------------------------------------------
# Fixtures & Synthetic Data Helpers
# ---------------------------------------------------------------------

@pytest.fixture
def sample_timestamps():
    """Generates 20 15M timestamps during Indian market hours (09:15 onwards)."""
    base = datetime(2026, 11, 4, 9, 15, tzinfo=IST_ZONE)
    return [base + timedelta(minutes=15 * i) for i in range(20)]


@pytest.fixture
def sample_candles_with_clear_pivots(sample_timestamps):
    """
    Creates a 20-candle series with known, unequivocal peaks and troughs:
    - Candle 5: Peak High = 25100.0 (Swing High confirmed by bar 8 under 3-bar window)
    - Candle 12: Trough Low = 24900.0 (Swing Low confirmed by bar 15 under 3-bar window)
    """
    ts = sample_timestamps
    data = []
    prices = [
        25000, 25020, 25050, 25080, 25070,  # 0..4
        25100,                              # 5: Peak High
        25060, 25040, 25010, 24980, 24950,  # 6..10
        24920,                              # 11
        24900,                              # 12: Trough Low
        24930, 24960, 24990, 25010, 25020,  # 13..17
        25030, 25040                        # 18..19
    ]

    for i in range(20):
        p = prices[i]
        is_peak = (i == 5)
        is_trough = (i == 12)

        h = p + (15.0 if not is_peak else 25.0)
        l = p - (15.0 if not is_trough else 25.0)
        o = p - 5.0
        c = p + 5.0
        v = 25000 + i * 500

        data.append({
            "timestamp": ts[i],
            "open": o,
            "high": h,
            "low": l,
            "close": c,
            "volume": v,
        })

    return pd.DataFrame(data)


# ---------------------------------------------------------------------
# 1. Event Models & Contracts Tests
# ---------------------------------------------------------------------

class TestEventModelsAndContracts:

    def test_valid_event_construction(self):
        now_dt = datetime.now(IST_ZONE)
        eid = generate_deterministic_event_id("NIFTY 50", "15m", "SWING_HIGH", "2026-11-04T09:15:00", "3.1.0")

        event = ICTEvent(
            event_id=eid,
            index="NIFTY 50",
            event_type=ICTEventType.SWING_HIGH,
            direction=EventDirection.BEARISH,
            timeframe="15m",
            price_level=25100.0,
            event_status=LiquidityLifecycleState.IDENTIFIED,
            created_at=now_dt,
            event_time=now_dt,
            available_at=now_dt,
            source_candle_identifiers=["2026-11-04T09:15:00"],
            source_data_quality="VERIFIED_LIVE",
            configuration_version="3.1.0",
            engine_version="3.1.0",
        )

        assert event.event_id.startswith("EVT-SWI-")
        assert event.index == "NIFTY 50"
        assert event.price_level == 25100.0
        assert event.event_status == LiquidityLifecycleState.IDENTIFIED

    def test_deterministic_event_id_generation_and_uniqueness(self):
        # Same canonical inputs MUST yield identical IDs
        id1 = generate_deterministic_event_id("NIFTY 50", "15m", "BSL", "candle_100", "3.1.0")
        id2 = generate_deterministic_event_id("NIFTY 50", "15m", "BSL", "candle_100", "3.1.0")
        assert id1 == id2
        assert len(id1) > 10

        # Different configuration versions MUST yield distinct IDs
        id_v2 = generate_deterministic_event_id("NIFTY 50", "15m", "BSL", "candle_100", "3.2.0")
        assert id1 != id_v2

        # Different timeframe or candle ID MUST yield distinct IDs
        id_tf = generate_deterministic_event_id("NIFTY 50", "5m", "BSL", "candle_100", "3.1.0")
        assert id1 != id_tf

    def test_lifecycle_state_machine_valid_transitions(self):
        now_dt = datetime.now(IST_ZONE)
        pid = generate_deterministic_event_id("NIFTY 50", "15m", "BSL", "c1", "3.1.0")

        pool = LiquidityPool(
            pool_id=pid,
            index="NIFTY 50",
            liquidity_type=LiquidityType.BSL,
            direction=EventDirection.BEARISH,
            timeframe="15m",
            level=25100.0,
            upper_bound=25110.0,
            lower_bound=25100.0,
            status=LiquidityLifecycleState.IDENTIFIED,
            formation_time=now_dt,
            available_at=now_dt,
            updated_at=now_dt,
        )

        # IDENTIFIED -> APPROACHING
        pool.transition_to(LiquidityLifecycleState.APPROACHING, now_dt)
        assert pool.status == LiquidityLifecycleState.APPROACHING

        # APPROACHING -> SWEPT
        pool.transition_to(LiquidityLifecycleState.SWEPT, now_dt)
        assert pool.status == LiquidityLifecycleState.SWEPT

        # SWEPT -> RECLAIMED
        pool.transition_to(LiquidityLifecycleState.RECLAIMED, now_dt)
        assert pool.status == LiquidityLifecycleState.RECLAIMED

        # RECLAIMED -> CONFIRMED
        pool.transition_to(LiquidityLifecycleState.CONFIRMED, now_dt)
        assert pool.status == LiquidityLifecycleState.CONFIRMED

        # CONFIRMED -> CONSUMED (Terminal)
        pool.transition_to(LiquidityLifecycleState.CONSUMED, now_dt)
        assert pool.status == LiquidityLifecycleState.CONSUMED

    def test_lifecycle_state_machine_invalid_transitions_rejected(self):
        now_dt = datetime.now(IST_ZONE)
        pid = generate_deterministic_event_id("NIFTY 50", "15m", "BSL", "c2", "3.1.0")

        pool = LiquidityPool(
            pool_id=pid,
            index="NIFTY 50",
            liquidity_type=LiquidityType.BSL,
            direction=EventDirection.BEARISH,
            timeframe="15m",
            level=25100.0,
            upper_bound=25110.0,
            lower_bound=25100.0,
            status=LiquidityLifecycleState.CONSUMED,  # Terminal state
            formation_time=now_dt,
            available_at=now_dt,
            updated_at=now_dt,
        )

        # Terminal state CONSUMED cannot transition back to IDENTIFIED or SWEPT
        with pytest.raises(ValueError, match="Invalid lifecycle transition"):
            pool.transition_to(LiquidityLifecycleState.IDENTIFIED, now_dt)

        with pytest.raises(ValueError, match="Invalid lifecycle transition"):
            pool.transition_to(LiquidityLifecycleState.SWEPT, now_dt)

    def test_timezone_aware_timestamp_handling(self):
        naive_dt = datetime(2026, 11, 4, 10, 30)
        aware_dt = _ensure_timezone_aware(naive_dt)
        assert aware_dt.tzinfo is not None
        assert str(aware_dt.tzinfo) == "Asia/Kolkata"

    def test_invalid_event_model_rejected(self):
        from pydantic import ValidationError
        now_dt = datetime.now(IST_ZONE)
        with pytest.raises(ValidationError):
            ICTEvent(
                event_id="EVT-TEST",
                index="NIFTY 50",
                event_type="NON_EXISTENT_TYPE",  # Invalid
                direction=EventDirection.BULLISH,
                timeframe="15m",
                created_at=now_dt,
                event_time=now_dt,
                available_at=now_dt,
            )


# ---------------------------------------------------------------------
# 2. Swing Detection Engine Tests
# ---------------------------------------------------------------------

class TestSwingDetectionEngine:

    def test_swing_high_detection_with_confirmation_delay(self, sample_candles_with_clear_pivots):
        df = sample_candles_with_clear_pivots
        engine = SwingDetectionEngine(LiquidityConfiguration(swing_left_bars=3, swing_right_bars=3))

        highs = engine.detect_swing_highs(df, symbol="NIFTY 50", timeframe="15m", left_bars=3, right_bars=3)

        assert len(highs) >= 1
        peak_sh = next(h for h in highs if h.bar_index == 5)
        assert peak_sh.swing_type == "HIGH"
        assert peak_sh.price > 25100.0

        # Critical Anti-Lookahead check:
        # Pivot happened at bar 5 (event_time = timestamp of bar 5)
        # But confirmation completed at bar 5 + 3 = bar 8 (available_at = timestamp of bar 8)
        assert peak_sh.event_time == df.iloc[5]["timestamp"]
        assert peak_sh.available_at == df.iloc[8]["timestamp"]
        assert peak_sh.available_at > peak_sh.event_time

    def test_swing_low_detection_with_confirmation_delay(self, sample_candles_with_clear_pivots):
        df = sample_candles_with_clear_pivots
        engine = SwingDetectionEngine(LiquidityConfiguration(swing_left_bars=3, swing_right_bars=3))

        lows = engine.detect_swing_lows(df, symbol="NIFTY 50", timeframe="15m", left_bars=3, right_bars=3)

        assert len(lows) >= 1
        trough_sl = next(l for l in lows if l.bar_index == 12)
        assert trough_sl.swing_type == "LOW"
        assert trough_sl.price < 24900.0

        # Confirmation delay check
        assert trough_sl.event_time == df.iloc[12]["timestamp"]
        assert trough_sl.available_at == df.iloc[15]["timestamp"]
        assert trough_sl.available_at > trough_sl.event_time

    def test_swing_anti_lookahead_as_of_filtering(self, sample_candles_with_clear_pivots):
        df = sample_candles_with_clear_pivots
        engine = SwingDetectionEngine()

        # At time of bar 6, bar 5 peak has occurred, BUT right 3 confirmation bars (bar 6, 7, 8)
        # have NOT all completed!
        cutoff_time = df.iloc[6]["timestamp"]
        pivots_at_t6 = engine.detect_swings(df, as_of_time=cutoff_time)

        # Bar 5 peak MUST NOT appear in results as of bar 6!
        assert not any(p.bar_index == 5 for p in pivots_at_t6)

        # At time of bar 8, confirmation is complete! Bar 5 peak MUST now be available.
        cutoff_time_t8 = df.iloc[8]["timestamp"]
        pivots_at_t8 = engine.detect_swings(df, as_of_time=cutoff_time_t8)
        assert any(p.bar_index == 5 for p in pivots_at_t8)

    def test_equal_extrema_tie_breaking_policies(self, sample_timestamps):
        ts = sample_timestamps[:10]
        # Bar 3 and Bar 4 have EXACT same high
        df_tie = pd.DataFrame([
            {"timestamp": ts[0], "open": 25000, "high": 25010, "low": 24990, "close": 25005, "volume": 1000},
            {"timestamp": ts[1], "open": 25005, "high": 25020, "low": 25000, "close": 25015, "volume": 1000},
            {"timestamp": ts[2], "open": 25015, "high": 25030, "low": 25010, "close": 25025, "volume": 1000},
            {"timestamp": ts[3], "open": 25025, "high": 25100, "low": 25020, "close": 25090, "volume": 1000},  # Peak 1
            {"timestamp": ts[4], "open": 25090, "high": 25100, "low": 25070, "close": 25080, "volume": 1000},  # Peak 2 (Tie)
            {"timestamp": ts[5], "open": 25080, "high": 25060, "low": 25040, "close": 25050, "volume": 1000},
            {"timestamp": ts[6], "open": 25050, "high": 25040, "low": 25020, "close": 25030, "volume": 1000},
            {"timestamp": ts[7], "open": 25030, "high": 25020, "low": 25000, "close": 25010, "volume": 1000},
        ])

        engine = SwingDetectionEngine()
        # 'FIRST' policy picks bar 3
        swings_first = engine.detect_swing_highs(df_tie, left_bars=2, right_bars=2, tie_breaking_policy="FIRST")
        assert len(swings_first) == 1
        assert swings_first[0].bar_index == 3

        # 'LAST' policy picks bar 4
        swings_last = engine.detect_swing_highs(df_tie, left_bars=2, right_bars=2, tie_breaking_policy="LAST")
        assert len(swings_last) == 1
        assert swings_last[0].bar_index == 4

    def test_swing_replay_determinism_and_non_repainting(self, sample_candles_with_clear_pivots):
        df = sample_candles_with_clear_pivots
        engine = SwingDetectionEngine()

        res1 = engine.detect_swings(df)
        res2 = engine.detect_swings(df)

        assert len(res1) == len(res2)
        for s1, s2 in zip(res1, res2):
            assert s1.event_id == s2.event_id
            assert s1.price == s2.price
            assert s1.available_at == s2.available_at


# ---------------------------------------------------------------------
# 3. Liquidity Intelligence Engine Tests
# ---------------------------------------------------------------------

class TestLiquidityIntelligenceEngine:

    def test_bsl_and_ssl_pool_generation_from_swings(self, sample_candles_with_clear_pivots):
        df = sample_candles_with_clear_pivots
        engine = LiquidityIntelligenceEngine()

        pools = engine.detect_liquidity_pools(df, symbol="NIFTY 50", timeframe="15m")

        bsl = [p for p in pools if p.liquidity_type == LiquidityType.BSL]
        ssl = [p for p in pools if p.liquidity_type == LiquidityType.SSL]

        assert len(bsl) >= 1
        assert len(ssl) >= 1

        # High swing pool is at level 25125.0
        assert any(p.level > 25100.0 for p in bsl)
        # Low swing pool is at level 24875.0
        assert any(p.level < 24900.0 for p in ssl)

    def test_equal_highs_and_equal_lows_clustering(self, sample_timestamps):
        ts = sample_timestamps[:16]
        # Create two distinct peaks with nearly identical price within 0.10% tolerance (e.g. 25050.0 and 25051.0)
        df_eq = pd.DataFrame([
            {"timestamp": ts[0], "open": 25000, "high": 25010, "low": 24990, "close": 25005, "volume": 1000},
            {"timestamp": ts[1], "open": 25005, "high": 25050, "low": 25000, "close": 25040, "volume": 1000},  # Peak 1 (Bar 1)
            {"timestamp": ts[2], "open": 25040, "high": 25020, "low": 25010, "close": 25015, "volume": 1000},
            {"timestamp": ts[3], "open": 25015, "high": 25010, "low": 24990, "close": 25000, "volume": 1000},
            {"timestamp": ts[4], "open": 25000, "high": 25051, "low": 24995, "close": 25045, "volume": 1000},  # Peak 2 (Bar 4, within 1 pt!)
            {"timestamp": ts[5], "open": 25045, "high": 25020, "low": 25010, "close": 25015, "volume": 1000},
            {"timestamp": ts[6], "open": 25015, "high": 25005, "low": 24990, "close": 24995, "volume": 1000},
            {"timestamp": ts[7], "open": 24995, "high": 24990, "low": 24970, "close": 24980, "volume": 1000},
        ])

        cfg = LiquidityConfiguration(swing_left_bars=1, swing_right_bars=1, eq_tolerance_pct=0.0010)
        engine = LiquidityIntelligenceEngine(config=cfg)

        pools = engine.detect_liquidity_pools(df_eq, symbol="NIFTY 50", timeframe="15m")
        eqh_pools = [p for p in pools if p.liquidity_type == LiquidityType.EQH]

        assert len(eqh_pools) >= 1
        eqh = eqh_pools[0]
        assert eqh.touch_count >= 2
        assert eqh.level == pytest.approx(25050.5, abs=0.5)
        assert eqh.evidence.touch_count >= 2

    def test_previous_day_and_week_liquidity_detection(self, sample_candles_with_clear_pivots):
        df = sample_candles_with_clear_pivots
        engine = LiquidityIntelligenceEngine()

        pools = engine.detect_liquidity_pools(
            df=df,
            symbol="NIFTY 50",
            prev_day_high=25200.0,
            prev_day_low=24800.0,
            prev_week_high=25350.0,
            prev_week_low=24700.0,
        )

        pdh = next((p for p in pools if p.liquidity_type == LiquidityType.PDH), None)
        pdl = next((p for p in pools if p.liquidity_type == LiquidityType.PDL), None)
        pwh = next((p for p in pools if p.liquidity_type == LiquidityType.PWH), None)
        pwl = next((p for p in pools if p.liquidity_type == LiquidityType.PWL), None)

        assert pdh is not None and pdh.level == 25200.0
        assert pdl is not None and pdl.level == 24800.0
        assert pwh is not None and pwh.level == 25350.0
        assert pwl is not None and pwl.level == 24700.0

    def test_wick_penetration_vs_candle_close_breakout(self, sample_timestamps):
        ts = sample_timestamps[:6]
        # Pool at 25100.0
        pool_bsl = LiquidityPool(
            pool_id="POOL_TEST_BSL",
            index="NIFTY 50",
            liquidity_type=LiquidityType.BSL,
            direction=EventDirection.BEARISH,
            timeframe="15m",
            level=25100.0,
            upper_bound=25110.0,
            lower_bound=25100.0,
            status=LiquidityLifecycleState.IDENTIFIED,
            formation_time=ts[0],
            available_at=ts[0],
            updated_at=ts[0],
        )

        # Bar 1: Wick reaches 25104 (penetration=4 pts), but body closes at 25098 with small wick (upper wick = 6, range = 24 -> wick_ratio = 0.25 < 0.35) -> SWEPT
        df_wick = pd.DataFrame([
            {"timestamp": ts[1], "open": 25085, "high": 25104, "low": 25080, "close": 25098, "volume": 50000},
        ])

        engine = LiquidityIntelligenceEngine()
        updated_pools, events = engine.evaluate_liquidity_lifecycle([pool_bsl], df_wick)

        assert updated_pools[0].status == LiquidityLifecycleState.SWEPT
        assert len(events) >= 1
        assert events[0].is_wick_sweep is True
        assert events[0].is_candle_close_breakout is False

        # Now test Decisive Breakout: Bar closes decisively above upper_bound (close=25130 > 25110)
        pool_bsl_2 = pool_bsl.model_copy()
        df_breakout = pd.DataFrame([
            {"timestamp": ts[1], "open": 25090, "high": 25140, "low": 25085, "close": 25130, "volume": 90000},
        ])
        updated_breakout, _ = engine.evaluate_liquidity_lifecycle([pool_bsl_2], df_breakout)
        assert updated_breakout[0].status == LiquidityLifecycleState.CONSUMED

    def test_sweep_and_reclaim_lifecycle_progression(self, sample_timestamps):
        ts = sample_timestamps[:5]
        pool_ssl = LiquidityPool(
            pool_id="POOL_TEST_SSL",
            index="NIFTY 50",
            liquidity_type=LiquidityType.SSL,
            direction=EventDirection.BULLISH,
            timeframe="15m",
            level=24900.0,
            upper_bound=24900.0,
            lower_bound=24890.0,
            status=LiquidityLifecycleState.IDENTIFIED,
            formation_time=ts[0],
            available_at=ts[0],
            updated_at=ts[0],
        )

        # Bar 1: Pin-bar with huge lower wick breaching 24900 down to 24880, closing at 24915 (reclaim!)
        df_reclaim = pd.DataFrame([
            {"timestamp": ts[1], "open": 24910, "high": 24925, "low": 24880, "close": 24915, "volume": 80000},
            {"timestamp": ts[2], "open": 24915, "high": 24950, "low": 24910, "close": 24945, "volume": 75000},  # Bullish follow-through
        ])

        engine = LiquidityIntelligenceEngine()
        updated_pools, events = engine.evaluate_liquidity_lifecycle([pool_ssl], df_reclaim)

        # Must progress through SWEPT -> RECLAIMED -> CONFIRMED
        assert updated_pools[0].status == LiquidityLifecycleState.CONFIRMED
        assert any(ev.is_reclaimed is True for ev in events)

    def test_missing_volume_preservation_not_zero_volume(self, sample_timestamps):
        ts = sample_timestamps[:5]
        # Dataframe with NaN volume
        df_nan_vol = pd.DataFrame([
            {"timestamp": ts[0], "open": 25000, "high": 25050, "low": 24980, "close": 25020, "volume": np.nan},
            {"timestamp": ts[1], "open": 25020, "high": 25080, "low": 25010, "close": 25070, "volume": np.nan},
            {"timestamp": ts[2], "open": 25070, "high": 25040, "low": 25000, "close": 25010, "volume": np.nan},
        ])

        engine = LiquidityIntelligenceEngine(LiquidityConfiguration(swing_left_bars=1, swing_right_bars=1))
        pools = engine.detect_liquidity_pools(df_nan_vol)

        bsl = next((p for p in pools if p.liquidity_type == LiquidityType.BSL), None)
        assert bsl is not None
        # Observed volume must remain None (missing/unavailable), NEVER silently replaced with 0.0
        assert bsl.evidence.observed_traded_volume is None
        assert bsl.evidence.volume_evidence_available is False

    def test_legacy_facade_compatibility(self, sample_candles_with_clear_pivots):
        df = sample_candles_with_clear_pivots
        # Call legacy static methods on LiquidityDetectionEngine
        legacy_pools = LiquidityDetectionEngine.identify_liquidity_pools(
            df=df,
            daily_high=25150.0,
            daily_low=24850.0,
            prev_day_high=25160.0,
            prev_day_low=24840.0,
        )

        assert "bslPools" in legacy_pools
        assert "sslPools" in legacy_pools
        assert "equalHighs" in legacy_pools
        assert "equalLows" in legacy_pools
        assert isinstance(legacy_pools["bslPools"], list)

        sweeps = LiquidityDetectionEngine.detect_liquidity_sweeps(df, legacy_pools)
        assert isinstance(sweeps, list)

        heatmap = LiquidityDetectionEngine.build_liquidity_heatmap(legacy_pools, current_price=25000.0, atr_14=100.0)
        assert isinstance(heatmap, list)
        if heatmap:
            assert "densityScore" in heatmap[0]
            assert "colorIntensity" in heatmap[0]
            assert "heatDensity" in heatmap[0]

    def test_session_and_opening_range_liquidity(self, sample_timestamps):
        ts = sample_timestamps[:6]  # 09:15, 09:30, 09:45, 10:00, 10:15, 10:30
        df = pd.DataFrame([
            {"timestamp": ts[0], "open": 25000, "high": 25060, "low": 24980, "close": 25040, "volume": 1000},
            {"timestamp": ts[1], "open": 25040, "high": 25090, "low": 25030, "close": 25080, "volume": 1000},
            {"timestamp": ts[2], "open": 25080, "high": 25075, "low": 25010, "close": 25020, "volume": 1000},
            {"timestamp": ts[3], "open": 25020, "high": 25110, "low": 25015, "close": 25100, "volume": 1000},
            {"timestamp": ts[4], "open": 25100, "high": 25120, "low": 25090, "close": 25110, "volume": 1000},
            {"timestamp": ts[5], "open": 25110, "high": 25130, "low": 25100, "close": 25125, "volume": 1000},
        ])

        engine = LiquidityIntelligenceEngine()
        pools = engine.detect_liquidity_pools(df, symbol="NIFTY 50", timeframe="15m")

        orh = next((p for p in pools if p.liquidity_type == LiquidityType.OPENING_RANGE_HIGH), None)
        orl = next((p for p in pools if p.liquidity_type == LiquidityType.OPENING_RANGE_LOW), None)

        assert orh is not None
        assert orl is not None
        # In bars 09:15 to 09:45, highest was bar 1 (high=25090), lowest was bar 0 (low=24980)
        assert orh.level == 25090.0
        assert orl.level == 24980.0

    def test_insufficient_or_empty_candles_returns_empty(self):
        engine = LiquidityIntelligenceEngine()
        assert engine.detect_liquidity_pools(pd.DataFrame()) == []
        assert engine.detect_liquidity_pools(None) == []


# ---------------------------------------------------------------------
# 4. Remediation Matrices: Lifecycle, Tie-Breaking, Thresholds, Sessions, DQ, Schema
# ---------------------------------------------------------------------

from app.data.quality_validator import FeedStatus
from app.data.market_calendar import MarketCalendar


class TestLifecycleRemediationMatrix:

    def test_permitted_transitions_sequence(self):
        now_dt = datetime.now(IST_ZONE)
        pool = LiquidityPool(
            pool_id="POOL_SEQ",
            index="NIFTY 50",
            liquidity_type=LiquidityType.BSL,
            direction=EventDirection.BEARISH,
            timeframe="15m",
            level=25000.0,
            upper_bound=25010.0,
            lower_bound=25000.0,
            status=LiquidityLifecycleState.IDENTIFIED,
            formation_time=now_dt,
            available_at=now_dt,
            updated_at=now_dt,
        )

        assert pool.status == LiquidityLifecycleState.IDENTIFIED
        pool.transition_to(LiquidityLifecycleState.APPROACHING, now_dt)
        assert pool.status == LiquidityLifecycleState.APPROACHING
        pool.transition_to(LiquidityLifecycleState.SWEPT, now_dt)
        assert pool.status == LiquidityLifecycleState.SWEPT
        pool.transition_to(LiquidityLifecycleState.RECLAIMED, now_dt)
        assert pool.status == LiquidityLifecycleState.RECLAIMED
        pool.transition_to(LiquidityLifecycleState.CONFIRMED, now_dt)
        assert pool.status == LiquidityLifecycleState.CONFIRMED

    def test_direct_swept_to_confirmed_prohibited(self):
        now_dt = datetime.now(IST_ZONE)
        pool = LiquidityPool(
            pool_id="POOL_SWEPT_CONF_FAIL",
            index="NIFTY 50",
            liquidity_type=LiquidityType.BSL,
            direction=EventDirection.BEARISH,
            timeframe="15m",
            level=25000.0,
            upper_bound=25010.0,
            lower_bound=25000.0,
            status=LiquidityLifecycleState.SWEPT,
            formation_time=now_dt,
            available_at=now_dt,
            updated_at=now_dt,
        )

        assert not validate_lifecycle_transition(LiquidityLifecycleState.SWEPT, LiquidityLifecycleState.CONFIRMED)
        with pytest.raises(ValueError, match="Invalid lifecycle transition"):
            pool.transition_to(LiquidityLifecycleState.CONFIRMED, now_dt)

    def test_terminal_states_isolation(self):
        now_dt = datetime.now(IST_ZONE)
        terminal_states = [
            LiquidityLifecycleState.CONSUMED,
            LiquidityLifecycleState.EXPIRED,
            LiquidityLifecycleState.INVALIDATED,
        ]
        active_states = [
            LiquidityLifecycleState.IDENTIFIED,
            LiquidityLifecycleState.APPROACHING,
            LiquidityLifecycleState.SWEPT,
            LiquidityLifecycleState.RECLAIMED,
            LiquidityLifecycleState.CONFIRMED,
        ]

        for term in terminal_states:
            for active in active_states:
                assert not validate_lifecycle_transition(term, active)

    def test_expiry_policy_max_lookback(self, sample_timestamps):
        base_ts = sample_timestamps[0]
        pool = LiquidityPool(
            pool_id="POOL_EXPIRY_TEST",
            index="NIFTY 50",
            liquidity_type=LiquidityType.BSL,
            direction=EventDirection.BEARISH,
            timeframe="15m",
            level=25100.0,
            upper_bound=25110.0,
            lower_bound=25100.0,
            status=LiquidityLifecycleState.IDENTIFIED,
            formation_time=base_ts,
            available_at=base_ts,
            updated_at=base_ts,
        )

        # Generate 6 candles far away from pool level
        candles = []
        for i in range(6):
            candles.append({
                "timestamp": base_ts + timedelta(minutes=15 * i),
                "open": 24900,
                "high": 24910,
                "low": 24890,
                "close": 24905,
                "volume": 1000,
            })
        df = pd.DataFrame(candles)

        # Max lookback set to 3 bars
        cfg = LiquidityConfiguration(max_lookback_bars=3, expiry_policy="MAX_LOOKBACK")
        engine = LiquidityIntelligenceEngine(config=cfg)

        updated_pools, _ = engine.evaluate_liquidity_lifecycle([pool], df)
        assert updated_pools[0].status == LiquidityLifecycleState.EXPIRED

    def test_expiry_policy_session_close(self, sample_timestamps):
        t0 = datetime(2026, 11, 4, 15, 0, tzinfo=IST_ZONE)
        pool = LiquidityPool(
            pool_id="POOL_SESSION_EXPIRY",
            index="NIFTY 50",
            liquidity_type=LiquidityType.BSL,
            direction=EventDirection.BEARISH,
            timeframe="15m",
            level=25100.0,
            upper_bound=25110.0,
            lower_bound=25100.0,
            status=LiquidityLifecycleState.IDENTIFIED,
            formation_time=t0,
            available_at=t0,
            updated_at=t0,
        )

        # Candle next morning
        t1 = datetime(2026, 11, 5, 9, 15, tzinfo=IST_ZONE)
        df_next_day = pd.DataFrame([
            {"timestamp": t1, "open": 24900, "high": 24920, "low": 24890, "close": 24910, "volume": 1000}
        ])

        cfg = LiquidityConfiguration(expiry_policy="SESSION_CLOSE")
        engine = LiquidityIntelligenceEngine(config=cfg)
        updated_pools, _ = engine.evaluate_liquidity_lifecycle([pool], df_next_day)
        assert updated_pools[0].status == LiquidityLifecycleState.EXPIRED

    def test_no_institutional_absorption_without_evidence(self, sample_timestamps):
        ts = sample_timestamps[:5]
        pool = LiquidityPool(
            pool_id="POOL_EVID_TEST",
            index="NIFTY 50",
            liquidity_type=LiquidityType.SSL,
            direction=EventDirection.BULLISH,
            timeframe="15m",
            level=24900.0,
            upper_bound=24900.0,
            lower_bound=24890.0,
            status=LiquidityLifecycleState.RECLAIMED,
            formation_time=ts[0],
            available_at=ts[0],
            updated_at=ts[0],
        )

        df = pd.DataFrame([
            {"timestamp": ts[1], "open": 24910, "high": 24940, "low": 24905, "close": 24935, "volume": 1000}
        ])

        engine = LiquidityIntelligenceEngine()
        updated_pools, events = engine.evaluate_liquidity_lifecycle([pool], df)

        # Follow-through candle confirmation should describe empirical reversal without unevidenced absorption assertions
        assert updated_pools[0].status == LiquidityLifecycleState.CONFIRMED
        for ev in events:
            assert "absorption" not in str(ev.evidence.rejection_reasons).lower()


class TestSwingTieBreakingMatrix:

    def test_flat_double_tops_all_policies(self, sample_timestamps):
        ts = sample_timestamps[:6]
        # Symmetrical double top at bars 2 and 3
        df = pd.DataFrame([
            {"timestamp": ts[0], "open": 25000, "high": 25010, "low": 24990, "close": 25005, "volume": 1000},
            {"timestamp": ts[1], "open": 25005, "high": 25050, "low": 25000, "close": 25045, "volume": 1000},
            {"timestamp": ts[2], "open": 25045, "high": 25100, "low": 25040, "close": 25095, "volume": 1000},  # Top 1
            {"timestamp": ts[3], "open": 25095, "high": 25100, "low": 25040, "close": 25080, "volume": 1000},  # Top 2
            {"timestamp": ts[4], "open": 25080, "high": 25050, "low": 25000, "close": 25020, "volume": 1000},
            {"timestamp": ts[5], "open": 25020, "high": 25010, "low": 24990, "close": 25000, "volume": 1000},
        ])

        engine = SwingDetectionEngine()

        # FIRST policy -> selects bar 2
        p_first = engine.detect_swing_highs(df, left_bars=2, right_bars=2, tie_breaking_policy="FIRST")
        assert len(p_first) == 1
        assert p_first[0].bar_index == 2

        # LAST policy -> selects bar 3
        p_last = engine.detect_swing_highs(df, left_bars=2, right_bars=2, tie_breaking_policy="LAST")
        assert len(p_last) == 1
        assert p_last[0].bar_index == 3

        # ALLOW_MULTI -> selects both bar 2 and 3
        p_multi = engine.detect_swing_highs(df, left_bars=2, right_bars=2, tie_breaking_policy="ALLOW_MULTI")
        assert len(p_multi) == 2
        assert [p.bar_index for p in p_multi] == [2, 3]

        # STRICT policy -> neither qualifies (neither is strictly greater than all neighbors)
        p_strict = engine.detect_swing_highs(df, left_bars=2, right_bars=2, tie_breaking_policy="STRICT")
        assert len(p_strict) == 0

    def test_flat_double_bottoms_all_policies(self, sample_timestamps):
        ts = sample_timestamps[:6]
        # Symmetrical double bottom at bars 2 and 3
        df = pd.DataFrame([
            {"timestamp": ts[0], "open": 25100, "high": 25110, "low": 25090, "close": 25095, "volume": 1000},
            {"timestamp": ts[1], "open": 25095, "high": 25060, "low": 25030, "close": 25035, "volume": 1000},
            {"timestamp": ts[2], "open": 25035, "high": 25030, "low": 24950, "close": 24960, "volume": 1000},  # Bottom 1
            {"timestamp": ts[3], "open": 24960, "high": 25030, "low": 24950, "close": 25010, "volume": 1000},  # Bottom 2
            {"timestamp": ts[4], "open": 25010, "high": 25060, "low": 25020, "close": 25055, "volume": 1000},
            {"timestamp": ts[5], "open": 25055, "high": 25110, "low": 25070, "close": 25100, "volume": 1000},
        ])

        engine = SwingDetectionEngine()

        p_first = engine.detect_swing_lows(df, left_bars=2, right_bars=2, tie_breaking_policy="FIRST")
        assert len(p_first) == 1
        assert p_first[0].bar_index == 2

        p_last = engine.detect_swing_lows(df, left_bars=2, right_bars=2, tie_breaking_policy="LAST")
        assert len(p_last) == 1
        assert p_last[0].bar_index == 3

        p_multi = engine.detect_swing_lows(df, left_bars=2, right_bars=2, tie_breaking_policy="ALLOW_MULTI")
        assert len(p_multi) == 2
        assert [p.bar_index for p in p_multi] == [2, 3]

        p_strict = engine.detect_swing_lows(df, left_bars=2, right_bars=2, tie_breaking_policy="STRICT")
        assert len(p_strict) == 0

    def test_consecutive_three_equal_highs(self, sample_timestamps):
        ts = sample_timestamps[:7]
        # 3 consecutive equal highs at bars 2, 3, 4
        df = pd.DataFrame([
            {"timestamp": ts[0], "open": 25000, "high": 25010, "low": 24990, "close": 25005, "volume": 1000},
            {"timestamp": ts[1], "open": 25005, "high": 25050, "low": 25000, "close": 25045, "volume": 1000},
            {"timestamp": ts[2], "open": 25045, "high": 25100, "low": 25040, "close": 25095, "volume": 1000},  # Bar 2
            {"timestamp": ts[3], "open": 25095, "high": 25100, "low": 25040, "close": 25080, "volume": 1000},  # Bar 3
            {"timestamp": ts[4], "open": 25080, "high": 25100, "low": 25040, "close": 25075, "volume": 1000},  # Bar 4
            {"timestamp": ts[5], "open": 25075, "high": 25050, "low": 25000, "close": 25020, "volume": 1000},
            {"timestamp": ts[6], "open": 25020, "high": 25010, "low": 24990, "close": 25000, "volume": 1000},
        ])

        engine = SwingDetectionEngine()
        # Bar 2 confirmed once right-side drops below plateau with right_bars=3
        p_first = engine.detect_swing_highs(df, left_bars=2, right_bars=3, tie_breaking_policy="FIRST")
        assert len(p_first) == 1
        assert p_first[0].bar_index == 2

        # Bar 4 confirmed under LAST with left_bars=3, right_bars=2
        p_last = engine.detect_swing_highs(df, left_bars=3, right_bars=2, tie_breaking_policy="LAST")
        assert len(p_last) == 1
        assert p_last[0].bar_index == 4

        p_strict = engine.detect_swing_highs(df, left_bars=2, right_bars=2, tie_breaking_policy="STRICT")
        assert len(p_strict) == 0


class TestThresholdConfiguration:

    def test_configuration_parameters_and_defaults(self):
        cfg = LiquidityConfiguration()
        assert cfg.eq_tolerance_pct == 0.0010
        assert cfg.approach_threshold_pct == 0.0020
        assert cfg.rejection_wick_ratio_min == 0.35
        assert cfg.max_lookback_bars == 250
        assert cfg.touch_count_min == 1
        assert cfg.expiry_policy == "MAX_LOOKBACK"

    def test_touch_count_min_filtering(self, sample_candles_with_clear_pivots):
        df = sample_candles_with_clear_pivots
        cfg = LiquidityConfiguration(touch_count_min=2)
        engine = LiquidityIntelligenceEngine(config=cfg)

        pools = engine.detect_liquidity_pools(df)
        # All returned pools must have at least 2 touches
        for p in pools:
            assert p.touch_count >= 2

    def test_uncalibrated_research_disclaimer(self):
        doc = LiquidityConfiguration.__doc__
        assert doc is not None
        assert "uncalibrated empirical research parameters" in doc
        assert "Zero profitability" in doc


class TestIndianSessionIntelligence:

    def test_all_five_session_windows_detected(self, sample_timestamps):
        # Build intraday candles across all session windows
        d = datetime(2026, 11, 4, tzinfo=IST_ZONE)
        times = [
            d.replace(hour=9, minute=20),   # Opening Range (09:15-09:45)
            d.replace(hour=10, minute=15),  # Morning (09:45-11:30)
            d.replace(hour=12, minute=0),   # Midday (11:30-13:30)
            d.replace(hour=14, minute=0),   # Afternoon (13:30-14:45)
            d.replace(hour=15, minute=0),   # Closing (14:45-15:30)
        ]
        candles = []
        for i, t in enumerate(times):
            candles.append({
                "timestamp": t,
                "open": 25000 + i * 10,
                "high": 25050 + i * 10,
                "low": 24980 + i * 10,
                "close": 25040 + i * 10,
                "volume": 5000,
            })
        df = pd.DataFrame(candles)

        engine = LiquidityIntelligenceEngine()
        pools = engine.detect_session_liquidity(df, symbol="NIFTY 50", timeframe="15m")

        pool_types = {p.liquidity_type for p in pools}
        assert LiquidityType.SESSION_HIGH in pool_types
        assert LiquidityType.SESSION_LOW in pool_types
        assert LiquidityType.OPENING_RANGE_HIGH in pool_types
        assert LiquidityType.OPENING_RANGE_LOW in pool_types

        pool_cids = {cid for p in pools for cid in p.source_candle_identifiers}
        assert "OPENING_RANGE" in pool_cids
        assert "MORNING_SESSION" in pool_cids
        assert "MIDDAY_SESSION" in pool_cids
        assert "AFTERNOON_SESSION" in pool_cids
        assert "CLOSING_SESSION" in pool_cids

    def test_holiday_and_weekend_handling_with_market_calendar(self):
        # 2026-01-26 is Republic Day (NSE Holiday)
        holiday_dt = datetime(2026, 1, 26, 10, 0, tzinfo=IST_ZONE)
        assert not MarketCalendar.is_trading_day(holiday_dt)

        df = pd.DataFrame([
            {"timestamp": holiday_dt, "open": 25000, "high": 25050, "low": 24980, "close": 25040, "volume": 1000}
        ])

        engine = LiquidityIntelligenceEngine()
        pools = engine.detect_session_liquidity(df, as_of_time=holiday_dt)

        for p in pools:
            assert p.status == LiquidityLifecycleState.INVALIDATED
            assert any("MarketCalendar lockout" in r for r in p.evidence.rejection_reasons)

    def test_asia_kolkata_timezone_enforcement(self, sample_candles_with_clear_pivots):
        df = sample_candles_with_clear_pivots
        engine = LiquidityIntelligenceEngine()
        pools = engine.detect_liquidity_pools(df)

        for p in pools:
            assert str(p.formation_time.tzinfo) == "Asia/Kolkata"
            assert str(p.available_at.tzinfo) == "Asia/Kolkata"
            assert str(p.updated_at.tzinfo) == "Asia/Kolkata"


class TestDataQualityLockoutMatrix:

    @pytest.mark.parametrize("status", [
        FeedStatus.DATA_OFFLINE,
        FeedStatus.DATA_UNAVAILABLE,
        FeedStatus.STALE,
        FeedStatus.STALE_TICK,
        FeedStatus.DEGRADED,
        FeedStatus.ANOMALOUS,
        FeedStatus.SYNTHETIC,
        "OFFLINE",
        "UNAVAILABLE",
        "MOCK",
        "UNKNOWN_BAD_FEED",
    ])
    def test_all_disqualifying_feed_statuses(self, sample_candles_with_clear_pivots, status):
        df = sample_candles_with_clear_pivots
        engine = LiquidityIntelligenceEngine()
        pools = engine.detect_liquidity_pools(df, data_quality_status=status)

        assert len(pools) > 0
        for p in pools:
            assert p.status == LiquidityLifecycleState.INVALIDATED
            assert any("Data Quality lockout" in r or "Data Quality rejection" in r for r in p.evidence.rejection_reasons)

    def test_repaired_mandatory_candles_lockout(self, sample_candles_with_clear_pivots):
        df = sample_candles_with_clear_pivots.copy()
        df.attrs["ohlc_repaired"] = True

        engine = LiquidityIntelligenceEngine()
        pools = engine.detect_liquidity_pools(df, data_quality_status="VERIFIED_LIVE")

        assert len(pools) > 0
        for p in pools:
            assert p.status == LiquidityLifecycleState.INVALIDATED
            assert any("repaired mandatory candles" in r for r in p.evidence.rejection_reasons)

    def test_missing_mandatory_candles_lockout(self, sample_candles_with_clear_pivots):
        df = sample_candles_with_clear_pivots.copy()
        df.attrs["missing_mandatory_candles"] = True

        engine = LiquidityIntelligenceEngine()
        pools = engine.detect_liquidity_pools(df, data_quality_status="VERIFIED_LIVE")

        assert len(pools) > 0
        for p in pools:
            assert p.status == LiquidityLifecycleState.INVALIDATED
            assert any("missing mandatory candles" in r for r in p.evidence.rejection_reasons)

    def test_invalid_ohlc_geometry_lockout(self, sample_timestamps):
        ts = sample_timestamps[:5]
        # Inverted high/low
        df_bad = pd.DataFrame([
            {"timestamp": ts[0], "open": 25000, "high": 24900, "low": 25100, "close": 25000, "volume": 1000},
            {"timestamp": ts[1], "open": 25000, "high": 24900, "low": 25100, "close": 25000, "volume": 1000},
            {"timestamp": ts[2], "open": 25000, "high": 24900, "low": 25100, "close": 25000, "volume": 1000},
        ])

        engine = LiquidityIntelligenceEngine()
        pools = engine.detect_liquidity_pools(df_bad, data_quality_status="VERIFIED_LIVE")

        for p in pools:
            assert p.status == LiquidityLifecycleState.INVALIDATED
            assert any("invalid ohlc geometry" in r.lower() or "ohlc violation" in r.lower() for r in p.evidence.rejection_reasons)

    def test_verified_live_unrepaired_qualifies(self, sample_candles_with_clear_pivots):
        df = sample_candles_with_clear_pivots
        engine = LiquidityIntelligenceEngine()
        pools = engine.detect_liquidity_pools(df, data_quality_status="VERIFIED_LIVE")

        assert len(pools) > 0
        assert any(p.status == LiquidityLifecycleState.IDENTIFIED for p in pools)


class TestEventSchemaCompliance:

    def test_common_ict_event_contract_fields(self):
        now_dt = datetime.now(IST_ZONE)
        event = ICTEvent(
            event_id="EVT-COMPLIANCE-01",
            index="NIFTY 50",
            event_type=ICTEventType.LIQUIDITY_POOL,
            direction=EventDirection.BEARISH,
            timeframe="15m",
            price_level=25150.0,
            zone_high=25160.0,
            zone_low=25150.0,
            event_status=LiquidityLifecycleState.IDENTIFIED,
            created_at=now_dt,
            event_time=now_dt,
            available_at=now_dt,
            confirmed_at=None,
            invalidated_at=None,
            source_candle_identifiers=["CANDLE-01"],
            data_quality="VERIFIED_LIVE",
            evidence={"touch_count": 2},
            configuration_version="3.1.0",
            engine_version="3.1.0",
        )

        # Check all 17 mandatory contract fields
        fields = [
            "event_id", "index", "event_type", "direction", "timeframe",
            "price_level", "event_status", "event_time", "available_at",
            "created_at", "confirmed_at", "invalidated_at",
            "source_candle_identifiers", "data_quality",
            "evidence", "configuration_version", "engine_version",
        ]
        for f in fields:
            assert hasattr(event, f), f"Missing field: {f}"
            assert getattr(event, f) is not None or f in ("confirmed_at", "invalidated_at")

        # Verify price_level / zone access
        assert event.price_level == 25150.0
        assert event.zone == (25150.0, 25160.0)

    def test_legacy_field_bidirectional_mappings(self):
        now_dt = datetime.now(IST_ZONE)

        # Construct using legacy parameter names: symbol, lifecycle_state, model_version, sweep_details, source_data_quality
        legacy_evt = ICTEvent(
            event_id="EVT-LEGACY-01",
            symbol="BANKNIFTY",
            event_type=ICTEventType.LIQUIDITY_SWEEP,
            direction=EventDirection.BULLISH,
            timeframe="5m",
            zone=(51200.0, 51250.0),
            lifecycle_state=LiquidityLifecycleState.SWEPT,
            created_at=now_dt,
            event_time=now_dt,
            available_at=now_dt,
            source_candle_identifiers=["c50"],
            source_data_quality="VERIFIED_LIVE",
            sweep_details={"penetration_depth_pts": 12.5},
            configuration_version="3.1.0",
            model_version="ict_smc_v3",
        )

        # 1. Verify canonical attributes are populated
        assert legacy_evt.index == "BANKNIFTY"
        assert legacy_evt.event_status == LiquidityLifecycleState.SWEPT
        assert legacy_evt.engine_version == "ict_smc_v3"
        assert legacy_evt.evidence == {"penetration_depth_pts": 12.5}
        assert legacy_evt.data_quality == "VERIFIED_LIVE"
        assert legacy_evt.price_level == 51225.0
        assert legacy_evt.zone == (51200.0, 51250.0)

        # 2. Verify legacy property accessors return identical values
        assert legacy_evt.symbol == "BANKNIFTY"
        assert legacy_evt.lifecycle_state == LiquidityLifecycleState.SWEPT
        assert legacy_evt.model_version == "ict_smc_v3"
        assert legacy_evt.sweep_details == {"penetration_depth_pts": 12.5}
        assert legacy_evt.source_data_quality == "VERIFIED_LIVE"

    def test_legacy_json_serialization_and_deserialization(self):
        now_dt = datetime.now(IST_ZONE)
        event = ICTEvent(
            event_id="EVT-JSON-01",
            index="NIFTY 50",
            event_type=ICTEventType.LIQUIDITY_CONFIRMED,
            direction=EventDirection.BEARISH,
            timeframe="15m",
            price_level=25100.0,
            event_status=LiquidityLifecycleState.CONFIRMED,
            created_at=now_dt,
            event_time=now_dt,
            available_at=now_dt,
            data_quality="VERIFIED_LIVE",
            evidence={"touch_count": 3},
            configuration_version="3.1.0",
            engine_version="3.1.0",
        )

        # Standard serialization
        canonical_json = event.model_dump_json()
        restored = ICTEvent.model_validate_json(canonical_json)
        assert restored.index == "NIFTY 50"
        assert restored.symbol == "NIFTY 50"
        assert restored.event_status == LiquidityLifecycleState.CONFIRMED
        assert restored.lifecycle_state == LiquidityLifecycleState.CONFIRMED
        assert restored.data_quality == "VERIFIED_LIVE"
        assert restored.source_data_quality == "VERIFIED_LIVE"

        # Legacy payload deserialization
        legacy_payload = {
            "event_id": "EVT-JSON-LEGACY",
            "symbol": "FINNIFTY",
            "event_type": "LIQUIDITY_POOL",
            "direction": "BEARISH",
            "timeframe": "15m",
            "price_level": 23500.0,
            "lifecycle_state": "IDENTIFIED",
            "created_at": now_dt.isoformat(),
            "event_time": now_dt.isoformat(),
            "available_at": now_dt.isoformat(),
            "source_data_quality": "VERIFIED_LIVE",
            "sweep_details": {"cluster_size": 2},
            "configuration_version": "3.1.0",
            "model_version": "3.1.0",
        }
        import json
        legacy_json_str = json.dumps(legacy_payload)
        restored_legacy = ICTEvent.model_validate_json(legacy_json_str)
        assert restored_legacy.index == "FINNIFTY"
        assert restored_legacy.symbol == "FINNIFTY"
        assert restored_legacy.event_status == LiquidityLifecycleState.IDENTIFIED
        assert restored_legacy.lifecycle_state == LiquidityLifecycleState.IDENTIFIED
        assert restored_legacy.data_quality == "VERIFIED_LIVE"
        assert restored_legacy.source_data_quality == "VERIFIED_LIVE"
        assert restored_legacy.evidence == {"cluster_size": 2}
        assert restored_legacy.sweep_details == {"cluster_size": 2}
        assert restored_legacy.engine_version == "3.1.0"
        assert restored_legacy.model_version == "3.1.0"

    def test_canonical_and_legacy_conflict_protection(self):
        now_dt = datetime.now(IST_ZONE)
        base_kwargs = {
            "event_id": "EVT-CONFLICT-TEST",
            "event_type": ICTEventType.LIQUIDITY_POOL,
            "direction": EventDirection.BEARISH,
            "timeframe": "15m",
            "price_level": 25000.0,
            "created_at": now_dt,
            "event_time": now_dt,
            "available_at": now_dt,
            "configuration_version": "3.1.0",
        }

        # 1. index vs symbol conflict
        with pytest.raises(ValueError, match="Conflicting fields: canonical 'index' .* and legacy 'symbol' .* contradict"):
            ICTEvent(**base_kwargs, index="NIFTY 50", symbol="BANKNIFTY")

        # 2. event_status vs lifecycle_state conflict
        with pytest.raises(ValueError, match="Conflicting fields: canonical 'event_status' .* and legacy 'lifecycle_state' .* contradict"):
            ICTEvent(
                **base_kwargs,
                index="NIFTY 50",
                event_status=LiquidityLifecycleState.IDENTIFIED,
                lifecycle_state=LiquidityLifecycleState.CONFIRMED,
            )

        # 3. engine_version vs model_version conflict
        with pytest.raises(ValueError, match="Conflicting fields: canonical 'engine_version' .* and legacy 'model_version' .* contradict"):
            ICTEvent(
                **base_kwargs,
                index="NIFTY 50",
                engine_version="3.1.0",
                model_version="2.0.0",
            )

        # 4. evidence vs sweep_details conflict
        with pytest.raises(ValueError, match="Conflicting fields: canonical 'evidence' and legacy 'sweep_details' contradict"):
            ICTEvent(
                **base_kwargs,
                index="NIFTY 50",
                evidence={"touch_count": 2},
                sweep_details={"touch_count": 5},
            )

        # 5. data_quality vs source_data_quality conflict
        with pytest.raises(ValueError, match="Conflicting fields: canonical 'data_quality' .* and legacy 'source_data_quality' .* contradict"):
            ICTEvent(
                **base_kwargs,
                index="NIFTY 50",
                data_quality="VERIFIED_LIVE",
                source_data_quality="SYNTHETIC",
            )

        # 6. Matching canonical and legacy values must SUCCEED cleanly
        evt_matching = ICTEvent(
            **base_kwargs,
            index="NIFTY 50",
            symbol="NIFTY 50",
            event_status=LiquidityLifecycleState.SWEPT,
            lifecycle_state=LiquidityLifecycleState.SWEPT,
            engine_version="3.1.0",
            model_version="3.1.0",
            evidence={"touch_count": 2},
            sweep_details={"touch_count": 2},
            data_quality="VERIFIED_LIVE",
            source_data_quality="VERIFIED_LIVE",
        )
        assert evt_matching.index == "NIFTY 50"
        assert evt_matching.symbol == "NIFTY 50"
        assert evt_matching.event_status == LiquidityLifecycleState.SWEPT
        assert evt_matching.lifecycle_state == LiquidityLifecycleState.SWEPT
        assert evt_matching.engine_version == "3.1.0"
        assert evt_matching.model_version == "3.1.0"
        assert evt_matching.evidence == {"touch_count": 2}
        assert evt_matching.sweep_details == {"touch_count": 2}
        assert evt_matching.data_quality == "VERIFIED_LIVE"
        assert evt_matching.source_data_quality == "VERIFIED_LIVE"

        # 7. Canonical serialization strictly produces the frozen 17-field contract
        dumped = evt_matching.model_dump()
        canonical_fields = {
            "event_id", "index", "event_type", "direction", "timeframe",
            "price_level", "zone_high", "zone_low", "event_status",
            "event_time", "available_at", "created_at", "confirmed_at",
            "invalidated_at", "source_candle_identifiers", "data_quality",
            "evidence", "configuration_version", "engine_version",
        }
        assert set(dumped.keys()).issubset(canonical_fields)
        # Ensure legacy aliases are not emitted in canonical dump
        assert "symbol" not in dumped
        assert "lifecycle_state" not in dumped
        assert "model_version" not in dumped
        assert "sweep_details" not in dumped
        assert "source_data_quality" not in dumped

    def test_swing_pool_liquidity_event_to_ict_event_conversion(self, sample_timestamps):
        ts = sample_timestamps[0]

        # 1. SwingPoint
        sp = SwingPoint(
            event_id="SP-01",
            index="NIFTY 50",
            swing_type="HIGH",
            price=25100.0,
            timeframe="15m",
            bar_index=5,
            candle_id="c5",
            event_time=ts,
            available_at=ts + timedelta(minutes=45),
            left_bars=3,
            right_bars=3,
            volume=50000,
        )
        evt_sp = sp.to_ict_event()
        assert isinstance(evt_sp, ICTEvent)
        assert evt_sp.price_level == 25100.0
        assert evt_sp.event_type == ICTEventType.SWING_HIGH

        # 2. LiquidityPool
        pool = LiquidityPool(
            pool_id="POOL-01",
            index="NIFTY 50",
            liquidity_type=LiquidityType.BSL,
            direction=EventDirection.BEARISH,
            timeframe="15m",
            level=25100.0,
            upper_bound=25110.0,
            lower_bound=25100.0,
            status=LiquidityLifecycleState.IDENTIFIED,
            formation_time=ts,
            available_at=ts,
            updated_at=ts,
        )
        evt_pool = pool.to_ict_event()
        assert isinstance(evt_pool, ICTEvent)
        assert evt_pool.price_level == 25100.0
        assert evt_pool.event_type == ICTEventType.LIQUIDITY_POOL

        # 3. LiquidityEvent
        le = LiquidityEvent(
            event_id="LE-01",
            pool_id="POOL-01",
            index="NIFTY 50",
            event_type=ICTEventType.LIQUIDITY_SWEEP,
            liquidity_type=LiquidityType.BSL,
            timeframe="15m",
            level=25100.0,
            trigger_candle_id="c6",
            penetration_price=25105.0,
            close_price=25095.0,
            penetration_depth_pts=5.0,
            event_time=ts,
            available_at=ts,
            is_wick_sweep=True,
            is_candle_close_breakout=False,
            is_reclaimed=False,
        )
        evt_le = le.to_ict_event()
        assert isinstance(evt_le, ICTEvent)
        assert evt_le.event_type == ICTEventType.LIQUIDITY_SWEEP

    def test_common_event_contract_serialization_roundtrip(self):
        now_dt = datetime.now(IST_ZONE)
        original_evt = ICTEvent(
            event_id="EVT-ROUNDTRIP-01",
            index="NIFTY 50",
            event_type=ICTEventType.LIQUIDITY_CONFIRMED,
            direction=EventDirection.BEARISH,
            timeframe="15m",
            price_level=25100.0,
            zone_high=25110.0,
            zone_low=25100.0,
            event_status=LiquidityLifecycleState.CONFIRMED,
            created_at=now_dt,
            event_time=now_dt,
            available_at=now_dt,
            confirmed_at=now_dt,
            invalidated_at=None,
            source_candle_identifiers=["c10", "c11"],
            data_quality="VERIFIED_LIVE",
            evidence={"touch_count": 2, "rejection_wick_ratio": 0.42},
            configuration_version="3.1.0",
            engine_version="3.1.0",
        )

        json_str = original_evt.model_dump_json()
        assert isinstance(json_str, str)

        restored_evt = ICTEvent.model_validate_json(json_str)
        assert restored_evt.event_id == original_evt.event_id
        assert restored_evt.price_level == original_evt.price_level
        assert restored_evt.event_status == original_evt.event_status
        assert restored_evt.evidence["rejection_wick_ratio"] == 0.42


class TestStep31FinalAcceptanceHardening:

    def test_approaching_to_identified_retreat(self, sample_timestamps):
        ts = sample_timestamps[:4]
        pool = LiquidityPool(
            pool_id="POOL_RETREAT_TEST",
            index="NIFTY 50",
            liquidity_type=LiquidityType.BSL,
            direction=EventDirection.BEARISH,
            timeframe="15m",
            level=25100.0,
            upper_bound=25110.0,
            lower_bound=25100.0,
            status=LiquidityLifecycleState.IDENTIFIED,
            formation_time=ts[0],
            available_at=ts[0],
            updated_at=ts[0],
        )

        # Bar 1: close = 25095 (distance = 5 pts, 0.02% <= 0.20% approach) -> APPROACHING
        # Bar 2: close = 25000 (distance = 100 pts, 0.40% > 0.30% retreat threshold) -> IDENTIFIED
        df = pd.DataFrame([
            {"timestamp": ts[1], "open": 25070, "high": 25098, "low": 25060, "close": 25095, "volume": 1000},
            {"timestamp": ts[2], "open": 25090, "high": 25092, "low": 24990, "close": 25000, "volume": 1000},
        ])

        cfg = LiquidityConfiguration(approach_threshold_pct=0.0020, approach_retreat_mult=1.5)
        engine = LiquidityIntelligenceEngine(config=cfg)

        # After Bar 1: should be APPROACHING
        pools_t1, _ = engine.evaluate_liquidity_lifecycle([pool], df.iloc[:1])
        assert pools_t1[0].status == LiquidityLifecycleState.APPROACHING

        # After Bar 2: price retreated beyond 0.30%, resets to IDENTIFIED
        pools_t2, _ = engine.evaluate_liquidity_lifecycle([pools_t1[0]], df.iloc[1:2])
        assert pools_t2[0].status == LiquidityLifecycleState.IDENTIFIED

    def test_identified_to_swept_direct_fast_market_gap(self, sample_timestamps):
        ts = sample_timestamps[:3]
        pool = LiquidityPool(
            pool_id="POOL_FAST_GAP",
            index="NIFTY 50",
            liquidity_type=LiquidityType.BSL,
            direction=EventDirection.BEARISH,
            timeframe="15m",
            level=25100.0,
            upper_bound=25110.0,
            lower_bound=25100.0,
            status=LiquidityLifecycleState.IDENTIFIED,
            formation_time=ts[0],
            available_at=ts[0],
            updated_at=ts[0],
        )

        # Bar 1: Starts far away at 25000, wicks up to 25105 (penetration 5 pts), but closes at 25090 with small rejection wick (< 0.35)
        # Directly transitions IDENTIFIED -> SWEPT in a single candle
        df = pd.DataFrame([
            {"timestamp": ts[1], "open": 25020, "high": 25105, "low": 25010, "close": 25090, "volume": 10000},
        ])

        engine = LiquidityIntelligenceEngine()
        pools, events = engine.evaluate_liquidity_lifecycle([pool], df)

        assert pools[0].status == LiquidityLifecycleState.SWEPT
        assert len(events) >= 1
        assert events[0].event_type == ICTEventType.LIQUIDITY_SWEEP
        assert events[0].is_wick_sweep is True

    def test_immutable_configuration_governance(self):
        cfg = LiquidityConfiguration()
        # Attempting to mutate a frozen configuration must raise an error
        with pytest.raises(Exception):
            cfg.approach_threshold_pct = 0.05

        with pytest.raises(Exception):
            cfg.max_lookback_bars = 500

    def test_configuration_validators(self):
        # Invalid expiry policy
        with pytest.raises(ValueError, match="Invalid expiry_policy"):
            LiquidityConfiguration(expiry_policy="INVALID_POLICY")

        # Invalid tie breaking policy
        with pytest.raises(ValueError, match="Invalid tie_breaking_policy"):
            LiquidityConfiguration(tie_breaking_policy="INVALID_POLICY")

        # Valid configurations
        cfg_never = LiquidityConfiguration(expiry_policy="NEVER")
        assert cfg_never.expiry_policy == "NEVER"

    def test_expiry_policy_never_persists_indefinitely(self, sample_timestamps):
        t0 = datetime(2026, 11, 4, 9, 15, tzinfo=IST_ZONE)
        pool = LiquidityPool(
            pool_id="POOL_NEVER_EXPIRY",
            index="NIFTY 50",
            liquidity_type=LiquidityType.BSL,
            direction=EventDirection.BEARISH,
            timeframe="15m",
            level=25100.0,
            upper_bound=25110.0,
            lower_bound=25100.0,
            status=LiquidityLifecycleState.IDENTIFIED,
            formation_time=t0,
            available_at=t0,
            updated_at=t0,
        )

        # 300 bars later and on subsequent session days
        t_future = datetime(2026, 11, 10, 14, 0, tzinfo=IST_ZONE)
        df_future = pd.DataFrame([
            {"timestamp": t_future, "open": 24900, "high": 24920, "low": 24890, "close": 24910, "volume": 1000}
        ])

        cfg = LiquidityConfiguration(expiry_policy="NEVER", max_lookback_bars=250)
        engine = LiquidityIntelligenceEngine(config=cfg)

        updated_pools, _ = engine.evaluate_liquidity_lifecycle([pool], df_future)
        # Pool must NEVER expire
        assert updated_pools[0].status == LiquidityLifecycleState.IDENTIFIED

    def test_complete_ohlc_validation_invariants(self, sample_timestamps):
        ts = sample_timestamps[:5]
        engine = LiquidityIntelligenceEngine()

        # 1. Non-positive price
        df_zero_price = pd.DataFrame([
            {"timestamp": ts[0], "open": 0.0, "high": 25100, "low": 24900, "close": 25000, "volume": 1000},
            {"timestamp": ts[1], "open": 25000, "high": 25100, "low": 24900, "close": 25000, "volume": 1000},
            {"timestamp": ts[2], "open": 25000, "high": 25100, "low": 24900, "close": 25000, "volume": 1000},
        ])
        pools = engine.detect_liquidity_pools(df_zero_price)
        assert all(p.status == LiquidityLifecycleState.INVALIDATED for p in pools)

        # 2. Duplicate timestamps
        df_dups = pd.DataFrame([
            {"timestamp": ts[0], "open": 25000, "high": 25100, "low": 24900, "close": 25000, "volume": 1000},
            {"timestamp": ts[0], "open": 25000, "high": 25100, "low": 24900, "close": 25000, "volume": 1000},
            {"timestamp": ts[1], "open": 25000, "high": 25100, "low": 24900, "close": 25000, "volume": 1000},
        ])
        pools_dup = engine.detect_liquidity_pools(df_dups)
        assert all(p.status == LiquidityLifecycleState.INVALIDATED for p in pools_dup)

        # 3. Non-monotonic timestamps
        df_non_mono = pd.DataFrame([
            {"timestamp": ts[2], "open": 25000, "high": 25100, "low": 24900, "close": 25000, "volume": 1000},
            {"timestamp": ts[0], "open": 25000, "high": 25100, "low": 24900, "close": 25000, "volume": 1000},
            {"timestamp": ts[1], "open": 25000, "high": 25100, "low": 24900, "close": 25000, "volume": 1000},
        ])
        pools_mono = engine.detect_liquidity_pools(df_non_mono)
        assert all(p.status == LiquidityLifecycleState.INVALIDATED for p in pools_mono)

        # 4. Infinite price
        df_inf = pd.DataFrame([
            {"timestamp": ts[0], "open": 25000, "high": np.inf, "low": 24900, "close": 25000, "volume": 1000},
            {"timestamp": ts[1], "open": 25000, "high": 25100, "low": 24900, "close": 25000, "volume": 1000},
            {"timestamp": ts[2], "open": 25000, "high": 25100, "low": 24900, "close": 25000, "volume": 1000},
        ])
        pools_inf = engine.detect_liquidity_pools(df_inf)
        assert all(p.status == LiquidityLifecycleState.INVALIDATED for p in pools_inf)

    def test_missing_timestamp_column_fails_closed(self):
        engine = LiquidityIntelligenceEngine()
        df_no_ts = pd.DataFrame([
            {"open": 25000, "high": 25100, "low": 24900, "close": 25050, "volume": 1000},
            {"open": 25050, "high": 25120, "low": 25000, "close": 25080, "volume": 1000},
        ])
        pools = engine.detect_liquidity_pools(df_no_ts)
        # Session pools or detected pools fail closed
        for p in pools:
            assert p.status == LiquidityLifecycleState.INVALIDATED
            assert any("Missing mandatory 'timestamp' column" in r for r in p.evidence.rejection_reasons)

    def test_mixed_timezones_fails_closed(self, sample_timestamps):
        ts = sample_timestamps[:3]
        # ts[0] is IST, ts[1] is converted to UTC, ts[2] is naive
        mixed_ts = [
            ts[0],
            ts[1].astimezone(timezone.utc),
            datetime(2026, 11, 4, 10, 0),  # Naive
        ]
        df_mixed = pd.DataFrame([
            {"timestamp": mixed_ts[0], "open": 25000, "high": 25050, "low": 24980, "close": 25040, "volume": 1000},
            {"timestamp": mixed_ts[1], "open": 25040, "high": 25090, "low": 25030, "close": 25080, "volume": 1000},
            {"timestamp": mixed_ts[2], "open": 25080, "high": 25110, "low": 25050, "close": 25100, "volume": 1000},
        ])
        engine = LiquidityIntelligenceEngine()
        pools = engine.detect_liquidity_pools(df_mixed)
        for p in pools:
            assert p.status == LiquidityLifecycleState.INVALIDATED
            assert any("Mixed timezones detected" in r for r in p.evidence.rejection_reasons)

    def test_data_quality_vs_source_data_quality_resolution(self):
        now_dt = datetime.now(IST_ZONE)

        # 1. Providing data_quality resolves to source_data_quality
        evt1 = ICTEvent(
            event_id="EVT-DQ-01",
            index="NIFTY 50",
            event_type=ICTEventType.LIQUIDITY_POOL,
            direction=EventDirection.BEARISH,
            timeframe="15m",
            price_level=25100.0,
            created_at=now_dt,
            event_time=now_dt,
            available_at=now_dt,
            data_quality="VERIFIED_LIVE",
        )
        assert evt1.source_data_quality == "VERIFIED_LIVE"
        assert evt1.data_quality == "VERIFIED_LIVE"

        # 2. Providing source_data_quality resolves to data_quality
        evt2 = ICTEvent(
            event_id="EVT-DQ-02",
            index="NIFTY 50",
            event_type=ICTEventType.LIQUIDITY_POOL,
            direction=EventDirection.BEARISH,
            timeframe="15m",
            price_level=25100.0,
            created_at=now_dt,
            event_time=now_dt,
            available_at=now_dt,
            source_data_quality="VERIFIED_EOD",
        )
        assert evt2.source_data_quality == "VERIFIED_EOD"
        assert evt2.data_quality == "VERIFIED_EOD"

    def test_max_lookback_boundary_condition(self, sample_timestamps):
        base_ts = sample_timestamps[0]
        pool = LiquidityPool(
            pool_id="POOL_BOUND_TEST",
            index="NIFTY 50",
            liquidity_type=LiquidityType.BSL,
            direction=EventDirection.BEARISH,
            timeframe="15m",
            level=25100.0,
            upper_bound=25110.0,
            lower_bound=25100.0,
            status=LiquidityLifecycleState.IDENTIFIED,
            formation_time=base_ts,
            available_at=base_ts,
            updated_at=base_ts,
        )

        cfg = LiquidityConfiguration(max_lookback_bars=5, expiry_policy="MAX_LOOKBACK")
        engine = LiquidityIntelligenceEngine(config=cfg)

        # 5 bars (exactly at boundary): pool is still active
        df_5 = pd.DataFrame([
            {"timestamp": base_ts + timedelta(minutes=15 * i), "open": 24900, "high": 24910, "low": 24890, "close": 24905, "volume": 1000}
            for i in range(5)
        ])
        pools_5, _ = engine.evaluate_liquidity_lifecycle([pool], df_5)
        assert pools_5[0].status == LiquidityLifecycleState.IDENTIFIED

        # 6 bars (exceeds boundary 6 > 5): transitions to EXPIRED
        df_6 = pd.DataFrame([
            {"timestamp": base_ts + timedelta(minutes=15 * i), "open": 24900, "high": 24910, "low": 24890, "close": 24905, "volume": 1000}
            for i in range(6)
        ])
        pools_6, _ = engine.evaluate_liquidity_lifecycle([pool], df_6)
        assert pools_6[0].status == LiquidityLifecycleState.EXPIRED

    def test_deterministic_replay_across_runs(self, sample_candles_with_clear_pivots):
        df = sample_candles_with_clear_pivots
        cfg = LiquidityConfiguration(configuration_version="3.1.0")

        engine1 = LiquidityIntelligenceEngine(config=cfg)
        engine2 = LiquidityIntelligenceEngine(config=cfg)

        pools1 = engine1.detect_liquidity_pools(df)
        pools2 = engine2.detect_liquidity_pools(df)

        assert len(pools1) == len(pools2)
        for p1, p2 in zip(pools1, pools2):
            assert p1.pool_id == p2.pool_id
            assert p1.level == p2.level
            assert p1.status == p2.status
            assert p1.formation_time == p2.formation_time
            assert p1.available_at == p2.available_at
            assert p1.model_dump_json() == p2.model_dump_json()

        # Replay lifecycle evaluation
        updated1, events1 = engine1.evaluate_liquidity_lifecycle(pools1, df)
        updated2, events2 = engine2.evaluate_liquidity_lifecycle(pools2, df)

        assert len(updated1) == len(updated2)
        assert len(events1) == len(events2)
        for u1, u2 in zip(updated1, updated2):
            assert u1.pool_id == u2.pool_id
            assert u1.status == u2.status
            assert u1.model_dump_json() == u2.model_dump_json()
        for e1, e2 in zip(events1, events2):
            assert e1.event_id == e2.event_id
            assert e1.model_dump_json() == e2.model_dump_json()
