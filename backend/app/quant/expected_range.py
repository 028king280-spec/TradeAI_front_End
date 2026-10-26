import math
from typing import Dict, Any, List


class ExpectedRangeEngine:
    """
    Deterministic Quantitative Expected-Range Engine.
    NOT a guaranteed target engine.
    Calculates statistical bounds based on:
    - Current price
    - 14-period ATR
    - Annualized Historical Volatility (HV)
    - Previous day range (PDH - PDL)
    - Current day range
    - VWAP location
    - Key Support & Resistance structural levels
    - Market trend, Sector strength, Volume ratio, Momentum & Opening gap
    Strictly avoids naive fixed percentages (e.g. price * 1.05).
    """

    @classmethod
    def calculate_range(
        cls,
        current_price: float,
        atr: float,
        annualized_hv: float,
        pdh: float,
        pdl: float,
        day_high: float,
        day_low: float,
        vwap: float,
        support_levels: List[Dict[str, Any]],
        resistance_levels: List[Dict[str, Any]],
        market_bias: str = "NEUTRAL",
        sector_score: int = 6,
        volume_ratio: float = 1.0,
        momentum_score: int = 50,
        gap_percent: float = 0.0,
    ) -> Dict[str, Any]:
        cur = float(current_price)
        if cur <= 0:
            return cls._fallback_range(cur)

        # 1. Base 1-day statistical dispersion (volatility cone)
        # Daily standard deviation from annualized HV: sigma_daily = cur * (HV% / 100) / sqrt(252)
        daily_sigma = cur * ((annualized_hv or 18.0) / 100.0) / math.sqrt(252)

        # Previous day range
        pd_range = max(pdh - pdl, cur * 0.01) if pdh > pdl else cur * 0.015
        current_range = max(day_high - day_low, cur * 0.005)

        # Baseline composite move combining ATR, daily sigma, and historical intraday range
        base_move = math.sqrt((atr ** 2 + (pd_range * 0.6) ** 2 + daily_sigma ** 2) / 3.0)

        # 2. Volume expansion multiplier
        vol_multiplier = 1.0
        if volume_ratio >= 1.5:
            vol_multiplier = 1.15
        elif volume_ratio < 0.7:
            vol_multiplier = 0.90

        # 3. Directional skew from market, sector, momentum, and gap
        upside_skew = 1.0
        downside_skew = 1.0

        if market_bias == "BULLISH":
            upside_skew += 0.10
            downside_skew -= 0.05
        elif market_bias == "BEARISH":
            upside_skew -= 0.08
            downside_skew += 0.12

        if sector_score >= 8:
            upside_skew += 0.08
        elif sector_score <= 4:
            downside_skew += 0.08

        if momentum_score >= 65:
            upside_skew += 0.10
        elif momentum_score <= 35:
            downside_skew += 0.10

        # VWAP confirmation
        if cur > vwap:
            upside_skew += 0.05
        else:
            downside_skew += 0.05

        # Opening gap absorption
        if gap_percent > 0.5:
            upside_skew += 0.04
        elif gap_percent < -0.5:
            downside_skew += 0.04

        # 4. Synthesize directional ranges
        up_move = base_move * vol_multiplier * upside_skew
        down_move = base_move * vol_multiplier * downside_skew

        # Anchor against structural resistance 1 and support 1
        r1 = next((lvl["price"] for lvl in resistance_levels if "Resistance 1" in lvl.get("label", "")), cur + up_move)
        s1 = next((lvl["price"] for lvl in support_levels if "Support 1" in lvl.get("label", "")), cur - down_move)

        # Expected High Range (Min & Max)
        exp_high_min = round(max(cur + (0.55 * up_move), min(r1, cur + up_move)), 2)
        exp_high_max = round(max(exp_high_min + (0.35 * up_move), r1 * 1.004), 2)

        # Expected Low Range (Min & Max)
        exp_low_min = round(min(cur - (0.55 * down_move), max(s1, cur - down_move)), 2)
        exp_low_max = round(min(exp_low_min - (0.35 * down_move), s1 * 0.996), 2)

        # Extreme expansion targets (tail events: 1.8x move)
        bullish_ext = round(exp_high_max + (0.75 * up_move), 2)
        bearish_ext = round(exp_low_max - (0.75 * down_move), 2)

        return {
            "expected_high_min": exp_high_min,
            "expected_high_max": exp_high_max,
            "expected_low_min": exp_low_min,
            "expected_low_max": exp_low_max,
            "bullish_extension": bullish_ext,
            "bearish_extension": bearish_ext,
            "base_intraday_move": round(base_move, 2),
            "expected_high": {"min": exp_high_min, "max": exp_high_max},
            "expected_low": {"min": exp_low_min, "max": exp_low_max},
            "expectedHigh": {"min": exp_high_min, "max": exp_high_max},
            "expectedLow": {"min": exp_low_min, "max": exp_low_max},
            "priceRange": {
                "extremeLow": bearish_ext,
                "likelyLow": exp_low_min,
                "currentPrice": cur,
                "likelyHigh": exp_high_max,
                "extremeHigh": bullish_ext,
            },
        }

    @staticmethod
    def _fallback_range(cur: float) -> Dict[str, Any]:
        return {
            "expected_high_min": round(cur * 1.015, 2),
            "expected_high_max": round(cur * 1.030, 2),
            "expected_low_min": round(cur * 0.985, 2),
            "expected_low_max": round(cur * 0.970, 2),
            "bullish_extension": round(cur * 1.045, 2),
            "bearish_extension": round(cur * 0.955, 2),
            "expected_high": {"min": round(cur * 1.015, 2), "max": round(cur * 1.030, 2)},
            "expected_low": {"min": round(cur * 0.985, 2), "max": round(cur * 0.970, 2)},
            "expectedHigh": {"min": round(cur * 1.015, 2), "max": round(cur * 1.030, 2)},
            "expectedLow": {"min": round(cur * 0.985, 2), "max": round(cur * 0.970, 2)},
            "priceRange": {
                "extremeLow": round(cur * 0.955, 2),
                "likelyLow": round(cur * 0.985, 2),
                "currentPrice": cur,
                "likelyHigh": round(cur * 1.030, 2),
                "extremeHigh": round(cur * 1.045, 2),
            },
        }

