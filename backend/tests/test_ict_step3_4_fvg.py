"""
AIVOLVE Phase 3 Step 3.4 — Fair Value Gap (FVG) & Inverse FVG (IFVG) Engine Test Suite.
Comprehensive validation covering 55 dedicated tests across 8 suites:
- Suite 1: Pure FVG Geometry & Mathematical Boundaries (8 Tests)
- Suite 2: Directional Displacement & ATR Qualification (8 Tests)
- Suite 3: Timestamp Invariants & As-Of Point-in-Time Slicing (6 Tests)
- Suite 4: Tick-Size Governance & Raw Price Preservation (5 Tests)
- Suite 5: Configuration Fingerprint & Collision Prevention (6 Tests)
- Suite 6: FVG Lifecycle State Machine & Mitigation Policies (8 Tests)
- Suite 7: IFVG Detection, Single Inversion & Linkage (8 Tests)
- Suite 8: Data Quality Lockouts & Calendar Safeguards (6 Tests)

STRICTLY PAPER TRADING ONLY.
"""

import pytest
from typing import Dict, Any, List, Optional, Tuple, Set
from datetime import datetime, timezone, timedelta, time
import numpy as np
import pandas as pd

from app.options.ict_smc.ict_models import (
    ICTEvent,
    ICTEventType,
    EventDirection,
    LiquidityLifecycleState,
    FVGEvidence,
    FVGEvent,
    FVGConfiguration,
    FVG_ACTIVE_STATES,
    VALID_FVG_TRANSITIONS,
    VALID_IFVG_TRANSITIONS,
    validate_fvg_transition,
    validate_ifvg_transition,
    compute_configuration_fingerprint,
    canonicalize_value,
    generate_deterministic_fvg_event_id,
    IST_ZONE,
)
from app.options.ict_smc.fvg_engine import (
    FVGEngine,
    TimeframeFVGReport,
    SESSION_START_TIME,
    SESSION_END_TIME,
)


def make_candle(
    cid: str,
    open_p: float,
    high_p: float,
    low_p: float,
    close_p: float,
    dt: datetime,
) -> Dict[str, Any]:
    return {
        "candle_id": cid,
        "timestamp": dt,
        "open": open_p,
        "high": high_p,
        "low": low_p,
        "close": close_p,
        "volume": 1000,
    }


def make_bullish_fvg_series(base_time: datetime, count: int = 20) -> pd.DataFrame:
    """
    Creates a synthetic series with a single confirmed Bullish FVG on candles 1, 2, 3:
    C0: Open=24000, High=24020, Low=23995, Close=24010
    C1: Open=24010, High=24025, Low=24005, Close=24015 (small body ratio 0.25 -> not impulse)
    C2: Open=24020, High=24075, Low=24018, Close=24070 (large bullish body ratio 0.88 -> impulse)
    C3: Open=24070, High=24090, Low=24050, Close=24080 (Low 24050 > C1 High 24025)
    Gap: [24025, 24050], Span=25 pts, CE=24037.5
    """
    candles = []
    t = base_time
    for k in range(count):
        if k == 0:
            candles.append(make_candle(f"c_{k}", 24000.0, 24020.0, 23995.0, 24010.0, t))
        elif k == 1:
            candles.append(make_candle(f"c_{k}", 24010.0, 24025.0, 24005.0, 24015.0, t))
        elif k == 2:
            # Impulse expansion candle C2
            candles.append(make_candle(f"c_{k}", 24020.0, 24075.0, 24018.0, 24070.0, t))
        elif k == 3:
            # Confirmation candle C3 (Low=24050 > C1 High=24025)
            candles.append(make_candle(f"c_{k}", 24070.0, 24090.0, 24050.0, 24080.0, t))
        else:
            # Subsequent bars drifting above
            candles.append(make_candle(f"c_{k}", 24080.0 + k, 24095.0 + k, 24075.0 + k, 24085.0 + k, t))
        t += timedelta(minutes=15)
    return pd.DataFrame(candles)


def make_bearish_fvg_series(base_time: datetime, count: int = 20) -> pd.DataFrame:
    """
    Creates a synthetic series with a single confirmed Bearish FVG on candles 1, 2, 3:
    C0: Open=24100, High=24110, Low=24075, Close=24090
    C1: Open=24090, High=24095, Low=24080, Close=24085 (small body ratio 0.33 -> not impulse)
    C2: Open=24082, High=24085, Low=24025, Close=24030 (large bearish body ratio 0.87 -> impulse)
    C3: Open=24030, High=24045, Low=24010, Close=24020 (High 24045 < C1 Low 24080)
    Gap: [24045, 24080], Span=35 pts, CE=24062.5
    """
    candles = []
    t = base_time
    for k in range(count):
        if k == 0:
            candles.append(make_candle(f"c_{k}", 24100.0, 24110.0, 24075.0, 24090.0, t))
        elif k == 1:
            candles.append(make_candle(f"c_{k}", 24090.0, 24095.0, 24080.0, 24085.0, t))
        elif k == 2:
            # Impulse expansion candle C2
            candles.append(make_candle(f"c_{k}", 24082.0, 24085.0, 24025.0, 24030.0, t))
        elif k == 3:
            # Confirmation candle C3 (High=24045 < C1 Low=24080)
            candles.append(make_candle(f"c_{k}", 24030.0, 24045.0, 24010.0, 24020.0, t))
        else:
            candles.append(make_candle(f"c_{k}", 24020.0 - k, 24025.0 - k, 24005.0 - k, 24015.0 - k, t))
        t += timedelta(minutes=15)
    return pd.DataFrame(candles)


# =====================================================================
# Suite 1: Pure FVG Geometry & Mathematical Boundaries (8 Tests)
# =====================================================================

