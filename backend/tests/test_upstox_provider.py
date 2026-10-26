import pytest
from datetime import datetime, timezone
from app.data.normalizer import MarketDataNormalizer
from app.data.providers.upstox_provider import UpstoxMarketDataProvider, UPSTOX_INSTRUMENT_MAP
from app.data.providers.factory import get_market_data_provider


def test_market_data_normalizer():
    quote = MarketDataNormalizer.normalize_quote(
        symbol="RELIANCE",
        exchange="NSE",
        instrument_key="NSE_EQ|INE002A01018",
        ltp=1456.80,
        open_price=1448.00,
        high=1462.50,
        low=1442.20,
        close=1438.90,
        volume=1234567,
    )
    assert quote["symbol"] == "RELIANCE"
    assert quote["exchange"] == "NSE"
    assert quote["instrument_key"] == "NSE_EQ|INE002A01018"
    assert quote["ltp"] == 1456.80
    assert quote["open"] == 1448.00
    assert quote["high"] == 1462.50
    assert quote["low"] == 1442.20
    assert quote["close"] == 1438.90
    assert quote["volume"] == 1234567
    assert quote["change"] == round(1456.80 - 1438.90, 2)
    assert quote["changePercent"] > 0


def test_normalize_upstox_raw_quote():
    raw_quote = {
        "instrument_token": "NSE_EQ|INE002A01018",
        "last_price": 1455.0,
        "volume": 2500000,
        "average_price": 1451.2,
        "ohlc": {
            "open": 1445.0,
            "high": 1460.0,
            "low": 1440.0,
            "close": 1448.0,
        },
        "net_change": 7.0,
    }
    normalized = MarketDataNormalizer.normalize_upstox_quote("RELIANCE", raw_quote)
    assert normalized["symbol"] == "RELIANCE"
    assert normalized["ltp"] == 1455.0
    assert normalized["volume"] == 2500000
    assert normalized["vwap"] == 1451.2
    assert normalized["open"] == 1445.0


@pytest.mark.asyncio
async def test_upstox_provider_fallback_and_status():
    provider = UpstoxMarketDataProvider()
    assert provider.get_provider_name() == "upstox"

    # In dev mode without live token, get_quote gracefully returns structured data with MOCK status
    quote = await provider.get_quote("RELIANCE")
    assert quote is not None
    assert quote["symbol"] == "RELIANCE"
    assert "dataStatus" in quote
    assert quote["dataStatus"] in ["LIVE", "MOCK", "UNAVAILABLE"]


@pytest.mark.asyncio
async def test_upstox_option_chain_preparation():
    provider = UpstoxMarketDataProvider()
    chain = await provider.get_option_chain("RELIANCE")
    assert chain["symbol"] == "RELIANCE"
    assert "status" in chain
    # In dev mode without Upstox token, returns UNAVAILABLE without fabricating fake option contracts
    assert chain["status"] in ["LIVE", "UNAVAILABLE"]


def test_upstox_instrument_mapping():
    assert "NIFTY 50" in UPSTOX_INSTRUMENT_MAP
    assert UPSTOX_INSTRUMENT_MAP["NIFTY 50"] == "NSE_INDEX|Nifty 50"
    assert "RELIANCE" in UPSTOX_INSTRUMENT_MAP
    assert UPSTOX_INSTRUMENT_MAP["RELIANCE"] == "NSE_EQ|INE002A01018"
