import os
import pytest
from multiprocessing import get_context
from fastapi.testclient import TestClient

from app.data.market_calendar import MarketCalendar
from app.core.config import settings
from app.options.paper_trading.paper_engine import PaperTradingEngine, SERVER_AUTHORIZED_MULTI_LEG_STRATEGIES
from app.options.paper_trading.profit_protection_research import (
    ProfitProtectionResearchEngine,
    ProfitProtectionPolicy,
    OptionTick,
)


@pytest.fixture(autouse=True)
def mock_market_open(monkeypatch):
    """Ensure MarketCalendar reports open so test orders proceed to rule checks."""
    monkeypatch.setattr(MarketCalendar, "is_market_open", lambda: True)


def _worker_multi_process_buy(storage_path, proc_idx, result_queue):
    """Worker function executed in separate OS processes for multi-process atomicity test."""
    try:
        from app.data.market_calendar import MarketCalendar
        MarketCalendar.is_market_open = lambda: True
        from app.options.paper_trading.paper_engine import PaperTradingEngine
        engine = PaperTradingEngine(storage_path=storage_path)
        res = engine.open_position(
            instrument="NIFTY 50",
            contract_symbol="NIFTY26NOV25750CE",
            bias="CE",
            strike=25750.0,
            expiry="26NOV2026",
            entry_premium=100.0,
            lots=1,
            lot_size=65,
            signal_id=f"SIG-PROC-{proc_idx}",
            request_id=f"REQ-PROC-{proc_idx}",
        )
        result_queue.put((proc_idx, res))
    except Exception as e:
        result_queue.put((proc_idx, {"success": False, "error": str(e)}))


def test_multiprocess_atomic_admission_safety(tmp_path):
    """
    P1 STEP 1: Verifies multi-process atomic admission across separate Python OS processes.
    Only 1 process must succeed; all other concurrent worker processes must be rejected.
    """
    storage = str(tmp_path / "paper_multiprocess.json")
    engine = PaperTradingEngine(storage_path=storage)
    engine.reset_account(initial_capital=500000.0)

    ctx = get_context("spawn")
    queue = ctx.Queue()

    # Launch 4 separate OS processes attempting to open the exact same contract
    num_processes = 4
    processes = []
    for i in range(num_processes):
        p = ctx.Process(target=_worker_multi_process_buy, args=(storage, i, queue))
        processes.append(p)

    for p in processes:
        p.start()

    for p in processes:
        p.join(timeout=10)

    results = []
    while not queue.empty():
        results.append(queue.get())

    assert len(results) == num_processes

    successes = [r for idx, r in results if r.get("success") is True]
    duplicates = [r for idx, r in results if r.get("reason") == "DUPLICATE_ACTIVE_CONTRACT"]

    # Exactly 1 process must succeed and exactly 3 must be rejected with DUPLICATE_ACTIVE_CONTRACT
    assert len(successes) == 1, f"Expected 1 success, got {len(successes)}: {results}"
    assert len(duplicates) == (num_processes - 1), f"Expected {num_processes - 1} duplicates, got {len(duplicates)}"

    # Verify state on disk has exactly 1 position and balance was deducted once
    reloaded_engine = PaperTradingEngine(storage_path=storage)
    assert len(reloaded_engine.state["openPositions"]) == 1
    assert reloaded_engine.state["balance"] == 500000.0 - (100.0 * 65)


