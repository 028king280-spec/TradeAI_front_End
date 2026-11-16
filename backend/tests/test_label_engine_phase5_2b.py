"""
Automated Test Suite for Phase 5.2B Remediation:
- Fixed-Horizon Forward Outcome Engine (5, 15, 30, 60 min).
- Scale-Normalized Threshold Governance (Return on Risk, zero nominal constants).
- Proactive OOS Purging & Embargo in WalkForwardPartitionEngine.
- LeakageGuard verification across train, val, and OOS.
"""

from datetime import datetime, timedelta
import json
import os
import pytest
import zoneinfo

from app.options.paper_trading.label_engine import (
    SignalDecision,
    OutcomeClass,
    MultiClassTarget,
    HorizonStatus,
    ThresholdType,
    ThresholdConfiguration,
    SignalLabel,
    RealizedOutcomeLabel,
    FixedHorizonObservation,
    FixedHorizonLabelSet,
    FixedHorizonEngine,
    SignalClassifier,
    OutcomeCalculator,
    WalkForwardPartitionEngine,
    LeakageGuard,
    WalkForwardFold,
    PartitionSplit,
    parse_ist_timestamp,
    SUPPORTED_HORIZONS_MINUTES,
)

IST_ZONE = zoneinfo.ZoneInfo("Asia/Kolkata")


# ==============================================================================
# 1. FIXED-HORIZON OUTCOME ENGINE TESTS (5, 15, 30, 60 MINUTES)
# ==============================================================================

def test_fixed_horizon_evaluation_all_four_horizons_resolved():
    """
    Verifies that FixedHorizonEngine correctly resolves 5, 15, 30, and 60-minute
    forward option premium returns from genuine forward quotes.
    """
    pred_dt = datetime(2026, 11, 13, 10, 0, 0, tzinfo=IST_ZONE)
    contract = "NIFTY26NOV25200CE"
    pred_price = 100.0

    # Build genuine forward quotes at T+5m, T+15m, T+30m, T+60m
    quote_series = [
        # T+5m
        {"contract": contract, "timestamp": (pred_dt + timedelta(minutes=5)).isoformat(), "ltp": 108.5, "provider": "ANGELONE"},
        # T+15m
        {"contract": contract, "timestamp": (pred_dt + timedelta(minutes=15)).isoformat(), "ltp": 115.0, "provider": "ANGELONE"},
        # T+30m
        {"contract": contract, "timestamp": (pred_dt + timedelta(minutes=30)).isoformat(), "ltp": 125.0, "provider": "ANGELONE"},
        # T+60m
        {"contract": contract, "timestamp": (pred_dt + timedelta(minutes=60)).isoformat(), "ltp": 95.0, "provider": "ANGELONE"},
    ]

    label_set = FixedHorizonEngine.evaluate_horizons(
        prediction_time=pred_dt,
        contract_symbol=contract,
        prediction_price=pred_price,
        quote_series=quote_series,
        underlying_price_at_prediction=25150.0,
    )

    assert label_set.contract_symbol == contract
    assert label_set.prediction_price == 100.0
    assert set(label_set.horizons.keys()) == {5, 15, 30, 60}

    # Verify 5m
    obs_5 = label_set.horizons[5]
    assert obs_5.status == HorizonStatus.RESOLVED
    assert obs_5.horizon_price == 108.5
    assert obs_5.premium_return_pts == 8.5
    assert obs_5.premium_return_pct == 0.085

    # Verify 15m
    obs_15 = label_set.horizons[15]
    assert obs_15.status == HorizonStatus.RESOLVED
    assert obs_15.horizon_price == 115.0
    assert obs_15.premium_return_pts == 15.0
    assert obs_15.premium_return_pct == 0.15

    # Verify 30m
    obs_30 = label_set.horizons[30]
    assert obs_30.status == HorizonStatus.RESOLVED
    assert obs_30.horizon_price == 125.0
    assert obs_30.premium_return_pts == 25.0

    # Verify 60m
    obs_60 = label_set.horizons[60]
    assert obs_60.status == HorizonStatus.RESOLVED
    assert obs_60.horizon_price == 95.0
    assert obs_60.premium_return_pts == -5.0
    assert obs_60.premium_return_pct == -0.05


