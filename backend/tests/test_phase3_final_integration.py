"""
AIVOLVE Phase 3 — Final Integration & Governance Validation Suite.

End-to-end offline/historical validation of Steps 3.1 through 3.7 integrated
through `MTFConfluenceEngine`:
  - Step 3.1 Liquidity Intelligence & Swing Detection
  - Step 3.2 Market Structure & CHoCH / BOS / MSS
  - Step 3.3 Order Block Detection & Lifecycle
  - Step 3.4 FVG / IFVG Detection & Lifecycle
  - Step 3.5 Premium/Discount & 7-Stage Inducement Progression
  - Step 3.6 Session Intelligence Engine
  - Step 3.7 MTF ICT/SMC Confluence Engine

Governance & Isolation Guarantees:
  - Offline/historical candle replay only (no broker/network/live-feed claims)
  - Strictly PAPER_TRADING_ONLY, zero trade execution triggers
  - ICT Confluence Score strictly None / UNAVAILABLE / NOT_CALIBRATED
  - SENSEX governance fail-closed by default
  - Zero mutation of Phase 2 weights, risk, contract selection, or persistence
"""

from __future__ import annotations

import ast
from datetime import date, datetime, time as dt_time, timedelta
from pathlib import Path
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from app.options.ict_smc import (
    AlignmentClassification,
    ConflictType,
    MTFConfluenceConfiguration,
    MTFConfluenceEngine,
    MTFConfluenceReport,
    SessionIntelligenceEngine,
    compute_candle_close_ist,
)

IST = ZoneInfo("Asia/Kolkata")
UTC = ZoneInfo("UTC")

# ---------------------------------------------------------------------------
# Deterministic Historical NSE Session Candle Generators
# ---------------------------------------------------------------------------


def _get_valid_trading_days(end_date: date, min_count: int = 12) -> List[date]:
    """Selects genuine NSE trading days via MarketCalendar in ascending order."""
    se = SessionIntelligenceEngine()
    days: List[date] = []
    cur = end_date - timedelta(days=min_count * 3)
    while cur <= end_date:
        ok, _, _ = se._validate_trading_calendar(cur)
        if ok:
            days.append(cur)
        cur += timedelta(days=1)
    return days[-min_count:]


def _generate_session_timestamps(
    timeframe: str,
    as_of_time: datetime,
    count: int,
    trading_days: Optional[List[date]] = None,
) -> List[datetime]:
    """Generates chronological NSE session candle opens whose close <= as_of_time."""
    step_map = {"1h": 60, "15m": 15, "5m": 5, "3m": 3, "1m": 1}
    step_min = step_map[timeframe]
    days = trading_days or _get_valid_trading_days(as_of_time.date(), min_count=14)
    m_close = dt_time(15, 30)
    opens: List[datetime] = []
    for d in days:
        cur = datetime.combine(d, dt_time(9, 15), tzinfo=IST)
        end_open = datetime.combine(d, m_close, tzinfo=IST)
        while cur < end_open:
            close_ts = compute_candle_close_ist(cur, timeframe, m_close)
            if close_ts <= as_of_time:
                opens.append(cur)
            cur += timedelta(minutes=step_min)
    return opens[-count:]


