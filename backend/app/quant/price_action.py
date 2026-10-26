from typing import Dict, Any, List
import numpy as np
import pandas as pd


class PriceActionAnalyzer:
    """
    Quantitative Price Action Engine:
    - Identifies Higher Highs (HH), Higher Lows (HL), Lower Highs (LH), Lower Lows (LL)
    - Breakout and Breakdown recognition (20-period swing channels)
    - Consolidation detection
    - Opening Gap Up / Down analysis
    - Previous Day High (PDH), Low (PDL), Close (PDC)
    """

    @classmethod
    def analyze_structure(cls, df: pd.DataFrame) -> Dict[str, Any]:
        if df.empty or len(df) < 5:
            return {
                "structure": "Neutral Consolidation",
                "trend_strength": "Moderate",
                "pdh": 0.0,
                "pdl": 0.0,
                "pdc": 0.0,
                "gap_type": "None",
                "gap_percent": 0.0,
                "is_breakout": False,
                "is_breakdown": False,
                "score": 6,
            }

        highs = df["high"]
        lows = df["low"]
        closes = df["close"]
        opens = df["open"]

        cur_price = float(closes.iloc[-1])
        cur_open = float(opens.iloc[-1])

        # Previous day levels (using second to last candle or shift)
        pdh = float(highs.iloc[-2]) if len(df) >= 2 else float(highs.iloc[-1])
        pdl = float(lows.iloc[-2]) if len(df) >= 2 else float(lows.iloc[-1])
        pdc = float(closes.iloc[-2]) if len(df) >= 2 else float(closes.iloc[-1])

        # Gap calculation
        gap_val = cur_open - pdc
        gap_pct = round((gap_val / pdc) * 100.0, 2) if pdc > 0 else 0.0
        if gap_pct >= 0.4:
            gap_type = "Gap Up"
        elif gap_pct <= -0.4:
            gap_type = "Gap Down"
        else:
            gap_type = "Normal Open"

        # 20-period channel
        window = min(20, len(df))
        range_high = float(highs.iloc[-window:-1].max()) if window > 1 else pdh
        range_low = float(lows.iloc[-window:-1].min()) if window > 1 else pdl

        is_breakout = cur_price > range_high
        is_breakdown = cur_price < range_low

        # Swing analysis (last 3 segments)
        h1 = float(highs.iloc[-1])
        h2 = float(highs.iloc[-min(5, len(df))])
        l1 = float(lows.iloc[-1])
        l2 = float(lows.iloc[-min(5, len(df))])

        if is_breakout or (h1 > h2 and l1 > l2):
            structure = "Higher Highs & Higher Lows (Bullish Expansion)"
            trend_strength = "Strong Bullish" if is_breakout else "Bullish"
            score = 10 if is_breakout else 8
        elif is_breakdown or (h1 < h2 and l1 < l2):
            structure = "Lower Highs & Lower Lows (Bearish Breakdown)"
            trend_strength = "Strong Bearish" if is_breakdown else "Bearish"
            score = 2 if is_breakdown else 4
        else:
            structure = "Consolidation / Symmetric Range"
            trend_strength = "Neutral"
            score = 6

        return {
            "structure": structure,
            "trend_strength": trend_strength,
            "pdh": round(pdh, 2),
            "pdl": round(pdl, 2),
            "pdc": round(pdc, 2),
            "gap_type": gap_type,
            "gap_percent": gap_pct,
            "is_breakout": is_breakout,
            "is_breakdown": is_breakdown,
            "range_high": round(range_high, 2),
            "range_low": round(range_low, 2),
            "score": score,  # 0 to 10 for multi-factor scoring
        }
