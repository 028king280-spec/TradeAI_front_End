"""
AIVOLVE v3.0 — Phase 6 Macro/Event Intelligence Automated Test Suite (REQ-6.12)
Validates Foundation Components:
- REQ-6.1: Event data models and policy invariants
- REQ-6.2: Versioned calendar store and institutional provenance
- REQ-6.3: Deterministic proximity calculation engine
- REQ-6.7: Hardened overnight drift and GIFT Nifty provenance
- Policy Governance: Strict assertion that unapproved thresholds remain GOVERNANCE_PENDING
- Invariant: Byte-for-byte SHA-256 match for all 6 protected baseline files
"""

import hashlib
import zoneinfo
from datetime import datetime, timezone, timedelta
from pathlib import Path
import pytest

from app.options.macro.macro_models import (
    MacroEventTier,
    EventScheduleType,
    EventLiveStatus,
    CalendarSourceType,
    ThresholdPolicyStatus,
    ProximityBand,
    MacroEventSource,
    MacroEvent,
    ProximityAssessment,
)
from app.options.macro.macro_calendar_store import MacroCalendarStore
from app.options.macro.macro_proximity_engine import MacroProximityEngine
from app.options.opening_outlook import calculate_next_session_opening_outlook

IST = zoneinfo.ZoneInfo("Asia/Kolkata")
EDT = zoneinfo.ZoneInfo("America/New_York")


# ==============================================================================
# 1. REQ-6.1: Model Instantiation, Timezone Awareness & Safety Invariants
# ==============================================================================

def test_macro_models_instantiation_and_serialization():
    source = MacroEventSource(
        authority="Reserve Bank of India",
        source_type=CalendarSourceType.RBI_OFFICIAL,
        reference_url="https://www.rbi.org.in/",
        verified_at="2026-01-05T10:00:00+05:30"
    )

    sched_time = datetime(2026, 2, 6, 10, 0, tzinfo=IST)
    event = MacroEvent(
        event_id="TEST-RBI-01",
        name="RBI MPC Decision",
        tier=MacroEventTier.TIER_1_CRITICAL,
        scheduled_time=sched_time,
        source=source,
        schedule_type=EventScheduleType.CONFIRMED,
        live_status=EventLiveStatus.SCHEDULED,
        affected_indices=["NIFTY 50", "BANK NIFTY"],
    )

    assert event.event_id == "TEST-RBI-01"
    assert event.tier == MacroEventTier.TIER_1_CRITICAL
    assert event.scheduled_time_ist().hour == 10
    assert event.scheduled_time_ist().minute == 0

    d = event.to_dict()
    assert d["eventId"] == "TEST-RBI-01"
    assert d["tier"] == "TIER_1_CRITICAL"
    assert d["source"]["sourceType"] == "RBI_OFFICIAL"
    assert "NIFTY 50" in d["affectedIndices"]


def test_macro_models_rejects_naive_timestamp():
    source = MacroEventSource(
        authority="Reserve Bank of India",
        source_type=CalendarSourceType.RBI_OFFICIAL
    )

    with pytest.raises(ValueError, match="scheduled_time must be timezone-aware"):
        MacroEvent(
            event_id="TEST-NAIVE",
            name="Naive Event",
            tier=MacroEventTier.TIER_2_HIGH,
            scheduled_time=datetime(2026, 2, 6, 10, 0),  # Naive (no tzinfo)
            source=source
        )


def test_macro_models_policy_governance_invariants():
    """
    CRITICAL POLICY INVARIANT:
    Unless policy_status == APPROVED, trading_override_active is forced False
    and position_scaling_factor is forced 1.0.
    """
    source = MacroEventSource(authority="Test", source_type=CalendarSourceType.MANUAL_UNVERIFIED)
    event = MacroEvent(
        event_id="TEST-GOV",
        name="Test Policy Event",
        tier=MacroEventTier.TIER_1_CRITICAL,
        scheduled_time=datetime(2026, 2, 6, 10, 0, tzinfo=IST),
        source=source
    )

    # Attempt to illegally arm trading override with GOVERNANCE_PENDING status
    assessment = ProximityAssessment(
        event=event,
        as_of_time=datetime(2026, 2, 6, 9, 55, tzinfo=IST),
        minutes_to_event=5.0,
        proximity_band=ProximityBand.EVENT_IMMINENT_BLACKOUT,
        policy_status=ThresholdPolicyStatus.GOVERNANCE_PENDING,
        trading_override_active=True,         # Attempted override
        position_scaling_factor=0.5,           # Attempted scaling
    )

    # Invariant validator must disarm these fields
    assert assessment.trading_override_active is False
    assert assessment.position_scaling_factor == 1.0
    assert assessment.policy_status == ThresholdPolicyStatus.GOVERNANCE_PENDING


