"""
AIVOLVE Phase 4, Step 4.8 — Strategy Performance & Evidence Review Schemas.

Enforces:
- Strict PAPER_TRADING_ONLY research/evidence classification provenance
- Three-way accounting domain isolation (`INDEX_POINTS_ONLY`,
  `INDEX_POINTS_AND_EXPLICIT_INR`, `SYNTHETIC_OPTION_INR_ONLY`)
- Phase 3 ICT/SMC score fixed at None (`UNAVAILABLE / NOT_CALIBRATED`)
- Explicit sample-size governance and no fabricated metadata labels (`UNKNOWN`)
"""

from __future__ import annotations

import hashlib
import json
import math
from enum import Enum
from typing import Any, Dict, Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.backtesting.analytics_models import (
    BucketDomainStats,
    DomainPerformanceMetrics,
    DomainRiskMetrics,
    MetricAvailabilityStatus,
    UNKNOWN_LABEL,
)
from app.backtesting.configuration import EXECUTION_MODE
from app.backtesting.revalidation_models import (
    DatasetTimeframeEligibility,
    ISOOSSplitEvaluation,
    ProtectedHashCheckRecord,
)
from app.backtesting.robustness_models import (
    RobustnessStatus,
    SampleSizeClassification,
    StabilityClassification,
)
from app.backtesting.simulation_models import AccountingUnitMode


STRATEGY_EVIDENCE_ENGINE_VERSION: str = "4.8.0"
RESEARCH_CLASSIFICATION_DISCLAIMER: str = (
    "Research evidence classification only — NOT a live trade recommendation; "
    "no strategy parameters, weights, or risk limits were modified."
)


def deterministic_evidence_hash(payload: Any) -> str:
    """Computes a canonical SHA-256 hex digest for reproducible Step 4.8 artifacts."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _check_finite(model: BaseModel, fields: Tuple[str, ...]) -> None:
    for fname in fields:
        val = getattr(model, fname)
        if val is not None and not math.isfinite(float(val)):
            raise ValueError(f"{fname} must be finite, got {val!r}")


class EvidenceVerdict(str, Enum):
    """Governance evidence classification (research only, never a live recommendation)."""

    STRONG_EVIDENCE = "STRONG_EVIDENCE"
    MODERATE_EVIDENCE = "MODERATE_EVIDENCE"
    WEAK_EVIDENCE = "WEAK_EVIDENCE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    DATA_QUALITY_BLOCKED = "DATA_QUALITY_BLOCKED"


class ReviewClassificationScope(str, Enum):
    """Scope classification for historical evidence eligibility."""

    VERIFIED_RESEARCH_ELIGIBLE = "VERIFIED_RESEARCH_ELIGIBLE"
    PARTIAL_RESEARCH_ONLY = "PARTIAL_RESEARCH_ONLY"
    REJECTED_OR_LOCKED = "REJECTED_OR_LOCKED"


class StrategyReviewConfig(BaseModel):
    """Immutable Step 4.8 evidence-review governance configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    review_version: str = STRATEGY_EVIDENCE_ENGINE_VERSION
    execution_mode: Literal["PAPER_TRADING_ONLY"] = "PAPER_TRADING_ONLY"
    min_trades_sufficient: int = Field(default=30, ge=5)
    min_trades_moderate: int = Field(default=100, ge=10)
    min_trades_strong: int = Field(default=300, ge=20)
    include_partial_research_only: bool = True
    require_positive_oos_expectancy: bool = True
    storage_db_path: Optional[str] = None

    @model_validator(mode="after")
    def _validate_thresholds(self) -> "StrategyReviewConfig":
        if not (self.min_trades_sufficient < self.min_trades_moderate < self.min_trades_strong):
            raise ValueError(
                "Sample thresholds must satisfy min_trades_sufficient < min_trades_moderate < min_trades_strong."
            )
        return self


