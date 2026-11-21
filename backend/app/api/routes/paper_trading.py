"""
FastAPI Routes for Intelligent Paper Trading & Self-Learning Engine.
Provides endpoints for:
- Simulated trade lifecycle (Open, Partial Exit, Full Exit, Live MFE/MAE Monitor)
- Exact Indian derivatives P&L calculation & fee accounting
- AI 9-factor post-trade review
- WHAT AI LEARNED Knowledge Center
"""

import math
import uuid
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Body, Depends, Query, HTTPException, status
from app.options.paper_trading.paper_engine import paper_engine
from app.options.paper_trading.cost_calculator import IndianDerivativesCostCalculator
from app.options.paper_trading.trade_evaluator import AITradeEvaluator
from app.options.paper_trading.ml_feedback_engine import MLFeedbackEngine
from app.data.market_calendar import MarketCalendar
from app.core.logging import logger
from app.core.auth import verify_operator_authorization

router = APIRouter(prefix="/api/paper-trading", tags=["Paper Trading & Self-Learning"])


async def _refresh_open_positions_live_quotes():
    """Fetches real-time market quotes from broker for all active paper positions."""
    open_pos = list(paper_engine.state.get("openPositions", []))
    if not open_pos:
        return
    try:
        from app.data.providers.factory import get_market_data_provider
        from app.data.instrument_master import get_instrument_master
        provider = get_market_data_provider()
        master = get_instrument_master()
        tokens = []
        token_to_symbol = {}
        for pos in open_pos:
            csym = pos.get("contractSymbol", "")
            c = master._options_by_symbol.get(csym)
            if c and c.get("token"):
                tok = str(c["token"])
                tokens.append(tok)
                token_to_symbol[tok] = csym
        if tokens and hasattr(provider, "get_batch_quotes"):
            quotes = await provider.get_batch_quotes("NFO", tokens)
            for tok, q in quotes.items():
                csym = token_to_symbol.get(tok)
                ltp = float(q.get("ltp") or 0.0)
                if csym and ltp > 0:
                    paper_engine.update_live_monitoring(
                        contract_symbol=csym,
                        current_ltp=ltp,
                        bar_high=ltp,
                        bar_low=ltp,
                    )
    except Exception as e:
        logger.warning(f"Notice refreshing paper trading live quotes: {e}")


@router.get("/portfolio")
async def get_paper_portfolio():
    """
    Returns virtual balance, portfolio metrics, win rate, profit factor,
    open positions (with MFE/MAE), and recent trade history.
    """
    await _refresh_open_positions_live_quotes()
    metrics = paper_engine.get_dashboard_metrics()
    return {
        "status": "SUCCESS",
        "timestamp": MarketCalendar.format_ist_timestamp(),
        **metrics,
    }


@router.post("/refresh-quotes")
async def refresh_paper_quotes():
    """
    Forces immediate re-fetching of live broker quotes for all open paper positions.
    """
    await _refresh_open_positions_live_quotes()
    metrics = paper_engine.get_dashboard_metrics()
    return {
        "status": "SUCCESS",
        "message": "Live option quotes refreshed from broker",
        "timestamp": MarketCalendar.format_ist_timestamp(),
        **metrics,
    }


