"""
AIVOLVE Phase 4, Step 4.7 — Historical Backtest Revalidation Models
Strict PAPER_TRADING_ONLY Pydantic v2 schemas with deterministic provenance,
dataset quality gating, domain isolation, and audit contracts.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.backtesting.analytics_models import BacktestAnalyticsReport
from app.backtesting.configuration import EXECUTION_MODE, IST_ZONE
from app.backtesting.dataset_validation import DatasetQualityStatus
from app.backtesting.robustness_models import (
    BacktestRobustnessReport,
    SampleSizeClassification,
)
from app.backtesting.simulation_models import AccountingUnitMode, SimulationRunResult


REVALIDATION_ENGINE_VERSION = "4.7.0"
REVALIDATION_REPORT_VERSION = "4.7.0-audit"


def parse_ist_datetime(value: datetime | str, field_name: str = "timestamp") -> datetime:
    """Parses a naive/aware datetime or ISO string and normalizes to Asia/Kolkata."""
    dt = datetime.fromisoformat(value) if isinstance(value, str) else value
    if not isinstance(dt, datetime):
        raise ValueError(f"{field_name} must be a valid datetime or ISO string.")
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        return dt.replace(tzinfo=IST_ZONE)
    return dt.astimezone(IST_ZONE)


def deterministic_reval_hash(payload: Any) -> str:
    """Computes a canonical SHA-256 hex digest for reproducible Step 4.7 artifacts."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class EligibilityClassification(str, Enum):
    """Dataset quality-gate classification for Step 4.7 replay eligibility."""

    VERIFIED_FULL_SESSION_ELIGIBLE = "VERIFIED_FULL_SESSION_ELIGIBLE"
    PARTIAL_RESEARCH_ONLY = "PARTIAL_RESEARCH_ONLY"
    REJECTED_QUALITY_GATE = "REJECTED_QUALITY_GATE"
    REJECTED_MIXED_QUALITY = "REJECTED_MIXED_QUALITY"
    GOVERNANCE_LOCKED = "GOVERNANCE_LOCKED"


class RevalidationStatus(str, Enum):
    """Terminal or gate status of a Step 4.7 historical revalidation run."""

    COMPLETED = "COMPLETED"
    COMPLETED_RESEARCH_ONLY_PARTIAL = "COMPLETED_RESEARCH_ONLY_PARTIAL"
    REJECTED_DATASET_QUALITY = "REJECTED_DATASET_QUALITY"
    GOVERNANCE_LOCKOUT = "GOVERNANCE_LOCKOUT"
    NO_ELIGIBLE_SIGNALS = "NO_ELIGIBLE_SIGNALS"


class AuditVerdict(str, Enum):
    """Final Step 4.7 audit report verdict."""

    PASS = "PASS"
    PARTIAL_PASS = "PARTIAL PASS"
    FAIL = "FAIL"


class RevalidationSignalDirection(str, Enum):
    """Exact Phase 2 setup actions evaluated at historical replay timestamps."""

    BUY_CE = "BUY_CE"
    BUY_PE = "BUY_PE"
    WAIT = "WAIT"
    NO_TRADE = "NO_TRADE"


class DatasetTimeframeEligibility(BaseModel):
    """Per-(instrument, timeframe) Step 4.6 dataset quality & session completeness record."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    instrument: str
    timeframe: str
    quality_status: DatasetQualityStatus
    eligibility: EligibilityClassification
    total_bars: int = Field(..., ge=0)
    eligible_complete_bars: int = Field(..., ge=0)
    expected_sessions_count: int = Field(..., ge=0)
    complete_sessions: Tuple[str, ...] = ()
    incomplete_sessions_excluded: Tuple[str, ...] = ()
    missing_intervals_count: int = Field(..., ge=0)
    dataset_fingerprint: str
    provenance_source: str = "step4_6_historical_store"
    date_range_start_ist: Optional[str] = None
    date_range_end_ist: Optional[str] = None
    full_session_claims_allowed: bool
    reasons: Tuple[str, ...] = ()


class DatasetEligibilityDecision(BaseModel):
    """Master Step 4.7 quality-gate decision across required timeframes before replay."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    instrument: str
    primary_timeframe: str
    required_timeframes: Tuple[str, ...]
    optional_timeframes: Tuple[str, ...] = ()
    overall_quality_status: DatasetQualityStatus
    eligibility: EligibilityClassification
    eligible_for_replay: bool
    full_session_claims_allowed: bool
    research_only_flag: bool
    composite_dataset_fingerprint: str
    calendar_fingerprint: str
    common_complete_sessions: Tuple[str, ...] = ()
    excluded_incomplete_sessions: Tuple[str, ...] = ()
    timeframe_records: Tuple[DatasetTimeframeEligibility, ...] = ()
    rejection_reasons: Tuple[str, ...] = ()