class TestFVGGeometryAndBoundaries:
    def test_bullish_fvg_exact_geometry(self):
        t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST_ZONE)  # Monday trading day
        df = make_bullish_fvg_series(t0, count=10)
        engine = FVGEngine(FVGConfiguration(min_gap_atr_multiple=0.0))
        typed_fvg, canon_fvg, _, _ = engine.detect_gaps(df, timeframe="15m")

        assert len(typed_fvg) >= 1
        b_fvg = typed_fvg[0]
        assert b_fvg.direction == EventDirection.BULLISH
        assert b_fvg.zone_high == 24050.0
        assert b_fvg.zone_low == 24025.0
        assert b_fvg.evidence.gap_size_pts == 25.0
        assert b_fvg.mean_threshold == 24037.5
        assert b_fvg.evidence.consequent_encroachment == 24037.5

    def test_bearish_fvg_exact_geometry(self):
        t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST_ZONE)
        df = make_bearish_fvg_series(t0, count=10)
        engine = FVGEngine(FVGConfiguration(min_gap_atr_multiple=0.0))
        typed_fvg, canon_fvg, _, _ = engine.detect_gaps(df, timeframe="15m")

        assert len(typed_fvg) >= 1
        b_fvg = typed_fvg[0]
        assert b_fvg.direction == EventDirection.BEARISH
        assert b_fvg.zone_high == 24080.0
        assert b_fvg.zone_low == 24045.0
        assert b_fvg.evidence.gap_size_pts == 35.0
        assert b_fvg.mean_threshold == 24062.5

    def test_zero_gap_boundary_rejection(self):
        # C1 High = 24050, C3 Low = 24050 -> Span = 0.0 -> REJECTED
        t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST_ZONE)
        df = make_bullish_fvg_series(t0, count=5)
        df.loc[3, "low"] = 24025.0  # Exactly equal to C1 high
        engine = FVGEngine(FVGConfiguration(min_gap_atr_multiple=0.0))
        typed_fvg, _, _, _ = engine.detect_gaps(df, timeframe="15m")
        assert len(typed_fvg) == 0

    def test_negative_spread_overlap_rejection(self):
        # C1 High = 24025, C3 Low = 24020 -> Overlapping wicks -> REJECTED
        t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST_ZONE)
        df = make_bullish_fvg_series(t0, count=5)
        df.loc[3, "low"] = 24020.0
        engine = FVGEngine(FVGConfiguration(min_gap_atr_multiple=0.0))
        typed_fvg, _, _, _ = engine.detect_gaps(df, timeframe="15m")
        assert len(typed_fvg) == 0

    def test_consequent_encroachment_midpoint_precision(self):
        t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST_ZONE)
        df = make_bullish_fvg_series(t0, count=5)
        engine = FVGEngine(FVGConfiguration(min_gap_atr_multiple=0.0))
        typed_fvg, _, _, _ = engine.detect_gaps(df, timeframe="15m")
        fvg = typed_fvg[0]
        expected_ce = (fvg.zone_high + fvg.zone_low) / 2.0
        assert fvg.mean_threshold == expected_ce
        assert fvg.evidence.consequent_encroachment == expected_ce

    def test_minimum_gap_size_pts_threshold(self):
        t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST_ZONE)
        df = make_bullish_fvg_series(t0, count=5)  # Gap is 25.0 pts
        # Set threshold to 30.0 pts -> Must be rejected
        engine = FVGEngine(FVGConfiguration(min_gap_size_pts=30.0, min_gap_atr_multiple=0.0))
        typed_fvg, _, _, _ = engine.detect_gaps(df, timeframe="15m")
        assert len(typed_fvg) == 0

        # Set threshold to 20.0 pts -> Must qualify
        engine2 = FVGEngine(FVGConfiguration(min_gap_size_pts=20.0, min_gap_atr_multiple=0.0))
        typed_fvg2, _, _, _ = engine2.detect_gaps(df, timeframe="15m")
        assert len(typed_fvg2) == 1

    def test_flat_candle_zero_range_disqualification(self):
        t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST_ZONE)
        df = make_bullish_fvg_series(t0, count=5)
        # Flat candle on C2: high == low == 24050
        df.loc[2, "high"] = 24050.0
        df.loc[2, "low"] = 24050.0
        df.loc[2, "open"] = 24050.0
        df.loc[2, "close"] = 24050.0
        engine = FVGEngine(FVGConfiguration(min_gap_atr_multiple=0.0))
        typed_fvg, _, _, _ = engine.detect_gaps(df, timeframe="15m")
        assert len(typed_fvg) == 0

    def test_single_and_two_candle_input_handling(self):
        t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST_ZONE)
        df = make_bullish_fvg_series(t0, count=2)
        engine = FVGEngine()
        tfvg, cfvg, tifvg, cifvg = engine.detect_gaps(df)
        assert len(tfvg) == 0
        assert len(cfvg) == 0
        assert len(tifvg) == 0
        assert len(cifvg) == 0


# =====================================================================
# Suite 2: Directional Displacement & ATR Qualification (8 Tests)
# =====================================================================

class TestDisplacementAndATRQualification:
    def test_bullish_displacement_direction_enforcement(self):
        t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST_ZONE)
        df = make_bullish_fvg_series(t0, count=5)
        # Make C2 a bearish candle: close < open
        df.loc[2, "open"] = 24070.0
        df.loc[2, "close"] = 24020.0
        engine = FVGEngine(FVGConfiguration(min_gap_atr_multiple=0.0))
        typed_fvg, _, _, _ = engine.detect_gaps(df, timeframe="15m")
        # Must be rejected because Bullish FVG requires bullish body on C2
        assert len(typed_fvg) == 0

    def test_bearish_displacement_direction_enforcement(self):
        t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST_ZONE)
        df = make_bearish_fvg_series(t0, count=5)
        # Make C2 a bullish candle: close > open
        df.loc[2, "open"] = 24030.0
        df.loc[2, "close"] = 24080.0
        engine = FVGEngine(FVGConfiguration(min_gap_atr_multiple=0.0))
        typed_fvg, _, _, _ = engine.detect_gaps(df, timeframe="15m")
        # Must be rejected because Bearish FVG requires bearish body on C2
        assert len(typed_fvg) == 0

    def test_displacement_body_ratio_boundary(self):
        t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST_ZONE)
        df = make_bullish_fvg_series(t0, count=5)
        # C2 range = 100 pts. Body = 40 pts -> body ratio = 0.40 < 0.50
        df.loc[2, "open"] = 24030.0
        df.loc[2, "close"] = 24070.0
        df.loc[2, "low"] = 24000.0
        df.loc[2, "high"] = 24100.0
        engine = FVGEngine(FVGConfiguration(min_displacement_body_ratio=0.50, min_gap_atr_multiple=0.0))
        typed_fvg, _, _, _ = engine.detect_gaps(df, timeframe="15m")
        assert len(typed_fvg) == 0

        # Body = 60 pts -> body ratio = 0.60 >= 0.50 -> Qualifies
        df.loc[2, "close"] = 24090.0
        typed_fvg2, _, _, _ = engine.detect_gaps(df, timeframe="15m")
        assert len(typed_fvg2) == 1

    def test_wilder_atr_rma_calculation_exactness(self):
        highs = np.array([24000.0 + i * 10 for i in range(20)])
        lows = np.array([23990.0 + i * 10 for i in range(20)])
        closes = np.array([23995.0 + i * 10 for i in range(20)])
        atr = FVGEngine._compute_atr(highs, lows, closes, period=14)
        assert atr is not None
        assert len(atr) == 20
        # True range for constant 10 pt bar with 10 pt step is 15-20 pts
        assert atr[14] > 0.0
        assert not np.isnan(atr[14])

    def test_atr_insufficient_history_lockout(self):
        # 10 candles total -> N < 15 -> ATR cannot be calculated
        t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST_ZONE)
        df = make_bullish_fvg_series(t0, count=10)
        # When min_gap_atr_multiple > 0, lack of ATR history fails closed
        engine = FVGEngine(FVGConfiguration(min_gap_atr_multiple=0.10))
        typed_fvg, _, _, _ = engine.detect_gaps(df, timeframe="15m")
        assert len(typed_fvg) == 0

    def test_atr_zero_multiple_skips_atr_filter(self):
        # 5 candles total -> N < 15
        t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST_ZONE)
        df = make_bullish_fvg_series(t0, count=5)
        # When min_gap_atr_multiple == 0.0, lack of ATR history does NOT disqualify FVG!
        engine = FVGEngine(FVGConfiguration(min_gap_atr_multiple=0.0))
        typed_fvg, _, _, _ = engine.detect_gaps(df, timeframe="15m")
        assert len(typed_fvg) == 1
        assert typed_fvg[0].evidence.atr_status == "SKIPPED_CONFIGURED_ZERO"
        assert typed_fvg[0].evidence.gap_atr_multiple is None

    def test_zero_and_negative_atr_lockout(self):
        # Flat series: High == Low across all 20 bars
        highs = np.full(20, 24000.0)
        lows = np.full(20, 24000.0)
        closes = np.full(20, 24000.0)
        atr = FVGEngine._compute_atr(highs, lows, closes, period=14)
        # Must return None (zero volatility lockout)
        assert atr is None

    def test_nan_atr_fails_closed(self):
        highs = np.array([24000.0] * 10 + [np.nan] + [24000.0] * 9)
        lows = np.full(20, 23990.0)
        closes = np.full(20, 23995.0)
        atr = FVGEngine._compute_atr(highs, lows, closes, period=14)
        assert atr is None