class DomainRobustnessDigest(BaseModel):
    """Compact domain-isolated summary of Step 4.5 robustness metrics."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    accounting_unit_mode: AccountingUnitMode
    provenance_label: str
    is_synthetic_modelled: bool
    overall_status: RobustnessStatus
    slippage_status: RobustnessStatus
    break_even_slippage_multiplier_points: Optional[float] = None
    break_even_slippage_multiplier_inr: Optional[float] = None
    remains_profitable_at_2x_slippage: Optional[bool] = None
    transaction_cost_status: RobustnessStatus
    break_even_cost_multiplier_inr: Optional[float] = None
    remains_profitable_at_2x_costs_inr: Optional[bool] = None
    regime_robustness_status: RobustnessStatus
    parameter_sensitivity_status: RobustnessStatus
    parameter_stability: StabilityClassification
    auto_optimization_performed: Literal[False] = False
    strategy_config_modified: Literal[False] = False
    oos_status: RobustnessStatus
    oos_no_lookahead_verified: bool
    monte_carlo_status: RobustnessStatus
    monte_carlo_iterations: int = Field(..., ge=0)
    mc_probability_positive_net_pnl: Optional[float] = None
    mc_p05_net_pnl_points: Optional[float] = None
    mc_p50_net_pnl_points: Optional[float] = None
    mc_p95_net_pnl_points: Optional[float] = None
    mc_p05_net_pnl_inr: Optional[float] = None
    mc_p50_net_pnl_inr: Optional[float] = None
    mc_p95_net_pnl_inr: Optional[float] = None
    mc_p95_max_drawdown_points: Optional[float] = None
    mc_p95_max_drawdown_inr: Optional[float] = None
    sample_size_classification: SampleSizeClassification
    statistical_significance_claimed: Literal[False] = False

    @model_validator(mode="after")
    def _validate_domain_purity(self) -> "DomainRobustnessDigest":
        if self.accounting_unit_mode == AccountingUnitMode.INDEX_POINTS_ONLY:
            if any(
                v is not None
                for v in (
                    self.break_even_slippage_multiplier_inr,
                    self.break_even_cost_multiplier_inr,
                    self.remains_profitable_at_2x_costs_inr,
                    self.mc_p05_net_pnl_inr,
                    self.mc_p50_net_pnl_inr,
                    self.mc_p95_net_pnl_inr,
                    self.mc_p95_max_drawdown_inr,
                )
            ):
                raise ValueError("DOMAIN_ISOLATION_VIOLATION: INR MC/cost fields forbidden in INDEX_POINTS_ONLY.")
        elif self.accounting_unit_mode == AccountingUnitMode.SYNTHETIC_OPTION_INR_ONLY:
            if any(
                v is not None
                for v in (
                    self.break_even_slippage_multiplier_points,
                    self.mc_p05_net_pnl_points,
                    self.mc_p50_net_pnl_points,
                    self.mc_p95_net_pnl_points,
                    self.mc_p95_max_drawdown_points,
                )
            ):
                raise ValueError("DOMAIN_ISOLATION_VIOLATION: Points fields forbidden in SYNTHETIC_OPTION_INR_ONLY.")
        return self


class DomainPerformanceEvidence(BaseModel):
    """Consolidated Step 4.4 + Step 4.5 + Step 4.7 evidence inside ONE isolated accounting domain."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    accounting_unit_mode: AccountingUnitMode
    provenance_label: str
    is_synthetic_modelled: bool
    actual_historical_options_status: Literal["BLOCKED"] = "BLOCKED"
    eligible_runs_count: int = Field(..., ge=0)
    revalidation_run_ids: Tuple[str, ...] = ()
    sessions_evaluated: int = Field(..., ge=0)
    total_signals: int = Field(..., ge=0)
    trades_opened: int = Field(..., ge=0)
    trades_closed: int = Field(..., ge=0)
    trades_rejected: int = Field(..., ge=0)
    trade_frequency_per_session: float = Field(..., ge=0.0)
    max_consecutive_wins: int = Field(..., ge=0)
    max_consecutive_losses: int = Field(..., ge=0)
    average_holding_duration_minutes: Optional[float] = Field(default=None, ge=0.0)
    reconciliation_verified: bool
    instrument_multiplier_inr_per_point: Optional[float] = None
    instrument_multiplier_documentation: Optional[str] = None
    points_metrics: Optional[DomainPerformanceMetrics] = None
    inr_metrics: Optional[DomainPerformanceMetrics] = None
    points_risk: Optional[DomainRiskMetrics] = None
    inr_risk: Optional[DomainRiskMetrics] = None
    is_oos_comparisons: Tuple[ISOOSSplitEvaluation, ...] = ()
    robustness_digests: Tuple[DomainRobustnessDigest, ...] = ()
    sample_size_classification: SampleSizeClassification
    statistical_significance_claimed: Literal[False] = False
    verdict: EvidenceVerdict
    reasons: Tuple[str, ...] = ()
    warnings: Tuple[str, ...] = ()

    @model_validator(mode="after")
    def _validate_domain_segregation(self) -> "DomainPerformanceEvidence":
        if self.accounting_unit_mode == AccountingUnitMode.INDEX_POINTS_ONLY:
            if (
                self.is_synthetic_modelled
                or self.inr_metrics is not None
                or self.inr_risk is not None
                or self.instrument_multiplier_inr_per_point is not None
            ):
                raise ValueError("DOMAIN_ISOLATION_VIOLATION: INR metrics/multiplier forbidden in INDEX_POINTS_ONLY.")
        elif self.accounting_unit_mode == AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR:
            if self.is_synthetic_modelled:
                raise ValueError("INDEX_POINTS_AND_EXPLICIT_INR cannot be marked synthetic.")
            if (self.points_metrics is None) != (self.inr_metrics is None):
                raise ValueError("INDEX_POINTS_AND_EXPLICIT_INR must keep both points_metrics and inr_metrics paired.")
        else:
            if (
                not self.is_synthetic_modelled
                or self.provenance_label != "SYNTHETIC_MODELLED_OPTION_PNL"
                or self.points_metrics is not None
                or self.points_risk is not None
            ):
                raise ValueError("DOMAIN_ISOLATION_VIOLATION: SYNTHETIC_OPTION_INR_ONLY provenance/unit mismatch.")
        if (
            self.sample_size_classification == SampleSizeClassification.INSUFFICIENT_SAMPLE
            and self.verdict in (EvidenceVerdict.STRONG_EVIDENCE, EvidenceVerdict.MODERATE_EVIDENCE)
        ):
            raise ValueError("GOVERNANCE_VIOLATION: INSUFFICIENT_SAMPLE cannot receive MODERATE or STRONG verdict.")
        return self


