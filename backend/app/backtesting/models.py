"""
AIVOLVE Phase 4 Step 4.2 — Canonical Data Models & Future Execution Design Contracts.

Defines immutable Pydantic v2 schemas for:
- Historical data integrity auditing
- Chunked historical download manifests & BLOCKED diagnostics
- Multi-year historical calendar verification
- Point-in-time deterministic Phase 3 replay results & isolated run store records
- Step 4.3+ Execution Simulator design specifications ONLY (zero execution or P&L code)
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol, Sequence, Tuple, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class IntegrityIssueSeverity(str, Enum):
    ERROR = "ERROR"
    WARNING = "WARNING"


class IntegrityStatus(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"


class DownloadStatus(str, Enum):
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"
    FAILED_INTEGRITY = "FAILED_INTEGRITY"
    GOVERNANCE_LOCKOUT = "GOVERNANCE_LOCKOUT"
    INCOMPLETE = "INCOMPLETE"


class CalendarStatus(str, Enum):
    TRADING_DAY = "TRADING_DAY"
    NON_TRADING_DAY = "NON_TRADING_DAY"
    CALENDAR_UNAVAILABLE = "CALENDAR_UNAVAILABLE"


class ReplayValidationStatus(str, Enum):
    VALIDATED = "VALIDATED"
    LOCKED_OUT = "LOCKED_OUT"
    FAILED = "FAILED"


class IntegrityIssue(BaseModel):
    """Single deterministic data-quality finding emitted by DataIntegrityAuditor."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str
    severity: IntegrityIssueSeverity = IntegrityIssueSeverity.ERROR
    message: str
    row_index: Optional[int] = None
    timestamp_ist: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)


class MissingCandleInterval(BaseModel):
    """Explicit gap record representing an absent expected bar (never backfilled)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    timeframe: str
    trading_date: str
    expected_open_ist: str
    expected_close_ist: str
    reason: str


class DataIntegrityReport(BaseModel):
    """Full audit report returned by DataIntegrityAuditor."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    is_valid: bool
    status: IntegrityStatus
    instrument: str
    timeframe: str
    total_bars: int
    valid_bars: int
    rejected_reasons: Tuple[str, ...] = ()
    issues: Tuple[IntegrityIssue, ...] = ()
    duplicate_timestamps: Tuple[str, ...] = ()
    missing_intervals: Tuple[MissingCandleInterval, ...] = ()
    repaired_detected: bool = False
    synthetic_detected: bool = False
    incomplete_candles_detected: int = 0
    tz_name: str = "Asia/Kolkata"
    first_timestamp_ist: Optional[str] = None
    last_timestamp_ist: Optional[str] = None
    dataset_fingerprint: str = ""


class ChunkDownloadRecord(BaseModel):
    """Traceable per-chunk download telemetry for date-range chunking & gap verification."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    chunk_index: int
    from_time_ist: str
    to_time_ist: str
    status: str
    bars_received: int = 0
    http_status: Optional[int] = None
    error_code: Optional[str] = None
    reason: Optional[str] = None


class HistoricalDownloadResult(BaseModel):
    """Outcome manifest returned by AngelOneHistoricalDataDownloader."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: DownloadStatus
    blocked: bool
    block_reason: Optional[str] = None
    provider: str = "angelone"
    instrument: str
    exchange: str
    symbol_token: str
    timeframe: str
    requested_from_ist: str
    requested_to_ist: str
    actual_from_ist: Optional[str] = None
    actual_to_ist: Optional[str] = None
    bars_downloaded: int = 0
    bars_stored: int = 0
    chunks_total: int = 0
    chunks_succeeded: int = 0
    chunks_empty: int = 0
    chunks: Tuple[ChunkDownloadRecord, ...] = ()
    integrity_report: Optional[DataIntegrityReport] = None
    dataset_fingerprint: Optional[str] = None
    ingestion_id: Optional[str] = None
    retrieved_at_utc: datetime


class HolidayScheduleRecord(BaseModel):
    """Verified annual exchange holiday schedule entry for multi-year calendar injection."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    year: int
    holidays: Dict[str, str]
    source: str
    verified: bool = True
    checksum_sha256: str = ""


class CalendarValidationResult(BaseModel):
    """Deterministic calendar validation outcome for a historical date."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    is_valid: bool
    is_trading_day: bool
    status: CalendarStatus
    target_date: date
    reason: str
    calendar_fingerprint: str


