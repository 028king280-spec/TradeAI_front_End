import pytest
import asyncio
import hashlib
from typing import Dict, Any
from unittest.mock import AsyncMock, patch

from app.api.routes.stocks import _normalize_api_data_status
from app.schemas.stock import StockQuote
from app.data.market_calendar import MarketCalendar
from app.services.stock_sentiment_service import StockSentimentCalculatorService
from app.services.news_scanner_service import IntradayNewsScannerService
from app.data.providers.angelone_provider import AngelOneMarketDataProvider
from app.core.config import settings


# ---------------------------------------------------------------------------
# TEST 1: Status Normalization
# ---------------------------------------------------------------------------
def test_normalize_api_data_status():
    # Live statuses
    assert _normalize_api_data_status("LIVE") == "LIVE"
    assert _normalize_api_data_status("live") == "LIVE"
    assert _normalize_api_data_status("VERIFIED_LIVE") == "LIVE"

    # Closed market / EOD statuses
    assert _normalize_api_data_status("MARKET_CLOSED") == "MARKET_CLOSED"
    assert _normalize_api_data_status("market_closed") == "MARKET_CLOSED"
    assert _normalize_api_data_status("VERIFIED_EOD") == "MARKET_CLOSED"
    assert _normalize_api_data_status("EOD") == "MARKET_CLOSED"

    # Offline / Stale statuses
    assert _normalize_api_data_status("DATA_OFFLINE") == "DATA_OFFLINE"
    assert _normalize_api_data_status("STALE") == "STALE"
    assert _normalize_api_data_status("UNAVAILABLE") == "UNAVAILABLE"

    # Mock statuses
    assert _normalize_api_data_status("MOCK") == "MOCK"
    assert _normalize_api_data_status("anything", is_mock=True) == "MOCK"

    # Unrecognized fallback
    assert _normalize_api_data_status("UNKNOWN_FEED") == "UNAVAILABLE"
    assert _normalize_api_data_status(None) == "UNAVAILABLE"


# ---------------------------------------------------------------------------
# TEST 2: StockQuote Schema Validation
# ---------------------------------------------------------------------------
def test_stock_quote_schema_validation():
    valid_live = {
        "symbol": "RELIANCE",
        "companyName": "Reliance Industries Limited",
        "exchange": "NSE",
        "currentPrice": 1377.50,
        "change": -2.60,
        "changePercent": -0.19,
        "openPrice": 1380.00,
        "dayHigh": 1386.50,
        "dayLow": 1373.00,
        "previousClose": 1380.10,
        "volume": 4521000.0,
        "timestamp": "2026-11-21T15:30:00+05:30",
        "dataStatus": "LIVE",
    }
    quote_obj = StockQuote(**valid_live)
    assert quote_obj.symbol == "RELIANCE"
    assert quote_obj.currentPrice == 1377.50
    assert quote_obj.dataStatus == "LIVE"

    valid_closed = {
        "symbol": "TCS",
        "companyName": "Tata Consultancy Services Limited",
        "exchange": "NSE",
        "currentPrice": 2376.20,
        "change": 14.50,
        "changePercent": 0.61,
        "openPrice": 2365.00,
        "dayHigh": 2382.00,
        "dayLow": 2360.00,
        "previousClose": 2361.70,
        "volume": 1250000.0,
        "timestamp": "2026-11-21T15:30:00+05:30",
        "dataStatus": "MARKET_CLOSED",
        "isTradeQualified": False,
    }
    quote_closed_obj = StockQuote(**valid_closed)
    assert quote_closed_obj.symbol == "TCS"
    assert quote_closed_obj.dataStatus == "MARKET_CLOSED"
    assert quote_closed_obj.isTradeQualified is False