class BreakdownEvidenceRow(BaseModel):
    """Cross-domain breakdown row keeping all three accounting domains strictly separate."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dimension: Literal[
        "market_regime",
        "trading_session",
        "instrument",
        "timeframe",
        "direction",
        "ict_smc_setup",
        "entry_reason",
        "exit_reason",
    ]
    bucket_key: str
    total_signals: int = Field(..., ge=0)
    buy_ce_count: int = Field(..., ge=0)
    buy_pe_count: int = Field(..., ge=0)
    wait_count: int = Field(..., ge=0)
    no_trade_count: int = Field(..., ge=0)
    eligible_signals: int = Field(..., ge=0)
    closed_trades_points_domain: int = Field(..., ge=0)
    closed_trades_explicit_inr_domain: int = Field(..., ge=0)
    closed_trades_synthetic_option_domain: int = Field(..., ge=0)
    points_stats: Optional[BucketDomainStats] = None
    explicit_inr_points_stats: Optional[BucketDomainStats] = None
    explicit_inr_stats: Optional[BucketDomainStats] = None
    synthetic_option_inr_stats: Optional[BucketDomainStats] = None
    missing_metadata_flag: bool = False
    sample_size_classification: SampleSizeClassification
    statistical_significance_claimed: Literal[False] = False
    verdict: EvidenceVerdict
    reasons: Tuple[str, ...] = ()

    @model_validator(mode="after")
    def _validate_bucket_domains(self) -> "BreakdownEvidenceRow":
        if self.points_stats is not None and self.points_stats.unit_label != "INDEX_POINTS":
            raise ValueError("points_stats must use INDEX_POINTS.")
        if self.explicit_inr_stats is not None and self.explicit_inr_stats.unit_label != "INR":
            raise ValueError("explicit_inr_stats must use INR.")
        if self.synthetic_option_inr_stats is not None:
            if (
                self.synthetic_option_inr_stats.unit_label != "INR"
                or self.synthetic_option_inr_stats.provenance_label != "SYNTHETIC_MODELLED_OPTION_PNL"
            ):
                raise ValueError("synthetic_option_inr_stats must preserve SYNTHETIC_MODELLED_OPTION_PNL.")
        return self


class ICTPillarEvidenceSummary(BaseModel):
    """Evidence summary for one of the 8 ICT/SMC & MTF pillars without calibrated scoring."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    pillar_name: Literal[
        "LIQUIDITY_SWEEPS",
        "BOS",
        "CHOCH_MSS",
        "ORDER_BLOCKS",
        "FVG_IFVG",
        "PREMIUM_DISCOUNT",
        "INDUCEMENT",
        "MTF_CONFLUENCE",
    ]
    events_observed_count: int = Field(..., ge=0)
    bullish_events_count: int = Field(..., ge=0)
    bearish_events_count: int = Field(..., ge=0)
    conflicts_observed_count: int = Field(..., ge=0)
    signals_present_count: int = Field(..., ge=0)
    eligible_signals_present_count: int = Field(..., ge=0)
    status_breakdown: Dict[str, int] = Field(default_factory=dict)
    closed_trades_count: int = Field(..., ge=0)
    points_stats: Optional[BucketDomainStats] = None
    explicit_inr_stats: Optional[BucketDomainStats] = None
    synthetic_option_inr_stats: Optional[BucketDomainStats] = None
    ict_score: None = None
    ict_score_status: Literal["UNAVAILABLE"] = "UNAVAILABLE"
    ict_calibration_status: Literal["NOT_CALIBRATED"] = "NOT_CALIBRATED"
    profitability_claimed: Literal[False] = False
    sample_size_classification: SampleSizeClassification
    verdict: EvidenceVerdict
    reasons: Tuple[str, ...] = ()


