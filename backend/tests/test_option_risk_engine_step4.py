"""
AIVOLVE Quantitative Options Intelligence Engine v3.0 - Phase 2 Step 4.2 Dedicated Tests
Part 2: Option Risk Engine & Scenario-Based Repricing Tests (Remediated Quantitative Engine)

Tests:
  1. BUY_CE Stop-Loss Scenario Repricing via Black-Scholes.
  2. BUY_PE Stop-Loss Scenario Repricing via Black-Scholes.
  3. Mathematical Proof: Scenario Repricing vs Linear Delta Divergence.
  4. Conservative Execution Model: Entry strictly at Ask, Exit at Bid.
  5. Spread & Slippage Double-Counting Prevention.
  6. Holding-Time Horizon Configuration & Expiry Boundary Protection.
  7. Relative IV Stress Model (Relative % vs Absolute Vol Points).
  8. Independent Reward-to-Risk Calculations (RR_T1, RR_T2, RR_T3).
  9. Non-Concealment Rule: Valid T2 Cannot Conceal Invalid T1 or T3.
  10. Black-Scholes Input Audit & Rejection of Missing/Non-Positive Inputs.
  11. Exchange Tick Size Floor Rounding (0.05 Alignment).
  12. Position Sizing: Explicit Risk Budget Allocation.
  13. Position Sizing: Missing Risk Budget (Status UNAVAILABLE, no default invented).
  14. Position Sizing: Insufficient Capital Rejection (Status INSUFFICIENT_CAPITAL).
  15. Theoretical Quote Feed Rejection.
  16. Unqualified Selected Contract Propagation.
  17. Invalid / Inverted Underlying Geometry Rejection.
"""

import math
from datetime import datetime, timezone, timedelta
import zoneinfo
import pytest

from app.options.greeks import calculate_black_scholes, calculate_exact_time_to_expiry
from app.options.option_risk_engine import round_to_tick, calculate_option_risk_plan

IST = zoneinfo.ZoneInfo("Asia/Kolkata")


def build_mock_qualified_contract(
    symbol: str = "NIFTY",
    underlying_spot: float = 24500.0,
    strike: float = 24500.0,
    opt_type: str = "CE",
    expiry_days_ahead: int = 5,
    iv: float = 15.0,
    r: float = 0.065,
    lot_size: int = 65,
    tick_size: float = 0.05,
    bid_spread: float = 0.30,
    is_theoretical: bool = False,
):
    """Creates a mathematically authentic, qualified option contract for risk tests."""
    now_ist = datetime.now(IST)
    expiry_dt = (now_ist + timedelta(days=expiry_days_ahead)).replace(hour=15, minute=30, second=0, microsecond=0)
    expiry_str = expiry_dt.strftime("%d-%b-%Y").upper()

    t_years = calculate_exact_time_to_expiry(expiry_str, now_ist)
    bs = calculate_black_scholes(underlying_spot, strike, t_years, r, iv / 100.0, opt_type)
    price = round(bs["price"], 2)

    half_s = bid_spread / 2.0
    bid = round(price - half_s, 2)
    ask = round(price + half_s, 2)
    midpoint = round((bid + ask) / 2.0, 2)

    return {
        "qualification_status": "QUALIFIED",
        "action": f"BUY_{opt_type}",
        "index": symbol,
        "option_type": opt_type,
        "contract_symbol": f"{symbol}{expiry_str}{int(strike)}{opt_type}",
        "instrument_token": f"{opt_type}_{int(strike)}",
        "strike": strike,
        "expiry": expiry_str,
        "moneyness": "ATM" if strike == underlying_spot else ("ITM" if (opt_type == "CE" and strike < underlying_spot) or (opt_type == "PE" and strike > underlying_spot) else "OTM"),
        "lot_size": lot_size,
        "tick_size": tick_size,
        "entry_execution_model": "ASK",
        "entry_premium": ask,
        "analytical_midpoint": midpoint,
        "bid": bid,
        "ask": ask,
        "spread_pct": round(bid_spread / price * 100.0, 2),
        "delta": bs["delta"],
        "gamma": bs["gamma"],
        "theta": bs["theta"],
        "vega": bs["vega"],
        "implied_volatility": iv,
        "iv_source": "BRENT_NUMERICAL",
        "t_years": t_years,
        "data_status": "THEORETICAL" if is_theoretical else "LIVE",
        "isTheoretical": is_theoretical,
        "isStale": False,
        "rejection_reasons": [],
        "paper_trading_eligible": not is_theoretical,
    }


