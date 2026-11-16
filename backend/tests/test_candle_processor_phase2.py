import numpy as np
import pandas as pd
import pytest

from app.options.candle_processor import (
    process_candlestick_series,
    calculate_true_range,
    calculate_atr_wilder,
    calculate_adx_wilder,
    calculate_ema,
    calculate_bollinger_bands,
    calculate_rsi,
    clean_and_validate_ohlcv,
    compute_intraday_vwap,
)


# =====================================================================
# 1. True Range & Wilder's ATR(14)
# =====================================================================

def test_true_range_and_atr_correctness():
    """Verify True Range captures gap up/down and ATR uses Wilder smoothing without fabrication."""
    highs = np.array([100.0, 105.0, 103.0, 110.0])
    lows = np.array([95.0, 101.0, 98.0, 104.0])
    closes = np.array([98.0, 102.0, 99.0, 108.0])

    tr = calculate_true_range(highs, lows, closes)
    # TR[0] = 100 - 95 = 5.0
    assert tr[0] == 5.0
    # TR[1] = max(105-101=4, |105-98|=7, |101-98|=3) = 7.0 (gap up)
    assert tr[1] == 7.0
    # TR[2] = max(103-98=5, |103-102|=1, |98-102|=4) = 5.0
    assert tr[2] == 5.0

    # Test Wilder ATR on series shorter than 14 bars -> must be all NaN (never fabricated default)
    short_tr = np.full(10, 5.0)
    short_atr = calculate_atr_wilder(short_tr, period=14)
    assert np.all(np.isnan(short_atr))

    # Test Wilder ATR on series of 20 bars with constant TR = 5.0
    const_tr = np.full(20, 5.0)
    atr = calculate_atr_wilder(const_tr, period=14)
    assert np.isnan(atr[12])  # 13th bar: NaN
    assert atr[13] == 5.0     # 14th bar: seed = mean of first 14 = 5.0
    assert atr[19] == 5.0     # subsequent bars stay at 5.0


def test_atr_warmup_and_normalized_atr_pct():
    """Verify ATR warm-up status and normalized ATR percentage."""
    n = 35
    closes = np.linspace(24000, 24500, n)
    highs = closes + 50.0
    lows = closes - 50.0
    opens = closes - 10.0
    vols = np.full(n, 1000)

    df = pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": closes, "volume": vols})
    res = process_candlestick_series(df, symbol="NIFTY 50", timeframe="15m")

    assert res["atr"] is not None
    assert res["atr"] > 0
    # Normalized ATR % = (ATR / Close) * 100
    expected_norm = round((res["atr"] / closes[-1]) * 100.0, 4)
    assert round(res["normalized_atr_pct"], 4) == expected_norm

    # For series < 14 bars: ATR must be None, NOT fabricated 15.0!
    short_df = df.iloc[:10].copy()
    short_res = process_candlestick_series(short_df, symbol="NIFTY 50", timeframe="15m")
    assert short_res["atr"] is None
    assert short_res["normalized_atr_pct"] is None
    assert short_res["indicator_warmup_status"]["atr"]["is_calculated"] is False


# =====================================================================
# 2. Wilder's ADX(14), +DI, -DI Directional Correctness
# =====================================================================

def test_adx_initialization_and_warmup_boundaries():
    """
    Mathematical Warm-up verification:
    - +DI and -DI become available at bar 14 (index 13).
    - ADX requires 14 DX values, meaning it becomes available at bar 27 (index 26).
    - Prior to bar 27, ADX must be None.
    """
    n = 35
    closes = np.linspace(100, 200, n)
    highs = closes + 2.0
    lows = closes - 2.0

    adx, p_di, m_di = calculate_adx_wilder(highs, lows, closes, period=14)

    # First non-nan +DI/-DI must be at index 13 (14th bar)
    assert np.isnan(p_di[12])
    assert not np.isnan(p_di[13])
    assert not np.isnan(m_di[13])

    # First non-nan ADX must be at index 26 (27th bar)
    assert np.isnan(adx[25])
    assert not np.isnan(adx[26])