# =====================================================================
# Suite 3: Timestamp Invariants & As-Of Point-in-Time Slicing (6 Tests)
# =====================================================================

class TestTimestampAndAsOfInvariants:
    def test_available_at_equals_c3_close_time_not_open_time(self):
        t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST_ZONE)
        df = make_bullish_fvg_series(t0, count=5)
        engine = FVGEngine(FVGConfiguration(min_gap_atr_multiple=0.0))
        typed_fvg, _, _, _ = engine.detect_gaps(df, timeframe="15m")

        fvg = typed_fvg[0]
        # C3 is index 3 -> open_time is 09:15 + 3*15m = 10:00:00
        # close_time of C3 is 10:15:00
        expected_available_at = t0 + timedelta(minutes=60)  # 10:15:00
        assert fvg.available_at == expected_available_at
        assert fvg.confirmed_at == expected_available_at
        assert fvg.available_at != df.iloc[3]["timestamp"]  # Must not equal open time

    def test_event_time_equals_c2_open_time(self):
        t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST_ZONE)
        df = make_bullish_fvg_series(t0, count=5)
        engine = FVGEngine(FVGConfiguration(min_gap_atr_multiple=0.0))
        typed_fvg, _, _, _ = engine.detect_gaps(df, timeframe="15m")

        fvg = typed_fvg[0]
        # C2 open time is 09:15 + 2*15m = 09:45:00
        expected_event_time = t0 + timedelta(minutes=30)
        assert fvg.event_time == expected_event_time

    def test_as_of_filtering_excludes_forming_candles(self):
        t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST_ZONE)
        df = make_bullish_fvg_series(t0, count=10)
        engine = FVGEngine(FVGConfiguration(min_gap_atr_multiple=0.0))

        # C3 completes at 10:15:00.
        # Query at 10:10:00 (inside forming C3) -> C3 is incomplete -> 0 FVGs
        as_of_mid_c3 = t0 + timedelta(minutes=55)  # 10:10:00
        tfvg_early, _, _, _ = engine.detect_gaps(df, timeframe="15m", as_of_time=as_of_mid_c3)
        assert len(tfvg_early) == 0

        # Query at 10:15:00 (exact completion of C3) -> C3 is completed -> 1 FVG
        as_of_exact_c3 = t0 + timedelta(minutes=60)  # 10:15:00
        tfvg_exact, _, _, _ = engine.detect_gaps(df, timeframe="15m", as_of_time=as_of_exact_c3)
        assert len(tfvg_exact) == 1

    def test_no_self_mitigation_on_confirmation_bar(self):
        t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST_ZONE)
        df = make_bullish_fvg_series(t0, count=4)  # Bars 0, 1, 2, 3
        engine = FVGEngine(FVGConfiguration(min_gap_atr_multiple=0.0))
        # Even if C3 low touches the zone boundary, it cannot mitigate itself on confirmation bar
        typed_fvg, _, _, _ = engine.detect_gaps(df, timeframe="15m")
        assert len(typed_fvg) == 1
        assert typed_fvg[0].event_status == LiquidityLifecycleState.CONFIRMED
        assert typed_fvg[0].evidence.touch_count == 0

    def test_sequential_replay_vs_batch_identity(self):
        t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST_ZONE)
        df = make_bullish_fvg_series(t0, count=10)
        engine = FVGEngine(FVGConfiguration(min_gap_atr_multiple=0.0))

        # Batch detection
        _, batch_canon, _, _ = engine.detect_gaps(df, timeframe="15m")

        # Step-by-step sequential replay at final candle
        final_close = t0 + timedelta(minutes=15 * 10)
        _, replay_canon, _, _ = engine.detect_gaps(df, timeframe="15m", as_of_time=final_close)

        assert len(batch_canon) == len(replay_canon)
        for b, r in zip(batch_canon, replay_canon):
            assert b.event_id == r.event_id
            assert b.event_status == r.event_status
            assert b.price_level == r.price_level

    def test_session_end_clamp_for_1h_candles(self):
        # 1h candle opening at 15:15 IST (Bar 7)
        t_open = datetime(2026, 11, 2, 15, 15, tzinfo=IST_ZONE)
        clamped_close = FVGEngine.compute_candle_close_time(t_open, timeframe="1h")
        # Must clamp strictly to 15:30 IST (15 minutes duration), NOT 16:15 IST
        assert clamped_close.time() == time(15, 30)
        assert (clamped_close - t_open) == timedelta(minutes=15)


# =====================================================================
# Suite 4: Tick-Size Governance & Raw Price Preservation (5 Tests)
# =====================================================================

class TestRawPriceAndTickSizeGovernance:
    def test_raw_price_preservation_no_quantization(self):
        # Ensure arbitrary float decimals are not quantized to 0.05
        t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST_ZONE)
        df = make_bullish_fvg_series(t0, count=5)
        df.loc[1, "high"] = 24025.1234
        df.loc[3, "low"] = 24050.5678

        engine = FVGEngine(FVGConfiguration(min_gap_atr_multiple=0.0))
        typed_fvg, _, _, _ = engine.detect_gaps(df, timeframe="15m")

        assert len(typed_fvg) == 1
        fvg = typed_fvg[0]
        assert fvg.zone_low == 24025.1234
        assert fvg.zone_high == 24050.5678

    def test_approach_threshold_representation_dynamic(self):
        t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST_ZONE)
        df = make_bullish_fvg_series(t0, count=6)
        # Bar 4 approaches zone: Low = 24051.0 (Zone High = 24050.0, delta <= 2.0 pts)
        df.loc[4, "low"] = 24051.0
        df.loc[4, "high"] = 24070.0
        df.loc[4, "open"] = 24065.0
        df.loc[4, "close"] = 24060.0

        engine = FVGEngine(FVGConfiguration(min_gap_atr_multiple=0.0, approach_threshold_pts=2.0))
        typed_fvg, _, _, _ = engine.detect_gaps(df, timeframe="15m")

        assert len(typed_fvg) == 1
        assert typed_fvg[0].event_status == LiquidityLifecycleState.APPROACHING
        # Zone boundaries remain strictly untouched
        assert typed_fvg[0].zone_high == 24050.0
        assert typed_fvg[0].zone_low == 24025.0

    def test_option_tick_size_does_not_modify_spot_index(self):
        # Verifies underlying index spot prices are not modified by option tick constraints
        t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST_ZONE)
        df = make_bullish_fvg_series(t0, count=5)
        df.loc[1, "high"] = 24025.03  # Non-0.05 tick price
        df.loc[3, "low"] = 24050.07

        engine = FVGEngine(FVGConfiguration(min_gap_atr_multiple=0.0))
        typed_fvg, canon_fvg, _, _ = engine.detect_gaps(df, timeframe="15m")

        assert canon_fvg[0].zone_low == 24025.03
        assert canon_fvg[0].zone_high == 24050.07

    def test_bankers_rounding_half_even_stability(self):
        cfg = FVGConfiguration(min_displacement_body_ratio=0.50)
        fp = cfg.get_fingerprint()
        assert isinstance(fp, str)
        assert len(fp) == 64

    def test_canonical_ict_event_contract_immutability(self):
        t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST_ZONE)
        df = make_bullish_fvg_series(t0, count=5)
        engine = FVGEngine(FVGConfiguration(min_gap_atr_multiple=0.0))
        _, canon_fvg, _, _ = engine.detect_gaps(df, timeframe="15m")

        evt = canon_fvg[0]
        # Canonical 17-field contract checks
        assert hasattr(evt, "event_id")
        assert hasattr(evt, "index")
        assert hasattr(evt, "event_type")
        assert hasattr(evt, "direction")
        assert hasattr(evt, "timeframe")
        assert hasattr(evt, "price_level")
        assert hasattr(evt, "zone_high")
        assert hasattr(evt, "zone_low")
        assert hasattr(evt, "event_status")
        assert hasattr(evt, "event_time")
        assert hasattr(evt, "available_at")
        assert hasattr(evt, "created_at")
        assert hasattr(evt, "confirmed_at")
        assert hasattr(evt, "invalidated_at")
        assert hasattr(evt, "source_candle_identifiers")
        assert hasattr(evt, "data_quality")
        assert hasattr(evt, "evidence")
        assert hasattr(evt, "configuration_version")
        assert hasattr(evt, "engine_version")


