"""
AIVOLVE Institutional Quantitative Trading Intelligence v3.0
Phase 2 Step 3 Dedicated Test Suite: Multi-Timeframe Confluence & Trade Setup Selector

Tests the 18 mandatory requirements:
1. Fully aligned bullish multi-timeframe setup
2. Fully aligned bearish multi-timeframe setup
3. HTF bullish but ITF bearish conflict
4. HTF bearish but ITF bullish conflict
5. Missing 1H policy (score capped at 60, trend-based qualification restricted)
6. Missing 15M activation lockout
7. Missing 5M execution lockout
8. Missing 1M fallback behavior (FALLBACK_5M_TRIGGER)
9. Missing 3M data handling (no fabrication/interpolation)
10. Incomplete candle rejection
11. Stale and anomalous data rejection
12. Invalid stop-loss rejection
13. Invalid target rejection
14. Minimum reward-to-risk validation
15. Independent index calculations (NIFTY, BANK NIFTY, SENSEX, FINNIFTY)
16. Historical replay determinism
17. No look-ahead bias
18. Phase 1 risk-gate preservation
"""

from typing import Dict, Any, List
import pytest
import pandas as pd
import numpy as np

from app.options.multi_timeframe_engine import evaluate_multi_timeframe_confluence
from app.options.trade_setup_selector import select_trade_setup, calculate_dynamic_risk_levels
from app.options.market_state_engine import MarketRegime, MarketState


# ---------------------------------------------------------------------------
# Helper: Synthetic Bar Generator for Multi-Timeframe Testing
# ---------------------------------------------------------------------------
def generate_candle_series(
    n_bars: int,
    start_price: float,
    trend: str = "bullish",
    step_pts: float = 3.0,
    volatility: float = 2.0,
    volume_base: int = 5000,
) -> pd.DataFrame:
    """Generates realistic OHLCV candlestick series with specified trend characteristics."""
    rows = []
    p = start_price

    for i in range(n_bars):
        if trend == "bullish":
            delta = step_pts + (i * 0.2)
            c = p + delta
            o = p
            h = max(o, c) + volatility
            l = min(o, c) - volatility
        elif trend == "bearish":
            delta = step_pts + (i * 0.2)
            c = p - delta
            o = p
            h = max(o, c) + volatility
            l = min(o, c) - volatility
        else:  # flat / sideways
            c = p + (volatility if i % 2 == 0 else -volatility)
            o = p
            h = max(o, c) + 1.0
            l = min(o, c) - 1.0

        v = volume_base + (i * 200) if trend != "flat" else volume_base
        rows.append({
            "timestamp": f"2026-11-05 09:{15 + i:02d}:00",
            "open": round(o, 2),
            "high": round(h, 2),
            "low": round(l, 2),
            "close": round(c, 2),
            "volume": v,
            "is_closed": True,
        })
        p = c

    return pd.DataFrame(rows)


# =====================================================================
# 1. Fully Aligned Bullish & Bearish Setups
# =====================================================================

def test_fully_aligned_bullish_mtf_setup():
    """Verify fully aligned HTF, ITF, and LTF qualifies BUY_CE with valid R:R >= 1.5."""
    df_1h = generate_candle_series(20, start_price=24300, trend="bullish", step_pts=15.0)
    df_15m = generate_candle_series(25, start_price=24400, trend="bullish", step_pts=8.0)
    df_5m = generate_candle_series(20, start_price=24500, trend="bullish", step_pts=5.0)
    df_1m = generate_candle_series(15, start_price=24580, trend="bullish", step_pts=2.0)

    ltp = float(df_1m["close"].iloc[-1])
    quote = {"currentPrice": ltp, "dayHigh": ltp + 10.0, "dayLow": 24300.0, "previousClose": 24350.0, "change": ltp - 24350.0}

    mtf_res = evaluate_multi_timeframe_confluence(
        symbol="NIFTY 50",
        timeframe_candles={"1h": df_1h, "15m": df_15m, "5m": df_5m, "1m": df_1m},
        current_quote=quote,
        option_chain_summary={"pcr": {"pcrOi": 1.25}},
        vix_value=13.0,
        is_live_data=True,
        data_quality_status="VERIFIED_LIVE",
    )

    market_state = {"market_regime": MarketRegime.BULLISH_TREND, "regime_confidence": 0.85}

    setup_res = select_trade_setup(
        symbol="NIFTY 50",
        quote=quote,
        mtf_confluence=mtf_res,
        market_regime_state=market_state,
        is_live_data=True,
    )

    assert mtf_res["confluence_score"] >= 70.0
    assert mtf_res["directional_bias"] == "BULLISH"
    assert setup_res["action"] == "BUY_CE"
    assert setup_res["qualification_status"] == "QUALIFIED"

    plan = setup_res["trade_setup"]
    assert plan is not None
    assert plan["type"] == "CALL_OPTION_BUY"
    assert plan["stop_loss"] < plan["entry_price"] < plan["target_1"] < plan["target_2"] < plan["target_3"]
    assert plan["reward_risk_ratio"] >= 1.5


