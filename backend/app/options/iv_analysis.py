from typing import Dict, Any, List, Optional


def analyze_implied_volatility(
    strikes_data: List[Dict[str, Any]],
    underlying_ltp: float,
    vix_value: Optional[float] = None,
    vix_change_pct: Optional[float] = None
) -> Dict[str, Any]:
    """
    Evaluates Implied Volatility (IV) dynamics across strikes and correlates with India VIX.
    
    Returns:
    - ATM IV (Average of CE and PE IV at nearest ATM strike)
    - IV Skew (PE IV - CE IV at ATM): Positive skew indicates elevated downside put hedging demand
    - Volatility Regime: Low / Moderate / Elevated / High
    - Implication for option buyers vs option writers
    """
    if not strikes_data:
        return {
            "atmIv": round(vix_value or 14.0, 2),
            "ivSkew": 0.0,
            "regime": "Moderate",
            "vixValue": vix_value,
            "vixChangePercent": vix_change_pct,
            "buyerEnvironment": "Favorable",
            "sellerEnvironment": "Moderate Risk",
            "analysis": "Standard volatility conditions.",
        }

    # Find ATM strike
    nearest_strike = min(strikes_data, key=lambda s: abs(float(s.get("strike", 0)) - underlying_ltp))
    ce_iv = float(nearest_strike.get("ce", {}).get("iv") or 14.0)
    pe_iv = float(nearest_strike.get("pe", {}).get("iv") or 14.5)
    atm_iv = round((ce_iv + pe_iv) / 2.0, 2)
    iv_skew = round(pe_iv - ce_iv, 2)

    ref_vol = vix_value if vix_value is not None else atm_iv

    if ref_vol < 12.0:
        regime = "Low"
        analysis = (
            "Extremely low volatility regime. Option premiums are cheap, but directional expansion "
            "is required for long option profitability. Mean reversion risk towards higher volatility."
        )
        buyer_env = "Favorable for Long Options (Low premium cost, risk of volatility expansion)"
        seller_env = "Caution for Option Sellers (Inadequate premium compensation for tail risk)"
    elif ref_vol <= 16.5:
        regime = "Moderate"
        analysis = (
            "Healthy, standard institutional volatility range. Premiums reflect balanced market risk. "
            "Directional setups with tight risk-reward have optimal probability of follow-through."
        )
        buyer_env = "Optimal with verified momentum triggers"
        seller_env = "Balanced for structured spreads"
    elif ref_vol <= 22.0:
        regime = "Elevated"
        analysis = (
            "Elevated volatility environment. Premiums carry higher extrinsic value and wider bid-ask spreads. "
            "Sharp intraday swings common; strict stop-losses required."
        )
        buyer_env = "High theta decay risk; requires immediate momentum"
        seller_env = "Attractive credit collection with defined risk hedges"
    else:
        regime = "High / Extreme"
        analysis = (
            "Extreme market volatility or impending event risk. Significant gap and expansion risk. "
            "Naked options trading strictly discouraged."
        )
        buyer_env = "Severe premium crash (IV crush) risk upon event conclusion"
        seller_env = "Extreme risk of gamma expansion; naked selling prohibited"

    return {
        "atmIv": atm_iv,
        "ceAtmIv": ce_iv,
        "peAtmIv": pe_iv,
        "ivSkew": iv_skew,
        "regime": regime,
        "vixValue": vix_value,
        "vixChangePercent": vix_change_pct,
        "buyerEnvironment": buyer_env,
        "sellerEnvironment": seller_env,
        "analysis": analysis,
    }
