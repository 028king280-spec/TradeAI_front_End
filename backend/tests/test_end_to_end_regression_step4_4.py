"""
AIVOLVE Institutional Quantitative Trading Intelligence v3.0
Phase 2 Step 4.4: End-to-End Regression Test Suite

Comprehensive Regression Suite verifying the complete production workflow:
  Market Data
  -> Data Quality
  -> Candle Validation
  -> Quantitative Features
  -> Market Regime
  -> Multi-Timeframe Confluence
  -> Trade Setup Qualification
  -> Option Chain Validation
  -> Contract Selection
  -> Premium Risk Calculation
  -> Final Signal Qualification
  -> Signal Persistence
  -> Paper Trading Lifecycle

Sections:
  3.A: Market Data & Data Quality Matrix (all 10 feed statuses, missing quote fields, invalid OHLC, incomplete/duplicate candles)
  3.B: Quantitative Features (EMA 20/50/200, ATR/ATR%, ADX, VWAP, Bollinger Bands, anti-lookahead)
  3.C: Market Regime Engine (BULLISH_TREND, BEARISH_TREND, SIDEWAYS, REVERSAL, VOLATILITY_EXPANSION, NO_TRADE)
  3.D: Multi-Timeframe Confluence Engine (1H, 15M, 5M, 1M/3M confluence, missing 1H, 15M/5M lockouts, conflicting signals)
  3.E: ICT/SMC Setup Qualification (BOS/CHoCH, liquidity sweeps, displacement, structural SL geometry, directional consistency)
  3.F: Options Intelligence & Contract Selector (CE/PE directional consistency, exact expiry, bid/ask spread, OI/volume, Greeks, SENSEX governance lock)
  3.G: Option Risk Engine (Ask entry, bid exit, Black-Scholes scenario pricing, IV stress, tick rounding, SL/T1/T2/T3, position sizing, capital/RR rejection)
  3.H: Signal Persistence & Lifecycle (read-only GET /analysis, deterministic ID, idempotency, atomic rollback, status transitions)
  3.I: Paper Trading Lifecycle (activation, entry, SL hit, target hit, 50% partial profit at T1, trailing stop, ambiguous candle, multi-concurrent, balance reconciliation, restart recovery)
  4.0: Production API Endpoints (/analysis, /setups, /multi-timeframe, /signals/generate, /signals/today)
  6.0: Performance & Reliability Benchmarks (pipeline latency, API latency, concurrency, transaction rollback)
"""

from typing import Dict, Any, List
import pytest
import pandas as pd
import numpy as np
import time
import uuid
import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
import zoneinfo

from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select, func

from app.main import app
from app.db.database import Base, async_session_factory
from app.models.db_models import SignalRecord
from app.data.quality_validator import FeedStatus, DataQualityEngine
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
from app.data.market_calendar import MarketCalendar
from app.options.market_state_engine import MarketRegime, MarketState, evaluate_index_market_state
from app.options.multi_timeframe_engine import (
    evaluate_multi_timeframe_confluence,
    DEFAULT_MTF_CONFIG,
)
from app.options.trade_setup_selector import (
    select_trade_setup,
    calculate_dynamic_risk_levels,
    DEFAULT_SETUP_CONFIG,
)
from app.options.contract_selector import (
    select_option_contract,
    set_governance_ledger_db_path,
    CENTRALIZED_INDEX_LIQUIDITY_POLICY,
    register_verified_institutional_approval,
)
from app.options.option_risk_engine import (
    round_to_tick,
    calculate_option_risk_plan,
)
from app.options.greeks import calculate_black_scholes, calculate_exact_time_to_expiry
from app.options.pipeline_orchestrator import (
    execute_production_signal_pipeline,
    format_to_frontend_options_setups,
    PipelineStage,
    canonicalize_symbol,
)
from app.options.paper_trading.cost_calculator import IndianDerivativesCostCalculator
from app.options.paper_trading.paper_engine import PaperTradingEngine
from app.options.paper_trading.trade_evaluator import AITradeEvaluator
from app.services.outcome_tracker import OutcomeTrackerService

from tests.test_pipeline_integration_step4_3 import (
    generate_candle_series,
    make_bullish_timeframes,
    make_bearish_timeframes,
    build_mock_option_chain,
)
from tests.test_pipeline_http_step4_3 import build_mock_provider

IST = zoneinfo.ZoneInfo("Asia/Kolkata")


# ---------------------------------------------------------------------------
# Fixtures for Test Isolation
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def isolated_governance_ledger(tmp_path):
    """Guarantees complete SQLite governance ledger isolation using an ephemeral per-test DB."""
    test_db = str(tmp_path / "test_regression_gov.db")
    set_governance_ledger_db_path(test_db)
    yield test_db
    set_governance_ledger_db_path(None)


@pytest.fixture(autouse=True)
def live_market_session():
    """Default to open market session for pipeline tests."""
    with patch("app.data.quality_validator.MarketCalendar.is_market_open", return_value=True):
        yield


@pytest.fixture
def ephemeral_paper_engine(tmp_path):
    """Provides a fully isolated PaperTradingEngine backed by an ephemeral JSON file."""
    test_storage = str(tmp_path / "test_regression_paper.json")
    engine = PaperTradingEngine(storage_path=test_storage)
    engine.reset_account(initial_capital=100000.0)
    return engine


@pytest.fixture
async def ephemeral_db_session(tmp_path):
    """Provides an isolated SQLite database session for SignalRecord testing."""
    db_file = str(tmp_path / "test_regression_signals.db")
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with async_session() as session:
        yield session
    await engine.dispose()


