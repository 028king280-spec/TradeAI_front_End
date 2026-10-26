import pytest
import pandas as pd
from datetime import datetime, timedelta
from app.analysis.support_resistance import SupportResistanceEngine
from app.analysis.expected_range import ExpectedRangeEngine


@pytest.fixture
def sample_ohlcv():
    dates = [datetime(2026, 1, 1) + timedelta(days=i) for i in range(30)]
    records = []
    base = 1500.0
    for i, d in enumerate(dates):
        p = base + i * 2.0
        records.append({
            "timestamp": d,
            "open": p - 2.0,
            "high": p + 10.0,
            "low": p - 8.0,
            "close": p,
            "volume": 200000,
        })
    return pd.DataFrame(records)


def test_support_resistance_levels(sample_ohlcv):
    current_price = 1550.0
    atr = 20.0
    levels = SupportResistanceEngine.calculate_levels(sample_ohlcv, current_price, atr)

    labels = [lvl["label"] for lvl in levels]
    assert "Resistance 2" in labels
    assert "Resistance 1" in labels
    assert "Current" in labels
    assert "Support 1" in labels
    assert "Support 2" in labels
    assert "Support 3" in labels

    # Verify price ordering
    r2 = next(l["price"] for l in levels if l["label"] == "Resistance 2")
    r1 = next(l["price"] for l in levels if l["label"] == "Resistance 1")
    s1 = next(l["price"] for l in levels if l["label"] == "Support 1")
    s2 = next(l["price"] for l in levels if l["label"] == "Support 2")
    s3 = next(l["price"] for l in levels if l["label"] == "Support 3")

    assert r2 > r1 >= current_price or r1 > s1
    assert current_price >= s1 > s2 > s3


def test_expected_range_bounds():
    current_price = 1456.80
    open_price = 1450.0
    previous_close = 1445.0
    day_high = 1462.0
    day_low = 1440.0
    atr = 22.5
    vwap = 1454.0

    res = ExpectedRangeEngine.calculate(
        current_price=current_price,
        open_price=open_price,
        previous_close=previous_close,
        day_high=day_high,
        day_low=day_low,
        atr=atr,
        vwap=vwap,
        trend="Bullish",
        market_bias="BULLISH",
        rsi=62.5,
    )

    exp_high = res["expectedHigh"]
    exp_low = res["expectedLow"]
    price_range = res["priceRange"]

    # Boundary assertions
    assert exp_high["min"] <= exp_high["max"]
    assert exp_low["min"] <= exp_low["max"]
    assert exp_low["max"] < current_price < exp_high["min"]

    # Range extremes
    assert price_range["extremeLow"] < price_range["likelyLow"]
    assert price_range["likelyHigh"] < price_range["extremeHigh"]
