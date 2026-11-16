"""
AIVOLVE Phase 4 Step 4.5 — Module E: Controlled Parameter Sensitivity Engine.

Measures strategy stability across explicitly supplied ParameterVariationSpec
perturbations via non-persisting isolated counterfactual re-simulations OR
homogeneous precomputed SimulationRunResult cohorts.

Strict Anti-Overfitting Guardrails:
- auto_optimization_performed is ALWAYS False
- best_parameter_selected is ALWAYS None
- strategy_config_modified is ALWAYS False
- Never runs silent grid searches or mutates production strategy configurations.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

import pandas as pd

from app.backtesting.analytics_models import (
    domain_has_inr,
    domain_has_points,
    validate_homogeneous_runs,
    validate_run_domain_integrity,
)
from app.backtesting.cost_model import SyntheticOptionCostConfig, UnderlyingPointsCostConfig
from app.backtesting.execution_simulator import HistoricalExecutionSimulator
from app.backtesting.performance_analytics import PerformanceAnalyticsEngine
from app.backtesting.risk_analytics import RiskAnalyticsEngine
from app.backtesting.robustness_models import (
    ParameterSensitivityResult,
    ParameterVariantResult,
    ParameterVariationSpec,
    RobustnessDomainMetrics,
    RobustnessStatus,
    StabilityClassification,
    evaluate_stressed_run,
)
from app.backtesting.simulation_models import (
    AccountingUnitMode,
    SimulationConfiguration,
    SimulationMode,
    SimulationRunResult,
    SimulationSignal,
    SimulationStatus,
    TriggerPriceDomain,
)


def _cost_configs_from_run(
    run: SimulationRunResult,
    *,
    slippage_override: Optional[float] = None,
) -> Tuple[Optional[UnderlyingPointsCostConfig], Optional[SyntheticOptionCostConfig]]:
    sched = run.cost_schedule
    slip = float(slippage_override if slippage_override is not None else sched.slippage_per_unit)
    common_kwargs = {
        "brokerage_per_order": sched.brokerage_per_order_inr,
        "stt_sell_rate": sched.stt_sell_rate,
        "exchange_txn_rate": sched.exchange_txn_rate,
        "gst_rate": sched.gst_rate,
        "sebi_turnover_rate": sched.sebi_turnover_rate,
        "stamp_duty_buy_rate": sched.stamp_duty_buy_rate,
        "slippage_per_unit": slip,
    }
    if run.mode == SimulationMode.UNDERLYING_POINTS_ONLY:
        return UnderlyingPointsCostConfig(**common_kwargs), None
    return None, SyntheticOptionCostConfig(**common_kwargs)


def _sim_config_from_run(run: SimulationRunResult) -> SimulationConfiguration:
    is_pts = run.mode == SimulationMode.UNDERLYING_POINTS_ONLY
    mon = run.portfolio.monetary_accounting_enabled
    return SimulationConfiguration(
        mode=run.mode,
        monetary_accounting_enabled=mon,
        starting_capital_inr=run.portfolio.starting_capital_inr if mon else None,
        instrument_multiplier_inr_per_point=run.portfolio.instrument_multiplier_inr_per_point if is_pts and mon else None,
        instrument_multiplier_documentation=run.portfolio.instrument_multiplier_documentation if is_pts and mon else None,
        ambiguity_policy=run.ambiguity_policy,
        gap_policy=run.gap_policy,
        require_verified_data_store=False,
    )


def _estimate_anchor(sig: SimulationSignal, entry_lookup: Dict[str, float]) -> float:
    if sig.signal_id in entry_lookup:
        return entry_lookup[sig.signal_id]
    if sig.entry_zone_min is not None and sig.entry_zone_max is not None:
        return 0.5 * (float(sig.entry_zone_min) + float(sig.entry_zone_max))
    if sig.entry_zone_min is not None:
        return float(sig.entry_zone_min)
    if sig.entry_zone_max is not None:
        return float(sig.entry_zone_max)
    return 0.5 * (float(sig.stop_loss) + float(sig.target_1))


def _is_upward_trigger(sig: SimulationSignal) -> bool:
    if sig.trigger_domain == TriggerPriceDomain.SYNTHETIC_OPTION_PREMIUM:
        return True
    is_pe_spot = (
        sig.synthetic_bs_assumptions is not None
        and sig.synthetic_bs_assumptions.option_type == "PE"
    )
    return sig.stop_loss < sig.target_1 and not is_pe_spot


def _apply_variation_to_signal(
    sig: SimulationSignal,
    spec: ParameterVariationSpec,
    entry_lookup: Dict[str, float],
    tick_size: float,
) -> SimulationSignal:
    p = spec.parameter_name
    anchor = _estimate_anchor(sig, entry_lookup)
    upward = _is_upward_trigger(sig)

    if p == "stop_loss":
        if spec.override_value is not None:
            new_sl = max(tick_size, round(float(spec.override_value), 4))
        else:
            assert spec.factor is not None
            dist = max(tick_size, abs(anchor - float(sig.stop_loss)) * spec.factor)
            new_sl = max(tick_size, round(anchor - dist if upward else anchor + dist, 4))
        # Preserve strict signal geometry invariant relative to target_1
        if upward and new_sl >= sig.target_1:
            new_sl = max(tick_size, round(sig.target_1 - tick_size, 4))
        elif not upward and new_sl <= sig.target_1:
            new_sl = round(sig.target_1 + tick_size, 4)
        return sig.model_copy(update={"stop_loss": new_sl})

    if p == "target_1":
        if spec.override_value is not None:
            new_t1 = max(tick_size, round(float(spec.override_value), 4))
        else:
            assert spec.factor is not None
            dist = max(tick_size, abs(float(sig.target_1) - anchor) * spec.factor)
            new_t1 = max(tick_size, round(anchor + dist if upward else anchor - dist, 4))
        new_t2 = sig.target_2
        if upward:
            if new_t1 <= sig.stop_loss:
                new_t1 = round(sig.stop_loss + tick_size, 4)
            if new_t2 is not None and new_t2 <= new_t1:
                new_t2 = round(new_t1 + tick_size, 4)
        else:
            if new_t1 >= sig.stop_loss:
                new_t1 = max(tick_size, round(sig.stop_loss - tick_size, 4))
            if new_t2 is not None and new_t2 >= new_t1:
                new_t2 = max(tick_size, round(new_t1 - tick_size, 4))
        return sig.model_copy(update={"target_1": new_t1, "target_2": new_t2})

    if p == "target_2":
        if sig.target_2 is None:
            return sig
        if spec.override_value is not None:
            new_t2 = max(tick_size, round(float(spec.override_value), 4))
        else:
            assert spec.factor is not None
            dist = max(tick_size, abs(float(sig.target_2) - anchor) * spec.factor)
            new_t2 = max(tick_size, round(anchor + dist if upward else anchor - dist, 4))
        if upward and new_t2 <= sig.target_1:
            new_t2 = round(sig.target_1 + tick_size, 4)
        elif not upward and new_t2 >= sig.target_1:
            new_t2 = max(tick_size, round(sig.target_1 - tick_size, 4))
        return sig.model_copy(update={"target_2": new_t2})

    if p == "partial_exit_fraction":
        raw_val = float(spec.override_value) if spec.override_value is not None else float(sig.partial_exit_fraction) * float(spec.factor or 1.0)
        clamped = max(0.05, min(0.95, round(raw_val, 4)))
        return sig.model_copy(update={"partial_exit_fraction": clamped})

    if p == "max_entry_wait_bars":
        raw_bars = int(spec.override_value) if spec.override_value is not None else round(sig.max_entry_wait_bars * float(spec.factor or 1.0))
        clamped_bars = max(1, min(50, raw_bars))
        return sig.model_copy(update={"max_entry_wait_bars": clamped_bars})

    if p == "intraday_square_off":
        val = bool(spec.override_value) if spec.override_value is not None else sig.intraday_square_off
        return sig.model_copy(update={"intraday_square_off": val})

    return sig


def _classify_stability(
    *,
    variant_results: Sequence[ParameterVariantResult],
    baseline_pts: Optional[RobustnessDomainMetrics],
    baseline_inr: Optional[RobustnessDomainMetrics],
) -> Tuple[
    StabilityClassification,
    int,
    Optional[float],
    Optional[float],
    Optional[float],
    Optional[float],
]:
    if len(variant_results) < 2:
        return StabilityClassification.INSUFFICIENT_DATA, 0, None, None, None, None

    use_inr_primary = baseline_inr is not None
    base_primary = baseline_inr if use_inr_primary else baseline_pts
    if base_primary is None or base_primary.total_closed_trades == 0:
        return StabilityClassification.INSUFFICIENT_DATA, 0, None, None, None, None

    def _calc_domain(
        getter,
        base_dom: Optional[RobustnessDomainMetrics],
    ) -> Tuple[Optional[float], Optional[float]]:
        if base_dom is None:
            return None, None
        nets = [getter(v).net_pnl for v in variant_results if getter(v) is not None]
        dds = [getter(v).max_drawdown for v in variant_results if getter(v) is not None]
        disp: Optional[float] = None
        if nets and abs(base_dom.net_pnl) > 1e-9:
            disp = round((max(nets) - min(nets)) / abs(base_dom.net_pnl), 6)
        dd_ratio: Optional[float] = None
        if dds:
            if base_dom.max_drawdown > 1e-9:
                dd_ratio = round(max(dds) / base_dom.max_drawdown, 6)
            elif max(dds) == 0.0:
                dd_ratio = 1.0
        return disp, dd_ratio

    disp_pts, dd_pts = _calc_domain(lambda v: v.points_metrics, baseline_pts)
    disp_inr, dd_inr = _calc_domain(lambda v: v.inr_metrics, baseline_inr)

    base_sign = 1 if base_primary.net_pnl > 1e-9 else (-1 if base_primary.net_pnl < -1e-9 else 0)
    sign_flips = 0
    for v in variant_results:
        if v.is_baseline:
            continue
        dom = v.inr_metrics if use_inr_primary else v.points_metrics
        if dom is None:
            continue
        v_sign = 1 if dom.net_pnl > 1e-9 else (-1 if dom.net_pnl < -1e-9 else 0)
        if base_sign != 0 and v_sign != base_sign:
            sign_flips += 1

    prim_disp = disp_inr if use_inr_primary else disp_pts
    prim_dd = dd_inr if use_inr_primary else dd_pts

    if (
        sign_flips > 0
        or (prim_disp is not None and prim_disp > 1.0)
        or (prim_dd is not None and prim_dd > 1.75)
    ):
        stab = StabilityClassification.UNSTABLE
    elif (
        (prim_disp is not None and prim_disp > 0.35)
        or (prim_dd is not None and prim_dd > 1.25)
    ):
        stab = StabilityClassification.MODERATELY_SENSITIVE
    else:
        stab = StabilityClassification.STABLE

    return stab, sign_flips, disp_pts, disp_inr, dd_pts, dd_inr


class ParameterSensitivityEngine:
    """Stateless controlled sensitivity evaluator (zero auto-optimization)."""

    def __init__(
        self,
        risk_engine: Optional[RiskAnalyticsEngine] = None,
        perf_engine: Optional[PerformanceAnalyticsEngine] = None,
    ) -> None:
        self._risk = risk_engine or RiskAnalyticsEngine()
        self._perf = perf_engine or PerformanceAnalyticsEngine(risk_engine=self._risk)

    def evaluate_precomputed_runs(
        self,
        *,
        baseline_run: SimulationRunResult,
        variant_runs: Sequence[Tuple[ParameterVariationSpec, SimulationRunResult]],
    ) -> ParameterSensitivityResult:
        """Evaluates precomputed homogeneous SimulationRunResult objects for each explicit ParameterVariationSpec."""
        all_runs = [baseline_run, *[r for _, r in variant_runs]]
        um, prov, is_synth = validate_homogeneous_runs(all_runs)

        if baseline_run.status != SimulationStatus.COMPLETED:
            return ParameterSensitivityResult(
                status=RobustnessStatus.RUN_NOT_COMPLETED,
                accounting_unit_mode=um,
                provenance_label=prov,
                is_synthetic_modelled=is_synth,
                evaluation_mode="PRECOMPUTED_RUNS",
                stability_classification=StabilityClassification.INSUFFICIENT_DATA,
                variants_evaluated=0,
                sign_flips_vs_baseline_count=0,
                warnings=(f"RUN_NOT_COMPLETED: Baseline run status is '{baseline_run.status.value}'.",),
            )

        base_pts, base_inr = evaluate_stressed_run(
            baseline_run,
            risk_engine=self._risk,
            perf_engine=self._perf,
        )
        rows: List[ParameterVariantResult] = [
            ParameterVariantResult(
                variation_id="BASELINE",
                label="Baseline",
                is_baseline=True,
                parameter_name="baseline",
                parameter_value_description="1.0x (baseline)",
                simulated_run_id=baseline_run.run_id,
                accounting_unit_mode=um,
                provenance_label=prov,
                points_metrics=base_pts,
                inr_metrics=base_inr,
                net_pnl_delta_points_vs_baseline=0.0 if base_pts is not None else None,
                net_pnl_delta_inr_vs_baseline=0.0 if base_inr is not None else None,
            )
        ]

        warnings: List[str] = []
        for spec, vrun in variant_runs:
            if vrun.status != SimulationStatus.COMPLETED:
                warnings.append(
                    f"VARIANT_NOT_COMPLETED: '{spec.variation_id}' status is '{vrun.status.value}' and was skipped."
                )
                continue
            v_pts, v_inr = evaluate_stressed_run(vrun, risk_engine=self._risk, perf_engine=self._perf)
            desc = (
                f"factor={spec.factor}"
                if spec.factor is not None
                else f"override={spec.override_value}"
            )
            rows.append(
                ParameterVariantResult(
                    variation_id=spec.variation_id,
                    label=spec.label,
                    is_baseline=False,
                    parameter_name=spec.parameter_name,
                    parameter_value_description=desc,
                    simulated_run_id=vrun.run_id,
                    accounting_unit_mode=um,
                    provenance_label=prov,
                    points_metrics=v_pts,
                    inr_metrics=v_inr,
                    net_pnl_delta_points_vs_baseline=(
                        round(v_pts.net_pnl - base_pts.net_pnl, 6)
                        if (v_pts is not None and base_pts is not None)
                        else None
                    ),
                    net_pnl_delta_inr_vs_baseline=(
                        round(v_inr.net_pnl - base_inr.net_pnl, 6)
                        if (v_inr is not None and base_inr is not None)
                        else None
                    ),
                )
            )

        stab, flips, disp_pts, disp_inr, dd_pts, dd_inr = _classify_stability(
            variant_results=rows,
            baseline_pts=base_pts,
            baseline_inr=base_inr,
        )
        return ParameterSensitivityResult(
            status=(
                RobustnessStatus.INSUFFICIENT_DATA
                if stab == StabilityClassification.INSUFFICIENT_DATA
                else RobustnessStatus.COMPLETED
            ),
            accounting_unit_mode=um,
            provenance_label=prov,
            is_synthetic_modelled=is_synth,
            evaluation_mode="PRECOMPUTED_RUNS",
            stability_classification=stab,
            variants_evaluated=len(rows),
            sign_flips_vs_baseline_count=flips,
            relative_net_pnl_dispersion_points=disp_pts,
            relative_net_pnl_dispersion_inr=disp_inr,
            max_drawdown_expansion_ratio_points=dd_pts,
            max_drawdown_expansion_ratio_inr=dd_inr,
            variants=tuple(rows),
            warnings=tuple(dict.fromkeys(warnings)),
        )

    def evaluate_controlled_variations(
        self,
        *,
        baseline_run: SimulationRunResult,
        variations: Sequence[ParameterVariationSpec],
        signals: Optional[Sequence[SimulationSignal]] = None,
        candles_df: Optional[pd.DataFrame] = None,
        base_sim_config: Optional[SimulationConfiguration] = None,
    ) -> ParameterSensitivityResult:
        """
        Re-simulates controlled parameter perturbations with `persist=False` over
        the exact same verified historical bars without ever auto-optimizing.
        """
        validate_run_domain_integrity(baseline_run)
        um = baseline_run.accounting_unit_mode
        prov = baseline_run.provenance_label

        if baseline_run.status != SimulationStatus.COMPLETED:
            return ParameterSensitivityResult(
                status=RobustnessStatus.RUN_NOT_COMPLETED,
                accounting_unit_mode=um,
                provenance_label=prov,
                is_synthetic_modelled=baseline_run.is_synthetic_modelled,
                evaluation_mode="NOT_EVALUATED",
                stability_classification=StabilityClassification.INSUFFICIENT_DATA,
                variants_evaluated=0,
                sign_flips_vs_baseline_count=0,
                warnings=(f"RUN_NOT_COMPLETED: Baseline run status is '{baseline_run.status.value}'.",),
            )

        if not variations or not signals or candles_df is None or candles_df.empty:
            return ParameterSensitivityResult(
                status=RobustnessStatus.INSUFFICIENT_DATA,
                accounting_unit_mode=um,
                provenance_label=prov,
                is_synthetic_modelled=baseline_run.is_synthetic_modelled,
                evaluation_mode="NOT_EVALUATED",
                stability_classification=StabilityClassification.INSUFFICIENT_DATA,
                variants_evaluated=0,
                sign_flips_vs_baseline_count=0,
                warnings=(
                    "PARAMETER_VARIATIONS_NOT_EVALUATED: Controlled re-simulation requires non-empty "
                    "`variations`, original `signals`, and verified `candles_df` (or pass precomputed variant runs).",
                ),
            )

        sim_cfg = base_sim_config or _sim_config_from_run(baseline_run)
        entry_lookup: Dict[str, float] = {
            t.signal_id: float(t.entry_price)
            for t in baseline_run.trades
            if t.entry_price is not None
        }

        variant_runs: List[Tuple[ParameterVariationSpec, SimulationRunResult]] = []
        for spec in variations:
            slip_override: Optional[float] = None
            if spec.parameter_name == "slippage_per_unit":
                if spec.override_value is not None:
                    slip_override = max(0.0, float(spec.override_value))
                else:
                    assert spec.factor is not None
                    slip_override = max(0.0, float(baseline_run.cost_schedule.slippage_per_unit) * spec.factor)

            pts_cost_cfg, opt_cost_cfg = _cost_configs_from_run(
                baseline_run,
                slippage_override=slip_override,
            )
            mod_signals = tuple(
                _apply_variation_to_signal(s, spec, entry_lookup, sim_cfg.tick_size)
                for s in signals
            )
            simulator = HistoricalExecutionSimulator(
                config=sim_cfg,
                points_cost_config=pts_cost_cfg,
                option_cost_config=opt_cost_cfg,
            )
            v_run = simulator.run_simulation(
                instrument=baseline_run.instrument,
                timeframe=baseline_run.timeframe,
                signals=mod_signals,
                candles_df=candles_df,
                replay_run_id=baseline_run.replay_run_id,
                persist=False,
            )
            variant_runs.append((spec, v_run))

        res = self.evaluate_precomputed_runs(baseline_run=baseline_run, variant_runs=variant_runs)
        return res.model_copy(update={"evaluation_mode": "CONTROLLED_RESIMULATION"})