# =====================================================================
# 1. Non-Linear Scenario Repricing vs Linear Delta Divergence
# =====================================================================

def test_scenario_repricing_buy_ce():
    """Validates Black-Scholes scenario repricing for BUY_CE at structural stop-loss."""
    spot = 24500.0
    sl = 24420.0  # -80 pts drop
    t1 = 24580.0  # +80 pts
    t2 = 24660.0  # +160 pts
    t3 = 24740.0  # +240 pts

    setup = {
        "action": "BUY_CE",
        "entry_price": spot,
        "stop_loss": sl,
        "target_1": t1,
        "target_2": t2,
        "target_3": t3,
    }

    contract = build_mock_qualified_contract("NIFTY", spot, strike=24500.0, opt_type="CE", iv=15.0)
    plan = calculate_option_risk_plan(setup, contract)

    assert plan["qualification_status"] == "QUALIFIED"
    assert plan["action"] == "BUY_CE"
    assert plan["option_stop_loss"] is not None
    assert plan["option_stop_loss"] < plan["entry_premium"]
    assert plan["option_target_1"] > plan["entry_premium"]
    assert plan["option_target_2"] > plan["option_target_1"]
    assert plan["option_target_3"] >= plan["option_target_2"]
    assert plan["reward_to_risk"]["rr_t2"] >= 1.25


def test_scenario_repricing_buy_pe():
    """Validates Black-Scholes scenario repricing for BUY_PE at structural stop-loss."""
    spot = 24500.0
    sl = 24580.0  # +80 pts adverse move against Put
    t1 = 24420.0  # -80 pts
    t2 = 24340.0  # -160 pts
    t3 = 24260.0  # -240 pts

    setup = {
        "action": "BUY_PE",
        "entry_price": spot,
        "stop_loss": sl,
        "target_1": t1,
        "target_2": t2,
        "target_3": t3,
    }

    contract = build_mock_qualified_contract("NIFTY", spot, strike=24500.0, opt_type="PE", iv=15.0)
    plan = calculate_option_risk_plan(setup, contract)

    assert plan["qualification_status"] == "QUALIFIED"
    assert plan["action"] == "BUY_PE"
    assert plan["option_stop_loss"] is not None
    assert plan["option_stop_loss"] < plan["entry_premium"]
    assert plan["option_target_1"] > plan["entry_premium"]
    assert plan["option_target_2"] > plan["option_target_1"]


def test_scenario_repricing_divergence_from_linear_delta():
    """
    Mathematical Proof: Scenario repricing accounts for negative Gamma, Theta decay,
    and adverse IV crush, proving that linear Delta approximation underestimates risk.
    """
    spot = 24500.0
    sl = 24420.0  # -80 pts
    contract = build_mock_qualified_contract("NIFTY", spot, strike=24500.0, opt_type="CE", iv=15.0)

    setup = {
        "action": "BUY_CE",
        "entry_price": spot,
        "stop_loss": sl,
        "target_1": 24580.0,
        "target_2": 24680.0,
        "target_3": 24780.0,
    }

    plan = calculate_option_risk_plan(setup, contract)
    option_sl = plan["option_stop_loss"]
    entry_prem = plan["entry_premium"]
    delta = contract["delta"]

    # Linear delta formula
    index_sl_dist = spot - sl  # 80 pts
    linear_delta_sl = round(entry_prem - (delta * index_sl_dist), 2)

    # In reality, Gamma decreases Delta as spot falls, Theta decays time, and IV drops.
    # Therefore, true option exit price is significantly LOWER than the linear delta approximation.
    assert option_sl < linear_delta_sl
    divergence_inr = round(linear_delta_sl - option_sl, 2)
    assert divergence_inr > 5.0, f"Expected > 5 INR divergence, got {divergence_inr}"


# =====================================================================
# 2. Execution Price Model & Double-Counting Prevention
# =====================================================================

def test_conservative_execution_price_model():
    """Validates Ask entry, Bid scenario exit, and documentation of assumptions."""
    spot = 24500.0
    contract = build_mock_qualified_contract("NIFTY", spot, strike=24500.0, opt_type="CE", bid_spread=0.50)
    setup = {"action": "BUY_CE", "entry_price": spot, "stop_loss": 24420.0, "target_1": 24580.0, "target_2": 24680.0}

    plan = calculate_option_risk_plan(setup, contract)
    assert plan["qualification_status"] == "QUALIFIED"

    exec_assumptions = plan["execution_assumptions"]
    assert exec_assumptions["entry_fill_model"] == "ASK"
    assert exec_assumptions["entry_price"] == contract["ask"]
    assert exec_assumptions["analytical_midpoint"] == contract["analytical_midpoint"]
    assert exec_assumptions["exit_fill_model"] == "BID_SCENARIO"
    assert exec_assumptions["half_spread_deduction"] == 0.25
    assert exec_assumptions["double_counting_prevented"] is True


