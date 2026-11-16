"""
AIVOLVE Institutional Quantitative Trading Intelligence v3.0
Phase 3 Step 3.7 — Multi-Timeframe (MTF) ICT/SMC Confluence Engine.

Deterministic, point-in-time Multi-Timeframe ICT/SMC intelligence synthesizer evaluating
existing Phase 3 outputs (Steps 3.1–3.6) across the institutional five-timeframe hierarchy:
  - 1H  : Higher Timeframe context
  - 15M : Intermediate structure
  - 5M  : Primary setup timeframe
  - 3M  : Entry refinement context
  - 1M  : Lower timeframe confirmation

Strict Governance & Safety Policies:
- Operating mode: `PAPER_TRADING_ONLY` (market intelligence only; zero trade execution).
- Never triggers `BUY_CE` or `BUY_PE`, modifies paper balances, or alters Phase 2 MTF
  weights, risk parameters, or contract selection.
- ICT Confluence Score remains strictly `None` with `score_status="UNAVAILABLE"` and
  `calibration_status="NOT_CALIBRATED"` until separately calibrated and approved.
  No timeframe weights, base scores, bonuses, or penalties are invented or applied.
- Does NOT duplicate or redefine Steps 3.1–3.6 engines; consumes existing Step 3.1–3.6
  outputs directly or orchestrates existing frozen engines cleanly.
- Strict no-lookahead causality: `available_at <= as_of_time`, completed candles only,
  invalidated/expired/unavailable lifecycle enforcement, duplicate event suppression,
  and deterministic SHA-256 identifiers (`MTF-...`, `CNFL-...`).
- Fail closed on disqualified feeds, stale/unavailable/incomplete evidence, invalid
  timestamps/OHLC, or unapproved `SENSEX` governance.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, time as dt_time
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple, Union
from zoneinfo import ZoneInfo

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.data.quality_validator import DataQualityEngine, FeedStatus
from app.options.candle_processor import calculate_atr_wilder, calculate_true_range
from app.options.ict_smc.fvg_engine import FVGEngine, TimeframeFVGReport
from app.options.ict_smc.ict_models import (
    EventDirection,
    FVGEvent,
    ICTEvent,
    ICTEventType,
    LiquidityEvent,
    LiquidityLifecycleState,
    LiquidityPool,
    MarketStructureEvent,
    MarketStructureEvidence,
    OrderBlockEvent,
    canonicalize_value,
)
from app.options.ict_smc.liquidity_engine import LiquidityIntelligenceEngine
from app.options.ict_smc.market_structure import MarketStructureEngine, TimeframeStructureReport
from app.options.ict_smc.order_block_engine import OrderBlockEngine, TimeframeOrderBlockReport
from app.options.ict_smc.premium_discount_engine import (
    DealingRange,
    DealingRangeStatus,
    InducementEvent,
    InducementStatus,
    PremiumDiscountEngine,
    TimeframePremiumDiscountReport,
    ZoneClassification,
)
from app.options.ict_smc.session_engine import (
    SessionConfiguration,
    SessionEvent,
    SessionEventKind,
    SessionIntelligenceEngine,
    SessionPhaseStatus,
    TimeframeSessionReport,
    _strict_bool_completion_flag,
    compute_candle_close_ist,
    normalize_feed_status,
    normalize_index_symbol,
)
from app.options.ict_smc.swing_detection import SwingDetectionEngine


# ============================================================================
# Constants & Canonical Enumerations
# ============================================================================

ENGINE_VERSION: str = "3.7.0"
DEFAULT_CONFIGURATION_VERSION: str = "3.7.0"
EXECUTION_MODE: str = "PAPER_TRADING_ONLY"
DEFAULT_TIMEZONE_NAME: str = "Asia/Kolkata"
IST_ZONE: ZoneInfo = ZoneInfo(DEFAULT_TIMEZONE_NAME)

MTF_TIMEFRAME_ORDER: Tuple[str, ...] = ("1h", "15m", "5m", "3m", "1m")

TIMEFRAME_ALIASES: Dict[str, str] = {
    "1h": "1h",
    "60m": "1h",
    "15m": "15m",
    "5m": "5m",
    "3m": "3m",
    "1m": "1m",
}

TIMEFRAME_ROLES: Dict[str, str] = {
    "1h": "HIGHER_TIMEFRAME_CONTEXT",
    "15m": "INTERMEDIATE_STRUCTURE",
    "5m": "PRIMARY_SETUP_TIMEFRAME",
    "3m": "ENTRY_REFINEMENT_CONTEXT",
    "1m": "LOWER_TIMEFRAME_CONFIRMATION",
}

DEFAULT_MAX_EVIDENCE_AGE_MINUTES: Dict[str, int] = {
    "1h": 720,
    "15m": 480,
    "5m": 420,
    "3m": 390,
    "1m": 390,
}

VALID_FEED_STATUSES: Set[str] = {
    FeedStatus.VERIFIED_LIVE.value if hasattr(FeedStatus.VERIFIED_LIVE, "value") else "VERIFIED_LIVE",
    FeedStatus.VERIFIED_EOD.value if hasattr(FeedStatus.VERIFIED_EOD, "value") else "VERIFIED_EOD",
    "VERIFIED_LIVE",
    "VERIFIED_EOD",
    "PRISTINE",
}

DISQUALIFYING_FEED_STATUSES: Set[str] = {
    "DATA_OFFLINE",
    "DATA_UNAVAILABLE",
    "STALE",
    "STALE_TICK",
    "DEGRADED",
    "ANOMALOUS",
    "SYNTHETIC",
    "OFFLINE",
    "UNAVAILABLE",
    "MOCK",
    "UNKNOWN",
    "INVALID_DATA",
    "CALENDAR_UNAVAILABLE",
    "NON_TRADING_DAY",
    "GOVERNANCE_LOCKOUT",
}

INACTIVE_TERMINAL_STATES: Set[LiquidityLifecycleState] = {
    LiquidityLifecycleState.INVALIDATED,
    LiquidityLifecycleState.EXPIRED,
    LiquidityLifecycleState.CONSUMED,
    LiquidityLifecycleState.MITIGATED,
}


class AlignmentClassification(str, Enum):
    """Descriptive multi-timeframe ICT/SMC alignment state (zero predictive claims)."""

    STRONG_BULLISH_ALIGNMENT = "STRONG_BULLISH_ALIGNMENT"
    BULLISH_ALIGNMENT = "BULLISH_ALIGNMENT"
    STRONG_BEARISH_ALIGNMENT = "STRONG_BEARISH_ALIGNMENT"
    BEARISH_ALIGNMENT = "BEARISH_ALIGNMENT"
    MIXED_ALIGNMENT = "MIXED_ALIGNMENT"
    NEUTRAL = "NEUTRAL"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    DATA_QUALITY_LOCKOUT = "DATA_QUALITY_LOCKOUT"


class ConflictType(str, Enum):
    """Structured ICT/SMC conflict categories."""

    HTF_ITF_DIVERGENCE = "HTF_ITF_DIVERGENCE"
    ITF_PRIMARY_DIVERGENCE = "ITF_PRIMARY_DIVERGENCE"
    PRIMARY_LTF_DIVERGENCE = "PRIMARY_LTF_DIVERGENCE"
    CROSS_TIMEFRAME_DIVERGENCE = "CROSS_TIMEFRAME_DIVERGENCE"
    HTF_LIQUIDITY_CONFLICT = "HTF_LIQUIDITY_CONFLICT"
    LIQUIDITY_CONFLICT = "LIQUIDITY_CONFLICT"
    PREMIUM_DISCOUNT_CONFLICT = "PREMIUM_DISCOUNT_CONFLICT"
    OB_FVG_INVALIDATION = "OB_FVG_INVALIDATION"
    SESSION_CONTEXT_CONFLICT = "SESSION_CONTEXT_CONFLICT"
    MISSING_TIMEFRAME_EVIDENCE = "MISSING_TIMEFRAME_EVIDENCE"
    STALE_OR_UNAVAILABLE_EVIDENCE = "STALE_OR_UNAVAILABLE_EVIDENCE"


class ConflictSeverity(str, Enum):
    """Severity of detected multi-timeframe conflicts."""

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    INFO = "INFO"


# ============================================================================
# Strict Type, Datetime & Deterministic Hashing Helpers
# ============================================================================

def _require_exact_str(val: Any, field_name: str) -> str:
    """Enforces exact built-in `str` to reject subclasses with overridden behaviors."""
    if type(val) is not str:
        raise TypeError(f"{field_name} must be an exact built-in str, got {type(val).__name__}")
    clean = val.strip()
    if not clean:
        raise ValueError(f"{field_name} cannot be empty")
    return clean


def _require_exact_list(val: Any, field_name: str) -> List[Any]:
    """Enforces exact built-in `list` to block mutating/untrusted container subclasses."""
    if type(val) is not list:
        raise TypeError(f"{field_name} must be an exact built-in list, got {type(val).__name__}")
    return val


def is_valid_tz_aware_datetime(dt: Any) -> bool:
    """Returns True iff `dt` is a datetime with a non-None UTC offset."""
    if not isinstance(dt, datetime):
        return False
    if dt.tzinfo is None:
        return False
    try:
        offset = dt.tzinfo.utcoffset(dt)
    except Exception:
        return False
    return offset is not None


def _convert_to_tz(dt: Any, tz: ZoneInfo, field_name: str) -> datetime:
    """Validates timezone-awareness strictly and converts to `tz`."""
    if isinstance(dt, pd.Timestamp):
        if pd.isna(dt):
            raise ValueError(f"{field_name} cannot be NaT")
        dt = dt.to_pydatetime()
    if not is_valid_tz_aware_datetime(dt):
        raise ValueError(f"{field_name} must be a valid timezone-aware datetime, got {dt!r}")
    return dt.astimezone(tz)


def _to_builtin_primitives(obj: Any) -> Any:
    """Recursively normalizes pd.Timestamp and NumPy scalars into native Python built-ins."""
    if isinstance(obj, pd.Timestamp):
        return None if pd.isna(obj) else obj.to_pydatetime()
    if isinstance(obj, dict):
        return {k: _to_builtin_primitives(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_builtin_primitives(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(_to_builtin_primitives(v) for v in obj)
    if getattr(type(obj), "__module__", None) == "numpy" and hasattr(obj, "item"):
        return obj.item()
    return obj


def _normalize_model_native(model_obj: Any) -> Any:
    """Returns a same-class Pydantic copy with Timestamp/NumPy fields converted to native built-ins."""
    updates: Dict[str, Any] = {}
    for fname in type(model_obj).model_fields:
        val = getattr(model_obj, fname)
        if (
            isinstance(val, (pd.Timestamp, dict, list, tuple))
            or getattr(type(val), "__module__", None) == "numpy"
        ):
            updates[fname] = _to_builtin_primitives(val)
    return model_obj.model_copy(update=updates) if updates else model_obj


def normalize_mtf_timeframe(timeframe: Any) -> str:
    """Normalizes strictly into one of the five supported MTF hierarchy keys."""
    clean = _require_exact_str(timeframe, "timeframe").lower()
    if clean not in TIMEFRAME_ALIASES:
        raise ValueError(
            f"Unsupported MTF timeframe '{timeframe}'. Permitted: {MTF_TIMEFRAME_ORDER}"
        )
    return TIMEFRAME_ALIASES[clean]


def generate_deterministic_mtf_id(
    prefix: str,
    parts: Sequence[str],
) -> str:
    """Generates reproducible SHA-256 identifier with fixed canonical prefix."""
    payload = "|".join(parts)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20].upper()
    return f"{prefix}-{digest}"


# ============================================================================
# Configuration & Input Bundle Contracts
# ============================================================================

class MTFConfluenceConfiguration(BaseModel):
    """
    Configuration for Phase 3 Step 3.7 MTF Confluence Engine.
    Contains ZERO scoring weights, base scores, bonuses, penalties, or trade thresholds.
    """

    model_config = ConfigDict(frozen=True)

    configuration_version: str = DEFAULT_CONFIGURATION_VERSION
    timezone_name: str = DEFAULT_TIMEZONE_NAME
    sensex_governance_approved: bool = False
    enforce_staleness_checks: bool = True
    max_evidence_age_minutes_by_tf: Dict[str, int] = Field(
        default_factory=lambda: dict(DEFAULT_MAX_EVIDENCE_AGE_MINUTES)
    )
    market_close_hhmm: str = "15:30"
    execution_mode: str = EXECUTION_MODE

    @model_validator(mode="after")
    def _validate_cfg(self) -> "MTFConfluenceConfiguration":
        _require_exact_str(self.configuration_version, "configuration_version")
        tz_clean = _require_exact_str(self.timezone_name, "timezone_name")
        try:
            ZoneInfo(tz_clean)
        except Exception as exc:
            raise ValueError(f"Invalid timezone_name '{self.timezone_name}': {exc}") from exc

        if self.execution_mode != EXECUTION_MODE:
            raise ValueError(f"execution_mode must be '{EXECUTION_MODE}', got '{self.execution_mode}'")

        for tf in MTF_TIMEFRAME_ORDER:
            if tf not in self.max_evidence_age_minutes_by_tf:
                raise ValueError(f"Missing max_evidence_age_minutes entry for timeframe '{tf}'")
            age_val = self.max_evidence_age_minutes_by_tf[tf]
            if type(age_val) is bool or not isinstance(age_val, int) or age_val <= 0:
                raise ValueError(f"max_evidence_age_minutes for '{tf}' must be positive int")
        return self

    def get_zone_info(self) -> ZoneInfo:
        return ZoneInfo(self.timezone_name)

    def configuration_fingerprint(self) -> str:
        canonical = canonicalize_value(self.model_dump())
        encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24].upper()


class TimeframeEvidenceBundle(BaseModel):
    """
    Aggregated outputs from Steps 3.1–3.6 for a single timeframe supplied to Step 3.7.
    All optional lists preserve strict Pydantic validation and immutable semantics.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    timeframe: str
    data_quality: str = "VERIFIED_LIVE"
    candles_df: Optional[Any] = None
    liquidity_pools: List[LiquidityPool] = Field(default_factory=list)
    liquidity_events: List[LiquidityEvent] = Field(default_factory=list)
    structure_events: List[Union[MarketStructureEvent, ICTEvent]] = Field(default_factory=list)
    structure_report: Optional[TimeframeStructureReport] = None
    order_block_events: List[Union[OrderBlockEvent, ICTEvent]] = Field(default_factory=list)
    order_block_report: Optional[TimeframeOrderBlockReport] = None
    fvg_events: List[Union[FVGEvent, ICTEvent]] = Field(default_factory=list)
    fvg_report: Optional[TimeframeFVGReport] = None
    premium_discount_report: Optional[TimeframePremiumDiscountReport] = None
    dealing_ranges: List[DealingRange] = Field(default_factory=list)
    inducement_events: List[InducementEvent] = Field(default_factory=list)
    session_report: Optional[TimeframeSessionReport] = None
    session_events: List[SessionEvent] = Field(default_factory=list)
    ict_events: List[ICTEvent] = Field(default_factory=list)
    current_price: Optional[float] = None