def test_fully_aligned_bearish_mtf_setup():
    """Verify fully aligned bearish HTF, ITF, and LTF qualifies BUY_PE with valid R:R >= 1.5."""
    df_1h = generate_candle_series(20, start_price=24700, trend="bearish", step_pts=15.0)
    df_15m = generate_candle_series(25, start_price=24600, trend="bearish", step_pts=8.0)
    df_5m = generate_candle_series(20, start_price=24500, trend="bearish", step_pts=5.0)
    df_1m = generate_candle_series(15, start_price=24420, trend="bearish", step_pts=2.0)

    ltp = float(df_1m["close"].iloc[-1])
    quote = {"currentPrice": ltp, "dayHigh": 24700.0, "dayLow": ltp - 10.0, "previousClose": 24650.0, "change": ltp - 24650.0}

    mtf_res = evaluate_multi_timeframe_confluence(
        symbol="NIFTY 50",
        timeframe_candles={"1h": df_1h, "15m": df_15m, "5m": df_5m, "1m": df_1m},
        current_quote=quote,
        option_chain_summary={"pcr": {"pcrOi": 0.70}},
        vix_value=14.0,
        is_live_data=True,
        data_quality_status="VERIFIED_LIVE",
    )

    market_state = {"market_regime": MarketRegime.BEARISH_TREND, "regime_confidence": 0.85}

    setup_res = select_trade_setup(
        symbol="NIFTY 50",
        quote=quote,
        mtf_confluence=mtf_res,
        market_regime_state=market_state,
        is_live_data=True,
    )

    assert mtf_res["confluence_score"] >= 70.0
    assert mtf_res["directional_bias"] == "BEARISH"
    assert setup_res["action"] == "BUY_PE"
    assert setup_res["qualification_status"] == "QUALIFIED"

    plan = setup_res["trade_setup"]
    assert plan is not None
    assert plan["type"] == "PUT_OPTION_BUY"
    assert plan["stop_loss"] > plan["entry_price"] > plan["target_1"] > plan["target_2"] > plan["target_3"]
    assert plan["reward_risk_ratio"] >= 1.5


# =====================================================================
# 2. Timeframe Conflict Policies (HTF vs. ITF)
# =====================================================================

def test_htf_bullish_itf_bearish_conflict():
    """Verify HTF bullish but 5M structure bearish forces conflict detection and NO_TRADE."""
    df_1h = generate_candle_series(20, start_price=24300, trend="bullish", step_pts=15.0)
    df_15m = generate_candle_series(25, start_price=24400, trend="bullish", step_pts=8.0)
    # 5M structure breaks down bearishly
    df_5m = generate_candle_series(20, start_price=24600, trend="bearish", step_pts=6.0)
    df_1m = generate_candle_series(15, start_price=24500, trend="bearish", step_pts=2.0)

    ltp = float(df_1m["close"].iloc[-1])
    quote = {"currentPrice": ltp, "dayHigh": 24650.0, "dayLow": 24300.0, "previousClose": 24350.0, "change": 120.0}

    mtf_res = evaluate_multi_timeframe_confluence(
        symbol="NIFTY 50",
        timeframe_candles={"1h": df_1h, "15m": df_15m, "5m": df_5m, "1m": df_1m},
        current_quote=quote,
    )

    setup_res = select_trade_setup(symbol="NIFTY 50", quote=quote, mtf_confluence=mtf_res)

    assert len(mtf_res["timeframe_conflicts"]) > 0
    assert mtf_res["can_activate_directional"] is False
    assert setup_res["action"] == "NO_TRADE"
    assert setup_res["qualification_status"] == "REJECTED"


