from typing import Dict, Any


def calculate_pcr(
    put_oi: float,
    call_oi: float,
    put_volume: float = 0.0,
    call_volume: float = 0.0
) -> Dict[str, Any]:
    """
    Computes Put-Call Ratio (PCR) for Open Interest and Volume with precise institutional interpretation.
    
    Interpretive Rules (Indian Indices):
    - PCR > 1.30: Bullish sentiment (High put writing / strong floor). Extreme (>1.65) warns of overbought reversal risk.
    - PCR 0.85 - 1.25: Neutral / balanced consolidation zone.
    - PCR < 0.75: Bearish sentiment (High call writing / heavy ceiling). Extreme (<0.55) indicates oversold bounce potential.
    """
    pcr_oi = round(put_oi / call_oi, 2) if call_oi > 0 else 1.0
    pcr_volume = round(put_volume / call_volume, 2) if call_volume > 0 else None

    if pcr_oi >= 1.30:
        if pcr_oi > 1.65:
            sentiment = "Bullish (Overbought Warning)"
            interpretation = "Significant put writing creates a strong support floor, but extreme values suggest overextended positioning with potential for profit-booking."
            signal = "BULLISH"
        else:
            sentiment = "Bullish"
            interpretation = "Put writing comfortably exceeds call writing, indicating robust institutional support below current index prices."
            signal = "BULLISH"
    elif pcr_oi <= 0.75:
        if pcr_oi < 0.55:
            sentiment = "Bearish (Oversold Bounce Watch)"
            interpretation = "Heavy call writing dominates the strikes, indicating stiff resistance overhead, though extreme low levels may spark short-covering bounces."
            signal = "BEARISH"
        else:
            sentiment = "Bearish"
            interpretation = "Call writing noticeably outpaces put writing, reflecting institutional caution and overhead supply."
            signal = "BEARISH"
    else:
        sentiment = "Neutral"
        interpretation = "Call and Put open interest are evenly balanced. Expect range-bound consolidation between immediate support and resistance."
        signal = "NEUTRAL"

    return {
        "pcrOi": pcr_oi,
        "pcrVolume": pcr_volume,
        "sentiment": sentiment,
        "signal": signal,
        "interpretation": interpretation,
        "scopeDescription": "Calculated across active weekly and monthly index option series (Total PE OI / Total CE OI).",
        "putOiTotal": int(put_oi),
        "callOiTotal": int(call_oi),
    }