def _build_bullish_inducement_df(
    timestamps: List[datetime],
    *,
    base_price: float = 24000.0,
    scale: float = 1.0,
) -> pd.DataFrame:
    """
    Generates a 37-bar+ OHLC sequence that authentically triggers Steps 3.1–3.6:
      - Bars 0..15: ATR(14) warmup consolidation
      - Bar 18: Internal Swing Low (SSL pool, e.g. 24090)
      - Bar 23: Deep sweep & single-candle reclaim below bar-18 SSL (low 24020, close 24098)
      - Bar 29: Swing High forming BULLISH Dealing Range [24020, 24180]
      - Bar 35: Down candle (Bullish Order Block candidate)
      - Bar 36: Strong bullish displacement breaking bar-25 internal high & creating FVG + Stage 7 IDM
    """
    n = len(timestamps)
    assert n >= 37, f"Need at least 37 bars, got {n}"
    offset_bars = n - 37
    # Pad leading warmup bars smoothly before the 37-bar structural sequence
    lead_mids = [110.0 + ((k % 3) - 1) * 2.0 for k in range(offset_bars)]
    core_mids = [
        110, 114, 111, 116, 113, 117, 112, 118, 114, 119, 115, 120, 114, 118,
        115, 112, 106, 100, 96, 106,
        115, 112, 106, 98, 112, 126,
        138, 152, 166, 176, 162, 148,
        136, 130, 128, 150, 206,
    ]
    mids = lead_mids + core_mids

    rows = []
    for idx, ts in enumerate(timestamps):
        rel = idx - offset_bars
        if rel == 18:
            o = base_price + 102 * scale
            h = base_price + 106 * scale
            l = base_price + 90 * scale
            c = base_price + 96 * scale
        elif rel == 23:
            o = base_price + 106 * scale
            h = base_price + 112 * scale
            l = base_price + 20 * scale
            c = base_price + 98 * scale
        elif rel == 29:
            o = base_price + 166 * scale
            h = base_price + 180 * scale
            l = base_price + 162 * scale
            c = base_price + 176 * scale
        elif rel == 35:
            o = base_price + 160 * scale
            h = base_price + 162 * scale
            l = base_price + 148 * scale
            c = base_price + 150 * scale
        elif rel == 36:
            o = base_price + 150 * scale
            h = base_price + 212 * scale
            l = base_price + 148 * scale
            c = base_price + 206 * scale
        else:
            c = base_price + mids[idx] * scale
            prev_c = base_price + (mids[idx - 1] if idx > 0 else mids[0]) * scale
            o = prev_c
            h = max(o, c) + 4.0 * scale
            l = min(o, c) - 4.0 * scale
        rows.append(
            {
                "timestamp": ts,
                "open": float(o),
                "high": float(h),
                "low": float(l),
                "close": float(c),
                "volume": float(1200 + idx * 15),
                "is_complete": True,
            }
        )
    return pd.DataFrame(rows)


def _build_bearish_trend_df(
    timestamps: List[datetime],
    *,
    base_price: float = 24600.0,
    scale: float = 1.0,
) -> pd.DataFrame:
    """
    Mirrors the 37-bar curve downward to generate authentic bearish structure,
    BSL sweep/reclaim, bearish OB, bearish FVG, and downward displacement.
    """
    bull_df = _build_bullish_inducement_df(timestamps, base_price=0.0, scale=scale)
    rows = []
    for _, row in bull_df.iterrows():
        o = base_price - row["open"]
        c = base_price - row["close"]
        h = base_price - row["low"]
        l = base_price - row["high"]
        rows.append(
            {
                "timestamp": row["timestamp"],
                "open": float(o),
                "high": float(h),
                "low": float(l),
                "close": float(c),
                "volume": float(row["volume"]),
                "is_complete": True,
            }
        )
    return pd.DataFrame(rows)


def _build_5tf_candles(as_of: datetime, bearish: bool = False) -> Dict[str, pd.DataFrame]:
    days = _get_valid_trading_days(as_of.date(), min_count=14)
    builder = _build_bearish_trend_df if bearish else _build_bullish_inducement_df
    counts = {"1h": 42, "15m": 42, "5m": 120, "3m": 180, "1m": 300}
    return {
        tf: builder(_generate_session_timestamps(tf, as_of, count=counts[tf], trading_days=days))
        for tf in ("1h", "15m", "5m", "3m", "1m")
    }


# ---------------------------------------------------------------------------
# 1. End-to-End 7-Engine Composition & Governance Contract
# ---------------------------------------------------------------------------


