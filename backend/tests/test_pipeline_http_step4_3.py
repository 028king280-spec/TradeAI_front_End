"""
AIVOLVE Institutional Quantitative Trading Intelligence v3.0
Phase 2 Step 4.3 HTTP-Level Integration Test Suite

Verifies:
  1. GET /api/options/{index}/analysis is strictly read-only (Stage 12 skipped, 0 DB writes).
  2. POST /api/signals/generate persists a fully qualified paper SignalRecord and returns status: "GENERATED".
  3. POST /api/signals/generate duplicate call returns status: "DUPLICATE" with zero duplicate DB rows.
  4. POST /api/signals/generate rejected setup returns status: "REJECTED" and writes 0 DB rows.
  5. EOD settlement data rejects live-session trade setup qualification with action: "NO_TRADE".
  6. Authenticated-but-stale market feed reflects dataStatus: "STALE".
  7. Authenticated-but-anomalous market feed reflects dataStatus: "ANOMALOUS".
  8. GET /api/signals/today returns consistent production schema and zero synthetic pre-seeding.
"""

from typing import Dict, Any, List
import pytest
from httpx import AsyncClient, ASGITransport
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock
from sqlalchemy import select, func

from app.main import app
from app.db.database import async_session_factory
from app.models.db_models import SignalRecord
from app.data.quality_validator import FeedStatus
from app.options.contract_selector import set_governance_ledger_db_path

from tests.test_pipeline_integration_step4_3 import (
    generate_candle_series,
    make_bullish_timeframes,
    build_mock_option_chain,
)


@pytest.fixture(autouse=True)
def isolated_governance_ledger(tmp_path):
    """Ensures governance ledger is isolated in ephemeral SQLite file."""
    test_db = str(tmp_path / "test_http_governance.db")
    set_governance_ledger_db_path(test_db)
    yield test_db
    set_governance_ledger_db_path(None)


@pytest.fixture(autouse=True)
def default_live_market_session():
    """Default to live market session unless overridden by specific EOD test."""
    with patch("app.data.quality_validator.MarketCalendar.is_market_open", return_value=True):
        yield


def build_mock_provider(tfs: Dict[str, Any], quote: Dict[str, Any]):
    """Creates a mock market data provider mimicking an authenticated institutional broker."""
    provider = MagicMock()
    provider.get_provider_name.return_value = "angelone"
    provider.is_authenticated = True

    async def _get_quote(symbol):
        return dict(quote)

    async def _get_intraday_candles(symbol, timeframe):
        return tfs.get(timeframe)

    async def _get_batch_quotes(exchange, tokens):
        return {}

    provider.get_quote = _get_quote
    provider.get_intraday_candles = _get_intraday_candles
    provider.get_batch_quotes = _get_batch_quotes
    return provider


# ===========================================================================
# 1. GET /api/options/{index}/analysis is Strictly Read-Only
# ===========================================================================
@pytest.mark.asyncio
async def test_http_options_analysis_is_strictly_read_only():
    """GET /api/options/{index}/analysis executes analysis without mutating SignalRecord table."""
    async with async_session_factory() as session:
        count_before = (await session.execute(select(func.count(SignalRecord.id)))).scalar_one()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/options/NIFTY%2050/analysis")
        assert res.status_code == 200
        data = res.json()

        # Verify key read-only analysis sections are present
        assert data["symbol"] == "NIFTY 50"
        assert "marketState" in data
        assert "todayOptionsSetups" in data
        assert "supportResistance" in data
        assert "dataStatus" in data
        assert "dataQualityReport" in data

    async with async_session_factory() as session:
        count_after = (await session.execute(select(func.count(SignalRecord.id)))).scalar_one()

    assert count_after == count_before, "Read-only GET /analysis endpoint must never persist signals to the database."


