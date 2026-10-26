from typing import Dict, Any
import numpy as np
import pandas as pd


class MomentumAnalyzer:
    """
    Quantitative Momentum Engine:
    - Rate of Change (ROC) across multiple horizons (5, 10, 20 periods)
    - Fast & Slow Stochastic Oscillator (%K, %D)
    - Momentum Acceleration (2nd derivative of price smoothing)
    - Directional Bias Score (0 to 100)
    """

    @staticmethod
    def calculate_stochastic(
        df: pd.DataFrame,
        k_period: int = 14,
        d_period: int = 3
    ) -> Dict[str, float]:
        if len(df) < k_period:
            return {"k": 50.0, "d": 50.0}

        low_min = df["low"].rolling(window=k_period).min()
        high_max = df["high"].rolling(window=k_period).max()

        k_fast = 100.0 * ((df["close"] - low_min) / (high_max - low_min).replace(0, np.nan))
        k = k_fast.rolling(window=3).mean()  # Slow %K
        d = k.rolling(window=d_period).mean()

        return {
            "k": round(float(k.iloc[-1]), 2) if not pd.isna(k.iloc[-1]) else 50.0,
            "d": round(float(d.iloc[-1]), 2) if not pd.isna(d.iloc[-1]) else 50.0,
        }

    @classmethod
    def analyze_momentum(cls, df: pd.DataFrame) -> Dict[str, Any]:
        if df.empty or len(df) < 10:
            return {
                "bias": "Neutral",
                "score": 50,
                "roc5": 0.0,
                "roc10": 0.0,
                "roc20": 0.0,
                "stoch_k": 50.0,
                "stoch_d": 50.0,
                "acceleration": "Stable",
            }

        close = df["close"]
        cur = float(close.iloc[-1])

        p5 = float(close.iloc[-min(5, len(close))])
        p10 = float(close.iloc[-min(10, len(close))])
        p20 = float(close.iloc[-min(20, len(close))])

        roc5 = round(((cur - p5) / p5) * 100, 2)
        roc10 = round(((cur - p10) / p10) * 100, 2)
        roc20 = round(((cur - p20) / p20) * 100, 2)

        stoch = cls.calculate_stochastic(df, 14, 3)

        # Acceleration: is ROC5 accelerating faster than ROC10?
        accel_diff = roc5 - (roc10 / 2.0)
        if accel_diff > 0.5:
            acceleration = "Expanding Bullish"
        elif accel_diff < -0.5:
            acceleration = "Expanding Bearish"
        else:
            acceleration = "Steady"

        # Momentum Score calculation (0 to 100)
        base_score = 50
        if roc10 > 0:
            base_score += min(30, int(roc10 * 8))
        else:
            base_score -= min(30, int(abs(roc10) * 8))

        if stoch["k"] > 60:
            base_score += 10
        elif stoch["k"] < 40:
            base_score -= 10

        score = max(0, min(100, base_score))
        bias = "Bullish" if score >= 60 else "Bearish" if score <= 40 else "Neutral"

        return {
            "bias": bias,
            "score": score,
            "roc5": roc5,
            "roc10": roc10,
            "roc20": roc20,
            "stoch_k": stoch["k"],
            "stoch_d": stoch["d"],
            "acceleration": acceleration,
        }
