from typing import Dict, Any, List


class ScoringEngine:
    """
    Institutional 7-Factor Quantitative Scoring Engine:
    - Technical Score: max 30
    - Market Score: max 20
    - Momentum Score: max 15
    - Volume Score: max 10
    - Sector Score: max 10
    - Price Structure Score: max 10
    - Risk Score: max 5
    Total Score: 0 to 100
    """

    @classmethod
    def calculate_score(
        cls,
        technical_data: Dict[str, Any],
        market_data: Dict[str, Any],
        momentum_data: Dict[str, Any],
        volume_data: Dict[str, Any],
        sector_data: Dict[str, Any],
        price_action_data: Dict[str, Any],
        volatility_data: Dict[str, Any],
        signal_type: str = "CALL",
    ) -> Dict[str, Any]:
        is_call = signal_type.upper() == "CALL"

        # 1. Technical Score (0 to 30)
        tech_score = 0.0
        rsi = technical_data.get("rsi", {}).get("currentValue", 50.0)
        if isinstance(rsi, (int, float)):
            if is_call and rsi >= 55:
                tech_score += min(10.0, (rsi - 45) * 0.4)
            elif not is_call and rsi <= 45:
                tech_score += min(10.0, (55 - rsi) * 0.4)
            else:
                tech_score += 4.0

        if technical_data.get("macd", {}).get("signal") == ("Bullish" if is_call else "Bearish"):
            tech_score += 8.0
        else:
            tech_score += 3.0

        if technical_data.get("vwap", {}).get("signal") == ("Bullish" if is_call else "Bearish"):
            tech_score += 6.0
        else:
            tech_score += 2.0

        if technical_data.get("ema20", {}).get("signal") == ("Bullish" if is_call else "Bearish"):
            tech_score += 6.0
        else:
            tech_score += 2.0
        tech_score = min(30.0, max(0.0, tech_score))

        # 2. Market Score (0 to 20)
        mkt_score = float(market_data.get("marketScoreWeight", 12.0))
        mkt_score = min(20.0, max(0.0, mkt_score))

        # 3. Momentum Score (0 to 15)
        mom_raw = momentum_data.get("score", 50)
        mom_score = round((mom_raw / 100.0) * 15.0, 1)
        mom_score = min(15.0, max(0.0, mom_score))

        # 4. Volume Score (0 to 10)
        vol_score = float(volume_data.get("score", 6))
        vol_score = min(10.0, max(0.0, vol_score))

        # 5. Sector Score (0 to 10)
        sec_score = float(sector_data.get("sector_score", 6))
        sec_score = min(10.0, max(0.0, sec_score))

        # 6. Price Structure Score (0 to 10)
        struct_score = float(price_action_data.get("score", 6))
        if not is_call:
            # Invert breakout structure for PUT
            struct_score = 10.0 - struct_score + 2.0
        struct_score = min(10.0, max(0.0, struct_score))

        # 7. Risk Score (0 to 5)
        atr_pct = volatility_data.get("atr_percent", 2.0)
        if atr_pct <= 2.2:
            risk_score = 5.0
        elif atr_pct <= 3.5:
            risk_score = 3.5
        else:
            risk_score = 2.0

        total = round(tech_score + mkt_score + mom_score + vol_score + sec_score + struct_score + risk_score)
        total = min(100, max(15, total))

        if total >= 80:
            status_text = "Strong Institutional Conviction"
        elif total >= 70:
            status_text = "Qualified Setup"
        elif total >= 60:
            status_text = "Watchlist Monitor"
        else:
            status_text = "Neutral / Risk High"

        categories = [
            {"category": "Technical Setup", "score": round(tech_score, 1), "maxScore": 30},
            {"category": "Macro Market", "score": round(mkt_score, 1), "maxScore": 20},
            {"category": "Price Momentum", "score": round(mom_score, 1), "maxScore": 15},
            {"category": "Institutional Volume", "score": round(vol_score, 1), "maxScore": 10},
            {"category": "Sector Tailwinds", "score": round(sec_score, 1), "maxScore": 10},
            {"category": "Price Action Structure", "score": round(struct_score, 1), "maxScore": 10},
            {"category": "Risk Management", "score": round(risk_score, 1), "maxScore": 5},
        ]

        return {
            "totalScore": total,
            "status": status_text,
            "categories": categories,
        }
