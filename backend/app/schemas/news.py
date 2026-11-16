from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime, timezone


class NewsItemSchema(BaseModel):
    id: str
    headline: str
    source: str
    url: str
    publishedAt: str
    retrievedAt: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    sentiment: str = "NEUTRAL"  # 'BULLISH' | 'BEARISH' | 'NEUTRAL'
    sentimentScore: int = 0     # -100 to +100
    impact: str = "MEDIUM"      # 'HIGH' | 'MEDIUM' | 'LOW'
    relatedSymbols: List[str] = Field(default_factory=list)
    category: str = "Markets"
    dataStatus: str = "LIVE"
    provider: str = "indian_financial_rss"


class AssetSentimentCardSchema(BaseModel):
    symbol: str
    name: str
    category: str  # 'Index' | 'Commodity' | 'Crypto' | 'Global' | 'Stock'
    scoreFormatted: str  # e.g. "+2.8", "+3.4", "-1.6", "-3.0"
    scoreValue: float
    sentiment: str  # 'BULLISH' | 'BEARISH' | 'NEUTRAL'
    sentimentRating: float  # 1.0 to 10.0
    changePercent: float
    sparkline: List[float] = Field(default_factory=list)
    articlesCount: int = 0
    keyCatalyst: str = ""


class MarketNewsSentimentSchema(BaseModel):
    overallSentiment: str  # 'BULLISH' | 'BEARISH' | 'NEUTRAL'
    sentimentRating: float  # 1.0 (Extreme Bearish) to 10.0 (Extreme Bullish), 5.5 = Neutral
    ratingLabel: str        # 'Strong Bearish' | 'Mild Bearish' | 'Neutral' | 'Mild Bullish' | 'Strong Bullish'
    sentimentScore: int     # -100 to +100
    bullishCount: int
    bearishCount: int
    neutralCount: int
    totalArticles: int
    ratingExplanation: str
    topBullishHeadlines: List[str]
    topBearishHeadlines: List[str]
    affectedKeySectors: List[str]
    assetCards: List[AssetSentimentCardSchema] = Field(default_factory=list)
    topGainer: Optional[str] = None
    topLoser: Optional[str] = None
    updatedAt: str




class NewsStatusSchema(BaseModel):
    provider: str
    sourceType: str
    status: str
    activeSources: List[str] = Field(default_factory=list)
    lastFetchTimestamp: Optional[str] = None
    totalArticlesFetched: int = 0
    cacheTtlSeconds: int = 900
    freeTier: bool = True
    rateLimitPerMinute: str = "Unmetered Public Feed"


class StockPriceMetricsSchema(BaseModel):
    symbol: str
    companyName: str
    currentPrice: float
    change: float
    changePercent: float
    dayHigh: float
    dayLow: float
    exchange: str = "NSE"
    isLive: bool = True


class StockSentimentAnalysisSchema(BaseModel):
    symbol: str
    companyName: str
    overallSentiment: str  # 'VERY BULLISH' | 'BULLISH' | 'NEUTRAL' | 'BEARISH' | 'VERY BEARISH'
    sentimentScore: int    # 0 to 100 scale
    polarityScore: int     # -100 to +100 raw polarity
    sentimentRating: float # 1.0 to 10.0 scale
    ratingLabel: str       # 'Strong Bullish' | 'Mild Bullish' | 'Neutral' | 'Mild Bearish' | 'Strong Bearish'
    confidence: str        # 'HIGH' | 'MODERATE' | 'LOW'
    totalArticles: int
    bullishCount: int
    bearishCount: int
    neutralCount: int
    bullishRatio: float    # percentage 0..100
    bearishRatio: float    # percentage 0..100
    neutralRatio: float    # percentage 0..100
    confluenceVerdict: str
    institutionalVerdict: str
    keyDrivers: List[str]  # Bullish catalysts
    riskFactors: List[str] # Bearish headwinds
    priceMetrics: Optional[StockPriceMetricsSchema] = None
    optionsMetrics: Optional[Dict[str, Any]] = None
    smcMetrics: Optional[Dict[str, Any]] = None
    sourcesVerified: List[str] = Field(default_factory=list)
    articles: List[NewsItemSchema] = Field(default_factory=list)
    calculatedAt: str
    disclaimer: str = "Quantitative sentiment analysis for informational purposes only. Not financial advice."