# ==============================================================================
# 2. REQ-6.2: Versioned Calendar Store & Institutional Provenance
# ==============================================================================

def test_macro_calendar_store_loading_and_provenance():
    store = MacroCalendarStore()
    events = store.get_all_events()

    assert len(events) >= 20, f"Expected at least 20 vetted events, got {len(events)}"

    stats = store.get_calendar_stats()
    assert stats["confirmedEvents"] >= 15
    assert stats["policyStatus"] == "GOVERNANCE_PENDING"

    # Verify RBI events have RBI_OFFICIAL source
    rbi_events = [e for e in events if "RBI" in e.event_id]
    assert len(rbi_events) >= 6
    for e in rbi_events:
        assert e.source.source_type == CalendarSourceType.RBI_OFFICIAL
        assert e.tier == MacroEventTier.TIER_1_CRITICAL
        assert e.schedule_type == EventScheduleType.CONFIRMED

    # Verify Budget 2027 is flagged as TENTATIVE
    budget_event = store.get_event_by_id("DOM-BUDGET-2027")
    assert budget_event is not None
    assert budget_event.schedule_type == EventScheduleType.TENTATIVE
    assert budget_event.source.source_type == CalendarSourceType.GOVT_GAZETTE


def test_macro_calendar_timezone_normalization():
    store = MacroCalendarStore()
    
    # FOMC rate decision is published at 14:00 EDT (America/New_York)
    # On 2026-03-18 (EDT is UTC-4): 14:00 EDT = 18:00 UTC = 23:30 IST (+05:30)
    fomc_mar = store.get_event_by_id("GLB-US-FOMC-2603")
    assert fomc_mar is not None
    assert fomc_mar.source.source_type == CalendarSourceType.FED_OFFICIAL
    
    ist_time = fomc_mar.scheduled_time_ist()
    assert ist_time.hour == 23
    assert ist_time.minute == 30
    assert ist_time.day == 18
    assert ist_time.month == 3


def test_macro_calendar_querying_and_filtering():
    store = MacroCalendarStore()

    # Query events in February 2026
    start_feb = datetime(2026, 2, 1, 0, 0, tzinfo=IST)
    end_feb = datetime(2026, 2, 28, 23, 59, tzinfo=IST)

    feb_events = store.get_events(start_time=start_feb, end_time=end_feb)
    assert len(feb_events) >= 3  # RBI MPC, CPI Jan, GDP Q3

    # Filter by Tier 1 only
    t1_events = store.get_events(start_time=start_feb, end_time=end_feb, tier=MacroEventTier.TIER_1_CRITICAL)
    assert all(e.tier == MacroEventTier.TIER_1_CRITICAL for e in t1_events)
    assert any("RBI" in e.event_id for e in t1_events)

    # Filter by index
    nifty_events = store.get_events(start_time=start_feb, end_time=end_feb, index="NIFTY 50")
    assert len(nifty_events) == len(feb_events)


# ==============================================================================
# 3. REQ-6.3: Deterministic Event Proximity Engine
# ==============================================================================