class ICTSMCEvidenceReviewResult(BaseModel):
    """Aggregate ICT/SMC pillar review guaranteeing score stays UNAVAILABLE / NOT_CALIBRATED."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    total_signals_inspected: int = Field(..., ge=0)
    total_eligible_signals_inspected: int = Field(..., ge=0)
    alignment_distribution: Dict[str, int] = Field(default_factory=dict)
    conflict_type_distribution: Dict[str, int] = Field(default_factory=dict)
    pillars: Tuple[ICTPillarEvidenceSummary, ...] = ()
    ict_score: None = None
    ict_score_status: Literal["UNAVAILABLE"] = "UNAVAILABLE"
    ict_calibration_status: Literal["NOT_CALIBRATED"] = "NOT_CALIBRATED"
    weights_or_thresholds_invented: Literal[False] = False
    verdict: EvidenceVerdict
    reasons: Tuple[str, ...] = ()


class SignalQualityReviewResult(BaseModel):
    """Audit of Phase 2 + Phase 3 signal behavior, eligibility funnel, and no-lookahead integrity."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    total_signals: int = Field(..., ge=0)
    action_distribution: Dict[str, int] = Field(default_factory=dict)
    eligible_signals: int = Field(..., ge=0)
    ineligible_signals: int = Field(..., ge=0)
    qualification_rate_pct: float = Field(..., ge=0.0, le=100.0)
    no_trade_rate_pct: float = Field(..., ge=0.0, le=100.0)
    wait_rate_pct: float = Field(..., ge=0.0, le=100.0)
    rejection_reason_distribution: Dict[str, int] = Field(default_factory=dict)
    entry_reason_distribution: Dict[str, int] = Field(default_factory=dict)
    exit_reason_distribution: Dict[str, int] = Field(default_factory=dict)
    missing_metadata_counts: Dict[str, int] = Field(default_factory=dict)
    executed_trades_count_points: int = Field(..., ge=0)
    unexecuted_eligible_signals_count: int = Field(..., ge=0)
    chronological_no_lookahead_verified: bool
    chronology_violations_count: int = Field(..., ge=0)
    verdict: EvidenceVerdict
    reasons: Tuple[str, ...] = ()


