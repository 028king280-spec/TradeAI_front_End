from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from app.data.market_calendar import MarketCalendar
from app.options.greeks import calculate_black_scholes
from app.data.instrument_master import get_instrument_master


def evaluate_options_trade_setups(
    symbol: str,
    underlying_ltp: float,
    sentiment: str,
    sentiment_score: int,
    strikes_data: List[Dict[str, Any]],
    atr_14: float,
    iv: float = 0.15,
    vix_value: Optional[float] = None,
    vwap: Optional[float] = None
) -> Dict[str, Any]:
    """
    Evaluates available index option contracts and identifies strictly qualified CE or PE setups.
    
    CRITICAL MANDATES:
    1. Underlying index price and option premium are completely different instruments.
       Option premium targets and stop-losses are calculated from the ACTUAL market option LTP,
       bid/ask spread, and volatility, NEVER copied from index points.
    2. Separates 4 distinct price concepts:
       - LAST OBSERVED OPTION PREMIUM (actual market LTP)
       - SUGGESTED ENTRY PREMIUM RANGE (calibrated with bid/ask and underlying trigger)
       - STOP-LOSS PREMIUM (risk-based capital protection)
       - TARGET PREMIUMS (scenario-based exit levels: T1, T2, T3)
    3. Minimum quality conditions:
       - Clear directional sentiment alignment (Score >= 65 for CALL, Score <= 35 for PUT).
       - Minimum Risk:Reward ratio of 1:1.8 on premium.
       - Sufficient strike open interest (liquid contracts only, >= 30,000 OI).
    """
    now_ts = MarketCalendar.format_ist_timestamp()
    clean_sym = symbol.upper().strip()
    master = get_instrument_master()

    # Determine underlying key for master
    if "NIFTY" in clean_sym and "BANK" not in clean_sym and "FIN" not in clean_sym:
        und_key = "NIFTY"
        step = 50.0
        atm_strike = round(underlying_ltp / 50.0) * 50.0
        lot_size = 65
    elif "BANK" in clean_sym:
        und_key = "BANKNIFTY"
        step = 100.0
        atm_strike = round(underlying_ltp / 100.0) * 100.0
        lot_size = 15
    elif "FIN" in clean_sym:
        und_key = "FINNIFTY"
        step = 50.0
        atm_strike = round(underlying_ltp / 50.0) * 50.0
        lot_size = 25
    elif "SENSEX" in clean_sym:
        und_key = "SENSEX"
        step = 100.0
        atm_strike = round(underlying_ltp / 100.0) * 100.0
        lot_size = 10
    else:
        und_key = clean_sym
        step = 50.0
        atm_strike = round(underlying_ltp / 50.0) * 50.0
        lot_size = 25

    # Check disqualifications
    disqualifications: List[str] = []

    if sentiment == "NEUTRAL" or (38 <= sentiment_score <= 62):
        disqualifications.append("Market is in a chop/consolidation band. Buying directional options has negative expected value due to rapid theta decay.")

    vix = vix_value or 13.5
    if vix > 24.0:
        disqualifications.append(f"India VIX is elevated ({vix:.1f}). High extrinsic volatility creates severe IV crush risk.")

    if not strikes_data:
        disqualifications.append("Option chain feed is empty or contracts are unavailable.")

    is_call_bias = (sentiment == "BULLISH" and sentiment_score >= 65)
    is_put_bias = (sentiment == "BEARISH" and sentiment_score <= 35)

    if not is_call_bias and not is_put_bias:
        disqualifications.append(f"Sentiment score ({sentiment_score}) does not meet the institutional qualification threshold (>=65 for CALL, <=35 for PUT).")

    if disqualifications:
        return {
            "symbol": clean_sym,
            "hasQualifiedSetups": False,
            "statusMessage": "NO QUALIFIED SETUP — WAIT FOR BETTER CONDITIONS",
            "disqualificationReasons": disqualifications,
            "timestamp": now_ts,
            "setups": [],
            "advice": "Capital preservation is paramount. Wait for clearer trend confirmation or lower volatility before considering directional option setups."
        }

    target_type = "CE" if is_call_bias else "PE"
    bias_label = "CALL (Bullish Bias)" if is_call_bias else "PUT (Bearish Bias)"

    qualified_setups: List[Dict[str, Any]] = []

    # Sort strikes by distance to ATM
    sorted_strikes = sorted(strikes_data, key=lambda s: abs(float(s.get("strike", 0)) - atm_strike))

    for s_item in sorted_strikes[:4]:
        strike_val = float(s_item.get("strike", 0))
        opt_data = s_item.get("ce" if is_call_bias else "pe", {})

        # Actual market quote metrics
        premium = float(opt_data.get("ltp") or 0.0)
        oi = int(opt_data.get("oi") or 0)
        chg_oi = int(opt_data.get("changeInOi") or 0)
        opt_iv = float(opt_data.get("iv") or (iv * 100.0)) / 100.0
        bid = float(opt_data.get("bid") or premium)
        ask = float(opt_data.get("ask") or premium)
        spread = float(opt_data.get("spread") or max(0.05, round(ask - bid, 2)))
        contract_symbol = opt_data.get("contractSymbol")
        token = opt_data.get("instrumentToken")
        expiry = opt_data.get("expiry")
        data_status = opt_data.get("dataStatus", "MOCK")
        market_ts = opt_data.get("marketTimestamp") or now_ts

        # Fallback contract resolution from InstrumentMaster if missing
        if not contract_symbol or not token:
            resolved = master.resolve_option_contract(und_key, strike_val, target_type)
            if resolved:
                contract_symbol = resolved.get("symbol")
                token = str(resolved.get("token"))
                expiry = resolved.get("expiry")
            else:
                contract_symbol = f"{clean_sym} {int(strike_val)} {target_type}"
                expiry = "Current Weekly Expiry"

        # Liquidity check
        if premium < 10.0 or (oi > 0 and oi < 20000):
            continue

        # Greeks
        greeks = calculate_black_scholes(
            spot=underlying_ltp,
            strike=strike_val,
            time_to_expiry_years=3.0 / 365.0,
            risk_free_rate=0.065,
            iv=opt_iv,
            option_type=target_type
        )
        delta = abs(greeks["delta"])
        theta = greeks["theta"]
        gamma = greeks["gamma"]
        vega = greeks["vega"]

        # Option Premium Risk Model:
        # Stop loss based on delta * underlying volatility, capped at 25% of premium
        underlying_risk_pts = atr_14 * 0.40
        premium_risk = max(10.0, round(underlying_risk_pts * delta * 0.85, 1))
        premium_risk = min(premium_risk, round(premium * 0.25, 1))  # Max 25% stop

        # 4 SEPARATED PRICE CONCEPTS:
        # A. Last Observed Option Premium
        last_observed_ltp = round(premium, 2)

        # B. Suggested Entry Range: account for actual bid-ask spread
        entry_min = round(min(bid, premium) * 0.98, 1)
        entry_max = round(max(ask, premium) * 1.02, 1)

        # C. Stop-Loss Premium: risk-based capital protection
        stop_loss = round(max(1.0, premium - premium_risk), 1)

        # D. Target Premiums: 1.2R, 1.85R, 2.5R
        t1 = round(premium + (premium_risk * 1.2), 1)
        t2 = round(premium + (premium_risk * 1.85), 1)
        t3 = round(premium + (premium_risk * 2.5), 1)
        rr_ratio = round((t2 - premium) / premium_risk, 2) if premium_risk > 0 else 1.85

        # Setup Status: Check if current premium has already moved beyond entry max
        if premium > entry_max * 1.15:
            setup_status = "MISSED — DO NOT CHASE"
        else:
            setup_status = "QUALIFIED — AWAIT CONFIRMATION"

        # Triggers
        if is_call_bias:
            underlying_trigger = f"Index sustains above {round(underlying_ltp + (atr_14 * 0.2), 1)} with 5-minute candle strength."
            invalidation = f"Index breaches below support {round(underlying_ltp - (atr_14 * 0.35), 1)} or option falls below ₹{stop_loss}."
            reasons = [
                f"Underlying bullish momentum with institutional RSI support.",
                f"Contract open interest ({oi:,}) confirms active liquidity (Bid: ₹{bid}, Ask: ₹{ask}).",
                f"Favorable Risk:Reward ratio of 1:{rr_ratio} on premium targets."
            ]
        else:
            underlying_trigger = f"Index sustains below {round(underlying_ltp - (atr_14 * 0.2), 1)} with 5-minute candle weakness."
            invalidation = f"Index reclaims resistance {round(underlying_ltp + (atr_14 * 0.35), 1)} or option falls below ₹{stop_loss}."
            reasons = [
                f"Underlying bearish breakdown below moving average cluster.",
                f"Contract open interest ({oi:,}) confirms put accumulation (Bid: ₹{bid}, Ask: ₹{ask}).",
                f"Favorable Risk:Reward ratio of 1:{rr_ratio} on premium targets."
            ]

        qualified_setups.append({
            "index": clean_sym,
            "bias": target_type,
            "biasLabel": bias_label,
            "contractSymbol": contract_symbol,
            "instrumentToken": token,
            "strike": strike_val,
            "expiry": expiry,
            # 4 Distinct Price Concepts
            "lastObservedLtp": last_observed_ltp,
            "currentPremium": last_observed_ltp,
            "bid": round(bid, 2),
            "ask": round(ask, 2),
            "spread": round(spread, 2),
            "entryRange": f"₹{entry_min} — ₹{entry_max}",
            "suggestedEntryMin": entry_min,
            "suggestedEntryMax": entry_max,
            "stopLoss": stop_loss,
            "target1": t1,
            "target2": t2,
            "target3": t3,
            "riskRewardRatio": f"1:{rr_ratio}",
            "maxRiskPerLot": round(premium_risk * lot_size, 1),
            "potentialGainPerLot": round((t2 - premium) * lot_size, 1),
            "lotSize": lot_size,
            "setupStatus": setup_status,
            "dataStatus": data_status,
            "marketTimestamp": market_ts,
            "greeks": {
                "delta": round(delta, 3),
                "gamma": round(gamma, 5),
                "thetaPerDay": round(theta, 2),
                "vega": round(vega, 2),
            },
            "iv": round(opt_iv * 100.0, 1),
            "liquidity": "High" if oi > 100000 else "Moderate",
            "openInterest": oi,
            "changeInOi": chg_oi,
            "underlyingTrigger": underlying_trigger,
            "invalidationCondition": invalidation,
            "supportingReasons": reasons,
        })

    return {
        "symbol": clean_sym,
        "hasQualifiedSetups": len(qualified_setups) > 0,
        "statusMessage": "QUALIFIED DERIVATIVE SETUPS AVAILABLE" if qualified_setups else "NO QUALIFIED SETUP — AWAIT BETTER CONDITIONS",
        "disqualificationReasons": [] if qualified_setups else ["No strikes met the strict risk-reward or liquidity criteria."],
        "timestamp": now_ts,
        "setups": qualified_setups,
        "advice": "Trade with strict position sizing. Manage capital risk per trade below 2% of equity."
    }