class AccountingDomainRunSpec(BaseModel):
    """Configuration for a single isolated Step 4.3 accounting-domain simulation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    domain_mode: AccountingUnitMode
    enabled: bool = True
    starting_capital_inr: Optional[float] = Field(default=None, gt=0.0)
    instrument_multiplier_inr_per_point: Optional[float] = Field(default=None, gt=0.0)
    instrument_multiplier_documentation: Optional[str] = None
    mode_a_margin_fraction: Optional[float] = Field(default=None, gt=0.0, le=1.0)
    quantity_units_points: int = Field(default=1, gt=0)
    synthetic_iv: float = Field(default=0.18, gt=0.01, lt=3.0)
    synthetic_risk_free_rate: float = Field(default=0.065, ge=0.0, le=0.5)
    synthetic_lots: int = Field(default=1, gt=0)
    synthetic_strike_step: int = Field(default=50, gt=0)

    @model_validator(mode="after")
    def _validate_domain_spec(self) -> "AccountingDomainRunSpec":
        if self.domain_mode == AccountingUnitMode.INDEX_POINTS_ONLY:
            if (
                self.starting_capital_inr is not None
                or self.instrument_multiplier_inr_per_point is not None
                or self.instrument_multiplier_documentation is not None
            ):
                raise ValueError(
                    "DOMAIN_ISOLATION_VIOLATION: INDEX_POINTS_ONLY forbids capital/INR multiplier settings."
                )
        elif self.domain_mode == AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR:
            if (
                self.starting_capital_inr is None
                or self.instrument_multiplier_inr_per_point is None
                or not (self.instrument_multiplier_documentation or "").strip()
            ):
                raise ValueError(
                    "INDEX_POINTS_AND_EXPLICIT_INR requires explicit capital, multiplier, and documentation."
                )
        else:
            if (
                self.instrument_multiplier_inr_per_point is not None
                or self.mode_a_margin_fraction is not None
            ):
                raise ValueError(
                    "DOMAIN_ISOLATION_VIOLATION: SYNTHETIC_OPTION_INR_ONLY forbids underlying multiplier/margin."
                )
        return self


class RevalidationConfig(BaseModel):
    """Immutable versioned Step 4.7 Historical Backtest Revalidation configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    revalidation_version: str = REVALIDATION_ENGINE_VERSION
    execution_mode: Literal["PAPER_TRADING_ONLY"] = "PAPER_TRADING_ONLY"
    instrument: str = "NIFTY 50"
    primary_timeframe: str = "5m"
    replay_timeframes: Tuple[str, ...] = ("1h", "15m", "5m", "3m", "1m")
    required_timeframes: Tuple[str, ...] = ("1h", "15m", "5m")
    start_time_ist: Optional[datetime] = None
    end_time_ist: Optional[datetime] = None

    # Dataset quality & session rules
    allow_partial_research_only: bool = False
    exclude_incomplete_sessions: bool = True
    require_identical_timeframe_quality: bool = True
    sensex_governance_approved: bool = False

    # Replay cadence & Phase 2 frozen evaluation inputs (no auto-optimization)
    eval_stride_bars: int = Field(default=1, ge=1, le=50)
    min_warmup_bars_primary: int = Field(default=15, ge=4, le=200)
    min_confluence_score: float = Field(default=70.0, ge=0.0, le=100.0)
    neutral_vix_value: float = Field(default=13.5, gt=0.0, le=100.0)
    max_entry_wait_bars: int = Field(default=2, ge=1, le=20)
    partial_exit_fraction: float = Field(default=0.5, gt=0.0, lt=1.0)
    intraday_square_off: bool = True
    square_off_time_hhmm: str = "15:20"

    # IS/OOS chronological split ratio
    is_ratio: float = Field(default=0.6, gt=0.1, lt=0.95)
    monte_carlo_simulations: int = Field(default=250, ge=25, le=2000)
    monte_carlo_seed: int = 47047

    # Storage paths (strictly isolated under backend/data/backtest/)
    storage_db_path: Optional[str] = None
    governance_ledger_path: Optional[str] = None


