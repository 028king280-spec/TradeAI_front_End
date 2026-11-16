"""
AIVOLVE Phase 3 Common ICT/SMC Event Data Contract.
Defines strongly typed Pydantic models for ICT events, swing pivots, liquidity pools,
liquidity events, evidence, configurations, and deterministic event ID generation.
"""

from typing import List, Dict, Any, Optional, Set, Union
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import math
import zoneinfo
from pydantic import BaseModel, Field, field_validator, ConfigDict, model_validator

IST_ZONE = zoneinfo.ZoneInfo("Asia/Kolkata")


# ---------------------------------------------------------------------
# 1. Core Enumerations
# ---------------------------------------------------------------------

class ICTEventType(str, Enum):
    SWING_HIGH = "SWING_HIGH"
    SWING_LOW = "SWING_LOW"
    LIQUIDITY_POOL = "LIQUIDITY_POOL"
    LIQUIDITY_SWEEP = "LIQUIDITY_SWEEP"
    LIQUIDITY_RECLAIM = "LIQUIDITY_RECLAIM"
    LIQUIDITY_CONFIRMED = "LIQUIDITY_CONFIRMED"
    LIQUIDITY_CONSUMED = "LIQUIDITY_CONSUMED"
    EQUAL_HIGHS = "EQUAL_HIGHS"
    EQUAL_LOWS = "EQUAL_LOWS"
    PREVIOUS_DAY_HIGH = "PREVIOUS_DAY_HIGH"
    PREVIOUS_DAY_LOW = "PREVIOUS_DAY_LOW"
    PREVIOUS_WEEK_HIGH = "PREVIOUS_WEEK_HIGH"
    PREVIOUS_WEEK_LOW = "PREVIOUS_WEEK_LOW"
    SESSION_HIGH = "SESSION_HIGH"
    SESSION_LOW = "SESSION_LOW"
    OPENING_RANGE = "OPENING_RANGE"
    BOS = "BOS"
    CHOCH = "CHOCH"
    MSS = "MSS"
    ORDER_BLOCK = "ORDER_BLOCK"
    FVG = "FVG"
    IFVG = "IFVG"


class EventDirection(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class ICTTimeframe(str, Enum):
    TF_1H = "1h"
    TF_15M = "15m"
    TF_5M = "5m"
    TF_3M = "3m"
    TF_1M = "1m"
    TF_1D = "1d"


class LiquidityType(str, Enum):
    BSL = "BSL"                       # Buy Side Liquidity
    SSL = "SSL"                       # Sell Side Liquidity
    EQH = "EQH"                       # Equal Highs
    EQL = "EQL"                       # Equal Lows
    PDH = "PDH"                       # Previous Day High
    PDL = "PDL"                       # Previous Day Low
    PWH = "PWH"                       # Previous Week High
    PWL = "PWL"                       # Previous Week Low
    SESSION_HIGH = "SESSION_HIGH"
    SESSION_LOW = "SESSION_LOW"
    OPENING_RANGE_HIGH = "OPENING_RANGE_HIGH"
    OPENING_RANGE_LOW = "OPENING_RANGE_LOW"


class LiquidityLifecycleState(str, Enum):
    IDENTIFIED = "IDENTIFIED"
    APPROACHING = "APPROACHING"
    SWEPT = "SWEPT"
    RECLAIMED = "RECLAIMED"
    CONFIRMED = "CONFIRMED"
    CONSUMED = "CONSUMED"
    EXPIRED = "EXPIRED"
    INVALIDATED = "INVALIDATED"
    MITIGATED = "MITIGATED"
    PARTIALLY_MITIGATED = "PARTIALLY_MITIGATED"


# ---------------------------------------------------------------------
# 2. Strict Lifecycle State Machine Validation
# Sequence: IDENTIFIED -> APPROACHING -> SWEPT -> RECLAIMED -> CONFIRMED
# Terminal states: CONSUMED, EXPIRED, INVALIDATED
#
# Intentional Transitions Justification:
# - IDENTIFIED -> SWEPT: Permitted and intentional. In fast-moving or gap-open conditions,
#   a single bar can directly wick penetrate the pool without spending a prior bar in APPROACHING.
#   Required Evidence: Wick penetration >= sweep_penetration_min_pts, with close on resting side.
# - APPROACHING -> SWEPT: Permitted and intentional. When price previously approached within
#   approach_threshold_pct and subsequently penetrates the pool with its wick.
# - APPROACHING -> IDENTIFIED: Permitted retreat/reset condition when price moves back away from
#   the pool beyond (approach_threshold_pct * approach_retreat_mult).
# - SWEPT -> CONFIRMED: Strictly PROHIBITED. A sweep cannot progress to confirmed without RECLAIMED
#   evidence (rejection wick ratio >= rejection_wick_ratio_min).
# ---------------------------------------------------------------------

VALID_LIFECYCLE_TRANSITIONS: Dict[LiquidityLifecycleState, Set[LiquidityLifecycleState]] = {
    LiquidityLifecycleState.IDENTIFIED: {
        LiquidityLifecycleState.APPROACHING,
        LiquidityLifecycleState.SWEPT,
        LiquidityLifecycleState.CONSUMED,
        LiquidityLifecycleState.EXPIRED,
        LiquidityLifecycleState.INVALIDATED,
    },
    LiquidityLifecycleState.APPROACHING: {
        LiquidityLifecycleState.IDENTIFIED,  # Price retreats away beyond retreat threshold
        LiquidityLifecycleState.SWEPT,       # Wick penetrates pool level
        LiquidityLifecycleState.CONSUMED,    # Decisive breakout candle body close
        LiquidityLifecycleState.EXPIRED,
        LiquidityLifecycleState.INVALIDATED,
    },
    # Strictly requires RECLAIM before CONFIRMED. SWEPT cannot jump directly to CONFIRMED.
    LiquidityLifecycleState.SWEPT: {
        LiquidityLifecycleState.RECLAIMED,
        LiquidityLifecycleState.CONSUMED,
        LiquidityLifecycleState.INVALIDATED,
    },
    # From RECLAIMED, progresses to CONFIRMED (completed reversal follow-through candle).
    LiquidityLifecycleState.RECLAIMED: {
        LiquidityLifecycleState.CONFIRMED,
        LiquidityLifecycleState.CONSUMED,
        LiquidityLifecycleState.INVALIDATED,
    },
    # CONFIRMED pool remains active until breached (CONSUMED), stale (EXPIRED), or invalidated.
    LiquidityLifecycleState.CONFIRMED: {
        LiquidityLifecycleState.CONSUMED,
        LiquidityLifecycleState.EXPIRED,
        LiquidityLifecycleState.INVALIDATED,
    },
    # Terminal states: cannot transition back into any active or other terminal state.
    LiquidityLifecycleState.CONSUMED: set(),
    LiquidityLifecycleState.EXPIRED: set(),
    LiquidityLifecycleState.INVALIDATED: set(),
}


def validate_lifecycle_transition(
    current_state: LiquidityLifecycleState,
    target_state: LiquidityLifecycleState,
) -> bool:
    """Checks whether the transition between current and target state is mathematically valid."""
    allowed = VALID_LIFECYCLE_TRANSITIONS.get(current_state, set())
    return target_state in allowed


VALID_ORDER_BLOCK_TRANSITIONS: Dict[LiquidityLifecycleState, Set[LiquidityLifecycleState]] = {
    LiquidityLifecycleState.IDENTIFIED: {
        LiquidityLifecycleState.CONFIRMED,
        LiquidityLifecycleState.INVALIDATED,
        LiquidityLifecycleState.EXPIRED,
    },
    LiquidityLifecycleState.CONFIRMED: {
        LiquidityLifecycleState.APPROACHING,
        LiquidityLifecycleState.PARTIALLY_MITIGATED,
        LiquidityLifecycleState.MITIGATED,
        LiquidityLifecycleState.INVALIDATED,
        LiquidityLifecycleState.EXPIRED,
    },
    LiquidityLifecycleState.APPROACHING: {
        LiquidityLifecycleState.CONFIRMED,  # Retreat/reset away from zone
        LiquidityLifecycleState.PARTIALLY_MITIGATED,
        LiquidityLifecycleState.MITIGATED,
        LiquidityLifecycleState.INVALIDATED,
        LiquidityLifecycleState.EXPIRED,
    },
    LiquidityLifecycleState.PARTIALLY_MITIGATED: {
        LiquidityLifecycleState.MITIGATED,
        LiquidityLifecycleState.INVALIDATED,
        LiquidityLifecycleState.EXPIRED,
    },
    # Terminal states: cannot transition back to active states
    LiquidityLifecycleState.MITIGATED: set(),
    LiquidityLifecycleState.INVALIDATED: set(),
    LiquidityLifecycleState.EXPIRED: set(),
    LiquidityLifecycleState.CONSUMED: set(),
}


def validate_order_block_transition(
    current_state: LiquidityLifecycleState,
    target_state: LiquidityLifecycleState,
) -> bool:
    """Checks whether the transition between Order Block lifecycle states is mathematically valid."""
    allowed = VALID_ORDER_BLOCK_TRANSITIONS.get(current_state, set())
    return target_state in allowed


# ---------------------------------------------------------------------
# 3. Deterministic Event Identifiers
# ---------------------------------------------------------------------

def generate_deterministic_event_id(
    index: str,
    timeframe: str,
    event_type: str,
    source_candle_id: str,
    configuration_version: str,
) -> str:
    """
    Generates a stable, reproducible ID from canonical event inputs:
    index + timeframe + event_type + source_candle_id + configuration_version
    Uses SHA-256 cryptographic digest.
    """
    clean_sym = str(index).upper().strip()
    clean_tf = str(timeframe).lower().strip()
    clean_type = str(event_type).upper().strip()
    clean_cid = str(source_candle_id).strip()
    clean_ver = str(configuration_version).strip()

    canonical_str = f"{clean_sym}|{clean_tf}|{clean_type}|{clean_cid}|{clean_ver}"
    digest = hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()[:16].upper()
    prefix = clean_type.replace("_", "")[:3]
    return f"EVT-{prefix}-{digest}"


# ---------------------------------------------------------------------
# 4. Typed Data Models
# ---------------------------------------------------------------------

def _ensure_timezone_aware(dt: Any) -> datetime:
    """Ensures datetime is timezone-aware. Defaults naive to Asia/Kolkata (IST)."""
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt)
        except Exception:
            dt = datetime.now(IST_ZONE)
    if not isinstance(dt, datetime):
        return datetime.now(IST_ZONE)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=IST_ZONE)
    return dt


