"""
Phase 5.2B: Deterministic Label Engineering, Outcome Engine & Walk-Forward Partitioning.

Implements:
1. Deterministic Signal Decision Classification (BUY_CE, BUY_PE, WAIT, NO_TRADE).
2. Strict architectural separation of Decision Signal Labels from Realized Outcome Labels.
3. Fixed-Horizon Outcome Engine (5, 15, 30, 60 minutes) using genuine forward option observations.
4. Scale-normalized threshold governance (Return on Risk, zero unapproved hardcoded constants).
5. Future outcome calculation strictly with genuine post-trade observations (zero fabrication).
6. Walk-forward train/validation/OOS temporal partition architecture with proactive OOS purging and embargo.
7. Anti-leakage and anti-contamination verification guards.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
import math
import os
import re
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union
import zoneinfo

from app.data.market_calendar import MarketCalendar
from app.options.paper_trading.cost_calculator import IndianDerivativesCostCalculator

IST_ZONE = zoneinfo.ZoneInfo("Asia/Kolkata")
SCHEMA_VERSION = "2.2.0"
SUPPORTED_HORIZONS_MINUTES = [5, 15, 30, 60]


class SignalDecision(str, Enum):
    BUY_CE = "BUY_CE"
    BUY_PE = "BUY_PE"
    WAIT = "WAIT"
    NO_TRADE = "NO_TRADE"


class OutcomeClass(str, Enum):
    WIN = "WIN"
    LOSS = "LOSS"
    SCRATCH = "SCRATCH"
    UNCONFIGURED = "UNCONFIGURED"
    UNRESOLVED = "UNRESOLVED"


class MultiClassTarget(int, Enum):
    UNCONFIGURED = -1  # Non-training-eligible state when threshold unapproved
    LOSS = 0
    SCRATCH = 1
    WIN = 2


class HorizonStatus(str, Enum):
    RESOLVED = "RESOLVED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    STALE_OBSERVATION = "STALE_OBSERVATION"
    FUTURE_LEAKAGE = "FUTURE_LEAKAGE"
    INVALID_CONTRACT = "INVALID_CONTRACT"
    OUT_OF_SESSION = "OUT_OF_SESSION"
    UNDERLYING_PRICE_REJECTED = "UNDERLYING_PRICE_REJECTED"


class ThresholdType(str, Enum):
    UNCONFIGURED = "UNCONFIGURED"
    RETURN_ON_RISK = "RETURN_ON_RISK"
    RETURN_ON_CAPITAL = "RETURN_ON_CAPITAL"


class PartitionType(str, Enum):
    TRAIN = "TRAIN"
    VALIDATION = "VALIDATION"
    OUT_OF_SAMPLE = "OUT_OF_SAMPLE"
    PURGED = "PURGED"
    EMBARGOED = "EMBARGOED"


def parse_ist_timestamp(ts: Union[str, datetime]) -> datetime:
    """
    Parses datetime, ISO-8601 string, or IST human readable string into an IST-aware datetime.
    """
    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            return ts.replace(tzinfo=IST_ZONE)
        return ts.astimezone(IST_ZONE)

    if not isinstance(ts, str) or not ts.strip():
        raise ValueError(f"Empty or invalid timestamp: {ts}")

    s = ts.strip()

    # Match human format with 'IST' e.g. "05 Nov 2026, 10:32 PM IST"
    if "IST" in s:
        clean = s.replace(" IST", "").strip()
        for fmt in ["%d %b %Y, %I:%M %p", "%d %b %Y, %I:%M:%S %p"]:
            try:
                return datetime.strptime(clean, fmt).replace(tzinfo=IST_ZONE)
            except Exception:
                pass

    # Match standard formats
    for fmt in [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S%z",
        "%d-%m-%Y %H:%M:%S",
        "%d/%m/%Y %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S%z",
    ]:
        try:
            dt = datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                return dt.replace(tzinfo=IST_ZONE)
            return dt.astimezone(IST_ZONE)
        except Exception:
            continue

    # Match ISO format
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=IST_ZONE)
        return dt.astimezone(IST_ZONE)
    except Exception as e:
        raise ValueError(f"Unable to parse timestamp '{ts}' into IST datetime: {e}")


@dataclass
class ThresholdConfiguration:
    """
    Scale-normalized threshold governance configuration.
    Requires explicit approval before activation in training pipelines.
    """
    is_approved: bool = False
    threshold_type: ThresholdType = ThresholdType.UNCONFIGURED
    threshold_value: Optional[float] = None  # e.g. 0.10 for 10% of initial risk R
    approval_reference: Optional[str] = None
    min_initial_risk_rupees: float = 100.0  # Minimum risk required to compute valid R

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_approved": self.is_approved,
            "threshold_type": self.threshold_type.value,
            "threshold_value": self.threshold_value,
            "approval_reference": self.approval_reference,
            "min_initial_risk_rupees": self.min_initial_risk_rupees,
        }


@dataclass
class SignalLabel:
    """
    Deterministic Decision Signal at prediction time T_decision.
    Known STRICTLY at entry time.
    """
    signal_type: SignalDecision
    decision_time: datetime
    direction: str  # "CE", "PE", "NEUTRAL"
    confidence: float  # 0.0 - 1.0
    setup_name: str
    reasons: List[str] = field(default_factory=list)
    market_status: str = "OPEN"
    is_actionable: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "signal_type": self.signal_type.value,
            "decision_time": self.decision_time.isoformat(),
            "direction": self.direction,
            "confidence": self.confidence,
            "setup_name": self.setup_name,
            "reasons": self.reasons,
            "market_status": self.market_status,
            "is_actionable": self.is_actionable,
            "metadata": self.metadata,
        }


@dataclass
class RealizedOutcomeLabel:
    """
    Realized Post-Trade Lifecycle Outcome at exit time T_exit >= T_entry.
    Evaluated STRICTLY after trade closure.
    """
    trade_id: str
    entry_time: datetime
    exit_time: datetime
    holding_duration_seconds: float
    entry_price: float
    exit_price: float
    quantity: int
    gross_pnl: float
    total_charges: float
    net_pnl: float
    binary_target: int  # 1 (Win), 0 (Loss), -1 (Unconfigured/Non-eligible)
    multiclass_target: MultiClassTarget  # -1: Unconfigured, 0: Loss, 1: Scratch, 2: Win
    outcome_class: OutcomeClass  # WIN, LOSS, SCRATCH, UNCONFIGURED, UNRESOLVED
    mfe_pts: float = 0.0
    mae_pts: float = 0.0
    return_on_risk: Optional[float] = None
    is_genuine: bool = True
    is_training_eligible: bool = False
    status: str = "CLOSED"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trade_id": self.trade_id,
            "entry_time": self.entry_time.isoformat(),
            "exit_time": self.exit_time.isoformat() if self.exit_time else None,
            "holding_duration_seconds": self.holding_duration_seconds,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "quantity": self.quantity,
            "gross_pnl": self.gross_pnl,
            "total_charges": self.total_charges,
            "net_pnl": self.net_pnl,
            "binary_target": self.binary_target,
            "multiclass_target": self.multiclass_target.value,
            "outcome_class": self.outcome_class.value,
            "mfe_pts": self.mfe_pts,
            "mae_pts": self.mae_pts,
            "return_on_risk": self.return_on_risk,
            "is_genuine": self.is_genuine,
            "is_training_eligible": self.is_training_eligible,
            "status": self.status,
            "metadata": self.metadata,
        }


@dataclass
class FixedHorizonObservation:
    """
    Genuine option-specific observation at a defined forward horizon.
    """
    horizon_minutes: int
    prediction_time: datetime
    target_time: datetime
    observation_time: Optional[datetime]
    contract_symbol: str
    prediction_price: float
    horizon_price: Optional[float]
    premium_return_pts: Optional[float]
    premium_return_pct: Optional[float]
    status: HorizonStatus
    status_reason: str = ""
    underlying_price_at_prediction: Optional[float] = None
    underlying_price_at_horizon: Optional[float] = None
    provenance: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "horizon_minutes": self.horizon_minutes,
            "prediction_time": self.prediction_time.isoformat(),
            "target_time": self.target_time.isoformat(),
            "observation_time": self.observation_time.isoformat() if self.observation_time else None,
            "contract_symbol": self.contract_symbol,
            "prediction_price": self.prediction_price,
            "horizon_price": self.horizon_price,
            "premium_return_pts": self.premium_return_pts,
            "premium_return_pct": self.premium_return_pct,
            "status": self.status.value,
            "status_reason": self.status_reason,
            "underlying_price_at_prediction": self.underlying_price_at_prediction,
            "underlying_price_at_horizon": self.underlying_price_at_horizon,
            "provenance": self.provenance,
        }


@dataclass
class FixedHorizonLabelSet:
    """
    Container for complete multi-horizon outcome evaluations.
    """
    observation_id: str
    prediction_time: datetime
    contract_symbol: str
    prediction_price: float
    horizons: Dict[int, FixedHorizonObservation]
    schema_version: str = SCHEMA_VERSION
    generated_at: datetime = field(default_factory=MarketCalendar.now_ist)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "prediction_time": self.prediction_time.isoformat(),
            "contract_symbol": self.contract_symbol,
            "prediction_price": self.prediction_price,
            "horizons": {h: obs.to_dict() for h, obs in self.horizons.items()},
            "schema_version": self.schema_version,
            "generated_at": self.generated_at.isoformat(),
            "metadata": self.metadata,
        }


class FixedHorizonEngine:
    """
    Task 1: Institutional Fixed-Horizon Forward Outcome Engine.
    Evaluates forward option price dynamics strictly at 5, 15, 30, and 60 minutes.
    Enforces:
    - Never substitutes underlying index prices for option premiums.
    - Observation occurs strictly after prediction timestamp.
    - Fails-closed with INSUFFICIENT_DATA on missing/stale quotes.
    - Zero price interpolation or synthetic fabrication.
    """

    SUPPORTED_HORIZONS = SUPPORTED_HORIZONS_MINUTES

    @classmethod
    def evaluate_horizons(
        cls,
        prediction_time: Union[str, datetime],
        contract_symbol: str,
        prediction_price: float,
        quote_series: List[Dict[str, Any]],
        horizons: Optional[List[int]] = None,
        max_staleness_seconds: float = 60.0,
        underlying_price_at_prediction: Optional[float] = None,
        observation_id: str = "OBS_FIXED_HORIZON",
        is_production_mode: bool = True,
    ) -> FixedHorizonLabelSet:
        pred_dt = parse_ist_timestamp(prediction_time)
        eval_horizons = horizons or cls.SUPPORTED_HORIZONS

        contract_str = str(contract_symbol).strip().upper()
        pred_p = float(prediction_price)

        # 1. Contract & Symbol Integrity
        is_valid_contract = bool(re.match(r"^(NIFTY|BANKNIFTY|FINNIFTY)\d{2}[A-Z]{3}\d{4,5}[CP]E$", contract_str))
        if "TEST" in contract_str or "MOCK" in contract_str:
            is_valid_contract = False

        # 2. Underlying Price Substitution Guard
        # If prediction_price matches underlying spot price within 5%, reject immediately
        is_underlying_substitution = False
        if underlying_price_at_prediction is not None and underlying_price_at_prediction > 0.0:
            if abs(pred_p - underlying_price_at_prediction) / underlying_price_at_prediction < 0.05:
                is_underlying_substitution = True

        horizon_results: Dict[int, FixedHorizonObservation] = {}

        for h in eval_horizons:
            target_dt = pred_dt + timedelta(minutes=h)

            if not is_valid_contract:
                horizon_results[h] = FixedHorizonObservation(
                    horizon_minutes=h,
                    prediction_time=pred_dt,
                    target_time=target_dt,
                    observation_time=None,
                    contract_symbol=contract_str,
                    prediction_price=pred_p,
                    horizon_price=None,
                    premium_return_pts=None,
                    premium_return_pct=None,
                    status=HorizonStatus.INVALID_CONTRACT,
                    status_reason=f"Contract '{contract_str}' fails canonical NIFTY option format or contains TEST/MOCK tag.",
                    underlying_price_at_prediction=underlying_price_at_prediction,
                )
                continue

            if is_underlying_substitution:
                horizon_results[h] = FixedHorizonObservation(
                    horizon_minutes=h,
                    prediction_time=pred_dt,
                    target_time=target_dt,
                    observation_time=None,
                    contract_symbol=contract_str,
                    prediction_price=pred_p,
                    horizon_price=None,
                    premium_return_pts=None,
                    premium_return_pct=None,
                    status=HorizonStatus.UNDERLYING_PRICE_REJECTED,
                    status_reason="Prediction price matches underlying index within 5%. Underlying price cannot substitute for option premium.",
                    underlying_price_at_prediction=underlying_price_at_prediction,
                )
                continue

            # 3. Market Session Boundary
            if not MarketCalendar.is_market_open(target_dt):
                horizon_results[h] = FixedHorizonObservation(
                    horizon_minutes=h,
                    prediction_time=pred_dt,
                    target_time=target_dt,
                    observation_time=None,
                    contract_symbol=contract_str,
                    prediction_price=pred_p,
                    horizon_price=None,
                    premium_return_pts=None,
                    premium_return_pct=None,
                    status=HorizonStatus.OUT_OF_SESSION,
                    status_reason=f"Target time {target_dt.isoformat()} falls outside exchange trading hours (09:15-15:30 IST).",
                    underlying_price_at_prediction=underlying_price_at_prediction,
                )
                continue

            # 4. Search Matching Quotes in quote_series
            # Find genuine quotes strictly after pred_dt
            candidate_quotes = []
            for q in quote_series:
                q_contract = str(q.get("contract") or q.get("contractSymbol") or "").strip().upper()
                if q_contract != contract_str:
                    continue

                q_ts_raw = q.get("timestamp") or q.get("tickTimestamp")
                if not q_ts_raw:
                    continue

                q_dt = parse_ist_timestamp(q_ts_raw)
                # Strict causality: observation must occur strictly after prediction
                if q_dt <= pred_dt:
                    continue

                # Future timestamp check vs current clock
                now_ist = MarketCalendar.now_ist()
                if (q_dt - now_ist).total_seconds() > 5.0:
                    candidate_quotes.append((q_dt, q, "FUTURE_LEAKAGE"))
                    continue

                if is_production_mode and str(q.get("provider", "")).upper() == "MOCK":
                    continue

                q_price = float(q.get("ltp") or q.get("price") or q.get("premium") or 0.0)
                if q_price <= 0.0:
                    continue

                candidate_quotes.append((q_dt, q, "VALID"))

            if not candidate_quotes:
                horizon_results[h] = FixedHorizonObservation(
                    horizon_minutes=h,
                    prediction_time=pred_dt,
                    target_time=target_dt,
                    observation_time=None,
                    contract_symbol=contract_str,
                    prediction_price=pred_p,
                    horizon_price=None,
                    premium_return_pts=None,
                    premium_return_pct=None,
                    status=HorizonStatus.INSUFFICIENT_DATA,
                    status_reason=f"No forward option observations found for contract '{contract_str}'.",
                    underlying_price_at_prediction=underlying_price_at_prediction,
                )
                continue

            # Check if any candidate has future leakage
            future_leaks = [item for item in candidate_quotes if item[2] == "FUTURE_LEAKAGE"]
            if future_leaks:
                bad_dt, bad_q, _ = future_leaks[0]
                horizon_results[h] = FixedHorizonObservation(
                    horizon_minutes=h,
                    prediction_time=pred_dt,
                    target_time=target_dt,
                    observation_time=bad_dt,
                    contract_symbol=contract_str,
                    prediction_price=pred_p,
                    horizon_price=None,
                    premium_return_pts=None,
                    premium_return_pct=None,
                    status=HorizonStatus.FUTURE_LEAKAGE,
                    status_reason=f"Observation timestamp {bad_dt.isoformat()} is ahead of market clock.",
                    underlying_price_at_prediction=underlying_price_at_prediction,
                )
                continue

            # Find quote closest to target_dt
            valid_quotes = [item for item in candidate_quotes if item[2] == "VALID"]
            if not valid_quotes:
                horizon_results[h] = FixedHorizonObservation(
                    horizon_minutes=h,
                    prediction_time=pred_dt,
                    target_time=target_dt,
                    observation_time=None,
                    contract_symbol=contract_str,
                    prediction_price=pred_p,
                    horizon_price=None,
                    premium_return_pts=None,
                    premium_return_pct=None,
                    status=HorizonStatus.INSUFFICIENT_DATA,
                    status_reason="No valid genuine quotes passed quality validation.",
                    underlying_price_at_prediction=underlying_price_at_prediction,
                )
                continue

            # Sort by proximity to target_dt
            valid_quotes.sort(key=lambda item: abs((item[0] - target_dt).total_seconds()))
            best_dt, best_quote, _ = valid_quotes[0]
            staleness = abs((best_dt - target_dt).total_seconds())

            if staleness > max_staleness_seconds:
                # If observation is far away (> 2x tolerance), consider it a complete absence of data
                if staleness > max(120.0, max_staleness_seconds * 2.0):
                    horizon_results[h] = FixedHorizonObservation(
                        horizon_minutes=h,
                        prediction_time=pred_dt,
                        target_time=target_dt,
                        observation_time=None,
                        contract_symbol=contract_str,
                        prediction_price=pred_p,
                        horizon_price=None,
                        premium_return_pts=None,
                        premium_return_pct=None,
                        status=HorizonStatus.INSUFFICIENT_DATA,
                        status_reason=f"No forward observations found near {h}-minute horizon window ({staleness:.1f}s away).",
                        underlying_price_at_prediction=underlying_price_at_prediction,
                    )
                else:
                    horizon_results[h] = FixedHorizonObservation(
                        horizon_minutes=h,
                        prediction_time=pred_dt,
                        target_time=target_dt,
                        observation_time=best_dt,
                        contract_symbol=contract_str,
                        prediction_price=pred_p,
                        horizon_price=None,
                        premium_return_pts=None,
                        premium_return_pct=None,
                        status=HorizonStatus.STALE_OBSERVATION,
                        status_reason=f"Nearest observation at {best_dt.isoformat()} exceeds tolerance ({staleness:.1f}s > {max_staleness_seconds}s).",
                        underlying_price_at_prediction=underlying_price_at_prediction,
                    )
                continue

            # Valid resolution
            h_price = float(best_quote.get("ltp") or best_quote.get("price") or best_quote.get("premium"))
            ret_pts = round(h_price - pred_p, 2)
            ret_pct = round((h_price - pred_p) / pred_p, 4)

            horizon_results[h] = FixedHorizonObservation(
                horizon_minutes=h,
                prediction_time=pred_dt,
                target_time=target_dt,
                observation_time=best_dt,
                contract_symbol=contract_str,
                prediction_price=pred_p,
                horizon_price=h_price,
                premium_return_pts=ret_pts,
                premium_return_pct=ret_pct,
                status=HorizonStatus.RESOLVED,
                status_reason="Resolved from verified forward option quote.",
                underlying_price_at_prediction=underlying_price_at_prediction,
                underlying_price_at_horizon=best_quote.get("underlyingLtp"),
                provenance={
                    "provider": best_quote.get("provider", "ANGELONE"),
                    "source": "VERIFIED_FORWARD_QUOTE",
                    "staleness_seconds": round(staleness, 2),
                }
            )

        return FixedHorizonLabelSet(
            observation_id=observation_id,
            prediction_time=pred_dt,
            contract_symbol=contract_str,
            prediction_price=pred_p,
            horizons=horizon_results,
            metadata={
                "max_staleness_seconds": max_staleness_seconds,
                "is_production_mode": is_production_mode,
            }
        )


class SignalClassifier:
    """
    Deterministic Market State & Signal Classifier.
    Classifies intentional trading decision at time T using ONLY information available at time T.
    Strictly forbids looking at future prices, exit details, or realized PnL.
    """

    CONFIDENCE_HIGH = 0.85
    CONFIDENCE_MEDIUM = 0.70
    CONFIDENCE_LOW = 0.50

    @classmethod
    def classify(
        cls,
        observation: Dict[str, Any],
        strict_session_check: bool = False,
    ) -> SignalLabel:
        reasons: List[str] = []

        # 1. Decision Time
        raw_ts = (
            observation.get("entryTimestamp")
            or observation.get("timestamp")
            or observation.get("decisionTime")
            or observation.get("createdAt")
        )
        if raw_ts:
            dt = parse_ist_timestamp(raw_ts)
        else:
            dt = MarketCalendar.now_ist()

        # 2. Market Session Check
        is_open = MarketCalendar.is_market_open(dt)
        market_status = observation.get("marketStatus") or ("OPEN" if is_open else "CLOSED")

        if strict_session_check and not is_open:
            return SignalLabel(
                signal_type=SignalDecision.NO_TRADE,
                decision_time=dt,
                direction="NEUTRAL",
                confidence=0.0,
                setup_name="OUT_OF_HOURS",
                reasons=["Exchange regular session closed (outside 09:15-15:30 IST)."],
                market_status="CLOSED",
                is_actionable=False,
            )

        # 3. Data Integrity & Degraded Feed Check
        if str(observation.get("provider", "")).upper() == "MOCK" and observation.get("isProduction", False):
            return SignalLabel(
                signal_type=SignalDecision.NO_TRADE,
                decision_time=dt,
                direction="NEUTRAL",
                confidence=0.0,
                setup_name="UNVERIFIED_DATA",
                reasons=["Synthetic mock provider rejected in production environment."],
                market_status=market_status,
                is_actionable=False,
            )

        # 4. Features extraction (strip future fields)
        features = observation.get("marketFeaturesAtEntry") or observation.get("features") or {}
        if not isinstance(features, dict):
            features = {}

        bias = str(
            observation.get("bias")
            or observation.get("signal")
            or observation.get("direction")
            or ""
        ).upper().strip()

        setup = str(
            observation.get("ictSetup")
            or observation.get("strategy")
            or "Institutional Setup"
        )
        mtf_score = float(features.get("mtfConfluenceScore", 0.0) or observation.get("mtfConfluenceScore", 0.0))
        dealing_regime = str(features.get("dealingRangeRegime", "") or "").upper()
        market_cond = str(features.get("marketCondition", "") or observation.get("condition", "")).upper()

        is_choppy = "CHOP" in market_cond or "SIDEWAYS" in market_cond or "RANGE_BOUND" in market_cond
        has_sweep = "SWEEP" in setup.upper() or features.get("sweepReclaim", False) or features.get("is_sweep_reclaim", False)
        has_bos = "BOS" in setup.upper() or "CHOCH" in setup.upper() or features.get("bosConfirmed", False)

        # 5. Deterministic Decision Classification
        if bias in ["CE", "BUY_CE"]:
            if mtf_score >= 70.0 and (dealing_regime == "DISCOUNT" or has_sweep or has_bos or not dealing_regime):
                conf = cls.CONFIDENCE_HIGH if mtf_score >= 80.0 else cls.CONFIDENCE_MEDIUM
                reasons.append(f"Bullish alignment: MTF score {mtf_score:.1f} >= 70.0 in {dealing_regime or 'Discount'} zone.")
                if has_sweep:
                    reasons.append("Liquidity sweep and reclaim confirmed.")
                return SignalLabel(
                    signal_type=SignalDecision.BUY_CE,
                    decision_time=dt,
                    direction="CE",
                    confidence=conf,
                    setup_name=setup,
                    reasons=reasons,
                    market_status=market_status,
                    is_actionable=True,
                )
            elif is_choppy and not has_sweep:
                return SignalLabel(
                    signal_type=SignalDecision.WAIT,
                    decision_time=dt,
                    direction="CE",
                    confidence=cls.CONFIDENCE_LOW,
                    setup_name=setup,
                    reasons=["Consolidation chop detected; awaiting liquidity purge / FVG expansion."],
                    market_status=market_status,
                    is_actionable=False,
                )
            else:
                return SignalLabel(
                    signal_type=SignalDecision.NO_TRADE,
                    decision_time=dt,
                    direction="CE",
                    confidence=cls.CONFIDENCE_LOW,
                    setup_name=setup,
                    reasons=[f"MTF score {mtf_score:.1f} insufficient or dealing range unfavorable."],
                    market_status=market_status,
                    is_actionable=False,
                )

        elif bias in ["PE", "BUY_PE"]:
            if mtf_score >= 70.0 and (dealing_regime == "PREMIUM" or has_sweep or has_bos or not dealing_regime):
                conf = cls.CONFIDENCE_HIGH if mtf_score >= 80.0 else cls.CONFIDENCE_MEDIUM
                reasons.append(f"Bearish alignment: MTF score {mtf_score:.1f} >= 70.0 in {dealing_regime or 'Premium'} zone.")
                if has_sweep:
                    reasons.append("Buy-side liquidity sweep confirmed.")
                return SignalLabel(
                    signal_type=SignalDecision.BUY_PE,
                    decision_time=dt,
                    direction="PE",
                    confidence=conf,
                    setup_name=setup,
                    reasons=reasons,
                    market_status=market_status,
                    is_actionable=True,
                )
            elif is_choppy and not has_sweep:
                return SignalLabel(
                    signal_type=SignalDecision.WAIT,
                    decision_time=dt,
                    direction="PE",
                    confidence=cls.CONFIDENCE_LOW,
                    setup_name=setup,
                    reasons=["Chop regime; awaiting sell-side displacement."],
                    market_status=market_status,
                    is_actionable=False,
                )
            else:
                return SignalLabel(
                    signal_type=SignalDecision.NO_TRADE,
                    decision_time=dt,
                    direction="PE",
                    confidence=cls.CONFIDENCE_LOW,
                    setup_name=setup,
                    reasons=[f"MTF score {mtf_score:.1f} insufficient or premium location suboptimal."],
                    market_status=market_status,
                    is_actionable=False,
                )

        elif bias == "WAIT":
            return SignalLabel(
                signal_type=SignalDecision.WAIT,
                decision_time=dt,
                direction="NEUTRAL",
                confidence=cls.CONFIDENCE_MEDIUM,
                setup_name="WAIT_SIGNAL",
                reasons=["Awaiting setup maturation or market structure shift."],
                market_status=market_status,
                is_actionable=False,
            )

        else:
            return SignalLabel(
                signal_type=SignalDecision.NO_TRADE,
                decision_time=dt,
                direction="NEUTRAL",
                confidence=0.0,
                setup_name="NO_ACTION",
                reasons=["No clear directional edge or bias specified."],
                market_status=market_status,
                is_actionable=False,
            )


class OutcomeCalculator:
    """
    Task 2: Institutional Outcome Calculation & Scale-Normalized Threshold Governance.
    - Eliminates hardcoded ₹50 nominal threshold.
    - Requires approved ThresholdConfiguration (e.g. Return on Risk R).
    - Classifies unconfigured outcomes as UNCONFIGURED (non-training eligible).
    - Prevents binary and multiclass target contradiction.
    """

    @classmethod
    def calculate_outcome(
        cls,
        trade: Dict[str, Any],
        threshold_config: Optional[ThresholdConfiguration] = None,
    ) -> RealizedOutcomeLabel:
        trade_id = str(trade.get("id") or trade.get("tradeId") or "UNKNOWN_TRADE")

        # 1. Entry & Exit Timestamps
        raw_entry_ts = trade.get("entryTimestamp") or trade.get("entryTime") or trade.get("timestamp")
        raw_exit_ts = trade.get("exitTimestamp") or trade.get("exitTime")

        if not raw_entry_ts:
            raise ValueError(f"Trade {trade_id} missing entry timestamp.")

        entry_dt = parse_ist_timestamp(raw_entry_ts)

        # Check if trade is unresolved (open or missing exit)
        is_open_status = str(trade.get("status", "")).upper() == "OPEN"
        has_no_exit = not raw_exit_ts or (trade.get("exitPrice") is None and trade.get("exitPremium") is None)
        if is_open_status or has_no_exit:
            return RealizedOutcomeLabel(
                trade_id=trade_id,
                entry_time=entry_dt,
                exit_time=entry_dt,
                holding_duration_seconds=0.0,
                entry_price=float(trade.get("entryPrice") or trade.get("entryPremium") or 0.0),
                exit_price=0.0,
                quantity=int(trade.get("quantity", 0)),
                gross_pnl=0.0,
                total_charges=0.0,
                net_pnl=0.0,
                binary_target=-1,
                multiclass_target=MultiClassTarget.UNCONFIGURED,
                outcome_class=OutcomeClass.UNRESOLVED,
                is_genuine=False,
                is_training_eligible=False,
                status="UNRESOLVED",
                metadata={"reason": "Position still open or exit observation missing."},
            )

        exit_dt = parse_ist_timestamp(raw_exit_ts)

        # 2. Strict Causality Check
        if exit_dt < entry_dt:
            raise ValueError(
                f"Temporal causality violation for trade {trade_id}: "
                f"exit_time ({exit_dt.isoformat()}) precedes entry_time ({entry_dt.isoformat()})."
            )

        holding_sec = (exit_dt - entry_dt).total_seconds()

        # 3. Prices and Quantities
        entry_p = float(trade.get("entryPrice") or trade.get("entryPremium") or 0.0)
        exit_p = float(trade.get("exitPrice") or trade.get("exitPremium") or 0.0)

        if "quantity" in trade and trade["quantity"] is not None:
            qty = int(trade["quantity"])
        elif "lots" in trade and trade["lots"] is not None:
            qty = int(trade["lots"]) * 65
        else:
            qty = 0

        if entry_p <= 0.0:
            raise ValueError(f"Trade {trade_id} has invalid non-positive entry price: {entry_p}")
        if exit_p < 0.0:
            raise ValueError(f"Trade {trade_id} has negative exit price: {exit_p}")
        if qty <= 0:
            raise ValueError(f"Trade {trade_id} has invalid non-positive quantity: {qty}")

        # 4. PnL and Transaction Costs
        if "netPnl" in trade and "transactionCharges" in trade:
            gross_pnl = float(trade.get("grossPnl", (exit_p - entry_p) * qty))
            charges = float(trade.get("transactionCharges") or trade.get("charges") or 0.0)
            net_pnl = float(trade.get("netPnl"))
        elif "netPnl" in trade and "charges" in trade:
            gross_pnl = float(trade.get("grossPnl", (exit_p - entry_p) * qty))
            charges = float(trade.get("charges", 0.0))
            net_pnl = float(trade.get("netPnl"))
        else:
            calc_res = IndianDerivativesCostCalculator.calculate_trade_costs_and_pnl(
                entry_price=entry_p,
                exit_price=exit_p,
                quantity=qty,
                position_type="BUY",
            )
            gross_pnl = float(calc_res.get("grossPnl", calc_res.get("gross_pnl", 0.0)))
            charges = float(calc_res.get("totalCosts", calc_res.get("total_charges", 0.0)))
            net_pnl = float(calc_res.get("netPnl", calc_res.get("net_pnl", 0.0)))

        # 5. Excursions & Return on Risk
        mfe_pts = float(trade.get("mfePts", 0.0))
        mae_pts = float(trade.get("maePts", 0.0))

        sl = float(trade.get("stopLoss", 0.0))
        return_on_risk: Optional[float] = None
        initial_risk_rupees = 0.0
        if sl > 0.0 and entry_p > sl:
            initial_risk_rupees = (entry_p - sl) * qty
            if initial_risk_rupees > 0.0:
                return_on_risk = round(net_pnl / initial_risk_rupees, 3)

        # 6. Scale-Normalized Threshold Governance (Zero Hardcoded Nominal Constants)
        cfg = threshold_config or ThresholdConfiguration()
        is_training_eligible = False
        binary_target = -1
        multiclass_target = MultiClassTarget.UNCONFIGURED
        outcome_class = OutcomeClass.UNCONFIGURED
        threshold_metadata: Dict[str, Any] = {
            "threshold_configured": cfg.is_approved,
            "threshold_type": cfg.threshold_type.value,
        }

        if not cfg.is_approved:
            # Threshold unapproved: classify as UNCONFIGURED and non-training-eligible
            is_training_eligible = False
            multiclass_target = MultiClassTarget.UNCONFIGURED
            outcome_class = OutcomeClass.UNCONFIGURED
            binary_target = -1
            threshold_metadata["reason"] = "Threshold configuration unapproved; outcome barred from training eligibility."

        elif cfg.threshold_type == ThresholdType.RETURN_ON_RISK:
            val = cfg.threshold_value
            if val is None or val < 0.0:
                is_training_eligible = False
                multiclass_target = MultiClassTarget.UNCONFIGURED
                outcome_class = OutcomeClass.UNCONFIGURED
                binary_target = -1
                threshold_metadata["reason"] = "Invalid or missing threshold_value for RETURN_ON_RISK."
            elif initial_risk_rupees < cfg.min_initial_risk_rupees:
                # Initial risk missing or below minimum threshold
                is_training_eligible = False
                multiclass_target = MultiClassTarget.UNCONFIGURED
                outcome_class = OutcomeClass.UNCONFIGURED
                binary_target = -1
                threshold_metadata["reason"] = f"Initial risk (₹{initial_risk_rupees:.1f}) below minimum required (₹{cfg.min_initial_risk_rupees:.1f})."
            else:
                # Scale-normalized classification on R
                r = net_pnl / initial_risk_rupees
                threshold_metadata["r_multiple"] = round(r, 4)
                threshold_metadata["epsilon"] = val

                if r > val:
                    multiclass_target = MultiClassTarget.WIN
                    outcome_class = OutcomeClass.WIN
                    binary_target = 1
                    is_training_eligible = True
                elif r < -val:
                    multiclass_target = MultiClassTarget.LOSS
                    outcome_class = OutcomeClass.LOSS
                    binary_target = 0
                    is_training_eligible = True
                else:
                    # Scratch outcome
                    multiclass_target = MultiClassTarget.SCRATCH
                    outcome_class = OutcomeClass.SCRATCH
                    # Contradiction Prevention: Scratch is quarantined from binary directional training
                    binary_target = -1
                    is_training_eligible = True
                    threshold_metadata["binary_directional_eligible"] = False

        return RealizedOutcomeLabel(
            trade_id=trade_id,
            entry_time=entry_dt,
            exit_time=exit_dt,
            holding_duration_seconds=holding_sec,
            entry_price=entry_p,
            exit_price=exit_p,
            quantity=qty,
            gross_pnl=round(gross_pnl, 2),
            total_charges=round(charges, 2),
            net_pnl=round(net_pnl, 2),
            binary_target=binary_target,
            multiclass_target=multiclass_target,
            outcome_class=outcome_class,
            mfe_pts=mfe_pts,
            mae_pts=mae_pts,
            return_on_risk=return_on_risk,
            is_genuine=True,
            is_training_eligible=is_training_eligible,
            status="CLOSED",
            metadata={
                "exitReason": trade.get("exitReason", "CLOSED"),
                "strategy": trade.get("strategy", ""),
                "threshold_governance": threshold_metadata,
            }
        )


@dataclass
class WalkForwardFold:
    fold_index: int
    train_indices: List[int]
    val_indices: List[int]
    purged_indices: List[int]
    embargoed_indices: List[int]
    train_start_time: datetime
    train_end_time: datetime
    val_start_time: datetime
    val_end_time: datetime
    embargo_end_time: datetime


@dataclass
class PartitionSplit:
    folds: List[WalkForwardFold]
    oos_indices: List[int]
    oos_start_time: Optional[datetime]
    oos_end_time: Optional[datetime]
    total_samples: int
    metadata: Dict[str, Any] = field(default_factory=dict)


class WalkForwardPartitionEngine:
    """
    Task 3: Institutional Walk-Forward Partition Engine with Proactive OOS Purging & Embargo.
    Implements:
    - Chronological sorting by entry time.
    - Proactive purging of ANY training or validation trade whose outcome spills into OOS holdout.
    - Embargo between development dataset and Out-Of-Sample (OOS) holdout.
    - Strict boundary equality handling.
    """

    @classmethod
    def _extract_times(cls, sample: Any) -> Tuple[datetime, datetime]:
        if isinstance(sample, RealizedOutcomeLabel):
            return sample.entry_time, sample.exit_time
        elif isinstance(sample, dict):
            entry_raw = sample.get("entryTimestamp") or sample.get("entryTime") or sample.get("timestamp")
            exit_raw = sample.get("exitTimestamp") or sample.get("exitTime") or entry_raw
            return parse_ist_timestamp(entry_raw), parse_ist_timestamp(exit_raw)
        else:
            raise TypeError(f"Unsupported sample type: {type(sample)}")

    @classmethod
    def partition(
        cls,
        samples: List[Any],
        n_splits: int = 3,
        oos_ratio: float = 0.20,
        embargo_duration: timedelta = timedelta(minutes=30),
        purge_overlapping: bool = True,
        oos_embargo_duration: Optional[timedelta] = None,
    ) -> PartitionSplit:
        if not samples:
            return PartitionSplit(folds=[], oos_indices=[], oos_start_time=None, oos_end_time=None, total_samples=0)

        n_total = len(samples)
        if n_total < 4:
            raise ValueError(f"Insufficient samples for walk-forward partitioning: {n_total} (minimum 4 required).")

        # 1. Chronological Sorting by entry time
        decorated = []
        for i, s in enumerate(samples):
            entry_dt, exit_dt = cls._extract_times(s)
            decorated.append((entry_dt, exit_dt, i))

        decorated.sort(key=lambda x: x[0])
        sorted_indices = [x[2] for x in decorated]

        # 2. Separate Out-Of-Sample (OOS) holdout with OOS Embargo
        actual_oos_embargo = oos_embargo_duration if oos_embargo_duration is not None else embargo_duration
        n_oos = int(n_total * oos_ratio) if oos_ratio > 0.0 else 0

        oos_embargoed_indices: List[int] = []
        if n_oos > 0 and n_oos < n_total:
            dev_candidate_indices = sorted_indices[:-n_oos]
            oos_candidate_indices = sorted_indices[-n_oos:]

            dev_end_dt = decorated[sorted_indices.index(dev_candidate_indices[-1])][0]
            oos_embargo_end_dt = dev_end_dt + actual_oos_embargo

            # OOS Embargo Enforcement: quarantine OOS candidates too close to dev_end
            oos_indices = []
            for idx in oos_candidate_indices:
                entry_dt, _, _ = next(item for item in decorated if item[2] == idx)
                if entry_dt < oos_embargo_end_dt:
                    oos_embargoed_indices.append(idx)
                else:
                    oos_indices.append(idx)
        else:
            dev_candidate_indices = sorted_indices
            oos_indices = []

        oos_start_dt = decorated[sorted_indices.index(oos_indices[0])][0] if oos_indices else None
        oos_end_dt = decorated[sorted_indices.index(oos_indices[-1])][1] if oos_indices else None

        # 3. Create Multi-Fold Walk-Forward on Development Set
        dev_indices = dev_candidate_indices
        n_dev = len(dev_indices)
        if n_dev < n_splits + 1:
            raise ValueError(
                f"Development set size ({n_dev}) too small for {n_splits} splits. "
                "Reduce n_splits or oos_ratio."
            )

        folds: List[WalkForwardFold] = []
        val_slice_size = max(1, n_dev // (n_splits + 1))

        for k in range(n_splits):
            train_cut = (k + 1) * val_slice_size
            val_end_cut = min(n_dev, (k + 2) * val_slice_size)
            if k == n_splits - 1:
                val_end_cut = n_dev

            candidate_train_idx = dev_indices[:train_cut]
            candidate_val_idx = dev_indices[train_cut:val_end_cut]

            if not candidate_train_idx or not candidate_val_idx:
                continue

            train_start_dt = decorated[sorted_indices.index(candidate_train_idx[0])][0]
            train_end_dt = decorated[sorted_indices.index(candidate_train_idx[-1])][0]

            val_start_dt = decorated[sorted_indices.index(candidate_val_idx[0])][0]
            val_end_dt = decorated[sorted_indices.index(candidate_val_idx[-1])][1]

            embargo_end_dt = train_end_dt + embargo_duration

            # 4. Chronological Purging (including Proactive OOS Purging)
            purged: List[int] = []
            final_train: List[int] = []

            if purge_overlapping:
                for idx in candidate_train_idx:
                    _, exit_dt, _ = next(item for item in decorated if item[2] == idx)
                    # Purge if exit overlaps into validation window OR into OOS holdout
                    if exit_dt >= val_start_dt or (oos_start_dt and exit_dt >= oos_start_dt):
                        purged.append(idx)
                    else:
                        final_train.append(idx)
            else:
                final_train = list(candidate_train_idx)

            # 5. Embargo Enforcement and Proactive OOS Purging for Validation
            embargoed: List[int] = []
            final_val: List[int] = []
            for idx in candidate_val_idx:
                entry_dt, exit_dt, _ = next(item for item in decorated if item[2] == idx)

                # Embargo check against train_end
                if entry_dt < embargo_end_dt:
                    embargoed.append(idx)
                    continue

                # Proactive OOS Purge: validation trade whose outcome spills into OOS is purged
                if purge_overlapping and oos_start_dt and exit_dt >= oos_start_dt:
                    purged.append(idx)
                    continue

                final_val.append(idx)

            folds.append(
                WalkForwardFold(
                    fold_index=k,
                    train_indices=final_train,
                    val_indices=final_val,
                    purged_indices=purged,
                    embargoed_indices=embargoed,
                    train_start_time=train_start_dt,
                    train_end_time=train_end_dt,
                    val_start_time=val_start_dt,
                    val_end_time=val_end_dt,
                    embargo_end_time=embargo_end_dt,
                )
            )

        return PartitionSplit(
            folds=folds,
            oos_indices=oos_indices,
            oos_start_time=oos_start_dt,
            oos_end_time=oos_end_dt,
            total_samples=n_total,
            metadata={
                "schema_version": SCHEMA_VERSION,
                "n_splits": n_splits,
                "oos_ratio": oos_ratio,
                "embargo_seconds": embargo_duration.total_seconds(),
                "oos_embargo_seconds": actual_oos_embargo.total_seconds(),
                "oos_embargoed_count": len(oos_embargoed_indices),
                "purge_overlapping": purge_overlapping,
            }
        )


class LeakageGuard:
    """
    Independent Auditor verifying zero temporal leakage, zero partition overlap,
    proactive OOS purging, and rigorous embargo compliance across all folds.
    """

    @classmethod
    def audit_partitions(
        cls,
        partition: PartitionSplit,
        samples: List[Any],
    ) -> Tuple[bool, List[str]]:
        violations: List[str] = []

        oos_set = set(partition.oos_indices)

        for fold in partition.folds:
            train_set = set(fold.train_indices)
            val_set = set(fold.val_indices)

            # 1. Internal index overlaps
            train_val_overlap = train_set.intersection(val_set)
            if train_val_overlap:
                violations.append(
                    f"Fold {fold.fold_index}: Train and Validation indices overlap: {train_val_overlap}"
                )

            train_oos_overlap = train_set.intersection(oos_set)
            if train_oos_overlap:
                violations.append(
                    f"Fold {fold.fold_index}: Train and OOS indices overlap: {train_oos_overlap}"
                )

            val_oos_overlap = val_set.intersection(oos_set)
            if val_oos_overlap:
                violations.append(
                    f"Fold {fold.fold_index}: Val and OOS indices overlap: {val_oos_overlap}"
                )

            # 2. Purging verification vs Validation window
            for idx in fold.train_indices:
                entry_dt, exit_dt = WalkForwardPartitionEngine._extract_times(samples[idx])
                if exit_dt >= fold.val_start_time:
                    violations.append(
                        f"Fold {fold.fold_index}: Purge failure! Train sample {idx} exit {exit_dt.isoformat()} "
                        f"spills into validation window starting {fold.val_start_time.isoformat()}."
                    )

            # 3. Embargo verification vs Training end
            for idx in fold.val_indices:
                entry_dt, exit_dt = WalkForwardPartitionEngine._extract_times(samples[idx])
                if entry_dt < fold.embargo_end_time:
                    violations.append(
                        f"Fold {fold.fold_index}: Embargo violation! Val sample {idx} entry {entry_dt.isoformat()} "
                        f"falls within embargo period ending {fold.embargo_end_time.isoformat()}."
                    )

            # 4. Proactive OOS Purge Verification (Train and Val MUST be resolved before OOS starts)
            if partition.oos_start_time and partition.oos_indices:
                for idx in fold.train_indices:
                    entry_dt, exit_dt = WalkForwardPartitionEngine._extract_times(samples[idx])
                    if exit_dt >= partition.oos_start_time:
                        violations.append(
                            f"Fold {fold.fold_index}: Proactive OOS Purge failure! Train sample {idx} exit {exit_dt.isoformat()} "
                            f"spills into OOS holdout starting {partition.oos_start_time.isoformat()}."
                        )
                for idx in fold.val_indices:
                    entry_dt, exit_dt = WalkForwardPartitionEngine._extract_times(samples[idx])
                    if exit_dt >= partition.oos_start_time:
                        violations.append(
                            f"Fold {fold.fold_index}: Proactive OOS Purge failure! Val sample {idx} exit {exit_dt.isoformat()} "
                            f"spills into OOS holdout starting {partition.oos_start_time.isoformat()}."
                        )

        is_clean = len(violations) == 0
        return is_clean, violations
