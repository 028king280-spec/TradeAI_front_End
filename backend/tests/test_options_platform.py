import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from app.options.greeks import calculate_black_scholes
from app.options.pcr import calculate_pcr
from app.options.max_pain import calculate_max_pain
from app.options.oi_analysis import analyze_open_interest
from app.options.iv_analysis import analyze_implied_volatility
from app.options.pattern_detection import detect_candlestick_and_chart_patterns
from app.options.support_resistance import compute_options_support_resistance_ladder
from app.options.session_outlook import calculate_session_outlook
from app.options.setup_selector import evaluate_options_trade_setups
from app.options.option_chain import generate_index_option_chain
from app.data.market_calendar import MarketCalendar


def test_black_scholes_greeks():
    # Spot 24800, Strike 24800 ATM, 3 days to expiry, 14% IV
    t_years = 3.0 / 365.0
    ce = calculate_black_scholes(spot=24800, strike=24800, time_to_expiry_years=t_years, iv=0.14, option_type="CE")
    pe = calculate_black_scholes(spot=24800, strike=24800, time_to_expiry_years=t_years, iv=0.14, option_type="PE")

    # ATM Call Delta ~ 0.50, Put Delta ~ -0.50
    assert 0.45 <= ce["delta"] <= 0.58
    assert -0.58 <= pe["delta"] <= -0.42
    assert ce["gamma"] > 0
    assert pe["gamma"] > 0
    # Theta should be negative (decaying in favor of sellers)
    assert ce["theta"] < 0
    assert pe["theta"] < 0
    assert ce["vega"] > 0
    assert ce["price"] > 0


def test_pcr_calculation():
    # Bullish scenario (High Put OI)
    bullish_pcr = calculate_pcr(put_oi=1500000, call_oi=1000000)
    assert bullish_pcr["pcrOi"] == 1.5
    assert bullish_pcr["signal"] == "BULLISH"

    # Bearish scenario (High Call OI)
    bearish_pcr = calculate_pcr(put_oi=600000, call_oi=1000000)
    assert bearish_pcr["pcrOi"] == 0.6
    assert bearish_pcr["signal"] == "BEARISH"

    # Neutral scenario (Equal OI)
    neutral_pcr = calculate_pcr(put_oi=1000000, call_oi=1000000)
    assert neutral_pcr["pcrOi"] == 1.0
    assert neutral_pcr["signal"] == "NEUTRAL"


def test_max_pain_calculation():
    # Strikes: 24700, 24800, 24900
    strikes = [
        {"strike": 24700, "ce": {"oi": 50000}, "pe": {"oi": 200000}},
        {"strike": 24800, "ce": {"oi": 150000}, "pe": {"oi": 150000}},
        {"strike": 24900, "ce": {"oi": 200000}, "pe": {"oi": 50000}},
    ]
    res = calculate_max_pain(strikes)
    assert res["maxPainStrike"] == 24800
    assert res["isDescriptiveOnly"] is True
    assert "disclaimer" in res


def test_oi_analysis_walls():
    strikes = [
        {"strike": 24700, "ce": {"oi": 40000, "changeInOi": 5000}, "pe": {"oi": 180000, "changeInOi": 25000}},
        {"strike": 24800, "ce": {"oi": 90000, "changeInOi": 10000}, "pe": {"oi": 120000, "changeInOi": 15000}},
        {"strike": 24900, "ce": {"oi": 210000, "changeInOi": 35000}, "pe": {"oi": 60000, "changeInOi": -2000}},
    ]
    oi_res = analyze_open_interest(strikes, underlying_ltp=24820, underlying_change=50.0)
    assert oi_res["callWall"] == 24900
    assert oi_res["putWall"] == 24700
    assert oi_res["maxCeAdditionStrike"] == 24900
    assert oi_res["maxPeAdditionStrike"] == 24700


def test_support_resistance_ladder():
    ladder_data = compute_options_support_resistance_ladder(
        current_price=24850.0,
        daily_high=24920.0,
        daily_low=24780.0,
        daily_close=24800.0,
        daily_open=24810.0,
        call_wall=25000.0,
        put_wall=24700.0,
        max_pain=24800.0
    )
    assert "support1" in ladder_data
    assert "resistance1" in ladder_data
    assert ladder_data["resistance1"]["price"] > 24850.0
    assert ladder_data["support1"]["price"] < 24850.0
    # Must contain both Price-Action and Option-Chain levels
    ladder_types = {item["levelType"] for item in ladder_data["ladder"]}
    assert "PRICE_ACTION" in ladder_types
    assert "OPTION_CHAIN" in ladder_types


