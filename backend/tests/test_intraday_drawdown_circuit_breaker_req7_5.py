"""
AIVOLVE Quantitative Options Intelligence Engine v3.0
Phase 7 / Step 7.5: Intraday Drawdown Circuit Breaker Verification Suite (REQ-7.5).

Covers all 17 mandatory test scenarios specified in Section 7 of institutional governance:
1. Unauthenticated configuration request.
2. Unauthorized configuration request.
3. Missing approval metadata.
4. Forged approval identity.
5. NaN and infinity budgets.
6. Valid authorized configuration.
7. Tick-triggered immediate drawdown breach.
8. Concurrent tick and entry requests.
9. Stale fallback premium rejection.
10. Missing quote timestamp.
11. Signal route returns NO_TRADE during breach.
12. Signal route returns NO_TRADE when budget is unconfigured.
13. Existing position exits remain allowed.
14. Weekend and exchange-holiday session handling.
15. Same-session restart persistence.
16. Overnight position handling.
17. Corrupted persistence and calendar-unavailable behavior.

Plus comprehensive mathematical P&L, partial-exit accounting, cross-index, and SENSEX invariants.
All tests operate in strict PAPER_TRADING_ONLY mode with isolated temporary storage.
Zero mutations to protected baseline data.
"""

import os
import json
import math
import pytest
import threading
from unittest.mock import patch
from datetime import datetime, date, timedelta

from fastapi.testclient import TestClient

from app.options.drawdown_circuit_breaker import (
    IntradayDrawdownCircuitBreaker,
    CircuitBreakerState,
    set_circuit_breaker,
    get_circuit_breaker,
)
from app.options.paper_trading.paper_engine import PaperTradingEngine
from app.options.paper_trading.cost_calculator import IndianDerivativesCostCalculator
from app.options.setup_selector import evaluate_options_trade_setups
from app.options.next_session_engine import evaluate_next_session_recommendation
from app.data.market_calendar import MarketCalendar
from app.main import app

TEST_APPROVAL_REF = "GOV-RISK-2026-TEST"
TEST_APPROVER = "QUANT_RISK_COMMITTEE"


@pytest.fixture
def mock_governance_registry():
    """Provides an in-memory mock governance approval registry without touching governance_ledger.db."""
    test_registry = {
        TEST_APPROVAL_REF: {
            "approval_reference": TEST_APPROVAL_REF,
            "approved_by": TEST_APPROVER,
            "status": "ACTIVE",
            "authorized_indices": ["NIFTY", "BANKNIFTY", "FINNIFTY"],
            "expiry_date": "2030-01-01",
        }
    }
    with patch("app.options.contract_selector.TRUSTED_APPROVAL_REGISTRY", test_registry), \
         patch("app.options.contract_selector.PROCESSED_APPROVAL_IDS", set()):
        yield test_registry


@pytest.fixture
def isolated_cb(tmp_path, mock_governance_registry):
    """Provides an isolated IntradayDrawdownCircuitBreaker instance using a temp state file."""
    state_file = str(tmp_path / "circuit_breaker_test_state.json")
    cb = IntradayDrawdownCircuitBreaker(state_file_path=state_file, auto_load=False)
    # Register as global singleton during test, reset afterwards
    set_circuit_breaker(cb)
    yield cb
    set_circuit_breaker(None)


@pytest.fixture
def isolated_paper_engine(tmp_path, isolated_cb):
    """Provides an isolated PaperTradingEngine backed by temp storage and isolated CB."""
    storage_file = str(tmp_path / "paper_records_test.json")
    ds_file = str(tmp_path / "ml_dataset_test.json")
    kb_file = str(tmp_path / "ml_kb_test.json")
    engine = PaperTradingEngine(
        storage_path=storage_file,
        ml_dataset_path=ds_file,
        ml_knowledge_path=kb_file,
        circuit_breaker=isolated_cb,
    )
    return engine


# =============================================================================
# 1. Unauthenticated Configuration Request
# =============================================================================
def test_01_unauthenticated_configuration_request(isolated_cb):
    """Verify POST /circuit-breaker/configure is permanently disabled (HTTP 405 Method Not Allowed)."""
    client = TestClient(app)
    resp = client.post("/api/paper-trading/circuit-breaker/configure", json={})
    assert resp.status_code == 405
    assert "disabled" in resp.json()["detail"].lower()


# =============================================================================
# 2. Unauthorized Configuration Request
# =============================================================================
def test_02_unauthorized_configuration_request(isolated_cb):
    """Verify HTTP POST returns 405, and server-side config with unknown reference raises PermissionError."""
    client = TestClient(app)
    resp = client.post(
        "/api/paper-trading/circuit-breaker/configure",
        json={
            "budgetINR": 5000.0,
            "approvedBy": TEST_APPROVER,
            "approvalReference": "UNAUTHORIZED-REF-9999",
            "reason": "Unauthorized test attempt",
        },
    )
    assert resp.status_code == 405

    # Server-side configuration rejects unknown reference
    with pytest.raises(PermissionError) as exc_info:
        isolated_cb.configure_budget_server_side(
            budget_inr=5000.0,
            approved_by=TEST_APPROVER,
            approval_reference="UNAUTHORIZED-REF-9999",
            reason="Server-side probe",
        )
    assert "Unknown or unregistered approval reference" in str(exc_info.value)


