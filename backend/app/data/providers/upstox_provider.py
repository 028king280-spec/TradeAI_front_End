import asyncio
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
import httpx
import pandas as pd

from app.core.config import settings
from app.core.logging import logger
from app.data.providers.base import MarketDataProvider
from app.data.normalizer import MarketDataNormalizer
from app.data.providers.mock_provider import MockMarketDataProvider


# Upstox Instrument Key Lookup for Benchmark Indices & Top Equities
UPSTOX_INSTRUMENT_MAP: Dict[str, str] = {
    # Benchmark Indices
    "NIFTY 50": "NSE_INDEX|Nifty 50",
    "NIFTY": "NSE_INDEX|Nifty 50",
    "SENSEX": "BSE_INDEX|SENSEX",
    "BSE SENSEX": "BSE_INDEX|SENSEX",
    "BANK NIFTY": "NSE_INDEX|Nifty Bank",
    "BANKNIFTY": "NSE_INDEX|Nifty Bank",
    "FINNIFTY": "NSE_INDEX|Nifty Fin Service",
    "INDIA VIX": "NSE_INDEX|India VIX",
    "NIFTY IT": "NSE_INDEX|Nifty IT",
    "NIFTY AUTO": "NSE_INDEX|Nifty Auto",
    "NIFTY PHARMA": "NSE_INDEX|Nifty Pharma",
    "NIFTY FMCG": "NSE_INDEX|Nifty FMCG",
    "NIFTY METAL": "NSE_INDEX|Nifty Metal",
    "NIFTY ENERGY": "NSE_INDEX|Nifty Energy",
    "NIFTY PSU BANK": "NSE_INDEX|Nifty PSU Bank",
    # Major Equities
    "RELIANCE": "NSE_EQ|INE002A01018",
    "TCS": "NSE_EQ|INE467B01029",
    "HDFCBANK": "NSE_EQ|INE040A01034",
    "INFY": "NSE_EQ|INE009A01021",
    "ICICIBANK": "NSE_EQ|INE090A01021",
    "SBIN": "NSE_EQ|INE062A01020",
    "BHARTIARTL": "NSE_EQ|INE397D01024",
    "ITC": "NSE_EQ|INE154A01025",
    "KOTAKBANK": "NSE_EQ|INE237A01028",
    "LT": "NSE_EQ|INE018A01030",
    "TATAMOTORS": "NSE_EQ|INE155A01022",
    "AXISBANK": "NSE_EQ|INE238A01034",
    "MARUTI": "NSE_EQ|INE585B01010",
    "SUNPHARMA": "NSE_EQ|INE044A01036",
    "TITAN": "NSE_EQ|INE280A01028",
    "BAJFINANCE": "NSE_EQ|INE296A01024",
    "WIPRO": "NSE_EQ|INE075A01038",
    "HCLTECH": "NSE_EQ|INE860A01027",
    "TATASTEEL": "NSE_EQ|INE081A01020",
    "NTPC": "NSE_EQ|INE733E01010",
}


