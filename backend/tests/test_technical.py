import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from app.analysis.technical import TechnicalAnalysisEngine


@pytest.fixture
def sample_daily_candles():
    dates = [datetime(2026, 1, 1) + timedelta(days=i) for i in range(100)]
    prices = [1000.0]
    rng = np.random.RandomState(42)
    for _ in range(99):
        prices.append(prices[-1] * (1 + rng.normal(0.001, 0.015)))

    records = []
    for d, p in zip(dates, prices):
        records.append({
            "timestamp": d,
            "open": p * 0.998,
            "high": p * 1.012,
            "low": p * 0.989,
            "close": p,
            "volume": int(rng.uniform(100000, 500000)),
        })
    return pd.DataFrame(records)


def test_rsi_calculation(sample_daily_candles):
    rsi = TechnicalAnalysisEngine.calculate_rsi(sample_daily_candles["close"], 14)
    assert len(rsi) == len(sample_daily_candles)
    last_rsi = float(rsi.iloc[-1])
    assert 0.0 <= last_rsi <= 100.0


def test_macd_calculation(sample_daily_candles):
    macd_dict = TechnicalAnalysisEngine.calculate_macd(sample_daily_candles["close"])
    assert "macd" in macd_dict
    assert "signal" in macd_dict
    assert "histogram" in macd_dict
    assert len(macd_dict["macd"]) == len(sample_daily_candles)


def test_ema_calculation(sample_daily_candles):
    ema20 = TechnicalAnalysisEngine.calculate_ema(sample_daily_candles["close"], 20)
    assert len(ema20) == len(sample_daily_candles)
    assert not pd.isna(ema20.iloc[-1])


def test_atr_calculation(sample_daily_candles):
    atr = TechnicalAnalysisEngine.calculate_atr(sample_daily_candles, 14)
    last_atr = float(atr.iloc[-1])
    assert last_atr > 0.0


def test_full_analysis_snapshot(sample_daily_candles):
    analysis = TechnicalAnalysisEngine.analyze(sample_daily_candles)
    assert "rsi" in analysis
    assert "macd" in analysis
    assert "ema20" in analysis
    assert "vwap" in analysis
    assert "atr" in analysis
    assert "volume" in analysis
    assert "momentum" in analysis
    assert "priceStructure" in analysis

    assert analysis["rsi"]["signal"] in ["Bullish", "Bearish", "Neutral"]
    assert analysis["ema20"]["signal"] in ["Bullish", "Bearish"]
