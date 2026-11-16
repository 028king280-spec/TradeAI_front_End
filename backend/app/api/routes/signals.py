from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Query, Path, HTTPException, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from app.core.logging import logger

from app.db.database import get_db
from app.schemas.market import ApiResponse
from app.schemas.signal import (
    SignalCandidateSchema,
    TrackedSignalSchema,
    SignalEventSchema,
    SignalTimelineSchema,
    SignalTimelineItemSchema,
)
from app.models.db_models import SignalRecord, SignalEventRecord
from app.services.signal_service import SignalService
from app.services.outcome_tracker import get_outcome_tracker
from app.data.market_calendar import MarketCalendar

router = APIRouter(prefix="/signals", tags=["Signals & Live Tracking"])


def _serialize_signal(s: SignalRecord) -> Dict[str, Any]:
    raw_events = []
    try:
        if "events" in s.__dict__ and s.events:
            raw_events = s.events
    except Exception:
        raw_events = []

    events = [
        {
            "id": ev.id,
            "signalId": ev.signal_id,
            "eventType": ev.event_type,
            "targetNumber": ev.target_number,
            "marketPrice": ev.market_price,
            "bid": ev.bid,
            "ask": ev.ask,
            "volume": ev.volume,
            "marketTimestamp": ev.market_timestamp.isoformat() if ev.market_timestamp else "",
            "receivedTimestamp": ev.received_timestamp.isoformat() if ev.received_timestamp else "",
            "elapsedSecondsFromSignal": ev.elapsed_seconds_from_signal,
            "elapsedSecondsFromEntry": ev.elapsed_seconds_from_entry,
            "priceSource": ev.price_source,
            "dataQualityStatus": ev.data_quality_status,
            "positionFractionClosed": ev.position_fraction_closed,
            "remainingPositionFraction": ev.remaining_position_fraction,
            "eventDetails": ev.event_details,
        }
        for ev in raw_events
    ]
    return {
        "id": s.id,
        "symbol": s.symbol,
        "contractSymbol": s.contract_symbol,
        "exchange": s.exchange,
        "instrumentToken": s.instrument_token,
        "strike": s.strike,
        "expiry": s.expiry,
        "optionType": s.option_type,
        "status": s.status,
        "underlyingPriceAtSignal": s.underlying_price_at_signal,
        "signalPremium": s.signal_premium,
        "signalBid": s.signal_bid,
        "signalAsk": s.signal_ask,
        "entryZoneMin": s.entry_zone_min,
        "entryZoneMax": s.entry_zone_max,
        "entryTriggerCondition": s.entry_trigger_condition,
        "stopLossPremium": s.stop_loss_premium,
        "target1Premium": s.target_1_premium,
        "target2Premium": s.target_2_premium,
        "target3Premium": s.target_3_premium,
        "trailingStopRule": s.trailing_stop_rule,
        "horizon": s.horizon,
        "sentiment": s.sentiment,
        "analysisScore": s.analysis_score,
        "confidence": s.confidence,
        "strategyVersion": s.strategy_version,
        "quantEngineVersion": s.quant_engine_version,
        "provider": s.provider,
        "dataStatus": s.data_status,
        "createdAt": s.created_at.isoformat() if s.created_at else "",
        "entryTriggeredAt": s.entry_triggered_at.isoformat() if s.entry_triggered_at else None,
        "entryObservedPrice": s.entry_observed_price,
        "entryObservedBid": s.entry_observed_bid,
        "entryObservedAsk": s.entry_observed_ask,
        "entryReferenceMethod": s.entry_reference_method,
        "closedAt": s.closed_at.isoformat() if s.closed_at else None,
        "finalOutcome": s.final_outcome,
        "grossPnlPoints": s.gross_pnl_points,
        "netPnlInr": s.net_pnl_inr,
        "lotSize": s.lot_size,
        "allocatedLots": s.allocated_lots,
        "remainingFraction": s.remaining_fraction,
        "isLive": s.is_live,
        "events": events,
    }


@router.get("/today")
async def get_today_signals(session: AsyncSession = Depends(get_db)):
    """
    Returns today's stock screener candidates plus all actively tracked derivative setups.
    Zero synthetic pre-seeding: returns an empty list when no signals have been qualified today.
    """
    calls = await SignalService.get_top_call_candidates()
    puts = await SignalService.get_top_put_candidates()

    # Fetch tracked signals created today
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    q = select(SignalRecord).where(SignalRecord.created_at >= today_start).order_by(desc(SignalRecord.created_at))
    res = await session.execute(q)
    tracked_signals = res.scalars().all()

    from app.data.providers.factory import get_market_data_provider
    provider = get_market_data_provider()
    is_live = (provider.get_provider_name() in ["angelone", "upstox"]) and getattr(provider, "is_authenticated", False)
    status_flag = "LIVE" if is_live else "MOCK"

    return ApiResponse(
        success=True,
        data={
            "calls": calls,
            "puts": puts,
            "trackedOptionSetups": [_serialize_signal(s) for s in tracked_signals],
            "totalTrackedToday": len(tracked_signals),
            "timestamp": MarketCalendar.now_ist().strftime("%d %b %Y, %I:%M %p IST"),
        },
        dataStatus=status_flag,
    )


