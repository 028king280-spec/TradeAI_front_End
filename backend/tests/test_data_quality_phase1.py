"""
AIVOLVE 3.0 — Phase 1 Test Suite & Safety Verification.
Covers:
- Safety 1: Market Closed & EOD Snapshot gating (No new trades allowed after hours).
- Safety 2: MOCK and SYNTHETIC feed protection (Never trade-qualified).
- Safety 3: WebSocket sequence semantics (Missing sequence vs confirmed gap) and reconnection reconciliation.
- Safety 4: Database durability (WAL mode and record preservation).
- Safety 5: Instrument-aware tick jump thresholds and opening gap handling.
- Safety 6: Fix verification for /next-session/recommendation UnboundLocalError.
"""

import sqlite3
import pytest
import pandas as pd
from datetime import datetime, timezone
from app.data.quality_validator import DataQualityEngine, FeedStatus
from app.data.market_calendar import MarketCalendar
from app.api.routes.options import canonicalize_symbol
from app.options.setup_selector import evaluate_options_trade_setups
from app.options.paper_trading.paper_engine import paper_engine


# =====================================================================
# Safety 1: Market Closed Safety
# =====================================================================
def test_market_closed_eod_snapshot_analysis_only():
    """Verify VERIFIED_EOD snapshots are available for analysis but NEVER trade-qualified."""
    eod_quote = {
        "symbol": "NIFTY 50",
        "ltp": 24500.0,
        "high": 24600.0,
        "low": 24400.0,
        "dataStatus": "MARKET_CLOSED",
        "feedStatus": "VERIFIED_EOD",
    }
    audit = DataQualityEngine.validate_quote("NIFTY 50", eod_quote)
    report = audit["dataQualityReport"]

    assert report["feedStatus"] == FeedStatus.VERIFIED_EOD
    assert report["isAnalysisQualified"] is True
    assert report["isTradeQualified"] is False  # Cannot execute trades on EOD snapshot


def test_market_closed_blocks_paper_trade_opening():
    """Confirm new paper trades cannot be opened when the exchange is closed."""
    # When market is closed (or simulated closed with EOD features)
    res = paper_engine.open_position(
        instrument="NIFTY",
        contract_symbol="NIFTY09NOV2624500CE",
        bias="CE",
        strike=24500,
        expiry="09NOV2026",
        entry_premium=150.0,
        market_features={
            "dataStatus": "MARKET_CLOSED",
            "feedStatus": "VERIFIED_EOD",
            "isTradeQualified": False,
        }
    )
    assert not res["success"]
    assert ("rejected" in res["message"].lower() or "closed" in res["message"].lower())


# =====================================================================
# Safety 2: Mock Data Protection
# =====================================================================
def test_mock_and_synthetic_feed_never_trade_qualified():
    """Verify MOCK and SYNTHETIC data can never become trade-qualified."""
    mock_quote = {
        "symbol": "NIFTY 50",
        "ltp": 24800.0,
        "high": 24850.0,
        "low": 24750.0,
        "dataStatus": "MOCK",
        "provider": "mock",
    }
    audit = DataQualityEngine.validate_quote("NIFTY 50", mock_quote)
    report = audit["dataQualityReport"]

    assert report["feedStatus"] == FeedStatus.SYNTHETIC
    assert report["isTradeQualified"] is False
    assert DataQualityEngine.is_trade_qualified(report) is False


def test_mock_feed_suppresses_trade_setups():
    """Confirm mock feeds cannot generate executable paper-trading signals."""
    mock_report = {
        "dataQualityScore": 0,
        "feedStatus": FeedStatus.SYNTHETIC,
        "isTradeQualified": False,
        "anomaliesDetected": ["Synthetic/Mock feed detected."],
    }
    setups = evaluate_options_trade_setups(
        symbol="NIFTY 50",
        underlying_ltp=24800.0,
        sentiment="BULLISH",
        sentiment_score=85,
        strikes_data=[],
        atr_14=120.0,
        data_quality_report=mock_report,
    )
    assert setups["primaryBias"] == "NO_TRADE"
    assert setups["isTradeQualified"] is False
    assert setups["dataGated"] is True
    assert len(setups["setups"]) == 0


def test_paper_engine_rejects_mock_order(monkeypatch):
    """Confirm paper engine strictly rejects order execution on mock data even during market hours."""
    monkeypatch.setattr(MarketCalendar, "is_market_open", lambda: True)
    res = paper_engine.open_position(
        instrument="NIFTY",
        contract_symbol="NIFTY09NOV2624500CE",
        bias="CE",
        strike=24500,
        expiry="09NOV2026",
        entry_premium=150.0,
        market_features={
            "dataStatus": "MOCK",
            "feedStatus": "SYNTHETIC",
            "isTradeQualified": False,
        }
    )
    assert not res["success"]
    assert "rejected by DataQualityEngine" in res["message"]


