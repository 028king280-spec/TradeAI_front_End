"""
AIVOLVE Institutional Quantitative Trading Intelligence v3.0
Phase 2 Step 4.3 Dedicated Test Suite: Production API Integration & End-to-End Signal Pipeline

Comprehensive tests covering all 20 required integration scenarios:
  A. Valid BUY_CE end-to-end pipeline
  B. Valid BUY_PE end-to-end pipeline
  C. Missing 1H timeframe (capped score at 60)
  D. Missing 15M timeframe (directional trade lockout)
  E. Missing 5M timeframe (total execution lockout)
  F. Incomplete candle rejection
  G. Stale market data rejection
  H. Synthetic/mock data rejection
  I. Missing option quote rejection
  J. Missing OI/volume rejection
  K. Invalid bid/ask spread rejection
  L. Invalid option contract rejection (Delta outside 0.35-0.55)
  M. Invalid stop-loss geometry rejection
  N. Insufficient reward-risk rejection (< 1.5)
  O. Missing capital budget behavior
  P. Empty signals database returns empty result (zero fake auto-seeding)
  Q. Repeated API request does not create duplicate signals (idempotency)
  R. Paper account balance remains unchanged for analysis-only requests
  S. Existing frontend response compatibility
  T. SENSEX remains locked when governance policy is unconfigured
"""

from typing import Dict, Any, List
import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
import zoneinfo

from app.options.pipeline_orchestrator import (
    execute_production_signal_pipeline,
    format_to_frontend_options_setups,
    PipelineStage,
    canonicalize_symbol,
)
from app.options.contract_selector import (
    set_governance_ledger_db_path,
    CENTRALIZED_INDEX_LIQUIDITY_POLICY,
)
from app.options.greeks import calculate_black_scholes, calculate_exact_time_to_expiry
from app.data.quality_validator import FeedStatus
from app.options.paper_trading.paper_engine import PaperTradingEngine
from app.models.db_models import SignalRecord
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
from app.db.database import Base

IST = zoneinfo.ZoneInfo("Asia/Kolkata")


@pytest.fixture(autouse=True)
def isolated_governance_ledger(tmp_path):
    """Ensures governance ledger is isolated in ephemeral SQLite file."""
    test_db = str(tmp_path / "test_pipeline_governance.db")
    set_governance_ledger_db_path(test_db)
    yield test_db
    set_governance_ledger_db_path(None)


@pytest.fixture(autouse=True)
def default_live_market_session():
    """Default to live market session for pipeline integration tests unless overridden."""
    with patch("app.data.quality_validator.MarketCalendar.is_market_open", return_value=True):
        yield


@pytest.fixture
async def async_test_session(tmp_path):
    """Provides an isolated in-memory SQLite database session for SignalRecord testing."""
    db_file = str(tmp_path / "test_signals_pipeline.db")
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with async_session() as session:
        yield session
    await engine.dispose()


# ---------------------------------------------------------------------------
# Helpers for Realistic Candle & Option Chain Synthesis
# ---------------------------------------------------------------------------
def generate_candle_series(
    n_bars: int,
    start_price: float,
    trend: str = "bullish",
    step_pts: float = 3.0,
    volatility: float = 2.0,
    volume_base: int = 5000,
) -> pd.DataFrame:
    """Generates realistic OHLCV candlestick series with monotonic timestamps."""
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
            "is_complete": True,
        })
        p = c

    return pd.DataFrame(rows)


