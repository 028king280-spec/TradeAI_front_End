"""
Angel One SmartAPI WebSocket v2 — Live Market Data Streaming.

Connects to Angel One's SmartStream WebSocket for real-time tick data:
- Binary protocol with struct-based message parsing
- Subscription modes: LTP, QUOTE, SNAP_QUOTE
- Auto-reconnect with exponential backoff
- Tick normalization & cache broadcast for instant frontend delivery

Protocol: wss://smartapisocket.angelone.in/smart-stream
Auth: API Key + Client Code + Feed Token
"""

import asyncio
import json
import struct
import time
from typing import Set, Dict, Any, Optional, List, Callable
import websockets

from app.core.config import settings
from app.core.logging import logger
from app.core.cache import CacheService
from app.data.normalizer import MarketDataNormalizer
from app.data.providers.angelone_provider import ANGELONE_TOKEN_MAP


# ============================================================
# SmartStream Exchange Type Mapping
# ============================================================
EXCHANGE_TYPE_MAP = {
    "NSE": 1,      # NSE Cash (CM)
    "NFO": 2,      # NSE F&O
    "BSE": 3,      # BSE Cash
    "BFO": 4,      # BSE F&O
    "MCX": 5,      # MCX Commodity
    "NCX": 7,      # NCDEX
    "CDS": 13,     # Currency Derivatives
}

# Subscription modes
MODE_LTP = 1
MODE_QUOTE = 2
MODE_SNAP_QUOTE = 3


