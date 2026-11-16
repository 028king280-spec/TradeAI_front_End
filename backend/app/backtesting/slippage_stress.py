"""
AIVOLVE Phase 4 Step 4.5 — Module B: Slippage Stress Engine.

Evaluates baseline (1.0x) and stressed (1.25x, 1.5x, 2.0x, 3.0x, configurable)
slippage scenarios over the exact same historical trade set and MTM equity curve,
strictly preserving AccountingUnitMode boundaries and zero lookahead bias.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from app.backtesting.analytics_models import domain_has_inr, domain_has_points, validate_run_domain_integrity
from app.backtesting.performance_analytics import PerformanceAnalyticsEngine
from app.backtesting.risk_analytics import RiskAnalyticsEngine, sort_closed_trades
from app.backtesting.robustness_models import (
    RobustnessDomainMetrics,
    RobustnessStatus,
    SlippageScenarioResult,
    SlippageStressConfig,
    SlippageStressResult,
    build_stressed_simulation_run,
    evaluate_stressed_run,
)
from app.backtesting.simulation_models import (
    AccountingUnitMode,
    FillRecord,
    OrderSide,
    SignalDirection,
    SimulationRunResult,
    SimulationStatus,
    TradeRecord,
)


def _compute_break_even_multiplier(net_pnl: float, friction_cost: float) -> Optional[float]:
    if friction_cost <= 1e-12:
        return None
    pre_friction = net_pnl + friction_cost
    if pre_friction <= 0.0:
        return None
    return round(pre_friction / friction_cost, 6)


def _compute_retention_ratio(scenario_net: float, baseline_net: Optional[float]) -> Optional[float]:
    if baseline_net is None or baseline_net <= 1e-12:
        return None
    return round(scenario_net / baseline_net, 6)


def _scale_fill_slippage(
    trade: TradeRecord,
    fill: FillRecord,
    multiplier: float,
    has_pts: bool,
    has_inr: bool,
) -> FillRecord:
    if abs(multiplier - 1.0) <= 1e-12:
        return fill

    old_slip_pu = float(fill.slippage_per_unit)
    new_slip_pu = round(old_slip_pu * multiplier, 6)
    delta_pu = new_slip_pu - old_slip_pu
    is_buy_leg = (
        (trade.direction == SignalDirection.LONG and fill.side == OrderSide.ENTRY)
        or (trade.direction == SignalDirection.SHORT and fill.side != OrderSide.ENTRY)
    )
    new_eff_price = max(
        0.0,
        round(float(fill.effective_fill_price) + (delta_pu if is_buy_leg else -delta_pu), 6),
    )

    old_slip_pts = float(fill.slippage_points_leg or 0.0) if has_pts else None
    new_slip_pts = round(old_slip_pts * multiplier, 6) if old_slip_pts is not None else None
    d_pts = (new_slip_pts - old_slip_pts) if (new_slip_pts is not None and old_slip_pts is not None) else 0.0
    new_net_pts_leg = (
        round(float(fill.net_points_impact_leg or 0.0) - d_pts, 6)
        if has_pts and fill.net_points_impact_leg is not None
        else fill.net_points_impact_leg
    )

    c = fill.costs
    if has_inr:
        old_slip_inr = float(c.slippage_cost_inr or 0.0)
        new_slip_inr = round(old_slip_inr * multiplier, 6)
        d_inr = new_slip_inr - old_slip_inr
        brok_stat = float(c.brokerage_and_statutory_inr or 0.0)
        new_tot_inr = round(brok_stat + new_slip_inr, 6)
        new_net_inr_leg = (
            round(float(fill.net_pnl_inr_impact_leg or 0.0) - d_inr, 6)
            if fill.net_pnl_inr_impact_leg is not None
            else fill.net_pnl_inr_impact_leg
        )
        new_costs = c.model_copy(
            update={
                "slippage_points_leg": new_slip_pts if has_pts else None,
                "slippage_cost_inr": new_slip_inr,
                "total_costs_inr": new_tot_inr,
            }
        )
    else:
        new_net_inr_leg = None
        new_costs = c.model_copy(
            update={
                "slippage_points_leg": new_slip_pts,
            }
        )

    return fill.model_copy(
        update={
            "slippage_per_unit": new_slip_pu,
            "effective_fill_price": new_eff_price,
            "slippage_points_leg": new_slip_pts,
            "net_points_impact_leg": new_net_pts_leg,
            "net_pnl_inr_impact_leg": new_net_inr_leg,
            "costs": new_costs,
        }
    )


class SlippageStressEngine:
    """Stateless deterministic engine stressing fill slippage across fixed historical fills."""

    def __init__(
        self,
        risk_engine: Optional[RiskAnalyticsEngine] = None,
        perf_engine: Optional[PerformanceAnalyticsEngine] = None,
    ) -> None:
        self._risk = risk_engine or RiskAnalyticsEngine()
        self._perf = perf_engine or PerformanceAnalyticsEngine(risk_engine=self._risk)

    def evaluate(
        self,
        run: SimulationRunResult,
        config: Optional[SlippageStressConfig] = None,
    ) -> SlippageStressResult:
        validate_run_domain_integrity(run)
        cfg = config or SlippageStressConfig()
        um = run.accounting_unit_mode
        has_pts = domain_has_points(um)
        has_inr = domain_has_inr(um)

        assumptions = (
            "Slippage stress scales baseline per-fill slippage linearly over fixed fill timestamps and raw reference prices.",
            "Entry/exit trigger timing, bar selection, and statutory fee rates are held constant; market-impact non-linearity is not modelled.",
        )

        if run.status != SimulationStatus.COMPLETED:
            return SlippageStressResult(
                status=RobustnessStatus.RUN_NOT_COMPLETED,
                accounting_unit_mode=um,
                provenance_label=run.provenance_label,
                is_synthetic_modelled=run.is_synthetic_modelled,
                config=cfg,
                warnings=(f"RUN_NOT_COMPLETED: SimulationRunResult status is '{run.status.value}'.",),
                assumptions=assumptions,
            )

        closed_trades = sort_closed_trades(run.trades)
        if not closed_trades:
            return SlippageStressResult(
                status=RobustnessStatus.NO_TRADES,
                accounting_unit_mode=um,
                provenance_label=run.provenance_label,
                is_synthetic_modelled=run.is_synthetic_modelled,
                config=cfg,
                warnings=("NO_CLOSED_TRADES: Slippage stress requires at least one closed trade.",),
                assumptions=assumptions,
            )

        warnings: List[str] = []
        base_slip_per_unit = float(run.cost_schedule.slippage_per_unit)
        closed_slip_pts = sum(float(t.slippage_points or 0.0) for t in closed_trades) if has_pts else 0.0
        closed_slip_inr = sum(float(t.total_slippage_cost_inr or 0.0) for t in closed_trades) if has_inr else 0.0
        if (has_pts and closed_slip_pts <= 1e-12) or (has_inr and closed_slip_inr <= 1e-12):
            warnings.append(
                "ZERO_BASELINE_SLIPPAGE: Baseline fills carry zero slippage; multiplicative scaling yields zero incremental slippage impact."
            )

        # Always compute exact 1.0x baseline first so deltas/retention are well-defined even if 1.0 is omitted in custom config.
        base_pts_m, base_inr_m = evaluate_stressed_run(run, risk_engine=self._risk, perf_engine=self._perf)
        base_gross_pts = base_pts_m.gross_pnl if base_pts_m is not None else None
        base_gross_inr = base_inr_m.gross_pnl if base_inr_m is not None else None
        base_net_pts = base_pts_m.net_pnl if base_pts_m is not None else None
        base_net_inr = base_inr_m.net_pnl if base_inr_m is not None else None

        scenarios: List[SlippageScenarioResult] = []
        by_mult: Dict[float, SlippageScenarioResult] = {}

        for mult in cfg.multipliers:
            if abs(mult - 1.0) <= 1e-12:
                pts_m, inr_m = base_pts_m, base_inr_m
                stressed_run = run
            else:
                new_sched = run.cost_schedule.model_copy(
                    update={"slippage_per_unit": round(base_slip_per_unit * mult, 6)}
                )
                stressed_run = build_stressed_simulation_run(
                    run,
                    lambda t, f, _m=mult: _scale_fill_slippage(t, f, _m, has_pts, has_inr),
                    new_cost_schedule=new_sched,
                )
                pts_m, inr_m = evaluate_stressed_run(
                    stressed_run,
                    risk_engine=self._risk,
                    perf_engine=self._perf,
                )

            closed_stressed = sort_closed_trades(stressed_run.trades)
            scen_slip_pts = round(sum(float(t.slippage_points or 0.0) for t in closed_stressed), 6) if has_pts else None
            scen_slip_inr = (
                round(sum(float(t.total_slippage_cost_inr or 0.0) for t in closed_stressed), 6)
                if has_inr
                else None
            )

            delta_pts = (
                round(pts_m.net_pnl - base_net_pts, 6)
                if (pts_m is not None and base_net_pts is not None)
                else None
            )
            delta_inr = (
                round(inr_m.net_pnl - base_net_inr, 6)
                if (inr_m is not None and base_net_inr is not None)
                else None
            )

            ret_pts = _compute_retention_ratio(pts_m.net_pnl, base_net_pts) if pts_m is not None else None
            ret_inr = _compute_retention_ratio(inr_m.net_pnl, base_net_inr) if inr_m is not None else None

            scen = SlippageScenarioResult(
                multiplier=mult,
                is_baseline=abs(mult - 1.0) <= 1e-12,
                accounting_unit_mode=um,
                provenance_label=run.provenance_label,
                slippage_unit=run.cost_schedule.slippage_unit,
                effective_slippage_per_unit=round(base_slip_per_unit * mult, 6),
                points_metrics=pts_m,
                inr_metrics=inr_m,
                total_slippage_points=scen_slip_pts,
                total_slippage_cost_inr=scen_slip_inr,
                net_pnl_delta_points_vs_baseline=delta_pts,
                net_pnl_delta_inr_vs_baseline=delta_inr,
                net_pnl_retention_ratio_points=ret_pts,
                net_pnl_retention_ratio_inr=ret_inr,
            )
            scenarios.append(scen)
            by_mult[round(mult, 6)] = scen

        be_pts = (
            _compute_break_even_multiplier(base_net_pts, closed_slip_pts)
            if (has_pts and base_net_pts is not None)
            else None
        )
        be_inr = (
            _compute_break_even_multiplier(base_net_inr, closed_slip_inr)
            if (has_inr and base_net_inr is not None)
            else None
        )
        if has_pts and base_net_pts is not None and (base_net_pts + closed_slip_pts) <= 0.0:
            warnings.append("UNPROFITABLE_BEFORE_SLIPPAGE_POINTS: Closed-trade P&L in index points is <= 0 even before slippage.")
        if has_inr and base_net_inr is not None and (base_net_inr + closed_slip_inr) <= 0.0:
            warnings.append("UNPROFITABLE_BEFORE_SLIPPAGE_INR: Closed-trade P&L in INR is <= 0 even before slippage.")

        s_2x = by_mult.get(2.0)
        s_3x = by_mult.get(3.0)

        return SlippageStressResult(
            status=RobustnessStatus.COMPLETED,
            accounting_unit_mode=um,
            provenance_label=run.provenance_label,
            is_synthetic_modelled=run.is_synthetic_modelled,
            config=cfg,
            baseline_gross_pnl_points=base_gross_pts,
            baseline_gross_pnl_inr=base_gross_inr,
            baseline_net_pnl_points=base_net_pts,
            baseline_net_pnl_inr=base_net_inr,
            break_even_slippage_multiplier_points=be_pts,
            break_even_slippage_multiplier_inr=be_inr,
            remains_profitable_at_2x_points=(s_2x.points_metrics.net_pnl > 0.0) if (s_2x and s_2x.points_metrics) else None,
            remains_profitable_at_2x_inr=(s_2x.inr_metrics.net_pnl > 0.0) if (s_2x and s_2x.inr_metrics) else None,
            remains_profitable_at_3x_points=(s_3x.points_metrics.net_pnl > 0.0) if (s_3x and s_3x.points_metrics) else None,
            remains_profitable_at_3x_inr=(s_3x.inr_metrics.net_pnl > 0.0) if (s_3x and s_3x.inr_metrics) else None,
            scenarios=tuple(scenarios),
            warnings=tuple(dict.fromkeys(warnings)),
            assumptions=assumptions,
        )

