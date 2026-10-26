import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from app.ml.features import FeatureEngineering
from app.ml.validation import TimeSeriesSplitter
from app.ml.models import ModelFactory
from app.ml.backtest import EconomicBacktester


@pytest.fixture
def sample_market_dataset():
    dates = [datetime(2025, 1, 1) + timedelta(days=i) for i in range(120)]
    prices = [1000.0]
    rng = np.random.RandomState(42)
    for _ in range(119):
        prices.append(prices[-1] * (1 + rng.normal(0.0005, 0.012)))

    records = []
    for d, p in zip(dates, prices):
        records.append({
            "timestamp": d,
            "open": p * 0.998,
            "high": p * 1.01,
            "low": p * 0.99,
            "close": p,
            "volume": int(rng.uniform(100000, 500000)),
        })
    return pd.DataFrame(records)


def test_feature_creation_and_labels(sample_market_dataset):
    X, y = FeatureEngineering.create_labels(sample_market_dataset)
    assert len(X) == len(y)
    assert len(X) > 50
    for feat in FeatureEngineering.FEATURE_NAMES:
        assert feat in X.columns
        assert not X[feat].isna().any()


def test_time_series_chronological_split(sample_market_dataset):
    X, y = FeatureEngineering.create_labels(sample_market_dataset)
    X_tr, X_val, X_te, y_tr, y_val, y_te = TimeSeriesSplitter.train_val_test_split(X, y)

    # Assert no overlapping indices and strict order
    assert X_tr.index[-1] < X_val.index[0]
    assert X_val.index[-1] < X_te.index[0]
    assert len(X_tr) + len(X_val) + len(X_te) == len(X)


def test_model_training_and_backtest(sample_market_dataset):
    X, y = FeatureEngineering.create_labels(sample_market_dataset)
    X_tr, X_val, X_te, y_tr, y_val, y_te = TimeSeriesSplitter.train_val_test_split(X, y)

    model = ModelFactory.create_model("random_forest")
    model.fit(X_tr, y_tr)

    eval_metrics = ModelFactory.evaluate_model(model, X_te, y_te)
    assert "accuracy" in eval_metrics
    assert "f1Score" in eval_metrics

    test_signals = pd.Series(model.predict(X_te))
    test_prices = sample_market_dataset.iloc[X_te.index]["close"]

    bt = EconomicBacktester.run_backtest(test_prices, test_signals)
    assert "winRate" in bt
    assert "profitFactor" in bt
    assert "maxDrawdownPercent" in bt
    assert "equityCurve" in bt