class AngelOneWebSocketManager:
    """
    Manages live streaming WebSocket connection to Angel One SmartStream.

    Features:
    - Binary tick parsing (struct-based, no protobuf dependency)
    - Real-time LTP, Quote, Snap Quote modes
    - Broadcasts normalized ticks to in-memory/Redis cache
    - Auto-reconnect with exponential backoff
    - Server-Sent Events (SSE) broadcast for frontend consumption
    """

    def __init__(self):
        self.api_key = settings.ANGELONE_API_KEY
        self.client_code = settings.ANGELONE_CLIENT_CODE
        self.ws_url = settings.ANGELONE_WS_URL

        # Session tokens (populated after provider login)
        self._feed_token: Optional[str] = None
        self._jwt_token: Optional[str] = None

        # Subscription management
        self.subscribed_tokens: Dict[str, List[Dict]] = {}  # exchange -> [{token, exchange_type}]
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.is_running = False
        self._reconnect_delay = 2
        self._task: Optional[asyncio.Task] = None

        # SSE broadcast: list of asyncio.Queue for each connected frontend client
        self._sse_clients: List[asyncio.Queue] = []

        # Latest tick cache (in-memory for instant access)
        self._latest_ticks: Dict[str, Dict[str, Any]] = {}

    def set_tokens(self, feed_token: str, jwt_token: str):
        """Set authentication tokens from provider login."""
        self._feed_token = feed_token
        self._jwt_token = jwt_token

    def add_subscription(self, exchange: str, token: str):
        """Add a single token subscription."""
        exchange_type = EXCHANGE_TYPE_MAP.get(exchange, 1)
        if exchange not in self.subscribed_tokens:
            self.subscribed_tokens[exchange] = []
        # Avoid duplicates
        existing = {t["token"] for t in self.subscribed_tokens[exchange]}
        if token not in existing:
            self.subscribed_tokens[exchange].append({
                "token": token,
                "exchange_type": exchange_type,
            })

    def add_symbol_subscription(self, symbol: str):
        """Resolve symbol and subscribe."""
        sym_clean = symbol.upper().strip()
        info = ANGELONE_TOKEN_MAP.get(sym_clean)
        if info:
            exchange = info.get("exchange", "NSE")
            token = info.get("symbol_token", info.get("token"))
            self.add_subscription(exchange, token)

    def register_sse_client(self) -> asyncio.Queue:
        """Register a new SSE client and return its queue."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._sse_clients.append(queue)
        return queue

    def unregister_sse_client(self, queue: asyncio.Queue):
        """Remove a disconnected SSE client."""
        if queue in self._sse_clients:
            self._sse_clients.remove(queue)

    def get_latest_tick(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get the latest cached tick for a symbol."""
        return self._latest_ticks.get(symbol.upper().strip())

    def get_all_latest_ticks(self) -> Dict[str, Dict[str, Any]]:
        """Get all latest cached ticks."""
        return dict(self._latest_ticks)

    async def start(self):
        """Start the background WebSocket streaming loop."""
        if self.is_running:
            return

        self.is_running = True

        # Subscribe to top default instruments
        for sym, info in ANGELONE_TOKEN_MAP.items():
            self.add_subscription(info["exchange"], info["symbol_token"])

        self._task = asyncio.create_task(self._connection_loop())
        logger.info("Angel One WebSocket Manager started background loop.")

    async def stop(self):
        """Stop the WebSocket connection."""
        self.is_running = False
        if self.ws:
            try:
                await self.ws.close()
            except Exception:
                pass
        if self._task:
            self._task.cancel()
        logger.info("Angel One WebSocket Manager stopped.")

    async def _connection_loop(self):
        """Main reconnection loop."""
        while self.is_running:
            if not self._feed_token or not self.client_code:
                # Wait for provider login to populate tokens
                logger.debug("Waiting for Angel One login to obtain feed token...")
                await asyncio.sleep(5)

                # Try to get tokens from the provider
                try:
                    from app.data.providers.factory import get_market_data_provider
                    provider = get_market_data_provider()
                    if hasattr(provider, 'feed_token') and provider.feed_token:
                        self._feed_token = provider.feed_token
                        self._jwt_token = provider.jwt_token
                        self.client_code = provider.client_code
                        logger.info("Feed token obtained from Angel One provider.")
                except Exception:
                    pass
                continue

            try:
                # Build WebSocket auth headers
                headers = {
                    "Authorization": f"Bearer {self._jwt_token}",
                    "x-api-key": self.api_key,
                    "x-client-code": self.client_code,
                    "x-feed-token": self._feed_token,
                }

                logger.info(f"Connecting to Angel One SmartStream WebSocket...")

                async with websockets.connect(
                    self.ws_url,
                    additional_headers=headers,
                    ping_interval=25,
                    ping_timeout=20,
                    close_timeout=10,
                    max_size=2**20,
                ) as ws:
                    self.ws = ws
                    self._reconnect_delay = 2
                    logger.info("✅ Angel One SmartStream WebSocket connected!")

                    # Send subscription request
                    await self._send_subscription(ws)

                    # Listen for binary ticks
                    while self.is_running:
                        message = await ws.recv()
                        await self._handle_message(message)

            except (websockets.ConnectionClosed, Exception) as e:
                logger.warning(
                    f"Angel One WebSocket disconnected: {e}. "
                    f"Reconnecting in {self._reconnect_delay}s..."
                )
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(self._reconnect_delay * 2, 60)

    async def _send_subscription(self, ws):
        """Send subscription message in SmartStream binary format."""
        # Build token list for subscription
        token_list = []
        for exchange, tokens in self.subscribed_tokens.items():
            for t in tokens:
                token_list.append({
                    "exchangeType": t["exchange_type"],
                    "tokens": [t["token"]],
                })

        # SmartStream subscription payload (JSON)
        sub_payload = {
            "correlationID": "aivolve_stream_01",
            "action": 1,  # 1 = subscribe
            "params": {
                "mode": MODE_QUOTE,
                "tokenList": token_list,
            },
        }

        await ws.send(json.dumps(sub_payload))
        logger.info(f"Subscribed to {sum(len(t) for t in self.subscribed_tokens.values())} Angel One instruments.")

    async def _handle_message(self, message: Any):
        """
        Parse binary tick message from Angel One SmartStream.
        
        Binary format (LTP mode - 27 bytes per packet):
        - Byte 0: Subscription mode (1=LTP, 2=Quote, 3=SnapQuote)
        - Byte 1: Exchange type
        - Bytes 2-26: Token (25 bytes, null-padded string)
        - Bytes 27+: Data fields based on mode
        
        Quote mode data:
        - LTP (8 bytes, double)
        - Last Traded Qty (4 bytes, int)
        - Average Price (8 bytes, double)
        - Volume (4 bytes, int)
        - Total Buy Qty (8 bytes, double)
        - Total Sell Qty (8 bytes, double)
        - Open (8 bytes, double)
        - High (8 bytes, double)
        - Low (8 bytes, double)
        - Close (8 bytes, double)
        """
        try:
            if isinstance(message, str):
                # JSON heartbeat or text message
                data = json.loads(message)
                if data.get("type") == "heartbeat":
                    return
                logger.debug(f"Angel One WS text message: {data}")
                return

            if not isinstance(message, bytes) or len(message) < 2:
                return

            # Parse binary header
            subscription_mode = message[0]
            exchange_type = message[1]

            if len(message) < 27:
                return

            # Extract token (bytes 2-26, null-padded ASCII string)
            token_bytes = message[2:27]
            token = token_bytes.split(b'\x00')[0].decode('ascii', errors='ignore').strip()

            if not token:
                return

            # Resolve token to symbol name
            symbol = self._resolve_token_to_symbol(token, exchange_type)

            # Parse based on subscription mode
            tick_data = {"symbol": symbol, "token": token, "exchange_type": exchange_type}

            if subscription_mode == MODE_LTP and len(message) >= 35:
                # LTP mode: 8 bytes for LTP after header
                ltp = struct.unpack('<d', message[27:35])[0] if len(message) >= 35 else 0.0
                tick_data["ltp"] = round(ltp, 2)

            elif subscription_mode == MODE_QUOTE and len(message) >= 107:
                # Quote mode: full OHLCV data
                offset = 27
                ltp = struct.unpack('<d', message[offset:offset+8])[0]
                offset += 8
                last_traded_qty = struct.unpack('<i', message[offset:offset+4])[0]
                offset += 4
                avg_price = struct.unpack('<d', message[offset:offset+8])[0]
                offset += 8
                volume = struct.unpack('<i', message[offset:offset+4])[0]
                offset += 4
                total_buy_qty = struct.unpack('<d', message[offset:offset+8])[0]
                offset += 8
                total_sell_qty = struct.unpack('<d', message[offset:offset+8])[0]
                offset += 8
                open_price = struct.unpack('<d', message[offset:offset+8])[0]
                offset += 8
                high = struct.unpack('<d', message[offset:offset+8])[0]
                offset += 8
                low = struct.unpack('<d', message[offset:offset+8])[0]
                offset += 8
                close = struct.unpack('<d', message[offset:offset+8])[0]

                tick_data.update({
                    "ltp": round(ltp, 2),
                    "open": round(open_price, 2),
                    "high": round(high, 2),
                    "low": round(low, 2),
                    "close": round(close, 2),
                    "volume": int(volume),
                    "avgPrice": round(avg_price, 2),
                    "lastTradedQty": last_traded_qty,
                    "totalBuyQty": total_buy_qty,
                    "totalSellQty": total_sell_qty,
                })

            elif subscription_mode == MODE_SNAP_QUOTE:
                # Snap quote includes depth data — parse similarly to Quote
                if len(message) >= 107:
                    offset = 27
                    ltp = struct.unpack('<d', message[offset:offset+8])[0]
                    offset += 8
                    last_traded_qty = struct.unpack('<i', message[offset:offset+4])[0]
                    offset += 4
                    avg_price = struct.unpack('<d', message[offset:offset+8])[0]
                    offset += 8
                    volume = struct.unpack('<i', message[offset:offset+4])[0]
                    offset += 4
                    total_buy_qty = struct.unpack('<d', message[offset:offset+8])[0]
                    offset += 8
                    total_sell_qty = struct.unpack('<d', message[offset:offset+8])[0]
                    offset += 8
                    open_price = struct.unpack('<d', message[offset:offset+8])[0]
                    offset += 8
                    high = struct.unpack('<d', message[offset:offset+8])[0]
                    offset += 8
                    low = struct.unpack('<d', message[offset:offset+8])[0]
                    offset += 8
                    close = struct.unpack('<d', message[offset:offset+8])[0]

                    tick_data.update({
                        "ltp": round(ltp, 2),
                        "open": round(open_price, 2),
                        "high": round(high, 2),
                        "low": round(low, 2),
                        "close": round(close, 2),
                        "volume": int(volume),
                        "avgPrice": round(avg_price, 2),
                    })

            # Add metadata
            tick_data["dataStatus"] = "LIVE"
            tick_data["provider"] = "angelone"
            tick_data["timestamp"] = time.time()

            # Store in local cache
            self._latest_ticks[symbol] = tick_data

            # Store in Redis/memory cache for API endpoints
            ltp_val = float(tick_data.get("ltp", 0))
            if ltp_val > 0:
                await CacheService.set(f"live_ltp:{symbol}", ltp_val, ttl_seconds=15)

                close_val = float(tick_data.get("close") or ltp_val)
                change = round(ltp_val - close_val, 2)
                change_pct = round((change / close_val) * 100, 2) if close_val else 0

                normalized = {
                    "symbol": symbol,
                    "companyName": f"{symbol} Limited",
                    "exchange": "NSE",
                    "ltp": ltp_val,
                    "currentPrice": ltp_val,
                    "open": float(tick_data.get("open") or ltp_val),
                    "openPrice": float(tick_data.get("open") or ltp_val),
                    "high": float(tick_data.get("high") or ltp_val),
                    "dayHigh": float(tick_data.get("high") or ltp_val),
                    "low": float(tick_data.get("low") or ltp_val),
                    "dayLow": float(tick_data.get("low") or ltp_val),
                    "close": close_val,
                    "previousClose": close_val,
                    "volume": int(tick_data.get("volume", 0)),
                    "vwap": float(tick_data.get("avgPrice") or ltp_val),
                    "change": change,
                    "changePercent": change_pct,
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "dataStatus": "LIVE",
                    "provider": "angelone",
                }
                await CacheService.set(f"live_quote:{symbol}", normalized, ttl_seconds=15)

            # Broadcast to all SSE clients
            await self._broadcast_tick(tick_data)

        except Exception as e:
            logger.debug(f"Error handling Angel One WebSocket message: {e}")

    def _resolve_token_to_symbol(self, token: str, exchange_type: int) -> str:
        """Reverse-lookup token to human-readable symbol."""
        for sym, info in ANGELONE_TOKEN_MAP.items():
            if info.get("symbol_token") == token or info.get("token") == token:
                return sym
        return token

    async def _broadcast_tick(self, tick_data: Dict[str, Any]):
        """Broadcast tick to all connected SSE clients."""
        dead_clients = []
        for queue in self._sse_clients:
            try:
                if queue.full():
                    # Drop oldest message if queue is full
                    try:
                        queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                queue.put_nowait(tick_data)
            except Exception:
                dead_clients.append(queue)

        # Clean up dead clients
        for q in dead_clients:
            self._sse_clients.remove(q)


# Global WebSocket Manager singleton
angelone_ws_manager = AngelOneWebSocketManager()
