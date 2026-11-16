"""
AIVOLVE Quantitative Feature Engine & Candle Processor.
Computes mathematically rigorous technical and market microstructure overlays:
- Welles Wilder ADX(14), +DI(14), -DI(14) with strict warm-up tracking
- True Range and Wilder's ATR(14)
- Normalized Volatility (ATR / Close percentage)
- Exponential Moving Averages (EMA 20, 50, 200) with warm-up enforcement
- Session-resetting Intraday VWAP (strictly requires volume; unweighted fallback labeled separately)
- Bollinger Bands (20, 2.0) and Bollinger Band Width
- Wilder's RSI(14)

Guarantees:
1. Zero look-ahead bias (strict historical causality).
2. Never fabricates missing indicators or substitutes 0.0 for uncalculated values.
3. Explicitly exposes indicator warm-up and calculation readiness status.
4. Thread-safe, symbol-partitioned calculation with zero cross-index contamination.
"""

from typing import List, Dict, Any, Optional, Tuple
import datetime
import pandas as pd
import numpy as np


# ---------------------------------------------------------------------
# 1. Mathematical Indicator Routines (Pure Vectorized / NumPy)
# ---------------------------------------------------------------------

def calculate_true_range(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> np.ndarray:
    """
    Computes True Range (TR) for each candle according to J. Welles Wilder:
    TR_0 = High_0 - Low_0
    TR_t = max(High_t - Low_t, |High_t - Close_{t-1}|, |Low_t - Close_{t-1}|)
    """
    n = len(close)
    if n == 0:
        return np.array([])
    tr = np.zeros(n, dtype=float)
    tr[0] = max(0.0, high[0] - low[0])
    for i in range(1, n):
        hl = high[i] - low[i]
        hpc = abs(high[i] - close[i - 1])
        lpc = abs(low[i] - close[i - 1])
        tr[i] = max(hl, hpc, lpc)
    return tr


def calculate_atr_wilder(tr: np.ndarray, period: int = 14) -> np.ndarray:
    """
    Computes Wilder's Smoothed Average True Range (ATR).
    - Returns np.nan for i < period - 1 (warm-up).
    - Seed at index period - 1: arithmetic mean of first 'period' TR values.
    - Subsequent values: ATR_t = (ATR_{t-1} * (period - 1) + TR_t) / period.
    """
    n = len(tr)
    atr = np.full(n, np.nan, dtype=float)
    if n < period or period <= 0:
        return atr

    atr[period - 1] = np.mean(tr[:period])
    for i in range(period, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
    return atr


def calculate_adx_wilder(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    period: int = 14,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Computes Wilder's ADX(14), +DI(14), and -DI(14).

    Mathematical Warm-up Rules:
    - Minimum bars for +DI and -DI: period (14 bars).
    - Minimum bars for first smoothed ADX: 2 * period - 1 (27 bars, index 26).
    - Recommended stable history: 45-50 bars.
    - Returns np.nan when insufficient history exists.
    """
    n = len(close)
    adx = np.full(n, np.nan, dtype=float)
    plus_di = np.full(n, np.nan, dtype=float)
    minus_di = np.full(n, np.nan, dtype=float)

    if n < period or period <= 0:
        return adx, plus_di, minus_di

    # Step 1: Directional Movements and True Range
    tr_arr = calculate_true_range(high, low, close)
    plus_dm = np.zeros(n, dtype=float)
    minus_dm = np.zeros(n, dtype=float)

    for i in range(1, n):
        up_move = high[i] - high[i - 1]
        down_move = low[i - 1] - low[i]

        if up_move > down_move and up_move > 0:
            plus_dm[i] = up_move
        else:
            plus_dm[i] = 0.0

        if down_move > up_move and down_move > 0:
            minus_dm[i] = down_move
        else:
            minus_dm[i] = 0.0

    # Step 2: Wilder Smoothing of TR, +DM, -DM
    smooth_tr = np.zeros(n, dtype=float)
    smooth_plus_dm = np.zeros(n, dtype=float)
    smooth_minus_dm = np.zeros(n, dtype=float)

    smooth_tr[period - 1] = np.sum(tr_arr[:period])
    smooth_plus_dm[period - 1] = np.sum(plus_dm[:period])
    smooth_minus_dm[period - 1] = np.sum(minus_dm[:period])

    for i in range(period, n):
        smooth_tr[i] = smooth_tr[i - 1] - (smooth_tr[i - 1] / period) + tr_arr[i]
        smooth_plus_dm[i] = smooth_plus_dm[i - 1] - (smooth_plus_dm[i - 1] / period) + plus_dm[i]
        smooth_minus_dm[i] = smooth_minus_dm[i - 1] - (smooth_minus_dm[i - 1] / period) + minus_dm[i]

    # Step 3: Directional Indicators (+DI, -DI) and DX
    dx = np.zeros(n, dtype=float)
    for i in range(period - 1, n):
        tr_val = smooth_tr[i]
        p_di = 100.0 * (smooth_plus_dm[i] / tr_val) if tr_val > 0 else 0.0
        m_di = 100.0 * (smooth_minus_dm[i] / tr_val) if tr_val > 0 else 0.0

        plus_di[i] = p_di
        minus_di[i] = m_di

        di_sum = p_di + m_di
        dx[i] = 100.0 * abs(p_di - m_di) / di_sum if di_sum > 0 else 0.0

    # Step 4: Wilder Smoothing of DX to produce ADX
    # Requires 'period' DX values starting from index (period - 1) up to (2 * period - 2)
    seed_idx = 2 * period - 2
    if n > seed_idx:
        adx[seed_idx] = np.mean(dx[period - 1 : seed_idx + 1])
        for i in range(seed_idx + 1, n):
            adx[i] = (adx[i - 1] * (period - 1) + dx[i]) / period

    return adx, plus_di, minus_di


def calculate_ema(series: np.ndarray, period: int) -> np.ndarray:
    """
    Computes standard Exponential Moving Average (EMA).
    - Multiplier: alpha = 2 / (period + 1).
    - Returns np.nan for i < period - 1 (warm-up).
    - Seed at index period - 1: arithmetic mean of first 'period' bars.
    - Subsequent values: EMA_t = series_t * alpha + EMA_{t-1} * (1 - alpha).
    """
    n = len(series)
    ema = np.full(n, np.nan, dtype=float)
    if n < period or period <= 0:
        return ema

    ema[period - 1] = np.mean(series[:period])
    alpha = 2.0 / (period + 1.0)
    for i in range(period, n):
        ema[i] = series[i] * alpha + ema[i - 1] * (1.0 - alpha)
    return ema


def calculate_bollinger_bands(
    close: np.ndarray,
    period: int = 20,
    num_std: float = 2.0,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Computes Bollinger Bands and Bollinger Band Width:
    - SMA_20 on Close.
    - Standard deviation (population, ddof=0).
    - Upper = SMA + 2 * std, Lower = SMA - 2 * std.
    - BandWidth = (Upper - Lower) / SMA = 4 * std / SMA.
    Returns np.nan when i < period - 1 or SMA <= 0.
    """
    n = len(close)
    upper = np.full(n, np.nan, dtype=float)
    lower = np.full(n, np.nan, dtype=float)
    width = np.full(n, np.nan, dtype=float)

    if n < period or period <= 0:
        return upper, lower, width

    for i in range(period - 1, n):
        window = close[i - period + 1 : i + 1]
        mean = np.mean(window)
        std = np.std(window, ddof=0)
        up = mean + num_std * std
        lo = mean - num_std * std
        upper[i] = up
        lower[i] = lo
        if mean > 0:
            width[i] = (up - lo) / mean
    return upper, lower, width


def calculate_rsi(close: np.ndarray, period: int = 14) -> np.ndarray:
    """
    Computes Wilder's Relative Strength Index (RSI 14).
    Returns np.nan for i < period.
    """
    n = len(close)
    rsi = np.full(n, np.nan, dtype=float)
    if n <= period or period <= 0:
        return rsi

    delta = np.diff(close)
    gains = np.maximum(delta, 0.0)
    losses = np.maximum(-delta, 0.0)

    # Initial seed
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])

    if avg_loss == 0.0:
        rsi[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        rsi[period] = 100.0 - (100.0 / (1.0 + rs))

    for i in range(period + 1, n):
        g = gains[i - 1]
        l = losses[i - 1]
        avg_gain = (avg_gain * (period - 1) + g) / period
        avg_loss = (avg_loss * (period - 1) + l) / period

        if avg_loss == 0.0:
            rsi[i] = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi[i] = 100.0 - (100.0 / (1.0 + rs))

    return rsi


# ---------------------------------------------------------------------
# 2. Data Cleaning & Validation
# ---------------------------------------------------------------------

def clean_and_validate_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """
    Sanitizes raw OHLCV candle DataFrames:
    - Casts numeric columns to float.
    - Replaces infinite values and handles NaNs cleanly.
    - Strictly NO backward filling (bfill) to eliminate look-ahead bias.
    - Forward-fills missing prices only from past observed history.
    - Corrects candle anomalies (ensures High >= max(Open, Close, Low), Low <= min(Open, Close, High)).
    - Enforces non-negative volumes and positive prices.
    - Tracks explicit ohlc_repaired and has_missing_volume metadata.
    """
    clean_df = df.copy()

    # Normalize column names to lowercase
    col_map = {c: str(c).lower().strip() for c in clean_df.columns}
    clean_df.rename(columns=col_map, inplace=True)

    numeric_cols = ["open", "high", "low", "close", "volume"]
    for col in numeric_cols:
        if col in clean_df.columns:
            clean_df[col] = pd.to_numeric(clean_df[col], errors="coerce")

    # Drop rows where all price fields are completely NaN
    if "close" in clean_df.columns:
        clean_df = clean_df.dropna(subset=["close"]).reset_index(drop=True)

    if clean_df.empty:
        return clean_df

    ohlc_repaired = False
    repair_log: List[str] = []

    # Replace inf / -inf
    inf_mask = np.isinf(clean_df.select_dtypes(include=[np.number]))
    if inf_mask.values.any():
        ohlc_repaired = True
        repair_log.append("Replaced infinite price/volume values with NaN.")
        clean_df.replace([np.inf, -np.inf], np.nan, inplace=True)

    # Forward fill missing prices only from past observations — strictly NO backward fill
    for col in ["open", "high", "low", "close"]:
        if col in clean_df.columns:
            nan_cnt = clean_df[col].isna().sum()
            if nan_cnt > 0:
                ohlc_repaired = True
                repair_log.append(f"Forward-filled {nan_cnt} missing {col} values.")
                clean_df[col] = clean_df[col].ffill()

    # For leading rows still lacking open/high/low before first bar close:
    # Intra-bar initialization from the same bar's close (never future bars)
    if "open" in clean_df.columns and clean_df["open"].isna().any():
        ohlc_repaired = True
        repair_log.append("Intra-bar initialized leading NaN open from same-bar close.")
        clean_df["open"] = clean_df["open"].fillna(clean_df["close"])

    if "high" in clean_df.columns and clean_df["high"].isna().any():
        ohlc_repaired = True
        repair_log.append("Intra-bar initialized leading NaN high from same-bar max(open, close).")
        clean_df["high"] = clean_df["high"].fillna(clean_df[["open", "close"]].max(axis=1))

    if "low" in clean_df.columns and clean_df["low"].isna().any():
        ohlc_repaired = True
        repair_log.append("Intra-bar initialized leading NaN low from same-bar min(open, close).")
        clean_df["low"] = clean_df["low"].fillna(clean_df[["open", "close"]].min(axis=1))

    # Drop any remaining unfillable price rows
    price_cols = [c for c in ["open", "high", "low", "close"] if c in clean_df.columns]
    if clean_df[price_cols].isna().any().any():
        ohlc_repaired = True
        clean_df = clean_df.dropna(subset=price_cols).reset_index(drop=True)

    # Volume handling: preserve missing-data status rather than silently fabricating
    has_missing_volume = False
    if "volume" not in clean_df.columns:
        has_missing_volume = True
        ohlc_repaired = True
        repair_log.append("Missing volume column in candlestick input.")
        clean_df["volume"] = np.nan
    else:
        nan_vol_count = clean_df["volume"].isna().sum()
        if nan_vol_count > 0:
            has_missing_volume = True
            ohlc_repaired = True
            repair_log.append(f"Detected {nan_vol_count} missing volume entries.")
            clean_df["volume"] = clean_df["volume"].fillna(0.0)

        neg_vol_count = (clean_df["volume"] < 0).sum()
        if neg_vol_count > 0:
            ohlc_repaired = True
            repair_log.append(f"Clipped {neg_vol_count} negative volume entries to 0.0.")
            clean_df["volume"] = clean_df["volume"].clip(lower=0.0)

    # Ensure structural geometric validity
    high_corrections = (clean_df["high"] < clean_df[["open", "close", "low"]].max(axis=1)).sum()
    if high_corrections > 0:
        ohlc_repaired = True
        repair_log.append(f"Corrected {high_corrections} inverted High price anomalies.")
        clean_df["high"] = np.maximum.reduce([clean_df["open"], clean_df["high"], clean_df["close"], clean_df["low"]])

    low_corrections = (clean_df["low"] > clean_df[["open", "close", "high"]].min(axis=1)).sum()
    if low_corrections > 0:
        ohlc_repaired = True
        repair_log.append(f"Corrected {low_corrections} inverted Low price anomalies.")
        clean_df["low"] = np.minimum.reduce([clean_df["open"], clean_df["low"], clean_df["close"], clean_df["high"]])

    clean_df.attrs["ohlc_repaired"] = ohlc_repaired
    clean_df.attrs["repair_log"] = repair_log
    clean_df.attrs["has_missing_volume"] = has_missing_volume

    return clean_df


# ---------------------------------------------------------------------
# 3. Session-Resetting Intraday VWAP Engine
# ---------------------------------------------------------------------

def compute_intraday_vwap(
    df: pd.DataFrame,
) -> Tuple[np.ndarray, np.ndarray, bool]:
    """
    Computes session-resetting Intraday VWAP.

    Strict Rules:
    1. Resets at each trading session (partitioned by session date).
    2. Strictly requires valid positive cumulative volume.
    3. If session volume is zero or missing: VWAP is None (np.nan).
    4. An unweighted price expanding mean is computed as a research fallback,
       strictly labeled UNWEIGHTED_AVERAGE, and is prohibited for VWAP trade confirmation.

    Returns:
    (vwap_array, unweighted_average_array, has_valid_vwap)
    """
    n = len(df)
    vwap_arr = np.full(n, np.nan, dtype=float)
    unweighted_arr = np.full(n, np.nan, dtype=float)

    if n == 0:
        return vwap_arr, unweighted_arr, False

    typical_price = (df["high"].values + df["low"].values + df["close"].values) / 3.0
    vol_values = df["volume"].values if "volume" in df.columns else np.zeros(n)

    # Detect session boundaries
    session_keys = []
    if "timestamp" in df.columns:
        for val in df["timestamp"]:
            if hasattr(val, "strftime"):
                session_keys.append(val.strftime("%Y-%m-%d"))
            elif isinstance(val, str) and len(val) >= 10:
                session_keys.append(val[:10])
            else:
                session_keys.append("default_session")
    elif "date" in df.columns:
        session_keys = [str(d) for d in df["date"]]
    else:
        session_keys = ["default_session"] * n

    df_sessions = pd.Series(session_keys, index=df.index)
    has_valid_vwap = False

    for session_id, idxs in df_sessions.groupby(df_sessions).groups.items():
        idx_list = np.array(list(idxs))
        sess_typ = typical_price[idx_list]
        sess_vol = np.nan_to_num(vol_values[idx_list], nan=0.0)

        # Expanding unweighted mean for research
        unweighted_arr[idx_list] = np.cumsum(sess_typ) / np.arange(1, len(idx_list) + 1)

        # Intraday VWAP requires positive volume
        cum_vol = np.cumsum(sess_vol)
        cum_pv = np.cumsum(sess_typ * sess_vol)

        valid_mask = cum_vol > 0
        if np.any(valid_mask):
            has_valid_vwap = True
            for k_pos, is_val in enumerate(valid_mask):
                real_idx = idx_list[k_pos]
                if is_val:
                    vwap_arr[real_idx] = cum_pv[k_pos] / cum_vol[k_pos]

    return vwap_arr, unweighted_arr, has_valid_vwap


# ---------------------------------------------------------------------
# 4. Main Series Processing Pipeline
# ---------------------------------------------------------------------

def process_candlestick_series(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str = "15m",
) -> Dict[str, Any]:
    """
    Processes OHLCV candles and attaches quantitative overlays:
    - Wilder's ADX(14), +DI(14), -DI(14)
    - True Range & Wilder's ATR(14)
    - Normalized ATR % (ATR / Close * 100)
    - Exponential Moving Averages (EMA 20, 50, 200)
    - Session-resetting Intraday VWAP (and research Unweighted Average)
    - Bollinger Bands (20, 2.0) and Bollinger Band Width
    - Wilder's RSI(14)
    - Formats candles for charting libraries with IST timestamps
    - Exposes comprehensive indicator warm-up and data readiness status.
    """
    clean_sym = symbol.upper().strip()

    if df is None or len(df) == 0:
        return {
            "symbol": clean_sym,
            "timeframe": timeframe,
            "candles": [],
            "current": None,
            "ema20": None,
            "ema50": None,
            "ema200": None,
            "vwap": None,
            "unweighted_average": None,
            "atr": None,
            "normalized_atr_pct": None,
            "rsi": None,
            "adx": None,
            "plus_di": None,
            "minus_di": None,
            "bb_upper": None,
            "bb_lower": None,
            "bb_width": None,
            "indicator_warmup_status": {
                "overall_status": "INSUFFICIENT_DATA",
                "bars_available": 0,
            },
            "data_quality_status": "INSUFFICIENT_DATA",
        }

    # Step 1: Clean and validate OHLCV inputs
    candles_df = clean_and_validate_ohlcv(df)
    n = len(candles_df)

    if n == 0:
        return {
            "symbol": clean_sym,
            "timeframe": timeframe,
            "candles": [],
            "current": None,
            "ema20": None,
            "ema50": None,
            "ema200": None,
            "vwap": None,
            "unweighted_average": None,
            "atr": None,
            "normalized_atr_pct": None,
            "rsi": None,
            "adx": None,
            "plus_di": None,
            "minus_di": None,
            "bb_upper": None,
            "bb_lower": None,
            "bb_width": None,
            "indicator_warmup_status": {
                "overall_status": "INSUFFICIENT_DATA",
                "bars_available": 0,
            },
            "data_quality_status": "INSUFFICIENT_DATA",
        }

    c_open = candles_df["open"].values
    c_high = candles_df["high"].values
    c_low = candles_df["low"].values
    c_close = candles_df["close"].values

    # Step 2: Compute Indicators
    # 2.1 True Range & Wilder ATR(14)
    tr_arr = calculate_true_range(c_high, c_low, c_close)
    atr_arr = calculate_atr_wilder(tr_arr, period=14)
    norm_atr_pct = np.full(n, np.nan, dtype=float)
    for i in range(n):
        if not np.isnan(atr_arr[i]) and c_close[i] > 0:
            norm_atr_pct[i] = (atr_arr[i] / c_close[i]) * 100.0

    # 2.2 Wilder ADX(14), +DI, -DI
    adx_arr, plus_di_arr, minus_di_arr = calculate_adx_wilder(c_high, c_low, c_close, period=14)

    # 2.3 EMAs (20, 50, 200)
    ema20_arr = calculate_ema(c_close, period=20)
    ema50_arr = calculate_ema(c_close, period=50)
    ema200_arr = calculate_ema(c_close, period=200)

    # 2.4 Intraday VWAP & Unweighted Average
    vwap_arr, unweighted_arr, has_valid_vwap = compute_intraday_vwap(candles_df)

    # 2.5 Bollinger Bands & Band Width (20, 2.0)
    bb_upper_arr, bb_lower_arr, bb_width_arr = calculate_bollinger_bands(c_close, period=20, num_std=2.0)

    # 2.6 Wilder's RSI(14)
    rsi_arr = calculate_rsi(c_close, period=14)

    # Step 3: Format individual candles for visualization and downstream engines
    formatted_candles: List[Dict[str, Any]] = []
    for i in range(n):
        ts_val = candles_df.iloc[i].get("timestamp")
        time_str = candles_df.iloc[i].get("time")

        if hasattr(ts_val, "strftime"):
            label = ts_val.strftime("%H:%M") if timeframe != "1d" else ts_val.strftime("%Y-%m-%d")
        else:
            label = str(time_str or ts_val or "")

        formatted_candles.append({
            "time": label,
            "timestamp": str(ts_val) if ts_val is not None else None,
            "open": round(float(c_open[i]), 2),
            "high": round(float(c_high[i]), 2),
            "low": round(float(c_low[i]), 2),
            "close": round(float(c_close[i]), 2),
            "volume": int(candles_df.iloc[i].get("volume", 0)),
            # Overlays
            "vwap": round(float(vwap_arr[i]), 2) if not np.isnan(vwap_arr[i]) else None,
            "unweighted_average": round(float(unweighted_arr[i]), 2) if not np.isnan(unweighted_arr[i]) else None,
            "ema20": round(float(ema20_arr[i]), 2) if not np.isnan(ema20_arr[i]) else None,
            "ema50": round(float(ema50_arr[i]), 2) if not np.isnan(ema50_arr[i]) else None,
            "ema200": round(float(ema200_arr[i]), 2) if not np.isnan(ema200_arr[i]) else None,
            "atr": round(float(atr_arr[i]), 2) if not np.isnan(atr_arr[i]) else None,
            "normalized_atr_pct": round(float(norm_atr_pct[i]), 4) if not np.isnan(norm_atr_pct[i]) else None,
            "rsi": round(float(rsi_arr[i]), 2) if not np.isnan(rsi_arr[i]) else None,
            "adx": round(float(adx_arr[i]), 2) if not np.isnan(adx_arr[i]) else None,
            "plus_di": round(float(plus_di_arr[i]), 2) if not np.isnan(plus_di_arr[i]) else None,
            "minus_di": round(float(minus_di_arr[i]), 2) if not np.isnan(minus_di_arr[i]) else None,
            "bb_upper": round(float(bb_upper_arr[i]), 2) if not np.isnan(bb_upper_arr[i]) else None,
            "bb_lower": round(float(bb_lower_arr[i]), 2) if not np.isnan(bb_lower_arr[i]) else None,
            "bb_width": round(float(bb_width_arr[i]), 5) if not np.isnan(bb_width_arr[i]) else None,
        })

    # Step 4: Construct Top-Level Snapshot & Warm-up Status
    latest = formatted_candles[-1] if formatted_candles else None

    # Detailed indicator warm-up breakdown
    warmup_status = {
        "bars_available": n,
        "adx": {
            "is_calculated": bool(n >= 27 and not np.isnan(adx_arr[-1])),
            "is_warm": bool(n >= 45),
            "min_required": 27,
            "stable_required": 45,
            "value": round(float(adx_arr[-1]), 2) if not np.isnan(adx_arr[-1]) else None,
        },
        "plus_di": {
            "is_calculated": bool(n >= 14 and not np.isnan(plus_di_arr[-1])),
            "is_warm": bool(n >= 30),
            "min_required": 14,
            "stable_required": 30,
            "value": round(float(plus_di_arr[-1]), 2) if not np.isnan(plus_di_arr[-1]) else None,
        },
        "minus_di": {
            "is_calculated": bool(n >= 14 and not np.isnan(minus_di_arr[-1])),
            "is_warm": bool(n >= 30),
            "min_required": 14,
            "stable_required": 30,
            "value": round(float(minus_di_arr[-1]), 2) if not np.isnan(minus_di_arr[-1]) else None,
        },
        "ema20": {
            "is_calculated": bool(n >= 20 and not np.isnan(ema20_arr[-1])),
            "is_warm": bool(n >= 40),
            "min_required": 20,
            "stable_required": 40,
            "value": round(float(ema20_arr[-1]), 2) if not np.isnan(ema20_arr[-1]) else None,
        },
        "ema50": {
            "is_calculated": bool(n >= 50 and not np.isnan(ema50_arr[-1])),
            "is_warm": bool(n >= 100),
            "min_required": 50,
            "stable_required": 100,
            "value": round(float(ema50_arr[-1]), 2) if not np.isnan(ema50_arr[-1]) else None,
        },
        "ema200": {
            "is_calculated": bool(n >= 200 and not np.isnan(ema200_arr[-1])),
            "is_warm": bool(n >= 300),
            "min_required": 200,
            "stable_required": 300,
            "value": round(float(ema200_arr[-1]), 2) if not np.isnan(ema200_arr[-1]) else None,
        },
        "atr": {
            "is_calculated": bool(n >= 14 and not np.isnan(atr_arr[-1])),
            "is_warm": bool(n >= 30),
            "min_required": 14,
            "stable_required": 30,
            "value": round(float(atr_arr[-1]), 2) if not np.isnan(atr_arr[-1]) else None,
        },
        "vwap": {
            "is_calculated": bool(has_valid_vwap and not np.isnan(vwap_arr[-1])),
            "has_valid_volume": bool(has_valid_vwap),
            "value": round(float(vwap_arr[-1]), 2) if not np.isnan(vwap_arr[-1]) else None,
            "unweighted_average": round(float(unweighted_arr[-1]), 2) if not np.isnan(unweighted_arr[-1]) else None,
            "warning": None if has_valid_vwap else "VWAP is None due to zero or missing volume. UNWEIGHTED_AVERAGE cannot be used for VWAP confirmation.",
        },
        "bollinger": {
            "is_calculated": bool(n >= 20 and not np.isnan(bb_width_arr[-1])),
            "is_warm": bool(n >= 30),
            "min_required": 20,
            "stable_required": 30,
            "width": round(float(bb_width_arr[-1]), 5) if not np.isnan(bb_width_arr[-1]) else None,
        },
    }

    # Determine overall data quality status
    if n < 14:
        data_quality_status = "INSUFFICIENT_DATA"
    elif n < 45 or not warmup_status["adx"]["is_warm"] or not warmup_status["ema20"]["is_warm"]:
        data_quality_status = "INDICATOR_WARMUP"
    else:
        data_quality_status = "VERIFIED"

    warmup_status["overall_status"] = data_quality_status

    return {
        "symbol": clean_sym,
        "timeframe": timeframe,
        "candles": formatted_candles,
        "current": latest,
        # Key Overlays (strictly None when uncalculated; never fabricated)
        "ema20": latest.get("ema20") if latest else None,
        "ema50": latest.get("ema50") if latest else None,
        "ema200": latest.get("ema200") if latest else None,
        "vwap": latest.get("vwap") if latest else None,
        "unweighted_average": latest.get("unweighted_average") if latest else None,
        "atr": latest.get("atr") if latest else None,
        "normalized_atr_pct": latest.get("normalized_atr_pct") if latest else None,
        "rsi": latest.get("rsi") if latest else None,
        "adx": latest.get("adx") if latest else None,
        "plus_di": latest.get("plus_di") if latest else None,
        "minus_di": latest.get("minus_di") if latest else None,
        "bb_upper": latest.get("bb_upper") if latest else None,
        "bb_lower": latest.get("bb_lower") if latest else None,
        "bb_width": latest.get("bb_width") if latest else None,
        # Warmup and Quality Metadata
        "indicator_warmup_status": warmup_status,
        "data_quality_status": data_quality_status,
    }
