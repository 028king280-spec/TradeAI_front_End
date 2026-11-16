import asyncio
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
import httpx
import pandas as pd

from app.core.config import settings
from app.core.logging import logger
from app.data.providers.base import MarketDataProvider
from app.data.normalizer import MarketDataNormalizer
from app.data.market_calendar import MarketCalendar
from app.data.quality_validator import DataQualityEngine


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
    - Explicit UNAVAILABLE/DEGRADED states on auth/API failures (never substitutes mock data).
    """

    _RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

    def __init__(self):
        self.base_url = settings.UPSTOX_BASE_URL
        self.access_token = settings.UPSTOX_ACCESS_TOKEN or settings.UPSTOX_ANALYTICS_TOKEN
        self.client_id = settings.UPSTOX_CLIENT_ID
        self._is_live = bool(self.access_token)
        self._max_retries = 2
        self._retry_backoff_seconds = 0.25
        self.last_error: Optional[str] = None
        self._diagnostics: Dict[str, Any] = {}

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

    def _build_unavailable_quote(
        self,
        symbol: str,
        reason: str,
        retry_attempts: int = 0,
        http_status: Optional[int] = None,
    ) -> Dict[str, Any]:
        self.last_error = reason
        now_iso = MarketCalendar.now().isoformat()
        diag = {
            "symbol": symbol,
            "status": "UNAVAILABLE",
            "reason": reason,
            "retry_attempts": retry_attempts,
            "http_status": http_status,
        }
        self._diagnostics[f"quote:{symbol}"] = diag
        return {
            "symbol": symbol,
            "companyName": symbol,
            "exchange": "NSE",
            "instrument_key": self._get_instrument_key(symbol),
            "ltp": 0.0,
            "currentPrice": 0.0,
            "open": 0.0,
            "openPrice": 0.0,
            "high": 0.0,
            "dayHigh": 0.0,
            "low": 0.0,
            "dayLow": 0.0,
            "close": 0.0,
            "previousClose": 0.0,
            "change": 0.0,
            "changePercent": 0.0,
            "volume": 0,
            "vwap": 0.0,
            "timestamp": now_iso,
            "dataStatus": "UNAVAILABLE",
            "feedStatus": "DATA_UNAVAILABLE",
            "isTradeQualified": False,
            "is_mock": False,
            "is_synthetic": False,
            "provider": "upstox",
            "degradedReason": reason,
            "retryAttempts": retry_attempts,
            "httpStatus": http_status,
        }

    def _build_unavailable_candles_df(
        self,
        symbol: str,
        timeframe: str,
        reason: str,
        retry_attempts: int = 0,
        http_status: Optional[int] = None,
    ) -> pd.DataFrame:
        self.last_error = reason
        self._diagnostics[f"candles:{symbol}:{timeframe}"] = {
            "symbol": symbol,
            "timeframe": timeframe,
            "status": "DATA_UNAVAILABLE",
            "reason": reason,
            "retry_attempts": retry_attempts,
            "http_status": http_status,
        }
        empty_df = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume", "vwap"])
        empty_df.attrs.update({
            "dataStatus": "DATA_UNAVAILABLE",
            "feedStatus": "DATA_UNAVAILABLE",
            "provider": "upstox",
            "timeframe": timeframe,
            "is_mock": False,
            "is_synthetic": False,
            "degraded_reason": reason,
            "retry_attempts": retry_attempts,
            "http_status": http_status,
        })
        return empty_df

    async def get_quote(self, symbol: str) -> Dict[str, Any]:
        """
        Fetch quote from Upstox REST API v2: GET /market-quote/quotes.
        Never substitutes mock/synthetic quotes on failure.
        """
        clean_sym = symbol.upper().strip()
        instrument_key = self._get_instrument_key(clean_sym)

        if not self.is_authenticated:
            return self._build_unavailable_quote(
                clean_sym,
                reason="Upstox provider not authenticated; mock fallback disabled.",
            )

        last_reason = f"Upstox quote unavailable for {clean_sym}."
        last_status: Optional[int] = None
        retries_attempted = 0
        url = f"{self.base_url}/market-quote/quotes"
        params = {"instrument_key": instrument_key}

        for attempt in range(self._max_retries + 1):
            retries_attempted = attempt
            try:
                async with httpx.AsyncClient(timeout=8.0) as client:
                    res = await client.get(url, headers=self._get_headers(), params=params)
                    last_status = res.status_code
                    if res.status_code == 200:
                        data = res.json()
                        raw_data = data.get("data", {}) if isinstance(data, dict) else {}
                        quote_data = raw_data.get(instrument_key) or (next(iter(raw_data.values()), None) if isinstance(raw_data, dict) else None)
                        if quote_data:
                            normalized = MarketDataNormalizer.normalize_upstox_quote(clean_sym, quote_data)
                            normalized["dataStatus"] = "LIVE"
                            normalized["feedStatus"] = "VERIFIED_LIVE"
                            normalized["provider"] = "upstox"
                            normalized["is_mock"] = False
                            normalized["is_synthetic"] = False
                            return normalized
                        last_reason = f"Upstox returned empty quote payload for {clean_sym}."
                        break
                    last_reason = f"Upstox API quote returned HTTP {res.status_code} for {clean_sym}."
                    if res.status_code in self._RETRYABLE_STATUS_CODES and attempt < self._max_retries:
                        await asyncio.sleep(self._retry_backoff_seconds * (2 ** attempt))
                        continue
                    break
            except Exception as e:
                last_reason = f"Upstox quote error for {clean_sym}: {e}"
                logger.error(last_reason)
                if attempt < self._max_retries:
                    await asyncio.sleep(self._retry_backoff_seconds * (2 ** attempt))
                    continue
                break

        logger.warning(f"{last_reason} (retries={retries_attempted})")
        return self._build_unavailable_quote(
            clean_sym,
            reason=last_reason,
            retry_attempts=retries_attempted,
            http_status=last_status,
        )

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
        Returns explicit empty degraded DataFrame on failure/rate-limit/empty payload.
        """
        clean_sym = symbol.upper().strip()
        instrument_key = self._get_instrument_key(clean_sym)

        if not self.is_authenticated:
            return self._build_unavailable_candles_df(
                clean_sym,
                timeframe,
                reason="Upstox provider not authenticated; mock candles disabled.",
            )

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
        url = f"{self.base_url}/historical-candle/{instrument_key}/{interval}/{to_str}/{from_str}"

        last_reason = f"Upstox historical candles unavailable for {clean_sym} ({timeframe})."
        last_status: Optional[int] = None
        retries_attempted = 0

        for attempt in range(self._max_retries + 1):
            retries_attempted = attempt
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    res = await client.get(url, headers=self._get_headers())
                    last_status = res.status_code
                    if res.status_code == 200:
                        payload = res.json()
                        candles = payload.get("data", {}).get("candles", []) if isinstance(payload, dict) else []
                        if candles:
                            # Upstox returns list of [timestamp, open, high, low, close, volume, oi]
                            df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume", "oi"])
                            df["timestamp"] = pd.to_datetime(df["timestamp"])
                            df = df.sort_values("timestamp").reset_index(drop=True)
                            df["vwap"] = ((df["high"] + df["low"] + df["close"]) / 3).round(2)
                            out = df[["timestamp", "open", "high", "low", "close", "volume", "vwap"]].copy()
                            out.attrs.update({
                                "dataStatus": "LIVE",
                                "provider": "upstox",
                                "timeframe": timeframe,
                                "is_mock": False,
                                "is_synthetic": False,
                            })
                            DataQualityEngine.validate_ohlc(out, timeframe=timeframe)
                            return out
                        last_reason = f"Upstox returned 0 historical candles for {clean_sym} ({timeframe})."
                        break
                    last_reason = f"Upstox historical candles HTTP {res.status_code} for {clean_sym} ({timeframe})."
                    if res.status_code in self._RETRYABLE_STATUS_CODES and attempt < self._max_retries:
                        await asyncio.sleep(self._retry_backoff_seconds * (2 ** attempt))
                        continue
                    break
            except Exception as e:
                last_reason = f"Upstox historical candles error for {clean_sym}: {e}"
                logger.error(last_reason)
                if attempt < self._max_retries:
                    await asyncio.sleep(self._retry_backoff_seconds * (2 ** attempt))
                    continue
                break

        return self._build_unavailable_candles_df(
            clean_sym,
            timeframe,
            reason=last_reason,
            retry_attempts=retries_attempted,
            http_status=last_status,
        )

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
            return self._build_unavailable_candles_df(
                clean_sym,
                timeframe,
                reason="Upstox provider not authenticated; mock intraday candles disabled.",
            )

        tf_map = {"1m": "1minute", "5m": "1minute", "15m": "30minute", "30m": "30minute"}
        interval = tf_map.get(timeframe, "1minute")
        url = f"{self.base_url}/historical-candle/intraday/{instrument_key}/{interval}"

        last_reason = f"Upstox intraday candles unavailable for {clean_sym} ({timeframe})."
        last_status: Optional[int] = None
        retries_attempted = 0

        for attempt in range(self._max_retries + 1):
            retries_attempted = attempt
            try:
                async with httpx.AsyncClient(timeout=8.0) as client:
                    res = await client.get(url, headers=self._get_headers())
                    last_status = res.status_code
                    if res.status_code == 200:
                        payload = res.json()
                        candles = payload.get("data", {}).get("candles", []) if isinstance(payload, dict) else []
                        if candles:
                            df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume", "oi"])
                            df["timestamp"] = pd.to_datetime(df["timestamp"])
                            df = df.sort_values("timestamp").reset_index(drop=True)
                            df["vwap"] = ((df["high"] + df["low"] + df["close"]) / 3).round(2)
                            out = df[["timestamp", "open", "high", "low", "close", "volume", "vwap"]].copy()
                            out.attrs.update({
                                "dataStatus": "LIVE",
                                "provider": "upstox",
                                "timeframe": timeframe,
                                "is_mock": False,
                                "is_synthetic": False,
                            })
                            DataQualityEngine.validate_ohlc(out, timeframe=timeframe)
                            return out
                        last_reason = f"Upstox returned 0 intraday candles for {clean_sym} ({timeframe})."
                        break
                    last_reason = f"Upstox intraday candles HTTP {res.status_code} for {clean_sym} ({timeframe})."
                    if res.status_code in self._RETRYABLE_STATUS_CODES and attempt < self._max_retries:
                        await asyncio.sleep(self._retry_backoff_seconds * (2 ** attempt))
                        continue
                    break
            except Exception as e:
                last_reason = f"Upstox intraday candles error for {clean_sym}: {e}"
                logger.error(last_reason)
                if attempt < self._max_retries:
                    await asyncio.sleep(self._retry_backoff_seconds * (2 ** attempt))
                    continue
                break

        return self._build_unavailable_candles_df(
            clean_sym,
            timeframe,
            reason=last_reason,
            retry_attempts=retries_attempted,
            http_status=last_status,
        )

    async def get_index_quote(self, index_symbol: str) -> Dict[str, Any]:
        return await self.get_quote(index_symbol)

    async def get_all_indices(self) -> List[Dict[str, Any]]:
        """
        Fetch quotes for all primary benchmark indices without mock substitution.
        """
        primary_indices = ["NIFTY 50", "BANK NIFTY", "FINNIFTY", "INDIA VIX"]
        tasks = [self.get_quote(idx) for idx in primary_indices]
        quotes = await asyncio.gather(*tasks, return_exceptions=True)

        results = []
        for idx_name, q in zip(primary_indices, quotes):
            if isinstance(q, dict) and q.get("dataStatus") == "LIVE" and float(q.get("ltp") or 0) > 0:
                results.append({
                    "symbol": idx_name,
                    "name": idx_name,
                    "currentValue": float(q["ltp"]),
                    "change": float(q.get("change", 0.0)),
                    "changePercent": float(q.get("changePercent", 0.0)),
                    "dayHigh": float(q.get("high", q["ltp"])),
                    "dayLow": float(q.get("low", q["ltp"])),
                    "trend": "Bullish" if float(q.get("change", 0.0)) >= 0 else "Bearish",
                    "sparkline": [q["low"], q["open"], q["ltp"], q["high"]],
                    "volatilityStatus": "Low" if idx_name == "INDIA VIX" and float(q["ltp"]) < 13 else "Moderate",
                    "dataStatus": "LIVE",
                    "provider": "upstox",
                    "is_mock": False,
                })
            else:
                q_dict = q if isinstance(q, dict) else {}
                results.append({
                    "symbol": idx_name,
                    "name": idx_name,
                    "currentValue": 0.0,
                    "change": 0.0,
                    "changePercent": 0.0,
                    "dayHigh": 0.0,
                    "dayLow": 0.0,
                    "trend": "Neutral",
                    "sparkline": [],
                    "volatilityStatus": "Unavailable",
                    "dataStatus": q_dict.get("dataStatus", "UNAVAILABLE"),
                    "feedStatus": q_dict.get("feedStatus", "DATA_UNAVAILABLE"),
                    "provider": "upstox",
                    "is_mock": False,
                    "is_synthetic": False,
                    "degradedReason": q_dict.get("degradedReason", f"Quote unavailable for {idx_name}"),
                })
        return results

    async def get_sector_data(self) -> List[Dict[str, Any]]:
        """Sectoral breadth feed not available via Upstox quote endpoint; never substitute mock data."""
        return []

    async def get_market_breadth(self) -> Dict[str, Any]:
        """Market breadth feed unavailable via Upstox; never substitute mock data."""
        return {
            "advancing": 0,
            "declining": 0,
            "unchanged": 0,
            "ratio": 0.0,
            "dataStatus": "UNAVAILABLE",
            "feedStatus": "DATA_UNAVAILABLE",
            "is_mock": False,
            "is_synthetic": False,
            "provider": "upstox",
            "degradedReason": "Market breadth feed unavailable from Upstox; mock fallback disabled.",
        }

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
