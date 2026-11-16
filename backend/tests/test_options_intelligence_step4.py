"""
AIVOLVE Quantitative Options Intelligence Engine v3.0 - Phase 2 Step 4.1 Dedicated Tests
Tests:
  1. Brent Numerical IV Solver Convergence (ITM, ATM, OTM)
  2. Invalid IV Inputs and Arbitrage Boundary Violation Rejection
  3. Exact Time-to-Expiry Calculation (IST, UTC, Expiry Day 15:30)
  4. Short Time-to-Expiry Numerical Stability (60m, 30m, 5m, 1m, exact expiry)
  5. Authoritative Expiry Calendar Validation (Holidays, Wednesday/Tuesday expiries)
  6. Field-Level Data Statuses: Missing vs Actual Zero OI & Volume
  7. Greeks Validity, Sensitivities, and Deep ITM Put Positive Theta
  8. Contract Quote Freshness and Depth Validation
  9. Synthetic Fallback Elimination (No mock OI, no mock volume, no fake spreads)
  10. Next-Session Theoretical Valuation Safety & Disclaimers
  11. Option Chain with Verified Live Quotes
  12. IV Dynamics & VIX Correlation Data Integrity
"""

import math
from datetime import datetime, date, time, timezone, timedelta
import zoneinfo
import pytest

from app.options.greeks import (
    norm_cdf,
    norm_pdf,
    calculate_black_scholes,
    calculate_exact_time_to_expiry,
    calculate_implied_volatility_brent,
    validate_contract_quote,
    parse_expiry_to_ist_datetime,
    parse_quote_to_ist_datetime,
)
from app.options.option_chain import generate_index_option_chain
from app.options.iv_analysis import analyze_implied_volatility
from app.options.next_session_engine import evaluate_next_session_recommendation
from app.data.instrument_master import get_instrument_master

IST = zoneinfo.ZoneInfo("Asia/Kolkata")


# =====================================================================
# 1. Brent Numerical IV Solver Convergence Tests
# =====================================================================

def test_brent_iv_convergence_atm():
    """Verify Brent solver recovers known IV for ATM Call and Put options."""
    spot = 24500.0
    strike = 24500.0
    t_years = 7.0 / 365.0
    r = 0.065
    target_iv = 0.155  # 15.5%

    ce_theoretical = calculate_black_scholes(spot, strike, t_years, r, target_iv, "CE")
    pe_theoretical = calculate_black_scholes(spot, strike, t_years, r, target_iv, "PE")

    solved_ce_iv = calculate_implied_volatility_brent(
        market_price=ce_theoretical["price"],
        spot=spot,
        strike=strike,
        time_to_expiry_years=t_years,
        risk_free_rate=r,
        option_type="CE"
    )
    solved_pe_iv = calculate_implied_volatility_brent(
        market_price=pe_theoretical["price"],
        spot=spot,
        strike=strike,
        time_to_expiry_years=t_years,
        risk_free_rate=r,
        option_type="PE"
    )

    assert solved_ce_iv is not None
    assert abs(solved_ce_iv - target_iv) < 1e-4

    assert solved_pe_iv is not None
    assert abs(solved_pe_iv - target_iv) < 1e-4


def test_brent_iv_convergence_itm_and_otm():
    """Verify Brent solver recovers known IV across moneyness levels."""
    spot = 24500.0
    t_years = 14.0 / 365.0
    r = 0.065

    # 1. OTM Call (Strike 25000, 16.0% IV)
    otm_call_iv = 0.160
    otm_call_price = calculate_black_scholes(spot, 25000.0, t_years, r, otm_call_iv, "CE")["price"]
    solved_otm_c = calculate_implied_volatility_brent(otm_call_price, spot, 25000.0, t_years, r, "CE")
    assert solved_otm_c is not None
    assert abs(solved_otm_c - otm_call_iv) < 1e-4

    # 2. ITM Call (Strike 24000, 14.5% IV)
    itm_call_iv = 0.145
    itm_call_price = calculate_black_scholes(spot, 24000.0, t_years, r, itm_call_iv, "CE")["price"]
    solved_itm_c = calculate_implied_volatility_brent(itm_call_price, spot, 24000.0, t_years, r, "CE")
    assert solved_itm_c is not None
    assert abs(solved_itm_c - itm_call_iv) < 1e-4

    # 3. OTM Put (Strike 24000, 18.0% IV)
    otm_put_iv = 0.180
    otm_put_price = calculate_black_scholes(spot, 24000.0, t_years, r, otm_put_iv, "PE")["price"]
    solved_otm_p = calculate_implied_volatility_brent(otm_put_price, spot, 24000.0, t_years, r, "PE")
    assert solved_otm_p is not None
    assert abs(solved_otm_p - otm_put_iv) < 1e-4

    # 4. ITM Put (Strike 25000, 15.0% IV)
    itm_put_iv = 0.150
    itm_put_price = calculate_black_scholes(spot, 25000.0, t_years, r, itm_put_iv, "PE")["price"]
    solved_itm_p = calculate_implied_volatility_brent(itm_put_price, spot, 25000.0, t_years, r, "PE")
    assert solved_itm_p is not None
    assert abs(solved_itm_p - itm_put_iv) < 1e-4