@router.post("/open")
async def open_simulated_trade(
    payload: Dict[str, Any] = Body(...),
    auth: str = Depends(verify_operator_authorization),
):
    """
    Fills and opens an active simulated paper trade position.
    """
    await _refresh_open_positions_live_quotes()
    instrument = payload.get("instrument", "NIFTY 50")
    contract_symbol = payload.get("contractSymbol", "NIFTY06NOV2624000CE")
    bias = payload.get("bias", "CE")
    strike = float(payload.get("strike", 24000.0))
    expiry = payload.get("expiry", "06NOV2026")
    entry_premium = float(payload.get("entryPremium", 120.0))
    raw_pos_type = payload.get("positionType", "BUY")
    clean_pos_type = str(raw_pos_type or "").strip().upper()
    if clean_pos_type != "BUY":
        raise HTTPException(
            status_code=422,
            detail={
                "status": "NAKED_OPTIONS_WRITING_PROHIBITED",
                "message": (
                    f"Paper trade rejected: Position type '{raw_pos_type}' is prohibited. "
                    "AIVOLVE institutional risk policy permits LONG (BUY) options only. "
                    "Naked option writing/shorting is strictly barred."
                ),
            },
        )
    position_type = clean_pos_type
    lots = int(payload.get("lots", 1))
    inst_clean = str(instrument or "").upper()
    default_lot = 30 if "BANK" in inst_clean else (60 if "FIN" in inst_clean else 65)
    lot_size = int(payload.get("lotSize") or default_lot)
    stop_loss = float(payload.get("stopLoss", 95.0))
    target_1 = float(payload.get("target1", 150.0))
    target_2 = float(payload.get("target2", 185.0))
    target_3 = float(payload.get("target3", 220.0))
    strategy = payload.get("strategy", "Model A (Liquidity Sweep & Retest)")
    ict_setup = payload.get("ictSetup", "Bullish SSL Sweep + FVG 50% CE")
    instrument_token = payload.get("instrumentToken") or payload.get("instrument_token")
    exchange = payload.get("exchange", "NFO")
    signal_id = payload.get("signalId") or payload.get("signal_id")
    request_id = payload.get("requestId") or payload.get("request_id")
    
    # Server-Authorized Hedging Permissions (P1 STEP 1):
    # Client-supplied allow_hedging flags must NEVER unilaterally bypass directional risk checks.
    # Hedging is strictly authorized only if the strategy matches server-authorized institutional multi-leg policies.
    from app.options.paper_trading.paper_engine import SERVER_AUTHORIZED_MULTI_LEG_STRATEGIES
    raw_allow_hedging = bool(payload.get("allowHedging") or payload.get("allow_hedging", False))
    raw_multi_leg = payload.get("multiLegStrategy") or payload.get("multi_leg_strategy")
    clean_multi_leg = str(raw_multi_leg or "").strip().upper() if raw_multi_leg else None

    if raw_allow_hedging and (not clean_multi_leg or clean_multi_leg not in SERVER_AUTHORIZED_MULTI_LEG_STRATEGIES):
        logger.warning(
            f"[SecurityAudit] Client-supplied allow_hedging flag rejected. "
            f"Strategy '{clean_multi_leg}' is not an authorized institutional multi-leg policy. Bypassing risk checks prohibited."
        )
        allow_hedging = False
        multi_leg_strategy = None
    elif clean_multi_leg and clean_multi_leg in SERVER_AUTHORIZED_MULTI_LEG_STRATEGIES:
        allow_hedging = True
        multi_leg_strategy = clean_multi_leg
    else:
        allow_hedging = False
        multi_leg_strategy = None
    
    # Sanitize client marketFeatures: Strip client-forged live/replay override flags
    raw_market_features = payload.get("marketFeatures", {}) or {}
    market_features = {k: v for k, v in raw_market_features.items() if k not in ("allowAfterHoursSimulation", "dataStatus", "feedStatus", "isReplay")}
    # Server-verified market session and data feed
    from app.data.quality_validator import FeedStatus
    market_features["isMarketOpen"] = MarketCalendar.is_market_open()
    market_features["dataStatus"] = FeedStatus.VERIFIED_LIVE if MarketCalendar.is_market_open() else FeedStatus.MARKET_CLOSED

    result = paper_engine.open_position(
        instrument=instrument,
        contract_symbol=contract_symbol,
        bias=bias,
        strike=strike,
        expiry=expiry,
        entry_premium=entry_premium,
        position_type=position_type,
        lots=lots,
        lot_size=lot_size,
        stop_loss=stop_loss,
        target_1=target_1,
        target_2=target_2,
        target_3=target_3,
        strategy=strategy,
        ict_setup=ict_setup,
        market_features=market_features,
        instrument_token=instrument_token,
        exchange=exchange,
        signal_id=signal_id,
        request_id=request_id,
        allow_hedging=allow_hedging,
        multi_leg_strategy=multi_leg_strategy,
    )
    return result


@router.get("/cooldowns")
async def get_paper_cooldowns(
    auth: str = Depends(verify_operator_authorization),
):
    """
    Returns active post-exit cooldowns and policy status (TASK 3).
    """
    return {
        "status": "SUCCESS",
        "timestamp": MarketCalendar.format_ist_timestamp(),
        **paper_engine.get_active_cooldowns(),
    }


@router.get("/session-cutoff")
async def get_session_cutoff():
    """
    Returns current session entry cutoff configuration and admissibility status.
    """
    return {
        "status": "SUCCESS",
        "timestamp": MarketCalendar.format_ist_timestamp(),
        **paper_engine.get_session_cutoff_status(),
    }