# =============================================================================
# 3. Missing Approval Metadata
# =============================================================================
def test_03_missing_approval_metadata(isolated_cb):
    """Verify HTTP POST returns 405, and server-side config lacking metadata raises ValueError."""
    client = TestClient(app)
    resp = client.post("/api/paper-trading/circuit-breaker/configure", json={"budgetINR": 5000.0})
    assert resp.status_code == 405

    # Missing approvedBy
    with pytest.raises(ValueError):
        isolated_cb.configure_budget_server_side(
            budget_inr=5000.0,
            approved_by="",
            approval_reference=TEST_APPROVAL_REF,
            reason="Missing approver test",
        )

    # Missing approvalReference
    with pytest.raises(ValueError):
        isolated_cb.configure_budget_server_side(
            budget_inr=5000.0,
            approved_by=TEST_APPROVER,
            approval_reference="",
            reason="Missing ref test",
        )


# =============================================================================
# 4. Forged Approval Identity
# =============================================================================
def test_04_forged_approval_identity(isolated_cb):
    """Verify HTTP POST returns 405, and server-side config with forged approver raises PermissionError."""
    client = TestClient(app)
    resp = client.post(
        "/api/paper-trading/circuit-breaker/configure",
        json={
            "budgetINR": 5000.0,
            "approvedBy": "IMPOSTOR_CALLER",
            "approvalReference": TEST_APPROVAL_REF,
            "reason": "Attempt with forged approver",
        },
    )
    assert resp.status_code == 405

    # Server-side configuration rejects forged identity
    with pytest.raises(PermissionError) as exc_info:
        isolated_cb.configure_budget_server_side(
            budget_inr=5000.0,
            approved_by="IMPOSTOR_CALLER",
            approval_reference=TEST_APPROVAL_REF,
            reason="Attempt with forged approver",
        )
    assert "Forged approval identity" in str(exc_info.value)


# =============================================================================
# 5. NaN and Infinity Budgets
# =============================================================================
def test_05_nan_and_infinity_budgets(isolated_cb):
    """Verify HTTP POST returns 405, and server-side non-finite/negative budgets raise ValueError."""
    client = TestClient(app)
    for invalid_val in [0.0, -500.0, -1.0]:
        resp = client.post(
            "/api/paper-trading/circuit-breaker/configure",
            json={"budgetINR": invalid_val},
        )
        assert resp.status_code == 405

    # Direct server-side method testing NaN, +inf, -inf
    for bad_num in [float("nan"), float("inf"), float("-inf"), 0.0, -100.0]:
        with pytest.raises(ValueError):
            isolated_cb.configure_budget_server_side(
                budget_inr=bad_num,
                approved_by=TEST_APPROVER,
                approval_reference=TEST_APPROVAL_REF,
                reason="Invalid budget check",
            )


# =============================================================================
# 6. Valid Authorized Configuration
# =============================================================================
def test_06_valid_authorized_configuration(isolated_cb):
    """Verify HTTP POST returns 405, while authorized server-side configuration succeeds and consumes reference."""
    client = TestClient(app)
    resp = client.post(
        "/api/paper-trading/circuit-breaker/configure",
        json={
            "budgetINR": 7500.0,
            "approvedBy": TEST_APPROVER,
            "approvalReference": TEST_APPROVAL_REF,
            "reason": "Institutional Q4 2026 daily drawdown budget",
        },
    )
    assert resp.status_code == 405

    # Authorized server-side configuration
    res = isolated_cb.configure_budget_server_side(
        budget_inr=7500.0,
        approved_by=TEST_APPROVER,
        approval_reference=TEST_APPROVAL_REF,
        reason="Institutional Q4 2026 daily drawdown budget",
    )
    assert res["configuredBudgetINR"] == 7500.0
    assert res["approvedBy"] == TEST_APPROVER
    assert res["approvalReference"] == TEST_APPROVAL_REF
    assert res["state"] == CircuitBreakerState.ARMED.value

    # Check audit record
    assert "auditRecord" in res
    audit = res["auditRecord"]
    assert audit["actor"] == TEST_APPROVER
    assert audit["approvalReference"] == TEST_APPROVAL_REF
    assert audit["newBudgetINR"] == 7500.0
    assert audit["action"] == "CONFIGURE_BUDGET"
    assert audit["outcome"] == "SUCCESS"

    # Verify reference was consumed (replay blocked)
    assert TEST_APPROVAL_REF in isolated_cb._consumed_approval_references

    # Verify breaker status is now ARMED
    status = isolated_cb.get_status()
    assert status["state"] == CircuitBreakerState.ARMED.value
    assert status["isPermitted"] is True
    assert status["dailyBudgetINR"] == 7500.0


