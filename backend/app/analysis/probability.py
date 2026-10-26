from typing import Dict, Any


class ProbabilityEngine:
    """
    Model-estimated probability engine based on multi-factor confluence
    (Trend, RSI, Price vs EMA, Price vs VWAP, Volume, Sector, and Market Context).
    """

    @classmethod
    def calculate(
        cls,
        technical: Dict[str, Any],
        market_context: Dict[str, Any],
        sector_analysis: Dict[str, Any]
    ) -> Dict[str, int]:
        score_bullish = 50
        score_bearish = 50

        raw_tech = technical.get("raw", {})
        price = raw_tech.get("currentPrice", 1000)
        rsi = raw_tech.get("rsi", 50)
        macd_hist = raw_tech.get("macd_hist", 0)
        ema20 = raw_tech.get("ema20", price)
        vwap = raw_tech.get("vwap", price)
        vol_ratio = raw_tech.get("vol_ratio", 1.0)

        # Technical factors
        if rsi >= 60:
            score_bullish += 12
            score_bearish -= 8
        elif rsi <= 40:
            score_bearish += 12
            score_bullish -= 8

        if macd_hist > 0:
            score_bullish += 8
            score_bearish -= 5
        else:
            score_bearish += 8
            score_bullish -= 5

        if price > ema20:
            score_bullish += 10
            score_bearish -= 6
        else:
            score_bearish += 10
            score_bullish -= 6

        if price > vwap:
            score_bullish += 8
            score_bearish -= 5
        else:
            score_bearish += 8
            score_bullish -= 5

        if vol_ratio > 1.2:
            if price > ema20:
                score_bullish += 6
            else:
                score_bearish += 6

        # Market Context
        mkt_bias = market_context.get("marketBias", "NEUTRAL")
        if mkt_bias == "BULLISH":
            score_bullish += 10
            score_bearish -= 8
        elif mkt_bias == "BEARISH":
            score_bearish += 10
            score_bullish -= 8

        # Sector Relative Strength
        rel_str = sector_analysis.get("relativeStrength", "Moderate")
        if rel_str == "Strong":
            score_bullish += 8
            score_bearish -= 4
        elif rel_str == "Lagging":
            score_bearish += 8
            score_bullish -= 4

        # Normalize to probability percentages summing to 100
        total = score_bullish + score_bearish
        upside_pct = int(round((score_bullish / total) * 100))
        # Clamp within realistic model boundaries (15% to 85%)
        upside_pct = max(15, min(85, upside_pct))
        downside_pct = 100 - upside_pct

        return {
            "upside": upside_pct,
            "downside": downside_pct,
            "neutral": 0,
        }
