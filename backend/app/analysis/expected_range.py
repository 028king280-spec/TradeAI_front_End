from typing import Dict, Any
import numpy as np


class ExpectedRangeEngine:
    """
    Calculates deterministic probability-based expected intraday range
    combining ATR, intraday expansion, VWAP deviations, directional momentum,
    and market/sector bias.
    """

    @classmethod
    def calculate(
        cls,
        current_price: float,
        open_price: float,
        previous_close: float,
        day_high: float,
        day_low: float,
        atr: float,
        vwap: float,
        trend: str,
        market_bias: str,
        rsi: float
    ) -> Dict[str, Any]:
        # Guard against zero or corrupted ATR
        effective_atr = max(atr, current_price * 0.012)

        # Baseline expected remaining intraday move (fraction of daily ATR)
        base_range = effective_atr * 0.85

        # Directional skew multiplier
        bullish_skew = 1.0
        bearish_skew = 1.0

        if trend == "Bullish":
            bullish_skew += 0.25
            bearish_skew -= 0.15
        elif trend == "Bearish":
            bullish_skew -= 0.15
            bearish_skew += 0.25

        if market_bias == "BULLISH":
            bullish_skew += 0.15
            bearish_skew -= 0.10
        elif market_bias == "BEARISH":
            bullish_skew -= 0.10
            bearish_skew += 0.15

        # RSI momentum adjustment
        if rsi > 65:
            bullish_skew += 0.10
        elif rsi < 35:
            bearish_skew += 0.10

        # Price relative to VWAP adjustment
        if current_price > vwap:
            bullish_skew += 0.08
        else:
            bearish_skew += 0.08

        # Calculate likely ranges
        # High Range: from min expected high to max expected high
        high_min = max(current_price * 1.004, max(day_high, current_price + (base_range * 0.35 * bullish_skew)))
        high_max = max(high_min * 1.003, current_price + (base_range * 0.85 * bullish_skew))

        # Low Range: from min expected low to max expected low
        low_max = min(current_price * 0.996, min(day_low, current_price - (base_range * 0.35 * bearish_skew)))
        low_min = min(low_max * 0.997, current_price - (base_range * 0.85 * bearish_skew))

        # Extremes (2.0 standard ATR deviation under tail scenarios)
        extreme_high = round(max(high_max * 1.005, current_price + (effective_atr * 1.4 * bullish_skew)), 2)
        extreme_low = round(min(low_min * 0.995, current_price - (effective_atr * 1.4 * bearish_skew)), 2)

        likely_high_min = round(high_min, 2)
        likely_high_max = round(high_max, 2)
        likely_low_min = round(low_min, 2)
        likely_low_max = round(low_max, 2)

        return {
            "expectedHigh": {
                "min": likely_high_min,
                "max": likely_high_max,
            },
            "expectedLow": {
                "min": likely_low_min,
                "max": likely_low_max,
            },
            "priceRange": {
                "extremeLow": extreme_low,
                "likelyLow": likely_low_min,
                "currentPrice": round(current_price, 2),
                "likelyHigh": likely_high_max,
                "extremeHigh": extreme_high,
            }
        }
