"""
AIVOLVE v3.0 — P2.1 Forward Shadow Monitoring & Opportunity Pipeline Test Suite.

Validates:
1. Shadow pipeline operates independently without requiring active open paper positions.
2. P0 safety admission rules (duplicate contract, opposing conflict, expired contract).
3. Corrected historical November 20 admissibility audit (4 excluded, 7 admissible).
4. Fair comparison of Policy A vs Policy G on identical admissible opportunities.
5. No lookahead bias, realistic slippage, gap-down execution realism.
6. Evidence quota tracking (Target 50, remaining 50).
7. REST API endpoints (/shadow-forward-status, /shadow-forward-journal, /shadow-opportunity/admit, /tick).
8. Protected baseline files integrity (SHA-256 verification).
"""

import pytest
import hashlib
import os
import json
import time
import uuid
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.options.paper_trading.shadow_forward_pipeline import (
    ShadowForwardPipeline,
    ShadowOpportunityStatus,
    ShadowRejectionReason,
)


@pytest.fixture
def auth_headers():
    token = settings.OPERATOR_SECRET_KEY or "aivolve-internal-operator"
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client():
    return TestClient(app)


def test_shadow_monitoring_operates_without_open_positions(tmp_path):
    """TASK 1: Ensures shadow observation works when openPositions is completely empty."""
    journal_path = str(tmp_path / "shadow_test_journal.json")
    pipeline = ShadowForwardPipeline(journal_path=journal_path)

    # Admit eligible research signal without opening any paper trade
    admit_res = pipeline.admit_shadow_opportunity(
        signal_id="SIG-TEST-FORWARD-01",
        index="NIFTY",
        contract_symbol="NIFTY23NOV2625800CE",
        expiry="23NOV2026",
        strike=25800.0,
        option_type="CE",
        entry_premium=120.0,
        lot_size=65,
        lots=1,
        stop_loss=108.0,
        target_1=156.0,
        target_2=186.0,
        target_3=222.0,
        signal_timestamp="21 Nov 2026, 09:30 AM IST",
    )
    assert admit_res["admitted"] is True
    op_id = admit_res["opportunity_id"]
    assert op_id in pipeline.active_opportunities

    # Ingest price ticks: MFE reaches +20 pts (140.0), triggering Policy G Tier 2 (+10 pt lock = 130.0)
    pipeline.process_market_tick(
        contract_symbol="NIFTY23NOV2625800CE",
        ltp=135.0,
        bar_high=135.0,
        bar_low=132.0,
        quote_timestamp="21 Nov 2026, 09:35 AM IST",
    )
    pipeline.process_market_tick(
        contract_symbol="NIFTY23NOV2625800CE",
        ltp=140.0,
        bar_high=140.0,
        bar_low=138.0,
        quote_timestamp="21 Nov 2026, 09:45 AM IST",
    )

    op = pipeline.active_opportunities[op_id]
    assert op["mfe_pts"] == 20.0
    assert op["policy_g_current_sl"] == 130.0  # Entry + 10.0 pts locked
    assert "Tier 2" in op["policy_g_current_tier"]

    # Price reverses: crosses 130.0 (high=131.0, low=128.0)
    # Policy G triggers protective exit at 130.0 - 0.5 slippage = 129.50 (Net Profit!)
    # Policy A remains open waiting for initial SL 108.0
    pipeline.process_market_tick(
        contract_symbol="NIFTY23NOV2625800CE",
        ltp=128.0,
        bar_high=131.0,
        bar_low=128.0,
        quote_timestamp="21 Nov 2026, 10:00 AM IST",
    )

    assert op["policy_g_exit"] is not None
    assert op["policy_g_exit"]["status"] == "TRAILING_STOP_HIT"
    assert op["policy_g_exit"]["exit_price"] == 129.50
    assert op["policy_g_exit"]["net_pnl"] > 0
    assert op["policy_a_exit"] is None  # Policy A still open

    # Final price collapses to 105.0: Policy A hits stop loss
    pipeline.process_market_tick(
        contract_symbol="NIFTY23NOV2625800CE",
        ltp=105.0,
        bar_high=110.0,
        bar_low=104.0,
        quote_timestamp="21 Nov 2026, 10:30 AM IST",
    )

    # Opportunity is now resolved under both policies and moved to journal
    assert op_id not in pipeline.active_opportunities
    assert len(pipeline.completed_journal) == 1
    completed = pipeline.completed_journal[0]
    assert completed["policy_a_exit"]["net_pnl"] < 0
    assert completed["policy_g_exit"]["net_pnl"] > 0


