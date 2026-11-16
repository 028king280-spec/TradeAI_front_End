import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta

from app.options.market_state_engine import (
    evaluate_index_market_state,
    MarketRegime,
    MarketState,
)


# =====================================================================
# 1. Sideways Market Detection & False Bearish Elimination
# =====================================================================

def test_sideways_market_detection():
    """Verify range-bound, low-momentum price action is classified as SIDEWAYS with isNoTrade=True."""
    df = pd.DataFrame([
        {"timestamp": "2026-10-16 09:15:00", "open": 24500, "high": 24520, "low": 24490, "close": 24505, "volume": 1000},
        {"timestamp": "2026-10-16 09:30:00", "open": 24505, "high": 24515, "low": 24495, "close": 24500, "volume": 950},
        {"timestamp": "2026-10-16 09:45:00", "open": 24500, "high": 24510, "low": 24490, "close": 24502, "volume": 900},
        {"timestamp": "2026-10-16 10:00:00", "open": 24502, "high": 24515, "low": 24492, "close": 24504, "volume": 920},
    ])
    quote = {"currentPrice": 24504.0, "dayHigh": 24520.0, "dayLow": 24490.0, "previousClose": 24500.0, "change": 4.0}
    info = {"vwap": 24502.0, "ema20": 24503.0, "ema50": 24504.0, "atr": 25.0, "rsi": 50.0}

    res = evaluate_index_market_state(
        symbol="NIFTY 50",
        quote=quote,
        candles_df=df,
        candles_info=info,
        option_chain_summary={"pcr": {"pcrOi": 1.02}, "callWall": 24600, "putWall": 24400, "maxPain": {"maxPainStrike": 24500}},
        vix_value=12.5,
        is_live_data=True,
    )

    assert res["market_regime"] == MarketRegime.SIDEWAYS
    assert res["marketState"] == MarketState.SIDEWAYS
    assert res["isNoTrade"] is True
    assert res["final_action"] == "NO_TRADE"
    assert "sideways" in res["explanation"].lower() or "range" in res["explanation"].lower()


def test_minor_bearish_dip_protection():
    """Verify a minor 0.35x ATR dip within a consolidating box does NOT trigger BEARISH_TREND or REVERSAL."""
    # Price is 24505 in a 24490-24520 range (ATR = 30). Drops 10 points to 24495.
    df = pd.DataFrame([
        {"timestamp": "t1", "open": 24500, "high": 24520, "low": 24490, "close": 24510, "volume": 1000},
        {"timestamp": "t2", "open": 24510, "high": 24515, "low": 24495, "close": 24498, "volume": 900},
    ])
    quote = {"currentPrice": 24498.0, "dayHigh": 24520.0, "dayLow": 24490.0, "previousClose": 24500.0, "change": -2.0}
    info = {"vwap": 24503.0, "ema20": 24504.0, "ema50": 24505.0, "atr": 30.0, "rsi": 48.0}

    res = evaluate_index_market_state(
        symbol="NIFTY 50",
        quote=quote,
        candles_df=df,
        candles_info=info,
        option_chain_summary={"pcr": {"pcrOi": 0.98}},
        vix_value=12.0,
        is_live_data=True,
    )

    # Must remain SIDEWAYS; strictly forbidden from calling a 2-point dip BEARISH!
    assert res["market_regime"] == MarketRegime.SIDEWAYS
    assert res["marketState"] == MarketState.SIDEWAYS
    assert res["isNoTrade"] is True


# =====================================================================
# 2. Independent Index States
# =====================================================================

def test_independent_index_states():
    """Verify NIFTY being Bullish does NOT force BANK NIFTY to be Bullish."""
    # NIFTY Strong Rally (+180 pts)
    nifty_df = pd.DataFrame([{"timestamp": "t1", "open": 24400, "high": 24600, "low": 24400, "close": 24580, "volume": 10000}])
    nifty_res = evaluate_index_market_state(
        symbol="NIFTY 50",
        quote={"currentPrice": 24580, "dayHigh": 24600, "dayLow": 24400, "previousClose": 24400, "change": 180},
        candles_df=nifty_df,
        candles_info={"vwap": 24480, "ema20": 24450, "ema50": 24400, "atr": 90, "rsi": 65.0},
        option_chain_summary={"pcr": {"pcrOi": 1.35}, "callWall": 24800, "putWall": 24400, "maxPain": {"maxPainStrike": 24500}},
        vix_value=13.0,
        is_live_data=True,
    )

    # BANK NIFTY Range-bound chop (+10 pts)
    bank_df = pd.DataFrame([{"timestamp": "t1", "open": 52000, "high": 52050, "low": 51980, "close": 52010, "volume": 1000}])
    bank_res = evaluate_index_market_state(
        symbol="BANK NIFTY",
        quote={"currentPrice": 52010, "dayHigh": 52050, "dayLow": 51980, "previousClose": 52000, "change": 10},
        candles_df=bank_df,
        candles_info={"vwap": 52005, "ema20": 52008, "ema50": 52010, "atr": 40, "rsi": 50.0},
        option_chain_summary={"pcr": {"pcrOi": 0.98}, "callWall": 52500, "putWall": 51800, "maxPain": {"maxPainStrike": 52000}},
        vix_value=13.0,
        is_live_data=True,
    )

    assert nifty_res["market_regime"] == MarketRegime.BULLISH_TREND
    assert nifty_res["marketState"] == MarketState.BULLISH
    assert bank_res["market_regime"] == MarketRegime.SIDEWAYS
    assert bank_res["marketState"] == MarketState.SIDEWAYS
    assert nifty_res["marketState"] != bank_res["marketState"]


