"""
AIVOLVE Phase 3 Step 3.6 — Automated Verification Suite.
Session Intelligence Engine (`Asia/Kolkata`, `PAPER_TRADING_ONLY`).

Covers all 19 mandatory Step 3.6 validation categories plus defensive type,
SENSEX governance, non-repainting causal replay, and no-calibration checks:
1. Every configured session boundary (Opening, Morning, Midday, Afternoon, Closing)
2. Correct IST timezone handling (UTC conversion, naive/mixed/malformed rejection)
3. Opening range creation and completion
4. Opening range breakout, breakdown, and retest
5. Session high/low updates & range expansion
6. Previous session high/low, breach & reclaim
7. Session transitions (Opening->Morning->Midday->Afternoon->Closing)
8. Missing candle intervals (explicit detection, never interpolated)
9. Invalid OHLC data (fail-closed)
10. Incomplete candle rejection (forming, False/None/NaN flag, 15:15 cap)
11. Weekend and holiday handling + calendar uncertainty fail-closed
12. Historical replay determinism & non-repainting
13. No-lookahead validation
14. Event ID determinism & config fingerprint sensitivity
15. Duplicate event prevention
16. Data-quality fail-closed behavior & index/SENSEX governance
17. Integration with existing Step 3.1 LiquidityPool / LiquidityEvent
18. Configurable session windows & Kill Zone research-only constraints
19. Multi-timeframe session observations & PAPER_TRADING_ONLY / UNAVAILABLE gates
"""

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from app.data import market_calendar as mc_module
from app.options.ict_smc import (
    EventDirection,
    ICTEvent,
    ICTEventType,
    KillZoneConfig,
    LiquidityEvent,
    LiquidityLifecycleState,
    LiquidityPool,
    LiquidityType,
    MissingCandleInterval,
    MultiTimeframeSessionSummary,
    OpeningRangeStatus,
    SessionClassification,
    SessionConfiguration,
    SessionEvent,
    SessionEventKind,
    SessionIntelligenceEngine,
    SessionPhaseStatus,
    SessionWindowConfig,
    TimeframeSessionReport,
    compute_candle_close_ist,
)


IST = ZoneInfo("Asia/Kolkata")
UTC = timezone.utc


# ============================================================================
# Isolated Synthetic Test Fixture Builders (Zero Production Persistence)
# ============================================================================

def ist_dt(
    hour: int,
    minute: int,
    second: int = 0,
    day: int = 11,
    month: int = 11,
    year: int = 2026,
) -> datetime:
    """Builds an IST-aware datetime on a verified 2026 trading date (default 2026-11-11 Wed)."""
    return datetime(year, month, day, hour, minute, second, tzinfo=IST)


def make_bar(
    ts: datetime,
    open_p: float,
    high_p: float,
    low_p: float,
    close_p: float,
    candle_id: Optional[str] = None,
    is_complete: Optional[bool] = True,
    include_flag_col: bool = True,
) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "timestamp": ts,
        "open": open_p,
        "high": high_p,
        "low": low_p,
        "close": close_p,
        "volume": 10000.0,
        "candle_id": candle_id or f"c_{ts.astimezone(IST).strftime('%Y%m%d_%H%M')}",
    }
    if include_flag_col:
        row["is_complete"] = is_complete
    return row


def make_full_day_5m_bars(
    trading_day: int = 11,
    base_price: float = 24800.0,
    start_hhmm: Tuple[int, int] = (9, 15),
    end_hhmm: Tuple[int, int] = (15, 30),
    skip_hhmm: Optional[set] = None,
    include_flag_col: bool = True,
) -> pd.DataFrame:
    """
    Generates deterministic well-formed 5m bars across a 2026 trading session [start, end).
    Default range spans Opening (09:15-09:45), Morning (09:45-11:30), Midday (11:30-13:30),
    Afternoon (13:30-14:45), Closing (14:45-15:30).
    """
    skip_hhmm = skip_hhmm or set()
    rows: List[Dict[str, Any]] = []
    cur = datetime(2026, 11, trading_day, start_hhmm[0], start_hhmm[1], tzinfo=IST)
    stop = datetime(2026, 11, trading_day, end_hhmm[0], end_hhmm[1], tzinfo=IST)
    idx = 0
    while cur < stop:
        hm = (cur.hour, cur.minute)
        if hm not in skip_hhmm:
            o = base_price + (idx % 5) * 2.0
            c = o + (3.0 if idx % 2 == 0 else -1.5)
            h = max(o, c) + 4.0
            l = min(o, c) - 4.0
            rows.append(
                make_bar(
                    ts=cur,
                    open_p=o,
                    high_p=h,
                    low_p=l,
                    close_p=c,
                    include_flag_col=include_flag_col,
                )
            )
        idx += 1
        cur += timedelta(minutes=5)
    df = pd.DataFrame(rows)
    df.attrs["timeframe"] = "5m"
    return df


# ============================================================================
# 1. Every Configured Session Boundary & Zero Overlap
# ============================================================================

