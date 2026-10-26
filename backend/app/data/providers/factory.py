from app.core.config import settings
from app.core.logging import logger
from app.data.providers.base import MarketDataProvider
from app.data.providers.upstox_provider import UpstoxMarketDataProvider
from app.data.providers.mock_provider import MockMarketDataProvider
from app.data.providers.real_provider import RealMarketDataProvider
from app.data.providers.dhan_provider import DhanMarketDataProvider
from app.data.providers.angelone_provider import AngelOneMarketDataProvider

_provider_instance: MarketDataProvider = None


def get_market_data_provider() -> MarketDataProvider:
    global _provider_instance
    if _provider_instance is None:
        mode = settings.MARKET_DATA_PROVIDER.lower()
        if mode in ["angelone", "smartapi", "angel"]:
            _provider_instance = AngelOneMarketDataProvider()
            logger.info("✅ Market Data Provider: Angel One SmartAPI")
        elif mode in ["upstox", "upstox_api"]:
            _provider_instance = UpstoxMarketDataProvider()
            logger.info("Market Data Provider: Upstox API v2")
        elif mode in ["dhan", "dhanhq"]:
            _provider_instance = DhanMarketDataProvider()
            logger.info("Market Data Provider: DhanHQ API v2")
        elif mode == "real":
            _provider_instance = RealMarketDataProvider()
        else:
            _provider_instance = MockMarketDataProvider()
            logger.info("Market Data Provider: Mock (Development)")
    return _provider_instance