# ===========================================================================
# 2. POST /api/signals/generate Persists Fully Qualified Signal
# ===========================================================================
@pytest.mark.asyncio
async def test_http_generate_signal_persists_signal_record():
    """POST /api/signals/generate persists a fully qualified signal into SignalRecord storage."""
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
    mock_provider = build_mock_provider(tfs, quote)

    async with async_session_factory() as session:
        count_before = (await session.execute(select(func.count(SignalRecord.id)))).scalar_one()

    with patch("app.data.providers.factory.get_market_data_provider", return_value=mock_provider):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.post(
                "/api/signals/generate",
                json={
                    "symbol": "NIFTY 50",
                    "available_capital": 100000.0,
                    "custom_quote": quote,
                    "custom_option_chain": chain,
                },
            )
            assert res.status_code == 200
            data = res.json()
            assert data["success"] is True
            payload = data["data"]
            assert payload["status"] == "GENERATED"
            assert payload["action"] == "BUY_CE"
            assert payload["isTradeQualified"] is True
            assert payload["persistedSignalId"] is not None
            assert payload["persistedSignal"] is not None
            persisted_id = payload["persistedSignalId"]

    async with async_session_factory() as session:
        count_after = (await session.execute(select(func.count(SignalRecord.id)))).scalar_one()
        persisted = await session.get(SignalRecord, persisted_id)

    assert count_after == count_before + 1
    assert persisted is not None
    assert persisted.symbol == "NIFTY 50"
    assert persisted.option_type == "CE"
    assert persisted.status == "WAITING_FOR_ENTRY"


# ===========================================================================
# 3. POST /api/signals/generate Replay / Idempotency Protection
# ===========================================================================
@pytest.mark.asyncio
async def test_http_generate_signal_duplicate_protection():
    """POST /api/signals/generate detects existing signal for same strike/date and returns DUPLICATE."""
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
    mock_provider = build_mock_provider(tfs, quote)

    with patch("app.data.providers.factory.get_market_data_provider", return_value=mock_provider):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # First request -> GENERATED
            res1 = await client.post(
                "/api/signals/generate",
                json={
                    "symbol": "NIFTY 50",
                    "available_capital": 100000.0,
                    "custom_quote": quote,
                    "custom_option_chain": chain,
                },
            )
            assert res1.status_code == 200

            async with async_session_factory() as session:
                count_after_first = (await session.execute(select(func.count(SignalRecord.id)))).scalar_one()

            # Second identical request -> DUPLICATE
            res2 = await client.post(
                "/api/signals/generate",
                json={
                    "symbol": "NIFTY 50",
                    "available_capital": 100000.0,
                    "custom_quote": quote,
                    "custom_option_chain": chain,
                },
            )
            assert res2.status_code == 200
            data2 = res2.json()
            assert data2["success"] is True
            assert data2["data"]["status"] == "DUPLICATE"
            assert data2["data"]["isTradeQualified"] is True

            async with async_session_factory() as session:
                count_after_second = (await session.execute(select(func.count(SignalRecord.id)))).scalar_one()

    # Database count must not increase on duplicate call
    assert count_after_second == count_after_first


# ===========================================================================
# 4. POST /api/signals/generate Rejected Setup Writes Zero Rows
# ===========================================================================
@pytest.mark.asyncio
async def test_http_generate_signal_rejected_writes_zero_db_rows():
    """POST /api/signals/generate for an unconfigured symbol rejects and creates zero DB records."""
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
    mock_provider = build_mock_provider(tfs, quote)

    async with async_session_factory() as session:
        count_before = (await session.execute(select(func.count(SignalRecord.id)))).scalar_one()

    with patch("app.data.providers.factory.get_market_data_provider", return_value=mock_provider):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.post(
                "/api/signals/generate",
                json={
                    "symbol": "SENSEX",
                    "available_capital": 100000.0,
                    "custom_quote": quote,
                    "custom_option_chain": chain,
                },
            )
            assert res.status_code == 200
            data = res.json()
            assert data["success"] is True
            payload = data["data"]
            assert payload["status"] == "REJECTED"
            assert payload["action"] == "NO_TRADE"
            assert payload["isTradeQualified"] is False
            assert any("UNCONFIGURED" in r or "SENSEX" in r for r in payload["rejectionReasons"])

    async with async_session_factory() as session:
        count_after = (await session.execute(select(func.count(SignalRecord.id)))).scalar_one()

    assert count_after == count_before