class TestSessionBoundaries:
    def test_exact_research_session_windows_non_overlapping(self):
        engine = SessionIntelligenceEngine()
        boundary_expectations = [
            (ist_dt(9, 14, 59), None),
            (ist_dt(9, 15, 0), "OPENING"),
            (ist_dt(9, 44, 59), "OPENING"),
            (ist_dt(9, 45, 0), "MORNING"),
            (ist_dt(11, 29, 59), "MORNING"),
            (ist_dt(11, 30, 0), "MIDDAY"),
            (ist_dt(13, 29, 59), "MIDDAY"),
            (ist_dt(13, 30, 0), "AFTERNOON"),
            (ist_dt(14, 44, 59), "AFTERNOON"),
            (ist_dt(14, 45, 0), "CLOSING"),
            (ist_dt(15, 29, 59), "CLOSING"),
            (ist_dt(15, 30, 0), None),
        ]
        for ts, expected_id in boundary_expectations:
            win = engine.classify_timestamp(ts)
            actual_id = win.session_id if win is not None else None
            assert actual_id == expected_id, f"At {ts.isoformat()}, expected {expected_id}, got {actual_id}"

    def test_classification_returns_required_fields_for_each_session(self):
        engine = SessionIntelligenceEngine()
        df = make_full_day_5m_bars(trading_day=11)
        probes = [
            (ist_dt(9, 40), "OPENING", "Opening", 9, 15, 9, 45),
            (ist_dt(11, 0), "MORNING", "Morning", 9, 45, 11, 30),
            (ist_dt(12, 30), "MIDDAY", "Midday", 11, 30, 13, 30),
            (ist_dt(14, 15), "AFTERNOON", "Afternoon", 13, 30, 14, 45),
            (ist_dt(15, 20), "CLOSING", "Closing", 14, 45, 15, 30),
        ]
        for as_of, exp_id, exp_name, sh, sm, eh, em in probes:
            rep = engine.evaluate_session(df, symbol="NIFTY 50", timeframe="5m", as_of_time=as_of)
            assert rep.is_valid is True
            cls = rep.current_session
            assert isinstance(cls, SessionClassification)
            assert cls.session_id == exp_id
            assert cls.session_name == exp_name
            assert cls.session_start == ist_dt(sh, sm)
            assert cls.session_end == ist_dt(eh, em)
            assert cls.current_session_status == SessionPhaseStatus.ACTIVE
            assert cls.timeframe == "5m"
            assert cls.trading_date == "2026-11-11"
            assert cls.timezone == "Asia/Kolkata"


# ============================================================================
# 2. Correct IST Timezone Handling
# ============================================================================

class TestISTTimezoneHandling:
    def test_utc_inputs_convert_equivalently_to_ist(self):
        engine = SessionIntelligenceEngine()
        df_ist = make_full_day_5m_bars(trading_day=11, end_hhmm=(10, 0))
        df_utc = df_ist.copy()
        df_utc["timestamp"] = [ts.astimezone(UTC) for ts in df_utc["timestamp"]]

        rep_ist = engine.evaluate_session(df_ist, symbol="NIFTY 50", timeframe="5m", as_of_time=ist_dt(10, 0))
        rep_utc = engine.evaluate_session(
            df_utc,
            symbol="NIFTY 50",
            timeframe="5m",
            as_of_time=ist_dt(10, 0).astimezone(UTC),
        )
        assert rep_utc.is_valid is True
        assert rep_utc.timezone == "Asia/Kolkata"
        assert rep_utc.current_session == rep_ist.current_session
        assert rep_utc.opening_range == rep_ist.opening_range
        assert [e.event_id for e in rep_utc.events] == [e.event_id for e in rep_ist.events]

    def test_naive_and_mixed_timezone_candles_fail_closed(self):
        engine = SessionIntelligenceEngine()
        df_naive = pd.DataFrame([
            make_bar(datetime(2026, 11, 11, 9, 15), 24800.0, 24810.0, 24795.0, 24805.0),
        ])
        rep_naive = engine.evaluate_session(df_naive, as_of_time=ist_dt(9, 30))
        assert rep_naive.is_valid is False
        assert rep_naive.data_quality == "INVALID_DATA"
        assert rep_naive.events == ()

        df_mixed = pd.DataFrame([
            make_bar(ist_dt(9, 15), 24800.0, 24810.0, 24795.0, 24805.0),
            make_bar(ist_dt(9, 20).astimezone(UTC), 24805.0, 24812.0, 24800.0, 24810.0),
        ])
        rep_mixed = engine.evaluate_session(df_mixed, as_of_time=ist_dt(9, 30))
        assert rep_mixed.is_valid is False
        assert any("Mixed timezones" in r for r in rep_mixed.rejection_reasons)

        with pytest.raises(ValueError, match="timezone-aware"):
            engine.evaluate_session(df_mixed, as_of_time=datetime(2026, 11, 11, 9, 30))


# ============================================================================
# 3 & 4. Opening Range Creation, Completion, Breakout, Breakdown & Retest
# ============================================================================

