from typing import List, Dict, Any
from fastapi import APIRouter
from app.core.config import settings
from app.data.market_calendar import MarketCalendar
from app.schemas.market import (
    ApiResponse,
    MarketIndexSchema,
    MarketSentimentSchema,
    MarketDriverSchema,
    SectorHeatmapItemSchema,
    RecentAISignalSchema
)
from app.services.market_service import MarketService


router = APIRouter(prefix="/market", tags=["Market"])


@router.get("/overview", response_model=ApiResponse[List[MarketIndexSchema]])
async def get_market_overview():
    indices = await MarketService.get_indices()
    return ApiResponse(success=True, data=indices)


@router.get("/live", response_model=ApiResponse[Dict[str, Any]])
async def get_market_live():
    """
    Returns live market pulse: real-time indices, market breadth, sentiment, and active data status.
    """
    indices = await MarketService.get_indices()
    sentiment = await MarketService.get_market_sentiment()
    provider_name = settings.MARKET_DATA_PROVIDER.lower()
    is_live = (
        (provider_name in ["angelone", "smartapi", "angel"] and bool(settings.ANGELONE_API_KEY))
        or (provider_name == "upstox" and bool(settings.UPSTOX_ACCESS_TOKEN))
    )
    data_status = "LIVE" if is_live else "MOCK"

    return ApiResponse(
        success=True,
        data={
            "indices": indices,
            "sentiment": sentiment,
            "marketStatus": MarketCalendar.get_market_status(),
            "provider": provider_name,
            "feedType": "SmartStream WebSocket + SmartAPI REST Quotes",
            "activeTickersCount": len(indices),
        },
        dataStatus=data_status,
    )


@router.get("/status", response_model=ApiResponse[Dict[str, Any]])
async def get_market_system_status():
    """
    Diagnostic status endpoint for market data providers, instrument master, and WebSocket feed.
    """
    from app.data.instrument_master import get_instrument_master
    from app.data.providers.factory import get_market_data_provider

    provider = get_market_data_provider()
    master = get_instrument_master()
    provider_name = settings.MARKET_DATA_PROVIDER.lower()

    is_live = (
        (provider_name in ["angelone", "smartapi", "angel"] and bool(settings.ANGELONE_API_KEY))
        or (provider_name == "upstox" and bool(settings.UPSTOX_ACCESS_TOKEN))
    )

    return ApiResponse(
        success=True,
        data={
            "activeProvider": provider_name,
            "providerClass": provider.__class__.__name__,
            "dataStatus": "LIVE" if is_live else "MOCK",
            "instrumentMaster": {
                "loaded": master.is_loaded(),
                "indexedContracts": len(master._by_token),
                "underlyingsCount": len(master._expiries_by_underlying),
            },
            "marketCalendar": MarketCalendar.get_market_status(),
            "feedConnected": True,
            "timestamp": MarketCalendar.now().isoformat(),
        },
        dataStatus="LIVE" if is_live else "MOCK",
    )


@router.get("/snapshot", response_model=ApiResponse[Dict[str, Any]])
async def get_market_snapshot():
    """
    Real-time market snapshot with verified indices, sentiment, and active drivers.
    """
    indices = await MarketService.get_indices()
    sentiment = await MarketService.get_market_sentiment()
    drivers = await MarketService.get_market_drivers()
    provider_name = settings.MARKET_DATA_PROVIDER.lower()
    is_live = (
        (provider_name in ["angelone", "smartapi", "angel"] and bool(settings.ANGELONE_API_KEY))
        or (provider_name == "upstox" and bool(settings.UPSTOX_ACCESS_TOKEN))
    )

    return ApiResponse(
        success=True,
        data={
            "indices": indices,
            "sentiment": sentiment,
            "drivers": drivers,
            "marketStatus": MarketCalendar.get_market_status(),
            "timestamp": MarketCalendar.now().isoformat(),
        },
        dataStatus="LIVE" if is_live else "MOCK",
    )


@router.get("/indices", response_model=ApiResponse[List[MarketIndexSchema]])
async def get_market_indices():
    indices = await MarketService.get_indices()
    return ApiResponse(success=True, data=indices)


@router.get("/sentiment", response_model=ApiResponse[MarketSentimentSchema])
async def get_market_sentiment():
    sentiment = await MarketService.get_market_sentiment()
    return ApiResponse(success=True, data=sentiment)


@router.get("/drivers", response_model=ApiResponse[List[MarketDriverSchema]])
async def get_market_drivers():
    drivers = await MarketService.get_market_drivers()
    return ApiResponse(success=True, data=drivers)


@router.get("/sectors", response_model=ApiResponse[List[SectorHeatmapItemSchema]])
async def get_sector_heatmap():
    sectors = await MarketService.get_sector_heatmap()
    return ApiResponse(success=True, data=sectors)


@router.get("/recent-signals", response_model=ApiResponse[List[RecentAISignalSchema]])
async def get_recent_signals():
    signals = await MarketService.get_recent_signals()
    return ApiResponse(success=True, data=signals)
