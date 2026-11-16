"""
AIVOLVE Institutional Quantitative Trading Intelligence v3.0
Phase 3 Step 3.6 — Session Intelligence Engine.

Deterministic, rule-based Indian market session intelligence engine operating strictly
in the `Asia/Kolkata` timezone under `PAPER_TRADING_ONLY` governance.

Provides:
1. Configurable Indian Market Session Windows (initial research defaults):
   - Opening:   09:15 - 09:45 IST
   - Morning:   09:45 - 11:30 IST
   - Midday:    11:30 - 13:30 IST
   - Afternoon: 13:30 - 14:45 IST
   - Closing:   14:45 - 15:30 IST
2. Session classification from completed candle timestamps (with half-open [start, end) boundaries).
3. Configurable Opening Range (OR) tracking: creation, strict post-completion availability,
   breakout above ORH, breakdown below ORL, and post-break retest observations.
4. Session High/Low & Previous Session High/Low tracking: session range, range expansion,
   and breach/reclaim observations with source candle IDs preserved.
5. Deterministic causal Session Transitions (Opening -> Morning -> Midday -> Afternoon -> Closing).
6. Time-Based Liquidity Observations integrating Step 3.1 `LiquidityPool` and `LiquidityEvent`
   without duplicating or redefining Step 3.1 liquidity logic.
7. Configurable Research Kill Zone windows (research observation only; zero scoring weights,
   zero profitability claims).
8. Deterministic point-in-time `historical_replay` and multi-timeframe synchronization.

Strict Governance & Safety Guarantees:
- Executed strictly in `PAPER_TRADING_ONLY` mode; never triggers `BUY_CE` or `BUY_PE`.
- ICT Confluence Score remains `UNAVAILABLE` / `NOT_CALIBRATED` until separately approved.
- Completed candles only; forming, incomplete, missing-flag, repaired, degraded, stale, mock,
  or synthetic data fail closed.
- Missing candle intervals are explicitly surfaced in diagnostics and NEVER backfilled.
- MarketCalendar uncertainty (missing/empty/out-of-coverage holiday schedule, invalid date,
  weekends, holidays) fails closed.
- SENSEX remains blocked unless explicitly authorized via `sensex_governance_approved=True`.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date, datetime, time as dt_time, timedelta
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple
from zoneinfo import ZoneInfo

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.data import market_calendar as market_calendar_module
from app.data.market_calendar import MarketCalendar
from app.data.quality_validator import DataQualityEngine, FeedStatus
from app.options.ict_smc.ict_models import (
    EventDirection,
    ICTEvent,
    ICTEventType,
    LiquidityEvent,
    LiquidityLifecycleState,
    LiquidityPool,
    LiquidityType,
    canonicalize_value,
)


# ============================================================================
# Constants & Canonical Enumerations
# ============================================================================

ENGINE_VERSION: str = "3.6.0"
DEFAULT_CONFIGURATION_VERSION: str = "3.6.0"
EXECUTION_MODE: str = "PAPER_TRADING_ONLY"
DEFAULT_TIMEZONE_NAME: str = "Asia/Kolkata"
IST_ZONE: ZoneInfo = ZoneInfo(DEFAULT_TIMEZONE_NAME)

TIMEFRAME_MINUTES: Dict[str, int] = {
    "1m": 1,
    "3m": 3,
    "5m": 5,
    "10m": 10,
    "15m": 15,
    "30m": 30,
    "1h": 60,
}

TIMEFRAME_ALIASES: Dict[str, str] = {
    "1m": "1m",
    "3m": "3m",
    "5m": "5m",
    "10m": "10m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1h",
    "60m": "1h",
}

CANONICAL_INDEX_MAP: Dict[str, str] = {
    "NIFTY": "NIFTY 50",
    "NIFTY50": "NIFTY 50",
    "NIFTY 50": "NIFTY 50",
    "BANKNIFTY": "BANK NIFTY",
    "BANK NIFTY": "BANK NIFTY",
    "NIFTY BANK": "BANK NIFTY",
    "FINNIFTY": "FINNIFTY",
    "NIFTY FIN SERVICE": "FINNIFTY",
    "SENSEX": "SENSEX",
    "BSE SENSEX": "SENSEX",
}

DEFAULT_APPROVED_INDICES: Set[str] = {"NIFTY 50", "BANK NIFTY", "FINNIFTY"}

VALID_FEED_STATUSES: Set[str] = {
    FeedStatus.VERIFIED_LIVE.value if hasattr(FeedStatus.VERIFIED_LIVE, "value") else "VERIFIED_LIVE",
    FeedStatus.VERIFIED_EOD.value if hasattr(FeedStatus.VERIFIED_EOD, "value") else "VERIFIED_EOD",
    "VERIFIED_LIVE",
    "VERIFIED_EOD",
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
    "CALENDAR_UNAVAILABLE",
    "INVALID_DATA",
}

HHMM_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


class SessionPhaseStatus(str, Enum):
    """Status of a market session or session window at `as_of_time`."""

    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CLOSED = "CLOSED"
    PRE_OPEN = "PRE_OPEN"
    POST_CLOSE = "POST_CLOSE"
    UNAVAILABLE = "UNAVAILABLE"
    NON_TRADING_DAY = "NON_TRADING_DAY"


class OpeningRangeStatus(str, Enum):
    """Lifecycle status of the Opening Range tracking state."""

    NOT_STARTED = "NOT_STARTED"
    FORMING = "FORMING"
    COMPLETE = "COMPLETE"
    UNAVAILABLE = "UNAVAILABLE"


class SessionEventKind(str, Enum):
    """Specific Step 3.6 session event subtypes mapped cleanly to canonical ICTEvent."""

    OPENING_RANGE_COMPLETE = "OPENING_RANGE_COMPLETE"
    OPENING_RANGE_BREAKOUT = "OPENING_RANGE_BREAKOUT"
    OPENING_RANGE_BREAKDOWN = "OPENING_RANGE_BREAKDOWN"
    OPENING_RANGE_RETEST = "OPENING_RANGE_RETEST"
    SESSION_HIGH_UPDATE = "SESSION_HIGH_UPDATE"
    SESSION_LOW_UPDATE = "SESSION_LOW_UPDATE"
    SESSION_HIGH_BREACH = "SESSION_HIGH_BREACH"
    SESSION_HIGH_RECLAIM = "SESSION_HIGH_RECLAIM"
    SESSION_LOW_BREACH = "SESSION_LOW_BREACH"
    SESSION_LOW_RECLAIM = "SESSION_LOW_BRECLAIM"
    SESSION_TRANSITION = "SESSION_TRANSITION"
    SESSION_LIQUIDITY_OBSERVATION = "SESSION_LIQUIDITY_OBSERVATION"


# ============================================================================
# Strict Validation, Canonical Hashing & Timezone Helpers
# ============================================================================

def _require_exact_str(val: Any, field_name: str) -> str:
    """Enforces exact built-in `str` to block custom subclass overrides."""
    if type(val) is not str:
        raise TypeError(f"{field_name} must be an exact built-in str, got {type(val).__name__}")
    stripped = val.strip()
    if not stripped:
        raise ValueError(f"{field_name} cannot be empty or whitespace")
    return stripped


def _require_finite_float(val: Any, field_name: str) -> float:
    """Enforces numeric finite float while rejecting booleans and custom classes."""
    if type(val) is bool or not isinstance(val, (int, float)):
        raise TypeError(f"{field_name} must be a numeric int/float (not bool), got {type(val).__name__}")
    fval = float(val)
    if not math.isfinite(fval):
        raise ValueError(f"{field_name} must be finite, got {val}")
    return fval


def _parse_hhmm(hhmm: str, field_name: str) -> dt_time:
    """Validates and parses strict 24-hour HH:MM strings."""
    clean = _require_exact_str(hhmm, field_name)
    if not HHMM_PATTERN.match(clean):
        raise ValueError(f"{field_name} must be valid HH:MM 24h format, got '{hhmm}'")
    hour, minute = clean.split(":")
    return dt_time(int(hour), int(minute))


def _time_to_minutes(t: dt_time) -> int:
    return t.hour * 60 + t.minute


def is_valid_tz_aware_datetime(dt: Any) -> bool:
    """Returns True only when `dt` is a datetime with a non-None UTC offset."""
    if not isinstance(dt, datetime):
        return False
    if dt.tzinfo is None:
        return False
    try:
        offset = dt.tzinfo.utcoffset(dt)
    except Exception:
        return False
    return offset is not None


def _convert_to_tz(dt: Any, tz: ZoneInfo, field_name: str = "timestamp") -> datetime:
    """Validates timezone-awareness strictly and converts to target ZoneInfo."""
    if isinstance(dt, pd.Timestamp):
        if pd.isna(dt):
            raise ValueError(f"{field_name} is NaT")
        dt = dt.to_pydatetime()
    if not is_valid_tz_aware_datetime(dt):
        raise ValueError(f"{field_name} must be a valid timezone-aware datetime, got {dt!r}")
    return dt.astimezone(tz)


def normalize_index_symbol(symbol: Any) -> str:
    """Normalizes known Indian index names cleanly without accepting unsupported assets."""
    clean = _require_exact_str(symbol, "symbol").upper()
    collapsed = " ".join(clean.split())
    if collapsed not in CANONICAL_INDEX_MAP:
        raise ValueError(
            f"Unsupported index '{symbol}'. Permitted indices: NIFTY 50, BANK NIFTY, FINNIFTY, SENSEX (subject to governance)"
        )
    return CANONICAL_INDEX_MAP[collapsed]


def normalize_timeframe(timeframe: Any) -> str:
    """Validates and canonicalizes supported intraday session timeframes."""
    clean = _require_exact_str(timeframe, "timeframe").lower()
    if clean not in TIMEFRAME_ALIASES:
        raise ValueError(
            f"Unsupported session timeframe '{timeframe}'. Supported timeframes: {sorted(TIMEFRAME_MINUTES.keys())}"
        )
    return TIMEFRAME_ALIASES[clean]


def normalize_feed_status(status: Any) -> str:
    """Safely converts FeedStatus enums or strings into canonical uppercase string."""
    if isinstance(status, Enum):
        raw = status.value
    else:
        raw = status
    if type(raw) is not str:
        return "UNKNOWN"
    return raw.strip().upper()


def compute_candle_close_ist(bar_open_tz: datetime, timeframe: str, market_close_time: dt_time) -> datetime:
    """
    Computes exact candle close timestamp in session timezone with NSE/BSE session close capping.
    Matches P0 live-data reliability rules for 15:15 (30m/1h) and 15:25 (10m) session boundaries.
    """
    tf = normalize_timeframe(timeframe)
    minutes = TIMEFRAME_MINUTES[tf]
    bar_end = bar_open_tz + timedelta(minutes=minutes)
    session_close_dt = datetime.combine(bar_open_tz.date(), market_close_time, tzinfo=bar_open_tz.tzinfo)
    if (
        bar_open_tz <= session_close_dt
        and bar_end > session_close_dt
        and (
            (bar_open_tz.hour == 15 and bar_open_tz.minute == 15 and minutes in (30, 60))
            or (bar_open_tz.hour == 15 and bar_open_tz.minute == 25 and minutes == 10)
        )
    ):
        return session_close_dt
    return bar_end


def generate_deterministic_session_id(
    index: str,
    timeframe: str,
    event_kind: str,
    trading_date: str,
    qualifier: str,
    configuration_fingerprint: str,
    engine_version: str = ENGINE_VERSION,
) -> str:
    """Generates a reproducible SHA-256 prefixed event/observation ID."""
    payload = "|".join([
        index,
        timeframe,
        event_kind,
        trading_date,
        qualifier,
        configuration_fingerprint,
        engine_version,
    ])
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20].upper()
    return f"SES-{digest}"


def _strict_bool_completion_flag(val: Any) -> Optional[bool]:
    """
    Strict P0 completion flag coercion.
    Returns `True` only when explicitly verified completed, `False` when explicitly forming/false,
    and `None` when missing/NaN/unrecognized so callers can fail closed.
    """
    if val is None:
        return None
    if isinstance(val, float) and math.isnan(val):
        return None
    if pd.isna(val):
        return None
    if type(val) is bool:
        return val
    if type(val) is int:
        if val == 1:
            return True
        if val == 0:
            return False
        return None
    if type(val) is str:
        norm = val.strip().lower()
        if norm in ("true", "1", "yes", "closed", "complete"):
            return True
        if norm in ("false", "0", "no", "open", "forming", ""):
            return False
        return None
    return None


# ============================================================================
# Configuration Models (Section 3 & 4F)
# ============================================================================

class SessionWindowConfig(BaseModel):
    """Configurable intraday market session window."""

    model_config = ConfigDict(frozen=True)

    session_id: str
    session_name: str
    start_time: str
    end_time: str
    sequence_order: int = Field(ge=0)
    research_hypothesis: str = (
        "Configurable Indian market session research window; not a calibrated trading edge."
    )

    @model_validator(mode="after")
    def _validate_window(self) -> "SessionWindowConfig":
        _require_exact_str(self.session_id, "session_id")
        _require_exact_str(self.session_name, "session_name")
        start_t = _parse_hhmm(self.start_time, "start_time")
        end_t = _parse_hhmm(self.end_time, "end_time")
        if _time_to_minutes(start_t) >= _time_to_minutes(end_t):
            raise ValueError(
                f"SessionWindowConfig '{self.session_id}': start_time ({self.start_time}) "
                f"must be strictly before end_time ({self.end_time})"
            )
        return self


class KillZoneConfig(BaseModel):
    """Configurable Kill Zone window for research observation only."""

    model_config = ConfigDict(frozen=True)

    kill_zone_id: str
    kill_zone_name: str
    start_time: str
    end_time: str
    research_only: bool = True
    is_proven_edge: bool = False
    scoring_weight: Optional[float] = None
    description: str = (
        "Research observation window only; does not indicate profitability or trigger signals."
    )

    @model_validator(mode="after")
    def _validate_kill_zone(self) -> "KillZoneConfig":
        _require_exact_str(self.kill_zone_id, "kill_zone_id")
        _require_exact_str(self.kill_zone_name, "kill_zone_name")
        start_t = _parse_hhmm(self.start_time, "start_time")
        end_t = _parse_hhmm(self.end_time, "end_time")
        if _time_to_minutes(start_t) >= _time_to_minutes(end_t):
            raise ValueError(
                f"KillZoneConfig '{self.kill_zone_id}': start_time ({self.start_time}) "
                f"must be strictly before end_time ({self.end_time})"
            )
        if not self.research_only:
            raise ValueError("KillZoneConfig must remain research_only=True")
        if self.is_proven_edge:
            raise ValueError("KillZoneConfig cannot claim is_proven_edge=True")
        if self.scoring_weight is not None:
            raise ValueError("Unapproved KillZoneConfig scoring_weight is prohibited in Step 3.6")
        return self


def default_indian_session_windows() -> Tuple[SessionWindowConfig, ...]:
    """Returns initial Step 3.6 research session windows in IST."""
    return (
        SessionWindowConfig(
            session_id="OPENING",
            session_name="Opening",
            start_time="09:15",
            end_time="09:45",
            sequence_order=0,
        ),
        SessionWindowConfig(
            session_id="MORNING",
            session_name="Morning",
            start_time="09:45",
            end_time="11:30",
            sequence_order=1,
        ),
        SessionWindowConfig(
            session_id="MIDDAY",
            session_name="Midday",
            start_time="11:30",
            end_time="13:30",
            sequence_order=2,
        ),
        SessionWindowConfig(
            session_id="AFTERNOON",
            session_name="Afternoon",
            start_time="13:30",
            end_time="14:45",
            sequence_order=3,
        ),
        SessionWindowConfig(
            session_id="CLOSING",
            session_name="Closing",
            start_time="14:45",
            end_time="15:30",
            sequence_order=4,
        ),
    )


def default_research_kill_zones() -> Tuple[KillZoneConfig, ...]:
    """Returns initial configurable Kill Zone research windows (hypothesis observation only)."""
    return (
        KillZoneConfig(
            kill_zone_id="KZ_OPENING_DISCOVERY",
            kill_zone_name="Opening Volatility Window",
            start_time="09:15",
            end_time="09:45",
        ),
        KillZoneConfig(
            kill_zone_id="KZ_MORNING_SESSION",
            kill_zone_name="Morning Liquidity Observation Window",
            start_time="09:45",
            end_time="11:00",
        ),
        KillZoneConfig(
            kill_zone_id="KZ_CLOSING_SQUAREOFF",
            kill_zone_name="Closing Session Observation Window",
            start_time="14:15",
            end_time="15:30",
        ),
    )


class SessionConfiguration(BaseModel):
    """
    Complete versioned configuration for Step 3.6 Session Intelligence Engine.
    All session windows, opening range durations, and kill zones are configurable hypotheses.
    """

    model_config = ConfigDict(frozen=True)

    configuration_version: str = DEFAULT_CONFIGURATION_VERSION
    timezone_name: str = DEFAULT_TIMEZONE_NAME
    market_open: str = "09:15"
    market_close: str = "15:30"
    session_windows: Tuple[SessionWindowConfig, ...] = Field(
        default_factory=default_indian_session_windows
    )
    opening_range_start: str = "09:15"
    opening_range_duration_minutes: int = Field(default=30, ge=1, le=375)
    kill_zones: Tuple[KillZoneConfig, ...] = Field(
        default_factory=default_research_kill_zones
    )
    or_breakout_requires_close: bool = True
    breakout_min_penetration_pts: float = Field(default=0.0, ge=0.0)
    retest_tolerance_pts: float = Field(default=2.0, ge=0.0)
    breach_penetration_min_pts: float = Field(default=0.0, ge=0.0)
    require_explicit_completion_flag: bool = False
    sensex_governance_approved: bool = False
    execution_mode: str = EXECUTION_MODE

    @model_validator(mode="after")
    def _validate_configuration(self) -> "SessionConfiguration":
        _require_exact_str(self.configuration_version, "configuration_version")
        tz_clean = _require_exact_str(self.timezone_name, "timezone_name")
        try:
            ZoneInfo(tz_clean)
        except Exception as exc:
            raise ValueError(f"Invalid timezone_name '{self.timezone_name}': {exc}") from exc

        if self.execution_mode != EXECUTION_MODE:
            raise ValueError(f"execution_mode must be '{EXECUTION_MODE}', got '{self.execution_mode}'")

        open_t = _parse_hhmm(self.market_open, "market_open")
        close_t = _parse_hhmm(self.market_close, "market_close")
        open_m = _time_to_minutes(open_t)
        close_m = _time_to_minutes(close_t)
        if open_m >= close_m:
            raise ValueError("market_open must be strictly before market_close")

        if not self.session_windows:
            raise ValueError("session_windows cannot be empty")

        seen_ids: Set[str] = set()
        seen_names: Set[str] = set()
        prev_end_m: Optional[int] = None
        prev_order: Optional[int] = None

        for win in self.session_windows:
            sid = win.session_id.upper()
            sname = win.session_name.lower()
            if sid in seen_ids:
                raise ValueError(f"Duplicate session_id '{win.session_id}' in session_windows")
            if sname in seen_names:
                raise ValueError(f"Duplicate session_name '{win.session_name}' in session_windows")
            seen_ids.add(sid)
            seen_names.add(sname)

            w_start_m = _time_to_minutes(_parse_hhmm(win.start_time, "window.start_time"))
            w_end_m = _time_to_minutes(_parse_hhmm(win.end_time, "window.end_time"))
            if w_start_m < open_m or w_end_m > close_m:
                raise ValueError(
                    f"Session '{win.session_id}' [{win.start_time}, {win.end_time}] exceeds "
                    f"market bounds [{self.market_open}, {self.market_close}]"
                )
            if prev_end_m is not None and w_start_m < prev_end_m:
                raise ValueError(
                    f"Overlapping or unsorted session window '{win.session_id}' starting at {win.start_time}"
                )
            if prev_order is not None and win.sequence_order <= prev_order:
                raise ValueError(
                    f"Session window '{win.session_id}' sequence_order must be strictly increasing"
                )
            prev_end_m = w_end_m
            prev_order = win.sequence_order

        or_start_t = _parse_hhmm(self.opening_range_start, "opening_range_start")
        or_start_m = _time_to_minutes(or_start_t)
        or_end_m = or_start_m + self.opening_range_duration_minutes
        if or_start_m < open_m or or_end_m > close_m:
            raise ValueError(
                f"Opening range [{self.opening_range_start} + {self.opening_range_duration_minutes}m] "
                f"exceeds configured market hours [{self.market_open}, {self.market_close}]"
            )

        seen_kz: Set[str] = set()
        prev_kz_end_m: Optional[int] = None
        for kz in self.kill_zones:
            kid = kz.kill_zone_id.upper()
            if kid in seen_kz:
                raise ValueError(f"Duplicate kill_zone_id '{kz.kill_zone_id}'")
            seen_kz.add(kid)
            k_start_m = _time_to_minutes(_parse_hhmm(kz.start_time, "kz.start_time"))
            k_end_m = _time_to_minutes(_parse_hhmm(kz.end_time, "kz.end_time"))
            if k_start_m < open_m or k_end_m > close_m:
                raise ValueError(
                    f"KillZone '{kz.kill_zone_id}' [{kz.start_time}, {kz.end_time}] exceeds market bounds"
                )
            if prev_kz_end_m is not None and k_start_m < prev_kz_end_m:
                raise ValueError(
                    f"Overlapping or unsorted KillZone '{kz.kill_zone_id}' starting at {kz.start_time}"
                )
            prev_kz_end_m = k_end_m

        return self

    def get_zone_info(self) -> ZoneInfo:
        return ZoneInfo(self.timezone_name)

    def configuration_fingerprint(self) -> str:
        """Returns deterministic SHA-256 fingerprint of this immutable configuration."""
        canonical = canonicalize_value(self.model_dump())
        encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24].upper()


# ============================================================================
# Output & Domain Event Models (Sections 4 & 5)
# ============================================================================

class MissingCandleInterval(BaseModel):
    """Explicit record of a missing expected completed candle interval (never interpolated)."""

    model_config = ConfigDict(frozen=True)

    expected_open_time: datetime
    expected_close_time: datetime
    timeframe: str
    session_id: Optional[str] = None
    session_name: Optional[str] = None
    reason: str = "MISSING_COMPLETED_CANDLE"


class SessionClassification(BaseModel):
    """Active session identification from completed candle timestamps (Section 4A)."""

    model_config = ConfigDict(frozen=True)

    session_id: Optional[str] = None
    session_name: Optional[str] = None
    session_start: Optional[datetime] = None
    session_end: Optional[datetime] = None
    current_session_status: SessionPhaseStatus
    timeframe: str
    trading_date: str
    timezone: str = DEFAULT_TIMEZONE_NAME
    completed_candles_in_session: int = 0
    last_completed_candle_id: Optional[str] = None
    last_completed_candle_close: Optional[datetime] = None
    active_kill_zones: Tuple[str, ...] = ()


class OpeningRangeState(BaseModel):
    """Configurable Opening Range intelligence snapshot (Section 4B)."""

    model_config = ConfigDict(frozen=True)

    index: str
    timeframe: str
    trading_date: str
    timezone: str = DEFAULT_TIMEZONE_NAME
    window_start: datetime
    window_end: datetime
    duration_minutes: int
    status: OpeningRangeStatus
    is_complete: bool
    opening_range_high: Optional[float] = None
    opening_range_low: Optional[float] = None
    midpoint: Optional[float] = None
    range_pts: Optional[float] = None
    available_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    breakout_above_detected: bool = False
    breakdown_below_detected: bool = False
    retest_observed: bool = False
    retest_direction: Optional[EventDirection] = None
    breakout_time: Optional[datetime] = None
    breakdown_time: Optional[datetime] = None
    retest_time: Optional[datetime] = None
    source_candle_ids: Tuple[str, ...] = ()
    missing_or_intervals_count: int = 0


class SessionRangeTracker(BaseModel):
    """Per-session high/low, range expansion, previous session & breach/reclaim tracking (Section 4C)."""

    model_config = ConfigDict(frozen=True)

    session_id: str
    session_name: str
    trading_date: str
    timeframe: str
    timezone: str = DEFAULT_TIMEZONE_NAME
    session_start: datetime
    session_end: datetime
    status: SessionPhaseStatus
    session_high: Optional[float] = None
    session_low: Optional[float] = None
    session_range: Optional[float] = None
    initial_range: Optional[float] = None
    range_expansion_pts: float = 0.0
    range_expansion_pct: Optional[float] = None
    high_updated_count: int = 0
    low_updated_count: int = 0
    high_candle_id: Optional[str] = None
    low_candle_id: Optional[str] = None
    high_time: Optional[datetime] = None
    low_time: Optional[datetime] = None
    previous_session_id: Optional[str] = None
    previous_session_name: Optional[str] = None
    previous_session_trading_date: Optional[str] = None
    previous_session_high: Optional[float] = None
    previous_session_low: Optional[float] = None
    breached_previous_high: bool = False
    reclaimed_previous_high: bool = False
    breached_previous_low: bool = False
    reclaimed_previous_low: bool = False
    source_candle_ids: Tuple[str, ...] = ()


class SessionTransition(BaseModel):
    """Deterministic causal transition between consecutive market sessions (Section 4D)."""

    model_config = ConfigDict(frozen=True)

    transition_id: str
    index: str
    timeframe: str
    trading_date: str
    from_session_id: str
    from_session_name: str
    to_session_id: str
    to_session_name: str
    expected_boundary_time: datetime
    event_time: datetime
    available_at: datetime
    is_adjacent_standard_transition: bool
    source_candle_ids: Tuple[str, ...]


class SessionLiquidityObservation(BaseModel):
    """Session-contextualized liquidity observation referencing Step 3.1 objects (Section 4E)."""

    model_config = ConfigDict(frozen=True)

    observation_id: str
    index: str
    timeframe: str
    session_id: Optional[str] = None
    session_name: Optional[str] = None
    observation_type: str
    referenced_pool_id: Optional[str] = None
    referenced_event_id: Optional[str] = None
    liquidity_type: Optional[LiquidityType] = None
    direction: EventDirection = EventDirection.NEUTRAL
    price_level: float
    event_time: datetime
    available_at: datetime
    source_candle_ids: Tuple[str, ...] = ()
    evidence: Dict[str, Any] = Field(default_factory=dict)


class KillZoneObservation(BaseModel):
    """Research-only Kill Zone observation summary (Section 4F)."""

    model_config = ConfigDict(frozen=True)

    kill_zone_id: str
    kill_zone_name: str
    window_start: datetime
    window_end: datetime
    is_active: bool
    completed_candles_count: int
    observed_high: Optional[float] = None
    observed_low: Optional[float] = None
    research_only: bool = True
    is_proven_edge: bool = False
    scoring_weight: Optional[float] = None


class SessionEvent(BaseModel):
    """
    Phase 3 Step 3.6 Session Intelligence Event following the canonical 17-field contract.
    Convertible directly to canonical `ICTEvent` without modifying frozen Step 3.1 contracts.
    """

    model_config = ConfigDict(frozen=True)

    event_id: str
    index: str
    event_type: ICTEventType
    session_event_kind: SessionEventKind
    direction: EventDirection
    timeframe: str
    price_level: Optional[float] = None
    zone_high: Optional[float] = None
    zone_low: Optional[float] = None
    event_status: LiquidityLifecycleState = LiquidityLifecycleState.IDENTIFIED
    event_time: datetime
    available_at: datetime
    created_at: datetime
    confirmed_at: Optional[datetime] = None
    invalidated_at: Optional[datetime] = None
    source_candle_ids: List[str] = Field(default_factory=list)
    data_quality: str = "VERIFIED_LIVE"
    evidence: Dict[str, Any] = Field(default_factory=dict)
    configuration_version: str = DEFAULT_CONFIGURATION_VERSION
    engine_version: str = ENGINE_VERSION

    @model_validator(mode="after")
    def _validate_causality(self) -> "SessionEvent":
        if not is_valid_tz_aware_datetime(self.event_time):
            raise ValueError("event_time must be timezone-aware")
        if not is_valid_tz_aware_datetime(self.available_at):
            raise ValueError("available_at must be timezone-aware")
        if not is_valid_tz_aware_datetime(self.created_at):
            raise ValueError("created_at must be timezone-aware")
        if self.available_at < self.event_time:
            raise ValueError("No-lookahead violation: available_at cannot precede event_time")
        if self.confirmed_at is not None:
            if not is_valid_tz_aware_datetime(self.confirmed_at):
                raise ValueError("confirmed_at must be timezone-aware")
            if self.confirmed_at < self.available_at:
                raise ValueError("No-lookahead violation: confirmed_at cannot precede available_at")
        if self.zone_high is not None and self.zone_low is not None and self.zone_high < self.zone_low:
            raise ValueError("zone_high cannot be less than zone_low")
        return self

    def to_ict_event(self) -> ICTEvent:
        """Converts typed Step 3.6 SessionEvent into canonical Phase 3 `ICTEvent`."""
        merged_evidence = dict(self.evidence)
        merged_evidence["session_event_kind"] = self.session_event_kind.value
        merged_evidence["execution_mode"] = EXECUTION_MODE
        return ICTEvent(
            event_id=self.event_id,
            index=self.index,
            event_type=self.event_type,
            direction=self.direction,
            timeframe=self.timeframe,
            price_level=self.price_level,
            zone_high=self.zone_high,
            zone_low=self.zone_low,
            event_status=self.event_status,
            event_time=self.event_time,
            available_at=self.available_at,
            created_at=self.created_at,
            confirmed_at=self.confirmed_at,
            invalidated_at=self.invalidated_at,
            source_candle_identifiers=list(self.source_candle_ids),
            data_quality=self.data_quality,
            evidence=merged_evidence,
            configuration_version=self.configuration_version,
            engine_version=self.engine_version,
        )


class TimeframeSessionReport(BaseModel):
    """Complete deterministic session intelligence report for one index & timeframe."""

    model_config = ConfigDict(frozen=True)

    index: str
    timeframe: str
    trading_date: str
    timezone: str = DEFAULT_TIMEZONE_NAME
    as_of_time: datetime
    data_quality: str
    is_valid: bool
    rejection_reasons: Tuple[str, ...] = ()
    execution_mode: str = EXECUTION_MODE
    confluence_score: Optional[float] = None
    score_status: str = "UNAVAILABLE"
    calibration_status: str = "NOT_CALIBRATED"
    current_session: Optional[SessionClassification] = None
    opening_range: Optional[OpeningRangeState] = None
    session_ranges: Dict[str, SessionRangeTracker] = Field(default_factory=dict)
    previous_session_summary: Optional[SessionRangeTracker] = None
    transitions: Tuple[SessionTransition, ...] = ()
    liquidity_observations: Tuple[SessionLiquidityObservation, ...] = ()
    kill_zone_observations: Tuple[KillZoneObservation, ...] = ()
    events: Tuple[SessionEvent, ...] = ()
    ict_events: Tuple[ICTEvent, ...] = ()
    completed_candles_count: int = 0
    incomplete_candles_excluded: int = 0
    future_candles_excluded: int = 0
    missing_intervals: Tuple[MissingCandleInterval, ...] = ()
    has_data_gaps: bool = False
    configuration_version: str = DEFAULT_CONFIGURATION_VERSION
    configuration_fingerprint: str
    engine_version: str = ENGINE_VERSION


class MultiTimeframeSessionSummary(BaseModel):
    """Multi-timeframe session synchronization report (scores strictly UNAVAILABLE)."""

    model_config = ConfigDict(frozen=True)

    index: str
    trading_date: str
    timezone: str = DEFAULT_TIMEZONE_NAME
    as_of_time: datetime
    data_quality: str
    is_valid: bool
    rejection_reasons: Tuple[str, ...] = ()
    timeframe_reports: Dict[str, TimeframeSessionReport] = Field(default_factory=dict)
    synchronized_active_session_id: Optional[str] = None
    synchronized_active_session_name: Optional[str] = None
    timeframe_session_agreement: bool = False
    all_events: Tuple[SessionEvent, ...] = ()
    ict_confluence_score: Optional[float] = None
    score_status: str = "UNAVAILABLE"
    calibration_status: str = "NOT_CALIBRATED"
    execution_mode: str = EXECUTION_MODE
    configuration_version: str = DEFAULT_CONFIGURATION_VERSION
    engine_version: str = ENGINE_VERSION


# ============================================================================
# Internal Validated Candle Representation
# ============================================================================

class _ValidatedBar:
    """Lightweight immutable internal bar after strict OHLC, timezone, and completion checks."""

    __slots__ = (
        "candle_id",
        "open_time",
        "close_time",
        "open",
        "high",
        "low",
        "close",
        "session",
    )

    def __init__(
        self,
        candle_id: str,
        open_time: datetime,
        close_time: datetime,
        open_p: float,
        high_p: float,
        low_p: float,
        close_p: float,
        session: Optional[SessionWindowConfig],
    ) -> None:
        self.candle_id = candle_id
        self.open_time = open_time
        self.close_time = close_time
        self.open = open_p
        self.high = high_p
        self.low = low_p
        self.close = close_p
        self.session = session


# ============================================================================
# Step 3.6 Session Intelligence Engine
# ============================================================================

class SessionIntelligenceEngine:
    """
    Deterministic Rule-Based Indian Market Session Intelligence Engine (Phase 3 Step 3.6).
    """

    def __init__(
        self,
        config: Optional[SessionConfiguration] = None,
        calendar: Optional[Any] = None,
    ) -> None:
        self.config = config or SessionConfiguration()
        self.calendar = calendar if calendar is not None else MarketCalendar
        self.tz = self.config.get_zone_info()
        self.config_fingerprint = self.config.configuration_fingerprint()
        self.market_open_time = _parse_hhmm(self.config.market_open, "market_open")
        self.market_close_time = _parse_hhmm(self.config.market_close, "market_close")

    # ------------------------------------------------------------------
    # Public Window Classification & Calendar Helpers
    # ------------------------------------------------------------------

    def classify_timestamp(self, timestamp: datetime) -> Optional[SessionWindowConfig]:
        """
        Deterministically maps a timezone-aware timestamp to its non-overlapping
        configured session window using half-open `[start, end)` intervals in Asia/Kolkata.
        """
        ts_tz = _convert_to_tz(timestamp, self.tz, "timestamp")
        bar_t = ts_tz.time().replace(second=0, microsecond=0) if (
            ts_tz.second == 0 and ts_tz.microsecond == 0
        ) else ts_tz.time()

        for win in self.config.session_windows:
            start_t = _parse_hhmm(win.start_time, "start_time")
            end_t = _parse_hhmm(win.end_time, "end_time")
            if start_t <= bar_t < end_t:
                return win
        return None

    def _window_datetimes(
        self,
        trading_date: date,
        start_hhmm: str,
        end_hhmm: str,
    ) -> Tuple[datetime, datetime]:
        st = _parse_hhmm(start_hhmm, "start_hhmm")
        et = _parse_hhmm(end_hhmm, "end_hhmm")
        return (
            datetime.combine(trading_date, st, tzinfo=self.tz),
            datetime.combine(trading_date, et, tzinfo=self.tz),
        )

    def _opening_range_bounds(self, trading_date: date) -> Tuple[datetime, datetime]:
        or_start_t = _parse_hhmm(self.config.opening_range_start, "opening_range_start")
        or_start_dt = datetime.combine(trading_date, or_start_t, tzinfo=self.tz)
        or_end_dt = or_start_dt + timedelta(minutes=self.config.opening_range_duration_minutes)
        return or_start_dt, or_end_dt

    def _validate_trading_calendar(
        self,
        target_date: date,
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Fail-closed MarketCalendar check:
        - Rejects weekends (Saturday/Sunday) as NON_TRADING_DAY.
        - Fails closed as CALENDAR_UNAVAILABLE when MarketCalendar lacks holiday schedule
          coverage for `target_date.year` or throws / returns invalid results.
        - Rejects exchange holidays as NON_TRADING_DAY.
        """
        if self.calendar is None:
            return False, "CALENDAR_UNAVAILABLE", "MarketCalendar provider is None (fail-closed)"

        # Explicit weekend check first
        if target_date.weekday() >= 5:
            return False, "NON_TRADING_DAY", f"Non-trading day: weekend ({target_date.isoformat()})"

        holidays = getattr(self.calendar, "NSE_HOLIDAYS", None)
        if holidays is None and self.calendar is MarketCalendar:
            holidays = getattr(market_calendar_module, "NSE_HOLIDAYS", None)
        if not isinstance(holidays, (set, frozenset, list, tuple)) or len(holidays) == 0:
            return (
                False,
                "CALENDAR_UNAVAILABLE",
                "Trading calendar holiday dataset is unavailable or empty (fail-closed)",
            )

        try:
            covered_years = {d.year for d in holidays if isinstance(d, date)}
        except Exception as exc:
            return (
                False,
                "CALENDAR_UNAVAILABLE",
                f"Trading calendar holiday dataset unreadable: {exc}",
            )

        if target_date.year not in covered_years:
            return (
                False,
                "CALENDAR_UNAVAILABLE",
                f"Trading calendar holiday schedule unavailable for year {target_date.year} (fail-closed)",
            )

        is_td_fn = getattr(self.calendar, "is_trading_day", None)
        if not callable(is_td_fn):
            return False, "CALENDAR_UNAVAILABLE", "MarketCalendar.is_trading_day is missing or uncallable"

        probe_dt = datetime.combine(target_date, dt_time(12, 0), tzinfo=self.tz)
        try:
            res = is_td_fn(probe_dt)
        except Exception as exc:
            return False, "CALENDAR_UNAVAILABLE", f"MarketCalendar check failed: {exc}"

        if type(res) is not bool:
            return False, "CALENDAR_UNAVAILABLE", f"MarketCalendar returned non-boolean status: {res!r}"

        if not res:
            return False, "NON_TRADING_DAY", f"Non-trading exchange holiday ({target_date.isoformat()})"

        return True, None, None

    # ------------------------------------------------------------------
    # Input Data Quality, Candle Filtering & Missing Interval Checks
    # ------------------------------------------------------------------

    def _validate_feed_and_dataframe(
        self,
        df: Any,
        timeframe: str,
        data_quality_status: Any,
        index_norm: str,
    ) -> Tuple[List[str], str]:
        """Performs strict Phase 1/2/3 fail-closed data-quality, OHLC, and timestamp checks."""
        reasons: List[str] = []

        if not self.config.sensex_governance_approved and index_norm == "SENSEX":
            reasons.append(
                "GOVERNANCE_LOCKOUT: SENSEX session intelligence requires explicit governance approval"
            )
            return reasons, "GOVERNANCE_LOCKOUT"

        df_attrs = df.attrs if (isinstance(df, pd.DataFrame) and hasattr(df, "attrs") and isinstance(df.attrs, dict)) else {}
        attr_status = df_attrs.get("data_status") or df_attrs.get("feed_status") or df_attrs.get("dataStatus")
        eff_status = normalize_feed_status(attr_status if attr_status is not None else data_quality_status)

        if eff_status in DISQUALIFYING_FEED_STATUSES or eff_status not in VALID_FEED_STATUSES:
            reasons.append(f"Phase 1/2 Data Quality lockout: non-qualifying feed status '{eff_status}'")

        if df_attrs.get("is_mock") is True or df_attrs.get("isMock") is True:
            reasons.append("Mock market data rejected (no synthetic fallback permitted)")
        if df_attrs.get("is_synthetic") is True or df_attrs.get("isSynthetic") is True:
            reasons.append("Synthetic market data rejected")
        if df_attrs.get("ohlc_repaired") is True:
            reasons.append("Phase 1/2 Data Quality lockout: ohlc_repaired=True dataset rejected")
        if df_attrs.get("missing_mandatory_candles") is True:
            reasons.append("Phase 1/2 Data Quality lockout: missing_mandatory_candles=True")

        if df is None:
            reasons.append("Candlestick DataFrame is None")
            return reasons, eff_status if eff_status in DISQUALIFYING_FEED_STATUSES else "DATA_UNAVAILABLE"

        if not isinstance(df, pd.DataFrame):
            reasons.append(f"Candlestick dataset must be pandas.DataFrame, got {type(df).__name__}")
            return reasons, "INVALID_DATA"

        if df.empty:
            reasons.append("Candlestick DataFrame is empty")
            return reasons, eff_status

        required_cols = {"timestamp", "open", "high", "low", "close"}
        if not required_cols.issubset(set(df.columns)):
            missing = sorted(required_cols - set(df.columns))
            reasons.append(f"Missing mandatory OHLCV columns: {missing}")
            return reasons, "INVALID_DATA"

        # Validate Phase 1/2 DataQualityEngine OHLC audit first
        val_res = DataQualityEngine.validate_ohlc(df, timeframe=timeframe)
        if not val_res.get("isValid", True):
            reasons.extend([f"Phase 1/2 OHLC violation: {v}" for v in val_res.get("violations", [])])
        if val_res.get("ohlc_repaired", False):
            reasons.append("Phase 1/2 OHLC lockout: candles required repair")

        # Strict element-level geometric & type verification
        o_vals = pd.to_numeric(df["open"], errors="coerce")
        h_vals = pd.to_numeric(df["high"], errors="coerce")
        l_vals = pd.to_numeric(df["low"], errors="coerce")
        c_vals = pd.to_numeric(df["close"], errors="coerce")

        for col_name, series in (("open", o_vals), ("high", h_vals), ("low", l_vals), ("close", c_vals)):
            if series.isna().any() or not series.map(math.isfinite).all():
                reasons.append(f"Non-finite or NaN values detected in column '{col_name}'")
            if (series <= 0).any():
                reasons.append(f"Non-positive prices detected in column '{col_name}'")

        if not reasons:
            max_oc = pd.concat([o_vals, c_vals], axis=1).max(axis=1)
            min_oc = pd.concat([o_vals, c_vals], axis=1).min(axis=1)
            if (h_vals < l_vals).any():
                reasons.append("Invalid OHLC geometry: high < low detected")
            if (h_vals < max_oc).any():
                reasons.append("Invalid OHLC geometry: high < max(open, close) detected")
            if (l_vals > min_oc).any():
                reasons.append("Invalid OHLC geometry: low > min(open, close) detected")

        # Strict timestamp verification (timezone-aware, monotonic, no duplicates)
        ts_col = df["timestamp"]
        if ts_col.isna().any():
            reasons.append("Null or NaN timestamps detected in candlestick series")
        else:
            parsed_utc_instants: List[datetime] = []
            tz_sigs: Set[str] = set()
            for raw_ts in ts_col:
                try:
                    dt_obj = raw_ts
                    if type(raw_ts) is str:
                        dt_obj = pd.to_datetime(raw_ts)
                    converted = _convert_to_tz(dt_obj, self.tz, "candle.timestamp")
                    if isinstance(dt_obj, (datetime, pd.Timestamp)) and dt_obj.tzinfo is not None:
                        sig = str(dt_obj.tzinfo)
                    else:
                        sig = str(converted.tzinfo)
                    tz_sigs.add(sig)
                    parsed_utc_instants.append(converted)
                except Exception as exc:
                    reasons.append(f"Malformed or naive candle timestamp '{raw_ts!r}': {exc}")
                    break

            if parsed_utc_instants and len(parsed_utc_instants) == len(ts_col):
                if len(tz_sigs) > 1:
                    reasons.append(f"Mixed timezones detected across candle timestamps: {sorted(tz_sigs)}")
                seen_ts: Set[datetime] = set()
                prev_ts: Optional[datetime] = None
                for ts_item in parsed_utc_instants:
                    if ts_item in seen_ts:
                        reasons.append(f"Duplicate candle timestamp detected: {ts_item.isoformat()}")
                        break
                    if prev_ts is not None and ts_item <= prev_ts:
                        reasons.append("Candle timestamps must be strictly monotonically increasing")
                        break
                    seen_ts.add(ts_item)
                    prev_ts = ts_item

        if "candle_id" in df.columns:
            ids = [str(v) for v in df["candle_id"]]
            if len(ids) != len(set(ids)):
                reasons.append("Duplicate candle_id values detected in dataset")

        out_status = "INVALID_DATA" if (reasons and eff_status in VALID_FEED_STATUSES) else eff_status
        return reasons, out_status

    def _extract_completed_bars(
        self,
        df: pd.DataFrame,
        timeframe: str,
        as_of_tz: datetime,
    ) -> Tuple[List[_ValidatedBar], int, int]:
        """
        Filters strictly completed, non-forming, non-future candles as of `as_of_tz`.
        Returns `(completed_bars, incomplete_candles_excluded, future_candles_excluded)`.
        """
        has_is_complete = "is_complete" in df.columns
        has_is_closed = "is_closed" in df.columns
        has_any_flag_col = has_is_complete or has_is_closed

        completed: List[_ValidatedBar] = []
        incomplete_excluded = 0
        future_excluded = 0

        for idx, row in df.iterrows():
            raw_ts = row["timestamp"]
            dt_obj = pd.to_datetime(raw_ts) if type(raw_ts) is str else raw_ts
            open_tz = _convert_to_tz(dt_obj, self.tz, "candle.timestamp")
            close_tz = compute_candle_close_ist(open_tz, timeframe, self.market_close_time)

            # Future lookahead exclusion relative to as_of_tz
            if open_tz > as_of_tz:
                future_excluded += 1
                continue

            if close_tz > as_of_tz:
                # Bar started on/before as_of_tz but closes in future -> live forming bar
                incomplete_excluded += 1
                continue

            # Explicit completion flags when required or present
            if has_any_flag_col:
                c_flag = _strict_bool_completion_flag(row["is_complete"]) if has_is_complete else None
                cl_flag = _strict_bool_completion_flag(row["is_closed"]) if has_is_closed else None

                # Fail closed on explicit False, None/NaN when column present, or conflicting flags
                if has_is_complete and c_flag is not True:
                    incomplete_excluded += 1
                    continue
                if has_is_closed and cl_flag is not True:
                    incomplete_excluded += 1
                    continue
            elif self.config.require_explicit_completion_flag:
                incomplete_excluded += 1
                continue

            candle_id = str(row["candle_id"]) if "candle_id" in df.columns else f"c_{open_tz.strftime('%Y%m%d_%H%M%S')}"
            session_win = self.classify_timestamp(open_tz)
            completed.append(
                _ValidatedBar(
                    candle_id=candle_id,
                    open_time=open_tz,
                    close_time=close_tz,
                    open_p=float(row["open"]),
                    high_p=float(row["high"]),
                    low_p=float(row["low"]),
                    close_p=float(row["close"]),
                    session=session_win,
                )
            )

        return completed, incomplete_excluded, future_excluded

    def _detect_missing_intervals(
        self,
        bars: Sequence[_ValidatedBar],
        timeframe: str,
        target_date: date,
        as_of_tz: datetime,
    ) -> List[MissingCandleInterval]:
        """
        Identifies missing expected intraday candle intervals on `target_date` up to
        `min(as_of_tz, market_close)` without fabricating or backfilling any candles.
        """
        step = timedelta(minutes=TIMEFRAME_MINUTES[timeframe])
        day_open = datetime.combine(target_date, self.market_open_time, tzinfo=self.tz)
        day_close = datetime.combine(target_date, self.market_close_time, tzinfo=self.tz)
        horizon = min(as_of_tz, day_close)

        if not bars:
            if horizon < day_open + step and horizon < day_close:
                return []
            # If market has progressed past first candle close and zero bars exist
            missing: List[MissingCandleInterval] = []
            cursor = day_open
            while cursor < day_close:
                expected_close = compute_candle_close_ist(cursor, timeframe, self.market_close_time)
                if expected_close > horizon:
                    break
                win = self.classify_timestamp(cursor)
                missing.append(
                    MissingCandleInterval(
                        expected_open_time=cursor,
                        expected_close_time=expected_close,
                        timeframe=timeframe,
                        session_id=win.session_id if win else None,
                        session_name=win.session_name if win else None,
                    )
                )
                cursor += step
            return missing

        observed_opens: Set[datetime] = {b.open_time for b in bars}
        start_cursor = day_open
        missing_list: List[MissingCandleInterval] = []
        cursor = start_cursor
        while cursor < day_close:
            expected_close = compute_candle_close_ist(cursor, timeframe, self.market_close_time)
            if expected_close > horizon:
                break
            if cursor not in observed_opens:
                win = self.classify_timestamp(cursor)
                missing_list.append(
                    MissingCandleInterval(
                        expected_open_time=cursor,
                        expected_close_time=expected_close,
                        timeframe=timeframe,
                        session_id=win.session_id if win else None,
                        session_name=win.session_name if win else None,
                    )
                )
            cursor += step
        return missing_list

    # ------------------------------------------------------------------
    # Step 3.6 Event Factory & Deduplication Helpers
    # ------------------------------------------------------------------

    def _emit_event(
        self,
        events: List[SessionEvent],
        seen_keys: Set[Tuple[str, str]],
        *,
        index_norm: str,
        timeframe: str,
        trading_date_str: str,
        event_type: ICTEventType,
        session_event_kind: SessionEventKind,
        direction: EventDirection,
        qualifier: str,
        dedupe_key: Tuple[str, str],
        event_time: datetime,
        available_at: datetime,
        confirmed_at: Optional[datetime],
        event_status: LiquidityLifecycleState,
        source_candle_ids: Sequence[str],
        data_quality: str,
        price_level: Optional[float] = None,
        zone_high: Optional[float] = None,
        zone_low: Optional[float] = None,
        evidence: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Builds and deduplicates a Step 3.6 SessionEvent with deterministic ID."""
        if dedupe_key in seen_keys:
            return
        seen_keys.add(dedupe_key)

        eid = generate_deterministic_session_id(
            index=index_norm,
            timeframe=timeframe,
            event_kind=session_event_kind.value,
            trading_date=trading_date_str,
            qualifier=qualifier,
            configuration_fingerprint=self.config_fingerprint,
            engine_version=ENGINE_VERSION,
        )
        ev_payload = dict(evidence or {})
        ev_payload["configuration_fingerprint"] = self.config_fingerprint
        ev_payload["trading_date"] = trading_date_str
        ev_payload["timezone"] = self.config.timezone_name

        events.append(
            SessionEvent(
                event_id=eid,
                index=index_norm,
                event_type=event_type,
                session_event_kind=session_event_kind,
                direction=direction,
                timeframe=timeframe,
                price_level=price_level,
                zone_high=zone_high,
                zone_low=zone_low,
                event_status=event_status,
                event_time=event_time,
                available_at=available_at,
                created_at=available_at,
                confirmed_at=confirmed_at,
                invalidated_at=None,
                source_candle_ids=list(source_candle_ids),
                data_quality=data_quality,
                evidence=ev_payload,
                configuration_version=self.config.configuration_version,
                engine_version=ENGINE_VERSION,
            )
        )

    # ------------------------------------------------------------------
    # Component Builders (Opening Range, Session Ranges, Transitions, Liquidity, Kill Zones)
    # ------------------------------------------------------------------

    def _compute_opening_range(
        self,
        day_bars: Sequence[_ValidatedBar],
        missing_intervals: Sequence[MissingCandleInterval],
        index_norm: str,
        timeframe: str,
        trading_date: date,
        as_of_tz: datetime,
        data_quality: str,
        events: List[SessionEvent],
        seen_keys: Set[Tuple[str, str]],
    ) -> OpeningRangeState:
        trading_date_str = trading_date.isoformat()
        or_start_dt, or_end_dt = self._opening_range_bounds(trading_date)

        if as_of_tz < or_start_dt:
            return OpeningRangeState(
                index=index_norm,
                timeframe=timeframe,
                trading_date=trading_date_str,
                timezone=self.config.timezone_name,
                window_start=or_start_dt,
                window_end=or_end_dt,
                duration_minutes=self.config.opening_range_duration_minutes,
                status=OpeningRangeStatus.NOT_STARTED,
                is_complete=False,
            )

        or_bars = [
            b for b in day_bars if or_start_dt <= b.open_time < or_end_dt
        ]
        or_missing = [
            m for m in missing_intervals if or_start_dt <= m.expected_open_time < or_end_dt
        ]

        # Wait until configured OR end has arrived on completed time and >=1 OR bar completed
        has_closed_or_span = bool(or_bars) and (
            or_bars[-1].close_time >= or_end_dt or as_of_tz >= or_end_dt
        )

        # For higher timeframes whose opening bar spans past or_end_dt (e.g. 1h at 09:15 closes 10:15):
        # if as_of_tz < 10:15, or_bars is empty -> FORMING strictly without leaking levels.
        if not or_bars or not has_closed_or_span:
            status = OpeningRangeStatus.UNAVAILABLE if (as_of_tz >= or_end_dt and not or_bars) else OpeningRangeStatus.FORMING
            return OpeningRangeState(
                index=index_norm,
                timeframe=timeframe,
                trading_date=trading_date_str,
                timezone=self.config.timezone_name,
                window_start=or_start_dt,
                window_end=or_end_dt,
                duration_minutes=self.config.opening_range_duration_minutes,
                status=status,
                is_complete=False,
                source_candle_ids=tuple(b.candle_id for b in or_bars),
                missing_or_intervals_count=len(or_missing),
            )

        or_high = max(b.high for b in or_bars)
        or_low = min(b.low for b in or_bars)
        or_mid = round((or_high + or_low) / 2.0, 4)
        or_range = round(or_high - or_low, 4)
        or_source_ids = tuple(b.candle_id for b in or_bars)
        completed_at = max(or_end_dt, or_bars[-1].close_time)

        self._emit_event(
            events,
            seen_keys,
            index_norm=index_norm,
            timeframe=timeframe,
            trading_date_str=trading_date_str,
            event_type=ICTEventType.OPENING_RANGE,
            session_event_kind=SessionEventKind.OPENING_RANGE_COMPLETE,
            direction=EventDirection.NEUTRAL,
            qualifier=f"OR_COMPLETE_{or_start_dt.strftime('%H%M')}_{or_end_dt.strftime('%H%M')}",
            dedupe_key=(SessionEventKind.OPENING_RANGE_COMPLETE.value, trading_date_str),
            event_time=or_end_dt,
            available_at=completed_at,
            confirmed_at=completed_at,
            event_status=LiquidityLifecycleState.CONFIRMED,
            source_candle_ids=or_source_ids,
            data_quality=data_quality,
            price_level=or_mid,
            zone_high=or_high,
            zone_low=or_low,
            evidence={
                "opening_range_high": or_high,
                "opening_range_low": or_low,
                "midpoint": or_mid,
                "range_pts": or_range,
                "duration_minutes": self.config.opening_range_duration_minutes,
                "missing_or_intervals_count": len(or_missing),
            },
        )

        # Evaluate breakouts, breakdowns, and subsequent retests strictly on completed post-OR bars
        post_or_bars = [b for b in day_bars if b.open_time >= or_end_dt and b.close_time >= completed_at]
        breakout_detected = False
        breakdown_detected = False
        breakout_time: Optional[datetime] = None
        breakdown_time: Optional[datetime] = None
        first_break_direction: Optional[EventDirection] = None
        first_break_idx: Optional[int] = None

        retest_observed = False
        retest_direction: Optional[EventDirection] = None
        retest_time: Optional[datetime] = None

        pen = self.config.breakout_min_penetration_pts
        ret_tol = self.config.retest_tolerance_pts

        for i, bar in enumerate(post_or_bars):
            broke_up = (
                bar.close > (or_high + pen)
                if self.config.or_breakout_requires_close
                else bar.high > (or_high + pen)
            )
            broke_dn = (
                bar.close < (or_low - pen)
                if self.config.or_breakout_requires_close
                else bar.low < (or_low - pen)
            )

            if broke_up and not breakout_detected:
                breakout_detected = True
                breakout_time = bar.close_time
                if first_break_direction is None:
                    first_break_direction = EventDirection.BULLISH
                    first_break_idx = i
                self._emit_event(
                    events,
                    seen_keys,
                    index_norm=index_norm,
                    timeframe=timeframe,
                    trading_date_str=trading_date_str,
                    event_type=ICTEventType.OPENING_RANGE,
                    session_event_kind=SessionEventKind.OPENING_RANGE_BREAKOUT,
                    direction=EventDirection.BULLISH,
                    qualifier=f"OR_BREAKOUT_{bar.candle_id}",
                    dedupe_key=(SessionEventKind.OPENING_RANGE_BREAKOUT.value, trading_date_str),
                    event_time=bar.open_time,
                    available_at=bar.close_time,
                    confirmed_at=bar.close_time,
                    event_status=LiquidityLifecycleState.CONFIRMED,
                    source_candle_ids=[bar.candle_id],
                    data_quality=data_quality,
                    price_level=or_high,
                    zone_high=or_high,
                    zone_low=or_low,
                    evidence={
                        "opening_range_high": or_high,
                        "breakout_close": bar.close,
                        "penetration_pts": round(bar.close - or_high, 4),
                    },
                )

            if broke_dn and not breakdown_detected:
                breakdown_detected = True
                breakdown_time = bar.close_time
                if first_break_direction is None:
                    first_break_direction = EventDirection.BEARISH
                    first_break_idx = i
                self._emit_event(
                    events,
                    seen_keys,
                    index_norm=index_norm,
                    timeframe=timeframe,
                    trading_date_str=trading_date_str,
                    event_type=ICTEventType.OPENING_RANGE,
                    session_event_kind=SessionEventKind.OPENING_RANGE_BREAKDOWN,
                    direction=EventDirection.BEARISH,
                    qualifier=f"OR_BREAKDOWN_{bar.candle_id}",
                    dedupe_key=(SessionEventKind.OPENING_RANGE_BREAKDOWN.value, trading_date_str),
                    event_time=bar.open_time,
                    available_at=bar.close_time,
                    confirmed_at=bar.close_time,
                    event_status=LiquidityLifecycleState.CONFIRMED,
                    source_candle_ids=[bar.candle_id],
                    data_quality=data_quality,
                    price_level=or_low,
                    zone_high=or_high,
                    zone_low=or_low,
                    evidence={
                        "opening_range_low": or_low,
                        "breakdown_close": bar.close,
                        "penetration_pts": round(or_low - bar.close, 4),
                    },
                )

            # Check retest strictly AFTER an earlier breakout/breakdown bar
            if not retest_observed and first_break_idx is not None and i > first_break_idx:
                if first_break_direction == EventDirection.BULLISH:
                    if bar.low <= (or_high + ret_tol) and bar.close >= (or_high - ret_tol) and bar.high >= or_high:
                        retest_observed = True
                        retest_direction = EventDirection.BULLISH
                        retest_time = bar.close_time
                        self._emit_event(
                            events,
                            seen_keys,
                            index_norm=index_norm,
                            timeframe=timeframe,
                            trading_date_str=trading_date_str,
                            event_type=ICTEventType.OPENING_RANGE,
                            session_event_kind=SessionEventKind.OPENING_RANGE_RETEST,
                            direction=EventDirection.BULLISH,
                            qualifier=f"OR_RETEST_BULLISH_{bar.candle_id}",
                            dedupe_key=(SessionEventKind.OPENING_RANGE_RETEST.value, "BULLISH"),
                            event_time=bar.open_time,
                            available_at=bar.close_time,
                            confirmed_at=bar.close_time,
                            event_status=LiquidityLifecycleState.CONFIRMED,
                            source_candle_ids=[bar.candle_id],
                            data_quality=data_quality,
                            price_level=or_high,
                            zone_high=or_high,
                            zone_low=or_low,
                            evidence={"retested_level": or_high, "bar_low": bar.low, "bar_close": bar.close},
                        )
                elif first_break_direction == EventDirection.BEARISH:
                    if bar.high >= (or_low - ret_tol) and bar.close <= (or_low + ret_tol) and bar.low <= or_low:
                        retest_observed = True
                        retest_direction = EventDirection.BEARISH
                        retest_time = bar.close_time
                        self._emit_event(
                            events,
                            seen_keys,
                            index_norm=index_norm,
                            timeframe=timeframe,
                            trading_date_str=trading_date_str,
                            event_type=ICTEventType.OPENING_RANGE,
                            session_event_kind=SessionEventKind.OPENING_RANGE_RETEST,
                            direction=EventDirection.BEARISH,
                            qualifier=f"OR_RETEST_BEARISH_{bar.candle_id}",
                            dedupe_key=(SessionEventKind.OPENING_RANGE_RETEST.value, "BEARISH"),
                            event_time=bar.open_time,
                            available_at=bar.close_time,
                            confirmed_at=bar.close_time,
                            event_status=LiquidityLifecycleState.CONFIRMED,
                            source_candle_ids=[bar.candle_id],
                            data_quality=data_quality,
                            price_level=or_low,
                            zone_high=or_high,
                            zone_low=or_low,
                            evidence={"retested_level": or_low, "bar_high": bar.high, "bar_close": bar.close},
                        )

        return OpeningRangeState(
            index=index_norm,
            timeframe=timeframe,
            trading_date=trading_date_str,
            timezone=self.config.timezone_name,
            window_start=or_start_dt,
            window_end=or_end_dt,
            duration_minutes=self.config.opening_range_duration_minutes,
            status=OpeningRangeStatus.COMPLETE,
            is_complete=True,
            opening_range_high=or_high,
            opening_range_low=or_low,
            midpoint=or_mid,
            range_pts=or_range,
            available_at=completed_at,
            completed_at=completed_at,
            breakout_above_detected=breakout_detected,
            breakdown_below_detected=breakdown_detected,
            retest_observed=retest_observed,
            retest_direction=retest_direction,
            breakout_time=breakout_time,
            breakdown_time=breakdown_time,
            retest_time=retest_time,
            source_candle_ids=or_source_ids,
            missing_or_intervals_count=len(or_missing),
        )

    def _compute_session_ranges_and_transitions(
        self,
        day_bars: Sequence[_ValidatedBar],
        prior_day_last_session: Optional[SessionRangeTracker],
        index_norm: str,
        timeframe: str,
        trading_date: date,
        as_of_tz: datetime,
        data_quality: str,
        events: List[SessionEvent],
        seen_keys: Set[Tuple[str, str]],
    ) -> Tuple[Dict[str, SessionRangeTracker], List[SessionTransition], Optional[SessionRangeTracker]]:
        """
        Computes causal per-session high/low trackers, expansion, previous session high/low,
        breach/reclaim observations, and session transitions strictly on completed candles.
        """
        trading_date_str = trading_date.isoformat()
        bars_by_sid: Dict[str, List[_ValidatedBar]] = {w.session_id: [] for w in self.config.session_windows}
        for bar in day_bars:
            if bar.session is not None and bar.session.session_id in bars_by_sid:
                bars_by_sid[bar.session.session_id].append(bar)

        trackers: Dict[str, SessionRangeTracker] = {}
        transitions: List[SessionTransition] = []
        last_completed_session_tracker: Optional[SessionRangeTracker] = prior_day_last_session
        prev_observed_win: Optional[SessionWindowConfig] = None
        prev_observed_bars: List[_ValidatedBar] = []

        breach_pen = self.config.breach_penetration_min_pts

        for win_idx, win in enumerate(self.config.session_windows):
            s_bars = bars_by_sid[win.session_id]
            if not s_bars:
                continue

            win_start_dt, win_end_dt = self._window_datetimes(trading_date, win.start_time, win.end_time)
            has_later_session_bars = any(
                bool(bars_by_sid[later_w.session_id])
                for later_w in self.config.session_windows[win_idx + 1 :]
            )
            status = (
                SessionPhaseStatus.COMPLETED
                if (as_of_tz >= win_end_dt or has_later_session_bars)
                else SessionPhaseStatus.ACTIVE
            )

            # Causal transition from immediately preceding observed session on target trading_date
            if prev_observed_win is not None and prev_observed_bars:
                first_bar = s_bars[0]
                is_adjacent = (win.sequence_order - prev_observed_win.sequence_order) == 1
                t_id = generate_deterministic_session_id(
                    index=index_norm,
                    timeframe=timeframe,
                    event_kind=SessionEventKind.SESSION_TRANSITION.value,
                    trading_date=trading_date_str,
                    qualifier=f"{prev_observed_win.session_id}_TO_{win.session_id}_{first_bar.candle_id}",
                    configuration_fingerprint=self.config_fingerprint,
                    engine_version=ENGINE_VERSION,
                )
                src_ids = (prev_observed_bars[-1].candle_id, first_bar.candle_id)
                transitions.append(
                    SessionTransition(
                        transition_id=t_id,
                        index=index_norm,
                        timeframe=timeframe,
                        trading_date=trading_date_str,
                        from_session_id=prev_observed_win.session_id,
                        from_session_name=prev_observed_win.session_name,
                        to_session_id=win.session_id,
                        to_session_name=win.session_name,
                        expected_boundary_time=win_start_dt,
                        event_time=first_bar.open_time,
                        available_at=first_bar.close_time,
                        is_adjacent_standard_transition=is_adjacent,
                        source_candle_ids=src_ids,
                    )
                )
                self._emit_event(
                    events,
                    seen_keys,
                    index_norm=index_norm,
                    timeframe=timeframe,
                    trading_date_str=trading_date_str,
                    event_type=ICTEventType.LIQUIDITY_POOL,
                    session_event_kind=SessionEventKind.SESSION_TRANSITION,
                    direction=EventDirection.NEUTRAL,
                    qualifier=f"{prev_observed_win.session_id}_TO_{win.session_id}_{first_bar.candle_id}",
                    dedupe_key=(
                        SessionEventKind.SESSION_TRANSITION.value,
                        f"{prev_observed_win.session_id}->{win.session_id}",
                    ),
                    event_time=first_bar.open_time,
                    available_at=first_bar.close_time,
                    confirmed_at=first_bar.close_time,
                    event_status=LiquidityLifecycleState.CONFIRMED,
                    source_candle_ids=src_ids,
                    data_quality=data_quality,
                    price_level=first_bar.open,
                    evidence={
                        "from_session_id": prev_observed_win.session_id,
                        "from_session_name": prev_observed_win.session_name,
                        "to_session_id": win.session_id,
                        "to_session_name": win.session_name,
                        "expected_boundary_time": win_start_dt.isoformat(),
                        "is_adjacent_standard_transition": is_adjacent,
                    },
                )

            # High/Low & Expansion progression bar by bar (zero repaint/lookahead)
            first_b = s_bars[0]
            running_high = first_b.high
            running_low = first_b.low
            initial_range = round(running_high - running_low, 4)
            high_cid = first_b.candle_id
            low_cid = first_b.candle_id
            high_time = first_b.close_time
            low_time = first_b.close_time
            high_updates = 0
            low_updates = 0

            # Track previous session high/low breach & reclaim states
            prev_s_high = last_completed_session_tracker.session_high if last_completed_session_tracker else None
            prev_s_low = last_completed_session_tracker.session_low if last_completed_session_tracker else None
            breached_ph = False
            reclaimed_ph = False
            breached_pl = False
            reclaimed_pl = False

            for idx_b, bar in enumerate(s_bars):
                if idx_b > 0:
                    if bar.high > running_high:
                        running_high = bar.high
                        high_cid = bar.candle_id
                        high_time = bar.close_time
                        high_updates += 1
                        self._emit_event(
                            events,
                            seen_keys,
                            index_norm=index_norm,
                            timeframe=timeframe,
                            trading_date_str=trading_date_str,
                            event_type=ICTEventType.SESSION_HIGH,
                            session_event_kind=SessionEventKind.SESSION_HIGH_UPDATE,
                            direction=EventDirection.BULLISH,
                            qualifier=f"{win.session_id}_HIGH_{bar.candle_id}",
                            dedupe_key=(SessionEventKind.SESSION_HIGH_UPDATE.value, f"{win.session_id}:{bar.candle_id}"),
                            event_time=bar.open_time,
                            available_at=bar.close_time,
                            confirmed_at=bar.close_time,
                            event_status=LiquidityLifecycleState.IDENTIFIED,
                            source_candle_ids=[bar.candle_id],
                            data_quality=data_quality,
                            price_level=running_high,
                            zone_high=running_high,
                            zone_low=running_low,
                            evidence={
                                "session_id": win.session_id,
                                "session_name": win.session_name,
                                "session_high": running_high,
                            },
                        )

                    if bar.low < running_low:
                        running_low = bar.low
                        low_cid = bar.candle_id
                        low_time = bar.close_time
                        low_updates += 1
                        self._emit_event(
                            events,
                            seen_keys,
                            index_norm=index_norm,
                            timeframe=timeframe,
                            trading_date_str=trading_date_str,
                            event_type=ICTEventType.SESSION_LOW,
                            session_event_kind=SessionEventKind.SESSION_LOW_UPDATE,
                            direction=EventDirection.BEARISH,
                            qualifier=f"{win.session_id}_LOW_{bar.candle_id}",
                            dedupe_key=(SessionEventKind.SESSION_LOW_UPDATE.value, f"{win.session_id}:{bar.candle_id}"),
                            event_time=bar.open_time,
                            available_at=bar.close_time,
                            confirmed_at=bar.close_time,
                            event_status=LiquidityLifecycleState.IDENTIFIED,
                            source_candle_ids=[bar.candle_id],
                            data_quality=data_quality,
                            price_level=running_low,
                            zone_high=running_high,
                            zone_low=running_low,
                            evidence={
                                "session_id": win.session_id,
                                "session_name": win.session_name,
                                "session_low": running_low,
                            },
                        )

                # Breach & Reclaim vs Previous Completed Session High
                if prev_s_high is not None and last_completed_session_tracker is not None:
                    prev_sid = last_completed_session_tracker.session_id
                    if not breached_ph and bar.high > (prev_s_high + breach_pen):
                        breached_ph = True
                        self._emit_event(
                            events,
                            seen_keys,
                            index_norm=index_norm,
                            timeframe=timeframe,
                            trading_date_str=trading_date_str,
                            event_type=ICTEventType.SESSION_HIGH,
                            session_event_kind=SessionEventKind.SESSION_HIGH_BREACH,
                            direction=EventDirection.BULLISH if bar.close > prev_s_high else EventDirection.NEUTRAL,
                            qualifier=f"{win.session_id}_BREACH_{prev_sid}_HIGH_{bar.candle_id}",
                            dedupe_key=(SessionEventKind.SESSION_HIGH_BREACH.value, f"{win.session_id}:{prev_sid}"),
                            event_time=bar.open_time,
                            available_at=bar.close_time,
                            confirmed_at=bar.close_time,
                            event_status=LiquidityLifecycleState.SWEPT,
                            source_candle_ids=[bar.candle_id],
                            data_quality=data_quality,
                            price_level=prev_s_high,
                            evidence={
                                "current_session_id": win.session_id,
                                "previous_session_id": prev_sid,
                                "previous_session_high": prev_s_high,
                                "breach_bar_high": bar.high,
                                "breach_bar_close": bar.close,
                            },
                        )
                    if breached_ph and not reclaimed_ph and bar.close < prev_s_high:
                        reclaimed_ph = True
                        self._emit_event(
                            events,
                            seen_keys,
                            index_norm=index_norm,
                            timeframe=timeframe,
                            trading_date_str=trading_date_str,
                            event_type=ICTEventType.SESSION_HIGH,
                            session_event_kind=SessionEventKind.SESSION_HIGH_RECLAIM,
                            direction=EventDirection.BEARISH,
                            qualifier=f"{win.session_id}_RECLAIM_{prev_sid}_HIGH_{bar.candle_id}",
                            dedupe_key=(SessionEventKind.SESSION_HIGH_RECLAIM.value, f"{win.session_id}:{prev_sid}"),
                            event_time=bar.open_time,
                            available_at=bar.close_time,
                            confirmed_at=bar.close_time,
                            event_status=LiquidityLifecycleState.RECLAIMED,
                            source_candle_ids=[bar.candle_id],
                            data_quality=data_quality,
                            price_level=prev_s_high,
                            evidence={
                                "current_session_id": win.session_id,
                                "previous_session_id": prev_sid,
                                "previous_session_high": prev_s_high,
                                "reclaim_close": bar.close,
                            },
                        )

                # Breach & Reclaim vs Previous Completed Session Low
                if prev_s_low is not None and last_completed_session_tracker is not None:
                    prev_sid = last_completed_session_tracker.session_id
                    if not breached_pl and bar.low < (prev_s_low - breach_pen):
                        breached_pl = True
                        self._emit_event(
                            events,
                            seen_keys,
                            index_norm=index_norm,
                            timeframe=timeframe,
                            trading_date_str=trading_date_str,
                            event_type=ICTEventType.SESSION_LOW,
                            session_event_kind=SessionEventKind.SESSION_LOW_BREACH,
                            direction=EventDirection.BEARISH if bar.close < prev_s_low else EventDirection.NEUTRAL,
                            qualifier=f"{win.session_id}_BREACH_{prev_sid}_LOW_{bar.candle_id}",
                            dedupe_key=(SessionEventKind.SESSION_LOW_BREACH.value, f"{win.session_id}:{prev_sid}"),
                            event_time=bar.open_time,
                            available_at=bar.close_time,
                            confirmed_at=bar.close_time,
                            event_status=LiquidityLifecycleState.SWEPT,
                            source_candle_ids=[bar.candle_id],
                            data_quality=data_quality,
                            price_level=prev_s_low,
                            evidence={
                                "current_session_id": win.session_id,
                                "previous_session_id": prev_sid,
                                "previous_session_low": prev_s_low,
                                "breach_bar_low": bar.low,
                                "breach_bar_close": bar.close,
                            },
                        )
                    if breached_pl and not reclaimed_pl and bar.close > prev_s_low:
                        reclaimed_pl = True
                        self._emit_event(
                            events,
                            seen_keys,
                            index_norm=index_norm,
                            timeframe=timeframe,
                            trading_date_str=trading_date_str,
                            event_type=ICTEventType.SESSION_LOW,
                            session_event_kind=SessionEventKind.SESSION_LOW_RECLAIM,
                            direction=EventDirection.BULLISH,
                            qualifier=f"{win.session_id}_RECLAIM_{prev_sid}_LOW_{bar.candle_id}",
                            dedupe_key=(SessionEventKind.SESSION_LOW_RECLAIM.value, f"{win.session_id}:{prev_sid}"),
                            event_time=bar.open_time,
                            available_at=bar.close_time,
                            confirmed_at=bar.close_time,
                            event_status=LiquidityLifecycleState.RECLAIMED,
                            source_candle_ids=[bar.candle_id],
                            data_quality=data_quality,
                            price_level=prev_s_low,
                            evidence={
                                "current_session_id": win.session_id,
                                "previous_session_id": prev_sid,
                                "previous_session_low": prev_s_low,
                                "reclaim_close": bar.close,
                            },
                        )

            total_range = round(running_high - running_low, 4)
            expansion_pts = round(max(0.0, total_range - initial_range), 4)
            expansion_pct = round((expansion_pts / initial_range) * 100.0, 4) if initial_range > 0.0 else None

            tracker = SessionRangeTracker(
                session_id=win.session_id,
                session_name=win.session_name,
                trading_date=trading_date_str,
                timeframe=timeframe,
                timezone=self.config.timezone_name,
                session_start=win_start_dt,
                session_end=win_end_dt,
                status=status,
                session_high=running_high,
                session_low=running_low,
                session_range=total_range,
                initial_range=initial_range,
                range_expansion_pts=expansion_pts,
                range_expansion_pct=expansion_pct,
                high_updated_count=high_updates,
                low_updated_count=low_updates,
                high_candle_id=high_cid,
                low_candle_id=low_cid,
                high_time=high_time,
                low_time=low_time,
                previous_session_id=last_completed_session_tracker.session_id if last_completed_session_tracker else None,
                previous_session_name=last_completed_session_tracker.session_name if last_completed_session_tracker else None,
                previous_session_trading_date=last_completed_session_tracker.trading_date if last_completed_session_tracker else None,
                previous_session_high=prev_s_high,
                previous_session_low=prev_s_low,
                breached_previous_high=breached_ph,
                reclaimed_previous_high=reclaimed_ph,
                breached_previous_low=breached_pl,
                reclaimed_previous_low=reclaimed_pl,
                source_candle_ids=tuple(b.candle_id for b in s_bars),
            )
            trackers[win.session_id] = tracker
            prev_observed_win = win
            prev_observed_bars = s_bars
            if status == SessionPhaseStatus.COMPLETED:
                last_completed_session_tracker = tracker

        # Previous session relative to current/last observed session in this timeframe
        previous_summary: Optional[SessionRangeTracker] = None
        tracker_list = list(trackers.values())
        if len(tracker_list) >= 2:
            previous_summary = tracker_list[-2]
        elif prior_day_last_session is not None:
            previous_summary = prior_day_last_session

        return trackers, transitions, previous_summary

    def _compute_prior_day_last_session(
        self,
        all_bars: Sequence[_ValidatedBar],
        target_date: date,
        timeframe: str,
    ) -> Optional[SessionRangeTracker]:
        """Builds previous completed session tracker from an earlier trading date if present in `all_bars`."""
        prior_bars = [b for b in all_bars if b.open_time.date() < target_date and b.session is not None]
        if not prior_bars:
            return None
        last_prior_date = prior_bars[-1].open_time.date()
        same_date_bars = [b for b in prior_bars if b.open_time.date() == last_prior_date]

        last_win: Optional[SessionWindowConfig] = None
        for win in reversed(self.config.session_windows):
            w_bars = [b for b in same_date_bars if b.session and b.session.session_id == win.session_id]
            if w_bars:
                last_win = win
                win_bars = w_bars
                break
        if last_win is None:
            return None

        win_start_dt, win_end_dt = self._window_datetimes(last_prior_date, last_win.start_time, last_win.end_time)
        hi = max(b.high for b in win_bars)
        lo = min(b.low for b in win_bars)
        init_r = round(win_bars[0].high - win_bars[0].low, 4)
        tot_r = round(hi - lo, 4)
        exp_pts = round(max(0.0, tot_r - init_r), 4)
        return SessionRangeTracker(
            session_id=last_win.session_id,
            session_name=last_win.session_name,
            trading_date=last_prior_date.isoformat(),
            timeframe=timeframe,
            timezone=self.config.timezone_name,
            session_start=win_start_dt,
            session_end=win_end_dt,
            status=SessionPhaseStatus.COMPLETED,
            session_high=hi,
            session_low=lo,
            session_range=tot_r,
            initial_range=init_r,
            range_expansion_pts=exp_pts,
            range_expansion_pct=round((exp_pts / init_r) * 100.0, 4) if init_r > 0.0 else None,
            high_candle_id=next(b.candle_id for b in win_bars if b.high == hi),
            low_candle_id=next(b.candle_id for b in win_bars if b.low == lo),
            high_time=next(b.close_time for b in win_bars if b.high == hi),
            low_time=next(b.close_time for b in win_bars if b.low == lo),
            source_candle_ids=tuple(b.candle_id for b in win_bars),
        )

    def _integrate_liquidity_observations(
        self,
        *,
        liquidity_pools: Optional[List[LiquidityPool]],
        liquidity_events: Optional[List[LiquidityEvent]],
        index_norm: str,
        timeframe: str,
        trading_date: date,
        as_of_tz: datetime,
        data_quality: str,
        events: List[SessionEvent],
        seen_keys: Set[Tuple[str, str]],
    ) -> Tuple[List[SessionLiquidityObservation], List[str]]:
        """
        Integrates existing Step 3.1 `LiquidityPool` and `LiquidityEvent` objects into
        time-causal session context without duplicating Step 3.1 detection logic.
        """
        observations: List[SessionLiquidityObservation] = []
        errors: List[str] = []
        trading_date_str = trading_date.isoformat()
        seen_obs: Set[Tuple[str, str]] = set()

        if liquidity_pools is not None:
            if type(liquidity_pools) is not list:
                raise TypeError("liquidity_pools must be an exact built-in list or None")
            for pool in liquidity_pools:
                if not isinstance(pool, LiquidityPool):
                    raise TypeError(f"Expected LiquidityPool, got {type(pool).__name__}")
                pool_idx = normalize_index_symbol(pool.index)
                if pool_idx != index_norm:
                    continue
                if pool.status == LiquidityLifecycleState.INVALIDATED:
                    continue
                avail_tz = _convert_to_tz(pool.available_at, self.tz, "LiquidityPool.available_at")
                form_tz = _convert_to_tz(pool.formation_time, self.tz, "LiquidityPool.formation_time")
                if avail_tz > as_of_tz:
                    continue
                if form_tz.date() != trading_date and pool.liquidity_type not in (
                    LiquidityType.PDH,
                    LiquidityType.PDL,
                    LiquidityType.SESSION_HIGH,
                    LiquidityType.SESSION_LOW,
                    LiquidityType.OPENING_RANGE_HIGH,
                    LiquidityType.OPENING_RANGE_LOW,
                ):
                    continue

                win = self.classify_timestamp(form_tz)
                obs_key = ("POOL", pool.pool_id)
                if obs_key in seen_obs:
                    continue
                seen_obs.add(obs_key)

                obs_type = (
                    f"SESSION_POOL_{pool.liquidity_type.value}"
                    if win is not None
                    else f"EXTERNAL_POOL_{pool.liquidity_type.value}"
                )
                obs_id = generate_deterministic_session_id(
                    index=index_norm,
                    timeframe=timeframe,
                    event_kind="OBS_POOL",
                    trading_date=trading_date_str,
                    qualifier=pool.pool_id,
                    configuration_fingerprint=self.config_fingerprint,
                )
                src_ids = tuple(pool.source_candle_identifiers or pool.source_candle_ids)
                obs = SessionLiquidityObservation(
                    observation_id=obs_id,
                    index=index_norm,
                    timeframe=timeframe,
                    session_id=win.session_id if win else None,
                    session_name=win.session_name if win else None,
                    observation_type=obs_type,
                    referenced_pool_id=pool.pool_id,
                    referenced_event_id=None,
                    liquidity_type=pool.liquidity_type,
                    direction=pool.direction,
                    price_level=pool.level,
                    event_time=form_tz,
                    available_at=avail_tz,
                    source_candle_ids=src_ids,
                    evidence={
                        "pool_status": pool.status.value,
                        "touch_count": pool.touch_count,
                        "source": "STEP_3_1_LIQUIDITY_POOL",
                    },
                )
                observations.append(obs)
                self._emit_event(
                    events,
                    seen_keys,
                    index_norm=index_norm,
                    timeframe=timeframe,
                    trading_date_str=trading_date_str,
                    event_type=ICTEventType.LIQUIDITY_POOL,
                    session_event_kind=SessionEventKind.SESSION_LIQUIDITY_OBSERVATION,
                    direction=pool.direction,
                    qualifier=f"POOL_{pool.pool_id}",
                    dedupe_key=(SessionEventKind.SESSION_LIQUIDITY_OBSERVATION.value, f"POOL:{pool.pool_id}"),
                    event_time=form_tz,
                    available_at=avail_tz,
                    confirmed_at=avail_tz,
                    event_status=pool.status,
                    source_candle_ids=src_ids,
                    data_quality=data_quality,
                    price_level=pool.level,
                    zone_high=pool.upper_bound,
                    zone_low=pool.lower_bound,
                    evidence={
                        "observation_id": obs_id,
                        "observation_type": obs_type,
                        "referenced_pool_id": pool.pool_id,
                        "session_id": win.session_id if win else None,
                        "session_name": win.session_name if win else None,
                        "liquidity_type": pool.liquidity_type.value,
                    },
                )

        if liquidity_events is not None:
            if type(liquidity_events) is not list:
                raise TypeError("liquidity_events must be an exact built-in list or None")
            for le in liquidity_events:
                if not isinstance(le, LiquidityEvent):
                    raise TypeError(f"Expected LiquidityEvent, got {type(le).__name__}")
                le_idx = normalize_index_symbol(le.index)
                if le_idx != index_norm:
                    continue
                if le.status == LiquidityLifecycleState.INVALIDATED:
                    continue
                avail_tz = _convert_to_tz(le.available_at, self.tz, "LiquidityEvent.available_at")
                ev_tz = _convert_to_tz(le.event_time, self.tz, "LiquidityEvent.event_time")
                if avail_tz > as_of_tz:
                    continue
                if ev_tz.date() != trading_date and avail_tz.date() != trading_date:
                    continue

                win = self.classify_timestamp(ev_tz)
                obs_key = ("EVENT", le.event_id)
                if obs_key in seen_obs:
                    continue
                seen_obs.add(obs_key)

                obs_type = f"SESSION_{le.event_type.value}"
                obs_id = generate_deterministic_session_id(
                    index=index_norm,
                    timeframe=timeframe,
                    event_kind="OBS_EVENT",
                    trading_date=trading_date_str,
                    qualifier=le.event_id,
                    configuration_fingerprint=self.config_fingerprint,
                )
                src_ids = (
                    tuple(le.source_candle_identifiers)
                    if le.source_candle_identifiers
                    else ((le.trigger_candle_id,) if le.trigger_candle_id else ())
                )
                le_price = le.price_level if le.price_level is not None else le.level
                obs = SessionLiquidityObservation(
                    observation_id=obs_id,
                    index=index_norm,
                    timeframe=timeframe,
                    session_id=win.session_id if win else None,
                    session_name=win.session_name if win else None,
                    observation_type=obs_type,
                    referenced_pool_id=le.pool_id,
                    referenced_event_id=le.event_id,
                    liquidity_type=le.liquidity_type,
                    direction=le.direction,
                    price_level=le_price,
                    event_time=ev_tz,
                    available_at=avail_tz,
                    source_candle_ids=src_ids,
                    evidence={
                        "step_3_1_event_type": le.event_type.value,
                        "step_3_1_event_status": le.status.value,
                        "source": "STEP_3_1_LIQUIDITY_EVENT",
                    },
                )
                observations.append(obs)
                self._emit_event(
                    events,
                    seen_keys,
                    index_norm=index_norm,
                    timeframe=timeframe,
                    trading_date_str=trading_date_str,
                    event_type=le.event_type,
                    session_event_kind=SessionEventKind.SESSION_LIQUIDITY_OBSERVATION,
                    direction=le.direction,
                    qualifier=f"EVENT_{le.event_id}",
                    dedupe_key=(SessionEventKind.SESSION_LIQUIDITY_OBSERVATION.value, f"EVENT:{le.event_id}"),
                    event_time=ev_tz,
                    available_at=avail_tz,
                    confirmed_at=_convert_to_tz(le.confirmed_at, self.tz, "LiquidityEvent.confirmed_at")
                    if le.confirmed_at is not None
                    else avail_tz,
                    event_status=le.status,
                    source_candle_ids=src_ids,
                    data_quality=data_quality,
                    price_level=le_price,
                    evidence={
                        "observation_id": obs_id,
                        "observation_type": obs_type,
                        "referenced_pool_id": le.pool_id,
                        "referenced_event_id": le.event_id,
                        "session_id": win.session_id if win else None,
                        "session_name": win.session_name if win else None,
                    },
                )

        return observations, errors

    def _compute_kill_zones(
        self,
        day_bars: Sequence[_ValidatedBar],
        trading_date: date,
        active_reference_time: Optional[datetime],
    ) -> List[KillZoneObservation]:
        """Produces research-only Kill Zone observation metrics over completed bars."""
        observations: List[KillZoneObservation] = []
        ref_t = active_reference_time.time() if active_reference_time else None

        for kz in self.config.kill_zones:
            start_dt, end_dt = self._window_datetimes(trading_date, kz.start_time, kz.end_time)
            start_t = _parse_hhmm(kz.start_time, "kz.start_time")
            end_t = _parse_hhmm(kz.end_time, "kz.end_time")

            kz_bars = [b for b in day_bars if start_dt <= b.open_time < end_dt]
            is_active = bool(ref_t is not None and start_t <= ref_t < end_t)
            obs_hi = max(b.high for b in kz_bars) if kz_bars else None
            obs_lo = min(b.low for b in kz_bars) if kz_bars else None
            observations.append(
                KillZoneObservation(
                    kill_zone_id=kz.kill_zone_id,
                    kill_zone_name=kz.kill_zone_name,
                    window_start=start_dt,
                    window_end=end_dt,
                    is_active=is_active,
                    completed_candles_count=len(kz_bars),
                    observed_high=obs_hi,
                    observed_low=obs_lo,
                    research_only=True,
                    is_proven_edge=False,
                    scoring_weight=None,
                )
            )
        return observations

    # ------------------------------------------------------------------
    # Public Analysis & Historical Replay Entry Points
    # ------------------------------------------------------------------

    def evaluate_session(
        self,
        df: Any,
        symbol: str = "NIFTY 50",
        timeframe: str = "5m",
        as_of_time: Optional[datetime] = None,
        data_quality_status: str = "VERIFIED_LIVE",
        liquidity_pools: Optional[List[LiquidityPool]] = None,
        liquidity_events: Optional[List[LiquidityEvent]] = None,
        target_trading_date: Optional[date] = None,
    ) -> TimeframeSessionReport:
        """
        Deterministically analyzes market session state, opening range, session highs/lows,
        transitions, liquidity observations, and research kill zones as of `as_of_time`.
        Fails closed on invalid feeds, calendar uncertainty, incomplete-only inputs, or bad OHLC.
        """
        index_norm = normalize_index_symbol(symbol)
        tf_norm = normalize_timeframe(timeframe)

        eff_now_raw = as_of_time if as_of_time is not None else self.calendar.now_ist()
        as_of_tz = _convert_to_tz(eff_now_raw, self.tz, "as_of_time")

        # Validate trading date / MarketCalendar fail-closed
        inferred_date = target_trading_date if target_trading_date is not None else as_of_tz.date()
        cal_ok, cal_status, cal_err = self._validate_trading_calendar(inferred_date)
        if not cal_ok:
            return TimeframeSessionReport(
                index=index_norm,
                timeframe=tf_norm,
                trading_date=inferred_date.isoformat(),
                timezone=self.config.timezone_name,
                as_of_time=as_of_tz,
                data_quality=cal_status or "CALENDAR_UNAVAILABLE",
                is_valid=False,
                rejection_reasons=(cal_err or "Calendar validation failed",),
                current_session=SessionClassification(
                    current_session_status=(
                        SessionPhaseStatus.NON_TRADING_DAY
                        if cal_status == "NON_TRADING_DAY"
                        else SessionPhaseStatus.UNAVAILABLE
                    ),
                    timeframe=tf_norm,
                    trading_date=inferred_date.isoformat(),
                    timezone=self.config.timezone_name,
                ),
                configuration_version=self.config.configuration_version,
                configuration_fingerprint=self.config_fingerprint,
            )

        # Strict DataFrame & data quality validation
        df_reasons, eff_status = self._validate_feed_and_dataframe(
            df=df,
            timeframe=tf_norm,
            data_quality_status=data_quality_status,
            index_norm=index_norm,
        )
        if df_reasons:
            return TimeframeSessionReport(
                index=index_norm,
                timeframe=tf_norm,
                trading_date=inferred_date.isoformat(),
                timezone=self.config.timezone_name,
                as_of_time=as_of_tz,
                data_quality=eff_status,
                is_valid=False,
                rejection_reasons=tuple(df_reasons),
                current_session=SessionClassification(
                    current_session_status=SessionPhaseStatus.UNAVAILABLE,
                    timeframe=tf_norm,
                    trading_date=inferred_date.isoformat(),
                    timezone=self.config.timezone_name,
                ),
                configuration_version=self.config.configuration_version,
                configuration_fingerprint=self.config_fingerprint,
            )

        # Completed-candles-only extraction (no forming or future candles)
        all_bars, incomplete_excluded, future_excluded = self._extract_completed_bars(
            df=df,
            timeframe=tf_norm,
            as_of_tz=as_of_tz,
        )

        # Target trading date: inferred_date, or latest completed bar date if target_trading_date omitted & as_of matches
        day_bars = [b for b in all_bars if b.open_time.date() == inferred_date]
        missing_intervals = self._detect_missing_intervals(
            bars=day_bars,
            timeframe=tf_norm,
            target_date=inferred_date,
            as_of_tz=as_of_tz,
        )

        events: List[SessionEvent] = []
        seen_keys: Set[Tuple[str, str]] = set()

        opening_range = self._compute_opening_range(
            day_bars=day_bars,
            missing_intervals=missing_intervals,
            index_norm=index_norm,
            timeframe=tf_norm,
            trading_date=inferred_date,
            as_of_tz=as_of_tz,
            data_quality=eff_status,
            events=events,
            seen_keys=seen_keys,
        )

        prior_day_last = self._compute_prior_day_last_session(
            all_bars=all_bars,
            target_date=inferred_date,
            timeframe=tf_norm,
        )

        session_ranges, transitions, prev_session_summary = self._compute_session_ranges_and_transitions(
            day_bars=day_bars,
            prior_day_last_session=prior_day_last,
            index_norm=index_norm,
            timeframe=tf_norm,
            trading_date=inferred_date,
            as_of_tz=as_of_tz,
            data_quality=eff_status,
            events=events,
            seen_keys=seen_keys,
        )

        liquidity_obs, _ = self._integrate_liquidity_observations(
            liquidity_pools=liquidity_pools,
            liquidity_events=liquidity_events,
            index_norm=index_norm,
            timeframe=tf_norm,
            trading_date=inferred_date,
            as_of_tz=as_of_tz,
            data_quality=eff_status,
            events=events,
            seen_keys=seen_keys,
        )

        # Determine active SessionClassification STRICTLY from completed candle timestamps (Section 4A)
        day_open_dt = datetime.combine(inferred_date, self.market_open_time, tzinfo=self.tz)
        day_close_dt = datetime.combine(inferred_date, self.market_close_time, tzinfo=self.tz)

        if not day_bars:
            if as_of_tz < day_open_dt:
                c_status = SessionPhaseStatus.PRE_OPEN
            elif as_of_tz >= day_close_dt:
                c_status = SessionPhaseStatus.POST_CLOSE
            else:
                c_status = SessionPhaseStatus.UNAVAILABLE
            classification = SessionClassification(
                current_session_status=c_status,
                timeframe=tf_norm,
                trading_date=inferred_date.isoformat(),
                timezone=self.config.timezone_name,
            )
            kz_obs = self._compute_kill_zones(day_bars, inferred_date, None)
        else:
            latest_bar = day_bars[-1]
            # Session status anchored on last completed candle's open_time + session window
            active_win = latest_bar.session
            kz_obs = self._compute_kill_zones(day_bars, inferred_date, latest_bar.open_time)
            active_kz_ids = tuple(k.kill_zone_id for k in kz_obs if k.is_active)

            if active_win is not None:
                win_start_dt, win_end_dt = self._window_datetimes(
                    inferred_date, active_win.start_time, active_win.end_time
                )
                c_status = (
                    SessionPhaseStatus.CLOSED
                    if as_of_tz >= day_close_dt
                    else (
                        SessionPhaseStatus.COMPLETED
                        if latest_bar.close_time >= win_end_dt and as_of_tz >= win_end_dt
                        else SessionPhaseStatus.ACTIVE
                    )
                )
                sess_bars = [
                    b for b in day_bars if b.session and b.session.session_id == active_win.session_id
                ]
                classification = SessionClassification(
                    session_id=active_win.session_id,
                    session_name=active_win.session_name,
                    session_start=win_start_dt,
                    session_end=win_end_dt,
                    current_session_status=c_status,
                    timeframe=tf_norm,
                    trading_date=inferred_date.isoformat(),
                    timezone=self.config.timezone_name,
                    completed_candles_in_session=len(sess_bars),
                    last_completed_candle_id=latest_bar.candle_id,
                    last_completed_candle_close=latest_bar.close_time,
                    active_kill_zones=active_kz_ids,
                )
            else:
                classification = SessionClassification(
                    current_session_status=(
                        SessionPhaseStatus.POST_CLOSE
                        if as_of_tz >= day_close_dt
                        else SessionPhaseStatus.UNAVAILABLE
                    ),
                    timeframe=tf_norm,
                    trading_date=inferred_date.isoformat(),
                    timezone=self.config.timezone_name,
                    last_completed_candle_id=latest_bar.candle_id,
                    last_completed_candle_close=latest_bar.close_time,
                    active_kill_zones=active_kz_ids,
                )

        # Deterministic chronological event ordering
        sorted_events = tuple(
            sorted(events, key=lambda e: (e.available_at, e.event_time, e.event_id))
        )
        ict_events = tuple(ev.to_ict_event() for ev in sorted_events)

        return TimeframeSessionReport(
            index=index_norm,
            timeframe=tf_norm,
            trading_date=inferred_date.isoformat(),
            timezone=self.config.timezone_name,
            as_of_time=as_of_tz,
            data_quality=eff_status,
            is_valid=True,
            rejection_reasons=(),
            execution_mode=EXECUTION_MODE,
            confluence_score=None,
            score_status="UNAVAILABLE",
            calibration_status="NOT_CALIBRATED",
            current_session=classification,
            opening_range=opening_range,
            session_ranges=session_ranges,
            previous_session_summary=prev_session_summary,
            transitions=tuple(transitions),
            liquidity_observations=tuple(liquidity_obs),
            kill_zone_observations=tuple(kz_obs),
            events=sorted_events,
            ict_events=ict_events,
            completed_candles_count=len(day_bars),
            incomplete_candles_excluded=incomplete_excluded,
            future_candles_excluded=future_excluded,
            missing_intervals=tuple(missing_intervals),
            has_data_gaps=len(missing_intervals) > 0,
            configuration_version=self.config.configuration_version,
            configuration_fingerprint=self.config_fingerprint,
            engine_version=ENGINE_VERSION,
        )

    def replay_session(
        self,
        df: Any,
        symbol: str = "NIFTY 50",
        timeframe: str = "5m",
        replay_times: Optional[Sequence[datetime]] = None,
        data_quality_status: str = "VERIFIED_LIVE",
        liquidity_pools: Optional[List[LiquidityPool]] = None,
        liquidity_events: Optional[List[LiquidityEvent]] = None,
        target_trading_date: Optional[date] = None,
    ) -> List[TimeframeSessionReport]:
        """
        Executes deterministic historical point-in-time replay across an ordered sequence
        of replay timestamps. If `replay_times` is None, replays strictly at each candle
        close timestamp present in `df` on the target date.
        """
        index_norm = normalize_index_symbol(symbol)
        tf_norm = normalize_timeframe(timeframe)

        if replay_times is not None:
            if type(replay_times) is not list and type(replay_times) is not tuple:
                raise TypeError("replay_times must be a list or tuple of timezone-aware datetimes")
            if not replay_times:
                return []
            converted_times = [_convert_to_tz(rt, self.tz, "replay_time") for rt in replay_times]
            for i in range(1, len(converted_times)):
                if converted_times[i] < converted_times[i - 1]:
                    raise ValueError("replay_times must be non-decreasing")
            schedule = converted_times
        else:
            if not isinstance(df, pd.DataFrame) or df.empty or "timestamp" not in df.columns:
                raise ValueError("Cannot derive replay_times automatically from empty or malformed DataFrame")
            raw_closes: List[datetime] = []
            for raw_ts in df["timestamp"]:
                dt_obj = pd.to_datetime(raw_ts) if type(raw_ts) is str else raw_ts
                open_tz = _convert_to_tz(dt_obj, self.tz, "candle.timestamp")
                if target_trading_date is None or open_tz.date() == target_trading_date:
                    raw_closes.append(compute_candle_close_ist(open_tz, tf_norm, self.market_close_time))
            schedule = sorted(set(raw_closes))

        reports: List[TimeframeSessionReport] = []
        for ts in schedule:
            rep = self.evaluate_session(
                df=df,
                symbol=index_norm,
                timeframe=tf_norm,
                as_of_time=ts,
                data_quality_status=data_quality_status,
                liquidity_pools=liquidity_pools,
                liquidity_events=liquidity_events,
                target_trading_date=target_trading_date or ts.date(),
            )
            reports.append(rep)
        return reports

    def analyze_multi_timeframe(
        self,
        data_by_timeframe: Dict[str, pd.DataFrame],
        symbol: str = "NIFTY 50",
        as_of_time: Optional[datetime] = None,
        data_quality_status: str = "VERIFIED_LIVE",
        liquidity_pools: Optional[List[LiquidityPool]] = None,
        liquidity_events: Optional[List[LiquidityEvent]] = None,
        target_trading_date: Optional[date] = None,
    ) -> MultiTimeframeSessionSummary:
        """
        Synchronizes Step 3.6 session intelligence across multiple timeframes cleanly.
        Confluence scoring remains UNAVAILABLE / NOT_CALIBRATED and mode PAPER_TRADING_ONLY.
        """
        if not isinstance(data_by_timeframe, dict) or not data_by_timeframe:
            raise ValueError("data_by_timeframe must be a non-empty dict mapping timeframe -> DataFrame")

        index_norm = normalize_index_symbol(symbol)
        eff_now_raw = as_of_time if as_of_time is not None else self.calendar.now_ist()
        as_of_tz = _convert_to_tz(eff_now_raw, self.tz, "as_of_time")
        t_date = target_trading_date if target_trading_date is not None else as_of_tz.date()

        tf_reports: Dict[str, TimeframeSessionReport] = {}
        all_reasons: List[str] = []
        all_valid = True
        worst_quality = "VERIFIED_LIVE"
        combined_events: List[SessionEvent] = []

        for tf_key, tf_df in data_by_timeframe.items():
            tf_norm = normalize_timeframe(tf_key)
            rep = self.evaluate_session(
                df=tf_df,
                symbol=index_norm,
                timeframe=tf_norm,
                as_of_time=as_of_tz,
                data_quality_status=data_quality_status,
                liquidity_pools=liquidity_pools,
                liquidity_events=liquidity_events,
                target_trading_date=t_date,
            )
            tf_reports[tf_norm] = rep
            if not rep.is_valid:
                all_valid = False
                worst_quality = rep.data_quality
                all_reasons.extend([f"[{tf_norm}] {r}" for r in rep.rejection_reasons])
            elif rep.data_quality != "VERIFIED_LIVE" and worst_quality == "VERIFIED_LIVE":
                worst_quality = rep.data_quality
            combined_events.extend(rep.events)

        active_sids = {
            rep.current_session.session_id
            for rep in tf_reports.values()
            if rep.is_valid and rep.current_session and rep.current_session.session_id
        }
        agreement = all_valid and len(active_sids) == 1
        sync_sid: Optional[str] = next(iter(active_sids)) if agreement else None
        sync_sname: Optional[str] = None
        if sync_sid is not None:
            for rep in tf_reports.values():
                if rep.current_session and rep.current_session.session_id == sync_sid:
                    sync_sname = rep.current_session.session_name
                    break

        deduped_events: Dict[str, SessionEvent] = {}
        for ev in sorted(combined_events, key=lambda e: (e.available_at, e.event_time, e.event_id)):
            deduped_events.setdefault(ev.event_id, ev)

        return MultiTimeframeSessionSummary(
            index=index_norm,
            trading_date=t_date.isoformat(),
            timezone=self.config.timezone_name,
            as_of_time=as_of_tz,
            data_quality=worst_quality,
            is_valid=all_valid,
            rejection_reasons=tuple(all_reasons),
            timeframe_reports=tf_reports,
            synchronized_active_session_id=sync_sid,
            synchronized_active_session_name=sync_sname,
            timeframe_session_agreement=agreement,
            all_events=tuple(deduped_events.values()),
            ict_confluence_score=None,
            score_status="UNAVAILABLE",
            calibration_status="NOT_CALIBRATED",
            execution_mode=EXECUTION_MODE,
            configuration_version=self.config.configuration_version,
            engine_version=ENGINE_VERSION,
        )


__all__ = [
    "ENGINE_VERSION",
    "DEFAULT_CONFIGURATION_VERSION",
    "EXECUTION_MODE",
    "DEFAULT_TIMEZONE_NAME",
    "IST_ZONE",
    "TIMEFRAME_MINUTES",
    "SessionPhaseStatus",
    "OpeningRangeStatus",
    "SessionEventKind",
    "SessionWindowConfig",
    "KillZoneConfig",
    "SessionConfiguration",
    "MissingCandleInterval",
    "SessionClassification",
    "OpeningRangeState",
    "SessionRangeTracker",
    "SessionTransition",
    "SessionLiquidityObservation",
    "KillZoneObservation",
    "SessionEvent",
    "TimeframeSessionReport",
    "MultiTimeframeSessionSummary",
    "SessionIntelligenceEngine",
    "default_indian_session_windows",
    "default_research_kill_zones",
    "normalize_index_symbol",
    "normalize_timeframe",
    "compute_candle_close_ist",
    "generate_deterministic_session_id",
]
