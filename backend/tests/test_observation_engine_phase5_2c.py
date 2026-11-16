"""
Phase 5.2C Automated Test Suite: Genuine Paper Observation & Data Accumulation Engine.

Verifies:
1. Preflight checks (Broker Auth, Instrument Master, WebSocket ticks, Market Hours, Data Quality).
2. Weekend / closed exchange session fail-closed behavior (No fake observations).
3. Inactive socket rejection (Connected but inactive socket is NEVER marked healthy live streaming).
4. Supported underlyings: NIFTY, BANKNIFTY, FINNIFTY authorized; SENSEX strictly GOVERNANCE_LOCKED.
5. Strict non-substitution invariant (Underlying spot price never substituted for option premium).
6. Bid/ask spread sanity and quote validation.
7. Production feature extraction validation (no synthetic/defaulted vectors).
8. ICT/SMC calibration guard (uncalibrated contexts recorded as NOT_CALIBRATED).
9. Fixed-horizon evaluation (5, 15, 30, 60m) and missing quotes handling (INSUFFICIENT_DATA).
10. Complete dataset isolation (ml_production_dataset.json isolated; ml_trade_dataset.json unmodified).
"""

import os
import json
import pytest
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from unittest.mock import patch, MagicMock

from app.data.market_calendar import MarketCalendar
from app.data.quality_validator import FeedStatus
from app.options.paper_trading.observation_engine import (
    PreflightChecker,
    PreflightReport,
    ObservationEngine,
    ObservationRecord,
    ALLOWED_OBSERVATION_UNDERLYINGS,
    GOVERNANCE_LOCKED_UNDERLYINGS,
    DEFAULT_PRODUCTION_DATASET_PATH,
    PROTECTED_ML_TRADE_DATASET_PATH,
    EXPECTED_ML_TRADE_DATASET_HASH,
)
from app.options.paper_trading.label_engine import (
    FixedHorizonObservation,
    HorizonStatus,
    SignalDecision,
)

IST = ZoneInfo("Asia/Kolkata")


def _get_valid_raw_features():
    """Helper providing standard verified production features."""
    return {
        "greeks": {
            "iv": 0.165,
            "delta": 0.52,
            "theta": -14.2,
            "gamma": 0.0028,
        },
        "spread": 1.25,
        "vix": 14.2,
        "atr": 125.0,
        "vwapDistancePct": 0.15,
        "dealingRangePct": 55.0,
        "mtfConfluenceScore": 75.0,
        "sweepReclaim": True,
        "displacementRatio": 1.45,
        "fvgGapPts": 18.5,
        "pcr": 1.05,
        "marketRegime": "TRENDING_BULL",
        "ictSetup": "Liquidity Sweep + MSS Reclaim",
    }


def test_preflight_audit_market_closed_on_weekend():
    """Asserts that PreflightChecker identifies weekend as MARKET_CLOSED and fails preflight."""
    # Simulate a Saturday at 11:00 AM IST
    saturday_dt = datetime(2026, 11, 14, 11, 0, 0, tzinfo=IST)
    with patch.object(MarketCalendar, "now_ist", return_value=saturday_dt):
        report = PreflightChecker.run_preflight_audit()
        assert report.passed is False
        assert report.session_status == "CLOSED"
        assert report.is_trading_day is False
        assert any("CLOSED" in r for r in report.rejection_reasons)


def test_preflight_audit_inactive_socket_rejection():
    """Asserts that a connected but inactive WebSocket is strictly rejected as UNHEALTHY."""
    # Weekday market session simulation
    weekday_dt = datetime(2026, 11, 16, 10, 30, 0, tzinfo=IST)
    with patch.object(MarketCalendar, "now_ist", return_value=weekday_dt), \
         patch("app.data.providers.angelone_websocket.angelone_ws_manager.get_diagnostics", return_value={
             "is_running": True,
             "is_healthy": False,  # Connected but no ticks for >30s
             "ticks_received": 12,
             "seconds_since_last_tick": 45.0,
         }), \
         patch("app.data.providers.angelone_provider.AngelOneMarketDataProvider.is_authenticated", return_value=True):
        
        report = PreflightChecker.run_preflight_audit()
        assert report.websocket_running is True
        assert report.websocket_healthy is False
        assert report.passed is False
        assert any("Inactive sockets cannot be classified as healthy" in r for r in report.rejection_reasons)