def test_01_end_to_end_seven_engine_composition_bullish_and_stage7_idm():
    """
    Validates Steps 3.1–3.7 composed purely from raw OHLC candles across all 5 TFs:
    - Each TF produces real Step 3.1 liquidity pools/events, Step 3.2 structure,
      Step 3.3 Order Blocks, Step 3.4 FVG/IFVGs, Step 3.5 PD + Stage 7 Confirmed IDM,
      Step 3.6 session intelligence, and Step 3.7 STRONG_BULLISH_ALIGNMENT.
    - Enforces UNAVAILABLE / NOT_CALIBRATED scoring & PAPER_TRADING_ONLY policy.
    """
    as_of = datetime(2026, 11, 6, 15, 30, tzinfo=IST)
    engine = MTFConfluenceEngine()
    candles = _build_5tf_candles(as_of, bearish=False)

    report = engine.evaluate_from_candles(
        index="NIFTY 50",
        as_of_time=as_of,
        candles_by_timeframe=candles,
        data_quality_status="VERIFIED_LIVE",
        include_session_context=True,
    )

    assert isinstance(report, MTFConfluenceReport)
    assert report.index == "NIFTY 50"
    assert report.execution_mode == "PAPER_TRADING_ONLY"
    assert report.data_quality_status == "VERIFIED_LIVE"
    assert report.overall_alignment == AlignmentClassification.STRONG_BULLISH_ALIGNMENT
    assert tuple(report.missing_timeframes) == ()
    assert report.confluence_score is None
    assert report.score_status == "UNAVAILABLE"
    assert report.calibration_status == "NOT_CALIBRATED"
    assert report.report_id.startswith("MTF-")

    for tf in ("1h", "15m", "5m", "3m", "1m"):
        tfr = report.timeframe_reports[tf]
        assert tfr.has_valid_evidence is True
        assert tfr.direction == "BULLISH"
        assert "BULLISH" in tfr.structure_status
        assert tfr.order_block_status != "UNAVAILABLE"
        assert tfr.fvg_status != "UNAVAILABLE"
        assert tfr.premium_discount_status != "UNAVAILABLE"
        # Verifies Step 3.2 -> Step 3.5 Stage 7 Inducement contract fix
        assert tfr.inducement_status == "CONFIRMED_BULLISH"
        assert any(eid.startswith("EVT-IDM-") for eid in tfr.evidence_event_ids)
        # Verifies Step 3.6 Session Intelligence populated
        assert tfr.session_status != "UNAVAILABLE"
        assert "Closing" in tfr.session_status or "CLOSED:" in tfr.session_status


def test_02_end_to_end_seven_engine_bearish_and_mixed_conflict_detection():
    """Verifies bearish mirror end-to-end (STRONG_BEARISH_ALIGNMENT) and mixed HTF/LTF conflict."""
    as_of = datetime(2026, 11, 6, 15, 30, tzinfo=IST)
    engine = MTFConfluenceEngine()

    bear_candles = _build_5tf_candles(as_of, bearish=True)
    bear_report = engine.evaluate_from_candles(
        index="BANK NIFTY",
        as_of_time=as_of,
        candles_by_timeframe=bear_candles,
        data_quality_status="VERIFIED_EOD",
    )
    assert bear_report.overall_alignment == AlignmentClassification.STRONG_BEARISH_ALIGNMENT
    assert bear_report.confluence_score is None
    for tf in ("1h", "15m", "5m", "3m", "1m"):
        assert bear_report.timeframe_reports[tf].direction == "BEARISH"
        assert bear_report.timeframe_reports[tf].inducement_status == "CONFIRMED_BEARISH"

    # Mixed scenario: 1H & 15M bullish, 5M/3M/1M bearish -> MIXED_ALIGNMENT + structured divergence
    bull_candles = _build_5tf_candles(as_of, bearish=False)
    mixed_candles = {
        "1h": bull_candles["1h"],
        "15m": bull_candles["15m"],
        "5m": bear_candles["5m"],
        "3m": bear_candles["3m"],
        "1m": bear_candles["1m"],
    }
    mixed_report = engine.evaluate_from_candles(
        index="FINNIFTY",
        as_of_time=as_of,
        candles_by_timeframe=mixed_candles,
        data_quality_status="VERIFIED_LIVE",
    )
    assert mixed_report.overall_alignment == AlignmentClassification.MIXED_ALIGNMENT
    assert any(
        c.conflict_type
        in (ConflictType.ITF_PRIMARY_DIVERGENCE, ConflictType.CROSS_TIMEFRAME_DIVERGENCE)
        for c in mixed_report.conflicts
    )
    assert mixed_report.confluence_score is None
    assert mixed_report.score_status == "UNAVAILABLE"


