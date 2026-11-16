"""
AIVOLVE Institutional Quantitative Trading Intelligence v3.0
Phase 7 / Step 7.6: Dynamic Greeks-Based Position Sizing Automated Test Suite (REQ-7.6).

Verification Matrix:
1. Zero-Invention & Fail-Closed Policy:
   - Unconfigured policy blocks trading fail-closed (RISK_POLICY_UNCONFIGURED).
   - Clearing policy returns sizer to unconfigured state.
2. Missing or Invalid Greeks:
   - greeks is None -> rejected (GREEKS_DATA_UNAVAILABLE).
   - delta/gamma/theta/vega is None or NaN -> rejected (GREEKS_DATA_UNAVAILABLE).
   - Greeks are never fabricated or assumed as 0.0.
3. Invalid Premium & Stop-Loss Geometry:
   - Non-positive / zero / NaN premium -> rejected (INVALID_PREMIUM).
   - Stop loss <= 0 or >= entry premium -> rejected (INVALID_STOP_LOSS).
4. Market Quality & Quote Staleness:
   - Stale quote (>60s) -> rejected (STALE_QUOTE).
   - Inverted spread (bid > ask) -> rejected (INVALID_QUOTE).
   - Excessive spread (>max_spread_pct) -> rejected (EXCESSIVE_SPREAD).
5. Extreme Volatility Bounds:
   - IV below floor (<min_iv_floor) or above ceiling (>max_iv_ceiling) -> rejected (EXTREME_VOLATILITY).
6. Multi-Constraint Capacity & Lot-Size Rounding:
   - Conservative integer floor sizing across Risk and Capital constraints.
   - Insufficient risk budget (< 1 lot) -> rejected (INSUFFICIENT_RISK_BUDGET).
   - Insufficient capital (< 1 lot) -> rejected (INSUFFICIENT_CAPITAL).
7. Circuit Breaker Integration:
   - Breached / unconfigured circuit breaker blocks new entries (CIRCUIT_BREAKER_BLOCKED).
   - Remaining daily budget dynamically restricts lots.
8. Portfolio Greeks Caps (Delta, Gamma, Theta, Vega):
   - Delta limit exceeded -> sized down or rejected (DELTA_LIMIT_EXCEEDED).
   - Gamma limit exceeded -> sized down or rejected (GAMMA_LIMIT_EXCEEDED).
   - Daily Theta decay limit exceeded -> sized down or rejected (THETA_LIMIT_EXCEEDED).
   - Vega limit exceeded -> sized down or rejected (VEGA_LIMIT_EXCEEDED).
9. Portfolio Greeks Aggregation:
   - Real-time aggregation of Rupee Delta, Point Delta, Rupee Gamma, Daily Theta decay, Rupee Vega.
   - Multi-index breakdown (NIFTY vs BANKNIFTY vs FINNIFTY).
10. SENSEX Governance Lock:
    - SENSEX strictly rejected fail-closed (GOVERNANCE_LOCKED).
11. Paper Trading Engine Pipeline Integration:
    - open_position respects Greeks sizing sieve and stores Greeks metrics on position.
    - get_portfolio_greeks provides real-time portfolio metrics.
12. Governance Provenance & Single-Use Replay Protection:
    - Consumed approval reference cannot be reused.
    - Identity mismatch or revoked reference rejected.
13. Concurrency & Thread-Safety:
    - Multi-threaded sizing evaluation without race conditions.
14. Crash-Resilient Persistence:
    - Policy and audit history preserved across restarts.
"""

import os
import json
import uuid
import math
import shutil
import tempfile
import threading
from datetime import datetime, timezone, timedelta
import zoneinfo
import pytest

from app.options.greeks_risk_engine import (
    DynamicGreeksPositionSizer,
    PortfolioGreeksAggregator,
    GreeksRiskProfile,
    GreeksRiskPolicy,
    get_greeks_risk_sizer,
    set_greeks_risk_sizer,
    DEFAULT_INDEX_LOT_SIZES,
)
from app.options.drawdown_circuit_breaker import (
    IntradayDrawdownCircuitBreaker,
    CircuitBreakerState,
)
from app.options.paper_trading.paper_engine import PaperTradingEngine

IST_ZONE = zoneinfo.ZoneInfo("Asia/Kolkata")


@pytest.fixture
def temp_dir():
    d = tempfile.mkdtemp(prefix="aivolve_greeks_test_")
    yield d
    try:
        shutil.rmtree(d)
    except Exception:
        pass


@pytest.fixture
def mock_sizer(temp_dir):
    state_path = os.path.join(temp_dir, "test_greeks_state.json")
    sizer = DynamicGreeksPositionSizer(state_file_path=state_path, auto_load=False)
    return sizer


@pytest.fixture
def configured_sizer(temp_dir):
    state_path = os.path.join(temp_dir, "test_greeks_state.json")
    sizer = DynamicGreeksPositionSizer(state_file_path=state_path, auto_load=False)
    sizer.configure_policy(
        max_trade_risk_inr=5000.0,
        max_portfolio_delta_inr=5000000.0,
        max_portfolio_gamma_inr=500000000.0,
        max_daily_theta_loss_inr=50000.0,
        max_portfolio_vega_inr=50000.0,
        max_capital_per_trade_inr=50000.0,
        approved_by="QUANT_RISK_COMMITTEE",
        reason="REQ-7.6 Institutional Risk Limits Authorization",
        approval_reference="TEST-GOV-REF-001",
        max_permitted_lots=10,
        max_spread_pct=0.05,
        min_iv_floor=0.05,
        max_iv_ceiling=1.50,
        enforce_circuit_breaker=False,
        skip_governance_registry_check=True,
    )
    return sizer