def test_preflight_supported_instruments_and_sensex_locked():
    """Asserts that NIFTY, BANKNIFTY, FINNIFTY are permitted while SENSEX is strictly locked."""
    assert "NIFTY" in ALLOWED_OBSERVATION_UNDERLYINGS
    assert "BANKNIFTY" in ALLOWED_OBSERVATION_UNDERLYINGS
    assert "FINNIFTY" in ALLOWED_OBSERVATION_UNDERLYINGS
    assert "SENSEX" in GOVERNANCE_LOCKED_UNDERLYINGS
    assert "SENSEX" not in ALLOWED_OBSERVATION_UNDERLYINGS


def test_observation_engine_rejects_closed_market():
    """Asserts that ObservationEngine rejects observations when market is closed (fail-closed)."""
    engine = ObservationEngine()
    saturday_dt = datetime(2026, 11, 14, 11, 0, 0, tzinfo=IST)
    raw_feats = _get_valid_raw_features()

    success, record, reason = engine.process_observation(
        underlying_symbol="NIFTY",
        contract_symbol="NIFTY26NOV25000CE",
        expiry_date="2026-11-26",
        strike_price=25000.0,
        option_type="CE",
        spot_ltp=25050.0,
        option_ltp=135.0,
        bid_price=134.5,
        ask_price=135.5,
        raw_market_data={},
        raw_features=raw_feats,
        observation_timestamp=saturday_dt,
    )

    assert success is False
    assert record is None
    assert "Exchange session is CLOSED" in reason


def test_observation_engine_rejects_governance_locked_sensex():
    """Asserts that SENSEX observations are strictly rejected under GOVERNANCE_LOCKED."""
    engine = ObservationEngine()
    # Past market open time (Friday Nov 13, 2026 10:00 AM IST)
    open_dt = datetime(2026, 11, 13, 10, 0, 0, tzinfo=IST)
    raw_feats = _get_valid_raw_features()

    success, record, reason = engine.process_observation(
        underlying_symbol="SENSEX",
        contract_symbol="SENSEX26NOV81000CE",
        expiry_date="2026-11-26",
        strike_price=81000.0,
        option_type="CE",
        spot_ltp=81200.0,
        option_ltp=240.0,
        bid_price=239.0,
        ask_price=241.0,
        raw_market_data={},
        raw_features=raw_feats,
        observation_timestamp=open_dt,
    )

    assert success is False
    assert record is None
    assert "GOVERNANCE_LOCKED" in reason


def test_observation_engine_rejects_spot_price_substitution():
    """Asserts that passing spot index price as option premium is rejected."""
    engine = ObservationEngine()
    open_dt = datetime(2026, 11, 13, 10, 0, 0, tzinfo=IST)
    raw_feats = _get_valid_raw_features()

    success, record, reason = engine.process_observation(
        underlying_symbol="NIFTY",
        contract_symbol="NIFTY26NOV25000CE",
        expiry_date="2026-11-26",
        strike_price=25000.0,
        option_type="CE",
        spot_ltp=25050.0,
        option_ltp=25050.0,  # ILLEGAL SUBSTITUTION
        bid_price=25049.0,
        ask_price=25051.0,
        raw_market_data={},
        raw_features=raw_feats,
        observation_timestamp=open_dt,
    )

    assert success is False
    assert record is None
    assert "non-substitution invariant violated" in reason


def test_observation_engine_rejects_inverted_market():
    """Asserts that inverted markets (ask < bid) or zero bids are rejected."""
    engine = ObservationEngine()
    open_dt = datetime(2026, 11, 13, 10, 0, 0, tzinfo=IST)
    raw_feats = _get_valid_raw_features()

    # Inverted spread: ask (100) < bid (105)
    success, record, reason = engine.process_observation(
        underlying_symbol="NIFTY",
        contract_symbol="NIFTY26NOV25000CE",
        expiry_date="2026-11-26",
        strike_price=25000.0,
        option_type="CE",
        spot_ltp=25050.0,
        option_ltp=102.0,
        bid_price=105.0,
        ask_price=100.0,
        raw_market_data={},
        raw_features=raw_feats,
        observation_timestamp=open_dt,
    )

    assert success is False
    assert "Inverted market" in reason