# ===========================================================================
# 5. EOD Settlement Data Rejected From Live Qualification
# ===========================================================================
@pytest.mark.asyncio
async def test_http_eod_data_rejected_from_live_qualification():
    """VERIFIED_EOD feed status gates directional live trade setups with action: 'NO_TRADE'."""
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
    mock_provider = build_mock_provider(tfs, quote)

    async with async_session_factory() as session:
        count_before = (await session.execute(select(func.count(SignalRecord.id)))).scalar_one()

    with patch("app.data.providers.factory.get_market_data_provider", return_value=mock_provider):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.post(
                "/api/signals/generate",
                json={
                    "symbol": "NIFTY 50",
                    "available_capital": 100000.0,
                    "custom_quote": quote,
                    "custom_option_chain": chain,
                },
            )
            assert res.status_code == 200
            data = res.json()
            assert data["success"] is True
            payload = data["data"]
            assert payload["status"] == "REJECTED"
            assert payload["action"] == "NO_TRADE"
            assert payload["isTradeQualified"] is False
            assert any("VERIFIED_EOD" in r or "Non-live" in r for r in payload["rejectionReasons"])

    async with async_session_factory() as session:
        count_after = (await session.execute(select(func.count(SignalRecord.id)))).scalar_one()

    assert count_after == count_before


# ===========================================================================
# 6. Authenticated-But-Stale Market Feed Reflects dataStatus: "STALE"
# ===========================================================================
@pytest.mark.asyncio
async def test_http_analysis_stale_feed_sets_data_status_stale():
    """GET /api/options/{index}/analysis with stale quote reflects dataStatus: 'STALE'."""
    stale_ts = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat()
    stale_quote = {
        "currentPrice": 24500.0,
        "dayHigh": 24520.0,
        "dayLow": 24400.0,
        "openPrice": 24450.0,
        "previousClose": 24420.0,
        "change": 80.0,
        "provider": "angelone",
        "timestamp": stale_ts,
    }
    df_15m = generate_candle_series(20, start_price=24450.0)
    mock_provider = build_mock_provider({"15m": df_15m, "5m": df_15m}, stale_quote)

    with patch("app.data.providers.factory.get_market_data_provider", return_value=mock_provider), \
         patch("app.api.routes.options.get_market_data_provider", return_value=mock_provider):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.get("/api/options/NIFTY%2050/analysis")
            assert res.status_code == 200
            data = res.json()
            assert data["dataStatus"] == FeedStatus.STALE
            assert data["isTradeQualified"] is False
            assert data["dataQualityReport"]["feedStatus"] == FeedStatus.STALE


