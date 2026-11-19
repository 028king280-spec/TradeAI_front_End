"""
FastAPI Routes for Intelligent Paper Trading & Self-Learning Engine.
Provides endpoints for:
- Simulated trade lifecycle (Open, Partial Exit, Full Exit, Live MFE/MAE Monitor)
- Exact Indian derivatives P&L calculation & fee accounting
- AI 9-factor post-trade review
- WHAT AI LEARNED Knowledge Center
"""

import math
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
    lot_size = int(payload.get("lotSize", 65 if "NIFTY" in instrument and "BANK" not in instrument else 15))
    stop_loss = float(payload.get("stopLoss", 95.0))
    target_1 = float(payload.get("target1", 150.0))
    target_2 = float(payload.get("target2", 185.0))
    target_3 = float(payload.get("target3", 220.0))
    strategy = payload.get("strategy", "Model A (Liquidity Sweep & Retest)")
    ict_setup = payload.get("ictSetup", "Bullish SSL Sweep + FVG 50% CE")
    market_features = payload.get("marketFeatures", {})

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
    )
    return result


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

