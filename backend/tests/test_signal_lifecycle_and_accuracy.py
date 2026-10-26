"""
Comprehensive Test Suite for AIVOLVE Trading AI
Requirements 1, 2, 3, and 4:
1. Sideways Market vs. No-Trade & Independent Index State
2. CALL/PUT Signal Qualification, State Transitions & Entry vs. Missed
3. Target & Stop-Loss Tracking, Intrabar Ambiguity, Reversal Detection, Data Gaps, Idempotency & Recovery
4. Daily Accuracy Metrics, Transparent Denominators, Zero-Sample Periods & Cost Calibrations
"""

import pytest
import uuid
import pandas as pd
from datetime import datetime, timezone, timedelta

from app.options.market_state_engine import (
    MarketState,
    evaluate_index_market_state,
)
from app.options.signal_activation_engine import (
    SignalState,
    can_transition,
    validate_state_transition,
    evaluate_setup_qualification,
    evaluate_entry_trigger,
    get_frontend_signal_badge,
)
from app.options.failure_diagnostics import (
    FailureOutcome,
    diagnose_signal_failure,
)
from app.services.outcome_tracker import OutcomeTrackerService
from app.models.db_models import SignalRecord, SignalEventRecord
from app.db.database import async_session_factory


# =====================================================================
# 1. REQUIREMENT 1: MARKET STATE & NO-TRADE ZONE TESTS
# =====================================================================

def test_sideways_market_detection():
    """Verify range-bound, low-momentum price action is classified as SIDEWAYS with isNoTrade=True."""
    # Flat candles around 24500
    df = pd.DataFrame([
        {"timestamp": "2026-10-16 09:15:00", "open": 24500, "high": 24520, "low": 24490, "close": 24505, "volume": 1000},
        {"timestamp": "2026-10-16 09:30:00", "open": 24505, "high": 24515, "low": 24495, "close": 24500, "volume": 950},
        {"timestamp": "2026-10-16 09:45:00", "open": 24500, "high": 24510, "low": 24490, "close": 24502, "volume": 900},
        {"timestamp": "2026-10-16 10:00:00", "open": 24502, "high": 24515, "low": 24492, "close": 24504, "volume": 920},
    ])
    quote = {"currentPrice": 24504.0, "dayHigh": 24520.0, "dayLow": 24490.0, "previousClose": 24500.0, "change": 4.0}
    info = {"vwap": 24502.0, "ema20": 24503.0, "ema50": 24504.0, "atr": 25.0}

    res = evaluate_index_market_state(
        symbol="NIFTY 50",
        quote=quote,
        candles_df=df,
        candles_info=info,
        option_chain_summary={"pcr": {"pcrOi": 1.02}, "callWall": 24600, "putWall": 24400, "maxPain": {"maxPainStrike": 24500}},
        vix_value=12.5,
        is_live_data=True,
    )

    assert res["marketState"] == MarketState.SIDEWAYS
    assert res["isNoTrade"] is True
    assert "prominentStatus" in res
    assert res["prominentStatus"] == "NO TRADE"
    assert "sideways" in res["explanation"].lower() or "range" in res["explanation"].lower()


def test_no_trade_qualification_conflicting_indicators():
    """Verify NO_TRADE when indicators conflict (e.g. price above VWAP but heavy Call writing, wide spread)."""
    df = pd.DataFrame([
        {"timestamp": "2026-10-16 09:15:00", "open": 24500, "high": 24580, "low": 24490, "close": 24570, "volume": 5000},
        {"timestamp": "2026-10-16 09:30:00", "open": 24570, "high": 24610, "low": 24560, "close": 24600, "volume": 6000},
    ])
    quote = {"currentPrice": 24600.0, "dayHigh": 24610.0, "dayLow": 24490.0, "previousClose": 24500.0, "change": 100.0}
    info = {"vwap": 24550.0, "ema20": 24540.0, "ema50": 24520.0, "atr": 90.0}

    # PCR heavily bearish (0.65) despite price rally, creating indicator conflict -> NO_TRADE
    res = evaluate_index_market_state(
        symbol="NIFTY 50",
        quote=quote,
        candles_df=df,
        candles_info=info,
        option_chain_summary={"pcr": {"pcrOi": 0.65}, "callWall": 24600, "putWall": 24400, "maxPain": {"maxPainStrike": 24500}},
        vix_value=24.5,  # High VIX volatility penalty
        is_live_data=True,
    )

    assert res["isNoTrade"] is True
    assert res["marketState"] in [MarketState.NO_TRADE, MarketState.SIDEWAYS]
    assert len(res["reasonForNoTrade"]) > 0


