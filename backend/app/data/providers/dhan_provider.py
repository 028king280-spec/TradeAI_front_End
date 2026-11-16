from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
import httpx
import pandas as pd
from app.data.providers.base import MarketDataProvider
from app.core.config import settings
from app.core.logging import logger

# Mapping common NSE equities to Dhan Security IDs (NSE_EQ)
DHAN_NSE_SECURITY_MAP = {
    "RELIANCE": "2885",
    "TCS": "11536",
    "INFY": "1594",
    "HDFCBANK": "1333",
    "ICICIBANK": "4963",
    "SBIN": "3045",
    "LT": "11483",
    "AXISBANK": "5900",
    "MARUTI": "10999",
    "ITC": "1660",
    "SUNPHARMA": "3351",
    "BHARTIARTL": "10604",
    "ADANIENT": "25",
    "M&M": "2031",
    "KOTAKBANK": "1922",
    "TATAMOTORS": "3456",
    "BAJFINANCE": "317",
    "NIFTY 50": "13",
    "BANK NIFTY": "25",
}


class DhanMarketDataProvider(MarketDataProvider):
    """
    DhanHQ API v2 Market Data Provider.
    Implements quotes, historical daily candles, and intraday candles
    using DhanHQ REST endpoints.
    """

    def __init__(self):
        self.client_id = settings.DHAN_CLIENT_ID
        self.access_token = settings.DHAN_ACCESS_TOKEN
        self.base_url = settings.DHAN_BASE_URL.rstrip("/")
        self.headers = {
            "client-id": self.client_id,
            "access-token": self.access_token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        self.timeout = httpx.Timeout(10.0, connect=5.0)

    def get_provider_name(self) -> str:
        return "dhan"

    def _get_sec_id(self, symbol: str) -> str:
        return DHAN_NSE_SECURITY_MAP.get(symbol.upper(), "2885")

    async def get_quote(self, symbol: str) -> Dict[str, Any]:
        if not self.access_token or not self.client_id:
            raise RuntimeError("DHAN_CLIENT_ID or DHAN_ACCESS_TOKEN is not configured in .env")

        sec_id = self._get_sec_id(symbol)
        url = f"{self.base_url}/marketfeed/quote"
        payload = {
            "NSE_EQ": [int(sec_id)]
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                res = await client.post(url, headers=self.headers, json=payload)
                res.raise_for_status()
                data = res.json().get("data", {}).get("NSE_EQ", {}).get(sec_id, {})

                ltp = float(data.get("last_price", 0.0))
                ohlc = data.get("ohlc", {})
                prev_close = float(ohlc.get("close", ltp))
                change = round(ltp - prev_close, 2)
                change_pct = round((change / prev_close) * 100, 2) if prev_close else 0.0

                return {
                    "symbol": symbol.upper(),
                    "companyName": data.get("company_name", symbol),
                    "exchange": "NSE",
                    "currentPrice": ltp,
                    "change": change,
                    "changePercent": change_pct,
                    "openPrice": float(ohlc.get("open", ltp)),
                    "dayHigh": float(ohlc.get("high", ltp)),
                    "dayLow": float(ohlc.get("low", ltp)),
                    "previousClose": prev_close,
                    "volume": float(data.get("volume", 0)),
                    "vwap": float(data.get("average_price", ltp)),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "dataStatus": "LIVE",
                }
        except Exception as e:
            logger.error(f"DhanHQ quote error for {symbol}: {e}")
            raise RuntimeError(f"DhanHQ API request failed: {e}")

    async def get_historical_candles(
        self,
        symbol: str,
        timeframe: str,
        from_date: datetime,
        to_date: datetime
    ) -> pd.DataFrame:
        if not self.access_token or not self.client_id:
            raise RuntimeError("DHAN_CLIENT_ID or DHAN_ACCESS_TOKEN is not configured in .env")

        sec_id = self._get_sec_id(symbol)
        url = f"{self.base_url}/charts/historical"
        payload = {
            "securityId": sec_id,
            "exchangeSegment": "NSE_EQ",
            "instrument": "EQUITY",
            "fromDate": from_date.strftime("%Y-%m-%d"),
            "toDate": to_date.strftime("%Y-%m-%d"),
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                res = await client.post(url, headers=self.headers, json=payload)
                res.raise_for_status()
                data = res.json().get("data", {})

                # Dhan returns { "open": [], "high": [], "low": [], "close": [], "volume": [], "timestamp": [] }
                opens = data.get("open", [])
                highs = data.get("high", [])
                lows = data.get("low", [])
                closes = data.get("close", [])
                volumes = data.get("volume", [])
                timestamps = data.get("timestamp", [])

                records = []
                for i in range(len(closes)):
                    records.append({
                        "timestamp": pd.to_datetime(timestamps[i], unit="s") if isinstance(timestamps[i], (int, float)) else pd.to_datetime(timestamps[i]),
                        "open": float(opens[i]),
                        "high": float(highs[i]),
                        "low": float(lows[i]),
                        "close": float(closes[i]),
                        "volume": float(volumes[i]),
                        "vwap": float((opens[i] + highs[i] + lows[i] + closes[i]) / 4),
                    })

                return pd.DataFrame(records)
        except Exception as e:
            logger.error(f"DhanHQ historical candles error for {symbol}: {e}")
            raise RuntimeError(f"DhanHQ historical candle request failed: {e}")

    async def get_intraday_candles(
        self,
        symbol: str,
        timeframe: str = "15m"
    ) -> pd.DataFrame:
        sec_id = self._get_sec_id(symbol)
        url = f"{self.base_url}/charts/intraday"
        # Dhan interval in minutes ("1", "5", "15", "25", "60")
        interval_min = timeframe.replace("m", "") if "m" in timeframe else "15"
        payload = {
            "securityId": sec_id,
            "exchangeSegment": "NSE_EQ",
            "instrument": "EQUITY",
            "interval": interval_min,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                res = await client.post(url, headers=self.headers, json=payload)
                res.raise_for_status()
                data = res.json().get("data", {})

                opens = data.get("open", [])
                highs = data.get("high", [])
                lows = data.get("low", [])
                closes = data.get("close", [])
                volumes = data.get("volume", [])
                timestamps = data.get("timestamp", [])

                records = []
                for i in range(len(closes)):
                    dt = pd.to_datetime(timestamps[i], unit="s") if isinstance(timestamps[i], (int, float)) else pd.to_datetime(timestamps[i])
                    records.append({
                        "timestamp": dt,
                        "time": dt.strftime("%H:%M"),
                        "open": float(opens[i]),
                        "high": float(highs[i]),
                        "low": float(lows[i]),
                        "close": float(closes[i]),
                        "volume": float(volumes[i]),
                        "vwap": float((opens[i] + highs[i] + lows[i] + closes[i]) / 4),
                    })
                return pd.DataFrame(records)
        except Exception as e:
            logger.warning(f"DhanHQ intraday candles error for {symbol}: {e}")
            empty_df = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume", "vwap"])
            empty_df.attrs.update({
                "dataStatus": "DATA_UNAVAILABLE",
                "feedStatus": "DATA_UNAVAILABLE",
                "provider": "dhan",
                "timeframe": timeframe,
                "is_mock": False,
                "is_synthetic": False,
                "degraded_reason": str(e),
            })
            return empty_df

    async def get_index_quote(self, index_symbol: str) -> Dict[str, Any]:
        indices = await self.get_all_indices()
        for idx in indices:
            if idx["symbol"].upper() == index_symbol.upper():
                return idx
        return indices[0]

    async def get_all_indices(self) -> List[Dict[str, Any]]:
        """Explicit unavailable index states — never return hardcoded synthetic prices."""
        return [
            {
                "symbol": sym,
                "name": label,
                "currentValue": 0.0,
                "change": 0.0,
                "changePercent": 0.0,
                "dayHigh": 0.0,
                "dayLow": 0.0,
                "trend": "Neutral",
                "sparkline": [],
                "volatilityStatus": "Unavailable",
                "dataStatus": "DATA_UNAVAILABLE",
                "feedStatus": "DATA_UNAVAILABLE",
                "provider": "dhan",
                "is_mock": False,
                "is_synthetic": False,
                "degradedReason": f"Dhan index snapshot unavailable for {sym}; synthetic prices disabled.",
            }
            for sym, label in [
                ("NIFTY 50", "Nifty 50 Index"),
                ("BANK NIFTY", "Nifty Bank Index"),
                ("FINNIFTY", "Nifty Financial Services"),
                ("INDIA VIX", "India Volatility Index"),
            ]
        ]

    async def get_sector_data(self) -> List[Dict[str, Any]]:
        """Sectoral data unavailable from Dhan REST API; never substitute static mock sectors."""
        return []

    async def get_market_breadth(self) -> Dict[str, Any]:
        return {
            "advancing": 0,
            "declining": 0,
            "unchanged": 0,
            "ratio": 0.0,
            "dataStatus": "DATA_UNAVAILABLE",
            "feedStatus": "DATA_UNAVAILABLE",
            "provider": "dhan",
            "is_mock": False,
            "is_synthetic": False,
            "degradedReason": "Market breadth feed unavailable from Dhan; synthetic data disabled.",
        }

    async def get_option_chain(
        self,
        symbol: str,
        expiry: Optional[str] = None
    ) -> Dict[str, Any]:
        return {"symbol": symbol, "expiry": expiry, "strikes": []}