@router.post("/session-cutoff/configure")
async def configure_session_cutoff(
    payload: Dict[str, Any] = Body(...),
    auth: str = Depends(verify_operator_authorization),
):
    """
    Configures session cutoff and EOD square-off parameters.
    """
    enabled = payload.get("enabled")
    min_window = payload.get("min_holding_window_minutes")
    sq_time = payload.get("eod_square_off_time")
    enforce_sq = payload.get("enforce_eod_squareoff")

    updated = paper_engine.configure_session_cutoff(
        enabled=enabled,
        min_holding_window_minutes=min_window,
        eod_square_off_time=sq_time,
        enforce_eod_squareoff=enforce_sq,
    )
    return {
        "status": "SUCCESS",
        "timestamp": MarketCalendar.format_ist_timestamp(),
        "config": updated,
        "statusDetails": paper_engine.get_session_cutoff_status(),
    }


@router.post("/close")
async def close_simulated_trade(
    payload: Dict[str, Any] = Body(...),
    auth: str = Depends(verify_operator_authorization),
):
    """
    Closes an open position completely, calculates net P&L after statutory fees,
    triggers AI 9-factor review and ML retraining.
    """
    position_id = payload.get("positionId")
    if not position_id:
        raise HTTPException(status_code=400, detail="positionId is required")

    exit_price = float(payload.get("exitPrice", 0.0))
    exit_reason = payload.get("exitReason", "Manually Closed")

    result = paper_engine.close_position(
        position_id=position_id,
        exit_price=exit_price,
        exit_reason=exit_reason,
    )
    return result


@router.post("/partial-exit")
async def partial_exit_simulated_trade(
    payload: Dict[str, Any] = Body(...),
    auth: str = Depends(verify_operator_authorization),
):
    """
    Closes a partial batch of lots (e.g. 50% at Target 1) while trailing stop loss to cost for runner.
    """
    position_id = payload.get("positionId")
    if not position_id:
        raise HTTPException(status_code=400, detail="positionId is required")

    exit_lots = int(payload.get("exitLots", 1))
    exit_price = float(payload.get("exitPrice", 0.0))
    exit_label = payload.get("exitLabel", "Target 1 Hit (50% Partial)")

    result = paper_engine.execute_partial_exit(
        position_id=position_id,
        exit_lots=exit_lots,
        exit_price=exit_price,
        exit_label=exit_label,
    )
    return result


@router.post("/update-live")
async def update_live_quote(
    payload: Dict[str, Any] = Body(...),
    auth: str = Depends(verify_operator_authorization),
):
    """
    Ingests live option ticks, updates MFE/MAE excursions, and triggers SL or Target auto-exits.
    """
    contract_symbol = payload.get("contractSymbol")
    current_ltp = float(payload.get("currentLtp", 0.0))
    bar_high = float(payload.get("barHigh", current_ltp))
    bar_low = float(payload.get("barLow", current_ltp))

    result = paper_engine.update_live_monitoring(
        contract_symbol=contract_symbol,
        current_ltp=current_ltp,
        bar_high=bar_high,
        bar_low=bar_low,
    )
    return {"status": "UPDATED", "position": result}


@router.get("/what-ai-learned")
async def get_what_ai_learned():
    """
    Returns the comprehensive WHAT AI LEARNED knowledge dashboard:
    best/worst setups, common mistakes, market conditions, and training history.
    """
    knowledge = MLFeedbackEngine.get_what_ai_learned()
    return {
        "status": "SUCCESS",
        "timestamp": MarketCalendar.format_ist_timestamp(),
        **knowledge,
    }


@router.get("/trade-evaluation/{trade_id}")
async def get_trade_evaluation(trade_id: str):
    """
    Returns the detailed 9-question AI trade evaluation for a completed trade.
    """
    closed = paper_engine.state.get("closedTrades", [])
    matched = next((t for t in closed if t.get("id") == trade_id), None)
    if not matched:
        raise HTTPException(status_code=404, detail="Trade not found in closed trades journal")

    eval_data = matched.get("aiEvaluation") or AITradeEvaluator.evaluate_completed_trade(matched)
    return {
        "status": "SUCCESS",
        "evaluation": eval_data,
    }