def build_mock_option_chain(
    symbol: str = "NIFTY",
    underlying_spot: float = 24500.0,
    expiry_days_ahead: int = 5,
    strikes: list = None,
    iv: float = 15.0,
    r: float = 0.065,
    custom_ce_overrides: dict = None,
    custom_pe_overrides: dict = None,
) -> Dict[str, Any]:
    """Generates an authentic Black-Scholes consistent option chain."""
    now_ist = datetime.now(IST)
    expiry_dt = (now_ist + timedelta(days=expiry_days_ahead)).replace(hour=15, minute=30, second=0, microsecond=0)
    expiry_str = expiry_dt.strftime("%d-%b-%Y").upper()
    t_years = calculate_exact_time_to_expiry(expiry_str, now_ist)

    if strikes is None:
        strikes = [24300, 24350, 24400, 24450, 24500, 24550, 24600, 24650, 24700]

    lot_size = 15 if "BANK" in symbol else (25 if "FIN" in symbol else 65)

    strike_records = []
    for k in strikes:
        k_flt = float(k)
        ce_bs = calculate_black_scholes(underlying_spot, k_flt, t_years, r, iv / 100.0, "CE")
        pe_bs = calculate_black_scholes(underlying_spot, k_flt, t_years, r, iv / 100.0, "PE")

        ce_price = round(ce_bs["price"], 2)
        pe_price = round(pe_bs["price"], 2)

        ce_data = {
            "symbol": f"{symbol}{expiry_str}{k}CE",
            "token": f"CE_{k}",
            "expiry": expiry_str,
            "ltp": ce_price,
            "bid": round(ce_price - 0.15, 2),
            "ask": round(ce_price + 0.15, 2),
            "spread_pct": round(0.30 / ce_price, 4) if ce_price > 0 else 0.0,
            "delta": ce_bs["delta"],
            "gamma": ce_bs["gamma"],
            "theta": ce_bs["theta"],
            "vega": ce_bs["vega"],
            "iv": iv,
            "iv_source": "BRENT_NUMERICAL",
            "oi": 150000,
            "volume": 75000,
            "lot_size": lot_size,
            "tick_size": 0.05,
            "isStale": False,
            "isTheoretical": False,
            "data_status": "LIVE",
        }

        pe_data = {
            "symbol": f"{symbol}{expiry_str}{k}PE",
            "token": f"PE_{k}",
            "expiry": expiry_str,
            "ltp": pe_price,
            "bid": round(pe_price - 0.15, 2),
            "ask": round(pe_price + 0.15, 2),
            "spread_pct": round(0.30 / pe_price, 4) if pe_price > 0 else 0.0,
            "delta": pe_bs["delta"],
            "gamma": pe_bs["gamma"],
            "theta": pe_bs["theta"],
            "vega": pe_bs["vega"],
            "iv": iv,
            "iv_source": "BRENT_NUMERICAL",
            "oi": 140000,
            "volume": 65000,
            "lot_size": lot_size,
            "tick_size": 0.05,
            "isStale": False,
            "isTheoretical": False,
            "data_status": "LIVE",
        }

        if custom_ce_overrides and k in custom_ce_overrides:
            ce_data.update(custom_ce_overrides[k])
        if custom_pe_overrides and k in custom_pe_overrides:
            pe_data.update(custom_pe_overrides[k])

        strike_records.append({
            "strike": k_flt,
            "ce": ce_data,
            "pe": pe_data,
        })

    return {
        "symbol": symbol,
        "selectedExpiry": expiry_str,
        "underlyingPrice": underlying_spot,
        "strikes": strike_records,
        "dataStatus": "LIVE",
    }


def make_bullish_timeframes(base_price: float = 24500.0) -> Dict[str, pd.DataFrame]:
    df_1h = generate_candle_series(20, start_price=base_price - 200, trend="bullish", step_pts=15.0)
    df_15m = generate_candle_series(25, start_price=base_price - 100, trend="bullish", step_pts=8.0)
    df_5m = generate_candle_series(20, start_price=base_price, trend="bullish", step_pts=5.0)
    df_1m = generate_candle_series(15, start_price=base_price + 80, trend="bullish", step_pts=2.0)
    return {"1h": df_1h, "15m": df_15m, "5m": df_5m, "1m": df_1m}


def make_bearish_timeframes(base_price: float = 24500.0) -> Dict[str, pd.DataFrame]:
    df_1h = generate_candle_series(20, start_price=base_price + 200, trend="bearish", step_pts=15.0)
    df_15m = generate_candle_series(25, start_price=base_price + 100, trend="bearish", step_pts=7.2)
    df_5m = generate_candle_series(20, start_price=base_price - 30, trend="bearish", step_pts=5.0)
    df_1m = generate_candle_series(15, start_price=base_price - 115, trend="bearish", step_pts=2.0)
    return {"1h": df_1h, "15m": df_15m, "5m": df_5m, "1m": df_1m}