# ============================================================================
# Output Contract Models (Sections 6 & 9)
# ============================================================================

class EvidenceSummaryItem(BaseModel):
    """Traceable source evidence entry grouped into bullish, bearish, or neutral buckets."""

    model_config = ConfigDict(frozen=True)

    event_id: str
    timeframe: str
    source_module: str
    event_category: str
    direction: EventDirection
    event_time: datetime
    available_at: datetime
    status: str
    summary: str


class ConflictRecord(BaseModel):
    """Structured multi-timeframe or intra-timeframe conflict record (Section 6)."""

    model_config = ConfigDict(frozen=True)

    conflict_id: str
    timeframe_a: str
    timeframe_b: str
    conflict_type: ConflictType
    direction_a: str
    direction_b: str
    severity: ConflictSeverity
    evidence_event_ids: Tuple[str, ...]
    event_time: datetime
    available_at: datetime
    explanation: str


class TimeframeConfluenceReport(BaseModel):
    """Per-timeframe ICT/SMC confluence evaluation matching Section 9 contract."""

    model_config = ConfigDict(frozen=True)

    timeframe: str
    timeframe_role: str
    direction: str
    evidence_event_ids: Tuple[str, ...] = ()
    structure_status: str = "UNAVAILABLE"
    liquidity_status: str = "UNAVAILABLE"
    order_block_status: str = "UNAVAILABLE"
    fvg_status: str = "UNAVAILABLE"
    premium_discount_status: str = "UNAVAILABLE"
    inducement_status: str = "UNAVAILABLE"
    session_status: str = "UNAVAILABLE"
    data_quality: str = "DATA_UNAVAILABLE"
    available_at: Optional[datetime] = None
    has_valid_evidence: bool = False
    bullish_signals: Tuple[str, ...] = ()
    bearish_signals: Tuple[str, ...] = ()
    neutral_signals: Tuple[str, ...] = ()
    future_events_excluded: int = 0
    invalidated_event_ids: Tuple[str, ...] = ()
    expired_event_ids: Tuple[str, ...] = ()
    future_candles_excluded: int = 0
    incomplete_candles_excluded: int = 0


class MTFConfluenceReport(BaseModel):
    """
    Top-level Step 3.7 Multi-Timeframe ICT/SMC Confluence Report (Section 9).
    Enforces PAPER_TRADING_ONLY and UNAVAILABLE / NOT_CALIBRATED scoring at construction.
    """

    model_config = ConfigDict(frozen=True)

    report_id: str
    index: str
    analysis_time: datetime
    execution_mode: str = EXECUTION_MODE
    overall_alignment: AlignmentClassification
    timeframe_reports: Dict[str, TimeframeConfluenceReport] = Field(default_factory=dict)
    bullish_evidence: Tuple[EvidenceSummaryItem, ...] = ()
    bearish_evidence: Tuple[EvidenceSummaryItem, ...] = ()
    neutral_evidence: Tuple[EvidenceSummaryItem, ...] = ()
    conflicts: Tuple[ConflictRecord, ...] = ()
    missing_timeframes: Tuple[str, ...] = ()
    data_quality_status: str
    confluence_score: Optional[float] = None
    score_status: str = "UNAVAILABLE"
    calibration_status: str = "NOT_CALIBRATED"
    evidence_event_ids: Tuple[str, ...] = ()
    configuration_version: str = DEFAULT_CONFIGURATION_VERSION
    configuration_fingerprint: str
    engine_version: str = ENGINE_VERSION
    explanation: str

    @model_validator(mode="after")
    def _enforce_governance_invariants(self) -> "MTFConfluenceReport":
        if self.execution_mode != EXECUTION_MODE:
            raise ValueError(f"execution_mode must remain '{EXECUTION_MODE}'")
        if self.confluence_score is not None:
            raise ValueError("ICT confluence_score must remain None until separately calibrated")
        if self.score_status != "UNAVAILABLE":
            raise ValueError("ICT score_status must remain 'UNAVAILABLE'")
        if self.calibration_status != "NOT_CALIBRATED":
            raise ValueError("ICT calibration_status must remain 'NOT_CALIBRATED'")
        return self


# ============================================================================
# Step 3.7 Multi-Timeframe ICT/SMC Confluence Engine
# ============================================================================

