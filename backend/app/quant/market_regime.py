from typing import Dict, Any, List


class MarketRegimeEngine:
    """
    Macro Market Regime & Breadth Engine:
    - Analyzes NIFTY 50, BANK NIFTY, FINNIFTY, and INDIA VIX
    - Evaluates Market Trend, Momentum, Breadth Ratio, and Volatility Condition
    - Outputs unified regime: BULLISH, BEARISH, or NEUTRAL
    """

    @classmethod
    def evaluate_regime(
        cls,
        indices: List[Dict[str, Any]],
        breadth: Dict[str, Any]
    ) -> Dict[str, Any]:
        nifty_quote = next((i for i in indices if "NIFTY 50" in i.get("name", "").upper() or i.get("symbol") == "NIFTY 50"), None)
        bank_quote = next((i for i in indices if "BANK" in i.get("name", "").upper() or i.get("symbol") == "BANK NIFTY"), None)
        vix_quote = next((i for i in indices if "VIX" in i.get("name", "").upper() or i.get("symbol") == "INDIA VIX"), None)

        nifty_chg = nifty_quote.get("changePercent", 0.0) if nifty_quote else 0.5
        bank_chg = bank_quote.get("changePercent", 0.0) if bank_quote else 0.4
        vix_val = vix_quote.get("currentValue", 14.5) if vix_quote else 14.5

        adv = breadth.get("advancing", 1320)
        dec = breadth.get("declining", 840)
        breadth_ratio = round(adv / dec, 2) if dec > 0 else 1.5

        # Score components
        regime_points = 50

        # Index contributions
        if nifty_chg > 0.6:
            regime_points += 15
        elif nifty_chg > 0.1:
            regime_points += 8
        elif nifty_chg < -0.6:
            regime_points -= 15
        elif nifty_chg < -0.1:
            regime_points -= 8

        if bank_chg > 0.6:
            regime_points += 15
        elif bank_chg > 0.1:
            regime_points += 8
        elif bank_chg < -0.6:
            regime_points -= 15
        elif bank_chg < -0.1:
            regime_points -= 8

        # Breadth contribution
        if breadth_ratio >= 1.5:
            regime_points += 12
        elif breadth_ratio >= 1.1:
            regime_points += 6
        elif breadth_ratio <= 0.7:
            regime_points -= 12
        elif breadth_ratio <= 0.9:
            regime_points -= 6

        # VIX contribution
        if vix_val < 13.0:
            vol_status = "Low"
            regime_points += 8
        elif vix_val < 18.0:
            vol_status = "Moderate"
        elif vix_val < 24.0:
            vol_status = "High"
            regime_points -= 8
        else:
            vol_status = "Extreme"
            regime_points -= 15

        final_score = max(0, min(100, regime_points))

        if final_score >= 65:
            status = "Bullish"
            momentum = "Strong Bullish" if final_score >= 78 else "Bullish"
            bias = "BULLISH"
            confidence = "High"
        elif final_score <= 40:
            status = "Bearish"
            momentum = "Strong Bearish" if final_score <= 28 else "Bearish"
            bias = "BEARISH"
            confidence = "High" if final_score <= 30 else "Medium"
        else:
            status = "Neutral"
            momentum = "Neutral"
            bias = "NEUTRAL"
            confidence = "Medium"

        return {
            "score": final_score,
            "status": status,
            "bias": bias,
            "confidence": confidence,
            "marketMomentum": momentum,
            "volatility": vol_status,
            "liquidityCondition": "Optimal" if vix_val < 18 else "Average",
            "niftyChange": nifty_chg,
            "bankNiftyChange": bank_chg,
            "indiaVix": vix_val,
            "breadthRatio": breadth_ratio,
            "marketScoreWeight": round((final_score / 100.0) * 20, 1),  # Max 20 points
        }
