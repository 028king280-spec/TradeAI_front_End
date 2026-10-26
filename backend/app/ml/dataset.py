from typing import Tuple, Optional
import numpy as np
import pandas as pd

from app.ml.features import FeatureEngineer


class DatasetBuilder:
    """
    Builds supervised machine learning datasets from historical OHLCV candles.
    Ensures labels are strictly forward-looking and features are strictly backward-looking.
    """

    @classmethod
    def build_dataset(
        cls,
        df: pd.DataFrame,
        horizon_candles: int = 3,
        threshold_pct: float = 1.2,
    ) -> Tuple[pd.DataFrame, pd.Series, pd.Series]:
        """
        X: features at time t
        y: label at time t+horizon (1 if forward_return > threshold else 0)
        timestamps: series of candle timestamps
        """
        if df.empty or len(df) < 30:
            return pd.DataFrame(), pd.Series(), pd.Series()

        features = FeatureEngineer.extract_features(df)
        if features.empty:
            return pd.DataFrame(), pd.Series(), pd.Series()

        # Calculate strictly forward returns: (close[t + horizon] - close[t]) / close[t]
        close = df.loc[features.index, "close"]
        forward_close = close.shift(-horizon_candles)
        forward_returns = ((forward_close - close) / close) * 100.0

        # Binary label: 1 if forward return exceeds positive hurdle, else 0
        labels = (forward_returns > threshold_pct).astype(int)

        # Drop the last horizon_candles which have NaN forward returns
        valid_idx = forward_returns.dropna().index
        X = features.loc[valid_idx]
        y = labels.loc[valid_idx]
        timestamps = df.loc[valid_idx, "timestamp"] if "timestamp" in df.columns else pd.Series(valid_idx)

        return X, y, timestamps