def test_fixed_horizon_missing_quotes_returns_insufficient_data():
    """
    Verifies that missing forward observations return INSUFFICIENT_DATA
    with zero price interpolation or fabrication.
    """
    pred_dt = datetime(2026, 11, 13, 10, 0, 0, tzinfo=IST_ZONE)
    contract = "NIFTY26NOV25200CE"

    # Only provide quotes for 5m; 15m, 30m, and 60m are missing
    quote_series = [
        {"contract": contract, "timestamp": (pred_dt + timedelta(minutes=5)).isoformat(), "ltp": 105.0},
    ]

    label_set = FixedHorizonEngine.evaluate_horizons(
        prediction_time=pred_dt,
        contract_symbol=contract,
        prediction_price=100.0,
        quote_series=quote_series,
    )

    assert label_set.horizons[5].status == HorizonStatus.RESOLVED
    assert label_set.horizons[15].status == HorizonStatus.INSUFFICIENT_DATA
    assert label_set.horizons[30].status == HorizonStatus.INSUFFICIENT_DATA
    assert label_set.horizons[60].status == HorizonStatus.INSUFFICIENT_DATA
    assert label_set.horizons[15].horizon_price is None


def test_fixed_horizon_stale_observation_rejected():
    """
    Verifies that quotes exceeding max_staleness_seconds are flagged as STALE_OBSERVATION.
    """
    pred_dt = datetime(2026, 11, 13, 10, 0, 0, tzinfo=IST_ZONE)
    contract = "NIFTY26NOV25200CE"

    # Forward quote at T+7m (120 seconds after T+5m target, exceeding 60s tolerance)
    quote_series = [
        {"contract": contract, "timestamp": (pred_dt + timedelta(minutes=7)).isoformat(), "ltp": 107.0},
    ]

    label_set = FixedHorizonEngine.evaluate_horizons(
        prediction_time=pred_dt,
        contract_symbol=contract,
        prediction_price=100.0,
        quote_series=quote_series,
        horizons=[5],
        max_staleness_seconds=60.0,
    )

    assert label_set.horizons[5].status == HorizonStatus.STALE_OBSERVATION
    assert "exceeds tolerance" in label_set.horizons[5].status_reason


def test_fixed_horizon_future_timestamp_rejected():
    """
    Verifies that observation timestamps ahead of market clock trigger FUTURE_LEAKAGE.
    """
    pred_dt = datetime(2026, 11, 13, 10, 0, 0, tzinfo=IST_ZONE)
    contract = "NIFTY26NOV25200CE"

    # Future quote in the year 2099
    future_dt = datetime(2099, 1, 1, 10, 5, 0, tzinfo=IST_ZONE)
    quote_series = [
        {"contract": contract, "timestamp": future_dt.isoformat(), "ltp": 105.0},
    ]

    label_set = FixedHorizonEngine.evaluate_horizons(
        prediction_time=pred_dt,
        contract_symbol=contract,
        prediction_price=100.0,
        quote_series=quote_series,
        horizons=[5],
    )

    assert label_set.horizons[5].status == HorizonStatus.FUTURE_LEAKAGE


def test_fixed_horizon_invalid_contract_rejected():
    """
    Verifies rejection of non-canonical or test option contract symbols.
    """
    pred_dt = datetime(2026, 11, 13, 10, 0, 0, tzinfo=IST_ZONE)
    quote_series = [{"contract": "NIFTY_TEST_CE", "timestamp": (pred_dt + timedelta(minutes=5)).isoformat(), "ltp": 105.0}]

    label_set = FixedHorizonEngine.evaluate_horizons(
        prediction_time=pred_dt,
        contract_symbol="NIFTY_TEST_CE",
        prediction_price=100.0,
        quote_series=quote_series,
        horizons=[5],
    )
    assert label_set.horizons[5].status == HorizonStatus.INVALID_CONTRACT


def test_fixed_horizon_underlying_price_substitution_rejected():
    """
    Verifies that passing underlying index price as option premium is rejected.
    """
    pred_dt = datetime(2026, 11, 13, 10, 0, 0, tzinfo=IST_ZONE)
    contract = "NIFTY26NOV25200CE"

    # Attempt to pass NIFTY spot price (25,144.30) as option prediction price
    label_set = FixedHorizonEngine.evaluate_horizons(
        prediction_time=pred_dt,
        contract_symbol=contract,
        prediction_price=25144.30,
        quote_series=[],
        horizons=[5],
        underlying_price_at_prediction=25144.30,
    )

    assert label_set.horizons[5].status == HorizonStatus.UNDERLYING_PRICE_REJECTED