@router.post("/generate")
async def generate_production_signal(
    payload: Dict[str, Any] = Body(default_factory=dict),
    session: AsyncSession = Depends(get_db),
):
    """
    Explicit Production Signal Generation & Persistence Endpoint:
    Runs the authoritative 12-stage pipeline and persists ONLY fully qualified
    paper trading signals into SQLite storage.

    Guarantees:
      - Read-only queries (GET /options/{index}/analysis) never persist signals.
      - Unqualified or rejected setups are never persisted into SignalRecord.
      - Replay/duplicate protection: deterministic ID prevents duplicate creation.
      - Atomic commit on success; rollback on failure.
      - Strictly paper trading simulation; zero broker order execution.
    """
    from app.options.pipeline_orchestrator import execute_production_signal_pipeline
    from app.api.routes.options import canonicalize_symbol
    from app.data.providers.factory import get_market_data_provider

    raw_symbol = payload.get("symbol") or payload.get("index") or "NIFTY 50"
    clean_sym = canonicalize_symbol(raw_symbol)
    available_capital = payload.get("available_capital")
    if available_capital is not None:
        try:
            available_capital = float(available_capital)
        except (ValueError, TypeError):
            available_capital = None

    provider = get_market_data_provider()

    try:
        pipeline_res = await execute_production_signal_pipeline(
            symbol=clean_sym,
            provider=provider,
            session=session,
            custom_quote=payload.get("custom_quote"),
            custom_option_chain=payload.get("custom_option_chain"),
            available_capital=available_capital,
            config=payload.get("config"),
        )
    except Exception as e:
        await session.rollback()
        logger.error(f"Pipeline execution error in POST /api/signals/generate: {e}")
        return ApiResponse(
            success=False,
            data={
                "status": "FAILED",
                "symbol": clean_sym,
                "error": str(e),
                "isTradeQualified": False,
            },
            dataStatus="DATA_UNAVAILABLE",
        )

    is_qualified = bool(pipeline_res.get("is_trade_qualified", False))
    persisted_id = pipeline_res.get("persisted_signal_id")
    action = pipeline_res.get("action", "NO_TRADE")
    stage_status = pipeline_res.get("stage_status", {})
    rejection_reasons = pipeline_res.get("rejection_reasons", [])
    feed_status = pipeline_res.get("data_quality_report", {}).get("feedStatus", "MOCK")

    if not is_qualified or action not in ("BUY_CE", "BUY_PE"):
        return ApiResponse(
            success=True,
            data={
                "status": "REJECTED",
                "symbol": clean_sym,
                "action": action,
                "isTradeQualified": False,
                "persistedSignalId": None,
                "rejectionReasons": rejection_reasons,
                "stageStatus": stage_status,
                "pipelineResult": pipeline_res.get("frontend_options_setups"),
            },
            dataStatus=feed_status,
        )

    is_duplicate = bool(pipeline_res.get("is_duplicate", False))
    status_str = "DUPLICATE" if is_duplicate else "GENERATED"

    # Explicit transaction commit
    try:
        await session.commit()
    except Exception as e:
        await session.rollback()
        logger.error(f"Transaction commit failed in POST /api/signals/generate: {e}")
        return ApiResponse(
            success=False,
            data={
                "status": "FAILED",
                "symbol": clean_sym,
                "error": f"Persistence commit failed: {e}",
                "isTradeQualified": False,
            },
            dataStatus=feed_status,
        )

    existing_sig = await session.get(SignalRecord, persisted_id) if persisted_id else None

    return ApiResponse(
        success=True,
        data={
            "status": status_str,
            "symbol": clean_sym,
            "action": action,
            "isTradeQualified": True,
            "persistedSignalId": persisted_id,
            "contract": pipeline_res.get("selected_contract", {}).get("contract_symbol"),
            "strike": pipeline_res.get("selected_contract", {}).get("strike"),
            "expiry": pipeline_res.get("selected_contract", {}).get("expiry"),
            "entryPremium": pipeline_res.get("risk_plan", {}).get("entry_premium"),
            "stopLossPremium": pipeline_res.get("risk_plan", {}).get("stop_loss_premium"),
            "target1Premium": pipeline_res.get("risk_plan", {}).get("target_1_premium"),
            "target2Premium": pipeline_res.get("risk_plan", {}).get("target_2_premium"),
            "target3Premium": pipeline_res.get("risk_plan", {}).get("target_3_premium"),
            "rewardRiskTarget1": pipeline_res.get("risk_plan", {}).get("reward_risk_target_1"),
            "stageStatus": stage_status,
            "persistedSignal": _serialize_signal(existing_sig) if existing_sig else None,
        },
        dataStatus=feed_status,
    )