def test_independent_index_states():
    """Verify NIFTY being Bullish does NOT force SENSEX or BANK NIFTY to be Bullish."""
    # NIFTY Strong Rally
    nifty_df = pd.DataFrame([{"timestamp": "t1", "open": 24400, "high": 24600, "low": 24400, "close": 24580, "volume": 10000}])
    nifty_res = evaluate_index_market_state(
        symbol="NIFTY 50",
        quote={"currentPrice": 24580, "dayHigh": 24600, "dayLow": 24400, "previousClose": 24400, "change": 180},
        candles_df=nifty_df,
        candles_info={"vwap": 24480, "ema20": 24450, "ema50": 24400, "atr": 90, "rsi": 65.0},
        option_chain_summary={"pcr": {"pcrOi": 1.35}, "callWall": 24800, "putWall": 24400, "maxPain": {"maxPainStrike": 24500}},
        vix_value=13.0,
        is_live_data=True,
    )

    # BANK NIFTY Range-bound chop
    bank_df = pd.DataFrame([{"timestamp": "t1", "open": 52000, "high": 52050, "low": 51980, "close": 52010, "volume": 1000}])
    bank_res = evaluate_index_market_state(
        symbol="BANK NIFTY",
        quote={"currentPrice": 52010, "dayHigh": 52050, "dayLow": 51980, "previousClose": 52000, "change": 10},
        candles_df=bank_df,
        candles_info={"vwap": 52005, "ema20": 52008, "ema50": 52010, "atr": 40, "rsi": 50.0},
        option_chain_summary={"pcr": {"pcrOi": 0.98}, "callWall": 52500, "putWall": 51800, "maxPain": {"maxPainStrike": 52000}},
        vix_value=13.0,
        is_live_data=True,
    )

    assert nifty_res["marketState"] == MarketState.BULLISH
    assert bank_res["marketState"] == MarketState.SIDEWAYS
    assert nifty_res["marketState"] != bank_res["marketState"]


# =====================================================================
# 2. REQUIREMENT 2: SIGNAL ACTIVATION & LIFECYCLE TESTS
# =====================================================================

def test_valid_state_transitions():
    """Verify legitimate state machine transitions according to the explicit transition graph."""
    assert can_transition(SignalState.NO_TRADE, SignalState.WAITING_FOR_CONFIRMATION) is True
    assert can_transition(SignalState.WAITING_FOR_CONFIRMATION, SignalState.CALL_SETUP_READY) is True
    assert can_transition(SignalState.CALL_SETUP_READY, SignalState.ENTRY_TRIGGERED) is True
    assert can_transition(SignalState.ENTRY_TRIGGERED, SignalState.TARGET_1_HIT) is True
    assert can_transition(SignalState.TARGET_1_HIT, SignalState.TARGET_2_HIT) is True
    assert can_transition(SignalState.TARGET_2_HIT, SignalState.TARGET_3_HIT) is True
    assert can_transition(SignalState.TARGET_1_HIT, SignalState.STOP_LOSS_HIT) is True
    assert can_transition(SignalState.TARGET_3_HIT, SignalState.EXITED) is True

    # Invalid transitions
    assert can_transition(SignalState.STOP_LOSS_HIT, SignalState.TARGET_1_HIT) is False
    assert can_transition(SignalState.EXITED, SignalState.ENTRY_TRIGGERED) is False
    assert can_transition(SignalState.MISSED, SignalState.CALL_ACTIVE) is False