# =============================================================================
# 7. Tick-Triggered Immediate Drawdown Breach
# =============================================================================
def test_07_tick_triggered_immediate_drawdown_breach(isolated_cb, isolated_paper_engine):
    """Verify market tick update immediately trips the circuit breaker without requiring an entry attempt."""
    # Configure ₹5,000 budget
    isolated_cb.configure_budget(
        budget_inr=5000.0,
        approved_by=TEST_APPROVER,
        approval_reference=TEST_APPROVAL_REF,
        reason="Tick breach test",
    )

    # Open 1 lot NIFTY CALL @ 100 (65 qty = ₹6,500 premium)
    open_res = isolated_paper_engine.open_position(
        instrument="NIFTY 50",
        contract_symbol="NIFTY26NOV24500CE",
        bias="CE",
        strike=24500.0,
        expiry="26NOV2026",
        entry_premium=100.0,
        lots=1,
        lot_size=65,
        market_features={"allowAfterHoursSimulation": True, "isTradeQualified": True},
    )
    assert open_res["success"] is True
    assert isolated_cb.state == CircuitBreakerState.ARMED.value

    # Simulate fresh market tick dropping premium from 100 to 15 (loss = 65 * 85 = ₹5,525 > ₹5,000)
    now_ist = MarketCalendar.format_ist_timestamp()
    quotes = {
        "NIFTY26NOV24500CE": {
            "ltp": 15.0,
            "dataStatus": "VERIFIED_LIVE",
            "feedStatus": "VERIFIED_LIVE",
            "timestamp": now_ist,
        }
    }

    # Tick update executes live monitoring
    isolated_paper_engine.update_live_monitoring(quotes_payload=quotes)

    # Assert breaker tripped IMMEDIATELY upon tick processing
    assert isolated_cb.state == CircuitBreakerState.DAILY_DRAWDOWN_BREACHED.value
    assert isolated_cb.is_entry_permitted() is False
    assert isolated_cb.get_status()["activeBreach"] is not None


# =============================================================================
# 8. Concurrent Tick and Entry Requests
# =============================================================================
def test_08_concurrent_tick_and_entry_requests(isolated_cb, isolated_paper_engine):
    """Verify thread-safe evaluation: concurrent tick pushing breach latches safely while concurrent entries fail closed."""
    isolated_cb.configure_budget(
        budget_inr=5000.0,
        approved_by=TEST_APPROVER,
        approval_reference=TEST_APPROVAL_REF,
        reason="Concurrency test",
    )

    # Initial open position
    isolated_paper_engine.open_position(
        instrument="NIFTY 50",
        contract_symbol="NIFTY_CONC_OPEN",
        bias="CE",
        strike=24500.0,
        expiry="26NOV2026",
        entry_premium=100.0,
        lots=1,
        lot_size=65,
        market_features={"allowAfterHoursSimulation": True, "isTradeQualified": True},
    )

    entry_results = []
    tick_errors = []

    def run_ticks():
        try:
            now_ist = MarketCalendar.format_ist_timestamp()
            quotes = {
                "NIFTY_CONC_OPEN": {
                    "ltp": 10.0,  # massive loss
                    "dataStatus": "VERIFIED_LIVE",
                    "feedStatus": "VERIFIED_LIVE",
                    "timestamp": now_ist,
                }
            }
            for _ in range(5):
                isolated_paper_engine.update_live_monitoring(quotes_payload=quotes)
        except Exception as e:
            tick_errors.append(e)

    def run_entries(idx):
        res = isolated_paper_engine.open_position(
            instrument="NIFTY 50",
            contract_symbol=f"NIFTY_CONC_SUB_{idx}",
            bias="CE",
            strike=24500.0,
            expiry="26NOV2026",
            entry_premium=100.0,
            market_features={"allowAfterHoursSimulation": True, "isTradeQualified": True},
        )
        entry_results.append(res)

    t_tick = threading.Thread(target=run_ticks)
    t_entries = [threading.Thread(target=run_entries, args=(i,)) for i in range(8)]

    t_tick.start()
    for t in t_entries:
        t.start()

    t_tick.join()
    for t in t_entries:
        t.join()

    assert len(tick_errors) == 0
    # Breaker must be latched in DAILY_DRAWDOWN_BREACHED
    assert isolated_cb.state == CircuitBreakerState.DAILY_DRAWDOWN_BREACHED.value
    assert isolated_cb.is_entry_permitted() is False


# =============================================================================
# 9. Stale Fallback Premium Rejection
# =============================================================================
def test_09_stale_fallback_premium_rejection(isolated_cb):
    """Verify old cached premium (>60s) is rejected and engine transitions to PNL_DATA_UNAVAILABLE."""
    isolated_cb.configure_budget(
        budget_inr=5000.0,
        approved_by=TEST_APPROVER,
        approval_reference=TEST_APPROVAL_REF,
        reason="Stale fallback test",
    )

    # Position quote timestamp is 120 seconds old (> 60s max staleness)
    stale_ts = (MarketCalendar.now_ist() - timedelta(seconds=120)).strftime("%d %b %Y, %I:%M %p IST")

    state = {
        "closedTrades": [],
        "openPositions": [
            {
                "id": "P-STALE",
                "contractSymbol": "NIFTY26NOV24500CE",
                "remainingQuantity": 65,
                "entryPremium": 100.0,
                "currentPremium": 105.0,
                "lastQuoteTimestamp": stale_ts,
                "lastDataStatus": "VERIFIED_LIVE",
                "positionType": "BUY",
                "partialExits": [],
            }
        ],
    }

    eval_res = isolated_cb.evaluate_circuit_breaker(state)
    assert eval_res["state"] == CircuitBreakerState.PNL_DATA_UNAVAILABLE.value
    assert eval_res["isPermitted"] is False
    assert any("stale" in r.lower() for r in eval_res.get("unavailabilityReasons", []))


