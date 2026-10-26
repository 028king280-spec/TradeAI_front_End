from typing import List, Dict, Any, Optional
import pandas as pd
import numpy as np


def detect_candlestick_and_chart_patterns(
    candles_df: pd.DataFrame,
    timeframe: str = "15m"
) -> List[Dict[str, Any]]:
    """
    Detects deterministic candlestick and price-action patterns on OHLCV DataFrame.
    
    Returns structured pattern records with:
    - Pattern Name
    - Timeframe
    - Confirmation Status (Confirmed vs Forming)
    - Interpretation (Bullish, Bearish, Neutral)
    - Relevant price levels (trigger, support, resistance, invalidation)
    - Confirmation and invalidation rules
    - Confidence rating
    """
    if candles_df is None or len(candles_df) < 2:
        return []

    patterns: List[Dict[str, Any]] = []
    df = candles_df.copy().reset_index(drop=True)

    # Latest candles
    curr = df.iloc[-1]
    prev1 = df.iloc[-2]
    prev2 = df.iloc[-3] if len(df) >= 3 else prev1

    c_close = float(curr["close"])
    c_open = float(curr["open"])
    c_high = float(curr["high"])
    c_low = float(curr["low"])

    p1_close = float(prev1["close"])
    p1_open = float(prev1["open"])
    p1_high = float(prev1["high"])
    p1_low = float(prev1["low"])

    body_curr = abs(c_close - c_open)
    range_curr = max(0.01, c_high - c_low)
    body_p1 = abs(p1_close - p1_open)
    range_p1 = max(0.01, p1_high - p1_low)

    upper_wick_curr = c_high - max(c_open, c_close)
    lower_wick_curr = min(c_open, c_close) - c_low

    # 1. Bullish Engulfing
    # Prior candle red, current green and completely engulfs prior candle body
    if p1_close < p1_open and c_close > c_open:
        if c_open <= p1_close and c_close >= p1_open and body_curr > body_p1:
            patterns.append({
                "patternName": "Bullish Engulfing",
                "timeframe": timeframe,
                "detectionTimestamp": str(curr.get("timestamp", curr.get("time", "Current"))),
                "interpretation": "BULLISH",
                "confirmed": True,
                "relevantPriceLevels": {
                    "triggerLevel": round(c_high, 2),
                    "supportLevel": round(min(c_low, p1_low), 2),
                    "invalidationLevel": round(min(c_low, p1_low) * 0.998, 2),
                },
                "confirmationCondition": f"Confirmed if subsequent bar opens and sustains above {round(c_close, 2)}.",
                "invalidationCondition": f"Invalidated on candle close below swing low {round(min(c_low, p1_low), 2)}.",
                "confidence": "High",
                "description": "Strong bullish reversal candle showing buyers completely overpowering prior selling pressure."
            })

    # 2. Bearish Engulfing
    # Prior candle green, current red and completely engulfs prior candle body
    if p1_close > p1_open and c_close < c_open:
        if c_open >= p1_close and c_close <= p1_open and body_curr > body_p1:
            patterns.append({
                "patternName": "Bearish Engulfing",
                "timeframe": timeframe,
                "detectionTimestamp": str(curr.get("timestamp", curr.get("time", "Current"))),
                "interpretation": "BEARISH",
                "confirmed": True,
                "relevantPriceLevels": {
                    "triggerLevel": round(c_low, 2),
                    "resistanceLevel": round(max(c_high, p1_high), 2),
                    "invalidationLevel": round(max(c_high, p1_high) * 1.002, 2),
                },
                "confirmationCondition": f"Confirmed on continuation below {round(c_low, 2)}.",
                "invalidationCondition": f"Invalidated on candle close above swing high {round(max(c_high, p1_high), 2)}.",
                "confidence": "High",
                "description": "Strong bearish distribution candle indicating sellers took decisive control."
            })

    # 3. Hammer (Bullish Rejection)
    # Small body near top, long lower wick >= 2x body, minimal upper wick
    if lower_wick_curr >= 2.0 * body_curr and upper_wick_curr <= 0.3 * range_curr and body_curr > 0:
        patterns.append({
            "patternName": "Hammer (Bullish Pin Bar)",
            "timeframe": timeframe,
            "detectionTimestamp": str(curr.get("timestamp", curr.get("time", "Current"))),
            "interpretation": "BULLISH",
            "confirmed": c_close >= p1_close,
            "relevantPriceLevels": {
                "supportLevel": round(c_low, 2),
                "triggerLevel": round(c_high, 2),
                "invalidationLevel": round(c_low * 0.998, 2),
            },
            "confirmationCondition": f"Next candle breaks above hammer high of {round(c_high, 2)}.",
            "invalidationCondition": f"Breach below lower shadow at {round(c_low, 2)}.",
            "confidence": "Medium",
            "description": "Intraday supply absorption; institutional demand stepped in at lower levels."
        })

    # 4. Shooting Star (Bearish Rejection)
    # Small body near bottom, long upper wick >= 2x body, minimal lower wick
    if upper_wick_curr >= 2.0 * body_curr and lower_wick_curr <= 0.3 * range_curr and body_curr > 0:
        patterns.append({
            "patternName": "Shooting Star (Bearish Pin Bar)",
            "timeframe": timeframe,
            "detectionTimestamp": str(curr.get("timestamp", curr.get("time", "Current"))),
            "interpretation": "BEARISH",
            "confirmed": c_close <= p1_close,
            "relevantPriceLevels": {
                "resistanceLevel": round(c_high, 2),
                "triggerLevel": round(c_low, 2),
                "invalidationLevel": round(c_high * 1.002, 2),
            },
            "confirmationCondition": f"Next candle breaks below shooting star low of {round(c_low, 2)}.",
            "invalidationCondition": f"Breach above upper shadow at {round(c_high, 2)}.",
            "confidence": "Medium",
            "description": "Supply rejection at highs; buyers failed to sustain the push, leaving overhead overhang."
        })

    # 5. Doji (Indecision)
    # Body <= 10% of total candle range
    if (body_curr / range_curr) < 0.10:
        patterns.append({
            "patternName": "Doji (Market Indecision)",
            "timeframe": timeframe,
            "detectionTimestamp": str(curr.get("timestamp", curr.get("time", "Current"))),
            "interpretation": "NEUTRAL",
            "confirmed": True,
            "relevantPriceLevels": {
                "rangeHigh": round(c_high, 2),
                "rangeLow": round(c_low, 2),
                "equilibrium": round((c_open + c_close) / 2.0, 2),
            },
            "confirmationCondition": f"Wait for directional breakout above {round(c_high, 2)} or below {round(c_low, 2)}.",
            "invalidationCondition": "Trade remains invalid until range boundary is broken with volume.",
            "confidence": "High",
            "description": "Equilibrium between bulls and bears. Indicates temporary pause or potential trend exhaustion."
        })

    # 6. Price Action Trend Structure (Higher Highs / Higher Lows vs Lower Highs / Lower Lows)
    if len(df) >= 10:
        highs = df["high"].values[-10:]
        lows = df["low"].values[-10:]
        
        # Check if recent 3 swings are higher
        is_higher_highs = highs[-1] > highs[-3] > highs[-5] if len(highs) >= 5 else False
        is_higher_lows = lows[-1] > lows[-3] > lows[-5] if len(lows) >= 5 else False

        is_lower_highs = highs[-1] < highs[-3] < highs[-5] if len(highs) >= 5 else False
        is_lower_lows = lows[-1] < lows[-3] < lows[-5] if len(lows) >= 5 else False

        if is_higher_highs and is_higher_lows:
            patterns.append({
                "patternName": "Higher Highs & Higher Lows (Ascending Channel)",
                "timeframe": timeframe,
                "detectionTimestamp": str(curr.get("timestamp", curr.get("time", "Current"))),
                "interpretation": "BULLISH",
                "confirmed": True,
                "relevantPriceLevels": {
                    "supportLevel": round(float(np.min(lows[-5:])), 2),
                    "channelResistance": round(float(np.max(highs[-5:])), 2),
                },
                "confirmationCondition": "Maintaining sequence above the previous swing low.",
                "invalidationCondition": f"Breakdown below last swing low {round(float(lows[-3]), 2)}.",
                "confidence": "High",
                "description": "Textbook bullish market structure with persistent demand at each pullback."
            })
        elif is_lower_highs and is_lower_lows:
            patterns.append({
                "patternName": "Lower Highs & Lower Lows (Descending Trend)",
                "timeframe": timeframe,
                "detectionTimestamp": str(curr.get("timestamp", curr.get("time", "Current"))),
                "interpretation": "BEARISH",
                "confirmed": True,
                "relevantPriceLevels": {
                    "resistanceLevel": round(float(np.max(highs[-5:])), 2),
                    "supportBreakdown": round(float(np.min(lows[-5:])), 2),
                },
                "confirmationCondition": "Maintaining lower high ceiling on pullbacks.",
                "invalidationCondition": f"Breakout above last swing high {round(float(highs[-3]), 2)}.",
                "confidence": "High",
                "description": "Consistent bearish trend structure with each successive rally encountering lower resistance."
            })
        else:
            # Consolidation Box
            ten_range = float(np.max(highs) - np.min(lows))
            if ten_range / c_close < 0.008:
                patterns.append({
                    "patternName": "Tight Consolidation / Compression Box",
                    "timeframe": timeframe,
                    "detectionTimestamp": str(curr.get("timestamp", curr.get("time", "Current"))),
                    "interpretation": "NEUTRAL",
                    "confirmed": True,
                    "relevantPriceLevels": {
                        "boxUpper": round(float(np.max(highs)), 2),
                        "boxLower": round(float(np.min(lows)), 2),
                    },
                    "confirmationCondition": f"Breakout above {round(float(np.max(highs)), 2)} or breakdown below {round(float(np.min(lows)), 2)}.",
                    "invalidationCondition": "Choppy trading within box boundaries.",
                    "confidence": "Medium",
                    "description": "Volatility compression in play. Tight range usually precedes an aggressive expansion move."
                })

    return patterns