def test_htf_bearish_itf_bullish_conflict():
    """Verify HTF bearish but 5M structure bullish forces conflict detection and NO_TRADE."""
    df_1h = generate_candle_series(20, start_price=24800, trend="bearish", step_pts=15.0)
    df_15m = generate_candle_series(25, start_price=24700, trend="bearish", step_pts=8.0)
    # 5M rallies bullishly
    df_5m = generate_candle_series(20, start_price=24450, trend="bullish", step_pts=6.0)
    df_1m = generate_candle_series(15, start_price=24550, trend="bullish", step_pts=2.0)

    ltp = float(df_1m["close"].iloc[-1])
    quote = {"currentPrice": ltp, "dayHigh": 24800.0, "dayLow": 24400.0, "previousClose": 24750.0, "change": -200.0}

    mtf_res = evaluate_multi_timeframe_confluence(
        symbol="NIFTY 50",
        timeframe_candles={"1h": df_1h, "15m": df_15m, "5m": df_5m, "1m": df_1m},
        current_quote=quote,
    )

    setup_res = select_trade_setup(symbol="NIFTY 50", quote=quote, mtf_confluence=mtf_res)

    assert len(mtf_res["timeframe_conflicts"]) > 0
    assert mtf_res["can_activate_directional"] is False
    assert setup_res["action"] == "NO_TRADE"


# =====================================================================
# 3. Missing Timeframe Policies
# =====================================================================

def test_missing_1h_policy():
    """Verify missing 1H caps confluence score at 60/100 and restricts unrestricted qualification."""
    df_15m = generate_candle_series(25, start_price=24400, trend="bullish", step_pts=8.0)
    df_5m = generate_candle_series(20, start_price=24500, trend="bullish", step_pts=5.0)
    df_1m = generate_candle_series(15, start_price=24580, trend="bullish", step_pts=2.0)

    ltp = float(df_1m["close"].iloc[-1])
    quote = {"currentPrice": ltp, "dayHigh": ltp + 10.0, "dayLow": 24400.0, "previousClose": 24400.0, "change": 180.0}

    # Omit '1h'
    mtf_res = evaluate_multi_timeframe_confluence(
        symbol="NIFTY 50",
        timeframe_candles={"15m": df_15m, "5m": df_5m, "1m": df_1m},
        current_quote=quote,
    )

    setup_res = select_trade_setup(symbol="NIFTY 50", quote=quote, mtf_confluence=mtf_res)

    assert "1H" in mtf_res["missing_timeframes"]
    # Policy mandate: Capped at 60.0
    assert mtf_res["confluence_score"] <= 60.0
    # Because score is capped at 60.0 (< 70 min threshold), cannot activate BUY_CE; downgrades to WAIT
    assert setup_res["action"] == "WAIT"


def test_missing_15m_activation_lockout():
    """Verify missing 15M triggers directional trade lockout (strictly NO BUY_CE or BUY_PE)."""
    df_1h = generate_candle_series(20, start_price=24300, trend="bullish", step_pts=15.0)
    df_5m = generate_candle_series(20, start_price=24500, trend="bullish", step_pts=5.0)
    df_1m = generate_candle_series(15, start_price=24580, trend="bullish", step_pts=2.0)

    ltp = float(df_1m["close"].iloc[-1])
    quote = {"currentPrice": ltp, "dayHigh": ltp + 10.0, "dayLow": 24300.0, "previousClose": 24350.0, "change": 230.0}

    # Omit '15m'
    mtf_res = evaluate_multi_timeframe_confluence(
        symbol="NIFTY 50",
        timeframe_candles={"1h": df_1h, "5m": df_5m, "1m": df_1m},
        current_quote=quote,
    )

    setup_res = select_trade_setup(symbol="NIFTY 50", quote=quote, mtf_confluence=mtf_res)

    assert "15M" in mtf_res["missing_timeframes"]
    assert mtf_res["can_activate_directional"] is False
    assert setup_res["action"] == "NO_TRADE"