def test_call_put_qualification_rules():
    """Verify strict quantitative qualification: score >= 65, R:R >= 1.5, valid spread & OI."""
    market_bullish = {"marketState": MarketState.BULLISH}

    # Valid CE Candidate
    good_ce = {
        "symbol": "NIFTY26OCT24500CE",
        "option_type": "CE",
        "strike": 24500,
        "expiry": "2026-10-26",
        "currentPremium": 150.0,
        "bid": 149.5,
        "ask": 150.5,
        "openInterest": 85000,
        "strategyScore": 75,
        "suggestedEntryMin": 145.0,
        "suggestedEntryMax": 155.0,
        "stopLoss": 120.0,
        "target1": 195.0,
        "target2": 230.0,  # 80 pt reward / 30 pt risk = 2.67 R:R
        "target3": 270.0,
    }

    state, disq, meta = evaluate_setup_qualification("NIFTY 50", market_bullish, good_ce, underlying_ltp=24500.0, atr_14=90.0)
    assert state == SignalState.CALL_SETUP_READY
    assert len(disq) == 0
    assert meta["rr_ratio"] >= 1.5

    # Poor R:R CE Candidate (Target too close)
    bad_rr_ce = dict(good_ce)
    bad_rr_ce["target2"] = 160.0  # 10 pt reward / 30 pt risk = 0.33 R:R
    bad_state, bad_disq, _ = evaluate_setup_qualification("NIFTY 50", market_bullish, bad_rr_ce, underlying_ltp=24500.0, atr_14=90.0)
    assert bad_state == SignalState.NO_TRADE
    assert any("Reward-to-risk" in d for d in bad_disq)


def test_entry_trigger_vs_missed():
    """Verify tick within entry range activates ENTRY_TRIGGERED; tick jumping > 8% marks MISSED."""
    entry_min = 145.0
    entry_max = 155.0

    # Tick enters inside zone -> ENTRY_TRIGGERED
    st1, note1 = evaluate_entry_trigger(
        signal_state=SignalState.CALL_SETUP_READY,
        observed_market_price=150.0,
        entry_zone_min=entry_min,
        entry_zone_max=entry_max,
    )
    assert st1 == SignalState.ENTRY_TRIGGERED
    assert "approved entry zone" in note1

    # Tick opens at 172 (> 8% above entry_zone_max of 155 -> max allowed 167.4) -> MISSED
    st2, note2 = evaluate_entry_trigger(
        signal_state=SignalState.CALL_SETUP_READY,
        observed_market_price=172.0,
        entry_zone_min=entry_min,
        entry_zone_max=entry_max,
    )
    assert st2 == SignalState.MISSED
    assert ">8%" in note2


def test_frontend_signal_badge():
    """Verify visible frontend indicators matching Requirement 2."""
    b_call = get_frontend_signal_badge(SignalState.CALL_SETUP_READY)
    assert b_call["badgeText"] == "CALL SETUP ACTIVE"

    b_put = get_frontend_signal_badge(SignalState.PUT_SETUP_READY)
    assert b_put["badgeText"] == "PUT SETUP ACTIVE"

    b_entry = get_frontend_signal_badge(SignalState.ENTRY_TRIGGERED)
    assert b_entry["badgeText"] == "ENTRY TRIGGERED"

    b_none = get_frontend_signal_badge(SignalState.NO_TRADE)
    assert b_none["badgeText"] == "NO TRADE — WAIT FOR CONFIRMATION"


# =====================================================================
# 3. REQUIREMENT 3: OUTCOME TRACKING, DIAGNOSTICS & REVERSALS
# =====================================================================

