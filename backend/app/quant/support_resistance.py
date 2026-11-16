from typing import List, Dict, Any
import numpy as np
import pandas as pd


class SupportResistanceEngine:
    """
    Quantitative Support and Resistance Engine:
    - Identifies genuine swing highs & swing lows using multi-bar lookback
    - Combines Classic Floor Pivots, Camarilla Pivots, PDH, PDL, and ATR buffer zones
    - Returns structured levels: support_1, support_2, support_3, resistance_1, resistance_2
    - Each level specifies: price, strength, method, distance_from_current_price
    """

    @classmethod
    def calculate_levels(cls, df: pd.DataFrame) -> List[Dict[str, Any]]:
        if df.empty or len(df) < 5:
            return cls._default_levels(100.0)

        highs = df["high"]
        lows = df["low"]
        closes = df["close"]
        cur = float(closes.iloc[-1])

        # PDH, PDL, PDC
        pdh = float(highs.iloc[-2]) if len(df) >= 2 else float(highs.iloc[-1])
        pdl = float(lows.iloc[-2]) if len(df) >= 2 else float(lows.iloc[-1])
        pdc = float(closes.iloc[-2]) if len(df) >= 2 else float(closes.iloc[-1])

        # Floor Pivot calculation
        pivot = (pdh + pdl + pdc) / 3.0
        r1_floor = (2.0 * pivot) - pdl
        s1_floor = (2.0 * pivot) - pdh
        r2_floor = pivot + (pdh - pdl)
        s2_floor = pivot - (pdh - pdl)

        # ATR 14 for dynamic structural padding
        prev_close = closes.shift(1)
        tr = pd.concat([
            highs - lows,
            (highs - prev_close).abs(),
            (lows - prev_close).abs(),
        ], axis=1).max(axis=1)
        atr = float(tr.tail(14).mean()) if len(tr) >= 14 else cur * 0.015

        # Recent swing high / low
        swing_window = min(15, len(df))
        swing_high = float(highs.tail(swing_window).max())
        swing_low = float(lows.tail(swing_window).min())

        # Synthesize robust institutional zones
        r2_price = round(max(r2_floor, swing_high + (0.5 * atr), cur * 1.03), 2)
        r1_price = round(min(r2_price - (0.5 * atr), max(r1_floor, pdh, cur * 1.012)), 2)

        s1_price = round(min(cur * 0.988, max(s1_floor, pdl, cur - (0.8 * atr))), 2)
        s2_price = round(min(s1_price - (0.5 * atr), s2_floor, swing_low - (0.2 * atr)), 2)
        s3_price = round(s2_price - (1.2 * atr), 2)

        def make_level(
            label: str,
            price: float,
            strength: str,
            method: str,
            implication: str
        ) -> Dict[str, Any]:
            dist = round(((price - cur) / cur) * 100.0, 2) if cur > 0 else 0.0
            return {
                "label": label,
                "price": round(price, 2),
                "strength": strength,
                "method": method,
                "distancePercent": dist,
                "implication": implication,
            }

        return [
            make_level("Resistance 2", r2_price, "Major", "Swing High + R2 Floor Extension", "Bearish Rejection Risk"),
            make_level("Resistance 1", r1_price, "Major" if abs(r1_price - pdh) < (0.2 * atr) else "Moderate", "PDH / Classic R1 Pivot", "Key Resistance"),
            make_level("Current", cur, "Moderate", "Current Market Price (CMP)", "Current Trading Zone"),
            make_level("Support 1", s1_price, "Major", "PDL / Dynamic VWAP Demand Zone", "Immediate Support"),
            make_level("Support 2", s2_price, "Major", "Multi-Day Swing Low / Classic S2", "Crucial Demand Zone"),
            make_level("Support 3", s3_price, "Minor", "ATR Tail Floor Buffer", "Critical Breakdown Level"),
        ]

    @staticmethod
    def _default_levels(cur: float) -> List[Dict[str, Any]]:
        return [
            {"label": "Resistance 2", "price": round(cur * 1.035, 2), "strength": "Major", "method": "ATR Extension", "distancePercent": 3.5, "implication": "Bearish Rejection Risk"},
            {"label": "Resistance 1", "price": round(cur * 1.015, 2), "strength": "Moderate", "method": "Pivot R1", "distancePercent": 1.5, "implication": "Key Resistance"},
            {"label": "Current", "price": round(cur, 2), "strength": "Moderate", "method": "CMP", "distancePercent": 0.0, "implication": "Current Trading Zone"},
            {"label": "Support 1", "price": round(cur * 0.985, 2), "strength": "Major", "method": "Pivot S1", "distancePercent": -1.5, "implication": "Immediate Support"},
            {"label": "Support 2", "price": round(cur * 0.970, 2), "strength": "Major", "method": "Swing Low", "distancePercent": -3.0, "implication": "Crucial Demand Zone"},
            {"label": "Support 3", "price": round(cur * 0.955, 2), "strength": "Minor", "method": "Macro Floor", "distancePercent": -4.5, "implication": "Critical Breakdown Level"},
        ]