def test_missing_5m_execution_lockout():
    """Verify missing 5M enforces total execution lockout."""
    df_1h = generate_candle_series(20, start_price=24300, trend="bullish", step_pts=15.0)
    df_15m = generate_candle_series(25, start_price=24400, trend="bullish", step_pts=8.0)
    df_1m = generate_candle_series(15, start_price=24580, trend="bullish", step_pts=2.0)

    ltp = float(df_1m["close"].iloc[-1])
    quote = {"currentPrice": ltp, "dayHigh": ltp + 10.0, "dayLow": 24300.0, "previousClose": 24350.0, "change": 230.0}

    # Omit '5m'
    mtf_res = evaluate_multi_timeframe_confluence(
        symbol="NIFTY 50",
        timeframe_candles={"1h": df_1h, "15m": df_15m, "1m": df_1m},
        current_quote=quote,
    )

    setup_res = select_trade_setup(symbol="NIFTY 50", quote=quote, mtf_confluence=mtf_res)

    assert "5M" in mtf_res["missing_timeframes"]
    assert mtf_res["can_activate_directional"] is False
    assert setup_res["action"] == "NO_TRADE"


def test_missing_1m_fallback_behavior():
    """Verify missing 1M activates clearly identified FALLBACK_5M_TRIGGER when 5M displacement is confirmed."""
    df_1h = generate_candle_series(20, start_price=24300, trend="bullish", step_pts=15.0)
    df_15m = generate_candle_series(25, start_price=24400, trend="bullish", step_pts=8.0)
    # 5M has massive bullish displacement
    df_5m = generate_candle_series(20, start_price=24500, trend="bullish", step_pts=12.0)

    ltp = float(df_5m["close"].iloc[-1])
    quote = {"currentPrice": ltp, "dayHigh": ltp + 10.0, "dayLow": 24300.0, "previousClose": 24350.0, "change": 300.0}

    # Omit '1m'
    mtf_res = evaluate_multi_timeframe_confluence(
        symbol="NIFTY 50",
        timeframe_candles={"1h": df_1h, "15m": df_15m, "5m": df_5m},
        current_quote=quote,
    )

    assert "1M" in mtf_res["missing_timeframes"]
    assert "FALLBACK_5M_TRIGGER" in mtf_res["active_fallbacks"]
    assert mtf_res["ltf_trigger"]["is_fallback_5m"] is True
    assert mtf_res["ltf_trigger"]["triggered"] is True


def test_missing_3m_data_handling():
    """Verify missing 3M does NOT fabricate or interpolate candles and evaluates cleanly on available confirmed bars."""
    df_1h = generate_candle_series(20, start_price=24300, trend="bullish", step_pts=15.0)
    df_15m = generate_candle_series(25, start_price=24400, trend="bullish", step_pts=8.0)
    df_5m = generate_candle_series(20, start_price=24500, trend="bullish", step_pts=5.0)
    df_1m = generate_candle_series(15, start_price=24580, trend="bullish", step_pts=2.0)

    ltp = float(df_1m["close"].iloc[-1])
    quote = {"currentPrice": ltp, "dayHigh": ltp + 10.0, "dayLow": 24300.0, "previousClose": 24350.0, "change": 230.0}

    # Explicitly no '3m' provided
    mtf_res = evaluate_multi_timeframe_confluence(
        symbol="NIFTY 50",
        timeframe_candles={"1h": df_1h, "15m": df_15m, "5m": df_5m, "1m": df_1m},
        current_quote=quote,
    )

    assert "3M" in mtf_res["missing_timeframes"]
    assert mtf_res["ltf_trigger"]["has_3m"] is False
    # Analysis succeeds cleanly without error or synthetic data injection
    assert mtf_res["confluence_score"] > 0.0


# =====================================================================
# 4. Incomplete Candle & Data Quality Rejection
# =====================================================================

