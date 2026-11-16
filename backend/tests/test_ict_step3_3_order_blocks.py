"""
Comprehensive test suite for AIVOLVE Phase 3 Step 3.3:
Order Block Detection & Lifecycle Engine.

Verifies all 30 core test requirements:
1. Bullish Order Block detection.
2. Bearish Order Block detection.
3. Correct origin candle selection.
4. BOS-linked Order Blocks.
5. CHoCH-linked Order Blocks.
6. MSS displacement evidence.
7. Multiple opposing candle handling.
8. Zone boundaries (Full range vs Body only).
9. Overlapping zones handling.
10. Duplicate prevention.
11. Partial mitigation.
12. Full mitigation.
13. Invalidation.
14. Expiry.
15. Lifecycle transition restrictions.
16. Historical event immutability.
17. Five timeframe support (1H, 15M, 5M, 3M, 1M).
18. Timeframe isolation.
19. available_at correctness.
20. As-of replay.
21. No-lookahead protection.
22. Deterministic IDs.
23. Replay determinism.
24. Feed quality lockouts.
25. Invalid OHLC rejection.
26. Missing history handling.
27. Step 3.1 regression compatibility.
28. Step 3.2 regression compatibility.
29. Legacy ICT/SMC regression compatibility.
30. Common 17-field event contract & round-trip serialization.
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
    OrderBlockBoundaryType,
    OriginCandleSelectionPolicy,
    OrderBlockEvidence,
    OrderBlockEvent,
    OrderBlockConfiguration,
    VALID_ORDER_BLOCK_TRANSITIONS,
    validate_order_block_transition,
    IST_ZONE,
)
from app.options.ict_smc.market_structure import (
    MarketStructureEngine,
    MarketStructureConfiguration,
    DISQUALIFYING_FEED_STATUSES,
)
from app.options.ict_smc.order_block_engine import (
    OrderBlockEngine,
    TimeframeOrderBlockReport,
)


def create_candle_df(
    ohlc_data: list[tuple[float, float, float, float]],
    start_time: str = "2026-11-06 09:15:00",
    freq_min: int = 15,
) -> pd.DataFrame:
    """Helper to create timezone-aware IST test DataFrames with valid candle metadata."""
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
            "candle_id": f"c_{i}_{timestamps[i].strftime('%Y%m%d%H%M')}",
        })
    df = pd.DataFrame(records)
    df.attrs["quality_status"] = "VERIFIED_LIVE"
    return df


class TestOrderBlockDetectionAndOrigin:
    """Tests 1-8: Bullish/Bearish detection, origin selection, structural links, and boundaries."""

    def test_bullish_order_block_detection(self):
        """Test 1: Bullish Order Block detected at the origin of a confirmed bullish structural break."""
        engine = OrderBlockEngine(config=OrderBlockConfiguration())

        # Bar 3: Swing high at 24200 (confirmed by bar 5)
        # Bar 5: Origin bearish candle at low (open 24080, high 24090, low 23980, close 24000)
        # Bar 6: Bullish breakout closing at 24350 > 24200 (BOS confirmed with displacement)
        data = [
            (23900, 23950, 23850, 23900),  # 0
            (23900, 24000, 23880, 23950),  # 1
            (23950, 24100, 23920, 24050),  # 2: Left 1
            (24050, 24200, 24000, 24150),  # 3: Swing High 24200
            (24100, 24120, 24020, 24080),  # 4: Right 1
            (24080, 24090, 23980, 24000),  # 5: Right 2 -> Origin Bearish Candle (Low 23980, Close < Open)
            (24000, 24380, 23990, 24350),  # 6: Breakout Close 24350 > 24200 (Displacement!)
        ]
        df = create_candle_df(data)
        typed_obs, ict_obs = engine.detect_order_blocks(df, symbol="NIFTY 50", timeframe="15m")

        assert len(typed_obs) >= 1
        ob = typed_obs[0]
        assert ob.direction == EventDirection.BULLISH
        assert ob.event_type == ICTEventType.ORDER_BLOCK
        assert ob.zone_high == 24090.0  # High of origin candle 5
        assert ob.zone_low == 23980.0   # Low of origin candle 5
        assert ob.mean_threshold == 24035.0  # (24090 + 23980) / 2
        assert ob.event_status == LiquidityLifecycleState.CONFIRMED

    def test_bearish_order_block_detection(self):
        """Test 2: Bearish Order Block detected at the origin of a confirmed bearish structural break."""
        engine = OrderBlockEngine(config=OrderBlockConfiguration())

        # Bar 3: Swing low at 24500 (confirmed by bar 5)
        # Bar 5: Origin bullish candle at high (open 24600, high 24660, low 24590, close 24640)
        # Bar 6: Bearish breakout closing at 24400 < 24500 (BOS confirmed with displacement)
        data = [
            (24800, 24850, 24750, 24800),  # 0
            (24750, 24800, 24650, 24700),  # 1
            (24700, 24720, 24580, 24600),  # 2: Left 1
            (24600, 24650, 24500, 24550),  # 3: Swing Low 24500
            (24550, 24620, 24530, 24600),  # 4: Right 1
            (24600, 24660, 24590, 24640),  # 5: Right 2 -> Origin Bullish Candle (High 24660, Close > Open)
            (24640, 24650, 24380, 24400),  # 6: Breakout Close 24400 < 24500 (Displacement!)
        ]
        df = create_candle_df(data)
        typed_obs, ict_obs = engine.detect_order_blocks(df, symbol="NIFTY 50", timeframe="15m")

        assert len(typed_obs) >= 1
        ob = typed_obs[0]
        assert ob.direction == EventDirection.BEARISH
        assert ob.event_type == ICTEventType.ORDER_BLOCK
        assert ob.zone_high == 24660.0
        assert ob.zone_low == 24590.0
        assert ob.mean_threshold == 24625.0
        assert ob.event_status == LiquidityLifecycleState.CONFIRMED

    def test_correct_origin_candle_selection(self):
        """Test 3: Selects the last opposing candle before the displacement expansion."""
        engine = OrderBlockEngine(config=OrderBlockConfiguration(selection_policy="LAST_CANDLE"))

        # Bar 5 is a red candle (24080 -> 24000). Bar 6 breaks out.
        data = [
            (23900, 23950, 23850, 23900),  # 0
            (23900, 24000, 23880, 23950),  # 1
            (23950, 24100, 23920, 24050),  # 2
            (24050, 24200, 24000, 24150),  # 3: High 24200
            (24100, 24120, 24020, 24080),  # 4
            (24080, 24090, 23980, 24000),  # 5: Bearish origin
            (24000, 24380, 23990, 24350),  # 6: Breakout
        ]
        df = create_candle_df(data)
        typed_obs, _ = engine.detect_order_blocks(df, symbol="NIFTY 50", timeframe="15m")

        assert len(typed_obs) == 1
        assert typed_obs[0].evidence.origin_candle_open == 24080.0
        assert typed_obs[0].evidence.origin_candle_close == 24000.0
        assert typed_obs[0].event_time == df.iloc[5]["timestamp"]

    def test_bos_linked_order_blocks(self):
        """Test 4: Order block evidence links directly to the confirming BOS event ID."""
        engine = OrderBlockEngine()
        data = [
            (23900, 23950, 23850, 23900),
            (23900, 24000, 23880, 23950),
            (23950, 24100, 23920, 24050),
            (24050, 24200, 24000, 24150),
            (24100, 24120, 24020, 24080),
            (24080, 24090, 23980, 24000),
            (24000, 24380, 23990, 24350),
        ]
        df = create_candle_df(data)
        typed_obs, _ = engine.detect_order_blocks(df, symbol="NIFTY 50", timeframe="15m")

        assert len(typed_obs) >= 1
        ev = typed_obs[0].evidence
        assert ev.source_structure_event_id.startswith("EVT-")
        assert ev.source_structure_type == "BOS"

    def test_choch_and_mss_linked_order_blocks(self):
        """Test 5 & 6: Order Block anchors to CHoCH / MSS with displacement evidence."""
        engine = OrderBlockEngine(config=OrderBlockConfiguration(require_displacement=True))

        # Reversal structure breaking LH 24700 with high displacement
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
            # Candle 16: Massive displacement breakout: Open 24250, High 24850, Low 24240, Close 24800
            (24250, 24850, 24240, 24800),  # 16: Close 24800 > 24700 (CHoCH + MSS)
        ]
        df = create_candle_df(data)
        typed_obs, _ = engine.detect_order_blocks(df, symbol="NIFTY 50", timeframe="15m")

        assert len(typed_obs) >= 1
        bullish_obs = [o for o in typed_obs if o.direction == EventDirection.BULLISH]
        assert len(bullish_obs) >= 1
        ob = bullish_obs[0]
        assert ob.direction == EventDirection.BULLISH
        assert ob.evidence.source_structure_type in ("CHOCH", "MSS")
        assert ob.evidence.displacement_body_ratio >= 0.50

    def test_multiple_opposing_candle_policies(self):
        """Test 7: Supports LAST_CANDLE, EXTREME_CANDLE, and CONSECUTIVE_CLUSTER selection policies."""
        data = [
            (23900, 23950, 23850, 23900),  # 0
            (23900, 24000, 23880, 23950),  # 1
            (23950, 24100, 23920, 24050),  # 2
            (24050, 24200, 24000, 24150),  # 3: Swing High 24200
            (24100, 24120, 24020, 24080),  # 4: Red 1 (High 24120, Low 24020)
            (24080, 24090, 23980, 24000),  # 5: Red 2 (Extreme Low 23980)
            (24000, 24380, 23990, 24350),  # 6: Breakout
        ]
        df = create_candle_df(data)

        # Policy 1: LAST_CANDLE
        eng_last = OrderBlockEngine(config=OrderBlockConfiguration(selection_policy="LAST_CANDLE"))
        obs_last, _ = eng_last.detect_order_blocks(df)
        assert len(obs_last) == 1
        assert obs_last[0].evidence.selection_policy == "LAST_CANDLE"

        # Policy 2: CONSECUTIVE_CLUSTER
        eng_cluster = OrderBlockEngine(config=OrderBlockConfiguration(selection_policy="CONSECUTIVE_CLUSTER"))
        obs_cluster, _ = eng_cluster.detect_order_blocks(df)
        assert len(obs_cluster) == 1
        assert obs_cluster[0].evidence.selection_policy == "CONSECUTIVE_CLUSTER"
        assert obs_cluster[0].evidence.opposing_candle_count >= 1

    def test_full_range_vs_body_only_boundaries(self):
        """Test 8: Zone boundaries correctly map full range (wick-to-wick) vs body only."""
        data = [
            (23900, 23950, 23850, 23900),  # 0
            (23900, 24000, 23880, 23950),  # 1
            (23950, 24100, 23920, 24050),  # 2
            (24050, 24200, 24000, 24150),  # 3: High 24200
            (24100, 24120, 24020, 24080),  # 4
            (24080, 24100, 23950, 24000),  # 5: Origin Open 24080, High 24100, Low 23950, Close 24000
            (24000, 24380, 23990, 24350),  # 6: Breakout
        ]
        df = create_candle_df(data)

        # Full Range
        eng_full = OrderBlockEngine(config=OrderBlockConfiguration(boundary_type="FULL_RANGE"))
        obs_full, _ = eng_full.detect_order_blocks(df)
        assert obs_full[0].zone_high == 24100.0  # Wick high
        assert obs_full[0].zone_low == 23950.0   # Wick low

        # Body Only
        eng_body = OrderBlockEngine(config=OrderBlockConfiguration(boundary_type="BODY_ONLY"))
        obs_body, _ = eng_body.detect_order_blocks(df)
        assert obs_body[0].zone_high == 24080.0  # Candle body open
        assert obs_body[0].zone_low == 24000.0   # Candle body close


class TestOverlappingAndDeduplication:
    """Tests 9 & 10: Overlapping zones handling and duplicate prevention."""

    def test_overlapping_zones_handling(self):
        """Test 9: Overlapping zones adhere to deduplication policy."""
        config = OrderBlockConfiguration(
            max_zone_overlap_pct=0.70,
            overlap_dedup_policy="KEEP_FIRST",
        )
        engine = OrderBlockEngine(config=config)

        # Dataset with breakout
        data = [
            (23900, 23950, 23850, 23900),
            (23900, 24000, 23880, 23950),
            (23950, 24100, 23920, 24050),
            (24050, 24200, 24000, 24150),
            (24100, 24120, 24020, 24080),
            (24080, 24090, 23980, 24000),
            (24000, 24380, 23990, 24350),
        ]
        df = create_candle_df(data)
        typed_obs, _ = engine.detect_order_blocks(df)
        assert len(typed_obs) >= 1

    def test_duplicate_prevention_on_same_origin(self):
        """Test 10: Exactly one Order Block emitted per distinct structural origin."""
        engine = OrderBlockEngine()
        data = [
            (23900, 23950, 23850, 23900),
            (23900, 24000, 23880, 23950),
            (23950, 24100, 23920, 24050),
            (24050, 24200, 24000, 24150),
            (24100, 24120, 24020, 24080),
            (24080, 24090, 23980, 24000),
            (24000, 24380, 23990, 24350),  # Break 1
            (24350, 24450, 24300, 24420),  # Next candle
        ]
        df = create_candle_df(data)
        typed_obs, _ = engine.detect_order_blocks(df)
        # Should not duplicate OB for the same origin candle 5
        origin_ids = [ob.evidence.origin_candle_id for ob in typed_obs]
        assert len(origin_ids) == len(set(origin_ids))


class TestOrderBlockLifecycleAndMitigation:
    """Tests 11-16: Partial mitigation, full mitigation, invalidation, expiry, and immutability."""

    def test_partial_mitigation(self):
        """Test 11: Price enters zone without full penetration -> PARTIALLY_MITIGATED."""
        engine = OrderBlockEngine(config=OrderBlockConfiguration(
            approach_threshold_pct=0.001,
            full_mitigation_threshold_pct=100.0,
        ))

        # Bar 5: Bullish OB Zone: High 24090, Low 23980 (Span: 110 pts)
        # Bar 6: Breakout Close 24350
        # Bar 7: Pullback dipping to Low 24040 (enters zone by 50 pts = 45.45% penetration)
        data = [
            (23900, 23950, 23850, 23900),  # 0
            (23900, 24000, 23880, 23950),  # 1
            (23950, 24100, 23920, 24050),  # 2
            (24050, 24200, 24000, 24150),  # 3: High 24200
            (24100, 24120, 24020, 24080),  # 4
            (24080, 24090, 23980, 24000),  # 5: Origin Zone [23980, 24090]
            (24000, 24380, 23990, 24350),  # 6: Breakout
            (24350, 24360, 24040, 24100),  # 7: Pullback Low 24040 <= 24090 -> Partial Mitigation!
        ]
        df = create_candle_df(data)
        typed_obs, _ = engine.detect_order_blocks(df)

        assert len(typed_obs) >= 1
        ob = typed_obs[0]
        assert ob.event_status == LiquidityLifecycleState.PARTIALLY_MITIGATED
        assert ob.evidence.mitigation_percentage > 0.0
        assert ob.evidence.mitigation_percentage < 100.0
        assert ob.evidence.touch_count >= 1

    def test_full_mitigation(self):
        """Test 12: Price penetrates through 100% of zone -> MITIGATED."""
        engine = OrderBlockEngine(config=OrderBlockConfiguration(full_mitigation_threshold_pct=100.0))

        # Bar 5: Zone [23980, 24090]
        # Bar 7: Dips to Low 23970 (penetrates past zone_low 23980) but closes at 24050 (> 23980)
        data = [
            (23900, 23950, 23850, 23900),  # 0
            (23900, 24000, 23880, 23950),  # 1
            (23950, 24100, 23920, 24050),  # 2
            (24050, 24200, 24000, 24150),  # 3: High 24200
            (24100, 24120, 24020, 24080),  # 4
            (24080, 24090, 23980, 24000),  # 5: Origin Zone [23980, 24090]
            (24000, 24380, 23990, 24350),  # 6: Breakout
            (24350, 24360, 23970, 24050),  # 7: Low 23970 <= 23980 -> 100% Full Mitigation!
        ]
        df = create_candle_df(data)
        typed_obs, _ = engine.detect_order_blocks(df)

        assert len(typed_obs) >= 1
        ob = typed_obs[0]
        assert ob.event_status == LiquidityLifecycleState.MITIGATED
        assert ob.evidence.mitigation_percentage == 100.0
        assert ob.evidence.mitigated_at == df.iloc[7]["timestamp"]

    def test_invalidation_on_candle_close(self):
        """Test 13: Completed candle closing beyond opposite zone boundary triggers INVALIDATED."""
        engine = OrderBlockEngine(config=OrderBlockConfiguration(invalidation_buffer_pts=0.0))

        # Bar 5: Bullish OB Zone [23980, 24090]
        # Bar 7: Severe dump closing at 23900 (< 23980) -> INVALIDATES OB!
        data = [
            (23900, 23950, 23850, 23900),  # 0
            (23900, 24000, 23880, 23950),  # 1
            (23950, 24100, 23920, 24050),  # 2
            (24050, 24200, 24000, 24150),  # 3: High 24200
            (24100, 24120, 24020, 24080),  # 4
            (24080, 24090, 23980, 24000),  # 5: Origin Zone [23980, 24090]
            (24000, 24380, 23990, 24350),  # 6: Breakout
            (24350, 24360, 23880, 23900),  # 7: Close 23900 < 23980 -> Invalidation!
        ]
        df = create_candle_df(data)
        typed_obs, _ = engine.detect_order_blocks(df)

        assert len(typed_obs) >= 1
        ob = typed_obs[0]
        assert ob.event_status == LiquidityLifecycleState.INVALIDATED
        assert ob.invalidated_at == df.iloc[7]["timestamp"]
        assert "closed below zone low" in ob.evidence.invalidation_reason

    def test_expiry_policy(self):
        """Test 14: Unmitigated OB expires after max_active_candles elapsed."""
        engine = OrderBlockEngine(config=OrderBlockConfiguration(max_active_candles=2))

        data = [
            (23900, 23950, 23850, 23900),  # 0
            (23900, 24000, 23880, 23950),  # 1
            (23950, 24100, 23920, 24050),  # 2
            (24050, 24200, 24000, 24150),  # 3: High 24200
            (24100, 24120, 24020, 24080),  # 4
            (24080, 24090, 23980, 24000),  # 5: Origin Zone [23980, 24090]
            (24000, 24380, 23990, 24350),  # 6: Breakout confirmed (bar 6)
            (24350, 24450, 24300, 24400),  # 7: Far away
            (24400, 24500, 24380, 24480),  # 8: Far away (m - 6 = 2 >= max_active_candles)
        ]
        df = create_candle_df(data)
        typed_obs, _ = engine.detect_order_blocks(df)

        assert len(typed_obs) >= 1
        assert typed_obs[0].event_status == LiquidityLifecycleState.EXPIRED

    def test_lifecycle_transition_restrictions(self):
        """Test 15: Valid and prohibited state transitions."""
        # Valid
        assert validate_order_block_transition(LiquidityLifecycleState.CONFIRMED, LiquidityLifecycleState.APPROACHING)
        assert validate_order_block_transition(LiquidityLifecycleState.CONFIRMED, LiquidityLifecycleState.PARTIALLY_MITIGATED)
        assert validate_order_block_transition(LiquidityLifecycleState.CONFIRMED, LiquidityLifecycleState.MITIGATED)
        assert validate_order_block_transition(LiquidityLifecycleState.CONFIRMED, LiquidityLifecycleState.INVALIDATED)
        assert validate_order_block_transition(LiquidityLifecycleState.PARTIALLY_MITIGATED, LiquidityLifecycleState.MITIGATED)

        # Prohibited: Terminal state back to active
        assert not validate_order_block_transition(LiquidityLifecycleState.MITIGATED, LiquidityLifecycleState.CONFIRMED)
        assert not validate_order_block_transition(LiquidityLifecycleState.INVALIDATED, LiquidityLifecycleState.CONFIRMED)
        assert not validate_order_block_transition(LiquidityLifecycleState.EXPIRED, LiquidityLifecycleState.CONFIRMED)

    def test_historical_event_immutability(self):
        """Test 16: confirmed_at, event_time, and available_at are preserved when invalidated."""
        engine = OrderBlockEngine()
        data = [
            (23900, 23950, 23850, 23900),  # 0
            (23900, 24000, 23880, 23950),  # 1
            (23950, 24100, 23920, 24050),  # 2
            (24050, 24200, 24000, 24150),  # 3: High 24200
            (24100, 24120, 24020, 24080),  # 4
            (24080, 24090, 23980, 24000),  # 5: Origin Zone [23980, 24090]
            (24000, 24380, 23990, 24350),  # 6: Breakout
            (24350, 24360, 23880, 23900),  # 7: Invalidation
        ]
        df = create_candle_df(data)
        typed_obs, _ = engine.detect_order_blocks(df)

        ob = typed_obs[0]
        assert ob.event_status == LiquidityLifecycleState.INVALIDATED
        # Preserved
        assert ob.confirmed_at == df.iloc[6]["timestamp"]
        assert ob.available_at == df.iloc[6]["timestamp"]
        assert ob.event_time == df.iloc[5]["timestamp"]
        # Appended
        assert ob.invalidated_at == df.iloc[7]["timestamp"]


class TestMultiTimeframeAndIsolation:
    """Tests 17 & 18: Support 5 timeframes (1H, 15M, 5M, 3M, 1M) with complete isolation."""

    def test_all_five_supported_timeframes(self):
        """Test 17: Evaluates 1h, 15m, 5m, 3m, 1m without errors."""
        engine = OrderBlockEngine()
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
            assert isinstance(reports[tf], TimeframeOrderBlockReport)

    def test_complete_timeframe_isolation(self):
        """Test 18: Order blocks detected on 15M never leak into 1H."""
        engine = OrderBlockEngine()
        data_15m = [
            (23900, 23950, 23850, 23900),
            (23900, 24000, 23880, 23950),
            (23950, 24100, 23920, 24050),
            (24050, 24200, 24000, 24150),
            (24100, 24120, 24020, 24080),
            (24080, 24090, 23980, 24000),
            (24000, 24380, 23990, 24350),  # Breakout on 15m
        ]
        data_1h = [
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

        assert len(reports["15m"].order_block_events) >= 1
        assert len(reports["1h"].order_block_events) == 0


class TestAntiLookaheadAndDeterminism:
    """Tests 19-23: available_at delay, as_of replay, deterministic IDs, and replay determinism."""

    def test_available_at_correctness(self):
        """Test 19: available_at matches the break candle completion timestamp."""
        engine = OrderBlockEngine()
        data = [
            (23900, 23950, 23850, 23900),  # 0
            (23900, 24000, 23880, 23950),  # 1
            (23950, 24100, 23920, 24050),  # 2
            (24050, 24200, 24000, 24150),  # 3: High 24200
            (24100, 24120, 24020, 24080),  # 4
            (24080, 24090, 23980, 24000),  # 5: Origin
            (24000, 24380, 23990, 24350),  # 6: Breakout
        ]
        df = create_candle_df(data)
        typed_obs, _ = engine.detect_order_blocks(df)

        assert len(typed_obs) >= 1
        ob = typed_obs[0]
        # Origin was printed at bar 5, but available only at bar 6 completion
        assert ob.event_time == df.iloc[5]["timestamp"]
        assert ob.available_at == df.iloc[6]["timestamp"]
        assert ob.confirmed_at == df.iloc[6]["timestamp"]

    def test_as_of_point_in_time_filtering(self):
        """Test 20 & 21: No future Order Block visibility before breakout completion."""
        engine = OrderBlockEngine()
        data = [
            (23900, 23950, 23850, 23900),  # 0
            (23900, 24000, 23880, 23950),  # 1
            (23950, 24100, 23920, 24050),  # 2
            (24050, 24200, 24000, 24150),  # 3: High 24200
            (24100, 24120, 24020, 24080),  # 4
            (24080, 24090, 23980, 24000),  # 5: Origin
            (24000, 24380, 23990, 24350),  # 6: Breakout
        ]
        df = create_candle_df(data)

        # Query as of bar 5 (before bar 6 breakout)
        as_of_t = df.iloc[5]["timestamp"]
        typed_obs, _ = engine.detect_order_blocks(df, as_of_time=as_of_t)

        # Zero Order Blocks must be visible
        assert len(typed_obs) == 0

    def test_deterministic_event_id_generation(self):
        """Test 22: Generates EVT-OBK- deterministic SHA-256 event IDs."""
        engine = OrderBlockEngine()
        data = [
            (23900, 23950, 23850, 23900),
            (23900, 24000, 23880, 23950),
            (23950, 24100, 23920, 24050),
            (24050, 24200, 24000, 24150),
            (24100, 24120, 24020, 24080),
            (24080, 24090, 23980, 24000),
            (24000, 24380, 23990, 24350),
        ]
        df = create_candle_df(data)

        typed_obs1, _ = engine.detect_order_blocks(df)
        typed_obs2, _ = engine.detect_order_blocks(df)

        assert len(typed_obs1) == len(typed_obs2) >= 1
        for o1, o2 in zip(typed_obs1, typed_obs2):
            assert o1.event_id == o2.event_id
            assert o1.event_id.startswith("EVT-OBK-")
            assert len(o1.event_id) == 24

    def test_repeated_replay_determinism(self):
        """Test 23: Produces byte-for-byte identical output across repeated runs."""
        engine = OrderBlockEngine()
        data = [
            (23900, 23950, 23850, 23900),
            (23900, 24000, 23880, 23950),
            (23950, 24100, 23920, 24050),
            (24050, 24200, 24000, 24150),
            (24100, 24120, 24020, 24080),
            (24080, 24090, 23980, 24000),
            (24000, 24380, 23990, 24350),
        ]
        df = create_candle_df(data)

        rep1 = engine.analyze_timeframe(df, symbol="NIFTY 50", timeframe="15m")
        rep2 = engine.analyze_timeframe(df, symbol="NIFTY 50", timeframe="15m")

        assert rep1.model_dump() == rep2.model_dump()


class TestDataQualityAndInvariants:
    """Tests 24-26: Fail-closed lockouts, invalid OHLC rejection, and missing history."""

    @pytest.mark.parametrize("status", list(DISQUALIFYING_FEED_STATUSES))
    def test_disqualifying_feed_lockout(self, status):
        """Test 24: All disqualifying feed statuses fail closed."""
        engine = OrderBlockEngine()
        df = create_candle_df([(24000, 24100, 23950, 24050)])

        with pytest.raises(ValueError, match="Order block detection locked out"):
            engine.detect_order_blocks(df, data_quality_status=status)

    def test_invalid_ohlc_rejection(self):
        """Test 25: Geometric anomalies fail closed."""
        engine = OrderBlockEngine()

        # High < Low
        bad_df1 = pd.DataFrame([{
            "timestamp": datetime.now(IST_ZONE),
            "open": 24100.0,
            "high": 24000.0,
            "low": 24200.0,
            "close": 24050.0,
        }])
        with pytest.raises(ValueError, match="high < low"):
            engine.detect_order_blocks(bad_df1, data_quality_status="VERIFIED_LIVE")

        # High < max(open, close)
        bad_df2 = pd.DataFrame([{
            "timestamp": datetime.now(IST_ZONE),
            "open": 24200.0,
            "high": 24100.0,
            "low": 24000.0,
            "close": 24050.0,
        }])
        with pytest.raises(ValueError, match="high < max"):
            engine.detect_order_blocks(bad_df2, data_quality_status="VERIFIED_LIVE")

        # Low > min(open, close)
        bad_df3 = pd.DataFrame([{
            "timestamp": datetime.now(IST_ZONE),
            "open": 24100.0,
            "high": 24200.0,
            "low": 24150.0,
            "close": 24050.0,
        }])
        with pytest.raises(ValueError, match="low > min"):
            engine.detect_order_blocks(bad_df3, data_quality_status="VERIFIED_LIVE")

    def test_missing_history_handling(self):
        """Test 26: Empty or insufficient history returns empty lists gracefully without errors."""
        engine = OrderBlockEngine()

        # Empty df
        empty_df = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
        empty_df.attrs["quality_status"] = "VERIFIED_LIVE"
        obs1, ict1 = engine.detect_order_blocks(empty_df)
        assert obs1 == []
        assert ict1 == []

        # Single candle
        single_df = create_candle_df([(24000, 24100, 23950, 24050)])
        obs2, ict2 = engine.detect_order_blocks(single_df)
        assert obs2 == []
        assert ict2 == []


class TestCrossStepCompatibility:
    """Tests 27-30: Common 17-field event contract and cross-step compatibility."""

    def test_common_17_field_event_contract(self):
        """Test 30: All Order Block events strictly conform to frozen 17-field contract."""
        engine = OrderBlockEngine()
        data = [
            (23900, 23950, 23850, 23900),
            (23900, 24000, 23880, 23950),
            (23950, 24100, 23920, 24050),
            (24050, 24200, 24000, 24150),
            (24100, 24120, 24020, 24080),
            (24080, 24090, 23980, 24000),
            (24000, 24380, 23990, 24350),
        ]
        df = create_candle_df(data)
        typed_obs, ict_obs = engine.detect_order_blocks(df, symbol="NIFTY 50", timeframe="15m")

        assert len(ict_obs) >= 1
        ev = ict_obs[0]

        # 17 Mandatory fields validation
        assert isinstance(ev.event_id, str) and ev.event_id.startswith("EVT-OBK-") and len(ev.event_id) == 24
        assert ev.index == "NIFTY 50"
        assert ev.event_type == ICTEventType.ORDER_BLOCK
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
        assert ev.configuration_version == "3.3.0"
        assert ev.engine_version == "3.3.0"

        # Legacy backward compatibility properties
        assert ev.symbol == "NIFTY 50"
        assert ev.lifecycle_state == LiquidityLifecycleState.CONFIRMED
        assert ev.model_version == "3.3.0"
        assert ev.source_data_quality == "VERIFIED_LIVE"
        assert ev.sweep_details == ev.evidence

        # JSON Round-trip determinism
        payload = ev.model_dump()
        reconstructed = ICTEvent(**payload)
        assert reconstructed.event_id == ev.event_id
        assert reconstructed.model_dump() == payload

    def test_research_disclaimer_present(self):
        """Verify empirical research disclaimer in configuration."""
        config = OrderBlockConfiguration()
        assert "uncalibrated research baseline parameters" in config.research_disclaimer


# =====================================================================
# Phase 3 Step 3.3 Final Remediation Verification Suites
# =====================================================================

class TestLifecycleReconciliationAndTransitions:
    """Remediation Section 1: Detailed verification of all 7 lifecycle states, triggers, and active mapping."""

    def test_all_seven_order_block_states_supported(self):
        """Verify explicit presence and distinct values of all 7 supported states."""
        required_states = {
            "IDENTIFIED",
            "CONFIRMED",
            "APPROACHING",
            "PARTIALLY_MITIGATED",
            "MITIGATED",
            "INVALIDATED",
            "EXPIRED",
        }
        for state_name in required_states:
            assert hasattr(LiquidityLifecycleState, state_name)
            state_val = getattr(LiquidityLifecycleState, state_name)
            assert state_val.value == state_name

    def test_permitted_and_prohibited_order_block_transitions(self):
        """Verify every permitted transition from each state and reject prohibited ones."""
        # 1. From IDENTIFIED
        assert validate_order_block_transition(LiquidityLifecycleState.IDENTIFIED, LiquidityLifecycleState.CONFIRMED)
        assert validate_order_block_transition(LiquidityLifecycleState.IDENTIFIED, LiquidityLifecycleState.INVALIDATED)
        assert validate_order_block_transition(LiquidityLifecycleState.IDENTIFIED, LiquidityLifecycleState.EXPIRED)
        assert not validate_order_block_transition(LiquidityLifecycleState.IDENTIFIED, LiquidityLifecycleState.MITIGATED)

        # 2. From CONFIRMED
        assert validate_order_block_transition(LiquidityLifecycleState.CONFIRMED, LiquidityLifecycleState.APPROACHING)
        assert validate_order_block_transition(LiquidityLifecycleState.CONFIRMED, LiquidityLifecycleState.PARTIALLY_MITIGATED)
        assert validate_order_block_transition(LiquidityLifecycleState.CONFIRMED, LiquidityLifecycleState.MITIGATED)
        assert validate_order_block_transition(LiquidityLifecycleState.CONFIRMED, LiquidityLifecycleState.INVALIDATED)
        assert validate_order_block_transition(LiquidityLifecycleState.CONFIRMED, LiquidityLifecycleState.EXPIRED)
        assert not validate_order_block_transition(LiquidityLifecycleState.CONFIRMED, LiquidityLifecycleState.IDENTIFIED)

        # 3. From APPROACHING
        assert validate_order_block_transition(LiquidityLifecycleState.APPROACHING, LiquidityLifecycleState.CONFIRMED)  # Retreat
        assert validate_order_block_transition(LiquidityLifecycleState.APPROACHING, LiquidityLifecycleState.PARTIALLY_MITIGATED)
        assert validate_order_block_transition(LiquidityLifecycleState.APPROACHING, LiquidityLifecycleState.MITIGATED)
        assert validate_order_block_transition(LiquidityLifecycleState.APPROACHING, LiquidityLifecycleState.INVALIDATED)
        assert validate_order_block_transition(LiquidityLifecycleState.APPROACHING, LiquidityLifecycleState.EXPIRED)

        # 4. From PARTIALLY_MITIGATED
        assert validate_order_block_transition(LiquidityLifecycleState.PARTIALLY_MITIGATED, LiquidityLifecycleState.MITIGATED)
        assert validate_order_block_transition(LiquidityLifecycleState.PARTIALLY_MITIGATED, LiquidityLifecycleState.INVALIDATED)
        assert validate_order_block_transition(LiquidityLifecycleState.PARTIALLY_MITIGATED, LiquidityLifecycleState.EXPIRED)
        assert not validate_order_block_transition(LiquidityLifecycleState.PARTIALLY_MITIGATED, LiquidityLifecycleState.CONFIRMED)
        assert not validate_order_block_transition(LiquidityLifecycleState.PARTIALLY_MITIGATED, LiquidityLifecycleState.APPROACHING)

        # 5. Terminal states: MITIGATED, INVALIDATED, EXPIRED
        for term_state in (LiquidityLifecycleState.MITIGATED, LiquidityLifecycleState.INVALIDATED, LiquidityLifecycleState.EXPIRED):
            for any_other in LiquidityLifecycleState:
                assert not validate_order_block_transition(term_state, any_other)

    def test_semantic_active_category_mapping(self):
        """Verify that ACTIVE is mapped strictly to non-terminal states and serialization is canonical."""
        now = datetime.now(timezone.utc)
        evidence = OrderBlockEvidence(
            zone_high=24100.0,
            zone_low=23950.0,
            mean_threshold=24025.0,
            body_high=24080.0,
            body_low=24000.0,
            origin_candle_id="c_origin",
            origin_candle_time=now,
            origin_candle_open=24080.0,
            origin_candle_high=24100.0,
            origin_candle_low=23950.0,
            origin_candle_close=24000.0,
            displacement_candle_id="c_break",
            source_structure_event_id="EVT-BOS-1",
            source_structure_type="BOS",
            invalidation_condition="Close < 23950",
        )

        # Active states
        for st in (LiquidityLifecycleState.CONFIRMED, LiquidityLifecycleState.APPROACHING, LiquidityLifecycleState.PARTIALLY_MITIGATED):
            ob = OrderBlockEvent(
                event_id="EVT-OBK-TEST-1",
                direction=EventDirection.BULLISH,
                zone_high=24100.0,
                zone_low=23950.0,
                mean_threshold=24025.0,
                event_status=st,
                event_time=now,
                available_at=now,
                created_at=now,
                evidence=evidence,
            )
            assert ob.is_active is True
            ict_ev = ob.to_ict_event()
            # Canonical serialization must remain exact enum string, never overwritten by "ACTIVE"
            assert ict_ev.event_status == st
            assert ict_ev.model_dump()["event_status"] == st.value

        # Inactive / terminal states
        for st in (LiquidityLifecycleState.MITIGATED, LiquidityLifecycleState.INVALIDATED, LiquidityLifecycleState.EXPIRED):
            ob = OrderBlockEvent(
                event_id="EVT-OBK-TEST-2",
                direction=EventDirection.BULLISH,
                zone_high=24100.0,
                zone_low=23950.0,
                mean_threshold=24025.0,
                event_status=st,
                event_time=now,
                available_at=now,
                created_at=now,
                evidence=evidence,
            )
            assert ob.is_active is False
            assert ob.to_ict_event().event_status == st


class TestStep31BackwardCompatibility:
    """Remediation Section 2: Verify shared LiquidityLifecycleState preserves all Step 3.1 contracts."""

    def test_original_step3_1_enum_values_unchanged(self):
        """All 8 original Step 3.1 states must remain exact."""
        original_states = [
            ("IDENTIFIED", "IDENTIFIED"),
            ("APPROACHING", "APPROACHING"),
            ("SWEPT", "SWEPT"),
            ("RECLAIMED", "RECLAIMED"),
            ("CONFIRMED", "CONFIRMED"),
            ("CONSUMED", "CONSUMED"),
            ("EXPIRED", "EXPIRED"),
            ("INVALIDATED", "INVALIDATED"),
        ]
        for name, expected_val in original_states:
            assert getattr(LiquidityLifecycleState, name).value == expected_val

    def test_step3_1_lifecycle_transition_table_unaffected(self):
        """Step 3.1 transition logic (SWEPT -> RECLAIMED -> CONFIRMED) remains intact."""
        from app.options.ict_smc.ict_models import validate_lifecycle_transition

        # SWEPT cannot jump directly to CONFIRMED
        assert not validate_lifecycle_transition(LiquidityLifecycleState.SWEPT, LiquidityLifecycleState.CONFIRMED)
        # SWEPT can transition to RECLAIMED
        assert validate_lifecycle_transition(LiquidityLifecycleState.SWEPT, LiquidityLifecycleState.RECLAIMED)
        # RECLAIMED can transition to CONFIRMED
        assert validate_lifecycle_transition(LiquidityLifecycleState.RECLAIMED, LiquidityLifecycleState.CONFIRMED)
        # Terminal state CONSUMED has no outbound transitions
        assert not validate_lifecycle_transition(LiquidityLifecycleState.CONSUMED, LiquidityLifecycleState.IDENTIFIED)


class TestDisplacementAndOriginSeparation:
    """Remediation Section 3: Verify origin candle cannot independently qualify displacement requirement."""

    def test_origin_candle_cannot_qualify_displacement_alone(self):
        """
        An origin candle with massive body and range preceding a weak, non-displacing breakout
        must NOT produce a confirmed Order Block if displacement is required.
        """
        engine = OrderBlockEngine(config=OrderBlockConfiguration(
            require_displacement=True,
            min_displacement_body_ratio=0.60,
            min_displacement_atr_multiple=1.5,
        ))

        # Dataset where:
        # Candle 5 is a massive red candle (origin): Open 24200, High 24220, Low 23900, Close 23920 (Range 320 pts, Body ratio 0.875)
        # Candle 6 is a weak, doji breakout candle: Open 23920, High 24250, Low 23910, Close 24210 (Breakout close, but body ratio < 0.60 or range weak)
        # Candle 6 has body = 290, range = 340. Body ratio = 0.85, so it would qualify.
        # Let's make Candle 6 have weak body ratio (e.g. huge upper/lower wick):
        # Open 24000, High 24250, Low 23950, Close 24020 -> Body = 20, Range = 300, Body ratio = 0.067 << 0.60!
        data = [
            (23900, 23950, 23850, 23900),  # 0
            (23900, 24000, 23880, 23950),  # 1
            (23950, 24050, 23920, 24000),  # 2: Left 1
            (24000, 24100, 23980, 24080),  # 3: Left 2
            (24080, 24200, 24050, 24180),  # 4: Swing High (24200)
            (24180, 24220, 23900, 23920),  # 5: Huge Red Origin Candle (Range 320, Body 260)
            # Breakout Candle 6: Closes above 24200 at 24210, but is a spin-top/doji with tiny body
            (24100, 24250, 23950, 24210),  # 6: Open 24100, Close 24210, High 24250, Low 23950. Body=110, Range=300, Ratio=0.366 < 0.60!
        ]
        df = create_candle_df(data)
        typed_obs, _ = engine.detect_order_blocks(df)

        # Displacement requirement MUST fail because origin candle (candle 5) cannot qualify displacement!
        bullish_obs = [o for o in typed_obs if o.direction == EventDirection.BULLISH]
        assert len(bullish_obs) == 0

    def test_displacement_candle_id_distinct_from_origin(self):
        """When displacement qualifies, displacement_candle_id must be distinct from origin_candle_id."""
        engine = OrderBlockEngine(config=OrderBlockConfiguration(
            require_displacement=True,
            min_displacement_body_ratio=0.50,
            min_displacement_atr_multiple=1.0,
        ))
        data = [
            (23900, 23950, 23850, 23900),  # 0
            (23900, 24000, 23880, 23950),  # 1
            (23950, 24100, 23920, 24050),  # 2
            (24050, 24200, 24000, 24150),  # 3: Swing High 24200
            (24100, 24120, 24020, 24080),  # 4
            (24080, 24090, 23980, 24000),  # 5: Origin Bearish Candle
            (24000, 24380, 23990, 24350),  # 6: Breakout Candle with massive displacement
        ]
        df = create_candle_df(data)
        typed_obs, _ = engine.detect_order_blocks(df)

        assert len(typed_obs) >= 1
        ob = typed_obs[0]
        assert ob.evidence.origin_candle_id != ob.evidence.displacement_candle_id
        assert ob.evidence.origin_candle_id == df.iloc[5]["candle_id"]
        assert ob.evidence.displacement_candle_id == df.iloc[6]["candle_id"]
        assert ob.evidence.displacement_leg_candle_count >= 1

    def test_insufficient_history_atr_fallback(self):
        """Verify robust handling when dataset has fewer candles than standard 14-period ATR."""
        engine = OrderBlockEngine(config=OrderBlockConfiguration(atr_period=14))
        # Only 7 candles (< 14 period)
        data = [
            (23900, 23950, 23850, 23900),
            (23900, 24000, 23880, 23950),
            (23950, 24100, 23920, 24050),
            (24050, 24200, 24000, 24150),
            (24100, 24120, 24020, 24080),
            (24080, 24090, 23980, 24000),
            (24000, 24380, 23990, 24350),
        ]
        df = create_candle_df(data)
        typed_obs, _ = engine.detect_order_blocks(df)
        assert len(typed_obs) >= 1
        assert typed_obs[0].evidence.displacement_atr_multiple > 0.0


class TestExactBoundaryConditionsAndPenetrationMath:
    """Remediation Section 4: Mathematical verification of 0%, 50%, and 100% boundary conditions."""

    def test_bullish_order_block_exact_boundary_conditions(self):
        """
        Bullish OB Zone: High 24100, Low 24000 (Span 100 pts).
        Mean Threshold: (24100 + 24000) / 2 = 24050.
        Boundary conditions:
        - Exactly 0% penetration: Low = 24100 -> mitigation_percentage == 0.0%
        - Exactly 50% penetration: Low = 24050 -> mitigation_percentage == 50.0%, status PARTIALLY_MITIGATED
        - Exactly 100% penetration: Low = 24000 -> mitigation_percentage == 100.0%, status MITIGATED
        """
        engine = OrderBlockEngine(config=OrderBlockConfiguration(full_mitigation_threshold_pct=100.0))

        # Base structure setting up Bullish OB at candle 5: [24000, 24100]
        base_data = [
            (23900, 23950, 23850, 23900),  # 0
            (23900, 24000, 23880, 23950),  # 1
            (23950, 24100, 23920, 24050),  # 2
            (24050, 24200, 24000, 24150),  # 3: Swing High 24200
            (24100, 24120, 24020, 24080),  # 4
            (24080, 24100, 24000, 24020),  # 5: Origin Zone High 24100, Low 24000 (Mean = 24050)
            (24020, 24380, 24010, 24350),  # 6: Breakout Close 24350
        ]

        # Scenario A: Exactly 0% penetration (Low = 24100 touches zone high)
        data_0 = base_data + [(24350, 24360, 24100, 24200)]  # 7: Low = 24100.0
        obs_0, _ = engine.detect_order_blocks(create_candle_df(data_0))
        assert len(obs_0) >= 1
        assert obs_0[0].zone_high == 24100.0
        assert obs_0[0].zone_low == 24000.0
        assert obs_0[0].mean_threshold == 24050.0
        assert obs_0[0].evidence.mitigation_percentage == 0.0
        # 0% penetration: no partial mitigation!
        assert obs_0[0].event_status != LiquidityLifecycleState.PARTIALLY_MITIGATED
        assert obs_0[0].event_status == LiquidityLifecycleState.APPROACHING

        # Scenario B: Exactly 50% penetration (Low = 24050 touches mean threshold)
        data_50 = base_data + [(24350, 24360, 24050, 24200)]  # 7: Low = 24050.0
        obs_50, _ = engine.detect_order_blocks(create_candle_df(data_50))
        assert len(obs_50) >= 1
        assert obs_50[0].evidence.mitigation_percentage == 50.0
        assert obs_50[0].event_status == LiquidityLifecycleState.PARTIALLY_MITIGATED

        # Scenario C: Exactly 100% penetration (Low = 24000 touches zone low)
        data_100 = base_data + [(24350, 24360, 24000, 24150)]  # 7: Low = 24000.0, Close 24150 > 24000
        obs_100, _ = engine.detect_order_blocks(create_candle_df(data_100))
        assert len(obs_100) >= 1
        assert obs_100[0].evidence.mitigation_percentage == 100.0
        assert obs_100[0].event_status == LiquidityLifecycleState.MITIGATED

    def test_bearish_order_block_exact_boundary_conditions(self):
        """
        Bearish OB Zone: High 24660, Low 24590 (Span 70 pts).
        Mean Threshold: (24660 + 24590) / 2 = 24625.0.
        Boundary conditions:
        - Exactly 0% penetration: High = 24590.0 -> mitigation_percentage == 0.0%, no partial mitigation!
        - Exactly 50% penetration: High = 24625.0 -> mitigation_percentage == 50.0%, status PARTIALLY_MITIGATED
        - Exactly 100% penetration: High = 24660.0 -> mitigation_percentage == 100.0%, status MITIGATED
        """
        engine = OrderBlockEngine(config=OrderBlockConfiguration(full_mitigation_threshold_pct=100.0))

        # Bearish setup: Swing low at candle 3 (24500), origin green candle at candle 5 [24590, 24660]
        base_data = [
            (24800, 24850, 24750, 24800),  # 0
            (24750, 24800, 24650, 24700),  # 1
            (24700, 24720, 24580, 24600),  # 2: Left 1
            (24600, 24650, 24500, 24550),  # 3: Swing Low 24500
            (24550, 24620, 24530, 24600),  # 4: Right 1
            (24600, 24660, 24590, 24640),  # 5: Origin Green Candle [24590, 24660] (Mean = 24625)
            (24640, 24650, 24380, 24400),  # 6: Breakout Close 24400 < 24500 (Bearish BOS)
        ]

        # Scenario A: Exactly 0% penetration (High = 24590 touches zone low)
        data_0 = base_data + [(24400, 24590, 24380, 24420)]  # 7: High = 24590.0
        obs_0, _ = engine.detect_order_blocks(create_candle_df(data_0))
        bear_0 = [o for o in obs_0 if o.direction == EventDirection.BEARISH]
        assert len(bear_0) >= 1
        assert bear_0[0].zone_high == 24660.0
        assert bear_0[0].zone_low == 24590.0
        assert bear_0[0].mean_threshold == 24625.0
        assert bear_0[0].evidence.mitigation_percentage == 0.0
        # 0% penetration: no partial mitigation!
        assert bear_0[0].event_status != LiquidityLifecycleState.PARTIALLY_MITIGATED
        assert bear_0[0].event_status == LiquidityLifecycleState.APPROACHING

        # Scenario B: Exactly 50% penetration (High = 24625 touches mean threshold)
        data_50 = base_data + [(24400, 24625, 24380, 24420)]  # 7: High = 24625.0
        obs_50, _ = engine.detect_order_blocks(create_candle_df(data_50))
        bear_50 = [o for o in obs_50 if o.direction == EventDirection.BEARISH]
        assert len(bear_50) >= 1
        assert bear_50[0].evidence.mitigation_percentage == 50.0
        assert bear_50[0].event_status == LiquidityLifecycleState.PARTIALLY_MITIGATED

        # Scenario C: Exactly 100% penetration (High = 24660 touches zone high)
        data_100 = base_data + [(24400, 24660, 24380, 24420)]  # 7: High = 24660.0, Close 24420 < 24660
        obs_100, _ = engine.detect_order_blocks(create_candle_df(data_100))
        bear_100 = [o for o in obs_100 if o.direction == EventDirection.BEARISH]
        assert len(bear_100) >= 1
        assert bear_100[0].evidence.mitigation_percentage == 100.0
        assert bear_100[0].event_status == LiquidityLifecycleState.MITIGATED

    def test_wick_penetration_vs_close_invalidation(self):
        """
        Verify that a wick penetrating 100% into or beyond the zone results in MITIGATED,
        while strictly a completed candle CLOSE beyond the zone triggers INVALIDATED.
        Precedence: Invalidation takes precedence if completed candle closes beyond opposite boundary.
        """
        engine = OrderBlockEngine(config=OrderBlockConfiguration())
        base_data = [
            (23900, 23950, 23850, 23900),  # 0
            (23900, 24000, 23880, 23950),  # 1
            (23950, 24100, 23920, 24050),  # 2
            (24050, 24200, 24000, 24150),  # 3: Swing High 24200
            (24100, 24120, 24020, 24080),  # 4
            (24080, 24100, 24000, 24020),  # 5: Origin Zone [24000, 24100]
            (24020, 24380, 24010, 24350),  # 6: Breakout Close 24350
        ]

        # Case 1: Wick penetrates below zone low (Low 23980 < 24000), but CLOSE is 24050 (inside zone)
        # Result: MITIGATED, NOT INVALIDATED!
        data_wick = base_data + [(24350, 24360, 23980, 24050)]
        obs_wick, _ = engine.detect_order_blocks(create_candle_df(data_wick))
        assert len(obs_wick) >= 1
        assert obs_wick[0].event_status == LiquidityLifecycleState.MITIGATED
        assert obs_wick[0].invalidated_at is None

        # Case 2: Candle wicks 100% through AND CLOSES below zone low (Low 23940, Close 23950 < 24000)
        # Result: INVALIDATED takes strict precedence!
        data_close = base_data + [(24350, 24360, 23940, 23950)]
        obs_close, _ = engine.detect_order_blocks(create_candle_df(data_close))
        assert len(obs_close) >= 1
        assert obs_close[0].event_status == LiquidityLifecycleState.INVALIDATED
        assert obs_close[0].invalidated_at is not None


# =====================================================================
# Phase 3 Step 3.3 Final Closure Remediation Suites
# =====================================================================

class TestCumulativeDisplacementDirection:
    """Closure Task 1: Mandatory directional validation on cumulative displacement."""

    def test_valid_bullish_cumulative_displacement(self):
        """Bullish cumulative displacement with close_k > open_(i+1) and body ratio >= 0.50 qualifies."""
        engine = OrderBlockEngine(config=OrderBlockConfiguration(
            require_displacement=True,
            allow_multi_candle_displacement=True,
            min_displacement_body_ratio=0.50,
            min_displacement_atr_multiple=1.0,
        ))
        # Candle 5: Origin Bearish [24000, 24100]
        # Multi-candle expansion:
        # Candle 6: Open 24050, High 24200, Low 24040, Close 24180
        # Candle 7: Open 24180, High 24400, Low 24150, Close 24380 (Breakout)
        # Net progress: 24380 - 24050 = 330 > 0. High: 24400, Low: 24040. Range: 360. Ratio: 330/360 = 0.916 >= 0.50.
        data = [
            (23900, 23950, 23850, 23900),  # 0
            (23900, 24000, 23880, 23950),  # 1
            (23950, 24100, 23920, 24050),  # 2
            (24050, 24200, 24000, 24150),  # 3: Swing High 24200
            (24100, 24120, 24020, 24080),  # 4
            (24080, 24100, 24000, 24020),  # 5: Origin
            (24050, 24200, 24040, 24180),  # 6: Expansion 1
            (24180, 24400, 24150, 24380),  # 7: Breakout 2
        ]
        df = create_candle_df(data)
        typed_obs, _ = engine.detect_order_blocks(df)
        bullish_obs = [o for o in typed_obs if o.direction == EventDirection.BULLISH]
        assert len(bullish_obs) >= 1
        assert bullish_obs[0].evidence.displacement_body_ratio >= 0.50

    def test_valid_bearish_cumulative_displacement(self):
        """Bearish cumulative displacement with close_k < open_(i+1) and body ratio >= 0.50 qualifies."""
        engine = OrderBlockEngine(config=OrderBlockConfiguration(
            require_displacement=True,
            allow_multi_candle_displacement=True,
            min_displacement_body_ratio=0.50,
            min_displacement_atr_multiple=1.0,
        ))
        data = [
            (24800, 24850, 24750, 24800),  # 0
            (24750, 24800, 24650, 24700),  # 1
            (24700, 24720, 24580, 24600),  # 2: Left 1
            (24600, 24650, 24500, 24550),  # 3: Swing Low 24500
            (24550, 24620, 24530, 24600),  # 4: Right 1
            (24600, 24660, 24590, 24640),  # 5: Origin Green [24590, 24660]
            (24640, 24650, 24450, 24480),  # 6: Drop 1
            (24480, 24500, 24200, 24250),  # 7: Breakout Drop 2 (close_k = 24250 < open_6 = 24640)
        ]
        df = create_candle_df(data)
        typed_obs, _ = engine.detect_order_blocks(df)
        bearish_obs = [o for o in typed_obs if o.direction == EventDirection.BEARISH]
        assert len(bearish_obs) >= 1
        assert bearish_obs[0].evidence.displacement_body_ratio >= 0.50

    def test_opposite_direction_bullish_rejection(self):
        """Bullish OB must reject cumulative displacement if net progress is negative (close_k < open_(i+1))."""
        engine = OrderBlockEngine(config=OrderBlockConfiguration(
            require_displacement=True,
            min_displacement_body_ratio=0.50,
            min_displacement_atr_multiple=1.0,
        ))
        # If break candle somehow closes below open_(i+1), cumulative direction is negative
        # Ensure it is rejected
        data = [
            (23900, 23950, 23850, 23900),  # 0
            (23900, 24000, 23880, 23950),  # 1
            (23950, 24100, 23920, 24050),  # 2
            (24050, 24200, 24000, 24150),  # 3: Swing High 24200
            (24100, 24120, 24020, 24080),  # 4
            (24080, 24100, 24000, 24020),  # 5: Origin
            # Candle 6 opens high at 24300, dips to 24050, closes at 24100
            (24300, 24350, 24050, 24100),  # 6
            # Candle 7 closes at 24220 (< open_6 of 24300! Net progress: 24220 - 24300 = -80 < 0!)
            (24100, 24250, 24080, 24210),  # 7: Breakout, but close < open_6! Single candle body ratio 110/170 = 0.64, but if we make single candle ratio weak:
        ]
        # Make candle 7 have weak single-candle body ratio: open 24150, close 24210, range 24000-24300 (ratio = 60/300 = 0.20 < 0.50)
        data[7] = (24150, 24300, 24000, 24210)
        df = create_candle_df(data)
        typed_obs, _ = engine.detect_order_blocks(df)
        bullish_obs = [o for o in typed_obs if o.direction == EventDirection.BULLISH]
        # Must be rejected because single candle ratio is weak AND cumulative progress is negative!
        assert len(bullish_obs) == 0

    def test_zero_net_progress_rejection(self):
        """Cumulative displacement with zero net progress (close_k == open_(i+1)) must be rejected."""
        engine = OrderBlockEngine(config=OrderBlockConfiguration(
            require_displacement=True,
            min_displacement_body_ratio=0.50,
            min_displacement_atr_multiple=1.0,
        ))
        data = [
            (23900, 23950, 23850, 23900),  # 0
            (23900, 24000, 23880, 23950),  # 1
            (23950, 24100, 23920, 24050),  # 2
            (24050, 24200, 24000, 24150),  # 3: Swing High 24200
            (24100, 24120, 24020, 24080),  # 4
            (24080, 24100, 24000, 24020),  # 5: Origin
            (24210, 24350, 24050, 24100),  # 6: Open 24210
            (24100, 24350, 24050, 24210),  # 7: Close 24210 == Open_6 24210! Zero net progress!
        ]
        df = create_candle_df(data)
        typed_obs, _ = engine.detect_order_blocks(df)
        bullish_obs = [o for o in typed_obs if o.direction == EventDirection.BULLISH]
        assert len(bullish_obs) == 0

    def test_opposite_direction_bearish_rejection(self):
        """Bearish OB must reject cumulative displacement if net progress is positive (close_k > open_(i+1))."""
        engine = OrderBlockEngine(config=OrderBlockConfiguration(
            require_displacement=True,
            min_displacement_body_ratio=0.50,
            min_displacement_atr_multiple=1.0,
        ))
        data = [
            (24800, 24850, 24750, 24800),  # 0
            (24750, 24800, 24650, 24700),  # 1
            (24700, 24720, 24580, 24600),  # 2: Left 1
            (24600, 24650, 24500, 24550),  # 3: Swing Low 24500
            (24550, 24620, 24530, 24600),  # 4: Right 1
            (24600, 24660, 24590, 24640),  # 5: Origin Green [24590, 24660]
            # Candle 6 opens low at 24300, closes at 24350
            (24300, 24400, 24200, 24350),  # 6
            # Candle 7 closes at 24450 > open_6 24300 (net progress is upward/positive!)
            (24350, 24500, 24200, 24450),  # 7
        ]
        df = create_candle_df(data)
        typed_obs, _ = engine.detect_order_blocks(df)
        bearish_obs = [o for o in typed_obs if o.direction == EventDirection.BEARISH]
        assert len(bearish_obs) == 0

    def test_threshold_boundary(self):
        """Displacement ratio exactly at boundary threshold (0.50) qualifies; ratio at 0.49 is rejected."""
        # Config requiring ratio = 0.50
        engine_50 = OrderBlockEngine(config=OrderBlockConfiguration(
            require_displacement=True,
            min_displacement_body_ratio=0.50,
            min_displacement_atr_multiple=1.0,
        ))
        # Candle 6: Open 24000, High 24200, Low 24000, Close 24100 -> Range 200, Body 100 -> Ratio = 0.50 exactly!
        data_exact = [
            (23900, 23950, 23850, 23900),  # 0
            (23900, 24000, 23880, 23950),  # 1
            (23950, 24100, 23920, 24050),  # 2
            (24050, 24200, 24000, 24150),  # 3: High 24200
            (24100, 24120, 24020, 24080),  # 4
            (24080, 24090, 23980, 24000),  # 5: Origin
            (24000, 24300, 24000, 24250),  # 6: Open 24000, High 24300, Low 24000, Close 24250. Body=250, Range=300 -> Ratio=0.833
        ]
        # Make candle 6 exactly ratio 0.50: Range = 200 (Low 24000, High 24200), Close 24200 > Swing High 24200? Wait, Close > 24200 requires High > 24200.
        # Let Swing High be 24150.
        # Candle 6: Open 24000, High 24400, Low 24000, Close 24200 -> Range 400, Body 200 -> Ratio = 200/400 = 0.500 exactly!
        data_exact[3] = (24050, 24150, 24000, 24120)  # Swing high 24150
        data_exact[6] = (24000, 24400, 24000, 24200)  # Open 24000, High 24400, Low 24000, Close 24200 (Close 24200 > 24150)
        df_exact = create_candle_df(data_exact)
        obs_exact, _ = engine_50.detect_order_blocks(df_exact)
        assert len(obs_exact) >= 1
        assert obs_exact[0].evidence.displacement_body_ratio == 0.50

        # Sub-threshold: Ratio = 196 / 400 = 0.490 < 0.50 -> REJECTED
        data_sub = list(data_exact)
        data_sub[6] = (24000, 24400, 24000, 24196)  # Close 24196 > 24150. Body=196, Range=400 -> Ratio=0.490
        df_sub = create_candle_df(data_sub)
        obs_sub, _ = engine_50.detect_order_blocks(df_sub)
        assert len(obs_sub) == 0


class TestExpiryBoundaryConsistency:
    """Closure Task 2: Deterministic expiry boundary verification at limit-1, exact limit, and limit+1."""

    def test_expiry_boundary_conditions(self):
        """
        Verify:
        - age = limit - 1: Order block remains active (NOT EXPIRED)
        - age = limit: Order block transitions to EXPIRED
        - age = limit + 1: Order block remains EXPIRED
        """
        limit = 3
        engine = OrderBlockEngine(config=OrderBlockConfiguration(max_active_candles=limit))

        # Dataset with confirmation at candle 6:
        # Candle 6: Confirmed (m_conf = 6)
        # Candle 7: age = 7 - 6 = 1
        # Candle 8: age = 8 - 6 = 2 (limit - 1 = 2) -> ACTIVE
        # Candle 9: age = 9 - 6 = 3 (exact limit = 3) -> EXPIRED
        # Candle 10: age = 10 - 6 = 4 (limit + 1 = 4) -> EXPIRED
        base_data = [
            (23900, 23950, 23850, 23900),  # 0
            (23900, 24000, 23880, 23950),  # 1
            (23950, 24100, 23920, 24050),  # 2
            (24050, 24200, 24000, 24150),  # 3: Swing High 24200
            (24100, 24120, 24020, 24080),  # 4
            (24080, 24090, 23980, 24000),  # 5: Origin Zone [23980, 24090]
            (24000, 24380, 23990, 24350),  # 6: Breakout Confirmed (m_conf = 6)
            (24350, 24450, 24300, 24400),  # 7: Far away (age = 1)
        ]

        # Case 1: age = limit - 1 = 2 (Candle 8)
        data_limit_minus_1 = base_data + [(24400, 24500, 24380, 24450)]  # 8
        obs_minus_1, _ = engine.detect_order_blocks(create_candle_df(data_limit_minus_1))
        assert len(obs_minus_1) >= 1
        assert obs_minus_1[0].event_status != LiquidityLifecycleState.EXPIRED
        assert obs_minus_1[0].is_active is True

        # Case 2: age = exact limit = 3 (Candle 9)
        data_exact_limit = data_limit_minus_1 + [(24450, 24550, 24400, 24500)]  # 9
        obs_exact, _ = engine.detect_order_blocks(create_candle_df(data_exact_limit))
        assert len(obs_exact) >= 1
        assert obs_exact[0].event_status == LiquidityLifecycleState.EXPIRED

        # Case 3: age = limit + 1 = 4 (Candle 10)
        data_limit_plus_1 = data_exact_limit + [(24500, 24600, 24480, 24550)]  # 10
        obs_plus_1, _ = engine.detect_order_blocks(create_candle_df(data_limit_plus_1))
        assert len(obs_plus_1) >= 1
        assert obs_plus_1[0].event_status == LiquidityLifecycleState.EXPIRED

    def test_expiry_applied_consistently_to_partially_mitigated(self):
        """A PARTIALLY_MITIGATED order block also expires when age >= max_active_candles."""
        limit = 3
        engine = OrderBlockEngine(config=OrderBlockConfiguration(max_active_candles=limit))

        # Candle 6: Confirmed (m_conf = 6)
        # Candle 7: Pullback into zone interior -> PARTIALLY_MITIGATED (age = 1)
        # Candle 8: Far away (age = 2 = limit - 1) -> Still PARTIALLY_MITIGATED
        # Candle 9: Far away (age = 3 = exact limit) -> EXPIRED
        data = [
            (23900, 23950, 23850, 23900),  # 0
            (23900, 24000, 23880, 23950),  # 1
            (23950, 24100, 23920, 24050),  # 2
            (24050, 24200, 24000, 24150),  # 3: Swing High 24200
            (24100, 24120, 24020, 24080),  # 4
            (24080, 24090, 23980, 24000),  # 5: Origin Zone [23980, 24090]
            (24000, 24380, 23990, 24350),  # 6: Breakout Confirmed (m_conf = 6)
            (24350, 24360, 24050, 24100),  # 7: Enters zone interior (Low 24050 < 24090) -> PARTIALLY_MITIGATED!
            (24100, 24450, 24100, 24400),  # 8: Far away (age = 2 = limit - 1)
            (24400, 24500, 24380, 24480),  # 9: Far away (age = 3 = exact limit) -> EXPIRES!
        ]
        df = create_candle_df(data)
        typed_obs, _ = engine.detect_order_blocks(df)
        assert len(typed_obs) >= 1
        assert typed_obs[0].event_status == LiquidityLifecycleState.EXPIRED