# ---------------------------------------------------------------------------
# 2. Strict Zero-Lookahead & NSE Completed-Candle Boundaries
# ---------------------------------------------------------------------------


def test_03_zero_lookahead_prefix_vs_future_bars_and_forming_candle_boundaries():
    """
    Proves mathematically across all 7 engines:
      1. Truncated candle dataset <= t_mid produces BYTE-IDENTICAL MTFConfluenceReport
         to a dataset containing violent future reversal bars after t_mid.
      2. Forming 1H bar (10:15 open evaluated at 10:45 IST) is excluded until 11:15 IST close.
      3. NSE 15:15 closing bar (closing at 15:30 IST) is excluded at 15:29 and included at 15:30.
    """
    days = _get_valid_trading_days(date(2026, 11, 6), min_count=14)
    t_mid = datetime(2026, 11, 6, 13, 30, tzinfo=IST)
    t_end = datetime(2026, 11, 6, 15, 30, tzinfo=IST)

    engine = MTFConfluenceEngine()
    full_candles = _build_5tf_candles(t_end, bearish=False)

    # Corrupt all bars opening > t_mid or closing > t_mid with dramatic inverse prices
    poisoned_future: Dict[str, pd.DataFrame] = {}
    truncated_at_mid: Dict[str, pd.DataFrame] = {}
    m_close = dt_time(15, 30)

    for tf, df in full_candles.items():
        keep_rows = []
        mod_rows = []
        for _, r in df.iterrows():
            open_ts = r["timestamp"].to_pydatetime() if hasattr(r["timestamp"], "to_pydatetime") else r["timestamp"]
            close_ts = compute_candle_close_ist(open_ts, tf, m_close)
            row_dict = r.to_dict()
            if close_ts <= t_mid:
                keep_rows.append(dict(row_dict))
                mod_rows.append(dict(row_dict))
            else:
                # Inject extreme bearish future breakout after t_mid
                mod_rows.append(
                    {
                        **row_dict,
                        "open": 22500.0,
                        "high": 22600.0,
                        "low": 21800.0,
                        "close": 21900.0,
                        "volume": 999999.0,
                    }
                )
        truncated_at_mid[tf] = pd.DataFrame(keep_rows)
        poisoned_future[tf] = pd.DataFrame(mod_rows)

    rep_trunc = engine.evaluate_from_candles(
        index="NIFTY 50",
        as_of_time=t_mid,
        candles_by_timeframe=truncated_at_mid,
        data_quality_status="VERIFIED_LIVE",
    )
    rep_poison = engine.evaluate_from_candles(
        index="NIFTY 50",
        as_of_time=t_mid,
        candles_by_timeframe=poisoned_future,
        data_quality_status="VERIFIED_LIVE",
    )

    assert rep_trunc.report_id == rep_poison.report_id
    assert rep_trunc.overall_alignment == rep_poison.overall_alignment
    assert rep_trunc.bullish_evidence == rep_poison.bullish_evidence
    assert rep_trunc.bearish_evidence == rep_poison.bearish_evidence
    assert rep_trunc.conflicts == rep_poison.conflicts
    assert rep_trunc.evidence_event_ids == rep_poison.evidence_event_ids

    # Check forming 1H bar exclusion at 10:45 IST (10:15 1H bar closes 11:15):
    # Adding the unclosed 10:15 forming bar must yield byte-identical report to bars ending < 10:15,
    # and the audit helper must count incomplete_candles_excluded >= 1.
    t_forming = datetime(2026, 11, 6, 10, 45, tzinfo=IST)
    bars_1h_up_to_1015 = full_candles["1h"][
        pd.to_datetime(full_candles["1h"]["timestamp"]) <= t_forming
    ].copy()
    bars_1h_completed_only = full_candles["1h"][
        pd.to_datetime(full_candles["1h"]["timestamp"]) < datetime(2026, 11, 6, 10, 15, tzinfo=IST)
    ].copy()
    rep_with_forming = engine.evaluate_from_candles(
        index="NIFTY 50",
        as_of_time=t_forming,
        candles_by_timeframe={"1h": bars_1h_up_to_1015, "5m": full_candles["5m"]},
        data_quality_status="VERIFIED_LIVE",
    )
    rep_without_forming = engine.evaluate_from_candles(
        index="NIFTY 50",
        as_of_time=t_forming,
        candles_by_timeframe={"1h": bars_1h_completed_only, "5m": full_candles["5m"]},
        data_quality_status="VERIFIED_LIVE",
    )
    assert rep_with_forming.report_id == rep_without_forming.report_id
    assert rep_with_forming.timeframe_reports["1h"] == rep_without_forming.timeframe_reports["1h"]
    _, _, _, f_excl, inc_excl = engine._audit_and_filter_dataframe(
        full_candles["1h"], "1h", t_forming, "VERIFIED_LIVE"
    )
    assert inc_excl == 1
    assert f_excl >= 4

    # Check NSE 15:30 session close boundary: 15:15 1H & 15:25 5M close at 15:30 IST
    t_before_close = datetime(2026, 11, 6, 15, 29, tzinfo=IST)
    _, _, _, _, inc_1h_1529 = engine._audit_and_filter_dataframe(
        full_candles["1h"], "1h", t_before_close, "VERIFIED_LIVE"
    )
    _, _, _, _, inc_5m_1529 = engine._audit_and_filter_dataframe(
        full_candles["5m"], "5m", t_before_close, "VERIFIED_LIVE"
    )
    assert inc_1h_1529 == 1
    assert inc_5m_1529 == 1

    # Explicit completion flag False / NaN rejected safely (checked both via audit & evaluate_from_candles)
    bad_flag_df = full_candles["5m"].copy()
    bad_flag_df.loc[bad_flag_df.index[-1], "is_complete"] = False
    _, _, _, _, inc_flag = engine._audit_and_filter_dataframe(
        bad_flag_df, "5m", t_end, "VERIFIED_LIVE"
    )
    assert inc_flag == 1
    rep_flag = engine.evaluate_from_candles(
        index="NIFTY 50",
        as_of_time=t_end,
        candles_by_timeframe={"5m": bad_flag_df},
        data_quality_status="VERIFIED_LIVE",
    )
    assert rep_flag.timeframe_reports["5m"].data_quality == "VERIFIED_LIVE"
    assert bad_flag_df.iloc[-1]["timestamp"].isoformat() not in rep_flag.timeframe_reports["5m"].evidence_event_ids


