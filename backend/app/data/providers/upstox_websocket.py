import asyncio
import json
from typing import Set, Dict, Any, Optional
import httpx
import websockets

from app.core.config import settings
from app.core.logging import logger
from app.core.cache import CacheService
from app.data.normalizer import MarketDataNormalizer
from app.data.providers.upstox_provider import UPSTOX_INSTRUMENT_MAP


class UpstoxWebSocketManager:
    """
    Manages live streaming WebSocket connection to Upstox Market Data Feed v2.
    - Connects to authorized WebSocket URL.
    - Dispatches ticks to MarketDataNormalizer.
    - Updates Redis/in-memory cache for ultra-fast zero-latency LTP queries.
    - Automatic reconnection with exponential backoff on network interrupt.
    """

    def __init__(self):
        self.access_token = settings.UPSTOX_ACCESS_TOKEN or settings.UPSTOX_ANALYTICS_TOKEN
        self.subscribed_keys: Set[str] = set()
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.is_running = False
        self._reconnect_delay = 2
        self._task: Optional[asyncio.Task] = None

    def add_subscription(self, instrument_key: str):
        self.subscribed_keys.add(instrument_key)

    def add_symbol_subscription(self, symbol: str):
        sym_clean = symbol.upper().strip()
        key = UPSTOX_INSTRUMENT_MAP.get(sym_clean, f"NSE_EQ|{sym_clean}")
        self.add_subscription(key)

    async def get_authorized_feed_url(self) -> Optional[str]:
        """
        Calls GET https://api.upstox.com/v2/feed/market-data-feed/authorize
        Returns the authorized WebSocket redirect URL.
        """
        if not self.access_token:
            return None

        url = f"{settings.UPSTOX_BASE_URL}/feed/market-data-feed/authorize"
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.access_token}",
        }

        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                res = await client.get(url, headers=headers)
                if res.status_code == 200:
                    data = res.json()
                    return data.get("data", {}).get("authorizedRedirectUri")
        except Exception as e:
            logger.warning(f"Could not obtain Upstox authorized feed URL: {e}")

        return None

    async def start(self):
        """
        Starts the background WebSocket listening loop.
        """
        if self.is_running:
            return

        self.is_running = True
        # Subscribe to top default instruments
        for key in UPSTOX_INSTRUMENT_MAP.values():
            self.subscribed_keys.add(key)

        self._task = asyncio.create_task(self._connection_loop())
        logger.info("Upstox WebSocket Manager started background loop.")

    async def stop(self):
        self.is_running = False
        if self.ws:
            await self.ws.close()
        if self._task:
            self._task.cancel()
        logger.info("Upstox WebSocket Manager stopped.")

    async def _connection_loop(self):
        while self.is_running:
            if not self.access_token:
                # No token provided, sleep and periodically recheck
                await asyncio.sleep(10)
                continue

            try:
                ws_url = await self.get_authorized_feed_url()
                if not ws_url:
                    logger.debug("Waiting for valid Upstox credentials to establish live WebSocket.")
                    await asyncio.sleep(15)
                    continue

                logger.info(f"Connecting to Upstox Market Feed...")
                async with websockets.connect(
                    ws_url,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=10,
                ) as ws:
                    self.ws = ws
                    self._reconnect_delay = 2
                    logger.info("Upstox live WebSocket connected successfully!")

                    # Send subscription payload
                    sub_payload = {
                        "guid": "aivolve_sub_01",
                        "method": "sub",
                        "data": {
                            "mode": "full",
                            "instrumentKeys": list(self.subscribed_keys),
                        },
                    }
                    await ws.send(json.dumps(sub_payload).encode("utf-8"))

                    # Listen for binary or JSON ticks
                    while self.is_running:
                        message = await ws.recv()
                        await self._handle_message(message)

            except (websockets.ConnectionClosed, Exception) as e:
                logger.warning(f"Upstox WebSocket disconnected: {e}. Reconnecting in {self._reconnect_delay}s...")
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(self._reconnect_delay * 2, 60)

    async def _handle_message(self, message: Any):
        """
        Normalizes tick payload and stores LTP and quote snapshot into Redis cache.
        """
        try:
            if isinstance(message, bytes):
                # Protobuf or UTF-8 encoded text
                try:
                    text_data = message.decode("utf-8")
                    data = json.loads(text_data)
                except Exception:
                    # Protobuf binary feed handling placeholder
                    return
            else:
                data = json.loads(message)

            feeds = data.get("feeds", {})
            for instrument_key, feed_item in feeds.items():
                full_feed = feed_item.get("fullFeed", {})
                ltpc = full_feed.get("marketFF", {}).get("ltpc", {})
                ohlc = full_feed.get("marketFF", {}).get("marketOHLC", {}).get("ohlc", [{}])[-1]

                ltp = float(ltpc.get("ltp", 0.0))
                open_price = float(ohlc.get("open", ltp))
                high = float(ohlc.get("high", ltp))
                low = float(ohlc.get("low", ltp))
                close = float(ohlc.get("close", ltp))
                volume = float(full_feed.get("marketFF", {}).get("vtt", 0))

                symbol = instrument_key.split("|")[-1]

                normalized = MarketDataNormalizer.normalize_quote(
                    symbol=symbol,
                    exchange="NSE",
                    instrument_key=instrument_key,
                    ltp=ltp,
                    open_price=open_price,
                    high=high,
                    low=low,
                    close=close,
                    volume=volume,
                )
                normalized["dataStatus"] = "LIVE"

                # Store in Redis/Cache for sub-millisecond retrieval by endpoints
                await CacheService.set(f"live_quote:{symbol}", normalized, ttl_seconds=30)
                await CacheService.set(f"live_ltp:{symbol}", ltp, ttl_seconds=30)

        except Exception as e:
            logger.debug(f"Error handling WebSocket message: {e}")


# Global WebSocket Manager singleton
ws_manager = UpstoxWebSocketManager()