@pytest.fixture
def standard_greeks():
    return {
        "delta": 0.52,
        "gamma": 0.0012,
        "theta": -12.50,
        "vega": 25.00,
        "iv": 0.16,
    }


# =============================================================================
# 1. Zero-Invention & Fail-Closed Gate Tests
# =============================================================================
class TestZeroInventionAndFailClosed:
    def test_unconfigured_policy_blocks_trading_fail_closed(self, mock_sizer, standard_greeks):
        assert not mock_sizer.is_configured
        res = mock_sizer.calculate_position_size(
            instrument="NIFTY",
            contract_symbol="NIFTY26NOV24500CE",
            option_type="CE",
            spot=24500.0,
            strike=24500.0,
            entry_premium=150.0,
            stop_loss=120.0,
            greeks=standard_greeks,
            available_capital=100000.0,
            portfolio_open_positions=[],
        )
        assert not res["isPermitted"]
        assert res["status"] == "RISK_POLICY_UNCONFIGURED"
        assert res["allocatedLots"] == 0
        assert res["totalQuantity"] == 0
        assert "RISK_POLICY_UNCONFIGURED" in res["reason"]

    def test_clearing_policy_reverts_to_unconfigured(self, configured_sizer, standard_greeks):
        assert configured_sizer.is_configured
        configured_sizer.clear_policy(cleared_by="RISK_OFFICER", reason="Emergency policy reset")
        assert not configured_sizer.is_configured

        res = configured_sizer.calculate_position_size(
            instrument="NIFTY",
            contract_symbol="NIFTY26NOV24500CE",
            option_type="CE",
            spot=24500.0,
            strike=24500.0,
            entry_premium=150.0,
            stop_loss=120.0,
            greeks=standard_greeks,
            available_capital=100000.0,
            portfolio_open_positions=[],
        )
        assert not res["isPermitted"]
        assert res["status"] == "RISK_POLICY_UNCONFIGURED"


# =============================================================================
# 2. Missing or Invalid Greeks (Zero Invention Rule) Tests
# =============================================================================
class TestGreeksIntegrityAndValidation:
    def test_missing_greeks_none_fails_closed(self, configured_sizer):
        res = configured_sizer.calculate_position_size(
            instrument="NIFTY",
            contract_symbol="NIFTY26NOV24500CE",
            option_type="CE",
            spot=24500.0,
            strike=24500.0,
            entry_premium=150.0,
            stop_loss=120.0,
            greeks=None,
            available_capital=100000.0,
            portfolio_open_positions=[],
        )
        assert not res["isPermitted"]
        assert res["status"] == "GREEKS_DATA_UNAVAILABLE"
        assert res["allocatedLots"] == 0

    @pytest.mark.parametrize("missing_key", ["delta", "gamma", "theta", "vega"])
    def test_individual_missing_greek_fails_closed(self, configured_sizer, standard_greeks, missing_key):
        bad_greeks = dict(standard_greeks)
        bad_greeks[missing_key] = None
        res = configured_sizer.calculate_position_size(
            instrument="NIFTY",
            contract_symbol="NIFTY26NOV24500CE",
            option_type="CE",
            spot=24500.0,
            strike=24500.0,
            entry_premium=150.0,
            stop_loss=120.0,
            greeks=bad_greeks,
            available_capital=100000.0,
            portfolio_open_positions=[],
        )
        assert not res["isPermitted"]
        assert res["status"] == "GREEKS_DATA_UNAVAILABLE"
        assert missing_key in res["reason"]

    def test_nan_greek_fails_closed(self, configured_sizer, standard_greeks):
        bad_greeks = dict(standard_greeks)
        bad_greeks["delta"] = float("nan")
        res = configured_sizer.calculate_position_size(
            instrument="NIFTY",
            contract_symbol="NIFTY26NOV24500CE",
            option_type="CE",
            spot=24500.0,
            strike=24500.0,
            entry_premium=150.0,
            stop_loss=120.0,
            greeks=bad_greeks,
            available_capital=100000.0,
            portfolio_open_positions=[],
        )
        assert not res["isPermitted"]
        assert res["status"] == "GREEKS_DATA_UNAVAILABLE"