def test_server_authorized_hedging_bypassing_prohibited(tmp_path, monkeypatch):
    """
    P1 STEP 1: Server-authorized hedging permissions.
    Client-provided allow_hedging flags must NEVER unilaterally bypass directional risk checks.
    """
    from app.main import app
    import app.api.routes.paper_trading as pt_route

    storage = str(tmp_path / "paper_hedging_sec.json")
    isolated_engine = PaperTradingEngine(storage_path=storage)
    isolated_engine.reset_account(initial_capital=200000.0)
    monkeypatch.setattr(pt_route, "paper_engine", isolated_engine)

    client = TestClient(app)
    auth_header = {"Authorization": f"Bearer {getattr(settings, 'OPERATOR_SECRET_KEY', '') or 'aivolve-internal-operator'}"}

    # 1. Open Bullish NIFTY 25700 CE
    r1 = client.post(
        "/api/paper-trading/open",
        json={
            "instrument": "NIFTY 50",
            "contractSymbol": "NIFTY26NOV25700CE",
            "bias": "CE",
            "strike": 25700.0,
            "expiry": "26NOV2026",
            "entryPremium": 120.0,
            "lots": 1,
            "lotSize": 65,
            "requestId": "HEDGE-REQ-1",
        },
        headers=auth_header,
    )
    assert r1.status_code == 200
    assert r1.json()["success"] is True

    # 2. Client passes allowHedging=True with NO authorized strategy (Bypass attempt)
    r2 = client.post(
        "/api/paper-trading/open",
        json={
            "instrument": "NIFTY 50",
            "contractSymbol": "NIFTY26NOV25700PE",
            "bias": "PE",
            "strike": 25700.0,
            "expiry": "26NOV2026",
            "entryPremium": 110.0,
            "lots": 1,
            "lotSize": 65,
            "allowHedging": True,
            "multiLegStrategy": None,
            "requestId": "HEDGE-REQ-2",
        },
        headers=auth_header,
    )
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["success"] is False
    assert d2["reason"] == "OPPOSING_DIRECTIONAL_CONFLICT"

    # 3. Client passes allowHedging=True with arbitrary forged strategy
    r3 = client.post(
        "/api/paper-trading/open",
        json={
            "instrument": "NIFTY 50",
            "contractSymbol": "NIFTY26NOV25700PE",
            "bias": "PE",
            "strike": 25700.0,
            "expiry": "26NOV2026",
            "entryPremium": 110.0,
            "lots": 1,
            "lotSize": 65,
            "allowHedging": True,
            "multiLegStrategy": "ARBITRARY_CUSTOM_STRATEGY",
            "requestId": "HEDGE-REQ-3",
        },
        headers=auth_header,
    )
    assert r3.status_code == 200
    d3 = r3.json()
    assert d3["success"] is False
    assert d3["reason"] == "OPPOSING_DIRECTIONAL_CONFLICT"

    # 4. Authorized institutional multi-leg strategy (LONG_STRADDLE) succeeds
    r4 = client.post(
        "/api/paper-trading/open",
        json={
            "instrument": "NIFTY 50",
            "contractSymbol": "NIFTY26NOV25700PE",
            "bias": "PE",
            "strike": 25700.0,
            "expiry": "26NOV2026",
            "entryPremium": 110.0,
            "lots": 1,
            "lotSize": 65,
            "allowHedging": True,
            "multiLegStrategy": "LONG_STRADDLE",
            "requestId": "HEDGE-REQ-4",
        },
        headers=auth_header,
    )
    assert r4.status_code == 200
    assert r4.json()["success"] is True


def test_reconstruction_pt_87bac4a8_and_pt_b43e2c4b_all_policies():
    """
    P1 STEP 2 & 3: Reconstructs PT-87BAC4A8 and PT-B43E2C4B across Policies A through G.
    Proves that Policy G and Policy C capture +₹1,314+ profit vs -₹758 loss on Policy A.
    """
    evaluation = ProfitProtectionResearchEngine.evaluate_20_nov_missed_profit_trades()
    t1 = evaluation["trade_PT_87BAC4A8"]
    t2 = evaluation["trade_PT_B43E2C4B"]
    combined = evaluation["combinedNetPnlByPolicy"]

    # Policy A (Original Static): Replicates actual historical loss
    assert t1["STATIC_A"]["netPnl"] < -700.0
    assert t2["STATIC_A"]["netPnl"] < -700.0
    assert combined["STATIC_A"] < -1400.0

    # Policy B (Breakeven): Protects capital, exits near breakeven
    assert t1["BREAKEVEN_B"]["netPnl"] > -100.0
    assert t1["BREAKEVEN_B"]["grossPnl"] >= 0.0

    # Policy C (ATR Trailing): Trailed at peak (~138.00), realizes +₹1,314+
    assert t1["ATR_TRAILING_C"]["netPnl"] > 1200.0
    assert t1["ATR_TRAILING_C"]["status"] == "TRAILING_STOP_HIT"

    # Policy G (Hybrid): Captures high excursion, realizes massive profit
    assert t1["HYBRID_G"]["netPnl"] > 1200.0
    assert t2["HYBRID_G"]["netPnl"] > 1200.0
    assert combined["HYBRID_G"] > 2500.0

    # Net positive improvement delta of Policy G over Policy A > ₹4,000
    improvement_delta = combined["HYBRID_G"] - combined["STATIC_A"]
    assert improvement_delta > 4000.0