def test_session_outlook_today_and_next():
    today = calculate_session_outlook("NIFTY 50", 24850.0, 24920.0, 24780.0, 24800.0, 24810.0, 110.0, mode="TODAY")
    assert today["mode"] == "TODAY"
    assert today["expectedRange"]["likelyHigh"] >= 24850.0
    assert today["expectedRange"]["likelyLow"] <= 24850.0
    assert "bullish" in today["scenarios"]
    assert "baseCase" in today["scenarios"]
    assert "bearish" in today["scenarios"]

    next_sess = calculate_session_outlook("NIFTY 50", 24850.0, 24920.0, 24780.0, 24800.0, 24810.0, 110.0, mode="NEXT_SESSION")
    assert next_sess["mode"] == "NEXT_SESSION"
    assert "Next Session Outlook" in next_sess["sessionLabel"]


def test_pattern_detection():
    # Build dataframe with Bullish Engulfing
    df = pd.DataFrame([
        {"open": 24850, "high": 24860, "low": 24820, "close": 24830, "volume": 100000},
        {"open": 24830, "high": 24840, "low": 24810, "close": 24815, "volume": 110000},
        {"open": 24810, "high": 24880, "low": 24805, "close": 24875, "volume": 250000},  # Bullish engulfing
    ])
    patterns = detect_candlestick_and_chart_patterns(df, "15m")
    pattern_names = [p["patternName"] for p in patterns]
    assert "Bullish Engulfing" in pattern_names


def test_setup_qualification_and_no_trade():
    # Neutral market should return NO QUALIFIED SETUP
    strikes = [
        {"strike": 24800, "ce": {"ltp": 95.0, "oi": 80000, "changeInOi": 5000, "iv": 14.5}, "pe": {"ltp": 90.0, "oi": 80000, "changeInOi": 5000, "iv": 14.8}},
        {"strike": 24850, "ce": {"ltp": 65.0, "oi": 70000, "changeInOi": 4000, "iv": 14.2}, "pe": {"ltp": 115.0, "oi": 75000, "changeInOi": 4000, "iv": 15.0}},
    ]
    neutral_setup = evaluate_options_trade_setups(
        symbol="NIFTY 50",
        underlying_ltp=24820.0,
        sentiment="NEUTRAL",
        sentiment_score=50,
        strikes_data=strikes,
        atr_14=100.0
    )
    assert neutral_setup["hasQualifiedSetups"] is False
    assert "NO QUALIFIED SETUP — WAIT FOR BETTER CONDITIONS" in neutral_setup["statusMessage"]

    # Bullish market with high score should produce qualified CE candidate
    bullish_setup = evaluate_options_trade_setups(
        symbol="NIFTY 50",
        underlying_ltp=24820.0,
        sentiment="BULLISH",
        sentiment_score=75,
        strikes_data=strikes,
        atr_14=100.0
    )
    assert bullish_setup["hasQualifiedSetups"] is True
    assert len(bullish_setup["setups"]) > 0
    candidate = bullish_setup["setups"][0]
    assert candidate["bias"] == "CE"
    # Verify premium levels vs index levels
    assert candidate["currentPremium"] < 500.0  # Option premium (not 24800 index)
    assert candidate["stopLoss"] < candidate["currentPremium"]
    assert candidate["target1"] > candidate["currentPremium"]
    assert candidate["target2"] > candidate["target1"]


from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_api_options_overview():
    res = client.get("/api/options/overview")
    assert res.status_code == 200
    data = res.json()
    assert "indices" in data
    assert "marketSentiment" in data
    assert "vix" in data
    symbols = [idx["symbol"] for idx in data["indices"]]
    assert "NIFTY 50" in symbols or "NIFTY" in symbols


def test_api_options_candles():
    res = client.get("/api/options/NIFTY/candles?timeframe=15m")
    assert res.status_code == 200
    data = res.json()
    assert "candles" in data
    assert len(data["candles"]) > 0
    assert "vwap" in data
    assert "ema20" in data


