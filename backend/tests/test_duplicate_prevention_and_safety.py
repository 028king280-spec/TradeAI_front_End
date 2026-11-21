import os
import time
import pytest
from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient

from app.data.market_calendar import MarketCalendar
from app.options.paper_trading.paper_engine import PaperTradingEngine


@pytest.fixture(autouse=True)
def mock_market_open(monkeypatch):
    """Ensure MarketCalendar reports open so order admission proceeds to rule checks."""
    monkeypatch.setattr(MarketCalendar, "is_market_open", lambda: True)


def test_duplicate_active_contract_rejection_exact_symbol(tmp_path):
    storage = str(tmp_path / "paper_dup_test.json")
    engine = PaperTradingEngine(storage_path=storage)
    engine.reset_account(initial_capital=100000.0)

    # 1. First order admitted
    res1 = engine.open_position(
        instrument="NIFTY 50",
        contract_symbol="NIFTY26NOV25750CE",
        bias="CE",
        strike=25750.0,
        expiry="26NOV2026",
        entry_premium=120.0,
        lots=1,
        lot_size=65,
        signal_id="SIG-001",
        request_id="REQ-001",
    )
    assert res1["success"] is True
    assert len(engine.state["openPositions"]) == 1

    # 2. Attempt duplicate entry with same contract symbol
    res2 = engine.open_position(
        instrument="NIFTY 50",
        contract_symbol="NIFTY26NOV25750CE",
        bias="CE",
        strike=25750.0,
        expiry="26NOV2026",
        entry_premium=122.0,
        lots=1,
        lot_size=65,
        signal_id="SIG-002",
        request_id="REQ-002",
    )
    assert res2["success"] is False
    assert res2["reason"] == "DUPLICATE_ACTIVE_CONTRACT"
    assert "DUPLICATE_ACTIVE_CONTRACT" in res2["message"]
    # Verify open positions count remains exactly 1 and balance not deducted again
    assert len(engine.state["openPositions"]) == 1
    assert engine.state["balance"] == 100000.0 - (120.0 * 65)


def test_duplicate_active_contract_rejection_by_token_and_attributes(tmp_path):
    storage = str(tmp_path / "paper_token_dup.json")
    engine = PaperTradingEngine(storage_path=storage)
    engine.reset_account(initial_capital=100000.0)

    res1 = engine.open_position(
        instrument="NIFTY 50",
        contract_symbol="NIFTY26NOV25750CE",
        bias="CE",
        strike=25750.0,
        expiry="26NOV2026",
        entry_premium=100.0,
        lots=1,
        lot_size=65,
        instrument_token=999888,
        signal_id="SIG-101",
        request_id="REQ-101",
    )
    assert res1["success"] is True

    # Same token with slightly different string format
    res2 = engine.open_position(
        instrument="NIFTY",
        contract_symbol="NIFTY_26NOV_25750_CE_ALT",
        bias="CE",
        strike=25750.0,
        expiry="26NOV2026",
        entry_premium=101.0,
        lots=1,
        lot_size=65,
        instrument_token=999888,
        signal_id="SIG-102",
        request_id="REQ-102",
    )
    assert res2["success"] is False
    assert res2["reason"] == "DUPLICATE_ACTIVE_CONTRACT"

    # Equivalent strike, expiry, bias on same underlying
    res3 = engine.open_position(
        instrument="NIFTY 50",
        contract_symbol="NIFTY26NOV25750CE_EQUIV",
        bias="CE",
        strike=25750.0,
        expiry="26NOV2026",
        entry_premium=102.0,
        lots=1,
        lot_size=65,
        signal_id="SIG-103",
        request_id="REQ-103",
    )
    assert res3["success"] is False
    assert res3["reason"] == "DUPLICATE_ACTIVE_CONTRACT"


def test_parallel_simultaneous_admissions_thread_safety(tmp_path):
    storage = str(tmp_path / "paper_parallel_dup.json")
    engine = PaperTradingEngine(storage_path=storage)
    engine.reset_account(initial_capital=500000.0)

    # Fire 8 concurrent attempts to buy the same contract
    def attempt_buy(idx):
        return engine.open_position(
            instrument="NIFTY 50",
            contract_symbol="NIFTY26NOV25750CE",
            bias="CE",
            strike=25750.0,
            expiry="26NOV2026",
            entry_premium=110.0,
            lots=1,
            lot_size=65,
            signal_id=f"SIG-PARALLEL-{idx}",
            request_id=f"REQ-PARALLEL-{idx}",
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(attempt_buy, range(8)))

    successes = [r for r in results if r["success"] is True]
    duplicates = [r for r in results if r.get("reason") == "DUPLICATE_ACTIVE_CONTRACT"]

    # Exactly 1 must succeed, 7 must be rejected with DUPLICATE_ACTIVE_CONTRACT
    assert len(successes) == 1
    assert len(duplicates) == 7
    assert len(engine.state["openPositions"]) == 1