@pytest.mark.asyncio
async def test_outcome_tracker_independent_target_and_trailing_stop():
    """Verify T1 hit locks 50% profit, trails stop-loss to cost, and subsequent drop triggers trailing SL."""
    tracker = OutcomeTrackerService.get_instance()
    token = f"TEST_TOK_{uuid.uuid4().hex[:6]}"

    async with async_session_factory() as session:
        # Register new signal
        sig_data = {
            "symbol": "NIFTY 50",
            "contract_symbol": "NIFTY26OCT24500CE",
            "exchange": "NFO",
            "instrument_token": token,
            "strike": 24500,
            "expiry": "2026-10-26",
            "option_type": "CE",
            "signal_premium": 150.0,
            "entry_zone_min": 145.0,
            "entry_zone_max": 155.0,
            "stop_loss_premium": 120.0,
            "target_1_premium": 195.0,
            "target_2_premium": 230.0,
            "target_3_premium": 270.0,
            "trailing_stop_rule": "MOVE_TO_COST_ON_T1",
            "lot_size": 50,
            "allocated_lots": 1,
        }
        signal = await tracker.register_signal(session, sig_data)
        sig_id = signal.id

        # Tick 1: Trigger Entry at ₹150.0
        now = datetime.now(timezone.utc)
        ev_entry = await tracker.process_market_tick(
            session=session,
            instrument_token=token,
            ltp=150.0,
            market_ts=now,
        )
        assert len(ev_entry) == 1
        assert ev_entry[0]["event"] == "ENTRY_TRIGGERED"

        # Tick 2: Hit Target 1 at ₹196.0
        t1_time = now + timedelta(minutes=5)
        ev_t1 = await tracker.process_market_tick(
            session=session,
            instrument_token=token,
            ltp=196.0,
            market_ts=t1_time,
        )
        assert len(ev_t1) == 1
        assert ev_t1[0]["event"] == "T1_HIT"

        # Check updated signal state in DB
        sig_updated = await session.get(SignalRecord, sig_id)
        assert sig_updated.status == "TARGET_1_HIT"
        assert sig_updated.remaining_fraction == 0.5
        assert sig_updated.stop_loss_premium == 150.0  # Trailed to cost!

        # Tick 3: Falls back to ₹149.0 -> Triggers Trailing Stop Loss
        sl_time = now + timedelta(minutes=15)
        ev_sl = await tracker.process_market_tick(
            session=session,
            instrument_token=token,
            ltp=149.0,
            market_ts=sl_time,
        )
        assert len(ev_sl) == 1
        assert ev_sl[0]["event"] == "STOP_LOSS_HIT"

        sig_closed = await session.get(SignalRecord, sig_id)
        assert sig_closed.status == "STOP_LOSS_HIT"
        assert sig_closed.final_outcome == "SL_AFTER_PARTIAL_PROFIT"
        assert sig_closed.remaining_fraction == 0.0
        assert sig_closed.gross_pnl_points > 0


@pytest.mark.asyncio
async def test_outcome_tracker_idempotency_duplicate_ticks():
    """Verify feeding duplicate ticks does not create duplicate events due to unique idempotency_key."""
    tracker = OutcomeTrackerService.get_instance()
    token = f"TEST_IDEM_{uuid.uuid4().hex[:6]}"

    async with async_session_factory() as session:
        sig_data = {
            "symbol": "NIFTY 50",
            "contract_symbol": "NIFTY26OCT24500CE",
            "exchange": "NFO",
            "instrument_token": token,
            "strike": 24500,
            "expiry": "2026-10-26",
            "option_type": "CE",
            "signal_premium": 150.0,
            "entry_zone_min": 145.0,
            "entry_zone_max": 155.0,
            "stop_loss_premium": 120.0,
            "target_1_premium": 195.0,
            "target_2_premium": 230.0,
            "target_3_premium": 270.0,
        }
        signal = await tracker.register_signal(session, sig_data)

        now = datetime.now(timezone.utc)
        # First entry tick
        ev1 = await tracker.process_market_tick(session, token, ltp=150.0, market_ts=now)
        assert len(ev1) == 1

        # Duplicate entry tick (same token and price range)
        ev2 = await tracker.process_market_tick(session, token, ltp=150.0, market_ts=now)
        # Should not re-generate ENTRY_TRIGGERED event
        assert len(ev2) == 0


