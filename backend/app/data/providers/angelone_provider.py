"""
Angel One SmartAPI v2 Market Data Provider.
Full integration with SmartAPI REST endpoints:
- TOTP-based Login & Session Management
- Real-time Market Quotes (LTP, Full Quote)
- Historical & Intraday OHLCV Candles
- Option Chain with Greeks
- Instrument Token Resolution via OpenAPI scrip master
"""

import asyncio
import hashlib
import time
import struct
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
import httpx
import pandas as pd

from app.core.config import settings
from app.core.logging import logger
from app.core.cache import CacheService
from app.data.providers.base import MarketDataProvider
from app.data.normalizer import MarketDataNormalizer
from app.data.providers.mock_provider import MockMarketDataProvider


# ============================================================
# TOTP Generator (RFC 6238 - No external dependency)
# ============================================================
def generate_totp(secret: str, period: int = 30, digits: int = 6) -> str:
    """
    Generates a TOTP code from a base32-encoded secret.
    Compatible with Angel One SmartAPI TOTP login.
    """
    import base64
    import hmac

    # Decode base32 secret
    missing_padding = len(secret) % 8
    if missing_padding:
        secret += "=" * (8 - missing_padding)
    key = base64.b32decode(secret.upper())

    # Time counter
    counter = int(time.time()) // period
    counter_bytes = struct.pack(">Q", counter)

    # HMAC-SHA1
    hmac_digest = hmac.new(key, counter_bytes, hashlib.sha1).digest()

    # Dynamic truncation
    offset = hmac_digest[-1] & 0x0F
    code = struct.unpack(">I", hmac_digest[offset:offset + 4])[0] & 0x7FFFFFFF
    otp = code % (10 ** digits)
    return str(otp).zfill(digits)