def test_reused_signal_id_rejection(tmp_path):
    storage = str(tmp_path / "paper_signal_dup.json")
    engine = PaperTradingEngine(storage_path=storage)
    engine.reset_account(initial_capital=100000.0)

    res1 = engine.open_position(
        instrument="NIFTY 50",
        contract_symbol="NIFTY26NOV25750CE",
        bias="CE",
        strike=25750.0,
        expiry="26NOV2026",
        entry_premium=100.0,
        lots=1,
        lot_size=65,
        signal_id="SIG-REUSED-001",
        request_id="REQ-001",
    )
    assert res1["success"] is True

    # Close the position so contract is no longer active
    engine.close_position(res1["position"]["id"], exit_price=120.0, exit_reason="TARGET_1_HIT")

    # Attempt new position with the SAME signal_id
    res2 = engine.open_position(
        instrument="NIFTY 50",
        contract_symbol="NIFTY26NOV25800CE",
        bias="CE",
        strike=25800.0,
        expiry="26NOV2026",
        entry_premium=90.0,
        lots=1,
        lot_size=65,
        signal_id="SIG-REUSED-001",
        request_id="REQ-002",
    )
    assert res2["success"] is False
    assert res2["reason"] == "DUPLICATE_SIGNAL_ID"


def test_reused_request_id_idempotency_rejection(tmp_path):
    storage = str(tmp_path / "paper_req_id_dup.json")
    engine = PaperTradingEngine(storage_path=storage)
    engine.reset_account(initial_capital=100000.0)

    res1 = engine.open_position(
        instrument="NIFTY 50",
        contract_symbol="NIFTY26NOV25750CE",
        bias="CE",
        strike=25750.0,
        expiry="26NOV2026",
        entry_premium=100.0,
        lots=1,
        lot_size=65,
        request_id="IDEMPOTENT-KEY-999",
    )
    assert res1["success"] is True

    # Re-submission with the same request_id
    res2 = engine.open_position(
        instrument="BANKNIFTY",
        contract_symbol="BANKNIFTY26NOV54000CE",
        bias="CE",
        strike=54000.0,
        expiry="26NOV2026",
        entry_premium=250.0,
        lots=1,
        lot_size=15,
        request_id="IDEMPOTENT-KEY-999",
    )
    assert res2["success"] is False
    assert res2["reason"] == "DUPLICATE_REQUEST_ID"


def test_cooldown_safety_after_stop_loss(tmp_path):
    storage = str(tmp_path / "paper_cooldown.json")
    engine = PaperTradingEngine(storage_path=storage)
    engine.reset_account(initial_capital=100000.0)

    # Configure cooldown: 300 seconds for stop loss hit
    engine.configure_cooldown(enabled=True, duration_seconds=300)

    res1 = engine.open_position(
        instrument="NIFTY 50",
        contract_symbol="NIFTY26NOV25750CE",
        bias="CE",
        strike=25750.0,
        expiry="26NOV2026",
        entry_premium=100.0,
        lots=1,
        lot_size=65,
        request_id="REQ-CD-1",
        signal_id="SIG-CD-1",
    )
    assert res1["success"] is True
    pos_id = res1["position"]["id"]

    # Close with STOP_LOSS_HIT
    close_res = engine.close_position(pos_id, exit_price=80.0, exit_reason="STOP_LOSS_HIT")
    assert close_res["success"] is True

    # Immediate re-entry attempt for the same contract
    res2 = engine.open_position(
        instrument="NIFTY 50",
        contract_symbol="NIFTY26NOV25750CE",
        bias="CE",
        strike=25750.0,
        expiry="26NOV2026",
        entry_premium=82.0,
        lots=1,
        lot_size=65,
        request_id="REQ-CD-2",
        signal_id="SIG-CD-2",
    )
    assert res2["success"] is False
    assert res2["reason"] == "TRADE_COOLDOWN_ACTIVE"
    assert "TRADE_COOLDOWN_ACTIVE" in res2["message"]

    # Clear cooldown manually and re-try
    engine.clear_cooldown("NIFTY26NOV25750CE")
    res3 = engine.open_position(
        instrument="NIFTY 50",
        contract_symbol="NIFTY26NOV25750CE",
        bias="CE",
        strike=25750.0,
        expiry="26NOV2026",
        entry_premium=82.0,
        lots=1,
        lot_size=65,
        request_id="REQ-CD-3",
        signal_id="SIG-CD-3",
    )
    assert res3["success"] is True