class ReplayPointResult(BaseModel):
    """Single point-in-time snapshot output emitted during chronological replay."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    as_of_time_ist: str
    report_id: str
    overall_alignment: str
    data_quality_status: str
    score_status: str
    calibration_status: str
    confluence_score: Optional[float] = None
    bars_used_by_timeframe: Dict[str, int] = Field(default_factory=dict)
    future_bars_excluded: Dict[str, int] = Field(default_factory=dict)
    incomplete_bars_excluded: Dict[str, int] = Field(default_factory=dict)
    conflicts_count: int = 0
    evidence_event_ids: Tuple[str, ...] = ()
    report: Dict[str, Any] = Field(default_factory=dict)


class ReplayRunRecord(BaseModel):
    """Isolated persisted backtest replay record saved strictly outside production tables."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str
    instrument: str
    timeframes: Tuple[str, ...]
    start_date_ist: str
    end_date_ist: str
    historical_date_range: str
    data_source: str
    dataset_fingerprint: str
    engine_version: str
    configuration_version: str
    calendar_source: str
    calendar_fingerprint: str
    replay_timestamps_ist: Tuple[str, ...]
    output_fingerprint: str
    validation_status: ReplayValidationStatus
    failure_reasons: Tuple[str, ...] = ()
    point_count: int
    points: Tuple[ReplayPointResult, ...] = ()
    created_at_utc: datetime


# ============================================================================
# Section 7 — Future Execution Simulator Design Contracts ONLY (Step 4.3+ Spec)
# ZERO trade execution, fill simulation, or P&L calculation implemented here.
# ============================================================================


class ExecutionTimingPolicy(str, Enum):
    """Mandatory no-lookahead execution timing policy."""

    NEXT_COMPLETED_BAR_OPEN = "NEXT_COMPLETED_BAR_OPEN"


class IntrabarAmbiguityPolicy(str, Enum):
    """Mandatory handling when both SL and profit target lie inside one bar's [low, high]."""

    CONSERVATIVE_SL_FIRST_WITH_AMBIGUOUS_TAG = "CONSERVATIVE_SL_FIRST_WITH_AMBIGUOUS_TAG"
    MARK_AMBIGUOUS_NO_FILL = "MARK_AMBIGUOUS_NO_FILL"


class SimulationDomainMode(str, Enum):
    """Strict separation between index-point accounting and INR option-premium simulation."""

    UNDERLYING_POINTS_ONLY = "UNDERLYING_POINTS_ONLY"
    OPTIONS_PREMIUM_SIMULATION = "OPTIONS_PREMIUM_SIMULATION"


class OptionDataMode(str, Enum):
    """Explicitly distinguishes real observed option bars from Black-Scholes approximations."""

    REAL_OPTION_OHLC = "REAL_OPTION_OHLC"
    SYNTHETIC_BS_MODEL = "SYNTHETIC_BS_MODEL"


class FillPriceModelSpec(BaseModel):
    """Design contract for realistic entry/exit fill simulation in future Step 4.3."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    timing_policy: ExecutionTimingPolicy = ExecutionTimingPolicy.NEXT_COMPLETED_BAR_OPEN
    entry_uses_ask_or_adverse_open: bool = True
    exit_uses_bid_or_adverse_level: bool = True
    slippage_points_per_leg: float = Field(default=0.5, ge=0.0)
    tick_size: float = Field(default=0.05, gt=0.0)
    enforce_tick_rounding: bool = True


class CostAndSlippageSpec(BaseModel):
    """Design contract for statutory Indian derivatives charges deducted from cash equity."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    exchange_segment: str = "NFO"  # Differentiate NFO vs BFO in future implementation
    brokerage_per_executed_order_inr: float = 20.0
    stt_sell_rate: float = 0.001
    exchange_txn_rate: float = 0.0005
    gst_rate_on_brokerage_and_exchange: float = 0.18
    sebi_turnover_rate: float = 0.000001
    stamp_duty_buy_rate: float = 0.00003
    deduct_total_costs_from_cash_balance: bool = True


class ExecutionSimulatorDesignSpec(BaseModel):
    """Complete declarative blueprint for future Step 4.3 Execution Simulator (non-executable)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    simulation_domain: SimulationDomainMode
    option_data_mode: Optional[OptionDataMode] = None
    intrabar_ambiguity_policy: IntrabarAmbiguityPolicy = (
        IntrabarAmbiguityPolicy.CONSERVATIVE_SL_FIRST_WITH_AMBIGUOUS_TAG
    )
    fill_model: FillPriceModelSpec = Field(default_factory=FillPriceModelSpec)
    cost_model: CostAndSlippageSpec = Field(default_factory=CostAndSlippageSpec)


@runtime_checkable
class FutureExecutionSimulatorProtocol(Protocol):
    """
    INTERFACE SPECIFICATION ONLY (Step 4.3+ Target).

    Not implemented in Step 4.2. Future implementations must:
    - Trigger decisions only on completed signal bars at close t_k and fill strictly on bar t_{k+1}.
    - Emit explicit AMBIGUOUS outcomes when [low, high] spans both SL and TP bounds.
    - Deduct full statutory charges + slippage from simulated portfolio cash equity.
    - Keep UNDERLYING_POINTS_ONLY and OPTIONS_PREMIUM_SIMULATION strictly segregated.
    - Require explicit REAL_OPTION_OHLC vs SYNTHETIC_BS_MODEL tagging on option simulations.
    """

    def simulate_from_replay(
        self,
        replay_run: ReplayRunRecord,
        design_spec: ExecutionSimulatorDesignSpec,
    ) -> Dict[str, Any]:
        ...

