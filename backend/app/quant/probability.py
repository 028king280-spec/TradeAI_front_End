from typing import Dict, Any
import numpy as np


class ProbabilityEngine:
    """
    Model-Estimated Probability Engine:
    - Synthesizes measurable quantitative features:
      * Trend & RSI momentum
      * MACD histogram direction
      * VWAP holding status
      * Institutional volume confirmation
      * Price action breakout/breakdown state
      * Macro market regime & Sector alpha
    - Uses softmax distribution ensuring:
      upside_probability + downside_probability + neutral_probability == 100%
    - Strictly labeled as MODEL ESTIMATES, never guaranteed certainty.
    """

    @classmethod
    def estimate_probabilities(
        cls,
        rsi: float,
        is_above_vwap: bool,
        is_breakout: bool,
        is_breakdown: bool,
        volume_ratio: float,
        momentum_score: int,
        market_bias: str,
        sector_score: int,
    ) -> Dict[str, int]:
        # Feature scoring for directional logits
        up_weight = 0.0
        down_weight = 0.0

        # 1. RSI
        if rsi >= 60:
            up_weight += (rsi - 50) * 0.08
        elif rsi <= 40:
            down_weight += (50 - rsi) * 0.08

        # 2. VWAP
        if is_above_vwap:
            up_weight += 0.8
        else:
            down_weight += 0.8

        # 3. Breakout / Breakdown
        if is_breakout:
            up_weight += 1.4
        elif is_breakdown:
            down_weight += 1.4

        # 4. Volume confirmation
        if volume_ratio >= 1.5:
            if up_weight > down_weight:
                up_weight += 0.9
            else:
                down_weight += 0.9

        # 5. Momentum score (0 to 100)
        up_weight += (momentum_score - 50) * 0.03

        # 6. Market bias
        if market_bias == "BULLISH":
            up_weight += 0.7
            down_weight -= 0.3
        elif market_bias == "BEARISH":
            down_weight += 0.7
            up_weight -= 0.3

        # 7. Sector score
        up_weight += (sector_score - 5) * 0.15

        # Neutral weight is based on balance / consolidation
        neutral_weight = 0.5 + max(0.0, 1.2 - abs(up_weight - down_weight))

        # Softmax normalization
        logits = np.array([up_weight, down_weight, neutral_weight])
        exp_logits = np.exp(logits - np.max(logits))
        probs = exp_logits / np.sum(exp_logits)

        # Convert to percentage integers summing to 100
        up_pct = int(round(probs[0] * 100))
        down_pct = int(round(probs[1] * 100))
        neutral_pct = 100 - (up_pct + down_pct)

        # Sanity bound
        if neutral_pct < 5:
            diff = 5 - neutral_pct
            neutral_pct = 5
            if up_pct >= down_pct:
                up_pct = max(0, up_pct - diff)
            else:
                down_pct = max(0, down_pct - diff)

        # Ensure exact 100 sum
        down_pct = 100 - (up_pct + neutral_pct)

        return {
            "upside": up_pct,
            "downside": down_pct,
            "neutral": neutral_pct,
            "upside_probability": up_pct,
            "downside_probability": down_pct,
            "neutral_probability": neutral_pct,
        }