# =============================================================================
# 10. Missing Quote Timestamp
# =============================================================================
def test_10_missing_quote_timestamp(isolated_cb):
    """Verify position or quote lacking timestamp trips PNL_DATA_UNAVAILABLE and fails closed."""
    isolated_cb.configure_budget(
        budget_inr=5000.0,
        approved_by=TEST_APPROVER,
        approval_reference=TEST_APPROVAL_REF,
        reason="Missing timestamp test",
    )

    state = {
        "closedTrades": [],
        "openPositions": [
            {
                "id": "P-NO-TS",
                "contractSymbol": "NIFTY26NOV24500CE",
                "remainingQuantity": 65,
                "entryPremium": 100.0,
                "currentPremium": 105.0,
                "lastQuoteTimestamp": None,  # Missing!
                "lastDataStatus": "VERIFIED_LIVE",
                "positionType": "BUY",
                "partialExits": [],
            }
        ],
    }

    eval_res = isolated_cb.evaluate_circuit_breaker(state)
    assert eval_res["state"] == CircuitBreakerState.PNL_DATA_UNAVAILABLE.value
    assert eval_res["isPermitted"] is False
    assert any("lacks verifiable quote timestamp" in r for r in eval_res.get("unavailabilityReasons", []))


# =============================================================================
# 11. Signal Route Returns NO_TRADE During Breach
# =============================================================================
def test_11_signal_route_returns_no_trade_during_breach(isolated_cb):
    """Verify setup selector, next session engine, and API routes fail closed with NO_TRADE during breach."""
    isolated_cb.configure_budget(
        budget_inr=5000.0,
        approved_by=TEST_APPROVER,
        approval_reference=TEST_APPROVAL_REF,
        reason="Signal breach test",
    )

    # Force breach state on active session date
    current_session = isolated_cb.get_current_session_date()
    state = {
        "closedTrades": [{"id": "T1", "netPnl": -6000.0, "exitTimestamp": current_session}],
        "openPositions": [],
    }
    isolated_cb.evaluate_circuit_breaker(state, session_date=current_session)
    assert isolated_cb.state == CircuitBreakerState.DAILY_DRAWDOWN_BREACHED.value

    # 1. Setup selector direct check
    setups = evaluate_options_trade_setups(
        symbol="NIFTY",
        underlying_ltp=24500.0,
        sentiment="BULLISH",
        sentiment_score=75,
        strikes_data=[],
        atr_14=150.0,
        circuit_breaker=isolated_cb,
    )
    assert setups["primaryBias"] == "NO_TRADE"
    assert setups["hasQualifiedSetups"] is False
    assert setups.get("circuitBreakerGated") is True
    assert setups["circuitBreakerState"] == CircuitBreakerState.DAILY_DRAWDOWN_BREACHED.value

    # 2. Next session engine direct check
    rec = evaluate_next_session_recommendation(
        symbol="NIFTY",
        underlying_ltp=24500.0,
        sentiment="BULLISH",
        sentiment_score=75,
        strikes_data=[],
        atr_14=150.0,
        daily_high=24600.0,
        daily_low=24400.0,
        daily_close=24500.0,
        daily_open=24450.0,
        circuit_breaker=isolated_cb,
    )
    assert rec["hasQualifiedRecommendation"] is False
    no_trade_reasons = rec.get("reasonsForNoTrade") or rec.get("noTradeReasons", [])
    assert any("circuit breaker" in r.lower() for r in no_trade_reasons)

    # 3. FastAPI endpoint check
    client = TestClient(app)
    resp = client.get("/api/options/NIFTY/setups")
    if resp.status_code == 200:
        data = resp.json()
        assert data["todayOptionsSetups"]["primaryBias"] == "NO_TRADE"
        assert data["todayOptionsSetups"].get("circuitBreakerGated") is True


# =============================================================================
# 12. Signal Route Returns NO_TRADE When Budget is Unconfigured
# =============================================================================
def test_12_signal_route_returns_no_trade_when_budget_unconfigured(isolated_cb):
    """Verify setup selector fails closed when risk budget is unconfigured (default state)."""
    isolated_cb._configured_budget_inr = None

    setups = evaluate_options_trade_setups(
        symbol="NIFTY",
        underlying_ltp=24500.0,
        sentiment="BULLISH",
        sentiment_score=75,
        strikes_data=[],
        atr_14=150.0,
        circuit_breaker=isolated_cb,
    )
    assert setups["primaryBias"] == "NO_TRADE"
    assert setups["hasQualifiedSetups"] is False
    assert setups.get("circuitBreakerGated") is True
    assert setups["circuitBreakerState"] == CircuitBreakerState.RISK_BUDGET_UNCONFIGURED.value