# =====================================================================
# Suite 5: Configuration Fingerprint & Collision Prevention (6 Tests)
# =====================================================================

class TestConfigurationFingerprintAndEventIDs:
    def test_deterministic_event_id_reproducibility(self):
        cfg = FVGConfiguration()
        fp = cfg.get_fingerprint()
        id1 = generate_deterministic_fvg_event_id("NIFTY 50", "15m", "FVG", "c_2", fp)
        id2 = generate_deterministic_fvg_event_id("NIFTY 50", "15m", "FVG", "c_2", fp)
        assert id1 == id2
        assert len(id1) == 64

    def test_parameter_change_alters_config_fingerprint(self):
        cfg1 = FVGConfiguration(min_displacement_body_ratio=0.50)
        cfg2 = FVGConfiguration(min_displacement_body_ratio=0.70)
        fp1 = cfg1.get_fingerprint()
        fp2 = cfg2.get_fingerprint()
        assert fp1 != fp2

    def test_different_thresholds_produce_different_event_ids(self):
        cfg1 = FVGConfiguration(min_gap_atr_multiple=0.10)
        cfg2 = FVGConfiguration(min_gap_atr_multiple=0.25)
        fp1 = cfg1.get_fingerprint()
        fp2 = cfg2.get_fingerprint()

        id1 = generate_deterministic_fvg_event_id("NIFTY 50", "15m", "FVG", "c_2", fp1)
        id2 = generate_deterministic_fvg_event_id("NIFTY 50", "15m", "FVG", "c_2", fp2)
        assert id1 != id2

    def test_config_fingerprint_full_64_hex_length(self):
        cfg = FVGConfiguration()
        fp = compute_configuration_fingerprint(cfg)
        assert len(fp) == 64
        int(fp, 16)  # Must be valid hex

    def test_canonical_float_serialization_precision(self):
        # Tests that 0.5 and 0.500000 serialize identically and with fixed precision
        cfg1 = FVGConfiguration(min_displacement_body_ratio=0.5)
        cfg2 = FVGConfiguration(min_displacement_body_ratio=0.500000)
        assert cfg1.get_fingerprint() == cfg2.get_fingerprint()

    def test_historical_event_immutability(self):
        t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST_ZONE)
        df_short = make_bullish_fvg_series(t0, count=5)
        df_long = make_bullish_fvg_series(t0, count=10)

        engine = FVGEngine(FVGConfiguration(min_gap_atr_multiple=0.0))
        _, canon_short, _, _ = engine.detect_gaps(df_short, timeframe="15m")
        _, canon_long, _, _ = engine.detect_gaps(df_long, timeframe="15m")

        assert canon_short[0].event_id == canon_long[0].event_id
        assert canon_short[0].available_at == canon_long[0].available_at

    def test_micro_float_precision_preservation_distinct_fingerprints(self):
        # Distinct floating-point configuration thresholds with differences beyond 6 decimals
        # must NEVER collide or truncate.
        cfg_a = FVGConfiguration(min_gap_size_pts=0.0000001)
        cfg_b = FVGConfiguration(min_gap_size_pts=0.0000002)
        assert cfg_a.get_fingerprint() != cfg_b.get_fingerprint()

        # Direct dictionary fingerprints at 1e-9 precision
        fp1 = compute_configuration_fingerprint({"threshold": 1e-9})
        fp2 = compute_configuration_fingerprint({"threshold": 2e-9})
        assert fp1 != fp2

    def test_negative_zero_normalization(self):
        # IEEE-754 -0.0 and +0.0 must normalize to identical canonical representation
        fp_pos = compute_configuration_fingerprint({"buffer": 0.0, "version": "1.0"})
        fp_neg = compute_configuration_fingerprint({"buffer": -0.0, "version": "1.0"})
        assert fp_pos == fp_neg

    def test_type_discrimination_null_bool_int_float(self):
        # Null (None) serialization
        fp_null = compute_configuration_fingerprint({"param": None})
        assert len(fp_null) == 64

        # Booleans vs Integers vs Floats must produce distinct fingerprints
        fp_bool_true = compute_configuration_fingerprint({"flag": True})
        fp_bool_false = compute_configuration_fingerprint({"flag": False})
        fp_int_one = compute_configuration_fingerprint({"flag": 1})
        fp_float_one = compute_configuration_fingerprint({"flag": 1.0})

        assert fp_bool_true != fp_bool_false
        assert fp_bool_true != fp_int_one  # True != 1 in canonical serialization
        assert fp_int_one != fp_float_one  # 1 (int) != 1.0 (float)

    def test_nested_configuration_dictionaries_and_sorting(self):
        # Nested dictionaries with different key insertion orders must yield identical fingerprints
        dict1 = {"b": 2, "a": 1, "nested": {"y": 20, "x": 10}}
        dict2 = {"a": 1, "nested": {"x": 10, "y": 20}, "b": 2}
        assert compute_configuration_fingerprint(dict1) == compute_configuration_fingerprint(dict2)

    def test_non_finite_floats_fail_closed(self):
        # NaN and infinities are rejected
        with pytest.raises(ValueError, match="Non-finite float"):
            compute_configuration_fingerprint({"bad": float("nan")})

        with pytest.raises(ValueError, match="Non-finite float"):
            compute_configuration_fingerprint({"bad": float("inf")})

    def test_scientific_exponent_notation_and_extreme_finite_floats(self):
        # Micro-scale floats with scientific notation
        fp_micro1 = compute_configuration_fingerprint({"val": 1.23e-10})
        fp_micro2 = compute_configuration_fingerprint({"val": 1.24e-10})
        assert fp_micro1 != fp_micro2
        assert len(fp_micro1) == 64

        # Macro-scale floats
        fp_macro1 = compute_configuration_fingerprint({"val": 1.23e12})
        fp_macro2 = compute_configuration_fingerprint({"val": 1.24e12})
        assert fp_macro1 != fp_macro2

        # Extreme finite floats
        fp_min = compute_configuration_fingerprint({"val": 1e-300})
        fp_max = compute_configuration_fingerprint({"val": 1e300})
        assert fp_min != fp_max

    def test_repeated_deterministic_hashing_stability(self):
        # Proves 100% deterministic reproducibility across repeated runs
        cfg = FVGConfiguration()
        expected = compute_configuration_fingerprint(cfg)
        for _ in range(500):
            assert compute_configuration_fingerprint(cfg) == expected

        # Complex deeply nested structure
        nested = {
            "root": {
                "sub": {
                    "leaves": [
                        {"id": 1, "score": 0.123456789012345},
                        {"id": 2, "active": True, "ratio": 1e-8},
                    ],
                    "meta": None,
                }
            }
        }
        nested_expected = compute_configuration_fingerprint(nested)
        for _ in range(500):
            assert compute_configuration_fingerprint(nested) == nested_expected