def test_plus_di_minus_di_directional_correctness():
    """Strongly trending up series must have +DI > -DI; strongly trending down must have -DI > +DI."""
    n = 50
    # 1. Bullish trend: ascending stairs
    bull_closes = np.linspace(100, 250, n)
    bull_highs = bull_closes + 3.0
    bull_lows = bull_closes - 1.0
    adx_b, p_di_b, m_di_b = calculate_adx_wilder(bull_highs, bull_lows, bull_closes, period=14)

    assert p_di_b[-1] > m_di_b[-1]
    assert adx_b[-1] > 25.0  # Strong directional trend

    # 2. Bearish trend: descending stairs
    bear_closes = np.linspace(250, 100, n)
    bear_highs = bear_closes + 1.0
    bear_lows = bear_closes - 3.0
    adx_s, p_di_s, m_di_s = calculate_adx_wilder(bear_highs, bear_lows, bear_closes, period=14)

    assert m_di_s[-1] > p_di_s[-1]
    assert adx_s[-1] > 25.0  # Strong directional trend


# =====================================================================
# 3. EMA Warm-Up Boundaries (20, 50, 200)
# =====================================================================

def test_ema_warmup_boundaries_and_ema200_insufficient():
    """Verify EMA warm-up thresholds and that insufficient history strictly returns None."""
    # Case A: 30 bars (enough for EMA 20, but insufficient for EMA 50 & 200)
    c_30 = np.linspace(100, 130, 30)
    ema20_30 = calculate_ema(c_30, period=20)
    ema50_30 = calculate_ema(c_30, period=50)
    ema200_30 = calculate_ema(c_30, period=200)

    assert not np.isnan(ema20_30[-1])
    assert np.isnan(ema50_30[-1])
    assert np.isnan(ema200_30[-1])

    # Case B: 75 bars (enough for EMA 20 & 50, insufficient for EMA 200)
    c_75 = np.linspace(100, 175, 75)
    ema20_75 = calculate_ema(c_75, period=20)
    ema50_75 = calculate_ema(c_75, period=50)
    ema200_75 = calculate_ema(c_75, period=200)

    assert not np.isnan(ema20_75[-1])
    assert not np.isnan(ema50_75[-1])
    assert np.isnan(ema200_75[-1])

    # Case C: 250 bars (enough for all three EMAs)
    c_250 = np.linspace(100, 350, 250)
    ema20_250 = calculate_ema(c_250, period=20)
    ema50_250 = calculate_ema(c_250, period=50)
    ema200_250 = calculate_ema(c_250, period=200)

    assert not np.isnan(ema20_250[-1])
    assert not np.isnan(ema50_250[-1])
    assert not np.isnan(ema200_250[-1])


# =====================================================================
# 4. Intraday VWAP Session Reset & Missing-Volume Behavior
# =====================================================================

def test_vwap_session_reset_across_dates():
    """Verify VWAP resets cleanly at each trading session boundary and does not accumulate across days."""
    dates = ["2026-10-15"] * 3 + ["2026-10-16"] * 3
    vols = [100.0, 200.0, 100.0, 300.0, 300.0, 400.0]
    highs = [102.0, 104.0, 103.0, 202.0, 204.0, 203.0]
    lows = [98.0, 100.0, 99.0, 198.0, 200.0, 199.0]
    closes = [100.0, 102.0, 101.0, 200.0, 202.0, 201.0]

    df = pd.DataFrame({"timestamp": dates, "open": closes, "high": highs, "low": lows, "close": closes, "volume": vols})
    vwap, unweighted, has_vwap = compute_intraday_vwap(df)

    assert has_vwap is True
    # Day 1 final VWAP should be around 101.25
    assert 100.0 < vwap[2] < 103.0
    # Day 2 first bar MUST reset to Day 2 price (~200.0), NOT contaminated by Day 1 (~101.0)
    assert round(vwap[3], 1) == 200.0


def test_vwap_missing_or_zero_volume_behavior():
    """If volume is missing or all zero, VWAP must be None (never labeled as valid VWAP)."""
    n = 10
    prices = np.full(n, 100.0)
    df_no_vol = pd.DataFrame({"open": prices, "high": prices + 1, "low": prices - 1, "close": prices, "volume": 0.0})

    vwap, unweighted, has_vwap = compute_intraday_vwap(df_no_vol)
    assert has_vwap is False
    assert np.all(np.isnan(vwap))
    assert not np.all(np.isnan(unweighted))

    res = process_candlestick_series(df_no_vol, symbol="NIFTY 50")
    assert res["vwap"] is None
    assert res["unweighted_average"] == 100.0
    assert "VWAP is None due to zero or missing volume" in res["indicator_warmup_status"]["vwap"]["warning"]