# ===========================================================================
# A. Valid BUY_CE End-to-End Pipeline
# ===========================================================================
@pytest.mark.asyncio
async def test_scenario_a_valid_buy_ce_pipeline():
    """Verify complete 12-stage pipeline execution for fully aligned BUY_CE."""
    tfs = make_bullish_timeframes(24500.0)
    ltp = float(tfs["1m"]["close"].iloc[-1])
    quote = {
        "currentPrice": ltp,
        "dayHigh": ltp + 10.0,
        "dayLow": 24300.0,
        "openPrice": 24400.0,
        "previousClose": 24350.0,
        "change": ltp - 24350.0,
        "provider": "angelone",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    chain = build_mock_option_chain("NIFTY", ltp, strikes=[24500, 24550, 24600, 24650, 24700])

    res = await execute_production_signal_pipeline(
        "NIFTY 50",
        custom_timeframes=tfs,
        custom_quote=quote,
        custom_option_chain=chain,
        available_capital=100000.0,
    )

    assert res["action"] == "BUY_CE"
    assert res["is_trade_qualified"] is True
    assert res["stage_status"][PipelineStage.STAGE_11_FINAL_QUALIFICATION] == "QUALIFIED"
    assert res["selected_contract"]["option_type"] == "CE"
    assert 0.35 <= abs(res["selected_contract"]["delta"]) <= 0.55
    assert res["risk_plan"]["entry_execution_model"] == "ASK"
    assert res["trade_setup"]["reward_risk_ratio"] >= 1.5

    fe = res["frontend_options_setups"]
    assert fe["hasQualifiedSetups"] is True
    assert len(fe["setups"]) == 1
    assert fe["setups"][0]["bias"] == "CE"
    assert fe["setups"][0]["currentPremium"] == res["risk_plan"]["entry_premium"]


# ===========================================================================
# B. Valid BUY_PE End-to-End Pipeline
# ===========================================================================
@pytest.mark.asyncio
async def test_scenario_b_valid_buy_pe_pipeline():
    """Verify complete 12-stage pipeline execution for fully aligned BUY_PE."""
    tfs = make_bearish_timeframes(24500.0)
    ltp = float(tfs["1m"]["close"].iloc[-1])
    quote = {
        "currentPrice": ltp,
        "dayHigh": 24700.0,
        "dayLow": ltp - 2.0,
        "openPrice": 24600.0,
        "previousClose": 24650.0,
        "change": ltp - 24650.0,
        "provider": "angelone",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    chain = build_mock_option_chain("NIFTY", ltp, strikes=[24150, 24200, 24250, 24300, 24350])

    res = await execute_production_signal_pipeline(
        "NIFTY 50",
        custom_timeframes=tfs,
        custom_quote=quote,
        custom_option_chain=chain,
        available_capital=100000.0,
    )

    assert res["action"] == "BUY_PE"
    assert res["is_trade_qualified"] is True
    assert res["selected_contract"]["option_type"] == "PE"
    assert 0.35 <= abs(res["selected_contract"]["delta"]) <= 0.55
    assert res["risk_plan"]["stop_loss_premium"] < res["risk_plan"]["entry_premium"]
    assert res["risk_plan"]["target_1_premium"] > res["risk_plan"]["entry_premium"]

    fe = res["frontend_options_setups"]
    assert fe["hasQualifiedSetups"] is True
    assert fe["setups"][0]["bias"] == "PE"


# ===========================================================================
# C. Missing 1H Timeframe (Capped Score at 60)
# ===========================================================================
@pytest.mark.asyncio
async def test_scenario_c_missing_1h_timeframe():
    """Verify missing 1H timeframe caps confluence score at 60 and restricts trade."""
    tfs = make_bullish_timeframes(24500.0)
    tfs["1h"] = None  # Missing 1H

    ltp = float(tfs["1m"]["close"].iloc[-1])
    quote = {"currentPrice": ltp, "dayHigh": ltp + 10.0, "dayLow": 24300.0, "openPrice": 24400.0, "previousClose": 24350.0, "change": ltp - 24350.0, "provider": "angelone", "timestamp": datetime.now(timezone.utc).isoformat()}
    chain = build_mock_option_chain("NIFTY", ltp, strikes=[24500, 24550, 24600, 24650, 24700])

    res = await execute_production_signal_pipeline(
        "NIFTY 50",
        custom_timeframes=tfs,
        custom_quote=quote,
        custom_option_chain=chain,
    )

    assert res["mtf_confluence"]["confluence_score"] <= 60.0
    assert res["is_trade_qualified"] is False
    assert res["action"] in ("WAIT", "NO_TRADE")


# ===========================================================================
# D. Missing 15M Timeframe (Directional Trade Lockout)
# ===========================================================================
@pytest.mark.asyncio
async def test_scenario_d_missing_15m_timeframe_lockout():
    """Verify missing 15M triggers directional trade lockout."""
    tfs = make_bullish_timeframes(24500.0)
    tfs["15m"] = None  # Missing 15M

    ltp = float(tfs["1m"]["close"].iloc[-1])
    quote = {"currentPrice": ltp, "dayHigh": ltp + 10.0, "dayLow": 24300.0, "openPrice": 24400.0, "previousClose": 24350.0, "change": ltp - 24350.0, "provider": "angelone", "timestamp": datetime.now(timezone.utc).isoformat()}

    with patch("app.data.quality_validator.MarketCalendar.is_market_open", return_value=True):
        res = await execute_production_signal_pipeline(
            "NIFTY 50",
            custom_timeframes=tfs,
            custom_quote=quote,
        )

    assert res["action"] == "NO_TRADE"
    assert res["is_trade_qualified"] is False
    assert any("15M" in r for r in res["rejection_reasons"])


# ===========================================================================
# E. Missing 5M Timeframe (Total Execution Lockout)
# ===========================================================================
@pytest.mark.asyncio
async def test_scenario_e_missing_5m_timeframe_lockout():
    """Verify missing 5M intermediate timeframe triggers total execution lockout."""
    tfs = make_bullish_timeframes(24500.0)
    tfs["5m"] = None  # Missing 5M

    ltp = float(tfs["1m"]["close"].iloc[-1])
    quote = {"currentPrice": ltp, "dayHigh": ltp + 10.0, "dayLow": 24300.0, "openPrice": 24400.0, "previousClose": 24350.0, "change": ltp - 24350.0, "provider": "angelone", "timestamp": datetime.now(timezone.utc).isoformat()}

    with patch("app.data.quality_validator.MarketCalendar.is_market_open", return_value=True):
        res = await execute_production_signal_pipeline(
            "NIFTY 50",
            custom_timeframes=tfs,
            custom_quote=quote,
        )

    assert res["action"] == "NO_TRADE"
    assert res["is_trade_qualified"] is False
    assert any("5M" in r for r in res["rejection_reasons"])


# ===========================================================================
# F. Incomplete Candle Rejection
# ===========================================================================
@pytest.mark.asyncio
async def test_scenario_f_incomplete_candle_rejection():
    """Verify live forming candles are filtered and cannot trigger execution."""
    tfs = make_bullish_timeframes(24500.0)
    # Mark the last 1M bar as forming
    tfs["1m"].iloc[-1, tfs["1m"].columns.get_loc("is_complete")] = False

    ltp = float(tfs["1m"]["close"].iloc[-2])
    quote = {"currentPrice": ltp, "dayHigh": ltp + 10.0, "dayLow": 24300.0, "openPrice": 24400.0, "previousClose": 24350.0, "change": ltp - 24350.0, "provider": "angelone", "timestamp": datetime.now(timezone.utc).isoformat()}
    chain = build_mock_option_chain("NIFTY", ltp, strikes=[24500, 24550, 24600, 24650, 24700])

    res = await execute_production_signal_pipeline(
        "NIFTY 50",
        custom_timeframes=tfs,
        custom_quote=quote,
        custom_option_chain=chain,
    )
    # Forming candle was excluded cleanly
    assert res["stage_status"][PipelineStage.STAGE_3_CANDLE_COMPLETENESS] == "SUCCESS"


# ===========================================================================
# G. Stale Market Data Rejection
# ===========================================================================
@pytest.mark.asyncio
async def test_scenario_g_stale_market_data_rejection():
    """Verify stale market quote feed is rejected at Stage 2."""
    tfs = make_bullish_timeframes(24500.0)
    ltp = float(tfs["1m"]["close"].iloc[-1])
    # Timestamp delayed by 2 hours
    stale_ts = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    quote = {
        "currentPrice": ltp,
        "dayHigh": ltp + 10.0,
        "dayLow": 24300.0,
        "openPrice": 24400.0,
        "previousClose": 24350.0,
        "change": ltp - 24350.0,
        "provider": "angelone",
        "timestamp": stale_ts,
    }

    with patch("app.data.quality_validator.MarketCalendar.is_market_open", return_value=True):
        res = await execute_production_signal_pipeline(
            "NIFTY 50",
            custom_timeframes=tfs,
            custom_quote=quote,
        )

    assert res["action"] == "NO_TRADE"
    assert res["is_trade_qualified"] is False
    assert any("Stale" in r or "latency" in r or "stale" in r for r in res["rejection_reasons"])


# ===========================================================================
# H. Synthetic/Mock Data Rejection
# ===========================================================================
@pytest.mark.asyncio
async def test_scenario_h_synthetic_mock_data_rejection():
    """Verify synthetic or mock market data is rejected at Stage 2."""
    tfs = make_bullish_timeframes(24500.0)
    ltp = float(tfs["1m"]["close"].iloc[-1])
    quote = {
        "currentPrice": ltp,
        "dayHigh": ltp + 10.0,
        "dayLow": 24300.0,
        "openPrice": 24400.0,
        "previousClose": 24350.0,
        "change": ltp - 24350.0,
        "provider": "mock",
        "is_mock": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    with patch("app.data.quality_validator.MarketCalendar.is_market_open", return_value=True):
        res = await execute_production_signal_pipeline(
            "NIFTY 50",
            custom_timeframes=tfs,
            custom_quote=quote,
        )

    assert res["action"] == "NO_TRADE"
    assert res["is_trade_qualified"] is False
    assert any("Synthetic or mock" in r for r in res["rejection_reasons"])


# ===========================================================================
# I. Missing Option Quote Rejection
# ===========================================================================
@pytest.mark.asyncio
async def test_scenario_i_missing_option_quote_rejection():
    """Verify option chain with missing broker quotes fails closed."""
    tfs = make_bullish_timeframes(24500.0)
    ltp = float(tfs["1m"]["close"].iloc[-1])
    quote = {"currentPrice": ltp, "dayHigh": ltp + 10.0, "dayLow": 24300.0, "openPrice": 24400.0, "previousClose": 24350.0, "change": ltp - 24350.0, "provider": "angelone", "timestamp": datetime.now(timezone.utc).isoformat()}

    res = await execute_production_signal_pipeline(
        "NIFTY 50",
        custom_timeframes=tfs,
        custom_quote=quote,
        custom_option_chain={"strikes": []},  # Empty chain
    )

    assert res["action"] == "NO_TRADE"
    assert res["is_trade_qualified"] is False
    assert any("Option chain" in r for r in res["rejection_reasons"])


# ===========================================================================
# J. Missing OI/Volume Rejection
# ===========================================================================
@pytest.mark.asyncio
async def test_scenario_j_low_oi_volume_rejection():
    """Verify illiquid option contract with zero volume/OI is rejected."""
    tfs = make_bullish_timeframes(24500.0)
    ltp = float(tfs["1m"]["close"].iloc[-1])
    quote = {"currentPrice": ltp, "dayHigh": ltp + 10.0, "dayLow": 24300.0, "openPrice": 24400.0, "previousClose": 24350.0, "change": ltp - 24350.0, "provider": "angelone", "timestamp": datetime.now(timezone.utc).isoformat()}

    # All contracts have 0 volume and 0 OI
    chain = build_mock_option_chain(
        "NIFTY", ltp,
        strikes=[24500, 24550, 24600, 24650, 24700],
        custom_ce_overrides={k: {"oi": 0, "volume": 0} for k in [24500, 24550, 24600, 24650, 24700]}
    )

    res = await execute_production_signal_pipeline(
        "NIFTY 50",
        custom_timeframes=tfs,
        custom_quote=quote,
        custom_option_chain=chain,
    )

    assert res["action"] == "NO_TRADE"
    assert res["is_trade_qualified"] is False
    assert any("liquid" in r.lower() or "oi" in r.lower() or "volume" in r.lower() or "spread" in r.lower() or "rejected" in r.lower() for r in res["rejection_reasons"])


# ===========================================================================
# K. Invalid Bid/Ask Spread Rejection
# ===========================================================================
@pytest.mark.asyncio
async def test_scenario_k_excessive_spread_rejection():
    """Verify contracts with bid/ask spread exceeding policy ceiling are rejected."""
    tfs = make_bullish_timeframes(24500.0)
    ltp = float(tfs["1m"]["close"].iloc[-1])
    quote = {"currentPrice": ltp, "dayHigh": ltp + 10.0, "dayLow": 24300.0, "openPrice": 24400.0, "previousClose": 24350.0, "change": ltp - 24350.0, "provider": "angelone", "timestamp": datetime.now(timezone.utc).isoformat()}

    # Blow out the spreads to 10%
    chain = build_mock_option_chain(
        "NIFTY", ltp,
        strikes=[24500, 24550, 24600, 24650, 24700],
        custom_ce_overrides={
            k: {"bid": 50.0, "ask": 75.0, "spread_pct": 0.50} for k in [24500, 24550, 24600, 24650, 24700]
        }
    )

    res = await execute_production_signal_pipeline(
        "NIFTY 50",
        custom_timeframes=tfs,
        custom_quote=quote,
        custom_option_chain=chain,
    )

    assert res["action"] == "NO_TRADE"
    assert res["is_trade_qualified"] is False
    assert any("spread" in r.lower() or "rejected" in r.lower() for r in res["rejection_reasons"])


# ===========================================================================
# L. Invalid Option Contract Rejection (Delta outside 0.35 - 0.55)
# ===========================================================================
@pytest.mark.asyncio
async def test_scenario_l_delta_out_of_bounds_rejection():
    """Verify contracts outside 0.35-0.55 delta band are rejected."""
    tfs = make_bullish_timeframes(24500.0)
    ltp = float(tfs["1m"]["close"].iloc[-1])
    quote = {"currentPrice": ltp, "dayHigh": ltp + 10.0, "dayLow": 24300.0, "openPrice": 24400.0, "previousClose": 24350.0, "change": ltp - 24350.0, "provider": "angelone", "timestamp": datetime.now(timezone.utc).isoformat()}

    # Force all deltas to 0.15 (deep OTM)
    chain = build_mock_option_chain(
        "NIFTY", ltp,
        strikes=[24500, 24550, 24600, 24650, 24700],
        custom_ce_overrides={k: {"delta": 0.15} for k in [24500, 24550, 24600, 24650, 24700]}
    )

    res = await execute_production_signal_pipeline(
        "NIFTY 50",
        custom_timeframes=tfs,
        custom_quote=quote,
        custom_option_chain=chain,
    )

    assert res["action"] == "NO_TRADE"
    assert res["is_trade_qualified"] is False


# ===========================================================================
# M. Invalid Stop-Loss Geometry Rejection
# ===========================================================================
@pytest.mark.asyncio
async def test_scenario_m_invalid_stop_loss_geometry():
    """Verify inverted stop-loss geometry is rejected at Stage 7."""
    tfs = make_bullish_timeframes(24500.0)
    ltp = float(tfs["1m"]["close"].iloc[-1])
    quote = {"currentPrice": ltp, "dayHigh": ltp + 10.0, "dayLow": 24300.0, "openPrice": 24400.0, "previousClose": 24350.0, "change": ltp - 24350.0, "provider": "angelone", "timestamp": datetime.now(timezone.utc).isoformat()}
    chain = build_mock_option_chain("NIFTY", ltp, strikes=[24500, 24550, 24600, 24650, 24700])

    # Invert target geometry so Target 2 < Target 1
    res = await execute_production_signal_pipeline(
        "NIFTY 50",
        custom_timeframes=tfs,
        custom_quote=quote,
        custom_option_chain=chain,
        config={"trade_setup_config": {"target_1_rr": 3.0, "target_2_rr": 1.0}},
    )

    assert res["action"] == "NO_TRADE"
    assert res["is_trade_qualified"] is False
    assert any("geometry" in r.lower() or "invalid" in r.lower() or "unqualified" in r.lower() for r in res["rejection_reasons"])


# ===========================================================================
# N. Insufficient Reward-Risk Rejection (< 1.5)
# ===========================================================================
@pytest.mark.asyncio
async def test_scenario_n_insufficient_reward_risk_rejection():
    """Verify Target 1 R:R < 1.5 is rejected at Stage 10."""
    tfs = make_bullish_timeframes(24500.0)
    ltp = float(tfs["1m"]["close"].iloc[-1])
    quote = {"currentPrice": ltp, "dayHigh": ltp + 10.0, "dayLow": 24300.0, "openPrice": 24400.0, "previousClose": 24350.0, "change": ltp - 24350.0, "provider": "angelone", "timestamp": datetime.now(timezone.utc).isoformat()}
    chain = build_mock_option_chain("NIFTY", ltp, strikes=[24500, 24550, 24600, 24650, 24700])

    # Force target_1 to be very small relative to stop-loss
    res = await execute_production_signal_pipeline(
        "NIFTY 50",
        custom_timeframes=tfs,
        custom_quote=quote,
        custom_option_chain=chain,
        config={"trade_setup_config": {"target_1_rr": 0.5, "min_reward_to_risk": 0.5}},
    )

    assert res["action"] == "NO_TRADE"
    assert res["is_trade_qualified"] is False
    assert any("1.5" in r or "reward" in r.lower() for r in res["rejection_reasons"])


# ===========================================================================
# O. Missing Capital Budget Behavior
# ===========================================================================
@pytest.mark.asyncio
async def test_scenario_o_insufficient_capital_budget():
    """Verify capital budget below 1 lot premium fails closed with informative status."""
    tfs = make_bullish_timeframes(24500.0)
    ltp = float(tfs["1m"]["close"].iloc[-1])
    quote = {"currentPrice": ltp, "dayHigh": ltp + 10.0, "dayLow": 24300.0, "openPrice": 24400.0, "previousClose": 24350.0, "change": ltp - 24350.0, "provider": "angelone", "timestamp": datetime.now(timezone.utc).isoformat()}
    chain = build_mock_option_chain("NIFTY", ltp, strikes=[24500, 24550, 24600, 24650, 24700])

    # Available capital of ₹100 is far below 1 lot cost
    res = await execute_production_signal_pipeline(
        "NIFTY 50",
        custom_timeframes=tfs,
        custom_quote=quote,
        custom_option_chain=chain,
        available_capital=100.0,
    )

    assert res["action"] == "NO_TRADE"
    assert res["is_trade_qualified"] is False
    assert res["stage_status"][PipelineStage.STAGE_10_OPTION_RISK_CALCULATION] == "CAPITAL_INSUFFICIENT"
    assert any("capital" in r.lower() for r in res["rejection_reasons"])


# ===========================================================================
# P. Empty Signals Database Returns Empty Result (Zero Fake Auto-Seeding)
# ===========================================================================
@pytest.mark.asyncio
async def test_scenario_p_empty_signals_database_returns_empty(async_test_session):
    """Verify /signals/today with empty DB returns 0 records and never seeds fake setups."""
    from app.api.routes.signals import get_today_signals

    response = await get_today_signals(session=async_test_session)
    assert response.success is True
    assert response.data["totalTrackedToday"] == 0
    assert response.data["trackedOptionSetups"] == []

    # Verify database genuinely has 0 records
    res = await async_test_session.execute(select(SignalRecord))
    signals = res.scalars().all()
    assert len(signals) == 0


# ===========================================================================
# Q. Repeated API Request Does Not Create Duplicate Signals (Idempotency)
# ===========================================================================
@pytest.mark.asyncio
async def test_scenario_q_idempotent_signal_persistence(async_test_session):
    """Verify repeated execution of the pipeline registers signal idempotently without duplicates."""
    tfs = make_bullish_timeframes(24500.0)
    ltp = float(tfs["1m"]["close"].iloc[-1])
    quote = {"currentPrice": ltp, "dayHigh": ltp + 10.0, "dayLow": 24300.0, "openPrice": 24400.0, "previousClose": 24350.0, "change": ltp - 24350.0, "provider": "angelone", "timestamp": datetime.now(timezone.utc).isoformat()}
    chain = build_mock_option_chain("NIFTY", ltp, strikes=[24500, 24550, 24600, 24650, 24700])

    # Run 1
    res1 = await execute_production_signal_pipeline(
        "NIFTY 50",
        session=async_test_session,
        custom_timeframes=tfs,
        custom_quote=quote,
        custom_option_chain=chain,
        available_capital=100000.0,
    )
    assert res1["persisted_signal_id"] is not None

    # Run 2
    res2 = await execute_production_signal_pipeline(
        "NIFTY 50",
        session=async_test_session,
        custom_timeframes=tfs,
        custom_quote=quote,
        custom_option_chain=chain,
        available_capital=100000.0,
    )
    assert res2["persisted_signal_id"] == res1["persisted_signal_id"]

    # Verify DB still has exactly 1 record
    res = await async_test_session.execute(select(SignalRecord))
    signals = res.scalars().all()
    assert len(signals) == 1


# ===========================================================================
# R. Paper Account Balance Remains Unchanged for Analysis-Only Requests
# ===========================================================================
@pytest.mark.asyncio
async def test_scenario_r_paper_balance_unmutated_by_analysis():
    """Verify analytical queries never execute orders or mutate paper trading account balance."""
    engine = PaperTradingEngine()
    initial_balance = engine.state["balance"]

    tfs = make_bullish_timeframes(24500.0)
    ltp = float(tfs["1m"]["close"].iloc[-1])
    quote = {"currentPrice": ltp, "dayHigh": ltp + 10.0, "dayLow": 24300.0, "openPrice": 24400.0, "previousClose": 24350.0, "change": ltp - 24350.0, "provider": "angelone", "timestamp": datetime.now(timezone.utc).isoformat()}
    chain = build_mock_option_chain("NIFTY", ltp, strikes=[24500, 24550, 24600, 24650, 24700])

    # Run full pipeline
    await execute_production_signal_pipeline(
        "NIFTY 50",
        custom_timeframes=tfs,
        custom_quote=quote,
        custom_option_chain=chain,
    )

    final_balance = engine.state["balance"]
    assert initial_balance == final_balance


# ===========================================================================
# S. Existing Frontend Response Compatibility
# ===========================================================================
def test_scenario_s_frontend_response_compatibility():
    """Verify format_to_frontend_options_setups perfectly satisfies OptionTradeSetup and TodayOptionsSetupsResult."""
    dummy_pipeline_result = {
        "symbol": "NIFTY 50",
        "action": "BUY_CE",
        "is_trade_qualified": True,
        "market_state": {"market_regime": "BULLISH_TREND"},
        "mtf_confluence": {"confluence_score": 85.0, "directional_bias": "BULLISH", "itf_structure": {}},
        "trade_setup": {"invalidation_condition": "5M candle close below ₹24480"},
        "selected_contract": {
            "contract_symbol": "NIFTY26NOV24550CE",
            "strike": 24550.0,
            "expiry": "26-NOV-2026",
            "delta": 0.52,
            "gamma": 0.0012,
            "theta": -2.1,
            "vega": 12.5,
            "implied_volatility": 14.8,
            "lot_size": 65,
            "oi": 180000,
            "volume": 95000,
            "spread_pct": 0.25,
            "derived_strike_spacing": 50.0,
            "moneyness": "ATM",
            "liquidity_policy_status": "APPROVED",
        },
        "risk_plan": {
            "entry_premium": 125.40,
            "stop_loss_premium": 95.00,
            "target_1_premium": 172.50,
            "target_2_premium": 205.00,
            "target_3_premium": 245.00,
            "reward_risk_target_1": 1.55,
            "reward_risk_target_2": 2.61,
            "reward_risk_target_3": 3.92,
            "max_risk_per_lot": 1976.0,
            "potential_gain_per_lot_t1": 3061.5,
            "capital_allocation_status": "QUALIFIED_SINGLE_LOT",
        },
    }

    fe = format_to_frontend_options_setups(dummy_pipeline_result)

    assert "symbol" in fe
    assert "hasQualifiedSetups" in fe
    assert "statusMessage" in fe
    assert "disqualificationReasons" in fe
    assert "timestamp" in fe
    assert "setups" in fe
    assert "pipelineMetadata" in fe

    setup = fe["setups"][0]
    required_keys = [
        "index", "bias", "biasLabel", "moneyness", "contractSymbol", "strike", "expiry",
        "currentPremium", "entryRange", "stopLoss", "target1", "target2", "target3",
        "riskRewardRatio", "maxRiskPerLot", "potentialGainPerLot", "greeks", "iv",
        "liquidity", "openInterest", "changeInOi", "underlyingTrigger", "invalidationCondition",
        "supportingReasons", "disclaimer"
    ]
    for k in required_keys:
        assert k in setup, f"Missing required frontend OptionTradeSetup field: {k}"


# ===========================================================================
# T. SENSEX Remains Locked When Governance Policy is Unconfigured
# ===========================================================================
@pytest.mark.asyncio
async def test_scenario_t_sensex_locked_when_unconfigured():
    """Verify SENSEX contract selection is rejected when institutional policy is UNCONFIGURED."""
    df_1h = generate_candle_series(20, start_price=79300, trend="bullish", step_pts=30.0)
    df_15m = generate_candle_series(25, start_price=79400, trend="bullish", step_pts=16.0)
    df_5m = generate_candle_series(20, start_price=79600, trend="bullish", step_pts=10.0)
    df_1m = generate_candle_series(15, start_price=79760, trend="bullish", step_pts=4.0)
    tfs = {"1h": df_1h, "15m": df_15m, "5m": df_5m, "1m": df_1m}

    ltp = float(df_1m["close"].iloc[-1])
    quote = {
        "currentPrice": ltp,
        "dayHigh": ltp + 20.0,
        "dayLow": 79300.0,
        "openPrice": 79400.0,
        "previousClose": 79350.0,
        "change": ltp - 79350.0,
        "provider": "angelone",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    chain = build_mock_option_chain("SENSEX", ltp, strikes=[79600, 79700, 79800, 79900, 80000])

    res = await execute_production_signal_pipeline(
        "SENSEX",
        custom_timeframes=tfs,
        custom_quote=quote,
        custom_option_chain=chain,
    )

    assert res["action"] == "NO_TRADE"
    assert res["is_trade_qualified"] is False
    assert any("UNCONFIGURED" in r or "SENSEX" in r for r in res["rejection_reasons"])


# ===========================================================================
# U. VERIFIED_EOD Data Gating (Regression: EOD Must Never Qualify Live Setups)
# ===========================================================================
@pytest.mark.asyncio
async def test_scenario_u_verified_eod_data_never_qualifies_live_setup():
    """Verify that EOD settlement data is strictly analysis-only and cannot qualify live trade setups."""
    tfs = make_bullish_timeframes(24500.0)
    ltp = float(tfs["1m"]["close"].iloc[-1])
    quote = {
        "currentPrice": ltp,
        "dayHigh": ltp + 10.0,
        "dayLow": 24300.0,
        "openPrice": 24400.0,
        "previousClose": 24350.0,
        "change": ltp - 24350.0,
        "provider": "angelone",
        "dataStatus": "VERIFIED_EOD",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    chain = build_mock_option_chain("NIFTY", ltp, strikes=[24500, 24550, 24600, 24650, 24700])

    res = await execute_production_signal_pipeline(
        "NIFTY 50",
        custom_timeframes=tfs,
        custom_quote=quote,
        custom_option_chain=chain,
        available_capital=100000.0,
    )

    # Must be analysis-only, never a live directional setup
    assert res["action"] == "NO_TRADE"
    assert res["is_trade_qualified"] is False
    assert any("VERIFIED_EOD" in r or "Non-live" in r for r in res["rejection_reasons"])
    # But market analysis stages must complete successfully
    assert res["mtf_confluence"] is not None
    assert res["market_state"] is not None