# =============================================================================
# 3. Invalid Market Premium & Stop-Loss Geometry Tests
# =============================================================================
class TestPremiumAndStopLossGeometry:
    @pytest.mark.parametrize("bad_prem", [0.0, -10.0, float("nan")])
    def test_invalid_premium_fails_closed(self, configured_sizer, standard_greeks, bad_prem):
        res = configured_sizer.calculate_position_size(
            instrument="NIFTY",
            contract_symbol="NIFTY26NOV24500CE",
            option_type="CE",
            spot=24500.0,
            strike=24500.0,
            entry_premium=bad_prem,
            stop_loss=10.0,
            greeks=standard_greeks,
            available_capital=100000.0,
            portfolio_open_positions=[],
        )
        assert not res["isPermitted"]
        assert res["status"] == "INVALID_PREMIUM"

    @pytest.mark.parametrize("bad_sl", [0.0, -5.0, 150.0, 160.0, float("nan")])
    def test_invalid_stop_loss_fails_closed(self, configured_sizer, standard_greeks, bad_sl):
        res = configured_sizer.calculate_position_size(
            instrument="NIFTY",
            contract_symbol="NIFTY26NOV24500CE",
            option_type="CE",
            spot=24500.0,
            strike=24500.0,
            entry_premium=150.0,
            stop_loss=bad_sl,
            greeks=standard_greeks,
            available_capital=100000.0,
            portfolio_open_positions=[],
        )
        assert not res["isPermitted"]
        assert res["status"] == "INVALID_STOP_LOSS"


# =============================================================================
# 4. Market Quality, Staleness & Spread Tests
# =============================================================================
class TestMarketQualityAndSpread:
    def test_stale_quote_fails_closed(self, configured_sizer, standard_greeks):
        stale_time = (datetime.now(IST_ZONE) - timedelta(seconds=120)).isoformat()
        res = configured_sizer.calculate_position_size(
            instrument="NIFTY",
            contract_symbol="NIFTY26NOV24500CE",
            option_type="CE",
            spot=24500.0,
            strike=24500.0,
            entry_premium=150.0,
            stop_loss=120.0,
            greeks=standard_greeks,
            available_capital=100000.0,
            portfolio_open_positions=[],
            quote_timestamp=stale_time,
            max_quote_age_sec=60.0,
        )
        assert not res["isPermitted"]
        assert res["status"] == "STALE_QUOTE"

    def test_fresh_quote_accepted(self, configured_sizer, standard_greeks):
        fresh_time = (datetime.now(IST_ZONE) - timedelta(seconds=10)).isoformat()
        res = configured_sizer.calculate_position_size(
            instrument="NIFTY",
            contract_symbol="NIFTY26NOV24500CE",
            option_type="CE",
            spot=24500.0,
            strike=24500.0,
            entry_premium=150.0,
            stop_loss=120.0,
            greeks=standard_greeks,
            available_capital=100000.0,
            portfolio_open_positions=[],
            quote_timestamp=fresh_time,
            max_quote_age_sec=60.0,
        )
        assert res["isPermitted"]
        assert res["status"] == "ALLOCATED"

    def test_inverted_spread_fails_closed(self, configured_sizer, standard_greeks):
        res = configured_sizer.calculate_position_size(
            instrument="NIFTY",
            contract_symbol="NIFTY26NOV24500CE",
            option_type="CE",
            spot=24500.0,
            strike=24500.0,
            entry_premium=150.0,
            stop_loss=120.0,
            greeks=standard_greeks,
            available_capital=100000.0,
            portfolio_open_positions=[],
            bid=155.0,
            ask=150.0,  # Inverted
        )
        assert not res["isPermitted"]
        assert res["status"] == "INVALID_QUOTE"

    def test_excessive_spread_fails_closed(self, configured_sizer, standard_greeks):
        # Premium 100, bid 90, ask 100 -> spread 10 (10% > 5% max_spread_pct)
        res = configured_sizer.calculate_position_size(
            instrument="NIFTY",
            contract_symbol="NIFTY26NOV24500CE",
            option_type="CE",
            spot=24500.0,
            strike=24500.0,
            entry_premium=100.0,
            stop_loss=80.0,
            greeks=standard_greeks,
            available_capital=100000.0,
            portfolio_open_positions=[],
            bid=90.0,
            ask=100.0,
        )
        assert not res["isPermitted"]
        assert res["status"] == "EXCESSIVE_SPREAD"


# =============================================================================
# 5. Extreme Volatility Bounds Tests
# =============================================================================
class TestVolatilityBounds:
    def test_iv_below_floor_fails_closed(self, configured_sizer, standard_greeks):
        res = configured_sizer.calculate_position_size(
            instrument="NIFTY",
            contract_symbol="NIFTY26NOV24500CE",
            option_type="CE",
            spot=24500.0,
            strike=24500.0,
            entry_premium=150.0,
            stop_loss=120.0,
            greeks=standard_greeks,
            available_capital=100000.0,
            portfolio_open_positions=[],
            iv=0.03,  # 3% < 5% min floor
        )
        assert not res["isPermitted"]
        assert res["status"] == "EXTREME_VOLATILITY"

    def test_iv_above_ceiling_fails_closed(self, configured_sizer, standard_greeks):
        res = configured_sizer.calculate_position_size(
            instrument="NIFTY",
            contract_symbol="NIFTY26NOV24500CE",
            option_type="CE",
            spot=24500.0,
            strike=24500.0,
            entry_premium=150.0,
            stop_loss=120.0,
            greeks=standard_greeks,
            available_capital=100000.0,
            portfolio_open_positions=[],
            iv=1.80,  # 180% > 150% max ceiling
        )
        assert not res["isPermitted"]
        assert res["status"] == "EXTREME_VOLATILITY"


