"""
AIVOLVE Institutional Quantitative Trading Intelligence v3.0
Phase 2 Step 3: Multi-Timeframe Confluence Engine

Coordinates and evaluates institutional market confluence across synchronized timeframes:
1. Higher Timeframe (HTF): 1H and 15M trend bias & macro structure.
2. Intermediate Timeframe (ITF): 5M market structure, BOS, CHoCH, liquidity sweeps, displacement.
3. Lower Timeframe (LTF): 1M / 3M execution trigger, micro structure shift, confirmed candle retest.

Strict Policies Enforced:
- Missing 1H: Capped at 60/100, trend-based qualification restricted.
- Missing 15M: Directional trade lockout (No BUY_CE or BUY_PE).
- Missing 5M: Total execution lockout.
- Missing 1M: Allows validated 5M-based fallback ('FALLBACK_5M_TRIGGER').
- Missing 3M: No fabrication/interpolation of missing bars.
- Incomplete Candle Rejection: Live forming candles cannot confirm triggers or structure shifts.
- Phase 1 Data-Quality Gates: Stale, anomalous, mock or synthetic data strictly rejected.
- Confluence Score: Normalized 0-100 metric, never represented as a win probability.
"""

from datetime import datetime, time as dt_time, timedelta
from typing import Dict, Any, List, Optional, Tuple
import pandas as pd
import numpy as np

from app.options.candle_processor import (
    calculate_adx_wilder,
    calculate_atr_wilder,
    calculate_ema,
    compute_intraday_vwap,
    calculate_bollinger_bands,
    process_candlestick_series,
)
from app.data.market_calendar import IST_ZONE, MarketCalendar


# ---------------------------------------------------------------------------
# Default Configuration
# ---------------------------------------------------------------------------
DEFAULT_MTF_CONFIG: Dict[str, Any] = {
    # Weights for Confluence Scoring (sum to 100)
    "weight_htf": 35.0,
    "weight_itf": 30.0,
    "weight_ltf": 20.0,
    "weight_quant": 10.0,
    "weight_options": 5.0,

    # Minimum history requirements (in completed bars)
    "min_bars_1h": 14,
    "min_bars_15m": 14,
    "min_bars_5m": 10,
    "min_bars_1m": 8,

    # Scoring Penalties
    "penalty_htf_itf_conflict": 30.0,
    "penalty_itf_ltf_conflict": 15.0,
    "penalty_data_degraded": 40.0,
    "cap_score_missing_1h": 60.0,

    # Structure & Trigger Parameters
    "displacement_body_atr_mult": 1.15,
    "liquidity_wick_ratio": 0.45,
    "adx_trend_threshold": 20.0,
    "adx_strong_trend": 25.0,
}


def _normalize_timeframe_key(key: str) -> str:
    """Standardizes timeframe dictionary keys to lowercase (e.g., '15M' -> '15m')."""
    return key.strip().lower()


SUPPORTED_CANDLE_TIMEFRAME_MINUTES: Dict[str, int] = {
    "1m": 1,
    "3m": 3,
    "5m": 5,
    "10m": 10,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "60m": 60,
}


def _coerce_bool_flag(val: Any) -> Optional[bool]:
    """Converts an explicit completion column value into a strict bool or None if missing."""
    if val is None or pd.isna(val):
        return None
    if isinstance(val, str):
        norm = val.strip().lower()
        if norm in ("false", "0", "no", "open", "forming", ""):
            return False
        if norm in ("true", "1", "yes", "closed", "complete"):
            return True
        return None
    if isinstance(val, (int, float)):
        import math
        if math.isnan(val):
            return None
        return bool(val)
    return bool(val)


def _to_ist_datetime(ts_raw: Any) -> Optional[datetime]:
    """Parses a timestamp scalar and converts or localizes it to IST timezone."""
    if ts_raw is None or pd.isna(ts_raw):
        return None
    try:
        ts = pd.to_datetime(ts_raw)
    except Exception:
        return None
    if ts is pd.NaT or pd.isna(ts):
        return None
    py_dt = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
    if not isinstance(py_dt, datetime):
        return None
    if py_dt.tzinfo is None:
        return py_dt.replace(tzinfo=IST_ZONE)
    return py_dt.astimezone(IST_ZONE)


