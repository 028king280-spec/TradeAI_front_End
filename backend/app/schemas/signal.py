from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime, timezone


class SignalCandidateSchema(BaseModel):
    symbol: str
    companyName: str
    exchange: str = "NSE"
    rank: int = 1
    currentPrice: float
    price: Optional[float] = None
    change: float
    changePercent: float
    trend: str  # 'Bullish' | 'Bearish' | 'Neutral'
    signalType: str  # 'CALL' | 'PUT' | 'NEUTRAL'
    analysisScore: int
    score: Optional[int] = None
    confidence: int
    expectedHigh: float
    expectedLow: float
    expected_high: Optional[float] = None
    expected_low: Optional[float] = None
    upside_probability: Optional[int] = 50
    downside_probability: Optional[int] = 50
    reason: Optional[str] = "Qualified Setup"
    sparkline: List[float] = Field(default_factory=list)
    qualified: bool = True


class SignalEventSchema(BaseModel):
    id: str
    signalId: str
    eventType: str
    targetNumber: Optional[int] = None
    marketPrice: float
    bid: Optional[float] = None
    ask: Optional[float] = None
    volume: Optional[int] = None
    marketTimestamp: str
    receivedTimestamp: str
    elapsedSecondsFromSignal: float
    elapsedSecondsFromEntry: Optional[float] = None
    priceSource: str = "angelone_stream"
    dataQualityStatus: str = "CONFIRMED"
    positionFractionClosed: float = 0.0
    remainingPositionFraction: float = 1.0
    eventDetails: Optional[Dict[str, Any]] = None


class TrackedSignalSchema(BaseModel):
    id: str
    symbol: str
    contractSymbol: str
    exchange: str = "NFO"
    instrumentToken: str
    strike: float
    expiry: str
    optionType: str
    status: str
    underlyingPriceAtSignal: float
    signalPremium: float
    signalBid: Optional[float] = None
    signalAsk: Optional[float] = None
    entryZoneMin: float
    entryZoneMax: float
    entryTriggerCondition: str
    stopLossPremium: float
    target1Premium: float
    target2Premium: float
    target3Premium: float
    trailingStopRule: str = "MOVE_TO_COST_ON_T1"
    horizon: str = "Next Session (1-2 Days)"
    sentiment: str = "BULLISH"
    analysisScore: int = 70
    confidence: str = "High"
    strategyVersion: str = "v2.1-conservative"
    quantEngineVersion: str = "1.0.0"
    provider: str = "angelone"
    dataStatus: str = "LIVE"
    createdAt: str
    entryTriggeredAt: Optional[str] = None
    entryObservedPrice: Optional[float] = None
    entryObservedBid: Optional[float] = None
    entryObservedAsk: Optional[float] = None
    entryReferenceMethod: Optional[str] = None
    closedAt: Optional[str] = None
    finalOutcome: Optional[str] = None
    grossPnlPoints: float = 0.0
    netPnlInr: float = 0.0
    lotSize: int = 25
    allocatedLots: int = 1
    remainingFraction: float = 1.0
    isLive: bool = True
    events: List[SignalEventSchema] = Field(default_factory=list)


class SignalTimelineItemSchema(BaseModel):
    timestamp: str
    title: str
    description: str
    price: float
    state: str
    elapsedMinutes: Optional[float] = None
    isTargetOrSl: bool = False


class SignalTimelineSchema(BaseModel):
    signalId: str
    contractSymbol: str
    underlying: str
    currentStatus: str
    finalOutcome: Optional[str] = None
    timeline: List[SignalTimelineItemSchema]


class TrackingStatusSchema(BaseModel):
    activeMonitoredContractsCount: int
    trackedTokens: List[str]
    provider: str
    feedStatus: str
    stateMachineVersion: str
    lastReconciliationDate: str
    autoTrackingEnabled: bool = True