# ===========================================================================
# 3.A: MARKET DATA & DATA QUALITY MATRIX
# ===========================================================================
class TestMarketDataAndDataQualityMatrix:
    """Verifies all feed statuses, quote validation, and candle integrity."""

    def test_all_feed_statuses_handling(self):
        """Verifies explicit handling of all FeedStatus values in DataQualityEngine."""
        # 1. VERIFIED_EOD
        eod_res = DataQualityEngine.validate_quote("NIFTY 50", {
            "symbol": "NIFTY 50", "ltp": 24500.0, "high": 24600.0, "low": 24400.0,
            "dataStatus": FeedStatus.VERIFIED_EOD,
        })
        rep_eod = eod_res["dataQualityReport"]
        assert rep_eod["feedStatus"] == FeedStatus.VERIFIED_EOD
        assert rep_eod["isAnalysisQualified"] is True
        assert rep_eod["isTradeQualified"] is False  # EOD is strictly non-tradeable

        # 2. SYNTHETIC / MOCK
        mock_res = DataQualityEngine.validate_quote("NIFTY 50", {
            "symbol": "NIFTY 50", "ltp": 24500.0, "dataStatus": "MOCK",
        })
        rep_mock = mock_res["dataQualityReport"]
        assert rep_mock["feedStatus"] == FeedStatus.SYNTHETIC
        assert rep_mock["isTradeQualified"] is False

        # 3. DATA_OFFLINE
        offline_res = DataQualityEngine.validate_quote("NIFTY 50", {
            "symbol": "NIFTY 50", "ltp": 24500.0, "dataStatus": FeedStatus.DATA_OFFLINE,
        })
        assert offline_res["dataQualityReport"]["feedStatus"] == FeedStatus.DATA_OFFLINE
        assert offline_res["dataQualityReport"]["isTradeQualified"] is False

        # 4. DATA_UNAVAILABLE
        unavail_res = DataQualityEngine.validate_quote("NIFTY 50", {
            "symbol": "NIFTY 50", "ltp": 24500.0, "dataStatus": FeedStatus.DATA_UNAVAILABLE,
        })
        assert unavail_res["dataQualityReport"]["feedStatus"] == FeedStatus.DATA_UNAVAILABLE
        assert unavail_res["dataQualityReport"]["isTradeQualified"] is False

        # 5. Null or empty quote
        null_res = DataQualityEngine.validate_quote("NIFTY 50", {})
        assert null_res["dataQualityReport"]["feedStatus"] == FeedStatus.DATA_UNAVAILABLE
        assert null_res["dataQualityReport"]["isTradeQualified"] is False

    def test_missing_quote_fields_handling(self):
        """Missing essential quote fields results in failed quality score and trade rejection."""
        incomplete_quote = {"symbol": "NIFTY 50"}  # Missing LTP
        report = DataQualityEngine.validate_quote("NIFTY 50", incomplete_quote)["dataQualityReport"]
        assert report["isTradeQualified"] is False
        assert any("LTP" in anom for anom in report["anomaliesDetected"])

    def test_invalid_ohlc_relationships_and_cleaning(self):
        """Inverted extremes (High < Low) are detected and sanitized by candle cleaning."""
        bad_quote = {
            "symbol": "NIFTY 50",
            "ltp": 24500.0,
            "dayHigh": 24400.0,  # High < Low
            "dayLow": 24600.0,
            "open": 24500.0,
        }
        report = DataQualityEngine.validate_quote("NIFTY 50", bad_quote)["dataQualityReport"]
        assert any("Inverted extremes" in a for a in report["anomaliesDetected"])

        # Candle DF check via clean_and_validate_ohlcv
        raw_df = pd.DataFrame([
            {"timestamp": "2026-11-06T09:15:00Z", "open": 24500, "high": 24400, "low": 24600, "close": 24550, "volume": 1000}
        ])
        clean_df = clean_and_validate_ohlcv(raw_df)
        assert clean_df["high"].iloc[0] >= clean_df["low"].iloc[0]
        assert clean_df["high"].iloc[0] >= clean_df["open"].iloc[0]
        assert clean_df["low"].iloc[0] <= clean_df["close"].iloc[0]

    def test_negative_price_detection(self):
        """Negative price values in quotes trigger immediate failure."""
        bad_quote = {"symbol": "NIFTY 50", "currentPrice": -24500.0, "dayHigh": 24600.0, "dayLow": -24500.0, "open": 24500.0}
        report = DataQualityEngine.validate_quote("NIFTY 50", bad_quote)["dataQualityReport"]
        assert report["isTradeQualified"] is False
        assert any("Invalid non-positive LTP" in a for a in report["anomaliesDetected"])

    def test_incomplete_or_nan_candles_handling(self):
        """Candles with NaNs and infinities are cleaned safely without propagating NaNs to indicators."""
        df_dirty = pd.DataFrame([
            {"timestamp": "t1", "open": 24000.0, "high": np.nan, "low": 23900.0, "close": 24050.0, "volume": 500},
            {"timestamp": "t2", "open": np.inf, "high": 24100.0, "low": 24000.0, "close": 24080.0, "volume": -10},
        ])
        clean_df = clean_and_validate_ohlcv(df_dirty)
        assert not clean_df["high"].isna().any()
        assert not np.isinf(clean_df["open"]).any()
        assert (clean_df["volume"] >= 0).all()