# =====================================================================
# 3. Directional Trend Regimes & Execution Restriction (WAIT)
# =====================================================================

def test_bullish_trend_regime_and_execution_restriction():
    """Verify Bullish Trend correctly identifies regime and enforces WAIT until Step 3 MTF synthesis."""
    quote = {"currentPrice": 24650.0, "dayHigh": 24660.0, "dayLow": 24500.0, "previousClose": 24500.0, "change": 150.0}
    info = {
        "vwap": 24580.0,
        "ema20": 24610.0,
        "ema50": 24560.0,
        "atr": 45.0,
        "rsi": 62.0,
        "adx": 28.5,
        "plus_di": 29.0,
        "minus_di": 12.0,
    }

    res = evaluate_index_market_state(
        symbol="NIFTY 50",
        quote=quote,
        candles_info=info,
        vix_value=13.0,
        is_live_data=True,
    )

    assert res["market_regime"] == MarketRegime.BULLISH_TREND
    assert res["trend_direction"] == "BULLISH"
    assert res["trend_strength"] == 28.5
    # Strict Step 2 execution gate: analytical only, requires MTF in Step 3!
    assert res["final_action"] == "WAIT"


def test_bearish_trend_regime_and_execution_restriction():
    """Verify Bearish Trend correctly identifies regime and enforces WAIT until Step 3 MTF synthesis."""
    quote = {"currentPrice": 24350.0, "dayHigh": 24550.0, "dayLow": 24340.0, "previousClose": 24500.0, "change": -150.0}
    info = {
        "vwap": 24420.0,
        "ema20": 24390.0,
        "ema50": 24440.0,
        "atr": 45.0,
        "rsi": 38.0,
        "adx": 31.0,
        "plus_di": 11.0,
        "minus_di": 32.0,
    }

    res = evaluate_index_market_state(
        symbol="NIFTY 50",
        quote=quote,
        candles_info=info,
        vix_value=14.5,
        is_live_data=True,
    )

    assert res["market_regime"] == MarketRegime.BEARISH_TREND
    assert res["trend_direction"] == "BEARISH"
    assert res["trend_strength"] == 31.0
    assert res["final_action"] == "WAIT"


# =====================================================================
# 4. Volatility Expansion Neutrality
# =====================================================================

def test_volatility_expansion_directional_neutrality():
    """
    Verify Volatility Expansion does not automatically imply direction or authorize BUY_CE/PE.
    Direction is evaluated separately and final_action is WAIT.
    """
    quote = {"currentPrice": 24800.0, "dayHigh": 24820.0, "dayLow": 24500.0, "previousClose": 24520.0, "change": 280.0}
    # Range is 320 pts with ATR = 40 (ratio = 8.0x ATR!)
    info = {"vwap": 24650.0, "ema20": 24700.0, "ema50": 24600.0, "atr": 40.0, "normalized_atr_pct": 1.45, "bb_width": 0.095}

    res = evaluate_index_market_state(
        symbol="NIFTY 50",
        quote=quote,
        candles_info=info,
        vix_value=18.0,
        is_live_data=True,
    )

    assert res["market_regime"] == MarketRegime.VOLATILITY_EXPANSION
    assert res["volatility_state"] == "EXPANDING"
    # Direction evaluated separately
    assert res["trend_direction"] in ["BULLISH", "BEARISH", "EXPANSION_UNCERTAIN"]
    # Never auto-buys!
    assert res["final_action"] == "WAIT"


# =====================================================================
# 5. Reversal Confirmation (Tri-Factor Requirement)
# =====================================================================