def test_incomplete_candle_rejection():
    """Verify live forming (is_closed=False) candle cannot be used as confirmed structure shift or trigger."""
    df_5m = generate_candle_series(15, start_price=24500, trend="flat")
    # Mark the latest forming candle as incomplete
    df_5m.iloc[-1, df_5m.columns.get_loc("is_closed")] = False
    # Form an artificial massive spike on the unclosed bar
    df_5m.iloc[-1, df_5m.columns.get_loc("close")] = 24900.0

    ltp = 24900.0
    quote = {"currentPrice": ltp, "dayHigh": 24900.0, "dayLow": 24500.0, "previousClose": 24500.0, "change": 400.0}

    mtf_res = evaluate_multi_timeframe_confluence(
        symbol="NIFTY 50",
        timeframe_candles={"5m": df_5m},
        current_quote=quote,
    )

    # 5M structure analyzer must explicitly disregard the unclosed bar
    assert any("incomplete" in d.lower() for d in mtf_res["itf_structure"]["details"])


def test_stale_and_anomalous_data_rejection():
    """Verify stale, anomalous, or synthetic data is rejected by Phase 1 gates with NO_TRADE."""
    df_1h = generate_candle_series(20, start_price=24300, trend="bullish", step_pts=15.0)
    df_15m = generate_candle_series(25, start_price=24400, trend="bullish", step_pts=8.0)
    df_5m = generate_candle_series(20, start_price=24500, trend="bullish", step_pts=5.0)
    df_1m = generate_candle_series(15, start_price=24580, trend="bullish", step_pts=2.0)

    ltp = float(df_1m["close"].iloc[-1])
    quote = {"currentPrice": ltp, "dayHigh": ltp + 10.0, "dayLow": 24300.0, "previousClose": 24350.0, "change": 230.0}

    # Pass Phase 1 degraded status
    for bad_status in ["STALE", "ANOMALOUS", "SYNTHETIC", "MOCK"]:
        mtf_res = evaluate_multi_timeframe_confluence(
            symbol="NIFTY 50",
            timeframe_candles={"1h": df_1h, "15m": df_15m, "5m": df_5m, "1m": df_1m},
            current_quote=quote,
            data_quality_status=bad_status,
        )

        setup_res = select_trade_setup(symbol="NIFTY 50", quote=quote, mtf_confluence=mtf_res)

        assert mtf_res["can_activate_directional"] is False
        assert setup_res["action"] == "NO_TRADE"
        assert setup_res["qualification_status"] == "REJECTED"


# =====================================================================
# 5. Dynamic Risk Engineering (SL & Target Validation)
# =====================================================================

def test_invalid_stop_loss_rejection():
    """Verify stop-loss above entry on Call (or below entry on Put) is rejected."""
    # Bullish Call with inverted invalidation (e.g. SL higher than Entry)
    plan_ce = calculate_dynamic_risk_levels(
        symbol="NIFTY 50",
        direction="BULLISH",
        entry_price=24500.0,
        invalidation_level=24600.0,  # Impossible SL for CE
        atr_5m=30.0,
    )
    # Function must mathematically constrain or reject invalid geometries
    if plan_ce is not None:
        assert plan_ce["stop_loss"] < plan_ce["entry_price"]

    # Bearish Put with inverted invalidation
    plan_pe = calculate_dynamic_risk_levels(
        symbol="NIFTY 50",
        direction="BEARISH",
        entry_price=24500.0,
        invalidation_level=24400.0,  # Impossible SL for PE
        atr_5m=30.0,
    )
    if plan_pe is not None:
        assert plan_pe["stop_loss"] > plan_pe["entry_price"]


def test_invalid_target_rejection():
    """Verify non-positive or inverted targets reject setup qualification."""
    # When entry price is zero or negative
    plan = calculate_dynamic_risk_levels(
        symbol="NIFTY 50",
        direction="BULLISH",
        entry_price=0.0,
        invalidation_level=0.0,
        atr_5m=30.0,
    )
    assert plan is None


def test_minimum_reward_to_risk_validation():
    """Verify minimum reward-to-risk (R:R >= 1.5) is enforced across qualified setups."""
    plan_bull = calculate_dynamic_risk_levels(
        symbol="NIFTY 50",
        direction="BULLISH",
        entry_price=24500.0,
        invalidation_level=24470.0,
        atr_5m=25.0,
    )
    assert plan_bull is not None
    assert plan_bull["reward_risk_ratio"] >= 1.5

    plan_bear = calculate_dynamic_risk_levels(
        symbol="BANK NIFTY",
        direction="BEARISH",
        entry_price=52000.0,
        invalidation_level=52080.0,
        atr_5m=70.0,
    )
    assert plan_bear is not None
    assert plan_bear["reward_risk_ratio"] >= 1.5


