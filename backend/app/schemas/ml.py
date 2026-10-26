from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class MLTrainRequest(BaseModel):
    modelType: str = "random_forest"  # logistic_regression, random_forest, gradient_boosting, mlp
    target: str = "next_30m_direction"  # next_30m_direction, next_60m_direction, intraday_expected_range
    symbols: List[str] = Field(default_factory=lambda: ["RELIANCE", "TCS", "INFY", "HDFCBANK", "SBIN"])
    lookbackDays: int = 180
    features: List[str] = Field(default_factory=lambda: [
        "returns", "rsi", "macd_diff", "ema_ratio", "vwap_ratio", "atr_percent", "volume_ratio"
    ])


class MLTrainResponse(BaseModel):
    jobId: str
    status: str
    message: str


class MLJobStatusSchema(BaseModel):
    jobId: str
    modelType: str
    target: str
    status: str  # RUNNING, COMPLETED, FAILED
    progress: int
    resultModelVersion: Optional[str] = None
    errorMessage: Optional[str] = None
    createdAt: str
    completedAt: Optional[str] = None


class MLModelDetailsSchema(BaseModel):
    modelVersion: str
    modelName: str
    modelType: str
    targetVariable: str
    status: str  # TRAINING, CANDIDATE, VALIDATION, APPROVED, PRODUCTION, REJECTED, ARCHIVED
    trainingDatasetVersion: str
    featureVersion: str
    trainingStart: str
    trainingEnd: str
    validationMetrics: Dict[str, Any]
    testMetrics: Dict[str, Any]
    backtestMetrics: Optional[Dict[str, Any]] = None
    createdAt: str


class MLBacktestRequest(BaseModel):
    modelVersion: str
    symbol: str = "RELIANCE"
    initialCapital: float = 100000.0
    slippageBps: float = 5.0
    brokeragePerTrade: float = 20.0


class MLBacktestResponse(BaseModel):
    modelVersion: str
    symbol: str
    totalTrades: int
    winRate: float
    profitFactor: float
    maxDrawdownPercent: float
    sharpeRatio: float
    totalReturnPercent: float
    netProfit: float
    equityCurve: List[Dict[str, Any]]