class MTFConfluenceEngine:
    """
    Phase 3 Step 3.7 Multi-Timeframe ICT/SMC Confluence Engine.

    Consumes existing Step 3.1–3.6 outputs across (1H, 15M, 5M, 3M, 1M) without modifying
    or duplicating any frozen Step 3.1–3.6 engine, Phase 2 weights, or execution logic.
    """

    def __init__(
        self,
        config: Optional[MTFConfluenceConfiguration] = None,
        session_config: Optional[SessionConfiguration] = None,
        calendar: Optional[Any] = None,
    ) -> None:
        self.config = config or MTFConfluenceConfiguration()
        self.tz = self.config.get_zone_info()
        self.config_fingerprint = self.config.configuration_fingerprint()

        # Compose existing frozen Step 3.1–3.6 engines directly (no reimplementation)
        self.swing_engine = SwingDetectionEngine()
        self.liquidity_engine = LiquidityIntelligenceEngine()
        self.structure_engine = MarketStructureEngine()
        self.order_block_engine = OrderBlockEngine()
        self.fvg_engine = FVGEngine()
        self.premium_discount_engine = PremiumDiscountEngine()
        eff_session_cfg = session_config or SessionConfiguration(
            sensex_governance_approved=self.config.sensex_governance_approved
        )
        self.session_engine = SessionIntelligenceEngine(config=eff_session_cfg, calendar=calendar)

    # ------------------------------------------------------------------
    # Strict Timeframe DataFrame Validation (Completed Candles Only)
    # ------------------------------------------------------------------

    def _audit_and_filter_dataframe(
        self,
        df: Any,
        timeframe: str,
        as_of_tz: datetime,
        bundle_status: str,
    ) -> Tuple[Optional[pd.DataFrame], str, List[str], int, int]:
        """
        Validates candle OHLC/timezone/quality and filters strictly to completed bars
        with `candle_close_time <= as_of_tz`. Fails closed on corrupted or mock feeds.
        """
        if df is None:
            return None, bundle_status, [], 0, 0

        if not isinstance(df, pd.DataFrame):
            return None, "INVALID_DATA", [f"[{timeframe}] candles_df must be pandas.DataFrame"], 0, 0

        reasons: List[str] = []
        attrs = df.attrs if (hasattr(df, "attrs") and isinstance(df.attrs, dict)) else {}
        attr_status = attrs.get("data_status") or attrs.get("feed_status") or attrs.get("dataStatus")
        eff_status = normalize_feed_status(attr_status if attr_status is not None else bundle_status)

        if eff_status in DISQUALIFYING_FEED_STATUSES or eff_status not in VALID_FEED_STATUSES:
            reasons.append(f"[{timeframe}] Non-qualifying feed status '{eff_status}'")
        if attrs.get("is_mock") is True or attrs.get("isMock") is True:
            reasons.append(f"[{timeframe}] Mock candle dataset rejected")
        if attrs.get("is_synthetic") is True or attrs.get("isSynthetic") is True:
            reasons.append(f"[{timeframe}] Synthetic candle dataset rejected")
        if attrs.get("ohlc_repaired") is True:
            reasons.append(f"[{timeframe}] ohlc_repaired=True candle dataset rejected")
        if attrs.get("missing_mandatory_candles") is True:
            reasons.append(f"[{timeframe}] missing_mandatory_candles=True")
        if str(attrs.get("quality_status", "")).strip().upper() == "REPAIRED":
            reasons.append(f"[{timeframe}] quality_status=REPAIRED candle dataset rejected")
        try:
            imp_cnt = attrs.get("imputed_bars_count", 0)
            if imp_cnt is not None and int(imp_cnt) > 0:
                reasons.append(f"[{timeframe}] imputed_bars_count={int(imp_cnt)} rejected")
        except Exception:
            reasons.append(f"[{timeframe}] Invalid imputed_bars_count metadata rejected")
        for flag_col, msg in (
            ("is_mock", "Mock candle dataset rejected"),
            ("isMock", "Mock candle dataset rejected"),
            ("is_synthetic", "Synthetic candle dataset rejected"),
            ("isSynthetic", "Synthetic candle dataset rejected"),
            ("ohlc_repaired", "ohlc_repaired=True candle dataset rejected"),
        ):
            if flag_col in df.columns:
                if any(
                    (isinstance(v, bool) and v) or str(v).strip().lower() in ("true", "1")
                    for v in df[flag_col].dropna().tolist()
                ):
                    reasons.append(f"[{timeframe}] {msg} ({flag_col}=True)")

        if df.empty:
            empty_q = (
                eff_status
                if eff_status in DISQUALIFYING_FEED_STATUSES
                else ("INVALID_DATA" if reasons else "NO_COMPLETED_BARS")
            )
            return None, empty_q, reasons, 0, 0

        req_cols = {"timestamp", "open", "high", "low", "close"}
        if not req_cols.issubset(set(df.columns)):
            reasons.append(f"[{timeframe}] Missing mandatory OHLC columns")
            return None, "INVALID_DATA", reasons, 0, 0

        val_res = DataQualityEngine.validate_ohlc(df, timeframe=timeframe)
        if not val_res.get("isValid", True):
            reasons.extend([f"[{timeframe}] {v}" for v in val_res.get("violations", [])])
        if val_res.get("ohlc_repaired", False):
            reasons.append(f"[{timeframe}] Phase 1/2 OHLC repair detected")

        for col in ("open", "high", "low", "close"):
            s = pd.to_numeric(df[col], errors="coerce")
            if s.isna().any() or not s.map(math.isfinite).all() or (s <= 0).any():
                reasons.append(f"[{timeframe}] Invalid non-finite/non-positive values in '{col}'")

        if reasons:
            out_q = eff_status if eff_status in DISQUALIFYING_FEED_STATUSES else "INVALID_DATA"
            return None, out_q, reasons, 0, 0

        close_hh, close_mm = [int(x) for x in self.config.market_close_hhmm.split(":")]
        m_close = dt_time(close_hh, close_mm)
        has_is_complete = "is_complete" in df.columns
        has_is_closed = "is_closed" in df.columns

        keep_indices: List[Any] = []
        future_excluded = 0
        incomplete_excluded = 0
        tz_offsets: Set[Any] = set()

        for idx, row in df.iterrows():
            raw_ts = row["timestamp"]
            try:
                ts_obj = pd.to_datetime(raw_ts) if type(raw_ts) is str else raw_ts
                ts_py = ts_obj.to_pydatetime() if isinstance(ts_obj, pd.Timestamp) else ts_obj
                if is_valid_tz_aware_datetime(ts_py):
                    tz_offsets.add(ts_py.utcoffset())
                open_tz = _convert_to_tz(ts_obj, self.tz, f"{timeframe}.candle.timestamp")
            except Exception as exc:
                return None, "INVALID_DATA", [f"[{timeframe}] Invalid candle timestamp: {exc}"], 0, 0

            close_tz = compute_candle_close_ist(open_tz, timeframe, m_close)
            if open_tz > as_of_tz:
                future_excluded += 1
                continue
            if close_tz > as_of_tz:
                incomplete_excluded += 1
                continue
            if has_is_complete and _strict_bool_completion_flag(row["is_complete"]) is not True:
                incomplete_excluded += 1
                continue
            if has_is_closed and _strict_bool_completion_flag(row["is_closed"]) is not True:
                incomplete_excluded += 1
                continue
            keep_indices.append(idx)

        if len(tz_offsets) > 1:
            return (
                None,
                "INVALID_DATA",
                [f"[{timeframe}] Mixed timezone timestamps rejected"],
                0,
                0,
            )

        filtered = df.loc[keep_indices].copy().reset_index(drop=True)
        filtered.attrs = dict(attrs)
        filtered.attrs["timeframe"] = timeframe
        filtered.attrs["data_status"] = eff_status
        return filtered, eff_status, [], future_excluded, incomplete_excluded

    # ------------------------------------------------------------------
    # Single-Timeframe Evidence Extraction, Lifecycle & Causal Filtering
    # ------------------------------------------------------------------

    def _evaluate_single_timeframe(
        self,
        *,
        tf: str,
        bundle: Optional[TimeframeEvidenceBundle],
        index_norm: str,
        as_of_tz: datetime,
    ) -> Tuple[
        TimeframeConfluenceReport,
        List[EvidenceSummaryItem],
        List[ConflictRecord],
        Dict[str, Any],
    ]:
        """
        Audits, deduplicates, temporally filters, and classifies all ICT/SMC evidence
        for one timeframe without lookahead or numeric weighting.
        """
        tf_role = TIMEFRAME_ROLES[tf]
        if bundle is None:
            return (
                TimeframeConfluenceReport(
                    timeframe=tf,
                    timeframe_role=tf_role,
                    direction="UNAVAILABLE",
                    data_quality="MISSING",
                    has_valid_evidence=False,
                ),
                [],
                [],
                {"pd_zone": None, "liquidity_dirs": set(), "session_dirs": set(), "invalidated": []},
            )

        b_tf = normalize_mtf_timeframe(bundle.timeframe)
        if b_tf != tf:
            raise ValueError(f"Bundle timeframe '{bundle.timeframe}' mismatches key '{tf}'")

        eff_status = normalize_feed_status(bundle.data_quality)
        df_filtered, df_status, df_reasons, future_candles, incomplete_candles = self._audit_and_filter_dataframe(
            bundle.candles_df, tf, as_of_tz, eff_status
        )
        if (df_status in DISQUALIFYING_FEED_STATUSES and not (bundle.candles_df is not None and bundle.candles_df.empty and eff_status in VALID_FEED_STATUSES and not df_reasons)) or eff_status in DISQUALIFYING_FEED_STATUSES or df_reasons:
            lock_q = df_status if df_status in DISQUALIFYING_FEED_STATUSES else (
                eff_status if eff_status in DISQUALIFYING_FEED_STATUSES else "INVALID_DATA"
            )
            c_id = generate_deterministic_mtf_id("CNFL", [index_norm, tf, "LOCKOUT", lock_q, self.config_fingerprint])
            conflict = ConflictRecord(
                conflict_id=c_id,
                timeframe_a=tf,
                timeframe_b=tf,
                conflict_type=ConflictType.STALE_OR_UNAVAILABLE_EVIDENCE,
                direction_a="UNAVAILABLE",
                direction_b="LOCKED_OUT",
                severity=ConflictSeverity.CRITICAL,
                evidence_event_ids=(),
                event_time=as_of_tz,
                available_at=as_of_tz,
                explanation="; ".join(df_reasons) if df_reasons else f"[{tf}] Disqualifying feed status '{lock_q}'",
            )
            return (
                TimeframeConfluenceReport(
                    timeframe=tf,
                    timeframe_role=tf_role,
                    direction="UNAVAILABLE",
                    data_quality=lock_q,
                    has_valid_evidence=False,
                    future_candles_excluded=future_candles,
                    incomplete_candles_excluded=incomplete_candles,
                ),
                [],
                [conflict],
                {"pd_zone": None, "liquidity_dirs": set(), "session_dirs": set(), "invalidated": []},
            )

        # Strict containers validation (exact built-in list)
        _require_exact_list(bundle.liquidity_pools, "liquidity_pools")
        _require_exact_list(bundle.liquidity_events, "liquidity_events")
        _require_exact_list(bundle.structure_events, "structure_events")
        _require_exact_list(bundle.order_block_events, "order_block_events")
        _require_exact_list(bundle.fvg_events, "fvg_events")
        _require_exact_list(bundle.dealing_ranges, "dealing_ranges")
        _require_exact_list(bundle.inducement_events, "inducement_events")
        _require_exact_list(bundle.session_events, "session_events")
        _require_exact_list(bundle.ict_events, "ict_events")

        # Validate if candles_df was passed and zero completed candles remained due to future/incomplete filtering
        if bundle.candles_df is not None and (df_filtered is None or df_filtered.empty):
            # All raw candles were future/incomplete and no completed bar exists
            c_id = generate_deterministic_mtf_id(
                "CNFL", [index_norm, tf, "NO_COMPLETED_BARS", str(future_candles), str(incomplete_candles)]
            )
            return (
                TimeframeConfluenceReport(
                    timeframe=tf,
                    timeframe_role=tf_role,
                    direction="UNAVAILABLE",
                    data_quality="NO_COMPLETED_BARS",
                    has_valid_evidence=False,
                    future_candles_excluded=future_candles,
                    incomplete_candles_excluded=incomplete_candles,
                ),
                [],
                [
                    ConflictRecord(
                        conflict_id=c_id,
                        timeframe_a=tf,
                        timeframe_b=tf,
                        conflict_type=ConflictType.STALE_OR_UNAVAILABLE_EVIDENCE,
                        direction_a="UNAVAILABLE",
                        direction_b="INCOMPLETE_OR_FUTURE_CANDLES",
                        severity=ConflictSeverity.HIGH,
                        evidence_event_ids=(),
                        event_time=as_of_tz,
                        available_at=as_of_tz,
                        explanation=f"[{tf}] Zero completed candles available as of {as_of_tz.isoformat()} "
                        f"(future_excluded={future_candles}, incomplete_excluded={incomplete_candles})",
                    )
                ],
                {"pd_zone": None, "liquidity_dirs": set(), "session_dirs": set(), "invalidated": []},
            )

        seen_event_ids: Set[str] = set()
        bullish_items: List[EvidenceSummaryItem] = []
        bearish_items: List[EvidenceSummaryItem] = []
        neutral_items: List[EvidenceSummaryItem] = []
        invalidated_ids: List[str] = []
        expired_ids: List[str] = []
        future_events_excluded = 0
        latest_available_at: Optional[datetime] = None
        disqualified_reasons: List[str] = []

        def _check_item_meta(
            item_id: str,
            item_idx: str,
            item_tf: str,
            ev_t: Any,
            avail_t: Any,
            inv_t: Any,
            dq: Optional[str],
        ) -> Tuple[bool, Optional[datetime], Optional[datetime], Optional[str]]:
            nonlocal future_events_excluded, latest_available_at
            norm_idx = normalize_index_symbol(item_idx)
            if norm_idx != index_norm:
                raise ValueError(f"Cross-index event '{item_id}' ({norm_idx}) supplied to '{index_norm}'")
            if normalize_mtf_timeframe(item_tf) != tf:
                raise ValueError(f"Cross-timeframe event '{item_id}' ({item_tf}) supplied to '{tf}'")

            e_dt = _convert_to_tz(ev_t, self.tz, f"{item_id}.event_time")
            a_dt = _convert_to_tz(avail_t, self.tz, f"{item_id}.available_at")
            if a_dt < e_dt:
                raise ValueError(f"Causality violation on '{item_id}': available_at < event_time")
            if dq is not None:
                dq_norm = normalize_feed_status(dq)
                if dq_norm in DISQUALIFYING_FEED_STATUSES or dq_norm not in VALID_FEED_STATUSES:
                    disqualified_reasons.append(f"[{tf}] Event '{item_id}' carries disqualifying status '{dq_norm}'")
                    return False, e_dt, a_dt, dq_norm
            if a_dt > as_of_tz:
                future_events_excluded += 1
                return False, e_dt, a_dt, None
            if inv_t is not None:
                i_dt = _convert_to_tz(inv_t, self.tz, f"{item_id}.invalidated_at")
                if i_dt <= as_of_tz:
                    if item_id not in invalidated_ids:
                        invalidated_ids.append(item_id)
                    return False, e_dt, a_dt, "INVALIDATED"
            return True, e_dt, a_dt, None

        def _record_item(
            item_id: str,
            source_module: str,
            category: str,
            direction: EventDirection,
            e_dt: datetime,
            a_dt: datetime,
            status_str: str,
            summary: str,
        ) -> bool:
            nonlocal latest_available_at
            if item_id in seen_event_ids:
                return False
            seen_event_ids.add(item_id)
            if latest_available_at is None or a_dt > latest_available_at:
                latest_available_at = a_dt
            entry = EvidenceSummaryItem(
                event_id=item_id,
                timeframe=tf,
                source_module=source_module,
                event_category=category,
                direction=direction,
                event_time=e_dt,
                available_at=a_dt,
                status=status_str,
                summary=summary,
            )
            if direction == EventDirection.BULLISH:
                bullish_items.append(entry)
            elif direction == EventDirection.BEARISH:
                bearish_items.append(entry)
            else:
                neutral_items.append(entry)
            return True

        # Category tracking for Section 9 statuses & Section 6 conflicts
        struct_dirs: List[EventDirection] = []
        liq_dirs: Set[EventDirection] = set()
        resting_pools_present = False
        ob_dirs: Set[EventDirection] = set()
        fvg_dirs: Set[EventDirection] = set()
        ifvg_dirs: Set[EventDirection] = set()
        ind_dirs: Set[EventDirection] = set()
        ind_in_prog = False
        ind_ambiguous = False
        sess_dirs: Set[EventDirection] = set()
        local_conflicts: List[ConflictRecord] = []

        # Combine structure events from report + direct list cleanly (deduplicated by seen_event_ids).
        # TimeframeStructureReport carries canonical ICTEvent records, whereas callers may also pass
        # typed MarketStructureEvent instances directly; route ICTEvent objects into combined_ict.
        combined_structure: List[MarketStructureEvent] = []
        combined_ict: List[ICTEvent] = list(bundle.ict_events)
        for item in bundle.structure_events:
            if isinstance(item, MarketStructureEvent):
                combined_structure.append(item)
            elif isinstance(item, ICTEvent):
                combined_ict.append(item)
        if bundle.structure_report is not None:
            sr_future = False
            if bundle.structure_report.as_of_time is not None:
                sr_as_of = _convert_to_tz(
                    bundle.structure_report.as_of_time, self.tz, "structure_report.as_of_time"
                )
                if sr_as_of > as_of_tz:
                    sr_future = True
            if not sr_future:
                for item in bundle.structure_report.structure_events:
                    if isinstance(item, MarketStructureEvent):
                        combined_structure.append(item)
                    elif isinstance(item, ICTEvent):
                        combined_ict.append(item)

        # Order by available_at cleanly for deterministic trend evaluation
        valid_structure: List[Tuple[MarketStructureEvent, datetime, datetime]] = []
        for sev in combined_structure:
            ok, e_dt, a_dt, _ = _check_item_meta(
                sev.event_id, sev.index, sev.timeframe, sev.event_time, sev.available_at, sev.invalidated_at, sev.data_quality
            )
            if not ok or e_dt is None or a_dt is None:
                continue
            if sev.event_status == LiquidityLifecycleState.INVALIDATED:
                if sev.event_id not in invalidated_ids:
                    invalidated_ids.append(sev.event_id)
                continue
            if sev.event_status == LiquidityLifecycleState.EXPIRED:
                if sev.event_id not in expired_ids:
                    expired_ids.append(sev.event_id)
                continue
            if sev.event_status in INACTIVE_TERMINAL_STATES:
                continue
            valid_structure.append((sev, e_dt, a_dt))

        valid_structure.sort(key=lambda x: (x[2], x[1], x[0].event_id))
        for sev, e_dt, a_dt in valid_structure:
            if _record_item(
                sev.event_id,
                "Step3.2:MarketStructure",
                sev.event_type.value,
                sev.direction,
                e_dt,
                a_dt,
                sev.event_status.value,
                f"{tf} {sev.event_type.value} {sev.direction.value} @ {sev.broken_level}",
            ):
                if sev.direction in (EventDirection.BULLISH, EventDirection.BEARISH):
                    struct_dirs.append(sev.direction)

        # Also incorporate Step 3.2 active_trend when structure_report provided cleanly
        report_trend_dir: Optional[EventDirection] = None
        if bundle.structure_report is not None:
            if bundle.structure_report.as_of_time is not None:
                r_as_of = _convert_to_tz(bundle.structure_report.as_of_time, self.tz, "structure_report.as_of_time")
                if r_as_of > as_of_tz:
                    future_events_excluded += 1
                else:
                    if normalize_feed_status(bundle.structure_report.data_quality) in DISQUALIFYING_FEED_STATUSES:
                        disqualified_reasons.append(f"[{tf}] structure_report disqualified")
                    t_val = bundle.structure_report.active_trend.value
                    if t_val == "BULLISH":
                        report_trend_dir = EventDirection.BULLISH
                    elif t_val == "BEARISH":
                        report_trend_dir = EventDirection.BEARISH

        # Liquidity Events (Step 3.1)
        for le in bundle.liquidity_events:
            ok, e_dt, a_dt, _ = _check_item_meta(
                le.event_id, le.index, le.timeframe, le.event_time, le.available_at, le.invalidated_at, le.source_data_quality
            )
            if not ok or e_dt is None or a_dt is None:
                continue
            if le.status == LiquidityLifecycleState.INVALIDATED:
                if le.event_id not in invalidated_ids:
                    invalidated_ids.append(le.event_id)
                continue
            if le.status == LiquidityLifecycleState.EXPIRED:
                if le.event_id not in expired_ids:
                    expired_ids.append(le.event_id)
                continue
            if le.status in (LiquidityLifecycleState.CONSUMED, LiquidityLifecycleState.MITIGATED):
                continue
            if le.confirmed_at is not None:
                c_dt = _convert_to_tz(le.confirmed_at, self.tz, f"{le.event_id}.confirmed_at")
                if c_dt > as_of_tz:
                    future_events_excluded += 1
                    continue
            if _record_item(
                le.event_id,
                "Step3.1:Liquidity",
                f"{le.event_type.value}:{le.liquidity_type.value}",
                le.direction,
                e_dt,
                a_dt,
                le.status.value,
                f"{tf} {le.event_type.value} ({le.liquidity_type.value}) @ {le.level}",
            ):
                if le.direction in (EventDirection.BULLISH, EventDirection.BEARISH):
                    liq_dirs.add(le.direction)

        # Liquidity Pools (Step 3.1)
        for lp in bundle.liquidity_pools:
            ok, e_dt, a_dt, _ = _check_item_meta(
                lp.pool_id, lp.index, lp.timeframe, lp.formation_time, lp.available_at, lp.invalidated_at, lp.source_data_quality
            )
            if not ok or e_dt is None or a_dt is None:
                continue
            if lp.status == LiquidityLifecycleState.INVALIDATED:
                if lp.pool_id not in invalidated_ids:
                    invalidated_ids.append(lp.pool_id)
                continue
            if lp.status == LiquidityLifecycleState.EXPIRED:
                if lp.pool_id not in expired_ids:
                    expired_ids.append(lp.pool_id)
                continue
            if lp.status in (LiquidityLifecycleState.CONSUMED, LiquidityLifecycleState.MITIGATED):
                continue
            # Resting IDENTIFIED/APPROACHING pools represent draw context; SWEPT/RECLAIMED/CONFIRMED are directional
            if lp.status in (LiquidityLifecycleState.SWEPT, LiquidityLifecycleState.RECLAIMED, LiquidityLifecycleState.CONFIRMED):
                pool_dir = lp.direction
                if _record_item(
                    lp.pool_id,
                    "Step3.1:LiquidityPool",
                    lp.liquidity_type.value,
                    pool_dir,
                    e_dt,
                    a_dt,
                    lp.status.value,
                    f"{tf} {lp.status.value} {lp.liquidity_type.value} @ {lp.level}",
                ):
                    if pool_dir in (EventDirection.BULLISH, EventDirection.BEARISH):
                        liq_dirs.add(pool_dir)
            else:
                resting_pools_present = True
                _record_item(
                    lp.pool_id,
                    "Step3.1:LiquidityPool",
                    lp.liquidity_type.value,
                    EventDirection.NEUTRAL,
                    e_dt,
                    a_dt,
                    lp.status.value,
                    f"{tf} Resting {lp.liquidity_type.value} ({lp.direction.value}) @ {lp.level}",
                )

        # Order Blocks (Step 3.3)
        all_obs: List[OrderBlockEvent] = []
        for item in bundle.order_block_events:
            if isinstance(item, OrderBlockEvent):
                all_obs.append(item)
            elif isinstance(item, ICTEvent):
                combined_ict.append(item)
        if bundle.order_block_report is not None:
            obr = bundle.order_block_report
            obr_future = False
            if obr.as_of_time is not None:
                r_as_of = _convert_to_tz(obr.as_of_time, self.tz, "order_block_report.as_of_time")
                if r_as_of > as_of_tz:
                    future_events_excluded += 1
                    obr_future = True
            if not obr_future:
                if normalize_feed_status(obr.data_quality) in DISQUALIFYING_FEED_STATUSES:
                    disqualified_reasons.append(f"[{tf}] order_block_report disqualified")
                for item in obr.order_block_events:
                    if isinstance(item, OrderBlockEvent):
                        all_obs.append(item)
                    elif isinstance(item, ICTEvent):
                        combined_ict.append(item)
        for ob in all_obs:
            ok, e_dt, a_dt, _ = _check_item_meta(
                ob.event_id, ob.index, ob.timeframe, ob.event_time, ob.available_at, ob.invalidated_at, ob.data_quality
            )
            if not ok or e_dt is None or a_dt is None:
                continue
            if ob.event_status == LiquidityLifecycleState.INVALIDATED:
                if ob.event_id not in invalidated_ids:
                    invalidated_ids.append(ob.event_id)
                continue
            if ob.event_status == LiquidityLifecycleState.EXPIRED:
                if ob.event_id not in expired_ids:
                    expired_ids.append(ob.event_id)
                continue
            if ob.event_status in (LiquidityLifecycleState.CONSUMED, LiquidityLifecycleState.MITIGATED):
                continue
            if _record_item(
                ob.event_id,
                "Step3.3:OrderBlock",
                ob.event_type.value,
                ob.direction,
                e_dt,
                a_dt,
                ob.event_status.value,
                f"{tf} {ob.direction.value} OB [{ob.zone_low}, {ob.zone_high}] ({ob.event_status.value})",
            ):
                if ob.direction in (EventDirection.BULLISH, EventDirection.BEARISH):
                    ob_dirs.add(ob.direction)

        # FVGs & IFVGs (Step 3.4)
        all_fvgs: List[FVGEvent] = []
        for item in bundle.fvg_events:
            if isinstance(item, FVGEvent):
                all_fvgs.append(item)
            elif isinstance(item, ICTEvent):
                combined_ict.append(item)
        if bundle.fvg_report is not None:
            fvgr = bundle.fvg_report
            fvgr_future = False
            if fvgr.as_of_time is not None:
                r_as_of = _convert_to_tz(fvgr.as_of_time, self.tz, "fvg_report.as_of_time")
                if r_as_of > as_of_tz:
                    future_events_excluded += 1
                    fvgr_future = True
            if not fvgr_future:
                if normalize_feed_status(fvgr.data_quality) in DISQUALIFYING_FEED_STATUSES:
                    disqualified_reasons.append(f"[{tf}] fvg_report disqualified")
                for item in list(fvgr.fvg_events) + list(fvgr.ifvg_events):
                    if isinstance(item, FVGEvent):
                        all_fvgs.append(item)
                    elif isinstance(item, ICTEvent):
                        combined_ict.append(item)
        for fvg in all_fvgs:
            ok, e_dt, a_dt, _ = _check_item_meta(
                fvg.event_id, fvg.index, fvg.timeframe, fvg.event_time, fvg.available_at, fvg.invalidated_at, fvg.data_quality
            )
            if not ok or e_dt is None or a_dt is None:
                continue
            if fvg.event_status == LiquidityLifecycleState.INVALIDATED:
                if fvg.event_id not in invalidated_ids:
                    invalidated_ids.append(fvg.event_id)
                continue
            if fvg.event_status == LiquidityLifecycleState.EXPIRED:
                if fvg.event_id not in expired_ids:
                    expired_ids.append(fvg.event_id)
                continue
            if fvg.event_status in (LiquidityLifecycleState.CONSUMED, LiquidityLifecycleState.MITIGATED):
                continue
            if _record_item(
                fvg.event_id,
                "Step3.4:FVG",
                fvg.event_type.value,
                fvg.direction,
                e_dt,
                a_dt,
                fvg.event_status.value,
                f"{tf} {fvg.direction.value} {fvg.event_type.value} [{fvg.zone_low}, {fvg.zone_high}]",
            ):
                if fvg.direction in (EventDirection.BULLISH, EventDirection.BEARISH):
                    if fvg.event_type == ICTEventType.IFVG:
                        ifvg_dirs.add(fvg.direction)
                    fvg_dirs.add(fvg.direction)

        # Canonical ICTEvents (supporting inputs from any Step 3.1-3.6 module converted to ICTEvent)
        for iev in combined_ict:
            ok, e_dt, a_dt, _ = _check_item_meta(
                iev.event_id, iev.index, iev.timeframe, iev.event_time, iev.available_at, iev.invalidated_at, iev.data_quality
            )
            if not ok or e_dt is None or a_dt is None:
                continue
            if iev.event_status == LiquidityLifecycleState.INVALIDATED:
                if iev.event_id not in invalidated_ids:
                    invalidated_ids.append(iev.event_id)
                continue
            if iev.event_status == LiquidityLifecycleState.EXPIRED:
                if iev.event_id not in expired_ids:
                    expired_ids.append(iev.event_id)
                continue
            if iev.event_status in (LiquidityLifecycleState.CONSUMED, LiquidityLifecycleState.MITIGATED):
                continue
            if _record_item(
                iev.event_id,
                "ICTEvent",
                iev.event_type.value,
                iev.direction,
                e_dt,
                a_dt,
                iev.event_status.value,
                f"{tf} {iev.event_type.value} {iev.direction.value}",
            ):
                if iev.event_type in (ICTEventType.BOS, ICTEventType.CHOCH, ICTEventType.MSS):
                    if iev.direction in (EventDirection.BULLISH, EventDirection.BEARISH):
                        struct_dirs.append(iev.direction)
                elif iev.event_type in (ICTEventType.LIQUIDITY_SWEEP, ICTEventType.LIQUIDITY_RECLAIM, ICTEventType.LIQUIDITY_CONFIRMED):
                    if iev.direction in (EventDirection.BULLISH, EventDirection.BEARISH):
                        liq_dirs.add(iev.direction)
                elif iev.event_type == ICTEventType.ORDER_BLOCK:
                    if iev.direction in (EventDirection.BULLISH, EventDirection.BEARISH):
                        ob_dirs.add(iev.direction)
                elif iev.event_type in (ICTEventType.FVG, ICTEventType.IFVG):
                    if iev.direction in (EventDirection.BULLISH, EventDirection.BEARISH):
                        if iev.event_type == ICTEventType.IFVG:
                            ifvg_dirs.add(iev.direction)
                        fvg_dirs.add(iev.direction)
                elif iev.event_type in (ICTEventType.OPENING_RANGE, ICTEventType.SESSION_HIGH, ICTEventType.SESSION_LOW):
                    if iev.direction in (EventDirection.BULLISH, EventDirection.BEARISH):
                        sess_dirs.add(iev.direction)

        # Premium/Discount & Inducement (Step 3.5)
        pd_zone: Optional[ZoneClassification] = None
        pd_range_dir: Optional[EventDirection] = None
        pd_available_at: Optional[datetime] = None

        all_inducements: List[InducementEvent] = list(bundle.inducement_events)
        all_ranges: List[DealingRange] = list(bundle.dealing_ranges)
        if bundle.premium_discount_report is not None:
            pdr = bundle.premium_discount_report
            pd_idx = normalize_index_symbol(pdr.index)
            if pd_idx != index_norm:
                raise ValueError(f"Cross-index PremiumDiscountReport ({pd_idx}) supplied to '{index_norm}'")
            if normalize_mtf_timeframe(pdr.timeframe) != tf:
                raise ValueError(f"Cross-timeframe PremiumDiscountReport ({pdr.timeframe}) supplied to '{tf}'")
            r_as_of = _convert_to_tz(pdr.as_of_time, self.tz, "premium_discount_report.as_of_time")
            if r_as_of > as_of_tz:
                future_events_excluded += 1
            else:
                all_inducements.extend(pdr.confirmed_inducements)
                if pdr.active_dealing_range is not None:
                    all_ranges.append(pdr.active_dealing_range)
                if pdr.current_zone is not None:
                    pd_zone = pdr.current_zone
                    pd_available_at = r_as_of

        # Evaluate dealing ranges causally
        valid_ranges: List[Tuple[DealingRange, datetime]] = []
        for dr in all_ranges:
            ok, _, a_dt, _ = _check_item_meta(
                dr.range_id, dr.index, dr.timeframe, dr.start_time, dr.available_at, None, None
            )
            if not ok or a_dt is None:
                continue
            if dr.status == DealingRangeStatus.INVALIDATED:
                if dr.range_id not in invalidated_ids:
                    invalidated_ids.append(dr.range_id)
                continue
            if dr.status == DealingRangeStatus.EXPIRED:
                if dr.range_id not in expired_ids:
                    expired_ids.append(dr.range_id)
                continue
            if dr.status == DealingRangeStatus.REPLACED:
                continue
            valid_ranges.append((dr, a_dt))

        if valid_ranges:
            latest_dr, dr_avail = max(valid_ranges, key=lambda x: (x[1], x[0].range_id))
            pd_range_dir = latest_dr.direction
            if latest_available_at is None or dr_avail > latest_available_at:
                latest_available_at = dr_avail
            _record_item(
                latest_dr.range_id,
                "Step3.5:DealingRange",
                "DEALING_RANGE",
                latest_dr.direction,
                _convert_to_tz(latest_dr.start_time, self.tz, "dr.start_time"),
                dr_avail,
                latest_dr.status.value,
                f"{tf} DealingRange {latest_dr.direction.value} [{latest_dr.low_price}, {latest_dr.high_price}]"
                + (f" zone={pd_zone.value}" if pd_zone else ""),
            )
            if pd_zone is None and bundle.current_price is not None:
                from app.options.ict_smc.premium_discount_engine import classify_zone

                pd_zone = classify_zone(
                    price=float(bundle.current_price),
                    high=float(latest_dr.high_price),
                    low=float(latest_dr.low_price),
                    equilibrium=float(latest_dr.equilibrium_price),
                    delta_r=float(latest_dr.delta_r),
                    neutral_band_delta=float(latest_dr.neutral_band_delta),
                )
                pd_available_at = dr_avail

        # Inducements (Step 3.5)
        for ind in all_inducements:
            ok, e_dt, a_dt, _ = _check_item_meta(
                ind.event_id, ind.index, ind.timeframe, ind.event_time, ind.available_at, None, None
            )
            if not ok or e_dt is None or a_dt is None:
                continue
            if ind.status == InducementStatus.INVALIDATED:
                if ind.event_id not in invalidated_ids:
                    invalidated_ids.append(ind.event_id)
                continue
            if ind.status == InducementStatus.EXPIRED:
                if ind.event_id not in expired_ids:
                    expired_ids.append(ind.event_id)
                continue
            if ind.status == InducementStatus.UNRESOLVED_AMBIGUITY:
                ind_ambiguous = True
                continue
            if ind.status != InducementStatus.CONFIRMED:
                ind_in_prog = True
                continue
            if _record_item(
                ind.event_id,
                "Step3.5:Inducement",
                "INDUCEMENT_CONFIRMED",
                ind.direction,
                e_dt,
                a_dt,
                ind.status.value,
                f"{tf} Confirmed {ind.direction.value} Inducement @ {ind.price_level}",
            ):
                if ind.direction in (EventDirection.BULLISH, EventDirection.BEARISH):
                    ind_dirs.add(ind.direction)

        # Session Intelligence (Step 3.6)
        combined_session_events: List[SessionEvent] = list(bundle.session_events)
        session_status_label = "UNAVAILABLE"
        if bundle.session_report is not None:
            sr = bundle.session_report
            if normalize_index_symbol(sr.index) != index_norm:
                raise ValueError(f"Cross-index SessionReport ({sr.index}) supplied to '{index_norm}'")
            if normalize_mtf_timeframe(sr.timeframe) != tf:
                raise ValueError(f"Cross-timeframe SessionReport ({sr.timeframe}) supplied to '{tf}'")
            sr_as_of = _convert_to_tz(sr.as_of_time, self.tz, "session_report.as_of_time")
            if sr_as_of > as_of_tz:
                future_events_excluded += 1
            else:
                sr_dq = normalize_feed_status(sr.data_quality)
                if not sr.is_valid or sr_dq in DISQUALIFYING_FEED_STATUSES:
                    disqualified_reasons.append(f"[{tf}] Step 3.6 session_report disqualified ({sr_dq})")
                else:
                    combined_session_events.extend(sr.events)
                    cs = sr.current_session
                    s_name = cs.session_name if (cs and cs.session_name) else "NONE"
                    s_state = cs.current_session_status.value if cs else SessionPhaseStatus.UNAVAILABLE.value
                    session_status_label = f"{s_state}:{s_name}"
                    if sr.has_data_gaps:
                        session_status_label += ":GAPS_DETECTED"
                        c_id = generate_deterministic_mtf_id(
                            "CNFL", [index_norm, tf, "SESSION_GAP", sr.trading_date]
                        )
                        local_conflicts.append(
                            ConflictRecord(
                                conflict_id=c_id,
                                timeframe_a=tf,
                                timeframe_b=tf,
                                conflict_type=ConflictType.SESSION_CONTEXT_CONFLICT,
                                direction_a="SESSION_DATA_GAP",
                                direction_b="INCOMPLETE_SESSION_SERIES",
                                severity=ConflictSeverity.MEDIUM,
                                evidence_event_ids=(),
                                event_time=sr_as_of,
                                available_at=sr_as_of,
                                explanation=f"[{tf}] Step 3.6 Session report detected {len(sr.missing_intervals)} missing interval(s)",
                            )
                        )

        for sev_s in combined_session_events:
            ok, e_dt, a_dt, _ = _check_item_meta(
                sev_s.event_id, sev_s.index, sev_s.timeframe, sev_s.event_time, sev_s.available_at, sev_s.invalidated_at, sev_s.data_quality
            )
            if not ok or e_dt is None or a_dt is None:
                continue
            if sev_s.event_status == LiquidityLifecycleState.INVALIDATED:
                if sev_s.event_id not in invalidated_ids:
                    invalidated_ids.append(sev_s.event_id)
                continue
            if sev_s.event_status in (LiquidityLifecycleState.EXPIRED, LiquidityLifecycleState.CONSUMED):
                continue
            is_directional_session_ev = sev_s.session_event_kind in (
                SessionEventKind.OPENING_RANGE_BREAKOUT,
                SessionEventKind.OPENING_RANGE_BREAKDOWN,
                SessionEventKind.OPENING_RANGE_RETEST,
                SessionEventKind.SESSION_HIGH_RECLAIM,
                SessionEventKind.SESSION_LOW_RECLAIM,
                SessionEventKind.SESSION_HIGH_BREACH,
                SessionEventKind.SESSION_LOW_BREACH,
            )
            dir_for_bucket = sev_s.direction if is_directional_session_ev else EventDirection.NEUTRAL
            if _record_item(
                sev_s.event_id,
                "Step3.6:Session",
                sev_s.session_event_kind.value,
                dir_for_bucket,
                e_dt,
                a_dt,
                sev_s.event_status.value,
                f"{tf} {sev_s.session_event_kind.value} {sev_s.direction.value}",
            ):
                if is_directional_session_ev and sev_s.direction in (EventDirection.BULLISH, EventDirection.BEARISH):
                    sess_dirs.add(sev_s.direction)

        # Disqualifying feed status across consumed events triggers immediate TF lockout
        if disqualified_reasons:
            c_id = generate_deterministic_mtf_id("CNFL", [index_norm, tf, "EVENT_LOCKOUT", str(len(disqualified_reasons))])
            return (
                TimeframeConfluenceReport(
                    timeframe=tf,
                    timeframe_role=tf_role,
                    direction="UNAVAILABLE",
                    data_quality="DATA_QUALITY_LOCKOUT",
                    has_valid_evidence=False,
                    future_events_excluded=future_events_excluded,
                    invalidated_event_ids=tuple(invalidated_ids),
                    expired_event_ids=tuple(expired_ids),
                    future_candles_excluded=future_candles,
                    incomplete_candles_excluded=incomplete_candles,
                ),
                [],
                [
                    ConflictRecord(
                        conflict_id=c_id,
                        timeframe_a=tf,
                        timeframe_b=tf,
                        conflict_type=ConflictType.STALE_OR_UNAVAILABLE_EVIDENCE,
                        direction_a="UNAVAILABLE",
                        direction_b="LOCKED_OUT",
                        severity=ConflictSeverity.CRITICAL,
                        evidence_event_ids=(),
                        event_time=as_of_tz,
                        available_at=as_of_tz,
                        explanation="; ".join(disqualified_reasons),
                    )
                ],
                {"pd_zone": None, "liquidity_dirs": set(), "session_dirs": set(), "invalidated": invalidated_ids},
            )

        # Staleness Age Audit relative to as_of_tz
        if self.config.enforce_staleness_checks and latest_available_at is not None:
            age_minutes = (as_of_tz - latest_available_at).total_seconds() / 60.0
            max_age = self.config.max_evidence_age_minutes_by_tf[tf]
            if age_minutes > max_age:
                c_id = generate_deterministic_mtf_id(
                    "CNFL", [index_norm, tf, "STALE_AGE", latest_available_at.isoformat()]
                )
                return (
                    TimeframeConfluenceReport(
                        timeframe=tf,
                        timeframe_role=tf_role,
                        direction="UNAVAILABLE",
                        data_quality="STALE",
                        available_at=latest_available_at,
                        has_valid_evidence=False,
                        future_events_excluded=future_events_excluded,
                        invalidated_event_ids=tuple(invalidated_ids),
                        expired_event_ids=tuple(expired_ids),
                    ),
                    [],
                    [
                        ConflictRecord(
                            conflict_id=c_id,
                            timeframe_a=tf,
                            timeframe_b=tf,
                            conflict_type=ConflictType.STALE_OR_UNAVAILABLE_EVIDENCE,
                            direction_a="STALE",
                            direction_b="EXCEEDED_MAX_AGE",
                            severity=ConflictSeverity.CRITICAL,
                            evidence_event_ids=tuple(sorted(seen_event_ids)),
                            event_time=latest_available_at,
                            available_at=latest_available_at,
                            explanation=f"[{tf}] Latest evidence age {age_minutes:.1f}m exceeds limit {max_age}m",
                        )
                    ],
                    {"pd_zone": None, "liquidity_dirs": set(), "session_dirs": set(), "invalidated": invalidated_ids},
                )

        # Summarize component statuses
        latest_struct_dir: Optional[EventDirection] = struct_dirs[-1] if struct_dirs else report_trend_dir
        unique_struct_dirs = set(struct_dirs)
        if report_trend_dir is not None and len(struct_dirs) > 0 and report_trend_dir != struct_dirs[-1]:
            unique_struct_dirs.add(report_trend_dir)

        if not unique_struct_dirs:
            structure_status = "UNAVAILABLE"
        elif len(unique_struct_dirs) > 1:
            structure_status = f"LATEST_{latest_struct_dir.value}_WITH_PRIOR_REVERSALS"
        else:
            structure_status = f"{next(iter(unique_struct_dirs)).value}_STRUCTURE"

        if not liq_dirs and not resting_pools_present:
            liquidity_status = "UNAVAILABLE"
        elif len(liq_dirs) > 1:
            liquidity_status = "CONFLICTING_LIQUIDITY"
            c_id = generate_deterministic_mtf_id("CNFL", [index_norm, tf, "INTRA_LIQ_CONFLICT", as_of_tz.isoformat()])
            local_conflicts.append(
                ConflictRecord(
                    conflict_id=c_id,
                    timeframe_a=tf,
                    timeframe_b=tf,
                    conflict_type=ConflictType.LIQUIDITY_CONFLICT,
                    direction_a="BULLISH",
                    direction_b="BEARISH",
                    severity=ConflictSeverity.HIGH,
                    evidence_event_ids=tuple(sorted(seen_event_ids)),
                    event_time=latest_available_at or as_of_tz,
                    available_at=latest_available_at or as_of_tz,
                    explanation=f"[{tf}] Both bullish and bearish active liquidity sweeps/reclaims observed",
                )
            )
        elif liq_dirs:
            liquidity_status = f"{next(iter(liq_dirs)).value}_LIQUIDITY_INTERACTION"
        else:
            liquidity_status = "RESTING_POOLS_IDENTIFIED"

        if ob_dirs:
            order_block_status = "CONFLICTING_OB" if len(ob_dirs) > 1 else f"{next(iter(ob_dirs)).value}_OB_ACTIVE"
        else:
            order_block_status = "INVALIDATED_ONLY" if invalidated_ids else "UNAVAILABLE"

        if fvg_dirs:
            if len(fvg_dirs) > 1:
                fvg_status = "CONFLICTING_FVG"
            else:
                d_f = next(iter(fvg_dirs))
                fvg_status = f"{d_f.value}_IFVG_ACTIVE" if d_f in ifvg_dirs else f"{d_f.value}_FVG_ACTIVE"
        else:
            fvg_status = "INVALIDATED_ONLY" if invalidated_ids else "UNAVAILABLE"

        pd_status = pd_zone.value if pd_zone is not None else "UNAVAILABLE"

        if ind_dirs:
            inducement_status = "CONFLICTING" if len(ind_dirs) > 1 else f"CONFIRMED_{next(iter(ind_dirs)).value}"
        elif ind_ambiguous:
            inducement_status = "UNRESOLVED_AMBIGUITY"
        elif ind_in_prog:
            inducement_status = "IN_PROGRESSION"
        else:
            inducement_status = "UNAVAILABLE"

        if sess_dirs and session_status_label == "UNAVAILABLE":
            session_status_label = f"ACTIVE_EVENTS:{'+'.join(sorted(d.value for d in sess_dirs))}"
        elif sess_dirs:
            session_status_label += f":{'+'.join(sorted(d.value for d in sess_dirs))}"

        # Intra-TF OB/FVG directional mismatch & Invalidation conflict detection
        if len(ob_dirs) == 1 and len(fvg_dirs) == 1 and ob_dirs != fvg_dirs:
            c_id = generate_deterministic_mtf_id("CNFL", [index_norm, tf, "OB_FVG_OPPOSING", as_of_tz.isoformat()])
            local_conflicts.append(
                ConflictRecord(
                    conflict_id=c_id,
                    timeframe_a=tf,
                    timeframe_b=tf,
                    conflict_type=ConflictType.OB_FVG_INVALIDATION,
                    direction_a=next(iter(ob_dirs)).value,
                    direction_b=next(iter(fvg_dirs)).value,
                    severity=ConflictSeverity.MEDIUM,
                    evidence_event_ids=tuple(sorted(seen_event_ids)),
                    event_time=latest_available_at or as_of_tz,
                    available_at=latest_available_at or as_of_tz,
                    explanation=f"[{tf}] Active OB direction opposes active FVG direction",
                )
            )
        if invalidated_ids and (bullish_items or bearish_items):
            # Track explicit OB/FVG invalidation presence
            c_id = generate_deterministic_mtf_id(
                "CNFL", [index_norm, tf, "INVALIDATED_PRESENT", ",".join(sorted(invalidated_ids))]
            )
            local_conflicts.append(
                ConflictRecord(
                    conflict_id=c_id,
                    timeframe_a=tf,
                    timeframe_b=tf,
                    conflict_type=ConflictType.OB_FVG_INVALIDATION,
                    direction_a="ACTIVE_BIAS",
                    direction_b="INVALIDATED_POI",
                    severity=ConflictSeverity.INFO if (ob_dirs or fvg_dirs or struct_dirs) else ConflictSeverity.MEDIUM,
                    evidence_event_ids=tuple(sorted(invalidated_ids)),
                    event_time=latest_available_at or as_of_tz,
                    available_at=latest_available_at or as_of_tz,
                    explanation=f"[{tf}] {len(invalidated_ids)} invalidated/mitigated zone(s) excluded from confluence support",
                )
            )

        # Determine non-weighted descriptive direction for this timeframe
        has_bull = len(bullish_items) > 0 or (latest_struct_dir == EventDirection.BULLISH)
        has_bear = len(bearish_items) > 0 or (latest_struct_dir == EventDirection.BEARISH)
        has_any_valid = bool(seen_event_ids) or (pd_zone is not None) or (report_trend_dir is not None)

        # Intra-TF direction precedence without invented weights:
        # 1. If latest confirmed structure + active directional evidence agree unanimously -> BULLISH / BEARISH
        # 2. If active directional evidence spans both BULLISH and BEARISH:
        #    - Check whether latest confirmed reversal (CHoCH/MSS) + majority components point one way vs minor opposition -> CONFLICTING if balanced/structural clash
        active_component_dirs: Set[EventDirection] = set()
        if latest_struct_dir in (EventDirection.BULLISH, EventDirection.BEARISH):
            active_component_dirs.add(latest_struct_dir)
        active_component_dirs.update(liq_dirs)
        active_component_dirs.update(ob_dirs)
        active_component_dirs.update(fvg_dirs)
        active_component_dirs.update(ind_dirs)

        if not has_any_valid:
            tf_direction = "UNAVAILABLE"
        elif len(active_component_dirs) > 1:
            tf_direction = "CONFLICTING"
        elif len(active_component_dirs) == 1:
            only_dir = next(iter(active_component_dirs))
            # Also verify session direction doesn't directly contradict sole active direction
            if sess_dirs and only_dir not in sess_dirs:
                tf_direction = "CONFLICTING"
            else:
                tf_direction = only_dir.value
        elif sess_dirs:
            tf_direction = next(iter(sess_dirs)).value if len(sess_dirs) == 1 else "CONFLICTING"
        elif has_bull and not has_bear:
            tf_direction = "BULLISH"
        elif has_bear and not has_bull:
            tf_direction = "BEARISH"
        else:
            tf_direction = "NEUTRAL"

        # Session conflict detection when directional structure vs directional session disagree
        if sess_dirs and tf_direction in ("BULLISH", "BEARISH"):
            exp_d = EventDirection(tf_direction)
            if exp_d not in sess_dirs:
                c_id = generate_deterministic_mtf_id(
                    "CNFL", [index_norm, tf, "SESSION_CONFLICT", tf_direction, as_of_tz.isoformat()]
                )
                local_conflicts.append(
                    ConflictRecord(
                        conflict_id=c_id,
                        timeframe_a=tf,
                        timeframe_b=tf,
                        conflict_type=ConflictType.SESSION_CONTEXT_CONFLICT,
                        direction_a=tf_direction,
                        direction_b="+".join(sorted(d.value for d in sess_dirs)),
                        severity=ConflictSeverity.HIGH,
                        evidence_event_ids=tuple(sorted(seen_event_ids)),
                        event_time=latest_available_at or as_of_tz,
                        available_at=latest_available_at or as_of_tz,
                        explanation=f"[{tf}] Session context ({session_status_label}) opposes structural bias {tf_direction}",
                    )
                )
        elif tf_direction == "CONFLICTING" and sess_dirs and len(active_component_dirs) == 1:
            comp_d = next(iter(active_component_dirs)).value
            c_id = generate_deterministic_mtf_id(
                "CNFL", [index_norm, tf, "SESSION_CONFLICT", comp_d, as_of_tz.isoformat()]
            )
            local_conflicts.append(
                ConflictRecord(
                    conflict_id=c_id,
                    timeframe_a=tf,
                    timeframe_b=tf,
                    conflict_type=ConflictType.SESSION_CONTEXT_CONFLICT,
                    direction_a=comp_d,
                    direction_b="+".join(sorted(d.value for d in sess_dirs)),
                    severity=ConflictSeverity.HIGH,
                    evidence_event_ids=tuple(sorted(seen_event_ids)),
                    event_time=latest_available_at or as_of_tz,
                    available_at=latest_available_at or as_of_tz,
                    explanation=f"[{tf}] Session direction disagrees with component bias {comp_d}",
                )
            )

        # Premium / Discount conflict within timeframe
        if pd_zone is not None:
            ref_d = tf_direction if tf_direction in ("BULLISH", "BEARISH") else (
                next(iter(active_component_dirs)).value if len(active_component_dirs) == 1 else None
            )
            pd_conflict_dir: Optional[str] = None
            if ref_d == "BULLISH" and pd_zone in (ZoneClassification.PREMIUM, ZoneClassification.DEEP_PREMIUM):
                pd_conflict_dir = pd_zone.value
            elif ref_d == "BEARISH" and pd_zone in (ZoneClassification.DISCOUNT, ZoneClassification.DEEP_DISCOUNT):
                pd_conflict_dir = pd_zone.value
            elif ref_d == "BULLISH" and pd_range_dir == EventDirection.BEARISH and pd_zone == ZoneClassification.ABOVE_RANGE:
                pd_conflict_dir = "ABOVE_BEARISH_RANGE"
            elif ref_d == "BEARISH" and pd_range_dir == EventDirection.BULLISH and pd_zone == ZoneClassification.BELOW_RANGE:
                pd_conflict_dir = "BELOW_BULLISH_RANGE"

            if pd_conflict_dir is not None and ref_d is not None:
                c_id = generate_deterministic_mtf_id(
                    "CNFL", [index_norm, tf, "PD_CONFLICT", ref_d, pd_conflict_dir]
                )
                local_conflicts.append(
                    ConflictRecord(
                        conflict_id=c_id,
                        timeframe_a=tf,
                        timeframe_b=tf,
                        conflict_type=ConflictType.PREMIUM_DISCOUNT_CONFLICT,
                        direction_a=ref_d,
                        direction_b=pd_conflict_dir,
                        severity=ConflictSeverity.HIGH,
                        evidence_event_ids=tuple(sorted(seen_event_ids)),
                        event_time=pd_available_at or latest_available_at or as_of_tz,
                        available_at=pd_available_at or latest_available_at or as_of_tz,
                        explanation=f"[{tf}] {ref_d} bias located in unfavorable {pd_conflict_dir} zone",
                    )
                )

        tf_report = TimeframeConfluenceReport(
            timeframe=tf,
            timeframe_role=tf_role,
            direction=tf_direction,
            evidence_event_ids=tuple(sorted(seen_event_ids)),
            structure_status=structure_status,
            liquidity_status=liquidity_status,
            order_block_status=order_block_status,
            fvg_status=fvg_status,
            premium_discount_status=pd_status,
            inducement_status=inducement_status,
            session_status=session_status_label,
            data_quality=eff_status,
            available_at=latest_available_at or pd_available_at,
            has_valid_evidence=has_any_valid,
            bullish_signals=tuple(b.summary for b in bullish_items),
            bearish_signals=tuple(b.summary for b in bearish_items),
            neutral_signals=tuple(n.summary for n in neutral_items),
            future_events_excluded=future_events_excluded,
            invalidated_event_ids=tuple(sorted(invalidated_ids)),
            expired_event_ids=tuple(sorted(expired_ids)),
            future_candles_excluded=future_candles,
            incomplete_candles_excluded=incomplete_candles,
        )
        all_items = bullish_items + bearish_items + neutral_items
        aux_ctx = {
            "pd_zone": pd_zone,
            "liquidity_dirs": liq_dirs,
            "session_dirs": sess_dirs,
            "invalidated": invalidated_ids,
        }
        return tf_report, all_items, local_conflicts, aux_ctx

    # ------------------------------------------------------------------
    # Cross-Timeframe Conflict Detection & Alignment Classification
    # ------------------------------------------------------------------

    def _detect_cross_timeframe_conflicts(
        self,
        *,
        index_norm: str,
        tf_reports: Dict[str, TimeframeConfluenceReport],
        aux_by_tf: Dict[str, Dict[str, Any]],
        as_of_tz: datetime,
    ) -> Tuple[List[ConflictRecord], Tuple[str, ...]]:
        conflicts: List[ConflictRecord] = []
        missing_tfs: List[str] = []

        # 1. Missing / unavailable timeframe conflicts
        for tf in MTF_TIMEFRAME_ORDER:
            rep = tf_reports[tf]
            if not rep.has_valid_evidence or rep.direction == "UNAVAILABLE":
                missing_tfs.append(tf)
                if rep.data_quality not in DISQUALIFYING_FEED_STATUSES:
                    sev = ConflictSeverity.HIGH if tf in ("1h", "15m", "5m") else ConflictSeverity.MEDIUM
                    c_id = generate_deterministic_mtf_id(
                        "CNFL", [index_norm, tf, "MISSING_TF", self.config_fingerprint]
                    )
                    conflicts.append(
                        ConflictRecord(
                            conflict_id=c_id,
                            timeframe_a=tf,
                            timeframe_b=tf,
                            conflict_type=ConflictType.MISSING_TIMEFRAME_EVIDENCE,
                            direction_a="UNAVAILABLE",
                            direction_b="MISSING",
                            severity=sev,
                            evidence_event_ids=(),
                            event_time=as_of_tz,
                            available_at=as_of_tz,
                            explanation=f"Timeframe {tf.upper()} ({TIMEFRAME_ROLES[tf]}) evidence is missing or unavailable",
                        )
                    )

        # 2. Adjacent hierarchical directional pairs (1h vs 15m, 15m vs 5m, 5m vs 3m, 5m vs 1m, 3m vs 1m)
        pair_checks = (
            ("1h", "15m", ConflictType.HTF_ITF_DIVERGENCE, ConflictSeverity.HIGH),
            ("15m", "5m", ConflictType.ITF_PRIMARY_DIVERGENCE, ConflictSeverity.HIGH),
            ("5m", "3m", ConflictType.PRIMARY_LTF_DIVERGENCE, ConflictSeverity.HIGH),
            ("5m", "1m", ConflictType.PRIMARY_LTF_DIVERGENCE, ConflictSeverity.HIGH),
            ("1h", "5m", ConflictType.CROSS_TIMEFRAME_DIVERGENCE, ConflictSeverity.HIGH),
        )
        for tf_a, tf_b, c_type, sev in pair_checks:
            ra, rb = tf_reports[tf_a], tf_reports[tf_b]
            da, db = ra.direction, rb.direction
            if da in ("BULLISH", "BEARISH") and db in ("BULLISH", "BEARISH") and da != db:
                t_a = ra.available_at or as_of_tz
                t_b = rb.available_at or as_of_tz
                avail = max(t_a, t_b)
                ev_t = min(t_a, t_b)
                c_id = generate_deterministic_mtf_id(
                    "CNFL", [index_norm, tf_a, tf_b, c_type.value, da, db, avail.isoformat()]
                )
                conflicts.append(
                    ConflictRecord(
                        conflict_id=c_id,
                        timeframe_a=tf_a,
                        timeframe_b=tf_b,
                        conflict_type=c_type,
                        direction_a=da,
                        direction_b=db,
                        severity=sev,
                        evidence_event_ids=tuple(sorted(set(ra.evidence_event_ids) | set(rb.evidence_event_ids))),
                        event_time=ev_t,
                        available_at=avail,
                        explanation=f"{tf_a.upper()} is {da} while {tf_b.upper()} is {db}",
                    )
                )

        # 3. Higher timeframe (1H) liquidity conflict against lower setups (15M/5M)
        htf_liq = aux_by_tf["1h"]["liquidity_dirs"]
        if len(htf_liq) == 1:
            htf_liq_dir = next(iter(htf_liq))
            for sub_tf in ("15m", "5m"):
                sub_rep = tf_reports[sub_tf]
                if sub_rep.direction in ("BULLISH", "BEARISH") and sub_rep.direction != htf_liq_dir.value:
                    avail = max(tf_reports["1h"].available_at or as_of_tz, sub_rep.available_at or as_of_tz)
                    c_id = generate_deterministic_mtf_id(
                        "CNFL", [index_norm, "1h", sub_tf, "HTF_LIQ", htf_liq_dir.value, sub_rep.direction]
                    )
                    conflicts.append(
                        ConflictRecord(
                            conflict_id=c_id,
                            timeframe_a="1h",
                            timeframe_b=sub_tf,
                            conflict_type=ConflictType.HTF_LIQUIDITY_CONFLICT,
                            direction_a=f"HTF_LIQUIDITY_{htf_liq_dir.value}",
                            direction_b=sub_rep.direction,
                            severity=ConflictSeverity.HIGH,
                            evidence_event_ids=tuple(sorted(set(tf_reports["1h"].evidence_event_ids) | set(sub_rep.evidence_event_ids))),
                            event_time=min(tf_reports["1h"].available_at or as_of_tz, sub_rep.available_at or as_of_tz),
                            available_at=avail,
                            explanation=f"1H liquidity sweep/reclaim ({htf_liq_dir.value}) opposes {sub_tf.upper()} setup ({sub_rep.direction})",
                        )
                    )

        # 4. Higher timeframe Premium/Discount opposing 15M/5M setups
        htf_pd: Optional[ZoneClassification] = aux_by_tf["1h"]["pd_zone"]
        if htf_pd is not None:
            for sub_tf in ("15m", "5m"):
                sub_rep = tf_reports[sub_tf]
                if sub_rep.direction == "BULLISH" and htf_pd in (ZoneClassification.PREMIUM, ZoneClassification.DEEP_PREMIUM):
                    c_id = generate_deterministic_mtf_id(
                        "CNFL", [index_norm, "1h", sub_tf, "HTF_PD_BULL_PREM", htf_pd.value]
                    )
                    conflicts.append(
                        ConflictRecord(
                            conflict_id=c_id,
                            timeframe_a="1h",
                            timeframe_b=sub_tf,
                            conflict_type=ConflictType.PREMIUM_DISCOUNT_CONFLICT,
                            direction_a=f"1H_ZONE_{htf_pd.value}",
                            direction_b=f"{sub_tf.upper()}_BULLISH",
                            severity=ConflictSeverity.HIGH,
                            evidence_event_ids=sub_rep.evidence_event_ids,
                            event_time=sub_rep.available_at or as_of_tz,
                            available_at=sub_rep.available_at or as_of_tz,
                            explanation=f"1H market location is in {htf_pd.value}, opposing {sub_tf.upper()} BULLISH setup",
                        )
                    )
                elif sub_rep.direction == "BEARISH" and htf_pd in (ZoneClassification.DISCOUNT, ZoneClassification.DEEP_DISCOUNT):
                    c_id = generate_deterministic_mtf_id(
                        "CNFL", [index_norm, "1h", sub_tf, "HTF_PD_BEAR_DISC", htf_pd.value]
                    )
                    conflicts.append(
                        ConflictRecord(
                            conflict_id=c_id,
                            timeframe_a="1h",
                            timeframe_b=sub_tf,
                            conflict_type=ConflictType.PREMIUM_DISCOUNT_CONFLICT,
                            direction_a=f"1H_ZONE_{htf_pd.value}",
                            direction_b=f"{sub_tf.upper()}_BEARISH",
                            severity=ConflictSeverity.HIGH,
                            evidence_event_ids=sub_rep.evidence_event_ids,
                            event_time=sub_rep.available_at or as_of_tz,
                            available_at=sub_rep.available_at or as_of_tz,
                            explanation=f"1H market location is in {htf_pd.value}, opposing {sub_tf.upper()} BEARISH setup",
                        )
                    )

        return conflicts, tuple(missing_tfs)

    def _classify_overall_alignment(
        self,
        *,
        data_quality_status: str,
        tf_reports: Dict[str, TimeframeConfluenceReport],
        conflicts: Sequence[ConflictRecord],
    ) -> AlignmentClassification:
        """Deterministic rule-based multi-timeframe alignment classifier (zero numeric weights)."""
        if data_quality_status in DISQUALIFYING_FEED_STATUSES or data_quality_status == "DATA_QUALITY_LOCKOUT":
            return AlignmentClassification.DATA_QUALITY_LOCKOUT

        if any(tf_reports[tf].data_quality in DISQUALIFYING_FEED_STATUSES or tf_reports[tf].data_quality == "DATA_QUALITY_LOCKOUT" for tf in MTF_TIMEFRAME_ORDER):
            return AlignmentClassification.DATA_QUALITY_LOCKOUT

        # Higher/primary foundation check: 1H, 15M, 5M MUST be valid and non-missing
        if any(not tf_reports[tf].has_valid_evidence or tf_reports[tf].direction == "UNAVAILABLE" for tf in ("1h", "15m", "5m")):
            return AlignmentClassification.INSUFFICIENT_DATA

        dirs = {tf: tf_reports[tf].direction for tf in MTF_TIMEFRAME_ORDER}
        present_dirs = {d for d in dirs.values() if d != "UNAVAILABLE"}

        if "CONFLICTING" in present_dirs:
            return AlignmentClassification.MIXED_ALIGNMENT
        if "BULLISH" in present_dirs and "BEARISH" in present_dirs:
            return AlignmentClassification.MIXED_ALIGNMENT

        high_non_missing_conflicts = [
            c
            for c in conflicts
            if c.conflict_type != ConflictType.MISSING_TIMEFRAME_EVIDENCE
            and c.severity in (ConflictSeverity.CRITICAL, ConflictSeverity.HIGH)
        ]

        if all(dirs[tf] == "BULLISH" for tf in MTF_TIMEFRAME_ORDER) and not high_non_missing_conflicts:
            return AlignmentClassification.STRONG_BULLISH_ALIGNMENT
        if all(dirs[tf] == "BEARISH" for tf in MTF_TIMEFRAME_ORDER) and not high_non_missing_conflicts:
            return AlignmentClassification.STRONG_BEARISH_ALIGNMENT

        core_bull = all(dirs[tf] == "BULLISH" for tf in ("1h", "15m", "5m"))
        core_bear = all(dirs[tf] == "BEARISH" for tf in ("1h", "15m", "5m"))

        if core_bull and "BEARISH" not in present_dirs:
            return AlignmentClassification.BULLISH_ALIGNMENT
        if core_bear and "BULLISH" not in present_dirs:
            return AlignmentClassification.BEARISH_ALIGNMENT

        if "BULLISH" in present_dirs and "BEARISH" not in present_dirs and dirs["1h"] == "BULLISH":
            return AlignmentClassification.BULLISH_ALIGNMENT
        if "BEARISH" in present_dirs and "BULLISH" not in present_dirs and dirs["1h"] == "BEARISH":
            return AlignmentClassification.BEARISH_ALIGNMENT

        return AlignmentClassification.NEUTRAL

    # ------------------------------------------------------------------
    # Public Entry Points: Precomputed Evidence & Candle Orchestration
    # ------------------------------------------------------------------

    def evaluate_from_evidence(
        self,
        *,
        index: str = "NIFTY 50",
        as_of_time: datetime,
        timeframe_evidence: Dict[str, TimeframeEvidenceBundle],
        data_quality_status: str = "VERIFIED_LIVE",
    ) -> MTFConfluenceReport:
        """
        Deterministic multi-timeframe confluence synthesis from Step 3.1–3.6 outputs.
        """
        index_norm = normalize_index_symbol(index)
        as_of_tz = _convert_to_tz(as_of_time, self.tz, "as_of_time")
        top_quality = normalize_feed_status(data_quality_status)

        if not isinstance(timeframe_evidence, dict):
            raise TypeError("timeframe_evidence must be a dict mapping timeframe -> TimeframeEvidenceBundle")

        normalized_bundles: Dict[str, TimeframeEvidenceBundle] = {}
        for tf_k, b_val in timeframe_evidence.items():
            tf_norm = normalize_mtf_timeframe(tf_k)
            if not isinstance(b_val, TimeframeEvidenceBundle):
                raise TypeError(f"Expected TimeframeEvidenceBundle for '{tf_k}', got {type(b_val).__name__}")
            if tf_norm in normalized_bundles:
                raise ValueError(f"Duplicate timeframe alias '{tf_k}' normalizing to '{tf_norm}'")
            normalized_bundles[tf_norm] = b_val

        # Governance Gate for SENSEX and top-level feed status
        if index_norm == "SENSEX" and not self.config.sensex_governance_approved:
            empty_tfs = {
                tf: TimeframeConfluenceReport(
                    timeframe=tf,
                    timeframe_role=TIMEFRAME_ROLES[tf],
                    direction="UNAVAILABLE",
                    data_quality="GOVERNANCE_LOCKOUT",
                )
                for tf in MTF_TIMEFRAME_ORDER
            }
            rep_id = generate_deterministic_mtf_id(
                "MTF", [index_norm, as_of_tz.isoformat(), "GOVERNANCE_LOCKOUT", self.config_fingerprint]
            )
            return MTFConfluenceReport(
                report_id=rep_id,
                index=index_norm,
                analysis_time=as_of_tz,
                execution_mode=EXECUTION_MODE,
                overall_alignment=AlignmentClassification.DATA_QUALITY_LOCKOUT,
                timeframe_reports=empty_tfs,
                missing_timeframes=MTF_TIMEFRAME_ORDER,
                data_quality_status="GOVERNANCE_LOCKOUT",
                confluence_score=None,
                score_status="UNAVAILABLE",
                calibration_status="NOT_CALIBRATED",
                configuration_version=self.config.configuration_version,
                configuration_fingerprint=self.config_fingerprint,
                engine_version=ENGINE_VERSION,
                explanation="SENSEX session/MTF intelligence blocked pending existing institutional governance approval.",
            )

        if top_quality in DISQUALIFYING_FEED_STATUSES or top_quality not in VALID_FEED_STATUSES:
            empty_tfs = {
                tf: TimeframeConfluenceReport(
                    timeframe=tf,
                    timeframe_role=TIMEFRAME_ROLES[tf],
                    direction="UNAVAILABLE",
                    data_quality=top_quality if top_quality in DISQUALIFYING_FEED_STATUSES else "INVALID_DATA",
                )
                for tf in MTF_TIMEFRAME_ORDER
            }
            eff_q = top_quality if top_quality in DISQUALIFYING_FEED_STATUSES else "INVALID_DATA"
            rep_id = generate_deterministic_mtf_id(
                "MTF", [index_norm, as_of_tz.isoformat(), eff_q, self.config_fingerprint]
            )
            return MTFConfluenceReport(
                report_id=rep_id,
                index=index_norm,
                analysis_time=as_of_tz,
                execution_mode=EXECUTION_MODE,
                overall_alignment=AlignmentClassification.DATA_QUALITY_LOCKOUT,
                timeframe_reports=empty_tfs,
                missing_timeframes=MTF_TIMEFRAME_ORDER,
                data_quality_status=eff_q,
                confluence_score=None,
                score_status="UNAVAILABLE",
                calibration_status="NOT_CALIBRATED",
                configuration_version=self.config.configuration_version,
                configuration_fingerprint=self.config_fingerprint,
                engine_version=ENGINE_VERSION,
                explanation=f"Data-quality fail-closed lockout: top-level feed status '{eff_q}'.",
            )

        tf_reports: Dict[str, TimeframeConfluenceReport] = {}
        aux_by_tf: Dict[str, Dict[str, Any]] = {}
        all_items: List[EvidenceSummaryItem] = []
        all_conflicts: List[ConflictRecord] = []

        for tf in MTF_TIMEFRAME_ORDER:
            rep, items, tf_conflicts, aux_ctx = self._evaluate_single_timeframe(
                tf=tf,
                bundle=normalized_bundles.get(tf),
                index_norm=index_norm,
                as_of_tz=as_of_tz,
            )
            tf_reports[tf] = rep
            aux_by_tf[tf] = aux_ctx
            all_items.extend(items)
            all_conflicts.extend(tf_conflicts)

        cross_conflicts, missing_tfs = self._detect_cross_timeframe_conflicts(
            index_norm=index_norm,
            tf_reports=tf_reports,
            aux_by_tf=aux_by_tf,
            as_of_tz=as_of_tz,
        )
        all_conflicts.extend(cross_conflicts)

        # Deduplicate conflicts & order deterministically
        dedup_conflicts: Dict[str, ConflictRecord] = {}
        for c in all_conflicts:
            dedup_conflicts.setdefault(c.conflict_id, c)
        ordered_conflicts = tuple(
            sorted(dedup_conflicts.values(), key=lambda c: (c.available_at, c.timeframe_a, c.timeframe_b, c.conflict_id))
        )

        # Determine aggregate data quality status across all supplied timeframes
        agg_quality = top_quality
        for tf in MTF_TIMEFRAME_ORDER:
            if tf in normalized_bundles:
                q_tf = tf_reports[tf].data_quality
                if q_tf in DISQUALIFYING_FEED_STATUSES or q_tf == "DATA_QUALITY_LOCKOUT":
                    agg_quality = q_tf
                    break

        overall = self._classify_overall_alignment(
            data_quality_status=agg_quality,
            tf_reports=tf_reports,
            conflicts=ordered_conflicts,
        )

        # Partition evidence across timeframes cleanly (deduplicated per (tf, event_id))
        bull_list: List[EvidenceSummaryItem] = []
        bear_list: List[EvidenceSummaryItem] = []
        neut_list: List[EvidenceSummaryItem] = []
        seen_global: Set[Tuple[str, str]] = set()
        seen_ids_flat: List[str] = []

        for item in sorted(all_items, key=lambda i: (i.available_at, i.event_time, i.timeframe, i.event_id)):
            gk = (item.timeframe, item.event_id)
            if gk in seen_global:
                continue
            seen_global.add(gk)
            if item.event_id not in seen_ids_flat:
                seen_ids_flat.append(item.event_id)
            if item.direction == EventDirection.BULLISH:
                bull_list.append(item)
            elif item.direction == EventDirection.BEARISH:
                bear_list.append(item)
            else:
                neut_list.append(item)

        rep_id = generate_deterministic_mtf_id(
            "MTF",
            [
                index_norm,
                as_of_tz.isoformat(),
                overall.value,
                agg_quality,
                self.config_fingerprint,
                ",".join(sorted(seen_ids_flat)),
                ",".join(c.conflict_id for c in ordered_conflicts),
            ],
        )

        tf_summary_parts = [f"{tf.upper()}={tf_reports[tf].direction}" for tf in MTF_TIMEFRAME_ORDER]
        explanation = (
            f"{index_norm} MTF ICT/SMC alignment at {as_of_tz.isoformat()}: {overall.value} "
            f"[{', '.join(tf_summary_parts)}]; conflicts={len(ordered_conflicts)}, "
            f"missing_timeframes={list(missing_tfs)}. Intelligence only ({EXECUTION_MODE}); "
            f"ICT confluence score remains UNAVAILABLE/NOT_CALIBRATED."
        )

        return MTFConfluenceReport(
            report_id=rep_id,
            index=index_norm,
            analysis_time=as_of_tz,
            execution_mode=EXECUTION_MODE,
            overall_alignment=overall,
            timeframe_reports=tf_reports,
            bullish_evidence=tuple(bull_list),
            bearish_evidence=tuple(bear_list),
            neutral_evidence=tuple(neut_list),
            conflicts=ordered_conflicts,
            missing_timeframes=missing_tfs,
            data_quality_status=agg_quality,
            confluence_score=None,
            score_status="UNAVAILABLE",
            calibration_status="NOT_CALIBRATED",
            evidence_event_ids=tuple(seen_ids_flat),
            configuration_version=self.config.configuration_version,
            configuration_fingerprint=self.config_fingerprint,
            engine_version=ENGINE_VERSION,
            explanation=explanation,
        )

    def evaluate_from_candles(
        self,
        *,
        index: str = "NIFTY 50",
        as_of_time: datetime,
        candles_by_timeframe: Dict[str, pd.DataFrame],
        data_quality_status: str = "VERIFIED_LIVE",
        include_session_context: bool = True,
    ) -> MTFConfluenceReport:
        """
        Orchestrates frozen Steps 3.1–3.6 engines on completed candles per timeframe
        and synthesizes the unified Step 3.7 `MTFConfluenceReport`.
        """
        index_norm = normalize_index_symbol(index)
        as_of_tz = _convert_to_tz(as_of_time, self.tz, "as_of_time")
        top_q = normalize_feed_status(data_quality_status)

        if not isinstance(candles_by_timeframe, dict):
            raise TypeError("candles_by_timeframe must be a dict mapping timeframe -> DataFrame")

        if top_q in DISQUALIFYING_FEED_STATUSES or top_q not in VALID_FEED_STATUSES or (
            index_norm == "SENSEX" and not self.config.sensex_governance_approved
        ):
            return self.evaluate_from_evidence(
                index=index_norm,
                as_of_time=as_of_tz,
                timeframe_evidence={},
                data_quality_status=top_q,
            )

        cal_ok, cal_status, _cal_err = self.session_engine._validate_trading_calendar(as_of_tz.date())
        if not cal_ok:
            cal_q = cal_status if cal_status in DISQUALIFYING_FEED_STATUSES else "CALENDAR_UNAVAILABLE"
            return self.evaluate_from_evidence(
                index=index_norm,
                as_of_time=as_of_tz,
                timeframe_evidence={},
                data_quality_status=cal_q,
            )

        bundles: Dict[str, TimeframeEvidenceBundle] = {}
        parent_range: Optional[DealingRange] = None

        # Process strictly in HTF -> LTF order so parent dealing range flows causally
        normalized_dfs: Dict[str, pd.DataFrame] = {}
        for k_tf, df_val in candles_by_timeframe.items():
            tf_norm = normalize_mtf_timeframe(k_tf)
            normalized_dfs[tf_norm] = df_val

        for tf in MTF_TIMEFRAME_ORDER:
            if tf not in normalized_dfs:
                continue
            raw_df = normalized_dfs[tf]
            filtered_df, eff_q, reasons, _, _ = self._audit_and_filter_dataframe(
                raw_df, tf, as_of_tz, top_q
            )
            if filtered_df is None or filtered_df.empty or reasons or eff_q in DISQUALIFYING_FEED_STATUSES:
                bundles[tf] = TimeframeEvidenceBundle(
                    timeframe=tf,
                    data_quality=eff_q,
                    candles_df=raw_df,
                )
                continue

            # Invoke frozen Step 3.1–3.6 engines strictly over completed bars (`filtered_df`).
            # Upstream structural engines (Steps 3.1–3.4) validate against {'VERIFIED_LIVE'},
            # while Steps 3.6/3.7 accept 'VERIFIED_EOD' historical EOD data; normalize only the
            # internal structural call status while preserving truthful `eff_q` on outputs.
            structural_q = "VERIFIED_LIVE" if eff_q in ("VERIFIED_EOD", "PRISTINE") else eff_q
            swings = self.swing_engine.detect_swings(
                df=filtered_df,
                symbol=index_norm,
                timeframe=tf,
                as_of_time=as_of_tz,
                data_quality_status=structural_q,
            )
            pools = self.liquidity_engine.detect_liquidity_pools(
                df=filtered_df,
                symbol=index_norm,
                timeframe=tf,
                as_of_time=as_of_tz,
                data_quality_status=structural_q,
            )
            updated_pools, liq_events = self.liquidity_engine.evaluate_liquidity_lifecycle(
                pools=pools,
                df=filtered_df,
                symbol=index_norm,
                timeframe=tf,
                as_of_time=as_of_tz,
            )
            struct_report = self.structure_engine.analyze_timeframe(
                df=filtered_df,
                symbol=index_norm,
                timeframe=tf,
                as_of_time=as_of_tz,
                data_quality_status=structural_q,
            )
            ob_report = self.order_block_engine.analyze_timeframe(
                df=filtered_df,
                structure_events=[
                    sev for sev in struct_report.structure_events
                ],
                symbol=index_norm,
                timeframe=tf,
                as_of_time=as_of_tz,
                data_quality_status=structural_q,
            )
            fvg_report = self.fvg_engine.analyze_timeframe(
                df=filtered_df,
                symbol=index_norm,
                timeframe=tf,
                as_of_time=as_of_tz,
                data_quality_status=structural_q,
            )

            latest_close = float(filtered_df["close"].iloc[-1])
            ts_to_bar_idx: Dict[datetime, int] = {}
            for bar_i, raw_bar_ts in enumerate(filtered_df["timestamp"].tolist()):
                ts_obj = pd.to_datetime(raw_bar_ts) if type(raw_bar_ts) is str else raw_bar_ts
                ts_to_bar_idx[_convert_to_tz(ts_obj, self.tz, f"{tf}.filtered.timestamp")] = bar_i

            atr_arr = None
            if len(filtered_df) >= 15:
                tr_arr = calculate_true_range(
                    filtered_df["high"].to_numpy(dtype=float),
                    filtered_df["low"].to_numpy(dtype=float),
                    filtered_df["close"].to_numpy(dtype=float),
                )
                atr_arr = calculate_atr_wilder(tr_arr, period=14)

            pd_swings = [_normalize_model_native(sw) for sw in swings]
            swing_type_by_id: Dict[str, str] = {
                sw.event_id.strip(): sw.swing_type.strip().upper()
                for sw in pd_swings
                if getattr(sw, "event_id", None) and getattr(sw, "swing_type", None)
            }
            pd_pools = [_normalize_model_native(pl) for pl in updated_pools]
            pd_liq_events = [
                _normalize_model_native(ev)
                for ev in liq_events
                if getattr(ev, "event_type", None)
                in (ICTEventType.LIQUIDITY_SWEEP, ICTEventType.LIQUIDITY_RECLAIM)
            ]

            typed_structure_events: List[MarketStructureEvent] = []
            atr_prov: Dict[str, Any] = {}
            for iev in struct_report.structure_events:
                if isinstance(iev, MarketStructureEvent):
                    ev_dict = _to_builtin_primitives(iev.evidence.model_dump())
                    raw_bst = str(ev_dict.get("broken_swing_type", "")).strip().upper()
                    bs_id = str(ev_dict.get("broken_swing_id", "")).strip()
                    if bs_id and bs_id in swing_type_by_id:
                        ev_dict["broken_swing_type"] = swing_type_by_id[bs_id]
                    elif raw_bst in ("HH", "LH", "EH", "HIGH", "SWING_HIGH"):
                        ev_dict["broken_swing_type"] = "HIGH"
                    elif raw_bst in ("LL", "HL", "EL", "LOW", "SWING_LOW"):
                        ev_dict["broken_swing_type"] = "LOW"
                    mse = iev.model_copy(
                        update={
                            "event_time": _to_builtin_primitives(iev.event_time),
                            "available_at": _to_builtin_primitives(iev.available_at),
                            "created_at": _to_builtin_primitives(iev.created_at),
                            "confirmed_at": _to_builtin_primitives(iev.confirmed_at or iev.available_at),
                            "invalidated_at": _to_builtin_primitives(iev.invalidated_at),
                            "evidence": MarketStructureEvidence(**ev_dict),
                        }
                    )
                elif isinstance(iev, ICTEvent):
                    ev_dict = _to_builtin_primitives(dict(iev.evidence)) if isinstance(iev.evidence, dict) else {}
                    raw_bst = str(ev_dict.get("broken_swing_type", "")).strip().upper()
                    bs_id = str(ev_dict.get("broken_swing_id", "")).strip()
                    if bs_id and bs_id in swing_type_by_id:
                        ev_dict["broken_swing_type"] = swing_type_by_id[bs_id]
                    elif raw_bst in ("HH", "LH", "EH", "HIGH", "SWING_HIGH"):
                        ev_dict["broken_swing_type"] = "HIGH"
                    elif raw_bst in ("LL", "HL", "EL", "LOW", "SWING_LOW"):
                        ev_dict["broken_swing_type"] = "LOW"
                    ms_ev = MarketStructureEvidence(**ev_dict)
                    mse = MarketStructureEvent(
                        event_id=iev.event_id,
                        index=iev.index,
                        event_type=iev.event_type,
                        direction=iev.direction,
                        timeframe=iev.timeframe,
                        broken_level=(
                            float(iev.price_level)
                            if iev.price_level is not None
                            else float(ms_ev.broken_level)
                        ),
                        event_status=iev.event_status,
                        event_time=_to_builtin_primitives(iev.event_time),
                        available_at=_to_builtin_primitives(iev.available_at),
                        created_at=_to_builtin_primitives(iev.created_at),
                        confirmed_at=_to_builtin_primitives(iev.confirmed_at or iev.available_at),
                        invalidated_at=_to_builtin_primitives(iev.invalidated_at),
                        source_candle_identifiers=list(iev.source_candle_identifiers),
                        data_quality=iev.data_quality,
                        evidence=ms_ev,
                        configuration_version=iev.configuration_version,
                        engine_version=iev.engine_version,
                    )
                else:
                    continue

                typed_structure_events.append(mse)
                break_ts = _convert_to_tz(mse.evidence.break_candle_time, self.tz, f"{tf}.break_candle_time")
                bar_k = ts_to_bar_idx.get(break_ts)
                if (
                    atr_arr is not None
                    and bar_k is not None
                    and bar_k >= 14
                    and bar_k < len(atr_arr)
                    and math.isfinite(float(atr_arr[bar_k]))
                    and float(atr_arr[bar_k]) > 0.0
                ):
                    atr_prov[mse.event_id] = {
                        "atr_status": "CALCULATED",
                        "is_fallback_atr": False,
                        "period": 14,
                        "atr_value": float(atr_arr[bar_k]),
                        "series_length": int(bar_k + 1),
                        "source": "WILDER_ATR_FROM_COMPLETED_CANDLES",
                    }
                else:
                    atr_prov[mse.event_id] = {
                        "atr_status": "UNAVAILABLE",
                        "is_fallback_atr": False,
                        "source": (
                            "WARMUP_OR_INSUFFICIENT_BARS_FOR_ATR_14"
                            if (atr_arr is None or bar_k is None or bar_k < 14)
                            else "NON_FINITE_ATR_14"
                        ),
                    }

            pd_report = self.premium_discount_engine.analyze_timeframe(
                index=index_norm,
                timeframe=tf,
                current_price=latest_close,
                swings=pd_swings,
                pools=pd_pools,
                liquidity_events=pd_liq_events,
                structure_events=typed_structure_events,
                as_of_time=as_of_tz,
                order_blocks=[_normalize_model_native(ob) for ob in ob_report.order_block_events],
                fvgs=[
                    _normalize_model_native(fv)
                    for fv in (list(fvg_report.fvg_events) + list(fvg_report.ifvg_events))
                ],
                parent_range=_normalize_model_native(parent_range) if parent_range is not None else None,
                atr_provenance=atr_prov,
            )
            if tf == "1h" and pd_report.active_dealing_range is not None:
                parent_range = pd_report.active_dealing_range

            sess_rep: Optional[TimeframeSessionReport] = None
            if include_session_context:
                session_q = "VERIFIED_LIVE" if eff_q == "PRISTINE" else eff_q
                cand_rep = self.session_engine.evaluate_session(
                    df=filtered_df,
                    symbol=index_norm,
                    timeframe=tf,
                    as_of_time=as_of_tz,
                    data_quality_status=session_q,
                    liquidity_pools=updated_pools,
                    liquidity_events=liq_events,
                )
                # Preserve valid session reports or calendar lockouts cleanly
                sess_rep = cand_rep

            bundles[tf] = TimeframeEvidenceBundle(
                timeframe=tf,
                data_quality=eff_q,
                candles_df=filtered_df,
                liquidity_pools=updated_pools,
                liquidity_events=liq_events,
                structure_report=struct_report,
                order_block_report=ob_report,
                fvg_report=fvg_report,
                premium_discount_report=pd_report,
                session_report=sess_rep,
                current_price=latest_close,
            )

        return self.evaluate_from_evidence(
            index=index_norm,
            as_of_time=as_of_tz,
            timeframe_evidence=bundles,
            data_quality_status=top_q,
        )

    def replay(
        self,
        *,
        index: str = "NIFTY 50",
        replay_times: Sequence[datetime],
        timeframe_evidence: Optional[Dict[str, TimeframeEvidenceBundle]] = None,
        candles_by_timeframe: Optional[Dict[str, pd.DataFrame]] = None,
        data_quality_status: str = "VERIFIED_LIVE",
    ) -> List[MTFConfluenceReport]:
        """Deterministic chronological replay over a sequence of `as_of_time` instants."""
        if type(replay_times) not in (list, tuple):
            raise TypeError("replay_times must be a list or tuple of timezone-aware datetimes")
        if (timeframe_evidence is None) == (candles_by_timeframe is None):
            raise ValueError("Provide exactly one of timeframe_evidence or candles_by_timeframe")

        converted = [_convert_to_tz(rt, self.tz, "replay_time") for rt in replay_times]
        for idx_t in range(1, len(converted)):
            if converted[idx_t] < converted[idx_t - 1]:
                raise ValueError("replay_times must be non-decreasing")

        reports: List[MTFConfluenceReport] = []
        for ts in converted:
            if timeframe_evidence is not None:
                reports.append(
                    self.evaluate_from_evidence(
                        index=index,
                        as_of_time=ts,
                        timeframe_evidence=timeframe_evidence,
                        data_quality_status=data_quality_status,
                    )
                )
            else:
                reports.append(
                    self.evaluate_from_candles(
                        index=index,
                        as_of_time=ts,
                        candles_by_timeframe=candles_by_timeframe or {},
                        data_quality_status=data_quality_status,
                    )
                )
        return reports


__all__ = [
    "ENGINE_VERSION",
    "DEFAULT_CONFIGURATION_VERSION",
    "EXECUTION_MODE",
    "MTF_TIMEFRAME_ORDER",
    "TIMEFRAME_ROLES",
    "DEFAULT_MAX_EVIDENCE_AGE_MINUTES",
    "AlignmentClassification",
    "ConflictType",
    "ConflictSeverity",
    "MTFConfluenceConfiguration",
    "TimeframeEvidenceBundle",
    "EvidenceSummaryItem",
    "ConflictRecord",
    "TimeframeConfluenceReport",
    "MTFConfluenceReport",
    "MTFConfluenceEngine",
    "normalize_mtf_timeframe",
    "generate_deterministic_mtf_id",
]
