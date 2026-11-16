"""
AIVOLVE Phase 4 Step 4.4 — Canonical Schemas for Backtest Analytics & Performance Evaluation.

Defines strict, immutable Pydantic schemas enforcing:
- PAPER_TRADING_ONLY research/evaluation provenance
- Strict three-way AccountingUnitMode segregation:
  1. INDEX_POINTS_ONLY (index points only; monetary INR fields strictly None)
  2. INDEX_POINTS_AND_EXPLICIT_INR (points & INR strictly segregated with documented multiplier)
  3. SYNTHETIC_OPTION_INR_ONLY (SYNTHETIC_MODELLED_OPTION_PNL watermarked INR; points fields strictly None)
- Safe zero-denominator and insufficient-sample handling (unavailable metrics remain None with explicit reasons)
- Explicit UNKNOWN handling for missing strategy metadata (no inferred labels)
"""

from __future__ import annotations

import math
from datetime import datetime, time as dt_time
from enum import Enum
from typing import Any, Dict, Literal, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.backtesting.configuration import EXECUTION_MODE, IST_ZONE
from app.backtesting.simulation_models import (
    AccountingUnitMode,
    CostScheduleVersion,
    SimulationMode,
    SimulationRunResult,
    SimulationStatus,
)

ANALYTICS_VERSION: str = "4.4.0"
UNKNOWN_LABEL: str = "UNKNOWN"
DEFAULT_MIN_TRADES_FOR_SIGNIFICANCE: int = 30

# Canonical AIVOLVE IST market session windows matching Step 3.6 Session Intelligence.
MARKET_SESSION_WINDOWS_IST: Tuple[Tuple[str, dt_time, dt_time, bool], ...] = (
    ("OPENING", dt_time(9, 15), dt_time(9, 45), False),
    ("MORNING", dt_time(9, 45), dt_time(11, 30), False),
    ("MIDDAY", dt_time(11, 30), dt_time(13, 30), False),
    ("AFTERNOON", dt_time(13, 30), dt_time(14, 45), False),
    ("CLOSING", dt_time(14, 45), dt_time(15, 30), True),
)


class AnalyticsStatus(str, Enum):
    COMPLETED = "COMPLETED"
    NO_TRADES = "NO_TRADES"
    RUN_NOT_COMPLETED = "RUN_NOT_COMPLETED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class MetricAvailabilityStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    NO_CLOSED_TRADES = "NO_CLOSED_TRADES"
    NO_WINNING_TRADES = "NO_WINNING_TRADES"
    NO_LOSING_TRADES = "NO_LOSING_TRADES"
    ZERO_LOSS_UNDEFINED = "ZERO_LOSS_UNDEFINED"
    ZERO_DRAWDOWN_UNDEFINED = "ZERO_DRAWDOWN_UNDEFINED"
    ZERO_RISK_DISTANCE_UNDEFINED = "ZERO_RISK_DISTANCE_UNDEFINED"
    NO_VALID_TIMESTAMPS = "NO_VALID_TIMESTAMPS"
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
    NOT_APPLICABLE_IN_DOMAIN = "NOT_APPLICABLE_IN_DOMAIN"


class MarketSessionBucket(str, Enum):
    OPENING = "OPENING"
    MORNING = "MORNING"
    MIDDAY = "MIDDAY"
    AFTERNOON = "AFTERNOON"
    CLOSING = "CLOSING"
    OUTSIDE_REGULAR_SESSION = "OUTSIDE_REGULAR_SESSION"
    UNKNOWN = "UNKNOWN"


class SignificanceStatus(str, Enum):
    NO_TRADES = "NO_TRADES"
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
    ZERO_VARIANCE = "ZERO_VARIANCE"
    DESCRIPTIVE_RESEARCH_ONLY = "DESCRIPTIVE_RESEARCH_ONLY"


def parse_ist_datetime(value: datetime | str, field_name: str = "timestamp") -> datetime:
    """Parses ISO string or datetime strictly requiring tzinfo and normalizing to Asia/Kolkata."""
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value)
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise TypeError(f"{field_name} must be datetime or ISO str, got {type(value).__name__}")
    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        raise ValueError(f"{field_name} must be timezone-aware, got {value!r}")
    return parsed.astimezone(IST_ZONE)


