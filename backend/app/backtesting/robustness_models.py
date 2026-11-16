"""
AIVOLVE Phase 4 Step 4.5 — Canonical Schemas & Shared Counterfactual Helpers
for Backtest Robustness & Stress Testing.

Enforces:
- PAPER_TRADING_ONLY research & validation provenance
- Strict three-way AccountingUnitMode segregation:
  1. INDEX_POINTS_ONLY
  2. INDEX_POINTS_AND_EXPLICIT_INR
  3. SYNTHETIC_OPTION_INR_ONLY
- No invented INR charges in pure index-point mode
- No auto-optimization or best-parameter selection in sensitivity analysis
- Explicit disclaimers that Monte Carlo & robustness outputs are research estimates,
  not statistical proof or future performance guarantees
"""

from __future__ import annotations

import math
from datetime import datetime
from enum import Enum
from typing import Callable, Dict, List, Literal, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.backtesting.analytics_models import (
    ANALYTICS_VERSION,
    AccountingModeSection,
    DatasetProvenanceSection,
    DomainPerformanceMetrics,
    DomainRiskMetrics,
    MetricAvailabilityStatus,
    PerformanceSummaryAnalytics,
    RiskSummaryAnalytics,
    RunConfigurationSection,
    WalkForwardResult,
    domain_has_inr,
    domain_has_points,
    parse_ist_datetime,
    validate_run_domain_integrity,
)
from app.backtesting.configuration import EXECUTION_MODE
from app.backtesting.performance_analytics import PerformanceAnalyticsEngine
from app.backtesting.risk_analytics import RiskAnalyticsEngine, is_clean_winner, sort_closed_trades
from app.backtesting.simulation_models import (
    AccountingUnitMode,
    CostBreakdown,
    CostScheduleVersion,
    EquityCurvePoint,
    FillRecord,
    OrderSide,
    PortfolioSummary,
    SimulationMode,
    SimulationRunResult,
    TradeLifecycleState,
    TradeRecord,
)

ROBUSTNESS_VERSION: str = "4.5.0"


class RobustnessStatus(str, Enum):
    COMPLETED = "COMPLETED"
    NO_TRADES = "NO_TRADES"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    NOT_APPLICABLE_IN_DOMAIN = "NOT_APPLICABLE_IN_DOMAIN"
    RUN_NOT_COMPLETED = "RUN_NOT_COMPLETED"


class SampleSizeClassification(str, Enum):
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
    LIMITED_EVIDENCE = "LIMITED_EVIDENCE"
    MODERATE_SAMPLE = "MODERATE_SAMPLE"
    LARGER_SAMPLE = "LARGER_SAMPLE"


class RobustnessRegimeBucket(str, Enum):
    TRENDING = "TRENDING"
    RANGING = "RANGING"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    LOW_VOLATILITY = "LOW_VOLATILITY"
    UNKNOWN_OR_INSUFFICIENT_DATA = "UNKNOWN_OR_INSUFFICIENT_DATA"


class StabilityClassification(str, Enum):
    STABLE = "STABLE"
    MODERATELY_SENSITIVE = "MODERATELY_SENSITIVE"
    UNSTABLE = "UNSTABLE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class MonteCarloMode(str, Enum):
    BOOTSTRAP_WITH_REPLACEMENT = "BOOTSTRAP_WITH_REPLACEMENT"
    PERMUTATION_WITHOUT_REPLACEMENT = "PERMUTATION_WITHOUT_REPLACEMENT"


def _check_finite_fields(model: BaseModel, fields: Sequence[str]) -> None:
    for fname in fields:
        val = getattr(model, fname)
        if val is not None and not math.isfinite(float(val)):
            raise ValueError(f"{fname} must be finite, got {val!r}")


def _validate_positive_multipliers(multipliers: Sequence[float], label: str) -> Tuple[float, ...]:
    if not multipliers:
        raise ValueError(f"{label} multipliers must be non-empty.")
    cleaned: List[float] = []
    seen = set()
    for m in multipliers:
        fm = float(m)
        if not math.isfinite(fm) or fm <= 0.0:
            raise ValueError(f"{label} multiplier must be finite and > 0.0, got {m!r}.")
        rounded_key = round(fm, 9)
        if rounded_key not in seen:
            seen.add(rounded_key)
            cleaned.append(fm)
    return tuple(sorted(cleaned))


