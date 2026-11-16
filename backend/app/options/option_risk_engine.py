"""
AIVOLVE Quantitative Options Intelligence Engine v3.0
Phase 2 Step 4.2: Option Risk Engine & Scenario-Based Premium Repricing.

Translates structurally validated underlying index trade setups into authoritative
option premium risk plans:
  - Non-linear Black-Scholes scenario repricing at structural invalidation & targets
  - Conservative execution pricing: Entry strictly at Ask, Exit at Bid (BS Mid minus half-spread) less slippage
  - Double-counting prevention: explicitly differentiates bid-ask spread crossing from slippage
  - Explicit scenario holding horizons labeled as uncalibrated quantitative assumptions
  - Relative IV stress modeling (Adverse crush at SL, Favorable expansion at Targets)
  - Independent target Reward-to-Risk evaluation (RR_T1, RR_T2, RR_T3) with zero concealment
  - Input auditing for Black-Scholes (r, q, iv_source, t, S, K) with theoretical model disclaimer
  - Zero-invention position sizing rule & capital budgeting
  - Paper-trading intelligence only. No live broker execution.
"""

from typing import Dict, Any, List, Optional
import math
from app.options.greeks import calculate_black_scholes

# Default scenario holding-time horizons (in minutes)
# Institutional Status: UNCALIBRATED ASSUMPTIONS.
DEFAULT_SCENARIO_HORIZONS = {
    "stop_loss_minutes": 30.0,
    "target_1_minutes": 45.0,
    "target_2_minutes": 75.0,
    "target_3_minutes": 120.0,
    "calibration_status": "ASSUMPTION",
    "calibration_notes": "Holding-time horizons are uncalibrated quantitative scenario assumptions; not statistically validated on out-of-sample trade data.",
}


def round_to_tick(price: float, tick_size: float = 0.05, mode: str = "floor") -> float:
    """
    Rounds an option premium to the authoritative exchange tick size.
    Modes:
      - 'floor': Conservative exit rounding (understates stop-loss & targets for capital protection)
      - 'ceil': Conservative entry rounding (overstates entry cost)
      - 'nearest': Standard rounding
    """
    if tick_size <= 0.0:
        return round(price, 2)
    ticks = price / tick_size
    if mode == "floor":
        rounded_ticks = math.floor(ticks + 1e-9)
    elif mode == "ceil":
        rounded_ticks = math.ceil(ticks - 1e-9)
    else:
        rounded_ticks = round(ticks)
    return round(rounded_ticks * tick_size, 4)