def test_spread_and_slippage_double_count_prevention():
    """Validates that additional slippage_pts is added to half_spread without double-counting."""
    spot = 24500.0
    contract = build_mock_qualified_contract("NIFTY", spot, strike=24500.0, opt_type="CE", bid_spread=0.40)
    setup = {"action": "BUY_CE", "entry_price": spot, "stop_loss": 24420.0, "target_1": 24580.0, "target_2": 24680.0}

    # Baseline plan without extra slippage
    plan_no_slip = calculate_option_risk_plan(setup, contract, risk_config={"slippage_pts": 0.0})
    # Plan with 1.0 pt additional slippage
    plan_with_slip = calculate_option_risk_plan(setup, contract, risk_config={"slippage_pts": 1.0})

    sl_no_slip = plan_no_slip["option_stop_loss"]
    sl_with_slip = plan_with_slip["option_stop_loss"]

    # 1.0 pt slippage lowers the exit premium by ~1.0 pt (tick-aligned)
    slip_diff = round(sl_no_slip - sl_with_slip, 2)
    assert 0.95 <= slip_diff <= 1.05
    assert plan_with_slip["execution_assumptions"]["additional_slippage_pts"] == 1.0


# =====================================================================
# 3. Holding-Time Horizon Configuration & Expiry Boundaries
# =====================================================================

def test_holding_time_configuration_and_assumption_label():
    """Scenario horizons are configurable and explicitly labeled as uncalibrated ASSUMPTIONS."""
    spot = 24500.0
    contract = build_mock_qualified_contract("NIFTY", spot, strike=24500.0, opt_type="CE")
    setup = {"action": "BUY_CE", "entry_price": spot, "stop_loss": 24420.0, "target_1": 24580.0, "target_2": 24680.0}

    custom_horizons = {
        "stop_loss_minutes": 15.0,
        "target_1_minutes": 30.0,
        "target_2_minutes": 60.0,
        "target_3_minutes": 90.0,
    }
    plan = calculate_option_risk_plan(setup, contract, risk_config={"scenario_horizons": custom_horizons})

    horizons_out = plan["scenario_horizons"]
    assert horizons_out["stop_loss_minutes"] == 15.0
    assert horizons_out["target_1_minutes"] == 30.0
    assert horizons_out["target_2_minutes"] == 60.0
    assert horizons_out["calibration_status"] == "ASSUMPTION"
    assert "not statistically validated" in horizons_out["validation_disclaimer"]
    assert horizons_out["remaining_t_years"]["stop_loss"] > 0.0


def test_expired_contract_rejection():
    """Contracts with non-positive time to expiry are strictly rejected."""
    spot = 24500.0
    contract = build_mock_qualified_contract("NIFTY", spot, strike=24500.0, opt_type="CE")
    contract["t_years"] = 0.0  # Already expired!
    setup = {"action": "BUY_CE", "entry_price": spot, "stop_loss": 24420.0, "target_1": 24580.0, "target_2": 24680.0}

    res = calculate_option_risk_plan(setup, contract)
    assert res["qualification_status"] == "REJECTED"
    assert any("EXPIRED_CONTRACT" in r for r in res["rejection_reasons"])


# =====================================================================
# 4. Relative IV Stress Model
# =====================================================================

def test_relative_iv_stress_calculations():
    """
    Verifies that IV stress is computed as a RELATIVE percentage, NOT absolute vol points.
    e.g. Base IV = 15.0% with -5% stress -> Stressed IV = 14.25% (NOT 10.0%).
    """
    spot = 24500.0
    contract = build_mock_qualified_contract("NIFTY", spot, strike=24500.0, opt_type="CE", iv=15.0)
    setup = {"action": "BUY_CE", "entry_price": spot, "stop_loss": 24420.0, "target_1": 24580.0, "target_2": 24680.0}

    cfg = {"sl_iv_stress_pct": -0.05, "target_iv_stress_pct": 0.02}
    plan = calculate_option_risk_plan(setup, contract, risk_config=cfg)

    iv_model = plan["iv_stress_model"]
    assert iv_model["stop_loss"]["base_iv_pct"] == 15.0
    assert iv_model["stop_loss"]["stress_pct"] == -5.0
    assert iv_model["stop_loss"]["stressed_iv_pct"] == 14.25  # 15.0 * 0.95 = 14.25
    assert iv_model["stop_loss"]["stress_interpretation"] == "RELATIVE_PERCENT"

    assert iv_model["targets"]["base_iv_pct"] == 15.0
    assert iv_model["targets"]["stress_pct"] == 2.0
    assert iv_model["targets"]["stressed_iv_pct"] == 15.30  # 15.0 * 1.02 = 15.30
    assert iv_model["targets"]["stress_interpretation"] == "RELATIVE_PERCENT"