class LiquidityEvidence(BaseModel):
    """
    Empirical evidence supporting a liquidity pool or event.
    Explicitly distinguishes observed traded volume from resting limit order pools.
    """
    touch_count: int = Field(default=1, ge=1)
    distance_from_current_pts: Optional[float] = None
    distance_from_current_pct: Optional[float] = None
    penetration_depth_pts: Optional[float] = None
    penetration_depth_pct: Optional[float] = None
    is_wick_penetration: bool = False
    is_candle_close_breakout: bool = False
    is_reclaim_confirmed: bool = False
    observed_traded_volume: Optional[float] = None  # Observed bar volume; NOT resting order volume
    volume_evidence_available: bool = True
    reaction_displacement_ratio: Optional[float] = None
    rejection_wick_ratio: Optional[float] = None
    source_swing_ids: List[str] = Field(default_factory=list)
    rejection_reasons: List[str] = Field(default_factory=list)


class SwingPoint(BaseModel):
    """
    Confirmed Fractal Swing High or Swing Low pivot.
    Strictly separates event_time (when pivot occurred) from available_at (when right confirmation completed).
    """
    event_id: str
    index: str
    swing_type: str  # 'HIGH' | 'LOW'
    price: float
    timeframe: str
    bar_index: int
    candle_id: str
    event_time: datetime
    available_at: datetime
    left_bars: int
    right_bars: int
    volume: Optional[float] = None
    data_quality_status: str = "VERIFIED_LIVE"
    configuration_version: str = "3.1.0"
    engine_version: str = "3.1.0"

    @property
    def symbol(self) -> str:
        return self.index

    @property
    def lifecycle_state(self) -> "LiquidityLifecycleState":
        return self.event_status

    @property
    def model_version(self) -> str:
        return self.engine_version

    @property
    def sweep_details(self) -> Dict[str, Any]:
        return self.evidence

    @property
    def event_status(self) -> "LiquidityLifecycleState":
        return LiquidityLifecycleState.CONFIRMED

    @property
    def created_at(self) -> datetime:
        return self.event_time

    @property
    def confirmed_at(self) -> datetime:
        return self.available_at

    @property
    def invalidated_at(self) -> Optional[datetime]:
        return None

    @property
    def source_candle_identifiers(self) -> List[str]:
        return [self.candle_id]

    @property
    def source_data_quality(self) -> str:
        return self.data_quality_status

    @property
    def data_quality(self) -> str:
        return self.data_quality_status

    @property
    def evidence(self) -> Dict[str, Any]:
        return {"left_bars": self.left_bars, "right_bars": self.right_bars, "volume": self.volume}

    def to_ict_event(self) -> "ICTEvent":
        evt_type = ICTEventType.SWING_HIGH if self.swing_type == "HIGH" else ICTEventType.SWING_LOW
        evt_dir = EventDirection.BEARISH if self.swing_type == "HIGH" else EventDirection.BULLISH
        return ICTEvent(
            event_id=self.event_id,
            index=self.index,
            event_type=evt_type,
            direction=evt_dir,
            timeframe=self.timeframe,
            price_level=self.price,
            event_status=LiquidityLifecycleState.CONFIRMED,
            created_at=self.event_time,
            event_time=self.event_time,
            available_at=self.available_at,
            confirmed_at=self.available_at,
            invalidated_at=None,
            source_candle_identifiers=[self.candle_id],
            data_quality=self.data_quality_status,
            evidence={"left_bars": self.left_bars, "right_bars": self.right_bars, "volume": self.volume},
            configuration_version=self.configuration_version,
            engine_version=self.engine_version,
        )

    @field_validator("event_time", "available_at", mode="before")
    def validate_tz(cls, v: Any) -> datetime:
        return _ensure_timezone_aware(v)