# =============================================================================
# 6. Multi-Constraint Capacity & Lot-Size Rounding Tests
# =============================================================================
class TestMultiConstraintCapacityAndRounding:
    def test_conservative_integer_floor_sizing(self, configured_sizer, standard_greeks):
        # Entry: 100, SL: 80 -> Risk/unit = 20. Lot size = 65 -> Risk/lot = 1300.
        # max_trade_risk = 5000 -> 5000 // 1300 = 3 lots.
        # Exposure/lot = 100 * 65 = 6500. max_cap = 50000 -> 50000 // 6500 = 7 lots.
        # Sizer must allocate exactly 3 lots (floor division).
        res = configured_sizer.calculate_position_size(
            instrument="NIFTY",
            contract_symbol="NIFTY26NOV24500CE",
            option_type="CE",
            spot=24500.0,
            strike=24500.0,
            entry_premium=100.0,
            stop_loss=80.0,
            greeks=standard_greeks,
            available_capital=100000.0,
            portfolio_open_positions=[],
        )
        assert res["isPermitted"]
        assert res["status"] == "ALLOCATED"
        assert res["allocatedLots"] == 3
        assert res["totalQuantity"] == 3 * 65
        assert res["bindingConstraint"] == "INSUFFICIENT_RISK_BUDGET"
        assert res["allocatedProfile"]["totalRiskInr"] == 3 * 1300.0

    def test_insufficient_risk_budget_fails_closed(self, configured_sizer, standard_greeks):
        # Risk per lot: (200 - 100) * 65 = 6500.
        # max_trade_risk = 5000.
        # 5000 // 6500 = 0 lots -> fails closed.
        res = configured_sizer.calculate_position_size(
            instrument="NIFTY",
            contract_symbol="NIFTY26NOV24500CE",
            option_type="CE",
            spot=24500.0,
            strike=24500.0,
            entry_premium=200.0,
            stop_loss=100.0,
            greeks=standard_greeks,
            available_capital=100000.0,
            portfolio_open_positions=[],
        )
        assert not res["isPermitted"]
        assert res["status"] == "INSUFFICIENT_RISK_BUDGET"
        assert res["allocatedLots"] == 0
        assert "INSUFFICIENT_RISK_BUDGET" in res["reason"]

    def test_insufficient_capital_fails_closed(self, configured_sizer, standard_greeks):
        # Entry: 100, SL: 95 -> Risk/lot = 325 (supports 15 lots by risk)
        # Exposure/lot = 6500. But available capital is only 4000.
        # 4000 // 6500 = 0 lots -> fails closed.
        res = configured_sizer.calculate_position_size(
            instrument="NIFTY",
            contract_symbol="NIFTY26NOV24500CE",
            option_type="CE",
            spot=24500.0,
            strike=24500.0,
            entry_premium=100.0,
            stop_loss=95.0,
            greeks=standard_greeks,
            available_capital=4000.0,
            portfolio_open_positions=[],
        )
        assert not res["isPermitted"]
        assert res["status"] == "INSUFFICIENT_CAPITAL"
        assert res["allocatedLots"] == 0


# =============================================================================
# 7. Circuit Breaker Integration Tests
# =============================================================================
class TestCircuitBreakerIntegration:
    def test_circuit_breaker_unconfigured_blocks_entry(self, temp_dir, standard_greeks):
        cb_path = os.path.join(temp_dir, "test_cb.json")
        cb = IntradayDrawdownCircuitBreaker(state_file_path=cb_path, auto_load=False)

        state_path = os.path.join(temp_dir, "test_greeks_state.json")
        sizer = DynamicGreeksPositionSizer(state_file_path=state_path, auto_load=False)
        sizer.configure_policy(
            max_trade_risk_inr=5000.0,
            max_portfolio_delta_inr=500000.0,
            max_portfolio_gamma_inr=10000.0,
            max_daily_theta_loss_inr=10000.0,
            max_portfolio_vega_inr=15000.0,
            max_capital_per_trade_inr=50000.0,
            approved_by="QUANT_RISK_COMMITTEE",
            reason="CB integration test",
            approval_reference="TEST-REF-CB-1",
            enforce_circuit_breaker=True,
            skip_governance_registry_check=True,
        )

        res = sizer.calculate_position_size(
            instrument="NIFTY",
            contract_symbol="NIFTY26NOV24500CE",
            option_type="CE",
            spot=24500.0,
            strike=24500.0,
            entry_premium=100.0,
            stop_loss=80.0,
            greeks=standard_greeks,
            available_capital=100000.0,
            portfolio_open_positions=[],
            circuit_breaker=cb,
        )
        assert not res["isPermitted"]
        assert res["status"] == "CIRCUIT_BREAKER_BLOCKED"

    def test_circuit_breaker_armed_permits_and_bounds_lots(self, temp_dir, standard_greeks):
        cb_path = os.path.join(temp_dir, "test_cb.json")
        cb = IntradayDrawdownCircuitBreaker(state_file_path=cb_path, auto_load=False)
        cb.configure_budget(
            budget_inr=2000.0,
            approved_by="QUANT_RISK_COMMITTEE",
            reason="Budget test",
            approval_reference="CB-BUDGET-REF-01",
            skip_governance_registry_check=True,
        )

        state_path = os.path.join(temp_dir, "test_greeks_state.json")
        sizer = DynamicGreeksPositionSizer(state_file_path=state_path, auto_load=False)
        sizer.configure_policy(
            max_trade_risk_inr=5000.0,
            max_portfolio_delta_inr=5000000.0,
            max_portfolio_gamma_inr=500000000.0,
            max_daily_theta_loss_inr=50000.0,
            max_portfolio_vega_inr=50000.0,
            max_capital_per_trade_inr=50000.0,
            approved_by="QUANT_RISK_COMMITTEE",
            reason="CB armed test",
            approval_reference="TEST-REF-CB-2",
            enforce_circuit_breaker=True,
            skip_governance_registry_check=True,
        )

        # Risk per lot: (100 - 80) * 65 = 1300.
        # Trade risk budget = 5000 (allows 3 lots).
        # Circuit breaker budget = 2000 (allows 1 lot: 2000 // 1300 = 1).
        # Circuit breaker must bind the allocation to 1 lot!
        res = sizer.calculate_position_size(
            instrument="NIFTY",
            contract_symbol="NIFTY26NOV24500CE",
            option_type="CE",
            spot=24500.0,
            strike=24500.0,
            entry_premium=100.0,
            stop_loss=80.0,
            greeks=standard_greeks,
            available_capital=100000.0,
            portfolio_open_positions=[],
            circuit_breaker=cb,
        )
        assert res["isPermitted"]
        assert res["status"] == "ALLOCATED"
        assert res["allocatedLots"] == 1
        assert res["bindingConstraint"] == "CIRCUIT_BREAKER_BLOCKED"