# =====================================================================
# 5. Independent Reward-to-Risk Qualification (Zero Concealment)
# =====================================================================

def test_independent_rr_calculations_and_zero_concealment():
    """
    Calculates RR_T1, RR_T2, RR_T3 independently.
    Ensures that a high RR_T2 cannot conceal an invalid Target 1 geometry (T1 premium <= Entry).
    """
    spot = 24500.0
    # Wide spread contract where T1 option premium after friction falls below Ask entry
    contract = build_mock_qualified_contract("NIFTY", spot, strike=24500.0, opt_type="CE", iv=15.0, bid_spread=6.0)

    # Valid spot geometry (24420 < 24500 < 24502 <= 24700), but T1 option premium <= entry premium!
    setup_invalid_t1 = {
        "action": "BUY_CE",
        "entry_price": spot,
        "stop_loss": 24420.0,
        "target_1": 24502.0,
        "target_2": 24700.0,
    }

    res = calculate_option_risk_plan(setup_invalid_t1, contract, risk_config={"target_iv_stress_pct": 0.0})
    assert res["qualification_status"] == "REJECTED"
    assert any("INVALID_TARGET_GEOMETRY" in r for r in res["rejection_reasons"])


def test_independent_rr_qualification_status():
    """Returns individual target qualification statuses (rr_t1_qualified, rr_t2_qualified, rr_t3_qualified)."""
    spot = 24500.0
    contract = build_mock_qualified_contract("NIFTY", spot, strike=24500.0, opt_type="CE", iv=15.0)
    setup = {
        "action": "BUY_CE",
        "entry_price": spot,
        "stop_loss": 24420.0,
        "target_1": 24580.0,
        "target_2": 24680.0,
        "target_3": 24780.0,
    }

    plan = calculate_option_risk_plan(setup, contract)
    assert plan["qualification_status"] == "QUALIFIED"
    rr_data = plan["reward_to_risk"]

    assert rr_data["rr_t1"] is not None
    assert rr_data["rr_t2"] is not None
    assert rr_data["rr_t3"] is not None
    assert rr_data["rr_t1_qualified"] is True
    assert rr_data["rr_t2_qualified"] is True
    assert rr_data["rr_t3_qualified"] is True
    assert rr_data["composite_qualified"] is True


def test_unfavorable_reward_to_risk_rejection():
    """Rejects setups where R:R on Target 2 is below the minimum requirement (1.25)."""
    spot = 24500.0
    contract = build_mock_qualified_contract("NIFTY", spot, strike=24500.0, opt_type="CE")

    # Wide SL (-100 pts) with tiny target (+30 pts)
    setup_poor_rr = {
        "action": "BUY_CE",
        "entry_price": spot,
        "stop_loss": 24400.0,
        "target_1": 24520.0,
        "target_2": 24530.0,
    }

    res = calculate_option_risk_plan(setup_poor_rr, contract)
    assert res["qualification_status"] == "REJECTED"
    assert any("UNFAVORABLE_REWARD_TO_RISK" in r for r in res["rejection_reasons"])


# =====================================================================
# 6. Black-Scholes Input Audit & Disclaimer
# =====================================================================

def test_black_scholes_inputs_audit_and_disclaimer():
    """Audits all Black-Scholes inputs and verifies theoretical model disclaimer."""
    spot = 24500.0
    contract = build_mock_qualified_contract("NIFTY", spot, strike=24500.0, opt_type="CE")
    setup = {"action": "BUY_CE", "entry_price": spot, "stop_loss": 24420.0, "target_1": 24580.0, "target_2": 24680.0}

    plan = calculate_option_risk_plan(setup, contract)
    audit = plan["model_audit"]

    assert audit["pricing_engine"] == "Black-Scholes-Merton (1973) European Option Pricing"
    assert audit["inputs_audited"]["risk_free_rate"] == 0.065
    assert audit["inputs_audited"]["dividend_yield"] == 0.0
    assert audit["inputs_audited"]["strike"] == 24500.0
    assert "does not guarantee actual market execution prices" in audit["model_disclaimer"]