# ============================================================
# Angel One Instrument Key Mapping (NSE segment tokens)
# ============================================================
ANGELONE_TOKEN_MAP: Dict[str, Dict[str, str]] = {
    # Benchmark Indices
    "NIFTY 50": {"token": "99926000", "exchange": "NSE", "symbol_token": "99926000", "tradingsymbol": "NIFTY"},
    "NIFTY": {"token": "99926000", "exchange": "NSE", "symbol_token": "99926000", "tradingsymbol": "NIFTY"},
    "SENSEX": {"token": "99919000", "exchange": "BSE", "symbol_token": "99919000", "tradingsymbol": "SENSEX"},
    "BSE SENSEX": {"token": "99919000", "exchange": "BSE", "symbol_token": "99919000", "tradingsymbol": "SENSEX"},
    "BANK NIFTY": {"token": "99926009", "exchange": "NSE", "symbol_token": "99926009", "tradingsymbol": "BANKNIFTY"},
    "BANKNIFTY": {"token": "99926009", "exchange": "NSE", "symbol_token": "99926009", "tradingsymbol": "BANKNIFTY"},
    "FINNIFTY": {"token": "99926037", "exchange": "NSE", "symbol_token": "99926037", "tradingsymbol": "FINNIFTY"},
    "INDIA VIX": {"token": "99926004", "exchange": "NSE", "symbol_token": "99926004", "tradingsymbol": "INDIAVIX"},
    "NIFTY IT": {"token": "99926013", "exchange": "NSE", "symbol_token": "99926013", "tradingsymbol": "NIFTYIT"},
    "NIFTY AUTO": {"token": "99926023", "exchange": "NSE", "symbol_token": "99926023", "tradingsymbol": "NIFTYAUTO"},
    "NIFTY PHARMA": {"token": "99926014", "exchange": "NSE", "symbol_token": "99926014", "tradingsymbol": "NIFTYPHARMA"},
    "NIFTY FMCG": {"token": "99926020", "exchange": "NSE", "symbol_token": "99926020", "tradingsymbol": "NIFTYFMCG"},
    "NIFTY METAL": {"token": "99926017", "exchange": "NSE", "symbol_token": "99926017", "tradingsymbol": "NIFTYMETAL"},
    "NIFTY ENERGY": {"token": "99926022", "exchange": "NSE", "symbol_token": "99926022", "tradingsymbol": "NIFTYENERGY"},
    "NIFTY PSU BANK": {"token": "99926026", "exchange": "NSE", "symbol_token": "99926026", "tradingsymbol": "NIFTYPSUBANK"},
    # Major Equities (NSE symbol tokens)
    "RELIANCE": {"token": "2885", "exchange": "NSE", "symbol_token": "2885", "tradingsymbol": "RELIANCE-EQ"},
    "TCS": {"token": "11536", "exchange": "NSE", "symbol_token": "11536", "tradingsymbol": "TCS-EQ"},
    "HDFCBANK": {"token": "1333", "exchange": "NSE", "symbol_token": "1333", "tradingsymbol": "HDFCBANK-EQ"},
    "INFY": {"token": "1594", "exchange": "NSE", "symbol_token": "1594", "tradingsymbol": "INFY-EQ"},
    "ICICIBANK": {"token": "4963", "exchange": "NSE", "symbol_token": "4963", "tradingsymbol": "ICICIBANK-EQ"},
    "SBIN": {"token": "3045", "exchange": "NSE", "symbol_token": "3045", "tradingsymbol": "SBIN-EQ"},
    "BHARTIARTL": {"token": "10604", "exchange": "NSE", "symbol_token": "10604", "tradingsymbol": "BHARTIARTL-EQ"},
    "ITC": {"token": "1660", "exchange": "NSE", "symbol_token": "1660", "tradingsymbol": "ITC-EQ"},
    "KOTAKBANK": {"token": "1922", "exchange": "NSE", "symbol_token": "1922", "tradingsymbol": "KOTAKBANK-EQ"},
    "LT": {"token": "11483", "exchange": "NSE", "symbol_token": "11483", "tradingsymbol": "LT-EQ"},
    "TATAMOTORS": {"token": "3456", "exchange": "NSE", "symbol_token": "3456", "tradingsymbol": "TATAMOTORS-EQ"},
    "AXISBANK": {"token": "5900", "exchange": "NSE", "symbol_token": "5900", "tradingsymbol": "AXISBANK-EQ"},
    "MARUTI": {"token": "10999", "exchange": "NSE", "symbol_token": "10999", "tradingsymbol": "MARUTI-EQ"},
    "SUNPHARMA": {"token": "3351", "exchange": "NSE", "symbol_token": "3351", "tradingsymbol": "SUNPHARMA-EQ"},
    "TITAN": {"token": "3506", "exchange": "NSE", "symbol_token": "3506", "tradingsymbol": "TITAN-EQ"},
    "BAJFINANCE": {"token": "317", "exchange": "NSE", "symbol_token": "317", "tradingsymbol": "BAJFINANCE-EQ"},
    "WIPRO": {"token": "3787", "exchange": "NSE", "symbol_token": "3787", "tradingsymbol": "WIPRO-EQ"},
    "HCLTECH": {"token": "7229", "exchange": "NSE", "symbol_token": "7229", "tradingsymbol": "HCLTECH-EQ"},
    "TATASTEEL": {"token": "3499", "exchange": "NSE", "symbol_token": "3499", "tradingsymbol": "TATASTEEL-EQ"},
    "NTPC": {"token": "11630", "exchange": "NSE", "symbol_token": "11630", "tradingsymbol": "NTPC-EQ"},
    "ADANIENT": {"token": "25", "exchange": "NSE", "symbol_token": "25", "tradingsymbol": "ADANIENT-EQ"},
    "M&M": {"token": "2031", "exchange": "NSE", "symbol_token": "2031", "tradingsymbol": "M&M-EQ"},
    "HINDUNILVR": {"token": "1394", "exchange": "NSE", "symbol_token": "1394", "tradingsymbol": "HINDUNILVR-EQ"},
    "POWERGRID": {"token": "14977", "exchange": "NSE", "symbol_token": "14977", "tradingsymbol": "POWERGRID-EQ"},
    "COALINDIA": {"token": "20374", "exchange": "NSE", "symbol_token": "20374", "tradingsymbol": "COALINDIA-EQ"},
}


