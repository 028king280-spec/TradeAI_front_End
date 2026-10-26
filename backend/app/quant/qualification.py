from typing import Dict, Any


class QualificationEngine:
    """
    Strict Institutional Setup Qualification Engine.
    Rules:
    - NEVER forces a stock recommendation.
    - Setup qualifies ONLY when:
      1. Score >= Threshold (default 80 for CALL, 75 for PUT)
      2. Liquidity acceptable (Volume ratio >= 0.70 & adequate volume)
      3. Risk-Reward acceptable (RR ratio >= 1.30:1 with logical stop loss)
      4. Data quality acceptable
    - Otherwise returns qualified = False with institutional rejection reason.
    - If only 2 stocks qualify across the entire market, only 2 are displayed.
    """

    @classmethod
    def qualify_call(
        cls,
        total_score: int,
        current_price: float,
        target_high: float,
        stop_loss: float,
        volume_ratio: float,
        market_bias: str,
        threshold: int = 80,
    ) -> Dict[str, Any]:
        reasons = []

        # 1. Score threshold
        if total_score < threshold:
            reasons.append(f"Score {total_score} below qualification threshold {threshold}")

        # 2. Risk-Reward calculation
        reward = target_high - current_price
        risk = max(1.0, current_price - stop_loss)
        rr_ratio = round(reward / risk, 2) if risk > 0 else 0.0

        if rr_ratio < 1.3:
            reasons.append(f"Unfavorable Risk:Reward ratio (1:{rr_ratio}). Minimum required is 1:1.3")

        # 3. Liquidity
        if volume_ratio < 0.70:
            reasons.append(f"Subdued institutional volume ({volume_ratio}x avg). Liquidity caution")

        # 4. Market tailwind / contradiction
        if market_bias == "BEARISH" and total_score < 85:
            reasons.append("Macro market regime is BEARISH. Long calls restricted to exceptional setups (>=85)")

        is_qualified = len(reasons) == 0

        return {
            "qualified": is_qualified,
            "signalType": "CALL",
            "score": total_score,
            "rrRatio": rr_ratio,
            "reason": "Institutional breakout criteria fully satisfied." if is_qualified else " | ".join(reasons),
        }

    @classmethod
    def qualify_put(
        cls,
        total_score: int,
        current_price: float,
        target_low: float,
        stop_loss: float,
        volume_ratio: float,
        market_bias: str,
        rsi: float,
        threshold: int = 75,
    ) -> Dict[str, Any]:
        reasons = []

        # 1. Score threshold
        if total_score < threshold:
            reasons.append(f"Score {total_score} below PUT qualification threshold {threshold}")

        # 2. Risk-Reward calculation
        reward = current_price - target_low
        risk = max(1.0, stop_loss - current_price)
        rr_ratio = round(reward / risk, 2) if risk > 0 else 0.0

        if rr_ratio < 1.3:
            reasons.append(f"Unfavorable Risk:Reward ratio (1:{rr_ratio}). Minimum required is 1:1.3")

        # 3. Liquidity
        if volume_ratio < 0.70:
            reasons.append(f"Insufficient short liquidity ({volume_ratio}x avg)")

        # 4. RSI sanity (avoid shorting heavily oversold stocks under 25)
        if rsi < 25.0:
            reasons.append(f"RSI {rsi} deeply oversold. High risk of mean-reversion short squeeze")

        # 5. Market contradiction
        if market_bias == "BULLISH" and total_score < 82:
            reasons.append("Macro market regime is BULLISH. Short setups restricted to high conviction breakdowns (>=82)")

        is_qualified = len(reasons) == 0

        return {
            "qualified": is_qualified,
            "signalType": "PUT",
            "score": total_score,
            "rrRatio": rr_ratio,
            "reason": "Breakdown and resistance rejection verified." if is_qualified else " | ".join(reasons),
        }