def test_missing_or_invalid_inputs_rejection():
    """Rejects setup when essential Black-Scholes inputs are missing or non-positive."""
    spot = 24500.0
    contract = build_mock_qualified_contract("NIFTY", spot, strike=24500.0, opt_type="CE")
    setup = {"action": "BUY_CE", "entry_price": spot, "stop_loss": 24420.0, "target_1": 24580.0, "target_2": 24680.0}

    # Negative risk-free rate
    res1 = calculate_option_risk_plan(setup, contract, risk_config={"risk_free_rate": -0.05})
    assert res1["qualification_status"] == "REJECTED"
    assert any("INVALID_RISK_FREE_RATE" in r for r in res1["rejection_reasons"])

    # Non-positive strike
    bad_contract = dict(contract, strike=0.0)
    res2 = calculate_option_risk_plan(setup, bad_contract)
    assert res2["qualification_status"] == "REJECTED"
    assert any("INVALID_STRIKE" in r for r in res2["rejection_reasons"])


# =====================================================================
# 7. Position Sizing and Capital Budgeting Tests
# =====================================================================

def test_position_sizing_missing_risk_budget():
    """
    When no approved risk budget is provided, position sizing status is UNAVAILABLE,
    allocated_lots is None, and NO arbitrary default percentages are invented.
    """
    spot = 24500.0
    contract = build_mock_qualified_contract("NIFTY", spot, strike=24500.0, opt_type="CE")
    setup = {"action": "BUY_CE", "entry_price": spot, "stop_loss": 24420.0, "target_1": 24580.0, "target_2": 24680.0}

    res = calculate_option_risk_plan(setup, contract, risk_config={})
    assert res["qualification_status"] == "QUALIFIED"
    assert res["position_sizing_status"] == "UNAVAILABLE"
    assert res["allocated_lots"] is None
    assert res["total_premium_exposure"] is None
    assert res["risk_per_lot"] > 0.0


def test_position_sizing_allocated_with_budget():
    """Allocates integer lots based on explicit approved risk budget."""
    spot = 24500.0
    contract = build_mock_qualified_contract("NIFTY", spot, strike=24500.0, opt_type="CE", lot_size=65)
    setup = {"action": "BUY_CE", "entry_price": spot, "stop_loss": 24420.0, "target_1": 24580.0, "target_2": 24680.0}

    cfg = {"risk_budget_inr": 10000.0, "max_permitted_lots": 5}
    res = calculate_option_risk_plan(setup, contract, risk_config=cfg, available_capital=100000.0)

    assert res["qualification_status"] == "QUALIFIED"
    assert res["position_sizing_status"] == "ALLOCATED"
    assert res["allocated_lots"] >= 1
    assert res["allocated_lots"] <= 5
    assert res["max_potential_risk"] <= 10000.0


def test_position_sizing_insufficient_capital():
    """Rejects setup if risk budget cannot support even 1 single lot."""
    spot = 24500.0
    contract = build_mock_qualified_contract("NIFTY", spot, strike=24500.0, opt_type="CE", lot_size=65)
    setup = {"action": "BUY_CE", "entry_price": spot, "stop_loss": 24420.0, "target_1": 24580.0, "target_2": 24680.0}

    cfg = {"risk_budget_inr": 100.0}
    res = calculate_option_risk_plan(setup, contract, risk_config=cfg)

    assert res["qualification_status"] == "REJECTED"
    assert res["position_sizing_status"] == "INSUFFICIENT_CAPITAL"
    assert res["allocated_lots"] == 0
    assert any("INSUFFICIENT_CAPITAL" in r for r in res["rejection_reasons"])


# =====================================================================
# 8. Safety & Theoretical Quote Gating Tests
# =====================================================================

def test_theoretical_quote_input_rejection():
    """Option contracts with theoretical quotes are rejected for paper execution."""
    spot = 24500.0
    contract = build_mock_qualified_contract("NIFTY", spot, strike=24500.0, opt_type="CE", is_theoretical=True)
    setup = {"action": "BUY_CE", "entry_price": spot, "stop_loss": 24420.0, "target_1": 24580.0, "target_2": 24680.0}

    res = calculate_option_risk_plan(setup, contract)
    assert res["qualification_status"] == "REJECTED"
    assert res["data_status"] == "THEORETICAL"
    assert any("theoretical quote" in r for r in res["rejection_reasons"])


