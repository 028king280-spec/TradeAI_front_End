"""
Live Market Data Streaming API Route.
Provides Server-Sent Events (SSE) endpoint for real-time tick streaming,
and REST endpoints for live quote snapshots.
"""

import asyncio
import json
import time
from typing import Optional
from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse, JSONResponse

from app.core.config import settings
from app.core.logging import logger
from app.core.cache import CacheService
from app.data.providers.factory import get_market_data_provider
from app.schemas.market import ApiResponse


router = APIRouter(prefix="/live", tags=["Live Streaming"])


@router.get("/stream")
async def live_market_stream(
    request: Request,
    symbols: Optional[str] = Query(
        default="NIFTY 50,BANK NIFTY,FINNIFTY",
        description="Comma-separated list of symbols to stream"
    ),
):
    """
    Server-Sent Events (SSE) endpoint for real-time market data.
    
    The frontend connects to this endpoint and receives a continuous stream
    of tick updates as they arrive from Angel One / Upstox WebSocket.
    
    Usage: GET /api/live/stream?symbols=NIFTY%2050,BANK%20NIFTY,RELIANCE
    
    Returns SSE events with JSON tick data:
    data: {"symbol": "NIFTY 50", "ltp": 24852.40, "change": 136.20, ...}
    """
    provider_mode = settings.MARKET_DATA_PROVIDER.lower()

    async def event_generator():
        """Generate SSE events from WebSocket tick stream."""
        queue = None
        try:
            if provider_mode in ["angelone", "smartapi", "angel"]:
                from app.data.providers.angelone_websocket import angelone_ws_manager
                queue = angelone_ws_manager.register_sse_client()

                # Send initial snapshot
                symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
                for sym in symbol_list:
                    cached = await CacheService.get(f"live_quote:{sym}")
                    if cached:
                        yield f"data: {json.dumps(cached, default=str)}\n\n"

                # Stream live ticks
                while True:
                    if await request.is_disconnected():
                        break

                    try:
                        tick = await asyncio.wait_for(queue.get(), timeout=30.0)
                        tick_symbol = tick.get("symbol", "").upper()
                        if not symbol_list or tick_symbol in symbol_list:
                            yield f"data: {json.dumps(tick, default=str)}\n\n"
                    except asyncio.TimeoutError:
                        # Send heartbeat to keep connection alive
                        yield f": heartbeat {int(time.time())}\n\n"

            else:
                # Fallback: poll cache for non-WebSocket providers
                symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
                while True:
                    if await request.is_disconnected():
                        break

                    for sym in symbol_list:
                        cached = await CacheService.get(f"live_quote:{sym}")
                        if cached:
                            yield f"data: {json.dumps(cached, default=str)}\n\n"

                    await asyncio.sleep(3)  # Poll every 3 seconds for REST providers

        except asyncio.CancelledError:
            pass
        finally:
            if queue and provider_mode in ["angelone", "smartapi", "angel"]:
                from app.data.providers.angelone_websocket import angelone_ws_manager
                angelone_ws_manager.unregister_sse_client(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Access-Control-Allow-Origin": "*",
        },
    )


@router.get("/quote/{symbol}")
async def get_live_quote(symbol: str):
    """
    Get instant live quote from cache or provider.
    Ultra-fast: checks WebSocket cache first, falls back to REST API.
    """
    clean_sym = symbol.upper().strip()

    # Try cache first (sub-millisecond)
    cached = await CacheService.get(f"live_quote:{clean_sym}")
    if cached:
        return ApiResponse(success=True, data=cached, dataStatus="LIVE")

    # Fallback to provider REST call
    provider = get_market_data_provider()
    try:
        quote = await provider.get_quote(clean_sym)
        return ApiResponse(
            success=True,
            data=quote,
            dataStatus=quote.get("dataStatus", "MOCK"),
        )
    except Exception as e:
        return ApiResponse(
            success=False,
            data=None,
            error={"code": "QUOTE_ERROR", "message": str(e)},
        )


@router.get("/ltp/{symbol}")
async def get_live_ltp(symbol: str):
    """Ultra-fast LTP-only endpoint."""
    clean_sym = symbol.upper().strip()

    cached_ltp = await CacheService.get(f"live_ltp:{clean_sym}")
    if cached_ltp:
        return {"symbol": clean_sym, "ltp": cached_ltp, "dataStatus": "LIVE"}

    # Fallback
    provider = get_market_data_provider()
    if hasattr(provider, 'get_ltp'):
        result = await provider.get_ltp(clean_sym)
        return result

    quote = await provider.get_quote(clean_sym)
    return {"symbol": clean_sym, "ltp": quote.get("ltp", 0), "dataStatus": quote.get("dataStatus", "MOCK")}


@router.get("/ticks")
async def get_all_live_ticks():
    """
    Get all currently cached live ticks — snapshot of latest data for all instruments.
    Used by frontend for initial state hydration.
    """
    provider_mode = settings.MARKET_DATA_PROVIDER.lower()

    if provider_mode in ["angelone", "smartapi", "angel"]:
        from app.data.providers.angelone_websocket import angelone_ws_manager
        ticks = angelone_ws_manager.get_all_latest_ticks()
        return ApiResponse(
            success=True,
            data=ticks,
            dataStatus="LIVE" if ticks else "WAITING",
        )

    return ApiResponse(
        success=True,
        data={},
        dataStatus="MOCK",
    )


@router.get("/status")
async def get_live_status():
    """
    Get live streaming connection status and diagnostics.
    """
    provider_mode = settings.MARKET_DATA_PROVIDER.lower()

    if provider_mode in ["angelone", "smartapi", "angel"]:
        from app.data.providers.angelone_websocket import angelone_ws_manager
        return {
            "provider": "angelone",
            "websocket_connected": angelone_ws_manager.is_running,
            "subscribed_exchanges": list(angelone_ws_manager.subscribed_tokens.keys()),
            "total_subscriptions": sum(
                len(tokens) for tokens in angelone_ws_manager.subscribed_tokens.values()
            ),
            "sse_clients_connected": len(angelone_ws_manager._sse_clients),
            "cached_ticks": len(angelone_ws_manager._latest_ticks),
            "status": "STREAMING" if angelone_ws_manager.is_running else "DISCONNECTED",
        }

    return {
        "provider": provider_mode,
        "websocket_connected": False,
        "status": "REST_POLLING",
    }
