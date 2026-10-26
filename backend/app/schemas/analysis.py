from typing import List, Dict, Optional, Any, Union
from pydantic import BaseModel, Field


class StockPriceRangeSchema(BaseModel):
    extremeLow: float
    likelyLow: float
    currentPrice: float
    likelyHigh: float
    extremeHigh: float


class ScenarioDetailSchema(BaseModel):
    title: str
    type: str  # 'bullish' | 'base' | 'bearish'
    trigger: str
    expectedZone: str
    conditions: List[str]
    confidence: str  # 'High' | 'Medium' | 'Low' | 'Medium/High'
    explanation: str


class SupportResistanceLevelSchema(BaseModel):
    label: str  # 'Resistance 2' | 'Resistance 1' | 'Current' | 'Support 1' | 'Support 2' | 'Support 3'
    price: float
    strength: str  # 'Major' | 'Moderate' | 'Minor'
    distancePercent: float
    implication: str


class IndicatorDetailSchema(BaseModel):
    name: str
    currentValue: Union[str, float, int]
    signal: str  # 'Bullish' | 'Bearish' | 'Neutral'
    interpretation: str
    strength: Optional[int] = 70


class TechnicalIndicatorsSchema(BaseModel):
    rsi: IndicatorDetailSchema
    macd: IndicatorDetailSchema
    ema20: IndicatorDetailSchema
    ema50: IndicatorDetailSchema
    ema200: IndicatorDetailSchema
    vwap: IndicatorDetailSchema
    atr: IndicatorDetailSchema
    volume: IndicatorDetailSchema
    momentum: IndicatorDetailSchema
    priceStructure: IndicatorDetailSchema


class VolumeAnalysisSchema(BaseModel):
    currentVolume: str
    averageVolume: str
    volumeRatio: float
    volumeTrend: str  # 'Above Average' | 'Average' | 'Below Average' | 'Surging'
    intradayBars: List[Dict[str, Any]] = Field(default_factory=list)


class SectorAnalysisSchema(BaseModel):
    sectorName: str
    sectorTrend: str  # 'Bullish' | 'Bearish' | 'Neutral'
    sectorPerformance: float
    relativeStrength: str  # 'Strong' | 'Moderate' | 'Lagging' | 'Neutral'
    stockVsSector: str


class MarketContextSchema(BaseModel):
    nifty50Trend: str
    bankNiftyTrend: str
    marketBreadthStatus: str  # 'Positive' | 'Neutral' | 'Negative'
    indiaVixStatus: str  # 'Low' | 'Moderate' | 'High' | 'Elevated'
    overallMarketSupport: str  # 'Strong' | 'Moderate' | 'Weak'


class NewsEventSchema(BaseModel):
    id: str
    time: str
    headline: str
    impact: str  # 'High' | 'Medium' | 'Low'
    sentiment: str  # 'Positive' | 'Negative' | 'Neutral'
    source: Optional[str] = None
    url: Optional[str] = None


class ScoreCategorySchema(BaseModel):
    category: str
    score: int
    maxScore: int


class StockAnalysisScoreSchema(BaseModel):
    totalScore: int
    status: str
    categories: List[ScoreCategorySchema]


class QualificationPillarSchema(BaseModel):
    pillar: str
    status: str  # 'Confirmed' | 'Positive' | 'Neutral' | 'Caution' | 'Negative'
    explanation: str


class AIConfidenceSchema(BaseModel):
    score: int
    level: str  # 'High' | 'Medium' | 'Low'
    note: str


class AIInsightSchema(BaseModel):
    symbol: str
    headlineQuestion: str
    explanation: str
    qualificationPillars: List[QualificationPillarSchema]
    risks: List[str]
    invalidationTriggers: List[str]
    scenarios: List[ScenarioDetailSchema]
    aiConfidence: AIConfidenceSchema
    citations: Optional[List[Dict[str, Any]]] = Field(default_factory=list)


class CandlePointSchema(BaseModel):
    time: str
    price: float
    vwap: float
    ema20: float
    ema50: float
    volume: float
    support: Optional[float] = None
    resistance: Optional[float] = None
    expectedHigh: Optional[float] = None
    expectedLow: Optional[float] = None


class ExpectedRangeMinMax(BaseModel):
    min: float
    max: float


class ProbabilitiesSchema(BaseModel):
    upside: int
    downside: int
    neutral: Optional[int] = 0


class OutlookChangesSchema(BaseModel):
    bullishConfirmation: str
    bearishConfirmation: str
    risks: List[str]


class StockAnalysisSchema(BaseModel):
    symbol: str
    companyName: str
    exchange: str
    category: str
    sector: str
    currentPrice: float
    change: float
    changePercent: float
    dayHigh: float
    dayLow: float
    volume: str
    analysisTimestamp: str
    trend: str  # 'Bullish' | 'Bearish' | 'Neutral'
    analysisScore: StockAnalysisScoreSchema
    confidence: int
    expectedHigh: ExpectedRangeMinMax
    expectedLow: ExpectedRangeMinMax
    probabilities: ProbabilitiesSchema
    currentBias: str
    priceRange: StockPriceRangeSchema
    bullishScenario: ScenarioDetailSchema
    baseScenario: ScenarioDetailSchema
    bearishScenario: ScenarioDetailSchema
    outlookChanges: OutlookChangesSchema
    supportResistance: List[SupportResistanceLevelSchema]
    technicalIndicators: TechnicalIndicatorsSchema
    volumeAnalysis: VolumeAnalysisSchema
    marketContext: MarketContextSchema
    sectorAnalysis: SectorAnalysisSchema
    news: List[NewsEventSchema]
    aiInsights: AIInsightSchema
    summary: str
    chartData: Dict[str, List[CandlePointSchema]]
    dataStatus: str = "MOCK"  # LIVE | MOCK | STALE | UNAVAILABLE
    dataTimestamp: Optional[str] = None