def test_macro_proximity_engine_math():
    store = MacroCalendarStore()
    engine = MacroProximityEngine(store)

    event = store.get_event_by_id("DOM-RBI-MPC-2602")
    assert event is not None
    # Scheduled for 2026-02-06 10:00:00 IST

    # Case 1: T-75 minutes (08:45 IST) -> PRE_EVENT_WATCH / DISTANT (>60m)
    as_of_t_minus_75 = datetime(2026, 2, 6, 8, 45, tzinfo=IST)
    a1 = engine.assess_event(event, as_of_t_minus_75)
    assert a1.minutes_to_event == 75.0
    assert a1.proximity_band == ProximityBand.PRE_EVENT_WATCH
    assert a1.is_blackout_proposed is False
    assert a1.is_warning_proposed is False

    # Case 2: T-30 minutes (09:30 IST) -> PRE_EVENT_WARNING (15m < dt <= 60m)
    as_of_t_minus_30 = datetime(2026, 2, 6, 9, 30, tzinfo=IST)
    a2 = engine.assess_event(event, as_of_t_minus_30)
    assert a2.minutes_to_event == 30.0
    assert a2.proximity_band == ProximityBand.PRE_EVENT_WARNING
    assert a2.is_warning_proposed is True
    assert a2.is_blackout_proposed is False

    # Case 3: T-5 minutes (09:55 IST) -> EVENT_IMMINENT_BLACKOUT (-15m <= dt <= 15m)
    as_of_t_minus_5 = datetime(2026, 2, 6, 9, 55, tzinfo=IST)
    a3 = engine.assess_event(event, as_of_t_minus_5)
    assert a3.minutes_to_event == 5.0
    assert a3.proximity_band == ProximityBand.EVENT_IMMINENT_BLACKOUT
    assert a3.is_blackout_proposed is True

    # Case 4: T = 0 (10:00 IST exact event release) -> EVENT_IMMINENT_BLACKOUT
    as_of_t_zero = datetime(2026, 2, 6, 10, 0, tzinfo=IST)
    a4 = engine.assess_event(event, as_of_t_zero)
    assert a4.minutes_to_event == 0.0
    assert a4.proximity_band == ProximityBand.EVENT_IMMINENT_BLACKOUT
    assert a4.is_blackout_proposed is True

    # Case 5: T+10 minutes (10:10 IST) -> Still inside ±15m window -> EVENT_IMMINENT_BLACKOUT
    as_of_t_plus_10 = datetime(2026, 2, 6, 10, 10, tzinfo=IST)
    a5 = engine.assess_event(event, as_of_t_plus_10)
    assert a5.minutes_to_event == -10.0
    assert a5.proximity_band == ProximityBand.EVENT_IMMINENT_BLACKOUT
    assert a5.is_blackout_proposed is True

    # Case 6: T+30 minutes (10:30 IST) -> POST_EVENT_REALIGNMENT (-60m <= dt < -15m)
    as_of_t_plus_30 = datetime(2026, 2, 6, 10, 30, tzinfo=IST)
    a6 = engine.assess_event(event, as_of_t_plus_30)
    assert a6.minutes_to_event == -30.0
    assert a6.proximity_band == ProximityBand.POST_EVENT_REALIGNMENT
    assert a6.is_blackout_proposed is False

    # Case 7: T+90 minutes (11:30 IST) -> DISTANT
    as_of_t_plus_90 = datetime(2026, 2, 6, 11, 30, tzinfo=IST)
    a7 = engine.assess_event(event, as_of_t_plus_90)
    assert a7.minutes_to_event == -90.0
    assert a7.proximity_band == ProximityBand.DISTANT


def test_macro_proximity_engine_governance_safeguards():
    """
    Confirms that evaluate_proximity NEVER alters trading state and keeps
    tradingOverrideActive False and positionScalingFactor 1.0 even during blackout window.
    """
    store = MacroCalendarStore()
    engine = MacroProximityEngine(store)

    # Evaluate right inside the blackout window of RBI MPC
    as_of_blackout = datetime(2026, 2, 6, 9, 58, tzinfo=IST)
    result = engine.evaluate_proximity(as_of=as_of_blackout, index="NIFTY 50")

    assert result["activeProximityBand"] == "EVENT_IMMINENT_BLACKOUT"
    assert result["diagnostics"]["hasProposedBlackout"] is True
    assert result["policyStatus"] == "GOVERNANCE_PENDING"

    # MANDATORY GOVERNANCE ASSERTIONS:
    assert result["governanceGuards"]["tradingOverrideActive"] is False
    assert result["governanceGuards"]["positionScalingFactor"] == 1.0
    assert result["governanceGuards"]["policyApprovalRequired"] is True


# ==============================================================================
# 4. REQ-6.7: Overnight Drift & GIFT Nifty Provenance Hardening
# ==============================================================================