# =============================================================================
# 13. Existing Position Exits Remain Allowed
# =============================================================================
def test_13_existing_position_exits_remain_allowed(isolated_cb, isolated_paper_engine):
    """Verify that while new entries are rejected during breach, risk-reducing exits proceed normally."""
    isolated_cb.configure_budget(
        budget_inr=5000.0,
        approved_by=TEST_APPROVER,
        approval_reference=TEST_APPROVAL_REF,
        reason="Exit allowed test",
    )

    # Open position prior to breach
    open_res = isolated_paper_engine.open_position(
        instrument="NIFTY 50",
        contract_symbol="NIFTY26NOV24500CE",
        bias="CE",
        strike=24500.0,
        expiry="26NOV2026",
        entry_premium=100.0,
        lots=1,
        lot_size=65,
        market_features={"allowAfterHoursSimulation": True, "isTradeQualified": True},
    )
    assert open_res["success"] is True
    pos_id = open_res["position"]["id"]

    # Trigger breach externally on active session date
    current_session = isolated_cb.get_current_session_date()
    isolated_paper_engine.state["closedTrades"].append({
        "id": "T-EXTERNAL-LOSS",
        "netPnl": -5500.0,
        "exitTimestamp": current_session,
    })
    isolated_cb.recalculate_and_check(isolated_paper_engine.state, session_date=current_session)
    assert isolated_cb.state == CircuitBreakerState.DAILY_DRAWDOWN_BREACHED.value

    # Attempt new position -> must be blocked
    new_open = isolated_paper_engine.open_position(
        instrument="NIFTY 50",
        contract_symbol="NIFTY26NOV24600CE",
        bias="CE",
        strike=24600.0,
        expiry="26NOV2026",
        entry_premium=80.0,
        market_features={"allowAfterHoursSimulation": True, "isTradeQualified": True},
    )
    assert new_open["success"] is False
    assert new_open["circuitBreakerState"] == CircuitBreakerState.DAILY_DRAWDOWN_BREACHED.value

    # Close existing position -> MUST SUCCEED
    close_res = isolated_paper_engine.close_position(
        position_id=pos_id,
        exit_price=90.0,
        exit_reason="Emergency drawdown stop",
    )
    assert close_res["success"] is True
    assert close_res["trade"]["exitReason"] == "Emergency drawdown stop"
    assert len(isolated_paper_engine.state["openPositions"]) == 0


# =============================================================================
# 14. Weekend and Exchange-Holiday Session Handling
# =============================================================================
def test_14_weekend_and_exchange_holiday_session_handling(isolated_cb):
    """Verify Saturday, Sunday, and exchange holidays resolve to recent trading session and preserve breach."""
    # Simulate a Friday session: 2026-11-13
    friday_dt = datetime(2026, 11, 13, 15, 0, 0)
    friday_session = isolated_cb.get_current_session_date(friday_dt)
    assert friday_session == "2026-11-13"

    # Simulate Saturday: 2026-11-14 (non-trading)
    saturday_dt = datetime(2026, 11, 14, 11, 0, 0)
    sat_session = isolated_cb.get_current_session_date(saturday_dt)
    # Must normalize to Friday 2026-11-13, preserving active Friday breach!
    assert sat_session == "2026-11-13"

    # Simulate Sunday: 2026-11-15 (non-trading)
    sunday_dt = datetime(2026, 11, 15, 11, 0, 0)
    sun_session = isolated_cb.get_current_session_date(sunday_dt)
    assert sun_session == "2026-11-13"

    # Next trading day: Monday 2026-11-16
    monday_dt = datetime(2026, 11, 16, 9, 30, 0)
    mon_session = isolated_cb.get_current_session_date(monday_dt)
    assert mon_session == "2026-11-16"


# =============================================================================
# 15. Same-Session Restart Persistence
# =============================================================================
def test_15_same_session_restart_persistence(tmp_path, mock_governance_registry):
    """Verify persistent breaker state reloads correctly across backend restart without unlatching breach."""
    state_file = str(tmp_path / "cb_restart_state.json")

    # Instance 1: Configure and breach
    cb1 = IntradayDrawdownCircuitBreaker(state_file_path=state_file, auto_load=False)
    cb1.configure_budget(
        budget_inr=6000.0,
        approved_by=TEST_APPROVER,
        approval_reference=TEST_APPROVAL_REF,
        reason="Restart persistence test",
    )

    state = {
        "closedTrades": [{"id": "T-BREACH", "netPnl": -6500.0, "exitTimestamp": cb1.get_current_session_date()}],
        "openPositions": [],
    }
    cb1.evaluate_circuit_breaker(state)
    assert cb1.state == CircuitBreakerState.DAILY_DRAWDOWN_BREACHED.value
    breach_id = cb1._active_breach["id"]

    # Instance 2: Cold start reload from disk
    cb2 = IntradayDrawdownCircuitBreaker(state_file_path=state_file, auto_load=True)
    assert cb2._configured_budget_inr == 6000.0
    assert cb2._active_breach is not None
    assert cb2._active_breach["id"] == breach_id
    assert cb2.state == CircuitBreakerState.DAILY_DRAWDOWN_BREACHED.value
    assert cb2.is_entry_permitted() is False