# =====================================================================
# 2. Invalid IV Inputs and Arbitrage Boundary Violation Rejection
# =====================================================================

def test_brent_iv_invalid_inputs():
    """Verify solver rejects non-positive or impossible inputs."""
    assert calculate_implied_volatility_brent(0.0, 24500, 24500, 0.05, 0.065, "CE") is None
    assert calculate_implied_volatility_brent(-10.0, 24500, 24500, 0.05, 0.065, "CE") is None
    assert calculate_implied_volatility_brent(100.0, 0.0, 24500, 0.05, 0.065, "CE") is None
    assert calculate_implied_volatility_brent(100.0, 24500, 0.0, 0.05, 0.065, "CE") is None
    assert calculate_implied_volatility_brent(100.0, 24500, 24500, 0.0, 0.065, "CE") is None
    assert calculate_implied_volatility_brent(100.0, 24500, 24500, -0.01, 0.065, "CE") is None
    assert calculate_implied_volatility_brent(100.0, 24500, 24500, 0.05, -0.01, "CE") is None


def test_brent_iv_arbitrage_boundary_violations():
    """Verify solver rejects option prices violating European arbitrage boundaries."""
    spot = 24500.0
    strike = 24000.0
    t = 10.0 / 365.0
    r = 0.065

    # CE price below intrinsic
    assert calculate_implied_volatility_brent(400.0, spot, strike, t, r, "CE") is None
    # CE price >= spot
    assert calculate_implied_volatility_brent(24600.0, spot, strike, t, r, "CE") is None

    # PE price below intrinsic
    assert calculate_implied_volatility_brent(350.0, 24000.0, 24500.0, t, r, "PE") is None
    # PE price >= strike
    assert calculate_implied_volatility_brent(25000.0, 24000.0, 24500.0, t, r, "PE") is None


# =====================================================================
# 3. Exact Time-to-Expiry Calculation Tests
# =====================================================================

def test_exact_time_to_expiry_calculation():
    """Verify exact time-to-expiry calculation in years, aligned with 15:30 IST."""
    expiry = "2026-11-26"
    quote_ts = "2026-11-26T09:30:00+05:30"
    t_years = calculate_exact_time_to_expiry(expiry, quote_ts)
    expected_hours = 6.0
    actual_hours = t_years * 365.0 * 24.0
    assert abs(actual_hours - expected_hours) < 0.01

    # Exact close at 15:30 IST
    t_exact_close = calculate_exact_time_to_expiry(expiry, "2026-11-26T15:30:00+05:30")
    assert t_exact_close == 0.0

    # Past close
    t_after_close = calculate_exact_time_to_expiry(expiry, "2026-11-26T16:00:00+05:30")
    assert t_after_close == 0.0


# =====================================================================
# 4. Short Time-to-Expiry Numerical Stability (60m, 30m, 5m, 1m, 0m)
# =====================================================================