class RobustnessDomainMetrics(BaseModel):
    """Domain-pure performance & drawdown summary inside one AccountingUnitMode."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    unit_label: Literal["INDEX_POINTS", "INR"]
    provenance_label: str
    total_closed_trades: int = Field(..., ge=0)
    winning_trades: int = Field(..., ge=0)
    losing_trades: int = Field(..., ge=0)
    win_rate: Optional[float] = None
    win_rate_pct: Optional[float] = None
    gross_pnl: float
    total_costs: float
    net_pnl: float
    expectancy: Optional[float] = None
    profit_factor: Optional[float] = None
    profit_factor_status: MetricAvailabilityStatus
    max_drawdown: float = Field(..., ge=0.0)
    max_drawdown_pct: Optional[float] = Field(default=None, ge=0.0)
    recovery_factor: Optional[float] = None
    recovery_factor_status: MetricAvailabilityStatus
    net_return_pct: Optional[float] = None
    ending_equity: Optional[float] = None

    @model_validator(mode="after")
    def _validate_domain(self) -> "RobustnessDomainMetrics":
        _check_finite_fields(
            self,
            (
                "win_rate",
                "win_rate_pct",
                "gross_pnl",
                "total_costs",
                "net_pnl",
                "expectancy",
                "profit_factor",
                "max_drawdown",
                "max_drawdown_pct",
                "recovery_factor",
                "net_return_pct",
                "ending_equity",
            ),
        )
        if self.unit_label == "INDEX_POINTS":
            if self.max_drawdown_pct is not None or self.net_return_pct is not None:
                raise ValueError(
                    "MODE_MIXING_POINTS_AND_CURRENCY: percentage return/drawdown fields "
                    "are forbidden in INDEX_POINTS metrics."
                )
        return self


class CostComponentsBreakdown(BaseModel):
    """Itemized INR fee components (statutory charges separated from slippage)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    brokerage_inr: float = Field(..., ge=0.0)
    stt_inr: float = Field(..., ge=0.0)
    exchange_txn_charges_inr: float = Field(..., ge=0.0)
    gst_inr: float = Field(..., ge=0.0)
    sebi_charges_inr: float = Field(..., ge=0.0)
    stamp_duty_inr: float = Field(..., ge=0.0)
    total_statutory_charges_inr: float = Field(..., ge=0.0)
    total_brokerage_and_statutory_inr: float = Field(..., ge=0.0)
    slippage_cost_inr: float = Field(..., ge=0.0)
    total_costs_inr: float = Field(..., ge=0.0)

    @model_validator(mode="after")
    def _validate_finite(self) -> "CostComponentsBreakdown":
        _check_finite_fields(
            self,
            (
                "brokerage_inr",
                "stt_inr",
                "exchange_txn_charges_inr",
                "gst_inr",
                "sebi_charges_inr",
                "stamp_duty_inr",
                "total_statutory_charges_inr",
                "total_brokerage_and_statutory_inr",
                "slippage_cost_inr",
                "total_costs_inr",
            ),
        )
        return self


class SlippageStressConfig(BaseModel):
    """Configuration for deterministic slippage stress multipliers."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    multipliers: Tuple[float, ...] = (1.0, 1.25, 1.5, 2.0, 3.0)

    @model_validator(mode="after")
    def _validate_cfg(self) -> "SlippageStressConfig":
        cleaned = _validate_positive_multipliers(self.multipliers, "SlippageStressConfig")
        object.__setattr__(self, "multipliers", cleaned)
        return self


class SlippageScenarioResult(BaseModel):
    """Single slippage stress multiplier evaluation result."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    multiplier: float = Field(..., gt=0.0)
    is_baseline: bool
    accounting_unit_mode: AccountingUnitMode
    provenance_label: str
    slippage_unit: Literal["INDEX_POINTS", "INR_PER_OPTION_UNIT"]
    effective_slippage_per_unit: float = Field(..., ge=0.0)
    points_metrics: Optional[RobustnessDomainMetrics] = None
    inr_metrics: Optional[RobustnessDomainMetrics] = None
    total_slippage_points: Optional[float] = Field(default=None, ge=0.0)
    total_slippage_cost_inr: Optional[float] = Field(default=None, ge=0.0)
    net_pnl_delta_points_vs_baseline: Optional[float] = None
    net_pnl_delta_inr_vs_baseline: Optional[float] = None
    net_pnl_retention_ratio_points: Optional[float] = None
    net_pnl_retention_ratio_inr: Optional[float] = None

    @model_validator(mode="after")
    def _validate_domain(self) -> "SlippageScenarioResult":
        um = self.accounting_unit_mode
        if um == AccountingUnitMode.INDEX_POINTS_ONLY:
            if self.points_metrics is None or self.inr_metrics is not None or self.total_slippage_cost_inr is not None:
                raise ValueError("MODE_MIXING_POINTS_AND_CURRENCY: INR slippage metrics forbidden in INDEX_POINTS_ONLY.")
        elif um == AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR:
            if self.points_metrics is None or self.inr_metrics is None:
                raise ValueError("INDEX_POINTS_AND_EXPLICIT_INR requires both points_metrics and inr_metrics.")
        else:
            if self.points_metrics is not None or self.inr_metrics is None or self.total_slippage_points is not None:
                raise ValueError("MODE_MIXING: Points slippage metrics forbidden in SYNTHETIC_OPTION_INR_ONLY.")
        return self


class SlippageStressResult(BaseModel):
    """Complete Module B slippage stress evaluation output."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: RobustnessStatus
    accounting_unit_mode: AccountingUnitMode
    provenance_label: str
    is_synthetic_modelled: bool
    config: SlippageStressConfig
    baseline_gross_pnl_points: Optional[float] = None
    baseline_gross_pnl_inr: Optional[float] = None
    baseline_net_pnl_points: Optional[float] = None
    baseline_net_pnl_inr: Optional[float] = None
    break_even_slippage_multiplier_points: Optional[float] = None
    break_even_slippage_multiplier_inr: Optional[float] = None
    remains_profitable_at_2x_points: Optional[bool] = None
    remains_profitable_at_2x_inr: Optional[bool] = None
    remains_profitable_at_3x_points: Optional[bool] = None
    remains_profitable_at_3x_inr: Optional[bool] = None
    scenarios: Tuple[SlippageScenarioResult, ...] = ()
    warnings: Tuple[str, ...] = ()
    assumptions: Tuple[str, ...] = ()


class TransactionCostStressConfig(BaseModel):
    """Configuration for deterministic non-slippage transaction cost stress multipliers."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    multipliers: Tuple[float, ...] = (1.0, 1.25, 1.5, 2.0)

    @model_validator(mode="after")
    def _validate_cfg(self) -> "TransactionCostStressConfig":
        cleaned = _validate_positive_multipliers(self.multipliers, "TransactionCostStressConfig")
        object.__setattr__(self, "multipliers", cleaned)
        return self


