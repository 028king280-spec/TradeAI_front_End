from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
import random


class NewsProvider(ABC):
    @abstractmethod
    async def get_news_for_stock(self, symbol: str, limit: int = 5) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    async def get_market_news(self, limit: int = 10) -> List[Dict[str, Any]]:
        pass


class MockNewsProvider(NewsProvider):
    MOCK_NEWS = {
        "RELIANCE": [
            {"time": "09:45 AM", "headline": "Reliance Retail expands hyper-local distribution network across Tier-2 cities", "impact": "High", "sentiment": "Positive"},
            {"time": "Yesterday", "headline": "Jio Platforms announces enterprise AI cloud deployment partnerships", "impact": "Medium", "sentiment": "Positive"},
            {"time": "2 days ago", "headline": "Crude refiners margins steady amidst OPEC supply quota updates", "impact": "Low", "sentiment": "Neutral"},
        ],
        "TCS": [
            {"time": "10:15 AM", "headline": "TCS bags $450M multi-year digital transformation deal with European insurer", "impact": "High", "sentiment": "Positive"},
            {"time": "Yesterday", "headline": "IT sector attrition moderates to 12.1% in Q2, boosting operational margins", "impact": "Medium", "sentiment": "Positive"},
        ],
        "INFY": [
            {"time": "09:30 AM", "headline": "Infosys faces delay in discretionary tech spending from US BFSI clients", "impact": "Medium", "sentiment": "Negative"},
            {"time": "Yesterday", "headline": "Infosys Topaz platform integrates generative workflows across 40 clients", "impact": "Medium", "sentiment": "Positive"},
        ],
        "SBIN": [
            {"time": "10:00 AM", "headline": "State Bank of India advances credit growth at 15.2% YoY, maintaining NIMs", "impact": "High", "sentiment": "Positive"},
            {"time": "Yesterday", "headline": "PSU Bank index hits fresh 52-week highs on asset quality improvements", "impact": "High", "sentiment": "Positive"},
        ],
        "HDFCBANK": [
            {"time": "09:50 AM", "headline": "HDFC Bank loan-to-deposit ratio normalizes ahead of analyst target", "impact": "High", "sentiment": "Positive"},
            {"time": "Yesterday", "headline": "Private banks see robust festive credit demand in retail portfolio", "impact": "Medium", "sentiment": "Positive"},
        ],
        "MARUTI": [
            {"time": "09:20 AM", "headline": "Auto component supply bottlenecks trim monthly wholesale dispatches", "impact": "High", "sentiment": "Negative"},
            {"time": "Yesterday", "headline": "Maruti expands hybrid powertrain line-up for compact SUV category", "impact": "Medium", "sentiment": "Neutral"},
        ],
    }

    async def get_news_for_stock(self, symbol: str, limit: int = 5) -> List[Dict[str, Any]]:
        sym = symbol.upper()
        items = self.MOCK_NEWS.get(sym, [
            {
                "time": "10:00 AM",
                "headline": f"{sym} observes institutional accumulation above key technical support",
                "impact": "Medium",
                "sentiment": "Neutral"
            }
        ])
        results = []
        for idx, item in enumerate(items[:limit]):
            results.append({
                "id": f"news-{sym}-{idx+1}",
                "time": item["time"],
                "headline": item["headline"],
                "impact": item["impact"],
                "sentiment": item["sentiment"],
            })
        return results

    async def get_market_news(self, limit: int = 10) -> List[Dict[str, Any]]:
        return [
            {"id": "mn-1", "time": "10:20 AM", "headline": "FIIs turn net buyers in Indian cash equities with ₹2,140 Cr inflows", "impact": "High", "sentiment": "Positive"},
            {"id": "mn-2", "time": "09:40 AM", "headline": "RBI monetary committee retains repo rate at 6.50% with focus on growth", "impact": "High", "sentiment": "Positive"},
            {"id": "mn-3", "time": "09:15 AM", "headline": "Asian markets trade firm following robust Wall Street corporate earnings", "impact": "Medium", "sentiment": "Positive"},
        ][:limit]