def test_cooldown_unconfigured_behavior(tmp_path):
    storage = str(tmp_path / "paper_no_cooldown.json")
    engine = PaperTradingEngine(storage_path=storage)
    engine.reset_account(initial_capital=100000.0)

    # Cooldown is unconfigured (0s duration) by default
    res1 = engine.open_position(
        instrument="NIFTY 50",
        contract_symbol="NIFTY26NOV25750CE",
        bias="CE",
        strike=25750.0,
        expiry="26NOV2026",
        entry_premium=100.0,
        lots=1,
        lot_size=65,
        request_id="REQ-NOCD-1",
        signal_id="SIG-NOCD-1",
    )
    pos_id = res1["position"]["id"]
    engine.close_position(pos_id, exit_price=80.0, exit_reason="STOP_LOSS_HIT")

    # With cooldown unconfigured, new entry with fresh signal/request ID is permitted
    res2 = engine.open_position(
        instrument="NIFTY 50",
        contract_symbol="NIFTY26NOV25750CE",
        bias="CE",
        strike=25750.0,
        expiry="26NOV2026",
        entry_premium=81.0,
        lots=1,
        lot_size=65,
        request_id="REQ-NOCD-2",
        signal_id="SIG-NOCD-2",
    )
    assert res2["success"] is True


def test_opposing_directional_conflict_rejection(tmp_path):
    storage = str(tmp_path / "paper_opposing.json")
    engine = PaperTradingEngine(storage_path=storage)
    engine.reset_account(initial_capital=200000.0)

    # 1. Open Bullish Directional Trade (NIFTY 25700 CE)
    res1 = engine.open_position(
        instrument="NIFTY 50",
        contract_symbol="NIFTY26NOV25700CE",
        bias="CE",
        strike=25700.0,
        expiry="26NOV2026",
        entry_premium=115.0,
        lots=1,
        lot_size=65,
        request_id="REQ-DIR-1",
        signal_id="SIG-DIR-1",
    )
    assert res1["success"] is True

    # 2. Attempt Opposing Bearish Trade (NIFTY 25700 PE) without hedging authorization
    res2 = engine.open_position(
        instrument="NIFTY 50",
        contract_symbol="NIFTY26NOV25700PE",
        bias="PE",
        strike=25700.0,
        expiry="26NOV2026",
        entry_premium=105.0,
        lots=1,
        lot_size=65,
        request_id="REQ-DIR-2",
        signal_id="SIG-DIR-2",
    )
    assert res2["success"] is False
    assert res2["reason"] == "OPPOSING_DIRECTIONAL_CONFLICT"
    assert "OPPOSING_DIRECTIONAL_CONFLICT" in res2["message"]

    # 3. Authorized Multi-Leg / Hedged Trade (e.g. straddle or hedging flag set)
    res3 = engine.open_position(
        instrument="NIFTY 50",
        contract_symbol="NIFTY26NOV25700PE",
        bias="PE",
        strike=25700.0,
        expiry="26NOV2026",
        entry_premium=105.0,
        lots=1,
        lot_size=65,
        allow_hedging=True,
        multi_leg_strategy="LONG_STRADDLE",
        request_id="REQ-HEDGE-1",
        signal_id="SIG-HEDGE-1",
    )
    assert res3["success"] is True