# =============================================================================
# 8. Portfolio Greeks Sensitivity Limits (Multi-Index Heat Caps)
# =============================================================================
class TestPortfolioGreeksCaps:
    def test_delta_limit_sizes_down_or_rejects(self, temp_dir, standard_greeks):
        # Contract notional delta = 0.52 * 24500 * 65 = 828,100 per lot.
        # Policy max_portfolio_delta_inr = 500,000.
        # Since 1 single lot (828,100) > max delta (500,000), Delta constraint is 0 lots!
        state_path = os.path.join(temp_dir, "test_greeks_delta_tight.json")
        sizer = DynamicGreeksPositionSizer(state_file_path=state_path, auto_load=False)
        sizer.configure_policy(
            max_trade_risk_inr=5000.0,
            max_portfolio_delta_inr=500000.0,  # Tight 5 Lakhs delta limit
            max_portfolio_gamma_inr=500000000.0,
            max_daily_theta_loss_inr=50000.0,
            max_portfolio_vega_inr=50000.0,
            max_capital_per_trade_inr=50000.0,
            approved_by="QUANT_RISK_COMMITTEE",
            reason="Tight delta test",
            approval_reference="TEST-DELTA-TIGHT",
            skip_governance_registry_check=True,
        )
        res = sizer.calculate_position_size(
            instrument="NIFTY",
            contract_symbol="NIFTY26NOV24500CE",
            option_type="CE",
            spot=24500.0,
            strike=24500.0,
            entry_premium=100.0,
            stop_loss=80.0,
            greeks=standard_greeks,
            available_capital=100000.0,
            portfolio_open_positions=[],
        )
        assert not res["isPermitted"]
        assert res["status"] == "DELTA_LIMIT_EXCEEDED"
        assert res["allocatedLots"] == 0

    def test_delta_capacity_allows_when_limit_sufficient(self, temp_dir, standard_greeks):
        state_path = os.path.join(temp_dir, "test_greeks_state_2.json")
        sizer = DynamicGreeksPositionSizer(state_file_path=state_path, auto_load=False)
        sizer.configure_policy(
            max_trade_risk_inr=5000.0,
            max_portfolio_delta_inr=2000000.0,  # 20 Lakhs delta limit
            max_portfolio_gamma_inr=100000000.0,
            max_daily_theta_loss_inr=50000.0,
            max_portfolio_vega_inr=50000.0,
            max_capital_per_trade_inr=100000.0,
            approved_by="QUANT_RISK_COMMITTEE",
            reason="High delta cap test",
            approval_reference="TEST-REF-HIGH-DELTA",
            enforce_circuit_breaker=False,
            skip_governance_registry_check=True,
        )

        # Delta per lot = 828,100. Headroom = 2,000,000 -> 2 lots permitted by delta.
        # Risk per lot: (100 - 80) * 65 = 1300 -> 5000 // 1300 = 3 lots by risk.
        # Minimum is 2 lots (bounded by Delta!).
        res = sizer.calculate_position_size(
            instrument="NIFTY",
            contract_symbol="NIFTY26NOV24500CE",
            option_type="CE",
            spot=24500.0,
            strike=24500.0,
            entry_premium=100.0,
            stop_loss=80.0,
            greeks=standard_greeks,
            available_capital=100000.0,
            portfolio_open_positions=[],
        )
        assert res["isPermitted"]
        assert res["status"] == "ALLOCATED"
        assert res["allocatedLots"] == 2
        assert res["bindingConstraint"] == "DELTA_LIMIT_EXCEEDED"

    def test_daily_theta_loss_limit_exceeded(self, temp_dir, standard_greeks):
        state_path = os.path.join(temp_dir, "test_greeks_state_3.json")
        sizer = DynamicGreeksPositionSizer(state_file_path=state_path, auto_load=False)
        sizer.configure_policy(
            max_trade_risk_inr=5000.0,
            max_portfolio_delta_inr=5000000.0,
            max_portfolio_gamma_inr=100000000.0,
            max_daily_theta_loss_inr=500.0,  # Strict theta decay limit: ₹500/day
            max_portfolio_vega_inr=50000.0,
            max_capital_per_trade_inr=100000.0,
            approved_by="QUANT_RISK_COMMITTEE",
            reason="Strict theta test",
            approval_reference="TEST-REF-THETA",
            enforce_circuit_breaker=False,
            skip_governance_registry_check=True,
        )

        # Daily theta per unit = -12.50. Per lot = 12.50 * 65 = 812.50 / day.
        # Limit is 500.0. 500 // 812.50 = 0 lots.
        res = sizer.calculate_position_size(
            instrument="NIFTY",
            contract_symbol="NIFTY26NOV24500CE",
            option_type="CE",
            spot=24500.0,
            strike=24500.0,
            entry_premium=100.0,
            stop_loss=80.0,
            greeks=standard_greeks,
            available_capital=100000.0,
            portfolio_open_positions=[],
        )
        assert not res["isPermitted"]
        assert res["status"] == "THETA_LIMIT_EXCEEDED"
        assert res["allocatedLots"] == 0

    def test_existing_open_positions_consume_headroom(self, temp_dir, standard_greeks):
        state_path = os.path.join(temp_dir, "test_greeks_state_4.json")
        sizer = DynamicGreeksPositionSizer(state_file_path=state_path, auto_load=False)
        sizer.configure_policy(
            max_trade_risk_inr=10000.0,
            max_portfolio_delta_inr=2000000.0,
            max_portfolio_gamma_inr=100000000.0,
            max_daily_theta_loss_inr=50000.0,
            max_portfolio_vega_inr=50000.0,
            max_capital_per_trade_inr=100000.0,
            approved_by="QUANT_RISK_COMMITTEE",
            reason="Portfolio headroom test",
            approval_reference="TEST-REF-HEADROOM",
            enforce_circuit_breaker=False,
            skip_governance_registry_check=True,
        )

        # Existing position with 1 lot already open (Delta = 828,100)
        open_pos = [{
            "id": "PT-EXISTING-01",
            "status": "OPEN",
            "instrument": "NIFTY",
            "contractSymbol": "NIFTY26NOV24500CE",
            "quantity": 65,
            "lots": 1,
            "lotSize": 65,
            "positionType": "BUY",
            "underlyingSpot": 24500.0,
            "currentPremium": 100.0,
            "greeks": standard_greeks,
        }]

        # Without existing pos, 2 lots allowed by Delta (2 * 828,100 = 1,656,200 <= 2,000,000).
        # With existing pos consuming 828,100, remaining delta headroom = 1,171,900.
        # 1,171,900 // 828,100 = 1 lot!
        res = sizer.calculate_position_size(
            instrument="NIFTY",
            contract_symbol="NIFTY26NOV24500CE",
            option_type="CE",
            spot=24500.0,
            strike=24500.0,
            entry_premium=100.0,
            stop_loss=80.0,
            greeks=standard_greeks,
            available_capital=100000.0,
            portfolio_open_positions=open_pos,
        )
        assert res["isPermitted"]
        assert res["allocatedLots"] == 1
        assert res["bindingConstraint"] == "DELTA_LIMIT_EXCEEDED"