# ---------------------------------------------------------------------------
# TEST 3: Stock Sentiment Service Price Preservation
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_stock_sentiment_preserves_live_price():
    live_quote = {
        "symbol": "RELIANCE",
        "companyName": "Reliance Industries Limited",
        "currentPrice": 1377.50,
        "ltp": 1377.50,
        "change": 5.20,
        "changePercent": 0.38,
        "dayHigh": 1385.00,
        "dayLow": 1370.00,
        "dataStatus": "LIVE",
        "feedStatus": "VERIFIED_LIVE",
        "timestamp": "2026-11-21T15:30:00+05:30",
    }

    with patch("app.services.stock_sentiment_service.get_market_data_provider") as mock_prov_factory, \
         patch("app.services.stock_sentiment_service.get_financial_news_provider") as mock_news_factory, \
         patch("app.core.cache.CacheService.get", return_value=None), \
         patch("app.core.cache.CacheService.set", return_value=True):

        mock_prov = AsyncMock()
        mock_prov.get_quote.return_value = live_quote
        mock_prov_factory.return_value = mock_prov

        mock_news = AsyncMock()
        mock_news.get_news_for_stock.return_value = []
        mock_news._fetch_google_rss.return_value = []
        mock_news_factory.return_value = mock_news

        result = await StockSentimentCalculatorService.calculate("RELIANCE")

        assert result is not None
        assert "priceMetrics" in result
        pm = result["priceMetrics"]
        assert pm["currentPrice"] == 1377.50
        assert pm["isLive"] is True
        assert pm["isEod"] is False
        assert pm["dataStatus"] == "LIVE"
        assert pm["priceLabel"] == "Live CMP"


@pytest.mark.asyncio
async def test_stock_sentiment_preserves_closed_market_eod_price():
    eod_quote = {
        "symbol": "TCS",
        "companyName": "Tata Consultancy Services Limited",
        "currentPrice": 2376.20,
        "ltp": 2376.20,
        "change": -8.50,
        "changePercent": -0.36,
        "dayHigh": 2390.00,
        "dayLow": 2370.00,
        "dataStatus": "MARKET_CLOSED",
        "feedStatus": "VERIFIED_EOD",
        "timestamp": "2026-11-21T15:30:00+05:30",
    }

    with patch("app.services.stock_sentiment_service.get_market_data_provider") as mock_prov_factory, \
         patch("app.services.stock_sentiment_service.get_financial_news_provider") as mock_news_factory, \
         patch("app.core.cache.CacheService.get", return_value=None), \
         patch("app.core.cache.CacheService.set", return_value=True):

        mock_prov = AsyncMock()
        mock_prov.get_quote.return_value = eod_quote
        mock_prov_factory.return_value = mock_prov

        mock_news = AsyncMock()
        mock_news.get_news_for_stock.return_value = []
        mock_news._fetch_google_rss.return_value = []
        mock_news_factory.return_value = mock_news

        result = await StockSentimentCalculatorService.calculate("TCS")

        assert result is not None
        pm = result["priceMetrics"]
        assert pm["currentPrice"] == 2376.20
        assert pm["isLive"] is False
        assert pm["isEod"] is True
        assert pm["dataStatus"] == "MARKET_CLOSED"
        assert pm["priceLabel"] == "Last Verified Close"


@pytest.mark.asyncio
async def test_stock_sentiment_hdfcbank_index_disambiguation():
    banknifty_masquerading = {
        "symbol": "HDFCBANK",
        "companyName": "HDFC Bank Limited",
        "currentPrice": 51820.00,  # Erroneously returning BANKNIFTY index level
        "ltp": 51820.00,
        "change": 350.00,
        "changePercent": 0.68,
        "dayHigh": 52000.00,
        "dayLow": 51500.00,
        "dataStatus": "LIVE",
    }

    with patch("app.services.stock_sentiment_service.get_market_data_provider") as mock_prov_factory, \
         patch("app.services.stock_sentiment_service.get_financial_news_provider") as mock_news_factory, \
         patch("app.core.cache.CacheService.get", return_value=None), \
         patch("app.core.cache.CacheService.set", return_value=True):

        mock_prov = AsyncMock()
        mock_prov.get_quote.return_value = banknifty_masquerading
        mock_prov_factory.return_value = mock_prov

        mock_news = AsyncMock()
        mock_news.get_news_for_stock.return_value = []
        mock_news._fetch_google_rss.return_value = []
        mock_news_factory.return_value = mock_news

        result = await StockSentimentCalculatorService.calculate("HDFCBANK")

        # Disambiguation guard should zero out index level price for HDFCBANK equity
        pm = result["priceMetrics"]
        assert pm["currentPrice"] == 0.0


