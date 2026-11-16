"""
AIVOLVE Institutional Quantitative Trading Intelligence v3.0
Phase 2 Step 4.4 Critical Audit Remediation Test Suite (AUDIT-4.4-01)

Verifies:
  1. Future values never flow backward into earlier candles (bfill banned).
  2. Missing OHLC values are not silently fabricated as genuine market data.
  3. Missing volume remains explicitly identifiable and tracked.
  4. Invalid High/Open/Close and Low/Open/Close relationships are detected.
  5. Repaired candles cannot generate qualified signals (fail-closed Stage 3).
  6. DEGRADED data cannot qualify a trade setup.
  7. Valid, unrepaired VERIFIED_LIVE candles continue to qualify trades.
  8. Point-in-time anti-lookahead consistency in historical replay.
"""

import math
import numpy as np
import pandas as pd
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

from app.options.candle_processor import (
    clean_and_validate_ohlcv,
    process_candlestick_series,
    compute_intraday_vwap,
    calculate_ema,
    calculate_atr_wilder,
    calculate_true_range,
    calculate_adx_wilder,
    calculate_bollinger_bands,
)
from app.data.quality_validator import DataQualityEngine, FeedStatus
from app.options.pipeline_orchestrator import execute_production_signal_pipeline, PipelineStage
from app.options.trade_setup_selector import select_trade_setup
from app.options.multi_timeframe_engine import evaluate_multi_timeframe_confluence
from tests.test_pipeline_integration_step4_3 import (
    make_bullish_timeframes,
    build_mock_option_chain,
)


@pytest.fixture(autouse=True)
def default_live_market_session():
    """Default to live market session for pipeline tests unless explicitly overridden."""
    with patch("app.data.quality_validator.MarketCalendar.is_market_open", return_value=True):
        yield


# ===========================================================================
# 1. Look-Ahead Bias & Anti-Backfill Tests
# ===========================================================================

def test_future_values_never_flow_backward_into_earlier_candles():
    """Verify that future candle prices (e.g. Bar 1) NEVER backfill into prior candles (Bar 0)."""
    df = pd.DataFrame([
        {"open": np.nan, "high": 24050.0, "low": 23980.0, "close": 24020.0, "volume": 1000},  # Bar 0 missing open
        {"open": 24800.0, "high": 24850.0, "low": 24780.0, "close": 24820.0, "volume": 2000},  # Bar 1 high future price
    ])

    clean = clean_and_validate_ohlcv(df)

    # Bar 0 open must NEVER be filled with Bar 1's future price (24800.0)
    assert clean["open"].iloc[0] != 24800.0
    # Must be initialized from intra-bar close (24020.0)
    assert clean["open"].iloc[0] == 24020.0
    assert clean.attrs["ohlc_repaired"] is True


def test_missing_ohlc_values_not_silently_fabricated():
    """Verify missing OHLC values set explicit repair audit metadata and fail pristine validation."""
    df_with_nan = pd.DataFrame([
        {"timestamp": "2026-11-06T09:15:00Z", "open": 24000.0, "high": np.nan, "low": 23950.0, "close": 24020.0, "volume": 500},
        {"timestamp": "2026-11-06T09:30:00Z", "open": 24020.0, "high": 24080.0, "low": 24010.0, "close": 24070.0, "volume": 600},
    ])

    audit = DataQualityEngine.validate_ohlc(df_with_nan, timeframe="15m")

    # Pristine validity must be False because repair was required
    assert audit["isValid"] is False
    assert audit["ohlc_repaired"] is True
    assert any("NaN" in str(v) for v in audit["violations"])
    assert len(audit["repair_details"]) > 0
    # Original data preserved bit-for-bit
    assert np.isnan(audit["originalDf"]["high"].iloc[0])


def test_missing_volume_remains_explicitly_identifiable():
    """Verify missing volume is flagged in metadata and disables VWAP qualification."""
    # Case A: Volume column completely omitted
    df_no_vol = pd.DataFrame([
        {"timestamp": "2026-11-06T09:15:00Z", "open": 24000.0, "high": 24050.0, "low": 23980.0, "close": 24020.0},
        {"timestamp": "2026-11-06T09:30:00Z", "open": 24020.0, "high": 24080.0, "low": 24010.0, "close": 24070.0},
    ])
    audit_no_vol = DataQualityEngine.validate_ohlc(df_no_vol)
    assert audit_no_vol["isValid"] is False
    assert audit_no_vol["ohlc_repaired"] is True
    assert any("Missing volume column" in v for v in audit_no_vol["violations"])

    clean_no_vol = clean_and_validate_ohlcv(df_no_vol)
    assert clean_no_vol.attrs["has_missing_volume"] is True

    vwap, unweighted, has_vwap = compute_intraday_vwap(clean_no_vol)
    assert has_vwap is False
    assert np.all(np.isnan(vwap))

    # Case B: Volume column has NaNs
    df_nan_vol = pd.DataFrame([
        {"timestamp": "2026-11-06T09:15:00Z", "open": 24000.0, "high": 24050.0, "low": 23980.0, "close": 24020.0, "volume": np.nan},
        {"timestamp": "2026-11-06T09:30:00Z", "open": 24020.0, "high": 24080.0, "low": 24010.0, "close": 24070.0, "volume": 500.0},
    ])
    audit_nan_vol = DataQualityEngine.validate_ohlc(df_nan_vol)
    assert audit_nan_vol["ohlc_repaired"] is True
    assert any("missing/NaN volume" in v for v in audit_nan_vol["violations"])