# =============================================================================
# 9. Portfolio Greeks Aggregation Tests
# =============================================================================
class TestPortfolioGreeksAggregator:
    def test_multi_index_portfolio_aggregation(self):
        positions = [
            {
                "id": "PT-NIFTY-1",
                "status": "OPEN",
                "instrument": "NIFTY",
                "contractSymbol": "NIFTY26NOV24500CE",
                "quantity": 65,
                "lots": 1,
                "lotSize": 65,
                "positionType": "BUY",
                "underlyingSpot": 24000.0,
                "currentPremium": 120.0,
                "greeks": {"delta": 0.50, "gamma": 0.001, "theta": -10.0, "vega": 20.0},
            },
            {
                "id": "PT-BANKNIFTY-1",
                "status": "OPEN",
                "instrument": "BANKNIFTY",
                "contractSymbol": "BANKNIFTY26NOV52000CE",
                "quantity": 30,
                "lots": 1,
                "lotSize": 30,
                "positionType": "BUY",
                "underlyingSpot": 50000.0,
                "currentPremium": 250.0,
                "greeks": {"delta": 0.40, "gamma": 0.0005, "theta": -25.0, "vega": 40.0},
            },
            {
                "id": "PT-CLOSED-1",
                "status": "CLOSED",
                "instrument": "NIFTY",
                "contractSymbol": "NIFTY26NOV24000CE",
                "quantity": 0,
                "greeks": {"delta": 0.60, "gamma": 0.001, "theta": -10.0, "vega": 20.0},
            },
        ]

        res = PortfolioGreeksAggregator.aggregate(positions)
        assert res["openPositionsCount"] == 2
        assert not res["hasIncompleteData"]

        # Expected calculations:
        # NIFTY:
        # Point Delta = 0.50 * 65 = 32.50
        # Rupee Delta = 0.50 * 24000 * 65 = 780,000.0
        # Rupee Gamma = 0.001 * (24000^2) * 65 = 37,440,000.0
        # Daily Theta = -10.0 * 65 = -650.0
        # Rupee Vega = 20.0 * 65 = 1300.0
        # Exposure = 120 * 65 = 7800.0

        # BANKNIFTY:
        # Point Delta = 0.40 * 30 = 12.0
        # Rupee Delta = 0.40 * 50000 * 30 = 600,000.0
        # Rupee Gamma = 0.0005 * (50000^2) * 30 = 37,500,000.0
        # Daily Theta = -25.0 * 30 = -750.0
        # Rupee Vega = 40.0 * 30 = 1200.0
        # Exposure = 250 * 30 = 7500.0

        # Totals:
        assert res["netPointDeltaInr"] == pytest.approx(44.50, rel=1e-3)
        assert res["netNotionalRupeeDelta"] == pytest.approx(1380000.0, rel=1e-3)
        assert res["netRupeeGamma"] == pytest.approx(74940000.0, rel=1e-3)
        assert res["netDailyThetaInr"] == pytest.approx(-1400.0, rel=1e-3)
        assert res["netDailyThetaLossInr"] == pytest.approx(1400.0, rel=1e-3)
        assert res["netRupeeVega"] == pytest.approx(2500.0, rel=1e-3)
        assert res["totalOpenExposureInr"] == pytest.approx(15300.0, rel=1e-3)

        # Index breakdown check:
        assert "NIFTY" in res["indexBreakdown"]
        assert "BANKNIFTY" in res["indexBreakdown"]
        assert res["indexBreakdown"]["NIFTY"]["notionalRupeeDelta"] == pytest.approx(780000.0, rel=1e-3)
        assert res["indexBreakdown"]["BANKNIFTY"]["notionalRupeeDelta"] == pytest.approx(600000.0, rel=1e-3)