@router.get("/history", response_model=ApiResponse[List[TrackedSignalSchema]])
async def get_signal_history(
    symbol: Optional[str] = Query(None, description="Filter by underlying (e.g. NIFTY 50)"),
    status: Optional[str] = Query(None, description="Filter by status (e.g. TARGET_1_HIT, STOP_LOSS_HIT, ACTIVE)"),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_db),
):
    """
    Returns persistent historical option signals.
    Never overwrites historical values with current prices.
    """
    q = select(SignalRecord)
    if symbol:
        q = q.where(SignalRecord.symbol == symbol)
    if status:
        q = q.where(SignalRecord.status == status)

    q = q.order_by(desc(SignalRecord.created_at)).limit(limit)
    res = await session.execute(q)
    signals = res.scalars().all()

    first_status = getattr(signals[0], "data_status", None) if signals else "MOCK"
    return ApiResponse(
        success=True,
        data=[_serialize_signal(s) for s in signals],
        dataStatus="LIVE" if first_status == "VERIFIED_LIVE" else first_status,
    )


@router.get("/market-state")
async def get_market_state(
    index: str = Query("NIFTY 50", description="Index symbol: NIFTY 50, SENSEX, BANK NIFTY"),
):
    """
    Evaluates current market state for the index:
    BULLISH, BEARISH, SIDEWAYS, NO_TRADE, DATA_UNAVAILABLE.
    Includes explicit NO-TRADE rationale and key breakout/breakdown triggers.
    """
    from app.options.market_state_engine import evaluate_index_market_state
    from app.data.providers.factory import get_market_data_provider
    from app.options.candle_processor import process_candlestick_series
    from app.api.routes.options import canonicalize_symbol

    clean = canonicalize_symbol(index)
    provider = get_market_data_provider()

    quote = await provider.get_quote(clean)
    candles_df = await provider.get_intraday_candles(clean, "15m")
    processed = process_candlestick_series(candles_df, clean, "15m")

    prov_name = provider.get_provider_name()
    quote_status = str(quote.get("dataStatus") or "")
    is_live = (prov_name in ["angelone", "upstox"]) and getattr(provider, "is_authenticated", False) and quote_status == "LIVE"

    state_info = evaluate_index_market_state(
        symbol=clean,
        quote=quote,
        candles_df=candles_df,
        candles_info=processed,
        is_live_data=is_live,
    )
    if prov_name == "mock" or quote.get("is_mock") or quote_status == "MOCK":
        api_status = "MOCK"
    elif quote_status in ("LIVE", "STALE", "UNAVAILABLE"):
        api_status = quote_status
    else:
        api_status = "UNAVAILABLE"
    return ApiResponse(success=True, data=state_info, dataStatus=api_status)


@router.get("/calls", response_model=ApiResponse[List[SignalCandidateSchema]])
async def get_call_candidates():
    calls = await SignalService.get_top_call_candidates()
    return ApiResponse(success=True, data=calls)


@router.get("/puts", response_model=ApiResponse[List[SignalCandidateSchema]])
async def get_put_candidates():
    puts = await SignalService.get_top_put_candidates()
    return ApiResponse(success=True, data=puts)


@router.get("/{signal_id}", response_model=ApiResponse[TrackedSignalSchema])
async def get_signal_by_id(
    signal_id: str = Path(..., description="Unique Signal UUID"),
    session: AsyncSession = Depends(get_db),
):
    """
    Returns full details for a single tracked signal including all event records.
    """
    q = select(SignalRecord).where(SignalRecord.id == signal_id)
    res = await session.execute(q)
    signal = res.scalar_one_or_none()
    if not signal:
        raise HTTPException(status_code=404, detail="Signal not found.")

    sig_status = getattr(signal, "data_status", None) or "MOCK"
    return ApiResponse(
        success=True,
        data=_serialize_signal(signal),
        dataStatus=sig_status,
    )


