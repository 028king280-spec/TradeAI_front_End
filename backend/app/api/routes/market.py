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


def _resolve_market_api_status(indices: List[Dict[str, Any]], provider_name: str) -> str:
    if provider_name == "mock" or any(idx.get("is_mock") or idx.get("dataStatus") == "MOCK" for idx in indices):
        return "MOCK"
    if any(idx.get("dataStatus") == "LIVE" for idx in indices):
        return "LIVE"
    return "UNAVAILABLE"


@router.get("/overview", response_model=ApiResponse[List[MarketIndexSchema]])
async def get_market_overview():
    indices = await MarketService.get_indices()
    provider_name = settings.MARKET_DATA_PROVIDER.lower()
    return ApiResponse(success=True, data=indices, dataStatus=_resolve_market_api_status(indices, provider_name))


@router.get("/live", response_model=ApiResponse[Dict[str, Any]])
async def get_market_live():
    """
    Returns live market pulse: real-time indices, market breadth, sentiment, and active data status.
    """
    indices = await MarketService.get_indices()
    sentiment = await MarketService.get_market_sentiment()
    provider_name = settings.MARKET_DATA_PROVIDER.lower()
    data_status = _resolve_market_api_status(indices, provider_name)

    return ApiResponse(
        success=True,
        data={
            "indices": indices,
            "sentiment": sentiment,
            "marketStatus": MarketCalendar.get_market_status(),
            "provider": provider_name,
            "feedType": "SmartStream WebSocket + SmartAPI REST Quotes",
            "activeTickersCount": sum(1 for idx in indices if idx.get("dataStatus") == "LIVE"),
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

    is_authed = bool(getattr(provider, "is_authenticated", False))
    if provider_name == "mock":
        status_label = "MOCK"
    elif (provider_name in ["angelone", "smartapi", "angel", "upstox", "dhan"]) and is_authed:
        status_label = "LIVE"
    else:
        status_label = "UNAVAILABLE"

    return ApiResponse(
        success=True,
        data={
            "activeProvider": provider_name,
            "providerClass": provider.__class__.__name__,
            "dataStatus": status_label,
            "instrumentMaster": {
                "loaded": master.is_loaded(),
                "indexedContracts": len(master._by_token),
                "underlyingsCount": len(master._expiries_by_underlying),
            },
            "marketCalendar": MarketCalendar.get_market_status(),
            "feedConnected": status_label == "LIVE",
            "timestamp": MarketCalendar.now().isoformat(),
        },
        dataStatus=status_label,
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

    return ApiResponse(
        success=True,
        data={
            "indices": indices,
            "sentiment": sentiment,
            "drivers": drivers,
            "marketStatus": MarketCalendar.get_market_status(),
            "timestamp": MarketCalendar.now().isoformat(),
        },
        dataStatus=_resolve_market_api_status(indices, provider_name),
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


@router.get("/observer", response_model=ApiResponse[Dict[str, Any]])
async def get_observer_dashboard():
    """
    Returns The God's Eye - Observer Signal Intelligence Array and Pattern Recognition Engine data.
    """
    data = await MarketService.get_observer_intelligence()
    indices = await MarketService.get_indices()
    provider_name = settings.MARKET_DATA_PROVIDER.lower()
    return ApiResponse(
        success=True,
        data=data,
        dataStatus=_resolve_market_api_status(indices, provider_name),
    )
