from typing import Dict, Any, List


class ScenarioEngine:
    """
    Generates rule-grounded Bullish, Base, and Bearish scenarios
    using computed support, resistance, expected ranges, and ATR.
    """

    @classmethod
    def generate(
        cls,
        current_price: float,
        expected_range: Dict[str, Any],
        sr_levels: List[Dict[str, Any]],
        trend: str,
        atr: float
    ) -> Dict[str, Any]:
        exp_high = expected_range.get("expectedHigh") or expected_range.get("expected_high", {"min": current_price * 1.01, "max": current_price * 1.02})
        exp_low = expected_range.get("expectedLow") or expected_range.get("expected_low", {"min": current_price * 0.99, "max": current_price * 0.98})


        r1 = next((lvl["price"] for lvl in sr_levels if lvl["label"] == "Resistance 1"), round(current_price * 1.012, 2))
        r2 = next((lvl["price"] for lvl in sr_levels if lvl["label"] == "Resistance 2"), round(current_price * 1.025, 2))
        s1 = next((lvl["price"] for lvl in sr_levels if lvl["label"] == "Support 1"), round(current_price * 0.988, 2))
        s2 = next((lvl["price"] for lvl in sr_levels if lvl["label"] == "Support 2"), round(current_price * 0.975, 2))

        bullish_trigger = round(max(current_price, r1 * 0.999), 2)
        bearish_trigger = round(min(current_price, s1 * 1.001), 2)

        bullish_confidence = "High" if trend == "Bullish" else "Medium"
        bearish_confidence = "High" if trend == "Bearish" else "Low"
        base_confidence = "Medium"

        bullish_scenario = {
            "title": "Bullish Breakout & Continuation",
            "type": "bullish",
            "trigger": f"Sustained 15-min close above ₹{bullish_trigger:.2f} with volume confirmation",
            "expectedZone": f"₹{exp_high['min']:.2f} – ₹{exp_high['max']:.2f}",
            "conditions": [
                f"Price maintains acceptance above VWAP and 20 EMA",
                f"Volume expansion exceeding 1.2x 20-day average on upward pushes",
                f"NIFTY / Sector index provides supportive market breadth",
            ],
            "confidence": bullish_confidence,
            "explanation": f"A clean breakout past ₹{bullish_trigger:.2f} opens expansion towards resistance zone ₹{r2:.2f}.",
            "invalidation": f"Reversal and 15-min close below ₹{s1:.2f}",
        }

        base_scenario = {
            "title": "Intraday Range Consolidation",
            "type": "base",
            "trigger": f"Price oscillates between support ₹{s1:.2f} and resistance ₹{r1:.2f}",
            "expectedZone": f"₹{s1:.2f} – ₹{r1:.2f}",
            "conditions": [
                "Index consolidation within early morning opening range",
                "Mean-reverting tick flows around dynamic VWAP",
            ],
            "confidence": base_confidence,
            "explanation": f"Expect range-bound price action between ₹{s1:.2f} and ₹{r1:.2f} prior to directional catalyst.",
            "invalidation": f"Strong directional breakout above ₹{r1:.2f} or breakdown below ₹{s1:.2f}",
        }

        bearish_scenario = {
            "title": "Breakdown & Mean Reversion",
            "type": "bearish",
            "trigger": f"Clean breakdown below demand shelf ₹{bearish_trigger:.2f}",
            "expectedZone": f"₹{exp_low['min']:.2f} – ₹{exp_low['max']:.2f}",
            "conditions": [
                f"Consecutive lower highs and lower lows below 20 EMA",
                f"Failure to hold VWAP with institutional block selling",
            ],
            "confidence": bearish_confidence,
            "explanation": f"Breach of ₹{bearish_trigger:.2f} exposes secondary demand floor at ₹{s2:.2f}.",
            "invalidation": f"Reclaim and close back above ₹{current_price:.2f}",
        }

        outlook_changes = {
            "bullishConfirmation": f"15-minute close above ₹{bullish_trigger:.2f} with volume surge validates upside target to ₹{exp_high['max']:.2f}.",
            "bearishConfirmation": f"Loss of ₹{s1:.2f} shifts intraday bias to defensive, targeting ₹{exp_low['min']:.2f}.",
            "risks": [
                "Index volatility expansion from macro geopolitical / rate headlines",
                "Low-volume false breakout risk around pivot resistance",
                f"Intraday stop-run below immediate support ₹{s1:.2f}",
            ],
        }

        return {
            "bullishScenario": bullish_scenario,
            "baseScenario": base_scenario,
            "bearishScenario": bearish_scenario,
            "outlookChanges": outlook_changes,
        }