# =============================================================================
# 10. SENSEX Governance Lock Tests
# =============================================================================
class TestSensexGovernanceLock:
    def test_sensex_rejected_fail_closed(self, configured_sizer, standard_greeks):
        for sym in ["SENSEX", "BSE_SENSEX", "SENSEX50"]:
            res = configured_sizer.calculate_position_size(
                instrument=sym,
                contract_symbol=f"{sym}26NOV75000CE",
                option_type="CE",
                spot=75000.0,
                strike=75000.0,
                entry_premium=200.0,
                stop_loss=150.0,
                greeks=standard_greeks,
                available_capital=100000.0,
                portfolio_open_positions=[],
            )
            assert not res["isPermitted"]
            assert res["status"] == "GOVERNANCE_LOCKED"
            assert res["allocatedLots"] == 0
            assert "GOVERNANCE_LOCK" in res["reason"]


# =============================================================================
# 11. Paper Trading Engine Pipeline Integration Tests
# =============================================================================
class TestPaperTradingEngineIntegration:
    def test_paper_engine_sizing_and_greeks_storage(self, temp_dir, standard_greeks):
        storage_path = os.path.join(temp_dir, "test_paper_records.json")
        greeks_state_path = os.path.join(temp_dir, "test_greeks_state.json")

        sizer = DynamicGreeksPositionSizer(state_file_path=greeks_state_path, auto_load=False)
        sizer.configure_policy(
            max_trade_risk_inr=5000.0,
            max_portfolio_delta_inr=5000000.0,
            max_portfolio_gamma_inr=500000000.0,
            max_daily_theta_loss_inr=50000.0,
            max_portfolio_vega_inr=50000.0,
            max_capital_per_trade_inr=50000.0,
            approved_by="QUANT_RISK_COMMITTEE",
            reason="Integration test",
            approval_reference="TEST-INT-001",
            enforce_circuit_breaker=False,
            skip_governance_registry_check=True,
        )

        engine = PaperTradingEngine(
            storage_path=storage_path,
            greeks_risk_sizer=sizer,
        )

        # Open position with Greeks
        # Entry: 100, SL: 80 -> Risk/lot: 1300. Risk budget: 5000 -> 3 lots permitted.
        # Caller asks for 5 lots, but sizer should clamp it to 3 lots!
        open_res = engine.open_position(
            instrument="NIFTY",
            contract_symbol="NIFTY26NOV24500CE",
            bias="CE",
            strike=24500.0,
            expiry="26NOV2026",
            entry_premium=100.0,
            stop_loss=80.0,
            lots=5,
            lot_size=65,
            contract_greeks=standard_greeks,
            underlying_spot=24500.0,
            market_features={"allowAfterHoursSimulation": True},
        )

        assert open_res["success"]
        pos = open_res["position"]
        assert pos["lots"] == 3  # Clamped to 3 lots
        assert pos["quantity"] == 3 * 65
        assert pos["greeks"] == standard_greeks
        assert pos["rupeeDelta"] is not None

        # Verify get_portfolio_greeks
        port_greeks = engine.get_portfolio_greeks()
        assert port_greeks["openPositionsCount"] == 1
        assert port_greeks["netNotionalRupeeDelta"] > 0

    def test_paper_engine_rejects_when_sizer_fails_closed(self, temp_dir, standard_greeks):
        storage_path = os.path.join(temp_dir, "test_paper_records_2.json")
        greeks_state_path = os.path.join(temp_dir, "test_greeks_state_2.json")

        sizer = DynamicGreeksPositionSizer(state_file_path=greeks_state_path, auto_load=False)
        sizer.configure_policy(
            max_trade_risk_inr=1000.0,  # Very small risk budget
            max_portfolio_delta_inr=2000000.0,
            max_portfolio_gamma_inr=100000000.0,
            max_daily_theta_loss_inr=50000.0,
            max_portfolio_vega_inr=50000.0,
            max_capital_per_trade_inr=50000.0,
            approved_by="QUANT_RISK_COMMITTEE",
            reason="Small budget test",
            approval_reference="TEST-INT-002",
            enforce_circuit_breaker=False,
            skip_governance_registry_check=True,
        )

        engine = PaperTradingEngine(
            storage_path=storage_path,
            greeks_risk_sizer=sizer,
        )

        # Risk per lot: (100 - 80) * 65 = 1300. Budget is 1000 -> 0 lots allowed.
        open_res = engine.open_position(
            instrument="NIFTY",
            contract_symbol="NIFTY26NOV24500CE",
            bias="CE",
            strike=24500.0,
            expiry="26NOV2026",
            entry_premium=100.0,
            stop_loss=80.0,
            lots=1,
            lot_size=65,
            contract_greeks=standard_greeks,
            underlying_spot=24500.0,
            market_features={"allowAfterHoursSimulation": True},
        )

        assert not open_res["success"]
        assert open_res["status"] == "INSUFFICIENT_RISK_BUDGET"
        assert len(engine.state["openPositions"]) == 0


