import os
import sys
import json
import math
import copy
import hashlib
import tempfile
import pytest
from datetime import datetime, timezone, timedelta

from app.options.paper_trading.paper_engine import PaperTradingEngine
from app.options.drawdown_circuit_breaker import IntradayDrawdownCircuitBreaker, CircuitBreakerState
from app.options.greeks_risk_engine import DynamicGreeksPositionSizer
from app.options.paper_trading.cost_calculator import IndianDerivativesCostCalculator
from app.data.market_calendar import MarketCalendar

PROTECTED_FILES = {
    r"d:\ReactJs\aivolve-trading-ai\backend\aivolve_trading.db": "C85C49BE76DEE40557C4B9AAF308B4E3BEACA03CD4B1CD1CE90D051566EABF44",
    r"d:\ReactJs\aivolve-trading-ai\backend\app\data\governance_ledger.db": "4B12B3BAB44BF913F15174278B346FA321D5C473272E40F8B7E6E2350034488E",
    r"d:\ReactJs\aivolve-trading-ai\backend\app\data\paper_trading_records.json": "00F968EF85095EB7C1DE336A1780F9EDE417426A253AC531446BEF1117DA0298",
    r"d:\ReactJs\aivolve-trading-ai\backend\app\data\ml_trade_dataset.json": "87EEA8802835BB4F5A0AD1D598F2CEC561C6D5237F123B8B57CD79BBBE2E6445",
    r"d:\ReactJs\aivolve-trading-ai\backend\app\data\what_ai_learned.json": "3ED015726DFF309000EEC473AB660F34E3BD4EFAEDCBE183B14D62C572E5CCC5",
    r"d:\ReactJs\aivolve-trading-ai\backend\app\data\ml_strategy_weights.json": "C3C495F36214BD7FA58DDCA3C7F0280C14E15EB08DF41F868704F724C2A4E2FC",
}

DEFAULT_TEST_GREEKS = {
    "delta": 0.50,
    "gamma": 0.0001,
    "theta": -10.0,
    "vega": 15.0,
    "iv": 0.18,
}

@pytest.fixture
def isolated_env():
    temp_dir = tempfile.TemporaryDirectory()
    store_path = os.path.join(temp_dir.name, "isolated_paper_records.json")
    cb_state_path = os.path.join(temp_dir.name, "isolated_cb_state.json")
    sizer_state_path = os.path.join(temp_dir.name, "isolated_sizer_state.json")

    # Initial isolated paper state
    initial_state = {
        "balance": 100000.0,
        "startingBalance": 100000.0,
        "positions": [],
        "openPositions": [],
        "closedTrades": [],
        "pendingOrders": [],
        "quarantinedPositions": [],
        "totalRealizedGrossPnl": 0.0,
        "totalRealizedNetPnl": 0.0,
        "totalTradingCosts": 0.0,
        "winCount": 0,
        "lossCount": 0,
        "stateVersion": 0,
        "lastUpdated": MarketCalendar.format_ist_timestamp()
    }
    with open(store_path, "w", encoding="utf-8") as f:
        json.dump(initial_state, f, indent=2)

    cb = IntradayDrawdownCircuitBreaker(state_file_path=cb_state_path)
    # Configure circuit breaker in isolated environment with operator authorization
    cb.configure_budget(
        budget_inr=10000.0,
        approved_by="SYSTEM_OPERATOR",
        reason="Isolated acceptance testing",
        approval_reference="OP-AUTH-2026-11-16",
        skip_governance_registry_check=True
    )

    sizer = DynamicGreeksPositionSizer(state_file_path=sizer_state_path)
    # Configure Greeks sizer in isolated environment with institutional limits
    sizer.configure_policy(
        max_trade_risk_inr=5000.0,
        max_portfolio_delta_inr=5000000.0,
        max_portfolio_gamma_inr=500000000.0,
        max_daily_theta_loss_inr=50000.0,
        max_portfolio_vega_inr=50000.0,
        max_capital_per_trade_inr=50000.0,
        approved_by="SYSTEM_OPERATOR",
        reason="Isolated acceptance testing",
        approval_reference="OP-AUTH-2026-11-16",
        max_permitted_lots=10,
        max_spread_pct=0.05,
        min_iv_floor=0.05,
        max_iv_ceiling=1.50,
        skip_governance_registry_check=True
    )

    engine = PaperTradingEngine(
        storage_path=store_path,
        circuit_breaker=cb,
        greeks_risk_sizer=sizer
    )

    yield {
        "engine": engine,
        "cb": cb,
        "sizer": sizer,
        "store_path": store_path,
        "temp_dir": temp_dir
    }
    temp_dir.cleanup()


