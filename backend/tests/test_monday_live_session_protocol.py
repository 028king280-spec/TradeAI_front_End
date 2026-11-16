"""
Automated Test Suite for Monday Live Session Protocol (Phase 5.2C).

Verifies:
1. Weekend / closed exchange session fail-closed behavior (No live observation outside hours).
2. Independent per-index verification for NIFTY, BANKNIFTY, FINNIFTY.
3. SENSEX governance lock enforcement.
4. Connected but inactive WebSocket rejection (not healthy streaming).
5. Isolated index degradation handling (failing index does not compromise other indices).
6. Non-fabrication invariant (zero synthetic data).
7. Report generation and baseline hash preservation.
"""

import os
import pytest
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from unittest.mock import patch, MagicMock

from app.data.market_calendar import MarketCalendar
from app.data.quality_validator import FeedStatus
from app.options.paper_trading.monday_live_session_protocol import (
    MondayLiveSessionProtocol,
    DEFAULT_REPORT_PATH,
)

IST = ZoneInfo("Asia/Kolkata")


def test_monday_protocol_market_closed_on_weekend():
    """Asserts that outside exchange hours, all indices are marked DATA_OFFLINE / inactive."""
    protocol = MondayLiveSessionProtocol()
    # Saturday 14 Nov 2026 13:40 IST
    saturday_dt = datetime(2026, 11, 14, 13, 40, 0, tzinfo=IST)
    audit = protocol.run_protocol_check(current_dt=saturday_dt)

    assert audit["is_market_open"] is False
    assert audit["is_trading_day"] is False
    assert audit["session_status"] == "CLOSED"
    assert len(audit["active_observing_indices"]) == 0
    assert "SENSEX" in audit["offline_or_locked_indices"]
    assert "NIFTY" in audit["offline_or_locked_indices"]
    assert audit["observations_recorded"] == 0
    assert audit["eligible_records"] == 0


def test_monday_protocol_sensex_strictly_locked():
    """Asserts that SENSEX is unconditionally governance locked."""
    protocol = MondayLiveSessionProtocol()
    statuses = protocol.verify_all_indices_independently()

    sensex_status = statuses.get("SENSEX")
    assert sensex_status is not None
    assert sensex_status.is_governance_locked is True
    assert sensex_status.policy_status == "UNCONFIGURED"
    assert sensex_status.is_observation_active is False
    assert any("GOVERNANCE_LOCKED" in r for r in sensex_status.rejection_reasons)


def test_monday_protocol_inactive_socket_rejection():
    """Asserts that a connected but inactive WebSocket fails data quality gates."""
    protocol = MondayLiveSessionProtocol()
    monday_dt = datetime(2026, 11, 16, 10, 0, 0, tzinfo=IST)

    with patch.object(MarketCalendar, "is_market_open", return_value=True), \
         patch.object(MarketCalendar, "is_trading_day", return_value=True), \
         patch("app.data.providers.angelone_provider.AngelOneMarketDataProvider.is_authenticated", return_value=True), \
         patch("app.data.providers.angelone_websocket.angelone_ws_manager.get_diagnostics", return_value={
             "is_running": True,
             "is_healthy": False,  # Connected but no incoming ticks!
             "ticks_received": 0,
             "seconds_since_last_tick": None,
         }):
        
        statuses = protocol.verify_all_indices_independently(current_dt=monday_dt)
        for sym in ["NIFTY", "BANKNIFTY", "FINNIFTY"]:
            assert statuses[sym].feed_quality_status == FeedStatus.DEGRADED
            assert statuses[sym].is_observation_active is False
            assert any("WebSocket ticks inactive" in r for r in statuses[sym].rejection_reasons)


def test_monday_protocol_independent_index_degradation():
    """Asserts that if one index has missing contracts, other qualifying indices continue."""
    protocol = MondayLiveSessionProtocol()
    monday_dt = datetime(2026, 11, 16, 10, 0, 0, tzinfo=IST)

    # Mock InstrumentMaster where FINNIFTY has 0 expiries but NIFTY & BANKNIFTY have expiries
    mock_im = MagicMock()
    mock_im.is_loaded.return_value = True
    mock_im.get_expiries.side_effect = lambda sym: ["23NOV2026"] if sym in ["NIFTY", "BANKNIFTY"] else []
    mock_im.get_strikes_for_underlying.side_effect = lambda sym: [25000.0] if sym in ["NIFTY", "BANKNIFTY"] else []

    with patch.object(MarketCalendar, "is_market_open", return_value=True), \
         patch.object(MarketCalendar, "is_trading_day", return_value=True), \
         patch("app.data.providers.angelone_provider.AngelOneMarketDataProvider.is_authenticated", return_value=True), \
         patch("app.data.providers.angelone_websocket.angelone_ws_manager.get_diagnostics", return_value={
             "is_running": True,
             "is_healthy": True,
             "ticks_received": 100,
             "seconds_since_last_tick": 1.2,
         }), \
         patch("app.data.instrument_master.InstrumentMaster.get_instance", return_value=mock_im):

        statuses = protocol.verify_all_indices_independently(current_dt=monday_dt)

        assert statuses["NIFTY"].feed_quality_status == FeedStatus.VERIFIED_LIVE
        assert statuses["NIFTY"].is_observation_active is True

        assert statuses["BANKNIFTY"].feed_quality_status == FeedStatus.VERIFIED_LIVE
        assert statuses["BANKNIFTY"].is_observation_active is True

        # FINNIFTY failed due to missing contracts, but did NOT compromise NIFTY or BANKNIFTY!
        assert statuses["FINNIFTY"].feed_quality_status == FeedStatus.DATA_UNAVAILABLE
        assert statuses["FINNIFTY"].is_observation_active is False

        # SENSEX remains locked
        assert statuses["SENSEX"].is_observation_active is False


def test_monday_protocol_report_generation(tmp_path):
    """Asserts that report generates cleanly with verifiable baseline hashes."""
    protocol = MondayLiveSessionProtocol()
    report_file = str(tmp_path / "test_live_report.md")

    content = protocol.generate_live_observation_report(output_path=report_file)
    assert os.path.exists(report_file)
    assert "Phase 5.2C Live Observation Report" in content
    assert "Monday, 16 November 2026" in content
    assert "Actual Live Observations Captured" in content
    assert "STRICTLY PAPER_TRADING_ONLY" in content


def test_monday_protocol_baseline_hashes():
    """Asserts that all six protected baseline files match their immutable SHA-256 hashes."""
    all_match, hash_map = MondayLiveSessionProtocol.audit_protected_baseline_hashes()
    assert all_match is True
    for file_path, status in hash_map.items():
        assert status == "MATCH"