def _compute_candle_close_ist(bar_start_ist: datetime, timeframe: str) -> Optional[datetime]:
    """Computes the closing boundary timestamp in IST for a candle starting at `bar_start_ist`."""
    tf = str(timeframe).strip().lower()
    if tf in SUPPORTED_CANDLE_TIMEFRAME_MINUTES:
        minutes = SUPPORTED_CANDLE_TIMEFRAME_MINUTES[tf]
        bar_end = bar_start_ist + timedelta(minutes=minutes)
        if (
            (bar_start_ist.hour == 15 and bar_start_ist.minute == 15 and minutes in (30, 60))
            or (bar_start_ist.hour == 15 and bar_start_ist.minute == 25 and minutes == 10)
        ):
            session_close = bar_start_ist.replace(hour=15, minute=30, second=0, microsecond=0)
            if bar_end > session_close:
                bar_end = session_close
        return bar_end
    if tf in ("1d", "day"):
        if bar_start_ist.time() <= dt_time(15, 30):
            return bar_start_ist.replace(hour=15, minute=30, second=0, microsecond=0)
        return (bar_start_ist + timedelta(days=1)).replace(hour=15, minute=30, second=0, microsecond=0)
    return None


def _is_candle_complete(
    candle: pd.Series,
    timeframe: Optional[str] = None,
    now_ist: Optional[datetime] = None,
) -> bool:
    """
    Verifies that a candle is fully closed and not a live forming or future lookahead bar.

    Fails closed when completion flags are missing/NaN unless timeframe-aware IST
    boundaries prove the bar has closed (`bar_end_ist <= now_ist`).
    """
    closed_flag = _coerce_bool_flag(candle["is_closed"]) if "is_closed" in candle else None
    complete_flag = _coerce_bool_flag(candle["is_complete"]) if "is_complete" in candle else None

    if closed_flag is False or complete_flag is False:
        return False

    has_explicit_true = (closed_flag is True) or (complete_flag is True)
    eff_now = _to_ist_datetime(now_ist) if now_ist is not None else MarketCalendar.now_ist()
    if eff_now is None:
        eff_now = MarketCalendar.now_ist()

    ts_raw = candle["timestamp"] if "timestamp" in candle else None
    bar_start_ist = _to_ist_datetime(ts_raw)
    eff_tf = timeframe or (candle["timeframe"] if "timeframe" in candle else None)

    if bar_start_ist is not None:
        if bar_start_ist > eff_now:
            return False
        if eff_tf:
            bar_end_ist = _compute_candle_close_ist(bar_start_ist, str(eff_tf))
            if bar_end_ist is None:
                return False
            return bar_end_ist <= eff_now
        return has_explicit_true

    return has_explicit_true


def filter_completed_candles(
    df: Optional[pd.DataFrame],
    timeframe: Optional[str] = None,
    now_ist: Optional[datetime] = None,
) -> Optional[pd.DataFrame]:
    """
    Excludes all forming, incomplete, or future lookahead candles from `df` using
    explicit completion flags and IST timeframe boundaries. Preserves df.attrs.
    """
    if df is None or df.empty:
        return df

    eff_tf = timeframe or (df.attrs.get("timeframe") if hasattr(df, "attrs") else None)
    eff_now = _to_ist_datetime(now_ist) if now_ist is not None else MarketCalendar.now_ist()
    if eff_now is None:
        eff_now = MarketCalendar.now_ist()

    keep_mask = [
        _is_candle_complete(row, timeframe=eff_tf, now_ist=eff_now)
        for _, row in df.iterrows()
    ]
    filtered = df.loc[keep_mask].copy().reset_index(drop=True)
    if hasattr(df, "attrs") and isinstance(df.attrs, dict):
        filtered.attrs = dict(df.attrs)
    if eff_tf:
        filtered.attrs["timeframe"] = eff_tf
    filtered.attrs["incomplete_candles_excluded"] = int(len(df) - len(filtered))
    return filtered