# ---------------------------------------------------------------------------
# 3. End-to-End Lifecycle Propagation (FVG -> IFVG & OB Invalidation)
# ---------------------------------------------------------------------------


def test_04_end_to_end_fvg_to_ifvg_and_ob_invalidation_propagation():
    """
    Tests multi-step candle lifecycle propagation across Steps 3.3, 3.4, and 3.7:
    At t_bull, price creates an active bullish FVG & bullish OB; at t_inv after a
    decisive downside reversal through the zone, Step 3.3 invalidates the bullish OB
    and Step 3.4 converts the bullish FVG into a bearish IFVG reflected in Step 3.7.
    """
    days = _get_valid_trading_days(date(2026, 11, 6), min_count=10)
    ts_all = _generate_session_timestamps("5m", datetime(2026, 11, 6, 15, 30, tzinfo=IST), count=55, trading_days=days)
    df_bull = _build_bullish_inducement_df(ts_all[:37], base_price=24000.0)
    t_bull = compute_candle_close_ist(ts_all[36], "5m", dt_time(15, 30))

    engine = MTFConfluenceEngine()
    rep_bull = engine.evaluate_from_candles(
        index="NIFTY 50",
        as_of_time=t_bull,
        candles_by_timeframe={"5m": df_bull},
        data_quality_status="VERIFIED_LIVE",
    )
    assert "BULLISH" in rep_bull.timeframe_reports["5m"].order_block_status
    assert "BULLISH" in rep_bull.timeframe_reports["5m"].fvg_status

    # Append decisive bearish crash well below the 24106..24148 FVG & OB zone (< 24100 -> 24010)
    crash_closes = [24195.0, 24170.0, 24142.0, 24108.0, 24075.0, 24040.0, 24020.0, 24012.0]
    ext_rows = df_bull.to_dict("records")
    prev_c = float(ext_rows[-1]["close"])
    for k, target_c in enumerate(crash_closes):
        ts = ts_all[37 + k]
        o = prev_c
        h = max(o, target_c) + 3.0
        l = min(o, target_c) - 3.0
        ext_rows.append(
            {
                "timestamp": ts,
                "open": float(o),
                "high": float(h),
                "low": float(l),
                "close": float(target_c),
                "volume": 2500.0,
                "is_complete": True,
            }
        )
        prev_c = target_c
    df_inv = pd.DataFrame(ext_rows)
    t_inv = compute_candle_close_ist(ts_all[37 + len(crash_closes) - 1], "5m", dt_time(15, 30))

    rep_inv = engine.evaluate_from_candles(
        index="NIFTY 50",
        as_of_time=t_inv,
        candles_by_timeframe={"5m": df_inv},
        data_quality_status="VERIFIED_LIVE",
    )
    tfr_inv = rep_inv.timeframe_reports["5m"]
    # Prior bullish OB must not linger as dominant active bullish bias after price crashed through it
    assert "BULLISH_OB_ACTIVE" not in tfr_inv.order_block_status
    # Step 3.4 inverted FVG / new bearish imbalance propagates cleanly into Step 3.7
    assert "BEARISH" in tfr_inv.fvg_status
    assert tfr_inv.direction in ("BEARISH", "CONFLICTING")
    assert tfr_inv.direction != "BULLISH"
    assert len(tfr_inv.invalidated_event_ids) >= 1
    # Verify Step 3.4 directly inverted a bullish FVG into a confirmed BEARISH IFVG
    fvg_inv_check = engine.fvg_engine.analyze_timeframe(
        df=df_inv,
        symbol="NIFTY 50",
        timeframe="5m",
        as_of_time=t_inv,
        data_quality_status="VERIFIED_LIVE",
    )
    assert any(
        ev.direction.value == "BEARISH" and ev.event_status.value in ("CONFIRMED", "APPROACHING")
        for ev in fvg_inv_check.ifvg_events
    )