def test_api_options_analysis():
    res = client.get("/api/options/NIFTY/analysis")
    assert res.status_code == 200
    data = res.json()
    assert "supportResistance" in data
    assert "sentiment" in data
    assert "todayOutlook" in data
    assert "nextSessionOutlook" in data
    assert "todayOptionsSetups" in data


def test_api_options_option_chain():
    res = client.get("/api/options/NIFTY/option-chain?filter_mode=ATM")
    assert res.status_code == 200
    data = res.json()
    assert "strikes" in data
    assert "pcr" in data
    assert "maxPain" in data
    assert "oiAnalysis" in data


def test_api_options_setups():
    res = client.get("/api/options/NIFTY/setups")
    assert res.status_code == 200
    data = res.json()
    assert "todayOptionsSetups" in data
    assert "hasQualifiedSetups" in data["todayOptionsSetups"]


def test_next_session_opening_outlook():
    from app.options.opening_outlook import calculate_next_session_opening_outlook
    outlook = calculate_next_session_opening_outlook(
        symbol="NIFTY 50",
        previous_close=24850.0,
        daily_high=24920.0,
        daily_low=24780.0,
        daily_open=24810.0,
        atr_14=120.0,
        vix_value=13.5
    )
    assert "expectedOpeningRange" in outlook
    assert "scenarios" in outlook
    assert "estimatedGap" in outlook
    assert "confidence" in outlook
    assert "supportingEvidence" in outlook
    assert "keyInvalidationConditions" in outlook
    assert outlook["expectedOpeningRange"]["low"] < outlook["expectedOpeningRange"]["high"]
    # Probabilities should exist in scenarios
    probs = outlook["scenarios"]
    assert "bullishGap" in probs
    assert "flatOpening" in probs
    assert "bearishGap" in probs


def test_next_session_recommendation_engine():
    from app.options.next_session_engine import evaluate_next_session_recommendation
    chain = generate_index_option_chain("NIFTY 50", 24850.0, 50.0, filter_mode="ATM")
    
    # Test Bullish Qualification
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
        vix_value=13.5
    )
    assert "stage" in rec
    assert "openingOutlook" in rec
    assert rec["hasQualifiedRecommendation"] is True
    assert rec["recommendation"] is not None
    assert rec["recommendation"]["optionType"] == "CE"
    assert rec["recommendation"]["stopLossPremium"] < rec["recommendation"]["lastVerifiedPremium"]
    assert rec["recommendation"]["target1Premium"] > rec["recommendation"]["lastVerifiedPremium"]
    assert "doNotChaseThreshold" in rec["recommendation"]

    # Test Neutral NO-TRADE Gate
    no_trade_rec = evaluate_next_session_recommendation(
        symbol="NIFTY 50",
        underlying_ltp=24850.0,
        sentiment="NEUTRAL",
        sentiment_score=50,
        strikes_data=chain["strikes"],
        atr_14=120.0,
        daily_high=24920.0,
        daily_low=24780.0,
        daily_close=24800.0,
        daily_open=24810.0,
        vix_value=13.5
    )
    assert no_trade_rec["hasQualifiedRecommendation"] is False
    assert no_trade_rec["decision"] == "NO TRADE"
    assert len(no_trade_rec["reasonsForNoTrade"]) > 0


def test_next_session_backtest():
    from app.options.next_session_backtest import run_next_session_historical_validation
    res = run_next_session_historical_validation(
        symbol="NIFTY 50",
        lookback_sessions=30,
        brokerage_per_order=20.0,
        slippage_pct=0.05
    )
    assert "metrics" in res
    assert "profitFactor" in res["metrics"]
    assert "winRate" in res["metrics"]
    assert "frictionAssumptions" in res
    assert "volatilityRegimePerformance" in res


def test_api_next_session_endpoints():
    res_outlook = client.get("/api/options/NIFTY/next-session/opening-outlook")
    assert res_outlook.status_code == 200
    assert "openingOutlook" in res_outlook.json()

    res_rec = client.get("/api/options/NIFTY/next-session/recommendation")
    assert res_rec.status_code == 200
    rec_data = res_rec.json()
    assert "stage" in rec_data
    assert "openingOutlook" in rec_data

    res_bt = client.get("/api/options/NIFTY/next-session/backtest?lookback_sessions=20")
    assert res_bt.status_code == 200
    assert "metrics" in res_bt.json()