@router.get("/{signal_id}/events", response_model=ApiResponse[List[SignalEventSchema]])
async def get_signal_events(
    signal_id: str = Path(..., description="Unique Signal UUID"),
    session: AsyncSession = Depends(get_db),
):
    """
    Returns chronological immutable market events for a signal.
    """
    q = select(SignalEventRecord).where(SignalEventRecord.signal_id == signal_id).order_by(SignalEventRecord.market_timestamp)
    res = await session.execute(q)
    events = res.scalars().all()

    return ApiResponse(
        success=True,
        data=[
            {
                "id": ev.id,
                "signalId": ev.signal_id,
                "eventType": ev.event_type,
                "targetNumber": ev.target_number,
                "marketPrice": ev.market_price,
                "bid": ev.bid,
                "ask": ev.ask,
                "volume": ev.volume,
                "marketTimestamp": ev.market_timestamp.isoformat(),
                "receivedTimestamp": ev.received_timestamp.isoformat(),
                "elapsedSecondsFromSignal": ev.elapsed_seconds_from_signal,
                "elapsedSecondsFromEntry": ev.elapsed_seconds_from_entry,
                "priceSource": ev.price_source,
                "dataQualityStatus": ev.data_quality_status,
                "positionFractionClosed": ev.position_fraction_closed,
                "remainingPositionFraction": ev.remaining_position_fraction,
                "eventDetails": ev.event_details,
            }
            for ev in events
        ],
        dataStatus="LIVE" if events and events[0].data_quality_status == "VERIFIED_LIVE" else "MOCK",
    )


@router.get("/{signal_id}/timeline", response_model=ApiResponse[SignalTimelineSchema])
async def get_signal_timeline(
    signal_id: str = Path(..., description="Unique Signal UUID"),
    session: AsyncSession = Depends(get_db),
):
    """
    Constructs a human-readable chronological timeline for signal progression.
    """
    q = select(SignalRecord).where(SignalRecord.id == signal_id)
    res = await session.execute(q)
    sig = res.scalar_one_or_none()
    if not sig:
        raise HTTPException(status_code=404, detail="Signal not found.")

    q_events = select(SignalEventRecord).where(SignalEventRecord.signal_id == signal_id).order_by(SignalEventRecord.market_timestamp)
    res_events = await session.execute(q_events)
    events = res_events.scalars().all()

    timeline_items: List[Dict[str, Any]] = [
        {
            "timestamp": sig.created_at.strftime("%I:%M:%S %p IST") if sig.created_at else "",
            "title": "Signal Generated",
            "description": f"Recommended {sig.contract_symbol} at observed LTP ₹{sig.signal_premium:.2f} (Entry zone: ₹{sig.entry_zone_min} - ₹{sig.entry_zone_max}).",
            "price": sig.signal_premium,
            "state": "WAITING_FOR_ENTRY",
            "elapsedMinutes": 0.0,
            "isTargetOrSl": False,
        }
    ]

    for ev in events:
        mins = round(ev.elapsed_seconds_from_entry / 60.0, 1) if ev.elapsed_seconds_from_entry is not None else round(ev.elapsed_seconds_from_signal / 60.0, 1)
        is_key = ev.event_type in ["T1_HIT", "T2_HIT", "T3_HIT", "STOP_LOSS_HIT"]
        timeline_items.append({
            "timestamp": ev.market_timestamp.strftime("%I:%M:%S %p IST") if ev.market_timestamp else "",
            "title": ev.event_type.replace("_", " "),
            "description": f"Executed at observed price ₹{ev.market_price:.2f} (elapsed: {mins} mins from entry).",
            "price": ev.market_price,
            "state": ev.event_type,
            "elapsedMinutes": mins,
            "isTargetOrSl": is_key,
        })

    return ApiResponse(
        success=True,
        data={
            "signalId": sig.id,
            "contractSymbol": sig.contract_symbol,
            "underlying": sig.symbol,
            "currentStatus": sig.status,
            "finalOutcome": sig.final_outcome,
            "timeline": timeline_items,
        },
        dataStatus="LIVE" if events and events[0].data_quality_status == "VERIFIED_LIVE" else "MOCK",
    )



@router.get("/{signal_id}/failure-analysis")
async def get_signal_failure_analysis(
    signal_id: str = Path(..., description="Unique Signal UUID"),
    session: AsyncSession = Depends(get_db),
):
    """
    Returns evidence-backed failure diagnostics for a signal based on recorded observations.
    Never fabricates unverified news or causal claims.
    """
    from app.options.failure_diagnostics import diagnose_signal_failure

    q = select(SignalRecord).where(SignalRecord.id == signal_id)
    res = await session.execute(q)
    sig = res.scalar_one_or_none()
    if not sig:
        raise HTTPException(status_code=404, detail="Signal not found.")

    q_events = select(SignalEventRecord).where(SignalEventRecord.signal_id == signal_id).order_by(SignalEventRecord.market_timestamp)
    res_events = await session.execute(q_events)
    events = res_events.scalars().all()

    analysis = diagnose_signal_failure(
        signal=sig,
        events=events,
        price_observations=[],
    )
    sig_status = getattr(sig, "data_status", None) or "MOCK"
    return ApiResponse(success=True, data=analysis, dataStatus=sig_status)
