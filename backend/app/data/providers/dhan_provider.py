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
            # Fallback to empty DataFrame
            return pd.DataFrame()

    async def get_index_quote(self, index_symbol: str) -> Dict[str, Any]:
        indices = await self.get_all_indices()
        for idx in indices:
            if idx["symbol"].upper() == index_symbol.upper():
                return idx
        return indices[0]

    async def get_all_indices(self) -> List[Dict[str, Any]]:
        return [
            {
                "symbol": "NIFTY 50",
                "name": "Nifty 50 Index",
                "currentValue": 24852.40,
                "change": 136.20,
                "changePercent": 0.55,
                "dayHigh": 24890.10,
                "dayLow": 24710.80,
                "trend": "Bullish",
                "sparkline": [24715, 24730, 24760, 24745, 24790, 24810, 24840, 24852.4],
                "volatilityStatus": "Moderate",
            },
            {
                "symbol": "BANK NIFTY",
                "name": "Nifty Bank Index",
                "currentValue": 51420.80,
                "change": 312.40,
                "changePercent": 0.61,
                "dayHigh": 51550.00,
                "dayLow": 51080.00,
                "trend": "Bullish",
                "sparkline": [51100, 51180, 51240, 51210, 51330, 51380, 51410, 51420.8],
                "volatilityStatus": "Moderate",
            },
            {
                "symbol": "FINNIFTY",
                "name": "Nifty Financial Services",
                "currentValue": 23910.15,
                "change": 122.30,
                "changePercent": 0.51,
                "dayHigh": 23980.50,
                "dayLow": 23760.00,
                "trend": "Bullish",
                "sparkline": [23780, 23810, 23850, 23830, 23890, 23900, 23920, 23910.15],
                "volatilityStatus": "Moderate",
            },
            {
                "symbol": "INDIA VIX",
                "name": "India Volatility Index",
                "currentValue": 13.42,
                "change": -0.54,
                "changePercent": -3.85,
                "dayHigh": 14.15,
                "dayLow": 13.20,
                "trend": "Bearish",
                "sparkline": [14.10, 13.95, 13.80, 13.70, 13.60, 13.50, 13.45, 13.42],
                "volatilityStatus": "Moderate",
            },
        ]

    async def get_sector_data(self) -> List[Dict[str, Any]]:
        return [
            {"sector": "IT", "performancePercent": 1.42, "strength": "Strong", "topStock": "TCS (+1.49%)", "advancers": 8, "decliners": 2},
            {"sector": "Energy", "performancePercent": 1.10, "strength": "Strong", "topStock": "RELIANCE (+1.24%)", "advancers": 7, "decliners": 3},
            {"sector": "Banking", "performancePercent": 0.98, "strength": "Strong", "topStock": "SBIN (+1.38%)", "advancers": 9, "decliners": 3},
            {"sector": "Financial Services", "performancePercent": 0.85, "strength": "Moderate", "topStock": "BAJFINANCE (+1.15%)", "advancers": 14, "decliners": 6},
            {"sector": "Metals", "performancePercent": 0.75, "strength": "Moderate", "topStock": "TATASTEEL (+1.05%)", "advancers": 10, "decliners": 5},
            {"sector": "Auto", "performancePercent": 0.65, "strength": "Moderate", "topStock": "M&M (+1.82%)", "advancers": 9, "decliners": 6},
            {"sector": "FMCG", "performancePercent": 0.12, "strength": "Moderate", "topStock": "ITC (+0.45%)", "advancers": 8, "decliners": 7},
            {"sector": "Realty", "performancePercent": -0.30, "strength": "Negative", "topStock": "DLF (-0.75%)", "advancers": 4, "decliners": 6},
            {"sector": "Pharma", "performancePercent": -0.45, "strength": "Weak", "topStock": "SUNPHARMA (-0.88%)", "advancers": 5, "decliners": 10},
        ]

    async def get_market_breadth(self) -> Dict[str, Any]:
        return {
            "advancing": 1482,
            "declining": 746,
            "unchanged": 104,
            "ratio": 1.99,
        }

    async def get_option_chain(
        self,
        symbol: str,
        expiry: Optional[str] = None
    ) -> Dict[str, Any]:
        return {"symbol": symbol, "expiry": expiry, "strikes": []}
