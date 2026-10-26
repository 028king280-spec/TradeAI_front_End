import pytest
import numpy as np
import pandas as pd

from app.quant.indicators import TechnicalIndicators
from app.quant.momentum import MomentumAnalyzer
from app.quant.volatility import VolatilityAnalyzer
from app.quant.volume import VolumeAnalyzer
from app.quant.price_action import PriceActionAnalyzer
from app.quant.support_resistance import SupportResistanceEngine
from app.quant.market_regime import MarketRegimeEngine
from app.quant.sector_strength import SectorStrengthEngine
from app.quant.expected_range import ExpectedRangeEngine
from app.quant.probability import ProbabilityEngine
from app.quant.scoring import ScoringEngine
from app.quant.qualification import QualificationEngine
from app.ml.backtesting import BacktestEngine
from app.ml.registry import ModelRegistry, ModelStatus


@pytest.fixture
def sample_ohlcv_df():
    # 50 simulated candles with realistic prices
    np.random.seed(42)
    n = 60
    base = 1450.0
    returns = np.random.normal(0.001, 0.012, n)
    prices = base * np.cumprod(1 + returns)

    highs = prices * (1 + np.random.uniform(0.002, 0.008, n))
    lows = prices * (1 - np.random.uniform(0.002, 0.008, n))
    opens = (highs + lows) / 2.0
    volumes = np.random.randint(50000, 500000, n)
    dates = pd.date_range("2026-01-01", periods=n, freq="D")

    return pd.DataFrame({
        "timestamp": dates,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": prices,
        "volume": volumes,
    })


def test_quant_indicators(sample_ohlcv_df):
    indicators = TechnicalIndicators.compute_all_indicators(sample_ohlcv_df)
    assert "rsi" in indicators
    assert "macd" in indicators
    assert "ema20" in indicators
    assert "vwap" in indicators
    assert "atr" in indicators

    rsi_val = indicators["rsi"]["currentValue"]
    assert 0 <= rsi_val <= 100
    assert indicators["rsi"]["signal"] in ["Bullish", "Bearish", "Neutral"]

    atr_val = indicators["atr"]["currentValue"]
    assert atr_val > 0


def test_quant_momentum(sample_ohlcv_df):
    mom = MomentumAnalyzer.analyze_momentum(sample_ohlcv_df)
    assert "score" in mom
    assert 0 <= mom["score"] <= 100
    assert "roc10" in mom
    assert "stoch_k" in mom
    assert mom["bias"] in ["Bullish", "Bearish", "Neutral"]


def test_quant_volatility(sample_ohlcv_df):
    vol = VolatilityAnalyzer.analyze_volatility(sample_ohlcv_df)
    assert "annualized_hv" in vol
    assert vol["annualized_hv"] > 0
    assert "regime" in vol
    assert vol["regime"] in ["Low", "Moderate", "High", "Elevated", "Extreme"]
    assert "atr_percent" in vol


def test_quant_volume(sample_ohlcv_df):
    v = VolumeAnalyzer.analyze_volume(sample_ohlcv_df)
    assert "volume_ratio" in v
    assert v["volume_ratio"] > 0
    assert "score" in v
    assert 0 <= v["score"] <= 10


def test_quant_price_action(sample_ohlcv_df):
    pa = PriceActionAnalyzer.analyze_structure(sample_ohlcv_df)
    assert "pdh" in pa
    assert "pdl" in pa
    assert pa["pdh"] >= pa["pdl"]
    assert "structure" in pa
    assert "trend_strength" in pa


def test_quant_support_resistance(sample_ohlcv_df):
    levels = SupportResistanceEngine.calculate_levels(sample_ohlcv_df)
    assert len(levels) == 6
    labels = [lvl["label"] for lvl in levels]
    assert "Resistance 2" in labels
    assert "Resistance 1" in labels
    assert "Current" in labels
    assert "Support 1" in labels
    assert "Support 2" in labels
    assert "Support 3" in labels

    # Monotonic price check
    r2 = next(l["price"] for l in levels if l["label"] == "Resistance 2")
    r1 = next(l["price"] for l in levels if l["label"] == "Resistance 1")
    s1 = next(l["price"] for l in levels if l["label"] == "Support 1")
    s2 = next(l["price"] for l in levels if l["label"] == "Support 2")
    assert r2 >= r1 >= s1 >= s2


def test_quant_market_regime():
    indices = [
        {"symbol": "NIFTY 50", "name": "NIFTY 50", "changePercent": 0.85, "currentValue": 24500.0},
        {"symbol": "BANK NIFTY", "name": "BANK NIFTY", "changePercent": 0.65, "currentValue": 52300.0},
        {"symbol": "INDIA VIX", "name": "INDIA VIX", "changePercent": -2.4, "currentValue": 12.8},
    ]
    breadth = {"advancing": 1500, "declining": 700}
    regime = MarketRegimeEngine.evaluate_regime(indices, breadth)
    assert regime["bias"] in ["BULLISH", "BEARISH", "NEUTRAL"]
    assert 0 <= regime["score"] <= 100


