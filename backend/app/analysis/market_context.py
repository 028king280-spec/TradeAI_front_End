from typing import Dict, Any, List


class MarketContextEngine:
    """
    Evaluates macro market environment using benchmark indices (NIFTY 50, BANK NIFTY,
    FINNIFTY, INDIA VIX) and market breadth to determine overarching market bias.
    """

    @classmethod
    def evaluate(
        cls,
        indices: List[Dict[str, Any]],
        breadth: Dict[str, Any]
    ) -> Dict[str, Any]:
        nifty = next((idx for idx in indices if "NIFTY 50" in idx["symbol"].upper()), None)
        bank_nifty = next((idx for idx in indices if "BANK" in idx["symbol"].upper()), None)
        vix = next((idx for idx in indices if "VIX" in idx["symbol"].upper()), None)

        nifty_change = nifty["changePercent"] if nifty else 0.0
        bank_change = bank_nifty["changePercent"] if bank_nifty else 0.0
        vix_val = vix["currentValue"] if vix else 14.0
        vix_change = vix["changePercent"] if vix else 0.0

        nifty_trend = "Bullish" if nifty_change > 0.2 else ("Bearish" if nifty_change < -0.2 else "Neutral")
        bank_trend = "Bullish" if bank_change > 0.2 else ("Bearish" if bank_change < -0.2 else "Neutral")

        # Breadth assessment
        ratio = breadth.get("ratio", 1.0)
        if ratio >= 1.5:
            breadth_status = "Positive"
        elif ratio <= 0.7:
            breadth_status = "Negative"
        else:
            breadth_status = "Neutral"

        # India VIX assessment
        if vix_val < 14.0:
            vix_status = "Low"
        elif vix_val <= 18.0:
            vix_status = "Moderate"
        elif vix_val <= 23.0:
            vix_status = "High"
        else:
            vix_status = "Elevated"

        # Overall market support score (0 to 100)
        support_score = 50
        if nifty_change > 0:
            support_score += min(20, int(nifty_change * 15))
        else:
            support_score -= min(20, int(abs(nifty_change) * 15))

        if bank_change > 0:
            support_score += min(15, int(bank_change * 12))
        else:
            support_score -= min(15, int(abs(bank_change) * 12))

        if ratio >= 1.3:
            support_score += 15
        elif ratio <= 0.8:
            support_score -= 15

        # VIX cooling is positive for trend continuation
        if vix_change < 0:
            support_score += 10
        elif vix_change > 5:
            support_score -= 10

        support_score = max(10, min(95, support_score))

        if support_score >= 68:
            market_bias = "BULLISH"
            overall_support = "Strong"
        elif support_score <= 38:
            market_bias = "BEARISH"
            overall_support = "Weak"
        else:
            market_bias = "NEUTRAL"
            overall_support = "Moderate"

        return {
            "marketBias": market_bias,
            "confidence": support_score,
            "nifty50Trend": nifty_trend,
            "bankNiftyTrend": bank_trend,
            "marketBreadthStatus": breadth_status,
            "indiaVixStatus": vix_status,
            "overallMarketSupport": overall_support,
            "raw": {
                "niftyChange": nifty_change,
                "bankChange": bank_change,
                "vixValue": vix_val,
                "vixChange": vix_change,
                "breadthRatio": ratio,
            }
        }