def classify_ist_session(dt_ist: datetime) -> MarketSessionBucket:
    """Classifies a timezone-aware timestamp into canonical NSE/BSE IST market sessions."""
    local_t = dt_ist.astimezone(IST_ZONE).time().replace(tzinfo=None)
    for label, start_t, end_t, inclusive_end in MARKET_SESSION_WINDOWS_IST:
        if inclusive_end:
            if start_t <= local_t <= end_t:
                return MarketSessionBucket(label)
        else:
            if start_t <= local_t < end_t:
                return MarketSessionBucket(label)
    return MarketSessionBucket.OUTSIDE_REGULAR_SESSION


def _check_all_finite(model: BaseModel, fields: Sequence[str]) -> None:
    for fname in fields:
        val = getattr(model, fname)
        if val is not None and not math.isfinite(float(val)):
            raise ValueError(f"{fname} must be finite, got {val!r}")


def validate_run_domain_integrity(run: SimulationRunResult) -> None:
    """Verifies internal accounting mode consistency of a persisted Step 4.3 run before analytics."""
    um = run.accounting_unit_mode
    if um != run.portfolio.accounting_unit_mode:
        raise ValueError(
            f"MIXED_DOMAIN_ANALYTICS_FORBIDDEN: run accounting_unit_mode ({um.value}) != "
            f"portfolio ({run.portfolio.accounting_unit_mode.value})."
        )
    if um == AccountingUnitMode.SYNTHETIC_OPTION_INR_ONLY:
        if run.provenance_label != "SYNTHETIC_MODELLED_OPTION_PNL" or not run.is_synthetic_modelled:
            raise ValueError(
                "SYNTHETIC_PROVENANCE_VIOLATION: SYNTHETIC_OPTION_INR_ONLY requires "
                "provenance_label='SYNTHETIC_MODELLED_OPTION_PNL' and is_synthetic_modelled=True."
            )
    elif um == AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR:
        mult = run.portfolio.instrument_multiplier_inr_per_point
        doc = (run.portfolio.instrument_multiplier_documentation or "").strip()
        if mult is None or not math.isfinite(mult) or mult <= 0.0 or len(doc) < 10:
            raise ValueError(
                "MULTIPLIER_DOCUMENTATION_REQUIRED: INDEX_POINTS_AND_EXPLICIT_INR requires explicit "
                "instrument_multiplier_inr_per_point > 0 and documented instrument_multiplier_documentation."
            )
    else:
        if run.portfolio.monetary_accounting_enabled:
            raise ValueError(
                "MODE_MIXING_POINTS_AND_CURRENCY: monetary_accounting_enabled cannot be True in INDEX_POINTS_ONLY."
            )


def validate_homogeneous_runs(
    runs: Sequence[SimulationRunResult],
) -> Tuple[AccountingUnitMode, str, bool]:
    """Rejects mixed-domain aggregation across heterogeneous SimulationRunResult objects."""
    if not runs:
        raise ValueError("At least one SimulationRunResult is required.")
    first = runs[0]
    validate_run_domain_integrity(first)
    um = first.accounting_unit_mode
    prov = first.provenance_label
    mult = first.portfolio.instrument_multiplier_inr_per_point
    for other in runs[1:]:
        validate_run_domain_integrity(other)
        if other.accounting_unit_mode != um:
            raise ValueError(
                f"MIXED_DOMAIN_ANALYTICS_FORBIDDEN: cannot combine {um.value} with {other.accounting_unit_mode.value}."
            )
        if other.provenance_label != prov:
            raise ValueError(
                f"MIXED_DOMAIN_ANALYTICS_FORBIDDEN: cannot combine provenance '{prov}' with '{other.provenance_label}'."
            )
        if um == AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR:
            other_mult = other.portfolio.instrument_multiplier_inr_per_point
            if mult is None or other_mult is None or abs(mult - other_mult) > 1e-9:
                raise ValueError(
                    f"MIXED_DOMAIN_ANALYTICS_FORBIDDEN: mismatched explicit INR multipliers ({mult} vs {other_mult})."
                )
    return um, prov, first.is_synthetic_modelled