# =====================================================================
# 5. Bollinger Bands & Band Width
# =====================================================================

def test_bollinger_band_width():
    """Verify Bollinger Band Width calculations and insufficient history behavior."""
    # Under 20 bars: all NaN
    c_short = np.full(15, 100.0)
    up, lo, width = calculate_bollinger_bands(c_short, period=20)
    assert np.all(np.isnan(width))

    # 25 bars with constant price 100.0 -> std = 0 -> width = 0.0
    c_const = np.full(25, 100.0)
    up_c, lo_c, width_c = calculate_bollinger_bands(c_const, period=20)
    assert width_c[19] == 0.0
    assert up_c[19] == 100.0
    assert lo_c[19] == 100.0

    # 25 bars with oscillating price -> width > 0
    c_osc = np.array([100.0 + (5.0 if i % 2 == 0 else -5.0) for i in range(25)])
    up_o, lo_o, width_o = calculate_bollinger_bands(c_osc, period=20)
    assert width_o[19] > 0.0
    assert up_o[19] > lo_o[19]


# =====================================================================
# 6. Data Cleaning & Anti-Lookahead Consistency
# =====================================================================

def test_nan_and_invalid_candle_handling():
    """Verify inverted high/low or negative volumes are sanitized without crashing."""
    df = pd.DataFrame([
        {"open": 100.0, "high": 90.0, "low": 110.0, "close": 105.0, "volume": -50.0},  # Inverted H/L, negative vol
        {"open": np.nan, "high": 120.0, "low": 95.0, "close": 115.0, "volume": np.nan},  # NaNs
    ])
    clean = clean_and_validate_ohlcv(df)

    assert len(clean) == 2
    assert clean["high"].iloc[0] >= clean["low"].iloc[0]
    assert clean["volume"].iloc[0] == 0.0
    assert not clean["open"].isna().any()


def test_anti_lookahead_consistency():
    """
    Strict anti-lookahead guarantee:
    Indicator values at bar index T must be bitwise/numerically identical
    whether calculated on the full dataset or on a dataset sliced up to T.
    """
    np.random.seed(123)
    n = 60
    closes = np.cumsum(np.random.normal(0.2, 1.0, n)) + 500.0
    highs = closes + np.random.uniform(0.5, 2.0, n)
    lows = closes - np.random.uniform(0.5, 2.0, n)
    opens = closes + np.random.uniform(-0.5, 0.5, n)
    vols = np.random.randint(100, 1000, n)

    full_df = pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": closes, "volume": vols})
    full_res = process_candlestick_series(full_df, symbol="NIFTY 50", timeframe="15m")

    # Evaluate prefix up to bar 40 (index 39)
    prefix_df = full_df.iloc[:40].copy()
    prefix_res = process_candlestick_series(prefix_df, symbol="NIFTY 50", timeframe="15m")

    candle_full_at_39 = full_res["candles"][39]
    candle_prefix_last = prefix_res["current"]

    # Verify all indicators at bar 39 match exactly
    for key in ["ema20", "ema50", "atr", "adx", "plus_di", "minus_di", "bb_width"]:
        val_full = candle_full_at_39[key]
        val_prefix = candle_prefix_last[key]
        if val_full is not None and val_prefix is not None:
            assert np.isclose(val_full, val_prefix, atol=1e-5), f"Mismatch in {key} at index 39!"


def test_independent_index_calculations():
    """Verify NIFTY and BANK NIFTY calculations do not leak state or mutate each other."""
    n = 50
    nifty_c = np.linspace(24000, 24500, n)
    nifty_df = pd.DataFrame({"open": nifty_c, "high": nifty_c + 20, "low": nifty_c - 20, "close": nifty_c, "volume": 5000})

    bank_c = np.linspace(51000, 52000, n)
    bank_df = pd.DataFrame({"open": bank_c, "high": bank_c + 50, "low": bank_c - 50, "close": bank_c, "volume": 8000})

    res_nifty = process_candlestick_series(nifty_df, symbol="NIFTY 50")
    res_bank = process_candlestick_series(bank_df, symbol="BANK NIFTY")

    assert res_nifty["symbol"] == "NIFTY 50"
    assert res_bank["symbol"] == "BANK NIFTY"
    assert res_nifty["current"]["close"] == 24500.0
    assert res_bank["current"]["close"] == 52000.0
    assert res_nifty["ema20"] != res_bank["ema20"]