@router.post("/calculate-costs")
async def calculate_costs_endpoint(payload: Dict[str, Any] = Body(...)):
    """
    Calculates exact Indian derivatives statutory taxes, brokerage, and net P&L.
    """
    entry_p = float(payload.get("entryPrice", 100.0))
    exit_p = float(payload.get("exitPrice", 125.0))
    qty = int(payload.get("quantity", 65))
    pos_type = payload.get("positionType", "BUY")

    breakdown = IndianDerivativesCostCalculator.calculate_trade_costs_and_pnl(
        entry_price=entry_p,
        exit_price=exit_p,
        quantity=qty,
        position_type=pos_type,
    )
    return breakdown


@router.post("/reset")
async def reset_paper_portfolio(auth: str = Depends(verify_operator_authorization)):
    """
    Resets the simulated portfolio back to default capital (₹1,00,000).
    """
    paper_engine.reset_account()
    return {
        "status": "SUCCESS",
        "message": "Virtual portfolio reset to starting balance of ₹1,00,000.",
    }


@router.get("/circuit-breaker")
async def get_circuit_breaker_status():
    """
    Returns real-time intraday drawdown circuit breaker status (REQ-7.5).
    Includes state (ARMED, DAILY_DRAWDOWN_BREACHED, RISK_BUDGET_UNCONFIGURED, PNL_DATA_UNAVAILABLE),
    net daily P&L, realized/floating breakdown, and active breach latch.
    """
    try:
        from app.options.drawdown_circuit_breaker import get_circuit_breaker
        cb = get_circuit_breaker()
        status = cb.get_status(paper_engine.state)
        return {
            "status": "SUCCESS",
            "timestamp": MarketCalendar.format_ist_timestamp(),
            "circuitBreaker": status,
        }
    except Exception as e:
        logger.error(f"[CircuitBreakerRoute] Error fetching status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/circuit-breaker/configure")
async def configure_circuit_breaker_budget():
    """
    PERMANENTLY DISABLED FOR SECURITY (REQ-7.5 P0 Remediation).
    External HTTP clients are strictly barred from configuring or resetting the daily risk budget.
    Daily risk budgets must only be configured via restricted server-side governance mechanisms.
    """
    logger.warning("[CircuitBreakerRoute] Blocked unauthorized attempt to configure risk budget via HTTP endpoint.")
    raise HTTPException(
        status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
        detail="HTTP configuration of circuit breaker budget is permanently disabled for security. Daily risk budgets must be configured solely via authorized server-side governance mechanisms.",
    )


@router.get("/profit-protection/research")
async def get_profit_protection_research(
    auth: str = Depends(verify_operator_authorization),
):
    """
    Returns isolated profit protection and trailing stop research analytics (P1 Research).
    Observation-only sandbox comparing Policies A through G across historical calibration
    and untouched out-of-sample evaluation datasets.
    """
    from app.options.paper_trading.profit_protection_research import ProfitProtectionResearchEngine
    return ProfitProtectionResearchEngine.get_read_only_dashboard_state()


@router.get("/profit-protection/simulated-position/{position_id}")
async def get_position_profit_protection_simulation(
    position_id: str,
    auth: str = Depends(verify_operator_authorization),
):
    """
    Returns real-time read-only counterfactual simulation of an active paper position
    under proposed Hybrid Profit Protection (Policy G).
    Does NOT modify live production stop-loss or execute broker orders.
    """
    from app.options.paper_trading.profit_protection_research import ProfitProtectionResearchEngine
    open_pos = paper_engine.state.get("openPositions", [])
    matched = next((p for p in open_pos if p["id"] == position_id), None)
    if not matched:
        closed_trades = paper_engine.state.get("closedTrades", [])
        matched = next((p for p in closed_trades if p["id"] == position_id), None)
    if not matched:
        raise HTTPException(
            status_code=404,
            detail=f"Position '{position_id}' not found in active or closed records.",
        )
    return ProfitProtectionResearchEngine.get_read_only_dashboard_state(position=matched)


@router.get("/profit-protection/shadow-monitoring")
async def get_profit_protection_shadow_monitoring(
    auth: str = Depends(verify_operator_authorization),
):
    """
    TASK 5: Read-only shadow monitoring endpoint for Policy G (Multi-Tier Hybrid Trailing Stop).
    Continuously audits active paper positions against hypothetical Policy G execution
    in real time without modifying active orders or risk governance.
    """
    return paper_engine.get_shadow_monitoring_state()


@router.get("/profit-protection/shadow-forward-status")
async def get_shadow_forward_status(
    auth: str = Depends(verify_operator_authorization),
):
    """
    TASK 7: Read-only forward shadow monitoring status and analytics dashboard.
    Distinguishes genuine forward shadow observations from realized paper P&L.
    """
    from app.options.paper_trading.shadow_forward_pipeline import shadow_pipeline
    return shadow_pipeline.get_shadow_dashboard_state()