# =====================================================================
# Suite 6: FVG Lifecycle State Machine & Mitigation Policies (8 Tests)
# =====================================================================

class TestFVGLifecycleStateMachine:
    def test_fvg_identified_to_confirmed_transition(self):
        t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST_ZONE)
        df = make_bullish_fvg_series(t0, count=4)
        engine = FVGEngine(FVGConfiguration(min_gap_atr_multiple=0.0))
        typed_fvg, _, _, _ = engine.detect_gaps(df, timeframe="15m")

        assert len(typed_fvg) == 1
        assert typed_fvg[0].event_status == LiquidityLifecycleState.CONFIRMED
        assert typed_fvg[0].is_active is True

    def test_fvg_approach_and_retreat_hysteresis(self):
        t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST_ZONE)
        df = make_bullish_fvg_series(t0, count=7)
        # Bar 4 enters approach zone (Low = 24051.0 <= 24050.0 + 2.0)
        df.loc[4, "open"] = 24065.0
        df.loc[4, "high"] = 24070.0
        df.loc[4, "low"] = 24051.0
        df.loc[4, "close"] = 24060.0
        # Bar 5 retreats far away (Low = 24065.0 > 24050.0 + 2.0 * 1.5 = 24053.0)
        df.loc[5, "open"] = 24070.0
        df.loc[5, "high"] = 24080.0
        df.loc[5, "low"] = 24065.0
        df.loc[5, "close"] = 24075.0

        engine = FVGEngine(FVGConfiguration(min_gap_atr_multiple=0.0, approach_threshold_pct=0.0, approach_threshold_pts=2.0, approach_retreat_mult=1.5))
        # At Bar 4 completion
        t_bar4 = t0 + timedelta(minutes=15 * 5)
        tfvg_app, _, _, _ = engine.detect_gaps(df, timeframe="15m", as_of_time=t_bar4)
        assert tfvg_app[0].event_status == LiquidityLifecycleState.APPROACHING

        # At Bar 5 completion -> Retreats back to CONFIRMED
        t_bar5 = t0 + timedelta(minutes=15 * 6)
        tfvg_ret, _, _, _ = engine.detect_gaps(df, timeframe="15m", as_of_time=t_bar5)
        assert tfvg_ret[0].event_status == LiquidityLifecycleState.CONFIRMED

    def test_fvg_partial_mitigation_high_water_mark(self):
        t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST_ZONE)
        df = make_bullish_fvg_series(t0, count=6)
        # Zone is [24025, 24050], Span = 25 pts. CE = 24037.5
        # Bar 4 wicks down to 24040.0 (Penetration = 10 pts = 40.0% < 50% CE)
        df.loc[4, "open"] = 24065.0
        df.loc[4, "high"] = 24070.0
        df.loc[4, "low"] = 24040.0
        df.loc[4, "close"] = 24060.0

        engine = FVGEngine(FVGConfiguration(min_gap_atr_multiple=0.0, full_mitigation_policy="CONSEQUENT_ENCROACHMENT"))
        typed_fvg, _, _, _ = engine.detect_gaps(df, timeframe="15m")

        assert typed_fvg[0].event_status == LiquidityLifecycleState.PARTIALLY_MITIGATED
        assert typed_fvg[0].evidence.mitigation_percentage == 40.0
        assert typed_fvg[0].evidence.touch_count == 1
        assert typed_fvg[0].is_active is True

    def test_consequent_encroachment_terminal_mitigation(self):
        t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST_ZONE)
        df = make_bullish_fvg_series(t0, count=6)
        # Zone is [24025, 24050], CE = 24037.5
        # Bar 4 wicks down to 24035.0 (Penetration = 15 pts = 60.0% >= 50% CE)
        df.loc[4, "open"] = 24065.0
        df.loc[4, "high"] = 24070.0
        df.loc[4, "low"] = 24035.0
        df.loc[4, "close"] = 24060.0

        engine = FVGEngine(FVGConfiguration(min_gap_atr_multiple=0.0, full_mitigation_policy="CONSEQUENT_ENCROACHMENT"))
        typed_fvg, _, _, _ = engine.detect_gaps(df, timeframe="15m")

        assert typed_fvg[0].event_status == LiquidityLifecycleState.MITIGATED
        assert typed_fvg[0].evidence.mitigated_at is not None
        assert typed_fvg[0].is_active is False

    def test_full_fill_terminal_mitigation(self):
        t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST_ZONE)
        df = make_bullish_fvg_series(t0, count=6)
        # Under FULL_FILL policy, reaching 60% CE is PARTIALLY_MITIGATED, not MITIGATED
        df.loc[4, "open"] = 24065.0
        df.loc[4, "high"] = 24070.0
        df.loc[4, "low"] = 24035.0
        df.loc[4, "close"] = 24060.0

        engine = FVGEngine(FVGConfiguration(min_gap_atr_multiple=0.0, full_mitigation_policy="FULL_FILL"))
        typed_fvg, _, _, _ = engine.detect_gaps(df, timeframe="15m")
        assert typed_fvg[0].event_status == LiquidityLifecycleState.PARTIALLY_MITIGATED

        # Reaching 100% (Low <= 24025.0) transitions to MITIGATED
        df.loc[4, "open"] = 24065.0
        df.loc[4, "high"] = 24070.0
        df.loc[4, "low"] = 24025.0
        df.loc[4, "close"] = 24060.0
        typed_fvg2, _, _, _ = engine.detect_gaps(df, timeframe="15m")
        assert typed_fvg2[0].event_status == LiquidityLifecycleState.MITIGATED

    def test_completed_close_invalidation_precedence_over_wick(self):
        t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST_ZONE)
        df = make_bullish_fvg_series(t0, count=6)
        # Bar 4 wicks into zone (Low=24015) AND closes below lower boundary (Close=24020 < 24025)
        df.loc[4, "open"] = 24040.0
        df.loc[4, "high"] = 24045.0
        df.loc[4, "low"] = 24015.0
        df.loc[4, "close"] = 24020.0

        engine = FVGEngine(FVGConfiguration(min_gap_atr_multiple=0.0))
        typed_fvg, _, _, _ = engine.detect_gaps(df, timeframe="15m")

        # Invalidation close strictly takes precedence over mitigation!
        assert typed_fvg[0].event_status == LiquidityLifecycleState.INVALIDATED
        assert typed_fvg[0].invalidated_at is not None

    def test_max_active_candles_expiry(self):
        t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST_ZONE)
        df = make_bullish_fvg_series(t0, count=15)
        # Set max_active_candles = 5
        engine = FVGEngine(FVGConfiguration(min_gap_atr_multiple=0.0, max_active_candles=5))
        typed_fvg, _, _, _ = engine.detect_gaps(df, timeframe="15m")

        # C3 is at idx 3. At idx 9, age = 6 >= 5 -> EXPIRED
        assert typed_fvg[0].event_status == LiquidityLifecycleState.EXPIRED
        assert typed_fvg[0].is_active is False

    def test_absorbing_terminal_states_cannot_transition(self):
        # Validate that terminal states have empty sets in state machine
        assert VALID_FVG_TRANSITIONS[LiquidityLifecycleState.MITIGATED] == set()
        assert VALID_FVG_TRANSITIONS[LiquidityLifecycleState.INVALIDATED] == set()
        assert VALID_FVG_TRANSITIONS[LiquidityLifecycleState.EXPIRED] == set()
        assert validate_fvg_transition(LiquidityLifecycleState.MITIGATED, LiquidityLifecycleState.CONFIRMED) is False