class TestOpeningRangeIntelligence:
    def test_opening_range_remains_unavailable_until_configured_completion(self):
        engine = SessionIntelligenceEngine()
        df = make_full_day_5m_bars(trading_day=11, end_hhmm=(10, 0))

        # At 09:40 (only 09:15..09:35 completed; 09:40 still forming) -> NOT complete
        rep_forming = engine.evaluate_session(df, timeframe="5m", as_of_time=ist_dt(9, 40))
        assert rep_forming.is_valid is True
        assert rep_forming.opening_range is not None
        assert rep_forming.opening_range.is_complete is False
        assert rep_forming.opening_range.status == OpeningRangeStatus.FORMING
        assert rep_forming.opening_range.opening_range_high is None
        assert rep_forming.opening_range.opening_range_low is None
        assert not any(
            e.session_event_kind == SessionEventKind.OPENING_RANGE_COMPLETE
            for e in rep_forming.events
        )

        # At 09:45 (09:40->09:45 bar closes) -> COMPLETE
        rep_done = engine.evaluate_session(df, timeframe="5m", as_of_time=ist_dt(9, 45))
        assert rep_done.opening_range is not None
        assert rep_done.opening_range.is_complete is True
        assert rep_done.opening_range.status == OpeningRangeStatus.COMPLETE
        assert rep_done.opening_range.available_at == ist_dt(9, 45)
        assert rep_done.opening_range.opening_range_high is not None
        assert rep_done.opening_range.opening_range_low is not None
        or_events = [
            e for e in rep_done.events
            if e.session_event_kind == SessionEventKind.OPENING_RANGE_COMPLETE
        ]
        assert len(or_events) == 1
        assert or_events[0].available_at == ist_dt(9, 45)

    def test_configurable_opening_range_duration_15m(self):
        cfg = SessionConfiguration(opening_range_duration_minutes=15)
        engine = SessionIntelligenceEngine(config=cfg)
        df = make_full_day_5m_bars(trading_day=11, end_hhmm=(10, 0))

        rep_0925 = engine.evaluate_session(df, timeframe="5m", as_of_time=ist_dt(9, 25))
        assert rep_0925.opening_range.is_complete is False

        rep_0930 = engine.evaluate_session(df, timeframe="5m", as_of_time=ist_dt(9, 30))
        assert rep_0930.opening_range.is_complete is True
        assert rep_0930.opening_range.duration_minutes == 15
        assert rep_0930.opening_range.window_end == ist_dt(9, 30)

    def test_opening_range_breakout_breakdown_and_retest(self):
        engine = SessionIntelligenceEngine(
            config=SessionConfiguration(retest_tolerance_pts=3.0)
        )
        # Opening range bars 09:15..09:40 stay strictly inside [24790, 24820]
        rows = [
            make_bar(ist_dt(9, 15), 24800.0, 24820.0, 24795.0, 24810.0, "c1"),
            make_bar(ist_dt(9, 20), 24810.0, 24818.0, 24790.0, 24805.0, "c2"),
            make_bar(ist_dt(9, 25), 24805.0, 24815.0, 24798.0, 24808.0, "c3"),
            make_bar(ist_dt(9, 30), 24808.0, 24816.0, 24792.0, 24802.0, "c4"),
            make_bar(ist_dt(9, 35), 24802.0, 24812.0, 24796.0, 24806.0, "c5"),
            make_bar(ist_dt(9, 40), 24806.0, 24814.0, 24799.0, 24810.0, "c6"),
            # Breakout above 24820 at 09:45 (closes 09:50)
            make_bar(ist_dt(9, 45), 24810.0, 24840.0, 24808.0, 24835.0, "c7"),
            # Retest of 24820 at 09:50 (low touches 24821, closes 24832)
            make_bar(ist_dt(9, 50), 24835.0, 24838.0, 24821.0, 24832.0, "c8"),
            # Later reversal breakdown below 24790 at 09:55 (closes 10:00)
            make_bar(ist_dt(9, 55), 24832.0, 24833.0, 24775.0, 24780.0, "c9"),
        ]
        df = pd.DataFrame(rows)

        # Incomplete breakout candle c7 at 09:48 must NOT confirm breakout!
        rep_incomplete = engine.evaluate_session(df, timeframe="5m", as_of_time=ist_dt(9, 48))
        assert rep_incomplete.opening_range.breakout_above_detected is False
        assert rep_incomplete.incomplete_candles_excluded == 1

        # After full sequence at 10:00 -> breakout, retest, and breakdown confirmed
        rep = engine.evaluate_session(df, timeframe="5m", as_of_time=ist_dt(10, 0))
        or_state = rep.opening_range
        assert or_state.opening_range_high == 24820.0
        assert or_state.opening_range_low == 24790.0
        assert or_state.breakout_above_detected is True
        assert or_state.breakout_time == ist_dt(9, 50)
        assert or_state.retest_observed is True
        assert or_state.retest_direction == EventDirection.BULLISH
        assert or_state.retest_time == ist_dt(9, 55)
        assert or_state.breakdown_below_detected is True
        assert or_state.breakdown_time == ist_dt(10, 0)

        kinds = [e.session_event_kind for e in rep.events]
        assert SessionEventKind.OPENING_RANGE_BREAKOUT in kinds
        assert SessionEventKind.OPENING_RANGE_RETEST in kinds
        assert SessionEventKind.OPENING_RANGE_BREAKDOWN in kinds


# ============================================================================
# 5, 6 & 7. Session High/Low, Previous Session, Breach/Reclaim & Transitions
# ============================================================================

class TestSessionHighLowAndTransitions:
    def test_session_ranges_expansion_previous_breach_reclaim_and_transitions(self):
        engine = SessionIntelligenceEngine()
        rows = [
            # Opening 09:15..09:40 -> High=24830, Low=24780 (range 50)
            make_bar(ist_dt(9, 15), 24800.0, 24815.0, 24790.0, 24810.0, "op1"),  # initial range 25
            make_bar(ist_dt(9, 20), 24810.0, 24830.0, 24780.0, 24805.0, "op2"),  # expands to 50 (+25)
            make_bar(ist_dt(9, 40), 24805.0, 24820.0, 24795.0, 24812.0, "op3"),
            # Morning 09:45..11:25: sweeps above prev high 24830 (high 24838) and reclaims below (close 24818)
            make_bar(ist_dt(9, 45), 24812.0, 24838.0, 24810.0, 24818.0, "mo1"),
            # Morning also breaches prev low 24780 (low 24772, close 24775)
            make_bar(ist_dt(10, 15), 24818.0, 24819.0, 24772.0, 24775.0, "mo2"),
            # And next candle closes back above 24780 -> low reclaim
            make_bar(ist_dt(10, 20), 24775.0, 24792.0, 24774.0, 24788.0, "mo3"),
            # Midday 11:30
            make_bar(ist_dt(11, 30), 24788.0, 24800.0, 24782.0, 24795.0, "md1"),
            # Afternoon 13:30
            make_bar(ist_dt(13, 30), 24795.0, 24812.0, 24790.0, 24808.0, "af1"),
            # Closing 14:45
            make_bar(ist_dt(14, 45), 24808.0, 24825.0, 24802.0, 24820.0, "cl1"),
        ]
        df = pd.DataFrame(rows)
        rep = engine.evaluate_session(df, timeframe="5m", as_of_time=ist_dt(15, 0))
        assert rep.is_valid is True

        # Opening range expansion stats
        op = rep.session_ranges["OPENING"]
        assert op.session_high == 24830.0
        assert op.session_low == 24780.0
        assert op.session_range == 50.0
        assert op.initial_range == 25.0
        assert op.range_expansion_pts == 25.0
        assert op.range_expansion_pct == 100.0
        assert op.high_candle_id == "op2"
        assert op.low_candle_id == "op2"

        # Morning carries Opening as previous session + detects high & low breach & reclaim
        mo = rep.session_ranges["MORNING"]
        assert mo.previous_session_id == "OPENING"
        assert mo.previous_session_high == 24830.0
        assert mo.previous_session_low == 24780.0
        assert mo.breached_previous_high is True
        assert mo.reclaimed_previous_high is True
        assert mo.breached_previous_low is True
        assert mo.reclaimed_previous_low is True
        assert "op1" not in mo.source_candle_ids
        assert "mo1" in mo.source_candle_ids

        # All 4 adjacent transitions emitted causally
        trans_pairs = [(t.from_session_id, t.to_session_id) for t in rep.transitions]
        assert trans_pairs == [
            ("OPENING", "MORNING"),
            ("MORNING", "MIDDAY"),
            ("MIDDAY", "AFTERNOON"),
            ("AFTERNOON", "CLOSING"),
        ]
        assert all(t.is_adjacent_standard_transition for t in rep.transitions)
        assert all(t.available_at >= t.event_time for t in rep.transitions)

        # Previous session summary relative to Closing is Afternoon
        assert rep.previous_session_summary is not None
        assert rep.previous_session_summary.session_id == "AFTERNOON"