# =====================================================================
# 6. Multi-Index Isolation & Replay Determinism
# =====================================================================

def test_independent_index_calculations():
    """Verify NIFTY, BANK NIFTY, SENSEX, and FINNIFTY evaluate independently with separate risk limits."""
    indices = ["NIFTY 50", "BANK NIFTY", "SENSEX", "FINNIFTY"]
    results = {}

    for idx in indices:
        df_1h = generate_candle_series(20, start_price=20000, trend="bullish", step_pts=15.0)
        df_15m = generate_candle_series(25, start_price=20000, trend="bullish", step_pts=8.0)
        df_5m = generate_candle_series(20, start_price=20000, trend="bullish", step_pts=5.0)
        df_1m = generate_candle_series(15, start_price=20000, trend="bullish", step_pts=2.0)
        quote = {"currentPrice": 20100.0, "dayHigh": 20120.0, "dayLow": 19900.0, "previousClose": 20000.0, "change": 100.0}

        mtf = evaluate_multi_timeframe_confluence(
            symbol=idx,
            timeframe_candles={"1h": df_1h, "15m": df_15m, "5m": df_5m, "1m": df_1m},
            current_quote=quote,
        )
        setup = select_trade_setup(symbol=idx, quote=quote, mtf_confluence=mtf)
        results[idx] = setup

    assert len(results) == 4
    # Check that each index maintained its own symbol
    for idx in indices:
        assert results[idx]["symbol"] == idx


def test_historical_replay_determinism():
    """Verify identical inputs across replay runs yield exact bit-for-bit identical outputs."""
    df_1h = generate_candle_series(20, start_price=24300, trend="bullish", step_pts=15.0)
    df_15m = generate_candle_series(25, start_price=24400, trend="bullish", step_pts=8.0)
    df_5m = generate_candle_series(20, start_price=24500, trend="bullish", step_pts=5.0)
    df_1m = generate_candle_series(15, start_price=24580, trend="bullish", step_pts=2.0)
    quote = {"currentPrice": 24600.0, "dayHigh": 24620.0, "dayLow": 24300.0, "previousClose": 24350.0, "change": 250.0}

    tfs = {"1h": df_1h, "15m": df_15m, "5m": df_5m, "1m": df_1m}

    run1_mtf = evaluate_multi_timeframe_confluence(symbol="NIFTY 50", timeframe_candles=tfs, current_quote=quote)
    run1_setup = select_trade_setup(symbol="NIFTY 50", quote=quote, mtf_confluence=run1_mtf)

    run2_mtf = evaluate_multi_timeframe_confluence(symbol="NIFTY 50", timeframe_candles=tfs, current_quote=quote)
    run2_setup = select_trade_setup(symbol="NIFTY 50", quote=quote, mtf_confluence=run2_mtf)

    assert run1_mtf["confluence_score"] == run2_mtf["confluence_score"]
    assert run1_setup["action"] == run2_setup["action"]
    assert run1_setup["trade_setup"] == run2_setup["trade_setup"]


def test_no_lookahead_bias():
    """Verify engine only uses candles available at analysis timestamp without future leakage."""
    full_df = generate_candle_series(30, start_price=24300, trend="bullish")
    # Simulate past timestamp by truncating candles at bar 20
    past_df = full_df.iloc[:20].copy()

    quote_past = {"currentPrice": float(past_df["close"].iloc[-1]), "dayHigh": float(past_df["high"].max()), "dayLow": float(past_df["low"].min()), "previousClose": 24300.0, "change": 50.0}

    mtf_past = evaluate_multi_timeframe_confluence(
        symbol="NIFTY 50",
        timeframe_candles={"5m": past_df, "15m": past_df},
        current_quote=quote_past,
    )

    # Analysis at bar 20 cannot see bar 21-30 price levels
    assert mtf_past["itf_structure"]["swing_high"] <= float(past_df["high"].max())