def test_short_time_to_expiry_greeks_and_iv():
    """
    Verifies that option time value is NOT discarded during the final trading hour.
    Explicitly tests at 60m, 30m, 5m, 1m, and exact expiry.
    """
    spot = 24500.0
    strike = 24500.0
    r = 0.065
    target_iv = 0.160

    durations = [
        ("60m", 60.0 * 60.0),
        ("30m", 30.0 * 60.0),
        ("5m", 5.0 * 60.0),
        ("1m", 1.0 * 60.0),
    ]

    for label, sec in durations:
        t_years = sec / (365.0 * 86400.0)
        # 1. Black-Scholes must compute valid positive time value and Greeks
        greeks = calculate_black_scholes(spot, strike, t_years, r, target_iv, "CE")
        assert greeks is not None, f"Failed at {label}"
        assert greeks["price"] > 0.0, f"Price should be > 0 at {label}"
        assert 0.49 < greeks["delta"] < 0.52, f"Delta anomaly at {label}"
        assert greeks["gamma"] > 0.0, f"Gamma anomaly at {label}"
        assert greeks["vega"] > 0.0, f"Vega anomaly at {label}"

        # 2. Brent IV solver must accurately invert the premium
        recovered_iv = calculate_implied_volatility_brent(greeks["price"], spot, strike, t_years, r, "CE")
        assert recovered_iv is not None, f"IV solver failed to invert at {label}"
        assert abs(recovered_iv - target_iv) < 1e-3, f"IV deviation at {label}: {recovered_iv} vs {target_iv}"

    # Exact Expiry (0 seconds remaining)
    greeks_exp = calculate_black_scholes(spot, strike, 0.0, r, target_iv, "CE")
    assert greeks_exp["price"] == 0.0
    assert greeks_exp["gamma"] == 0.0
    assert greeks_exp["theta"] == 0.0
    assert greeks_exp["vega"] == 0.0


# =====================================================================
# 5. Authoritative Expiry Calendar Validation
# =====================================================================

def test_expiry_calendar_authoritative_dates_and_holidays():
    """
    Verifies that contract expiry parsing never hardcodes Thursday or Wednesday.
    Accurately supports arbitrary weekdays (e.g. Tuesday holiday shifts) and explicit timestamps.
    """
    # 1. Tuesday Expiry (e.g. holiday shifted)
    dt_tues = parse_expiry_to_ist_datetime("24NOV2026")
    assert dt_tues.strftime("%A") == "Tuesday"
    assert dt_tues.time() == time(15, 30, 0)

    # 2. Wednesday Expiry (e.g. Bank Nifty weekly cycle)
    dt_wed = parse_expiry_to_ist_datetime("25NOV2026")
    assert dt_wed.strftime("%A") == "Wednesday"
    assert dt_wed.time() == time(15, 30, 0)

    # 3. Explicit exchange timestamp preservation (e.g. 14:45 closing session)
    dt_custom = parse_expiry_to_ist_datetime("2026-11-26T14:45:00+05:30")
    assert dt_custom.time() == time(14, 45, 0)

    # 4. Format variations
    for fmt in ["26NOV2026", "26-Nov-2026", "2026-11-26", "26 Nov 2026"]:
        parsed = parse_expiry_to_ist_datetime(fmt)
        assert parsed.date() == date(2026, 11, 26)
        assert parsed.time() == time(15, 30, 0)


# =====================================================================
# 6. Field-Level Data Statuses: Missing vs Actual Zero OI & Volume
# =====================================================================

def test_missing_vs_actual_zero_oi_and_volume():
    """
    Verifies strict distinction between:
    - Actual verified zero open interest (oi=0, oiStatus='AVAILABLE')
    - Missing feed open interest (oi=None, oiStatus='MISSING')
    - Actual verified zero volume (volume=0, volumeStatus='AVAILABLE')
    - Missing feed volume (volume=None, volumeStatus='MISSING')
    """
    now_iso = datetime.now(IST).isoformat()

    # 1. Verified Zero OI and Volume
    q_zero = {
        "ltp": 50.0,
        "bid": 49.0,
        "ask": 51.0,
        "openInterest": 0,
        "volume": 0,
        "marketTimestamp": now_iso,
    }
    v_zero = validate_contract_quote(q_zero)
    assert v_zero["oi"] == 0
    assert v_zero["oiStatus"] == "AVAILABLE"
    assert "ZERO_OI" in v_zero["issues"]
    assert "MISSING_OI" not in v_zero["issues"]

    assert v_zero["volume"] == 0
    assert v_zero["volumeStatus"] == "AVAILABLE"
    assert "ZERO_VOLUME" in v_zero["issues"]
    assert "MISSING_VOLUME" not in v_zero["issues"]

    # 2. Missing OI and Volume (omitted from quote)
    q_missing = {
        "ltp": 50.0,
        "bid": 49.0,
        "ask": 51.0,
        "marketTimestamp": now_iso,
    }
    v_missing = validate_contract_quote(q_missing)
    assert v_missing["oi"] is None
    assert v_missing["oiStatus"] == "MISSING"
    assert "MISSING_OI" in v_missing["issues"]

    assert v_missing["volume"] is None
    assert v_missing["volumeStatus"] == "MISSING"
    assert "MISSING_VOLUME" in v_missing["issues"]


