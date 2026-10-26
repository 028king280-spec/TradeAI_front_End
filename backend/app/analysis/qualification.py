from typing import Dict, Any, Optional
from app.core.config import settings


class QualificationEngine:
    """
    Evaluates whether a stock setup qualifies for Top CALL or Top PUT candidate status.
    Enforces strict risk-reward, liquidity, and non-conflicting market rules.
    """

    @classmethod
    def qualify_call(
        cls,
        analysis_score: int,
        current_price: float,
        expected_high_max: float,
        support_1: float,
        market_bias: str,
        volume_ratio: float
    ) -> Dict[str, Any]:
        potential_upside = expected_high_max - current_price
        risk_downside = current_price - support_1

        # Must have positive risk-reward (at least 1.3:1)
        rr_ratio = (potential_upside / risk_downside) if risk_downside > 0 else 1.0

        is_score_ok = analysis_score >= settings.QUALIFICATION_SCORE_THRESHOLD
        is_rr_ok = rr_ratio >= 1.2
        is_market_ok = market_bias != "BEARISH"
        is_liquidity_ok = volume_ratio >= 0.8

        is_qualified = is_score_ok and is_rr_ok and is_market_ok and is_liquidity_ok

        reason = "Qualified Bullish Setup" if is_qualified else (
            "Score below qualification threshold" if not is_score_ok else (
                "Unfavorable risk-reward ratio" if not is_rr_ok else (
                    "Market bias conflicts with long exposure" if not is_market_ok else "Subdued liquidity"
                )
            )
        )

        return {
            "qualified": is_qualified,
            "signalType": "CALL",
            "riskReward": round(rr_ratio, 2),
            "reason": reason,
        }

    @classmethod
    def qualify_put(
        cls,
        analysis_score: int,
        current_price: float,
        expected_low_min: float,
        resistance_1: float,
        market_bias: str,
        volume_ratio: float,
        rsi: float
    ) -> Dict[str, Any]:
        potential_downside = current_price - expected_low_min
        risk_upside = resistance_1 - current_price

        rr_ratio = (potential_downside / risk_upside) if risk_upside > 0 else 1.0

        # PUT setup qualification: bearish conditions
        is_bearish_score = analysis_score <= 65 or rsi <= 45
        is_rr_ok = rr_ratio >= 1.2
        is_market_ok = market_bias != "BULLISH"
        is_liquidity_ok = volume_ratio >= 0.8

        is_qualified = is_bearish_score and is_rr_ok and is_market_ok and is_liquidity_ok

        # Map to 0-100 scale for candidate table display
        put_score = max(70, min(90, int(100 - analysis_score + 25))) if is_qualified else 60

        reason = "Qualified Bearish Put Setup" if is_qualified else "Criteria not satisfied for put trade"

        return {
            "qualified": is_qualified,
            "signalType": "PUT",
            "putScore": put_score,
            "riskReward": round(rr_ratio, 2),
            "reason": reason,
        }
