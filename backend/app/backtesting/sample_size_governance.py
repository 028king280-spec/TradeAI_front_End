"""
AIVOLVE Phase 4 Step 4.5 — Module H: Sample Size Governance Engine.

Applies transparent, configurable evidence thresholds:
- < 30 closed trades:   INSUFFICIENT_SAMPLE
- 30-99 closed trades:  LIMITED_EVIDENCE
- 100-299 closed trades: MODERATE_SAMPLE
- >= 300 closed trades: LARGER_SAMPLE

Explicitly never treats any trade count alone as proof of statistical significance
or future alpha durability.
"""

from __future__ import annotations

from typing import Optional

from app.backtesting.analytics_models import validate_run_domain_integrity
from app.backtesting.risk_analytics import sort_closed_trades
from app.backtesting.robustness_models import (
    RobustnessStatus,
    SampleSizeClassification,
    SampleSizeGovernanceConfig,
    SampleSizeGovernanceResult,
)
from app.backtesting.simulation_models import SimulationRunResult, SimulationStatus


class SampleSizeGovernanceEngine:
    """Stateless evidence-classification guardrail over historical trade count."""

    def evaluate(
        self,
        run: SimulationRunResult,
        config: Optional[SampleSizeGovernanceConfig] = None,
    ) -> SampleSizeGovernanceResult:
        validate_run_domain_integrity(run)
        cfg = config or SampleSizeGovernanceConfig()

        common_limitations = (
            "Sample size alone does not establish statistical significance; overlapping positions, regime dependence, and non-stationarity reduce effective independent degrees of freedom.",
            "Historical backtest counts exclude live operational risk, liquidity impact, and selection bias.",
        )

        if run.status != SimulationStatus.COMPLETED:
            return SampleSizeGovernanceResult(
                status=RobustnessStatus.RUN_NOT_COMPLETED,
                classification=SampleSizeClassification.INSUFFICIENT_SAMPLE,
                closed_trades_count=0,
                thresholds=cfg,
                explanation=f"Simulation status is '{run.status.value}'; zero completed evidence evaluated.",
                statistical_significance_claimed=False,
                limitations=common_limitations,
            )

        n = len(sort_closed_trades(run.trades))
        if n == 0:
            return SampleSizeGovernanceResult(
                status=RobustnessStatus.NO_TRADES,
                classification=SampleSizeClassification.INSUFFICIENT_SAMPLE,
                closed_trades_count=0,
                thresholds=cfg,
                explanation="Zero closed trades observed; sample size is strictly insufficient.",
                statistical_significance_claimed=False,
                limitations=common_limitations,
            )

        if n < cfg.insufficient_below:
            cls = SampleSizeClassification.INSUFFICIENT_SAMPLE
            expl = (
                f"{n} closed trades (< {cfg.insufficient_below}): INSUFFICIENT_SAMPLE. "
                "Metrics are highly sensitive to single outlier trades and cannot support quantitative confidence."
            )
            status = RobustnessStatus.INSUFFICIENT_DATA
        elif n < cfg.limited_below:
            cls = SampleSizeClassification.LIMITED_EVIDENCE
            expl = (
                f"{n} closed trades ({cfg.insufficient_below}-{cfg.limited_below - 1}): LIMITED_EVIDENCE. "
                "Directional sanity checks only; wide sampling variance remains."
            )
            status = RobustnessStatus.COMPLETED
        elif n < cfg.moderate_below:
            cls = SampleSizeClassification.MODERATE_SAMPLE
            expl = (
                f"{n} closed trades ({cfg.limited_below}-{cfg.moderate_below - 1}): MODERATE_SAMPLE. "
                "Usable for descriptive robustness stress analysis across subperiods, but still not proof of edge."
            )
            status = RobustnessStatus.COMPLETED
        else:
            cls = SampleSizeClassification.LARGER_SAMPLE
            expl = (
                f"{n} closed trades (>= {cfg.moderate_below}): LARGER_SAMPLE. "
                "Supports broader regime and OOS testing, though high trade count alone still does not prove statistical significance."
            )
            status = RobustnessStatus.COMPLETED

        return SampleSizeGovernanceResult(
            status=status,
            classification=cls,
            closed_trades_count=n,
            thresholds=cfg,
            explanation=expl,
            statistical_significance_claimed=False,
            limitations=common_limitations,
        )