class LiquidityPool(BaseModel):
    """
    Identified Liquidity Pool (BSL, SSL, EQH, EQL, PDH, PDL, Session Extremes).
    Maintains full lifecycle state machine and verification metadata.
    """
    pool_id: str
    index: str
    liquidity_type: LiquidityType
    direction: EventDirection
    timeframe: str
    level: float
    upper_bound: float
    lower_bound: float
    status: LiquidityLifecycleState = LiquidityLifecycleState.IDENTIFIED
    touch_count: int = Field(default=1, ge=1)
    evidence: LiquidityEvidence = Field(default_factory=LiquidityEvidence)
    formation_time: datetime
    available_at: datetime
    updated_at: datetime
    confirmed_at: Optional[datetime] = None
    invalidated_at: Optional[datetime] = None
    source_candle_ids: List[str] = Field(default_factory=list)
    source_candle_identifiers: List[str] = Field(default_factory=list)
    source_data_quality: str = "VERIFIED_LIVE"
    configuration_version: str = "3.1.0"
    engine_version: str = "3.1.0"

    @property
    def symbol(self) -> str:
        return self.index

    @property
    def lifecycle_state(self) -> "LiquidityLifecycleState":
        return self.status

    @property
    def model_version(self) -> str:
        return self.engine_version

    @property
    def sweep_details(self) -> Dict[str, Any]:
        return self.evidence.model_dump()

    @property
    def price_level(self) -> float:
        return self.level

    @property
    def event_id(self) -> str:
        return self.pool_id

    @property
    def event_type(self) -> "ICTEventType":
        return ICTEventType.LIQUIDITY_POOL

    @property
    def event_status(self) -> "LiquidityLifecycleState":
        return self.status

    @property
    def data_quality(self) -> str:
        return self.source_data_quality

    @property
    def event_time(self) -> datetime:
        return self.formation_time

    @property
    def created_at(self) -> datetime:
        return self.formation_time

    def to_ict_event(self) -> "ICTEvent":
        return ICTEvent(
            event_id=self.pool_id,
            index=self.index,
            event_type=ICTEventType.LIQUIDITY_POOL,
            direction=self.direction,
            timeframe=self.timeframe,
            price_level=self.level,
            zone_high=self.upper_bound,
            zone_low=self.lower_bound,
            event_status=self.status,
            created_at=self.formation_time,
            event_time=self.formation_time,
            available_at=self.available_at,
            confirmed_at=self.confirmed_at,
            invalidated_at=self.invalidated_at,
            source_candle_identifiers=self.source_candle_identifiers,
            data_quality=self.source_data_quality,
            evidence=self.evidence.model_dump(),
            configuration_version=self.configuration_version,
            engine_version=self.engine_version,
        )

    @field_validator("formation_time", "available_at", "updated_at", mode="before")
    def validate_tz(cls, v: Any) -> datetime:
        return _ensure_timezone_aware(v)

    def transition_to(
        self,
        new_state: LiquidityLifecycleState,
        timestamp: datetime,
        reason: str = "",
    ) -> None:
        """Transitions pool to a new lifecycle state enforcing the strict sequence."""
        ts = _ensure_timezone_aware(timestamp)
        if not validate_lifecycle_transition(self.status, new_state):
            raise ValueError(
                f"Invalid lifecycle transition: cannot transition LiquidityPool '{self.pool_id}' "
                f"from {self.status.value} to {new_state.value}. (Reason: {reason})"
            )
        self.status = new_state
        self.updated_at = ts
        if new_state == LiquidityLifecycleState.CONFIRMED and not self.confirmed_at:
            self.confirmed_at = ts
        elif new_state in (
            LiquidityLifecycleState.CONSUMED,
            LiquidityLifecycleState.INVALIDATED,
            LiquidityLifecycleState.EXPIRED,
        ):
            self.invalidated_at = ts


class LiquidityEvent(BaseModel):
    """
    Represents an interaction or state-change event on a liquidity pool
    (e.g., Wick Sweep, Candle Breakout, Reclaim).
    """
    event_id: str
    pool_id: str
    index: str
    event_type: ICTEventType
    liquidity_type: LiquidityType
    direction: EventDirection = EventDirection.NEUTRAL
    timeframe: str
    level: float
    price_level: Optional[float] = None
    trigger_candle_id: str
    penetration_price: float
    close_price: float
    penetration_depth_pts: float
    event_time: datetime
    available_at: datetime
    created_at: Optional[datetime] = None
    confirmed_at: Optional[datetime] = None
    invalidated_at: Optional[datetime] = None
    is_wick_sweep: bool
    is_candle_close_breakout: bool
    is_reclaimed: bool
    evidence: LiquidityEvidence = Field(default_factory=LiquidityEvidence)
    status: LiquidityLifecycleState = LiquidityLifecycleState.IDENTIFIED
    source_candle_identifiers: List[str] = Field(default_factory=list)
    source_data_quality: str = "VERIFIED_LIVE"
    configuration_version: str = "3.1.0"
    engine_version: str = "3.1.0"

    @property
    def symbol(self) -> str:
        return self.index

    @property
    def lifecycle_state(self) -> "LiquidityLifecycleState":
        return self.status

    @property
    def model_version(self) -> str:
        return self.engine_version

    @property
    def sweep_details(self) -> Dict[str, Any]:
        return self.evidence.model_dump()

    @property
    def event_status(self) -> "LiquidityLifecycleState":
        return self.status

    @property
    def data_quality(self) -> str:
        return self.source_data_quality

    def to_ict_event(self) -> "ICTEvent":
        return ICTEvent(
            event_id=self.event_id,
            index=self.index,
            event_type=self.event_type,
            direction=self.direction,
            timeframe=self.timeframe,
            price_level=self.level,
            event_status=self.status,
            created_at=self.created_at or self.event_time,
            event_time=self.event_time,
            available_at=self.available_at,
            confirmed_at=self.confirmed_at,
            invalidated_at=self.invalidated_at,
            source_candle_identifiers=self.source_candle_identifiers,
            data_quality=self.source_data_quality,
            evidence=self.evidence.model_dump(),
            configuration_version=self.configuration_version,
            engine_version=self.engine_version,
        )

    @field_validator("event_time", "available_at", mode="before")
    def validate_tz(cls, v: Any) -> datetime:
        return _ensure_timezone_aware(v)