def calculate_option_risk_plan(
    underlying_setup: Dict[str, Any],
    selected_contract: Dict[str, Any],
    risk_config: Optional[Dict[str, Any]] = None,
    available_capital: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Converts underlying index trade plan into an authoritative option premium risk plan.
    
    CRITICAL: Does NOT use linear delta approximations (Option SL != Premium - Delta * Index SL Distance).
    Implements Black-Scholes non-linear repricing under structural scenario conditions.
    """
    cfg = risk_config or {}
    rejection_reasons: List[str] = []

    # 1. Selected Contract Qualification Check
    if not selected_contract or selected_contract.get("qualification_status") != "QUALIFIED":
        passed_reasons = selected_contract.get("rejection_reasons", []) if selected_contract else []
        reasons = passed_reasons if passed_reasons else ["Selected option contract is not qualified"]
        return {
            "qualification_status": "REJECTED",
            "action": underlying_setup.get("action", "NO_TRADE"),
            "index": selected_contract.get("index") if selected_contract else "UNKNOWN",
            "option_type": selected_contract.get("option_type") if selected_contract else None,
            "contract_symbol": selected_contract.get("contract_symbol") if selected_contract else None,
            "instrument_token": selected_contract.get("instrument_token") if selected_contract else None,
            "strike": selected_contract.get("strike") if selected_contract else None,
            "expiry": selected_contract.get("expiry") if selected_contract else None,
            "moneyness": selected_contract.get("moneyness") if selected_contract else None,
            "lot_size": selected_contract.get("lot_size") if selected_contract else None,
            "tick_size": selected_contract.get("tick_size") if selected_contract else None,
            "entry_execution_model": "ASK",
            "entry_premium": None,
            "analytical_midpoint": None,
            "bid": None,
            "ask": None,
            "spread_pct": None,
            "delta": None,
            "gamma": None,
            "theta": None,
            "vega": None,
            "implied_volatility": None,
            "iv_source": None,
            "underlying_entry": underlying_setup.get("entry_price"),
            "underlying_stop_loss": underlying_setup.get("stop_loss"),
            "underlying_targets": {
                "target_1": underlying_setup.get("target_1"),
                "target_2": underlying_setup.get("target_2"),
                "target_3": underlying_setup.get("target_3"),
            },
            "option_stop_loss": None,
            "option_target_1": None,
            "option_target_2": None,
            "option_target_3": None,
            "risk_per_unit": None,
            "risk_per_lot": None,
            "total_premium_exposure": None,
            "reward_to_risk": {
                "rr_t1": None,
                "rr_t2": None,
                "rr_t3": None,
                "rr_t1_qualified": False,
                "rr_t2_qualified": False,
                "rr_t3_qualified": False,
                "composite_qualified": False,
            },
            "position_sizing_status": "UNAVAILABLE",
            "data_status": selected_contract.get("data_status", "DATA_UNAVAILABLE") if selected_contract else "DATA_UNAVAILABLE",
            "execution_assumptions": {},
            "scenario_horizons": {},
            "iv_stress_model": {},
            "model_audit": {},
            "rejection_reasons": reasons,
            "paper_trading_eligible": False,
        }

    # Verify that quote is not theoretical
    if selected_contract.get("isTheoretical") is True or selected_contract.get("data_status") == "THEORETICAL":
        return {
            "qualification_status": "REJECTED",
            "action": underlying_setup.get("action", "NO_TRADE"),
            "index": selected_contract.get("index"),
            "option_type": selected_contract.get("option_type"),
            "contract_symbol": selected_contract.get("contract_symbol"),
            "instrument_token": selected_contract.get("instrument_token"),
            "strike": selected_contract.get("strike"),
            "expiry": selected_contract.get("expiry"),
            "moneyness": selected_contract.get("moneyness"),
            "lot_size": selected_contract.get("lot_size"),
            "tick_size": selected_contract.get("tick_size"),
            "entry_execution_model": "ASK",
            "entry_premium": None,
            "analytical_midpoint": None,
            "bid": None,
            "ask": None,
            "spread_pct": None,
            "delta": None,
            "gamma": None,
            "theta": None,
            "vega": None,
            "implied_volatility": None,
            "iv_source": None,
            "underlying_entry": underlying_setup.get("entry_price"),
            "underlying_stop_loss": underlying_setup.get("stop_loss"),
            "underlying_targets": {
                "target_1": underlying_setup.get("target_1"),
                "target_2": underlying_setup.get("target_2"),
                "target_3": underlying_setup.get("target_3"),
            },
            "option_stop_loss": None,
            "option_target_1": None,
            "option_target_2": None,
            "option_target_3": None,
            "risk_per_unit": None,
            "risk_per_lot": None,
            "total_premium_exposure": None,
            "reward_to_risk": {
                "rr_t1": None,
                "rr_t2": None,
                "rr_t3": None,
                "rr_t1_qualified": False,
                "rr_t2_qualified": False,
                "rr_t3_qualified": False,
                "composite_qualified": False,
            },
            "position_sizing_status": "UNAVAILABLE",
            "data_status": "THEORETICAL",
            "execution_assumptions": {},
            "scenario_horizons": {},
            "iv_stress_model": {},
            "model_audit": {},
            "rejection_reasons": ["Selected contract has theoretical quote; live market quote required for risk planning"],
            "paper_trading_eligible": False,
        }

    # 2. Extract & Validate Underlying Geometry
    action = underlying_setup.get("action")
    is_call = (action == "BUY_CE")
    opt_type = "CE" if is_call else "PE"

    spot_entry = float(underlying_setup.get("entry_price") or 0.0)
    sl_spot = float(underlying_setup.get("stop_loss") or 0.0)
    t1_spot = float(underlying_setup.get("target_1") or 0.0)
    t2_spot = float(underlying_setup.get("target_2") or 0.0)
    has_explicit_t3 = (underlying_setup.get("target_3") is not None and float(underlying_setup.get("target_3") or 0.0) > 0.0)
    t3_spot = float(underlying_setup.get("target_3")) if has_explicit_t3 else t2_spot

    if spot_entry <= 0.0 or sl_spot <= 0.0 or t1_spot <= 0.0 or t2_spot <= 0.0:
        rejection_reasons.append("Underlying setup contains non-positive entry, stop-loss, or target levels")
    elif is_call and not (sl_spot < spot_entry < t1_spot <= t2_spot):
        rejection_reasons.append(f"Invalid underlying Call geometry: SL({sl_spot}) < Entry({spot_entry}) < T1({t1_spot}) <= T2({t2_spot}) violated")
    elif not is_call and not (sl_spot > spot_entry > t1_spot >= t2_spot):
        rejection_reasons.append(f"Invalid underlying Put geometry: SL({sl_spot}) > Entry({spot_entry}) > T1({t1_spot}) >= T2({t2_spot}) violated")

    # 3. Contract Core Parameters & Model Input Audit
    strike = float(selected_contract.get("strike") or 0.0)
    t0 = float(selected_contract.get("t_years") or 0.0)
    r = float(cfg.get("risk_free_rate", 0.065))
    q = float(cfg.get("dividend_yield", 0.0))  # 0.0 for European cash-settled index options
    iv_pct = float(selected_contract.get("implied_volatility") or 0.0)
    sigma0 = iv_pct / 100.0
    lot_size = int(selected_contract.get("lot_size") or 0)
    tick_size = float(selected_contract.get("tick_size") or 0.05)
    iv_source = selected_contract.get("iv_source", "BRENT_NUMERICAL")

    if strike <= 0.0:
        rejection_reasons.append(f"INVALID_STRIKE: Contract strike ({strike}) must be positive")
    if t0 <= 0.0:
        rejection_reasons.append(f"EXPIRED_CONTRACT: Time to expiry ({t0}) must be strictly positive")
    if r <= 0.0:
        rejection_reasons.append(f"INVALID_RISK_FREE_RATE: Risk-free rate ({r}) must be positive")
    if sigma0 <= 0.0:
        rejection_reasons.append(f"INVALID_IV: Implied volatility ({iv_pct}) must be strictly positive")
    if lot_size <= 0:
        rejection_reasons.append(f"INVALID_LOT_SIZE: Lot size ({lot_size}) must be positive")

    # Conservative Execution Price Model:
    # Entry strictly uses Ask!
    ask_0 = float(selected_contract.get("ask") or 0.0)
    bid_0 = float(selected_contract.get("bid") or 0.0)
    analytical_midpoint = selected_contract.get("analytical_midpoint") or round((bid_0 + ask_0) / 2.0, 2)
    entry_premium = ask_0 if ask_0 > 0.0 else float(selected_contract.get("entry_premium") or 0.0)

    if entry_premium <= 0.0:
        rejection_reasons.append("Option entry premium (Ask) is non-positive or unavailable")
    if bid_0 <= 0.0:
        rejection_reasons.append("Option bid depth is non-positive or unavailable")

    # Half-spread is the distance between mid-market valuation and bid fill
    half_spread = max(tick_size, round((ask_0 - bid_0) / 2.0, 4)) if ask_0 >= bid_0 else tick_size
    slippage_pts = float(cfg.get("slippage_pts", 0.0))

    if rejection_reasons:
        return {
            "qualification_status": "REJECTED",
            "action": action,
            "index": selected_contract.get("index", "UNKNOWN"),
            "option_type": opt_type,
            "contract_symbol": selected_contract.get("contract_symbol"),
            "instrument_token": selected_contract.get("instrument_token"),
            "strike": strike,
            "expiry": selected_contract.get("expiry"),
            "moneyness": selected_contract.get("moneyness"),
            "lot_size": lot_size,
            "tick_size": tick_size,
            "entry_execution_model": "ASK",
            "entry_premium": entry_premium if entry_premium > 0 else None,
            "analytical_midpoint": analytical_midpoint,
            "bid": bid_0,
            "ask": ask_0,
            "spread_pct": selected_contract.get("spread_pct"),
            "delta": selected_contract.get("delta"),
            "gamma": selected_contract.get("gamma"),
            "theta": selected_contract.get("theta"),
            "vega": selected_contract.get("vega"),
            "implied_volatility": iv_pct,
            "iv_source": iv_source,
            "underlying_entry": spot_entry,
            "underlying_stop_loss": sl_spot,
            "underlying_targets": {"target_1": t1_spot, "target_2": t2_spot, "target_3": t3_spot},
            "option_stop_loss": None,
            "option_target_1": None,
            "option_target_2": None,
            "option_target_3": None,
            "risk_per_unit": None,
            "risk_per_lot": None,
            "total_premium_exposure": None,
            "reward_to_risk": {
                "rr_t1": None,
                "rr_t2": None,
                "rr_t3": None,
                "rr_t1_qualified": False,
                "rr_t2_qualified": False,
                "rr_t3_qualified": False,
                "composite_qualified": False,
            },
            "position_sizing_status": "UNAVAILABLE",
            "data_status": selected_contract.get("data_status", "LIVE"),
            "execution_assumptions": {},
            "scenario_horizons": {},
            "iv_stress_model": {},
            "model_audit": {},
            "rejection_reasons": rejection_reasons,
            "paper_trading_eligible": False,
        }

    # 4. Holding-Time Scenario Horizons (Explicit Configuration)
    # Labeled as uncalibrated assumptions
    horizons_cfg = cfg.get("scenario_horizons", cfg.get("scenario_horizons_minutes", {}))
    sl_holding_min = float(horizons_cfg.get("stop_loss_minutes", horizons_cfg.get("stop_loss", DEFAULT_SCENARIO_HORIZONS["stop_loss_minutes"])))
    t1_holding_min = float(horizons_cfg.get("target_1_minutes", horizons_cfg.get("target_1", DEFAULT_SCENARIO_HORIZONS["target_1_minutes"])))
    t2_holding_min = float(horizons_cfg.get("target_2_minutes", horizons_cfg.get("target_2", DEFAULT_SCENARIO_HORIZONS["target_2_minutes"])))
    t3_holding_min = float(horizons_cfg.get("target_3_minutes", horizons_cfg.get("target_3", DEFAULT_SCENARIO_HORIZONS["target_3_minutes"])))

    # Compute remaining time to expiry in years; strictly prevent negative time
    t_sl = max(0.0, t0 - (sl_holding_min * 60.0 / (365.0 * 86400.0)))
    t_t1 = max(0.0, t0 - (t1_holding_min * 60.0 / (365.0 * 86400.0)))
    t_t2 = max(0.0, t0 - (t2_holding_min * 60.0 / (365.0 * 86400.0)))
    t_t3 = max(0.0, t0 - (t3_holding_min * 60.0 / (365.0 * 86400.0)))

    # 5. Configurable IV Stress Model (Relative Percentages)
    # Adverse Volatility Stress at Stop-Loss: e.g. -5% relative drop
    sl_iv_stress_pct = float(cfg.get("sl_iv_stress_pct", cfg.get("adverse_iv_stress_pct", -0.05)))
    sigma_sl = max(0.01, sigma0 * (1.0 + sl_iv_stress_pct))

    # Favorable Volatility Stress at Targets: e.g. +2% relative expansion
    target_iv_stress_pct = float(cfg.get("target_iv_stress_pct", 0.02))
    sigma_target = max(0.01, sigma0 * (1.0 + target_iv_stress_pct))

    # 6. Non-Linear Scenario Repricing via Black-Scholes
    # A. Stop-Loss Repricing
    bs_sl = calculate_black_scholes(sl_spot, strike, t_sl, r, sigma_sl, opt_type)
    if not bs_sl or bs_sl.get("price") is None:
        rejection_reasons.append("RISK_UNAVAILABLE: Black-Scholes repricing failed for stop-loss scenario")
        option_sl = 0.0
    else:
        raw_sl_premium = float(bs_sl["price"])
        # Friction deduction: sell into Bid (deduct half-spread) and apply additional slippage
        net_sl_premium = raw_sl_premium - half_spread - slippage_pts
        option_sl = round_to_tick(net_sl_premium, tick_size, mode="floor")

    # B. Targets Repricing
    bs_t1 = calculate_black_scholes(t1_spot, strike, t_t1, r, sigma_target, opt_type)
    bs_t2 = calculate_black_scholes(t2_spot, strike, t_t2, r, sigma_target, opt_type)

    if not bs_t1 or not bs_t2:
        rejection_reasons.append("RISK_UNAVAILABLE: Black-Scholes repricing failed for target scenarios")
        opt_t1, opt_t2, opt_t3 = 0.0, 0.0, 0.0
    else:
        raw_t1 = float(bs_t1["price"])
        raw_t2 = float(bs_t2["price"])
        opt_t1 = round_to_tick(raw_t1 - half_spread - slippage_pts, tick_size, mode="floor")
        opt_t2 = round_to_tick(raw_t2 - half_spread - slippage_pts, tick_size, mode="floor")

        if has_explicit_t3 and t3_spot != t2_spot:
            bs_t3 = calculate_black_scholes(t3_spot, strike, t_t3, r, sigma_target, opt_type)
            if bs_t3 and bs_t3.get("price") is not None:
                raw_t3 = float(bs_t3["price"])
                opt_t3 = round_to_tick(raw_t3 - half_spread - slippage_pts, tick_size, mode="floor")
            else:
                opt_t3 = opt_t2
        else:
            opt_t3 = opt_t2

    # 7. Stop-Loss & Target Geometry Validation
    if option_sl <= 0.0:
        rejection_reasons.append(f"INVALID_OPTION_STOP_GEOMETRY: Calculated option stop-loss (₹{option_sl}) is non-positive")
    if option_sl >= entry_premium:
        rejection_reasons.append(f"INVALID_OPTION_STOP_GEOMETRY: Stop-loss premium (₹{option_sl}) must be below entry (₹{entry_premium})")

    risk_per_unit = round(entry_premium - option_sl, 2)
    if risk_per_unit <= 0.0:
        rejection_reasons.append(f"INVALID_RISK_PER_UNIT: Non-positive risk per unit ({risk_per_unit})")

    if opt_t1 <= entry_premium:
        rejection_reasons.append(f"INVALID_TARGET_GEOMETRY: Target 1 premium (₹{opt_t1}) does not exceed entry premium (₹{entry_premium})")
    if opt_t2 < opt_t1:
        rejection_reasons.append(f"INVALID_TARGET_GEOMETRY: Target 2 premium (₹{opt_t2}) is below Target 1 (₹{opt_t1})")
    if opt_t3 < opt_t2:
        rejection_reasons.append(f"INVALID_TARGET_GEOMETRY: Target 3 premium (₹{opt_t3}) is below Target 2 (₹{opt_t2})")

    # 8. Independent Reward-to-Risk Calculation (RR_T1, RR_T2, RR_T3)
    # Zero concealment: T2 validity does not conceal T1 or T3 failure!
    reward_t1 = round(opt_t1 - entry_premium, 2)
    reward_t2 = round(opt_t2 - entry_premium, 2)
    reward_t3 = round(opt_t3 - entry_premium, 2)

    rr_t1 = round(reward_t1 / risk_per_unit, 2) if risk_per_unit > 0 else 0.0
    rr_t2 = round(reward_t2 / risk_per_unit, 2) if risk_per_unit > 0 else 0.0
    rr_t3 = round(reward_t3 / risk_per_unit, 2) if risk_per_unit > 0 else 0.0

    min_rr_t1 = float(cfg.get("min_rr_t1", 0.50))
    min_rr_t2 = float(cfg.get("min_reward_to_risk", cfg.get("min_rr_t2", 1.25)))  # Preserved 1.25 threshold
    min_rr_t3 = float(cfg.get("min_rr_t3", 1.50))

    rr_t1_qualified = (opt_t1 > entry_premium) and (rr_t1 >= min_rr_t1)
    rr_t2_qualified = (opt_t2 >= opt_t1) and (rr_t2 >= min_rr_t2)
    rr_t3_qualified = (opt_t3 >= opt_t2) and (rr_t3 >= min_rr_t3)

    if rr_t2 < min_rr_t2:
        rejection_reasons.append(f"UNFAVORABLE_REWARD_TO_RISK: R:R ratio on T2 ({rr_t2}) is below minimum requirement {min_rr_t2}")

    risk_per_lot = round(risk_per_unit * lot_size, 2)
    exposure_per_lot = round(entry_premium * lot_size, 2)

    # 9. Position Sizing & Capital Allocation (Zero-Invention Rule)
    risk_budget_inr = cfg.get("risk_budget_inr")
    risk_budget_pct = cfg.get("risk_budget_pct")

    if risk_budget_inr is None and risk_budget_pct is not None and available_capital is not None:
        risk_budget_inr = float(available_capital) * float(risk_budget_pct)

    max_permitted_lots = int(cfg.get("max_permitted_lots", 10))

    if risk_budget_inr is None:
        # Zero-invention rule: no approved budget = UNAVAILABLE, no assumed %!
        position_sizing_status = "UNAVAILABLE"
        allocated_lots = None
        total_premium_exposure = None
        max_potential_risk = None
    else:
        budget = float(risk_budget_inr)
        lots_by_risk = int(budget // risk_per_lot) if risk_per_lot > 0 else 0

        if available_capital is not None:
            lots_by_capital = int(float(available_capital) // exposure_per_lot) if exposure_per_lot > 0 else 0
            candidate_lots = min(lots_by_risk, lots_by_capital)
        else:
            candidate_lots = lots_by_risk

        allocated_lots = min(candidate_lots, max_permitted_lots)

        if allocated_lots < 1:
            position_sizing_status = "INSUFFICIENT_CAPITAL"
            allocated_lots = 0
            total_premium_exposure = 0.0
            max_potential_risk = 0.0
            rejection_reasons.append(
                f"INSUFFICIENT_CAPITAL: Risk budget (₹{budget:,.2f}) or capital cannot support 1 full lot "
                f"(risk/lot=₹{risk_per_lot:,.2f}, exposure/lot=₹{exposure_per_lot:,.2f})"
            )
        else:
            position_sizing_status = "ALLOCATED"
            total_premium_exposure = round(allocated_lots * exposure_per_lot, 2)
            max_potential_risk = round(allocated_lots * risk_per_lot, 2)

    # 10. Audit Metadata & Quantitative Model Assumptions
    execution_assumptions = {
        "entry_fill_model": "ASK",
        "entry_price": entry_premium,
        "analytical_midpoint": analytical_midpoint,
        "exit_fill_model": "BID_SCENARIO",
        "half_spread_deduction": half_spread,
        "additional_slippage_pts": slippage_pts,
        "double_counting_prevented": True,
        "tick_rounding_mode": "floor",
        "tick_size": tick_size,
        "execution_notes": (
            "Entry executed at quoted Ask; exit modeled at scenario Bid "
            "(BS theoretical Mid minus half-spread) less additional slippage_pts. "
            "Midpoint is retained for analytical valuation only; not assumed executable."
        ),
    }

    scenario_horizons = {
        "stop_loss_minutes": sl_holding_min,
        "target_1_minutes": t1_holding_min,
        "target_2_minutes": t2_holding_min,
        "target_3_minutes": t3_holding_min,
        "calibration_status": "ASSUMPTION",
        "validation_disclaimer": "Holding-time horizons are uncalibrated quantitative scenario assumptions; not statistically validated on out-of-sample trade data.",
        "remaining_t_years": {
            "entry": round(t0, 6),
            "stop_loss": round(t_sl, 6),
            "target_1": round(t_t1, 6),
            "target_2": round(t_t2, 6),
            "target_3": round(t_t3, 6),
        },
    }

    iv_stress_model = {
        "stop_loss": {
            "base_iv_pct": round(iv_pct, 4),
            "stress_pct": round(sl_iv_stress_pct * 100.0, 2),
            "stressed_iv_pct": round(sigma_sl * 100.0, 4),
            "stress_interpretation": "RELATIVE_PERCENT",
            "parameter_source": cfg.get("iv_stress_source", "CONFIG_UNVALIDATED_ASSUMPTION"),
            "formula": "stressed_iv = base_iv * (1.0 + stress_pct / 100.0)",
        },
        "targets": {
            "base_iv_pct": round(iv_pct, 4),
            "stress_pct": round(target_iv_stress_pct * 100.0, 2),
            "stressed_iv_pct": round(sigma_target * 100.0, 4),
            "stress_interpretation": "RELATIVE_PERCENT",
            "parameter_source": cfg.get("iv_stress_source", "CONFIG_UNVALIDATED_ASSUMPTION"),
            "formula": "stressed_iv = base_iv * (1.0 + stress_pct / 100.0)",
        },
    }

    model_audit = {
        "pricing_engine": "Black-Scholes-Merton (1973) European Option Pricing",
        "inputs_audited": {
            "risk_free_rate": r,
            "risk_free_rate_source": cfg.get("risk_free_rate_source", "RBI 91-Day T-Bill Benchmark (0.065)"),
            "dividend_yield": q,
            "dividend_yield_note": "European cash-settled index options (q=0.0)",
            "iv_source": iv_source,
            "time_to_expiry_years": round(t0, 6),
            "option_type": opt_type,
            "strike": strike,
            "spot_entry": spot_entry,
            "spot_sl": sl_spot,
            "spot_t1": t1_spot,
            "spot_t2": t2_spot,
            "spot_t3": t3_spot,
        },
        "model_disclaimer": (
            "Black-Scholes is a theoretical continuous-time European pricing model assuming geometric "
            "Brownian motion. It does not account for volatility skew shifts, jump diffusion, discrete liquidity gaps, "
            "or wide market spreads, and does not guarantee actual market execution prices or fills."
        ),
    }

    reward_to_risk_summary = {
        "rr_t1": rr_t1,
        "rr_t2": rr_t2,
        "rr_t3": rr_t3,
        "rr_t1_qualified": rr_t1_qualified,
        "rr_t2_qualified": rr_t2_qualified,
        "rr_t3_qualified": rr_t3_qualified,
        "min_required_rr": {
            "t1": min_rr_t1,
            "t2": min_rr_t2,
            "t3": min_rr_t3,
        },
        "composite_qualified": (rr_t1_qualified and rr_t2_qualified and rr_t3_qualified),
    }

    is_qualified = (len(rejection_reasons) == 0)

    return {
        "qualification_status": "QUALIFIED" if is_qualified else "REJECTED",
        "action": action if is_qualified else "NO_TRADE",
        "index": selected_contract.get("index", "UNKNOWN"),
        "option_type": opt_type,
        "contract_symbol": selected_contract.get("contract_symbol"),
        "instrument_token": selected_contract.get("instrument_token"),
        "strike": strike,
        "expiry": selected_contract.get("expiry"),
        "moneyness": selected_contract.get("moneyness"),
        "lot_size": lot_size,
        "tick_size": tick_size,
        "entry_execution_model": "ASK",
        "entry_premium": entry_premium,
        "analytical_midpoint": analytical_midpoint,
        "bid": bid_0,
        "ask": ask_0,
        "spread_pct": selected_contract.get("spread_pct"),
        "delta": selected_contract.get("delta"),
        "gamma": selected_contract.get("gamma"),
        "theta": selected_contract.get("theta"),
        "vega": selected_contract.get("vega"),
        "implied_volatility": iv_pct,
        "iv_source": iv_source,
        "underlying_entry": spot_entry,
        "underlying_stop_loss": sl_spot,
        "underlying_targets": {
            "target_1": t1_spot,
            "target_2": t2_spot,
            "target_3": t3_spot,
        },
        "option_stop_loss": option_sl if is_qualified else None,
        "option_target_1": opt_t1 if is_qualified else None,
        "option_target_2": opt_t2 if is_qualified else None,
        "option_target_3": opt_t3 if is_qualified else None,
        "risk_per_unit": risk_per_unit if is_qualified else None,
        "risk_per_lot": risk_per_lot if is_qualified else None,
        "allocated_lots": allocated_lots,
        "total_premium_exposure": total_premium_exposure,
        "max_potential_risk": max_potential_risk,
        "reward_to_risk": reward_to_risk_summary,
        "position_sizing_status": position_sizing_status,
        "data_status": selected_contract.get("data_status", "LIVE"),
        "execution_assumptions": execution_assumptions,
        "scenario_horizons": scenario_horizons,
        "iv_stress_model": iv_stress_model,
        "model_audit": model_audit,
        "rejection_reasons": rejection_reasons,
        "paper_trading_eligible": is_qualified,
    }