def test_reversal_confirmation_requires_structure_shift():
    """Verify reversal requires established prior trend and massive displacement."""
    # Established uptrend to 24800, then aggressive 120-pt supply dump to 24680 (ATR = 60)
    df = pd.DataFrame([
        {"timestamp": "t1", "open": 24500, "high": 24700, "low": 24500, "close": 24680, "volume": 5000},
        {"timestamp": "t2", "open": 24680, "high": 24800, "low": 24680, "close": 24800, "volume": 8000},
        {"timestamp": "t3", "open": 24800, "high": 24800, "low": 24670, "close": 24680, "volume": 9000},
    ])
    quote = {"currentPrice": 24680.0, "dayHigh": 24800.0, "dayLow": 24500.0, "previousClose": 24550.0, "change": 130.0}
    info = {"vwap": 24710.0, "ema20": 24730.0, "ema50": 24680.0, "atr": 50.0, "rsi": 42.0, "adx": 24.0}

    res = evaluate_index_market_state(
        symbol="NIFTY 50",
        quote=quote,
        candles_df=df,
        candles_info=info,
        vix_value=14.0,
        is_live_data=True,
    )

    # 120-pt drop from peak (2.4x ATR) with price falling below swing midpoint
    assert res["market_regime"] == MarketRegime.REVERSAL
    assert res["trend_direction"] == "BEARISH"
    assert res["final_action"] == "WAIT"


# =====================================================================
# 6. Missing Indicators, Options Fallback, Stale Data
# =====================================================================

def test_missing_options_chain_fallback():
    """Verify missing options chain allows price-based regime classification without error."""
    quote = {"currentPrice": 24600.0, "dayHigh": 24620.0, "dayLow": 24500.0, "previousClose": 24500.0, "change": 100.0}
    info = {"vwap": 24550.0, "ema20": 24570.0, "ema50": 24530.0, "atr": 40.0, "adx": 26.0, "plus_di": 25.0, "minus_di": 12.0}

    # Pass option_chain_summary=None
    res = evaluate_index_market_state(
        symbol="NIFTY 50",
        quote=quote,
        candles_info=info,
        option_chain_summary=None,
        is_live_data=True,
    )

    assert res["market_regime"] == MarketRegime.BULLISH_TREND
    assert res["evaluationFactors"]["optionChainEvidence"]["status"] == "UNAVAILABLE"
    assert res["indicator_confluence"]["pcr"] is None


def test_stale_data_rejection():
    """Verify market data feed older than 15 minutes is rejected with NO_TRADE."""
    quote = {"currentPrice": 24500.0, "dayHigh": 24550.0, "dayLow": 24450.0, "previousClose": 24480.0, "change": 20.0}
    stale_time = datetime.now(timezone.utc) - timedelta(minutes=25)

    res = evaluate_index_market_state(
        symbol="NIFTY 50",
        quote=quote,
        last_update_utc=stale_time,
        is_live_data=True,
    )

    assert res["market_regime"] == MarketRegime.NO_TRADE
    assert res["isNoTrade"] is True
    assert any("stale" in r.lower() for r in res["rejection_reasons"])


def test_insufficient_history_data_unavailable():
    """Verify empty quote or zero LTP returns DATA_UNAVAILABLE."""
    res = evaluate_index_market_state(
        symbol="NIFTY 50",
        quote={"currentPrice": 0.0},
        is_live_data=False,
    )

    assert res["market_regime"] == MarketRegime.DATA_UNAVAILABLE
    assert res["final_action"] == "NO_TRADE"
    assert res["data_quality_status"] == "DATA_UNAVAILABLE"


# =====================================================================
# 7. Four-Index Isolation & Replay Consistency
# =====================================================================

def test_index_isolation_four_indices():
    """Verify NIFTY 50, BANK NIFTY, FINNIFTY, and SENSEX maintain independent parameters and state."""
    indices = ["NIFTY 50", "BANK NIFTY", "FINNIFTY", "SENSEX"]
    results = {}

    for idx in indices:
        q = {"currentPrice": 10000.0, "dayHigh": 10010.0, "dayLow": 9990.0, "previousClose": 10000.0, "change": 0.0}
        results[idx] = evaluate_index_market_state(symbol=idx, quote=q, is_live_data=True)

    for idx in indices:
        assert results[idx]["index"] == idx
        assert results[idx]["market_regime"] == MarketRegime.SIDEWAYS


def test_historical_replay_consistency():
    """Verify evaluating identical historical input twice yields identical deterministic results."""
    quote = {"currentPrice": 24550.0, "dayHigh": 24580.0, "dayLow": 24480.0, "previousClose": 24500.0, "change": 50.0}
    info = {"vwap": 24520.0, "ema20": 24530.0, "ema50": 24510.0, "atr": 40.0}

    run_1 = evaluate_index_market_state(symbol="NIFTY 50", quote=quote, candles_info=info)
    run_2 = evaluate_index_market_state(symbol="NIFTY 50", quote=quote, candles_info=info)

    assert run_1["market_regime"] == run_2["market_regime"]
    assert run_1["trend_direction"] == run_2["trend_direction"]
    assert run_1["final_action"] == run_2["final_action"]
    assert run_1["regime_confidence"] == run_2["regime_confidence"]