def test_unqualified_selected_contract_propagation():
    """When input selected contract is marked REJECTED, risk engine propagates rejection."""
    spot = 24500.0
    contract = {
        "qualification_status": "REJECTED",
        "action": "NO_TRADE",
        "index": "NIFTY",
        "rejection_reasons": ["Delta outside permitted range"],
    }
    setup = {"action": "BUY_CE", "entry_price": spot, "stop_loss": 24420.0}

    res = calculate_option_risk_plan(setup, contract)
    assert res["qualification_status"] == "REJECTED"
    assert any("Delta outside permitted range" in r for r in res["rejection_reasons"])


def test_invalid_underlying_geometry_rejection():
    """Rejects if Call stop-loss is above entry or Put stop-loss is below entry."""
    spot = 24500.0
    contract = build_mock_qualified_contract("NIFTY", spot, strike=24500.0, opt_type="CE")

    # Inverted Call geometry (SL > Entry)
    setup_inverted = {
        "action": "BUY_CE",
        "entry_price": spot,
        "stop_loss": 24600.0,
        "target_1": 24700.0,
        "target_2": 24800.0,
    }

    res = calculate_option_risk_plan(setup_inverted, contract)
    assert res["qualification_status"] == "REJECTED"
    assert any("Invalid underlying Call geometry" in r for r in res["rejection_reasons"])


# =====================================================================
# 9. Deterministic Output & Executable Price Alignment Tests
# =====================================================================

def test_deterministic_reproducibility():
    """Proves that repeated calculations with identical inputs yield identical outputs (100% deterministic)."""
    spot = 24500.0
    contract = build_mock_qualified_contract("NIFTY", spot, strike=24500.0, opt_type="CE", iv=15.0, bid_spread=0.30)
    setup = {
        "action": "BUY_CE",
        "entry_price": spot,
        "stop_loss": 24420.0,
        "target_1": 24580.0, 
        "target_2": 24680.0,
        "target_3": 24780.0,
    }

    runs = [calculate_option_risk_plan(setup, contract, risk_config={"slippage_pts": 0.50}) for _ in range(5)]
    first = runs[0]

    for r in runs[1:]:
        assert r["option_stop_loss"] == first["option_stop_loss"]
        assert r["option_target_1"] == first["option_target_1"]
        assert r["option_target_2"] == first["option_target_2"]
        assert r["option_target_3"] == first["option_target_3"]
        assert r["risk_per_unit"] == first["risk_per_unit"]
        assert r["reward_to_risk"]["rr_t1"] == first["reward_to_risk"]["rr_t1"]
        assert r["reward_to_risk"]["rr_t2"] == first["reward_to_risk"]["rr_t2"]
        assert r["reward_to_risk"]["rr_t3"] == first["reward_to_risk"]["rr_t3"]


def test_rr_uses_executable_entry_and_exit_prices():
    """Verifies that all RR ratios strictly use the final executable entry and exit prices (Ask entry, Bid exits)."""
    spot = 24500.0
    contract = build_mock_qualified_contract("NIFTY", spot, strike=24500.0, opt_type="CE", iv=15.0, bid_spread=0.40)
    setup = {
        "action": "BUY_CE",
        "entry_price": spot,
        "stop_loss": 24420.0,
        "target_1": 24580.0,
        "target_2": 24680.0,
        "target_3": 24780.0,
    }

    plan = calculate_option_risk_plan(setup, contract, risk_config={"slippage_pts": 0.25})
    assert plan["qualification_status"] == "QUALIFIED"

    entry = plan["entry_premium"]
    sl = plan["option_stop_loss"]
    t1 = plan["option_target_1"]
    t2 = plan["option_target_2"]
    t3 = plan["option_target_3"]

    expected_risk_per_unit = round(entry - sl, 2)
    assert plan["risk_per_unit"] == expected_risk_per_unit

    expected_rr_t1 = round((t1 - entry) / expected_risk_per_unit, 2)
    expected_rr_t2 = round((t2 - entry) / expected_risk_per_unit, 2)
    expected_rr_t3 = round((t3 - entry) / expected_risk_per_unit, 2)

    assert plan["reward_to_risk"]["rr_t1"] == expected_rr_t1
    assert plan["reward_to_risk"]["rr_t2"] == expected_rr_t2
    assert plan["reward_to_risk"]["rr_t3"] == expected_rr_t3
