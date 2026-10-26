from typing import List, Dict, Any, Optional
import numpy as np
import pandas as pd
from datetime import datetime, timezone


def compute_options_support_resistance_ladder(
    current_price: float,
    daily_high: float,
    daily_low: float,
    daily_close: float,
    daily_open: float,
    candles_df: Optional[pd.DataFrame] = None,
    call_wall: Optional[float] = None,
    put_wall: Optional[float] = None,
    max_pain: Optional[float] = None,
    atr_14: Optional[float] = None
) -> Dict[str, Any]:
    """
    Constructs an institutional Support & Resistance ladder for Indian index options.
    Distinguishes Price-Derived levels from Option-Chain (OI) derived levels.
    """
    curr = float(current_price)
    h = float(daily_high)
    l = float(daily_low)
    c = float(daily_close)
    rng = max(1.0, h - l)

    # 1. Camarilla Pivots
    h4 = c + (rng * 1.1) / 2.0  # Breakout resistance
    h3 = c + (rng * 1.1) / 4.0  # Reversal resistance
    l3 = c - (rng * 1.1) / 4.0  # Reversal support
    l4 = c - (rng * 1.1) / 2.0  # Breakdown support

    # 2. Classic Floor Pivots
    pivot = (h + l + c) / 3.0
    r1 = (2.0 * pivot) - l
    s1 = (2.0 * pivot) - h
    r2 = pivot + rng
    s2 = pivot - rng
    r3 = h + 2.0 * (pivot - l)
    s3 = l - 2.0 * (h - pivot)

    # Candidate Raw Levels
    raw_levels = [
        {"name": "Previous Day High", "price": h, "type": "PRICE_ACTION", "method": "Prior Session High", "strength": "Major"},
        {"name": "Previous Day Low", "price": l, "type": "PRICE_ACTION", "method": "Prior Session Low", "strength": "Major"},
        {"name": "Day Open", "price": daily_open, "type": "PRICE_ACTION", "method": "Session Open", "strength": "Minor"},
        {"name": "Camarilla H4 (Breakout)", "price": h4, "type": "PRICE_ACTION", "method": "Camarilla Breakout Level", "strength": "Major"},
        {"name": "Camarilla H3 (Reversal)", "price": h3, "type": "PRICE_ACTION", "method": "Camarilla Resistance", "strength": "Moderate"},
        {"name": "Camarilla L3 (Reversal)", "price": l3, "type": "PRICE_ACTION", "method": "Camarilla Demand Zone", "strength": "Moderate"},
        {"name": "Camarilla L4 (Breakdown)", "price": l4, "type": "PRICE_ACTION", "method": "Camarilla Breakdown Level", "strength": "Major"},
        {"name": "Classic Pivot Point", "price": pivot, "type": "PRICE_ACTION", "method": "Floor Pivot Equilibrium", "strength": "Moderate"},
        {"name": "Classic R1", "price": r1, "type": "PRICE_ACTION", "method": "Floor Pivot R1", "strength": "Moderate"},
        {"name": "Classic S1", "price": s1, "type": "PRICE_ACTION", "method": "Floor Pivot S1", "strength": "Moderate"},
        {"name": "Classic R2", "price": r2, "type": "PRICE_ACTION", "method": "Floor Pivot R2", "strength": "Major"},
        {"name": "Classic S2", "price": s2, "type": "PRICE_ACTION", "method": "Floor Pivot S2", "strength": "Major"},
    ]

    # Incorporate Option Chain levels if valid
    if call_wall and call_wall > 0:
        raw_levels.append({
            "name": f"Call Wall (OI Strike {int(call_wall)})",
            "price": float(call_wall),
            "type": "OPTION_CHAIN",
            "method": "Highest CE Open Interest Ceiling",
            "strength": "Major",
        })

    if put_wall and put_wall > 0:
        raw_levels.append({
            "name": f"Put Wall (OI Strike {int(put_wall)})",
            "price": float(put_wall),
            "type": "OPTION_CHAIN",
            "method": "Highest PE Open Interest Floor",
            "strength": "Major",
        })

    if max_pain and max_pain > 0:
        raw_levels.append({
            "name": f"Max Pain ({int(max_pain)})",
            "price": float(max_pain),
            "type": "OPTION_CHAIN",
            "method": "Option Max Pain (Descriptive)",
            "strength": "Moderate",
        })

    # Separate into Resistances (price > current) and Supports (price < current)
    # Deduplicate nearly identical levels (within 0.1% threshold)
    threshold = curr * 0.0015

    resistances = [x for x in raw_levels if x["price"] > curr + (curr * 0.0005)]
    supports = [x for x in raw_levels if x["price"] < curr - (curr * 0.0005)]

    # Sort
    resistances.sort(key=lambda x: x["price"])  # ascending from nearest to farthest
    supports.sort(key=lambda x: x["price"], reverse=True)  # descending from nearest to farthest

    def deduplicate(level_list):
        result = []
        for item in level_list:
            if not any(abs(item["price"] - r["price"]) < threshold for r in result):
                result.append(item)
        return result

    dedup_res = deduplicate(resistances)
    dedup_sup = deduplicate(supports)

    now_ts = datetime.now(timezone.utc).isoformat()

    # Build Support 1, 2, 3
    s1_obj = dedup_sup[0] if len(dedup_sup) > 0 else {"name": "S1 (Estimated)", "price": round(curr * 0.992, 2), "type": "PRICE_ACTION", "method": "ATR Band", "strength": "Moderate"}
    s2_obj = dedup_sup[1] if len(dedup_sup) > 1 else {"name": "S2 (Estimated)", "price": round(curr * 0.985, 2), "type": "PRICE_ACTION", "method": "ATR Band", "strength": "Major"}
    s3_obj = dedup_sup[2] if len(dedup_sup) > 2 else {"name": "S3 (Estimated)", "price": round(curr * 0.978, 2), "type": "PRICE_ACTION", "method": "ATR Band", "strength": "Major"}

    # Build Resistance 1, 2, 3
    r1_obj = dedup_res[0] if len(dedup_res) > 0 else {"name": "R1 (Estimated)", "price": round(curr * 1.008, 2), "type": "PRICE_ACTION", "method": "ATR Band", "strength": "Moderate"}
    r2_obj = dedup_res[1] if len(dedup_res) > 1 else {"name": "R2 (Estimated)", "price": round(curr * 1.015, 2), "type": "PRICE_ACTION", "method": "ATR Band", "strength": "Major"}
    r3_obj = dedup_res[2] if len(dedup_res) > 2 else {"name": "R3 (Estimated)", "price": round(curr * 1.022, 2), "type": "PRICE_ACTION", "method": "ATR Band", "strength": "Major"}

    def format_level(obj, role):
        p = round(float(obj["price"]), 2)
        dist_pct = round(((p - curr) / curr) * 100.0, 2)
        return {
            "role": role,
            "label": obj["name"],
            "price": p,
            "levelType": obj["type"],
            "calculationMethod": obj["method"],
            "strength": obj["strength"],
            "distancePercent": dist_pct,
            "confirmationStatus": "Confirmed" if abs(dist_pct) < 1.0 else "Untested",
            "timestamp": now_ts,
        }

    ladder = [
        format_level(r3_obj, "Resistance 3"),
        format_level(r2_obj, "Resistance 2"),
        format_level(r1_obj, "Resistance 1"),
        {
            "role": "Current Price",
            "label": "Current Market Level",
            "price": round(curr, 2),
            "levelType": "SPOT",
            "calculationMethod": "Real-time / Latest Close",
            "strength": "Major",
            "distancePercent": 0.0,
            "confirmationStatus": "Active",
            "timestamp": now_ts,
        },
        format_level(s1_obj, "Support 1"),
        format_level(s2_obj, "Support 2"),
        format_level(s3_obj, "Support 3"),
    ]

    # Add Call Wall and Put Wall to ladder if not already represented
    if call_wall and not any(item.get("levelType") == "OPTION_CHAIN" and item.get("role", "").startswith("Resistance") for item in ladder):
        cw_obj = {"name": f"Call Wall (OI Strike {int(call_wall)})", "price": float(call_wall), "type": "OPTION_CHAIN", "method": "Highest CE Open Interest Ceiling", "strength": "Major"}
        ladder.insert(0, format_level(cw_obj, "Call Wall (Major OI Resistance)"))

    if put_wall and not any(item.get("levelType") == "OPTION_CHAIN" and item.get("role", "").startswith("Support") for item in ladder):
        pw_obj = {"name": f"Put Wall (OI Strike {int(put_wall)})", "price": float(put_wall), "type": "OPTION_CHAIN", "method": "Highest PE Open Interest Floor", "strength": "Major"}
        ladder.append(format_level(pw_obj, "Put Wall (Major OI Support)"))

    return {
        "support1": format_level(s1_obj, "Support 1"),
        "support2": format_level(s2_obj, "Support 2"),
        "support3": format_level(s3_obj, "Support 3"),
        "resistance1": format_level(r1_obj, "Resistance 1"),
        "resistance2": format_level(r2_obj, "Resistance 2"),
        "resistance3": format_level(r3_obj, "Resistance 3"),
        "ladder": ladder,
    }