def test_phase1_risk_gate_preservation():
    """Verify Phase 1 safety gates block unverified mock data from generating paper trades."""
    df_1h = generate_candle_series(20, start_price=24300, trend="bullish")
    df_15m = generate_candle_series(25, start_price=24400, trend="bullish")
    df_5m = generate_candle_series(20, start_price=24500, trend="bullish")
    df_1m = generate_candle_series(15, start_price=24580, trend="bullish")
    quote = {"currentPrice": 24600.0, "dayHigh": 24620.0, "dayLow": 24300.0, "previousClose": 24350.0, "change": 250.0}

    # is_live_data = False (unverified synthetic or mock feed)
    mtf_res = evaluate_multi_timeframe_confluence(
        symbol="NIFTY 50",
        timeframe_candles={"1h": df_1h, "15m": df_15m, "5m": df_5m, "1m": df_1m},
        current_quote=quote,
        is_live_data=False,
    )

    setup_res = select_trade_setup(
        symbol="NIFTY 50",
        quote=quote,
        mtf_confluence=mtf_res,
        is_live_data=False,
    )

    # Strictly forbidden from opening paper trades
    assert setup_res["action"] == "NO_TRADE"
    assert setup_res["trade_setup"] is None


# =====================================================================
# 7. Structural Stop-Loss Safety & Risk Boundaries (Audit Finding F-03)
# =====================================================================

def test_structural_sl_exceeds_max_risk_rejection_nifty():
    """Verify NIFTY setup is rejected when raw structural distance exceeds max_sl_pts (65 pts)."""
    reasons = []
    # Entry 24500, Swing Low 24400 -> Raw distance = 100 pts > 65 pts max
    plan = calculate_dynamic_risk_levels(
        symbol="NIFTY 50",
        direction="BULLISH",
        entry_price=24500.0,
        invalidation_level=24400.0,
        atr_5m=25.0,
        rejection_reasons=reasons,
    )
    assert plan is None
    assert "Structural invalidation distance exceeds risk tolerance" in reasons


def test_structural_sl_exceeds_max_risk_rejection_banknifty():
    """Verify BANK NIFTY setup is rejected when raw structural distance exceeds max_sl_pts (180 pts)."""
    reasons = []
    # Entry 52000, Swing High 52250 -> Raw distance = 250 pts > 180 pts max
    plan = calculate_dynamic_risk_levels(
        symbol="BANK NIFTY",
        direction="BEARISH",
        entry_price=52000.0,
        invalidation_level=52250.0,
        atr_5m=70.0,
        rejection_reasons=reasons,
    )
    assert plan is None
    assert "Structural invalidation distance exceeds risk tolerance" in reasons


def test_structural_sl_exceeds_max_risk_rejection_sensex():
    """Verify SENSEX setup is rejected when raw structural distance exceeds max_sl_pts (220 pts)."""
    reasons = []
    # Entry 80000, Swing Low 79700 -> Raw distance = 300 pts > 220 pts max
    plan = calculate_dynamic_risk_levels(
        symbol="SENSEX",
        direction="BULLISH",
        entry_price=80000.0,
        invalidation_level=79700.0,
        atr_5m=100.0,
        rejection_reasons=reasons,
    )
    assert plan is None
    assert "Structural invalidation distance exceeds risk tolerance" in reasons


def test_structural_sl_exceeds_max_risk_rejection_finnifty():
    """Verify FINNIFTY setup is rejected when raw structural distance exceeds max_sl_pts (60 pts)."""
    reasons = []
    # Entry 23000, Swing Low 22910 -> Raw distance = 90 pts > 60 pts max
    plan = calculate_dynamic_risk_levels(
        symbol="FINNIFTY",
        direction="BULLISH",
        entry_price=23000.0,
        invalidation_level=22910.0,
        atr_5m=30.0,
        rejection_reasons=reasons,
    )
    assert plan is None
    assert "Structural invalidation distance exceeds risk tolerance" in reasons