class DimensionAssessment(BaseModel):
    """Explicit governance assessment for a review dimension with verdict and reasons."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    area: str
    verdict: EvidenceVerdict
    sample_size_classification: SampleSizeClassification
    statistical_significance_claimed: Literal[False] = False
    reasons: Tuple[str, ...] = ()
    limitations: Tuple[str, ...] = ()


class StrategyVerdictSummary(BaseModel):
    """Master Step 4.8 strategy evidence verdict without optimization or live claims."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    overall_verdict: EvidenceVerdict
    overall_sample_size: SampleSizeClassification
    statistical_significance_claimed: Literal[False] = False
    research_classification_disclaimer: str = RESEARCH_CLASSIFICATION_DISCLAIMER
    auto_optimization_performed: Literal[False] = False
    strategy_parameters_modified: Literal[False] = False
    overall_reasons: Tuple[str, ...] = ()
    instrument_assessments: Tuple[DimensionAssessment, ...] = ()
    regime_assessment: DimensionAssessment
    session_assessment: DimensionAssessment
    ict_smc_assessment: DimensionAssessment
    risk_and_drawdown_assessment: DimensionAssessment
    data_quality_limitations: Tuple[str, ...] = ()
    sample_size_limitations: Tuple[str, ...] = ()


class StrategyEvidenceReviewReport(BaseModel):
    """Complete immutable Step 4.8 Strategy Performance & Evidence Review artifact."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    review_id: str
    review_fingerprint: str
    review_version: str = STRATEGY_EVIDENCE_ENGINE_VERSION
    execution_mode: Literal["PAPER_TRADING_ONLY"] = "PAPER_TRADING_ONLY"
    research_classification_disclaimer: str = RESEARCH_CLASSIFICATION_DISCLAIMER
    config: StrategyReviewConfig
    data_sources: Dict[str, Any] = Field(default_factory=dict)
    dataset_eligibility_matrix: Tuple[DatasetTimeframeEligibility, ...] = ()
    revalidation_runs_summary: Tuple[Dict[str, Any], ...] = ()
    domain_evidence: Dict[str, DomainPerformanceEvidence] = Field(default_factory=dict)
    regime_evidence: Tuple[BreakdownEvidenceRow, ...] = ()
    session_evidence: Tuple[BreakdownEvidenceRow, ...] = ()
    instrument_evidence: Tuple[BreakdownEvidenceRow, ...] = ()
    timeframe_evidence: Tuple[BreakdownEvidenceRow, ...] = ()
    direction_evidence: Tuple[BreakdownEvidenceRow, ...] = ()
    ict_setup_evidence: Tuple[BreakdownEvidenceRow, ...] = ()
    entry_reason_evidence: Tuple[BreakdownEvidenceRow, ...] = ()
    exit_reason_evidence: Tuple[BreakdownEvidenceRow, ...] = ()
    ict_smc_evidence: ICTSMCEvidenceReviewResult
    signal_quality: SignalQualityReviewResult
    verdict_summary: StrategyVerdictSummary
    known_limitations: Tuple[str, ...] = ()
    test_results_summary: Dict[str, Any] = Field(default_factory=dict)
    protected_hash_checks: Tuple[ProtectedHashCheckRecord, ...] = ()
    production_isolation_evidence: Dict[str, Any] = Field(default_factory=dict)
    created_at_utc: str