def test_observation_engine_valid_live_observation_processed():
    """Asserts that valid genuine observation in market hours passes all gates and records record."""
    engine = ObservationEngine()
    open_dt = datetime(2026, 11, 13, 10, 0, 0, tzinfo=IST)
    raw_feats = _get_valid_raw_features()

    success, record, reason = engine.process_observation(
        underlying_symbol="NIFTY",
        contract_symbol="NIFTY26NOV25000CE",
        expiry_date="2026-11-26",
        strike_price=25000.0,
        option_type="CE",
        spot_ltp=25050.0,
        option_ltp=135.0,
        bid_price=134.5,
        ask_price=135.5,
        raw_market_data={},
        raw_features=raw_feats,
        observation_timestamp=open_dt,
        ict_smc_context={"is_calibrated": False},  # Uncalibrated test
    )

    assert success is True
    assert record is not None
    assert record.underlying_symbol == "NIFTY"
    assert record.contract_symbol == "NIFTY26NOV25000CE"
    assert record.option_ltp == 135.0
    assert record.spread == 1.0
    assert len(record.features) == 14
    assert record.data_classification == "VERIFIED_LIVE_PAPER"
    assert record.is_validated is True
    # Training eligibility is False until forward horizons resolve!
    assert record.is_training_eligible is False
    assert record.ict_smc_context == {"status": "NOT_CALIBRATED", "calibrated": False}


def test_observation_engine_forward_horizons_missing_is_insufficient_data():
    """Asserts that when forward quotes are missing, horizons return INSUFFICIENT_DATA."""
    engine = ObservationEngine()
    open_dt = datetime(2026, 11, 13, 10, 0, 0, tzinfo=IST)
    raw_feats = _get_valid_raw_features()

    success, record, _ = engine.process_observation(
        underlying_symbol="BANKNIFTY",
        contract_symbol="BANKNIFTY26NOV52000CE",
        expiry_date="2026-11-26",
        strike_price=52000.0,
        option_type="CE",
        spot_ltp=52100.0,
        option_ltp=280.0,
        bid_price=279.0,
        ask_price=281.0,
        raw_market_data={},
        raw_features=raw_feats,
        observation_timestamp=open_dt,
    )
    assert success is True

    # Empty forward observations list
    h_success, label_set, msg = engine.evaluate_observation_forward_horizons(
        observation_id=record.observation_id,
        forward_quotes=[],
    )

    assert h_success is True
    assert label_set is not None
    # All 4 horizons must be INSUFFICIENT_DATA
    for minutes in [5, 15, 30, 60]:
        h_label = label_set.horizons[minutes]
        assert h_label.status == HorizonStatus.INSUFFICIENT_DATA
    assert record.is_training_eligible is False


def test_observation_engine_forward_horizons_all_resolved():
    """Asserts that when genuine forward quotes are present, horizons resolve and record is eligible."""
    engine = ObservationEngine()
    open_dt = datetime(2026, 11, 13, 10, 0, 0, tzinfo=IST)
    raw_feats = _get_valid_raw_features()

    success, record, _ = engine.process_observation(
        underlying_symbol="FINNIFTY",
        contract_symbol="FINNIFTY26NOV24000CE",
        expiry_date="2026-11-26",
        strike_price=24000.0,
        option_type="CE",
        spot_ltp=24050.0,
        option_ltp=90.0,
        bid_price=89.5,
        ask_price=90.5,
        raw_market_data={},
        raw_features=raw_feats,
        observation_timestamp=open_dt,
    )
    assert success is True

    # Genuine forward quotes matching contract symbol
    forward_quotes = [
        {"contract": "FINNIFTY26NOV24000CE", "timestamp": (open_dt + timedelta(minutes=5)).isoformat(), "ltp": 95.0},
        {"contract": "FINNIFTY26NOV24000CE", "timestamp": (open_dt + timedelta(minutes=15)).isoformat(), "ltp": 102.0},
        {"contract": "FINNIFTY26NOV24000CE", "timestamp": (open_dt + timedelta(minutes=30)).isoformat(), "ltp": 98.0},
        {"contract": "FINNIFTY26NOV24000CE", "timestamp": (open_dt + timedelta(minutes=60)).isoformat(), "ltp": 110.0},
    ]

    h_success, label_set, msg = engine.evaluate_observation_forward_horizons(
        observation_id=record.observation_id,
        forward_quotes=forward_quotes,
    )

    assert h_success is True
    for minutes in [5, 15, 30, 60]:
        h_label = label_set.horizons[minutes]
        assert h_label.status == HorizonStatus.RESOLVED
        assert h_label.horizon_price is not None
    assert record.is_training_eligible is True


def test_production_dataset_isolation_integrity(tmp_path):
    """Asserts that protected ml_trade_dataset.json hash is validated before persisting."""
    test_prod_file = str(tmp_path / "test_production_dataset.json")
    engine = ObservationEngine(production_dataset_path=test_prod_file)

    # 1. Baseline hash verification must succeed
    assert engine.verify_dataset_isolation() is True

    # 2. Persistence works cleanly without touching ml_trade_dataset.json
    added = engine.persist_production_dataset()
    assert added == 0  # Buffer was empty
    assert engine.verify_dataset_isolation() is True