class ICTEvent(BaseModel):
    """
    Unified common ICT event envelope matching Phase 3 Section 6 specification.
    Strictly implements the frozen 17-field event contract with full bidirectional
    backward compatibility for legacy consumer field aliases:
    1. event_id (str)
    2. index (str) [alias/property: symbol]
    3. event_type (ICTEventType)
    4. direction (EventDirection)
    5. timeframe (str)
    6. price_level / zone (float / tuple[float, float])
    7. event_status (LiquidityLifecycleState) [alias/property: lifecycle_state]
    8. event_time (datetime)
    9. available_at (datetime)
    10. created_at (datetime)
    11. confirmed_at (Optional[datetime])
    12. invalidated_at (Optional[datetime])
    13. source_candle_identifiers (List[str])
    14. data_quality (str) [alias/property: source_data_quality]
    15. evidence (Dict[str, Any]) [alias/property: sweep_details]
    16. configuration_version (str)
    17. engine_version (str) [alias/property: model_version]
    """
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    # 1. event_id
    event_id: str
    # 2. index (legacy: symbol)
    index: str
    # 3. event_type
    event_type: ICTEventType
    # 4. direction
    direction: EventDirection
    # 5. timeframe
    timeframe: str
    # 6. price_level / zone
    price_level: Optional[float] = None
    zone_high: Optional[float] = None
    zone_low: Optional[float] = None
    # 7. event_status (legacy: lifecycle_state)
    event_status: LiquidityLifecycleState = LiquidityLifecycleState.IDENTIFIED
    # 8. event_time
    event_time: datetime
    # 9. available_at
    available_at: datetime
    # 10. created_at
    created_at: datetime
    # 11. confirmed_at
    confirmed_at: Optional[datetime] = None
    # 12. invalidated_at
    invalidated_at: Optional[datetime] = None
    # 13. source_candle_identifiers
    source_candle_identifiers: List[str] = Field(default_factory=list)
    # 14. data_quality (legacy: source_data_quality)
    data_quality: str = "VERIFIED_LIVE"
    # 15. evidence (legacy: sweep_details)
    evidence: Dict[str, Any] = Field(default_factory=dict)
    # 16. configuration_version
    configuration_version: str = "3.1.0"
    # 17. engine_version (legacy: model_version)
    engine_version: str = "3.1.0"

    # Backward compatibility properties for legacy consumers
    @property
    def symbol(self) -> str:
        return self.index

    @property
    def lifecycle_state(self) -> LiquidityLifecycleState:
        return self.event_status

    @property
    def source_data_quality(self) -> str:
        return self.data_quality

    @property
    def model_version(self) -> str:
        return self.engine_version

    @property
    def sweep_details(self) -> Dict[str, Any]:
        return self.evidence

    @property
    def zone(self) -> Optional[tuple[float, float]]:
        if self.zone_low is not None and self.zone_high is not None:
            return (self.zone_low, self.zone_high)
        if self.price_level is not None:
            return (self.price_level, self.price_level)
        return None

    @model_validator(mode="before")
    @classmethod
    def resolve_legacy_field_mappings(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # 1. symbol <-> index conflict protection & mapping
            if "index" in data and "symbol" in data:
                val_index = str(data["index"]).strip()
                val_symbol = str(data["symbol"]).strip()
                if val_index != val_symbol:
                    raise ValueError(
                        f"Conflicting fields: canonical 'index' ('{data['index']}') "
                        f"and legacy 'symbol' ('{data['symbol']}') contradict."
                    )
            elif "symbol" in data and "index" not in data:
                data["index"] = data["symbol"]

            # 2. lifecycle_state <-> event_status conflict protection & mapping
            if "event_status" in data and "lifecycle_state" in data:
                es = data["event_status"].value if hasattr(data["event_status"], "value") else str(data["event_status"]).strip()
                ls = data["lifecycle_state"].value if hasattr(data["lifecycle_state"], "value") else str(data["lifecycle_state"]).strip()
                if es != ls:
                    raise ValueError(
                        f"Conflicting fields: canonical 'event_status' ('{es}') "
                        f"and legacy 'lifecycle_state' ('{ls}') contradict."
                    )
            elif "lifecycle_state" in data and "event_status" not in data:
                data["event_status"] = data["lifecycle_state"]

            # 3. model_version <-> engine_version conflict protection & mapping
            if "engine_version" in data and "model_version" in data:
                val_ev = str(data["engine_version"]).strip()
                val_mv = str(data["model_version"]).strip()
                if val_ev != val_mv:
                    raise ValueError(
                        f"Conflicting fields: canonical 'engine_version' ('{data['engine_version']}') "
                        f"and legacy 'model_version' ('{data['model_version']}') contradict."
                    )
            elif "model_version" in data and "engine_version" not in data:
                data["engine_version"] = data["model_version"]

            # 4. sweep_details <-> evidence conflict protection & mapping
            if "evidence" in data and "sweep_details" in data:
                ev_norm = data["evidence"].model_dump() if hasattr(data["evidence"], "model_dump") else data["evidence"]
                sd_norm = data["sweep_details"].model_dump() if hasattr(data["sweep_details"], "model_dump") else data["sweep_details"]
                if ev_norm != sd_norm:
                    raise ValueError(
                        "Conflicting fields: canonical 'evidence' and legacy 'sweep_details' contradict."
                    )
            elif "sweep_details" in data and "evidence" not in data:
                data["evidence"] = data["sweep_details"]

            # 5. source_data_quality <-> data_quality conflict protection & mapping
            if "data_quality" in data and "source_data_quality" in data:
                val_dq = str(data["data_quality"]).strip()
                val_sdq = str(data["source_data_quality"]).strip()
                if val_dq != val_sdq:
                    raise ValueError(
                        f"Conflicting fields: canonical 'data_quality' ('{data['data_quality']}') "
                        f"and legacy 'source_data_quality' ('{data['source_data_quality']}') contradict."
                    )
            elif "source_data_quality" in data and "data_quality" not in data:
                data["data_quality"] = data["source_data_quality"]

            # 6. zone tuple / bounds handling
            if "zone" in data and isinstance(data["zone"], (list, tuple)) and len(data["zone"]) == 2:
                if "zone_low" not in data:
                    data["zone_low"] = float(data["zone"][0])
                if "zone_high" not in data:
                    data["zone_high"] = float(data["zone"][1])
                if "price_level" not in data:
                    data["price_level"] = round((float(data["zone"][0]) + float(data["zone"][1])) / 2.0, 2)
        return data

    @field_validator("created_at", "event_time", "available_at", mode="before")
    def validate_tz(cls, v: Any) -> datetime:
        return _ensure_timezone_aware(v)


class LiquidityConfiguration(BaseModel):
    """
    Versioned configuration parameters for Liquidity and Swing Detection.
    NOTE: All defaults are uncalibrated empirical research parameters.
    Zero profitability, win rate, or predictive power is claimed or implied.
    """
    model_config = ConfigDict(frozen=True)

    configuration_version: str = "3.1.0"

    # Swing Pivot Settings
    swing_left_bars: int = Field(default=3, ge=1)
    swing_right_bars: int = Field(default=3, ge=1)
    tie_breaking_policy: str = "FIRST"  # 'FIRST' | 'LAST' | 'ALLOW_MULTI' | 'STRICT'

    # Equal Highs / Lows (EQH / EQL)
    eq_tolerance_pct: float = Field(default=0.0010, ge=0.0)    # 0.10% price tolerance (25 pts on NIFTY 25,000)
    eq_tolerance_tick_mult: int = Field(default=4, ge=1)        # 4 ticks (0.20 pts on 0.05 tick size)
    min_touches_for_eq: int = Field(default=2, ge=2)
    touch_count_min: int = Field(default=1, ge=1)

    # Lifecycle & Sweep Thresholds
    approach_threshold_pct: float = Field(default=0.0020, gt=0.0)  # 0.20% proximity
    approach_retreat_mult: float = Field(default=1.5, ge=1.0)     # Distance factor to retreat APPROACHING -> IDENTIFIED
    sweep_penetration_min_pts: float = Field(default=1.5, ge=0.0)
    rejection_wick_ratio_min: float = Field(default=0.35, ge=0.0, le=1.0)
    max_lookback_bars: int = Field(default=250, ge=1)
    expiry_policy: str = "MAX_LOOKBACK"  # 'MAX_LOOKBACK' | 'SESSION_CLOSE' | 'NEVER'

    # Indian Market Session Windows (IST)
    opening_range_start: str = "09:15"
    opening_range_end: str = "09:45"
    morning_start: str = "09:45"
    morning_end: str = "11:30"
    midday_start: str = "11:30"
    midday_end: str = "13:30"
    afternoon_start: str = "13:30"
    afternoon_end: str = "14:45"
    closing_start: str = "14:45"
    closing_end: str = "15:30"

    @field_validator("expiry_policy")
    def validate_expiry_policy(cls, v: str) -> str:
        valid_policies = {"MAX_LOOKBACK", "SESSION_CLOSE", "NEVER"}
        clean = str(v).upper().strip()
        if clean not in valid_policies:
            raise ValueError(f"Invalid expiry_policy '{v}'. Permitted values: {valid_policies}")
        return clean

    @field_validator("tie_breaking_policy")
    def validate_tie_breaking_policy(cls, v: str) -> str:
        valid_policies = {"FIRST", "LAST", "ALLOW_MULTI", "STRICT"}
        clean = str(v).upper().strip()
        if clean not in valid_policies:
            raise ValueError(f"Invalid tie_breaking_policy '{v}'. Permitted values: {valid_policies}")
        return clean


# =====================================================================
# Phase 3 Step 3.2 Models: Market Structure & Change of Character
# =====================================================================

class StructuralSwingType(str, Enum):
    """Classification of confirmed swing pivots into structural hierarchy."""
    HH = "HH"              # Higher High
    HL = "HL"              # Higher Low
    LH = "LH"              # Lower High
    LL = "LL"              # Lower Low
    EH = "EH"              # Equal High
    EL = "EL"              # Equal Low
    INITIAL = "INITIAL"    # Initial baseline pivot (no preceding same-extrema to compare)
    UNCERTAIN = "UNCERTAIN"


class TrendBias(str, Enum):
    """Established structural market trend direction."""
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class StructuralSwing(BaseModel):
    """
    Confirmed swing point enriched with institutional structural classification (HH, HL, LH, LL).
    """
    event_id: str
    index: str
    timeframe: str
    swing_type: str  # "HIGH" or "LOW"
    classification: StructuralSwingType
    price: float
    bar_index: int
    candle_id: str
    event_time: datetime
    available_at: datetime
    source_swing_id: str
    previous_same_extrema_id: Optional[str] = None
    price_diff: float = 0.0
    price_diff_pct: float = 0.0
    data_quality_status: str = "VERIFIED_LIVE"
    configuration_version: str = "3.2.0"
    engine_version: str = "3.2.0"

    @property
    def symbol(self) -> str:
        return self.index

    @field_validator("event_time", "available_at", mode="before")
    def validate_tz(cls, v: Any) -> datetime:
        return _ensure_timezone_aware(v)


class MarketStructureEvidence(BaseModel):
    """
    Empirical quantitative evidence accompanying every BOS, CHoCH, and MSS event.
    """
    broken_level: float
    broken_swing_id: str
    broken_swing_type: str
    broken_swing_time: datetime
    break_candle_id: str
    break_candle_time: datetime
    break_candle_open: float
    break_candle_high: float
    break_candle_low: float
    break_candle_close: float
    penetration_depth_pts: float
    is_body_close: bool = True
    body_to_range_ratio: float = 0.0
    atr: Optional[float] = None
    atr_multiple: Optional[float] = None
    previous_trend: str = "NEUTRAL"
    new_trend: str = "NEUTRAL"
    prior_liquidity_swept: bool = False
    displacement_confirmed: bool = False
    break_classification: str = "CONTINUATION_BOS"  # 'INITIAL_ESTABLISHMENT' | 'CONTINUATION_BOS' | 'REVERSAL_CHOCH'
    protected_level: Optional[float] = None
    protected_swing_id: Optional[str] = None
    linked_event_id: Optional[str] = None
    invalidation_reason: Optional[str] = None

    @field_validator("broken_swing_time", "break_candle_time", mode="before")
    def validate_tz(cls, v: Any) -> datetime:
        return _ensure_timezone_aware(v)


class MarketStructureEvent(BaseModel):
    """
    Domain model for a confirmed Market Structure break (BOS, CHoCH, MSS).
    Provides seamless .to_ict_event() conversion to the canonical 17-field contract.
    """
    event_id: str
    index: str
    event_type: ICTEventType
    direction: EventDirection
    timeframe: str
    broken_level: float
    event_status: LiquidityLifecycleState = LiquidityLifecycleState.CONFIRMED
    event_time: datetime
    available_at: datetime
    created_at: datetime
    confirmed_at: Optional[datetime] = None
    invalidated_at: Optional[datetime] = None
    source_candle_identifiers: List[str] = Field(default_factory=list)
    data_quality: str = "VERIFIED_LIVE"
    evidence: MarketStructureEvidence
    configuration_version: str = "3.2.0"
    engine_version: str = "3.2.0"

    @property
    def symbol(self) -> str:
        return self.index

    @property
    def lifecycle_state(self) -> LiquidityLifecycleState:
        return self.event_status

    @property
    def source_data_quality(self) -> str:
        return self.data_quality

    @property
    def model_version(self) -> str:
        return self.engine_version

    @property
    def sweep_details(self) -> Dict[str, Any]:
        return self.evidence.model_dump()

    def to_ict_event(self) -> ICTEvent:
        return ICTEvent(
            event_id=self.event_id,
            index=self.index,
            event_type=self.event_type,
            direction=self.direction,
            timeframe=self.timeframe,
            price_level=self.broken_level,
            event_status=self.event_status,
            event_time=self.event_time,
            available_at=self.available_at,
            created_at=self.created_at,
            confirmed_at=self.confirmed_at or self.available_at,
            invalidated_at=self.invalidated_at,
            source_candle_identifiers=self.source_candle_identifiers,
            data_quality=self.data_quality,
            evidence=self.evidence.model_dump(),
            configuration_version=self.configuration_version,
            engine_version=self.engine_version,
        )


class MarketStructureConfiguration(BaseModel):
    """
    Configuration parameters governing swing detection and structural break classification.
    Notice: Default displacement thresholds (body ratio 0.50, ATR multiple 1.0) are
    uncalibrated structural baseline filters provided for deterministic research and testing.
    They do not represent an empirically validated trading edge or financial advice.
    """
    configuration_version: str = "3.2.0"
    engine_version: str = "3.2.0"
    research_disclaimer: str = (
        "Default displacement thresholds (body ratio 0.50, ATR multiple 1.0) are uncalibrated "
        "research baseline parameters for rule testing and do not represent an empirical trading edge."
    )

    # Swing detection configuration
    swing_left_bars: int = Field(default=3, ge=1)
    swing_right_bars: int = Field(default=3, ge=1)
    tie_breaking_policy: str = "FIRST"  # 'FIRST' | 'LAST' | 'ALLOW_MULTI' | 'STRICT'

    # Break confirmation configuration
    require_candle_close: bool = True
    equal_tolerance_pct: float = Field(default=0.0005, ge=0.0)

    # Market Structure Shift (MSS) displacement parameters
    mss_require_displacement: bool = True
    mss_min_body_ratio: float = Field(default=0.50, ge=0.0, le=1.0)
    mss_min_atr_multiple: float = Field(default=1.0, ge=0.0)
    mss_require_prior_sweep: bool = False

    # Event lifecycle & invalidation configuration
    enable_invalidation_tracking: bool = True
    invalidation_reclose_threshold_pts: float = Field(default=0.0, ge=0.0)

    # Lookback & memory bounds
    lookback_candles: int = Field(default=300, ge=10)

    @field_validator("tie_breaking_policy")
    def validate_tie_breaking_policy(cls, v: str) -> str:
        valid_policies = {"FIRST", "LAST", "ALLOW_MULTI", "STRICT"}
        clean = str(v).upper().strip()
        if clean not in valid_policies:
            raise ValueError(f"Invalid tie_breaking_policy '{v}'. Permitted values: {valid_policies}")
        return clean


# =====================================================================
# Phase 3 Step 3.3: Order Block Models & Configuration
# =====================================================================

class OrderBlockBoundaryType(str, Enum):
    FULL_RANGE = "FULL_RANGE"  # High to Low
    BODY_ONLY = "BODY_ONLY"    # Candle Open to Close body range


class OriginCandleSelectionPolicy(str, Enum):
    LAST_CANDLE = "LAST_CANDLE"                 # Last opposing candle before impulse expansion
    EXTREME_CANDLE = "EXTREME_CANDLE"           # Candle containing absolute extreme high/low of swing
    CONSECUTIVE_CLUSTER = "CONSECUTIVE_CLUSTER" # Aggregate cluster of consecutive opposing candles


class OrderBlockEvidence(BaseModel):
    """
    Explainable evidence and geometric characteristics of a confirmed Order Block.
    """
    zone_high: float = Field(..., description="Upper price boundary of the Order Block zone")
    zone_low: float = Field(..., description="Lower price boundary of the Order Block zone")
    mean_threshold: float = Field(..., description="Consequent encroachment / 50% midpoint of the zone")
    body_high: float = Field(..., description="Upper boundary of the candle body")
    body_low: float = Field(..., description="Lower boundary of the candle body")
    boundary_type: str = Field(default="FULL_RANGE", description="Boundary policy: FULL_RANGE | BODY_ONLY")
    origin_candle_id: str = Field(..., description="Identifier of the origin candle")
    origin_candle_time: datetime = Field(..., description="Timestamp of the origin candle")
    origin_candle_open: float = Field(..., description="Open price of the origin candle")
    origin_candle_high: float = Field(..., description="High price of the origin candle")
    origin_candle_low: float = Field(..., description="Low price of the origin candle")
    origin_candle_close: float = Field(..., description="Close price of the origin candle")
    displacement_candle_id: str = Field(default="", description="Identifier of the candle providing displacement confirmation (distinct from origin)")
    displacement_leg_candle_count: int = Field(default=1, ge=1, description="Number of candles in the displacement leg")
    source_structure_event_id: str = Field(..., description="Deterministic event ID of the confirming BOS/CHoCH/MSS")
    source_structure_type: str = Field(..., description="Type of confirming structure: BOS | CHOCH | MSS")
    displacement_body_ratio: float = Field(default=0.0, description="Body-to-range ratio of confirming displacement")
    displacement_atr_multiple: float = Field(default=0.0, description="Displacement range in ATR multiples")
    mitigation_percentage: float = Field(default=0.0, ge=0.0, le=100.0, description="Depth percentage penetrated into zone (0-100%)")
    mitigated_at: Optional[datetime] = Field(default=None, description="Timestamp when mitigation occurred")
    invalidation_condition: str = Field(..., description="Exact price condition that causes invalidation")
    invalidation_reason: Optional[str] = Field(default=None, description="Causal justification if invalidated")
    touch_count: int = Field(default=0, ge=0, description="Number of touches/tests into the zone")
    selection_policy: str = Field(default="LAST_CANDLE", description="Selection rule used to isolate origin candle")
    opposing_candle_count: int = Field(default=1, ge=1, description="Number of opposing candles in the origin base")


ORDER_BLOCK_ACTIVE_STATES: Set[LiquidityLifecycleState] = {
    LiquidityLifecycleState.CONFIRMED,
    LiquidityLifecycleState.APPROACHING,
    LiquidityLifecycleState.PARTIALLY_MITIGATED,
}


class OrderBlockEvent(BaseModel):
    """
    Point-in-time Order Block event strictly convertible to canonical 17-field ICTEvent.
    """
    event_id: str
    index: str = "NIFTY 50"
    event_type: ICTEventType = ICTEventType.ORDER_BLOCK
    direction: EventDirection
    timeframe: str = "15m"
    zone_high: float
    zone_low: float
    mean_threshold: float
    event_status: LiquidityLifecycleState = LiquidityLifecycleState.CONFIRMED
    event_time: datetime
    available_at: datetime
    created_at: datetime
    confirmed_at: Optional[datetime] = None
    invalidated_at: Optional[datetime] = None
    source_candle_identifiers: List[str] = Field(default_factory=list)
    data_quality: str = "VERIFIED_LIVE"
    evidence: OrderBlockEvidence
    configuration_version: str = "3.3.0"
    engine_version: str = "3.3.0"

    @property
    def is_active(self) -> bool:
        """
        Returns True if the order block is active and resting for retests.
        Maps the semantic category 'ACTIVE' strictly to non-terminal states
        {CONFIRMED, APPROACHING, PARTIALLY_MITIGATED} without mutating canonical serialization.
        """
        return self.event_status in ORDER_BLOCK_ACTIVE_STATES

    def to_ict_event(self) -> ICTEvent:
        # price_level is entry threshold: zone_high for BULLISH, zone_low for BEARISH
        entry_price = self.zone_high if self.direction == EventDirection.BULLISH else self.zone_low
        return ICTEvent(
            event_id=self.event_id,
            index=self.index.upper().strip(),
            event_type=ICTEventType.ORDER_BLOCK,
            direction=self.direction,
            timeframe=self.timeframe.lower().strip(),
            price_level=entry_price,
            event_status=self.event_status,
            event_time=self.event_time,
            available_at=self.available_at,
            created_at=self.created_at,
            confirmed_at=self.confirmed_at,
            invalidated_at=self.invalidated_at,
            source_candle_identifiers=self.source_candle_identifiers,
            data_quality=self.data_quality,
            evidence=self.evidence.model_dump(),
            configuration_version=self.configuration_version,
            engine_version=self.engine_version,
        )


class OrderBlockConfiguration(BaseModel):
    """
    Configuration parameters governing Order Block detection, displacement validation,
    zone boundaries, deduplication, and lifecycle mitigation.
    """
    configuration_version: str = "3.3.0"
    engine_version: str = "3.3.0"
    research_disclaimer: str = (
        "Default Order Block detection and mitigation thresholds are uncalibrated "
        "research baseline parameters for rule testing and do not represent an empirical trading edge."
    )

    boundary_type: str = "FULL_RANGE"               # 'FULL_RANGE' | 'BODY_ONLY'
    selection_policy: str = "LAST_CANDLE"           # 'LAST_CANDLE' | 'EXTREME_CANDLE' | 'CONSECUTIVE_CLUSTER'
    swing_left_bars: int = Field(default=2, ge=1)
    swing_right_bars: int = Field(default=2, ge=1)
    require_displacement: bool = True
    min_displacement_body_ratio: float = Field(default=0.50, ge=0.0, le=1.0)
    min_displacement_atr_multiple: float = Field(default=1.0, ge=0.0)
    atr_period: int = Field(default=14, ge=2)
    allow_multi_candle_displacement: bool = Field(default=True)

    # Approach threshold: fraction beyond zone edge to qualify as APPROACHING (e.g., 0.001 = 0.1%)
    approach_threshold_pct: float = Field(default=0.001, ge=0.0)
    approach_retreat_mult: float = Field(default=1.5, ge=1.0)

    # Mitigation configuration
    full_mitigation_threshold_pct: float = Field(default=100.0, ge=10.0, le=100.0)
    full_mitigation_requires_mean_threshold: bool = False

    # Invalidation configuration
    enable_invalidation_tracking: bool = True
    invalidation_buffer_pts: float = Field(default=0.0, ge=0.0)

    # Expiry & overlap deduplication
    max_active_candles: int = Field(default=300, ge=1)
    max_zone_overlap_pct: float = Field(default=0.80, ge=0.0, le=1.0)
    overlap_dedup_policy: str = "KEEP_FIRST"        # 'KEEP_FIRST' | 'KEEP_NEWEST' | 'MERGE'

    # Lookback
    lookback_candles: int = Field(default=300, ge=10)

    @field_validator("boundary_type")
    def validate_boundary_type(cls, v: str) -> str:
        clean = str(v).upper().strip()
        if clean not in {"FULL_RANGE", "BODY_ONLY"}:
            raise ValueError(f"Invalid boundary_type '{v}'. Permitted: FULL_RANGE, BODY_ONLY")
        return clean

    @field_validator("selection_policy")
    def validate_selection_policy(cls, v: str) -> str:
        clean = str(v).upper().strip()
        if clean not in {"LAST_CANDLE", "EXTREME_CANDLE", "CONSECUTIVE_CLUSTER"}:
            raise ValueError(f"Invalid selection_policy '{v}'. Permitted: LAST_CANDLE, EXTREME_CANDLE, CONSECUTIVE_CLUSTER")
        return clean


# =====================================================================
# Phase 3 Step 3.4 — Fair Value Gap (FVG) & Inverse Fair Value Gap (IFVG) Models
# =====================================================================

class FVGEvidence(BaseModel):
    """
    Explainable evidence and quantitative characteristics of a confirmed FVG or IFVG.
    Stores parent-child linkage, displacement evidence, and retest metrics.
    """
    candle_1_id: str = Field(..., description="Identifier of origin boundary candle C1")
    candle_2_id: str = Field(..., description="Identifier of impulse expansion candle C2")
    candle_3_id: str = Field(..., description="Identifier of confirmation boundary candle C3")
    gap_size_pts: float = Field(..., description="Absolute point spread of the gap (zone_high - zone_low)")
    gap_atr_multiple: Optional[float] = Field(default=None, description="Gap height in multiples of ATR(14) at confirmation")
    atr_status: str = Field(default="COMPUTED", description="Status of ATR evaluation: COMPUTED | SKIPPED_CONFIGURED_ZERO | UNAVAILABLE")
    consequent_encroachment: float = Field(..., description="50% midpoint / Consequent Encroachment level")
    displacement_body_ratio: float = Field(default=0.0, description="Body-to-range ratio of impulse candle C2")
    mitigation_percentage: float = Field(default=0.0, ge=0.0, le=100.0, description="Cumulative high-water penetration percentage (0-100%)")
    mitigated_at: Optional[datetime] = Field(default=None, description="Timestamp when mitigation threshold was traversed")
    invalidation_condition: str = Field(..., description="Exact price condition that causes invalidation")
    invalidation_reason: Optional[str] = Field(default=None, description="Causal justification if invalidated or inverted")
    touch_count: int = Field(default=0, ge=0, description="Cumulative count of price tests into the zone")
    is_inverted: bool = Field(default=False, description="True if this gap has experienced role-reversal into an IFVG")
    source_fvg_id: Optional[str] = Field(default=None, description="Deterministic event ID of parent FVG for IFVGs")
    inversion_candle_id: Optional[str] = Field(default=None, description="Identifier of candle causing inversion")
    inversion_close: Optional[float] = Field(default=None, description="Close price of the candle that triggered inversion")
    inversion_time: Optional[datetime] = Field(default=None, description="Timestamp of the candle that triggered inversion")


FVG_ACTIVE_STATES: Set[LiquidityLifecycleState] = {
    LiquidityLifecycleState.CONFIRMED,
    LiquidityLifecycleState.APPROACHING,
    LiquidityLifecycleState.PARTIALLY_MITIGATED,
}

VALID_FVG_TRANSITIONS: Dict[LiquidityLifecycleState, Set[LiquidityLifecycleState]] = {
    LiquidityLifecycleState.IDENTIFIED: {
        LiquidityLifecycleState.CONFIRMED,
        LiquidityLifecycleState.INVALIDATED,
        LiquidityLifecycleState.EXPIRED,
    },
    LiquidityLifecycleState.CONFIRMED: {
        LiquidityLifecycleState.APPROACHING,
        LiquidityLifecycleState.PARTIALLY_MITIGATED,
        LiquidityLifecycleState.MITIGATED,
        LiquidityLifecycleState.INVALIDATED,
        LiquidityLifecycleState.EXPIRED,
    },
    LiquidityLifecycleState.APPROACHING: {
        LiquidityLifecycleState.CONFIRMED,  # Retreat/reset away from zone
        LiquidityLifecycleState.PARTIALLY_MITIGATED,
        LiquidityLifecycleState.MITIGATED,
        LiquidityLifecycleState.INVALIDATED,
        LiquidityLifecycleState.EXPIRED,
    },
    LiquidityLifecycleState.PARTIALLY_MITIGATED: {
        LiquidityLifecycleState.MITIGATED,
        LiquidityLifecycleState.INVALIDATED,
        LiquidityLifecycleState.EXPIRED,
    },
    # Terminal absorbing states: cannot transition back to active states
    LiquidityLifecycleState.MITIGATED: set(),
    LiquidityLifecycleState.INVALIDATED: set(),
    LiquidityLifecycleState.EXPIRED: set(),
    LiquidityLifecycleState.CONSUMED: set(),
}

VALID_IFVG_TRANSITIONS: Dict[LiquidityLifecycleState, Set[LiquidityLifecycleState]] = {
    LiquidityLifecycleState.CONFIRMED: {
        LiquidityLifecycleState.APPROACHING,
        LiquidityLifecycleState.PARTIALLY_MITIGATED,
        LiquidityLifecycleState.MITIGATED,
        LiquidityLifecycleState.INVALIDATED,
        LiquidityLifecycleState.EXPIRED,
    },
    LiquidityLifecycleState.APPROACHING: {
        LiquidityLifecycleState.CONFIRMED,  # Retreat/reset
        LiquidityLifecycleState.PARTIALLY_MITIGATED,
        LiquidityLifecycleState.MITIGATED,
        LiquidityLifecycleState.INVALIDATED,
        LiquidityLifecycleState.EXPIRED,
    },
    LiquidityLifecycleState.PARTIALLY_MITIGATED: {
        LiquidityLifecycleState.MITIGATED,
        LiquidityLifecycleState.INVALIDATED,
        LiquidityLifecycleState.EXPIRED,
    },
    # Terminal absorbing states: single inversion guarantee (no secondary inversion)
    LiquidityLifecycleState.MITIGATED: set(),
    LiquidityLifecycleState.INVALIDATED: set(),
    LiquidityLifecycleState.EXPIRED: set(),
    LiquidityLifecycleState.CONSUMED: set(),
}


def validate_fvg_transition(
    current_state: LiquidityLifecycleState,
    target_state: LiquidityLifecycleState,
) -> bool:
    """Checks whether the transition between FVG lifecycle states is mathematically valid."""
    allowed = VALID_FVG_TRANSITIONS.get(current_state, set())
    return target_state in allowed


def validate_ifvg_transition(
    current_state: LiquidityLifecycleState,
    target_state: LiquidityLifecycleState,
) -> bool:
    """Checks whether the transition between IFVG lifecycle states is mathematically valid."""
    allowed = VALID_IFVG_TRANSITIONS.get(current_state, set())
    return target_state in allowed


def canonicalize_value(val: Any) -> Any:
    """
    Deterministically normalizes a configuration value for canonical serialization:
    - None -> None (maps to JSON null)
    - bool -> bool (preserves True/False, checked before int)
    - int -> int (checked before float)
    - float -> checks finite (rejects NaN, Inf), normalizes -0.0 to 0.0, preserves exact IEEE-754 precision
    - str -> stripped string
    - dict / Mapping -> sorted key-value pairs recursively normalized
    - list / tuple -> elements recursively normalized
    - BaseModel -> model_dump() recursively normalized
    """
    if val is None:
        return None
    if isinstance(val, bool):
        return val
    if isinstance(val, int):
        return val
    if isinstance(val, float):
        if math.isnan(val) or math.isinf(val):
            raise ValueError(f"Non-finite float '{val}' is not permitted in canonical configuration fingerprint")
        if val == 0.0:
            return 0.0
        return val
    if isinstance(val, str):
        return val.strip()
    if isinstance(val, dict):
        return {str(k).strip(): canonicalize_value(v) for k, v in sorted(val.items(), key=lambda item: str(item[0]))}
    if isinstance(val, (list, tuple)):
        return [canonicalize_value(x) for x in val]
    if isinstance(val, BaseModel):
        return canonicalize_value(val.model_dump())
    return str(val).strip()


def compute_configuration_fingerprint(config: Union["FVGConfiguration", Dict[str, Any]]) -> str:
    """
    Computes a deterministic, collision-resistant 64-hexadecimal SHA-256 configuration
    fingerprint from canonically serialized active detection parameters.

    Serialization Standard:
    Uses AIVOLVE Custom Deterministic Canonical JSON format.
    Note on RFC 8785: Python json.dumps() with sort_keys=True and compact separators does
    NOT strictly conform to full RFC 8785 (JCS), as RFC 8785 mandates ECMA-262 number-to-string
    formatting and merges integer 1 with float 1.0. AIVOLVE deliberately uses this custom
    deterministic format to preserve semantic type distinctions (bool vs int vs float).

    Preserves all meaningful IEEE-754 floating-point precision without artificial truncation.
    Applies strict canonical normalization:
    - Normalizes IEEE-754 negative zero (-0.0) to positive zero (0.0).
    - Preserves boolean types distinctly from integers (True/False vs 1/0).
    - Preserves null/None distinctly.
    - Preserves arbitrary precision of floats and integers.
    - Rejects non-finite floats (NaN, +Inf, -Inf).
    - Recursively canonicalizes nested dictionaries with lexicographically sorted keys.
    - Serializes via compact deterministic JSON (sort_keys=True, separators=(',', ':')).
    - Computes full 64-character SHA-256 digest.

    Note: Cryptographic hashes are collision-resistant, not mathematically collision-proof.
    """
    if isinstance(config, dict):
        canonical_dict = canonicalize_value(config)
    elif hasattr(config, "configuration_version"):
        active_dict = {
            "approach_retreat_mult": config.approach_retreat_mult,
            "approach_threshold_pct": config.approach_threshold_pct,
            "approach_threshold_pts": config.approach_threshold_pts,
            "atr_period": config.atr_period,
            "configuration_version": config.configuration_version,
            "deduplication_policy": config.deduplication_policy.upper().strip(),
            "enable_ifvg_conversion": config.enable_ifvg_conversion,
            "full_mitigation_policy": config.full_mitigation_policy.upper().strip(),
            "invalidation_buffer_pts": config.invalidation_buffer_pts,
            "lookback_candles": config.lookback_candles,
            "max_active_candles": config.max_active_candles,
            "min_displacement_body_ratio": config.min_displacement_body_ratio,
            "min_gap_atr_multiple": config.min_gap_atr_multiple,
            "min_gap_size_pts": config.min_gap_size_pts,
        }
        canonical_dict = canonicalize_value(active_dict)
    else:
        canonical_dict = canonicalize_value(config)

    canonical_json = json.dumps(canonical_dict, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def generate_deterministic_fvg_event_id(
    index: str,
    timeframe: str,
    event_type: str,
    source_candle_id: str,
    config_fingerprint: str,
) -> str:
    """
    Generates a stable, reproducible, collision-resistant event ID incorporating the
    full 64-hex SHA-256 configuration fingerprint:
    index + timeframe + event_type + source_candle_id + config_fingerprint
    """
    raw_str = (
        f"{str(index).upper().strip()}|"
        f"{str(timeframe).lower().strip()}|"
        f"{str(event_type).upper().strip()}|"
        f"{str(source_candle_id).strip()}|"
        f"{str(config_fingerprint).strip()}"
    )
    return hashlib.sha256(raw_str.encode("utf-8")).hexdigest()


class FVGEvent(BaseModel):
    """
    Point-in-time Fair Value Gap (FVG) or Inverse FVG (IFVG) event strictly
    convertible to canonical 17-field ICTEvent envelope.
    """
    event_id: str
    index: str = "NIFTY 50"
    event_type: ICTEventType = ICTEventType.FVG
    direction: EventDirection
    timeframe: str = "15m"
    zone_high: float
    zone_low: float
    mean_threshold: float
    event_status: LiquidityLifecycleState = LiquidityLifecycleState.CONFIRMED
    event_time: datetime
    available_at: datetime
    created_at: datetime
    confirmed_at: Optional[datetime] = None
    invalidated_at: Optional[datetime] = None
    source_candle_identifiers: List[str] = Field(default_factory=list)
    data_quality: str = "VERIFIED_LIVE"
    evidence: FVGEvidence
    configuration_version: str = "3.4.0"
    engine_version: str = "3.4.0"

    @property
    def is_active(self) -> bool:
        """
        Returns True if the gap is active and resting for retests.
        Maps the semantic category 'ACTIVE' strictly to non-terminal states
        {CONFIRMED, APPROACHING, PARTIALLY_MITIGATED} without mutating canonical serialization.
        """
        return self.event_status in FVG_ACTIVE_STATES

    def to_ict_event(self) -> ICTEvent:
        # For Bullish FVG: primary entry price is upper boundary zone_high (retested from above)
        # For Bearish FVG: primary entry price is lower boundary zone_low (retested from below)
        # For Bullish IFVG: primary entry price is zone_high (retested from above)
        # For Bearish IFVG: primary entry price is zone_low (retested from below)
        entry_price = self.zone_high if self.direction == EventDirection.BULLISH else self.zone_low
        return ICTEvent(
            event_id=self.event_id,
            index=self.index.upper().strip(),
            event_type=self.event_type,
            direction=self.direction,
            timeframe=self.timeframe.lower().strip(),
            price_level=entry_price,
            zone_high=self.zone_high,
            zone_low=self.zone_low,
            event_status=self.event_status,
            event_time=self.event_time,
            available_at=self.available_at,
            created_at=self.created_at,
            confirmed_at=self.confirmed_at,
            invalidated_at=self.invalidated_at,
            source_candle_identifiers=self.source_candle_identifiers,
            data_quality=self.data_quality,
            evidence=self.evidence.model_dump(),
            configuration_version=self.configuration_version,
            engine_version=self.engine_version,
        )


class FVGConfiguration(BaseModel):
    """
    Configuration parameters governing FVG detection, directional displacement validation,
    consequent encroachment, inversion into IFVG, and lifecycle tracking.
    """
    configuration_version: str = "3.4.0"
    engine_version: str = "3.4.0"
    research_disclaimer: str = (
        "Default FVG detection and mitigation thresholds are uncalibrated "
        "research baseline parameters for rule testing and do not represent an empirical trading edge."
    )

    min_gap_size_pts: float = Field(default=0.0, ge=0.0)
    min_gap_atr_multiple: float = Field(default=0.10, ge=0.0)
    atr_period: int = Field(default=14, ge=2)
    min_displacement_body_ratio: float = Field(default=0.50, ge=0.0, le=1.0)
    full_mitigation_policy: str = "CONSEQUENT_ENCROACHMENT"  # 'CONSEQUENT_ENCROACHMENT' | 'FULL_FILL'
    enable_ifvg_conversion: bool = True

    # Approach threshold: hybrid pts + pct
    approach_threshold_pct: float = Field(default=0.001, ge=0.0)
    approach_threshold_pts: float = Field(default=2.0, ge=0.0)
    approach_retreat_mult: float = Field(default=1.5, ge=1.0)

    # Invalidation configuration
    invalidation_buffer_pts: float = Field(default=0.0, ge=0.0)

    # Expiry & deduplication
    max_active_candles: int = Field(default=300, ge=1)
    deduplication_policy: str = "KEEP_ALL"
    lookback_candles: int = Field(default=300, ge=10)

    @field_validator("full_mitigation_policy")
    def validate_mitigation_policy(cls, v: str) -> str:
        clean = str(v).upper().strip()
        if clean not in {"CONSEQUENT_ENCROACHMENT", "FULL_FILL"}:
            raise ValueError(f"Invalid full_mitigation_policy '{v}'. Permitted: CONSEQUENT_ENCROACHMENT, FULL_FILL")
        return clean

    @field_validator("deduplication_policy")
    def validate_dedup_policy(cls, v: str) -> str:
        clean = str(v).upper().strip()
        if clean not in {"KEEP_ALL", "KEEP_FIRST", "KEEP_NEWEST"}:
            raise ValueError(f"Invalid deduplication_policy '{v}'. Permitted: KEEP_ALL, KEEP_FIRST, KEEP_NEWEST")
        return clean

    def get_fingerprint(self) -> str:
        """Returns the full 64-hex SHA-256 configuration fingerprint."""
        return compute_configuration_fingerprint(self)