# ============================================================================
# 8. Missing Candle Intervals (Never Interpolated)
# ============================================================================

class TestMissingCandleIntervals:
    def test_missing_bars_explicitly_reported_never_fabricated(self):
        engine = SessionIntelligenceEngine()
        # Omit 09:25 and 09:50 bars
        df = make_full_day_5m_bars(
            trading_day=11,
            end_hhmm=(10, 0),
            skip_hhmm={(9, 25), (9, 50)},
        )
        rep = engine.evaluate_session(df, timeframe="5m", as_of_time=ist_dt(10, 0))
        assert rep.is_valid is True
        assert rep.has_data_gaps is True
        assert rep.completed_candles_count == 7  # 9 expected minus 2 omitted (no synthetic fill)
        missing_opens = {(m.expected_open_time.hour, m.expected_open_time.minute) for m in rep.missing_intervals}
        assert missing_opens == {(9, 25), (9, 50)}
        assert rep.opening_range.missing_or_intervals_count == 1


# ============================================================================
# 9. Invalid OHLC Data (Fail Closed)
# ============================================================================

class TestInvalidOHLCFailClosed:
    @pytest.mark.parametrize(
        "bad_row",
        [
            make_bar(ist_dt(9, 15), 24800.0, 24790.0, 24810.0, 24805.0),  # high < low
            make_bar(ist_dt(9, 15), 24820.0, 24815.0, 24795.0, 24805.0),  # high < open
            make_bar(ist_dt(9, 15), 24800.0, 24820.0, 24805.0, 24810.0),  # low > open
            make_bar(ist_dt(9, 15), -100.0, 24810.0, -110.0, 24800.0),    # negative price
            make_bar(ist_dt(9, 15), 24800.0, np.nan, 24790.0, 24805.0),   # NaN
            make_bar(ist_dt(9, 15), 24800.0, float("inf"), 24790.0, 24805.0),  # Inf
        ],
    )
    def test_invalid_ohlc_geometry_and_non_finite_values_rejected(self, bad_row):
        engine = SessionIntelligenceEngine()
        df = pd.DataFrame([bad_row])
        rep = engine.evaluate_session(df, timeframe="5m", as_of_time=ist_dt(9, 30))
        assert rep.is_valid is False
        assert rep.data_quality == "INVALID_DATA"
        assert rep.events == ()

    def test_duplicate_timestamps_and_non_monotonic_series_rejected(self):
        engine = SessionIntelligenceEngine()
        df_dup = pd.DataFrame([
            make_bar(ist_dt(9, 15), 24800.0, 24810.0, 24795.0, 24805.0, "c1"),
            make_bar(ist_dt(9, 15), 24801.0, 24812.0, 24796.0, 24806.0, "c2"),
        ])
        assert engine.evaluate_session(df_dup, as_of_time=ist_dt(9, 30)).is_valid is False

        df_rev = pd.DataFrame([
            make_bar(ist_dt(9, 20), 24800.0, 24810.0, 24795.0, 24805.0, "c1"),
            make_bar(ist_dt(9, 15), 24801.0, 24812.0, 24796.0, 24806.0, "c2"),
        ])
        assert engine.evaluate_session(df_rev, as_of_time=ist_dt(9, 30)).is_valid is False


# ============================================================================
# 10. Incomplete Candle Rejection
# ============================================================================

class TestIncompleteCandleRejection:
    def test_rejects_false_none_nan_flags_and_future_close_boundary(self):
        engine = SessionIntelligenceEngine()
        df = pd.DataFrame([
            make_bar(ist_dt(9, 15), 24800.0, 24810.0, 24795.0, 24805.0, "c1", is_complete=True),
            # Explicit False flag even though time passed -> must exclude!
            make_bar(ist_dt(9, 20), 24805.0, 25999.0, 24000.0, 25900.0, "c_false", is_complete=False),
            # Missing/None flag inside flagged feed -> must exclude!
            make_bar(ist_dt(9, 25), 24805.0, 25999.0, 24000.0, 25900.0, "c_none", is_complete=None),
            # Spoofed True flag whose close_time (09:35) > as_of_time (09:33) -> must exclude!
            make_bar(ist_dt(9, 30), 24805.0, 25999.0, 24000.0, 25900.0, "c_forming", is_complete=True),
        ])
        rep = engine.evaluate_session(df, timeframe="5m", as_of_time=ist_dt(9, 33))
        assert rep.is_valid is True
        assert rep.completed_candles_count == 1
        assert rep.incomplete_candles_excluded == 3
        assert rep.session_ranges["OPENING"].session_high == 24810.0
        assert rep.session_ranges["OPENING"].session_low == 24795.0

    def test_require_explicit_completion_flag_rejects_flagless_dataframe(self):
        engine = SessionIntelligenceEngine(
            config=SessionConfiguration(require_explicit_completion_flag=True)
        )
        df = make_full_day_5m_bars(trading_day=11, end_hhmm=(9, 45), include_flag_col=False)
        rep = engine.evaluate_session(df, timeframe="5m", as_of_time=ist_dt(9, 45))
        assert rep.completed_candles_count == 0
        assert rep.incomplete_candles_excluded == len(df)
        assert rep.opening_range.is_complete is False

    def test_1515_1h_bar_caps_close_at_1530(self):
        engine = SessionIntelligenceEngine()
        df = pd.DataFrame([
            make_bar(ist_dt(15, 15), 24800.0, 24850.0, 24790.0, 24840.0, "c_1515_1h", is_complete=True)
        ])
        assert compute_candle_close_ist(ist_dt(15, 15), "1h", datetime(2026, 11, 11, 15, 30).time()) == ist_dt(15, 30)

        rep_forming = engine.evaluate_session(df, timeframe="1h", as_of_time=ist_dt(15, 29, 59))
        assert rep_forming.completed_candles_count == 0
        assert rep_forming.incomplete_candles_excluded == 1

        rep_closed = engine.evaluate_session(df, timeframe="1h", as_of_time=ist_dt(15, 30, 0))
        assert rep_closed.completed_candles_count == 1
        assert rep_closed.current_session.session_id == "CLOSING"


