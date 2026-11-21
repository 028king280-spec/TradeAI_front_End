"""
Unit and Integration Test Suite for Late Session Entry Cutoff & Automatic Exit Safety Audit.
Validates:
1. Entry admission before cutoff (14:40:00 IST) succeeds.
2. Entry admission immediately before cutoff (14:49:59 IST) succeeds.
3. Entry admission at cutoff (14:50:00 IST) is rejected with INSUFFICIENT_HOLDING_TIME_BEFORE_EOD_SQUAREOFF.
4. Entry admission after cutoff (15:09:23 IST) is rejected with INSUFFICIENT_HOLDING_TIME_BEFORE_EOD_SQUAREOFF.
5. Replay / simulation bypass (allowAfterHoursSimulation / isReplay) permits sandbox evaluation.
6. Stop-loss remains 100% armed and active; triggers without delay on adverse tick.
7. Target 1 behavior cleanly distinguishes multi-lot partial booking (50%) vs single-lot breakeven trailing.
8. Non-fabricated fills and separation of lastVerifiedQuoteTimestamp, fillTimestamp, and ledgerCleanupTimestamp.
9. Automatic EOD square-off triggers properly at/after 15:10 IST with EOD_SQUARE_OFF status (not MANUALLY_CLOSED).
10. Configurable session cutoff settings via configure_session_cutoff.
11. Pristine SHA-256 baseline file integrity preservation.
"""

import os
import json
import hashlib
import tempfile
import pytest
from datetime import datetime, timezone, timedelta

from app.options.paper_trading.paper_engine import PaperTradingEngine
from app.data.market_calendar import MarketCalendar

# Baseline file hashes that MUST remain unmodified
PROTECTED_BASELINE_HASHES = {
    "backend/app/data/paper_trading_records.json": "69c7f386f9a209b3806d33f3cd8d6f89d4150a576abdafa702db77aa365309c8",
    "backend/app/data/daily_post_market_reviews/review_2026-11-19.json": "3229109910faa9ca9642f54e8bc78647e013046d94e73f729a03bf537efcb4b3",
    "backend/app/data/daily_post_market_reviews/review_2026-11-20.json": "f6f8b83888f84325f381c82581bfb0962b6302f6b9f3996333d591445bea631a",
    "aivolve_trading.db": "8870d868aa300a7ebc0c51b5f820d8a7c467e3c33f2634edd1d7329afdff519f",
}