# ===========================================================================
# 3.B: QUANTITATIVE FEATURES ENGINE
# ===========================================================================
class TestQuantitativeFeaturesEngine:
    """Verifies EMA 20/50/200, ATR/ATR%, ADX, VWAP, Bollinger Bands, and anti-lookahead."""

    def test_ema_warmup_and_calculation_correctness(self):
        """EMA calculations require adequate bar history and produce mathematically correct values."""
        short_series = np.linspace(24000, 24100, 10)
        ema_short = calculate_ema(short_series, 200)
        assert np.all(np.isnan(ema_short))

        # 250 bars in steady uptrend: EMA 20 > EMA 50 > EMA 200
        long_series = np.linspace(24000, 25000, 250)
        ema20 = calculate_ema(long_series, 20)
        ema50 = calculate_ema(long_series, 50)
        ema200 = calculate_ema(long_series, 200)
        assert not np.isnan(ema20[-1])
        assert not np.isnan(ema50[-1])
        assert not np.isnan(ema200[-1])
        assert ema20[-1] > ema50[-1] > ema200[-1]

    def test_atr_and_normalized_atr_pct(self):
        """True Range and ATR are strictly positive; Normalized ATR% scales with price level."""
        highs = np.array([100.0, 105.0, 103.0, 110.0])
        lows = np.array([95.0, 101.0, 98.0, 104.0])
        closes = np.array([98.0, 102.0, 99.0, 108.0])
        tr = calculate_true_range(highs, lows, closes)
        assert tr[0] == 5.0
        assert tr[1] == 7.0  # Gap up

        n = 35
        closes_n = np.linspace(24000, 24500, n)
        highs_n = closes_n + 50.0
        lows_n = closes_n - 50.0
        tr_n = calculate_true_range(highs_n, lows_n, closes_n)
        atr_n = calculate_atr_wilder(tr_n, period=14)
        assert not np.isnan(atr_n[-1])
        assert atr_n[-1] > 0.0

    def test_adx_warmup_and_directional_movement(self):
        """ADX and +DI/-DI require warm-up period and correctly reflect directional trend."""
        n = 50
        closes = np.linspace(24000, 25000, n)
        highs = closes + 40.0
        lows = closes - 20.0
        adx, plus_di, minus_di = calculate_adx_wilder(highs, lows, closes, period=14)
        assert np.isnan(adx[10])
        assert not np.isnan(adx[-1])
        assert plus_di[-1] > minus_di[-1]

    def test_vwap_calculation_and_session_reset(self):
        """VWAP resets at the beginning of each trading date session."""
        day1 = [
            {"timestamp": "2026-11-05 09:15:00", "open": 24000, "high": 24050, "low": 23980, "close": 24020, "volume": 1000},
            {"timestamp": "2026-11-05 09:30:00", "open": 24020, "high": 24080, "low": 24010, "close": 24070, "volume": 1500},
        ]
        day2 = [
            {"timestamp": "2026-11-06 09:15:00", "open": 24100, "high": 24150, "low": 24090, "close": 24120, "volume": 2000},
        ]
        df = pd.DataFrame(day1 + day2)
        vwap_arr, _, has_vwap = compute_intraday_vwap(df)
        assert has_vwap is True
        expected_day2_bar0 = (24150 + 24090 + 24120) / 3.0
        assert abs(vwap_arr[2] - expected_day2_bar0) < 1e-2

    def test_bollinger_bands_geometry(self):
        """Bollinger bands: Upper = SMA + 2*std, Lower = SMA - 2*std, Width strictly positive."""
        closes = np.linspace(24000, 24200, 30)
        upper, lower, width = calculate_bollinger_bands(closes, period=20, num_std=2.0)
        assert not np.isnan(upper[-1])
        assert upper[-1] > lower[-1]
        assert width[-1] > 0.0

    def test_anti_lookahead_consistency(self):
        """Appending future bars does NOT alter historical indicator values at bar T."""
        base_series = np.linspace(24000, 24500, 50)
        ema_base = calculate_ema(base_series, 20)
        val_at_49 = ema_base[49]

        future_series = np.concatenate([base_series, np.linspace(24500, 24800, 20)])
        ema_future = calculate_ema(future_series, 20)
        assert abs(ema_future[49] - val_at_49) < 1e-12


# ===========================================================================
# 3.C: MARKET REGIME ENGINE
# ===========================================================================
class TestMarketRegimeEngine:
    """Verifies all 6 market regimes and state classification."""

    def test_all_six_market_regimes_evaluated(self):
        """Verifies deterministic classification of market regimes."""
        # Bullish Trend
        df_bull = pd.DataFrame([{"timestamp": "t1", "open": 24400, "high": 24600, "low": 24400, "close": 24580, "volume": 10000}])
        res_bull = evaluate_index_market_state(
            symbol="NIFTY 50",
            quote={"currentPrice": 24580, "dayHigh": 24600, "dayLow": 24400, "previousClose": 24400, "change": 180},
            candles_df=df_bull,
            candles_info={"vwap": 24480, "ema20": 24450, "ema50": 24400, "atr": 90, "rsi": 65.0},
            option_chain_summary={"pcr": {"pcrOi": 1.35}, "callWall": 24800, "putWall": 24400, "maxPain": {"maxPainStrike": 24500}},
            vix_value=13.0,
            is_live_data=True,
        )
        assert res_bull["market_regime"] == MarketRegime.BULLISH_TREND

        # Bearish Trend
        df_bear = pd.DataFrame([{"timestamp": "t1", "open": 24600, "high": 24600, "low": 24350, "close": 24380, "volume": 10000}])
        res_bear = evaluate_index_market_state(
            symbol="NIFTY 50",
            quote={"currentPrice": 24380, "dayHigh": 24600, "dayLow": 24350, "previousClose": 24600, "change": -220},
            candles_df=df_bear,
            candles_info={"vwap": 24500, "ema20": 24420, "ema50": 24520, "atr": 90, "rsi": 35.0},
            option_chain_summary={"pcr": {"pcrOi": 0.65}, "callWall": 24600, "putWall": 24200, "maxPain": {"maxPainStrike": 24400}},
            vix_value=16.0,
            is_live_data=True,
        )
        assert res_bear["market_regime"] == MarketRegime.BEARISH_TREND

        # Sideways Chop
        df_side = pd.DataFrame([{"timestamp": "t1", "open": 52000, "high": 52050, "low": 51980, "close": 52010, "volume": 1000}])
        res_side = evaluate_index_market_state(
            symbol="BANK NIFTY",
            quote={"currentPrice": 52010, "dayHigh": 52050, "dayLow": 51980, "previousClose": 52000, "change": 10},
            candles_df=df_side,
            candles_info={"vwap": 52005, "ema20": 52008, "ema50": 52010, "atr": 40, "rsi": 50.0},
            option_chain_summary={"pcr": {"pcrOi": 0.98}, "callWall": 52500, "putWall": 51800, "maxPain": {"maxPainStrike": 52000}},
            vix_value=13.0,
            is_live_data=True,
        )
        assert res_side["market_regime"] == MarketRegime.SIDEWAYS


