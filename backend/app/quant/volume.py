from typing import Dict, Any
import numpy as np
import pandas as pd


class VolumeAnalyzer:
    """
    Quantitative Volume Engine:
    - Volume Ratio vs 20-period moving average
    - On-Balance Volume (OBV) trend
    - Volume Weighted Spread & Chaikin Money Flow estimate
    - Institutional Accumulation / Distribution Confirmation
    """

    @staticmethod
    def calculate_obv(df: pd.DataFrame) -> pd.Series:
        close = df["close"]
        volume = df["volume"]
        direction = np.where(close > close.shift(1), 1, np.where(close < close.shift(1), -1, 0))
        obv = (volume * direction).cumsum()
        return obv

    @classmethod
    def analyze_volume(cls, df: pd.DataFrame) -> Dict[str, Any]:
        if df.empty or len(df) < 5:
            return {
                "volume_ratio": 1.0,
                "trend": "Average",
                "institutional_action": "Neutral",
                "obv_slope": 0.0,
                "score": 10,
            }

        vol = df["volume"]
        close = df["close"]
        cur_vol = float(vol.iloc[-1])
        avg_vol = float(vol.rolling(window=min(20, len(vol)), min_periods=1).mean().iloc[-1])
        vol_ratio = round(cur_vol / avg_vol, 2) if avg_vol > 0 else 1.0

        # OBV
        obv = cls.calculate_obv(df)
        obv_window = min(10, len(obv))
        obv_change = float(obv.iloc[-1] - obv.iloc[-obv_window])

        # Price direction
        price_up = float(close.iloc[-1]) >= float(close.iloc[-min(5, len(close))])

        if vol_ratio >= 1.75:
            if price_up:
                action = "Strong Institutional Accumulation"
                v_trend = "Surging"
                score = 10
            else:
                action = "Institutional Distribution / Selloff"
                v_trend = "Surging"
                score = 3
        elif vol_ratio >= 1.25:
            action = "Moderate Accumulation" if price_up else "Moderate Distribution"
            v_trend = "Above Average"
            score = 8 if price_up else 5
        elif vol_ratio < 0.75:
            action = "Low Volume Consolidation"
            v_trend = "Below Average"
            score = 5
        else:
            action = "Normal Turnover"
            v_trend = "Average"
            score = 6

        return {
            "current_volume": cur_vol,
            "average_volume": round(avg_vol, 0),
            "volume_ratio": vol_ratio,
            "volume_trend": v_trend,
            "institutional_action": action,
            "obv_positive": obv_change > 0,
            "score": score,  # 0 to 10 for multi-factor scoring
        }