# ---------------------------------------------------------------------------
# TEST 4: Angel One Provider EOD Snapshot & Fallback Safety
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_angelone_eod_snapshot_is_not_trade_qualified():
    provider = AngelOneMarketDataProvider()
    cached_last_verified = {
        "symbol": "RELIANCE",
        "companyName": "Reliance Industries Limited",
        "currentPrice": 1377.50,
        "close": 1377.50,
        "is_mock": False,
    }

    with patch("app.core.cache.CacheService.get") as mock_cache_get, \
         patch("app.core.cache.CacheService.set", return_value=True):

        async def cache_side_effect(key):
            if key == "eod_quote:RELIANCE":
                return None
            if key == "last_verified_quote:RELIANCE":
                return cached_last_verified
            return None

        mock_cache_get.side_effect = cache_side_effect

        token_info = {"exchange": "NSE", "symbol_token": "2885"}
        eod_res = await provider._get_eod_snapshot("RELIANCE", token_info)

        assert eod_res["currentPrice"] == 1377.50
        assert eod_res["dataStatus"] == "MARKET_CLOSED"
        assert eod_res["feedStatus"] == "VERIFIED_EOD"
        assert eod_res["isTradeQualified"] is False  # Invariant: EOD must never qualify trades
        assert "timestamp" in eod_res


@pytest.mark.asyncio
async def test_angelone_offline_quote_includes_timestamp():
    provider = AngelOneMarketDataProvider()
    token_info = {"exchange": "NSE", "symbol_token": "9999"}

    with patch("app.core.cache.CacheService.get", return_value=None):
        eod_res = await provider._get_eod_snapshot("UNKNOWN_SYM", token_info)
        assert eod_res["dataStatus"] == "DATA_OFFLINE"
        assert "timestamp" in eod_res
        assert eod_res["isTradeQualified"] is False


# ---------------------------------------------------------------------------
# TEST 5: Default Market Data Provider Configuration
# ---------------------------------------------------------------------------
def test_default_market_data_provider():
    assert settings.MARKET_DATA_PROVIDER == "angelone"


# ---------------------------------------------------------------------------
# TEST 6: Protected Baseline Files Integrity
# ---------------------------------------------------------------------------
def test_protected_baseline_hashes():
    expected_hashes = {
        "app/data/paper_trading_records.json": "69c7f386f9a209b3806d33f3cd8d6f89d4150a576abdafa702db77aa365309c8",
        "app/data/governance_ledger.db": "4b12b3bab44bf913f15174278b346fa321d5c473272e40f8b7e6e2350034488e",
        "app/data/ml_trade_dataset.json": "3fdf091dfbbdb70c7d22785ae8ebe15cf6fefc2f03e95407617a968145e8319c",
        "app/data/what_ai_learned.json": "39bc53d93a5f49fd8c53b9c871102f8e940e0519a5faf963eb1737346f244c8c",
        "app/data/ml_strategy_weights.json": "0455dbad35af172dc37ddd645e4487a058369a4e1a4cdef9a5c923a85992e937",
    }

    import os
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    workspace_dir = os.path.dirname(backend_dir)
    for rel_path, expected_hash in expected_hashes.items():
        full_path = os.path.join(backend_dir, rel_path)
        assert os.path.exists(full_path), f"Missing protected file: {full_path}"
        with open(full_path, "rb") as f:
            actual_hash = hashlib.sha256(f.read()).hexdigest().lower()
        assert actual_hash == expected_hash, f"Hash mismatch for {rel_path}: expected {expected_hash}, got {actual_hash}"

    # Also verify workspace-level aivolve_trading.db
    db_path = os.path.join(workspace_dir, "aivolve_trading.db")
    if os.path.exists(db_path):
        with open(db_path, "rb") as f:
            db_hash = hashlib.sha256(f.read()).hexdigest().lower()
        assert db_hash == "8870d868aa300a7ebc0c51b5f820d8a7c467e3c33f2634edd1d7329afdff519f"