def test_opening_outlook_gift_nifty_unavailable_provenance():
    """
    REQ-6.7: When GIFT Nifty feed is offline / missing, verify:
    - driftSource is explicitly GIFT_NIFTY_UNAVAILABLE
    - isLiveGiftNifty is False
    - evidence does NOT claim GIFT Nifty was observed
    """
    outlook = calculate_next_session_opening_outlook(
        symbol="NIFTY 50",
        previous_close=24800.0,
        daily_high=24880.0,
        daily_low=24720.0,
        daily_open=24750.0,
        atr_14=110.0,
        vix_value=13.0,
        gift_nifty_drift_points=None  # Feed unavailable
    )

    assert "driftProvenance" in outlook
    prov = outlook["driftProvenance"]
    assert prov["driftSource"] == "GIFT_NIFTY_UNAVAILABLE"
    assert prov["driftStatus"] == "ESTIMATED_MOMENTUM_FALLBACK"
    assert prov["isLiveGiftNifty"] is False
    assert prov["giftNiftyDriftPoints"] is None

    assert outlook["estimatedGap"]["driftSource"] == "GIFT_NIFTY_UNAVAILABLE"

    # Check evidence statement
    evidence_text = " ".join(outlook["supportingEvidence"])
    assert "GIFT Nifty feed UNAVAILABLE" in evidence_text
    assert "technical estimate" in evidence_text


def test_opening_outlook_gift_nifty_live_provenance():
    """
    REQ-6.7: When GIFT Nifty feed is provided, verify:
    - driftSource is GIFT_NIFTY_LIVE
    - isLiveGiftNifty is True
    - evidence acknowledges live GIFT Nifty observation
    """
    outlook = calculate_next_session_opening_outlook(
        symbol="NIFTY 50",
        previous_close=24800.0,
        daily_high=24880.0,
        daily_low=24720.0,
        daily_open=24750.0,
        atr_14=110.0,
        vix_value=13.0,
        gift_nifty_drift_points=55.0  # Live tick provided
    )

    assert "driftProvenance" in outlook
    prov = outlook["driftProvenance"]
    assert prov["driftSource"] == "GIFT_NIFTY_LIVE"
    assert prov["driftStatus"] == "OBSERVED"
    assert prov["isLiveGiftNifty"] is True
    assert prov["giftNiftyDriftPoints"] == 55.0

    assert outlook["estimatedGap"]["driftSource"] == "GIFT_NIFTY_LIVE"

    evidence_text = " ".join(outlook["supportingEvidence"])
    assert "GIFT Nifty live tick" in evidence_text


# ==============================================================================
# 5. REQ-6.8: Feed Adapter Architecture & Anti-Fabrication Safeguards
# ==============================================================================

@pytest.mark.asyncio
async def test_macro_feed_adapter_fail_closed_without_credentials():
    """
    REQ-6.8: Without external API credentials, verify adapter fails closed:
    - Never fabricates synthetic events
    - Returns empty list
    - Reports CREDENTIALS_UNCONFIGURED
    """
    from app.options.macro.macro_feed_adapter import ExternalMacroFeedAdapter

    adapter = ExternalMacroFeedAdapter(
        provider_name="TEST_FEED",
        api_key=None,  # No credentials
        base_url=None
    )

    assert adapter.is_configured is False
    
    start_time = datetime(2026, 2, 1, 0, 0, tzinfo=IST)
    end_time = datetime(2026, 2, 28, 23, 59, tzinfo=IST)
    
    # Must return empty list, zero fake records
    events = await adapter.fetch_events(start_time, end_time)
    assert events == []

    # Connection check returns DATA_OFFLINE / CREDENTIALS_UNCONFIGURED
    conn = await adapter.check_connection()
    assert conn["status"] == "DATA_OFFLINE"
    assert conn["credentialsStatus"] == "CREDENTIALS_UNCONFIGURED"
    assert conn["isLive"] is False


def test_macro_feed_adapter_status_reporting():
    from app.options.macro.macro_feed_adapter import get_macro_feed_adapter

    adapter = get_macro_feed_adapter()
    status_info = adapter.get_adapter_status()

    assert "provider" in status_info
    assert "failClosedPolicy" in status_info
    assert "Zero synthetic events" in status_info["failClosedPolicy"]


# ==============================================================================
# 6. REQ-6.11: FastAPI Endpoints & Integration Verification
# ==============================================================================