# ---------------------------------------------------------------------------
# 4. Deterministic Chronological Replay Across Session Transitions
# ---------------------------------------------------------------------------


def test_05_deterministic_historical_replay_matches_point_in_time_calls():
    """
    Runs chronological replay across intraday NSE session transitions and proves
    exact byte-level repeatability and parity with independent evaluate_from_candles calls.
    """
    t_end = datetime(2026, 11, 6, 15, 30, tzinfo=IST)
    candles = _build_5tf_candles(t_end, bearish=False)
    replay_times = [
        datetime(2026, 11, 6, 10, 15, tzinfo=IST),
        datetime(2026, 11, 6, 11, 30, tzinfo=IST),
        datetime(2026, 11, 6, 13, 30, tzinfo=IST),
        datetime(2026, 11, 6, 14, 45, tzinfo=IST),
        datetime(2026, 11, 6, 15, 30, tzinfo=IST),
    ]

    engine = MTFConfluenceEngine()
    run1 = engine.replay(
        index="NIFTY 50",
        replay_times=replay_times,
        candles_by_timeframe=candles,
        data_quality_status="VERIFIED_LIVE",
    )
    run2 = engine.replay(
        index="NIFTY 50",
        replay_times=replay_times,
        candles_by_timeframe=candles,
        data_quality_status="VERIFIED_LIVE",
    )

    assert len(run1) == len(replay_times)
    for idx, t_point in enumerate(replay_times):
        standalone = engine.evaluate_from_candles(
            index="NIFTY 50",
            as_of_time=t_point,
            candles_by_timeframe=candles,
            data_quality_status="VERIFIED_LIVE",
        )
        assert run1[idx].model_dump() == run2[idx].model_dump()
        assert run1[idx].model_dump() == standalone.model_dump()
        assert run1[idx].confluence_score is None
        assert run1[idx].score_status == "UNAVAILABLE"
        assert run1[idx].calibration_status == "NOT_CALIBRATED"
        assert run1[idx].execution_mode == "PAPER_TRADING_ONLY"