def test_valid_independent_contract_admissions(tmp_path):
    storage = str(tmp_path / "paper_independent.json")
    engine = PaperTradingEngine(storage_path=storage)
    engine.reset_account(initial_capital=200000.0)

    # Open NIFTY 25750 CE
    res1 = engine.open_position(
        instrument="NIFTY 50",
        contract_symbol="NIFTY26NOV25750CE",
        bias="CE",
        strike=25750.0,
        expiry="26NOV2026",
        entry_premium=100.0,
        lots=1,
        lot_size=65,
        request_id="REQ-IND-1",
        signal_id="SIG-IND-1",
    )
    assert res1["success"] is True

    # Open BANKNIFTY 54000 CE (independent underlying and contract)
    res2 = engine.open_position(
        instrument="BANKNIFTY",
        contract_symbol="BANKNIFTY26NOV54000CE",
        bias="CE",
        strike=54000.0,
        expiry="26NOV2026",
        entry_premium=200.0,
        lots=1,
        lot_size=15,
        request_id="REQ-IND-2",
        signal_id="SIG-IND-2",
    )
    assert res2["success"] is True
    assert len(engine.state["openPositions"]) == 2


def test_admission_after_legitimate_closure(tmp_path):
    storage = str(tmp_path / "paper_legit_close.json")
    engine = PaperTradingEngine(storage_path=storage)
    engine.reset_account(initial_capital=100000.0)

    res1 = engine.open_position(
        instrument="NIFTY 50",
        contract_symbol="NIFTY26NOV25750CE",
        bias="CE",
        strike=25750.0,
        expiry="26NOV2026",
        entry_premium=100.0,
        lots=1,
        lot_size=65,
        request_id="REQ-CLOSE-1",
        signal_id="SIG-CLOSE-1",
    )
    pos_id = res1["position"]["id"]

    # Close position legitimately at Target 1
    engine.close_position(pos_id, exit_price=130.0, exit_reason="TARGET_1_HIT")
    assert len(engine.state["openPositions"]) == 0

    # New entry for same contract with new signal & request ID
    res2 = engine.open_position(
        instrument="NIFTY 50",
        contract_symbol="NIFTY26NOV25750CE",
        bias="CE",
        strike=25750.0,
        expiry="26NOV2026",
        entry_premium=125.0,
        lots=1,
        lot_size=65,
        request_id="REQ-CLOSE-2",
        signal_id="SIG-CLOSE-2",
    )
    assert res2["success"] is True
    assert len(engine.state["openPositions"]) == 1


def test_restart_and_persistence_recovery(tmp_path):
    storage = str(tmp_path / "paper_restart.json")
    engine1 = PaperTradingEngine(storage_path=storage)
    engine1.reset_account(initial_capital=100000.0)

    # Open position with specific request and signal IDs
    res1 = engine1.open_position(
        instrument="NIFTY 50",
        contract_symbol="NIFTY26NOV25750CE",
        bias="CE",
        strike=25750.0,
        expiry="26NOV2026",
        entry_premium=100.0,
        lots=1,
        lot_size=65,
        request_id="REQ-PERSIST-1",
        signal_id="SIG-PERSIST-1",
    )
    assert res1["success"] is True

    # Simulate backend restart by instantiating a new engine with same storage
    engine2 = PaperTradingEngine(storage_path=storage)
    assert len(engine2.state["openPositions"]) == 1
    assert "REQ-PERSIST-1" in engine2._processed_request_ids
    assert "SIG-PERSIST-1" in engine2._executed_signal_ids

    # Attempt duplicate contract admission on restarted engine
    dup_contract = engine2.open_position(
        instrument="NIFTY 50",
        contract_symbol="NIFTY26NOV25750CE",
        bias="CE",
        strike=25750.0,
        expiry="26NOV2026",
        entry_premium=105.0,
        lots=1,
        lot_size=65,
        request_id="REQ-PERSIST-2",
        signal_id="SIG-PERSIST-2",
    )
    assert dup_contract["success"] is False
    assert dup_contract["reason"] == "DUPLICATE_ACTIVE_CONTRACT"

    # Attempt reused request ID on restarted engine
    dup_req = engine2.open_position(
        instrument="BANKNIFTY",
        contract_symbol="BANKNIFTY26NOV54000CE",
        bias="CE",
        strike=54000.0,
        expiry="26NOV2026",
        entry_premium=200.0,
        lots=1,
        lot_size=15,
        request_id="REQ-PERSIST-1",
        signal_id="SIG-PERSIST-3",
    )
    assert dup_req["success"] is False
    assert dup_req["reason"] == "DUPLICATE_REQUEST_ID"


