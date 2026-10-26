from typing import List, Dict, Any
from app.data.providers.factory import get_market_data_provider
from app.data.market_calendar import MarketCalendar
from app.core.cache import CacheService


class MarketService:
    @classmethod
    async def get_indices(cls) -> List[Dict[str, Any]]:
        cached = await CacheService.get("market_indices")
        if cached:
            return cached

        provider = get_market_data_provider()
        indices = await provider.get_all_indices()
        await CacheService.set("market_indices", indices, ttl_seconds=30)
        return indices

    @classmethod
    async def get_market_sentiment(cls) -> Dict[str, Any]:
        cached = await CacheService.get("market_sentiment")
        if cached:
            return cached

        provider = get_market_data_provider()
        breadth = await provider.get_market_breadth()
        indices = await provider.get_all_indices()

        nifty = next((idx for idx in indices if "NIFTY 50" in idx["symbol"]), None)
        nifty_change = nifty["changePercent"] if nifty else 0.55

        sentiment_score = int(min(92, max(25, 50 + (breadth["ratio"] - 1.0) * 20 + nifty_change * 15)))
        status = "Bullish" if sentiment_score >= 65 else ("Bearish" if sentiment_score <= 40 else "Neutral")
        momentum = "Strong Bullish" if sentiment_score >= 75 else ("Bullish" if sentiment_score >= 60 else "Neutral")

        result = {
            "score": sentiment_score,
            "status": status,
            "confidence": "High" if abs(sentiment_score - 50) > 20 else "Medium",
            "marketBreadth": breadth,
            "marketMomentum": momentum,
            "volatility": "Moderate",
            "liquidityCondition": "Optimal",
            "lastUpdated": MarketCalendar.format_ist_timestamp(),
        }

        await CacheService.set("market_sentiment", result, ttl_seconds=30)
        return result

    @classmethod
    async def get_market_drivers(cls) -> List[Dict[str, Any]]:
        return [
            {
                "id": "1",
                "title": "NIFTY 50 Trend",
                "value": "Bullish Continuation",
                "subtext": "Trading above 20 EMA with positive RSI divergence",
                "trend": "Bullish",
                "indicator": "positive",
            },
            {
                "id": "2",
                "title": "BANK NIFTY Trend",
                "value": "Sustained Strength",
                "subtext": "Private banks holding breakout above 51,200 level",
                "trend": "Bullish",
                "indicator": "positive",
            },
            {
                "id": "3",
                "title": "Market Breadth",
                "value": "1.99x Favoring Buyers",
                "subtext": "1,482 Advances vs 746 Declines on NSE cash",
                "trend": "Bullish",
                "indicator": "positive",
            },
            {
                "id": "4",
                "title": "Sector Strength",
                "value": "IT & Energy Leading",
                "subtext": "Nifty IT (+1.42%) & Energy (+1.10%) leading sector gains",
                "trend": "Bullish",
                "indicator": "positive",
            },
            {
                "id": "5",
                "title": "India VIX",
                "value": "13.42 (-3.85%)",
                "subtext": "Cooling volatility provides favorable risk-reward for long setups",
                "trend": "Bullish",
                "indicator": "positive",
            },
            {
                "id": "6",
                "title": "Volume Activity",
                "value": "+28% Above 20D Avg",
                "subtext": "Institutional block activity concentrated in large-cap leaders",
                "trend": "Bullish",
                "indicator": "positive",
            },
        ]

    @classmethod
    async def get_sector_heatmap(cls) -> List[Dict[str, Any]]:
        cached = await CacheService.get("sector_heatmap")
        if cached:
            return cached

        provider = get_market_data_provider()
        data = await provider.get_sector_data()
        await CacheService.set("sector_heatmap", data, ttl_seconds=60)
        return data

    @classmethod
    async def get_recent_signals(cls) -> List[Dict[str, Any]]:
        return [
            {
                "id": "sig-1",
                "time": "10:30 AM",
                "symbol": "RELIANCE",
                "companyName": "Reliance Industries Ltd.",
                "signal": "Bullish",
                "score": 86,
                "expectedMove": "+1.8% to +2.6%",
                "status": "Active",
            },
            {
                "id": "sig-2",
                "time": "10:15 AM",
                "symbol": "TCS",
                "companyName": "Tata Consultancy Services",
                "signal": "Bullish",
                "score": 84,
                "expectedMove": "+1.5% to +2.2%",
                "status": "Active",
            },
            {
                "id": "sig-3",
                "time": "10:05 AM",
                "symbol": "SBIN",
                "companyName": "State Bank of India",
                "signal": "Bullish",
                "score": 81,
                "expectedMove": "+1.2% to +1.9%",
                "status": "Active",
            },
            {
                "id": "sig-4",
                "time": "09:50 AM",
                "symbol": "INFY",
                "companyName": "Infosys Limited",
                "signal": "Bearish",
                "score": 79,
                "expectedMove": "-1.4% to -2.1%",
                "status": "Active",
            },
            {
                "id": "sig-5",
                "time": "09:35 AM",
                "symbol": "MARUTI",
                "companyName": "Maruti Suzuki India",
                "signal": "Bearish",
                "score": 76,
                "expectedMove": "-1.1% to -1.8%",
                "status": "Active",
            },
            {
                "id": "sig-6",
                "time": "09:20 AM",
                "symbol": "HDFCBANK",
                "companyName": "HDFC Bank Limited",
                "signal": "Bullish",
                "score": 83,
                "expectedMove": "+1.4% to +2.0%",
                "status": "Target Met",
            },
        ]