# ============================================================================
# 11. Weekend, Holiday & Calendar Uncertainty Fail-Closed
# ============================================================================

class TestCalendarValidation:
    def test_weekend_and_nse_holiday_fail_closed(self):
        engine = SessionIntelligenceEngine()
        # 2026-11-14 is Saturday
        sat_df = pd.DataFrame([
            make_bar(ist_dt(9, 15, day=14), 24800.0, 24810.0, 24795.0, 24805.0)
        ])
        rep_sat = engine.evaluate_session(sat_df, as_of_time=ist_dt(10, 0, day=14))
        assert rep_sat.is_valid is False
        assert rep_sat.data_quality == "NON_TRADING_DAY"
        assert rep_sat.current_session.current_session_status == SessionPhaseStatus.NON_TRADING_DAY
        assert rep_sat.events == ()

        # 2026-11-24 is a verified NSE_HOLIDAYS entry
        assert date(2026, 11, 24) in mc_module.NSE_HOLIDAYS
        hol_df = pd.DataFrame([
            make_bar(ist_dt(9, 15, day=24), 24800.0, 24810.0, 24795.0, 24805.0)
        ])
        rep_hol = engine.evaluate_session(hol_df, as_of_time=ist_dt(10, 0, day=24))
        assert rep_hol.is_valid is False
        assert rep_hol.data_quality == "NON_TRADING_DAY"
        assert rep_hol.events == ()

    def test_out_of_coverage_year_and_broken_calendar_fail_closed(self):
        engine = SessionIntelligenceEngine()
        df_2027 = pd.DataFrame([
            make_bar(ist_dt(9, 15, day=27, month=1, year=2027), 24800.0, 24810.0, 24795.0, 24805.0)
        ])
        rep_2027 = engine.evaluate_session(df_2027, as_of_time=ist_dt(10, 0, day=27, month=1, year=2027))
        assert rep_2027.is_valid is False
        assert rep_2027.data_quality == "CALENDAR_UNAVAILABLE"

        class BrokenCalendar:
            NSE_HOLIDAYS = set()

            @staticmethod
            def is_trading_day(_dt):
                return True

        broken_engine = SessionIntelligenceEngine(calendar=BrokenCalendar())
        df = make_full_day_5m_bars(trading_day=11, end_hhmm=(9, 45))
        rep_broken = broken_engine.evaluate_session(df, as_of_time=ist_dt(9, 45))
        assert rep_broken.is_valid is False
        assert rep_broken.data_quality == "CALENDAR_UNAVAILABLE"


# ============================================================================
# 12 & 13. Historical Replay Determinism, Non-Repainting & No-Lookahead
# ============================================================================

class TestReplayAndNoLookahead:
    def test_replay_determinism_non_repainting_and_strict_no_lookahead(self):
        engine = SessionIntelligenceEngine()
        df_full = make_full_day_5m_bars(trading_day=11)
        schedule = [ist_dt(9, 30), ist_dt(9, 45), ist_dt(10, 30), ist_dt(12, 0), ist_dt(15, 30)]

        run_a = engine.replay_session(df_full, timeframe="5m", replay_times=schedule)
        run_b = engine.replay_session(df_full, timeframe="5m", replay_times=schedule)
        assert [r.model_dump() for r in run_a] == [r.model_dump() for r in run_b]

        # At 09:30: future bars must be excluded, OR incomplete, zero Morning transitions
        r_0930 = run_a[0]
        assert r_0930.future_candles_excluded > 0
        assert r_0930.opening_range.is_complete is False
        assert r_0930.opening_range.opening_range_high is None
        assert "MORNING" not in r_0930.session_ranges
        assert r_0930.transitions == ()

        # At 09:45 -> OR completes; confirm its event_id & range remain immutable through 15:30 (non-repainting)
        r_0945 = run_a[1]
        r_1530 = run_a[-1]
        assert r_0945.opening_range.opening_range_high == r_1530.opening_range.opening_range_high
        assert r_0945.opening_range.opening_range_low == r_1530.opening_range.opening_range_low

        or_id_0945 = next(
            e.event_id for e in r_0945.events if e.session_event_kind == SessionEventKind.OPENING_RANGE_COMPLETE
        )
        or_id_1530 = next(
            e.event_id for e in r_1530.events if e.session_event_kind == SessionEventKind.OPENING_RANGE_COMPLETE
        )
        assert or_id_0945 == or_id_1530

        # Strict causal timestamps on all emitted SessionEvents and converted ICTEvents
        for rep in run_a:
            for ev in rep.events:
                assert ev.available_at <= rep.as_of_time
                assert ev.available_at >= ev.event_time
                if ev.confirmed_at is not None:
                    assert ev.confirmed_at >= ev.available_at
                ict_ev = ev.to_ict_event()
                assert isinstance(ict_ev, ICTEvent)
                assert ict_ev.event_id == ev.event_id


# ============================================================================
# 14 & 15. Event ID Determinism & Duplicate Event Prevention
# ============================================================================