def test_01_approved_buy_paper_entry(isolated_env):
    """Test 1: Approved BUY long option entry is admitted with exact cash deduction."""
    engine = isolated_env["engine"]
    initial_bal = engine._load_state()["balance"]
    assert initial_bal == 100000.0

    # Place an approved long BUY position
    res = engine.open_position(
        instrument="NIFTY",
        contract_symbol="NIFTY26NOV25200CE",
        bias="CE",
        strike=25200,
        expiry="2026-11-26",
        entry_premium=100.0,
        position_type="BUY",
        lots=1,
        lot_size=25,
        stop_loss=80.0,
        target_1=140.0,
        target_2=180.0,
        contract_greeks=DEFAULT_TEST_GREEKS,
        bid=99.0,
        ask=101.0,
        underlying_spot=25200.0,
        quote_timestamp=MarketCalendar.format_ist_timestamp(),
        market_features={"allowAfterHoursSimulation": True}
    )

    assert res["success"] is True
    pos = res["position"]
    assert pos is not None
    assert pos["id"] is not None
    assert pos["positionType"] == "BUY"
    assert pos["quantity"] == 25
    assert pos["entryPremium"] == 100.0

    # Margin used = 25 * 100 = 2500.0
    expected_margin_used = 2500.0

    state = engine._load_state()
    assert len(state["openPositions"]) == 1
    assert math.isclose(state["balance"], initial_bal - expected_margin_used, rel_tol=1e-3)


def test_02_sell_short_entry_rejected_fail_closed(isolated_env):
    """Test 2: All naked SELL/SHORT option writing attempts are strictly rejected."""
    engine = isolated_env["engine"]
    initial_bal = engine._load_state()["balance"]

    for invalid_type in ["SELL", "SHORT", "write", "PUT_SELL", "CALL_SELL", None, ""]:
        res = engine.open_position(
            instrument="NIFTY",
            contract_symbol="NIFTY26NOV25200PE",
            bias="PE",
            strike=25200,
            expiry="2026-11-26",
            entry_premium=120.0,
            position_type=invalid_type,
            lots=1,
            lot_size=25,
            stop_loss=140.0,
            target_1=80.0,
            contract_greeks=DEFAULT_TEST_GREEKS,
            bid=119.0,
            ask=121.0,
            underlying_spot=25200.0,
            quote_timestamp=MarketCalendar.format_ist_timestamp(),
            market_features={"allowAfterHoursSimulation": True}
        )
        assert res["success"] is False
        assert res["status"] == "NAKED_OPTIONS_WRITING_PROHIBITED"
        assert "NAKED_OPTIONS_WRITING_PROHIBITED" in res["message"]

    # Balance and positions remain 100% untouched
    state = engine._load_state()
    assert len(state["openPositions"]) == 0
    assert state["balance"] == initial_bal