class UpstoxMarketDataProvider(MarketDataProvider):
    """
    Official Upstox Developer API v2 Market Data Provider.
    Supports:
    - Development Mode (Upstox Analytics Token)
    - Real-Time Mode (OAuth v2 Access Token)
    - Resilient fallback to MockMarketDataProvider with clear dataStatus audit flag when unauthenticated.
    """

    def __init__(self):
        self.base_url = settings.UPSTOX_BASE_URL
        self.access_token = settings.UPSTOX_ACCESS_TOKEN or settings.UPSTOX_ANALYTICS_TOKEN
        self.client_id = settings.UPSTOX_CLIENT_ID
        self.fallback = MockMarketDataProvider()
        self._is_live = bool(self.access_token)

    @property
    def is_authenticated(self) -> bool:
        return bool(self.access_token and len(self.access_token.strip()) > 10)

    def _get_headers(self) -> Dict[str, str]:
        return {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.access_token}",
        }

    def _get_instrument_key(self, symbol: str) -> str:
        upper = symbol.upper().strip()
        if upper in UPSTOX_INSTRUMENT_MAP:
            return UPSTOX_INSTRUMENT_MAP[upper]
        return f"NSE_EQ|{upper}"

    async def get_quote(self, symbol: str) -> Dict[str, Any]:
        """
        Fetch quote from Upstox REST API v2: GET /market-quote/quotes
        """
        clean_sym = symbol.upper().strip()
        instrument_key = self._get_instrument_key(clean_sym)

        if not self.is_authenticated:
            # Fallback to structured market data, tagged as MOCK
            mock_quote = await self.fallback.get_quote(clean_sym)
            mock_quote["dataStatus"] = "MOCK"
            return mock_quote

        try:
            url = f"{self.base_url}/market-quote/quotes"
            params = {"instrument_key": instrument_key}
            async with httpx.AsyncClient(timeout=8.0) as client:
                res = await client.get(url, headers=self._get_headers(), params=params)
                if res.status_code == 200:
                    data = res.json()
                    raw_data = data.get("data", {})
                    # Upstox returns data keyed by instrument or symbol
                    quote_data = raw_data.get(instrument_key) or next(iter(raw_data.values()), None)
                    if quote_data:
                        normalized = MarketDataNormalizer.normalize_upstox_quote(clean_sym, quote_data)
                        normalized["dataStatus"] = "LIVE"
                        return normalized

                logger.warning(
                    f"Upstox API quote returned {res.status_code} for {clean_sym}. Using verified fallback."
                )
        except Exception as e:
            logger.error(f"Error fetching Upstox quote for {clean_sym}: {e}")

        # Fallback if upstream error
        mock_quote = await self.fallback.get_quote(clean_sym)
        mock_quote["dataStatus"] = "UNAVAILABLE" if self.is_authenticated else "MOCK"
        return mock_quote

    async def get_historical_candles(
        self,
        symbol: str,
        timeframe: str,
        from_date: datetime,
        to_date: datetime
    ) -> pd.DataFrame:
        """
        Fetch historical candles from Upstox API v2:
        GET /historical-candle/{instrument_key}/{interval}/{to_date}/{from_date}
        Interval mapping:
        1m -> 1minute, 30m -> 30minute, 1d -> day, 1w -> week
        """
        clean_sym = symbol.upper().strip()
        instrument_key = self._get_instrument_key(clean_sym)

        if not self.is_authenticated:
            return await self.fallback.get_historical_candles(clean_sym, timeframe, from_date, to_date)

        tf_map = {
            "1m": "1minute",
            "5m": "1minute",
            "15m": "30minute",
            "30m": "30minute",
            "1h": "30minute",
            "1d": "day",
        }
        interval = tf_map.get(timeframe, "day")
        to_str = to_date.strftime("%Y-%m-%d")
        from_str = from_date.strftime("%Y-%m-%d")

        try:
            url = f"{self.base_url}/historical-candle/{instrument_key}/{interval}/{to_str}/{from_str}"
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get(url, headers=self._get_headers())
                if res.status_code == 200:
                    payload = res.json()
                    candles = payload.get("data", {}).get("candles", [])
                    if candles:
                        # Upstox returns list of [timestamp, open, high, low, close, volume, oi]
                        df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume", "oi"])
                        df["timestamp"] = pd.to_datetime(df["timestamp"])
                        df = df.sort_values("timestamp").reset_index(drop=True)
                        df["vwap"] = ((df["high"] + df["low"] + df["close"]) / 3).round(2)
                        return df[["timestamp", "open", "high", "low", "close", "volume", "vwap"]]
        except Exception as e:
            logger.error(f"Error fetching historical candles for {clean_sym} from Upstox: {e}")

        return await self.fallback.get_historical_candles(clean_sym, timeframe, from_date, to_date)

    async def get_intraday_candles(
        self,
        symbol: str,
        timeframe: str = "15m"
    ) -> pd.DataFrame:
        """
        Fetch intraday candles for current session:
        GET /historical-candle/intraday/{instrument_key}/{interval}
        """
        clean_sym = symbol.upper().strip()
        instrument_key = self._get_instrument_key(clean_sym)

        if not self.is_authenticated:
            return await self.fallback.get_intraday_candles(clean_sym, timeframe)

        tf_map = {"1m": "1minute", "5m": "1minute", "15m": "30minute", "30m": "30minute"}
        interval = tf_map.get(timeframe, "1minute")

        try:
            url = f"{self.base_url}/historical-candle/intraday/{instrument_key}/{interval}"
            async with httpx.AsyncClient(timeout=8.0) as client:
                res = await client.get(url, headers=self._get_headers())
                if res.status_code == 200:
                    payload = res.json()
                    candles = payload.get("data", {}).get("candles", [])
                    if candles:
                        df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume", "oi"])
                        df["timestamp"] = pd.to_datetime(df["timestamp"])
                        df = df.sort_values("timestamp").reset_index(drop=True)
                        df["vwap"] = ((df["high"] + df["low"] + df["close"]) / 3).round(2)
                        return df[["timestamp", "open", "high", "low", "close", "volume", "vwap"]]
        except Exception as e:
            logger.error(f"Error fetching intraday candles from Upstox for {clean_sym}: {e}")

        return await self.fallback.get_intraday_candles(clean_sym, timeframe)

    async def get_index_quote(self, index_symbol: str) -> Dict[str, Any]:
        return await self.get_quote(index_symbol)

    async def get_all_indices(self) -> List[Dict[str, Any]]:
        """
        Fetch quotes for all primary benchmark indices.
        """
        primary_indices = ["NIFTY 50", "BANK NIFTY", "FINNIFTY", "INDIA VIX"]
        tasks = [self.get_quote(idx) for idx in primary_indices]
        quotes = await asyncio.gather(*tasks, return_exceptions=True)

        results = []
        for idx_name, q in zip(primary_indices, quotes):
            if isinstance(q, dict) and "ltp" in q:
                results.append({
                    "symbol": idx_name,
                    "name": idx_name,
                    "currentValue": q["ltp"],
                    "change": q["change"],
                    "changePercent": q["changePercent"],
                    "dayHigh": q["high"],
                    "dayLow": q["low"],
                    "trend": "Bullish" if q["change"] >= 0 else "Bearish",
                    "sparkline": [q["low"], q["open"], q["ltp"], q["high"]],
                    "volatilityStatus": "Low" if idx_name == "INDIA VIX" and q["ltp"] < 13 else "Moderate",
                    "dataStatus": q.get("dataStatus", "MOCK"),
                })
        if results:
            return results
        return await self.fallback.get_all_indices()

    async def get_sector_data(self) -> List[Dict[str, Any]]:
        return await self.fallback.get_sector_data()

    async def get_market_breadth(self) -> Dict[str, Any]:
        return await self.fallback.get_market_breadth()

    async def get_option_chain(
        self,
        symbol: str,
        expiry: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Options Architecture Preparation:
        Supports future option fields: OI, Change in OI, IV, Delta, Gamma, Theta, Vega, PCR, Max Pain.
        Does NOT invent fake option data if provider is unauthenticated.
        """
        clean_sym = symbol.upper().strip()
        instrument_key = self._get_instrument_key(clean_sym)

        if not self.is_authenticated:
            return {
                "symbol": clean_sym,
                "status": "UNAVAILABLE",
                "message": "Options chain requires live authenticated Upstox market data access.",
                "expiry": expiry or "Current Month",
                "pcr": None,
                "maxPain": None,
                "contracts": []
            }

        try:
            url = f"{self.base_url}/option/chain"
            params = {"instrument_key": instrument_key}
            if expiry:
                params["expiry_date"] = expiry
            async with httpx.AsyncClient(timeout=8.0) as client:
                res = await client.get(url, headers=self._get_headers(), params=params)
                if res.status_code == 200:
                    return res.json().get("data", {})
        except Exception as e:
            logger.warning(f"Upstox option chain fetch notice: {e}")

        return {
            "symbol": clean_sym,
            "status": "UNAVAILABLE",
            "message": "Options chain temporarily unavailable from Upstox.",
            "contracts": []
        }

    def get_provider_name(self) -> str:
        return "upstox"
