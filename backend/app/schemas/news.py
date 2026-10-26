from typing import List, Optional
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
    impact: str = "MEDIUM"      # 'HIGH' | 'MEDIUM' | 'LOW'
    relatedSymbols: List[str] = Field(default_factory=list)
    dataStatus: str = "LIVE"
    provider: str = "rss_financial_feed"


class NewsStatusSchema(BaseModel):
    provider: str
    sourceType: str
    status: str
    lastFetchTimestamp: Optional[str] = None
    totalArticlesFetched: int = 0
    cacheTtlSeconds: int = 900
    freeTier: bool = True
    rateLimitPerMinute: str = "Unmetered Public Feed"