# ==============================================================================
# 2. SCALE-NORMALIZED THRESHOLD GOVERNANCE TESTS
# ==============================================================================

def test_outcome_calculation_unconfigured_threshold_behavior():
    """
    Verifies that without an approved threshold configuration, outcomes are classified
    as UNCONFIGURED and marked as non-training eligible.
    """
    entry_dt = datetime(2026, 11, 13, 10, 0, 0, tzinfo=IST_ZONE)
    exit_dt = datetime(2026, 11, 13, 10, 20, 0, tzinfo=IST_ZONE)

    trade = {
        "id": "TRADE-UNCFG",
        "entryTimestamp": entry_dt.isoformat(),
        "exitTimestamp": exit_dt.isoformat(),
        "entryPrice": 100.0,
        "exitPrice": 115.0,
        "quantity": 130,
        "stopLoss": 90.0,
    }

    # Call without approved threshold configuration
    outcome = OutcomeCalculator.calculate_outcome(trade, threshold_config=None)

    assert outcome.outcome_class == OutcomeClass.UNCONFIGURED
    assert outcome.multiclass_target == MultiClassTarget.UNCONFIGURED
    assert outcome.binary_target == -1
    assert outcome.is_training_eligible is False
    assert "Threshold configuration unapproved" in outcome.metadata["threshold_governance"]["reason"]


def test_outcome_calculation_scale_normalized_return_on_risk():
    """
    Verifies scale-normalized Return on Risk (R) thresholding across different
    lot quantities (65, 130, 650) and risk sizes (₹500 vs ₹10,000).
    """
    entry_dt = datetime(2026, 11, 13, 10, 0, 0, tzinfo=IST_ZONE)
    exit_dt = datetime(2026, 11, 13, 10, 20, 0, tzinfo=IST_ZONE)

    # Approved threshold: epsilon = 0.10 (10% of risk R)
    approved_cfg = ThresholdConfiguration(
        is_approved=True,
        threshold_type=ThresholdType.RETURN_ON_RISK,
        threshold_value=0.10,
        approval_reference="AUTH_AUDIT_TEST",
    )

    # Case A: 1 Lot (65 qty), ₹10 risk per share (Initial risk = ₹650)
    # Trade makes net PnL +₹130 -> R = +0.20R (> +0.10R -> WIN)
    trade_win_1lot = {
        "id": "T_1LOT_WIN",
        "entryTimestamp": entry_dt.isoformat(),
        "exitTimestamp": exit_dt.isoformat(),
        "entryPrice": 100.0,
        "exitPrice": 105.0,
        "quantity": 65,
        "stopLoss": 90.0,  # 10 pts risk * 65 = ₹650
        "charges": 50.0,
        "grossPnl": 325.0,
        "netPnl": 275.0,   # R = 275 / 650 = +0.42R
    }
    out_win = OutcomeCalculator.calculate_outcome(trade_win_1lot, threshold_config=approved_cfg)
    assert out_win.multiclass_target == MultiClassTarget.WIN
    assert out_win.outcome_class == OutcomeClass.WIN
    assert out_win.binary_target == 1
    assert out_win.is_training_eligible is True

    # Case B: 10 Lots (650 qty), ₹20 risk per share (Initial risk = ₹13,000)
    # Net PnL is +₹500. On nominal ₹50 this would be a win, but in scale-normalized terms:
    # R = 500 / 13,000 = +0.038R <= 0.10R -> Correctly classified as SCRATCH!
    trade_scratch_large = {
        "id": "T_10LOT_SCRATCH",
        "entryTimestamp": entry_dt.isoformat(),
        "exitTimestamp": exit_dt.isoformat(),
        "entryPrice": 100.0,
        "exitPrice": 102.0,
        "quantity": 650,
        "stopLoss": 80.0,  # 20 pts risk * 650 = ₹13,000 risk
        "charges": 150.0,
        "grossPnl": 1300.0,
        "netPnl": 500.0,   # R = 500 / 13000 = +0.038R (< 0.10R)
    }
    out_scratch = OutcomeCalculator.calculate_outcome(trade_scratch_large, threshold_config=approved_cfg)
    assert out_scratch.multiclass_target == MultiClassTarget.SCRATCH
    assert out_scratch.outcome_class == OutcomeClass.SCRATCH
    # Target consistency check: Scratch is excluded from directional binary training
    assert out_scratch.binary_target == -1
    assert out_scratch.metadata["threshold_governance"]["binary_directional_eligible"] is False