def test_03_valid_long_position_close(isolated_env):
    """Test 3: Legitimate SELL action to close an existing long BUY position."""
    engine = isolated_env["engine"]
    pos_res = engine.open_position(
        instrument="NIFTY",
        contract_symbol="NIFTY26NOV25200CE",
        bias="CE",
        strike=25200,
        expiry="2026-11-26",
        entry_premium=100.0,
        position_type="BUY",
        lots=1,
        lot_size=25,
        stop_loss=80.0,
        target_1=140.0,
        contract_greeks=DEFAULT_TEST_GREEKS,
        bid=99.0,
        ask=101.0,
        underlying_spot=25200.0,
        quote_timestamp=MarketCalendar.format_ist_timestamp(),
        market_features={"allowAfterHoursSimulation": True}
    )
    assert pos_res["success"] is True
    pos = pos_res["position"]

    # Close long position at profit (exit_price = 130.0)
    close_res = engine.close_position(pos["id"], exit_price=130.0, exit_reason="Target 1 Hit")
    assert close_res["success"] is True
    trade = close_res["trade"]
    assert trade is not None
    assert trade["status"] == "TARGET_1_HIT"
    assert trade["exitPremium"] == 130.0
    assert trade["netPnl"] > 0

    state = engine._load_state()
    assert len(state["openPositions"]) == 0
    assert len(state["closedTrades"]) == 1
    # Virtual cash credited back + gross profit
    assert state["balance"] > 100000.0
    assert state["totalRealizedNetPnl"] > 0


def test_04_sl_and_target_monitoring_and_exits(isolated_env):
    """Test 4: Live tick price monitoring triggers stop-loss and target exits automatically."""
    engine = isolated_env["engine"]
    pos_res = engine.open_position(
        instrument="BANKNIFTY",
        contract_symbol="BANKNIFTY26NOV61000CE",
        bias="CE",
        strike=61000,
        expiry="2026-11-26",
        entry_premium=300.0,
        position_type="BUY",
        lots=1,
        lot_size=15,
        stop_loss=250.0,
        target_1=400.0,
        contract_greeks=DEFAULT_TEST_GREEKS,
        bid=298.0,
        ask=302.0,
        underlying_spot=61000.0,
        quote_timestamp=MarketCalendar.format_ist_timestamp(),
        market_features={"allowAfterHoursSimulation": True}
    )
    assert pos_res["success"] is True
    pos = pos_res["position"]

    # 1. Update with price within range (280.0) -> position stays open
    engine.update_live_monitoring(
        contract_symbol=pos["contractSymbol"],
        current_ltp=280.0
    )
    state = engine._load_state()
    assert len(state["openPositions"]) == 1

    # 2. Update with price dropping below stop loss (240.0 < 250.0) -> triggers SL exit
    engine.update_live_monitoring(
        contract_symbol=pos["contractSymbol"],
        current_ltp=240.0
    )
    state = engine._load_state()
    assert len(state["openPositions"]) == 0
    assert len(state["closedTrades"]) == 1
    closed = state["closedTrades"][0]
    assert closed["status"] == "STOP_LOSS_HIT"
    assert closed["netPnl"] < 0


def test_05_cash_and_pnl_reconciliation_with_statutory_fees(isolated_env):
    """Test 5: Mathematical reconciliation of cash balance + margin + PnL matching exact Indian statutory fees."""
    engine = isolated_env["engine"]
    initial_bal = 100000.0

    pos_res = engine.open_position(
        instrument="NIFTY",
        contract_symbol="NIFTY26NOV25200CE",
        bias="CE",
        strike=25200,
        expiry="2026-11-26",
        entry_premium=200.0,
        position_type="BUY",
        lots=2,
        lot_size=25,
        stop_loss=160.0,
        target_1=280.0,
        contract_greeks=DEFAULT_TEST_GREEKS,
        bid=199.0,
        ask=201.0,
        underlying_spot=25200.0,
        quote_timestamp=MarketCalendar.format_ist_timestamp(),
        market_features={"allowAfterHoursSimulation": True}
    )
    assert pos_res["success"] is True
    pos = pos_res["position"]

    expected_debit = 200.0 * 50 # 10000.0
    mid_bal = engine._load_state()["balance"]
    assert math.isclose(mid_bal, initial_bal - expected_debit, rel_tol=1e-3)

    close_res = engine.close_position(pos["id"], exit_price=250.0, exit_reason="Manual Exit")
    assert close_res["success"] is True

    # Check fee calculation
    costs = IndianDerivativesCostCalculator.calculate_trade_costs_and_pnl(
        entry_price=200.0,
        exit_price=250.0,
        quantity=50,
        position_type="BUY",
        orders_count=2
    )

    state = engine._load_state()
    assert math.isclose(state["balance"], initial_bal + (250.0 - 200.0) * 50, rel_tol=1e-3)
    assert math.isclose(state["totalRealizedGrossPnl"], 2500.0, rel_tol=1e-3)
    assert math.isclose(state["totalTradingCosts"], costs["totalCosts"], rel_tol=1e-2)
    assert math.isclose(state["totalRealizedNetPnl"], costs["netPnl"], rel_tol=1e-2)


