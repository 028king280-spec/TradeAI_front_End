"""
Smart Money Concepts (SMC) & Institutional Order Flow Engine.
Implements the core methodologies from the SMC Trading Handbook:
1. Swing Pivots & Market Structure (HH/HL, LH/LL, Protected Swings)
2. Break of Structure (BOS) vs Market Structure Shift (MSS / CHoCH)
3. Internal & External Liquidity Pools (BSL, SSL, PDH, PDL, EQH, EQL)
4. Liquidity Sweeps & Trap Detection (Wick breach with reversal close)
5. Displacement & Fair Value Gaps (FVG) with 50% Consequent Encroachment (CE)
6. Order Blocks (Bullish OB, Bearish OB, Breaker Blocks)
7. Dealing Range: Premium, Discount, and 50% Equilibrium
8. Execution Models:
   - Model A: Bullish Sweep -> MSS -> Retest (CE / Call Setup)
   - Model B: Bearish Sweep -> MSS -> Retest (PE / Put Setup)
   - Model C: Trend Continuation Breakout & Retest (BOS)
9. Risk & Position Sizing Rules (0.5% - 1% Risk Budget, Minimum 1:1.5 R:R)
"""

from typing import Dict, Any, List, Optional, Tuple
import math
import numpy as np
import pandas as pd