def test_invalid_high_low_geometry_detected():
    """Verify invalid geometric relationships (High < max(O,C), Low > min(O,C)) are detected and flagged."""
    df_bad_geom = pd.DataFrame([
        # Bar 0: High (24010) is less than Open (24050)
        {"timestamp": "2026-11-06T09:15:00Z", "open": 24050.0, "high": 24010.0, "low": 23980.0, "close": 24000.0, "volume": 1000},
        # Bar 1: Low (24040) is greater than Close (24020)
        {"timestamp": "2026-11-06T09:30:00Z", "open": 24060.0, "high": 24090.0, "low": 24040.0, "close": 24020.0, "volume": 1200},
    ])

    audit = DataQualityEngine.validate_ohlc(df_bad_geom)
    assert audit["isValid"] is False
    assert audit["ohlc_repaired"] is True
    assert any("High < max(Open, Close)" in v for v in audit["violations"])
    assert any("Low > min(Open, Close)" in v for v in audit["violations"])


# ===========================================================================
# 2. Pipeline Fail-Closed Protection Tests
# ===========================================================================

@pytest.mark.asyncio
async def test_repaired_candles_cannot_generate_qualified_signals():
    """Verify repaired candles on required timeframes trigger Stage 3 failure and force NO_TRADE."""
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

    # Corrupt 5M candle series with inverted High < Open
    corrupt_5m = tfs["5m"].copy()
    corrupt_5m.loc[corrupt_5m.index[5], "high"] = corrupt_5m.loc[corrupt_5m.index[5], "open"] - 15.0
    tfs["5m"] = corrupt_5m

    res = await execute_production_signal_pipeline(
        "NIFTY 50",
        custom_timeframes=tfs,
        custom_quote=quote,
        custom_option_chain=chain,
        available_capital=100000.0,
    )

    # Must fail Stage 3 and lock out trading
    assert res["stage_status"][PipelineStage.STAGE_3_CANDLE_COMPLETENESS] == "FAILED"
    assert res["action"] == "NO_TRADE"
    assert res["is_trade_qualified"] is False
    assert res["data_quality_report"]["feedStatus"] == FeedStatus.DEGRADED
    assert any("Repaired or invalid OHLC candles" in r for r in res["rejection_reasons"])


def test_degraded_data_cannot_qualify_trade():
    """Verify that DEGRADED data quality status strictly blocks trade setup qualification."""
    tfs = make_bullish_timeframes(24500.0)
    ltp = float(tfs["1m"]["close"].iloc[-1])
    quote = {"currentPrice": ltp, "dayHigh": ltp + 10.0, "dayLow": 24300.0, "previousClose": 24350.0, "change": 230.0}

    mtf_res = evaluate_multi_timeframe_confluence(
        symbol="NIFTY 50",
        timeframe_candles=tfs,
        current_quote=quote,
        data_quality_status=FeedStatus.DEGRADED,
        is_live_data=False,
    )

    setup_res = select_trade_setup(
        symbol="NIFTY 50",
        quote=quote,
        mtf_confluence=mtf_res,
        is_live_data=False,
    )

    assert mtf_res["can_activate_directional"] is False
    assert setup_res["action"] == "NO_TRADE"
    assert setup_res["qualification_status"] in ["REJECTED", "UNQUALIFIED"]


@pytest.mark.asyncio
async def test_valid_unrepaired_verified_live_candles_continue_to_work():
    """Verify that pristine, valid VERIFIED_LIVE market data qualifies trade setups as normal."""
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

    assert res["stage_status"][PipelineStage.STAGE_3_CANDLE_COMPLETENESS] == "SUCCESS"
    assert res["action"] == "BUY_CE"
    assert res["is_trade_qualified"] is True
    assert res["data_quality_report"]["feedStatus"] == FeedStatus.VERIFIED_LIVE


def test_no_lookahead_bias_in_historical_replay():
    """
    Mathematical point-in-time invariant:
    Indicator values at bar index T must be identical whether calculated
    on the full 50-bar series or a sliced 30-bar series ending at T.
    """
    np.random.seed(42)
    n = 50
    closes = np.cumsum(np.random.randn(n) * 2.0) + 24500.0
    highs = closes + np.abs(np.random.randn(n)) + 5.0
    lows = closes - np.abs(np.random.randn(n)) - 5.0
    opens = closes + np.random.randn(n)
    vols = np.random.randint(100, 5000, size=n).astype(float)

    full_df = pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": closes, "volume": vols})
    t = 30
    sliced_df = full_df.iloc[:t].copy()

    full_res = process_candlestick_series(full_df, symbol="NIFTY 50")
    sliced_res = process_candlestick_series(sliced_df, symbol="NIFTY 50")

    # Bar T-1 (last bar of sliced) must match exactly in full_res
    full_bar_t = full_res["candles"][t - 1]
    sliced_bar_t = sliced_res["candles"][-1]

    assert full_bar_t["ema20"] == sliced_bar_t["ema20"]
    assert full_bar_t["atr"] == sliced_bar_t["atr"]
    assert full_bar_t["bb_upper"] == sliced_bar_t["bb_upper"]
    assert full_bar_t["bb_lower"] == sliced_bar_t["bb_lower"]
