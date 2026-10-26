from typing import Dict, Any, List
from app.core.config import settings


class ScoringEngine:
    """
    Deterministic 100-point multi-factor quantitative scoring model:
    - Technical Strength: 30 max
    - Market Support: 20 max
    - Momentum: 15 max
    - Volume Quality: 10 max
    - Sector Strength: 10 max
    - Price Structure: 10 max
    - Volatility / Risk Quality: 5 max
    """

    @classmethod
    def evaluate(
        cls,
        technical: Dict[str, Any],
        market_context: Dict[str, Any],
        sector_analysis: Dict[str, Any]
    ) -> Dict[str, Any]:
        raw_tech = technical.get("raw", {})
        price = raw_tech.get("currentPrice", 1000)
        rsi = raw_tech.get("rsi", 50)
        macd_hist = raw_tech.get("macd_hist", 0)
        ema20 = raw_tech.get("ema20", price)
        ema50 = raw_tech.get("ema50", price)
        vwap = raw_tech.get("vwap", price)
        vol_ratio = raw_tech.get("vol_ratio", 1.0)
        roc10 = raw_tech.get("roc10", 0.0)

        # 1. Technical Strength (max 30)
        tech_score = 0
        if price >= ema20:
            tech_score += 8
        if price >= ema50:
            tech_score += 7
        if price >= vwap:
            tech_score += 8
        if macd_hist > 0:
            tech_score += 7
        tech_score = min(30, max(0, tech_score))

        # 2. Market Support (max 20)
        mkt_bias = market_context.get("marketBias", "NEUTRAL")
        mkt_conf = market_context.get("confidence", 50)
        if mkt_bias == "BULLISH":
            mkt_score = int(14 + (mkt_conf - 50) * 0.12)
        elif mkt_bias == "BEARISH":
            mkt_score = int(6 + (mkt_conf - 50) * 0.1)
        else:
            mkt_score = 10
        mkt_score = min(20, max(0, mkt_score))

        # 3. Momentum (max 15)
        mom_score = 0
        if 50 <= rsi <= 72:
            mom_score += 8
        elif rsi > 72:
            mom_score += 5  # Overbought caution
        elif 40 <= rsi < 50:
            mom_score += 4

        if roc10 > 1.5:
            mom_score += 7
        elif roc10 > 0:
            mom_score += 4
        mom_score = min(15, max(0, mom_score))

        # 4. Volume Quality (max 10)
        vol_score = 0
        if vol_ratio >= 1.3:
            vol_score = 10
        elif vol_ratio >= 1.0:
            vol_score = 8
        elif vol_ratio >= 0.7:
            vol_score = 6
        else:
            vol_score = 4

        # 5. Sector Strength (max 10)
        sec_score = min(10, max(2, sector_analysis.get("sectorScore", 7)))

        # 6. Price Structure (max 10)
        structure_sig = technical.get("priceStructure", {}).get("signal", "Neutral")
        if structure_sig == "Bullish":
            struct_score = 9
        elif structure_sig == "Neutral":
            struct_score = 6
        else:
            struct_score = 3

        # 7. Volatility / Risk Quality (max 5)
        vix_status = market_context.get("indiaVixStatus", "Moderate")
        if vix_status in ["Low", "Moderate"]:
            risk_score = 5
        elif vix_status == "High":
            risk_score = 3
        else:
            risk_score = 2

        total_score = tech_score + mkt_score + mom_score + vol_score + sec_score + struct_score + risk_score
        total_score = min(100, max(0, total_score))

        # Determine grade and setup status
        if total_score >= settings.QUALIFICATION_SCORE_THRESHOLD:
            grade = "STRONG"
            status = "Strong Bullish Setup" if price >= ema20 else "Qualified Setup"
            bias = "Bullish"
        elif total_score >= 70:
            grade = "QUALIFIED"
            status = "Qualified Setup"
            bias = "Bullish" if price >= ema20 else "Neutral"
        elif total_score >= settings.WATCH_SCORE_THRESHOLD:
            grade = "WATCH"
            status = "Watchlist / Neutral Setup"
            bias = "Neutral"
        else:
            grade = "REJECT"
            status = "High Risk / Reject Setup"
            bias = "Bearish"

        categories = [
            {"category": "Technical Strength", "score": tech_score, "maxScore": 30},
            {"category": "Market Support", "score": mkt_score, "maxScore": 20},
            {"category": "Momentum", "score": mom_score, "maxScore": 15},
            {"category": "Volume Quality", "score": vol_score, "maxScore": 10},
            {"category": "Sector Strength", "score": sec_score, "maxScore": 10},
            {"category": "Price Structure", "score": struct_score, "maxScore": 10},
            {"category": "Risk Quality", "score": risk_score, "maxScore": 5},
        ]

        return {
            "totalScore": total_score,
            "status": status,
            "grade": grade,
            "bias": bias,
            "confidence": total_score,
            "categories": categories,
        }
