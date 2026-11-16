import pytest
import math
from datetime import datetime, timedelta
import zoneinfo

from app.options.paper_trading.feature_pipeline import (
    FeaturePipelineValidator,
    FeatureValidationResult,
    EXPECTED_FEATURE_NAMES,
    SCHEMA_VERSION,
)
from app.options.paper_trading.ml_feedback_engine import MLFeedbackEngine
from app.data.market_calendar import MarketCalendar

IST_ZONE = zoneinfo.ZoneInfo("Asia/Kolkata")


def create_valid_trade_payload():
    return {
        "id": "PT-VAL-001",
        "contractSymbol": "NIFTY17NOV2625150CE",
        "bias": "CE",
        "spread": 1.0,
        "entryTimestamp": "13 Nov 2026, 02:30 PM IST",
        "netPnl": 2500.0,
        "strategy": "Model A (Liquidity Sweep & Retest)",
        "marketFeaturesAtEntry": {
            "greeks": {
                "iv": 0.128,
                "delta": 0.512,
                "theta": -11.6,
                "gamma": 0.00065,
            },
            "vix": 13.5,
            "atr": 97.0,
            "vwapDistancePct": 0.0015,
            "dealingRangePct": 38.0,
            "mtfConfluenceScore": 88.0,
            "sweepReclaim": True,
            "displacementRatio": 1.65,
            "fvgGapPts": 18.5,
            "pcr": 1.15,
            "marketCondition": "Trending",
        },
    }


def test_valid_production_feature_extraction():
    trade = create_valid_trade_payload()
    res = FeaturePipelineValidator.validate_and_extract(trade, is_production_mode=True, strict_session_check=False)
    assert res.is_valid is True
    assert len(res.feature_vector) == 14
    assert res.error_code is None
    assert res.metadata["schema_version"] == SCHEMA_VERSION
    assert res.metadata["trade_id"] == "PT-VAL-001"
    # IV, Delta, Theta, Gamma
    assert res.feature_vector[0] == 0.128
    assert res.feature_vector[1] == 0.512
    assert res.feature_vector[2] == -11.6
    assert res.feature_vector[3] == 0.00065


def test_empty_market_features_fails_closed():
    trade = create_valid_trade_payload()
    trade["marketFeaturesAtEntry"] = {}
    res = FeaturePipelineValidator.validate_and_extract(trade, is_production_mode=True)
    assert res.is_valid is False
    assert res.error_code == "FEATURE_EXTRACTION_FAILED"
    assert any("empty or missing" in r for r in res.rejection_reasons)

    # MLFeedbackEngine.extract_production_features must raise ValueError
    with pytest.raises(ValueError, match="FEATURE_EXTRACTION_FAILED"):
        MLFeedbackEngine.extract_production_features(trade)


def test_missing_mandatory_greek_fails_closed():
    trade = create_valid_trade_payload()
    del trade["marketFeaturesAtEntry"]["greeks"]["iv"]
    res = FeaturePipelineValidator.validate_and_extract(trade, is_production_mode=True)
    assert res.is_valid is False
    assert any("iv' is missing" in r for r in res.rejection_reasons)


def test_nan_or_inf_feature_fails_closed():
    trade = create_valid_trade_payload()
    trade["marketFeaturesAtEntry"]["vix"] = float("nan")
    res = FeaturePipelineValidator.validate_and_extract(trade, is_production_mode=True)
    assert res.is_valid is False
    assert any("NaN or Infinite" in r for r in res.rejection_reasons)

    trade["marketFeaturesAtEntry"]["vix"] = float("inf")
    res2 = FeaturePipelineValidator.validate_and_extract(trade, is_production_mode=True)
    assert res2.is_valid is False
    assert any("NaN or Infinite" in r for r in res2.rejection_reasons)