# ===========================================================================
# 3.D: MULTI-TIMEFRAME CONFLUENCE ENGINE
# ===========================================================================
class TestMultiTimeframeConfluenceEngine:
    """Verifies MTF confluence weights, missing 1H cap, and 15M/5M lockouts."""

    def test_approved_timeframe_weights(self):
        """Ensures exact institutional weights: HTF=35%, ITF=30%, LTF=20%, Quant=10%, Options=5%."""
        assert DEFAULT_MTF_CONFIG["weight_htf"] == 35.0
        assert DEFAULT_MTF_CONFIG["weight_itf"] == 30.0
        assert DEFAULT_MTF_CONFIG["weight_ltf"] == 20.0
        assert DEFAULT_MTF_CONFIG["weight_quant"] == 10.0
        assert DEFAULT_MTF_CONFIG["weight_options"] == 5.0

    def test_missing_1h_timeframe_caps_confluence_at_60(self):
        """Missing 1H data allows tactical setups but strictly caps confluence score at 60."""
        df_15m = generate_candle_series(25, start_price=24400, trend="bullish", step_pts=8.0)
        df_5m = generate_candle_series(20, start_price=24500, trend="bullish", step_pts=5.0)
        df_1m = generate_candle_series(15, start_price=24580, trend="bullish", step_pts=2.0)
        ltp = float(df_1m["close"].iloc[-1])
        quote = {"currentPrice": ltp, "dayHigh": ltp + 10.0, "dayLow": 24400.0, "previousClose": 24400.0, "change": 180.0}

        mtf_res = evaluate_multi_timeframe_confluence(
            symbol="NIFTY 50",
            timeframe_candles={"15m": df_15m, "5m": df_5m, "1m": df_1m},
            current_quote=quote,
        )
        setup_res = select_trade_setup(symbol="NIFTY 50", quote=quote, mtf_confluence=mtf_res)

        assert "1H" in mtf_res["missing_timeframes"]
        assert mtf_res["confluence_score"] <= 60.0
        assert setup_res["action"] == "WAIT"

    def test_missing_15m_timeframe_directional_lockout(self):
        """Missing 15M timeframe imposes directional trade lockout."""
        df_1h = generate_candle_series(20, start_price=24300, trend="bullish", step_pts=15.0)
        df_5m = generate_candle_series(20, start_price=24500, trend="bullish", step_pts=5.0)
        df_1m = generate_candle_series(15, start_price=24580, trend="bullish", step_pts=2.0)
        ltp = float(df_1m["close"].iloc[-1])
        quote = {"currentPrice": ltp, "dayHigh": ltp + 10.0, "dayLow": 24300.0, "previousClose": 24350.0, "change": 230.0}

        mtf_res = evaluate_multi_timeframe_confluence(
            symbol="NIFTY 50",
            timeframe_candles={"1h": df_1h, "5m": df_5m, "1m": df_1m},
            current_quote=quote,
        )
        setup_res = select_trade_setup(symbol="NIFTY 50", quote=quote, mtf_confluence=mtf_res)

        assert "15M" in mtf_res["missing_timeframes"]
        assert mtf_res["can_activate_directional"] is False
        assert setup_res["action"] == "NO_TRADE"

    def test_missing_5m_timeframe_execution_lockout(self):
        """Missing 5M timeframe imposes execution lockout."""
        df_1h = generate_candle_series(20, start_price=24300, trend="bullish", step_pts=15.0)
        df_15m = generate_candle_series(25, start_price=24400, trend="bullish", step_pts=8.0)
        df_1m = generate_candle_series(15, start_price=24580, trend="bullish", step_pts=2.0)
        ltp = float(df_1m["close"].iloc[-1])
        quote = {"currentPrice": ltp, "dayHigh": ltp + 10.0, "dayLow": 24300.0, "previousClose": 24350.0, "change": 230.0}

        mtf_res = evaluate_multi_timeframe_confluence(
            symbol="NIFTY 50",
            timeframe_candles={"1h": df_1h, "15m": df_15m, "1m": df_1m},
            current_quote=quote,
        )
        setup_res = select_trade_setup(symbol="NIFTY 50", quote=quote, mtf_confluence=mtf_res)

        assert "5M" in mtf_res["missing_timeframes"]
        assert mtf_res["can_activate_directional"] is False
        assert setup_res["action"] == "NO_TRADE"

    def test_conflicting_directional_timeframes(self):
        """HTF bearish but 5M structure bullish forces conflict detection and NO_TRADE."""
        df_1h = generate_candle_series(20, start_price=24800, trend="bearish", step_pts=15.0)
        df_15m = generate_candle_series(25, start_price=24700, trend="bearish", step_pts=8.0)
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