class RevalidationSignalRecord(BaseModel):
    """Complete point-in-time Phase 2 + Phase 3 historical decision audit record."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    signal_id: str
    as_of_time_ist: str
    session_date_ist: str
    session_bucket: str
    instrument: str
    primary_timeframe: str
    spot_reference: float = Field(..., gt=0.0)

    # Phase 2 & 3 decision evidence
    signal_direction: RevalidationSignalDirection
    qualification_status: str
    market_regime: str
    phase2_directional_bias: str
    phase2_confluence_score: Optional[float] = None
    phase2_missing_timeframes: Tuple[str, ...] = ()

    # Phase 3 ICT/SMC evidence (score MUST remain UNAVAILABLE / NOT_CALIBRATED)
    phase3_alignment: str
    phase3_ict_score: None = None
    phase3_score_status: Literal["UNAVAILABLE"] = "UNAVAILABLE"
    phase3_calibration_status: Literal["NOT_CALIBRATED"] = "NOT_CALIBRATED"
    phase3_bullish_evidence: Tuple[str, ...] = ()
    phase3_bearish_evidence: Tuple[str, ...] = ()
    phase3_conflicts: Tuple[str, ...] = ()
    source_event_ids: Tuple[str, ...] = ()
    source_replay_report_id: str

    # Trade levels (only populated when actionable BUY_CE / BUY_PE & geometry valid)
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    target_1: Optional[float] = None
    target_2: Optional[float] = None
    reward_risk_ratio: Optional[float] = None

    # Quality, eligibility, and versions
    data_quality_status: str
    entry_eligible: bool
    rejection_reasons: Tuple[str, ...] = ()
    dataset_fingerprint: str
    engine_versions: Dict[str, str]
    config_fingerprint: str

    @model_validator(mode="after")
    def _validate_phase3_and_actionability(self) -> "RevalidationSignalRecord":
        if self.phase3_ict_score is not None:
            raise ValueError("ICT confluence score must remain None (UNAVAILABLE / NOT_CALIBRATED).")
        if self.entry_eligible and self.signal_direction not in (
            RevalidationSignalDirection.BUY_CE,
            RevalidationSignalDirection.BUY_PE,
        ):
            raise ValueError("WAIT or NO_TRADE signals cannot be entry_eligible=True.")
        if self.entry_eligible:
            if (
                self.stop_loss is None
                or self.target_1 is None
                or not math.isfinite(self.stop_loss)
                or not math.isfinite(self.target_1)
            ):
                raise ValueError("Eligible signals require finite stop_loss and target_1.")
        return self


class BreakdownBucketMetrics(BaseModel):
    """Generic breakdown bucket across signals and domain-specific closed trades."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dimension: str
    bucket_key: str
    total_signals: int = Field(..., ge=0)
    buy_ce_count: int = Field(..., ge=0)
    buy_pe_count: int = Field(..., ge=0)
    wait_count: int = Field(..., ge=0)
    no_trade_count: int = Field(..., ge=0)
    eligible_signals: int = Field(..., ge=0)
    closed_trades: int = Field(..., ge=0)
    wins: int = Field(..., ge=0)
    losses: int = Field(..., ge=0)
    win_rate_pct: Optional[float] = None
    net_pnl_points: Optional[float] = None
    net_pnl_inr: Optional[float] = None


class ISOOSSplitEvaluation(BaseModel):
    """Chronological In-Sample vs Out-of-Sample comparison without future leakage."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    accounting_unit_mode: AccountingUnitMode
    split_boundary_ist: Optional[str] = None
    is_period: Optional[str] = None
    oos_period: Optional[str] = None
    is_signals_count: int = Field(..., ge=0)
    oos_signals_count: int = Field(..., ge=0)
    is_closed_trades: int = Field(..., ge=0)
    oos_closed_trades: int = Field(..., ge=0)
    is_win_rate_pct: Optional[float] = None
    oos_win_rate_pct: Optional[float] = None
    is_net_pnl_points: Optional[float] = None
    oos_net_pnl_points: Optional[float] = None
    is_net_pnl_inr: Optional[float] = None
    oos_net_pnl_inr: Optional[float] = None
    no_lookahead_verified: bool = True
    notes: Tuple[str, ...] = ()


class AccountingDomainEvaluation(BaseModel):
    """Complete Step 4.3 + Step 4.4 + Step 4.5 evaluation within one isolated domain."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    domain_mode: AccountingUnitMode
    provenance_label: str
    is_synthetic_modelled: bool
    actual_historical_options_status: Literal["BLOCKED"] = "BLOCKED"
    simulation_run: SimulationRunResult
    analytics_report: BacktestAnalyticsReport
    robustness_report: BacktestRobustnessReport
    is_oos_comparison: ISOOSSplitEvaluation
    sample_size_classification: SampleSizeClassification
    statistical_significance_claimed: Literal[False] = False
    warnings: Tuple[str, ...] = ()