def test_quant_sector_strength():
    heatmap = [
        {"sector": "NIFTY ENERGY", "performancePercent": 1.2, "strength": "Strong"},
        {"sector": "NIFTY IT", "performancePercent": -0.5, "strength": "Weak"},
    ]
    res = SectorStrengthEngine.evaluate_sector("RELIANCE", 1.8, heatmap)
    assert res["sectorName"] == "NIFTY ENERGY"
    assert res["alpha"] == 0.6  # 1.8 - 1.2
    assert res["relative_strength"] == "Moderate" or res["relative_strength"] == "Strong"


def test_quant_deterministic_expected_range(sample_ohlcv_df):
    cur_price = 1450.0
    sr_levels = SupportResistanceEngine.calculate_levels(sample_ohlcv_df)
    exp = ExpectedRangeEngine.calculate_range(
        current_price=cur_price,
        atr=22.5,
        annualized_hv=19.2,
        pdh=1460.0,
        pdl=1438.0,
        day_high=1458.0,
        day_low=1444.0,
        vwap=1449.0,
        support_levels=sr_levels,
        resistance_levels=sr_levels,
    )
    assert exp["expected_high_min"] > cur_price
    assert exp["expected_high_max"] >= exp["expected_high_min"]
    assert exp["expected_low_min"] < cur_price
    assert exp["expected_low_max"] <= exp["expected_low_min"]
    assert exp["bullish_extension"] > exp["expected_high_max"]
    assert exp["bearish_extension"] < exp["expected_low_max"]


def test_quant_probability_sum_100():
    probs = ProbabilityEngine.estimate_probabilities(
        rsi=64.0,
        is_above_vwap=True,
        is_breakout=True,
        is_breakdown=False,
        volume_ratio=1.6,
        momentum_score=72,
        market_bias="BULLISH",
        sector_score=8,
    )
    total = probs["upside"] + probs["downside"] + probs["neutral"]
    assert total == 100
    assert probs["upside"] > probs["downside"]


def test_quant_scoring():
    tech = {"rsi": {"currentValue": 65.0}, "macd": {"signal": "Bullish"}, "vwap": {"signal": "Bullish"}, "ema20": {"signal": "Bullish"}}
    mkt = {"marketScoreWeight": 16.0}
    mom = {"score": 75}
    vol = {"score": 8}
    sec = {"sector_score": 8}
    pa = {"score": 8}
    vola = {"atr_percent": 1.8}

    score_res = ScoringEngine.calculate_score(tech, mkt, mom, vol, sec, pa, vola, "CALL")
    assert 0 <= score_res["totalScore"] <= 100
    assert len(score_res["categories"]) == 7


def test_quant_qualification_no_force():
    # Test qualified call
    qual_pass = QualificationEngine.qualify_call(
        total_score=84,
        current_price=1000.0,
        target_high=1040.0,
        stop_loss=980.0,
        volume_ratio=1.4,
        market_bias="BULLISH",
    )
    assert qual_pass["qualified"] is True

    # Test rejected call due to low score
    qual_fail = QualificationEngine.qualify_call(
        total_score=68,
        current_price=1000.0,
        target_high=1040.0,
        stop_loss=980.0,
        volume_ratio=1.4,
        market_bias="BULLISH",
    )
    assert qual_fail["qualified"] is False
    assert "below qualification threshold" in qual_fail["reason"]


def test_backtesting_engine(sample_ohlcv_df):
    # Create simple signals alternating every 10 bars
    signals = pd.Series(0, index=sample_ohlcv_df.index)
    signals.iloc[5] = 1
    signals.iloc[20] = 1
    signals.iloc[35] = -1

    res = BacktestEngine.run_backtest(
        df=sample_ohlcv_df,
        signals=signals,
        initial_capital=1000000.0,
    )
    assert "win_rate" in res
    assert "profit_factor" in res
    assert "max_drawdown_pct" in res
    assert "sharpe_ratio" in res
    assert "expectancy" in res
    assert res["initial_capital"] == 1000000.0
    assert "disclaimer" in res


def test_model_registry_lifecycle():
    model_id = ModelRegistry.register_model(
        name="test_rf_model",
        version="v1.0",
        model_type="random_forest",
        model_obj=None,
        scaler=None,
        metrics={"auc": 0.72},
        features=["rsi", "macd"],
    )
    assert model_id is not None
    assert ModelRegistry.promote_to_validated(model_id) is True
    assert ModelRegistry.promote_to_production(model_id) is True
    prod = ModelRegistry.get_production_model()
    assert prod is not None
    assert prod["status"] == ModelStatus.PRODUCTION.value
