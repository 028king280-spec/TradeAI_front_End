"""
Advanced Fair Value Gap (FVG) & Order Block Engine (ICT + SMC).
Implements detection, tracking, and state validation of:
1. Fair Value Gaps (FVG):
   - Bullish FVG
   - Bearish FVG
   - 50% Consequent Encroachment (CE) midpoint
   - Partially Filled FVG
   - Fully Filled / Mitigated FVG
   - Inverse FVG (IFVG - invalidated gap flipped into opposite support/resistance)
2. Order Blocks (OB):
   - Bullish Order Block (Last down candle before decisive impulsive displacement)
   - Bearish Order Block (Last up candle before decisive impulsive displacement)
   - Breaker Block (Violated Order Block flipped into opposite role)
   - Mitigation Block (Retested and absorbed institutional order cluster)
   - Validated vs. Invalidated status tracking
"""

from typing import Dict, Any, List, Optional
import pandas as pd
import numpy as np


class FvgOrderBlockEngine:
    """
    Detects and manages institutional imbalances (FVG) and order footprints (OB / Breakers).
    """

    @staticmethod
    def detect_fair_value_gaps(
        df: pd.DataFrame,
        timeframe: str = "15m",
        min_gap_pts: float = 3.0
    ) -> List[Dict[str, Any]]:
        """
        Detects 3-candle Fair Value Gaps with state transitions:
        FRESH -> PARTIALLY_FILLED -> FULLY_FILLED (Mitigated) -> INVERSE_FVG
        """
        fvgs = []
        n = len(df)
        if n < 4:
            return fvgs

        for i in range(2, n):
            c1 = df.iloc[i - 2]
            c2 = df.iloc[i - 1]
            c3 = df.iloc[i]

            c1_h, c1_l = float(c1["high"]), float(c1["low"])
            c2_o, c2_c = float(c2["open"]), float(c2["close"])
            c3_h, c3_l = float(c3["high"]), float(c3["low"])

            # Displacement check on middle bar
            c2_body = abs(c2_c - c2_o)
            c2_range = max(0.01, float(c2["high"]) - float(c2["low"]))
            displacement_ratio = round(c2_body / c2_range, 2)
            ts = str(c2.get("timestamp", c2.get("time", f"bar_{i-1}")))

            # 1. Bullish FVG: Candle 1 High < Candle 3 Low
            if c3_l > c1_h and c2_c > c2_o and (c3_l - c1_h) >= min_gap_pts and displacement_ratio >= 0.50:
                top = round(c3_l, 2)
                bottom = round(c1_h, 2)
                ce_50 = round((top + bottom) / 2.0, 2)
                gap_size = round(top - bottom, 2)

                # Track subsequent fill history
                subsequent_bars = df.iloc[i + 1:] if i + 1 < n else pd.DataFrame()
                status = "FRESH"
                is_inverse = False
                lowest_retest = top

                if not subsequent_bars.empty:
                    min_after = float(subsequent_bars["low"].min())
                    lowest_retest = round(min_after, 2)
                    close_after = subsequent_bars["close"].tolist()

                    if any(c < bottom for c in close_after):
                        # Candle closed decisively below the FVG floor -> Flipped to Inverse FVG (Resistance)
                        status = "INVERSE_FVG"
                        is_inverse = True
                    elif min_after <= bottom:
                        status = "FULLY_FILLED"
                    elif min_after <= ce_50:
                        status = "PARTIALLY_FILLED_CE_TESTED"
                    elif min_after < top:
                        status = "PARTIALLY_FILLED"

                fvgs.append({
                    "id": f"fvg_bull_{i-1}",
                    "type": "INVERSE_BULLISH_FVG" if is_inverse else "BULLISH_FVG",
                    "originalType": "BULLISH_FVG",
                    "timeframe": timeframe,
                    "barIndex": i - 1,
                    "timestamp": ts,
                    "top": top,
                    "bottom": bottom,
                    "ce50": ce_50,
                    "gapSize": gap_size,
                    "displacementRatio": displacement_ratio,
                    "status": status,
                    "isMitigated": status in ["FULLY_FILLED", "INVERSE_FVG"],
                    "isInverse": is_inverse,
                    "bias": "BEARISH_RESISTANCE" if is_inverse else "BULLISH_SUPPORT",
                    "lowestRetest": lowest_retest,
                    "description": (
                        f"Inverse FVG (flipped resistance) between ₹{bottom} and ₹{top}."
                        if is_inverse else
                        f"Bullish FVG zone [₹{bottom} — ₹{top}] with 50% Consequent Encroachment (CE) at ₹{ce_50}. Status: {status}."
                    )
                })

            # 2. Bearish FVG: Candle 1 Low > Candle 3 High
            elif c1_l > c3_h and c2_c < c2_o and (c1_l - c3_h) >= min_gap_pts and displacement_ratio >= 0.50:
                top = round(c1_l, 2)
                bottom = round(c3_h, 2)
                ce_50 = round((top + bottom) / 2.0, 2)
                gap_size = round(top - bottom, 2)

                subsequent_bars = df.iloc[i + 1:] if i + 1 < n else pd.DataFrame()
                status = "FRESH"
                is_inverse = False
                highest_retest = bottom

                if not subsequent_bars.empty:
                    max_after = float(subsequent_bars["high"].max())
                    highest_retest = round(max_after, 2)
                    close_after = subsequent_bars["close"].tolist()

                    if any(c > top for c in close_after):
                        # Candle closed decisively above the FVG ceiling -> Flipped to Inverse FVG (Support)
                        status = "INVERSE_FVG"
                        is_inverse = True
                    elif max_after >= top:
                        status = "FULLY_FILLED"
                    elif max_after >= ce_50:
                        status = "PARTIALLY_FILLED_CE_TESTED"
                    elif max_after > bottom:
                        status = "PARTIALLY_FILLED"

                fvgs.append({
                    "id": f"fvg_bear_{i-1}",
                    "type": "INVERSE_BEARISH_FVG" if is_inverse else "BEARISH_FVG",
                    "originalType": "BEARISH_FVG",
                    "timeframe": timeframe,
                    "barIndex": i - 1,
                    "timestamp": ts,
                    "top": top,
                    "bottom": bottom,
                    "ce50": ce_50,
                    "gapSize": gap_size,
                    "displacementRatio": displacement_ratio,
                    "status": status,
                    "isMitigated": status in ["FULLY_FILLED", "INVERSE_FVG"],
                    "isInverse": is_inverse,
                    "bias": "BULLISH_SUPPORT" if is_inverse else "BEARISH_RESISTANCE",
                    "highestRetest": highest_retest,
                    "description": (
                        f"Inverse FVG (flipped support) between ₹{bottom} and ₹{top}."
                        if is_inverse else
                        f"Bearish FVG zone [₹{bottom} — ₹{top}] with 50% Consequent Encroachment (CE) at ₹{ce_50}. Status: {status}."
                    )
                })

        return fvgs

    @staticmethod
    def detect_order_blocks_and_breakers(
        df: pd.DataFrame,
        timeframe: str = "15m"
    ) -> List[Dict[str, Any]]:
        """
        Detects Order Blocks (OB), Breaker Blocks, and Mitigation Blocks.
        - Bullish Order Block: Down candle prior to sharp bullish displacement.
        - Bearish Order Block: Up candle prior to sharp bearish displacement.
        - Breaker Block: When price breaks through an Order Block, it flips into a Breaker (support becomes resistance or vice versa).
        - Mitigation Block: Order Block that was retested to mitigate smart money exposure.
        """
        blocks = []
        n = len(df)
        if n < 5:
            return blocks

        for i in range(2, n - 2):
            curr = df.iloc[i]
            next1 = df.iloc[i + 1]
            next2 = df.iloc[i + 2]

            c_o, c_c = float(curr["open"]), float(curr["close"])
            c_h, c_l = float(curr["high"]), float(curr["low"])
            ts = str(curr.get("timestamp", curr.get("time", f"bar_{i}")))

            disp_up = float(next1["close"]) > float(next1["open"]) and float(next2["close"]) > float(next2["open"])
            disp_down = float(next1["close"]) < float(next1["open"]) and float(next2["close"]) < float(next2["open"])

            subsequent_bars = df.iloc[i + 3:] if i + 3 < n else pd.DataFrame()

            # 1. Bullish Order Block Check
            if c_c < c_o and disp_up:
                up_gain = float(next2["close"]) - c_h
                if up_gain > (c_h - c_l) * 1.2:
                    top = round(c_h, 2)
                    bottom = round(c_l, 2)
                    midpoint = round((top + bottom) / 2.0, 2)

                    status = "VALID_ACTIVE"
                    block_type = "BULLISH_OB"
                    bias = "BULLISH"

                    # Check for Breaker or Mitigation
                    if not subsequent_bars.empty:
                        min_low = float(subsequent_bars["low"].min())
                        closes = subsequent_bars["close"].tolist()
                        if any(c < bottom for c in closes):
                            # Broken to downside -> Flipped to Bearish Breaker Block
                            block_type = "BEARISH_BREAKER"
                            bias = "BEARISH"
                            status = "FLIPPED_BREAKER"
                        elif min_low <= top:
                            status = "MITIGATED"

                    blocks.append({
                        "id": f"ob_bull_{i}",
                        "type": block_type,
                        "originalType": "BULLISH_OB",
                        "timeframe": timeframe,
                        "barIndex": i,
                        "timestamp": ts,
                        "top": top,
                        "bottom": bottom,
                        "midpoint": midpoint,
                        "bias": bias,
                        "status": status,
                        "isValid": status in ["VALID_ACTIVE", "FLIPPED_BREAKER"],
                        "description": (
                            f"Bearish Breaker Block [₹{bottom} — ₹{top}] (Broken Bullish OB flipped into overhead supply resistance)."
                            if block_type == "BEARISH_BREAKER" else
                            f"Bullish Order Block [₹{bottom} — ₹{top}] with Mean Threshold at ₹{midpoint}. Status: {status}."
                        )
                    })

            # 2. Bearish Order Block Check
            elif c_c > c_o and disp_down:
                down_drop = c_l - float(next2["close"])
                if down_drop > (c_h - c_l) * 1.2:
                    top = round(c_h, 2)
                    bottom = round(c_l, 2)
                    midpoint = round((top + bottom) / 2.0, 2)

                    status = "VALID_ACTIVE"
                    block_type = "BEARISH_OB"
                    bias = "BEARISH"

                    # Check for Breaker or Mitigation
                    if not subsequent_bars.empty:
                        max_high = float(subsequent_bars["high"].max())
                        closes = subsequent_bars["close"].tolist()
                        if any(c > top for c in closes):
                            # Broken to upside -> Flipped to Bullish Breaker Block
                            block_type = "BULLISH_BREAKER"
                            bias = "BULLISH"
                            status = "FLIPPED_BREAKER"
                        elif max_high >= bottom:
                            status = "MITIGATED"

                    blocks.append({
                        "id": f"ob_bear_{i}",
                        "type": block_type,
                        "originalType": "BEARISH_OB",
                        "timeframe": timeframe,
                        "barIndex": i,
                        "timestamp": ts,
                        "top": top,
                        "bottom": bottom,
                        "midpoint": midpoint,
                        "bias": bias,
                        "status": status,
                        "isValid": status in ["VALID_ACTIVE", "FLIPPED_BREAKER"],
                        "description": (
                            f"Bullish Breaker Block [₹{bottom} — ₹{top}] (Broken Bearish OB flipped into institutional demand floor)."
                            if block_type == "BULLISH_BREAKER" else
                            f"Bearish Order Block [₹{bottom} — ₹{top}] with Mean Threshold at ₹{midpoint}. Status: {status}."
                        )
                    })

        return blocks
