from typing import Dict, Any
import numpy as np
import pandas as pd


class VolatilityAnalyzer:
    """
    Quantitative Volatility Engine:
    - Annualized Historical Volatility (from daily or log return standard deviation)
    - Normalized ATR Percentage
    - Bollinger Bands & Bandwidth
    - Regime Classification: Low / Moderate / High / Elevated / Extreme
    """

    @staticmethod
    def calculate_bollinger_bands(
        series: pd.Series,
        window: int = 20,
        num_std: float = 2.0
    ) -> Dict[str, float]:
        if len(series) < window:
            val = float(series.iloc[-1])
            return {"upper": val, "middle": val, "lower": val, "bandwidth": 0.0}

        middle = series.rolling(window=window).mean()
        std = series.rolling(window=window).std()
        upper = middle + (num_std * std)
        lower = middle - (num_std * std)

        cur_mid = float(middle.iloc[-1])
        cur_up = float(upper.iloc[-1])
        cur_low = float(lower.iloc[-1])
        bandwidth = round(((cur_up - cur_low) / cur_mid) * 100.0, 2) if cur_mid > 0 else 0.0

        return {
            "upper": round(cur_up, 2),
            "middle": round(cur_mid, 2),
            "lower": round(cur_low, 2),
            "bandwidth": bandwidth,
        }

    @staticmethod
    def calculate_historical_volatility(series: pd.Series, window: int = 20) -> float:
        """
        Annualized Historical Volatility using log returns (252 trading days).
        """
        if len(series) < 5:
            return 18.0

        log_returns = np.log(series / series.shift(1)).dropna()
        daily_std = log_returns.tail(window).std()
        annualized_vol = daily_std * np.sqrt(252) * 100.0
        return round(float(annualized_vol), 2) if not np.isnan(annualized_vol) else 18.0

    @classmethod
    def analyze_volatility(cls, df: pd.DataFrame) -> Dict[str, Any]:
        if df.empty or len(df) < 5:
            return {
                "regime": "Moderate",
                "annualized_hv": 18.5,
                "atr_percent": 1.8,
                "bandwidth": 3.5,
                "bb_upper": 0.0,
                "bb_lower": 0.0,
                "risk_adjustment_factor": 1.0,
            }

        close = df["close"]
        cur = float(close.iloc[-1])

        # ATR calculation
        prev_close = close.shift(1)
        tr = pd.concat([
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ], axis=1).max(axis=1)
        atr_14 = float(tr.rolling(window=min(14, len(df))).mean().iloc[-1])
        atr_pct = round((atr_14 / cur) * 100.0, 2) if cur > 0 else 1.5

        # Historical Volatility
        hv = cls.calculate_historical_volatility(close, window=min(20, len(close)))

        # Bollinger Bands
        bb = cls.calculate_bollinger_bands(close, window=min(20, len(close)))

        # Regime classification
        if hv < 14.0 and atr_pct < 1.4:
            regime = "Low"
            risk_adj = 0.85
        elif hv < 24.0 and atr_pct < 2.5:
            regime = "Moderate"
            risk_adj = 1.0
        elif hv < 35.0:
            regime = "High"
            risk_adj = 1.2
        elif hv < 48.0:
            regime = "Elevated"
            risk_adj = 1.4
        else:
            regime = "Extreme"
            risk_adj = 1.8

        return {
            "regime": regime,
            "annualized_hv": hv,
            "atr_percent": atr_pct,
            "bandwidth": bb["bandwidth"],
            "bb_upper": bb["upper"],
            "bb_lower": bb["lower"],
            "risk_adjustment_factor": risk_adj,
        }
