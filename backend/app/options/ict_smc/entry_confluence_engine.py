"""
Advanced Entry Confirmation & Confluence Engine (ICT + SMC).
Implements the 8-Step Institutional Confluence Pipeline:
1. Higher-Timeframe (HTF) Trend & Equilibrium Bias Alignment
2. Price approaches key Liquidity Level (BSL / SSL)
3. Liquidity Sweep with Reclaim occurs (Stop Run / Trap)
4. Strong Directional Displacement appears (Candle Body/Range >= 60%)
5. Bullish/Bearish CHoCH or Market Structure Shift (MSS) confirmed on 5M
6. Fair Value Gap (FVG) or Order Block (OB) forms
7. Price retraces into FVG Consequent Encroachment (50% CE) or OB Mean Threshold
8. 5-Minute Entry Trigger Candle confirmation

Evaluates independent execution models separately:
- Model A: Bullish Liquidity Sweep -> MSS -> FVG Retest (Call/CE)
- Model B: Bearish Liquidity Sweep -> MSS -> FVG Retest (Put/PE)
- Model C: Trend Continuation Breakout -> BOS -> Retest (Trend Follow)
- Model D: Dealing Range Reversal (Discount/Premium Boundary Exhaustion)
"""

from typing import Dict, Any, List, Optional


class EntryConfluenceEngine:
    """
    Evaluates institutional trade setups against the 8-step confluence checklist.
    """

    @classmethod
    def evaluate_confluence(
        cls,
        model_type: str,  # "MODEL_A", "MODEL_B", "MODEL_C", "MODEL_D"
        htf_alignment: bool,
        approaching_liquidity: bool,
        liquidity_sweep_confirmed: bool,
        displacement_confirmed: bool,
        choch_mss_confirmed: bool,
        fvg_or_ob_present: bool,
        retracement_into_poi: bool,
        trigger_candle_confirmed: bool,
        required_threshold: int = 5
    ) -> Dict[str, Any]:
        """
        Evaluates a model against the 8-step checklist.
        Configurable threshold (default: at least 5 of 8 criteria must be verified).
        """
        checklist = [
            {"step": 1, "name": "HTF Alignment", "passed": htf_alignment, "weight": 15, "description": "Daily/1H macro trend agrees with trade direction."},
            {"step": 2, "name": "Liquidity Approach", "passed": approaching_liquidity, "weight": 10, "description": "Price approaching external/internal liquidity pool."},
            {"step": 3, "name": "Liquidity Sweep with Reclaim", "passed": liquidity_sweep_confirmed, "weight": 15, "description": "Wick breached stops and closed back inside boundary."},
            {"step": 4, "name": "Directional Displacement", "passed": displacement_confirmed, "weight": 15, "description": "Impulsive expansion candle (body/range >= 58%)."},
            {"step": 5, "name": "CHoCH / MSS Confirmation", "passed": choch_mss_confirmed, "weight": 15, "description": "Market structure shift confirmed on 5M timeframe."},
            {"step": 6, "name": "FVG / Order Block Present", "passed": fvg_or_ob_present, "weight": 10, "description": "Institutional imbalance or order block identified."},
            {"step": 7, "name": "Retracement into POI (50% CE)", "passed": retracement_into_poi, "weight": 10, "description": "Price pulled back into FVG CE or OB threshold."},
            {"step": 8, "name": "Trigger Candle Close", "passed": trigger_candle_confirmed, "weight": 10, "description": "5M trigger candle closes directionally with rejection wick."},
        ]

        passed_count = sum(1 for c in checklist if c["passed"])
        earned_score = sum(c["weight"] for c in checklist if c["passed"])
        is_qualified = (passed_count >= required_threshold) and (earned_score >= 65)

        missing_steps = [c["name"] for c in checklist if not c["passed"]]

        return {
            "modelType": model_type,
            "isQualified": is_qualified,
            "status": "QUALIFIED" if is_qualified else "WATCHLIST_AWAITING_CONFIRMATION",
            "passedCount": passed_count,
            "totalSteps": len(checklist),
            "confluenceScore": earned_score,
            "checklist": checklist,
            "missingSteps": missing_steps,
            "summary": (
                f"{model_type} QUALIFIED with {passed_count}/8 institutional confirmations ({earned_score}/100 pts)."
                if is_qualified else
                f"{model_type} ON WATCHLIST ({passed_count}/8 confirmed). Awaiting: {', '.join(missing_steps[:2])}."
            )
        }