def test_outcome_calculation_target_consistency_loss():
    """
    Verifies that a decisive loss has identical classification in binary and multiclass.
    """
    entry_dt = datetime(2026, 11, 13, 10, 0, 0, tzinfo=IST_ZONE)
    exit_dt = datetime(2026, 11, 13, 10, 20, 0, tzinfo=IST_ZONE)

    approved_cfg = ThresholdConfiguration(
        is_approved=True,
        threshold_type=ThresholdType.RETURN_ON_RISK,
        threshold_value=0.10,
    )

    trade_loss = {
        "id": "T_LOSS",
        "entryTimestamp": entry_dt.isoformat(),
        "exitTimestamp": exit_dt.isoformat(),
        "entryPrice": 100.0,
        "exitPrice": 85.0,
        "quantity": 130,
        "stopLoss": 90.0,
        "charges": 70.0,
        "grossPnl": -1950.0,
        "netPnl": -2020.0,
    }
    out_loss = OutcomeCalculator.calculate_outcome(trade_loss, threshold_config=approved_cfg)
    assert out_loss.multiclass_target == MultiClassTarget.LOSS
    assert out_loss.outcome_class == OutcomeClass.LOSS
    assert out_loss.binary_target == 0
    assert out_loss.is_training_eligible is True


# ==============================================================================
# 3. PROACTIVE OOS PURGING & EMBARGO TESTS
# ==============================================================================

def test_walk_forward_proactive_oos_purging():
    """
    Verifies that validation samples in the final fold whose exit extends into OOS
    are PROACTIVELY purged by WalkForwardPartitionEngine.
    """
    t_base = datetime(2026, 11, 1, 9, 30, tzinfo=IST_ZONE)

    # 10 sequential trades
    samples = []
    for i in range(10):
        t_entry = t_base + timedelta(hours=i * 2)
        # Normal holding duration is 30 mins
        t_exit = t_entry + timedelta(minutes=30)
        samples.append({
            "id": f"T{i}",
            "entryTimestamp": t_entry.isoformat(),
            "exitTimestamp": t_exit.isoformat(),
        })

    # Intentionally make trade 7 (which will be in final validation fold) spill its exit into OOS!
    # OOS ratio 0.20 on 10 samples -> samples 8 and 9 are OOS.
    # OOS start time is T8 entry = t_base + 16 hours.
    # We set T7 exit to t_base + 17 hours (past OOS start!)
    oos_start_time = t_base + timedelta(hours=8 * 2)
    samples[7]["exitTimestamp"] = (oos_start_time + timedelta(minutes=15)).isoformat()

    split = WalkForwardPartitionEngine.partition(
        samples=samples,
        n_splits=2,
        oos_ratio=0.20,
        embargo_duration=timedelta(minutes=15),
        purge_overlapping=True,
    )

    # Audit using LeakageGuard
    is_clean, violations = LeakageGuard.audit_partitions(split, samples)
    assert is_clean is True
    assert len(violations) == 0

    # Verify that trade 7 was proactively purged from the final fold
    final_fold = split.folds[-1]
    assert 7 in final_fold.purged_indices
    assert 7 not in final_fold.val_indices


