import hashlib
import json
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List
import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from app.data.providers.factory import get_market_data_provider
from app.data.financial_news_provider import get_financial_news_provider
from app.data.market_calendar import MarketCalendar
from app.quant.indicators import TechnicalIndicators
from app.quant.momentum import MomentumAnalyzer
from app.quant.volatility import VolatilityAnalyzer
from app.quant.volume import VolumeAnalyzer
from app.quant.price_action import PriceActionAnalyzer
from app.quant.support_resistance import SupportResistanceEngine
from app.quant.market_regime import MarketRegimeEngine
from app.quant.sector_strength import SectorStrengthEngine
from app.quant.expected_range import ExpectedRangeEngine
from app.quant.probability import ProbabilityEngine
from app.quant.scoring import ScoringEngine
from app.quant.qualification import QualificationEngine
from app.analysis.scenarios import ScenarioEngine
from app.ai.grounded_explainer import GroundedAIExplainer
from app.rag.vector_store import VectorStoreService
from app.core.cache import CacheService
from app.core.logging import logger


class AnalysisService:
    """
    Main quantitative analysis orchestrator. Executes the deterministic pipeline:
    REAL DATA -> NORMALIZATION -> QUANT INDICATORS -> MOMENTUM & VOLATILITY ->
    PRICE ACTION & S/R -> MARKET REGIME -> SECTOR ALPHA -> EXPECTED RANGE ->
    MODEL PROBABILITIES -> 7-FACTOR SCORING -> AI EXPLANATION -> RESPONSE
    """

    @classmethod
    async def get_analysis(
        cls,
        symbol: str,
        session: Optional[AsyncSession] = None
    ) -> Dict[str, Any]:
        sym = symbol.upper()
        cache_key = f"stock_analysis:{sym}"
        cached = await CacheService.get(cache_key)
        if cached:
            return cached

        provider = get_market_data_provider()
        news_provider = get_financial_news_provider()

        # 1. Fetch Quote & Candles (unavailable states remain explicit)
        quote = await provider.get_quote(sym)
        raw_ltp = quote.get("currentPrice") if quote.get("currentPrice") is not None else quote.get("ltp")
        current_price = float(raw_ltp) if raw_ltp is not None else 0.0
        open_price = float(quote.get("openPrice") or quote.get("open", current_price))
        prev_close = float(quote.get("previousClose") or quote.get("close", current_price))
        day_high = float(quote.get("dayHigh") or quote.get("high", current_price))
        day_low = float(quote.get("dayLow") or quote.get("low", current_price))

        to_dt = datetime.now(timezone.utc)
        from_dt = to_dt - timedelta(days=220)  # Sufficient for 200 EMA
        df_daily = await provider.get_historical_candles(sym, "1d", from_dt, to_dt)
        df_intraday = await provider.get_intraday_candles(sym, "15m")

        # 2. Python Quant Engine Calculations
        technical = TechnicalIndicators.compute_all_indicators(df_daily)
        momentum = MomentumAnalyzer.analyze_momentum(df_daily)
        volatility = VolatilityAnalyzer.analyze_volatility(df_daily)
        volume_eval = VolumeAnalyzer.analyze_volume(df_daily)
        price_action = PriceActionAnalyzer.analyze_structure(df_daily)

        # 3. Support & Resistance Structural Levels
        sr_levels = SupportResistanceEngine.calculate_levels(df_daily)

        # 4. Market Context & Sector Analysis
        indices = await provider.get_all_indices()
        breadth = await provider.get_market_breadth()
        market_ctx = MarketRegimeEngine.evaluate_regime(indices, breadth)

        sector_data = await provider.get_sector_data()
        stock_sector = quote.get("sector", "Diversified")
        sector_eval = SectorStrengthEngine.evaluate_sector(sym, quote.get("changePercent", 0.0), sector_data)

        # Trend Determination
        trend = "Bullish" if current_price >= technical["ema20"]["currentValue"] and technical["rsi"]["currentValue"] >= 50 else (
            "Bearish" if current_price < technical["ema20"]["currentValue"] and technical["rsi"]["currentValue"] < 45 else "Neutral"
        )

        # 5. Deterministic Expected High & Low Range Engine
        expected_range = ExpectedRangeEngine.calculate_range(
            current_price=current_price,
            atr=technical["atr"]["currentValue"],
            annualized_hv=volatility["annualized_hv"],
            pdh=price_action["pdh"],
            pdl=price_action["pdl"],
            day_high=day_high,
            day_low=day_low,
            vwap=technical["vwap"]["currentValue"],
            support_levels=sr_levels,
            resistance_levels=sr_levels,
            market_bias=market_ctx["bias"],
            sector_score=sector_eval["sector_score"],
            volume_ratio=volume_eval["volume_ratio"],
            momentum_score=momentum["score"],
            gap_percent=price_action["gap_percent"],
        )

        # 6. Model-Estimated Probabilities & Scenarios
        probabilities = ProbabilityEngine.estimate_probabilities(
            rsi=technical["rsi"]["currentValue"],
            is_above_vwap=current_price >= technical["vwap"]["currentValue"],
            is_breakout=price_action["is_breakout"],
            is_breakdown=price_action["is_breakdown"],
            volume_ratio=volume_eval["volume_ratio"],
            momentum_score=momentum["score"],
            market_bias=market_ctx["bias"],
            sector_score=sector_eval["sector_score"],
        )
        scenarios = ScenarioEngine.generate(current_price, expected_range, sr_levels, trend, technical["atr"]["currentValue"])

        # 7. 7-Factor Institutional Scoring
        score_eval = ScoringEngine.calculate_score(
            technical_data=technical,
            market_data=market_ctx,
            momentum_data=momentum,
            volume_data=volume_eval,
            sector_data=sector_eval,
            price_action_data=price_action,
            volatility_data=volatility,
            signal_type="CALL" if probabilities["upside"] >= probabilities["downside"] else "PUT",
        )
        analysis_score = score_eval["totalScore"]

        # 8. Volume Analysis
        if not df_daily.empty and "volume" in df_daily.columns:
            raw_vol_avg = df_daily["volume"].rolling(20).mean().iloc[-1] if len(df_daily) >= 20 else df_daily["volume"].mean()
            vol_avg20 = float(raw_vol_avg) if pd.notna(raw_vol_avg) else 0.0
        else:
            vol_avg20 = 0.0
        vol_ratio = volume_eval["volume_ratio"]
        vol_trend = "Surging" if vol_ratio >= 1.5 else ("Above Average" if vol_ratio >= 1.1 else ("Average" if vol_ratio >= 0.8 else "Below Average"))

        intraday_bars = []
        if not df_intraday.empty:
            for idx, row in df_intraday.tail(16).iterrows():
                intraday_bars.append({
                    "time": row.get("time", str(row["timestamp"])[:5]),
                    "volume": int(row["volume"]),
                    "isUp": bool(row["close"] >= row["open"]),
                })

        vol_val = float(quote.get('volume') or 0)
        vol_analysis = {
            "currentVolume": f"{vol_val / 1000000:.2f}M" if vol_val >= 1000000 else f"{int(vol_val / 1000)}K",
            "averageVolume": f"{vol_avg20 / 1000000:.2f}M" if vol_avg20 >= 1000000 else f"{int(vol_avg20 / 1000)}K",
            "volumeRatio": vol_ratio,
            "volumeTrend": vol_trend,
            "intradayBars": intraday_bars,
        }

        # 9. News Events (Live Financial RSS)
        raw_news = await news_provider.get_news_for_stock(sym, limit=4)
        news_items = []
        for n in raw_news:
            sent_raw = str(n.get("sentiment", "NEUTRAL")).upper()
            sent_map = {"BULLISH": "Positive", "BEARISH": "Negative", "NEUTRAL": "Neutral"}
            sentiment = sent_map.get(sent_raw, "Neutral")
            impact_raw = str(n.get("impact", "Medium")).capitalize()
            news_items.append({
                "id": str(n.get("id", f"news-{abs(hash(n.get('headline','')))}")),
                "time": str(n.get("publishedAt") or "Recent"),
                "headline": str(n.get("headline", "")),
                "impact": impact_raw if impact_raw in ["High", "Medium", "Low"] else "Medium",
                "sentiment": sentiment,
                "source": str(n.get("source", "Financial News")),
                "url": str(n.get("url", "")),
            })

        # 10. Module 7 RAG Knowledge Search
        rag_chunks = []
        if session:
            try:
                rag_chunks = await VectorStoreService.search(session, f"{sym} {stock_sector} technical momentum", top_k=2)
            except Exception as e:
                logger.warning(f"RAG search error for {sym}: {e}")

        # 11. Grounded AI Explanation
        ai_insights = await GroundedAIExplainer.explain(
            symbol=sym,
            company_name=quote["companyName"],
            current_price=current_price,
            trend=trend,
            score=analysis_score,
            technical=technical,
            expected_range=expected_range,
            probabilities=probabilities,
            market_context=market_ctx,
            sector_analysis=sector_eval,
            scenarios=scenarios,
            rag_chunks=rag_chunks,
        )

        # 12. Chart Data Generation
        chart_data = cls._generate_chart_data(df_intraday, df_daily, current_price, expected_range, sr_levels)

        # Assemble full analytical payload
        payload = {
            "symbol": sym,
            "companyName": quote.get("companyName", sym),
            "exchange": quote.get("exchange", "NSE"),
            "category": quote.get("category", "Large Cap"),
            "sector": stock_sector,
            "currentPrice": current_price,
            "change": quote.get("change", 0.0),
            "changePercent": quote.get("changePercent", 0.0),
            "dayHigh": day_high,
            "dayLow": day_low,
            "volume": vol_analysis["currentVolume"],
            "analysisTimestamp": MarketCalendar.format_ist_timestamp(),
            "trend": trend,
            "analysisScore": {
                "totalScore": analysis_score,
                "status": score_eval["status"],
                "categories": score_eval["categories"],
            },
            "confidence": analysis_score,
            "expectedHigh": expected_range["expectedHigh"],
            "expectedLow": expected_range["expectedLow"],
            "probabilities": probabilities,
            "currentBias": trend,
            "priceRange": expected_range["priceRange"],
            "bullishScenario": scenarios["bullishScenario"],
            "baseScenario": scenarios["baseScenario"],
            "bearishScenario": scenarios["bearishScenario"],
            "outlookChanges": scenarios["outlookChanges"],
            "supportResistance": sr_levels,
            "technicalIndicators": technical,
            "volumeAnalysis": vol_analysis,
            "marketContext": {
                **market_ctx,
                "nifty50Trend": "Bullish" if market_ctx.get("niftyChange", 0) > 0.1 else ("Bearish" if market_ctx.get("niftyChange", 0) < -0.1 else "Neutral"),
                "bankNiftyTrend": "Bullish" if market_ctx.get("bankNiftyChange", 0) > 0.1 else ("Bearish" if market_ctx.get("bankNiftyChange", 0) < -0.1 else "Neutral"),
                "marketBreadthStatus": "Positive" if market_ctx.get("breadthRatio", 1) >= 1.1 else ("Negative" if market_ctx.get("breadthRatio", 1) <= 0.9 else "Neutral"),
                "indiaVixStatus": market_ctx.get("volatility", "Moderate"),
                "overallMarketSupport": "Strong" if market_ctx.get("bias") == "BULLISH" else ("Weak" if market_ctx.get("bias") == "BEARISH" else "Moderate"),
            },
            "sectorAnalysis": {
                **sector_eval,
                "relativeStrength": sector_eval.get("relativeStrength") or sector_eval.get("relative_strength", "Neutral"),
            },
            "news": news_items,
            "aiInsights": ai_insights,
            "summary": (
                f"{quote.get('companyName', sym)} ({sym}) is in a {trend.lower()} regime at ₹{current_price:.2f}. "
                f"Quantitative score is {analysis_score}/100 ({score_eval['status']}). "
                f"Expected high range: ₹{expected_range['expectedHigh']['min']:.2f}–₹{expected_range['expectedHigh']['max']:.2f}; "
                f"Expected low range: ₹{expected_range['expectedLow']['min']:.2f}–₹{expected_range['expectedLow']['max']:.2f}."
            ),
            "chartData": chart_data,
            "dataStatus": quote.get("dataStatus", "UNAVAILABLE"),
            "dataTimestamp": quote.get("timestamp"),
        }

        # Cache for 45 seconds during market hours
        await CacheService.set(cache_key, payload, ttl_seconds=45)
        return payload

    @classmethod
    def _generate_chart_data(
        cls,
        df_intraday: pd.DataFrame,
        df_daily: pd.DataFrame,
        current_price: float,
        expected_range: Dict[str, Any],
        sr_levels: List[Dict[str, Any]]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Formats multi-timeframe candle points (1D, 5D, 1M, 3M, 6M, 1Y)
        with VWAP, EMA20, EMA50, expected boundaries, and key levels.
        """
        r1 = next((lvl["price"] for lvl in sr_levels if lvl["label"] == "Resistance 1"), current_price * 1.015)
        s1 = next((lvl["price"] for lvl in sr_levels if lvl["label"] == "Support 1"), current_price * 0.985)
        exp_high = expected_range["expectedHigh"]["max"]
        exp_low = expected_range["expectedLow"]["min"]

        def df_to_points(df: pd.DataFrame, is_intraday: bool = False) -> List[Dict[str, Any]]:
            points = []
            if df.empty:
                return points
            df_reset = df.reset_index(drop=True)
            close = df_reset["close"]
            ema20 = TechnicalIndicators.calculate_ema(close, 20)
            ema50 = TechnicalIndicators.calculate_ema(close, 50)
            vwap = TechnicalIndicators.calculate_vwap(df_reset)


            for i in range(len(df_reset)):
                row = df_reset.iloc[i]
                t_label = row.get("time") if is_intraday and "time" in row else str(row["timestamp"])[:10]
                points.append({
                    "time": t_label,
                    "price": round(float(row["close"]), 2),
                    "vwap": round(float(vwap.iloc[i]), 2),
                    "ema20": round(float(ema20.iloc[i]), 2),
                    "ema50": round(float(ema50.iloc[i]), 2),
                    "volume": int(row["volume"]),
                    "support": s1,
                    "resistance": r1,
                    "expectedHigh": exp_high,
                    "expectedLow": exp_low,
                })
            return points

        points_1d = df_to_points(df_intraday, is_intraday=True) if not df_intraday.empty else []
        points_5d = df_to_points(df_daily.tail(5))
        points_1m = df_to_points(df_daily.tail(22))
        points_3m = df_to_points(df_daily.tail(66))
        points_6m = df_to_points(df_daily.tail(132))
        points_1y = df_to_points(df_daily.tail(250))

        return {
            "1D": points_1d,
            "5D": points_5d,
            "1M": points_1m,
            "3M": points_3m,
            "6M": points_6m,
            "1Y": points_1y,
        }
