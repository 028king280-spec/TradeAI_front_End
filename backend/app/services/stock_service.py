from typing import List, Dict, Any, Optional
from app.core.cache import CacheService
from app.data.providers.factory import get_market_data_provider
from app.data.providers.mock_provider import MOCK_UNIVERSE

# Master directory of Indian stocks compatible with frontend search
INDIAN_STOCKS_DIRECTORY = [
    {"symbol": "RELIANCE", "companyName": "Reliance Industries Limited", "exchange": "NSE", "category": "Large Cap", "sector": "Energy & Conglomerates", "currentPrice": 1456.80, "change": 17.85, "changePercent": 1.24, "volume": "1.42M", "trend": "Bullish", "analysisScore": 86, "isFno": True},
    {"symbol": "TCS", "companyName": "Tata Consultancy Services Limited", "exchange": "NSE", "category": "Large Cap", "sector": "IT", "currentPrice": 4235.50, "change": 62.10, "changePercent": 1.49, "volume": "890K", "trend": "Bullish", "analysisScore": 84, "isFno": True},
    {"symbol": "INFY", "companyName": "Infosys Limited", "exchange": "NSE", "category": "Large Cap", "sector": "IT", "currentPrice": 1845.20, "change": -24.30, "changePercent": -1.30, "volume": "2.10M", "trend": "Bearish", "analysisScore": 79, "isFno": True},
    {"symbol": "SBIN", "companyName": "State Bank of India", "exchange": "NSE", "category": "Large Cap", "sector": "Banking", "currentPrice": 815.40, "change": 11.10, "changePercent": 1.38, "volume": "4.60M", "trend": "Bullish", "analysisScore": 81, "isFno": True},
    {"symbol": "LT", "companyName": "Larsen & Toubro Limited", "exchange": "NSE", "category": "Large Cap", "sector": "Infrastructure", "currentPrice": 3620.00, "change": 42.50, "changePercent": 1.19, "volume": "650K", "trend": "Bullish", "analysisScore": 83, "isFno": True},
    {"symbol": "HDFCBANK", "companyName": "HDFC Bank Limited", "exchange": "NSE", "category": "Large Cap", "sector": "Banking", "currentPrice": 1642.30, "change": 14.80, "changePercent": 0.91, "volume": "3.80M", "trend": "Bullish", "analysisScore": 83, "isFno": True},
    {"symbol": "ICICIBANK", "companyName": "ICICI Bank Limited", "exchange": "NSE", "category": "Large Cap", "sector": "Banking", "currentPrice": 1218.60, "change": 12.40, "changePercent": 1.03, "volume": "2.90M", "trend": "Bullish", "analysisScore": 82, "isFno": True},
    {"symbol": "AXISBANK", "companyName": "Axis Bank Limited", "exchange": "NSE", "category": "Large Cap", "sector": "Banking", "currentPrice": 1175.40, "change": 3.20, "changePercent": 0.27, "volume": "1.75M", "trend": "Neutral", "analysisScore": 68, "isFno": True},
    {"symbol": "MARUTI", "companyName": "Maruti Suzuki India Limited", "exchange": "NSE", "category": "Large Cap", "sector": "Auto", "currentPrice": 12150.00, "change": -145.00, "changePercent": -1.18, "volume": "340K", "trend": "Bearish", "analysisScore": 76, "isFno": True},
    {"symbol": "ITC", "companyName": "ITC Limited", "exchange": "NSE", "category": "Large Cap", "sector": "FMCG", "currentPrice": 502.10, "change": 2.25, "changePercent": 0.45, "volume": "3.20M", "trend": "Neutral", "analysisScore": 65, "isFno": True},
    {"symbol": "SUNPHARMA", "companyName": "Sun Pharmaceutical Industries Limited", "exchange": "NSE", "category": "Large Cap", "sector": "Pharma", "currentPrice": 1820.75, "change": -16.20, "changePercent": -0.88, "volume": "950K", "trend": "Bearish", "analysisScore": 74, "isFno": True},
    {"symbol": "BHARTIARTL", "companyName": "Bharti Airtel Limited", "exchange": "NSE", "category": "Large Cap", "sector": "Telecom", "currentPrice": 1548.00, "change": 18.50, "changePercent": 1.21, "volume": "1.80M", "trend": "Bullish", "analysisScore": 80, "isFno": True},
    {"symbol": "ADANIENT", "companyName": "Adani Enterprises Limited", "exchange": "NSE", "category": "Large Cap", "sector": "Metals", "currentPrice": 2980.50, "change": 15.00, "changePercent": 0.51, "volume": "1.10M", "trend": "Neutral", "analysisScore": 66, "isFno": True},
    {"symbol": "M&M", "companyName": "Mahindra & Mahindra Limited", "exchange": "NSE", "category": "Large Cap", "sector": "Auto", "currentPrice": 2780.00, "change": 49.70, "changePercent": 1.82, "volume": "1.25M", "trend": "Bullish", "analysisScore": 85, "isFno": True},
    {"symbol": "KOTAKBANK", "companyName": "Kotak Mahindra Bank Limited", "exchange": "NSE", "category": "Large Cap", "sector": "Banking", "currentPrice": 1785.60, "change": 4.10, "changePercent": 0.23, "volume": "1.15M", "trend": "Neutral", "analysisScore": 67, "isFno": True},
]


class StockService:
    @classmethod
    async def search_stocks(
        cls,
        query: str = "",
        exchange: Optional[str] = "ALL",
        cap: Optional[str] = "ALL"
    ) -> List[Dict[str, Any]]:
        q = query.strip().upper()
        results = INDIAN_STOCKS_DIRECTORY

        if q:
            results = [
                s for s in results
                if q in s["symbol"].upper() or q in s["companyName"].upper()
            ]

        if exchange and exchange != "ALL":
            results = [s for s in results if s["exchange"] == exchange]

        if cap and cap != "ALL":
            results = [s for s in results if s["category"] == cap]

        # Enrich with live quotes from cache if available
        enriched = []
        for s in results:
            item = dict(s)
            cached = await CacheService.get(f"live_quote:{s['symbol']}")
            if cached and isinstance(cached, dict) and cached.get("currentPrice", 0) > 0:
                item["currentPrice"] = cached["currentPrice"]
                item["change"] = cached.get("change", item["change"])
                item["changePercent"] = cached.get("changePercent", item["changePercent"])
                item["trend"] = "Bullish" if item["change"] >= 0 else "Bearish"
            enriched.append(item)

        return enriched

    @classmethod
    async def get_stock_by_symbol(cls, symbol: str) -> Optional[Dict[str, Any]]:
        upper = symbol.upper()
        for s in INDIAN_STOCKS_DIRECTORY:
            if s["symbol"] == upper:
                return s
        return None