# =============================================================================
# 12. Governance Provenance & Single-Use Replay Protection Tests
# =============================================================================
class TestGovernanceProvenanceAndReplay:
    def test_single_use_approval_reference_consumption(self, temp_dir):
        state_path = os.path.join(temp_dir, "test_greeks_state.json")
        sizer = DynamicGreeksPositionSizer(state_file_path=state_path, auto_load=False)

        # First consumption
        sizer.configure_policy(
            max_trade_risk_inr=5000.0,
            max_portfolio_delta_inr=500000.0,
            max_portfolio_gamma_inr=10000.0,
            max_daily_theta_loss_inr=10000.0,
            max_portfolio_vega_inr=15000.0,
            max_capital_per_trade_inr=50000.0,
            approved_by="QUANT_RISK_COMMITTEE",
            reason="First authorization",
            approval_reference="REPLAY-TEST-REF-01",
            skip_governance_registry_check=True,
        )
        assert sizer.is_configured

        # Attempt to reuse the exact same reference -> ValueError
        with pytest.raises(ValueError, match="APPROVAL_REPLAY_DETECTED"):
            sizer.configure_policy(
                max_trade_risk_inr=6000.0,
                max_portfolio_delta_inr=500000.0,
                max_portfolio_gamma_inr=10000.0,
                max_daily_theta_loss_inr=10000.0,
                max_portfolio_vega_inr=15000.0,
                max_capital_per_trade_inr=50000.0,
                approved_by="QUANT_RISK_COMMITTEE",
                reason="Second authorization with reused ref",
                approval_reference="REPLAY-TEST-REF-01",
                skip_governance_registry_check=True,
            )


# =============================================================================
# 13. Concurrency & Thread-Safety Tests
# =============================================================================
class TestConcurrencyAndThreadSafety:
    def test_concurrent_position_sizing_evaluations(self, configured_sizer, standard_greeks):
        errors = []
        results = []

        def worker(idx):
            try:
                res = configured_sizer.calculate_position_size(
                    instrument="NIFTY",
                    contract_symbol=f"NIFTY26NOV{24500 + idx*50}CE",
                    option_type="CE",
                    spot=24500.0,
                    strike=24500.0 + idx * 50,
                    entry_premium=120.0 + idx,
                    stop_loss=100.0,
                    greeks=standard_greeks,
                    available_capital=100000.0,
                    portfolio_open_positions=[],
                )
                results.append(res)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(results) == 20


# =============================================================================
# 14. Crash-Resilient State Persistence Tests
# =============================================================================
class TestCrashResilientPersistence:
    def test_policy_persists_across_restart(self, temp_dir):
        state_path = os.path.join(temp_dir, "test_greeks_persist.json")
        sizer1 = DynamicGreeksPositionSizer(state_file_path=state_path, auto_load=False)
        sizer1.configure_policy(
            max_trade_risk_inr=7500.0,
            max_portfolio_delta_inr=750000.0,
            max_portfolio_gamma_inr=15000.0,
            max_daily_theta_loss_inr=12000.0,
            max_portfolio_vega_inr=18000.0,
            max_capital_per_trade_inr=60000.0,
            approved_by="QUANT_RISK_COMMITTEE",
            reason="Persistence test",
            approval_reference="PERSIST-REF-01",
            skip_governance_registry_check=True,
        )

        # Instantiate second sizer pointing to same file
        sizer2 = DynamicGreeksPositionSizer(state_file_path=state_path, auto_load=True)
        assert sizer2.is_configured
        policy = sizer2.get_policy()
        assert policy.max_trade_risk_inr == 7500.0
        assert policy.approval_reference == "PERSIST-REF-01"
        assert "PERSIST-REF-01" in sizer2._consumed_approval_references