def domain_has_points(um: AccountingUnitMode) -> bool:
    return um in (AccountingUnitMode.INDEX_POINTS_ONLY, AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR)


def domain_has_inr(um: AccountingUnitMode) -> bool:
    return um in (AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR, AccountingUnitMode.SYNTHETIC_OPTION_INR_ONLY)


class MetricAvailability(BaseModel):
    """Explains why a nullable metric is unavailable or zero-denominator undefined."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    metric_name: str
    status: MetricAvailabilityStatus
    reason: str


class DomainPerformanceMetrics(BaseModel):
    """Single-domain closed-trade performance metrics (`INDEX_POINTS` or `INR`)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    unit_label: Literal["INDEX_POINTS", "INR"]
    provenance_label: str
    total_closed_trades: int = Field(..., ge=0)
    winning_trades: int = Field(..., ge=0)
    losing_trades: int = Field(..., ge=0)
    strict_positive_trades: int = Field(..., ge=0)
    strict_negative_trades: int = Field(..., ge=0)
    breakeven_trades: int = Field(..., ge=0)
    intrabar_ambiguous_trades: int = Field(..., ge=0)
    win_rate: Optional[float] = None
    win_rate_pct: Optional[float] = None
    gross_pnl: float
    total_costs: float
    net_pnl: float
    average_win: Optional[float] = None
    average_loss: Optional[float] = None
    average_loss_abs: Optional[float] = None
    largest_win: Optional[float] = None
    largest_loss: Optional[float] = None
    largest_loss_abs: Optional[float] = None
    profit_factor: Optional[float] = None
    profit_factor_status: MetricAvailabilityStatus
    expectancy: Optional[float] = None
    average_risk_reward: Optional[float] = None
    average_risk_reward_status: MetricAvailabilityStatus
    average_planned_risk_reward: Optional[float] = None
    average_realized_r_multiple: Optional[float] = None
    max_drawdown: float = Field(..., ge=0.0)
    max_drawdown_pct: Optional[float] = Field(default=None, ge=0.0)
    recovery_factor: Optional[float] = None
    recovery_factor_status: MetricAvailabilityStatus
    net_return_pct: Optional[float] = None
    min_trade_pnl: Optional[float] = None
    p10_trade_pnl: Optional[float] = None
    p25_trade_pnl: Optional[float] = None
    median_trade_pnl: Optional[float] = None
    p75_trade_pnl: Optional[float] = None
    p90_trade_pnl: Optional[float] = None
    max_trade_pnl: Optional[float] = None
    availability_notes: Tuple[MetricAvailability, ...] = ()

    @model_validator(mode="after")
    def _validate_domain_purity(self) -> "DomainPerformanceMetrics":
        _check_all_finite(
            self,
            (
                "win_rate",
                "win_rate_pct",
                "gross_pnl",
                "total_costs",
                "net_pnl",
                "average_win",
                "average_loss",
                "average_loss_abs",
                "largest_win",
                "largest_loss",
                "largest_loss_abs",
                "profit_factor",
                "expectancy",
                "average_risk_reward",
                "average_planned_risk_reward",
                "average_realized_r_multiple",
                "max_drawdown",
                "max_drawdown_pct",
                "recovery_factor",
                "net_return_pct",
                "min_trade_pnl",
                "p10_trade_pnl",
                "p25_trade_pnl",
                "median_trade_pnl",
                "p75_trade_pnl",
                "p90_trade_pnl",
                "max_trade_pnl",
            ),
        )
        if self.unit_label == "INDEX_POINTS":
            if self.max_drawdown_pct is not None or self.net_return_pct is not None:
                raise ValueError(
                    "MODE_MIXING_POINTS_AND_CURRENCY: monetary percentage fields are forbidden in INDEX_POINTS metrics."
                )
        return self


