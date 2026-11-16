import asyncio
from typing import List, Dict, Any
from app.services.analysis_service import AnalysisService
from app.services.stock_service import INDIAN_STOCKS_DIRECTORY
from app.quant.qualification import QualificationEngine
from app.core.cache import CacheService
from app.core.logging import logger


class SignalService:
    """
    Computes qualified Top CALL and Top PUT candidate setups.
    Enforces strict qualification criteria: NEVER forces 5+5 candidates.
    Returns only genuine setups that meet institutional risk-reward rules.
    """

    @classmethod
    async def _get_universe_analyses(cls, universe: List[str]) -> Dict[str, Dict[str, Any]]:
        results = await asyncio.gather(
            *[AnalysisService.get_analysis(sym) for sym in universe],
            return_exceptions=True
        )
        analyses = {}
        for sym, res in zip(universe, results):
            if isinstance(res, dict):
                analyses[sym] = res
            else:
                logger.warning(f"Error fetching analysis for {sym}: {res}")
        return analyses

    @classmethod
    async def get_top_call_candidates(cls) -> List[Dict[str, Any]]:
        cached = await CacheService.get("top_call_candidates")
        if cached is not None:
            return cached

        candidates = []
        universe = [s["symbol"] for s in INDIAN_STOCKS_DIRECTORY[:10]]
        analyses = await cls._get_universe_analyses(universe)

        for sym, analysis in analyses.items():
            try:
                score = analysis["analysisScore"]["totalScore"]
                current_price = analysis["currentPrice"]
                exp_high = analysis["expectedHigh"]["max"]
                s1 = next((lvl["price"] for lvl in analysis["supportResistance"] if lvl["label"] == "Support 1"), current_price * 0.985)
                vol_ratio = float(analysis["technicalIndicators"]["volume"]["currentValue"].replace("x", ""))
                mkt_bias = analysis["marketContext"].get("bias") or analysis["marketContext"].get("marketBias", "NEUTRAL")

                qual = QualificationEngine.qualify_call(score, current_price, exp_high, s1, vol_ratio, mkt_bias)

                if qual["qualified"]:
                    sparkline = [pt["price"] for pt in analysis["chartData"].get("1D", [])[-8:]]
                    if not sparkline:
                        sparkline = [current_price * (1 + (i - 4) * 0.002) for i in range(8)]

                    candidates.append({
                        "rank": 0,  # Assigned after sort
                        "symbol": sym,
                        "companyName": analysis["companyName"],
                        "exchange": analysis["exchange"],
                        "price": current_price,
                        "currentPrice": current_price,
                        "change": analysis["change"],
                        "changePercent": analysis["changePercent"],
                        "trend": analysis["trend"],
                        "signalType": "CALL",
                        "score": score,
                        "analysisScore": score,
                        "confidence": analysis["confidence"],
                        "expected_high": exp_high,
                        "expected_low": analysis["expectedLow"]["min"],
                        "expectedHigh": exp_high,
                        "expectedLow": analysis["expectedLow"]["min"],
                        "upside_probability": analysis["probabilities"]["upside"],
                        "downside_probability": analysis["probabilities"]["downside"],
                        "reason": qual.get("reason", "Institutional momentum & VWAP hold"),
                        "sparkline": sparkline,
                        "qualified": True,
                    })
            except Exception as e:
                logger.warning(f"Error evaluating CALL candidate for {sym}: {e}")

        # Sort by analysisScore descending, take up to 5
        candidates.sort(key=lambda c: c["analysisScore"], reverse=True)
        qualified_calls = candidates[:5]

        # Assign rank 1..N
        for idx, c in enumerate(qualified_calls):
            c["rank"] = idx + 1

        # Cache for 180 seconds
        await CacheService.set("top_call_candidates", qualified_calls, ttl_seconds=180)
        return qualified_calls

    @classmethod
    async def get_top_put_candidates(cls) -> List[Dict[str, Any]]:
        cached = await CacheService.get("top_put_candidates")
        if cached is not None:
            return cached

        candidates = []
        universe = [s["symbol"] for s in INDIAN_STOCKS_DIRECTORY[:10]]
        analyses = await cls._get_universe_analyses(universe)

        for sym, analysis in analyses.items():
            try:
                score = analysis["analysisScore"]["totalScore"]
                current_price = analysis["currentPrice"]
                exp_low = analysis["expectedLow"]["min"]
                r1 = next((lvl["price"] for lvl in analysis["supportResistance"] if lvl["label"] == "Resistance 1"), current_price * 1.015)
                vol_ratio = float(analysis["technicalIndicators"]["volume"]["currentValue"].replace("x", ""))
                mkt_bias = analysis["marketContext"].get("bias") or analysis["marketContext"].get("marketBias", "NEUTRAL")
                rsi = float(analysis["technicalIndicators"]["rsi"]["currentValue"])

                qual = QualificationEngine.qualify_put(score, current_price, exp_low, r1, vol_ratio, mkt_bias, rsi)

                if qual["qualified"]:
                    sparkline = [pt["price"] for pt in analysis["chartData"].get("1D", [])[-8:]]
                    if not sparkline:
                        sparkline = [current_price * (1 - (i - 4) * 0.002) for i in range(8)]

                    candidates.append({
                        "rank": 0,
                        "symbol": sym,
                        "companyName": analysis["companyName"],
                        "exchange": analysis["exchange"],
                        "price": current_price,
                        "currentPrice": current_price,
                        "change": analysis["change"],
                        "changePercent": analysis["changePercent"],
                        "trend": "Bearish",
                        "signalType": "PUT",
                        "score": score,
                        "analysisScore": score,
                        "confidence": max(60, score - 3),
                        "expected_high": analysis["expectedHigh"]["max"],
                        "expected_low": exp_low,
                        "expectedHigh": analysis["expectedHigh"]["max"],
                        "expectedLow": exp_low,
                        "upside_probability": analysis["probabilities"]["upside"],
                        "downside_probability": analysis["probabilities"]["downside"],
                        "reason": qual.get("reason", "Resistance rejection and breakdown"),
                        "sparkline": sparkline,
                        "qualified": True,
                    })
            except Exception as e:
                logger.warning(f"Error evaluating PUT candidate for {sym}: {e}")

        candidates.sort(key=lambda c: c["analysisScore"], reverse=True)
        qualified_puts = candidates[:5]

        for idx, c in enumerate(qualified_puts):
            c["rank"] = idx + 1

        await CacheService.set("top_put_candidates", qualified_puts, ttl_seconds=180)
        return qualified_puts