class RevalidationSummaryMetrics(BaseModel):
    """Signal, rejection, exit-reason, and frequency distribution across the revalidation run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sessions_evaluated: int = Field(..., ge=0)
    replay_timestamps_count: int = Field(..., ge=0)
    total_signals_evaluated: int = Field(..., ge=0)
    action_distribution: Dict[str, int]
    trade_frequency_per_session: float = Field(..., ge=0.0)
    no_trade_frequency_pct: float = Field(..., ge=0.0, le=100.0)
    wait_frequency_pct: float = Field(..., ge=0.0, le=100.0)
    eligible_signals_count: int = Field(..., ge=0)
    ineligible_signals_count: int = Field(..., ge=0)
    rejection_reason_distribution: Dict[str, int]
    market_regime_distribution: Dict[str, int]
    entry_reason_distribution: Dict[str, int]
    exit_reason_distribution: Dict[str, int]


class HistoricalRevalidationRunResult(BaseModel):
    """Top-level Step 4.7 historical revalidation output artifact."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    revalidation_id: str
    run_fingerprint: str
    revalidation_version: str = REVALIDATION_ENGINE_VERSION
    execution_mode: Literal["PAPER_TRADING_ONLY"] = "PAPER_TRADING_ONLY"
    status: RevalidationStatus
    actual_historical_options_status: Literal["BLOCKED"] = "BLOCKED"
    config: RevalidationConfig
    eligibility_decision: DatasetEligibilityDecision
    replay_run_id: Optional[str] = None
    evaluated_start_ist: Optional[str] = None
    evaluated_end_ist: Optional[str] = None
    signals: Tuple[RevalidationSignalRecord, ...] = ()
    summary_metrics: RevalidationSummaryMetrics
    domain_evaluations: Dict[str, AccountingDomainEvaluation] = Field(default_factory=dict)
    regime_breakdown: Tuple[BreakdownBucketMetrics, ...] = ()
    session_breakdown: Tuple[BreakdownBucketMetrics, ...] = ()
    direction_breakdown: Tuple[BreakdownBucketMetrics, ...] = ()
    known_limitations: Tuple[str, ...] = ()
    created_at_utc: str


class ProtectedHashCheckRecord(BaseModel):
    """SHA-256 baseline verification entry for one protected non-backtest artifact."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    label: str
    path: str
    expected_sha256: Optional[str] = None
    observed_sha256: Optional[str] = None
    exists: bool
    matched: bool


class RevalidationAuditReport(BaseModel):
    """Complete 17-section Step 4.7 Final Historical Revalidation Audit Report."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    report_id: str
    report_fingerprint: str
    report_version: str = REVALIDATION_REPORT_VERSION
    execution_mode: Literal["PAPER_TRADING_ONLY"] = "PAPER_TRADING_ONLY"
    verdict: AuditVerdict
    verdict_reasons: Tuple[str, ...] = ()

    # Section 1-3: Dataset Matrix, Evaluated Periods, Exclusions
    dataset_eligibility_matrix: Tuple[DatasetTimeframeEligibility, ...] = ()
    instruments_and_periods_evaluated: Tuple[Dict[str, Any], ...] = ()
    verified_and_partial_exclusions: Tuple[Dict[str, Any], ...] = ()

    # Section 4-8: Replay, Signals, Action Distribution, Execution/Cost Summary
    total_replay_sessions: int = Field(..., ge=0)
    total_signals_generated: int = Field(..., ge=0)
    action_distribution: Dict[str, int]
    total_eligible_signals: int = Field(..., ge=0)
    executed_trades_by_domain: Dict[str, int]
    execution_and_cost_summary: Dict[str, Dict[str, Any]]

    # Section 9-14: Domain Performance, Regimes, IS/OOS, Robustness, Sample Size, Limitations
    domain_performance_summary: Dict[str, Dict[str, Any]]
    market_regime_performance: Tuple[BreakdownBucketMetrics, ...] = ()
    is_oos_comparison: Dict[str, ISOOSSplitEvaluation] = Field(default_factory=dict)
    robustness_summary: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    sample_size_classifications: Dict[str, str] = Field(default_factory=dict)
    known_limitations: Tuple[str, ...] = ()

    # Section 15-17: Tests, Hashes, Isolation Evidence
    test_results_summary: Dict[str, Any] = Field(default_factory=dict)
    protected_hash_checks: Tuple[ProtectedHashCheckRecord, ...] = ()
    production_isolation_evidence: Dict[str, Any] = Field(default_factory=dict)
    revalidation_run_ids: Tuple[str, ...] = ()
    created_at_utc: str