class PerformanceSummaryAnalytics(BaseModel):
    """Top-level performance summary keeping INDEX_POINTS and INR strictly separated."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    accounting_unit_mode: AccountingUnitMode
    provenance_label: str
    is_synthetic_modelled: bool
    instrument_multiplier_inr_per_point: Optional[float] = None
    instrument_multiplier_documentation: Optional[str] = None
    total_signals: int = Field(..., ge=0)
    trades_opened: int = Field(..., ge=0)
    trades_closed: int = Field(..., ge=0)
    trades_open: int = Field(..., ge=0)
    trades_rejected_or_cancelled: int = Field(..., ge=0)
    partial_exits_count: int = Field(..., ge=0)
    intrabar_ambiguous_count: int = Field(..., ge=0)
    max_consecutive_wins: int = Field(..., ge=0)
    max_consecutive_losses: int = Field(..., ge=0)
    current_streak_type: Literal["WIN", "LOSS", "NONE"]
    current_streak_count: int = Field(..., ge=0)
    average_holding_duration_seconds: Optional[float] = Field(default=None, ge=0.0)
    average_holding_duration_minutes: Optional[float] = Field(default=None, ge=0.0)
    min_holding_duration_seconds: Optional[float] = Field(default=None, ge=0.0)
    median_holding_duration_seconds: Optional[float] = Field(default=None, ge=0.0)
    max_holding_duration_seconds: Optional[float] = Field(default=None, ge=0.0)
    holding_duration_status: MetricAvailabilityStatus
    points_metrics: Optional[DomainPerformanceMetrics] = None
    inr_metrics: Optional[DomainPerformanceMetrics] = None
    reconciliation_verified: bool
    net_pnl_reconciliation_diff_points: Optional[float] = None
    net_pnl_reconciliation_diff_inr: Optional[float] = None

    @model_validator(mode="after")
    def _validate_accounting_sections(self) -> "PerformanceSummaryAnalytics":
        if self.accounting_unit_mode == AccountingUnitMode.INDEX_POINTS_ONLY:
            if self.points_metrics is None or self.inr_metrics is not None:
                raise ValueError(
                    "MODE_MIXING_POINTS_AND_CURRENCY: INDEX_POINTS_ONLY requires points_metrics only and inr_metrics=None."
                )
        elif self.accounting_unit_mode == AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR:
            if self.points_metrics is None or self.inr_metrics is None:
                raise ValueError(
                    "INDEX_POINTS_AND_EXPLICIT_INR requires both points_metrics and inr_metrics in separate sections."
                )
        else:
            if self.points_metrics is not None or self.inr_metrics is None:
                raise ValueError(
                    "MODE_MIXING: SYNTHETIC_OPTION_INR_ONLY requires inr_metrics only and points_metrics=None."
                )
        return self


class DrawdownTimelinePoint(BaseModel):
    """Chronological IST drawdown observation segregated by accounting domain."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    timestamp_ist: str
    accounting_unit_mode: AccountingUnitMode
    equity_points: Optional[float] = None
    peak_points: Optional[float] = None
    drawdown_points: Optional[float] = None
    equity_inr: Optional[float] = None
    peak_inr: Optional[float] = None
    drawdown_inr: Optional[float] = None
    drawdown_pct: Optional[float] = None

    @model_validator(mode="after")
    def _validate_point_domain(self) -> "DrawdownTimelinePoint":
        pts = (self.equity_points, self.peak_points, self.drawdown_points)
        inr = (self.equity_inr, self.peak_inr, self.drawdown_inr, self.drawdown_pct)
        if self.accounting_unit_mode == AccountingUnitMode.INDEX_POINTS_ONLY:
            if any(v is None for v in pts) or any(v is not None for v in inr):
                raise ValueError("MODE_MIXING_POINTS_AND_CURRENCY: DrawdownTimelinePoint violated INDEX_POINTS_ONLY.")
        elif self.accounting_unit_mode == AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR:
            if any(v is None for v in pts) or any(v is None for v in inr):
                raise ValueError("INDEX_POINTS_AND_EXPLICIT_INR DrawdownTimelinePoint requires both domains.")
        else:
            if any(v is not None for v in pts) or any(v is None for v in inr):
                raise ValueError("MODE_MIXING: DrawdownTimelinePoint violated SYNTHETIC_OPTION_INR_ONLY.")
        return self