def test_identical_fallback_vector_rejected():
    trade = create_valid_trade_payload()
    # Populate with the exact known default fallback pattern
    trade["marketFeaturesAtEntry"] = {
        "greeks": {"iv": 0.14, "delta": 0.5, "theta": -12.0, "gamma": 0.002},
        "spread": 1.2,
        "vix": 13.5,
        "atr": 110.0,
        "vwapDistancePct": 0.002,
        "dealingRangePct": 35.0,
        "mtfConfluenceScore": 85.0,
        "sweepReclaim": True,
        "displacementRatio": 1.5,
        "fvgGapPts": 20.0,
        "pcr": 1.1,
    }
    trade["spread"] = 1.2
    res = FeaturePipelineValidator.validate_and_extract(trade, is_production_mode=True)
    assert res.is_valid is False
    assert any("Identical artificial fallback feature vector" in r for r in res.rejection_reasons)


def test_delta_bounds_rejection():
    trade = create_valid_trade_payload()
    # Call delta must be between 0.0 and 1.0
    trade["marketFeaturesAtEntry"]["greeks"]["delta"] = 1.25
    res = FeaturePipelineValidator.validate_and_extract(trade, is_production_mode=True)
    assert res.is_valid is False
    assert any("Call delta out of theoretical bounds" in r for r in res.rejection_reasons)

    # Put delta must be between -1.0 and 0.0
    trade["bias"] = "PE"
    trade["marketFeaturesAtEntry"]["greeks"]["delta"] = 0.50
    res2 = FeaturePipelineValidator.validate_and_extract(trade, is_production_mode=True)
    assert res2.is_valid is False
    assert any("Put delta out of theoretical bounds" in r for r in res2.rejection_reasons)


def test_test_contract_symbol_rejected_in_production():
    trade = create_valid_trade_payload()
    trade["contractSymbol"] = "NIFTY_TEST_CONTRACT_CE"
    res = FeaturePipelineValidator.validate_and_extract(trade, is_production_mode=True)
    assert res.is_valid is False
    assert any("Test contract detected in production pipeline" in r for r in res.rejection_reasons)


def test_out_of_hours_session_rejected_in_production():
    trade = create_valid_trade_payload()
    trade["entryTimestamp"] = "13 Nov 2026, 10:30 PM IST"
    res = FeaturePipelineValidator.validate_and_extract(trade, is_production_mode=True, strict_session_check=True)
    assert res.is_valid is False
    assert any("outside regular exchange trading hours" in r for r in res.rejection_reasons)


def test_future_timestamp_leakage_rejected():
    trade = create_valid_trade_payload()
    future_time = MarketCalendar.now_ist() + timedelta(minutes=30)
    trade["entryTimestamp"] = future_time.strftime("%d %b %Y, %I:%M %p IST")
    res = FeaturePipelineValidator.validate_and_extract(trade, is_production_mode=True, strict_session_check=False)
    assert res.is_valid is False
    assert any("Future timestamp leakage detected" in r for r in res.rejection_reasons)


def test_production_dataset_isolation_and_deduplication(tmp_path):
    test_prod_file = str(tmp_path / "isolated_production_dataset.json")
    trade = create_valid_trade_payload()

    # 1. Record first sample -> Success
    res1 = MLFeedbackEngine.record_production_sample(
        trade=trade,
        production_dataset_path=test_prod_file,
    )
    assert res1["success"] is True
    assert res1["totalProductionSamples"] == 1
    assert res1["sample"]["schemaVersion"] == "2.0.0"
    assert res1["sample"]["provenance"]["source"] == "VERIFIED_LIVE_PAPER"

    # 2. Record duplicate tradeId -> Rejected
    res2 = MLFeedbackEngine.record_production_sample(
        trade=trade,
        production_dataset_path=test_prod_file,
    )
    assert res2["success"] is False
    assert res2["error"] == "DUPLICATE_SAMPLE_REJECTED"


def test_backward_compatibility_preserved_with_legacy_extract():
    # Legacy extraction must continue to work without crashing for existing test fixtures
    mock_legacy_trade = {
        "id": "PT-LEGACY-001",
        "bias": "CE",
        "marketFeaturesAtEntry": {}
    }
    vec = MLFeedbackEngine.extract_features(mock_legacy_trade, strict_mode=False)
    assert len(vec) == 14
    assert vec[0] == 0.14  # IV fallback preserved for legacy unit fixtures