def test_api_macro_calendar_endpoint():
    """
    REQ-6.11: GET /api/macro/calendar returns valid envelope and all 28 events.
    """
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    response = client.get("/api/macro/calendar")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["dataStatus"] == "LIVE"
    assert "events" in data["data"]
    assert "stats" in data["data"]
    assert "governancePolicy" in data["data"]
    assert data["data"]["count"] >= 20
    assert len(data["data"]["events"]) == data["data"]["count"]


def test_api_macro_calendar_filtering():
    """
    REQ-6.11: GET /api/macro/calendar with tier and index filters.
    """
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)

    # Filter Tier 1 Critical only
    res = client.get("/api/macro/calendar?tier=TIER_1_CRITICAL")
    assert res.status_code == 200
    data = res.json()["data"]
    assert all(e["tier"] == "TIER_1_CRITICAL" for e in data["events"])

    # Invalid tier returns 400
    res_bad = client.get("/api/macro/calendar?tier=INVALID_TIER")
    assert res_bad.status_code == 400


def test_api_macro_proximity_endpoint():
    """
    REQ-6.11: GET /api/macro/proximity evaluates proximity and enforces policy guards.
    """
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    res = client.get("/api/macro/proximity?index=NIFTY%2050")

    assert res.status_code == 200
    data = res.json()["data"]
    assert "activeProximityBand" in data
    assert "governanceGuards" in data
    assert "diagnostics" in data

    # STRICT POLICY SAFEGUARD ASSERTIONS
    assert data["governanceGuards"]["tradingOverrideActive"] is False
    assert data["governanceGuards"]["positionScalingFactor"] == 1.0
    assert data["governanceGuards"]["policyApprovalRequired"] is True


def test_api_macro_event_by_id_endpoint():
    """
    REQ-6.11: GET /api/macro/events/{event_id} returns event detail or 404.
    """
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)

    # Valid event
    res = client.get("/api/macro/events/DOM-RBI-MPC-2602")
    assert res.status_code == 200
    ev = res.json()["data"]
    assert ev["eventId"] == "DOM-RBI-MPC-2602"
    assert ev["tier"] == "TIER_1_CRITICAL"

    # Missing event returns 404
    res_404 = client.get("/api/macro/events/NON_EXISTENT_EVENT_XYZ")
    assert res_404.status_code == 404


def test_api_macro_feed_status_endpoint():
    """
    REQ-6.11: GET /api/macro/feed-status reports adapter configuration.
    """
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    res = client.get("/api/macro/feed-status")

    assert res.status_code == 200
    data = res.json()["data"]
    assert "connection" in data
    assert "adapter" in data
    assert data["connection"]["credentialsStatus"] in ["CREDENTIALS_UNCONFIGURED", "AUTHENTICATED"]


# ==============================================================================
# 7. Protected Baseline Hash Verification
# ==============================================================================

PROTECTED_HASHES = {
    "aivolve_trading.db": "C85C49BE76DEE40557C4B9AAF308B4E3BEACA03CD4B1CD1CE90D051566EABF44",
    "app/data/governance_ledger.db": "4B12B3BAB44BF913F15174278B346FA321D5C473272E40F8B7E6E2350034488E",
    "app/data/paper_trading_records.json": "00F968EF85095EB7C1DE336A1780F9EDE417426A253AC531446BEF1117DA0298",
    "app/data/ml_trade_dataset.json": "87EEA8802835BB4F5A0AD1D598F2CEC561C6D5237F123B8B57CD79BBBE2E6445",
    "app/data/what_ai_learned.json": "3ED015726DFF309000EEC473AB660F34E3BD4EFAEDCBE183B14D62C572E5CCC5",
    "app/data/ml_strategy_weights.json": "C3C495F36214BD7FA58DDCA3C7F0280C14E15EB08DF41F868704F724C2A4E2FC",
}


def test_protected_baseline_hashes_unmodified():
    base_dir = Path(__file__).resolve().parent.parent
    for rel_path, expected_hash in PROTECTED_HASHES.items():
        file_path = base_dir / rel_path
        assert file_path.exists(), f"Protected file missing: {file_path}"

        hasher = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                hasher.update(chunk)
        actual_hash = hasher.hexdigest().upper()

        assert actual_hash == expected_hash, (
            f"CRITICAL INVARIANT VIOLATION: Hash mismatch for {rel_path}!\n"
            f"Expected: {expected_hash}\n"
            f"Actual:   {actual_hash}"
        )