class TestDeterminismAndDeduplication:
    def test_event_id_determinism_and_config_sensitivity(self):
        df = make_full_day_5m_bars(trading_day=11, end_hhmm=(10, 30))
        eng1 = SessionIntelligenceEngine(config=SessionConfiguration(opening_range_duration_minutes=30))
        eng2 = SessionIntelligenceEngine(config=SessionConfiguration(opening_range_duration_minutes=30))
        eng_alt = SessionIntelligenceEngine(config=SessionConfiguration(opening_range_duration_minutes=15))

        r1 = eng1.evaluate_session(df, timeframe="5m", as_of_time=ist_dt(10, 30))
        r2 = eng2.evaluate_session(df, timeframe="5m", as_of_time=ist_dt(10, 30))
        r_alt = eng_alt.evaluate_session(df, timeframe="5m", as_of_time=ist_dt(10, 30))

        assert r1.configuration_fingerprint == r2.configuration_fingerprint
        assert r1.configuration_fingerprint != r_alt.configuration_fingerprint
        assert [e.event_id for e in r1.events] == [e.event_id for e in r2.events]
        assert set(e.event_id for e in r1.events) != set(e.event_id for e in r_alt.events)

    def test_duplicate_events_prevented_across_repeated_breaches_and_duplicate_pools(self):
        engine = SessionIntelligenceEngine()
        rows = [
            make_bar(ist_dt(9, 15), 24800.0, 24810.0, 24790.0, 24805.0, "op1"),
            # Multiple consecutive Morning candles above Opening high 24810 -> only ONE breach event
            make_bar(ist_dt(9, 45), 24805.0, 24815.0, 24804.0, 24814.0, "mo1"),
            make_bar(ist_dt(9, 50), 24814.0, 24822.0, 24812.0, 24820.0, "mo2"),
            make_bar(ist_dt(9, 55), 24820.0, 24825.0, 24815.0, 24818.0, "mo3"),
        ]
        dup_pool = LiquidityPool(
            pool_id="POOL-DUP-1",
            index="NIFTY 50",
            liquidity_type=LiquidityType.BSL,
            direction=EventDirection.BEARISH,
            timeframe="5m",
            level=24810.0,
            upper_bound=24812.0,
            lower_bound=24810.0,
            status=LiquidityLifecycleState.IDENTIFIED,
            formation_time=ist_dt(9, 20),
            available_at=ist_dt(9, 25),
            updated_at=ist_dt(9, 25),
            source_candle_identifiers=["op1"],
        )
        rep = engine.evaluate_session(
            pd.DataFrame(rows),
            timeframe="5m",
            as_of_time=ist_dt(10, 0),
            liquidity_pools=[dup_pool, dup_pool],
        )
        breaches = [e for e in rep.events if e.session_event_kind == SessionEventKind.SESSION_HIGH_BREACH]
        assert len(breaches) == 1
        assert len(rep.liquidity_observations) == 1
        event_ids = [e.event_id for e in rep.events]
        assert len(event_ids) == len(set(event_ids))


# ============================================================================
# 16. Data-Quality Fail-Closed & Index/SENSEX Governance
# ============================================================================

class TestDataQualityAndIndexGovernance:
    @pytest.mark.parametrize(
        "bad_status",
        ["DEGRADED", "STALE", "STALE_TICK", "ANOMALOUS", "DATA_OFFLINE", "DATA_UNAVAILABLE", "SYNTHETIC", "MOCK"],
    )
    def test_disqualifying_feed_status_fails_closed(self, bad_status):
        engine = SessionIntelligenceEngine()
        df = make_full_day_5m_bars(trading_day=11, end_hhmm=(10, 0))
        rep = engine.evaluate_session(df, as_of_time=ist_dt(10, 0), data_quality_status=bad_status)
        assert rep.is_valid is False
        assert rep.data_quality == bad_status
        assert rep.events == ()

    def test_mock_synthetic_and_repaired_attrs_rejected(self):
        engine = SessionIntelligenceEngine()
        for attr_key in ("is_mock", "is_synthetic", "ohlc_repaired", "missing_mandatory_candles"):
            df = make_full_day_5m_bars(trading_day=11, end_hhmm=(10, 0))
            df.attrs[attr_key] = True
            rep = engine.evaluate_session(df, as_of_time=ist_dt(10, 0))
            assert rep.is_valid is False
            assert rep.events == ()

    def test_supported_indices_and_sensex_governance_gate(self):
        df = make_full_day_5m_bars(trading_day=11, end_hhmm=(10, 0))
        engine_default = SessionIntelligenceEngine()
        for idx_sym in ("NIFTY 50", "BANK NIFTY", "FINNIFTY"):
            assert engine_default.evaluate_session(df, symbol=idx_sym, as_of_time=ist_dt(10, 0)).is_valid is True

        # SENSEX blocked without governance approval
        rep_sensex_blocked = engine_default.evaluate_session(df, symbol="SENSEX", as_of_time=ist_dt(10, 0))
        assert rep_sensex_blocked.is_valid is False
        assert rep_sensex_blocked.data_quality == "GOVERNANCE_LOCKOUT"

        # SENSEX succeeds only when explicitly governance-approved
        engine_sensex = SessionIntelligenceEngine(
            config=SessionConfiguration(sensex_governance_approved=True)
        )
        rep_sensex_ok = engine_sensex.evaluate_session(df, symbol="SENSEX", as_of_time=ist_dt(10, 0))
        assert rep_sensex_ok.is_valid is True
        assert rep_sensex_ok.index == "SENSEX"

        with pytest.raises(ValueError, match="Unsupported index"):
            engine_default.evaluate_session(df, symbol="RELIANCE", as_of_time=ist_dt(10, 0))


# ============================================================================
# 17. Integration with Step 3.1 LiquidityPool / LiquidityEvent
# ============================================================================

