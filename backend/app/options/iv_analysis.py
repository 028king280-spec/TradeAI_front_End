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
    - ATM IV (Average of CE and PE IV at nearest ATM strike, or None if market quotes unavailable)
    - IV Skew (PE IV - CE IV at ATM): Positive skew indicates elevated downside put hedging demand
    - Volatility Regime: Low / Moderate / Elevated / High / Extreme / Unavailable
    - Implication for option buyers vs option writers

    Data Integrity:
    - Never fabricates missing option IV.
    - Never presents India VIX as verified options ATM IV.
    """
    if not strikes_data:
        ref_vol = vix_value
        if ref_vol is None:
            regime = "Unavailable"
            analysis = "Options chain feed and India VIX data unavailable."
            buyer_env = "Indeterminate"
            seller_env = "Indeterminate"
        elif ref_vol < 12.0:
            regime = "Low"
            analysis = "Low volatility environment based on India VIX. Long options require rapid directional expansion."
            buyer_env = "Favorable for Long Options"
            seller_env = "Caution for Option Sellers"
        elif ref_vol <= 16.5:
            regime = "Moderate"
            analysis = "Standard volatility conditions based on India VIX."
            buyer_env = "Optimal with verified momentum triggers"
            seller_env = "Balanced for structured spreads"
        elif ref_vol <= 22.0:
            regime = "Elevated"
            analysis = "Elevated volatility based on India VIX. Expect higher premium decay."
            buyer_env = "High theta decay risk; requires immediate momentum"
            seller_env = "Attractive credit collection with defined risk hedges"
        else:
            regime = "High / Extreme"
            analysis = "Extreme market volatility or impending event risk."
            buyer_env = "Severe premium crash (IV crush) risk"
            seller_env = "Extreme risk of gamma expansion; naked selling prohibited"

        return {
            "atmIv": None,
            "ivSkew": None,
            "regime": regime,
            "vixValue": vix_value,
            "vixChangePercent": vix_change_pct,
            "buyerEnvironment": buyer_env,
            "sellerEnvironment": seller_env,
            "analysis": analysis,
        }

    # Find ATM strike
    nearest_strike = min(strikes_data, key=lambda s: abs(float(s.get("strike", 0)) - underlying_ltp))
    ce_iv_raw = nearest_strike.get("ce", {}).get("iv")
    pe_iv_raw = nearest_strike.get("pe", {}).get("iv")

    ce_iv = float(ce_iv_raw) if ce_iv_raw is not None else None
    pe_iv = float(pe_iv_raw) if pe_iv_raw is not None else None

    if ce_iv is not None and pe_iv is not None:
        atm_iv = round((ce_iv + pe_iv) / 2.0, 2)
        iv_skew = round(pe_iv - ce_iv, 2)
    elif ce_iv is not None:
        atm_iv = round(ce_iv, 2)
        iv_skew = None
    elif pe_iv is not None:
        atm_iv = round(pe_iv, 2)
        iv_skew = None
    else:
        atm_iv = None
        iv_skew = None

    ref_vol = atm_iv if atm_iv is not None else vix_value

    if ref_vol is None:
        regime = "Unavailable"
        analysis = "Verified option market IV and India VIX are unavailable. Regime indeterminate."
        buyer_env = "Indeterminate"
        seller_env = "Indeterminate"
    elif ref_vol < 12.0:
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
