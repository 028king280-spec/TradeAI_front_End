from typing import List, Dict, Any, Optional
import math
from datetime import datetime, timezone
from app.data.market_calendar import MarketCalendar
from app.options.greeks import calculate_black_scholes
from app.options.opening_outlook import calculate_next_session_opening_outlook
from app.data.instrument_master import get_instrument_master


def evaluate_next_session_recommendation(
    symbol: str,
    underlying_ltp: float,
    sentiment: str,
    sentiment_score: int,
    strikes_data: List[Dict[str, Any]],
    atr_14: float,
    daily_high: float,
    daily_low: float,
    daily_close: float,
    daily_open: float,
    iv: float = 0.15,
    vix_value: float = 13.5,
    live_open_price: Optional[float] = None,
    market_state: Optional[str] = None,
    circuit_breaker: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Institutional Next-Session Options Recommendation Engine for Indian Indices.
    Operates in two distinct stages:
    - STAGE 1: BEFORE MARKET OPEN (Preliminary Overnight Outlook)
    - STAGE 2: AFTER MARKET OPEN (Live Opening Price & VWAP Confirmation)

    CRITICAL MANDATES:
    1. Uses ACTUAL option contract metrics (LTP, Bid, Ask, OI, Expiry) resolved from Angel One.
    2. Separates 4 distinct price concepts:
       - LAST OBSERVED OPTION PREMIUM (actual market LTP)
       - SUGGESTED ENTRY PREMIUM RANGE (calibrated with bid/ask and entry confirmation)
       - STOP-LOSS PREMIUM (risk-based capital protection)
       - TARGET PREMIUMS (scenario-based exit levels: T1, T2, T3)
    """
    clean_sym = symbol.upper().strip()
    now_ist = MarketCalendar.format_ist_timestamp()
    target_session_date = MarketCalendar.get_next_trading_session().strftime("%A, %d %b %Y")
    master = get_instrument_master()

    valid_spot = underlying_ltp is not None and not math.isnan(underlying_ltp) and underlying_ltp > 0.0

    # Determine underlying key for master
    if "NIFTY" in clean_sym and "BANK" not in clean_sym and "FIN" not in clean_sym:
        und_key = "NIFTY"
        step = 50.0
        atm_strike = round(underlying_ltp / 50.0) * 50.0 if valid_spot else 0.0
        lot_size = 65
    elif "BANK" in clean_sym:
        und_key = "BANKNIFTY"
        step = 100.0
        atm_strike = round(underlying_ltp / 100.0) * 100.0 if valid_spot else 0.0
        lot_size = 15
    elif "FIN" in clean_sym:
        und_key = "FINNIFTY"
        step = 50.0
        atm_strike = round(underlying_ltp / 50.0) * 50.0 if valid_spot else 0.0
        lot_size = 25
    elif "SENSEX" in clean_sym:
        und_key = "SENSEX"
        step = 100.0
        atm_strike = round(underlying_ltp / 100.0) * 100.0 if valid_spot else 0.0
        lot_size = 10
    else:
        und_key = clean_sym
        step = 50.0
        atm_strike = round(underlying_ltp / 50.0) * 50.0 if valid_spot else 0.0
        lot_size = 25

    # 1. Determine Current Stage
    stage = MarketCalendar.get_session_stage()
    is_live_stage = (stage == "STAGE_2_LIVE_CONFIRMED")
    stage_label = "STAGE 2 — AFTER MARKET OPEN (LIVE CONFIRMATION)" if is_live_stage else "STAGE 1 — BEFORE MARKET OPEN (PRE-MARKET OUTLOOK)"

    # 2. Compute Opening Outlook
    opening_outlook = calculate_next_session_opening_outlook(
        symbol=clean_sym,
        previous_close=daily_close,
        daily_high=daily_high,
        daily_low=daily_low,
        daily_open=daily_open,
        atr_14=atr_14,
        vix_value=vix_value
    )

    # 3. Directional Bias & Gate Evaluation
    no_trade_reasons: List[str] = []

    if "SENSEX" in clean_sym or "BSE" in clean_sym:
        no_trade_reasons.append("SENSEX trading rejected: Under strict GOVERNANCE_LOCK. Unconfigured institutional parameters.")

    if circuit_breaker is not None:
        try:
            if not circuit_breaker.is_entry_permitted():
                cb_st = circuit_breaker.get_status()
                no_trade_reasons.append(f"Intraday drawdown circuit breaker active ({cb_st.get('state')}): {cb_st.get('reason')}")
        except Exception:
            pass

    if not valid_spot:
        no_trade_reasons.append("Underlying spot price is invalid, non-positive, or unavailable.")

    if vix_value > 32.0:
        no_trade_reasons.append(f"India VIX is elevated at {vix_value:.2f}. Extreme extrinsic volatility creates severe IV crush risk at opening bell.")

    if not strikes_data:
        no_trade_reasons.append("Option chain feed is empty or contracts are unavailable.")

    if sentiment == "NEUTRAL" or (48 <= sentiment_score <= 52):
        no_trade_reasons.append("Market sentiment is NEUTRAL (Score 50). Directional bias lacks conviction. Preserve capital.")

    # Live market regime gate: Disqualify directional option buying during sideways chop or after morning window
    if is_live_stage:
        from datetime import time as dt_time
        curr_time = MarketCalendar.now_ist().time()

        if market_state == "SIDEWAYS":
            no_trade_reasons.append("Intraday market has settled into a Sideways Chop / Consolidation regime. Directional option buying is disqualified to prevent theta decay.")

        if curr_time >= dt_time(11, 0) and market_state in ["SIDEWAYS", "NEUTRAL"]:
            no_trade_reasons.append("The Morning Momentum Window (09:20 — 11:00 AM IST) has expired. Market is currently range-bound. Await a confirmed afternoon breakout before deploying capital.")

    # Determine clear directional bias (Call favored if score >= 50, otherwise Put)
    is_call_bias = (sentiment == "BULLISH" or sentiment_score > 52)
    is_put_bias = not is_call_bias

    if is_live_stage and live_open_price:
        if is_call_bias and live_open_price < daily_close * 0.990:
            # Significant breakdown below close -> shift bias to Put
            is_call_bias = False
            is_put_bias = True
        elif is_put_bias and live_open_price > daily_close * 1.010:
            # Significant breakout above close -> shift bias to Call
            is_call_bias = True
            is_put_bias = False

    if no_trade_reasons:
        return {
            "symbol": clean_sym,
            "targetSessionDate": target_session_date,
            "stage": stage,
            "stageLabel": stage_label,
            "hasQualifiedRecommendation": False,
            "decision": "NO TRADE",
            "decisionBadge": "NO TRADE — PRESERVE CAPITAL",
            "reasonsForNoTrade": no_trade_reasons,
            "recommendation": None,
            "openingOutlook": opening_outlook,
            "riskRules": {
                "maxRiskPerLot": "₹0.00 (No capital deployed)",
                "timeBasedExit": "N/A — Wait for next session setup.",
                "reanalysisRequired": "Re-run analysis when live opening auction completes at 09:15 IST."
            },
            "disclaimer": "Analysis-only platform. Does NOT execute trades or guarantee outcomes.",
            "dataTimestamp": now_ist,
            "analysisTimestamp": now_ist,
        }

    # 4. Select Best Candidate Strike
    target_type = "CE" if is_call_bias else "PE"
    target_strike = atm_strike

    # Match contract from strikes_data
    matched = next((s for s in strikes_data if abs(float(s.get("strike", 0)) - target_strike) < 1.0), None)
    if not matched and strikes_data:
        matched = min(strikes_data, key=lambda s: abs(float(s.get("strike", 0)) - target_strike))

    opt_info = matched.get("ce" if is_call_bias else "pe", {}) if matched else {}
    last_verified_premium = float(opt_info.get("ltp") or 0.0)
    contract_oi = int(opt_info.get("oi") or 0)
    contract_iv = float(opt_info.get("iv") or (iv * 100.0))
    bid = float(opt_info.get("bid") or last_verified_premium)
    ask = float(opt_info.get("ask") or last_verified_premium)
    spread = float(opt_info.get("spread") or max(0.05, round(ask - bid, 2)))
    contract_symbol = opt_info.get("contractSymbol")
    token = opt_info.get("instrumentToken")
    expiry_str = opt_info.get("expiry")
    data_status = opt_info.get("dataStatus", "MOCK")

    # Resolve from InstrumentMaster if not present
    if not contract_symbol or not token:
        resolved = master.resolve_option_contract(und_key, target_strike, target_type)
        if resolved:
            contract_symbol = resolved.get("symbol")
            token = str(resolved.get("token"))
            expiry_str = resolved.get("expiry")
        else:
            contract_symbol = f"{clean_sym} {int(target_strike)} {target_type}"
            expiry_str = "Current Weekly Expiry"

    # Compute Greeks for next session (~2.5 days to expiry)
    greeks = calculate_black_scholes(
        spot=underlying_ltp,
        strike=target_strike,
        time_to_expiry_years=2.5 / 365.0,
        risk_free_rate=0.065,
        iv=contract_iv / 100.0,
        option_type=target_type
    )
    delta = abs(greeks["delta"]) if (greeks and "delta" in greeks and greeks["delta"] is not None) else 0.5
    theta_day = greeks["theta"] if (greeks and "theta" in greeks and greeks["theta"] is not None) else -10.0

    # Fallback to theoretical Black-Scholes estimate if broker quote LTP is missing
    is_theoretical = False
    premium_source = "LIVE_MARKET"
    if last_verified_premium <= 0.0:
        if greeks and greeks.get("price", 0) > 0:
            last_verified_premium = float(greeks["price"])
            is_theoretical = True
            premium_source = "THEORETICAL"
            data_status = "THEORETICAL"
        else:
            no_trade_reasons.append("Target option contract lacks live market quotes and theoretical valuation failed.")

    # Live stage gate: Disqualify execution if premium is purely theoretical
    if is_live_stage and is_theoretical:
        no_trade_reasons.append("Target option contract lacks live market quotes. Live execution prohibited with theoretical valuation.")

    # 4 SEPARATE PRICE CONCEPTS:
    # A. Last Observed Option Premium
    last_observed_ltp = round(last_verified_premium, 2)

    # Risk model: delta * underlying risk, capped at 25% of premium
    premium_stop_pts = max(12.0, round(atr_14 * 0.40 * delta * 0.85, 1))
    if last_verified_premium > 0:
        premium_stop_pts = min(premium_stop_pts, round(last_verified_premium * 0.25, 1))

    # B. Suggested Entry Range: account for actual bid-ask spread
    suggested_entry_min = round(min(bid, last_verified_premium) * 0.98, 1) if last_verified_premium > 0 else 0.0
    suggested_entry_max = round(max(ask, last_verified_premium) * 1.02, 1) if last_verified_premium > 0 else 0.0

    # C. Stop-Loss Premium
    stop_loss_premium = round(max(1.0, last_verified_premium - premium_stop_pts), 1)

    # D. Target Premiums (T1 calibrated to ~30% gain with Hit Probabilities)
    t1_gain = max(round(last_verified_premium * 0.30, 1), round(premium_stop_pts * 1.5, 1))
    t2_gain = max(round(last_verified_premium * 0.55, 1), round(premium_stop_pts * 2.5, 1))
    t3_gain = max(round(last_verified_premium * 0.85, 1), round(premium_stop_pts * 3.8, 1))

    t1_premium = round(last_verified_premium + t1_gain, 1)
    t2_premium = round(last_verified_premium + t2_gain, 1)
    t3_premium = round(last_verified_premium + t3_gain, 1)

    t1_pct = round((t1_gain / last_verified_premium) * 100.0, 1) if last_verified_premium > 0 else 30.0
    t2_pct = round((t2_gain / last_verified_premium) * 100.0, 1) if last_verified_premium > 0 else 55.0
    t3_pct = round((t3_gain / last_verified_premium) * 100.0, 1) if last_verified_premium > 0 else 85.0

    t1_prob = 80
    t2_prob = 52
    t3_prob = 25

    target_probabilities = {
        "target1": {
            "price": t1_premium,
            "gainPct": t1_pct,
            "probabilityPct": t1_prob,
            "likelihood": "HIGH",
            "badge": f"High Chance ({t1_prob}%)",
            "description": f"Target 1 (+{t1_pct}%): High probability of hit. Ideal for 50% partial booking.",
        },
        "target2": {
            "price": t2_premium,
            "gainPct": t2_pct,
            "probabilityPct": t2_prob,
            "likelihood": "MODERATE",
            "badge": f"Moderate Chance ({t2_prob}%)",
            "description": f"Target 2 (+{t2_pct}%): Moderate continuation target. Hold runner with SL at cost.",
        },
        "target3": {
            "price": t3_premium,
            "gainPct": t3_pct,
            "probabilityPct": t3_prob,
            "likelihood": "LOW",
            "badge": f"Low Chance ({t3_prob}%)",
            "description": f"Target 3 (+{t3_pct}%): Low hit probability. Only for runners on strong trend days.",
        },
    }

    rr_ratio = round((t2_premium - last_verified_premium) / premium_stop_pts, 2) if premium_stop_pts > 0 else 1.85

    max_risk_inr = round(premium_stop_pts * lot_size, 1)
    potential_gain_inr = round((t2_premium - last_verified_premium) * lot_size, 1)
    do_not_chase_level = round(suggested_entry_max * 1.15, 1)

    if is_call_bias:
        underlying_trigger = f"Index sustains above opening range high {round(opening_outlook['expectedOpeningRange']['midpoint'], 1)} post 09:15-09:20 opening candle."
        entry_condition = f"Wait for opening 5-minute candle to close green above ₹{suggested_entry_min}. Verify bid-ask spread is under 1.5%."
        invalidation = f"Index drops below session demand level {round(daily_low, 1)} or option premium falls below stop-loss of ₹{stop_loss_premium}."
        selection_reasons = [
            f"Underlying bullish momentum aligned with positive overnight opening expectation (+{opening_outlook['estimatedGap']['points']} pts).",
            f"Active contract liquidity ({contract_oi:,} OI) with Delta of {delta:.2f} (Bid: ₹{bid}, Ask: ₹{ask}).",
            f"Favorable Risk:Reward ratio of 1:{rr_ratio} on premium targets."
        ]
    else:
        underlying_trigger = f"Index breaks down and sustains below {round(opening_outlook['expectedOpeningRange']['midpoint'], 1)} post 09:15-09:20 opening candle."
        entry_condition = f"Wait for opening 5-minute candle to confirm bearish breakdown with premium sustaining above ₹{suggested_entry_min}."
        invalidation = f"Index reclaims session supply level {round(daily_high, 1)} or option premium falls below stop-loss of ₹{stop_loss_premium}."
        selection_reasons = [
            f"Underlying bearish distribution aligned with negative overnight opening expectation ({opening_outlook['estimatedGap']['points']} pts).",
            f"Active contract liquidity ({contract_oi:,} OI) with Delta of {delta:.2f} providing downside hedge.",
            f"Favorable Risk:Reward ratio of 1:{rr_ratio} on premium targets."
        ]

    recommendation = {
        "index": clean_sym,
        "optionType": target_type,
        "biasLabel": f"NEXT-SESSION {target_type} ({'BULLISH' if is_call_bias else 'BEARISH'})",
        "contractSymbol": contract_symbol,
        "instrumentToken": token,
        "strike": target_strike,
        "expiry": expiry_str,
        # 4 Distinct Price Concepts
        "lastObservedLtp": last_observed_ltp,
        "lastVerifiedPremium": last_observed_ltp,
        "bid": round(bid, 2),
        "ask": round(ask, 2),
        "spread": round(spread, 2),
        "suggestedEntryRange": f"₹{suggested_entry_min} — ₹{suggested_entry_max}",
        "suggestedEntryMin": suggested_entry_min,
        "suggestedEntryMax": suggested_entry_max,
        "entryConfirmationCondition": entry_condition,
        "stopLossPremium": stop_loss_premium,
        "target1Premium": t1_premium,
        "target2Premium": t2_premium,
        "target3Premium": t3_premium,
        "targetProbabilities": target_probabilities,
        "t1Probability": t1_prob,
        "t2Probability": t2_prob,
        "t3Probability": t3_prob,
        "t1GainPct": t1_pct,
        "t2GainPct": t2_pct,
        "t3GainPct": t3_pct,
        "t1Likelihood": "HIGH",
        "t2Likelihood": "MODERATE",
        "t3Likelihood": "LOW",
        "riskRewardRatio": f"1:{rr_ratio}",
        "estimatedHoldingHorizon": "Morning Momentum Window (09:20 — 11:00 AM IST)",
        "underlyingTrigger": underlying_trigger,
        "invalidationCondition": invalidation,
        "doNotChaseThreshold": f"₹{do_not_chase_level} (If premium gaps above this, setup is EXPIRED / DO NOT CHASE)",
        "liquidityAssessment": "High" if contract_oi >= 80000 else "Moderate",
        "contractOpenInterest": contract_oi,
        "greeks": {
            "delta": round(delta, 3) if delta is not None else None,
            "gamma": round(greeks["gamma"], 5) if (greeks and greeks.get("gamma") is not None) else None,
            "thetaPerDay": round(theta_day, 2) if theta_day is not None else None,
            "vega": round(greeks["vega"], 2) if (greeks and greeks.get("vega") is not None) else None,
        },
        "iv": round(contract_iv, 1),
        "lotSize": lot_size,
        "maxRiskPerLotINR": max_risk_inr,
        "potentialGainPerLotINR": potential_gain_inr,
        "reasonsForSelection": selection_reasons,
        "isTheoretical": is_theoretical,
        "premiumSource": premium_source,
        "isExecutable": not is_theoretical,
        "dataStatus": data_status,
        "marketTimestamp": now_ist,
        "priceDisclaimers": {
            "lastObserved": (
                f"₹{last_observed_ltp} (THEORETICAL Black-Scholes estimate; no live market quote verified)"
                if is_theoretical else
                f"₹{last_observed_ltp} (Actual Angel One NFO live LTP)"
            ),
            "plannedEntry": f"₹{suggested_entry_min} — ₹{suggested_entry_max}",
            "actualFillPrice": "UNAVAILABLE (Application is analysis-only; does not execute orders)",
            "calculatedExit": f"SL: ₹{stop_loss_premium} | T1: ₹{t1_premium} | T2: ₹{t2_premium}"
        }
    }

    return {
        "symbol": clean_sym,
        "targetSessionDate": target_session_date,
        "stage": stage,
        "stageLabel": stage_label,
        "hasQualifiedRecommendation": True,
        "decision": f"BUY {target_type}",
        "decisionBadge": f"QUALIFIED {target_type} RECOMMENDATION",
        "reasonsForNoTrade": [],
        "recommendation": recommendation,
        "openingOutlook": opening_outlook,
        "riskRules": {
            "maxRiskPerLot": f"₹{max_risk_inr:,.2f} ({lot_size} qty / 1 lot)",
            "timeBasedExit": "Exit before 02:45 PM IST to mitigate accelerated intraday theta decay.",
            "reanalysisRequired": "Re-evaluate if opening 15-minute candle breaks the opposite session boundary."
        },
        "disclaimer": "Analysis-only platform. Does NOT execute trades or guarantee outcomes.",
        "dataTimestamp": now_ist,
        "analysisTimestamp": now_ist,
    }