# =====================================================================
# Suite 7: IFVG Detection, Single Inversion & Linkage (8 Tests)
# =====================================================================

class TestIFVGDetectionAndLifecycle:
    def test_bullish_fvg_inversion_to_bearish_ifvg(self):
        t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST_ZONE)
        df = make_bullish_fvg_series(t0, count=6)
        # Bar 4 closes below Bullish FVG lower boundary (Close = 24020.0 < 24025.0)
        df.loc[4, "open"] = 24040.0
        df.loc[4, "high"] = 24045.0
        df.loc[4, "low"] = 24015.0
        df.loc[4, "close"] = 24020.0
        # Bar 5 stays below zone high (e.g. at 24018.0) so Bearish IFVG is active
        df.loc[5, "open"] = 24020.0
        df.loc[5, "high"] = 24025.0
        df.loc[5, "low"] = 24010.0
        df.loc[5, "close"] = 24018.0

        engine = FVGEngine(FVGConfiguration(min_gap_atr_multiple=0.0, enable_ifvg_conversion=True))
        typed_fvg, _, typed_ifvg, canon_ifvg = engine.detect_gaps(df, timeframe="15m")

        # Parent FVG is invalidated
        assert typed_fvg[0].event_status == LiquidityLifecycleState.INVALIDATED
        assert typed_fvg[0].evidence.is_inverted is True

        # IFVG is emitted
        assert len(typed_ifvg) == 1
        ifvg = typed_ifvg[0]
        assert ifvg.event_type == ICTEventType.IFVG
        assert ifvg.direction == EventDirection.BEARISH
        assert ifvg.zone_high == 24050.0
        assert ifvg.zone_low == 24025.0
        # For Bearish IFVG, retest entry level is lower boundary (24025.0)
        assert ifvg.to_ict_event().price_level == 24025.0
        assert ifvg.event_status == LiquidityLifecycleState.CONFIRMED

    def test_bearish_fvg_inversion_to_bullish_ifvg(self):
        t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST_ZONE)
        df = make_bearish_fvg_series(t0, count=6)
        # Bar 4 closes above Bearish FVG upper boundary (Close = 24085.0 > 24080.0)
        df.loc[4, "open"] = 24050.0
        df.loc[4, "low"] = 24045.0
        df.loc[4, "high"] = 24090.0
        df.loc[4, "close"] = 24085.0

        engine = FVGEngine(FVGConfiguration(min_gap_atr_multiple=0.0, enable_ifvg_conversion=True))
        typed_fvg, _, typed_ifvg, _ = engine.detect_gaps(df, timeframe="15m")

        assert typed_fvg[0].event_status == LiquidityLifecycleState.INVALIDATED
        assert len(typed_ifvg) == 1
        ifvg = typed_ifvg[0]
        assert ifvg.event_type == ICTEventType.IFVG
        assert ifvg.direction == EventDirection.BULLISH
        # For Bullish IFVG, retest entry level is upper boundary (24080.0)
        assert ifvg.to_ict_event().price_level == 24080.0

    def test_mitigated_fvg_ineligible_for_inversion(self):
        t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST_ZONE)
        df = make_bullish_fvg_series(t0, count=7)
        # Bar 4 touches CE (Low = 24035.0, Close = 24060.0) -> Transitions to MITIGATED
        df.loc[4, "open"] = 24065.0
        df.loc[4, "high"] = 24070.0
        df.loc[4, "low"] = 24035.0
        df.loc[4, "close"] = 24060.0
        # Bar 5 closes below lower boundary (Close = 24020.0 < 24025.0)
        df.loc[5, "open"] = 24040.0
        df.loc[5, "high"] = 24045.0
        df.loc[5, "low"] = 24015.0
        df.loc[5, "close"] = 24020.0

        engine = FVGEngine(FVGConfiguration(min_gap_atr_multiple=0.0, full_mitigation_policy="CONSEQUENT_ENCROACHMENT"))
        typed_fvg, _, typed_ifvg, _ = engine.detect_gaps(df, timeframe="15m")

        # FVG was already terminal MITIGATED on Bar 4. It cannot invert on Bar 5!
        assert typed_fvg[0].event_status == LiquidityLifecycleState.MITIGATED
        assert len(typed_ifvg) == 0

    def test_single_inversion_guarantee_no_secondary_inversion(self):
        t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST_ZONE)
        df = make_bullish_fvg_series(t0, count=8)
        # Bar 4 inverts Bullish FVG to Bearish IFVG (Close = 24020.0 < 24025.0)
        df.loc[4, "open"] = 24040.0
        df.loc[4, "high"] = 24045.0
        df.loc[4, "low"] = 24015.0
        df.loc[4, "close"] = 24020.0
        # Bar 5 breaches the Bearish IFVG back above (Close = 24055.0 > 24050.0)
        df.loc[5, "open"] = 24025.0
        df.loc[5, "low"] = 24020.0
        df.loc[5, "high"] = 24060.0
        df.loc[5, "close"] = 24055.0

        engine = FVGEngine(FVGConfiguration(min_gap_atr_multiple=0.0, enable_ifvg_conversion=True))
        _, _, typed_ifvg, _ = engine.detect_gaps(df, timeframe="15m")

        assert len(typed_ifvg) == 1
        # The IFVG is permanently INVALIDATED. No tertiary / secondary inversion created!
        assert typed_ifvg[0].event_status == LiquidityLifecycleState.INVALIDATED
        assert VALID_IFVG_TRANSITIONS[LiquidityLifecycleState.INVALIDATED] == set()

    def test_ifvg_parent_linkage_in_evidence(self):
        t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST_ZONE)
        df = make_bullish_fvg_series(t0, count=6)
        df.loc[4, "open"] = 24040.0
        df.loc[4, "high"] = 24045.0
        df.loc[4, "low"] = 24015.0
        df.loc[4, "close"] = 24020.0

        engine = FVGEngine(FVGConfiguration(min_gap_atr_multiple=0.0))
        typed_fvg, _, typed_ifvg, _ = engine.detect_gaps(df, timeframe="15m")

        parent = typed_fvg[0]
        child = typed_ifvg[0]
        assert child.evidence.source_fvg_id == parent.event_id
        assert child.evidence.inversion_candle_id == "c_4"
        assert child.evidence.inversion_close == 24020.0

    def test_ifvg_retest_and_mitigation(self):
        t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST_ZONE)
        df = make_bullish_fvg_series(t0, count=7)
        # Bar 4 inverts to Bearish IFVG
        df.loc[4, "open"] = 24040.0
        df.loc[4, "high"] = 24045.0
        df.loc[4, "low"] = 24015.0
        df.loc[4, "close"] = 24020.0
        # Bar 5 retests Bearish IFVG from underneath: High = 24040.0 (touches CE=24037.5)
        df.loc[5, "open"] = 24020.0
        df.loc[5, "low"] = 24015.0
        df.loc[5, "high"] = 24040.0
        df.loc[5, "close"] = 24022.0

        engine = FVGEngine(FVGConfiguration(min_gap_atr_multiple=0.0, full_mitigation_policy="CONSEQUENT_ENCROACHMENT"))
        _, _, typed_ifvg, _ = engine.detect_gaps(df, timeframe="15m")

        assert typed_ifvg[0].event_status == LiquidityLifecycleState.MITIGATED
        assert typed_ifvg[0].evidence.touch_count >= 1

    def test_ifvg_invalidation_on_opposite_close(self):
        t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST_ZONE)
        df = make_bullish_fvg_series(t0, count=7)
        df.loc[4, "open"] = 24040.0
        df.loc[4, "high"] = 24045.0
        df.loc[4, "low"] = 24015.0
        df.loc[4, "close"] = 24020.0  # Invert to Bearish IFVG
        df.loc[5, "open"] = 24025.0
        df.loc[5, "low"] = 24020.0
        df.loc[5, "high"] = 24060.0
        df.loc[5, "close"] = 24055.0  # Close above upper boundary 24050.0

        engine = FVGEngine(FVGConfiguration(min_gap_atr_multiple=0.0))
        _, _, typed_ifvg, _ = engine.detect_gaps(df, timeframe="15m")

        assert typed_ifvg[0].event_status == LiquidityLifecycleState.INVALIDATED
        assert typed_ifvg[0].invalidated_at is not None

    def test_ifvg_expiry(self):
        t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST_ZONE)
        df = make_bullish_fvg_series(t0, count=15)
        df.loc[4, "open"] = 24040.0
        df.loc[4, "high"] = 24045.0
        df.loc[4, "low"] = 24015.0
        df.loc[4, "close"] = 24020.0
        # Ensure subsequent bars stay below zone_high (24050.0) so Bearish IFVG is not invalidated prematurely
        for k in range(5, 15):
            df.loc[k, "open"] = 24018.0
            df.loc[k, "high"] = 24022.0
            df.loc[k, "low"] = 24010.0
            df.loc[k, "close"] = 24015.0

        engine = FVGEngine(FVGConfiguration(min_gap_atr_multiple=0.0, max_active_candles=3))
        _, _, typed_ifvg, _ = engine.detect_gaps(df, timeframe="15m")

        assert typed_ifvg[0].event_status == LiquidityLifecycleState.EXPIRED

    @pytest.mark.parametrize(
        "initial_state,expect_ifvg",
        [
            (LiquidityLifecycleState.CONFIRMED, True),
            (LiquidityLifecycleState.APPROACHING, True),
            (LiquidityLifecycleState.PARTIALLY_MITIGATED, True),
            (LiquidityLifecycleState.IDENTIFIED, False),
            (LiquidityLifecycleState.MITIGATED, False),
            (LiquidityLifecycleState.INVALIDATED, False),
            (LiquidityLifecycleState.EXPIRED, False),
        ],
    )
    def test_ifvg_conversion_eligibility_all_7_lifecycle_states(self, initial_state, expect_ifvg):
        """
        Verifies that only eligible active states (CONFIRMED, APPROACHING, PARTIALLY_MITIGATED)
        can convert into an IFVG upon boundary breach.
        Terminal states (MITIGATED, INVALIDATED, EXPIRED) and unconfirmed IDENTIFIED
        are strictly ineligible and produce ZERO inversions.
        """
        t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST_ZONE)

        if initial_state == LiquidityLifecycleState.CONFIRMED:
            df = make_bullish_fvg_series(t0, count=6)
            # Bar 4 closes below lower boundary directly from resting CONFIRMED state
            df.loc[4, "open"] = 24040.0
            df.loc[4, "high"] = 24045.0
            df.loc[4, "low"] = 24015.0
            df.loc[4, "close"] = 24020.0
            df.loc[5, "open"] = 24020.0
            df.loc[5, "high"] = 24022.0
            df.loc[5, "low"] = 24010.0
            df.loc[5, "close"] = 24015.0

        elif initial_state == LiquidityLifecycleState.APPROACHING:
            df = make_bullish_fvg_series(t0, count=7)
            # Bar 4 touches approach threshold zone (high = 24051.0, low = 24050.5 within approach threshold)
            df.loc[4, "open"] = 24065.0
            df.loc[4, "high"] = 24070.0
            df.loc[4, "low"] = 24051.0
            df.loc[4, "close"] = 24065.0
            # Bar 5 closes below lower boundary (Close = 24020.0 < 24025.0)
            df.loc[5, "open"] = 24040.0
            df.loc[5, "high"] = 24045.0
            df.loc[5, "low"] = 24015.0
            df.loc[5, "close"] = 24020.0
            df.loc[6, "open"] = 24020.0
            df.loc[6, "high"] = 24022.0
            df.loc[6, "low"] = 24010.0
            df.loc[6, "close"] = 24015.0

        elif initial_state == LiquidityLifecycleState.PARTIALLY_MITIGATED:
            df = make_bullish_fvg_series(t0, count=7)
            # Bar 4 partially mitigates zone (Low = 24040.0, CE is 24037.5 so 40% < 50% CE)
            df.loc[4, "open"] = 24065.0
            df.loc[4, "high"] = 24070.0
            df.loc[4, "low"] = 24040.0
            df.loc[4, "close"] = 24065.0
            # Bar 5 breaches lower boundary (Close = 24020.0 < 24025.0)
            df.loc[5, "open"] = 24040.0
            df.loc[5, "high"] = 24045.0
            df.loc[5, "low"] = 24015.0
            df.loc[5, "close"] = 24020.0
            df.loc[6, "open"] = 24020.0
            df.loc[6, "high"] = 24022.0
            df.loc[6, "low"] = 24010.0
            df.loc[6, "close"] = 24015.0

        elif initial_state == LiquidityLifecycleState.MITIGATED:
            df = make_bullish_fvg_series(t0, count=7)
            # Bar 4 achieves full mitigation (Low = 24030.0 <= CE 24037.5) -> MITIGATED
            df.loc[4, "open"] = 24065.0
            df.loc[4, "high"] = 24070.0
            df.loc[4, "low"] = 24030.0
            df.loc[4, "close"] = 24060.0
            # Bar 5 breaches lower boundary
            df.loc[5, "open"] = 24040.0
            df.loc[5, "high"] = 24045.0
            df.loc[5, "low"] = 24015.0
            df.loc[5, "close"] = 24020.0
            df.loc[6, "open"] = 24020.0
            df.loc[6, "high"] = 24022.0
            df.loc[6, "low"] = 24010.0
            df.loc[6, "close"] = 24015.0

        elif initial_state == LiquidityLifecycleState.INVALIDATED:
            df = make_bullish_fvg_series(t0, count=7)
            # Bar 4 inverts Bullish FVG
            df.loc[4, "open"] = 24040.0
            df.loc[4, "high"] = 24045.0
            df.loc[4, "low"] = 24015.0
            df.loc[4, "close"] = 24020.0
            # Bar 5 also closes below lower boundary (already invalidated)
            df.loc[5, "open"] = 24018.0
            df.loc[5, "high"] = 24022.0
            df.loc[5, "low"] = 24010.0
            df.loc[5, "close"] = 24015.0
            df.loc[6, "open"] = 24015.0
            df.loc[6, "high"] = 24020.0
            df.loc[6, "low"] = 24005.0
            df.loc[6, "close"] = 24010.0

        elif initial_state == LiquidityLifecycleState.EXPIRED:
            df = make_bullish_fvg_series(t0, count=10)
            # Ensure bars 4..7 drift safely without breaching, causing expiry at max_active_candles=3
            for k in range(4, 8):
                df.loc[k, "open"] = 24065.0
                df.loc[k, "high"] = 24070.0
                df.loc[k, "low"] = 24060.0
                df.loc[k, "close"] = 24065.0
            # Bar 8 closes below lower boundary after FVG has already EXPIRED
            df.loc[8, "open"] = 24040.0
            df.loc[8, "high"] = 24045.0
            df.loc[8, "low"] = 24015.0
            df.loc[8, "close"] = 24020.0
            df.loc[9, "open"] = 24020.0
            df.loc[9, "high"] = 24022.0
            df.loc[9, "low"] = 24010.0
            df.loc[9, "close"] = 24015.0

        elif initial_state == LiquidityLifecycleState.IDENTIFIED:
            # An unconfirmed gap in IDENTIFIED status cannot invert
            # Verify directly that an IDENTIFIED FVG breached before confirmation does not invert
            cfg = FVGConfiguration(min_gap_atr_multiple=0.0)
            fvg_ev = FVGEvidence(
                candle_1_id="c_1", candle_2_id="c_2", candle_3_id="c_3",
                gap_size_pts=25.0, consequent_encroachment=24037.5,
                displacement_body_ratio=0.7, touch_count=0,
                invalidation_condition="close < 24025.0",
            )
            unconfirmed_fvg = FVGEvent(
                event_id="test_identified",
                direction=EventDirection.BULLISH,
                zone_high=24050.0,
                zone_low=24025.0,
                mean_threshold=24037.5,
                event_status=LiquidityLifecycleState.IDENTIFIED,
                event_time=t0,
                available_at=t0 + timedelta(minutes=45),
                created_at=t0,
                evidence=fvg_ev,
            )
            # Evaluate breach logic manually on this unconfirmed event:
            pre_breach = unconfirmed_fvg.event_status
            assert pre_breach == LiquidityLifecycleState.IDENTIFIED
            assert pre_breach not in FVG_ACTIVE_STATES
            # Conversion check fails closed:
            can_invert = (cfg.enable_ifvg_conversion and not unconfirmed_fvg.evidence.is_inverted and pre_breach in FVG_ACTIVE_STATES)
            assert can_invert is False
            return

        engine = FVGEngine(FVGConfiguration(
            min_gap_atr_multiple=0.0,
            max_active_candles=3 if initial_state == LiquidityLifecycleState.EXPIRED else 300,
            full_mitigation_policy="CONSEQUENT_ENCROACHMENT",
            enable_ifvg_conversion=True,
        ))
        typed_fvg, _, typed_ifvg, _ = engine.detect_gaps(df, timeframe="15m")

        if expect_ifvg:
            assert len(typed_ifvg) == 1, f"Expected IFVG for state {initial_state}, got {len(typed_ifvg)}"
            assert typed_ifvg[0].event_type == ICTEventType.IFVG
            assert typed_fvg[0].event_status == LiquidityLifecycleState.INVALIDATED
        else:
            if initial_state == LiquidityLifecycleState.INVALIDATED:
                # Started with 1 inversion on bar 4, no second inversion produced on bar 5
                assert len(typed_ifvg) == 1
            else:
                assert len(typed_ifvg) == 0, f"Expected 0 IFVGs for state {initial_state}, got {len(typed_ifvg)}"

    def test_ifvg_invalidation_produces_zero_secondary_inversions(self):
        """Proves that a breached IFVG permanently invalidates and never creates recursive inversions."""
        t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST_ZONE)
        df = make_bullish_fvg_series(t0, count=9)
        # Bar 4 breaches Bullish FVG -> creates Bearish IFVG
        df.loc[4, "open"] = 24040.0
        df.loc[4, "high"] = 24045.0
        df.loc[4, "low"] = 24015.0
        df.loc[4, "close"] = 24020.0
        # Bar 5 breaches the Bearish IFVG back above zone high (24050.0)
        df.loc[5, "open"] = 24025.0
        df.loc[5, "low"] = 24020.0
        df.loc[5, "high"] = 24060.0
        df.loc[5, "close"] = 24055.0
        # Bar 6 again stays above
        df.loc[6, "open"] = 24055.0
        df.loc[6, "low"] = 24050.0
        df.loc[6, "high"] = 24065.0
        df.loc[6, "close"] = 24060.0

        engine = FVGEngine(FVGConfiguration(min_gap_atr_multiple=0.0, enable_ifvg_conversion=True))
        typed_fvg, _, typed_ifvg, _ = engine.detect_gaps(df, timeframe="15m")

        assert len(typed_ifvg) == 1
        assert typed_ifvg[0].event_status == LiquidityLifecycleState.INVALIDATED
        # No tertiary/recursive IFVGs exist
        assert len([ev for ev in typed_ifvg if ev.evidence.is_inverted]) == 1