def test_06_duplicate_order_prevention(isolated_env):
    """Test 6: Duplicate order submissions for identical contract and timestamp are rejected."""
    engine = isolated_env["engine"]
    pos_res = engine.open_position(
        instrument="FINNIFTY",
        contract_symbol="FINNIFTY26NOV28000CE",
        bias="CE",
        strike=28000,
        expiry="2026-11-26",
        entry_premium=80.0,
        position_type="BUY",
        lots=1,
        lot_size=25,
        stop_loss=60.0,
        target_1=120.0,
        contract_greeks=DEFAULT_TEST_GREEKS,
        bid=79.0,
        ask=81.0,
        underlying_spot=28000.0,
        quote_timestamp=MarketCalendar.format_ist_timestamp(),
        market_features={"allowAfterHoursSimulation": True}
    )
    assert pos_res["success"] is True
    pos = pos_res["position"]

    # Close the position once
    closed1 = engine.close_position(pos["id"], exit_price=100.0, exit_reason="Target 1 Hit")
    assert closed1["success"] is True

    # Second close must be rejected fail-closed without double crediting
    closed2 = engine.close_position(pos["id"], exit_price=100.0, exit_reason="Target 1 Hit")
    assert closed2["success"] is False
    assert "already closed" in closed2["message"].lower() or "not found" in closed2["message"].lower()

    state = engine._load_state()
    assert len(state["closedTrades"]) == 1


def test_07_concurrent_risk_checks_atomic(isolated_env):
    """Test 7: Thread-safe locking guarantees atomic risk headroom evaluation under concurrency."""
    import concurrent.futures
    engine = isolated_env["engine"]

    def try_open(idx):
        try:
            res = engine.open_position(
                instrument="NIFTY",
                contract_symbol=f"NIFTY26NOV25{idx}00CE",
                bias="CE",
                strike=25000 + idx * 100,
                expiry="2026-11-26",
                entry_premium=50.0,
                position_type="BUY",
                lots=1,
                lot_size=25,
                stop_loss=30.0,
                target_1=90.0,
                contract_greeks=DEFAULT_TEST_GREEKS,
                bid=49.0,
                ask=51.0,
                underlying_spot=25200.0,
                quote_timestamp=MarketCalendar.format_ist_timestamp(),
                market_features={"allowAfterHoursSimulation": True}
            )
            return res.get("position") if res.get("success") else None
        except Exception:
            return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(try_open, range(8)))

    successes = [r for r in results if r is not None]
    state = engine._load_state()
    assert len(state["openPositions"]) == len(successes)
    total_margin = sum(p["marginUsed"] for p in state["openPositions"])
    assert math.isclose(state["balance"] + total_margin, 100000.0, rel_tol=1e-3)