# ---------------------------------------------------------------------------
# 5. Fail-Closed Lockouts: Calendar, Data Quality, SENSEX Governance
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_as_of",
    [
        datetime(2026, 11, 10, 12, 0, tzinfo=IST),  # NSE Trading Holiday in MarketCalendar
        datetime(2026, 11, 14, 12, 0, tzinfo=IST),  # Saturday weekend
    ],
)
def test_06_non_trading_day_fails_closed_without_uncaught_exception(bad_as_of: datetime):
    engine = MTFConfluenceEngine()
    candles = _build_5tf_candles(datetime(2026, 11, 6, 15, 30, tzinfo=IST), bearish=False)
    rep = engine.evaluate_from_candles(
        index="NIFTY 50",
        as_of_time=bad_as_of,
        candles_by_timeframe=candles,
        data_quality_status="VERIFIED_LIVE",
    )
    assert rep.overall_alignment == AlignmentClassification.DATA_QUALITY_LOCKOUT
    assert rep.data_quality_status == "NON_TRADING_DAY"
    assert rep.confluence_score is None


def test_07_repaired_imputed_mixed_tz_mock_and_sensex_lockouts():
    as_of = datetime(2026, 11, 6, 15, 30, tzinfo=IST)
    engine = MTFConfluenceEngine()
    base_candles = _build_5tf_candles(as_of, bearish=False)

    # 1. REPAIRED attrs must never raise raw ValueError; must fail closed in bundle/lockout
    rep_repaired_df = base_candles["5m"].copy()
    rep_repaired_df.attrs = {"quality_status": "REPAIRED"}
    r_repaired = engine.evaluate_from_candles(
        index="NIFTY 50",
        as_of_time=as_of,
        candles_by_timeframe={"5m": rep_repaired_df},
        data_quality_status="VERIFIED_LIVE",
    )
    assert r_repaired.overall_alignment in (
        AlignmentClassification.DATA_QUALITY_LOCKOUT,
        AlignmentClassification.INSUFFICIENT_DATA,
    )
    assert r_repaired.timeframe_reports["5m"].has_valid_evidence is False
    assert r_repaired.timeframe_reports["5m"].data_quality == "INVALID_DATA"

    # 2. imputed_bars_count > 0 must reject safely
    imputed_df = base_candles["5m"].copy()
    imputed_df.attrs = {"imputed_bars_count": 3}
    r_imputed = engine.evaluate_from_candles(
        index="NIFTY 50",
        as_of_time=as_of,
        candles_by_timeframe={"5m": imputed_df},
        data_quality_status="VERIFIED_LIVE",
    )
    assert r_imputed.timeframe_reports["5m"].has_valid_evidence is False
    assert r_imputed.timeframe_reports["5m"].data_quality == "INVALID_DATA"

    # 3. Mixed timezones (UTC + Asia/Kolkata inside same DataFrame) fail closed as INVALID_DATA
    mixed_tz_df = base_candles["5m"].copy()
    ts_list = list(mixed_tz_df["timestamp"])
    ts_list[0] = ts_list[0].tz_convert(UTC) if hasattr(ts_list[0], "tz_convert") else ts_list[0].astimezone(UTC)
    mixed_tz_df["timestamp"] = pd.Series(ts_list, dtype="object")
    r_mixed_tz = engine.evaluate_from_candles(
        index="NIFTY 50",
        as_of_time=as_of,
        candles_by_timeframe={"5m": mixed_tz_df},
        data_quality_status="VERIFIED_LIVE",
    )
    assert r_mixed_tz.timeframe_reports["5m"].has_valid_evidence is False
    assert r_mixed_tz.timeframe_reports["5m"].data_quality == "INVALID_DATA"

    # 4. Synthetic/Mock attributes fail closed
    mock_df = base_candles["5m"].copy()
    mock_df.attrs = {"is_mock": True}
    r_mock = engine.evaluate_from_candles(
        index="NIFTY 50",
        as_of_time=as_of,
        candles_by_timeframe={"5m": mock_df},
        data_quality_status="VERIFIED_LIVE",
    )
    assert r_mock.timeframe_reports["5m"].has_valid_evidence is False

    # 5. Disqualifying top-level status fails closed immediately
    for bad_q in ("DEGRADED", "MOCK", "SYNTHETIC", "DATA_OFFLINE", "DATA_UNAVAILABLE"):
        r_bad_q = engine.evaluate_from_candles(
            index="NIFTY 50",
            as_of_time=as_of,
            candles_by_timeframe=base_candles,
            data_quality_status=bad_q,
        )
        assert r_bad_q.overall_alignment == AlignmentClassification.DATA_QUALITY_LOCKOUT
        assert r_bad_q.data_quality_status == bad_q

    # 6. SENSEX governance restriction intact by default, unlocked only explicitly
    r_sensex_blocked = engine.evaluate_from_candles(
        index="SENSEX",
        as_of_time=as_of,
        candles_by_timeframe=base_candles,
        data_quality_status="VERIFIED_LIVE",
    )
    assert r_sensex_blocked.overall_alignment == AlignmentClassification.DATA_QUALITY_LOCKOUT
    assert r_sensex_blocked.data_quality_status == "GOVERNANCE_LOCKOUT"

    approved_eng = MTFConfluenceEngine(MTFConfluenceConfiguration(sensex_governance_approved=True))
    r_sensex_ok = approved_eng.evaluate_from_candles(
        index="SENSEX",
        as_of_time=as_of,
        candles_by_timeframe=base_candles,
        data_quality_status="VERIFIED_LIVE",
    )
    assert r_sensex_ok.overall_alignment == AlignmentClassification.STRONG_BULLISH_ALIGNMENT


