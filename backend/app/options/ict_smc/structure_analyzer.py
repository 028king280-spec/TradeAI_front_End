"""
Advanced Market Structure Analyzer (ICT + SMC).
Implements automatic detection and tracking of:
- Swing Highs and Swing Lows (Fractal pivots)
- Higher High (HH), Higher Low (HL), Lower High (LH), Lower Low (LL)
- Break of Structure (BOS - Bullish & Bearish with candle-body confirmation)
- Change of Character (CHoCH) & Market Structure Shift (MSS with displacement)
- Internal vs. External Structure Hierarchy

Every detected point includes:
- Detected price level
- Timeframe
- Detection timestamp
- Confirmation status (CONFIRMED vs PENDING)
- Strength and reliability factors (displacement, volume ratio, wick dynamics)
"""

from typing import Dict, Any, List, Optional
import pandas as pd
import numpy as np


class MarketStructureAnalyzer:
    """
    Institutional Market Structure Engine for Equities and Index Derivatives.
    """

    @staticmethod
    def identify_swings(
        df: pd.DataFrame,
        window: int = 3,
        timeframe: str = "15m",
        structure_type: str = "EXTERNAL"
    ) -> List[Dict[str, Any]]:
        """
        Identifies swing pivots with dynamic lookback window.
        - window=3: Minor/Internal swings
        - window=5 to 7: Major/External swings
        """
        swings = []
        n = len(df)
        if n < (window * 2 + 1):
            return swings

        for i in range(window, n - window):
            curr_bar = df.iloc[i]
            curr_h = float(curr_bar["high"])
            curr_l = float(curr_bar["low"])
            ts = str(curr_bar.get("timestamp", curr_bar.get("time", f"bar_{i}")))

            # Check Swing High
            is_high = True
            for w in range(1, window + 1):
                if float(df.iloc[i - w]["high"]) >= curr_h or float(df.iloc[i + w]["high"]) >= curr_h:
                    is_high = False
                    break

            if is_high:
                # Reliability and strength factors
                vol_window = df.iloc[max(0, i - 5):min(n, i + 6)]["volume"].mean() if "volume" in df else 1000
                curr_vol = float(curr_bar.get("volume", vol_window))
                vol_ratio = round(curr_vol / max(1.0, vol_window), 2)
                upper_wick = curr_h - max(float(curr_bar["open"]), float(curr_bar["close"]))
                total_range = max(0.01, curr_h - curr_l)
                wick_rejection_pct = round((upper_wick / total_range) * 100.0, 1)

                swings.append({
                    "index": i,
                    "type": "SWING_HIGH",
                    "structureType": structure_type,
                    "price": round(curr_h, 2),
                    "timestamp": ts,
                    "timeframe": timeframe,
                    "status": "CONFIRMED",
                    "strength": "STRONG" if vol_ratio > 1.2 or wick_rejection_pct > 35 else "MODERATE",
                    "volumeRatio": vol_ratio,
                    "wickRejectionPct": wick_rejection_pct,
                })

            # Check Swing Low
            is_low = True
            for w in range(1, window + 1):
                if float(df.iloc[i - w]["low"]) <= curr_l or float(df.iloc[i + w]["low"]) <= curr_l:
                    is_low = False
                    break

            if is_low:
                vol_window = df.iloc[max(0, i - 5):min(n, i + 6)]["volume"].mean() if "volume" in df else 1000
                curr_vol = float(curr_bar.get("volume", vol_window))
                vol_ratio = round(curr_vol / max(1.0, vol_window), 2)
                lower_wick = min(float(curr_bar["open"]), float(curr_bar["close"])) - curr_l
                total_range = max(0.01, curr_h - curr_l)
                wick_rejection_pct = round((lower_wick / total_range) * 100.0, 1)

                swings.append({
                    "index": i,
                    "type": "SWING_LOW",
                    "structureType": structure_type,
                    "price": round(curr_l, 2),
                    "timestamp": ts,
                    "timeframe": timeframe,
                    "status": "CONFIRMED",
                    "strength": "STRONG" if vol_ratio > 1.2 or wick_rejection_pct > 35 else "MODERATE",
                    "volumeRatio": vol_ratio,
                    "wickRejectionPct": wick_rejection_pct,
                })

        # Check pending/unconfirmed swings at the most recent edge of data
        if n >= 3:
            last_idx = n - 1
            last_bar = df.iloc[last_idx]
            prev_bar = df.iloc[last_idx - 1]
            if float(last_bar["high"]) > float(prev_bar["high"]):
                swings.append({
                    "index": last_idx,
                    "type": "SWING_HIGH",
                    "structureType": structure_type,
                    "price": round(float(last_bar["high"]), 2),
                    "timestamp": str(last_bar.get("timestamp", last_bar.get("time", "Current"))),
                    "timeframe": timeframe,
                    "status": "PENDING",
                    "strength": "FORMING",
                    "volumeRatio": 1.0,
                    "wickRejectionPct": 0.0,
                })
            elif float(last_bar["low"]) < float(prev_bar["low"]):
                swings.append({
                    "index": last_idx,
                    "type": "SWING_LOW",
                    "structureType": structure_type,
                    "price": round(float(last_bar["low"]), 2),
                    "timestamp": str(last_bar.get("timestamp", last_bar.get("time", "Current"))),
                    "timeframe": timeframe,
                    "status": "PENDING",
                    "strength": "FORMING",
                    "volumeRatio": 1.0,
                    "wickRejectionPct": 0.0,
                })

        return sorted(swings, key=lambda s: s["index"])

    @staticmethod
    def classify_trend_points(swings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Classifies confirmed swings into:
        - Higher High (HH)
        - Higher Low (HL)
        - Lower High (LH)
        - Lower Low (LL)
        """
        classified = []
        highs = [s for s in swings if s["type"] == "SWING_HIGH" and s["status"] == "CONFIRMED"]
        lows = [s for s in swings if s["type"] == "SWING_LOW" and s["status"] == "CONFIRMED"]

        # Classify Highs
        for idx, h in enumerate(highs):
            h_copy = dict(h)
            if idx == 0:
                h_copy["label"] = "HIGH"
            else:
                prev_h = highs[idx - 1]["price"]
                if h["price"] > prev_h:
                    h_copy["label"] = "HH"  # Higher High
                    h_copy["description"] = f"Higher High at ₹{h['price']} (Bullish expansion above ₹{prev_h})"
                else:
                    h_copy["label"] = "LH"  # Lower High
                    h_copy["description"] = f"Lower High at ₹{h['price']} (Bearish lower resistance below ₹{prev_h})"
            classified.append(h_copy)

        # Classify Lows
        for idx, l in enumerate(lows):
            l_copy = dict(l)
            if idx == 0:
                l_copy["label"] = "LOW"
            else:
                prev_l = lows[idx - 1]["price"]
                if l["price"] > prev_l:
                    l_copy["label"] = "HL"  # Higher Low
                    l_copy["description"] = f"Higher Low at ₹{l['price']} (Bullish structural support above ₹{prev_l})"
                else:
                    l_copy["label"] = "LL"  # Lower Low
                    l_copy["description"] = f"Lower Low at ₹{l['price']} (Bearish breakdown below ₹{prev_l})"
            classified.append(l_copy)

        return sorted(classified, key=lambda p: p["index"])

    @staticmethod
    def detect_bos_and_choch(
        df: pd.DataFrame,
        classified_points: List[Dict[str, Any]],
        timeframe: str = "15m"
    ) -> Dict[str, Any]:
        """
        Detects Break of Structure (BOS), Change of Character (CHoCH), and Market Structure Shift (MSS).
        Rules:
        - Bullish BOS: Price closes above the most recent Swing High in an uptrend (HH break).
        - Bearish BOS: Price closes below the most recent Swing Low in a downtrend (LL break).
        - Bullish CHoCH/MSS: Price in downtrend closes above the last LH with displacement.
        - Bearish CHoCH/MSS: Price in uptrend closes below the last HL with displacement.
        """
        events = []
        n = len(df)
        if n < 5 or not classified_points:
            return {"events": [], "currentStructure": "NEUTRAL", "lastBos": None, "lastChoch": None}

        # Track active reference high and low
        active_highs = [p for p in classified_points if p["type"] == "SWING_HIGH"]
        active_lows = [p for p in classified_points if p["type"] == "SWING_LOW"]

        current_trend = "NEUTRAL"
        # Determine baseline trend from last 2 points
        if len(active_highs) >= 2 and len(active_lows) >= 2:
            if active_highs[-1]["price"] > active_highs[-2]["price"] and active_lows[-1]["price"] >= active_lows[-2]["price"]:
                current_trend = "BULLISH"
            elif active_highs[-1]["price"] <= active_highs[-2]["price"] and active_lows[-1]["price"] < active_lows[-2]["price"]:
                current_trend = "BEARISH"

        for i in range(1, n):
            c_bar = df.iloc[i]
            c_close = float(c_bar["close"])
            c_open = float(c_bar["open"])
            c_high = float(c_bar["high"])
            c_low = float(c_bar["low"])
            ts = str(c_bar.get("timestamp", c_bar.get("time", f"bar_{i}")))

            body_size = abs(c_close - c_open)
            candle_range = max(0.01, c_high - c_low)
            displacement_ratio = round(body_size / candle_range, 2)
            has_displacement = displacement_ratio >= 0.58 and c_close > c_open if c_close > c_open else displacement_ratio >= 0.58

            # Candidate prior swing highs prior to bar i
            prior_highs = [p for p in active_highs if p["index"] < i]
            prior_lows = [p for p in active_lows if p["index"] < i]

            if not prior_highs or not prior_lows:
                continue

            last_ref_high = prior_highs[-1]
            last_ref_low = prior_lows[-1]

            # 1. Bullish Breakout Check
            if c_close > last_ref_high["price"] and float(df.iloc[i - 1]["close"]) <= last_ref_high["price"]:
                is_choch = (current_trend == "BEARISH" or last_ref_high.get("label") == "LH")
                event_type = "BULLISH_CHOCH" if is_choch else "BULLISH_BOS"
                if is_choch and has_displacement:
                    event_type = "BULLISH_MSS"

                events.append({
                    "index": i,
                    "type": event_type,
                    "direction": "BULLISH",
                    "brokenLevel": last_ref_high["price"],
                    "closePrice": round(c_close, 2),
                    "brokenSwingLabel": last_ref_high.get("label", "HIGH"),
                    "timestamp": ts,
                    "timeframe": timeframe,
                    "status": "CONFIRMED",
                    "displacementRatio": displacement_ratio,
                    "hasDisplacement": has_displacement,
                    "strength": "HIGH" if has_displacement else "MODERATE",
                    "description": (
                        f"Bullish Market Structure Shift (MSS) above ₹{last_ref_high['price']} with displacement."
                        if event_type == "BULLISH_MSS" else
                        f"Bullish {'Change of Character (CHoCH)' if is_choch else 'Break of Structure (BOS)'} confirmed above ₹{last_ref_high['price']}."
                    )
                })
                current_trend = "BULLISH"

            # 2. Bearish Breakdown Check
            elif c_close < last_ref_low["price"] and float(df.iloc[i - 1]["close"]) >= last_ref_low["price"]:
                is_choch = (current_trend == "BULLISH" or last_ref_low.get("label") == "HL")
                event_type = "BEARISH_CHOCH" if is_choch else "BEARISH_BOS"
                if is_choch and has_displacement:
                    event_type = "BEARISH_MSS"

                events.append({
                    "index": i,
                    "type": event_type,
                    "direction": "BEARISH",
                    "brokenLevel": last_ref_low["price"],
                    "closePrice": round(c_close, 2),
                    "brokenSwingLabel": last_ref_low.get("label", "LOW"),
                    "timestamp": ts,
                    "timeframe": timeframe,
                    "status": "CONFIRMED",
                    "displacementRatio": displacement_ratio,
                    "hasDisplacement": has_displacement,
                    "strength": "HIGH" if has_displacement else "MODERATE",
                    "description": (
                        f"Bearish Market Structure Shift (MSS) below ₹{last_ref_low['price']} with displacement."
                        if event_type == "BEARISH_MSS" else
                        f"Bearish {'Change of Character (CHoCH)' if is_choch else 'Break of Structure (BOS)'} confirmed below ₹{last_ref_low['price']}."
                    )
                })
                current_trend = "BEARISH"

        last_bos = next((e for e in reversed(events) if "BOS" in e["type"]), None)
        last_choch = next((e for e in reversed(events) if "CHOCH" in e["type"] or "MSS" in e["type"]), None)

        return {
            "events": events[-10:],
            "currentStructure": current_trend,
            "lastBos": last_bos,
            "lastChoch": last_choch,
        }

    @classmethod
    def analyze_market_structure(
        cls,
        df: pd.DataFrame,
        timeframe: str = "15m"
    ) -> Dict[str, Any]:
        """
        Comprehensive market structure analysis combining:
        - External Structure (Macro swings, major dealing boundaries)
        - Internal Structure (Intra-leg swings, minor shifts)
        - Trend point classification (HH, HL, LH, LL)
        - BOS, CHoCH, and MSS detection with confirmation status
        """
        if df is None or len(df) < 5:
            return {
                "timeframe": timeframe,
                "status": "INSUFFICIENT_DATA",
                "externalSwings": [],
                "internalSwings": [],
                "classifiedPoints": [],
                "bosChoch": {"events": [], "currentStructure": "NEUTRAL", "lastBos": None, "lastChoch": None},
                "summary": "Insufficient candle bars to evaluate institutional structure.",
            }

        # 1. Major External Swings (Window = 4-5)
        external_swings = cls.identify_swings(df, window=4, timeframe=timeframe, structure_type="EXTERNAL")

        # 2. Minor Internal Swings (Window = 2)
        internal_swings = cls.identify_swings(df, window=2, timeframe=timeframe, structure_type="INTERNAL")

        # 3. Classify Trend Points (HH, HL, LH, LL)
        classified_points = cls.classify_trend_points(external_swings if len(external_swings) >= 4 else internal_swings)

        # 4. BOS, CHoCH and MSS
        bos_choch = cls.detect_bos_and_choch(df, classified_points, timeframe=timeframe)

        # Build structural summary
        last_h = next((p for p in reversed(classified_points) if p["type"] == "SWING_HIGH"), None)
        last_l = next((p for p in reversed(classified_points) if p["type"] == "SWING_LOW"), None)

        struct_bias = bos_choch.get("currentStructure", "NEUTRAL")

        # Fallback trend direction from price momentum if no BOS/CHoCH yet
        if struct_bias == "NEUTRAL" and len(df) >= 5:
            first_c = float(df.iloc[0]["close"])
            last_c = float(df.iloc[-1]["close"])
            pct_change = (last_c - first_c) / first_c if first_c > 0 else 0
            if pct_change > 0.005:
                struct_bias = "BULLISH"
            elif pct_change < -0.005:
                struct_bias = "BEARISH"

        h_label = last_h["label"] if last_h else "N/A"
        l_label = last_l["label"] if last_l else "N/A"

        summary = (
            f"{timeframe.upper()} Market Structure is {struct_bias}. "
            f"Last external points: {h_label} at ₹{last_h['price'] if last_h else 0} and "
            f"{l_label} at ₹{last_l['price'] if last_l else 0}."
        )

        return {
            "timeframe": timeframe,
            "status": "CONFIRMED",
            "structureBias": struct_bias,
            "externalSwings": external_swings[-8:],
            "internalSwings": internal_swings[-12:],
            "classifiedPoints": classified_points[-8:],
            "bosChoch": bos_choch,
            "summary": summary,
        }