class AngelOneMarketDataProvider(MarketDataProvider):
    """
    Angel One SmartAPI v2 Market Data Provider.
    
    Supports:
    - TOTP-based automated login (no manual OTP required)
    - Real-time LTP, Full Quote, Snap Quote
    - Historical & Intraday OHLCV Candles  
    - Option Chain with OI, IV, Greeks
    - Resilient fallback to MockMarketDataProvider
    
    API Docs: https://smartapi.angelone.in/docs
    """

    def __init__(self):
        self.base_url = settings.ANGELONE_BASE_URL.rstrip("/")
        self.api_key = settings.ANGELONE_API_KEY
        self.client_code = settings.ANGELONE_CLIENT_CODE
        self.pin = settings.ANGELONE_PIN
        self.totp_secret = settings.ANGELONE_TOTP_SECRET
        self.ws_url = settings.ANGELONE_WS_URL

        # Session state
        self._jwt_token: Optional[str] = None
        self._refresh_token: Optional[str] = None
        self._feed_token: Optional[str] = None
        self._login_time: Optional[float] = None
        self._is_logged_in = False

        self.fallback = MockMarketDataProvider()

    @property
    def is_authenticated(self) -> bool:
        if not self._is_logged_in or not self._jwt_token:
            return False
        # Angel One tokens typically expire after 6 hours
        if self._login_time and (time.time() - self._login_time) > 18000:
            return False
        return True

    def _get_headers(self) -> Dict[str, str]:
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-UserType": "USER",
            "X-SourceID": "WEB",
            "X-ClientLocalIP": "127.0.0.1",
            "X-ClientPublicIP": "223.229.197.95",
            "X-MACAddress": "00:00:00:00:00:00",
            "X-PrivateKey": self.api_key,
            "Authorization": f"Bearer {self._jwt_token}" if self._jwt_token else "",
        }

    async def login(self) -> bool:
        """
        Perform TOTP-based login to Angel One SmartAPI.
        Returns True on success.
        """
        if not self.client_code or not self.pin or not self.totp_secret:
            logger.warning("Angel One credentials (CLIENT_CODE, PIN, TOTP_SECRET) not configured.")
            return False

        try:
            totp = generate_totp(self.totp_secret)
            url = f"{self.base_url}/rest/auth/angelbroking/user/v1/loginByPassword"
            payload = {
                "clientcode": self.client_code,
                "password": self.pin,
                "totp": totp,
            }

            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(url, json=payload, headers=self._get_headers())
                data = res.json()

                if data.get("status") and data.get("data"):
                    session_data = data["data"]
                    self._jwt_token = session_data.get("jwtToken")
                    self._refresh_token = session_data.get("refreshToken")
                    self._feed_token = session_data.get("feedToken")
                    self._is_logged_in = True
                    self._login_time = time.time()
                    logger.info(f"✅ Angel One SmartAPI login successful for client: {self.client_code}")
                    return True
                else:
                    error_msg = data.get("message", "Unknown login error")
                    logger.error(f"❌ Angel One login failed: {error_msg}")
                    return False

        except Exception as e:
            logger.error(f"Angel One login exception: {e}")
            return False

    async def _ensure_authenticated(self) -> bool:
        """Auto-login if session expired or not yet logged in."""
        if self.is_authenticated:
            return True
        return await self.login()

    def _get_token_info(self, symbol: str) -> Dict[str, str]:
        """Resolve symbol to Angel One token info."""
        upper = symbol.upper().strip()
        if upper in ANGELONE_TOKEN_MAP:
            return ANGELONE_TOKEN_MAP[upper]
        # Default to NSE equity
        return {
            "token": upper,
            "exchange": "NSE",
            "symbol_token": upper,
            "tradingsymbol": f"{upper}-EQ",
        }

    def _get_exchange_segment(self, symbol: str) -> str:
        """Map exchange to SmartAPI segment string."""
        info = self._get_token_info(symbol)
        exchange = info.get("exchange", "NSE")
        token = info.get("token", "")
        # Indices have tokens starting with 999
        if token.startswith("999"):
            return "NSE"  # Indices use NSE exchange
        return exchange

    async def get_quote(self, symbol: str) -> Dict[str, Any]:
        """
        Fetch full market quote from Angel One SmartAPI.
        Endpoint: POST /rest/secure/angelbroking/market/v1/quote/
        """
        clean_sym = symbol.upper().strip()
        token_info = self._get_token_info(clean_sym)

        # Fast cache check (only accept valid populated quotes with non-zero price)
        cached = await CacheService.get(f"live_quote:{clean_sym}")
        if isinstance(cached, dict) and cached.get("currentPrice", 0) > 0 and "companyName" in cached:
            return cached

        if not await self._ensure_authenticated():
            mock_quote = await self.fallback.get_quote(clean_sym)
            mock_quote["dataStatus"] = "MOCK"
            return mock_quote

        try:
            url = f"{self.base_url}/rest/secure/angelbroking/market/v1/quote/"
            exchange = token_info.get("exchange", "NSE")
            symbol_token = token_info.get("symbol_token", clean_sym)
            trading_symbol = token_info.get("tradingsymbol", clean_sym)

            payload = {
                "mode": "FULL",
                "exchangeTokens": {
                    exchange: [symbol_token],
                },
            }

            async with httpx.AsyncClient(timeout=6.0) as client:
                res = await client.post(url, json=payload, headers=self._get_headers())
                data = res.json()

                if data.get("status") and data.get("data"):
                    fetched = data["data"].get("fetched", [])
                    if fetched:
                        quote_raw = fetched[0]
                        ltp = float(quote_raw.get("ltp", 0.0))
                        open_price = float(quote_raw.get("open", ltp))
                        high = float(quote_raw.get("high", ltp))
                        low = float(quote_raw.get("low", ltp))
                        close = float(quote_raw.get("close", ltp))
                        volume = float(quote_raw.get("tradeVolume", 0))
                        avg_price = float(quote_raw.get("avgPrice", 0)) or ((open_price + high + low + close) / 4)
                        change = float(quote_raw.get("netChange", ltp - close))
                        change_pct = float(quote_raw.get("percentChange", 0))

                        info = self.fallback._get_stock_info(clean_sym) if hasattr(self.fallback, "_get_stock_info") else {}
                        company_name = info.get("companyName", f"{clean_sym} Limited")
                        sector = info.get("sector", "Diversified")
                        category = info.get("category", "Large Cap")

                        normalized = MarketDataNormalizer.normalize_quote(
                            symbol=clean_sym,
                            exchange=exchange,
                            instrument_key=f"{exchange}|{symbol_token}",
                            ltp=ltp,
                            open_price=open_price,
                            high=high,
                            low=low,
                            close=close,
                            volume=volume,
                            vwap=avg_price,
                            change=change,
                            change_percent=change_pct,
                        )
                        normalized["companyName"] = company_name
                        normalized["sector"] = sector
                        normalized["category"] = category
                        normalized["currentPrice"] = ltp
                        normalized["openPrice"] = open_price
                        normalized["dayHigh"] = high
                        normalized["dayLow"] = low
                        normalized["previousClose"] = close
                        normalized["dataStatus"] = "LIVE"
                        normalized["provider"] = "angelone"
                        normalized["tradingSymbol"] = trading_symbol

                        # Cache for fast access & zero lag
                        await CacheService.set(f"live_quote:{clean_sym}", normalized, ttl_seconds=5)
                        await CacheService.set(f"live_ltp:{clean_sym}", ltp, ttl_seconds=5)

                        return normalized

                logger.warning(f"Angel One quote returned no data for {clean_sym}. Response: {data.get('message', '')}")

        except Exception as e:
            logger.error(f"Error fetching Angel One quote for {clean_sym}: {e}")

        mock_quote = await self.fallback.get_quote(clean_sym)
        mock_quote["dataStatus"] = "UNAVAILABLE" if self.is_authenticated else "MOCK"
        return mock_quote

    async def get_ltp(self, symbol: str) -> Dict[str, Any]:
        """
        Fast LTP-only fetch.
        Endpoint: POST /rest/secure/angelbroking/market/v1/quote/
        """
        clean_sym = symbol.upper().strip()
        token_info = self._get_token_info(clean_sym)

        # Check cache first
        cached = await CacheService.get(f"live_ltp:{clean_sym}")
        if cached:
            return {"symbol": clean_sym, "ltp": cached, "dataStatus": "LIVE"}

        if not await self._ensure_authenticated():
            return {"symbol": clean_sym, "ltp": 0, "dataStatus": "MOCK"}

        try:
            url = f"{self.base_url}/rest/secure/angelbroking/market/v1/quote/"
            exchange = token_info.get("exchange", "NSE")
            symbol_token = token_info.get("symbol_token", clean_sym)

            payload = {
                "mode": "LTP",
                "exchangeTokens": {
                    exchange: [symbol_token],
                },
            }

            async with httpx.AsyncClient(timeout=5.0) as client:
                res = await client.post(url, json=payload, headers=self._get_headers())
                data = res.json()

                if data.get("status") and data.get("data"):
                    fetched = data["data"].get("fetched", [])
                    if fetched:
                        ltp = float(fetched[0].get("ltp", 0))
                        await CacheService.set(f"live_ltp:{clean_sym}", ltp, ttl_seconds=10)
                        return {"symbol": clean_sym, "ltp": ltp, "dataStatus": "LIVE"}

        except Exception as e:
            logger.error(f"Angel One LTP error for {clean_sym}: {e}")

        return {"symbol": clean_sym, "ltp": 0, "dataStatus": "UNAVAILABLE"}

    async def get_batch_quotes(self, exch_seg: str, tokens: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        Fetch quotes for multiple tokens in a single request.
        Endpoint: POST /rest/secure/angelbroking/market/v1/quote/
        Returns mapping: token -> parsed quote dict
        """
        if not tokens:
            return {}

        results: Dict[str, Dict[str, Any]] = {}
        missing_tokens = []

        # 1. Check cache first
        for token in tokens:
            cached = await CacheService.get(f"token_quote:{exch_seg}:{token}")
            if cached and isinstance(cached, dict) and cached.get("ltp") is not None:
                results[token] = cached
            else:
                missing_tokens.append(str(token))

        if not missing_tokens:
            return results

        if not await self._ensure_authenticated():
            return results

        try:
            url = f"{self.base_url}/rest/secure/angelbroking/market/v1/quote/"
            batch_size = 40
            for i in range(0, len(missing_tokens), batch_size):
                chunk = missing_tokens[i:i + batch_size]
                payload = {
                    "mode": "FULL",
                    "exchangeTokens": {
                        exch_seg: chunk,
                    },
                }

                async with httpx.AsyncClient(timeout=8.0) as client:
                    res = await client.post(url, json=payload, headers=self._get_headers())
                    if res.status_code == 200 and res.text.strip():
                        data = res.json()
                        if data.get("status") and data.get("data"):
                            fetched = data["data"].get("fetched", [])
                            for item in fetched:
                                sym_token = str(item.get("symbolToken"))
                                ltp = float(item.get("ltp") or 0.0)
                                depth = item.get("depth", {})
                                buy_orders = depth.get("buy", [])
                                sell_orders = depth.get("sell", [])

                                best_bid = float(buy_orders[0].get("price", ltp)) if buy_orders else ltp
                                best_ask = float(sell_orders[0].get("price", ltp)) if sell_orders else ltp
                                spread = round(max(0.0, best_ask - best_bid), 2)

                                q_dict = {
                                    "symbolToken": sym_token,
                                    "tradingSymbol": item.get("tradingSymbol"),
                                    "exchange": item.get("exchange", exch_seg),
                                    "ltp": ltp,
                                    "open": float(item.get("open") or ltp),
                                    "high": float(item.get("high") or ltp),
                                    "low": float(item.get("low") or ltp),
                                    "close": float(item.get("close") or ltp),
                                    "volume": int(item.get("tradeVolume") or 0),
                                    "openInterest": int(item.get("opnInterest") or 0),
                                    "bid": best_bid,
                                    "ask": best_ask,
                                    "spread": spread,
                                    "change": float(item.get("netChange") or 0.0),
                                    "changePercent": float(item.get("percentChange") or 0.0),
                                    "marketTimestamp": item.get("exchFeedTime") or datetime.now(timezone.utc).isoformat(),
                                    "receivedAt": datetime.now(timezone.utc).isoformat(),
                                    "dataStatus": "LIVE",
                                    "provider": "angelone",
                                }
                                results[sym_token] = q_dict
                                await CacheService.set(f"token_quote:{exch_seg}:{sym_token}", q_dict, ttl_seconds=5)
                                if item.get("tradingSymbol"):
                                    await CacheService.set(f"live_ltp:{item.get('tradingSymbol')}", ltp, ttl_seconds=5)

        except Exception as e:
            logger.error(f"Error in Angel One get_batch_quotes: {e}")

        return results

    async def get_option_quote(
        self,
        underlying: str,
        strike: float,
        option_type: str,
        expiry: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Resolves official contract and returns canonical option quote schema.
        """
        from app.data.instrument_master import get_instrument_master
        master = get_instrument_master()
        contract = master.resolve_option_contract(underlying, strike, option_type, expiry)
        if not contract:
            return None

        token = str(contract.get("token"))
        exch_seg = contract.get("exch_seg", "NFO")
        quotes = await self.get_batch_quotes(exch_seg, [token])
        q = quotes.get(token)

        if q:
            return {
                "instrument": contract.get("symbol"),
                "underlying": contract.get("name", underlying),
                "exchange": exch_seg,
                "expiry": contract.get("expiry"),
                "strike": strike,
                "optionType": option_type.upper(),
                "instrumentToken": token,
                "ltp": q["ltp"],
                "bid": q["bid"],
                "ask": q["ask"],
                "spread": q["spread"],
                "volume": q["volume"],
                "openInterest": q["openInterest"],
                "marketTimestamp": q["marketTimestamp"],
                "receivedAt": q["receivedAt"],
                "dataStatus": "LIVE",
                "provider": "angelone",
                "lotSize": int(contract.get("lotsize") or 25),
                "tickSize": float(contract.get("tick_size") or 0.05),
            }

        return None

    async def get_historical_candles(
        self,
        symbol: str,
        timeframe: str,
        from_date: datetime,
        to_date: datetime,
    ) -> pd.DataFrame:
        """
        Fetch historical candles from Angel One SmartAPI.
        Endpoint: POST /rest/secure/angelbroking/historical/v1/getCandleData
        
        Intervals: ONE_MINUTE, THREE_MINUTE, FIVE_MINUTE, TEN_MINUTE, 
                   FIFTEEN_MINUTE, THIRTY_MINUTE, ONE_HOUR, ONE_DAY
        """
        clean_sym = symbol.upper().strip()
        token_info = self._get_token_info(clean_sym)

        cache_key = f"hist_candles:{clean_sym}:{timeframe}:{from_date.strftime('%Y%m%d%H')}"
        cached_json = await CacheService.get(cache_key)
        if cached_json:
            try:
                import io
                return pd.read_json(io.StringIO(cached_json))
            except Exception:
                pass

        if not await self._ensure_authenticated():
            return await self.fallback.get_historical_candles(clean_sym, timeframe, from_date, to_date)

        tf_map = {
            "1m": "ONE_MINUTE",
            "3m": "THREE_MINUTE",
            "5m": "FIVE_MINUTE",
            "10m": "TEN_MINUTE",
            "15m": "FIFTEEN_MINUTE",
            "30m": "THIRTY_MINUTE",
            "1h": "ONE_HOUR",
            "1d": "ONE_DAY",
        }
        interval = tf_map.get(timeframe, "ONE_DAY")
        exchange = token_info.get("exchange", "NSE")
        symbol_token = token_info.get("symbol_token", clean_sym)
        trading_symbol = token_info.get("tradingsymbol", clean_sym)

        try:
            url = f"{self.base_url}/rest/secure/angelbroking/historical/v1/getCandleData"
            payload = {
                "exchange": exchange,
                "symboltoken": symbol_token,
                "interval": interval,
                "fromdate": from_date.strftime("%Y-%m-%d %H:%M"),
                "todate": to_date.strftime("%Y-%m-%d %H:%M"),
            }

            async with httpx.AsyncClient(timeout=3.5) as client:
                res = await client.post(url, json=payload, headers=self._get_headers())
                if res.status_code == 200 and res.text.strip():
                    try:
                        data = res.json()
                    except Exception:
                        data = {}

                    if data.get("status") and data.get("data"):
                        candles = data["data"]
                        if candles and len(candles) > 0:
                            # Angel One returns: [[timestamp, open, high, low, close, volume], ...]
                            df = pd.DataFrame(
                                candles,
                                columns=["timestamp", "open", "high", "low", "close", "volume"],
                            )
                            df["timestamp"] = pd.to_datetime(df["timestamp"])
                            df = df.sort_values("timestamp").reset_index(drop=True)
                            df["vwap"] = ((df["high"] + df["low"] + df["close"]) / 3).round(2)
                            result_df = df[["timestamp", "open", "high", "low", "close", "volume", "vwap"]]
                            await CacheService.set(cache_key, result_df.to_json(), ttl_seconds=60)
                            return result_df

        except Exception as e:
            logger.debug(f"Angel One historical candle fallback for {clean_sym}: {e}")

        return await self.fallback.get_historical_candles(clean_sym, timeframe, from_date, to_date)

    async def get_intraday_candles(
        self,
        symbol: str,
        timeframe: str = "15m",
    ) -> pd.DataFrame:
        """
        Fetch today's intraday candles using historical API with current day range.
        """
        from_date = datetime.now(timezone(timedelta(hours=5, minutes=30))).replace(
            hour=9, minute=15, second=0, microsecond=0
        )
        to_date = datetime.now(timezone(timedelta(hours=5, minutes=30)))

        return await self.get_historical_candles(symbol, timeframe, from_date, to_date)

    async def get_index_quote(self, index_symbol: str) -> Dict[str, Any]:
        return await self.get_quote(index_symbol)

    async def get_all_indices(self) -> List[Dict[str, Any]]:
        """
        Fetch quotes for all primary benchmark indices: NIFTY 50, SENSEX, BANK NIFTY, FINNIFTY, INDIA VIX.
        """
        primary_indices = ["NIFTY 50", "SENSEX", "BANK NIFTY", "FINNIFTY", "INDIA VIX"]
        tasks = [self.get_quote(idx) for idx in primary_indices]
        quotes = await asyncio.gather(*tasks, return_exceptions=True)

        results = []
        for idx_name, q in zip(primary_indices, quotes):
            quote_data = q if (isinstance(q, dict) and "ltp" in q and q.get("currentPrice", 0) > 0) else None
            if not quote_data:
                try:
                    quote_data = await self.fallback.get_quote(idx_name)
                except Exception:
                    quote_data = None

            if quote_data and isinstance(quote_data, dict):
                ltp = float(quote_data.get("currentPrice") or quote_data.get("ltp", 0.0))
                chg = float(quote_data.get("change", 0.0))
                chg_pct = float(quote_data.get("changePercent", 0.0))
                d_high = float(quote_data.get("dayHigh") or quote_data.get("high", ltp))
                d_low = float(quote_data.get("dayLow") or quote_data.get("low", ltp))
                d_open = float(quote_data.get("openPrice") or quote_data.get("open", ltp))
                d_close = float(quote_data.get("previousClose") or quote_data.get("close", ltp - chg))

                results.append({
                    "symbol": idx_name,
                    "name": quote_data.get("name", idx_name),
                    "currentValue": ltp,
                    "change": chg,
                    "changePercent": chg_pct,
                    "dayHigh": d_high,
                    "dayLow": d_low,
                    "openPrice": d_open,
                    "previousClose": d_close,
                    "trend": "Bullish" if chg >= 0 else "Bearish",
                    "sparkline": quote_data.get("sparkline") or [d_low, d_open, ltp, d_high],
                    "volatilityStatus": "Low" if idx_name == "INDIA VIX" and ltp < 13 else "Moderate",
                    "dataStatus": quote_data.get("dataStatus", "MOCK"),
                    "provider": quote_data.get("provider", "angelone"),
                })

        if len(results) >= 4:
            return results
        return await self.fallback.get_all_indices()

    async def get_sector_data(self) -> List[Dict[str, Any]]:
        """Sectoral indices from Angel One or fallback."""
        return await self.fallback.get_sector_data()

    async def get_market_breadth(self) -> Dict[str, Any]:
        return await self.fallback.get_market_breadth()

    async def get_option_chain(
        self,
        symbol: str,
        expiry: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Fetch option chain from Angel One SmartAPI.
        Endpoint: POST /rest/secure/angelbroking/marketData/v1/optionGreek
        """
        clean_sym = symbol.upper().strip()

        if not await self._ensure_authenticated():
            return {
                "symbol": clean_sym,
                "status": "UNAVAILABLE",
                "message": "Options chain requires live authenticated Angel One SmartAPI access.",
                "expiry": expiry or "Current Month",
                "pcr": None,
                "maxPain": None,
                "contracts": [],
            }

        try:
            url = f"{self.base_url}/rest/secure/angelbroking/marketData/v1/optionGreek"
            token_info = self._get_token_info(clean_sym)

            payload = {
                "name": clean_sym.replace(" ", ""),
                "expirydate": expiry or "",
            }

            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(url, json=payload, headers=self._get_headers())
                data = res.json()

                if data.get("status") and data.get("data"):
                    return {
                        "symbol": clean_sym,
                        "status": "LIVE",
                        "data": data["data"],
                        "dataStatus": "LIVE",
                        "provider": "angelone",
                    }

        except Exception as e:
            logger.warning(f"Angel One option chain fetch error: {e}")

        return {
            "symbol": clean_sym,
            "status": "UNAVAILABLE",
            "message": "Options chain temporarily unavailable from Angel One.",
            "contracts": [],
        }

    @property
    def feed_token(self) -> Optional[str]:
        """Return feed token for WebSocket connection."""
        return self._feed_token

    @property
    def jwt_token(self) -> Optional[str]:
        return self._jwt_token

    def get_provider_name(self) -> str:
        return "angelone"