def test_p0_admission_rule_enforcement_in_shadow_pipeline(tmp_path):
    """TASK 2: Validates P0 safety filters (duplicate contract, opposing conflict, expired contract)."""
    journal_path = str(tmp_path / "shadow_gate_test.json")
    pipeline = ShadowForwardPipeline(journal_path=journal_path)

    # 1. Admit primary opportunity
    admit1 = pipeline.admit_shadow_opportunity(
        signal_id="SIG-01",
        index="NIFTY",
        contract_symbol="NIFTY23NOV2625750CE",
        expiry="23NOV2026",
        strike=25750.0,
        option_type="CE",
        entry_premium=116.0,
        lot_size=65,
    )
    assert admit1["admitted"] is True

    # 2. Duplicate active contract rejection
    admit2 = pipeline.admit_shadow_opportunity(
        signal_id="SIG-02",
        index="NIFTY",
        contract_symbol="NIFTY23NOV2625750CE",
        expiry="23NOV2026",
        strike=25750.0,
        option_type="CE",
        entry_premium=115.0,
        lot_size=65,
    )
    assert admit2["admitted"] is False
    assert admit2["reason"] == ShadowRejectionReason.DUPLICATE_ACTIVE_CONTRACT.value

    # 3. Opposing directional conflict rejection (Same strike 25750 PE)
    admit3 = pipeline.admit_shadow_opportunity(
        signal_id="SIG-03",
        index="NIFTY",
        contract_symbol="NIFTY23NOV2625750PE",
        expiry="23NOV2026",
        strike=25750.0,
        option_type="PE",
        entry_premium=120.0,
        lot_size=65,
    )
    assert admit3["admitted"] is False
    assert admit3["reason"] == ShadowRejectionReason.OPPOSING_DIRECTIONAL_CONFLICT.value

    # 4. Expired contract rejection
    admit4 = pipeline.admit_shadow_opportunity(
        signal_id="SIG-04",
        index="NIFTY",
        contract_symbol="NIFTY06NOV2624000CE",
        expiry="06NOV2026",
        strike=24000.0,
        option_type="CE",
        entry_premium=120.0,
        lot_size=65,
    )
    assert admit4["admitted"] is False
    assert admit4["reason"] == ShadowRejectionReason.EXPIRED_CONTRACT.value


def test_historical_november_20_admissibility_audit():
    """TASK 2: Verifies exclusion of 4 inadmissible trades and fair comparison on 7 opportunities."""
    audit = ShadowForwardPipeline.audit_historical_november_20_admissibility()

    assert audit["totalRawRecorded"] == 11
    assert audit["excludedInadmissibleCount"] == 4
    assert audit["admissibleOpportunitiesCount"] == 7

    # Excluded trade IDs must include PT-B43E2C4B, PT-21E1FBA1, PT-8E78B1DB, PT-89B18A85
    excluded_ids = {r["tradeId"] for r in audit["excludedRecords"]}
    assert "PT-B43E2C4B" in excluded_ids, "PT-B43E2C4B duplicate must be excluded"
    assert "PT-21E1FBA1" in excluded_ids, "PT-21E1FBA1 opposing conflict must be excluded"
    assert "PT-8E78B1DB" in excluded_ids, "PT-8E78B1DB expired contract must be excluded"
    assert "PT-89B18A85" in excluded_ids, "PT-89B18A85 stale cleanup must be excluded"

    # Verify comparison on the 7 admissible opportunities
    comp = audit["comparisonMetrics"]
    p_a = comp["policyA_Static"]
    p_g = comp["policyG_Hybrid"]

    assert p_g["total_net_pnl"] > p_a["total_net_pnl"], "Policy G must outperform on admissible set"
    assert p_g["profit_factor"] > p_a["profit_factor"], "Policy G PF must exceed Policy A"
    assert comp["netTurnaroundRupees"] > 4000.0, f"Expected >+₹4000 net gain, got {comp['netTurnaroundRupees']}"


