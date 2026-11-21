"""
AIVOLVE v3.0 — P2 Independent Profit Protection & Shadow Mode Test Suite.

Validates:
1. Data provenance separation of synthetic vs genuine market data.
2. Independent walk-forward replay on genuine historical paper records.
3. Execution realism (slippage, gap fills, transaction costs).
4. Read-only Policy G shadow monitoring without live order mutation.
5. REST API endpoint /profit-protection/shadow-monitoring.
6. Final institutional validation verdict and governance locks.
7. Protected baseline files integrity (SHA-256 verification).
"""

import pytest
import hashlib
import os
import json
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.data.market_calendar import MarketCalendar
from app.options.paper_trading.paper_engine import paper_engine
from app.options.paper_trading.profit_protection_research import ProfitProtectionPolicy
from app.options.paper_trading.independent_profit_validation import (
    IndependentProfitValidator,
    ValidationVerdict,
)


@pytest.fixture(autouse=True)
def mock_market_open(monkeypatch):
    """Ensure MarketCalendar reports market open so admission tests proceed cleanly."""
    monkeypatch.setattr(MarketCalendar, "is_market_open", lambda: True)


@pytest.fixture
def auth_headers():
    token = settings.OPERATOR_SECRET_KEY or "aivolve-internal-operator"
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client():
    return TestClient(app)


def test_data_provenance_audit_separates_synthetic_and_genuine():
    """TASK 1: Ensures data provenance separates synthetic models from genuine market records."""
    audit = IndependentProfitValidator.audit_data_provenance()
    assert audit["syntheticSamplesCount"] == 45, "Should identify exactly 45 synthetic setups (20 CAL + 25 OOS)"
    assert audit["genuineHistoricalSamplesCount"] >= 23, "Should identify at least 23 genuine historical trades"
    assert "synthetic" in audit["provenanceFinding"].lower()
    assert "empirical" in audit["provenanceFinding"].lower()


def test_walk_forward_replay_empirical_reproducibility():
    """TASK 2: Reproduces walk-forward metrics across genuine historical paper trades."""
    replay = IndependentProfitValidator.execute_independent_walk_forward_replay()

    # Out-of-sample (20 Nov 2026) checks
    oos = replay["outOfSampleEvaluation"]
    assert "STATIC_A" in oos
    assert "HYBRID_G" in oos
    assert "ATR_TRAILING_C" in oos

    # Policy G must outperform Static A on 20 Nov out-of-sample
    assert oos["HYBRID_G"]["total_net_pnl"] > oos["STATIC_A"]["total_net_pnl"]
    assert oos["HYBRID_G"]["profit_factor"] > oos["STATIC_A"]["profit_factor"]
    assert oos["HYBRID_G"]["win_rate_percent"] >= oos["STATIC_A"]["win_rate_percent"]

    # Verify turnaround delta
    delta = replay["empiricalDeltaNovember20"]
    assert delta["netTurnaroundRupees"] >= 5000.0, f"Expected >=+₹5000 net improvement on 20 Nov, got {delta['netTurnaroundRupees']}"

    # Target trades PT-87BAC4A8 and PT-B43E2C4B counterfactual verification
    target_trades = {t["tradeId"]: t for t in replay["november20TargetTrades"]}
    assert "PT-87BAC4A8" in target_trades
    assert "PT-B43E2C4B" in target_trades

    t1 = target_trades["PT-87BAC4A8"]
    t2 = target_trades["PT-B43E2C4B"]
    assert t1["policyANetPnl"] < 0, "Original Policy A should show loss"
    assert t1["policyGNetPnl"] > 0, "Policy G should convert PT-87BAC4A8 to profit"
    assert t2["policyANetPnl"] < 0, "Original Policy A should show loss"
    assert t2["policyGNetPnl"] > 0, "Policy G should convert PT-B43E2C4B to profit"


def test_execution_realism_slippage_and_regulatory_charges():
    """TASK 3: Audits slippage and statutory charge accounting on replay fills."""
    sample_trade = {
        "id": "TEST-EXEC-01",
        "contractSymbol": "NIFTY23NOV2625750CE",
        "positionType": "BUY",
        "entryPremium": 100.0,
        "initialStopLoss": 88.0,
        "target1": 130.0,
        "target2": 155.0,
        "mfePts": 25.0,  # Triggers Tier 2 (+10 pts lock = ₹110.0)
        "maePts": 5.0,
        "lots": 1,
        "lotSize": 65,
        "exitPremium": 95.0,  # Reversal below locked stop
        "netPnl": -400.0,
        "exitReason": "Manual Close",
        "status": "CLOSED",
    }

    res_g = IndependentProfitValidator.replay_trade_under_policy(sample_trade, ProfitProtectionPolicy.HYBRID_G)
    assert res_g["status"] == "HYBRID_PROTECTIVE_EXIT"
    # Execution should be at protective stop (116.0 for Tier 3 trail) minus 0.5 slippage = 115.50
    assert res_g["exitPrice"] == 115.50
    assert res_g["netPnl"] > 0, "Should achieve net positive profit after slippage and costs"
    assert res_g["retainedMfePercent"] > 0