class TransactionCostScenarioResult(BaseModel):
    """Single fee-schedule stress multiplier result with itemized INR breakdown."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    multiplier: float = Field(..., gt=0.0)
    is_baseline: bool
    accounting_unit_mode: AccountingUnitMode
    provenance_label: str
    cost_components: Optional[CostComponentsBreakdown] = None
    points_metrics: Optional[RobustnessDomainMetrics] = None
    inr_metrics: Optional[RobustnessDomainMetrics] = None
    net_pnl_delta_inr_vs_baseline: Optional[float] = None
    net_pnl_retention_ratio_inr: Optional[float] = None

    @model_validator(mode="after")
    def _validate_domain(self) -> "TransactionCostScenarioResult":
        um = self.accounting_unit_mode
        if um == AccountingUnitMode.INDEX_POINTS_ONLY:
            if self.inr_metrics is not None or self.cost_components is not None:
                raise ValueError("MODE_MIXING_POINTS_AND_CURRENCY: INR cost breakdown forbidden in INDEX_POINTS_ONLY.")
        elif um == AccountingUnitMode.INDEX_POINTS_AND_EXPLICIT_INR:
            if self.points_metrics is None or self.inr_metrics is None or self.cost_components is None:
                raise ValueError("INDEX_POINTS_AND_EXPLICIT_INR requires points, INR metrics, and cost_components.")
        else:
            if self.points_metrics is not None or self.inr_metrics is None or self.cost_components is None:
                raise ValueError("SYNTHETIC_OPTION_INR_ONLY requires INR metrics and cost_components with no points.")
        return self


class TransactionCostStressResult(BaseModel):
    """Complete Module C transaction-cost sensitivity evaluation output."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: RobustnessStatus
    accounting_unit_mode: AccountingUnitMode
    provenance_label: str
    is_synthetic_modelled: bool
    monetary_charges_applicable: bool
    gst_rate_preserved: Optional[float] = None
    config: TransactionCostStressConfig
    break_even_cost_multiplier_inr: Optional[float] = None
    remains_profitable_at_2x_inr: Optional[bool] = None
    scenarios: Tuple[TransactionCostScenarioResult, ...] = ()
    warnings: Tuple[str, ...] = ()
    assumptions: Tuple[str, ...] = ()


class MarketRegimeConfig(BaseModel):
    """Deterministic causal market regime classification thresholds."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    adx_period: int = Field(default=14, ge=2, le=100)
    atr_period: int = Field(default=14, ge=2, le=100)
    adx_trend_threshold: float = Field(default=20.0, gt=0.0)
    adx_range_threshold: float = Field(default=18.0, gt=0.0)
    volatility_lookback_bars: int = Field(default=50, ge=15, le=500)
    high_vol_atr_ratio_threshold: float = Field(default=1.25, gt=1.0)
    low_vol_atr_ratio_threshold: float = Field(default=0.80, gt=0.0, lt=1.0)
    min_trades_per_bucket: int = Field(default=5, ge=1)

    @model_validator(mode="after")
    def _validate_thresholds(self) -> "MarketRegimeConfig":
        if self.adx_range_threshold > self.adx_trend_threshold:
            raise ValueError(
                f"adx_range_threshold ({self.adx_range_threshold}) cannot exceed adx_trend_threshold ({self.adx_trend_threshold})."
            )
        return self


class MarketRegimeBucketResult(BaseModel):
    """Performance metrics evaluated for one market regime bucket."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    regime: RobustnessRegimeBucket
    classification_source: Literal[
        "EXPLICIT_METADATA",
        "REPLAY_ARTIFACT",
        "CAUSAL_OHLCV_INDICATORS",
        "UNKNOWN_MISSING",
    ]
    trades_count: int = Field(..., ge=0)
    is_sparse_bucket: bool
    points_metrics: Optional[RobustnessDomainMetrics] = None
    inr_metrics: Optional[RobustnessDomainMetrics] = None
    trade_ids: Tuple[str, ...] = ()


class MarketRegimeRobustnessResult(BaseModel):
    """Complete Module D regime-wise robustness evaluation output."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: RobustnessStatus
    accounting_unit_mode: AccountingUnitMode
    provenance_label: str
    is_synthetic_modelled: bool
    config: MarketRegimeConfig
    total_closed_trades: int = Field(..., ge=0)
    classified_trades_count: int = Field(..., ge=0)
    unknown_or_insufficient_trades_count: int = Field(..., ge=0)
    no_future_bar_leakage_verified: bool
    buckets: Tuple[MarketRegimeBucketResult, ...] = ()
    best_regime_by_net_pnl: Optional[RobustnessRegimeBucket] = None
    worst_regime_by_net_pnl: Optional[RobustnessRegimeBucket] = None
    warnings: Tuple[str, ...] = ()


class ParameterVariationSpec(BaseModel):
    """Single explicitly recorded parameter perturbation (never auto-optimized)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    variation_id: str = Field(..., min_length=1)
    label: str = Field(..., min_length=1)
    parameter_name: Literal[
        "stop_loss",
        "target_1",
        "target_2",
        "partial_exit_fraction",
        "max_entry_wait_bars",
        "slippage_per_unit",
        "intraday_square_off",
    ]
    factor: Optional[float] = Field(default=None, gt=0.0)
    override_value: Optional[float | int | bool | str] = None
    notes: str = ""

    @model_validator(mode="after")
    def _validate_spec(self) -> "ParameterVariationSpec":
        if self.factor is not None and not math.isfinite(self.factor):
            raise ValueError(f"factor must be finite, got {self.factor!r}")
        if self.factor is None and self.override_value is None:
            raise ValueError("ParameterVariationSpec requires either factor or override_value.")
        return self