@pytest.fixture
def temp_engine():
    """Provides an isolated PaperTradingEngine backed by a temporary file."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        temp_path = f.name
    
    init_state = {
        "balance": 100000.0,
        "startingBalance": 100000.0,
        "openPositions": [],
        "closedTrades": [],
        "winCount": 0,
        "lossCount": 0,
        "totalRealizedGrossPnl": 0.0,
        "totalRealizedNetPnl": 0.0,
        "totalTradingCosts": 0.0,
        "stateVersion": 1,
    }
    with open(temp_path, "w") as f:
        json.dump(init_state, f)
    
    engine = PaperTradingEngine(storage_path=temp_path)
    # Ensure default session cutoff configuration
    engine.configure_session_cutoff(
        enabled=True,
        min_holding_window_minutes=20.0,
        eod_square_off_time="15:10",
        enforce_eod_squareoff=True,
    )
    yield engine
    
    if os.path.exists(temp_path):
        os.remove(temp_path)
    lock_file = f"{temp_path}.lock"
    if os.path.exists(lock_file):
        os.remove(lock_file)


class TestLateSessionEntryCutoff:
    """Tests for late session entry cutoff rules and EOD square-off schedule."""

    def test_cutoff_math_defaults(self, temp_engine):
        """Verifies cutoff calculation with default 15:10 EOD square-off and 20m window -> 14:50 IST."""
        status = temp_engine.get_session_cutoff_status(datetime(2026, 11, 20, 14, 30, 0))
        assert status["cutoffTime"] == "14:50 IST"
        assert status["eodSquareOffTime"] == "15:10 IST"
        assert status["minHoldingWindowMinutes"] == 20.0
        assert status["isAdmissible"] is True
        assert status["isPastCutoff"] is False
        assert status["isPastEodSquareOff"] is False

    def test_entry_before_cutoff_admitted(self, temp_engine, monkeypatch):
        """14:40 IST: Well before cutoff, entry must be permitted."""
        monkeypatch.setattr(MarketCalendar, "is_market_open", lambda: True)
        res = temp_engine.open_position(
            instrument="NIFTY 50",
            contract_symbol="NIFTY23NOV2625800CE",
            bias="CE",
            strike=25800,
            expiry="23NOV2026",
            entry_premium=113.50,
            lots=1,
            lot_size=65,
            stop_loss=102.30,
            target_1=150.60,
            target_2=173.20,
            market_features={
                "evalTimestamp": "2026-11-20 14:40:00",
                "isTradeQualified": True,
                "dataStatus": "VERIFIED_LIVE",
            },
        )
        assert res["success"] is True
        assert res["position"]["contractSymbol"] == "NIFTY23NOV2625800CE"

    def test_entry_immediately_before_cutoff_admitted(self, temp_engine, monkeypatch):
        """14:49:59 IST: Right before cutoff, entry must be permitted."""
        monkeypatch.setattr(MarketCalendar, "is_market_open", lambda: True)
        res = temp_engine.open_position(
            instrument="NIFTY 50",
            contract_symbol="NIFTY23NOV2625800CE",
            bias="CE",
            strike=25800,
            expiry="23NOV2026",
            entry_premium=113.50,
            lots=1,
            lot_size=65,
            stop_loss=102.30,
            target_1=150.60,
            target_2=173.20,
            market_features={
                "evalTimestamp": "2026-11-20 14:49:59",
                "isTradeQualified": True,
                "dataStatus": "VERIFIED_LIVE",
            },
        )
        assert res["success"] is True

    def test_entry_exactly_at_cutoff_rejected(self, temp_engine, monkeypatch):
        """14:50:00 IST: Exactly at cutoff, entry must be rejected."""
        monkeypatch.setattr(MarketCalendar, "is_market_open", lambda: True)
        res = temp_engine.open_position(
            instrument="NIFTY 50",
            contract_symbol="NIFTY23NOV2625800CE",
            bias="CE",
            strike=25800,
            expiry="23NOV2026",
            entry_premium=113.50,
            lots=1,
            lot_size=65,
            stop_loss=102.30,
            target_1=150.60,
            target_2=173.20,
            market_features={
                "evalTimestamp": "2026-11-20 14:50:00",
                "isTradeQualified": True,
                "dataStatus": "VERIFIED_LIVE",
            },
        )
        assert res["success"] is False
        assert res["code"] == "INSUFFICIENT_HOLDING_TIME_BEFORE_EOD_SQUAREOFF"
        assert "past entry cutoff" in res["message"]

    def test_entry_after_cutoff_reported_trade_rejected(self, temp_engine, monkeypatch):
        """15:09:23 IST (Reported trade): Must be strictly rejected."""
        monkeypatch.setattr(MarketCalendar, "is_market_open", lambda: True)
        res = temp_engine.open_position(
            instrument="NIFTY 50",
            contract_symbol="NIFTY23NOV2625800CE",
            bias="CE",
            strike=25800,
            expiry="23NOV2026",
            entry_premium=113.50,
            lots=1,
            lot_size=65,
            stop_loss=102.30,
            target_1=150.60,
            target_2=173.20,
            market_features={
                "evalTimestamp": "2026-11-20 15:09:23",
                "isTradeQualified": True,
                "dataStatus": "VERIFIED_LIVE",
            },
        )
        assert res["success"] is False
        assert res["code"] == "INSUFFICIENT_HOLDING_TIME_BEFORE_EOD_SQUAREOFF"
        assert res["sessionCutoff"]["remainingMinutesBeforeSquareOff"] < 1.0

    def test_replay_bypass_allowed_for_testing(self, temp_engine, monkeypatch):
        """allowAfterHoursSimulation / isReplay bypasses cutoff for sandbox testing."""
        monkeypatch.setattr(MarketCalendar, "is_market_open", lambda: False)
        res = temp_engine.open_position(
            instrument="NIFTY 50",
            contract_symbol="NIFTY23NOV2625800CE",
            bias="CE",
            strike=25800,
            expiry="23NOV2026",
            entry_premium=113.50,
            lots=1,
            lot_size=65,
            stop_loss=102.30,
            target_1=150.60,
            target_2=173.20,
            market_features={
                "allowAfterHoursSimulation": True,
                "isReplay": True,
                "evalTimestamp": "2026-11-20 15:09:23",
                "isTradeQualified": True,
                "dataStatus": "VERIFIED_LIVE",
            },
        )
        assert res["success"] is True


class TestAutomaticExitAndProtectiveStopLoss:
    """Tests for stop loss protection, Target 1 behavior, and EOD square-off."""

    def test_stop_loss_protection_remains_active(self, temp_engine):
        """Protective stop loss must remain 100% armed and trigger when premium drops below SL."""
        res = temp_engine.open_position(
            instrument="NIFTY 50",
            contract_symbol="NIFTY23NOV2625800CE",
            bias="CE",
            strike=25800,
            expiry="23NOV2026",
            entry_premium=113.50,
            lots=1,
            lot_size=65,
            stop_loss=102.30,
            target_1=150.60,
            target_2=173.20,
            market_features={"allowAfterHoursSimulation": True},
        )
        pid = res["position"]["id"]

        # Tick 1: Normal market fluctuation above SL
        temp_engine.update_live_monitoring(
            contract_symbol="NIFTY23NOV2625800CE",
            current_ltp=110.00,
            bar_high=115.00,
            bar_low=108.00,
            quote_timestamp="2026-11-20 14:45:00",
        )
        assert len(temp_engine.state["openPositions"]) == 1

        # Tick 2: Stop loss hit at 101.50 (below 102.30)
        close_res = temp_engine.update_live_monitoring(
            contract_symbol="NIFTY23NOV2625800CE",
            current_ltp=101.50,
            bar_high=105.00,
            bar_low=101.00,
            quote_timestamp="2026-11-20 14:46:12",
        )
        assert len(temp_engine.state["openPositions"]) == 0
        assert len(temp_engine.state["closedTrades"]) == 1
        closed = temp_engine.state["closedTrades"][0]
        assert closed["status"] == "STOP_LOSS_HIT"
        assert closed["exitReason"] == "Stop Loss Hit"
        assert closed["exitPremium"] <= 102.30
        assert closed["fillTimestamp"] == "2026-11-20 14:46:12"

    def test_eod_square_off_status_classification(self, temp_engine):
        """At or after 15:10 IST, open position must be automatically closed with status EOD_SQUARE_OFF."""
        res = temp_engine.open_position(
            instrument="NIFTY 50",
            contract_symbol="NIFTY23NOV2625800CE",
            bias="CE",
            strike=25800,
            expiry="23NOV2026",
            entry_premium=113.50,
            lots=1,
            lot_size=65,
            stop_loss=102.30,
            target_1=150.60,
            target_2=173.20,
            market_features={"allowAfterHoursSimulation": True},
        )
        pid = res["position"]["id"]

        # Tick at 15:10:05 IST triggers EOD square-off
        temp_engine.update_live_monitoring(
            contract_symbol="NIFTY23NOV2625800CE",
            current_ltp=116.20,
            bar_high=117.00,
            bar_low=115.50,
            quote_timestamp="2026-11-20 15:10:05",
        )
        assert len(temp_engine.state["openPositions"]) == 0
        assert len(temp_engine.state["closedTrades"]) == 1
        closed = temp_engine.state["closedTrades"][0]
        assert closed["status"] == "EOD_SQUARE_OFF"
        assert "EOD Square-Off" in closed["exitReason"]
        assert closed["fillTimestamp"] == "2026-11-20 15:10:05"
        assert closed["lastVerifiedQuoteTimestamp"] == "2026-11-20 15:10:05"
        assert closed["ledgerCleanupTimestamp"] is not None

    def test_target_1_single_lot_trails_sl_to_cost(self, temp_engine):
        """For lots == 1, reaching Target 1 trails SL to entry cost rather than liquidating."""
        res = temp_engine.open_position(
            instrument="NIFTY 50",
            contract_symbol="NIFTY23NOV2625800CE",
            bias="CE",
            strike=25800,
            expiry="23NOV2026",
            entry_premium=113.50,
            lots=1,
            lot_size=65,
            stop_loss=102.30,
            target_1=150.60,
            target_2=173.20,
            market_features={"allowAfterHoursSimulation": True},
        )

        # Reaches T1
        temp_engine.update_live_monitoring(
            contract_symbol="NIFTY23NOV2625800CE",
            current_ltp=151.00,
            bar_high=152.00,
            bar_low=148.00,
            quote_timestamp="2026-11-20 14:20:00",
        )
        assert len(temp_engine.state["openPositions"]) == 1
        pos = temp_engine.state["openPositions"][0]
        assert pos["status"] == "TARGET_1_HIT"
        # SL trailed to at least entry cost
        assert pos["stopLoss"] >= 113.50

    def test_target_1_multi_lot_partial_exit(self, temp_engine):
        """For lots > 1, reaching Target 1 books 50% partial exit and trails SL to cost."""
        res = temp_engine.open_position(
            instrument="NIFTY 50",
            contract_symbol="NIFTY23NOV2625800CE",
            bias="CE",
            strike=25800,
            expiry="23NOV2026",
            entry_premium=113.50,
            lots=2,
            lot_size=65,
            stop_loss=102.30,
            target_1=150.60,
            target_2=173.20,
            market_features={"allowAfterHoursSimulation": True},
        )

        # Reaches T1
        temp_engine.update_live_monitoring(
            contract_symbol="NIFTY23NOV2625800CE",
            current_ltp=151.00,
            bar_high=152.00,
            bar_low=148.00,
            quote_timestamp="2026-11-20 14:20:00",
        )
        assert len(temp_engine.state["openPositions"]) == 1
        pos = temp_engine.state["openPositions"][0]
        assert pos["remainingLots"] == 1
        assert pos["remainingQuantity"] == 65
        assert len(pos["partialExits"]) == 1
        assert pos["partialExits"][0]["exitLots"] == 1
        assert pos["stopLoss"] == 113.50


class TestConfigurableSessionCutoff:
    """Verifies that cutoff settings can be dynamically configured."""

    def test_configure_session_cutoff(self, temp_engine):
        cfg = temp_engine.configure_session_cutoff(
            min_holding_window_minutes=30.0,
            eod_square_off_time="15:15",
        )
        assert cfg["min_holding_window_minutes"] == 30.0
        assert cfg["eod_square_off_time"] == "15:15"

        status = temp_engine.get_session_cutoff_status(datetime(2026, 11, 20, 14, 40, 0))
        assert status["cutoffTime"] == "14:45 IST"
        assert status["eodSquareOffTime"] == "15:15 IST"


class TestBaselineIntegrity:
    """Ensures none of the protected baseline files have been modified."""

    def test_protected_files_unmodified(self):
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        for rel_path, expected_hash in PROTECTED_BASELINE_HASHES.items():
            full_path = os.path.join(project_root, rel_path)
            assert os.path.exists(full_path), f"Protected file missing: {rel_path}"
            with open(full_path, "rb") as f:
                actual_hash = hashlib.sha256(f.read()).hexdigest()
            assert actual_hash == expected_hash, f"Protected file {rel_path} was corrupted! Expected {expected_hash}, got {actual_hash}"