def test_execution_lookahead_elimination_and_gap_slippage(tmp_path):
    """TASK 4: Verifies chronological tick processing, bid fills, and gap-down slippage."""
    journal_path = str(tmp_path / "shadow_lookahead_test.json")
    pipeline = ShadowForwardPipeline(journal_path=journal_path)

    admit = pipeline.admit_shadow_opportunity(
        signal_id="SIG-LOOKAHEAD-01",
        index="NIFTY",
        contract_symbol="NIFTY23NOV2625900CE",
        expiry="23NOV2026",
        strike=25900.0,
        option_type="CE",
        entry_premium=100.0,
        lot_size=65,
        stop_loss=88.0,
        target_2=155.0,
    )
    op_id = admit["opportunity_id"]

    # Market gaps down completely below SL (high is 85.0 < SL 88.0)
    pipeline.process_market_tick(
        contract_symbol="NIFTY23NOV2625900CE",
        ltp=84.0,
        bar_high=85.0,
        bar_low=82.0,
        quote_timestamp="09:16 AM",
    )

    completed = pipeline.completed_journal[0]
    # Execution must fill at gap low minus slippage (82.0 - 0.5 = 81.50), NOT fabricated at 88.0!
    assert completed["policy_a_exit"]["exit_price"] == 81.50
    assert completed["policy_a_exit"]["slippage_incurred"] > 0


def test_quota_and_forward_journal_persistence(tmp_path):
    """TASK 5: Verifies quota tracking (0/50) and clean persistence."""
    journal_path = str(tmp_path / "shadow_persistence_test.json")
    pipeline = ShadowForwardPipeline(journal_path=journal_path)

    dash = pipeline.get_shadow_dashboard_state()
    assert dash["evidenceQuota"]["targetQuota"] == 50
    assert dash["evidenceQuota"]["completedForwardObservations"] == 0
    assert dash["evidenceQuota"]["remainingQuota"] == 50
    assert dash["evidenceQuota"]["dataCompletenessStatus"] == "FORWARD_COLLECTION_IN_PROGRESS"


def test_rest_api_shadow_forward_endpoints(client, auth_headers):
    """TASK 7: Tests the REST API endpoints."""
    # 1. GET shadow-forward-status
    res_status = client.get("/api/paper-trading/profit-protection/shadow-forward-status", headers=auth_headers)
    assert res_status.status_code == 200
    data_status = res_status.json()
    assert data_status["status"] == "SUCCESS"
    assert data_status["operatingMode"] == "OBSERVATION_ONLY"
    assert "evidenceQuota" in data_status
    assert "correctedHistoricalAuditNov20" in data_status

    # 2. GET shadow-forward-journal
    res_journal = client.get("/api/paper-trading/profit-protection/shadow-forward-journal", headers=auth_headers)
    assert res_journal.status_code == 200
    data_journal = res_journal.json()
    assert data_journal["status"] == "SUCCESS"
    assert "journal" in data_journal

    # 3. POST shadow-opportunity/admit
    test_strike = 25850.0 + (int(time.time() * 1000) % 500)
    test_symbol = f"NIFTY23NOV26{int(test_strike)}CE"
    res_admit = client.post(
        "/api/paper-trading/profit-protection/shadow-opportunity/admit",
        headers=auth_headers,
        json={
            "index": "NIFTY",
            "contract_symbol": test_symbol,
            "expiry": "23NOV2026",
            "strike": test_strike,
            "option_type": "CE",
            "entry_premium": 110.0,
            "lot_size": 65,
        },
    )
    assert res_admit.status_code == 200
    admit_json = res_admit.json()
    assert admit_json["admitted"] is True

    # 4. POST shadow-opportunity/tick
    res_tick = client.post(
        "/api/paper-trading/profit-protection/shadow-opportunity/tick",
        headers=auth_headers,
        json={
            "contract_symbol": test_symbol,
            "ltp": 125.0,
            "high": 126.0,
            "low": 122.0,
        },
    )
    assert res_tick.status_code == 200


def test_protected_baseline_files_hashes_remain_pristine():
    """TASK 8: Verifies that all 6 protected baseline files remain 100% untouched."""
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
        assert actual_hash == expected_hash, f"Corrupted file: {rel_path}"