class DrawdownEpisode(BaseModel):
    """Single peak-to-trough-to-recovery underwater interval."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    episode_id: str
    unit_label: Literal["INDEX_POINTS", "INR"]
    peak_time_ist: str
    trough_time_ist: str
    recovery_time_ist: Optional[str] = None
    recovered: bool
    peak_equity: float
    trough_equity: float
    max_drawdown: float = Field(..., ge=0.0)
    max_drawdown_pct: Optional[float] = Field(default=None, ge=0.0)
    duration_bars: int = Field(..., ge=1)
    duration_seconds: float = Field(..., ge=0.0)


class DomainRiskMetrics(BaseModel):
    """Single-domain risk and drawdown metrics."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    unit_label: Literal["INDEX_POINTS", "INR"]
    provenance_label: str
    max_drawdown: float = Field(..., ge=0.0)
    max_drawdown_pct: Optional[float] = Field(default=None, ge=0.0)
    max_drawdown_peak_time_ist: Optional[str] = None
    max_drawdown_trough_time_ist: Optional[str] = None
    max_drawdown_recovery_time_ist: Optional[str] = None
    recovery_factor: Optional[float] = None
    recovery_factor_status: MetricAvailabilityStatus
    average_drawdown: Optional[float] = Field(default=None, ge=0.0)
    ulcer_index_points: Optional[float] = Field(default=None, ge=0.0)
    ulcer_index_pct: Optional[float] = Field(default=None, ge=0.0)
    current_drawdown: float = Field(..., ge=0.0)
    is_currently_in_drawdown: bool
    largest_loss: Optional[float] = None
    largest_loss_abs: Optional[float] = None
    max_consecutive_losses: int = Field(..., ge=0)
    max_drawdown_duration_bars: int = Field(..., ge=0)
    max_drawdown_duration_seconds: float = Field(..., ge=0.0)
    episodes_count: int = Field(..., ge=0)
    episodes: Tuple[DrawdownEpisode, ...] = ()

    @model_validator(mode="after")
    def _validate_risk_domain(self) -> "DomainRiskMetrics":
        if self.unit_label == "INDEX_POINTS":
            if self.max_drawdown_pct is not None or self.ulcer_index_pct is not None:
                raise ValueError(
                    "MODE_MIXING_POINTS_AND_CURRENCY: monetary percentage risk metrics forbidden in INDEX_POINTS."
                )
        else:
            if self.ulcer_index_points is not None:
                raise ValueError("ulcer_index_points forbidden in INR risk metrics.")
        return self


class RiskSummaryAnalytics(BaseModel):
    """Complete drawdown & tail-loss risk summary segregated per accounting mode."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    accounting_unit_mode: AccountingUnitMode
    provenance_label: str
    is_synthetic_modelled: bool
    points_risk: Optional[DomainRiskMetrics] = None
    inr_risk: Optional[DomainRiskMetrics] = None
    drawdown_timeline: Tuple[DrawdownTimelinePoint, ...] = ()

    @model_validator(mode="after")
    def _validate_risk_sections(self) -> "RiskSummaryAnalytics":
        if self.accounting_unit_mode == AccountingUnitMode.INDEX_POINTS_ONLY:
            if self.points_risk is None or self.inr_risk is not None:
                raise ValueError("MODE_MIXING_POINTS_AND_CURRENCY: INDEX_POINTS_ONLY requires points_risk only.")
        elif self.accounting_unit_mode == AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR:
            if self.points_risk is None or self.inr_risk is None:
                raise ValueError("INDEX_POINTS_AND_EXPLICIT_INR requires both points_risk and inr_risk.")
        else:
            if self.points_risk is not None or self.inr_risk is None:
                raise ValueError("MODE_MIXING: SYNTHETIC_OPTION_INR_ONLY requires inr_risk only.")
        return self


class BucketDomainStats(BaseModel):
    """Domain-pure aggregate statistics reused by time-series & strategy breakdown buckets."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    unit_label: Literal["INDEX_POINTS", "INR"]
    provenance_label: str
    winning_trades: int = Field(..., ge=0)
    losing_trades: int = Field(..., ge=0)
    win_rate: Optional[float] = None
    gross_pnl: float
    total_costs: float
    net_pnl: float
    expectancy: Optional[float] = None
    profit_factor: Optional[float] = None
    profit_factor_status: MetricAvailabilityStatus