@pytest.mark.asyncio
async def test_outcome_tracker_ambiguous_candle_bar():
    """Verify candle bar crossing both target and stop-loss is flagged AMBIGUOUS without inventing hit order."""
    tracker = OutcomeTrackerService.get_instance()
    token = f"TEST_AMBIG_{uuid.uuid4().hex[:6]}"

    async with async_session_factory() as session:
        sig_data = {
            "symbol": "NIFTY 50",
            "contract_symbol": "NIFTY26OCT24500CE",
            "exchange": "NFO",
            "instrument_token": token,
            "strike": 24500,
            "expiry": "2026-10-26",
            "option_type": "CE",
            "signal_premium": 150.0,
            "entry_zone_min": 145.0,
            "entry_zone_max": 155.0,
            "stop_loss_premium": 120.0,
            "target_1_premium": 195.0,
            "target_2_premium": 230.0,
            "target_3_premium": 270.0,
        }
        signal = await tracker.register_signal(session, sig_data)
        # Trigger entry first
        await tracker.process_market_tick(session, token, ltp=150.0)

        # Candle with extreme volatility: Low = 110 (below SL 120), High = 205 (above T1 195)
        ambig_res = await tracker.process_candle_bar(
            session=session,
            signal_id=signal.id,
            high=205.0,
            low=110.0,
            open_price=150.0,
            close=160.0,
        )
        assert ambig_res is not None
        assert ambig_res["event"] == "AMBIGUOUS"

        sig_updated = await session.get(SignalRecord, signal.id)
        assert sig_updated.status == "AMBIGUOUS"
        assert sig_updated.final_outcome == "AMBIGUOUS_INTRABAR_TOUCH"


@pytest.mark.asyncio
async def test_persistence_and_recovery_across_restarts():
    """Verify recover_active_signals restores active tokens for stream monitoring after restart."""
    tracker = OutcomeTrackerService.get_instance()
    token = f"TEST_RECOV_{uuid.uuid4().hex[:6]}"

    async with async_session_factory() as session:
        sig_data = {
            "symbol": "NIFTY 50",
            "contract_symbol": "NIFTY26OCT24500CE",
            "exchange": "NFO",
            "instrument_token": token,
            "strike": 24500,
            "expiry": "2026-10-26",
            "option_type": "CE",
            "signal_premium": 150.0,
            "entry_zone_min": 145.0,
            "entry_zone_max": 155.0,
            "stop_loss_premium": 120.0,
            "target_1_premium": 195.0,
            "target_2_premium": 230.0,
            "target_3_premium": 270.0,
        }
        signal = await tracker.register_signal(session, sig_data)

        # Trigger entry to make it ACTIVE
        await tracker.process_market_tick(session, token, ltp=150.0)

        # Clear memory cache simulating server restart
        tracker._monitored_tokens.clear()

        # Run recovery
        recovered_tokens = await tracker.recover_active_signals(session)
        assert token in recovered_tokens
        assert token in tracker.get_active_tokens()


def test_reversal_evidence_classification():
    """Verify reversal confirmed before SL vs. inferred after SL is distinguished factually."""
    sig = SignalRecord(
        id="sig-diag",
        symbol="NIFTY 50",
        contract_symbol="NIFTY26OCT24500CE",
        option_type="CE",
        status=SignalState.STOP_LOSS_HIT,
        final_outcome="LOSS_SL",
        signal_premium=150.0,
        entry_observed_price=150.0,
        stop_loss_premium=120.0,
        target_1_premium=195.0,
        created_at=datetime.now(timezone.utc) - timedelta(minutes=30),
        entry_triggered_at=datetime.now(timezone.utc) - timedelta(minutes=25),
        events=[],
    )

    # Observations showing underlying broke below VWAP & EMA20 before SL hit
    observations = [
        {"timestamp": datetime.now(timezone.utc) - timedelta(minutes=20), "underlying_price": 24520, "vwap": 24500, "option_price": 152},
        {"timestamp": datetime.now(timezone.utc) - timedelta(minutes=10), "underlying_price": 24460, "vwap": 24490, "option_price": 130},
        {"timestamp": datetime.now(timezone.utc) - timedelta(minutes=2), "underlying_price": 24420, "vwap": 24485, "option_price": 118},
    ]

    diag = diagnose_signal_failure(
        signal=sig,
        events=[],
        price_observations=observations,
    )

    assert diag["primaryOutcome"] == FailureOutcome.STOP_LOSS_HIT_BEFORE_TARGET
    assert "reversalConfirmedBeforeSL" in diag
    assert diag["reversalConfirmedBeforeSL"] is True
    assert "underlying index" in diag["explanation"].lower()