def test_realistic_slippage_and_gap_down_fill():
    """
    P1 STEP 5: Verifies that virtual stops never assume a perfect stop fill on gap-down.
    If price gaps below SL, fill price must be <= gap low minus slippage.
    """
    # Option enters at 100.0, SL at 88.0 (-12 pts).
    # Next bar gaps violently down to 75.0 (Low 74.0, LTP 75.0)
    ticks = [
        OptionTick("01:00 PM", 100.0, 102.0, 99.0),
        OptionTick("01:05 PM", 75.0, 78.0, 74.0),
    ]
    res = ProfitProtectionResearchEngine.simulate_trade_path(
        trade_id="GAP-TEST-1",
        contract_symbol="NIFTY26NOV25750CE",
        entry_price=100.0,
        entry_timestamp="01:00 PM",
        initial_sl=88.0,
        target_1=130.0,
        target_2=155.0,
        lots=1,
        lot_size=65,
        ticks=ticks,
        policy=ProfitProtectionPolicy.STATIC_A,
        slippage_pts=0.5,
    )
    # Fill price must be realistic: min(ltp, low, sl) - 0.5 = 74.0 - 0.5 = 73.5
    assert res.exit_price <= 74.0
    assert res.exit_price < 88.0  # NOT filled at theoretical 88.0 stop!
    assert res.slippage_incurred > 0.0


def test_append_only_audit_trail_preservation():
    """
    P1 STEP 5: Verifies append-only audit trail for each stop-loss modification.
    """
    ticks = ProfitProtectionResearchEngine.get_historical_20_nov_ticks_for_25750_ce()
    res = ProfitProtectionResearchEngine.simulate_trade_path(
        trade_id="AUDIT-TEST",
        contract_symbol="NIFTY23NOV2625750CE",
        entry_price=116.30,
        entry_timestamp="01:51 PM",
        initial_sl=104.30,
        target_1=151.20,
        target_2=180.30,
        lots=1,
        lot_size=65,
        ticks=ticks,
        policy=ProfitProtectionPolicy.HYBRID_G,
    )

    assert len(res.sl_history) >= 2
    # Verify chronological monotonically increasing stop modifications
    for i in range(1, len(res.sl_history)):
        assert res.sl_history[i].new_sl >= res.sl_history[i - 1].new_sl
        assert res.sl_history[i].trigger_reason != ""
        assert res.sl_history[i].mfe_pts > 0


def test_walk_forward_oos_benchmark_validity():
    """
    P1 STEP 4: Validates walk-forward out-of-sample benchmarking.
    Separates in-sample calibration and untouched OOS evaluation sets.
    """
    benchmark = ProfitProtectionResearchEngine.run_walk_forward_benchmark()
    in_sample = benchmark["inSampleCalibration"]
    oos = benchmark["outOfSampleEvaluation"]
    verdict = benchmark["statisticalVerdict"]

    assert "HYBRID_G" in oos
    assert "STATIC_A" in oos
    assert oos["HYBRID_G"]["profitFactor"] > oos["STATIC_A"]["profitFactor"]
    assert oos["HYBRID_G"]["expectancy"] > oos["STATIC_A"]["expectancy"]
    assert verdict["statisticallySignificant"] is True
    assert verdict["productionDeploymentStatus"] == "RESEARCH_ONLY_OBSERVATION"


def test_read_only_api_endpoints(monkeypatch, tmp_path):
    """
    P1 STEP 6: Verifies read-only profit protection research endpoints in FastAPI.
    """
    from app.main import app
    import app.api.routes.paper_trading as pt_route

    storage = str(tmp_path / "paper_research_api.json")
    isolated_engine = PaperTradingEngine(storage_path=storage)
    isolated_engine.reset_account(initial_capital=200000.0)
    # Add a sample open position
    isolated_engine.open_position(
        instrument="NIFTY 50",
        contract_symbol="NIFTY26NOV25750CE",
        bias="CE",
        strike=25750.0,
        expiry="26NOV2026",
        entry_premium=116.30,
        lots=1,
        lot_size=65,
        request_id="RES-POS-1",
    )
    pos_id = isolated_engine.state["openPositions"][0]["id"]
    monkeypatch.setattr(pt_route, "paper_engine", isolated_engine)

    client = TestClient(app)
    auth_header = {"Authorization": f"Bearer {getattr(settings, 'OPERATOR_SECRET_KEY', '') or 'aivolve-internal-operator'}"}

    # 1. Benchmark overview endpoint
    r1 = client.get("/api/paper-trading/profit-protection/research", headers=auth_header)
    assert r1.status_code == 200
    d1 = r1.json()
    assert d1["status"] == "SUCCESS"
    assert d1["mode"] == "RESEARCH_ONLY_OBSERVATION"
    assert "walkForwardBenchmark" in d1

    # 2. Position counterfactual simulation endpoint
    r2 = client.get(f"/api/paper-trading/profit-protection/simulated-position/{pos_id}", headers=auth_header)
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["status"] == "SUCCESS"
    assert "activePositionSimulation" in d2
    assert d2["activePositionSimulation"]["contractSymbol"] == "NIFTY26NOV25750CE"
    assert d2["activePositionSimulation"]["observationOnly"] is True