class TimeBucketPerformance(BaseModel):
    """Single deterministic IST period (day/week/month/session) performance row."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    bucket_type: Literal["DAILY", "WEEKLY", "MONTHLY", "SESSION"]
    bucket_key: str
    period_start_ist: Optional[str] = None
    period_end_ist: Optional[str] = None
    accounting_unit_mode: AccountingUnitMode
    provenance_label: str
    trades_count: int = Field(..., ge=0)
    partial_exits_count: int = Field(..., ge=0)
    ambiguous_trades_count: int = Field(..., ge=0)
    points_stats: Optional[BucketDomainStats] = None
    inr_stats: Optional[BucketDomainStats] = None

    @model_validator(mode="after")
    def _validate_bucket_domain(self) -> "TimeBucketPerformance":
        if self.accounting_unit_mode == AccountingUnitMode.INDEX_POINTS_ONLY:
            if self.points_stats is None or self.inr_stats is not None:
                raise ValueError("MODE_MIXING_POINTS_AND_CURRENCY: TimeBucket INR stats forbidden in INDEX_POINTS_ONLY.")
        elif self.accounting_unit_mode == AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR:
            if self.points_stats is None or self.inr_stats is None:
                raise ValueError("INDEX_POINTS_AND_EXPLICIT_INR TimeBucket requires both points_stats and inr_stats.")
        else:
            if self.points_stats is not None or self.inr_stats is None:
                raise ValueError("MODE_MIXING: TimeBucket points stats forbidden in SYNTHETIC_OPTION_INR_ONLY.")
        return self


class EquityCurveSnapshot(BaseModel):
    """Normalized chronological equity curve row tagged with IST datetime components."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    timestamp_ist: str
    date_ist: str
    session_ist: MarketSessionBucket
    accounting_unit_mode: AccountingUnitMode
    equity_points: Optional[float] = None
    drawdown_points: Optional[float] = None
    total_equity_inr: Optional[float] = None
    drawdown_inr: Optional[float] = None
    drawdown_pct: Optional[float] = None
    open_trades_count: int = Field(..., ge=0)


class TimeSeriesAnalyticsResult(BaseModel):
    """Deterministic IST time-series breakdown and curves."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    accounting_unit_mode: AccountingUnitMode
    provenance_label: str
    is_synthetic_modelled: bool
    timezone_name: Literal["Asia/Kolkata"] = "Asia/Kolkata"
    aggregation_timestamp_basis: Literal["EXIT_TIME_IST"] = "EXIT_TIME_IST"
    session_timestamp_basis: Literal["ENTRY_TIME_IST"] = "ENTRY_TIME_IST"
    daily: Tuple[TimeBucketPerformance, ...] = ()
    weekly: Tuple[TimeBucketPerformance, ...] = ()
    monthly: Tuple[TimeBucketPerformance, ...] = ()
    session_wise: Tuple[TimeBucketPerformance, ...] = ()
    drawdown_timeline: Tuple[DrawdownTimelinePoint, ...] = ()
    equity_curve: Tuple[EquityCurveSnapshot, ...] = ()
    total_closed_trades_aggregated: int = Field(..., ge=0)
    unclosed_trades_excluded_count: int = Field(..., ge=0)
    reconciliation_matches_totals: bool


class WalkForwardWindowSpec(BaseModel):
    """Strict non-overlapping chronological In-Sample / Out-of-Sample window specification."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    window_id: str = Field(..., min_length=1)
    is_start_ist: datetime
    is_end_ist: datetime
    oos_start_ist: datetime
    oos_end_ist: datetime
    purge_duration_seconds: float = Field(default=0.0, ge=0.0)
    embargo_duration_seconds: float = Field(default=0.0, ge=0.0)

    @model_validator(mode="after")
    def _validate_chronology(self) -> "WalkForwardWindowSpec":
        is_s = parse_ist_datetime(self.is_start_ist, "is_start_ist")
        is_e = parse_ist_datetime(self.is_end_ist, "is_end_ist")
        oos_s = parse_ist_datetime(self.oos_start_ist, "oos_start_ist")
        oos_e = parse_ist_datetime(self.oos_end_ist, "oos_end_ist")
        if is_s >= is_e:
            raise ValueError("WALK_FORWARD_INVALID_WINDOW: is_start_ist must be strictly < is_end_ist.")
        if oos_s < is_e:
            raise ValueError(
                "WALK_FORWARD_LOOKAHEAD_VIOLATION: oos_start_ist must be >= is_end_ist (future leakage forbidden)."
            )
        if oos_s >= oos_e:
            raise ValueError("WALK_FORWARD_INVALID_WINDOW: oos_start_ist must be strictly < oos_end_ist.")
        return self


