"""
AIVOLVE Phase 4 Step 4.5 — Module C: Transaction Cost Stress Engine.

Applies baseline (1.0x) and stressed (1.25x, 1.5x, 2.0x, configurable) multipliers
to non-slippage transaction costs (brokerage, STT, exchange charges, GST at preserved
gst_rate, SEBI charges, stamp duty), strictly separated from slippage.
Fails explicitly with NOT_APPLICABLE_IN_DOMAIN on pure INDEX_POINTS_ONLY runs
without ever inventing statutory INR rates.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from app.backtesting.analytics_models import domain_has_inr, validate_run_domain_integrity
from app.backtesting.performance_analytics import PerformanceAnalyticsEngine
from app.backtesting.risk_analytics import RiskAnalyticsEngine, sort_closed_trades
from app.backtesting.robustness_models import (
    RobustnessStatus,
    TransactionCostScenarioResult,
    TransactionCostStressConfig,
    TransactionCostStressResult,
    build_stressed_simulation_run,
    compute_cost_components_breakdown,
    evaluate_stressed_run,
)
from app.backtesting.simulation_models import (
    AccountingUnitMode,
    FillRecord,
    SimulationRunResult,
    SimulationStatus,
    TradeRecord,
)


def _scale_fill_transaction_fees(
    _trade: TradeRecord,
    fill: FillRecord,
    multiplier: float,
    gst_rate: float,
) -> FillRecord:
    if abs(multiplier - 1.0) <= 1e-12:
        return fill

    c = fill.costs
    new_brok = round(float(c.brokerage_inr or 0.0) * multiplier, 6)
    new_stt = round(float(c.stt_inr or 0.0) * multiplier, 6)
    new_exch = round(float(c.exchange_txn_charges_inr or 0.0) * multiplier, 6)
    new_gst = round((new_brok + new_exch) * gst_rate, 6)
    new_sebi = round(float(c.sebi_charges_inr or 0.0) * multiplier, 6)
    new_stamp = round(float(c.stamp_duty_inr or 0.0) * multiplier, 6)
    new_brok_stat = round(new_brok + new_stt + new_exch + new_gst + new_sebi + new_stamp, 6)

    fixed_slip = float(c.slippage_cost_inr or 0.0)
    new_total_costs = round(new_brok_stat + fixed_slip, 6)
    d_cost = new_total_costs - float(c.total_costs_inr or 0.0)
    new_net_inr_leg = (
        round(float(fill.net_pnl_inr_impact_leg or 0.0) - d_cost, 6)
        if fill.net_pnl_inr_impact_leg is not None
        else fill.net_pnl_inr_impact_leg
    )

    new_costs = c.model_copy(
        update={
            "brokerage_inr": new_brok,
            "stt_inr": new_stt,
            "exchange_txn_charges_inr": new_exch,
            "gst_inr": new_gst,
            "sebi_charges_inr": new_sebi,
            "stamp_duty_inr": new_stamp,
            "brokerage_and_statutory_inr": new_brok_stat,
            "total_costs_inr": new_total_costs,
        }
    )
    return fill.model_copy(
        update={
            "net_pnl_inr_impact_leg": new_net_inr_leg,
            "costs": new_costs,
        }
    )


class TransactionCostStressEngine:
    """Stateless deterministic evaluator of non-slippage transaction fee & tax sensitivity."""

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
        config: Optional[TransactionCostStressConfig] = None,
    ) -> TransactionCostStressResult:
        validate_run_domain_integrity(run)
        cfg = config or TransactionCostStressConfig()
        um = run.accounting_unit_mode

        assumptions = (
            "Non-slippage fee stress scales brokerage, STT, exchange transaction charges, SEBI turnover fee, and stamp duty uniformly while preserving statutory GST rate on stressed brokerage+exchange.",
            "Fill slippage and executed prices remain fixed so slippage sensitivity is never conflated with fee sensitivity.",
        )

        if run.status != SimulationStatus.COMPLETED:
            return TransactionCostStressResult(
                status=RobustnessStatus.RUN_NOT_COMPLETED,
                accounting_unit_mode=um,
                provenance_label=run.provenance_label,
                is_synthetic_modelled=run.is_synthetic_modelled,
                monetary_charges_applicable=domain_has_inr(um) and run.cost_schedule.monetary_charges_enabled,
                gst_rate_preserved=float(run.cost_schedule.gst_rate) if domain_has_inr(um) else None,
                config=cfg,
                warnings=(f"RUN_NOT_COMPLETED: SimulationRunResult status is '{run.status.value}'.",),
                assumptions=assumptions,
            )

        if um == AccountingUnitMode.INDEX_POINTS_ONLY or not run.cost_schedule.monetary_charges_enabled:
            return TransactionCostStressResult(
                status=RobustnessStatus.NOT_APPLICABLE_IN_DOMAIN,
                accounting_unit_mode=um,
                provenance_label=run.provenance_label,
                is_synthetic_modelled=run.is_synthetic_modelled,
                monetary_charges_applicable=False,
                gst_rate_preserved=None,
                config=cfg,
                warnings=(
                    "NOT_APPLICABLE_IN_DOMAIN: Transaction cost stress requires enabled INR monetary accounting; "
                    "statutory rates are never invented for INDEX_POINTS_ONLY runs.",
                ),
                assumptions=assumptions,
            )

        closed_trades = sort_closed_trades(run.trades)
        if not closed_trades:
            return TransactionCostStressResult(
                status=RobustnessStatus.NO_TRADES,
                accounting_unit_mode=um,
                provenance_label=run.provenance_label,
                is_synthetic_modelled=run.is_synthetic_modelled,
                monetary_charges_applicable=True,
                gst_rate_preserved=float(run.cost_schedule.gst_rate),
                config=cfg,
                warnings=("NO_CLOSED_TRADES: Transaction cost stress requires at least one closed trade.",),
                assumptions=assumptions,
            )

        warnings: List[str] = []
        gst_rate = float(run.cost_schedule.gst_rate)
        closed_bs_inr = sum(float(t.total_brokerage_and_statutory_inr or 0.0) for t in closed_trades)
        if closed_bs_inr <= 1e-12:
            warnings.append(
                "ZERO_BASELINE_STATUTORY_FEES: Baseline fills contain zero brokerage/statutory fees; fee multipliers produce zero fee delta."
            )

        base_pts_m, base_inr_m = evaluate_stressed_run(run, risk_engine=self._risk, perf_engine=self._perf)
        assert base_inr_m is not None
        base_net_inr = base_inr_m.net_pnl

        scenarios: List[TransactionCostScenarioResult] = []
        by_mult: Dict[float, TransactionCostScenarioResult] = {}

        for mult in cfg.multipliers:
            if abs(mult - 1.0) <= 1e-12:
                stressed_run = run
                pts_m, inr_m = base_pts_m, base_inr_m
            else:
                sched = run.cost_schedule
                new_sched = sched.model_copy(
                    update={
                        "brokerage_per_order_inr": round(float(sched.brokerage_per_order_inr) * mult, 8),
                        "stt_sell_rate": round(float(sched.stt_sell_rate) * mult, 10),
                        "exchange_txn_rate": round(float(sched.exchange_txn_rate) * mult, 10),
                        "sebi_turnover_rate": round(float(sched.sebi_turnover_rate) * mult, 10),
                        "stamp_duty_buy_rate": round(float(sched.stamp_duty_buy_rate) * mult, 10),
                    }
                )
                stressed_run = build_stressed_simulation_run(
                    run,
                    lambda t, f, _m=mult: _scale_fill_transaction_fees(t, f, _m, gst_rate),
                    new_cost_schedule=new_sched,
                )
                pts_m, inr_m = evaluate_stressed_run(
                    stressed_run,
                    risk_engine=self._risk,
                    perf_engine=self._perf,
                )

            assert inr_m is not None
            breakdown = compute_cost_components_breakdown(stressed_run)
            delta_inr = round(inr_m.net_pnl - base_net_inr, 6)
            ret_inr = round(inr_m.net_pnl / base_net_inr, 6) if base_net_inr > 1e-12 else None

            scen = TransactionCostScenarioResult(
                multiplier=mult,
                is_baseline=abs(mult - 1.0) <= 1e-12,
                accounting_unit_mode=um,
                provenance_label=run.provenance_label,
                cost_components=breakdown,
                points_metrics=pts_m,
                inr_metrics=inr_m,
                net_pnl_delta_inr_vs_baseline=delta_inr,
                net_pnl_retention_ratio_inr=ret_inr,
            )
            scenarios.append(scen)
            by_mult[round(mult, 6)] = scen

        be_mult_inr: Optional[float] = None
        if closed_bs_inr > 1e-12:
            pre_fee_net = base_net_inr + closed_bs_inr
            if pre_fee_net > 0.0:
                be_mult_inr = round(pre_fee_net / closed_bs_inr, 6)
            else:
                warnings.append("UNPROFITABLE_BEFORE_STATUTORY_FEES: Closed-trade net INR is <= 0 even before brokerage and taxes.")

        s_2x = by_mult.get(2.0)

        return TransactionCostStressResult(
            status=RobustnessStatus.COMPLETED,
            accounting_unit_mode=um,
            provenance_label=run.provenance_label,
            is_synthetic_modelled=run.is_synthetic_modelled,
            monetary_charges_applicable=True,
            gst_rate_preserved=gst_rate,
            config=cfg,
            break_even_cost_multiplier_inr=be_mult_inr,
            remains_profitable_at_2x_inr=(s_2x.inr_metrics.net_pnl > 0.0) if (s_2x and s_2x.inr_metrics) else None,
            scenarios=tuple(scenarios),
            warnings=tuple(dict.fromkeys(warnings)),
            assumptions=assumptions,
        )