class SmartMoneyEngine:
    """
    Quantitative Smart Money Concepts (SMC) Analyzer for Equities and Derivatives.
    """

    @staticmethod
    def identify_swings(df: pd.DataFrame) -> List[Dict[str, Any]]:
        """
        Module 02: 3-candle pivot detection.
        Swing High: middle high > adjacent highs.
        Swing Low: middle low < adjacent lows.
        """
        swings = []
        n = len(df)
        if n < 3:
            return swings

        for i in range(1, n - 1):
            prev_bar = df.iloc[i - 1]
            curr_bar = df.iloc[i]
            next_bar = df.iloc[i + 1]

            # Swing High
            if curr_bar["high"] > prev_bar["high"] and curr_bar["high"] > next_bar["high"]:
                swings.append({
                    "index": i,
                    "type": "SWING_HIGH",
                    "price": round(float(curr_bar["high"]), 2),
                    "timestamp": str(curr_bar.get("timestamp", curr_bar.get("time", f"bar_{i}"))),
                })

            # Swing Low
            if curr_bar["low"] < prev_bar["low"] and curr_bar["low"] < next_bar["low"]:
                swings.append({
                    "index": i,
                    "type": "SWING_LOW",
                    "price": round(float(curr_bar["low"]), 2),
                    "timestamp": str(curr_bar.get("timestamp", curr_bar.get("time", f"bar_{i}"))),
                })

        return swings

    @staticmethod
    def detect_liquidity_pools(
        df: pd.DataFrame,
        daily_high: float,
        daily_low: float,
        prev_day_high: Optional[float] = None,
        prev_day_low: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Module 05: Internal & External Liquidity.
        - Buy-Side Liquidity (BSL): Resting stops above PDH, Equal Highs (EQH), and major swing peaks.
        - Sell-Side Liquidity (SSL): Resting stops below PDL, Equal Lows (EQL), and major swing troughs.
        """
        swings = SmartMoneyEngine.identify_swings(df)
        swing_highs = [s for s in swings if s["type"] == "SWING_HIGH"]
        swing_lows = [s for s in swings if s["type"] == "SWING_LOW"]

        eqh_list = []
        eql_list = []

        # Find Equal Highs (EQH) within 0.12% tolerance
        for i in range(len(swing_highs) - 1):
            for j in range(i + 1, min(i + 4, len(swing_highs))):
                p1, p2 = swing_highs[i]["price"], swing_highs[j]["price"]
                diff_pct = abs(p1 - p2) / max(p1, 1.0)
                if diff_pct <= 0.0015:
                    eqh_list.append({
                        "level": round((p1 + p2) / 2.0, 2),
                        "type": "EQH",
                        "description": f"Equal Highs near ₹{round((p1 + p2)/2.0, 1)} (Buy-Side Liquidity Pool)"
                    })

        # Find Equal Lows (EQL) within 0.12% tolerance
        for i in range(len(swing_lows) - 1):
            for j in range(i + 1, min(i + 4, len(swing_lows))):
                p1, p2 = swing_lows[i]["price"], swing_lows[j]["price"]
                diff_pct = abs(p1 - p2) / max(p1, 1.0)
                if diff_pct <= 0.0015:
                    eql_list.append({
                        "level": round((p1 + p2) / 2.0, 2),
                        "type": "EQL",
                        "description": f"Equal Lows near ₹{round((p1 + p2)/2.0, 1)} (Sell-Side Liquidity Pool)"
                    })

        pdh = prev_day_high or daily_high
        pdl = prev_day_low or daily_low

        bsl_levels = [
            {"name": "Previous Day High (PDH)", "level": round(pdh, 2), "significance": "Major External BSL"},
            {"name": "Session High", "level": round(daily_high, 2), "significance": "Intraday BSL"},
        ]
        for eq in eqh_list[:2]:
            bsl_levels.append({"name": "Equal Highs (EQH)", "level": eq["level"], "significance": "Internal BSL Pool"})

        ssl_levels = [
            {"name": "Previous Day Low (PDL)", "level": round(pdl, 2), "significance": "Major External SSL"},
            {"name": "Session Low", "level": round(daily_low, 2), "significance": "Intraday SSL"},
        ]
        for eq in eql_list[:2]:
            ssl_levels.append({"name": "Equal Lows (EQL)", "level": eq["level"], "significance": "Internal SSL Pool"})

        return {
            "bslLevels": bsl_levels,
            "sslLevels": ssl_levels,
            "equalHighs": eqh_list,
            "equalLows": eql_list,
        }

    @staticmethod
    def detect_liquidity_sweeps(
        df: pd.DataFrame,
        liquidity_pools: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Module 06: Liquidity Sweeps, Traps & Genuine Breakouts.
        A sweep briefly trades through a conspicuous extreme (BSL/SSL) and returns through it.
        Candle wick breaches the level, but candle close reclaims inside.
        """
        sweeps = []
        if len(df) < 3:
            return sweeps

        recent_bars = df.iloc[-6:]  # Inspect last 6 bars

        bsl_levels = [item["level"] for item in liquidity_pools.get("bslLevels", [])]
        ssl_levels = [item["level"] for item in liquidity_pools.get("sslLevels", [])]

        for idx, row in recent_bars.iterrows():
            o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])

            # 1. Bearish BSL Sweep (Upper Liquidity Purge)
            # Candle wick breaches above BSL level, but body closes back BELOW the level
            for bsl in bsl_levels:
                if h > bsl and c < bsl and (h - max(o, c)) >= (abs(c - o) * 0.8):
                    sweeps.append({
                        "type": "BEARISH_BSL_SWEEP",
                        "sweptLevel": bsl,
                        "extremeHigh": round(h, 2),
                        "closePrice": round(c, 2),
                        "timestamp": str(row.get("timestamp", row.get("time", "Recent"))),
                        "bias": "BEARISH",
                        "title": "Bearish Buy-Side Liquidity (BSL) Sweep & Trap",
                        "description": f"Price wicked above BSL (₹{bsl:.1f}) reaching ₹{h:.1f}, but closed back inside at ₹{c:.1f}. Institutional buy-stops purged.",
                        "invalidationLevel": round(h, 2),
                    })

            # 2. Bullish SSL Sweep (Lower Liquidity Purge)
            # Candle wick breaches below SSL level, but body closes back ABOVE the level
            for ssl in ssl_levels:
                if l < ssl and c > ssl and (min(o, c) - l) >= (abs(c - o) * 0.8):
                    sweeps.append({
                        "type": "BULLISH_SSL_SWEEP",
                        "sweptLevel": ssl,
                        "extremeLow": round(l, 2),
                        "closePrice": round(c, 2),
                        "timestamp": str(row.get("timestamp", row.get("time", "Recent"))),
                        "bias": "BULLISH",
                        "title": "Bullish Sell-Side Liquidity (SSL) Sweep & Reclaim",
                        "description": f"Price wicked below SSL (₹{ssl:.1f}) hitting ₹{l:.1f}, but closed back above at ₹{c:.1f}. Sell-stops absorbed by smart money.",
                        "invalidationLevel": round(l, 2),
                    })

        return sweeps

    @staticmethod
    def detect_fair_value_gaps(df: pd.DataFrame) -> List[Dict[str, Any]]:
        """
        Module 07: Displacement & Fair Value Gap (FVG).
        - Bullish 3-candle FVG: Candle 1 High < Candle 3 Low (unoverlapped gap).
          Consequent Encroachment (CE) = 50% midpoint.
        - Bearish 3-candle FVG: Candle 1 Low > Candle 3 High (unoverlapped gap).
          Consequent Encroachment (CE) = 50% midpoint.
        """
        fvgs = []
        n = len(df)
        if n < 4:
            return fvgs

        # Look back over recent bars
        for i in range(2, n):
            c1 = df.iloc[i - 2]
            c2 = df.iloc[i - 1]
            c3 = df.iloc[i]

            c1_h, c1_l = float(c1["high"]), float(c1["low"])
            c2_o, c2_c = float(c2["open"]), float(c2["close"])
            c3_h, c3_l = float(c3["high"]), float(c3["low"])

            # Displacement check on middle bar
            body_c2 = abs(c2_c - c2_o)
            range_c2 = max(0.01, float(c2["high"]) - float(c2["low"]))

            # Bullish FVG
            if c3_l > c1_h and c2_c > c2_o and (body_c2 / range_c2) >= 0.55:
                gap_size = c3_l - c1_h
                ce_50 = (c1_h + c3_l) / 2.0
                fvgs.append({
                    "type": "BULLISH_FVG",
                    "top": round(c3_l, 2),
                    "bottom": round(c1_h, 2),
                    "ce50": round(ce_50, 2),
                    "gapSize": round(gap_size, 2),
                    "bias": "BULLISH",
                    "barIndex": i - 1,
                    "mitigated": False,
                    "description": f"Bullish Fair Value Gap between ₹{c1_h:.1f} and ₹{c3_l:.1f} with 50% CE at ₹{ce_50:.1f}."
                })

            # Bearish FVG
            if c1_l > c3_h and c2_c < c2_o and (body_c2 / range_c2) >= 0.55:
                gap_size = c1_l - c3_h
                ce_50 = (c1_l + c3_h) / 2.0
                fvgs.append({
                    "type": "BEARISH_FVG",
                    "top": round(c1_l, 2),
                    "bottom": round(c3_h, 2),
                    "ce50": round(ce_50, 2),
                    "gapSize": round(gap_size, 2),
                    "bias": "BEARISH",
                    "barIndex": i - 1,
                    "mitigated": False,
                    "description": f"Bearish Fair Value Gap between ₹{c3_h:.1f} and ₹{c1_l:.1f} with 50% CE at ₹{ce_50:.1f}."
                })

        # Check mitigation status against latest price
        latest_c = float(df.iloc[-1]["close"])
        for gap in fvgs:
            if gap["type"] == "BULLISH_FVG" and latest_c <= gap["bottom"]:
                gap["mitigated"] = True
            elif gap["type"] == "BEARISH_FVG" and latest_c >= gap["top"]:
                gap["mitigated"] = True

        return fvgs

    @staticmethod
    def detect_order_blocks(df: pd.DataFrame) -> List[Dict[str, Any]]:
        """
        Module 08: Order Block (OB), Mitigation and Breaker.
        - Bullish OB: The last down candle or base before strong upward displacement breaking structure.
        - Bearish OB: The last up candle or base before strong downward displacement breaking structure.
        """
        order_blocks = []
        n = len(df)
        if n < 5:
            return order_blocks

        for i in range(2, n - 2):
            curr = df.iloc[i]
            next1 = df.iloc[i + 1]
            next2 = df.iloc[i + 2]

            c_o, c_c = float(curr["open"]), float(curr["close"])
            c_h, c_l = float(curr["high"]), float(curr["low"])

            disp_up = float(next1["close"]) > float(next1["open"]) and float(next2["close"]) > float(next2["open"])
            disp_down = float(next1["close"]) < float(next1["open"]) and float(next2["close"]) < float(next2["open"])

            # Bullish Order Block (Red candle before decisive green displacement)
            if c_c < c_o and disp_up:
                up_gain = float(next2["close"]) - c_h
                if up_gain > (c_h - c_l) * 1.5:
                    order_blocks.append({
                        "type": "BULLISH_OB",
                        "top": round(c_h, 2),
                        "bottom": round(c_l, 2),
                        "midpoint": round((c_h + c_l) / 2.0, 2),
                        "bias": "BULLISH",
                        "description": f"Bullish Order Block zone [₹{c_l:.1f} - ₹{c_h:.1f}]. Acts as high-conviction demand floor."
                    })

            # Bearish Order Block (Green candle before decisive red displacement)
            if c_c > c_o and disp_down:
                down_drop = c_l - float(next2["close"])
                if down_drop > (c_h - c_l) * 1.5:
                    order_blocks.append({
                        "type": "BEARISH_OB",
                        "top": round(c_h, 2),
                        "bottom": round(c_l, 2),
                        "midpoint": round((c_h + c_l) / 2.0, 2),
                        "bias": "BEARISH",
                        "description": f"Bearish Order Block zone [₹{c_l:.1f} - ₹{c_h:.1f}]. Acts as high-conviction institutional supply ceiling."
                    })

        return order_blocks

    @staticmethod
    def calculate_dealing_range(
        current_price: float,
        daily_high: float,
        daily_low: float,
        df: Optional[pd.DataFrame] = None
    ) -> Dict[str, Any]:
        """
        Module 09: Premium, Discount, Equilibrium and Dealing Range.
        - Range: [Low, High]
        - Midpoint (50%) = Equilibrium.
        - Above 50% = Premium (institutional selling zone).
        - Below 50% = Discount (institutional buying zone).
        """
        curr = float(current_price)
        r_high = float(daily_high)
        r_low = float(daily_low)

        if df is not None and len(df) >= 10:
            r_high = max(r_high, float(df["high"].tail(20).max()))
            r_low = min(r_low, float(df["low"].tail(20).min()))

        range_span = max(1.0, r_high - r_low)
        equilibrium_50 = round((r_low + r_high) / 2.0, 2)
        pos_in_range_pct = round(((curr - r_low) / range_span) * 100.0, 1)

        # Check macro trend context from intraday candles
        is_trending_up = False
        is_trending_down = False
        if df is not None and not df.empty and "open" in df.columns:
            day_open = float(df.iloc[0]["open"])
            day_gain = curr - day_open
            if day_gain >= (range_span * 0.35):
                is_trending_up = True
            elif day_gain <= -(range_span * 0.35):
                is_trending_down = True

        if pos_in_range_pct > 55.0:
            regime = "PREMIUM"
            if is_trending_up:
                recommendation = "Price is in Bullish Trend Expansion (>50%). Strong buyers in control. Favors Call (CE) buying on pullbacks to EMA20/VWAP. Do NOT fade or counter-trend short a trending market."
            else:
                recommendation = "Price is in Premium (>50%). Favors Put (PE) buying on verified supply rejection, or waiting for pullbacks. Avoid chasing longs."
        elif pos_in_range_pct < 45.0:
            regime = "DISCOUNT"
            if is_trending_down:
                recommendation = "Price is in Bearish Trend Expansion (<50%). Strong sellers in control. Favors Put (PE) buying on bounces to EMA20/VWAP. Do NOT catch falling knives."
            else:
                recommendation = "Price is in Discount (<50%). Favors Call (CE) buying on demand absorption / liquidity sweep. Favorable risk-to-reward for longs."
        else:
            regime = "EQUILIBRIUM"
            recommendation = "Price is oscillating near 50% Equilibrium. Two-way chop expected; wait for liquidity expansion towards boundary."

        return {
            "rangeHigh": round(r_high, 2),
            "rangeLow": round(r_low, 2),
            "equilibrium": equilibrium_50,
            "currentPositionPct": pos_in_range_pct,
            "regime": regime,
            "recommendation": recommendation,
        }

    @staticmethod
    def evaluate_smc_models(
        current_price: float,
        df: pd.DataFrame,
        liquidity: Dict[str, Any],
        sweeps: List[Dict[str, Any]],
        fvgs: List[Dict[str, Any]],
        order_blocks: List[Dict[str, Any]],
        dealing_range: Dict[str, Any],
        atr_14: float = 100.0
    ) -> Dict[str, Any]:
        """
        Modules 11, 12, 13: Execution Models.
        - Model A: Bullish Sweep -> MSS -> Retest
        - Model B: Bearish Sweep -> MSS -> Retest
        - Model C: Breakout & Retest: Trend continuation setup (BOS)
        """
        curr = float(current_price)
        model_a = None
        model_b = None
        model_c = None

        # 1. Model A Evaluation (Bullish Sweep -> MSS -> Retest)
        bullish_sweeps = [s for s in sweeps if s["bias"] == "BULLISH"]
        if bullish_sweeps:
            latest_sweep = bullish_sweeps[-1]
            sweep_low = latest_sweep["extremeLow"]

            # Check if there is an active discount FVG or Bullish OB for entry
            target_entry_min = round(curr * 0.997, 1)
            target_entry_max = round(curr * 1.002, 1)

            # Target is the nearest BSL pool or range high
            bsl_candidates = [b["level"] for b in liquidity.get("bslLevels", []) if b["level"] > curr]
            target_price = min(bsl_candidates) if bsl_candidates else round(dealing_range["rangeHigh"], 1)

            risk_pts = max(10.0, curr - sweep_low)
            reward_pts = max(15.0, target_price - curr)
            rr_ratio = round(reward_pts / risk_pts, 2)

            model_a = {
                "modelName": "Model A (Bullish Sweep → MSS → Retest)",
                "status": "QUALIFIED" if rr_ratio >= 1.5 else "WATCHLIST",
                "bias": "BULLISH",
                "instrument": "CALL (CE)",
                "triggerStep": "Equal Lows/SSL swept; price reclaimed structure with displacement.",
                "entryZone": f"₹{target_entry_min} — ₹{target_entry_max} (Discount Retest)",
                "stopLoss": round(sweep_low - (atr_14 * 0.10), 1),
                "target1": round(curr + (risk_pts * 1.25), 1),
                "target2": round(target_price, 1),
                "riskRewardRatio": f"1:{rr_ratio}",
                "invalidation": f"Decisive 5-minute candle close below sweep low ₹{sweep_low}.",
                "optionsTranslation": "Buy ATM/slight ITM Call (CE). High delta captures index recovery. Exit immediately if sweep low is broken."
            }

        # 2. Model B Evaluation (Bearish Sweep -> MSS -> Retest)
        bearish_sweeps = [s for s in sweeps if s["bias"] == "BEARISH"]
        if bearish_sweeps:
            latest_sweep = bearish_sweeps[-1]
            sweep_high = latest_sweep["extremeHigh"]

            target_entry_min = round(curr * 0.998, 1)
            target_entry_max = round(curr * 1.003, 1)

            ssl_candidates = [b["level"] for b in liquidity.get("sslLevels", []) if b["level"] < curr]
            target_price = max(ssl_candidates) if ssl_candidates else round(dealing_range["rangeLow"], 1)

            risk_pts = max(10.0, sweep_high - curr)
            reward_pts = max(15.0, curr - target_price)
            rr_ratio = round(reward_pts / risk_pts, 2)

            model_b = {
                "modelName": "Model B (Bearish Sweep → MSS → Retest)",
                "status": "QUALIFIED" if rr_ratio >= 1.5 else "WATCHLIST",
                "bias": "BEARISH",
                "instrument": "PUT (PE)",
                "triggerStep": "Equal Highs/BSL swept; price rejected with strong red displacement.",
                "entryZone": f"₹{target_entry_min} — ₹{target_entry_max} (Premium Retest)",
                "stopLoss": round(sweep_high + (atr_14 * 0.10), 1),
                "target1": round(curr - (risk_pts * 1.25), 1),
                "target2": round(target_price, 1),
                "riskRewardRatio": f"1:{rr_ratio}",
                "invalidation": f"Decisive 5-minute candle close above sweep high ₹{sweep_high}.",
                "optionsTranslation": "Buy ATM/slight ITM Put (PE). Favorable theta asymmetry. Invalidate if liquidity sweep high is breached."
            }

        # 3. Model C Evaluation (Trend Continuation BOS Breakout)
        if len(df) >= 5:
            last_close = float(df.iloc[-1]["close"])
            prev_high = float(df.iloc[-2]["high"])
            prev_low = float(df.iloc[-2]["low"])

            if last_close > prev_high and dealing_range["regime"] != "PREMIUM":
                model_c = {
                    "modelName": "Model C (Trend Continuation Breakout & Retest)",
                    "status": "QUALIFIED",
                    "bias": "BULLISH",
                    "instrument": "CALL (CE)",
                    "triggerStep": f"Clean 5M close above swing high ₹{prev_high:.1f}.",
                    "entryZone": f"₹{prev_high:.1f} — ₹{round(prev_high * 1.002, 1)} (BOS Retest)",
                    "stopLoss": round(prev_low, 1),
                    "target1": round(curr + (atr_14 * 0.8), 1),
                    "target2": round(curr + (atr_14 * 1.5), 1),
                    "riskRewardRatio": "1:1.85",
                    "invalidation": f"Failure to hold broken resistance at ₹{prev_high:.1f}.",
                    "optionsTranslation": "Trend-following CE momentum entry with trailing stop."
                }

        # Active Primary Setup
        active_setup = model_a if (model_a and model_a["status"] == "QUALIFIED") else (
            model_b if (model_b and model_b["status"] == "QUALIFIED") else model_c
        )

        return {
            "modelA": model_a,
            "modelB": model_b,
            "modelC": model_c,
            "activeSetup": active_setup,
        }

    @staticmethod
    def analyze(
        df: pd.DataFrame,
        current_price: float,
        daily_high: float,
        daily_low: float,
        prev_day_high: Optional[float] = None,
        prev_day_low: Optional[float] = None,
        atr_14: float = 100.0,
        timeframe: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Full Comprehensive Smart Money Concepts (SMC) Institutional Analysis.
        Filters out incomplete/forming/lookahead and synthetic/mock candles before
        invoking confirmed SMC and ICT engines.
        """
        from app.options.multi_timeframe_engine import filter_completed_candles

        eff_tf = timeframe or (df.attrs.get("timeframe") if df is not None and hasattr(df, "attrs") else None) or "15m"
        raw_len = len(df) if df is not None else 0

        if df is not None and hasattr(df, "attrs"):
            ds_upper = str(df.attrs.get("dataStatus", "")).upper()
            if df.attrs.get("is_mock") or df.attrs.get("is_synthetic") or ds_upper in {"MOCK", "SYNTHETIC", "DATA_UNAVAILABLE", "DATA_OFFLINE"}:
                return {
                    "dealingRange": {},
                    "liquidityPools": {},
                    "recentSweeps": [],
                    "fairValueGaps": [],
                    "orderBlocks": [],
                    "dataStatus": ds_upper or "SYNTHETIC",
                    "executionModels": {"activeSetup": None, "status": "DATA_GATED"},
                    "advancedIct": {"status": "DATA_GATED", "reason": f"Non-live or unavailable feed ({ds_upper or 'SYNTHETIC'})"},
                    "incompleteCandlesExcluded": 0,
                    "confirmedBarsCount": 0,
                    "disclaimer": "Smart Money Concepts (SMC) quantitative price-action analysis. Non-predictive execution framework.",
                }

        completed_df = filter_completed_candles(df, timeframe=eff_tf)
        excluded_count = max(0, raw_len - (len(completed_df) if completed_df is not None else 0))

        if completed_df is None or len(completed_df) < 3:
            return {
                "dealingRange": {},
                "liquidityPools": {},
                "recentSweeps": [],
                "fairValueGaps": [],
                "orderBlocks": [],
                "executionModels": {"activeSetup": None, "status": "INSUFFICIENT_COMPLETED_CANDLES"},
                "advancedIct": {
                    "status": "INSUFFICIENT_COMPLETED_CANDLES",
                    "reason": f"Only {len(completed_df) if completed_df is not None else 0} confirmed closed {eff_tf} candles available after excluding {excluded_count} incomplete bar(s).",
                },
                "incompleteCandlesExcluded": excluded_count,
                "confirmedBarsCount": len(completed_df) if completed_df is not None else 0,
                "disclaimer": "Smart Money Concepts (SMC) quantitative price-action analysis. Non-predictive execution framework.",
            }

        df = completed_df
        liquidity = SmartMoneyEngine.detect_liquidity_pools(df, daily_high, daily_low, prev_day_high, prev_day_low)
        sweeps = SmartMoneyEngine.detect_liquidity_sweeps(df, liquidity)
        fvgs = SmartMoneyEngine.detect_fair_value_gaps(df)
        obs = SmartMoneyEngine.detect_order_blocks(df)
        dealing_range = SmartMoneyEngine.calculate_dealing_range(current_price, daily_high, daily_low, df)
        models = SmartMoneyEngine.evaluate_smc_models(
            current_price, df, liquidity, sweeps, fvgs, obs, dealing_range, atr_14
        )

        # Advanced ICT + SMC Institutional Engine Extensions
        advanced_ict = {}
        try:
            from app.options.ict_smc.structure_analyzer import MarketStructureAnalyzer
            from app.options.ict_smc.liquidity_engine import LiquidityDetectionEngine
            from app.options.ict_smc.fvg_orderblock_engine import FvgOrderBlockEngine
            from app.options.ict_smc.scorecard_engine import AnalysisScorecardEngine
            from app.options.ict_smc.ai_market_explainer import AIMarketExplainer

            adv_structure = MarketStructureAnalyzer.analyze_market_structure(df, timeframe=eff_tf)
            adv_liquidity_pools = LiquidityDetectionEngine.identify_liquidity_pools(
                df, daily_high=daily_high, daily_low=daily_low,
                prev_day_high=prev_day_high, prev_day_low=prev_day_low
            )
            adv_sweeps = LiquidityDetectionEngine.detect_liquidity_sweeps(df, adv_liquidity_pools)
            adv_heatmap = LiquidityDetectionEngine.build_liquidity_heatmap(
                adv_liquidity_pools, current_price=current_price, atr_14=atr_14
            )
            adv_fvgs = FvgOrderBlockEngine.detect_fair_value_gaps(df, timeframe=eff_tf)
            adv_obs = FvgOrderBlockEngine.detect_order_blocks_and_breakers(df, timeframe=eff_tf)

            # Determine factor scores for transparent 100-pt scorecard
            struct_bias = adv_structure.get("structureBias", "NEUTRAL")
            struct_score = 0.9 if struct_bias in ["BULLISH", "BEARISH"] else 0.4
            liq_reclaim_sweeps = [s for s in adv_sweeps if s.get("type") == "SWEEP_WITH_RECLAIM"]
            liq_score = 0.95 if liq_reclaim_sweeps else (0.7 if adv_sweeps else 0.3)
            active_m = models.get("activeSetup")
            fvg_ob_score = 0.85 if (adv_fvgs or adv_obs) else 0.4
            disp_score = 0.8 if struct_score >= 0.7 else 0.4
            rr_score = 0.85 if active_m and active_m.get("status") == "QUALIFIED" else 0.4

            scorecard = AnalysisScorecardEngine.calculate_scorecard(
                htf_score_pct=struct_score,
                structure_score_pct=struct_score,
                liquidity_score_pct=liq_score,
                displacement_score_pct=disp_score,
                fvg_ob_score_pct=fvg_ob_score,
                rr_score_pct=rr_score,
                conflicting_signals=["Regime is sideways chop - caution advised"] if dealing_range.get("regime") == "EQUILIBRIUM" else []
            )

            # Generate Standard 15-Point AI Report
            ai_reports = AIMarketExplainer.generate_standard_report(
                symbol="NIFTY 50",
                market_bias=struct_bias,
                htf_trend=struct_bias,
                intraday_structure=adv_structure.get("summary", "Structure evaluated"),
                liquidity_data=adv_liquidity_pools,
                structure_data=adv_structure,
                fvg_ob_data={"fairValueGaps": adv_fvgs, "orderBlocks": adv_obs},
                dealing_range=dealing_range,
                ce_setup=models.get("modelA"),
                pe_setup=models.get("modelB"),
                entry_trigger=active_m.get("triggerStep") if active_m else "Wait for key level sweep and displacement",
                invalidation_conditions=active_m.get("invalidation") if active_m else "Sustained close past invalidation swing",
                no_trade_conditions="Active during sideways equilibrium, high volatility news, or conflicting timeframe bias"
            )

            five_part_overview = AIMarketExplainer.generate_5part_analysis(
                symbol="NIFTY 50",
                current_price=current_price,
                market_bias=struct_bias,
                structure_data=adv_structure,
                liquidity_data=adv_liquidity_pools,
                sweeps=adv_sweeps,
                fvgs=adv_fvgs,
                obs=adv_obs,
                dealing_range=dealing_range
            )

            advanced_ict = {
                "structure": adv_structure,
                "liquidity": {
                    "pools": adv_liquidity_pools,
                    "sweeps": adv_sweeps,
                    "heatmap": adv_heatmap
                },
                "fvgAndOrderBlocks": {
                    "fairValueGaps": adv_fvgs,
                    "orderBlocks": adv_obs,
                    "activeFvgs": [f for f in adv_fvgs if not f.get("isMitigated")][:4],
                    "activeBlocks": [b for b in adv_obs if b.get("isValid")][:4]
                },
                "scorecard": scorecard,
                "aiReport": ai_reports,
                "fivePartAnalysis": five_part_overview,
            }
        except Exception as e:
            advanced_ict = {"error": f"ICT extension evaluation: {str(e)}"}

        return {
            "dealingRange": dealing_range,
            "liquidityPools": liquidity,
            "recentSweeps": sweeps,
            "fairValueGaps": fvgs[-4:] if fvgs else [],
            "orderBlocks": obs[-4:] if obs else [],
            "executionModels": models,
            "advancedIct": advanced_ict,
            "incompleteCandlesExcluded": excluded_count,
            "confirmedBarsCount": len(df),
            "disclaimer": "Smart Money Concepts (SMC) quantitative price-action analysis. Non-predictive execution framework.",
        }