class WalkForwardWindowResult(BaseModel):
    """Out-of-sample & In-sample chronological evaluation result for one window."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    window_id: str
    is_start_ist: str
    is_end_ist: str
    oos_start_ist: str
    oos_end_ist: str
    purge_duration_seconds: float = Field(..., ge=0.0)
    embargo_duration_seconds: float = Field(..., ge=0.0)
    purged_is_trade_ids: Tuple[str, ...] = ()
    embargoed_oos_trade_ids: Tuple[str, ...] = ()
    is_trades_count: int = Field(..., ge=0)
    oos_trades_count: int = Field(..., ge=0)
    is_status: AnalyticsStatus
    oos_status: AnalyticsStatus
    is_performance: PerformanceSummaryAnalytics
    oos_performance: PerformanceSummaryAnalytics
    oos_degradation_ratio_points: Optional[float] = None
    oos_degradation_ratio_inr: Optional[float] = None
    significance_status: SignificanceStatus
    statistical_significance_claimed: bool = False
    warnings: Tuple[str, ...] = ()


class WalkForwardResult(BaseModel):
    """Aggregate chronological walk-forward & out-of-sample evaluation report."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    accounting_unit_mode: AccountingUnitMode
    provenance_label: str
    is_synthetic_modelled: bool
    window_scheme: Literal["ANCHORED_EXPANDING", "ROLLING", "EXPLICIT_WINDOWS", "IS_OOS_SPLIT"]
    chronological_only: Literal[True] = True
    shuffling_used: Literal[False] = False
    no_lookahead_verified: bool
    min_trades_for_significance: int = Field(..., ge=1)
    windows_count: int = Field(..., ge=0)
    valid_oos_windows_count: int = Field(..., ge=0)
    total_purged_is_trades: int = Field(..., ge=0)
    total_embargoed_oos_trades: int = Field(..., ge=0)
    windows: Tuple[WalkForwardWindowResult, ...] = ()
    aggregate_oos_performance: Optional[PerformanceSummaryAnalytics] = None
    aggregate_oos_significance_status: SignificanceStatus
    statistical_significance_claimed: bool = False
    oos_t_stat_points: Optional[float] = None
    oos_t_stat_inr: Optional[float] = None
    warnings: Tuple[str, ...] = ()


class TradeEvaluationMetadata(BaseModel):
    """Explicit non-inferred strategy/setup/regime metadata for a trade or signal."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ict_smc_setup: Optional[str] = None
    market_regime: Optional[str] = None
    session: Optional[str] = None
    entry_reason: Optional[str] = None


class StrategyBreakdownBucket(BaseModel):
    """Performance grouped strictly by an explicit metadata dimension (`UNKNOWN` when missing)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dimension: Literal[
        "ict_smc_setup",
        "direction",
        "timeframe",
        "market_regime",
        "session",
        "entry_reason",
        "exit_reason",
    ]
    category: str
    accounting_unit_mode: AccountingUnitMode
    provenance_label: str
    trades_count: int = Field(..., ge=0)
    points_stats: Optional[BucketDomainStats] = None
    inr_stats: Optional[BucketDomainStats] = None

    @model_validator(mode="after")
    def _validate_strat_domain(self) -> "StrategyBreakdownBucket":
        if self.accounting_unit_mode == AccountingUnitMode.INDEX_POINTS_ONLY:
            if self.points_stats is None or self.inr_stats is not None:
                raise ValueError("MODE_MIXING_POINTS_AND_CURRENCY: StrategyBucket INR forbidden in INDEX_POINTS_ONLY.")
        elif self.accounting_unit_mode == AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR:
            if self.points_stats is None or self.inr_stats is None:
                raise ValueError("INDEX_POINTS_AND_EXPLICIT_INR StrategyBucket requires both points_stats and inr_stats.")
        else:
            if self.points_stats is not None or self.inr_stats is None:
                raise ValueError("MODE_MIXING: StrategyBucket points forbidden in SYNTHETIC_OPTION_INR_ONLY.")
        return self