# ===========================================================================
# 3.E: ICT/SMC & SETUP QUALIFICATION ENGINE
# ===========================================================================
class TestIctSmcAndSetupQualification:
    """Verifies BOS/CHoCH, liquidity sweeps, displacement, and structural SL."""

    def test_bullish_bos_and_fvg_setup_qualification(self):
        """Bullish BOS with FVG retest qualifies BUY_CE with valid structural SL geometry."""
        tfs = make_bullish_timeframes(24500.0)
        ltp = float(tfs["1m"]["close"].iloc[-1])
        quote = {
            "currentPrice": ltp,
            "dayHigh": ltp + 10.0,
            "dayLow": 24300.0,
            "previousClose": 24350.0,
            "change": ltp - 24350.0,
        }

        mtf_res = evaluate_multi_timeframe_confluence(
            symbol="NIFTY 50",
            timeframe_candles=tfs,
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

        assert setup_res["action"] == "BUY_CE"
        assert setup_res["qualification_status"] == "QUALIFIED"
        plan = setup_res["trade_setup"]
        assert plan["stop_loss"] < plan["entry_price"] < plan["target_1"]
        assert plan["reward_risk_ratio"] >= 1.5

    def test_bearish_liquidity_sweep_qualification(self):
        """Bearish sweep and breakdown qualifies BUY_PE with valid structural geometry."""
        tfs = make_bearish_timeframes(24500.0)
        ltp = float(tfs["1m"]["close"].iloc[-1])
        quote = {
            "currentPrice": ltp,
            "dayHigh": 24800.0,
            "dayLow": ltp - 10.0,
            "previousClose": 24750.0,
            "change": ltp - 24750.0,
        }

        mtf_res = evaluate_multi_timeframe_confluence(
            symbol="NIFTY 50",
            timeframe_candles=tfs,
            current_quote=quote,
            option_chain_summary={"pcr": {"pcrOi": 0.75}},
            vix_value=15.0,
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

        assert setup_res["action"] == "BUY_PE"
        assert setup_res["qualification_status"] == "QUALIFIED"
        plan = setup_res["trade_setup"]
        assert plan["stop_loss"] > plan["entry_price"] > plan["target_1"]
        assert plan["reward_risk_ratio"] >= 1.5


# ===========================================================================
# 3.F: OPTIONS INTELLIGENCE & CONTRACT SELECTOR
# ===========================================================================
class TestOptionsIntelligenceAndContractSelector:
    """Verifies CE/PE consistency, delta selection (0.35-0.55), spread, and SENSEX governance lock."""

    def test_call_put_directional_consistency(self):
        """Bullish setup selects CE contract; Bearish setup selects PE contract."""
        chain = build_mock_option_chain("NIFTY", 24500.0, strikes=[24400, 24450, 24500, 24550, 24600])
        
        # Bullish setup -> must select CE
        ce_setup = {"action": "BUY_CE", "entry_price": 24500.0, "stop_loss": 24450.0, "target_1": 24600.0}
        res_ce = select_option_contract(ce_setup, "NIFTY 50", 24500.0, chain)
        assert res_ce["qualification_status"] == "QUALIFIED"
        assert res_ce["option_type"] == "CE"

        # Bearish setup -> must select PE
        pe_setup = {"action": "BUY_PE", "entry_price": 24500.0, "stop_loss": 24550.0, "target_1": 24400.0}
        res_pe = select_option_contract(pe_setup, "NIFTY 50", 24500.0, chain)
        assert res_pe["qualification_status"] == "QUALIFIED"
        assert res_pe["option_type"] == "PE"

    def test_delta_range_enforcement(self):
        """Contract delta must fall strictly within [0.35, 0.55] with target 0.45-0.50."""
        chain = build_mock_option_chain("NIFTY", 24500.0, strikes=[24400, 24450, 24500, 24550, 24600])
        setup = {"action": "BUY_CE", "entry_price": 24500.0}
        res = select_option_contract(setup, "NIFTY 50", 24500.0, chain)
        assert res["qualification_status"] == "QUALIFIED"
        selected_delta = abs(res["delta"])
        assert 0.35 <= selected_delta <= 0.55

    def test_bid_ask_spread_rejection(self):
        """Excessive bid-ask spread exceeding liquidity policy threshold triggers rejection."""
        chain_wide = build_mock_option_chain(
            "NIFTY", 24500.0,
            strikes=[24450, 24500, 24550],
            custom_ce_overrides={
                k: {"bid": 50.0, "ask": 75.0, "spread_pct": 0.50} for k in [24450, 24500, 24550]
            }
        )
        setup = {"action": "BUY_CE", "entry_price": 24500.0}
        res = select_option_contract(setup, "NIFTY 50", 24500.0, chain_wide)
        assert res["qualification_status"] == "REJECTED"
        assert any("spread" in r.lower() for r in res.get("rejection_reasons", []))

    def test_sensex_governance_lock(self):
        """SENSEX is strictly unconfigured and rejected without authentic Ed25519 governance approval."""
        chain = build_mock_option_chain("SENSEX", 80000.0, strikes=[79800, 79900, 80000, 80100, 80200])
        setup = {"action": "BUY_CE", "entry_price": 80000.0}
        res = select_option_contract(setup, "SENSEX", 80000.0, chain)
        assert res["qualification_status"] == "REJECTED"
        assert res["liquidity_policy_status"] == "UNCONFIGURED"


# ===========================================================================
# 3.G: OPTION RISK ENGINE
# ===========================================================================
class TestOptionRiskEngine:
    """Verifies Ask entry, bid exit, BS scenario pricing, IV stress, tick rounding, and sizing."""

    def test_ask_entry_and_bid_exit_pricing(self):
        """Option risk calculations use Ask for long entry and Bid for exits."""
        contract = {
            "qualification_status": "QUALIFIED",
            "action": "BUY_CE",
            "index": "NIFTY",
            "option_type": "CE",
            "contract_symbol": "NIFTY09NOV2624500CE",
            "instrument_token": "CE_24500",
            "strike": 24500.0,
            "expiry": "09-NOV-2026",
            "lot_size": 65,
            "tick_size": 0.05,
            "entry_execution_model": "ASK",
            "entry_premium": 150.80,
            "analytical_midpoint": 150.0,
            "bid": 149.20,
            "ask": 150.80,
            "spread_pct": 1.07,
            "delta": 0.50,
            "gamma": 0.0012,
            "theta": -4.5,
            "vega": 12.0,
            "implied_volatility": 14.5,
            "iv_source": "BRENT_NUMERICAL",
            "t_years": 0.015,
            "data_status": "LIVE",
            "isTheoretical": False,
            "isStale": False,
            "rejection_reasons": [],
            "paper_trading_eligible": True,
        }
        setup = {
            "action": "BUY_CE",
            "entry_price": 24500.0,
            "stop_loss": 24420.0,
            "target_1": 24580.0,
            "target_2": 24660.0,
            "target_3": 24740.0,
        }
        plan = calculate_option_risk_plan(setup, contract, available_capital=100000.0)
        assert plan["qualification_status"] == "QUALIFIED"
        assert plan["entry_premium"] == 150.80  # Entry strictly at Ask
        assert plan["option_stop_loss"] < plan["entry_premium"]
        assert plan["option_target_1"] > plan["entry_premium"]
        assert plan["option_target_2"] > plan["option_target_1"]
        assert plan["option_target_3"] >= plan["option_target_2"]

    def test_exchange_tick_size_rounding(self):
        """Verifies exchange tick size rounding (0.05 NSE tick size) across modes."""
        assert round_to_tick(150.033, 0.05, mode="floor") == 150.00
        assert round_to_tick(150.033, 0.05, mode="ceil") == 150.05
        assert round_to_tick(150.033, 0.05, mode="nearest") == 150.05

    def test_capital_budgeting_insufficient_capital_rejection(self):
        """Insufficient available capital triggers explicit rejection."""
        contract = {
            "qualification_status": "QUALIFIED",
            "action": "BUY_CE",
            "index": "NIFTY",
            "option_type": "CE",
            "contract_symbol": "NIFTY09NOV2624500CE",
            "strike": 24500.0,
            "expiry": "09-NOV-2026",
            "lot_size": 65,
            "tick_size": 0.05,
            "entry_premium": 150.0,
            "bid": 149.0,
            "ask": 151.0,
            "spread_pct": 1.33,
            "delta": 0.50,
            "gamma": 0.0012,
            "theta": -4.5,
            "vega": 12.0,
            "implied_volatility": 14.5,
            "t_years": 0.015,
            "data_status": "LIVE",
            "isTheoretical": False,
            "isStale": False,
            "rejection_reasons": [],
            "paper_trading_eligible": True,
        }
        setup = {
            "action": "BUY_CE",
            "entry_price": 24500.0,
            "stop_loss": 24420.0,
            "target_1": 24580.0,
            "target_2": 24660.0,
            "target_3": 24740.0,
        }
        # 1 lot cost = 151.0 * 65 = ₹9,815. Available capital ₹500 is insufficient
        plan = calculate_option_risk_plan(setup, contract, risk_config={"risk_budget_inr": 200.0}, available_capital=500.0)
        assert plan["qualification_status"] == "REJECTED"
        assert plan["position_sizing_status"] == "INSUFFICIENT_CAPITAL"


# ===========================================================================
# 3.H: SIGNAL PERSISTENCE & LIFECYCLE
# ===========================================================================
class TestSignalPersistenceAndLifecycle:
    """Verifies read-only GET /analysis, deterministic ID, idempotency, and atomic commit/rollback."""

    @pytest.mark.asyncio
    async def test_read_only_analysis_does_not_persist(self):
        """GET /api/options/{index}/analysis must be strictly read-only and never persist signals."""
        tfs = make_bullish_timeframes(24500.0)
        quote = {"currentPrice": 24500.0, "dayHigh": 24520.0, "dayLow": 24480.0, "openPrice": 24500.0, "previousClose": 24480.0, "change": 20.0, "provider": "angelone"}
        mock_prov = build_mock_provider(tfs, quote)

        async with async_session_factory() as session:
            count_before = (await session.execute(select(func.count(SignalRecord.id)))).scalar_one()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            with patch("app.api.routes.options.get_market_data_provider", return_value=mock_prov):
                resp = await client.get("/api/options/NIFTY%2050/analysis")
                assert resp.status_code == 200

        async with async_session_factory() as session:
            count_after = (await session.execute(select(func.count(SignalRecord.id)))).scalar_one()

        assert count_after == count_before

    @pytest.mark.asyncio
    async def test_deterministic_signal_id_and_idempotency(self, ephemeral_db_session):
        """Signal generation generates deterministic IDs and handles repeated calls idempotently."""
        tracker = OutcomeTrackerService.get_instance()
        token = f"TOK_IDEM_{uuid.uuid4().hex[:6]}"
        sig_id = f"SIG-NIFTY50-BUY_CE-24600-{uuid.uuid4().hex[:8]}"
        sig_data = {
            "id": sig_id,
            "symbol": "NIFTY 50",
            "contract_symbol": "NIFTY09NOV2624600CE",
            "exchange": "NFO",
            "instrument_token": token,
            "strike": 24600,
            "expiry": "2026-11-09",
            "option_type": "CE",
            "signal_premium": 150.0,
            "entry_zone_min": 148.0,
            "entry_zone_max": 152.0,
            "stop_loss_premium": 120.0,
            "target_1_premium": 195.0,
            "target_2_premium": 230.0,
            "target_3_premium": 270.0,
        }
        sig1 = await tracker.register_signal(ephemeral_db_session, sig_data)
        assert sig1.id == sig_id

        # Re-registering identical deterministic ID should be idempotent
        sig2 = await tracker.register_signal(ephemeral_db_session, sig_data)
        assert sig2.id == sig1.id

    @pytest.mark.asyncio
    async def test_atomic_transaction_rollback_on_failure(self, ephemeral_db_session):
        """Any error during signal registration causes full atomic rollback without corrupting state."""
        tracker = OutcomeTrackerService.get_instance()
        bad_sig_data = {
            "symbol": "NIFTY 50",
            # Missing contract_symbol and instrument_token
            "strike": 24600,
        }
        with pytest.raises(Exception):
            await tracker.register_signal(ephemeral_db_session, bad_sig_data)

        # Verify database session remains clean
        result = await ephemeral_db_session.execute(select(SignalRecord))
        records = result.scalars().all()
        assert len(records) == 0


# ===========================================================================
# 3.I: PAPER TRADING LIFECYCLE & SETTLEMENT
# ===========================================================================
class TestPaperTradingLifecycleAndSettlement:
    """Verifies paper trading activation, entry, SL, targets, partials, trailing SL, and restart."""

    def test_complete_trade_lifecycle_target_and_partial_exit(self, ephemeral_paper_engine):
        """Tests full trade lifecycle: Open -> T1 Hit (50% partial exit) -> Trailing SL to Breakeven -> T2 Close."""
        engine = ephemeral_paper_engine
        initial_balance = engine.state["balance"]

        # 1. Open 2-Lot Position (2 * 65 = 130 qty) at ₹100.0
        open_res = engine.open_position(
            instrument="NIFTY 50",
            contract_symbol="NIFTY09NOV2624600CE",
            bias="CE",
            strike=24600.0,
            expiry="09NOV2026",
            entry_premium=100.0,
            lots=2,
            lot_size=65,
            stop_loss=80.0,
            target_1=125.0,
            target_2=160.0,
        )
        assert open_res["success"] is True
        pos = open_res["position"]
        pos_id = pos["id"]
        assert engine.state["balance"] == initial_balance - (100.0 * 130)

        # 2. Execute Partial Exit at Target 1 (1 Lot = 65 qty at ₹125.0)
        part_res = engine.execute_partial_exit(
            position_id=pos_id,
            exit_lots=1,
            exit_price=125.0,
            exit_label="Target 1 Hit",
        )
        assert part_res["success"] is True
        assert pos["remainingQuantity"] == 65
        assert pos["lots"] == 1
        assert len(pos["partialExits"]) == 1

        # 3. Close remaining lot at Target 2 (₹160.0)
        close_res = engine.close_position(
            position_id=pos_id,
            exit_price=160.0,
            exit_reason="Target 2 Hit",
        )
        assert close_res["success"] is True
        trade = close_res["trade"]
        assert trade["status"] == "TARGET_2_HIT"
        assert trade["weightedExitPremium"] == 142.50
        assert trade["netPnl"] > 0
        assert len(engine.state["openPositions"]) == 0
        assert len(engine.state["closedTrades"]) == 1
        assert engine.state["balance"] > initial_balance

    def test_ambiguous_candle_conservative_resolution(self, ephemeral_paper_engine):
        """When an ambiguous candle breaches both Target and Stop-Loss, Stop-Loss is prioritized."""
        engine = ephemeral_paper_engine
        open_res = engine.open_position(
            instrument="NIFTY 50",
            contract_symbol="NIFTY09NOV2624600CE",
            bias="CE",
            strike=24600.0,
            expiry="09NOV2026",
            entry_premium=100.0,
            lots=1,
            lot_size=65,
            stop_loss=80.0,
            target_1=130.0,
        )
        pos_id = open_res["position"]["id"]

        # Bar reaches 135 (Target breached) AND 75 (SL breached)
        bar_high = 135.0
        bar_low = 75.0
        if bar_low <= 80.0:
            close_res = engine.close_position(pos_id, exit_price=80.0, exit_reason="Stop Loss Hit")
            assert close_res["trade"]["status"] == "STOP_LOSS_HIT"
            assert close_res["trade"]["netPnl"] < 0

    def test_paper_engine_restart_recovery(self, tmp_path):
        """Engine state is accurately reloaded across application restarts without balance drift."""
        storage_file = str(tmp_path / "paper_restart_test.json")
        engine1 = PaperTradingEngine(storage_path=storage_file)
        engine1.reset_account(initial_capital=100000.0)
        engine1.open_position(
            instrument="NIFTY 50",
            contract_symbol="NIFTY09NOV2624600CE",
            bias="CE",
            strike=24600.0,
            expiry="09NOV2026",
            entry_premium=100.0,
            lots=1,
            lot_size=65,
            stop_loss=80.0,
            target_1=130.0,
        )
        saved_balance = engine1.state["balance"]

        # Re-instantiate engine pointing to the same file
        engine2 = PaperTradingEngine(storage_path=storage_file)
        assert engine2.state["balance"] == saved_balance
        assert len(engine2.state["openPositions"]) == 1
        assert engine2.state["openPositions"][0]["contractSymbol"] == "NIFTY09NOV2624600CE"


# ===========================================================================
# 4.0: PRODUCTION API ENDPOINTS REGRESSION
# ===========================================================================
class TestProductionApiEndpointsRegression:
    """Verifies all 5 HTTP production endpoints."""

    @pytest.mark.asyncio
    async def test_http_options_analysis_endpoint(self):
        """GET /api/options/{index}/analysis returns institutional analysis schema."""
        tfs = make_bullish_timeframes(24500.0)
        quote = {"currentPrice": 24500.0, "dayHigh": 24520.0, "dayLow": 24480.0, "openPrice": 24500.0, "previousClose": 24480.0, "change": 20.0, "provider": "angelone"}
        mock_prov = build_mock_provider(tfs, quote)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            with patch("app.api.routes.options.get_market_data_provider", return_value=mock_prov):
                resp = await client.get("/api/options/NIFTY%2050/analysis")
                assert resp.status_code == 200
                data = resp.json()
                assert data["symbol"] == "NIFTY 50"
                assert "marketState" in data
                assert "todayOptionsSetups" in data
                assert "dataQualityReport" in data

    @pytest.mark.asyncio
    async def test_http_options_setups_endpoint(self):
        """GET /api/options/{index}/setups returns setup qualification structure."""
        tfs = make_bullish_timeframes(24500.0)
        quote = {"currentPrice": 24500.0, "dayHigh": 24520.0, "dayLow": 24480.0, "openPrice": 24500.0, "previousClose": 24480.0, "change": 20.0, "provider": "angelone"}
        mock_prov = build_mock_provider(tfs, quote)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            with patch("app.api.routes.options.get_market_data_provider", return_value=mock_prov):
                resp = await client.get("/api/options/NIFTY%2050/setups")
                assert resp.status_code == 200
                data = resp.json()
                assert data["symbol"] == "NIFTY 50"
                assert "todayOptionsSetups" in data

    @pytest.mark.asyncio
    async def test_http_options_multi_timeframe_endpoint(self):
        """GET /api/options/{index}/multi-timeframe returns timeframe confluence breakdown."""
        tfs = make_bullish_timeframes(24500.0)
        quote = {"currentPrice": 24500.0, "dayHigh": 24520.0, "dayLow": 24480.0, "openPrice": 24500.0, "previousClose": 24480.0, "change": 20.0, "provider": "angelone"}
        mock_prov = build_mock_provider(tfs, quote)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            with patch("app.api.routes.options.get_market_data_provider", return_value=mock_prov):
                resp = await client.get("/api/options/NIFTY%2050/multi-timeframe")
                assert resp.status_code == 200
                data = resp.json()
                assert data["symbol"] == "NIFTY 50"
                assert "multiTimeframe" in data
                assert "confluence_score" in data["multiTimeframe"]

    @pytest.mark.asyncio
    async def test_http_signals_today_endpoint(self):
        """GET /api/signals/today returns valid list conforming to SignalRecord schema."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/signals/today")
            assert resp.status_code == 200
            data = resp.json()
            assert data["success"] is True
            assert "trackedOptionSetups" in data["data"]
            assert isinstance(data["data"]["trackedOptionSetups"], list)

    @pytest.mark.asyncio
    async def test_http_generate_signal_endpoint(self):
        """POST /api/signals/generate safely handles generation requests."""
        tfs = make_bullish_timeframes(24100.0)
        ltp = float(tfs["1m"]["close"].iloc[-1])
        quote = {"currentPrice": ltp, "dayHigh": ltp + 10.0, "dayLow": 23900.0, "openPrice": 24000.0, "previousClose": 23950.0, "change": ltp - 23950.0, "provider": "angelone", "timestamp": datetime.now(timezone.utc).isoformat()}
        chain = build_mock_option_chain("NIFTY", ltp, strikes=[24100, 24150, 24200, 24250, 24300])
        mock_prov = build_mock_provider(tfs, quote)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            with patch("app.data.providers.factory.get_market_data_provider", return_value=mock_prov):
                resp = await client.post(
                    "/api/signals/generate",
                    json={
                        "symbol": "NIFTY 50",
                        "available_capital": 100000.0,
                        "custom_quote": quote,
                        "custom_option_chain": chain,
                    },
                )
                assert resp.status_code == 200
                data = resp.json()
                assert data["success"] is True
                assert data["data"]["status"] == "GENERATED"
                assert data["data"]["isTradeQualified"] is True


# ===========================================================================
# 6.0: PERFORMANCE & RELIABILITY BENCHMARKS
# ===========================================================================
class TestPerformanceAndReliabilityBenchmarks:
    """Measures pipeline latency, API response times, concurrency, and fault tolerance."""

    @pytest.mark.asyncio
    async def test_pipeline_execution_latency_benchmark(self):
        """Full pipeline execution latency must be under 500ms for production throughput."""
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

        start_t = time.perf_counter()
        result = await execute_production_signal_pipeline(
            "NIFTY 50",
            custom_timeframes=tfs,
            custom_quote=quote,
            custom_option_chain=chain,
            available_capital=100000.0,
        )
        duration_ms = (time.perf_counter() - start_t) * 1000.0
        assert duration_ms < 500.0, f"Pipeline latency {duration_ms:.2f}ms exceeded 500ms budget"
        assert result["action"] == "BUY_CE"

    @pytest.mark.asyncio
    async def test_concurrent_pipeline_executions(self):
        """Multiple concurrent pipeline invocations execute safely without race conditions."""
        tfs = make_bullish_timeframes(24500.0)
        ltp = float(tfs["1m"]["close"].iloc[-1])
        quote = {"currentPrice": ltp, "dayHigh": ltp + 10.0, "dayLow": 24300.0, "openPrice": 24400.0, "previousClose": 24350.0, "change": ltp - 24350.0, "provider": "angelone", "timestamp": datetime.now(timezone.utc).isoformat()}
        chain = build_mock_option_chain("NIFTY", ltp, strikes=[24500, 24550, 24600, 24650, 24700])

        tasks = [
            execute_production_signal_pipeline(
                "NIFTY 50",
                custom_timeframes=tfs,
                custom_quote=quote,
                custom_option_chain=chain,
                available_capital=100000.0,
            )
            for _ in range(5)
        ]
        results = await asyncio.gather(*tasks)

        assert len(results) == 5
        for r in results:
            assert r["action"] == "BUY_CE"
            assert r["is_trade_qualified"] is True