def test_eod_cleanup_timestamp_separation(tmp_path):
    storage = str(tmp_path / "paper_eod_safety.json")
    engine = PaperTradingEngine(storage_path=storage)
    engine.reset_account(initial_capital=100000.0)

    res1 = engine.open_position(
        instrument="NIFTY 50",
        contract_symbol="NIFTY26NOV25750CE",
        bias="CE",
        strike=25750.0,
        expiry="26NOV2026",
        entry_premium=100.0,
        lots=1,
        lot_size=65,
        request_id="REQ-EOD-1",
        signal_id="SIG-EOD-1",
    )
    pos_id = res1["position"]["id"]

    # Provide a verified quote update
    engine.update_live_monitoring(
        contract_symbol="NIFTY26NOV25750CE",
        current_ltp=95.0,
        bar_high=102.0,
        bar_low=94.0,
    )

    # Perform post-market cleanup at 15:53:00 IST
    close_res = engine.close_position(
        pos_id,
        exit_price=95.0,
        exit_reason="EOD_MARKET_CLOSE_AUTO_SQUARE_OFF",
        exit_timestamp="03:53:15 pm",
    )
    assert close_res["success"] is True

    closed_trade = engine.state["closedTrades"][0]
    # Verify fillTimestamp is set to last verified quote time, not post-market ledger cleanup
    assert closed_trade["isPostMarketCleanup"] is True
    assert closed_trade["marketSessionClose"] == "15:30:00 IST"
    assert "ledgerCleanupTimestamp" in closed_trade
    assert closed_trade["ledgerCleanupTimestamp"] == "03:53:15 pm"
    assert "fillTimestamp" in closed_trade
    assert closed_trade["fillTimestamp"] != ""


def test_api_route_duplicate_prevention_and_cooldown(tmp_path, monkeypatch):
    from app.main import app
    from app.options.paper_trading.paper_engine import PaperTradingEngine
    from app.core.config import settings
    import app.api.routes.paper_trading as pt_route

    # Isolate engine in route module
    storage = str(tmp_path / "paper_api_test.json")
    isolated_engine = PaperTradingEngine(storage_path=storage)
    isolated_engine.reset_account(initial_capital=200000.0)
    monkeypatch.setattr(pt_route, "paper_engine", isolated_engine)

    client = TestClient(app)
    auth_header = {"Authorization": f"Bearer {getattr(settings, 'OPERATOR_SECRET_KEY', '') or 'aivolve-internal-operator'}"}

    payload1 = {
        "instrument": "NIFTY 50",
        "contractSymbol": "NIFTY26NOV25750CE",
        "bias": "CE",
        "strike": 25750.0,
        "expiry": "26NOV2026",
        "entryPremium": 100.0,
        "lots": 1,
        "lotSize": 65,
        "requestId": "API-REQ-1",
        "signalId": "API-SIG-1",
        "instrumentToken": 555444,
    }

    # First request
    r1 = client.post("/api/paper-trading/open", json=payload1, headers=auth_header)
    assert r1.status_code == 200
    d1 = r1.json()
    assert d1["success"] is True

    # Duplicate contract request
    payload2 = {
        "instrument": "NIFTY 50",
        "contractSymbol": "NIFTY26NOV25750CE",
        "bias": "CE",
        "strike": 25750.0,
        "expiry": "26NOV2026",
        "entryPremium": 102.0,
        "lots": 1,
        "lotSize": 65,
        "requestId": "API-REQ-2",
        "signalId": "API-SIG-2",
        "instrumentToken": 555444,
    }
    r2 = client.post("/api/paper-trading/open", json=payload2, headers=auth_header)
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["success"] is False
    assert d2["reason"] == "DUPLICATE_ACTIVE_CONTRACT"

    # Duplicate request ID
    payload3 = {
        "instrument": "BANKNIFTY",
        "contractSymbol": "BANKNIFTY26NOV54000CE",
        "bias": "CE",
        "strike": 54000.0,
        "expiry": "26NOV2026",
        "entryPremium": 200.0,
        "lots": 1,
        "lotSize": 15,
        "requestId": "API-REQ-1",
    }
    r3 = client.post("/api/paper-trading/open", json=payload3, headers=auth_header)
    assert r3.status_code == 200
    d3 = r3.json()
    assert d3["success"] is False
    assert d3["reason"] == "DUPLICATE_REQUEST_ID"

    # Check cooldowns endpoint
    r_cd = client.get("/api/paper-trading/cooldowns", headers=auth_header)
    assert r_cd.status_code == 200
    d_cd = r_cd.json()
    assert "activeCooldowns" in d_cd
    assert "policy" in d_cd
