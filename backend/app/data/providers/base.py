from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Dict, Any, Optional
import pandas as pd


class MarketDataProvider(ABC):
    """
    Abstract interface for Indian Market Data Providers (NSE / BSE).
    Enables switching seamlessly between MockMarketDataProvider and RealMarketDataProvider.
    """

    @abstractmethod
    async def get_quote(self, symbol: str) -> Dict[str, Any]:
        """
        Fetch real-time or latest quote for a stock:
        LTP, change, changePercent, high, low, open, close, volume, vwap.
        """
        pass

    @abstractmethod
    async def get_historical_candles(
        self,
        symbol: str,
        timeframe: str,
        from_date: datetime,
        to_date: datetime
    ) -> pd.DataFrame:
        """
        Fetch historical OHLCV data as pandas DataFrame:
        Columns: ['timestamp', 'open', 'high', 'low', 'close', 'volume', 'vwap']
        """
        pass

    @abstractmethod
    async def get_intraday_candles(
        self,
        symbol: str,
        timeframe: str = "15m"
    ) -> pd.DataFrame:
        """
        Fetch today's intraday OHLCV candles as pandas DataFrame.
        """
        pass

    @abstractmethod
    async def get_index_quote(self, index_symbol: str) -> Dict[str, Any]:
        """
        Fetch quote for index (e.g. NIFTY 50, BANK NIFTY, FINNIFTY, INDIA VIX).
        """
        pass

    @abstractmethod
    async def get_all_indices(self) -> List[Dict[str, Any]]:
        """
        Fetch all benchmark indices.
        """
        pass

    @abstractmethod
    async def get_sector_data(self) -> List[Dict[str, Any]]:
        """
        Fetch sectoral performance heatmap data.
        """
        pass

    @abstractmethod
    async def get_market_breadth(self) -> Dict[str, Any]:
        """
        Fetch market breadth (advances, declines, ratio).
        """
        pass

    @abstractmethod
    async def get_option_chain(
        self,
        symbol: str,
        expiry: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Fetch option chain with OI, Change in OI, IV, and Greeks where available.
        """
        pass

    @abstractmethod
    def get_provider_name(self) -> str:
        """
        Returns 'mock' or real provider identifier.
        """
        pass