class TestStep31LiquidityIntegration:
    def test_integrates_step3_1_pools_and_events_causally(self):
        engine = SessionIntelligenceEngine()
        df = make_full_day_5m_bars(trading_day=11, end_hhmm=(11, 0))

        or_pool = LiquidityPool(
            pool_id="POOL-ORH-1",
            index="NIFTY 50",
            liquidity_type=LiquidityType.OPENING_RANGE_HIGH,
            direction=EventDirection.BEARISH,
            timeframe="5m",
            level=24815.0,
            upper_bound=24817.0,
            lower_bound=24815.0,
            status=LiquidityLifecycleState.IDENTIFIED,
            formation_time=ist_dt(9, 25),
            available_at=ist_dt(9, 45),
            updated_at=ist_dt(9, 45),
            source_candle_identifiers=["c_20261111_0925"],
        )
        sweep_evt = LiquidityEvent(
            event_id="EVT-SWP-MORNING",
            pool_id="POOL-ORH-1",
            index="NIFTY 50",
            event_type=ICTEventType.LIQUIDITY_SWEEP,
            liquidity_type=LiquidityType.OPENING_RANGE_HIGH,
            direction=EventDirection.BEARISH,
            timeframe="5m",
            level=24815.0,
            price_level=24816.0,
            trigger_candle_id="c_20261111_1010",
            penetration_price=24817.5,
            close_price=24813.0,
            penetration_depth_pts=2.5,
            is_wick_sweep=True,
            is_candle_close_breakout=False,
            is_reclaimed=False,
            event_time=ist_dt(10, 10),
            available_at=ist_dt(10, 15),
            created_at=ist_dt(10, 15),
            confirmed_at=ist_dt(10, 15),
            status=LiquidityLifecycleState.SWEPT,
            source_candle_identifiers=["c_20261111_1010"],
        )
        future_evt = LiquidityEvent(
            event_id="EVT-FUTURE-1400",
            pool_id="POOL-ORH-1",
            index="NIFTY 50",
            event_type=ICTEventType.LIQUIDITY_RECLAIM,
            liquidity_type=LiquidityType.OPENING_RANGE_HIGH,
            direction=EventDirection.BEARISH,
            timeframe="5m",
            level=24815.0,
            price_level=24814.0,
            trigger_candle_id="c_20261111_1400",
            penetration_price=24817.0,
            close_price=24812.0,
            penetration_depth_pts=2.0,
            is_wick_sweep=True,
            is_candle_close_breakout=False,
            is_reclaimed=True,
            event_time=ist_dt(14, 0),
            available_at=ist_dt(14, 5),
            created_at=ist_dt(14, 5),
            status=LiquidityLifecycleState.RECLAIMED,
            source_candle_identifiers=["c_20261111_1400"],
        )
        other_index_pool = LiquidityPool(
            pool_id="POOL-BANK-1",
            index="BANK NIFTY",
            liquidity_type=LiquidityType.BSL,
            direction=EventDirection.BEARISH,
            timeframe="5m",
            level=52000.0,
            upper_bound=52010.0,
            lower_bound=52000.0,
            status=LiquidityLifecycleState.IDENTIFIED,
            formation_time=ist_dt(9, 30),
            available_at=ist_dt(9, 45),
            updated_at=ist_dt(9, 45),
            source_candle_identifiers=["c_bn_1"],
        )

        rep = engine.evaluate_session(
            df,
            symbol="NIFTY 50",
            timeframe="5m",
            as_of_time=ist_dt(11, 0),
            liquidity_pools=[or_pool, other_index_pool],
            liquidity_events=[sweep_evt, future_evt],
        )
        assert rep.is_valid is True
        assert len(rep.liquidity_observations) == 2
        obs_by_ref = {o.referenced_pool_id or "": o for o in rep.liquidity_observations}
        assert all(o.referenced_event_id != "EVT-FUTURE-1400" for o in rep.liquidity_observations)
        assert all(o.index == "NIFTY 50" for o in rep.liquidity_observations)
        sweep_obs = next(o for o in rep.liquidity_observations if o.referenced_event_id == "EVT-SWP-MORNING")
        assert sweep_obs.session_id == "MORNING"
        assert "POOL-ORH-1" in obs_by_ref


# ============================================================================
# 18. Configurable Session Windows & Kill Zone Research Governance
# ============================================================================

class TestConfigurableWindowsAndKillZones:
    def test_custom_non_overlapping_session_windows_and_kill_zones(self):
        custom_cfg = SessionConfiguration(
            market_open="09:15",
            market_close="15:30",
            session_windows=(
                SessionWindowConfig(
                    session_id="EARLY", session_name="Early Block",
                    start_time="09:15", end_time="11:30", sequence_order=0,
                ),
                SessionWindowConfig(
                    session_id="LATE", session_name="Late Block",
                    start_time="11:30", end_time="15:30", sequence_order=1,
                ),
            ),
            opening_range_duration_minutes=45,
            kill_zones=(
                KillZoneConfig(
                    kill_zone_id="KZ_RESEARCH_1",
                    kill_zone_name="Custom Research KZ",
                    start_time="09:30",
                    end_time="10:30",
                ),
            ),
        )
        engine = SessionIntelligenceEngine(config=custom_cfg)
        df = make_full_day_5m_bars(trading_day=11, end_hhmm=(12, 0))
        rep = engine.evaluate_session(df, timeframe="5m", as_of_time=ist_dt(12, 0))
        assert rep.is_valid is True
        assert list(rep.session_ranges.keys()) == ["EARLY", "LATE"]
        assert rep.opening_range.duration_minutes == 45
        assert [(t.from_session_id, t.to_session_id) for t in rep.transitions] == [("EARLY", "LATE")]
        assert len(rep.kill_zone_observations) == 1
        kz = rep.kill_zone_observations[0]
        assert kz.research_only is True
        assert kz.is_proven_edge is False
        assert kz.scoring_weight is None

    def test_rejects_overlapping_sessions_and_unapproved_killzone_weights(self):
        with pytest.raises(ValueError, match="Overlapping"):
            SessionConfiguration(
                session_windows=(
                    SessionWindowConfig(
                        session_id="S1", session_name="S1",
                        start_time="09:15", end_time="10:30", sequence_order=0,
                    ),
                    SessionWindowConfig(
                        session_id="S2", session_name="S2",
                        start_time="10:00", end_time="11:30", sequence_order=1,
                    ),
                )
            )

        with pytest.raises(ValueError, match="scoring_weight"):
            KillZoneConfig(
                kill_zone_id="KZ_BAD",
                kill_zone_name="Weighted KZ",
                start_time="09:15",
                end_time="09:45",
                scoring_weight=0.25,
            )


