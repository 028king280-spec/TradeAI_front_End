"""
Intelligent Paper Trading & Self-Learning Engine Package.
"""

from app.options.paper_trading.cost_calculator import IndianDerivativesCostCalculator
from app.options.paper_trading.paper_engine import PaperTradingEngine, paper_engine
from app.options.paper_trading.trade_evaluator import AITradeEvaluator
from app.options.paper_trading.ml_feedback_engine import MLFeedbackEngine
from app.options.paper_trading.label_engine import (
    SignalDecision,
    OutcomeClass,
    MultiClassTarget,
    HorizonStatus,
    ThresholdType,
    ThresholdConfiguration,
    SignalLabel,
    RealizedOutcomeLabel,
    FixedHorizonObservation,
    FixedHorizonLabelSet,
    FixedHorizonEngine,
    SignalClassifier,
    OutcomeCalculator,
    WalkForwardPartitionEngine,
    LeakageGuard,
    WalkForwardFold,
    PartitionSplit,
    SUPPORTED_HORIZONS_MINUTES,
)
from app.options.paper_trading.observation_engine import (
    PreflightChecker,
    PreflightReport,
    ObservationEngine,
    ObservationRecord,
    ObservationClassification,
)

__all__ = [
    "IndianDerivativesCostCalculator",
    "PaperTradingEngine",
    "paper_engine",
    "AITradeEvaluator",
    "MLFeedbackEngine",
    "SignalDecision",
    "OutcomeClass",
    "MultiClassTarget",
    "HorizonStatus",
    "ThresholdType",
    "ThresholdConfiguration",
    "SignalLabel",
    "RealizedOutcomeLabel",
    "FixedHorizonObservation",
    "FixedHorizonLabelSet",
    "FixedHorizonEngine",
    "SignalClassifier",
    "OutcomeCalculator",
    "WalkForwardPartitionEngine",
    "LeakageGuard",
    "WalkForwardFold",
    "PartitionSplit",
    "SUPPORTED_HORIZONS_MINUTES",
    "PreflightChecker",
    "PreflightReport",
    "ObservationEngine",
    "ObservationRecord",
    "ObservationClassification",
]