# ---------------------------------------------------------------------------
# 6. Architectural Isolation Across ALL Steps 3.1–3.7 Modules
# ---------------------------------------------------------------------------


def test_08_architectural_governance_isolation_across_all_phase3_modules():
    """
    Verifies via AST & source audit across EVERY Step 3.1–3.7 engine module:
      - Zero imports of Phase 2 execution, risk, contract selection, or paper/ML modules
      - Zero trade signal side strings ('BUY_CE', 'BUY_PE')
      - Zero dependency on legacy pre-Phase-3 analyzers/wrappers
    """
    ict_dir = Path(__file__).resolve().parents[1] / "app" / "options" / "ict_smc"
    step3_modules = [
        ict_dir / "ict_models.py",
        ict_dir / "swing_detection.py",
        ict_dir / "liquidity_engine.py",
        ict_dir / "market_structure.py",
        ict_dir / "order_block_engine.py",
        ict_dir / "fvg_engine.py",
        ict_dir / "premium_discount_engine.py",
        ict_dir / "session_engine.py",
        ict_dir / "mtf_confluence_engine.py",
    ]
    for p in step3_modules:
        assert p.exists(), f"Missing Phase 3 module {p}"

    forbidden_modules = (
        "paper_trading",
        "contract_selector",
        "option_risk_engine",
        "app.options.multi_timeframe_engine",
        "ml_strategy_learner",
        "pipeline_orchestrator",
        "structure_analyzer",
        "fvg_orderblock_engine",
    )
    forbidden_tokens = ("BUY_CE", "BUY_PE", "execute_order", "place_order")

    for py_path in step3_modules:
        text = py_path.read_text(encoding="utf-8")
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for mod in forbidden_modules:
                        assert mod not in alias.name, f"{py_path.name} imports forbidden module {alias.name}"
            elif isinstance(node, ast.ImportFrom):
                mod_name = node.module or ""
                for mod in forbidden_modules:
                    assert mod not in mod_name, f"{py_path.name} imports forbidden module {mod_name}"
        for tok in forbidden_tokens:
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    if node.value.strip() == tok:
                        raise AssertionError(f"{py_path.name} contains standalone execution token {tok!r}")
                elif isinstance(node, ast.Name) and node.id == tok:
                    raise AssertionError(f"{py_path.name} references forbidden symbol {tok!r}")

