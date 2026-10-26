from typing import Dict, Any, List


class SectorAnalysisEngine:
    """
    Evaluates industry sector strength and compares stock performance
    against its sector benchmark.
    """

    @classmethod
    def evaluate(
        cls,
        stock_sector: str,
        stock_change_pct: float,
        sector_data: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        matched_sector = None
        for s in sector_data:
            if s["sector"].lower() in stock_sector.lower() or stock_sector.lower() in s["sector"].lower():
                matched_sector = s
                break

        if not matched_sector:
            # Fallback default sector
            matched_sector = {
                "sector": stock_sector,
                "performancePercent": 0.5,
                "strength": "Moderate",
                "topStock": f"{stock_sector} Leaders",
            }

        sec_perf = float(matched_sector.get("performancePercent", 0.0))
        sec_trend = "Bullish" if sec_perf > 0.3 else ("Bearish" if sec_perf < -0.3 else "Neutral")

        # Relative strength: stock vs sector
        perf_diff = stock_change_pct - sec_perf
        if perf_diff > 0.5:
            rel_strength = "Strong"
            comparison = f"Outperforming sector by {perf_diff:+.2f}% with leading momentum"
            sector_score = 9
        elif perf_diff >= -0.2:
            rel_strength = "Moderate"
            comparison = f"Tracking sector in-line ({perf_diff:+.2f}% spread)"
            sector_score = 7
        elif perf_diff >= -0.8:
            rel_strength = "Neutral"
            comparison = f"Consolidating behind sector pace ({perf_diff:+.2f}% spread)"
            sector_score = 5
        else:
            rel_strength = "Lagging"
            comparison = f"Underperforming sector by {abs(perf_diff):.2f}%"
            sector_score = 3

        return {
            "sectorName": matched_sector["sector"],
            "sectorTrend": sec_trend,
            "sectorPerformance": sec_perf,
            "relativeStrength": rel_strength,
            "stockVsSector": comparison,
            "sectorScore": sector_score,
        }
