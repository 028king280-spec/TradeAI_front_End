from typing import List, Dict, Any, Optional


def analyze_open_interest(
    strikes_data: List[Dict[str, Any]],
    underlying_ltp: float,
    underlying_change: float = 0.0
) -> Dict[str, Any]:
    """
    Performs institutional analysis on strike-by-strike open interest (OI) and Change in OI.
    
    Identifies:
    1. Call Wall (Highest CE OI Strike -> Primary Resistance)
    2. Put Wall (Highest PE OI Strike -> Primary Support)
    3. Major CE Addition (Fresh Call Writing -> Upper Ceiling)
    4. Major PE Addition (Fresh Put Writing -> Strong Floor)
    5. Net Institutional Positioning (Long Buildup, Short Covering, etc.)
    """
    total_ce_oi = 0
    total_pe_oi = 0
    total_ce_chg_oi = 0
    total_pe_chg_oi = 0

    max_ce_oi = -1
    call_wall = None

    max_pe_oi = -1
    put_wall = None

    max_ce_add = float("-inf")
    max_ce_add_strike = None

    max_pe_add = float("-inf")
    max_pe_add_strike = None

    strike_summaries = []

    for item in strikes_data:
        strike = float(item.get("strike", 0))
        ce = item.get("ce", {}) or {}
        pe = item.get("pe", {}) or {}

        ce_oi = int(ce.get("oi") or 0)
        pe_oi = int(pe.get("oi") or 0)
        ce_chg = int(ce.get("changeInOi") or 0)
        pe_chg = int(pe.get("changeInOi") or 0)

        total_ce_oi += ce_oi
        total_pe_oi += pe_oi
        total_ce_chg_oi += ce_chg
        total_pe_chg_oi += pe_chg

        if ce_oi > max_ce_oi:
            max_ce_oi = ce_oi
            call_wall = strike

        if pe_oi > max_pe_oi:
            max_pe_oi = pe_oi
            put_wall = strike

        if ce_chg > max_ce_add:
            max_ce_add = ce_chg
            max_ce_add_strike = strike

        if pe_chg > max_pe_add:
            max_pe_add = pe_chg
            max_pe_add_strike = strike

        strike_summaries.append({
            "strike": strike,
            "ceOi": ce_oi,
            "peOi": pe_oi,
            "ceChgOi": ce_chg,
            "peChgOi": pe_chg,
            "isAtm": abs(strike - underlying_ltp) <= (underlying_ltp * 0.003),
        })

    # Buildup Classification based on Price Direction & Net OI Change
    # If price is UP and PE OI is expanding heavily: Put Writing / Bullish Support
    # If price is DOWN and CE OI is expanding heavily: Call Writing / Bearish Resistance
    if underlying_change >= 0:
        if total_pe_chg_oi > total_ce_chg_oi and total_pe_chg_oi > 0:
            positioning = "Aggressive Put Writing"
            implication = "Bullish. Market participants are writing puts, signaling expectations of sustained support."
        elif total_ce_chg_oi < 0:
            positioning = "Call Short-Covering"
            implication = "Bullish momentum driven by call sellers rushing to cover and close short positions."
        else:
            positioning = "Mild Long Buildup"
            implication = "Modest upside positioning with steady open interest accumulation."
    else:
        if total_ce_chg_oi > total_pe_chg_oi and total_ce_chg_oi > 0:
            positioning = "Aggressive Call Writing"
            implication = "Bearish. Call writers are aggressively creating ceilings at immediate overhead strikes."
        elif total_pe_chg_oi < 0:
            positioning = "Put Long-Unwinding"
            implication = "Bearish pressure as put writers are forced to surrender levels under selling momentum."
        else:
            positioning = "Short Buildup"
            implication = "Underlying index decline supported by expanding call open interest."

    return {
        "callWall": call_wall,
        "callWallOi": max_ce_oi,
        "putWall": put_wall,
        "putWallOi": max_pe_oi,
        "maxCeAdditionStrike": max_ce_add_strike,
        "maxCeAdditionOi": max_ce_add,
        "maxPeAdditionStrike": max_pe_add_strike,
        "maxPeAdditionOi": max_pe_add,
        "totalCeOi": total_ce_oi,
        "totalPeOi": total_pe_oi,
        "totalCeChgOi": total_ce_chg_oi,
        "totalPeChgOi": total_pe_chg_oi,
        "positioning": positioning,
        "implication": implication,
        "strikeSummaries": strike_summaries,
    }