# ============================================================================
# 19. Multi-Timeframe Session Observations & PAPER_TRADING_ONLY Enforcement
# ============================================================================

class TestMultiTimeframeAndGovernance:
    def test_multi_timeframe_synchronization_and_unavailable_scoring(self):
        engine = SessionIntelligenceEngine()
        df_5m = make_full_day_5m_bars(trading_day=11, end_hhmm=(10, 30))

        # Build aligned 15m & 1m series up to 10:30
        rows_15m = [
            make_bar(ist_dt(9, 15) + timedelta(minutes=15 * i), 24800.0 + i, 24820.0 + i, 24790.0 + i, 24810.0 + i)
            for i in range(5)  # 09:15, 09:30, 09:45, 10:00, 10:15 (last closes 10:30)
        ]
        rows_1m = [
            make_bar(ist_dt(9, 15) + timedelta(minutes=i), 24800.0, 24815.0, 24795.0, 24805.0)
            for i in range(75)  # 09:15..10:29 (last closes 10:30)
        ]

        summary = engine.analyze_multi_timeframe(
            {"15m": pd.DataFrame(rows_15m), "5m": df_5m, "1m": pd.DataFrame(rows_1m)},
            symbol="NIFTY 50",
            as_of_time=ist_dt(10, 30),
        )
        assert isinstance(summary, MultiTimeframeSessionSummary)
        assert summary.is_valid is True
        assert summary.execution_mode == "PAPER_TRADING_ONLY"
        assert summary.ict_confluence_score is None
        assert summary.score_status == "UNAVAILABLE"
        assert summary.calibration_status == "NOT_CALIBRATED"
        assert summary.synchronized_active_session_id == "MORNING"
        assert summary.synchronized_active_session_name == "Morning"
        assert summary.timeframe_session_agreement is True

        # Ensure all individual timeframe reports enforce identical uncalibrated & paper policy
        for rep in summary.timeframe_reports.values():
            assert rep.execution_mode == "PAPER_TRADING_ONLY"
            assert rep.confluence_score is None
            assert rep.score_status == "UNAVAILABLE"
            assert rep.calibration_status == "NOT_CALIBRATED"

    def test_exact_builtin_type_defenses_block_subclasses(self):
        class EvilStr(str):
            pass

        engine = SessionIntelligenceEngine()
        df = make_full_day_5m_bars(trading_day=11, end_hhmm=(9, 45))

        with pytest.raises(TypeError, match="exact built-in str"):
            engine.evaluate_session(df, symbol=EvilStr("NIFTY 50"), as_of_time=ist_dt(9, 45))

        with pytest.raises(TypeError, match="exact built-in list"):
            engine.evaluate_session(df, as_of_time=ist_dt(9, 45), liquidity_pools=())  # type: ignore[arg-type]

    def test_prior_day_closing_propagates_to_next_day_opening_and_auto_replay_works(self):
        engine = SessionIntelligenceEngine()
        # 2026-11-04 Wed Closing + 2026-11-05 Thu Opening (both non-holiday trading days)
        assert date(2026, 11, 4) not in mc_module.NSE_HOLIDAYS
        assert date(2026, 11, 5) not in mc_module.NSE_HOLIDAYS

        rows = [
            make_bar(ist_dt(14, 45, day=4), 24700.0, 24755.0, 24695.0, 24740.0, "prev_cl_1"),
            make_bar(ist_dt(15, 25, day=4), 24740.0, 24760.0, 24720.0, 24750.0, "prev_cl_2"),
            make_bar(ist_dt(9, 15, day=5), 24750.0, 24770.0, 24745.0, 24765.0, "cur_op_1"),
            make_bar(ist_dt(9, 20, day=5), 24765.0, 24768.0, 24752.0, 24758.0, "cur_op_2"),
        ]
        df = pd.DataFrame(rows)
        rep = engine.evaluate_session(
            df,
            timeframe="5m",
            as_of_time=ist_dt(9, 25, day=5),
            target_trading_date=date(2026, 11, 5),
        )
        assert rep.is_valid is True
        op = rep.session_ranges["OPENING"]
        assert op.previous_session_id == "CLOSING"
        assert op.previous_session_trading_date == "2026-11-04"
        assert op.previous_session_high == 24760.0
        assert op.previous_session_low == 24695.0
        assert op.breached_previous_high is True

        # Auto replay schedule for 2026-11-05 without explicit replay_times
        auto_reports = engine.replay_session(
            df,
            timeframe="5m",
            target_trading_date=date(2026, 11, 5),
        )
        assert [r.as_of_time for r in auto_reports] == [ist_dt(9, 20, day=5), ist_dt(9, 25, day=5)]

        # Verify malformed timestamp & empty DataFrame fail closed cleanly
        df_bad_ts = pd.DataFrame([
            make_bar(ist_dt(9, 15), 24800.0, 24810.0, 24795.0, 24805.0)
        ])
        df_bad_ts["timestamp"] = ["not-a-valid-timestamp"]
        assert engine.evaluate_session(df_bad_ts, as_of_time=ist_dt(9, 30)).is_valid is False
        assert engine.evaluate_session(pd.DataFrame(), as_of_time=ist_dt(9, 30)).is_valid is False

        # Verify ICTEvent 17-field contract conversion fields are present
        assert len(rep.ict_events) > 0
        for ict_ev in rep.ict_events:
            assert ict_ev.event_id
            assert ict_ev.index == "NIFTY 50"
            assert ict_ev.timeframe == "5m"
            assert ict_ev.available_at >= ict_ev.event_time
            assert "session_event_kind" in ict_ev.evidence
            assert ict_ev.evidence["execution_mode"] == "PAPER_TRADING_ONLY"

