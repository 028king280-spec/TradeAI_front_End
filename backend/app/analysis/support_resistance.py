from typing import List, Dict, Any
import numpy as np
import pandas as pd


class SupportResistanceEngine:
    """
    Calculates deterministic support and resistance levels using:
    - Camarilla & Classic Pivot calculations
    - Previous Day High, Low, Close
    - 20-day Swing Highs and Swing Lows
    - ATR volatility distance buffers
    """

    @classmethod
    def calculate_levels(
        cls,
        df_daily: pd.DataFrame,
        current_price: float,
        atr: float
    ) -> List[Dict[str, Any]]:
        if len(df_daily) < 2:
            prev_high = current_price * 1.01
            prev_low = current_price * 0.99
            prev_close = current_price
        else:
            prev_bar = df_daily.iloc[-2]
            prev_high = float(prev_bar["high"])
            prev_low = float(prev_bar["low"])
            prev_close = float(prev_bar["close"])

        # Pivot Points: Standard & Camarilla
        camarilla_range = prev_high - prev_low
        cam_r3 = round(prev_close + camarilla_range * 1.1 / 4.0, 2)
        cam_r4 = round(prev_close + camarilla_range * 1.1 / 2.0, 2)
        cam_s3 = round(prev_close - camarilla_range * 1.1 / 4.0, 2)
        cam_s4 = round(prev_close - camarilla_range * 1.1 / 2.0, 2)

        # Swing levels over last 20 sessions
        window = min(len(df_daily), 20)
        recent_df = df_daily.iloc[-window:]
        swing_high = float(recent_df["high"].max())
        swing_low = float(recent_df["low"].min())

        # Resistance 2: Major structural barrier (higher of swing_high or cam_r4)
        r2_price = round(max(current_price * 1.015, max(swing_high, cam_r4)), 2)
        r2_dist = round(((r2_price - current_price) / current_price) * 100, 2)

        # Resistance 1: Immediate barrier (cam_r3 or prev_high)
        candidate_r1 = max(prev_high, cam_r3)
        if candidate_r1 <= current_price:
            candidate_r1 = round(current_price + (atr * 0.6), 2)
        r1_price = round(min(candidate_r1, r2_price - 1.0), 2)
        r1_dist = round(((r1_price - current_price) / current_price) * 100, 2)

        # Support 1: Immediate demand shelf (cam_s3 or prev_low)
        candidate_s1 = min(prev_low, cam_s3)
        if candidate_s1 >= current_price:
            candidate_s1 = round(current_price - (atr * 0.6), 2)
        s1_price = round(candidate_s1, 2)
        s1_dist = round(((s1_price - current_price) / current_price) * 100, 2)

        # Support 2: Crucial demand zone (cam_s4 or swing_low)
        candidate_s2 = min(s1_price - (atr * 0.5), max(swing_low, cam_s4))
        if candidate_s2 >= s1_price:
            candidate_s2 = round(s1_price - (atr * 0.7), 2)
        s2_price = round(candidate_s2, 2)
        s2_dist = round(((s2_price - current_price) / current_price) * 100, 2)

        # Support 3: Critical breakdown level (major support / swing low minus buffer)
        s3_price = round(min(s2_price - (atr * 0.8), swing_low - (atr * 0.4)), 2)
        s3_dist = round(((s3_price - current_price) / current_price) * 100, 2)

        return [
            {
                "label": "Resistance 2",
                "price": r2_price,
                "strength": "Major",
                "distancePercent": r2_dist,
                "implication": "Bearish Rejection Risk",
                "source": "Swing High / Camarilla R4",
            },
            {
                "label": "Resistance 1",
                "price": r1_price,
                "strength": "Moderate",
                "distancePercent": r1_dist,
                "implication": "Key Resistance",
                "source": "Previous Day High / Camarilla R3",
            },
            {
                "label": "Current",
                "price": round(current_price, 2),
                "strength": "Minor",
                "distancePercent": 0.0,
                "implication": "Current Trading Zone",
                "source": "LTP",
            },
            {
                "label": "Support 1",
                "price": s1_price,
                "strength": "Moderate",
                "distancePercent": s1_dist,
                "implication": "Immediate Support",
                "source": "Previous Day Low / Camarilla S3",
            },
            {
                "label": "Support 2",
                "price": s2_price,
                "strength": "Major",
                "distancePercent": s2_dist,
                "implication": "Crucial Demand Zone",
                "source": "Recent Swing Demand / Camarilla S4",
            },
            {
                "label": "Support 3",
                "price": s3_price,
                "strength": "Major",
                "distancePercent": s3_dist,
                "implication": "Critical Breakdown Level",
                "source": "Structural Swing Low Floor",
            },
        ]