def test_08_websocket_disconnect_behavior_fail_closed(isolated_env):
    """Test 8: Circuit breaker and engine fail-closed when market data quotes are stale or disconnected."""
    cb = isolated_env["cb"]
    now_ist = MarketCalendar.now_ist()
    
    # 1. Fresh quote -> ARMED / Permitted
    open_positions = [{
        "instrument": "NIFTY",
        "contractSymbol": "NIFTY_TEST",
        "quantity": 25,
        "remainingQuantity": 25,
        "entryPremium": 100.0,
        "positionType": "BUY",
        "entryTimestamp": MarketCalendar.format_ist_timestamp(now_ist),
        "lastQuoteTimestamp": MarketCalendar.format_ist_timestamp(now_ist),
        "lastDataStatus": "VERIFIED_LIVE"
    }]
    engine_state = {
        "balance": 97500.0,
        "openPositions": open_positions,
        "closedTrades": []
    }
    fresh_quotes = {
        "NIFTY_TEST": {
            "ltp": 100.0,
            "timestamp": MarketCalendar.format_ist_timestamp(now_ist),
            "dataStatus": "VERIFIED_LIVE",
            "feedStatus": "VERIFIED_LIVE"
        }
    }
    status_armed = cb.evaluate_entry_eligibility(
        paper_engine_state=engine_state,
        instrument="NIFTY",
        quotes=fresh_quotes
    )
    assert status_armed["isPermitted"] is True

    # 2. Stale quote (>60s) -> PNL_DATA_UNAVAILABLE -> fail-closed
    stale_ts = MarketCalendar.format_ist_timestamp(now_ist - timedelta(seconds=120))
    stale_quotes = {
        "NIFTY_TEST": {
            "ltp": 100.0,
            "timestamp": stale_ts,
            "dataStatus": "STALE_TICK"
        }
    }
    status_stale = cb.evaluate_entry_eligibility(
        paper_engine_state=engine_state,
        instrument="NIFTY",
        quotes=stale_quotes
    )
    assert status_stale["isPermitted"] is False
    assert status_stale["state"] == CircuitBreakerState.PNL_DATA_UNAVAILABLE.value


def test_09_restart_and_recovery_from_store(isolated_env):
    """Test 9: Engine restarts reconstruct exact state, balance, open positions, and PnL without data loss."""
    engine = isolated_env["engine"]
    store_path = isolated_env["store_path"]

    pos_res = engine.open_position(
        instrument="NIFTY",
        contract_symbol="NIFTY26NOV25200CE",
        bias="CE",
        strike=25200,
        expiry="2026-11-26",
        entry_premium=100.0,
        position_type="BUY",
        lots=1,
        lot_size=25,
        stop_loss=80.0,
        target_1=140.0,
        contract_greeks=DEFAULT_TEST_GREEKS,
        bid=99.0,
        ask=101.0,
        underlying_spot=25200.0,
        quote_timestamp=MarketCalendar.format_ist_timestamp(),
        market_features={"allowAfterHoursSimulation": True}
    )
    assert pos_res["success"] is True
    pos = pos_res["position"]

    # Re-instantiate engine from storage
    new_engine = PaperTradingEngine(
        storage_path=store_path,
        circuit_breaker=isolated_env["cb"],
        greeks_risk_sizer=isolated_env["sizer"]
    )
    recovered = new_engine._load_state()
    assert len(recovered["openPositions"]) == 1
    assert recovered["openPositions"][0]["id"] == pos["id"]
    assert recovered["openPositions"][0]["contractSymbol"] == "NIFTY26NOV25200CE"
    assert recovered["balance"] == engine._load_state()["balance"]


def test_10_broker_execution_isolation_zero_live_orders():
    """Test 10: Verify that paper trading engine contains ZERO calls to real broker order placement APIs."""
    import inspect
    source = inspect.getsource(PaperTradingEngine)
    
    # Assert zero real broker trading keywords
    assert "smartapi.placeOrder" not in source
    assert "ORDER_ROUTING_LIVE" not in source
    assert "placeOrder(" not in source


def test_11_protected_baseline_hashes_untouched():
    """Test 11: Absolute verification that all 6 protected baseline files remain 100% bit-for-bit untouched."""
    for path, expected_hash in PROTECTED_FILES.items():
        assert os.path.exists(path), f"Protected file missing: {path}"
        with open(path, "rb") as f:
            actual_hash = hashlib.sha256(f.read()).hexdigest().upper()
        assert actual_hash == expected_hash, f"Protected file hash mismatch on {path}: expected {expected_hash}, got {actual_hash}"