# =====================================================================
# 7. Greeks Validity, Sensitivities, and Deep ITM Put Positive Theta
# =====================================================================

def test_deep_itm_put_positive_theta_and_sensitivities():
    """
    Demonstrates that European Put theta can be mathematically positive
    when deep in-the-money and risk-free rate r > 0.
    """
    spot = 10000.0
    strike = 25000.0
    t = 0.5
    r = 0.065
    sigma = 0.15

    deep_put = calculate_black_scholes(spot, strike, t, r, sigma, "PE")
    assert deep_put is not None
    # Put delta should be close to -1.0
    assert -1.0 <= deep_put["delta"] < -0.99
    # Mathematical property: Deep ITM European put has positive theta
    assert deep_put["theta"] > 0.0, f"Expected positive theta for deep ITM put, got {deep_put['theta']}"

    # Standard ATM Call: theta must be negative
    atm_call = calculate_black_scholes(24500.0, 24500.0, t, r, sigma, "CE")
    assert atm_call["theta"] < 0.0


def test_put_call_parity_across_rates():
    """Verifies European Put-Call Parity: C - P = S - K * exp(-rt)."""
    spot = 24500.0
    strike = 24500.0
    t = 30.0 / 365.0
    sigma = 0.18

    for r in [0.0, 0.065, 0.10]:
        ce = calculate_black_scholes(spot, strike, t, r, sigma, "CE")
        pe = calculate_black_scholes(spot, strike, t, r, sigma, "PE")
        exp_rt = math.exp(-r * t)
        parity_err = abs((ce["price"] - pe["price"]) - (spot - strike * exp_rt))
        assert parity_err < 0.10, f"Parity failed at r={r}: err={parity_err}"


# =====================================================================
# 8. Contract Quote Freshness and Depth Validation
# =====================================================================

def test_quote_validation_inverted_spread():
    """Inverted spread (bid > ask) must be rejected with INVALID_QUOTE."""
    quote = {
        "ltp": 150.0,
        "bid": 155.0,
        "ask": 145.0,
        "openInterest": 10000,
        "volume": 5000,
    }
    val = validate_contract_quote(quote)
    assert val["isValid"] is False
    assert val["status"] == "INVALID_QUOTE"
    assert val["quoteStatus"] == "INVALID"
    assert "INVERTED_SPREAD" in val["issues"]


def test_quote_validation_stale_quote():
    """Quote older than 180 seconds must be flagged as STALE."""
    old_time = (datetime.now(IST) - timedelta(seconds=240)).isoformat()
    quote = {
        "ltp": 150.0,
        "bid": 149.0,
        "ask": 151.0,
        "openInterest": 50000,
        "volume": 10000,
        "marketTimestamp": old_time
    }
    val = validate_contract_quote(quote, max_stale_seconds=180)
    assert val["isValid"] is False
    assert val["status"] == "STALE"
    assert val["quoteStatus"] == "STALE"
    assert "STALE_QUOTE" in val["issues"]


# =====================================================================
# 9. Synthetic Fallback Elimination Tests
# =====================================================================

def test_option_chain_synthetic_fallback_elimination():
    """Verify generate_index_option_chain without broker quotes eliminates synthetic data."""
    chain = generate_index_option_chain("NIFTY 50", 24500.0, 0.0, real_quotes_map=None)

    assert chain["dataStatus"] == "DATA_UNAVAILABLE"
    assert chain["totalCallOi"] == 0
    assert chain["totalPutOi"] == 0

    for strike in chain["strikes"]:
        ce = strike["ce"]
        pe = strike["pe"]

        assert ce["dataStatus"] == "DATA_UNAVAILABLE"
        assert pe["dataStatus"] == "DATA_UNAVAILABLE"

        assert ce["ltp"] is None
        assert ce["bid"] is None
        assert ce["ask"] is None
        assert ce["spread"] is None
        assert ce["iv"] is None
        assert ce["delta"] is None

        # Distinct missing statuses
        assert ce["oi"] is None
        assert ce["oiStatus"] == "MISSING"
        assert ce["volume"] is None
        assert ce["volumeStatus"] == "MISSING"


# =====================================================================
# 10. Next-Session Theoretical Valuation Safety & Disclaimers
# =====================================================================