class ParameterVariantResult(BaseModel):
    """Evaluation output for a single controlled parameter variant."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    variation_id: str
    label: str
    is_baseline: bool
    parameter_name: str
    parameter_value_description: str
    simulated_run_id: str
    accounting_unit_mode: AccountingUnitMode
    provenance_label: str
    points_metrics: Optional[RobustnessDomainMetrics] = None
    inr_metrics: Optional[RobustnessDomainMetrics] = None
    net_pnl_delta_points_vs_baseline: Optional[float] = None
    net_pnl_delta_inr_vs_baseline: Optional[float] = None


class ParameterSensitivityResult(BaseModel):
    """Complete Module E parameter sensitivity report (anti-overfitting guaranteed)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: RobustnessStatus
    accounting_unit_mode: AccountingUnitMode
    provenance_label: str
    is_synthetic_modelled: bool
    evaluation_mode: Literal["CONTROLLED_RESIMULATION", "PRECOMPUTED_RUNS", "NOT_EVALUATED"]
    stability_classification: StabilityClassification
    auto_optimization_performed: Literal[False] = False
    best_parameter_selected: Literal[None] = None
    strategy_config_modified: Literal[False] = False
    variants_evaluated: int = Field(..., ge=0)
    sign_flips_vs_baseline_count: int = Field(..., ge=0)
    relative_net_pnl_dispersion_points: Optional[float] = None
    relative_net_pnl_dispersion_inr: Optional[float] = None
    max_drawdown_expansion_ratio_points: Optional[float] = None
    max_drawdown_expansion_ratio_inr: Optional[float] = None
    variants: Tuple[ParameterVariantResult, ...] = ()
    warnings: Tuple[str, ...] = ()


class OutOfSampleRobustnessResult(BaseModel):
    """Complete Module F chronological out-of-sample stability evaluation output."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: RobustnessStatus
    accounting_unit_mode: AccountingUnitMode
    provenance_label: str
    is_synthetic_modelled: bool
    walk_forward_result: Optional[WalkForwardResult] = None
    windows_count: int = Field(..., ge=0)
    valid_oos_windows_count: int = Field(..., ge=0)
    total_is_trades: int = Field(..., ge=0)
    total_oos_trades: int = Field(..., ge=0)
    is_aggregate_points: Optional[RobustnessDomainMetrics] = None
    oos_aggregate_points: Optional[RobustnessDomainMetrics] = None
    is_aggregate_inr: Optional[RobustnessDomainMetrics] = None
    oos_aggregate_inr: Optional[RobustnessDomainMetrics] = None
    oos_expectancy_retention_ratio_points: Optional[float] = None
    oos_expectancy_retention_ratio_inr: Optional[float] = None
    oos_win_rate_delta_pct_points: Optional[float] = None
    positive_oos_windows_ratio_points: Optional[float] = None
    positive_oos_windows_ratio_inr: Optional[float] = None
    no_lookahead_verified: bool
    statistical_significance_claimed: Literal[False] = False
    warnings: Tuple[str, ...] = ()


class MonteCarloConfig(BaseModel):
    """Configuration for reproducible seeded Monte Carlo trade-sequence resampling."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    seed: int = 42
    n_iterations: int = Field(default=1000, ge=10, le=50_000)
    mode: MonteCarloMode = MonteCarloMode.BOOTSTRAP_WITH_REPLACEMENT
    min_trades_required: int = Field(default=5, ge=2)


