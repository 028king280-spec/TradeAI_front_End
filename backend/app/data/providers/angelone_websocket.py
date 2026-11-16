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
import math
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

EXCHANGE_TYPE_REVERSE = {v: k for k, v in EXCHANGE_TYPE_MAP.items()}
VALID_EXCHANGE_TYPES = frozenset(EXCHANGE_TYPE_MAP.values())
CDS_EXCHANGE_TYPE = EXCHANGE_TYPE_MAP["CDS"]

# Subscription modes & verified SmartAPI v2 minimum packet lengths (bytes)
MODE_LTP = 1
MODE_QUOTE = 2
MODE_SNAP_QUOTE = 3

MIN_PACKET_LEN_BY_MODE = {
    MODE_LTP: 51,
    MODE_QUOTE: 123,
    MODE_SNAP_QUOTE: 379,
}

# Reasonable Unix epoch-ms bounds (2015-01-01 to 2100-01-01) for SmartAPI v2 timestamps
_MIN_VALID_EPOCH_MS = 1_420_070_400_000
_MAX_VALID_EPOCH_MS = 4_102_444_800_000


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

        # Sequence tracking & tick audit metrics (Engine 1 & 2)
        self._sequence_counters: Dict[str, int] = {}
        self._tick_metrics: Dict[str, Any] = {
            "ticks_received": 0,
            "sequence_gaps": 0,
            "anomalies_filtered": 0,
            "malformed_packets": 0,
            "last_tick_time": None,
        }

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

                    # Reconcile fresh REST snapshots immediately to heal any dropped ticks (Item 3)
                    asyncio.create_task(self._reconcile_snapshots())

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

    async def _reconcile_snapshots(self):
        """
        Executes snapshot reconciliation across benchmark indices
        immediately after WebSocket connection/reconnection to heal state gaps (Safety Item 3).
        """
        try:
            from app.data.providers.factory import get_market_data_provider
            provider = get_market_data_provider()
            benchmark_indices = ["NIFTY 50", "BANK NIFTY", "SENSEX", "FINNIFTY"]
            logger.info("Reconciling fresh REST snapshots after WebSocket connect...")
            for sym in benchmark_indices:
                try:
                    quote = await provider.get_quote(sym)
                    if quote and float(quote.get("currentPrice") or 0) > 0:
                        await CacheService.set(f"live_quote:{sym}", quote, ttl_seconds=15)
                        await CacheService.set(f"live_ltp:{sym}", float(quote.get("currentPrice")), ttl_seconds=15)
                except Exception as qe:
                    logger.debug(f"Snapshot reconciliation skip for {sym}: {qe}")
            logger.info("✅ Post-connect snapshot reconciliation complete.")
        except Exception as e:
            logger.warning(f"Error during post-connect snapshot reconciliation: {e}")

    @staticmethod
    def parse_binary_packet(message: Any) -> Optional[Dict[str, Any]]:
        """
        Decode an Angel One SmartAPI v2 SmartStream binary packet safely.

        Verified SmartAPI v2 little-endian layout:
        - Byte 0: subscription_mode (1=LTP, 2=Quote, 3=SnapQuote)
        - Byte 1: exchange_type (1=NSE, 2=NFO, 3=BSE, 4=BFO, 5=MCX, 7=NCX, 13=CDS)
        - Bytes 2..27: token (25-byte null-padded ASCII string)
        - Bytes 27..35: sequence_number (<q, int64)
        - Bytes 35..43: exchange_timestamp (<q, epoch milliseconds)
        - Bytes 43..51: last_traded_price (<q, scaled by 100 or 1e7 for CDS)
        - Bytes 51..123 (Quote >= 123B): last_traded_qty (<q), avg_price (<q),
          volume (<q), total_buy_qty (<d), total_sell_qty (<d), open (<q),
          high (<q), low (<q), close (<q)
        - Bytes 123..379 (SnapQuote >= 379B): last_traded_ts (<q), OI (<q),
          OI change % (<d), best-5 buy/sell (10x20B <hqqh), circuits & 52W (<qqqq)

        Returns None on malformed, truncated, or mathematically invalid packets.
        """
        if not isinstance(message, (bytes, bytearray)):
            return None

        if len(message) < MIN_PACKET_LEN_BY_MODE[MODE_LTP]:
            return None

        subscription_mode = message[0]
        exchange_type = message[1]

        min_len = MIN_PACKET_LEN_BY_MODE.get(subscription_mode)
        if min_len is None or exchange_type not in VALID_EXCHANGE_TYPES:
            return None
        if len(message) < min_len:
            return None

        # Extract null-padded ASCII token strictly without silently ignoring bad bytes
        raw_token = bytes(message[2:27]).split(b"\x00", 1)[0]
        try:
            token = raw_token.decode("ascii").strip()
        except UnicodeDecodeError:
            return None
        if not token or any(ord(ch) < 32 or ord(ch) > 126 for ch in token):
            return None

        try:
            sequence_number, exchange_timestamp_ms, raw_ltp = struct.unpack_from("<qqq", message, 27)
        except struct.error:
            return None

        if sequence_number < 0:
            return None
        if not (_MIN_VALID_EPOCH_MS <= exchange_timestamp_ms <= _MAX_VALID_EPOCH_MS):
            return None

        price_divisor = 10000000.0 if exchange_type == CDS_EXCHANGE_TYPE else 100.0
        price_decimals = 4 if exchange_type == CDS_EXCHANGE_TYPE else 2
        ltp = raw_ltp / price_divisor
        if not math.isfinite(ltp) or ltp <= 0.0 or ltp >= 1e9:
            return None

        exchange_ts_sec = exchange_timestamp_ms / 1000.0
        tick_data: Dict[str, Any] = {
            "token": token,
            "exchange_type": exchange_type,
            "exchange": EXCHANGE_TYPE_REVERSE.get(exchange_type, "NSE"),
            "subscription_mode": subscription_mode,
            "sequence_number": int(sequence_number),
            "exchange_timestamp": int(exchange_timestamp_ms),
            "exchange_timestamp_sec": exchange_ts_sec,
            "ltp": round(ltp, price_decimals),
            "timestamp": exchange_ts_sec,
        }

        if subscription_mode in (MODE_QUOTE, MODE_SNAP_QUOTE):
            try:
                (
                    last_traded_qty,
                    raw_avg_price,
                    volume,
                    total_buy_qty,
                    total_sell_qty,
                    raw_open,
                    raw_high,
                    raw_low,
                    raw_close,
                ) = struct.unpack_from("<qqqddqqqq", message, 51)
            except struct.error:
                return None

            if last_traded_qty < 0 or volume < 0:
                return None
            if not (math.isfinite(total_buy_qty) and total_buy_qty >= 0.0):
                return None
            if not (math.isfinite(total_sell_qty) and total_sell_qty >= 0.0):
                return None

            avg_price = raw_avg_price / price_divisor
            open_price = raw_open / price_divisor
            high_price = raw_high / price_divisor
            low_price = raw_low / price_divisor
            close_price = raw_close / price_divisor

            for price_val in (avg_price, open_price, high_price, low_price, close_price):
                if not math.isfinite(price_val) or price_val < 0.0 or price_val >= 1e9:
                    return None

            if high_price > 0.0 and low_price > 0.0 and high_price < low_price:
                return None

            tick_data.update({
                "open": round(open_price, price_decimals),
                "high": round(high_price, price_decimals),
                "low": round(low_price, price_decimals),
                "close": round(close_price, price_decimals),
                "volume": int(volume),
                "avgPrice": round(avg_price, price_decimals),
                "lastTradedQty": int(last_traded_qty),
                "totalBuyQty": float(total_buy_qty),
                "totalSellQty": float(total_sell_qty),
            })

        if subscription_mode == MODE_SNAP_QUOTE:
            try:
                last_traded_ts_ms, open_interest, oi_change_pct = struct.unpack_from("<qqd", message, 123)
                upper_c, lower_c, w52_high, w52_low = struct.unpack_from("<qqqq", message, 347)
            except struct.error:
                return None

            if last_traded_ts_ms < 0 or open_interest < 0:
                return None
            if not math.isfinite(oi_change_pct):
                return None

            upper_circuit = upper_c / price_divisor
            lower_circuit = lower_c / price_divisor
            week_52_high = w52_high / price_divisor
            week_52_low = w52_low / price_divisor

            for bound_val in (upper_circuit, lower_circuit, week_52_high, week_52_low):
                if not math.isfinite(bound_val) or bound_val < 0.0 or bound_val >= 1e9:
                    return None
            if upper_circuit > 0.0 and lower_circuit > 0.0 and upper_circuit < lower_circuit:
                return None
            if week_52_high > 0.0 and week_52_low > 0.0 and week_52_high < week_52_low:
                return None

            best_buy: List[Dict[str, Any]] = []
            best_sell: List[Dict[str, Any]] = []
            offset = 147
            for idx in range(10):
                try:
                    flag, qty, raw_p, orders = struct.unpack_from("<hqqh", message, offset)
                except struct.error:
                    return None
                offset += 20
                if qty < 0 or raw_p < 0 or orders < 0 or flag not in (0, 1):
                    return None
                entry = {
                    "quantity": int(qty),
                    "price": round(raw_p / price_divisor, price_decimals),
                    "orders": int(orders),
                }
                # SmartAPI v2 encodes 5 buy levels in slots 0-4 followed by 5 sell levels in slots 5-9
                if idx < 5:
                    best_buy.append(entry)
                else:
                    best_sell.append(entry)

            tick_data.update({
                "lastTradedTimestamp": int(last_traded_ts_ms),
                "openInterest": int(open_interest),
                "oiChangePercent": round(oi_change_pct, 4),
                "upperCircuit": round(upper_circuit, price_decimals),
                "lowerCircuit": round(lower_circuit, price_decimals),
                "week52High": round(week_52_high, price_decimals),
                "week52Low": round(week_52_low, price_decimals),
                "best5Buy": best_buy,
                "best5Sell": best_sell,
            })

        return tick_data

    async def _handle_message(self, message: Any):
        """
        Parse binary tick message or JSON text message from Angel One SmartStream.
        """
        try:
            if isinstance(message, str):
                # JSON heartbeat or text message
                data = json.loads(message)
                if data.get("type") == "heartbeat":
                    return
                logger.debug(f"Angel One WS text message: {data}")
                return

            tick_data = self.parse_binary_packet(message)
            if tick_data is None:
                self._tick_metrics["malformed_packets"] += 1
                self._tick_metrics["anomalies_filtered"] += 1
                logger.debug(
                    f"Rejected malformed Angel One binary packet (len={len(message) if isinstance(message, (bytes, bytearray)) else 'N/A'})"
                )
                return

            token = tick_data["token"]
            exchange_type = tick_data["exchange_type"]
            symbol = self._resolve_token_to_symbol(token, exchange_type)
            tick_data["symbol"] = symbol
            tick_data["dataStatus"] = "LIVE"
            tick_data["provider"] = "angelone"

            # Data Quality Engine: Tick validation & exchange sequence tracking
            from app.data.quality_validator import DataQualityEngine
            last_tick = self._latest_ticks.get(symbol)
            seq_num = tick_data["sequence_number"]
            prev_seq = self._sequence_counters.get(token)
            if seq_num == 0 and (prev_seq is None or prev_seq == 0):
                # Index feeds frequently carry constant seq=0 when no exchange sequence is assigned
                expected_seq = None
            else:
                expected_seq = (prev_seq + 1) if prev_seq is not None else None

            validation = DataQualityEngine.validate_tick(symbol, tick_data, last_tick=last_tick, expected_sequence=expected_seq)

            if validation.get("gapDetected"):
                self._tick_metrics["sequence_gaps"] += 1
                logger.warning(f"WebSocket sequence gap detected for {symbol}: {validation.get('anomalies')}")

            if not validation.get("isValid"):
                self._tick_metrics["anomalies_filtered"] += 1
                logger.debug(f"Filtered anomalous/freak tick for {symbol}: {validation.get('anomalies')}")
                return

            self._sequence_counters[token] = seq_num
            self._tick_metrics["ticks_received"] += 1
            self._tick_metrics["last_tick_time"] = time.time()
            tick_data = validation.get("sanitizedTick", tick_data)

            # Store in local cache
            self._latest_ticks[symbol] = tick_data

            # Store in Redis/memory cache for API endpoints
            ltp_val = float(tick_data.get("ltp", 0))
            if ltp_val > 0:
                await CacheService.set(f"live_ltp:{symbol}", ltp_val, ttl_seconds=15)

                close_val = float(tick_data.get("close") or ltp_val)
                change = round(ltp_val - close_val, 2)
                change_pct = round((change / close_val) * 100, 2) if close_val else 0

                exch_ts_sec = float(tick_data.get("exchange_timestamp_sec") or time.time())
                normalized = {
                    "symbol": symbol,
                    "companyName": f"{symbol} Limited",
                    "exchange": tick_data.get("exchange", "NSE"),
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
                    "exchangeTimestamp": tick_data.get("exchange_timestamp"),
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(exch_ts_sec)),
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
        try:
            from app.data.instrument_master import InstrumentMaster
            inst = InstrumentMaster.get_instance().resolve_token(token)
            if inst:
                return inst.get("symbol") or inst.get("name") or token
        except Exception:
            pass
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

    def get_diagnostics(self) -> Dict[str, Any]:
        """Returns WebSocket streaming health metrics, tick volume, and sequence audit."""
        now = time.time()
        last_time = self._tick_metrics.get("last_tick_time")
        sec_since_last_tick = (now - last_time) if last_time else None
        is_healthy = self.is_running and (sec_since_last_tick is not None and sec_since_last_tick < 30.0)
        return {
            "is_running": self.is_running,
            "is_healthy": is_healthy,
            "ticks_received": self._tick_metrics["ticks_received"],
            "sequence_gaps_detected": self._tick_metrics["sequence_gaps"],
            "anomalies_filtered": self._tick_metrics["anomalies_filtered"],
            "malformed_packets_rejected": self._tick_metrics.get("malformed_packets", 0),
            "seconds_since_last_tick": round(sec_since_last_tick, 2) if sec_since_last_tick else None,
            "subscribed_tokens_count": sum(len(t) for t in self.subscribed_tokens.values()),
            "connected_sse_clients": len(self._sse_clients),
        }


# Global WebSocket Manager singleton
angelone_ws_manager = AngelOneWebSocketManager()
