from typing import List, Dict, Any, Optional


def calculate_max_pain(strikes_data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Computes Option Max Pain (Strike where cumulative loss to option sellers/writers is minimized).
    
    Formula:
    For hypothetical expiry at strike S_i:
    Total Loss = Sum_j [ max(0, S_i - Strike_j) * Call_OI_j ] + Sum_j [ max(0, Strike_j - S_i) * Put_OI_j ]
    Max Pain Strike = argmin_{S_i} (Total Loss)
    
    CRITICAL DISCLAIMER:
    Max Pain is a descriptive statistic showing current open interest distribution.
    It is NOT a guaranteed price target and dynamic hedging can shift it rapidly.
    """
    if not strikes_data or len(strikes_data) < 3:
        return {
            "maxPainStrike": None,
            "minCumulativeLoss": None,
            "strikesEvaluated": 0,
            "isDescriptiveOnly": True,
            "disclaimer": "Insufficient strike data to calculate Max Pain.",
        }

    valid_strikes = []
    for item in strikes_data:
        strike = item.get("strike")
        ce = item.get("ce", {}) or {}
        pe = item.get("pe", {}) or {}
        ce_oi = float(ce.get("oi") or 0.0)
        pe_oi = float(pe.get("oi") or 0.0)
        if strike is not None and (ce_oi > 0 or pe_oi > 0):
            valid_strikes.append({"strike": float(strike), "ce_oi": ce_oi, "pe_oi": pe_oi})

    if not valid_strikes:
        return {
            "maxPainStrike": None,
            "minCumulativeLoss": None,
            "strikesEvaluated": 0,
            "isDescriptiveOnly": True,
            "disclaimer": "Zero open interest available for Max Pain analysis.",
        }

    strike_values = [s["strike"] for s in valid_strikes]
    min_loss = float("inf")
    max_pain_strike = strike_values[0]

    for candidate_spot in strike_values:
        total_loss = 0.0
        for s in valid_strikes:
            k = s["strike"]
            # Call buyer payoff
            call_loss = max(0.0, candidate_spot - k) * s["ce_oi"]
            # Put buyer payoff
            put_loss = max(0.0, k - candidate_spot) * s["pe_oi"]
            total_loss += call_loss + put_loss

        if total_loss < min_loss:
            min_loss = total_loss
            max_pain_strike = candidate_spot

    return {
        "maxPainStrike": round(max_pain_strike, 1),
        "minCumulativeLoss": round(min_loss, 2),
        "strikesEvaluated": len(valid_strikes),
        "isDescriptiveOnly": True,
        "disclaimer": (
            "Max Pain is a descriptive positioning statistic derived from current open interest. "
            "It reflects where option writers face minimum cumulative payoff, but does not represent a guaranteed market target."
        ),
    }
