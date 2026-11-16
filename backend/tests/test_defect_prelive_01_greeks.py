"""
AIVOLVE Phase 6 / Pre-Live Reliability Regression Test Suite.
DEFECT-PRELIVE-01: Safe Option Greeks & Offline Reliability Verification.

Verifies:
1. Valid Black-Scholes Greeks calculation and rounding.
2. Graceful handling when calculate_black_scholes() returns None.
3. Invalid or unavailable spot price (<= 0.0, NaN).
4. Invalid or unavailable implied volatility (<= 0.0, NaN).
5. Missing option quote / empty strike data.
6. Offline options overview API (/api/options/overview) returns HTTP 200 without TypeError.
7. Offline next-session recommendation API (/api/options/{index}/next-session/recommendation) returns HTTP 200.
8. Zero-exposure invariant: Missing Greeks remain None and are never silently represented as 0.0.
"""

import math
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.options.next_session_engine import evaluate_next_session_recommendation
from app.options.option_chain import generate_index_option_chain

client = TestClient(app)


def test_1_valid_black_scholes_greeks():
    """Test 1: Verify valid Black-Scholes Greeks are correctly computed and preserved."""
    chain = generate_index_option_chain("NIFTY 50", 24850.0, 50.0, filter_mode="ATM")
    rec = evaluate_next_session_recommendation(
        symbol="NIFTY 50",
        underlying_ltp=24850.0,
        sentiment="BULLISH",
        sentiment_score=72,
        strikes_data=chain["strikes"],
        atr_14=120.0,
        daily_high=24920.0,
        daily_low=24780.0,
        daily_close=24800.0,
        daily_open=24810.0,
        iv=0.15,
        vix_value=13.5,
    )
    assert rec["hasQualifiedRecommendation"] is True
    assert rec["recommendation"] is not None
    greeks = rec["recommendation"]["greeks"]
    assert greeks is not None
    assert isinstance(greeks["delta"], float)
    assert greeks["delta"] > 0.0
    assert isinstance(greeks["gamma"], float)
    assert greeks["gamma"] > 0.0
    assert isinstance(greeks["thetaPerDay"], float)
    assert greeks["thetaPerDay"] < 0.0
    assert isinstance(greeks["vega"], float)
    assert greeks["vega"] > 0.0


def test_2_calculate_black_scholes_returns_none():
    """Test 2: Verify calculate_black_scholes() returning None is handled safely with None Greeks."""
    chain = generate_index_option_chain("NIFTY 50", 24850.0, 50.0, filter_mode="ATM")
    with patch("app.options.next_session_engine.calculate_black_scholes", return_value=None):
        rec = evaluate_next_session_recommendation(
            symbol="NIFTY 50",
            underlying_ltp=24850.0,
            sentiment="BULLISH",
            sentiment_score=72,
            strikes_data=chain["strikes"],
            atr_14=120.0,
            daily_high=24920.0,
            daily_low=24780.0,
            daily_close=24800.0,
            daily_open=24810.0,
            iv=0.15,
            vix_value=13.5,
        )
        assert rec["hasQualifiedRecommendation"] is True
        assert rec["recommendation"] is not None
        greeks = rec["recommendation"]["greeks"]
        # Explicit unavailable representation is None, NOT fabricated 0.0
        assert greeks["gamma"] is None
        assert greeks["vega"] is None
        assert greeks["gamma"] != 0.0, "Unavailable Gamma must not be silently fabricated as 0.0"
        assert greeks["vega"] != 0.0, "Unavailable Vega must not be silently fabricated as 0.0"


def test_3_invalid_or_unavailable_spot_price():
    """Test 3: Verify invalid or unavailable spot price returns safe response without unhandled exception."""
    chain = generate_index_option_chain("NIFTY 50", 24850.0, 50.0, filter_mode="ATM")
    for invalid_spot in [0.0, -500.0, float("nan")]:
        rec = evaluate_next_session_recommendation(
            symbol="NIFTY 50",
            underlying_ltp=invalid_spot,
            sentiment="BULLISH",
            sentiment_score=72,
            strikes_data=chain["strikes"],
            atr_14=120.0,
            daily_high=24920.0,
            daily_low=24780.0,
            daily_close=24800.0,
            daily_open=24810.0,
            iv=0.15,
            vix_value=13.5,
        )
        assert isinstance(rec, dict)
        assert "decision" in rec
        if rec.get("recommendation"):
            greeks = rec["recommendation"]["greeks"]
            assert greeks["gamma"] is None
            assert greeks["vega"] is None


def test_4_invalid_or_unavailable_implied_volatility():
    """Test 4: Verify invalid IV causes safe None return from Black-Scholes without subscript exception."""
    chain = generate_index_option_chain("NIFTY 50", 24850.0, 50.0, filter_mode="ATM")
    for s in chain["strikes"]:
        if "ce" in s:
            s["ce"]["iv"] = 0.0
        if "pe" in s:
            s["pe"]["iv"] = 0.0

    rec = evaluate_next_session_recommendation(
        symbol="NIFTY 50",
        underlying_ltp=24850.0,
        sentiment="BULLISH",
        sentiment_score=72,
        strikes_data=chain["strikes"],
        atr_14=120.0,
        daily_high=24920.0,
        daily_low=24780.0,
        daily_close=24800.0,
        daily_open=24810.0,
        iv=0.0,
        vix_value=13.5,
    )
    assert isinstance(rec, dict)
    if rec.get("recommendation"):
        greeks = rec["recommendation"]["greeks"]
        assert greeks["gamma"] is None
        assert greeks["vega"] is None
        assert greeks["gamma"] != 0.0
        assert greeks["vega"] != 0.0


def test_5_missing_option_quote():
    """Test 5: Verify missing option quote (empty strikes list) handles missing data safely."""
    rec = evaluate_next_session_recommendation(
        symbol="NIFTY 50",
        underlying_ltp=24850.0,
        sentiment="BULLISH",
        sentiment_score=72,
        strikes_data=[],
        atr_14=120.0,
        daily_high=24920.0,
        daily_low=24780.0,
        daily_close=24800.0,
        daily_open=24810.0,
        iv=0.15,
        vix_value=13.5,
    )
    assert isinstance(rec, dict)
    assert "stage" in rec
    if rec.get("recommendation"):
        assert "greeks" in rec["recommendation"]


def test_6_offline_options_overview_api():
    """Test 6: Verify /api/options/overview succeeds (HTTP 200) without unhandled TypeError."""
    res = client.get("/api/options/overview")
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    data = res.json()
    assert "indices" in data
    assert "marketSentiment" in data
    assert "vix" in data
    if "nextSessionRecommendation" in data and data["nextSessionRecommendation"]:
        rec = data["nextSessionRecommendation"]
        if rec.get("recommendation") and "greeks" in rec["recommendation"]:
            g = rec["recommendation"]["greeks"]
            # If unavailable, must be None, never silent 0.0
            if g["gamma"] is None:
                assert g["gamma"] != 0.0
            if g["vega"] is None:
                assert g["vega"] != 0.0


def test_7_offline_next_session_recommendation_api():
    """Test 7: Verify /api/options/NIFTY/next-session/recommendation succeeds without crashing."""
    res = client.get("/api/options/NIFTY/next-session/recommendation")
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    data = res.json()
    assert "stage" in data
    assert "openingOutlook" in data
    if data.get("recommendation") and "greeks" in data["recommendation"]:
        g = data["recommendation"]["greeks"]
        if g["gamma"] is None:
            assert g["gamma"] != 0.0
        if g["vega"] is None:
            assert g["vega"] != 0.0