class StrategyAnalyticsResult(BaseModel):
    """Deterministic strategy attribution across explicit non-inferred dimensions."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    accounting_unit_mode: AccountingUnitMode
    provenance_label: str
    is_synthetic_modelled: bool
    total_closed_trades: int = Field(..., ge=0)
    ict_score_status: str = "UNAVAILABLE"
    ict_calibration_status: str = "NOT_CALIBRATED"
    by_ict_setup: Tuple[StrategyBreakdownBucket, ...] = ()
    by_direction: Tuple[StrategyBreakdownBucket, ...] = ()
    by_timeframe: Tuple[StrategyBreakdownBucket, ...] = ()
    by_market_regime: Tuple[StrategyBreakdownBucket, ...] = ()
    by_session: Tuple[StrategyBreakdownBucket, ...] = ()
    by_entry_reason: Tuple[StrategyBreakdownBucket, ...] = ()
    by_exit_reason: Tuple[StrategyBreakdownBucket, ...] = ()
    unknown_metadata_counts: Dict[str, int] = Field(default_factory=dict)


class TradeDistributionSummary(BaseModel):
    """Distribution & holding-period statistics strictly bounded by domain."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    accounting_unit_mode: AccountingUnitMode
    total_closed_trades: int = Field(..., ge=0)
    points_quantiles: Optional[Dict[str, Optional[float]]] = None
    inr_quantiles: Optional[Dict[str, Optional[float]]] = None
    exit_reason_counts: Dict[str, int] = Field(default_factory=dict)
    direction_counts: Dict[str, int] = Field(default_factory=dict)
    holding_duration_seconds_summary: Dict[str, Optional[float]] = Field(default_factory=dict)


class RunConfigurationSection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str
    run_output_fingerprint: str
    run_status: SimulationStatus
    execution_mode: str = EXECUTION_MODE
    mode: SimulationMode
    instrument: str
    timeframe: str
    simulator_version: str
    cost_model_version: str
    cost_schedule: CostScheduleVersion
    ambiguity_policy: str
    gap_policy: str


class DatasetProvenanceSection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    dataset_fingerprint: str
    calendar_fingerprint: str
    historical_date_range: str
    replay_run_id: Optional[str] = None
    provenance_label: str
    is_synthetic_modelled: bool
    instrument_multiplier_inr_per_point: Optional[float] = None
    instrument_multiplier_documentation: Optional[str] = None
    provenance_warnings: Tuple[str, ...] = ()


class AccountingModeSection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    accounting_unit_mode: AccountingUnitMode
    monetary_accounting_enabled: bool
    points_unit: Optional[Literal["INDEX_POINTS"]] = None
    currency_unit: Optional[Literal["INR"]] = None


class ReproducibilityMetadata(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    analytics_version: str = ANALYTICS_VERSION
    timezone_name: Literal["Asia/Kolkata"] = "Asia/Kolkata"
    execution_mode: str = EXECUTION_MODE
    run_id: str
    run_output_fingerprint: str
    dataset_fingerprint: str
    calendar_fingerprint: str
    replay_run_id: Optional[str] = None
    report_fingerprint: str


class BacktestAnalyticsReport(BaseModel):
    """Complete reproducible Step 4.4 quantitative evaluation artifact."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    report_id: str
    report_fingerprint: str
    analytics_version: str = ANALYTICS_VERSION
    execution_mode: str = EXECUTION_MODE
    status: AnalyticsStatus
    run_configuration_and_fingerprint: RunConfigurationSection
    dataset_provenance: DatasetProvenanceSection
    accounting_mode: AccountingModeSection
    performance_summary: PerformanceSummaryAnalytics
    risk_summary: RiskSummaryAnalytics
    time_based_breakdown: TimeSeriesAnalyticsResult
    trade_distribution: TradeDistributionSummary
    walk_forward_results: Optional[WalkForwardResult] = None
    strategy_breakdown: StrategyAnalyticsResult
    data_quality_warnings: Tuple[str, ...] = ()
    statistical_limitations: Tuple[str, ...] = ()
    reproducibility_metadata: ReproducibilityMetadata
    created_at_utc: datetime