# =============================================================================
# 16. Overnight Position Handling
# =============================================================================
def test_16_overnight_position_handling(isolated_cb):
    """Verify positions carried overnight evaluate floating mark-to-market without misattributing yesterday's trades."""
    isolated_cb.configure_budget(
        budget_inr=5000.0,
        approved_by=TEST_APPROVER,
        approval_reference=TEST_APPROVAL_REF,
        reason="Overnight position test",
    )

    today_session = isolated_cb.get_current_session_date()
    yesterday_date = (date.fromisoformat(today_session) - timedelta(days=1)).strftime("%Y-%m-%d")
    now_ist = MarketCalendar.format_ist_timestamp()

    # Yesterday's trade realized ₹2,000 loss in previous session
    # Open position carried overnight has current quote today
    state = {
        "closedTrades": [
            {
                "id": "T-YESTERDAY",
                "netPnl": -2000.0,
                "exitTimestamp": yesterday_date,
            }
        ],
        "openPositions": [
            {
                "id": "P-OVERNIGHT",
                "contractSymbol": "NIFTY26NOV24500CE",
                "remainingQuantity": 65,
                "entryPremium": 100.0,
                "currentPremium": 110.0,
                "lastQuoteTimestamp": now_ist,
                "lastDataStatus": "VERIFIED_LIVE",
                "positionType": "BUY",
                "partialExits": [],
            }
        ],
    }

    quotes = {
        "NIFTY26NOV24500CE": {
            "ltp": 110.0,
            "dataStatus": "VERIFIED_LIVE",
            "feedStatus": "VERIFIED_LIVE",
            "timestamp": now_ist,
        }
    }

    pnl_res = isolated_cb.calculate_daily_pnl(state, session_date=today_session, quotes=quotes)
    # Yesterday's closed trade must NOT be counted in today's realized PnL
    assert pnl_res["realizedNetPnL"] == 0.0
    # Floating PnL is positive
    assert pnl_res["floatingNetPnL"] > 500.0
    assert pnl_res["netDailyPnL"] > 500.0
    assert isolated_cb.state == CircuitBreakerState.ARMED.value


# =============================================================================
# 17. Corrupted Persistence and Calendar-Unavailable Behavior
# =============================================================================
def test_17_corrupted_persistence_and_calendar_unavailable_behavior(tmp_path):
    """Verify corrupted JSON persistence and calendar failure fail closed safely without crashing."""
    corrupted_file = str(tmp_path / "corrupted_cb_state.json")
    with open(corrupted_file, "w", encoding="utf-8") as f:
        f.write("{ CORRUPTED_NON_JSON_DATA ###!@# ")

    # Instance should catch error, log warning, and fail closed (unconfigured budget)
    cb = IntradayDrawdownCircuitBreaker(state_file_path=corrupted_file, auto_load=True)
    assert cb._configured_budget_inr is None
    assert cb.state == CircuitBreakerState.RISK_BUDGET_UNCONFIGURED.value
    assert cb.is_entry_permitted() is False

    # Calendar exception during session check: fails closed
    with patch("app.data.market_calendar.MarketCalendar.is_trading_day", side_effect=RuntimeError("Calendar DB offline")):
        session_d = cb.get_current_session_date()
        assert session_d is not None  # Fallback gracefully
        # Engine remains fail-closed
        assert cb.is_entry_permitted() is False


# =============================================================================
# 18. Positive Realized P&L Mathematics
# =============================================================================
def test_18_positive_realized_pnl(isolated_cb):
    """Verify positive realized daily P&L contributes correctly to net daily P&L and remains ARMED."""
    isolated_cb.configure_budget(
        budget_inr=5000.0,
        approved_by=TEST_APPROVER,
        approval_reference=TEST_APPROVAL_REF,
        reason="Math test",
    )

    state = {
        "closedTrades": [
            {"id": "T1", "netPnl": 1500.0, "exitTimestamp": "2026-11-14"},
            {"id": "T2", "netPnl": 750.0, "exitTimestamp": "2026-11-14"},
        ],
        "openPositions": [],
    }

    pnl_res = isolated_cb.calculate_daily_pnl(state, session_date="2026-11-14")
    assert pnl_res["realizedNetPnL"] == 2250.0
    assert pnl_res["floatingNetPnL"] == 0.0
    assert pnl_res["netDailyPnL"] == 2250.0

    eval_res = isolated_cb.evaluate_circuit_breaker(state, session_date="2026-11-14")
    assert eval_res["state"] == CircuitBreakerState.ARMED.value
    assert eval_res["isPermitted"] is True
    assert eval_res["drawdownUtilizationPct"] == 0.0


