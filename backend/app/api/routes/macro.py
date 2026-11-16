"""
AIVOLVE v3.0 — Macro & Event Intelligence API Endpoints (REQ-6.11)
Part of Phase 6: Macro, Event & Overnight Drift Engine (Engine 8)

Provides RESTful access to institutional macroeconomic calendar records,
deterministic proximity calculations, and feed adapter status.
"""

from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
import zoneinfo
from fastapi import APIRouter, Query, HTTPException, status

from app.schemas.market import ApiResponse
from app.options.macro.macro_models import MacroEventTier
from app.options.macro.macro_calendar_store import MacroCalendarStore
from app.options.macro.macro_proximity_engine import MacroProximityEngine
from app.options.macro.macro_feed_adapter import get_macro_feed_adapter

router = APIRouter(prefix="/macro", tags=["Macro & Event Intelligence"])

IST = zoneinfo.ZoneInfo("Asia/Kolkata")


@router.get("/calendar", response_model=ApiResponse[Dict[str, Any]])
async def get_macro_calendar(
    start_time: Optional[str] = Query(None, description="ISO 8601 start timestamp filter"),
    end_time: Optional[str] = Query(None, description="ISO 8601 end timestamp filter"),
    tier: Optional[str] = Query(None, description="TIER_1_CRITICAL | TIER_2_HIGH | TIER_3_MEDIUM"),
    index: Optional[str] = Query(None, description="Filter by affected index (e.g. NIFTY 50)"),
):
    """
    Retrieves institutional macroeconomic calendar events, provenance, and stats.
    """
    store = MacroCalendarStore.get_instance()

    parsed_start = None
    if start_time:
        try:
            parsed_start = datetime.fromisoformat(start_time)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid start_time ISO timestamp: {start_time}"
            )

    parsed_end = None
    if end_time:
        try:
            parsed_end = datetime.fromisoformat(end_time)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid end_time ISO timestamp: {end_time}"
            )

    filter_tier = None
    if tier:
        try:
            filter_tier = MacroEventTier(tier.upper())
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid tier: {tier}. Must be one of {[t.value for t in MacroEventTier]}"
            )

    events = store.get_events(
        start_time=parsed_start,
        end_time=parsed_end,
        tier=filter_tier,
        index=index
    )

    stats = store.get_calendar_stats()
    policy = store.get_governance_policy()

    return ApiResponse(
        success=True,
        data={
            "events": [e.to_dict() for e in events],
            "stats": stats,
            "governancePolicy": policy,
            "count": len(events),
        },
        dataStatus="LIVE" if len(events) > 0 else "UNAVAILABLE",
    )


@router.get("/proximity", response_model=ApiResponse[Dict[str, Any]])
async def get_macro_proximity(
    as_of: Optional[str] = Query(None, description="ISO 8601 timestamp to evaluate proximity from"),
    index: Optional[str] = Query("NIFTY 50", description="Index to assess (e.g. NIFTY 50, BANK NIFTY, FINNIFTY)"),
    lookback_minutes: float = Query(60.0, ge=0.0, le=1440.0, description="Past window in minutes to evaluate"),
    lookforward_minutes: float = Query(240.0, ge=0.0, le=1440.0, description="Future window in minutes to evaluate"),
):
    """
    Evaluates deterministic mathematical time proximity between decision time and scheduled events.
    
    SAFETY GOVERNANCE INVARIANT:
    All trading actions (tradingOverrideActive, positionScalingFactor) remain strictly
    disarmed (False and 1.0) until policy thresholds receive formal governance sign-off.
    """
    parsed_as_of = None
    if as_of:
        try:
            parsed_as_of = datetime.fromisoformat(as_of)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid as_of ISO timestamp: {as_of}"
            )

    store = MacroCalendarStore.get_instance()
    engine = MacroProximityEngine(store)

    report = engine.evaluate_proximity(
        as_of=parsed_as_of,
        index=index,
        lookback_minutes=lookback_minutes,
        lookforward_minutes=lookforward_minutes,
    )

    return ApiResponse(
        success=True,
        data=report,
        dataStatus="LIVE",
    )


@router.get("/events/{event_id}", response_model=ApiResponse[Dict[str, Any]])
async def get_macro_event_by_id(event_id: str):
    """
    Retrieves full provenance and detail for a specific macro event ID.
    """
    store = MacroCalendarStore.get_instance()
    event = store.get_event_by_id(event_id.strip())
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Macro event '{event_id}' not found in calendar store."
        )

    return ApiResponse(
        success=True,
        data=event.to_dict(),
        dataStatus="LIVE",
    )


@router.get("/feed-status", response_model=ApiResponse[Dict[str, Any]])
async def get_macro_feed_status():
    """
    Returns connection and credential status for external macro calendar adapters.
    """
    adapter = get_macro_feed_adapter()
    conn_info = await adapter.check_connection()
    adapter_status = adapter.get_adapter_status()

    return ApiResponse(
        success=True,
        data={
            "connection": conn_info,
            "adapter": adapter_status,
        },
        dataStatus="LIVE" if conn_info.get("isLive") else "UNAVAILABLE",
    )