# =====================================================================
# Safety 3: WebSocket Sequence Semantics
# =====================================================================
def test_websocket_missing_sequence_vs_gap():
    """Handle missing sequence information separately from confirmed packet drops."""
    # Mode 1/2 packets from Angel One do not carry sequence numbers
    packet_no_seq = {"ltp": 24500.0, "volume": 1000}
    val = DataQualityEngine.validate_tick("NIFTY 50", packet_no_seq, expected_sequence=None)
    assert val["sequenceStatus"] == "SEQUENCE_NOT_PROVIDED"
    assert not val["gapDetected"]

    # When sequence is carried and drops packets
    packet_gapped = {"ltp": 24505.0, "volume": 1200, "sequence_number": 250}
    val_gap = DataQualityEngine.validate_tick("NIFTY 50", packet_gapped, expected_sequence=240)
    assert val_gap["sequenceStatus"] == "GAP_DETECTED"
    assert val_gap["gapDetected"] is True
    assert val_gap["feedStatus"] == FeedStatus.DEGRADED


# =====================================================================
# Safety 4: Database Durability & WAL Configuration
# =====================================================================
def test_sqlite_wal_mode_and_record_preservation():
    """Verify SQLite WAL pragma configuration and confirm records remain intact."""
    from app.db.database import get_active_db_path
    conn = sqlite3.connect(get_active_db_path())
    c = conn.cursor()
    journal_mode = c.execute("PRAGMA journal_mode;").fetchone()[0].lower()
    assert journal_mode == "wal", f"Expected WAL mode, got {journal_mode}"

    # Verify existing table records
    sig_count = c.execute("SELECT COUNT(*) FROM signals;").fetchone()[0]
    candle_count = c.execute("SELECT COUNT(*) FROM market_candles;").fetchone()[0]
    conn.close()

    assert sig_count > 0, "Signals table was unexpectedly emptied!"
    assert candle_count > 0, "Market candles table was unexpectedly emptied!"


# =====================================================================
# Safety 5: Instrument-Aware Tick Jumps & Market Gaps
# =====================================================================
def test_instrument_aware_option_jump_allowed():
    """Verify legitimate 20% option premium tick jump is allowed for options but rejected for spot."""
    # Option: ₹40 -> ₹48 is a 20% jump, which is normal for options with +60 volume
    opt_tick_1 = {"ltp": 40.0, "volume": 500}
    opt_tick_2 = {"ltp": 48.0, "volume": 580}
    val_opt = DataQualityEngine.validate_tick("NIFTY2624500CE", opt_tick_2, last_tick=opt_tick_1)
    assert val_opt["isValid"] is True
    assert val_opt["feedStatus"] == FeedStatus.VERIFIED_LIVE

    # Spot Index: 24,000 -> 24,500 (+2.08% in a single tick with low volume) should be flagged
    spot_tick_1 = {"ltp": 24000.0, "volume": 5000}
    spot_tick_2 = {"ltp": 24500.0, "volume": 5050}
    val_spot = DataQualityEngine.validate_tick("NIFTY 50", spot_tick_2, last_tick=spot_tick_1)
    assert val_spot["isValid"] is False
    assert val_spot["feedStatus"] == FeedStatus.ANOMALOUS


def test_legitimate_session_opening_gap_preserved():
    """Verify legitimate market opening gap (consistent with openPrice) is not rejected as freak tick."""
    reference_candles = pd.DataFrame({
        "open": [24200, 24220, 24210],
        "high": [24250, 24240, 24230],
        "low": [24180, 24190, 24200],
        "close": [24220, 24210, 24215],
    })
    atr_14 = 80.0
    # Next session opens with +400 pts gap up at 24610. LTP matches openPrice
    gap_quote = {
        "symbol": "NIFTY 50",
        "ltp": 24615.0,
        "openPrice": 24610.0,
        "dayHigh": 24650.0,
        "dayLow": 24600.0,
    }
    audit = DataQualityEngine.validate_quote("NIFTY 50", gap_quote, reference_candles=reference_candles, atr_14=atr_14)
    report = audit["dataQualityReport"]

    assert any("Legitimate opening session gap verified" in c for c in report["checksPassed"])
    assert report["feedStatus"] != FeedStatus.ANOMALOUS


# =====================================================================
# Safety 6: Previous Crash Fix Verification
# =====================================================================
def test_next_session_recommendation_crash_fixed():
    """Verify the previous UnboundLocalError: candles_df is completely resolved."""
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    response = client.get("/api/options/NIFTY/next-session/recommendation")
    assert response.status_code == 200
    data = response.json()
    assert "stage" in data
    assert "openingOutlook" in data
    assert "dataQualityReport" in data
