from typing import List, Optional, Generic, TypeVar, Any
from datetime import datetime, timezone
from pydantic import BaseModel, Field

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    success: bool = True
    data: Optional[T] = None
    error: Optional[dict] = None
    dataStatus: str = "MOCK"  # 'LIVE' | 'STALE' | 'MOCK' | 'UNAVAILABLE'
    dataTimestamp: Optional[str] = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    analysisTimestamp: Optional[str] = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class MarketIndexSchema(BaseModel):
    symbol: str
    name: str
    currentValue: float
    change: float
    changePercent: float
    dayHigh: float
    dayLow: float
    trend: str  # 'Bullish' | 'Bearish' | 'Neutral'
    sparkline: List[float] = Field(default_factory=list)
    volatilityStatus: Optional[str] = "Moderate"


class MarketBreadthSchema(BaseModel):
    advancing: int
    declining: int
    unchanged: int
    ratio: float


class MarketSentimentSchema(BaseModel):
    score: int
    status: str  # 'Bullish' | 'Bearish' | 'Neutral'
    confidence: str  # 'Low' | 'Medium' | 'High'
    marketBreadth: MarketBreadthSchema
    marketMomentum: str  # 'Strong Bullish' | 'Bullish' | 'Neutral' | 'Bearish' | 'Strong Bearish'
    volatility: str  # 'Low' | 'Moderate' | 'High' | 'Extreme'
    liquidityCondition: str  # 'Optimal' | 'Average' | 'Tight'
    lastUpdated: str


class MarketDriverSchema(BaseModel):
    id: str
    title: str
    value: str
    subtext: str
    trend: str
    indicator: str  # 'positive' | 'negative' | 'neutral'


class SectorHeatmapItemSchema(BaseModel):
    sector: str
    performancePercent: float
    strength: str  # 'Strong' | 'Moderate' | 'Weak' | 'Negative'
    topStock: str
    advancers: int
    decliners: int


class RecentAISignalSchema(BaseModel):
    id: str
    time: str
    symbol: str
    companyName: str
    signal: str  # 'Bullish' | 'Bearish'
    score: int
    expectedMove: str
    status: str  # 'Active' | 'Target Met' | 'Trailing'
