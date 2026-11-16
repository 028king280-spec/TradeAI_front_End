"""
AIVOLVE Phase 4 Step 4.5 — Module G: Deterministic Seeded Monte Carlo Resampling Engine.

Evaluates trade-sequence order uncertainty and sampling variability via seeded
bootstrap resampling (with replacement) or trade-order permutation (without replacement).
Strictly segregates AccountingUnitMode domains and labels all distributions as
historical resampling estimates, NEVER predictions or proof of statistical significance.
"""

from __future__ import annotations

import math
import random
from typing import List, Optional, Sequence, Tuple

from app.backtesting.analytics_models import domain_has_inr, domain_has_points, validate_run_domain_integrity
from app.backtesting.performance_analytics import linear_quantile
from app.backtesting.risk_analytics import is_clean_winner, sort_closed_trades
from app.backtesting.robustness_models import (
    MonteCarloConfig,
    MonteCarloDomainDistribution,
    MonteCarloMode,
    MonteCarloResult,
    PercentileDistribution,
    RobustnessStatus,
)
from app.backtesting.simulation_models import SimulationRunResult, SimulationStatus


def _summarize_distribution(values: Sequence[float], observed: float) -> PercentileDistribution:
    s = sorted(float(v) for v in values)
    n = len(s)
    mean_v = sum(s) / n
    var = sum((x - mean_v) ** 2 for x in s) / n
    return PercentileDistribution(
        observed=round(float(observed), 6),
        min=round(s[0], 6),
        p05=round(float(linear_quantile(s, 0.05) or s[0]), 6),
        p25=round(float(linear_quantile(s, 0.25) or s[0]), 6),
        p50=round(float(linear_quantile(s, 0.50) or s[0]), 6),
        p75=round(float(linear_quantile(s, 0.75) or s[0]), 6),
        p95=round(float(linear_quantile(s, 0.95) or s[0]), 6),
        max=round(s[-1], 6),
        mean=round(mean_v, 6),
        std=round(math.sqrt(max(0.0, var)), 6),
    )


def _path_metrics(
    ordered_pnls: Sequence[float],
    clean_win_flags: Sequence[bool],
    starting_equity: float,
    compute_pct: bool,
) -> Tuple[float, Optional[float], float, float, int]:
    """Computes `(max_dd, max_dd_pct, net_pnl, ending_eq, max_consec_losses)` on one sequence."""
    eq = starting_equity
    peak = starting_equity
    max_dd = 0.0
    max_dd_pct = 0.0 if compute_pct else None
    consec_loss = 0
    max_consec_loss = 0

    for pnl, is_win in zip(ordered_pnls, clean_win_flags):
        eq += pnl
        if eq > peak:
            peak = eq
        dd = max(0.0, peak - eq)
        if dd > max_dd:
            max_dd = dd
        if compute_pct and peak > 0.0:
            dd_pct = dd / peak * 100.0
            assert max_dd_pct is not None
            if dd_pct > max_dd_pct:
                max_dd_pct = dd_pct

        if is_win:
            consec_loss = 0
        else:
            consec_loss += 1
            if consec_loss > max_consec_loss:
                max_consec_loss = consec_loss

    net_pnl = eq - starting_equity
    return max_dd, max_dd_pct, net_pnl, eq, max_consec_loss


def _simulate_domain_paths(
    *,
    unit_label: str,
    provenance_label: str,
    pnls: Sequence[float],
    clean_flags: Sequence[bool],
    sample_index_paths: Sequence[Sequence[int]],
    starting_equity: Optional[float],
) -> MonteCarloDomainDistribution:
    compute_pct = unit_label == "INR"
    start_eq = float(starting_equity or 0.0) if unit_label == "INR" else 0.0

    obs_dd, obs_dd_pct, obs_net, obs_end_eq, obs_streak = _path_metrics(
        pnls,
        clean_flags,
        start_eq,
        compute_pct,
    )

    sim_dds: List[float] = []
    sim_dd_pcts: List[float] = []
    sim_nets: List[float] = []
    sim_end_eqs: List[float] = []
    sim_streaks: List[float] = []

    for idxs in sample_index_paths:
        seq_pnls = [pnls[i] for i in idxs]
        seq_wins = [clean_flags[i] for i in idxs]
        dd, dd_pct, net_p, end_e, streak = _path_metrics(
            seq_pnls,
            seq_wins,
            start_eq,
            compute_pct,
        )
        sim_dds.append(dd)
        if dd_pct is not None:
            sim_dd_pcts.append(dd_pct)
        sim_nets.append(net_p)
        sim_end_eqs.append(end_e)
        sim_streaks.append(float(streak))

    n_iter = len(sample_index_paths)
    prob_pos = sum(1 for x in sim_nets if x > 0.0) / n_iter
    prob_dd_exceed = sum(1 for x in sim_dds if x > obs_dd + 1e-12) / n_iter

    end_eq_dist: Optional[PercentileDistribution]
    if unit_label == "INR":
        end_eq_dist = _summarize_distribution(sim_end_eqs, obs_end_eq) if starting_equity is not None else None
    else:
        end_eq_dist = _summarize_distribution(sim_end_eqs, obs_end_eq)

    return MonteCarloDomainDistribution(
        unit_label=unit_label,  # type: ignore[arg-type]
        provenance_label=provenance_label,
        max_drawdown=_summarize_distribution(sim_dds, obs_dd),
        max_drawdown_pct=(
            _summarize_distribution(sim_dd_pcts, float(obs_dd_pct or 0.0)) if compute_pct else None
        ),
        ending_net_pnl=_summarize_distribution(sim_nets, obs_net),
        ending_equity=end_eq_dist,
        max_consecutive_losses=_summarize_distribution(sim_streaks, float(obs_streak)),
        probability_of_positive_net_pnl=round(prob_pos, 6),
        probability_of_drawdown_exceeding_observed=round(prob_dd_exceed, 6),
    )


