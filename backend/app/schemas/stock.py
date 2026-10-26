from typing import Optional
from pydantic import BaseModel


class StockSearchItem(BaseModel):
    symbol: str
    companyName: str
    exchange: str
    category: str
    sector: str
    currentPrice: float
    change: float
    changePercent: float
    volume: str
    trend: str
    analysisScore: int
    isFno: bool = True


class StockQuote(BaseModel):
    symbol: str
    companyName: str
    exchange: str
    currentPrice: float
    change: float
    changePercent: float
    openPrice: float
    dayHigh: float
    dayLow: float
    previousClose: float
    volume: float
    vwap: Optional[float] = None
    timestamp: str
    dataStatus: str = "MOCK"  # LIVE, MOCK, STALE, UNAVAILABLE