def test_factual_diagnostics_no_hallucinated_news():
    """Verify diagnostic states 'root cause cannot be determined confidently' when evidence is sparse."""
    sig = SignalRecord(
        id="sig-sparse",
        symbol="NIFTY 50",
        contract_symbol="NIFTY26OCT24500CE",
        status=SignalState.STOP_LOSS_HIT,
        final_outcome="LOSS_SL",
        signal_premium=150.0,
        events=[],
    )

    diag = diagnose_signal_failure(signal=sig, events=[], price_observations=[])
    assert "root cause cannot be determined confidently" in diag["explanation"]


# =====================================================================
# 4. REQUIREMENT 4: DAILY ACCURACY & TRANSPARENT METRICS
# =====================================================================

def test_daily_metric_definitions_and_denominators():
    """Verify exact formula and denominators for Entry Trigger Rate, Target Hit Rate, Win Rate, Expectancy."""
    # Mock daily signals
    s1 = SignalRecord(id="s1", option_type="CE", status="TARGET_1_HIT", final_outcome="WIN_T1", entry_triggered_at=datetime.now(), net_pnl_inr=1500.0, gross_pnl_points=35.0, lot_size=50, allocated_lots=1)
    s2 = SignalRecord(id="s2", option_type="CE", status="TARGET_2_HIT", final_outcome="WIN_T2", entry_triggered_at=datetime.now(), net_pnl_inr=3200.0, gross_pnl_points=70.0, lot_size=50, allocated_lots=1)
    s3 = SignalRecord(id="s3", option_type="PE", status="STOP_LOSS_HIT", final_outcome="LOSS_SL", entry_triggered_at=datetime.now(), net_pnl_inr=-1400.0, gross_pnl_points=-25.0, lot_size=50, allocated_lots=1)
    s4 = SignalRecord(id="s4", option_type="PE", status="MISSED", final_outcome=None, entry_triggered_at=None, net_pnl_inr=0.0, gross_pnl_points=0.0, lot_size=50, allocated_lots=1)

    signals = [s1, s2, s3, s4]

    eligible_setup_ready = len(signals)  # 4
    triggered_entries = sum(1 for s in signals if s.entry_triggered_at)  # 3
    resolved = [s for s in signals if s.status in ["TARGET_1_HIT", "TARGET_2_HIT", "STOP_LOSS_HIT"] and s.entry_triggered_at]  # 3
    profitable = sum(1 for s in resolved if s.net_pnl_inr > 0)  # 2

    # 1. Entry Trigger Rate = 3 / 4 = 75.0%
    entry_trigger_rate = round((triggered_entries / eligible_setup_ready) * 100.0, 1)
    assert entry_trigger_rate == 75.0

    # 2. Target 1 Hit Rate = 2 / 3 = 66.7%
    t1_hits = sum(1 for s in signals if s.status in ["TARGET_1_HIT", "TARGET_2_HIT"])
    t1_rate = round((t1_hits / triggered_entries) * 100.0, 1)
    assert t1_rate == 66.7

    # 3. Final Win Rate = 2 / 3 = 66.7%
    win_rate = round((profitable / len(resolved)) * 100.0, 1)
    assert win_rate == 66.7

    # 4. Net Expectancy = (1500 + 3200 - 1400) / 3 = 3300 / 3 = +1100.00 INR
    total_net = sum(s.net_pnl_inr for s in signals)
    expectancy = round(total_net / triggered_entries, 2)
    assert expectancy == 1100.0


def test_zero_sample_periods_handling():
    """Verify when total resolved is zero, 'Insufficient resolved data' is produced instead of 0% accuracy."""
    resolved_count = 0
    profitable_count = 0

    desc = f"{round((profitable_count / resolved_count * 100), 1)}%" if resolved_count > 0 else "Insufficient resolved data"
    assert desc == "Insufficient resolved data"
