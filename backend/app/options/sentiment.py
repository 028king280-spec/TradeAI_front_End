from typing import Dict, Any, List, Optional


def evaluate_options_market_sentiment(
    symbol: str,
    current_price: float,
    vwap: float,
    ema_20: float,
    ema_50: float,
    rsi_14: float,
    pcr_oi: float,
    total_ce_chg_oi: int,
    total_pe_chg_oi: int,
    vix_value: Optional[float] = None,
    day_high: Optional[float] = None,
    day_low: Optional[float] = None
) -> Dict[str, Any]:
    """
    Deterministic Quantitative Sentiment Engine for Indian Index Options.
    Aggregates multi-factor evidence across Technicals, Derivatives OI, Volatility, and Greeks.
    """
    bullish_pts = 0.0
    bearish_pts = 0.0
    supporting_factors: List[str] = []
    conflicting_factors: List[str] = []
    reasons_to_avoid: List[str] = []

    # 1. Price vs VWAP (15 pts)
    if current_price > vwap:
        bullish_pts += 15.0
        supporting_factors.append(f"Price ({current_price}) is sustaining above intraday VWAP ({vwap}), signaling institutional buyers are in control.")
    else:
        bearish_pts += 15.0
        supporting_factors.append(f"Price ({current_price}) is trading below intraday VWAP ({vwap}), signaling institutional selling pressure.")

    # 2. Moving Average Alignment (EMA 20 & EMA 50) (20 pts)
    if current_price > ema_20 > ema_50:
        bullish_pts += 20.0
        supporting_factors.append(f"Bullish moving average stack (Price > EMA20 > EMA50). Short-term momentum is aligned with the prevailing trend.")
    elif current_price < ema_20 < ema_50:
        bearish_pts += 20.0
        supporting_factors.append(f"Bearish moving average stack (Price < EMA20 < EMA50). Short-term trend is actively downward.")
    else:
        bullish_pts += 5.0
        bearish_pts += 5.0
        conflicting_factors.append("Moving averages are compressed/flat, indicating range-bound chop rather than a trending environment.")

    # 3. Momentum via RSI (15 pts)
    if rsi_14 >= 58.0:
        bullish_pts += 15.0
        supporting_factors.append(f"RSI (14) at {rsi_14:.1f} shows expanding positive momentum without reaching extreme overbought levels.")
    elif rsi_14 <= 42.0:
        bearish_pts += 15.0
        supporting_factors.append(f"RSI (14) at {rsi_14:.1f} shows decisive downward momentum.")
    else:
        bullish_pts += 5.0
        bearish_pts += 5.0
        conflicting_factors.append(f"RSI (14) is at {rsi_14:.1f} (42-58 neutral band), reflecting lack of strong directional conviction.")

    # 4. Derivatives PCR (OI) (25 pts)
    if pcr_oi >= 1.25:
        bullish_pts += 25.0
        supporting_factors.append(f"High Put-Call Ratio of {pcr_oi:.2f} confirms heavy put writing support across active strikes.")
    elif pcr_oi <= 0.75:
        bearish_pts += 25.0
        supporting_factors.append(f"Low Put-Call Ratio of {pcr_oi:.2f} confirms aggressive call writing forming a stiff overhead ceiling.")
    else:
        bullish_pts += 10.0
        bearish_pts += 10.0
        conflicting_factors.append(f"PCR is balanced at {pcr_oi:.2f}, indicating neither option buyers nor writers have decisive control.")

    # 5. Change in Open Interest Dynamics (15 pts)
    if total_pe_chg_oi > total_ce_chg_oi and total_pe_chg_oi > 0:
        bullish_pts += 15.0
        supporting_factors.append("Fresh put writing additions outpace call writing, showing institutional accumulation of support.")
    elif total_ce_chg_oi > total_pe_chg_oi and total_ce_chg_oi > 0:
        bearish_pts += 15.0
        supporting_factors.append("Fresh call writing additions outpace put writing, showing aggressive resistance capping.")
    else:
        conflicting_factors.append("Net intraday change in OI is mixed between CE and PE strikes.")

    # 6. Volatility & India VIX Assessment (10 pts)
    vix = vix_value if vix_value is not None else 13.5
    if vix < 12.0:
        reasons_to_avoid.append("India VIX is very low (<12.0). Option premiums are low, but directional follow-through may be sluggish.")
    elif vix > 22.0:
        reasons_to_avoid.append("India VIX is elevated (>22.0). Option premiums carry high extrinsic risk; sharp intraday whipsaws are likely.")

    # If conflicting factors exceed 2 or scores are closely tied
    score_diff = abs(bullish_pts - bearish_pts)
    if score_diff < 15.0:
        reasons_to_avoid.append("Market is currently exhibiting sideways compression. Buying directional options in chop leads to severe theta erosion.")

    # Determine Overall Sentiment
    if bullish_pts >= 60.0 and bullish_pts > bearish_pts + 15.0:
        sentiment = "BULLISH"
        sentiment_score = int(round(bullish_pts))
        trend_strength = "Strong" if bullish_pts >= 75.0 else "Moderate"
        confidence = "High" if len(conflicting_factors) <= 1 else "Medium"
    elif bearish_pts >= 60.0 and bearish_pts > bullish_pts + 15.0:
        sentiment = "BEARISH"
        sentiment_score = int(round(100.0 - bearish_pts))
        trend_strength = "Strong" if bearish_pts >= 75.0 else "Moderate"
        confidence = "High" if len(conflicting_factors) <= 1 else "Medium"
    else:
        sentiment = "NEUTRAL"
        sentiment_score = 50
        trend_strength = "Weak / Sideways"
        confidence = "Medium"

    trigger_high = day_high if day_high else current_price * 1.005
    trigger_low = day_low if day_low else current_price * 0.995

    return {
        "symbol": symbol.upper(),
        "overallSentiment": sentiment,
        "sentimentScore": sentiment_score,
        "trendStrength": trend_strength,
        "confidence": confidence,
        "bullishEvidenceScore": round(bullish_pts, 1),
        "bearishEvidenceScore": round(bearish_pts, 1),
        "supportingFactors": supporting_factors,
        "conflictingFactors": conflicting_factors,
        "reasonsToAvoidTrade": reasons_to_avoid,
        "confirmationLevel": f"Breakout above {round(trigger_high, 2)} for Bullish, or breakdown below {round(trigger_low, 2)} for Bearish.",
        "importantPriceTriggers": {
            "bullishConfirmation": round(trigger_high, 2),
            "bearishConfirmation": round(trigger_low, 2),
            "vwapEquilibrium": round(vwap, 2),
        },
        "criticalDerivativeNotice": (
            "IMPORTANT: Underlying index directional bias does not guarantee option profitability. "
            "Option buyers must overcome theta decay and IV fluctuations to achieve net positive returns."
        ),
    }