def test_shadow_mode_live_monitoring_read_only(tmp_path):
    """TASK 5: Verifies that shadow mode computes Policy G metrics without altering active paper trades."""
    from app.options.paper_trading.paper_engine import PaperTradingEngine
    test_engine = PaperTradingEngine(storage_path=str(tmp_path / "shadow_test.json"))
    test_engine.reset_account(initial_capital=100000.0)

    trade_id = "SHADOW-TEST-POS-01"
    contract = "NIFTY23NOV2625900CE"
    open_res = test_engine.open_position(
        instrument="NIFTY 50",
        contract_symbol=contract,
        bias="CE",
        strike=25900.0,
        expiry="23NOV2026",
        entry_premium=100.0,
        position_type="BUY",
        lots=1,
        lot_size=65,
        stop_loss=88.0,
        target_1=130.0,
        target_2=155.0,
        target_3=180.0,
        signal_id="SIG-SHADOW-01",
        request_id="REQ-SHADOW-01",
    )
    assert open_res.get("success") is True or "position" in open_res

    # Position is open. Simulate live quote update: premium rises to 115.0 (+15 pts MFE, Tier 1 breakeven)
    res = test_engine.update_live_monitoring(
        contract_symbol=contract,
        current_ltp=115.0,
        bar_high=115.5,
        bar_low=114.0,
    )

    open_pos = [p for p in test_engine.state.get("openPositions", []) if p.get("contractSymbol") == contract]
    assert len(open_pos) == 1, "Position must remain open (not prematurely closed by shadow mode)"
    pos = open_pos[0]

    # Verify shadow policy evaluation attached
    assert "shadowPolicyG" in pos
    s_eval = pos["shadowPolicyG"]
    assert s_eval["shadowPolicy"] == "HYBRID_G"
    assert s_eval["shadowTier"] == "Tier 1 (Risk-Free Breakeven)"
    assert s_eval["shadowProtectiveStop"] == 100.5
    assert s_eval["observationOnly"] is True

    # Active position SL under existing static governance remains 88.0 (NOT mutated by shadow)
    assert pos["stopLoss"] == 88.0


def test_shadow_monitoring_api_endpoint(client, auth_headers):
    """TASK 5: Verifies the REST API endpoint /profit-protection/shadow-monitoring."""
    response = client.get("/api/paper-trading/profit-protection/shadow-monitoring", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "SUCCESS"
    assert data["operatingMode"] == "OBSERVATION_ONLY"
    assert data["policy"] == "HYBRID_G"
    assert "activeShadowEvaluations" in data
    assert data["executionAuthority"] == "SHADOW_MONITORING_ONLY_NO_LIVE_ORDERS"


def test_validation_verdict_and_governance():
    """TASK 4 & FINAL: Verifies institutional verdict and governance enforcement."""
    summary = IndependentProfitValidator.get_independent_validation_summary()
    assert summary["validationVerdict"] == ValidationVerdict.INSUFFICIENT_EVIDENCE.value
    assert summary["mathematicalAlgorithmStatus"] == "VALIDATED"
    assert summary["empiricalLiveEvidenceStatus"] == "INSUFFICIENT_EVIDENCE"
    assert summary["shadowMonitoringStatus"] == "APPROVED_AND_READY"
    assert summary["governanceChecklist"]["operatingMode"] == "OBSERVATION_ONLY"
    assert summary["governanceChecklist"]["realBrokerOrdersDeployed"] is False


def test_protected_baseline_files_hashes_unchanged():
    """TASK 4: Verifies that protected baseline files remain 100% pristine."""
    expected_hashes = {
        "backend/app/data/paper_trading_records.json": "69c7f386f9a209b3806d33f3cd8d6f89d4150a576abdafa702db77aa365309c8",
        "backend/app/data/daily_post_market_reviews/review_2026-11-19.json": "3229109910faa9ca9642f54e8bc78647e013046d94e73f729a03bf537efcb4b3",
        "backend/app/data/daily_post_market_reviews/review_2026-11-20.json": "f6f8b83888f84325f381c82581bfb0962b6302f6b9f3996333d591445bea631a",
        "aivolve_trading.db": "8870d868aa300a7ebc0c51b5f820d8a7c467e3c33f2634edd1d7329afdff519f",
    }

    for rel_path, expected_hash in expected_hashes.items():
        assert os.path.exists(rel_path), f"Baseline file missing: {rel_path}"
        h = hashlib.sha256()
        with open(rel_path, "rb") as f:
            while chunk := f.read(8192):
                h.update(chunk)
        actual_hash = h.hexdigest()
        assert actual_hash == expected_hash, f"Baseline file {rel_path} was corrupted! Expected {expected_hash}, got {actual_hash}"