class PercentileDistribution(BaseModel):
    """Descriptive empirical percentiles across seeded Monte Carlo paths."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    observed: float
    min: float
    p05: float
    p25: float
    p50: float
    p75: float
    p95: float
    max: float
    mean: float
    std: float

    @model_validator(mode="after")
    def _validate_finite(self) -> "PercentileDistribution":
        _check_finite_fields(self, ("observed", "min", "p05", "p25", "p50", "p75", "p95", "max", "mean", "std"))
        return self


class MonteCarloDomainDistribution(BaseModel):
    """Domain-pure Monte Carlo path distributions (`INDEX_POINTS` or `INR`)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    unit_label: Literal["INDEX_POINTS", "INR"]
    provenance_label: str
    max_drawdown: PercentileDistribution
    max_drawdown_pct: Optional[PercentileDistribution] = None
    ending_net_pnl: PercentileDistribution
    ending_equity: Optional[PercentileDistribution] = None
    max_consecutive_losses: PercentileDistribution
    probability_of_positive_net_pnl: float = Field(..., ge=0.0, le=1.0)
    probability_of_drawdown_exceeding_observed: float = Field(..., ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _validate_domain(self) -> "MonteCarloDomainDistribution":
        if self.unit_label == "INDEX_POINTS" and self.max_drawdown_pct is not None:
            raise ValueError(
                "MODE_MIXING_POINTS_AND_CURRENCY: max_drawdown_pct is forbidden in INDEX_POINTS Monte Carlo output."
            )
        return self


class MonteCarloResult(BaseModel):
    """Complete Module G seeded Monte Carlo trade-sequence analysis output."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: RobustnessStatus
    accounting_unit_mode: AccountingUnitMode
    provenance_label: str
    is_synthetic_modelled: bool
    config: MonteCarloConfig
    trade_count: int = Field(..., ge=0)
    is_estimate_not_prediction: Literal[True] = True
    statistical_significance_claimed: Literal[False] = False
    points_distribution: Optional[MonteCarloDomainDistribution] = None
    inr_distribution: Optional[MonteCarloDomainDistribution] = None
    limitations: Tuple[str, ...] = ()
    warnings: Tuple[str, ...] = ()


class SampleSizeGovernanceConfig(BaseModel):
    """Configurable sample-size governance thresholds for evidence classification."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    insufficient_below: int = Field(default=30, ge=2)
    limited_below: int = Field(default=100, ge=3)
    moderate_below: int = Field(default=300, ge=4)

    @model_validator(mode="after")
    def _validate_order(self) -> "SampleSizeGovernanceConfig":
        if not (self.insufficient_below < self.limited_below < self.moderate_below):
            raise ValueError(
                "SampleSizeGovernanceConfig thresholds must satisfy insufficient_below < limited_below < moderate_below."
            )
        return self


class SampleSizeGovernanceResult(BaseModel):
    """Complete Module H sample-size sufficiency classification output."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: RobustnessStatus
    classification: SampleSizeClassification
    closed_trades_count: int = Field(..., ge=0)
    thresholds: SampleSizeGovernanceConfig
    explanation: str
    statistical_significance_claimed: Literal[False] = False
    limitations: Tuple[str, ...] = ()


class RobustnessReproducibilityMetadata(BaseModel):
    """Exact Step 4.5 fingerprint & provenance metadata for deterministic reproduction."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    robustness_version: str = ROBUSTNESS_VERSION
    analytics_version: str = ANALYTICS_VERSION
    timezone_name: Literal["Asia/Kolkata"] = "Asia/Kolkata"
    execution_mode: str = EXECUTION_MODE
    run_id: str
    run_output_fingerprint: str
    dataset_fingerprint: str
    calendar_fingerprint: str
    replay_run_id: Optional[str] = None
    configuration_fingerprint: str
    report_fingerprint: str


class BacktestRobustnessReport(BaseModel):
    """Complete reproducible Step 4.5 Backtest Robustness & Stress Testing artifact."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    report_id: str
    report_fingerprint: str
    configuration_fingerprint: str
    robustness_version: str = ROBUSTNESS_VERSION
    execution_mode: str = EXECUTION_MODE
    status: RobustnessStatus
    run_configuration: RunConfigurationSection
    dataset_provenance: DatasetProvenanceSection
    accounting_mode: AccountingModeSection
    slippage_stress: SlippageStressResult
    transaction_cost_stress: TransactionCostStressResult
    market_regime_robustness: MarketRegimeRobustnessResult
    parameter_sensitivity: Optional[ParameterSensitivityResult] = None
    out_of_sample_robustness: OutOfSampleRobustnessResult
    monte_carlo_analysis: MonteCarloResult
    sample_size_governance: SampleSizeGovernanceResult
    statistical_significance_claimed: Literal[False] = False
    warnings: Tuple[str, ...] = ()
    limitations: Tuple[str, ...] = ()
    reproducibility_metadata: RobustnessReproducibilityMetadata
    created_at_utc: datetime


# ============================================================================
# Shared Conversion & Counterfactual Evaluation Helpers
# ============================================================================


def to_robustness_domain_metrics(
    perf_dom: Optional[DomainPerformanceMetrics],
    risk_dom: Optional[DomainRiskMetrics],
    *,
    starting_capital_inr: Optional[float] = None,
) -> Optional[RobustnessDomainMetrics]:
    """Converts Step 4.4 domain performance & risk models into RobustnessDomainMetrics."""
    if perf_dom is None:
        return None
    max_dd = risk_dom.max_drawdown if risk_dom is not None else perf_dom.max_drawdown
    max_dd_pct = risk_dom.max_drawdown_pct if risk_dom is not None else perf_dom.max_drawdown_pct
    rec_factor = risk_dom.recovery_factor if risk_dom is not None else perf_dom.recovery_factor
    rec_status = risk_dom.recovery_factor_status if risk_dom is not None else perf_dom.recovery_factor_status

    ending_eq: Optional[float]
    if perf_dom.unit_label == "INR":
        ending_eq = (starting_capital_inr + perf_dom.net_pnl) if starting_capital_inr is not None else None
    else:
        ending_eq = perf_dom.net_pnl

    return RobustnessDomainMetrics(
        unit_label=perf_dom.unit_label,
        provenance_label=perf_dom.provenance_label,
        total_closed_trades=perf_dom.total_closed_trades,
        winning_trades=perf_dom.winning_trades,
        losing_trades=perf_dom.losing_trades,
        win_rate=perf_dom.win_rate,
        win_rate_pct=perf_dom.win_rate_pct,
        gross_pnl=perf_dom.gross_pnl,
        total_costs=perf_dom.total_costs,
        net_pnl=perf_dom.net_pnl,
        expectancy=perf_dom.expectancy,
        profit_factor=perf_dom.profit_factor,
        profit_factor_status=perf_dom.profit_factor_status,
        max_drawdown=max_dd,
        max_drawdown_pct=max_dd_pct if perf_dom.unit_label == "INR" else None,
        recovery_factor=rec_factor,
        recovery_factor_status=rec_status,
        net_return_pct=perf_dom.net_return_pct if perf_dom.unit_label == "INR" else None,
        ending_equity=ending_eq,
    )


def extract_segregated_metrics(
    perf_summary: PerformanceSummaryAnalytics,
    risk_summary: Optional[RiskSummaryAnalytics] = None,
    *,
    starting_capital_inr: Optional[float] = None,
) -> Tuple[Optional[RobustnessDomainMetrics], Optional[RobustnessDomainMetrics]]:
    """Extracts domain-pure `(points_metrics, inr_metrics)` from Step 4.4 summaries."""
    pts = to_robustness_domain_metrics(
        perf_summary.points_metrics,
        risk_summary.points_risk if risk_summary is not None else None,
        starting_capital_inr=None,
    )
    inr = to_robustness_domain_metrics(
        perf_summary.inr_metrics,
        risk_summary.inr_risk if risk_summary is not None else None,
        starting_capital_inr=starting_capital_inr,
    )
    return pts, inr


def compute_cost_components_breakdown(run: SimulationRunResult) -> Optional[CostComponentsBreakdown]:
    """Aggregates itemized INR cost components directly from executed fills inside a run."""
    if not domain_has_inr(run.accounting_unit_mode):
        return None
    opened_trades = [
        t
        for t in run.trades
        if t.state not in (TradeLifecycleState.REJECTED, TradeLifecycleState.CANCELLED, TradeLifecycleState.PENDING)
    ]
    brok = 0.0
    stt = 0.0
    exch = 0.0
    gst = 0.0
    sebi = 0.0
    stamp = 0.0
    slip = 0.0
    for t in opened_trades:
        for f in t.fills:
            c = f.costs
            brok += float(c.brokerage_inr or 0.0)
            stt += float(c.stt_inr or 0.0)
            exch += float(c.exchange_txn_charges_inr or 0.0)
            gst += float(c.gst_inr or 0.0)
            sebi += float(c.sebi_charges_inr or 0.0)
            stamp += float(c.stamp_duty_inr or 0.0)
            slip += float(c.slippage_cost_inr or 0.0)
    statutory = stt + exch + gst + sebi + stamp
    brok_stat = brok + statutory
    total = brok_stat + slip
    return CostComponentsBreakdown(
        brokerage_inr=round(brok, 6),
        stt_inr=round(stt, 6),
        exchange_txn_charges_inr=round(exch, 6),
        gst_inr=round(gst, 6),
        sebi_charges_inr=round(sebi, 6),
        stamp_duty_inr=round(stamp, 6),
        total_statutory_charges_inr=round(statutory, 6),
        total_brokerage_and_statutory_inr=round(brok_stat, 6),
        slippage_cost_inr=round(slip, 6),
        total_costs_inr=round(total, 6),
    )


def build_stressed_simulation_run(
    base_run: SimulationRunResult,
    fill_updater: Callable[[TradeRecord, FillRecord], FillRecord],
    *,
    new_cost_schedule: Optional[CostScheduleVersion] = None,
) -> SimulationRunResult:
    """
    Rebuilds a counterfactual SimulationRunResult with updated fill-level slippage or fees,
    adjusting TradeRecord totals, chronological MTM EquityCurvePoint bars, and PortfolioSummary
    without mutating or persisting the original SimulationRunResult.
    """
    validate_run_domain_integrity(base_run)
    um = base_run.accounting_unit_mode
    has_pts = domain_has_points(um)
    has_inr = domain_has_inr(um)

    # Track per-fill timestamp friction deltas for exact MTM equity curve adjustment.
    fill_deltas: List[Tuple[datetime, float, float]] = []
    updated_trades: List[TradeRecord] = []

    total_slip_pts = 0.0
    total_net_pts = 0.0
    total_brok_inr = 0.0
    total_stat_inr = 0.0
    total_brok_stat_inr = 0.0
    total_slip_inr = 0.0
    total_costs_inr = 0.0
    total_net_inr = 0.0
    winning_trades = 0
    losing_trades = 0

    for trade in base_run.trades:
        if (
            trade.state in (TradeLifecycleState.REJECTED, TradeLifecycleState.CANCELLED, TradeLifecycleState.PENDING)
            or not trade.fills
        ):
            updated_trades.append(trade)
            continue

        new_fills: List[FillRecord] = []
        t_slip_pts = 0.0
        t_bs_inr = 0.0
        t_slip_inr = 0.0
        t_costs_inr = 0.0

        for old_f in trade.fills:
            new_f = fill_updater(trade, old_f)
            new_fills.append(new_f)

            d_pts = (
                float(new_f.slippage_points_leg or 0.0) - float(old_f.slippage_points_leg or 0.0)
                if has_pts
                else 0.0
            )
            d_inr = (
                float(new_f.costs.total_costs_inr or 0.0) - float(old_f.costs.total_costs_inr or 0.0)
                if has_inr
                else 0.0
            )
            if abs(d_pts) > 0.0 or abs(d_inr) > 0.0:
                fill_deltas.append((parse_ist_datetime(new_f.executed_at_ist, "executed_at_ist"), d_pts, d_inr))

            if has_pts:
                t_slip_pts += float(new_f.slippage_points_leg or 0.0)
            if has_inr:
                c = new_f.costs
                t_brok = float(c.brokerage_inr or 0.0)
                t_stat = (
                    float(c.stt_inr or 0.0)
                    + float(c.exchange_txn_charges_inr or 0.0)
                    + float(c.gst_inr or 0.0)
                    + float(c.sebi_charges_inr or 0.0)
                    + float(c.stamp_duty_inr or 0.0)
                )
                total_brok_inr += t_brok
                total_stat_inr += t_stat
                t_bs_inr += float(c.brokerage_and_statutory_inr or (t_brok + t_stat))
                t_slip_inr += float(c.slippage_cost_inr or 0.0)
                t_costs_inr += float(c.total_costs_inr or 0.0)

        new_net_pts = (float(trade.gross_points or 0.0) - t_slip_pts) if has_pts else None
        new_net_inr = (float(trade.gross_pnl_inr or 0.0) - t_costs_inr) if has_inr else None

        new_trade = trade.model_copy(
            update={
                "fills": tuple(new_fills),
                "slippage_points": round(t_slip_pts, 6) if has_pts else None,
                "net_points": round(new_net_pts, 6) if has_pts and new_net_pts is not None else None,
                "total_brokerage_and_statutory_inr": round(t_bs_inr, 6) if has_inr else None,
                "total_slippage_cost_inr": round(t_slip_inr, 6) if has_inr else None,
                "total_costs_inr": round(t_costs_inr, 6) if has_inr else None,
                "net_pnl_inr": round(new_net_inr, 6) if has_inr and new_net_inr is not None else None,
            }
        )
        updated_trades.append(new_trade)

        if has_pts:
            total_slip_pts += float(new_trade.slippage_points or 0.0)
            total_net_pts += float(new_trade.net_points or 0.0)
        if has_inr:
            total_brok_stat_inr += float(new_trade.total_brokerage_and_statutory_inr or 0.0)
            total_slip_inr += float(new_trade.total_slippage_cost_inr or 0.0)
            total_costs_inr += float(new_trade.total_costs_inr or 0.0)
            total_net_inr += float(new_trade.net_pnl_inr or 0.0)

        if new_trade.state == TradeLifecycleState.CLOSED:
            net_dom = float(new_trade.net_points or 0.0) if um == AccountingUnitMode.INDEX_POINTS_ONLY else float(new_trade.net_pnl_inr or 0.0)
            if is_clean_winner(new_trade, net_dom):
                winning_trades += 1
            else:
                losing_trades += 1

    # Rebuild chronological MTM equity curve deltas & drawdowns.
    fill_deltas.sort(key=lambda item: item[0])
    cum_d_pts = 0.0
    cum_d_inr = 0.0
    ev_idx = 0
    n_ev = len(fill_deltas)

    peak_pts = 0.0
    max_dd_pts = 0.0
    peak_inr = float(base_run.portfolio.starting_capital_inr or 0.0)
    max_dd_inr = 0.0
    max_dd_pct = 0.0

    new_curve: List[EquityCurvePoint] = []
    sorted_curve = sorted(
        base_run.equity_curve,
        key=lambda p: parse_ist_datetime(p.timestamp_ist, "equity_curve.timestamp_ist"),
    )
    for pt in sorted_curve:
        bar_dt = parse_ist_datetime(pt.timestamp_ist, "equity_curve.timestamp_ist")
        while ev_idx < n_ev and fill_deltas[ev_idx][0] <= bar_dt:
            cum_d_pts += fill_deltas[ev_idx][1]
            cum_d_inr += fill_deltas[ev_idx][2]
            ev_idx += 1

        updates: Dict[str, object] = {}
        if has_pts:
            new_slip_pt = float(pt.total_slippage_points or 0.0) + cum_d_pts
            new_rnet_pt = float(pt.realized_net_points or 0.0) - cum_d_pts
            new_ceq_pt = float(pt.cumulative_equity_points or 0.0) - cum_d_pts
            peak_pts = max(peak_pts, new_ceq_pt)
            dd_pts = max(0.0, peak_pts - new_ceq_pt)
            max_dd_pts = max(max_dd_pts, dd_pts)
            updates.update(
                {
                    "total_slippage_points": new_slip_pt,
                    "realized_net_points": new_rnet_pt,
                    "cumulative_equity_points": new_ceq_pt,
                    "drawdown_points": dd_pts,
                }
            )
        if has_inr:
            new_cash = float(pt.available_cash_inr or 0.0) - cum_d_inr
            new_rnet_inr = float(pt.realized_net_pnl_inr or 0.0) - cum_d_inr
            new_tot_costs = float(pt.total_costs_inr or 0.0) + cum_d_inr
            new_eq_inr = float(pt.total_equity_inr or 0.0) - cum_d_inr
            peak_inr = max(peak_inr, new_eq_inr)
            dd_inr = max(0.0, peak_inr - new_eq_inr)
            dd_pct = (dd_inr / peak_inr * 100.0) if peak_inr > 0.0 else 0.0
            max_dd_inr = max(max_dd_inr, dd_inr)
            max_dd_pct = max(max_dd_pct, dd_pct)
            updates.update(
                {
                    "available_cash_inr": new_cash,
                    "realized_net_pnl_inr": new_rnet_inr,
                    "total_costs_inr": new_tot_costs,
                    "total_equity_inr": new_eq_inr,
                    "drawdown_inr": dd_inr,
                    "drawdown_pct": dd_pct,
                }
            )
        new_curve.append(pt.model_copy(update=updates))

    # Consume any trailing fill deltas beyond the last bar if curve was partial.
    while ev_idx < n_ev:
        cum_d_pts += fill_deltas[ev_idx][1]
        cum_d_inr += fill_deltas[ev_idx][2]
        ev_idx += 1

    base_port = base_run.portfolio
    port_updates: Dict[str, object] = {
        "winning_trades": winning_trades,
        "losing_trades": losing_trades,
    }
    if has_pts:
        end_cum_pts = float(base_port.ending_cumulative_points or 0.0) - cum_d_pts
        port_updates.update(
            {
                "total_slippage_points": round(total_slip_pts, 6),
                "realized_net_points": round(total_net_pts, 6),
                "ending_cumulative_points": round(end_cum_pts, 6),
                "max_drawdown_points": round(max_dd_pts, 6),
            }
        )
    if has_inr:
        start_cap = float(base_port.starting_capital_inr or 0.0)
        end_eq_inr = float(base_port.ending_equity_inr or start_cap) - cum_d_inr
        avail_cash = float(base_port.available_cash_inr or start_cap) - cum_d_inr
        unrealized_inr = float(base_port.unrealized_pnl_inr or 0.0)
        net_ret_pct = ((total_net_inr + unrealized_inr) / start_cap * 100.0) if start_cap > 0.0 else 0.0
        port_updates.update(
            {
                "available_cash_inr": round(avail_cash, 6),
                "ending_equity_inr": round(end_eq_inr, 6),
                "total_brokerage_inr": round(total_brok_inr, 6),
                "total_statutory_charges_inr": round(total_stat_inr, 6),
                "total_brokerage_and_statutory_inr": round(total_brok_stat_inr, 6),
                "total_slippage_cost_inr": round(total_slip_inr, 6),
                "total_costs_inr": round(total_costs_inr, 6),
                "realized_net_pnl_inr": round(total_net_inr, 6),
                "net_return_pct": round(net_ret_pct, 6),
                "max_drawdown_inr": round(max_dd_inr, 6),
                "max_drawdown_pct": round(max_dd_pct, 6),
            }
        )

    return base_run.model_copy(
        update={
            "cost_schedule": new_cost_schedule or base_run.cost_schedule,
            "portfolio": base_port.model_copy(update=port_updates),
            "equity_curve": tuple(new_curve),
            "trades": tuple(updated_trades),
        }
    )


def evaluate_stressed_run(
    stressed_run: SimulationRunResult,
    *,
    risk_engine: Optional[RiskAnalyticsEngine] = None,
    perf_engine: Optional[PerformanceAnalyticsEngine] = None,
) -> Tuple[Optional[RobustnessDomainMetrics], Optional[RobustnessDomainMetrics]]:
    """Evaluates a counterfactual SimulationRunResult through Step 4.4 Risk & Performance engines."""
    r_eng = risk_engine or RiskAnalyticsEngine()
    p_eng = perf_engine or PerformanceAnalyticsEngine(risk_engine=r_eng)
    rs = r_eng.evaluate_run(stressed_run)
    ps = p_eng.evaluate_run(stressed_run, risk_summary=rs)
    return extract_segregated_metrics(
        ps,
        rs,
        starting_capital_inr=stressed_run.portfolio.starting_capital_inr,
    )


def evaluate_closed_trade_slice_metrics(
    *,
    closed_trades: Sequence[TradeRecord],
    reference_run: SimulationRunResult,
    slice_prefix: str,
    risk_engine: Optional[RiskAnalyticsEngine] = None,
    perf_engine: Optional[PerformanceAnalyticsEngine] = None,
) -> Tuple[Optional[RobustnessDomainMetrics], Optional[RobustnessDomainMetrics]]:
    """Evaluates a closed-trade subset strictly within reference_run's AccountingUnitMode."""
    r_eng = risk_engine or RiskAnalyticsEngine()
    p_eng = perf_engine or PerformanceAnalyticsEngine(risk_engine=r_eng)
    ordered = sort_closed_trades(closed_trades)
    rs = r_eng.evaluate_components(
        accounting_unit_mode=reference_run.accounting_unit_mode,
        provenance_label=reference_run.provenance_label,
        is_synthetic_modelled=reference_run.is_synthetic_modelled,
        closed_trades=ordered,
        equity_curve=(),
        starting_capital_inr=reference_run.portfolio.starting_capital_inr,
        episode_prefix=slice_prefix,
    )
    ps = p_eng.evaluate_trade_slice(
        closed_trades=ordered,
        accounting_unit_mode=reference_run.accounting_unit_mode,
        provenance_label=reference_run.provenance_label,
        is_synthetic_modelled=reference_run.is_synthetic_modelled,
        starting_capital_inr=reference_run.portfolio.starting_capital_inr,
        instrument_multiplier_inr_per_point=reference_run.portfolio.instrument_multiplier_inr_per_point,
        instrument_multiplier_documentation=reference_run.portfolio.instrument_multiplier_documentation,
        slice_prefix=slice_prefix,
    )
    return extract_segregated_metrics(
        ps,
        rs,
        starting_capital_inr=reference_run.portfolio.starting_capital_inr,
    )