# ---------------------------------------------------------------------------
# 1. Higher Timeframe (HTF) Analysis — 1H & 15M
# ---------------------------------------------------------------------------
def analyze_htf_bias(
    df_1h: Optional[pd.DataFrame],
    df_15m: Optional[pd.DataFrame],
    symbol: str,
    ltp: float,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Evaluates Higher Timeframe (HTF) directional bias across 1H and 15M.
    Returns normalized bias score (0.0 to 1.0) and directional state.
    """
    cfg = config or DEFAULT_MTF_CONFIG
    details: List[str] = []

    df_15m = filter_completed_candles(df_15m, timeframe="15m")
    df_1h = filter_completed_candles(df_1h, timeframe="1h")

    # 15M is mandatory for directional activation
    has_15m = df_15m is not None and not df_15m.empty and len(df_15m) >= cfg["min_bars_15m"]
    has_1h = df_1h is not None and not df_1h.empty and len(df_1h) >= cfg["min_bars_1h"]

    if not has_15m:
        return {
            "direction": "UNKNOWN",
            "score": 0.0,
            "has_15m": False,
            "has_1h": has_1h,
            "adx_15m": None,
            "ema_alignment_15m": "UNKNOWN",
            "vwap_alignment_15m": "UNKNOWN",
            "details": ["15M timeframe unavailable or insufficient bars. Directional trading locked."],
        }

    # Ensure 15M indicators
    p_15m = process_candlestick_series(df_15m, symbol=symbol)
    vwap_15m = p_15m.get("vwap")
    ema20_15m = p_15m.get("ema20")
    ema50_15m = p_15m.get("ema50")
    adx_15m = p_15m.get("adx")
    plus_di_15m = p_15m.get("plus_di")
    minus_di_15m = p_15m.get("minus_di")

    bull_points_15m = 0
    bear_points_15m = 0

    close_15m = float(df_15m["close"].iloc[-1])
    open_15m = float(df_15m["open"].iloc[0])

    # 15M Price Slope / Change
    if close_15m > open_15m:
        bull_points_15m += 1
        details.append(f"15M: Net positive slope (+{close_15m - open_15m:.1f} pts)")
    elif close_15m < open_15m:
        bear_points_15m += 1
        details.append(f"15M: Net negative slope ({close_15m - open_15m:.1f} pts)")

    # Price vs VWAP
    if vwap_15m:
        if close_15m > vwap_15m or ltp > vwap_15m:
            bull_points_15m += 1
            details.append(f"15M: Price above VWAP (₹{vwap_15m:.1f})")
        else:
            bear_points_15m += 1
            details.append(f"15M: Price below VWAP (₹{vwap_15m:.1f})")

    # EMA 20/50 alignment or EMA 20 relationship
    if ema20_15m and ema50_15m:
        if ema20_15m > ema50_15m:
            bull_points_15m += 1
            details.append("15M: EMA 20 > EMA 50 (Bullish alignment)")
        elif ema20_15m < ema50_15m:
            bear_points_15m += 1
            details.append("15M: EMA 20 < EMA 50 (Bearish alignment)")
    elif ema20_15m:
        if close_15m > ema20_15m:
            bull_points_15m += 1
            details.append("15M: Close > EMA 20 (Bullish bias)")
        elif close_15m < ema20_15m:
            bear_points_15m += 1
            details.append("15M: Close < EMA 20 (Bearish bias)")

    # ADX & DI dominance
    if adx_15m and adx_15m >= cfg["adx_trend_threshold"]:
        if plus_di_15m is not None and minus_di_15m is not None:
            if plus_di_15m > minus_di_15m:
                bull_points_15m += 1
                details.append(f"15M: ADX {adx_15m:.1f} confirming Bullish (+DI > -DI)")
            elif minus_di_15m > plus_di_15m:
                bear_points_15m += 1
                details.append(f"15M: ADX {adx_15m:.1f} confirming Bearish (-DI > +DI)")

    # 1H Confirmation (if available)
    bull_points_1h = 0
    bear_points_1h = 0
    if has_1h and df_1h is not None:
        p_1h = process_candlestick_series(df_1h, symbol=symbol)
        ema20_1h = p_1h.get("ema20")
        ema50_1h = p_1h.get("ema50")
        close_1h = float(df_1h["close"].iloc[-1])
        open_1h = float(df_1h["open"].iloc[0])

        if close_1h > open_1h:
            bull_points_1h += 1
        elif close_1h < open_1h:
            bear_points_1h += 1

        if ema20_1h and close_1h > ema20_1h:
            bull_points_1h += 1
            details.append("1H: Price above EMA 20")
        elif ema20_1h and close_1h < ema20_1h:
            bear_points_1h += 1
            details.append("1H: Price below EMA 20")

        if ema20_1h and ema50_1h:
            if ema20_1h > ema50_1h:
                bull_points_1h += 1
                details.append("1H: EMA 20 > EMA 50 Bullish trend")
            elif ema20_1h < ema50_1h:
                bear_points_1h += 1
                details.append("1H: EMA 20 < EMA 50 Bearish trend")
    else:
        details.append("1H: Unavailable or warm-up. HTF score evaluated solely on 15M.")

    # Synthesize Direction
    total_bull = bull_points_15m + bull_points_1h
    total_bear = bear_points_15m + bear_points_1h

    if total_bull > total_bear and total_bull >= 1:
        direction = "BULLISH"
        score = min(1.0, 0.4 + (total_bull * 0.15))
    elif total_bear > total_bull and total_bear >= 1:
        direction = "BEARISH"
        score = min(1.0, 0.4 + (total_bear * 0.15))
    else:
        direction = "NEUTRAL"
        score = 0.3

    return {
        "direction": direction,
        "score": round(score, 2),
        "has_15m": True,
        "has_1h": has_1h,
        "adx_15m": adx_15m,
        "ema_alignment_15m": "BULLISH" if bull_points_15m > bear_points_15m else ("BEARISH" if bear_points_15m > bull_points_15m else "NEUTRAL"),
        "vwap_alignment_15m": "ABOVE" if vwap_15m and ltp > vwap_15m else "BELOW",
        "details": details,
    }


# ---------------------------------------------------------------------------
# 2. Intermediate Timeframe (ITF) Analysis — 5M Structure
# ---------------------------------------------------------------------------
def analyze_itf_5m_structure(
    df_5m: Optional[pd.DataFrame],
    symbol: str,
    ltp: float,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Evaluates 5M Market Structure:
    - Higher-High / Higher-Low or Lower-High / Lower-Low sequences
    - Break of Structure (BOS) on candle body closes
    - Change of Character (CHoCH)
    - Liquidity sweeps & institutional displacement
    """
    cfg = config or DEFAULT_MTF_CONFIG
    details: List[str] = []

    raw_len = len(df_5m) if df_5m is not None else 0
    eval_df = filter_completed_candles(df_5m, timeframe="5m")
    if eval_df is not None and len(eval_df) < raw_len:
        details.append("5M: Incomplete or future candle(s) excluded; relying strictly on prior confirmed closed bar.")

    if eval_df is None or eval_df.empty or len(eval_df) < cfg["min_bars_5m"] or len(eval_df) < 5:
        return {
            "direction": "UNKNOWN",
            "score": 0.0,
            "has_5m": False,
            "bos_detected": False,
            "choch_detected": False,
            "liquidity_sweep": False,
            "displacement": False,
            "swing_high": 0.0,
            "swing_low": 0.0,
            "atr_5m": 0.0,
            "details": details + ["5M: Insufficient confirmed closed bars. Execution locked."],
        }

    p_5m = process_candlestick_series(eval_df, symbol=symbol)
    atr = p_5m.get("atr") or float((eval_df["high"] - eval_df["low"]).mean())
    recent = eval_df.tail(min(len(eval_df), 15))

    # Swing high/low determination from confirmed bars
    swing_high = float(recent["high"].iloc[:-1].max()) if len(recent) > 2 else float(recent["high"].max())
    swing_low = float(recent["low"].iloc[:-1].min()) if len(recent) > 2 else float(recent["low"].min())

    last_close = float(eval_df["close"].iloc[-1])
    last_open = float(eval_df["open"].iloc[-1])
    last_high = float(eval_df["high"].iloc[-1])
    last_low = float(eval_df["low"].iloc[-1])
    body_size = abs(last_close - last_open)

    # 1. Break of Structure (BOS)
    bos_bullish = last_close > swing_high
    bos_bearish = last_close < swing_low

    # 2. Displacement Confirmation (Institutional expansion bar)
    is_displacement = body_size >= (atr * cfg["displacement_body_atr_mult"])

    # 3. Liquidity Sweep Detection (wick swept high/low but closed back inside)
    upper_wick = last_high - max(last_open, last_close)
    lower_wick = min(last_open, last_close) - last_low
    candle_range = max(1.0, last_high - last_low)

    bearish_sweep = (last_high > swing_high) and (last_close < swing_high) and (upper_wick / candle_range >= cfg["liquidity_wick_ratio"])
    bullish_sweep = (last_low < swing_low) and (last_close > swing_low) and (lower_wick / candle_range >= cfg["liquidity_wick_ratio"])

    # 4. CHoCH / Market Structure Shift
    choch_bullish = False
    choch_bearish = False
    if len(eval_df) >= 8:
        # Prior 3 candles trending down, now aggressive close above local swing
        prior_closes = eval_df["close"].iloc[-5:-1]
        if prior_closes.is_monotonic_decreasing and last_close > swing_high:
            choch_bullish = True
        elif prior_closes.is_monotonic_increasing and last_close < swing_low:
            choch_bearish = True

    # Direction and Confluence Scoring for 5M Structure
    direction = "NEUTRAL"
    score = 0.2

    if bos_bullish or choch_bullish:
        direction = "BULLISH"
        score = 0.70
        if is_displacement:
            score += 0.20
            details.append("5M: Bullish BOS with strong institutional displacement.")
        else:
            details.append("5M: Bullish BOS / structure break confirmed.")
        if bullish_sweep:
            score += 0.10
            details.append("5M: Liquidity sweep of lows confirmed prior to expansion.")
    elif bos_bearish or choch_bearish:
        direction = "BEARISH"
        score = 0.70
        if is_displacement:
            score += 0.20
            details.append("5M: Bearish BOS with strong institutional displacement.")
        else:
            details.append("5M: Bearish BOS / breakdown confirmed.")
        if bearish_sweep:
            score += 0.10
            details.append("5M: Liquidity sweep of highs confirmed prior to breakdown.")
    elif last_close > swing_low and last_close > (swing_high + swing_low) / 2.0:
        # Holding upper half of 5M swing structure
        direction = "BULLISH"
        score = 0.50
        details.append(f"5M: Structure leaning Bullish (Trading at ₹{last_close:.1f}, above midpoint ₹{(swing_high+swing_low)/2:.1f}).")
    elif last_close < swing_high and last_close < (swing_high + swing_low) / 2.0:
        # Holding lower half of 5M swing structure
        direction = "BEARISH"
        score = 0.50
        details.append(f"5M: Structure leaning Bearish (Trading at ₹{last_close:.1f}, below midpoint ₹{(swing_high+swing_low)/2:.1f}).")
    else:
        direction = "SIDEWAYS"
        score = 0.30
        details.append(f"5M: Compressed inside range ₹{swing_low:.1f} — ₹{swing_high:.1f}.")

    return {
        "direction": direction,
        "score": round(min(1.0, score), 2),
        "has_5m": True,
        "bos_detected": bool(bos_bullish or bos_bearish),
        "choch_detected": bool(choch_bullish or choch_bearish),
        "liquidity_sweep": bool(bullish_sweep or bearish_sweep),
        "displacement": bool(is_displacement),
        "swing_high": swing_high,
        "swing_low": swing_low,
        "atr_5m": atr,
        "details": details,
    }


# ---------------------------------------------------------------------------
# 3. Lower Timeframe (LTF) Analysis — 1M / 3M Execution Trigger
# ---------------------------------------------------------------------------
def analyze_ltf_trigger(
    df_1m: Optional[pd.DataFrame],
    df_3m: Optional[pd.DataFrame],
    itf_5m_result: Dict[str, Any],
    symbol: str,
    ltp: float,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Evaluates Lower Timeframe (LTF) execution trigger.
    - Uses 1M confirmed closed candle for micro entry trigger.
    - If 1M missing, allows clearly validated 5M fallback ('FALLBACK_5M_TRIGGER').
    - If 3M is missing, do not fabricate or interpolate.
    - Rejects live incomplete candles.
    """
    cfg = config or DEFAULT_MTF_CONFIG
    details: List[str] = []

    raw_1m_len = len(df_1m) if df_1m is not None else 0
    eval_1m = filter_completed_candles(df_1m, timeframe="1m")
    eval_3m = filter_completed_candles(df_3m, timeframe="3m")

    has_1m = eval_1m is not None and not eval_1m.empty and len(eval_1m) >= cfg["min_bars_1m"]
    has_3m = eval_3m is not None and not eval_3m.empty and len(eval_3m) >= 5

    # 1. 1M Primary Trigger Execution
    if has_1m and eval_1m is not None:
        if len(eval_1m) < raw_1m_len:
            details.append("1M: Forming or future candle(s) excluded; evaluating confirmed completed bar.")

        if len(eval_1m) < 4:
            return {
                "triggered": False,
                "direction": "NONE",
                "trigger_type": "INSUFFICIENT_1M_BARS",
                "entry_price": ltp,
                "invalidation_price": 0.0,
                "score": 0.0,
                "is_fallback_5m": False,
                "has_1m": False,
                "has_3m": has_3m,
                "details": ["1M: Insufficient confirmed bars."],
            }

        c_last = float(eval_1m["close"].iloc[-1])
        o_last = float(eval_1m["open"].iloc[-1])
        h_last = float(eval_1m["high"].iloc[-1])
        l_last = float(eval_1m["low"].iloc[-1])
        recent_1m = eval_1m.tail(min(len(eval_1m), 8))
        micro_high = float(recent_1m["high"].iloc[:-1].max())
        micro_low = float(recent_1m["low"].iloc[:-1].min())

        is_bull_1m = (c_last > o_last) and (c_last >= micro_high)
        is_bear_1m = (c_last < o_last) and (c_last <= micro_low)

        if is_bull_1m:
            details.append(f"1M: Micro bullish expansion confirmed above ₹{micro_high:.1f}.")
            return {
                "triggered": True,
                "direction": "BULLISH",
                "trigger_type": "1M_MICRO_BREAKOUT",
                "entry_price": c_last,
                "invalidation_price": l_last,
                "score": 0.85,
                "is_fallback_5m": False,
                "has_1m": True,
                "has_3m": has_3m,
                "details": details,
            }
        elif is_bear_1m:
            details.append(f"1M: Micro bearish breakdown confirmed below ₹{micro_low:.1f}.")
            return {
                "triggered": True,
                "direction": "BEARISH",
                "trigger_type": "1M_MICRO_BREAKDOWN",
                "entry_price": c_last,
                "invalidation_price": h_last,
                "score": 0.85,
                "is_fallback_5m": False,
                "has_1m": True,
                "has_3m": has_3m,
                "details": details,
            }
        else:
            details.append("1M: No active micro trigger; consolidation observed.")
            return {
                "triggered": False,
                "direction": "NONE",
                "trigger_type": "1M_CONSOLIDATING",
                "entry_price": ltp,
                "invalidation_price": 0.0,
                "score": 0.35,
                "is_fallback_5m": False,
                "has_1m": True,
                "has_3m": has_3m,
                "details": details,
            }

    # 2. 1M Missing: Validated 5M Fallback Policy
    if itf_5m_result.get("has_5m") and itf_5m_result.get("direction") in ["BULLISH", "BEARISH"] and (
        itf_5m_result.get("bos_detected") or itf_5m_result.get("choch_detected") or itf_5m_result.get("displacement")
    ):
        direction = itf_5m_result["direction"]
        entry = ltp
        inval = itf_5m_result["swing_low"] if direction == "BULLISH" else itf_5m_result["swing_high"]
        details.append(f"1M Missing: Activated FALLBACK_5M_TRIGGER on confirmed 5M {direction} structure break.")
        return {
            "triggered": True,
            "direction": direction,
            "trigger_type": "FALLBACK_5M_TRIGGER",
            "entry_price": entry,
            "invalidation_price": inval,
            "score": 0.65,  # Slightly lower score due to fallback trigger
            "is_fallback_5m": True,
            "has_1m": False,
            "has_3m": has_3m,
            "details": details,
        }

    # No LTF trigger available
    details.append("1M Unavailable and 5M does not meet strict displacement fallback criteria.")
    return {
        "triggered": False,
        "direction": "NONE",
        "trigger_type": "NO_TRIGGER",
        "entry_price": ltp,
        "invalidation_price": 0.0,
        "score": 0.0,
        "is_fallback_5m": False,
        "has_1m": False,
        "has_3m": has_3m,
        "details": details,
    }


# ---------------------------------------------------------------------------
# 4. Master Multi-Timeframe Confluence Synthesis
# ---------------------------------------------------------------------------
def evaluate_multi_timeframe_confluence(
    symbol: str,
    timeframe_candles: Dict[str, pd.DataFrame],
    current_quote: Dict[str, Any],
    option_chain_summary: Optional[Dict[str, Any]] = None,
    vix_value: float = 13.5,
    is_live_data: bool = True,
    data_quality_status: str = "VERIFIED_LIVE",
    market_regime_state: Optional[Dict[str, Any]] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Synthesizes HTF, ITF, and LTF into a deterministic confluence score and directional bias.
    """
    cfg = config or DEFAULT_MTF_CONFIG
    clean_sym = symbol.upper().strip()
    ltp = float(current_quote.get("currentPrice") or current_quote.get("ltp", 0.0))

    missing_timeframes: List[str] = []
    active_fallbacks: List[str] = []
    timeframe_conflicts: List[str] = []
    rejection_reasons: List[str] = []

    # Normalize timeframe candle keys; retain raw frames for analyzer detail reporting
    # while checking availability and standalone indicators strictly on confirmed completed bars
    raw_tf: Dict[str, Optional[pd.DataFrame]] = {
        _normalize_timeframe_key(k): v for k, v in timeframe_candles.items()
    }
    closed_tf: Dict[str, Optional[pd.DataFrame]] = {
        tf: filter_completed_candles(v, timeframe=tf) for tf, v in raw_tf.items()
    }

    df_1h = raw_tf.get("1h")
    df_15m = raw_tf.get("15m")
    df_5m = raw_tf.get("5m")
    df_3m = raw_tf.get("3m")
    df_1m = raw_tf.get("1m")

    df_1h_closed = closed_tf.get("1h")
    df_15m_closed = closed_tf.get("15m")
    df_5m_closed = closed_tf.get("5m")
    df_3m_closed = closed_tf.get("3m")
    df_1m_closed = closed_tf.get("1m")

    # Timeframe Availability Tracking (based strictly on confirmed completed bars)
    if df_1h_closed is None or df_1h_closed.empty:
        missing_timeframes.append("1H")
    if df_15m_closed is None or df_15m_closed.empty:
        missing_timeframes.append("15M")
    if df_5m_closed is None or df_5m_closed.empty:
        missing_timeframes.append("5M")
    if df_3m_closed is None or df_3m_closed.empty:
        missing_timeframes.append("3M")
    if df_1m_closed is None or df_1m_closed.empty:
        missing_timeframes.append("1M")

    # 1. Evaluate Individual Timeframes (each analyzer filters via filter_completed_candles)
    htf_res = analyze_htf_bias(df_1h, df_15m, clean_sym, ltp, cfg)
    itf_res = analyze_itf_5m_structure(df_5m, clean_sym, ltp, cfg)
    ltf_res = analyze_ltf_trigger(df_1m, df_3m, itf_res, clean_sym, ltp, cfg)

    if ltf_res.get("is_fallback_5m"):
        active_fallbacks.append("FALLBACK_5M_TRIGGER")

    # 2. Check Execution Lockouts (Policies)
    can_activate_directional = True

    if "15M" in missing_timeframes or not htf_res["has_15m"]:
        can_activate_directional = False
        rejection_reasons.append("15M timeframe unavailable; directional trade activation is strictly locked.")

    if "5M" in missing_timeframes or not itf_res["has_5m"]:
        can_activate_directional = False
        rejection_reasons.append("5M timeframe unavailable; total execution lockout enforced.")

    if data_quality_status in ["STALE", "ANOMALOUS", "SYNTHETIC", "MOCK", "DATA_UNAVAILABLE", "DATA_OFFLINE", "DEGRADED"] or not is_live_data:
        can_activate_directional = False
        rejection_reasons.append(f"Phase 1 Data Quality rejection: status is '{data_quality_status}'.")

    # 3. Timeframe Conflicts Detection
    htf_dir = htf_res["direction"]
    itf_dir = itf_res["direction"]
    ltf_dir = ltf_res["direction"]

    if htf_dir in ["BULLISH", "BEARISH"] and itf_dir in ["BULLISH", "BEARISH"] and htf_dir != itf_dir:
        timeframe_conflicts.append(f"HTF/ITF Conflict: HTF is {htf_dir} while 5M structure is {itf_dir}.")
        can_activate_directional = False

    if itf_dir in ["BULLISH", "BEARISH"] and ltf_dir in ["BULLISH", "BEARISH"] and itf_dir != ltf_dir:
        timeframe_conflicts.append(f"ITF/LTF Conflict: 5M structure is {itf_dir} while micro trigger is {ltf_dir}.")

    # 4. Quantitative Feature Confirmation (10%)
    quant_score = 0.5
    if market_regime_state:
        regime_val = market_regime_state.get("market_regime")
        conf_val = float(market_regime_state.get("regime_confidence", 0.5))
        quant_score = conf_val
    else:
        # Evaluate standalone from confirmed 5M indicators
        p_5m = process_candlestick_series(df_5m_closed, symbol=clean_sym) if (df_5m_closed is not None and not df_5m_closed.empty) else {}
        adx_5m = p_5m.get("adx")
        if adx_5m and adx_5m >= cfg["adx_strong_trend"]:
            quant_score = 0.8
        elif adx_5m and adx_5m >= cfg["adx_trend_threshold"]:
            quant_score = 0.65
        else:
            quant_score = 0.40

    # 5. Options Context (5%)
    options_score = 0.5
    chain = option_chain_summary or {}
    pcr = float(chain.get("pcr", {}).get("pcrOi", 1.0)) if isinstance(chain.get("pcr"), dict) else (float(chain.get("pcr")) if isinstance(chain.get("pcr"), (int, float)) else None)
    if pcr is not None:
        if htf_dir == "BULLISH" and pcr >= 1.0:
            options_score = 0.85
        elif htf_dir == "BEARISH" and pcr <= 0.85:
            options_score = 0.85
        elif (htf_dir == "BULLISH" and pcr < 0.70) or (htf_dir == "BEARISH" and pcr > 1.30):
            options_score = 0.20
        else:
            options_score = 0.50

    # 6. Confluence Score Calculation (0.0 to 100.0)
    # Weighting: HTF 35%, ITF 30%, LTF 20%, Quant 10%, Options 5%
    raw_score = (
        (htf_res["score"] * cfg["weight_htf"]) +
        (itf_res["score"] * cfg["weight_itf"]) +
        (ltf_res["score"] * cfg["weight_ltf"]) +
        (quant_score * cfg["weight_quant"]) +
        (options_score * cfg["weight_options"])
    )

    # Apply Deductions & Penalties
    deductions = 0.0
    if timeframe_conflicts:
        deductions += cfg["penalty_htf_itf_conflict"]
    if data_quality_status in ["STALE", "ANOMALOUS", "SYNTHETIC", "MOCK", "DATA_UNAVAILABLE", "DATA_OFFLINE", "DEGRADED"]:
        deductions += cfg["penalty_data_degraded"]

    confluence_score = max(0.0, raw_score - deductions)

    # Policy: Missing 1H caps confluence score at 60/100
    if "1H" in missing_timeframes:
        confluence_score = min(confluence_score, cfg["cap_score_missing_1h"])

    confluence_score = round(min(100.0, confluence_score), 1)

    # 7. Synthesize Overall Directional Bias
    if htf_dir == itf_dir and htf_dir in ["BULLISH", "BEARISH"]:
        directional_bias = htf_dir
    elif timeframe_conflicts:
        directional_bias = "CONFLICTING"
    elif itf_dir in ["BULLISH", "BEARISH"]:
        directional_bias = itf_dir
    else:
        directional_bias = "NEUTRAL"

    return {
        "symbol": clean_sym,
        "confluence_score": confluence_score,
        "directional_bias": directional_bias,
        "can_activate_directional": can_activate_directional,
        "htf_bias": htf_res,
        "itf_structure": itf_res,
        "ltf_trigger": ltf_res,
        "quant_confirmation": {"score": quant_score},
        "options_context": {"score": options_score, "pcr": pcr},
        "missing_timeframes": missing_timeframes,
        "active_fallbacks": active_fallbacks,
        "timeframe_conflicts": timeframe_conflicts,
        "rejection_reasons": rejection_reasons,
        "data_quality_status": data_quality_status,
        "timestamp": MarketCalendar.format_ist_timestamp(),
    }