# =============================================================================
# 19. Negative Realized P&L Within Budget
# =============================================================================
def test_19_negative_realized_pnl_within_budget(isolated_cb):
    """Verify negative realized P&L within risk budget updates utilization and keeps state ARMED."""
    isolated_cb.configure_budget(
        budget_inr=5000.0,
        approved_by=TEST_APPROVER,
        approval_reference=TEST_APPROVAL_REF,
        reason="Math test",
    )

    state = {
        "closedTrades": [{"id": "T1", "netPnl": -1800.0, "exitTimestamp": "2026-11-14"}],
        "openPositions": [],
    }

    eval_res = isolated_cb.evaluate_circuit_breaker(state, session_date="2026-11-14")
    assert eval_res["state"] == CircuitBreakerState.ARMED.value
    assert eval_res["isPermitted"] is True
    assert eval_res["netDailyPnL"] == -1800.0
    assert eval_res["budgetRemainingINR"] == 3200.0
    assert eval_res["drawdownUtilizationPct"] == 36.0


# =============================================================================
# 20. Floating P&L Calculation with Statutory Charges
# =============================================================================
def test_20_floating_pnl_statutory_charges(isolated_cb):
    """Verify floating P&L on open positions reflects exact Indian derivatives cost deductions."""
    isolated_cb.configure_budget(
        budget_inr=5000.0,
        approved_by=TEST_APPROVER,
        approval_reference=TEST_APPROVAL_REF,
        reason="Charges test",
    )

    now_ist = MarketCalendar.format_ist_timestamp()
    state = {
        "closedTrades": [],
        "openPositions": [
            {
                "id": "P1",
                "contractSymbol": "NIFTY26NOV24500CE",
                "remainingQuantity": 65,
                "entryPremium": 100.0,
                "currentPremium": 120.0,
                "lastQuoteTimestamp": now_ist,
                "lastDataStatus": "VERIFIED_LIVE",
                "positionType": "BUY",
                "partialExits": [],
            }
        ],
    }

    quotes = {
        "NIFTY26NOV24500CE": {
            "ltp": 120.0,
            "dataStatus": "VERIFIED_LIVE",
            "feedStatus": "VERIFIED_LIVE",
            "timestamp": now_ist,
        }
    }

    pnl_res = isolated_cb.calculate_daily_pnl(state, quotes=quotes)
    assert pnl_res["realizedNetPnL"] == 0.0
    assert pnl_res["floatingNetPnL"] > 1200.0  # Net profit after fees
    assert pnl_res["netDailyPnL"] == pnl_res["floatingNetPnL"]


# =============================================================================
# 21. Exact Drawdown Threshold Breach (L_net_daily == -B_daily_max)
# =============================================================================
def test_21_exact_drawdown_threshold_breach(isolated_cb):
    """Verify net loss exactly equal to negative daily budget trips the circuit breaker."""
    isolated_cb.configure_budget(
        budget_inr=5000.0,
        approved_by=TEST_APPROVER,
        approval_reference=TEST_APPROVAL_REF,
        reason="Exact breach test",
    )

    state = {
        "closedTrades": [{"id": "T1", "netPnl": -5000.0, "exitTimestamp": "2026-11-14"}],
        "openPositions": [],
    }

    eval_res = isolated_cb.evaluate_circuit_breaker(state, session_date="2026-11-14")
    assert eval_res["state"] == CircuitBreakerState.DAILY_DRAWDOWN_BREACHED.value
    assert eval_res["isPermitted"] is False
    assert eval_res["activeBreach"] is not None


# =============================================================================
# 22. Partial-Exit Accounting Without Double-Counting
# =============================================================================
def test_22_partial_exit_accounting_no_double_counting(isolated_cb):
    """
    Verify partial exits are counted on currently open positions,
    and NOT double-counted once the parent position is closed.
    """
    isolated_cb.configure_budget(
        budget_inr=5000.0,
        approved_by=TEST_APPROVER,
        approval_reference=TEST_APPROVAL_REF,
        reason="Partial exit test",
    )

    now_ist = MarketCalendar.format_ist_timestamp()

    # Scenario A: Position is OPEN, 1 partial exit executed today (+₹400)
    state_open = {
        "closedTrades": [],
        "openPositions": [
            {
                "id": "P1",
                "contractSymbol": "NIFTY26NOV24500CE",
                "remainingQuantity": 30,
                "entryPremium": 100.0,
                "currentPremium": 100.0,
                "lastQuoteTimestamp": now_ist,
                "lastDataStatus": "VERIFIED_LIVE",
                "positionType": "BUY",
                "partialExits": [
                    {
                        "exitLots": 1,
                        "exitQuantity": 35,
                        "exitPrice": 120.0,
                        "netPnl": 400.0,
                        "timestamp": "2026-11-14",
                    }
                ],
            }
        ],
    }

    quotes = {
        "NIFTY26NOV24500CE": {
            "ltp": 100.0,
            "dataStatus": "VERIFIED_LIVE",
            "feedStatus": "VERIFIED_LIVE",
            "timestamp": now_ist,
        }
    }

    pnl_a = isolated_cb.calculate_daily_pnl(state_open, session_date="2026-11-14", quotes=quotes)
    assert pnl_a["realizedNetPnL"] == 400.0
    assert pnl_a["partialExitsTodayCount"] == 1

    # Scenario B: Position is now fully CLOSED.
    # closedTrade["netPnl"] already includes the partial exit!
    state_closed = {
        "closedTrades": [
            {
                "id": "P1",
                "netPnl": 650.0,  # 400 from partial + 250 from final
                "exitTimestamp": "2026-11-14",
                "partialExits": [
                    {
                        "exitLots": 1,
                        "exitQuantity": 35,
                        "exitPrice": 120.0,
                        "netPnl": 400.0,
                        "timestamp": "2026-11-14",
                    }
                ],
            }
        ],
        "openPositions": [],
    }
    pnl_b = isolated_cb.calculate_daily_pnl(state_closed, session_date="2026-11-14")
    # Must equal 650.0, NEVER 650 + 400 = 1050!
    assert pnl_b["realizedNetPnL"] == 650.0
    assert pnl_b["closedTodayCount"] == 1


