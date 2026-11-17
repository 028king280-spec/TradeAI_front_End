"""Independent 60-point research profile. Never submits or mutates paper orders."""
from decimal import Decimal, ROUND_HALF_UP
from math import isfinite
from uuid import uuid4

from app.data.market_calendar import MarketCalendar
from app.options.pipeline_orchestrator import execute_production_signal_pipeline

ENGINE_ID = "research_60_target30_v1"


async def evaluate_research_setup(symbol, provider, custom_quote, custom_timeframes, custom_option_chain):
    # Both score gates must use this profile. Production defaults remain untouched.
    result = await execute_production_signal_pipeline(
        symbol=symbol, provider=provider, session=None,
        custom_quote=custom_quote, custom_timeframes=custom_timeframes,
        custom_option_chain=custom_option_chain,
        config={"min_confluence_score": 60.0,
                "trade_setup_config": {"min_confluence_score": 60.0}},
    )
    return build_research_setup(result)


def build_research_setup(result):
    reasons = list(result.get("rejection_reasons") or [])
    score = float((result.get("mtf_confluence") or {}).get("confluence_score") or 0)
    qualified = bool(result.get("is_trade_qualified")) and result.get("action") in {"BUY_CE", "BUY_PE"}
    if not isfinite(score) or score < 60:
        qualified = False
        reasons.append("Research confluence score must be at least 60/100.")
    plan = result.get("risk_plan") or {}
    contract = result.get("selected_contract") or {}
    setup = None
    if qualified:
        entry = float(plan.get("entry_premium") or 0)
        stop = float(plan.get("stop_loss_premium") or 0)
        if not all(isfinite(x) for x in (entry, stop)) or not 0 < stop < entry:
            qualified = False
            reasons.append("Research premium / stop-loss geometry is invalid.")
        else:
            target = float((Decimal(str(entry)) * Decimal("1.30")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
            rr = (target - entry) / (entry - stop)
            if rr < 1.5:
                qualified = False
                reasons.append("Research +30% target fails minimum gross reward-to-risk of 1.5.")
            else:
                setup = {"contractSymbol": contract.get("contract_symbol"),
                         "optionType": contract.get("option_type"), "expiry": contract.get("expiry"),
                         "strike": contract.get("strike"), "entryPremium": entry,
                         "stopLoss": stop, "targetPremium": target, "targetGainPct": 30,
                         "grossRewardRisk": round(rr, 4)}
    return {"id": str(uuid4()), "engineId": ENGINE_ID, "symbol": result.get("symbol"),
            "timestamp": MarketCalendar.format_ist_timestamp(), "threshold": 60,
            "score": score if isfinite(score) else None, "qualified": qualified,
            "action": result.get("action") if qualified else "NO_TRADE",
            "reasons": reasons, "setup": setup, "mode": "RESEARCH_ONLY",
            "dataStatus": (result.get("data_quality_report") or {}).get("feedStatus", "DATA_UNAVAILABLE"),
            "stages": dict(result.get("stage_status") or {}),
            "features": {"confluence": result.get("mtf_confluence") or {},
                         "marketState": result.get("market_state") or {}},
            "journalSaved": False}