def test_next_session_theoretical_tagging():
    """
    Verifies that when next_session_engine evaluates without live quotes,
    it stamps the recommendation as THEORETICAL and non-executable.
    """
    strikes = [{
        "strike": 24850.0,
        "ce": {"ltp": None, "oi": None, "oiStatus": "MISSING", "dataStatus": "DATA_UNAVAILABLE"},
        "pe": {"ltp": None, "oi": None, "oiStatus": "MISSING", "dataStatus": "DATA_UNAVAILABLE"}
    }]

    rec = evaluate_next_session_recommendation(
        symbol="NIFTY 50",
        underlying_ltp=24850.0,
        sentiment="BULLISH",
        sentiment_score=72,
        strikes_data=strikes,
        atr_14=120.0,
        daily_high=24920.0,
        daily_low=24780.0,
        daily_close=24800.0,
        daily_open=24810.0,
        vix_value=13.5
    )

    assert rec["hasQualifiedRecommendation"] is True
    rec_detail = rec["recommendation"]
    assert rec_detail["isTheoretical"] is True
    assert rec_detail["premiumSource"] == "THEORETICAL"
    assert rec_detail["isExecutable"] is False
    assert rec_detail["dataStatus"] == "THEORETICAL"
    assert "THEORETICAL" in rec_detail["priceDisclaimers"]["lastObserved"]


# =====================================================================
# 11. Option Chain with Verified Live Quotes
# =====================================================================

def test_option_chain_with_live_quotes():
    """Verify option chain correctly computes Brent IV and Greeks when live quotes are supplied."""
    master = get_instrument_master()
    expiries = master.get_expiries("NIFTY")
    selected_expiry = expiries[0] if expiries else "2026-11-26"

    ce_contract = master.resolve_option_contract("NIFTY", 24500.0, "CE", selected_expiry)
    pe_contract = master.resolve_option_contract("NIFTY", 24500.0, "PE", selected_expiry)

    assert ce_contract is not None
    assert pe_contract is not None

    ce_token = str(ce_contract["token"])
    pe_token = str(pe_contract["token"])

    now_iso = datetime.now(IST).isoformat()
    mock_quotes = {
        ce_token: {
            "symbolToken": ce_token,
            "tradingSymbol": ce_contract["symbol"],
            "ltp": 165.0,
            "bid": 164.5,
            "ask": 165.5,
            "openInterest": 150000,
            "volume": 25000,
            "change": 1200,
            "marketTimestamp": now_iso,
        },
        pe_token: {
            "symbolToken": pe_token,
            "tradingSymbol": pe_contract["symbol"],
            "ltp": 140.0,
            "bid": 139.5,
            "ask": 140.5,
            "openInterest": 180000,
            "volume": 30000,
            "change": 2500,
            "marketTimestamp": now_iso,
        }
    }

    chain = generate_index_option_chain(
        symbol="NIFTY",
        underlying_ltp=24500.0,
        underlying_change=25.0,
        real_quotes_map=mock_quotes,
        expiry=selected_expiry
    )

    assert chain["dataStatus"] == "LIVE"
    atm_strike_data = next((s for s in chain["strikes"] if abs(s["strike"] - 24500.0) < 1.0), None)
    assert atm_strike_data is not None

    ce = atm_strike_data["ce"]
    assert ce["dataStatus"] == "LIVE"
    assert ce["quoteStatus"] == "AVAILABLE"
    assert ce["oiStatus"] == "AVAILABLE"
    assert ce["volumeStatus"] == "AVAILABLE"
    assert ce["ltp"] == 165.0
    assert ce["oi"] == 150000
    assert ce["volume"] == 25000
    assert ce["iv"] is not None and ce["iv"] > 0.0
    assert ce["delta"] is not None and 0.0 < ce["delta"] < 1.0


# =====================================================================
# 12. IV Dynamics & VIX Correlation Data Integrity
# =====================================================================

def test_iv_analysis_data_integrity():
    """Verify analyze_implied_volatility does not fabricate ATM IV or conflate with VIX."""
    res_empty = analyze_implied_volatility([], underlying_ltp=24500.0, vix_value=14.5)
    assert res_empty["atmIv"] is None
    assert res_empty["vixValue"] == 14.5
    assert res_empty["regime"] == "Moderate"

    strikes_no_iv = [{
        "strike": 24500.0,
        "ce": {"iv": None},
        "pe": {"iv": None}
    }]
    res_no_iv = analyze_implied_volatility(strikes_no_iv, underlying_ltp=24500.0, vix_value=18.0)
    assert res_no_iv["atmIv"] is None
    assert res_no_iv["ivSkew"] is None
    assert res_no_iv["regime"] == "Elevated"