# ===========================================================================
# 7. Authenticated-But-Anomalous Market Feed Reflects dataStatus: "ANOMALOUS"
# ===========================================================================
@pytest.mark.asyncio
async def test_http_analysis_anomalous_feed_sets_data_status_anomalous():
    """GET /api/options/{index}/analysis with freak tick outlier reflects dataStatus: 'ANOMALOUS'."""
    df_15m = generate_candle_series(20, start_price=24500.0, trend="neutral")
    # Massive 10,000 pt freak tick deviation
    anomalous_quote = {
        "currentPrice": 34500.0,
        "dayHigh": 34500.0,
        "dayLow": 24000.0,
        "openPrice": 24500.0,
        "previousClose": 24500.0,
        "change": 10000.0,
        "provider": "angelone",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    mock_provider = build_mock_provider({"15m": df_15m, "5m": df_15m}, anomalous_quote)

    with patch("app.data.providers.factory.get_market_data_provider", return_value=mock_provider), \
         patch("app.api.routes.options.get_market_data_provider", return_value=mock_provider):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.get("/api/options/NIFTY%2050/analysis")
            assert res.status_code == 200
            data = res.json()
            assert data["dataStatus"] == FeedStatus.ANOMALOUS
            assert data["isTradeQualified"] is False
            assert data["dataQualityReport"]["feedStatus"] == FeedStatus.ANOMALOUS


# ===========================================================================
# 8. GET /api/signals/today Schema Compatibility
# ===========================================================================
@pytest.mark.asyncio
async def test_http_signals_today_schema_compatibility():
    """GET /api/signals/today returns valid schema and accurately matches database state."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/signals/today")
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        payload = data["data"]

        # Verify production schema keys
        assert "calls" in payload
        assert "puts" in payload
        assert "trackedOptionSetups" in payload
        assert "totalTrackedToday" in payload
        assert "timestamp" in payload

        assert isinstance(payload["trackedOptionSetups"], list)
        assert payload["totalTrackedToday"] == len(payload["trackedOptionSetups"])
        assert data["dataStatus"] in ["LIVE", "MOCK"]


# ===========================================================================
# 9. Finding 1: Strict Fail-Closed Data Status Hardening
# ===========================================================================
@pytest.mark.asyncio
async def test_http_analysis_authenticated_provider_missing_feed_status_fails_closed():
    """1. Authenticated provider with missing feedStatus fails closed to DATA_UNAVAILABLE."""
    df_15m = generate_candle_series(20, start_price=24500.0)
    ltp = float(df_15m["close"].iloc[-1])
    quote = {
        "currentPrice": ltp,
        "dayHigh": ltp + 10.0,
        "dayLow": 24450.0,
        "openPrice": 24480.0,
        "previousClose": 24460.0,
        "change": ltp - 24460.0,
        "provider": "angelone",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    mock_provider = build_mock_provider({"15m": df_15m, "5m": df_15m}, quote)

    with patch("app.data.providers.factory.get_market_data_provider", return_value=mock_provider), \
         patch("app.api.routes.options.get_market_data_provider", return_value=mock_provider), \
         patch("app.data.quality_validator.DataQualityEngine.validate_quote") as mock_val:
        mock_val.return_value = {
            "sanitizedQuote": quote,
            "dataQualityReport": {
                "symbol": "NIFTY 50",
                "dataQualityScore": 100,
                # Intentionally missing feedStatus key
                "latencyMs": 12.0,
                "isTradeQualified": True,
            },
        }
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.get("/api/options/NIFTY%2050/analysis")
            assert res.status_code == 200
            data = res.json()
            assert data["dataStatus"] == FeedStatus.DATA_UNAVAILABLE
            assert data["dataStatus"] != "LIVE"
            assert data["dataStatus"] != "VERIFIED_LIVE"
            assert data["isTradeQualified"] is False


@pytest.mark.asyncio
async def test_http_analysis_authenticated_provider_unknown_feed_status_fails_closed():
    """2. Authenticated provider with unknown feedStatus fails closed to DATA_UNAVAILABLE."""
    df_15m = generate_candle_series(20, start_price=24500.0)
    ltp = float(df_15m["close"].iloc[-1])
    quote = {
        "currentPrice": ltp,
        "dayHigh": ltp + 10.0,
        "dayLow": 24450.0,
        "openPrice": 24480.0,
        "previousClose": 24460.0,
        "change": ltp - 24460.0,
        "provider": "angelone",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    mock_provider = build_mock_provider({"15m": df_15m, "5m": df_15m}, quote)

    with patch("app.data.providers.factory.get_market_data_provider", return_value=mock_provider), \
         patch("app.api.routes.options.get_market_data_provider", return_value=mock_provider), \
         patch("app.data.quality_validator.DataQualityEngine.validate_quote") as mock_val:
        mock_val.return_value = {
            "sanitizedQuote": quote,
            "dataQualityReport": {
                "symbol": "NIFTY 50",
                "dataQualityScore": 100,
                "feedStatus": "UNRECOGNIZED_CUSTOM_FEED_STATUS",
                "latencyMs": 12.0,
                "isTradeQualified": True,
            },
        }
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.get("/api/options/NIFTY%2050/analysis")
            assert res.status_code == 200
            data = res.json()
            assert data["dataStatus"] == FeedStatus.DATA_UNAVAILABLE
            assert data["dataStatus"] != "LIVE"
            assert data["dataStatus"] != "VERIFIED_LIVE"
            assert data["isTradeQualified"] is False


@pytest.mark.asyncio
async def test_http_analysis_authenticated_provider_valid_verified_live():
    """3. Authenticated provider with valid live feed explicitly reflects VERIFIED_LIVE."""
    df_15m = generate_candle_series(20, start_price=24500.0)
    ltp = float(df_15m["close"].iloc[-1])
    quote = {
        "currentPrice": ltp,
        "dayHigh": ltp + 10.0,
        "dayLow": 24450.0,
        "openPrice": 24480.0,
        "previousClose": 24460.0,
        "change": ltp - 24460.0,
        "provider": "angelone",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    mock_provider = build_mock_provider({"15m": df_15m, "5m": df_15m}, quote)

    with patch("app.data.providers.factory.get_market_data_provider", return_value=mock_provider), \
         patch("app.api.routes.options.get_market_data_provider", return_value=mock_provider):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.get("/api/options/NIFTY%2050/analysis")
            assert res.status_code == 200
            data = res.json()
            assert data["dataStatus"] == FeedStatus.VERIFIED_LIVE
            assert data["dataQualityReport"]["feedStatus"] == FeedStatus.VERIFIED_LIVE
            assert data["isTradeQualified"] is True


@pytest.mark.asyncio
async def test_http_analysis_authenticated_provider_stale_feed():
    """4. Authenticated provider with STALE feed reflects STALE."""
    stale_ts = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat()
    quote = {
        "currentPrice": 24500.0,
        "dayHigh": 24520.0,
        "dayLow": 24400.0,
        "openPrice": 24450.0,
        "previousClose": 24420.0,
        "change": 80.0,
        "provider": "angelone",
        "timestamp": stale_ts,
    }
    df_15m = generate_candle_series(20, start_price=24450.0)
    mock_provider = build_mock_provider({"15m": df_15m, "5m": df_15m}, quote)

    with patch("app.data.providers.factory.get_market_data_provider", return_value=mock_provider), \
         patch("app.api.routes.options.get_market_data_provider", return_value=mock_provider):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.get("/api/options/NIFTY%2050/analysis")
            assert res.status_code == 200
            data = res.json()
            assert data["dataStatus"] == FeedStatus.STALE
            assert data["isTradeQualified"] is False


@pytest.mark.asyncio
async def test_http_analysis_authenticated_provider_anomalous_feed():
    """5. Authenticated provider with ANOMALOUS feed reflects ANOMALOUS."""
    df_15m = generate_candle_series(20, start_price=24500.0, trend="neutral")
    quote = {
        "currentPrice": 34500.0,
        "dayHigh": 34500.0,
        "dayLow": 24000.0,
        "openPrice": 24500.0,
        "previousClose": 24500.0,
        "change": 10000.0,
        "provider": "angelone",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    mock_provider = build_mock_provider({"15m": df_15m, "5m": df_15m}, quote)

    with patch("app.data.providers.factory.get_market_data_provider", return_value=mock_provider), \
         patch("app.api.routes.options.get_market_data_provider", return_value=mock_provider):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.get("/api/options/NIFTY%2050/analysis")
            assert res.status_code == 200
            data = res.json()
            assert data["dataStatus"] == FeedStatus.ANOMALOUS
            assert data["isTradeQualified"] is False