class MonteCarloEngine:
    """Deterministic seeded trade-sequence resampling engine."""

    def evaluate(
        self,
        run: SimulationRunResult,
        config: Optional[MonteCarloConfig] = None,
    ) -> MonteCarloResult:
        validate_run_domain_integrity(run)
        cfg = config or MonteCarloConfig()
        um = run.accounting_unit_mode

        base_limitations = (
            "Monte Carlo resampling estimates historical trade-sequence variability under an IID/exchangeability assumption; it is NOT a forecast of future market performance.",
            "Serial trade correlation, volatility clustering, overlapping margin saturation, and intraday MTM intrabar excursions beyond closed trade outcomes are ignored.",
        )

        if run.status != SimulationStatus.COMPLETED:
            return MonteCarloResult(
                status=RobustnessStatus.RUN_NOT_COMPLETED,
                accounting_unit_mode=um,
                provenance_label=run.provenance_label,
                is_synthetic_modelled=run.is_synthetic_modelled,
                config=cfg,
                trade_count=0,
                limitations=base_limitations,
                warnings=(f"RUN_NOT_COMPLETED: SimulationRunResult status is '{run.status.value}'.",),
            )

        closed_trades = sort_closed_trades(run.trades)
        n_trades = len(closed_trades)
        if n_trades == 0:
            return MonteCarloResult(
                status=RobustnessStatus.NO_TRADES,
                accounting_unit_mode=um,
                provenance_label=run.provenance_label,
                is_synthetic_modelled=run.is_synthetic_modelled,
                config=cfg,
                trade_count=0,
                limitations=base_limitations,
                warnings=("NO_CLOSED_TRADES: Monte Carlo resampling requires closed trades.",),
            )

        if n_trades < cfg.min_trades_required:
            return MonteCarloResult(
                status=RobustnessStatus.INSUFFICIENT_DATA,
                accounting_unit_mode=um,
                provenance_label=run.provenance_label,
                is_synthetic_modelled=run.is_synthetic_modelled,
                config=cfg,
                trade_count=n_trades,
                limitations=base_limitations,
                warnings=(
                    f"INSUFFICIENT_TRADES_FOR_MONTE_CARLO: Found {n_trades} closed trade(s), below min_trades_required={cfg.min_trades_required}.",
                ),
            )

        rng = random.Random(cfg.seed)
        base_indices = list(range(n_trades))
        sample_paths: List[List[int]] = []
        if cfg.mode == MonteCarloMode.BOOTSTRAP_WITH_REPLACEMENT:
            for _ in range(cfg.n_iterations):
                sample_paths.append([rng.randrange(n_trades) for _ in base_indices])
        else:
            for _ in range(cfg.n_iterations):
                perm = list(base_indices)
                rng.shuffle(perm)
                sample_paths.append(perm)

        warnings: List[str] = []
        if cfg.mode == MonteCarloMode.PERMUTATION_WITHOUT_REPLACEMENT:
            warnings.append(
                "PERMUTATION_INVARIANT_ENDING_PNL: Sampling without replacement keeps terminal net P&L identical across paths; only sequence drawdown and loss-streak paths vary."
            )
        if n_trades < 30:
            warnings.append(
                f"SMALL_SAMPLE_BOOTSTRAP_CAUTION: Resampling only {n_trades} trade(s) (< 30) creates high tail-estimate instability."
            )

        pts_dist: Optional[MonteCarloDomainDistribution] = None
        if domain_has_points(um):
            pts_pnls = [float(t.net_points or 0.0) for t in closed_trades]
            pts_wins = [is_clean_winner(t, p) for t, p in zip(closed_trades, pts_pnls)]
            pts_dist = _simulate_domain_paths(
                unit_label="INDEX_POINTS",
                provenance_label=run.provenance_label,
                pnls=pts_pnls,
                clean_flags=pts_wins,
                sample_index_paths=sample_paths,
                starting_equity=None,
            )

        inr_dist: Optional[MonteCarloDomainDistribution] = None
        if domain_has_inr(um):
            inr_pnls = [float(t.net_pnl_inr or 0.0) for t in closed_trades]
            inr_wins = [is_clean_winner(t, p) for t, p in zip(closed_trades, inr_pnls)]
            inr_dist = _simulate_domain_paths(
                unit_label="INR",
                provenance_label=run.provenance_label,
                pnls=inr_pnls,
                clean_flags=inr_wins,
                sample_index_paths=sample_paths,
                starting_equity=run.portfolio.starting_capital_inr,
            )

        return MonteCarloResult(
            status=RobustnessStatus.COMPLETED,
            accounting_unit_mode=um,
            provenance_label=run.provenance_label,
            is_synthetic_modelled=run.is_synthetic_modelled,
            config=cfg,
            trade_count=n_trades,
            is_estimate_not_prediction=True,
            statistical_significance_claimed=False,
            points_distribution=pts_dist,
            inr_distribution=inr_dist,
            limitations=base_limitations,
            warnings=tuple(dict.fromkeys(warnings)),
        )