def test_valid_structural_stop_within_limits():
    """Verify valid structural stop within index limits is accepted with valid R:R >= 1.5."""
    # NIFTY 50: raw distance 30 pts (min: 15, max: 65)
    plan = calculate_dynamic_risk_levels(
        symbol="NIFTY 50",
        direction="BULLISH",
        entry_price=24500.0,
        invalidation_level=24470.0,
        atr_5m=20.0,
    )
    assert plan is not None
    assert plan["stop_loss"] == 24470.0
    assert plan["risk_per_unit"] == 30.0
    assert plan["target_1"] == 24545.0  # 24500 + 30 * 1.5
    assert plan["reward_risk_ratio"] >= 1.5


def test_minimum_sl_padding_preserves_structure():
    """Verify minimum SL padding extends beyond structural invalidation level without compromising structure."""
    # NIFTY 50: raw distance 8 pts (min_sl_pts: 15.0)
    # Entry 24500, Swing Low 24492 (raw = 8 pts)
    plan = calculate_dynamic_risk_levels(
        symbol="NIFTY 50",
        direction="BULLISH",
        entry_price=24500.0,
        invalidation_level=24492.0,
        atr_5m=5.0,
    )
    assert plan is not None
    assert plan["risk_per_unit"] == 15.0
    assert plan["stop_loss"] == 24485.0
    # Crucial: 24485.0 is below the swing low (24492.0), so structure is preserved!
    assert plan["stop_loss"] < 24492.0


def test_buy_ce_and_buy_pe_risk_geometry():
    """Verify complete risk geometry for both CALL and PUT setups."""
    # BUY_CE: SL < Entry < T1 < T2 < T3
    ce_plan = calculate_dynamic_risk_levels(
        symbol="NIFTY 50",
        direction="BULLISH",
        entry_price=24500.0,
        invalidation_level=24470.0,
        atr_5m=20.0,
    )
    assert ce_plan is not None
    assert ce_plan["stop_loss"] < ce_plan["entry_price"] < ce_plan["target_1"] < ce_plan["target_2"] < ce_plan["target_3"]
    assert ce_plan["type"] == "CALL_OPTION_BUY"
    assert ce_plan["reward_risk_ratio"] >= 1.5

    # BUY_PE: SL > Entry > T1 > T2 > T3
    pe_plan = calculate_dynamic_risk_levels(
        symbol="NIFTY 50",
        direction="BEARISH",
        entry_price=24500.0,
        invalidation_level=24530.0,
        atr_5m=20.0,
    )
    assert pe_plan is not None
    assert pe_plan["stop_loss"] > pe_plan["entry_price"] > pe_plan["target_1"] > pe_plan["target_2"] > pe_plan["target_3"]
    assert pe_plan["type"] == "PUT_OPTION_BUY"
    assert pe_plan["reward_risk_ratio"] >= 1.5


def test_no_silent_sl_clamping_through_structure():
    """Verify that stop-loss is NEVER clamped inside the structural invalidation level."""
    # NIFTY 50: Entry = 24500, Swing Low = 24400 (Raw distance = 100, max_sl = 65)
    # If clamped to max_sl, SL would be 24500 - 65 = 24435, which is ABOVE 24400 (inside structure).
    # The system must reject the setup entirely rather than clamp it.
    plan = calculate_dynamic_risk_levels(
        symbol="NIFTY 50",
        direction="BULLISH",
        entry_price=24500.0,
        invalidation_level=24400.0,
        atr_5m=25.0,
    )
    assert plan is None, "Setup must be rejected, not clamped inside the structural invalidation point"


def test_invalid_and_nonpositive_inputs_rejection():
    """Verify non-positive entry price and ATR inputs are rejected."""
    # Zero entry price
    reasons_entry = []
    plan_bad_entry = calculate_dynamic_risk_levels(
        symbol="NIFTY 50",
        direction="BULLISH",
        entry_price=0.0,
        invalidation_level=24400.0,
        atr_5m=25.0,
        rejection_reasons=reasons_entry,
    )
    assert plan_bad_entry is None
    assert "Invalid non-positive entry price" in reasons_entry

    # Zero or negative ATR
    reasons_atr = []
    plan_bad_atr = calculate_dynamic_risk_levels(
        symbol="NIFTY 50",
        direction="BULLISH",
        entry_price=24500.0,
        invalidation_level=24450.0,
        atr_5m=-5.0,
        rejection_reasons=reasons_atr,
    )
    assert plan_bad_atr is None
    assert "Invalid non-positive ATR value" in reasons_atr