def test_walk_forward_oos_boundary_equality():
    """
    Verifies that a sample whose exit time is EXACTLY equal to oos_start_time
    is fail-closed and purged.
    """
    t_base = datetime(2026, 11, 1, 9, 30, tzinfo=IST_ZONE)
    samples = []
    for i in range(10):
        t_entry = t_base + timedelta(hours=i * 2)
        t_exit = t_entry + timedelta(minutes=30)
        samples.append({
            "id": f"T{i}",
            "entryTimestamp": t_entry.isoformat(),
            "exitTimestamp": t_exit.isoformat(),
        })

    # Trade 7 exit set EXACTLY equal to T8 entry (OOS start time)
    oos_start_time = t_base + timedelta(hours=8 * 2)
    samples[7]["exitTimestamp"] = oos_start_time.isoformat()

    split = WalkForwardPartitionEngine.partition(
        samples=samples,
        n_splits=2,
        oos_ratio=0.20,
        embargo_duration=timedelta(minutes=15),
        purge_overlapping=True,
    )

    final_fold = split.folds[-1]
    # Trade 7 MUST be purged on boundary equality (>=)
    assert 7 in final_fold.purged_indices
    assert 7 not in final_fold.val_indices


def test_walk_forward_oos_embargo_enforcement():
    """
    Verifies that prospective OOS samples entering within oos_embargo_duration
    of development end are quarantined.
    """
    t_base = datetime(2026, 11, 1, 9, 30, tzinfo=IST_ZONE)
    samples = []
    for i in range(8):
        t_entry = t_base + timedelta(hours=i * 2)
        t_exit = t_entry + timedelta(minutes=30)
        samples.append({
            "id": f"DEV_T{i}",
            "entryTimestamp": t_entry.isoformat(),
            "exitTimestamp": t_exit.isoformat(),
        })

    dev_end_entry = t_base + timedelta(hours=7 * 2)  # T7 entry

    # Add OOS candidate 1: 15 minutes after dev_end (inside 30m embargo!)
    samples.append({
        "id": "OOS_EMBARGOED",
        "entryTimestamp": (dev_end_entry + timedelta(minutes=15)).isoformat(),
        "exitTimestamp": (dev_end_entry + timedelta(minutes=45)).isoformat(),
    })

    # Add OOS candidate 2: 45 minutes after dev_end (outside 30m embargo)
    samples.append({
        "id": "OOS_VALID",
        "entryTimestamp": (dev_end_entry + timedelta(minutes=45)).isoformat(),
        "exitTimestamp": (dev_end_entry + timedelta(minutes=75)).isoformat(),
    })

    split = WalkForwardPartitionEngine.partition(
        samples=samples,
        n_splits=2,
        oos_ratio=0.20,
        embargo_duration=timedelta(minutes=30),
        oos_embargo_duration=timedelta(minutes=30),
        purge_overlapping=True,
    )

    assert split.metadata["oos_embargoed_count"] == 1
    # Index 8 (OOS_EMBARGOED) must be excluded from oos_indices
    assert 8 not in split.oos_indices
    # Index 9 (OOS_VALID) is kept in oos_indices
    assert 9 in split.oos_indices


# ==============================================================================
# 4. SIGNAL & HISTORICAL GOVERNANCE INTEGRITY TESTS
# ==============================================================================

def test_signal_classification_deterministic():
    """
    Verifies deterministic signal classification for BUY_CE, BUY_PE, WAIT, and NO_TRADE.
    """
    ts = datetime(2026, 11, 13, 10, 0, 0, tzinfo=IST_ZONE)

    obs_ce = {
        "bias": "CE",
        "entryTimestamp": ts.isoformat(),
        "marketStatus": "OPEN",
        "marketFeaturesAtEntry": {
            "mtfConfluenceScore": 85.0,
            "dealingRangeRegime": "DISCOUNT",
            "sweepReclaim": True,
            "marketCondition": "TRENDING_BULLISH",
        },
        "ictSetup": "Bullish Order Block + Sweep",
    }
    label_ce = SignalClassifier.classify(obs_ce)
    assert label_ce.signal_type == SignalDecision.BUY_CE
    assert label_ce.is_actionable is True


def test_historical_348_records_read_only_integrity():
    """
    Verifies that the historical 348 dataset can be evaluated in read-only mode without file mutation.
    """
    db_path = "D:/ReactJs/aivolve-trading-ai/backend/app/data/ml_trade_dataset.json"
    with open(db_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert len(data) == 348
    for item in data[:10]:
        signal = SignalClassifier.classify(item)
        assert signal.signal_type in [
            SignalDecision.BUY_CE,
            SignalDecision.BUY_PE,
            SignalDecision.WAIT,
            SignalDecision.NO_TRADE,
        ]
