from typing import List, Tuple
import numpy as np
import pandas as pd


FEATURE_NAMES: List[str] = [
    "return_1d",
    "return_5d",
    "return_10d",
    "rsi_14",
    "macd_hist_norm",
    "dist_ema20_pct",
    "dist_ema50_pct",
    "dist_vwap_pct",
    "atr_pct",
    "volume_ratio",
    "intraday_range_pct",
    "gap_pct",
]


class FeatureEngineer:
    """
    Feature engineering pipeline for Machine Learning and Quantitative models.
    Strictly prevents look-ahead bias and future information leakage:
    All features at index t are computed using data at or before t.
    """

    FEATURE_NAMES: List[str] = FEATURE_NAMES

    @classmethod
    def create_labels(
        cls,
        df: pd.DataFrame,
        target: str = "next_30m_direction",
        horizon: int = 1
    ) -> Tuple[pd.DataFrame, pd.Series]:
        feat = cls.extract_features(df)
        if feat.empty:
            return pd.DataFrame(), pd.Series(dtype=int)

        close = df.loc[feat.index, "close"]
        forward_close = close.shift(-horizon)
        forward_returns = (forward_close - close) / close

        # Target label: 1 if positive return, 0 otherwise
        y = (forward_returns > 0).astype(int)

        # Drop the last horizon rows which have NaN forward return
        valid_idx = forward_returns.dropna().index
        X = feat.loc[valid_idx]
        y = y.loc[valid_idx]
        return X, y

    @staticmethod
    def extract_features(df: pd.DataFrame) -> pd.DataFrame:

        if df.empty or len(df) < 25:
            return pd.DataFrame()

        df_feat = pd.DataFrame(index=df.index)
        close = df["close"]
        high = df["high"]
        low = df["low"]
        vol = df["volume"]
        prev_close = close.shift(1)

        # 1. Returns
        df_feat["return_1d"] = close.pct_change(1)
        df_feat["return_5d"] = close.pct_change(5)
        df_feat["return_10d"] = close.pct_change(10)

        # 2. RSI (14)
        delta = close.diff()
        gain = (delta.where(delta > 0, 0.0)).ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
        loss = (-delta.where(delta < 0, 0.0)).ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
        rs = gain / loss.replace(0, np.nan)
        df_feat["rsi_14"] = (100.0 - (100.0 / (1.0 + rs))).fillna(50.0)

        # 3. MACD Normalized
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26
        signal = macd.ewm(span=9, adjust=False).mean()
        hist = macd - signal
        df_feat["macd_hist_norm"] = (hist / close).fillna(0.0) * 100.0

        # 4. Moving Average Distances
        ema20 = close.ewm(span=20, adjust=False).mean()
        ema50 = close.ewm(span=50, adjust=False).mean()
        df_feat["dist_ema20_pct"] = ((close - ema20) / ema20) * 100.0
        df_feat["dist_ema50_pct"] = ((close - ema50) / ema50) * 100.0

        # 5. VWAP Distance
        typical = (high + low + close) / 3.0
        pv = typical * vol
        vwap = pv.cumsum() / vol.cumsum().replace(0, np.nan)
        vwap = vwap.bfill().ffill()
        df_feat["dist_vwap_pct"] = ((close - vwap) / vwap) * 100.0

        # 6. ATR %
        tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
        atr14 = tr.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
        df_feat["atr_pct"] = (atr14 / close) * 100.0

        # 7. Volume Ratio
        vol_sma20 = vol.rolling(window=20, min_periods=1).mean()
        df_feat["volume_ratio"] = (vol / vol_sma20.replace(0, np.nan)).fillna(1.0)

        # 8. Intraday Range & Gap
        df_feat["intraday_range_pct"] = ((high - low) / close) * 100.0
        df_feat["gap_pct"] = ((df["open"] - prev_close) / prev_close.replace(0, np.nan)).fillna(0.0) * 100.0

        return df_feat.dropna()


# Backward compatibility alias
FeatureEngineering = FeatureEngineer