@router.get("/profit-protection/shadow-forward-journal")
async def get_shadow_forward_journal(
    limit: int = 50,
    auth: str = Depends(verify_operator_authorization),
):
    """
    Returns the persistent forward shadow observation journal records.
    """
    from app.options.paper_trading.shadow_forward_pipeline import shadow_pipeline
    return {
        "status": "SUCCESS",
        "totalCompleted": len(shadow_pipeline.completed_journal),
        "totalActive": len(shadow_pipeline.active_opportunities),
        "totalRejected": len(shadow_pipeline.rejected_records),
        "journal": shadow_pipeline.completed_journal[-limit:],
        "activeOpportunities": list(shadow_pipeline.active_opportunities.values()),
        "rejectedRecords": shadow_pipeline.rejected_records[-limit:],
    }


@router.post("/profit-protection/shadow-opportunity/admit")
async def admit_shadow_forward_opportunity(
    payload: Dict[str, Any],
    auth: str = Depends(verify_operator_authorization),
):
    """
    TASK 1: Admits an eligible research signal into the read-only forward shadow pipeline
    without opening any paper trades or modifying risk budgets.
    """
    from app.options.paper_trading.shadow_forward_pipeline import shadow_pipeline
    return shadow_pipeline.admit_shadow_opportunity(
        signal_id=payload.get("signal_id") or payload.get("signalId") or f"SIG-{uuid.uuid4().hex[:6].upper()}",
        index=payload.get("index", "NIFTY"),
        contract_symbol=payload.get("contract_symbol") or payload.get("contractSymbol"),
        expiry=payload.get("expiry", "CURRENT_EXPIRY"),
        strike=float(payload.get("strike", 0.0)),
        option_type=payload.get("option_type") or payload.get("optionType", "CE"),
        entry_premium=float(payload.get("entry_premium") or payload.get("entryPremium", 100.0)),
        lot_size=int(payload.get("lot_size") or payload.get("lotSize", 65)),
        lots=int(payload.get("lots", 1)),
        stop_loss=payload.get("stop_loss") or payload.get("stopLoss"),
        target_1=payload.get("target_1") or payload.get("target1"),
        target_2=payload.get("target_2") or payload.get("target2"),
        target_3=payload.get("target_3") or payload.get("target3"),
        signal_quality=payload.get("signal_quality") or payload.get("signalQuality", "HIGH_CONFLUENCE"),
        market_regime=payload.get("market_regime") or payload.get("marketRegime", "TRENDING_EXPANSION"),
        technical_features=payload.get("technical_features") or payload.get("technicalFeatures"),
        sentiment_inputs=payload.get("sentiment_inputs") or payload.get("sentimentInputs"),
        data_quality_status=payload.get("data_quality_status") or payload.get("dataQualityStatus", "VERIFIED_LIVE"),
        instrument_token=payload.get("instrument_token") or payload.get("instrumentToken"),
        underlying_spot=payload.get("underlying_spot") or payload.get("underlyingSpot"),
        bid=payload.get("bid"),
        ask=payload.get("ask"),
        force_admit=payload.get("force_admit", False),
    )


@router.post("/profit-protection/shadow-opportunity/tick")
async def process_shadow_forward_tick(
    payload: Dict[str, Any],
    auth: str = Depends(verify_operator_authorization),
):
    """
    TASK 3 & 4: Ingests a market quote tick into active shadow opportunities.
    Evaluates Policy A and Policy G without lookahead bias.
    """
    from app.options.paper_trading.shadow_forward_pipeline import shadow_pipeline
    return shadow_pipeline.process_market_tick(
        contract_symbol=payload.get("contract_symbol") or payload.get("contractSymbol"),
        ltp=float(payload.get("ltp") or payload.get("lastPrice", 0.0)),
        bar_high=payload.get("bar_high") or payload.get("high"),
        bar_low=payload.get("bar_low") or payload.get("low"),
        bid=payload.get("bid"),
        ask=payload.get("ask"),
        underlying_spot=payload.get("underlying_spot") or payload.get("spot"),
        quote_timestamp=payload.get("quote_timestamp") or payload.get("timestamp"),
        feed_status=payload.get("feed_status") or payload.get("feedStatus", "VERIFIED_LIVE"),
        atr=payload.get("atr"),
    )