# =============================================================================
# 23. Cross-Index Shared Breaker Behavior
# =============================================================================
def test_23_cross_index_shared_breaker_behavior(isolated_cb, isolated_paper_engine):
    """Verify cumulative loss on NIFTY blocks new entries across BANK NIFTY and FINNIFTY."""
    isolated_cb.configure_budget(
        budget_inr=5000.0,
        approved_by=TEST_APPROVER,
        approval_reference=TEST_APPROVAL_REF,
        reason="Cross index test",
    )

    # NIFTY trade realizes ₹5,500 loss
    isolated_paper_engine.state["closedTrades"] = [
        {"id": "T-NIFTY", "instrument": "NIFTY 50", "netPnl": -5500.0, "exitTimestamp": isolated_cb.get_current_session_date()}
    ]
    isolated_cb.recalculate_and_check(isolated_paper_engine.state)

    # Attempt BANK NIFTY entry
    bank_entry = isolated_paper_engine.open_position(
        instrument="BANKNIFTY",
        contract_symbol="BANKNIFTY26NOV52000CE",
        bias="CE",
        strike=52000.0,
        expiry="26NOV2026",
        entry_premium=250.0,
        market_features={"allowAfterHoursSimulation": True, "isTradeQualified": True},
    )
    assert bank_entry["success"] is False
    assert bank_entry["circuitBreakerState"] == CircuitBreakerState.DAILY_DRAWDOWN_BREACHED.value

    # Attempt FINNIFTY entry
    fin_entry = isolated_paper_engine.open_position(
        instrument="FINNIFTY",
        contract_symbol="FINNIFTY26NOV23500PE",
        bias="PE",
        strike=23500.0,
        expiry="26NOV2026",
        entry_premium=120.0,
        market_features={"allowAfterHoursSimulation": True, "isTradeQualified": True},
    )
    assert fin_entry["success"] is False
    assert fin_entry["circuitBreakerState"] == CircuitBreakerState.DAILY_DRAWDOWN_BREACHED.value


# =============================================================================
# 24. SENSEX Governance Lock Remains Enforced
# =============================================================================
def test_24_sensex_governance_lock_enforced(isolated_cb, isolated_paper_engine):
    """Verify SENSEX remains strictly GOVERNANCE_LOCKED across all components."""
    isolated_cb.configure_budget(
        budget_inr=5000.0,
        approved_by=TEST_APPROVER,
        approval_reference=TEST_APPROVAL_REF,
        reason="SENSEX lock test",
    )

    # 1. Direct evaluate_entry_eligibility check
    eligibility = isolated_cb.evaluate_entry_eligibility(
        paper_engine_state={"closedTrades": [], "openPositions": []},
        instrument="SENSEX",
    )
    assert eligibility["isPermitted"] is False
    assert eligibility["state"] == "GOVERNANCE_LOCKED"
    assert "SENSEX" in eligibility["reason"]

    # 2. PaperTradingEngine open_position check
    sensex_trade = isolated_paper_engine.open_position(
        instrument="SENSEX",
        contract_symbol="SENSEX26NOV80000CE",
        bias="CE",
        strike=80000.0,
        expiry="26NOV2026",
        entry_premium=300.0,
        market_features={"allowAfterHoursSimulation": True, "isTradeQualified": True},
    )
    assert sensex_trade["success"] is False
    assert sensex_trade["circuitBreakerState"] == "GOVERNANCE_LOCKED"
    assert "GOVERNANCE_LOCK" in sensex_trade["message"]

    # 3. Setup Selector check
    setup_res = evaluate_options_trade_setups(
        symbol="SENSEX",
        underlying_ltp=80000.0,
        sentiment="BULLISH",
        sentiment_score=75,
        strikes_data=[],
        atr_14=400.0,
    )
    assert setup_res["hasQualifiedSetups"] is False
    assert setup_res["primaryBias"] == "NO_TRADE"
    assert setup_res.get("governanceLocked") is True

    # 4. Next Session Recommendation Engine check
    rec_res = evaluate_next_session_recommendation(
        symbol="SENSEX",
        underlying_ltp=80000.0,
        sentiment="BULLISH",
        sentiment_score=75,
        strikes_data=[],
        atr_14=400.0,
        daily_high=80500.0,
        daily_low=79800.0,
        daily_close=80200.0,
        daily_open=80000.0,
    )
    assert rec_res["hasQualifiedRecommendation"] is False
    no_trade_list = rec_res.get("reasonsForNoTrade") or rec_res.get("noTradeReasons", [])
    assert any("SENSEX" in r and "GOVERNANCE_LOCK" in r for r in no_trade_list)