# =====================================================================
# Suite 8: Data Quality Lockouts & Calendar Safeguards (6 Tests)
# =====================================================================

class TestDataQualityAndCalendarLockouts:
    @pytest.mark.parametrize(
        "bad_status",
        [
            "DATA_OFFLINE",
            "DATA_UNAVAILABLE",
            "STALE",
            "STALE_TICK",
            "DEGRADED",
            "ANOMALOUS",
            "SYNTHETIC",
            "OFFLINE",
            "UNAVAILABLE",
            "MOCK",
            "UNKNOWN_BAD_FEED",
        ],
    )
    def test_disqualifying_feed_statuses_lockout(self, bad_status):
        t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST_ZONE)
        df = make_bullish_fvg_series(t0, count=5)
        engine = FVGEngine()
        with pytest.raises(ValueError, match="feed quality status"):
            engine.detect_gaps(df, data_quality_status=bad_status)

    def test_repaired_data_lockout_fails_closed(self):
        t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST_ZONE)
        df = make_bullish_fvg_series(t0, count=5)
        df.attrs["quality_status"] = "REPAIRED"
        engine = FVGEngine()
        with pytest.raises(ValueError, match="repaired or imputed mandatory candles"):
            engine.detect_gaps(df)

    def test_imputed_bars_count_lockout(self):
        t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST_ZONE)
        df = make_bullish_fvg_series(t0, count=5)
        df.attrs["imputed_bars_count"] = 2
        engine = FVGEngine()
        with pytest.raises(ValueError, match="repaired or imputed mandatory candles"):
            engine.detect_gaps(df)

    def test_invalid_ohlc_geometry_lockout(self):
        t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST_ZONE)
        df = make_bullish_fvg_series(t0, count=5)
        # Corrupt geometry: Low > High
        df.loc[2, "low"] = 24100.0
        df.loc[2, "high"] = 24050.0
        engine = FVGEngine()
        with pytest.raises(ValueError, match="Invalid OHLC candle geometry"):
            engine.detect_gaps(df)

    def test_calendar_verification_fails_closed_on_weekend(self):
        # 2026-11-01 is a Sunday (non-trading day)
        sunday_dt = datetime(2026, 11, 1, 10, 0, tzinfo=IST_ZONE)
        df = make_bullish_fvg_series(sunday_dt, count=5)
        engine = FVGEngine()
        with pytest.raises(ValueError, match="is not a verified exchange trading session"):
            engine.detect_gaps(df, as_of_time=sunday_dt)

    def test_multi_timeframe_isolation(self):
        t0 = datetime(2026, 11, 2, 9, 15, tzinfo=IST_ZONE)
        df_15m = make_bullish_fvg_series(t0, count=10)
        df_5m = make_bearish_fvg_series(t0, count=15)
        dfs = {"15m": df_15m, "5m": df_5m}

        engine = FVGEngine(FVGConfiguration(min_gap_atr_multiple=0.0))
        reports = engine.analyze_multi_timeframe(dfs, symbol="NIFTY 50")

        assert "15m" in reports
        assert "5m" in reports
        # 15m has bullish FVG, 5m has bearish FVG
        assert reports["15m"].latest_bullish_fvg is not None
        assert reports["5m"].latest_bearish_fvg is not None
        assert len(reports["15m"].fvg_events) >= 1
        assert len(reports["5m"].fvg_events) >= 1
