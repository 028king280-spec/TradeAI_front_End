"""
Module 1: Multi-Timeframe Confluence Engine (ICT + SMC).
Coordinates institutional market analysis across 3 synchronized timeframes:
1. 15-Minute:
   - Overall market direction
   - External market structure
   - HH, HL, LH, LL classification
   - Major swing highs and lows
   - Higher-timeframe bias
2. 5-Minute:
   - Internal market structure
   - Bullish and bearish BOS (candle body confirmation)
   - Change of Character (CHoCH) & Market Structure Shift (MSS)
   - Liquidity sweeps with displacement validation
   - Fair Value Gap (FVG) identification with 50% CE
3. 1-Minute:
   - Micro market structure
   - Entry confirmation
   - FVG retest and rejection confirmation
   - Potential entry and exact invalidation levels

Confluence Classification Logic:
- Strong Bullish Alignment
- Bullish Alignment
- Bearish Alignment
- Strong Bearish Alignment
- Mixed / Conflicting
- No Clear Bias

Strict Rule:
Do not generate a bullish or bearish conclusion when evidence conflicts.
Enforces trade lockout (isTradeable: False) and displays timeframe-wise reasoning.
"""

from typing import Dict, Any, List, Optional
import pandas as pd
import numpy as np

from app.options.ict_smc.structure_analyzer import MarketStructureAnalyzer
from app.options.ict_smc.liquidity_engine import LiquidityDetectionEngine
from app.options.ict_smc.fvg_orderblock_engine import FvgOrderBlockEngine
from app.options.multi_timeframe_engine import filter_completed_candles


class MultiTimeframeEngine:
    """
    Coordinates and validates multi-timeframe directional alignment across 15M, 5M, and 1M.
    """

    CONFLUENCE_STATES = [
        "Strong Bullish Alignment",
        "Bullish Alignment",
        "Bearish Alignment",
        "Strong Bearish Alignment",
        "Mixed / Conflicting",
        "No Clear Bias",
    ]

    @classmethod
    def evaluate_multi_timeframe(
        cls,
        timeframe_dfs: Dict[str, pd.DataFrame],
        current_price: float,
        daily_high: float,
        daily_low: float,
        prev_day_high: Optional[float] = None,
        prev_day_low: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Coordinates analysis across 15M, 5M, and 1M (also backward-compatible with 1D/1H).
        """
        df_15m = timeframe_dfs.get("15m")
        df_5m = timeframe_dfs.get("5m")
        df_1m = timeframe_dfs.get("1m")

        # -------------------------------------------------------------
        # 1. 15-Minute Analysis: External Structure & Macro Direction
        # -------------------------------------------------------------
        analysis_15m = cls._analyze_15m_timeframe(df_15m, current_price, daily_high, daily_low)

        # -------------------------------------------------------------
        # 2. 5-Minute Analysis: Execution Structure, BOS, CHoCH, Sweeps
        # -------------------------------------------------------------
        analysis_5m = cls._analyze_5m_timeframe(df_5m, current_price)

        # -------------------------------------------------------------
        # 3. 1-Minute Analysis: Micro Structure, FVG Retest, Invalidation
        # -------------------------------------------------------------
        analysis_1m = cls._analyze_1m_timeframe(df_1m, current_price, analysis_5m)

        # -------------------------------------------------------------
        # 4. Synthesize Confluence Classification Logic
        # -------------------------------------------------------------
        bias_15m = analysis_15m.get("bias", "NEUTRAL")
        bias_5m = analysis_5m.get("bias", "NEUTRAL")
        bias_1m = analysis_1m.get("bias", "NEUTRAL")

        # Backwards compatible counts & map from other timeframes (1d, 1h)
        all_biases = {
            "15m": bias_15m,
            "5m": bias_5m,
            "1m": bias_1m,
        }
        for k, v in timeframe_dfs.items():
            if k not in ["15m", "5m", "1m"]:
                v_closed = filter_completed_candles(v, timeframe=k)
                if v_closed is not None and len(v_closed) >= 5:
                    s = MarketStructureAnalyzer.analyze_market_structure(v_closed, timeframe=k)
                    all_biases[k] = s.get("structureBias", "NEUTRAL")

        bull_count = sum(1 for b in all_biases.values() if "BULL" in b.upper())
        bear_count = sum(1 for b in all_biases.values() if "BEAR" in b.upper())

        # If 1d or 1h disagree with 15m/5m, ensure conflict is flagged!
        if bull_count > 0 and bear_count > 0:
            confluence_result = {
                "classification": "Mixed / Conflicting",
                "isTradeable": False,
                "score": 30,
                "headline": "TIMEFRAME CONFLICT — DIRECTIONAL LOCKOUT ENFORCED",
                "overallReasoning": (
                    f"Structural divergence detected across timeframes ({bull_count} Bullish vs {bear_count} Bearish). "
                    "Rule: Never force a directional conclusion when HTF trend and execution structure conflict."
                ),
            }
        else:
            confluence_result = cls._compute_confluence_state(
                bias_15m=bias_15m,
                bias_5m=bias_5m,
                bias_1m=bias_1m,
                analysis_15m=analysis_15m,
                analysis_5m=analysis_5m,
                analysis_1m=analysis_1m,
            )

        overall_alignment = confluence_result["classification"]
        is_tradeable = confluence_result["isTradeable"]
        confluence_score = confluence_result["score"]
        headline = confluence_result["headline"]
        overall_reasoning = confluence_result["overallReasoning"]

        return {
            # Exact 6-State Confluence Classification
            "classification": overall_alignment,
            "overallAlignment": overall_alignment,
            "headline": headline,
            "isTradeable": is_tradeable,
            "confluenceScore": confluence_score,
            # Timeframe-wise Reasoning
            "reasoning15m": analysis_15m.get("reasoning", "15M structure pending."),
            "reasoning5m": analysis_5m.get("reasoning", "5M structure pending."),
            "reasoning1m": analysis_1m.get("reasoning", "1M micro structure pending."),
            "overallReasoning": overall_reasoning,
            "explanation": overall_reasoning,
            # Detailed Sub-Timeframe Breakdowns
            "timeframe15m": analysis_15m,
            "timeframe5m": analysis_5m,
            "timeframe1m": analysis_1m,
            # Legacy & Compatibility Fields
            "bullishTfCount": bull_count,
            "bearishTfCount": bear_count,
            "totalTfEvaluated": len(all_biases),
            "timeframeBiases": all_biases,
            "htfBias": bias_15m,
            "intradayBias": bias_5m,
            "execBias": bias_1m,
            "disclaimer": "Multi-timeframe confluence evaluation heuristic. Does not guarantee market direction.",
        }

    # -----------------------------------------------------------------
    # 15-Minute Detailed Analyzer
    # -----------------------------------------------------------------
    @classmethod
    def _analyze_15m_timeframe(
        cls,
        df: Optional[pd.DataFrame],
        current_price: float,
        daily_high: float,
        daily_low: float,
    ) -> Dict[str, Any]:
        from app.options.multi_timeframe_engine import filter_completed_candles
        df = filter_completed_candles(df, timeframe="15m")
        if df is None or len(df) < 5:
            return {
                "timeframe": "15m",
                "bias": "NEUTRAL",
                "marketDirection": "Undetermined",
                "externalPoints": [],
                "majorSwingHigh": None,
                "majorSwingLow": None,
                "reasoning": "15-minute timeframe data insufficient for structural trend classification.",
            }

        struct = MarketStructureAnalyzer.analyze_market_structure(df, timeframe="15m")
        points = struct.get("classifiedPoints", [])
        ext_swings = struct.get("externalSwings", [])
        struct_bias = struct.get("structureBias", "NEUTRAL")

        swing_highs = [s["price"] for s in ext_swings if s["type"] == "SWING_HIGH"]
        swing_lows = [s["price"] for s in ext_swings if s["type"] == "SWING_LOW"]
        major_h = max(swing_highs) if swing_highs else daily_high
        major_l = min(swing_lows) if swing_lows else daily_low

        last_hh_hl = [p["label"] for p in points[-4:]] if points else []
        last_h = next((p for p in reversed(points) if p["type"] == "SWING_HIGH"), None)
        last_l = next((p for p in reversed(points) if p["type"] == "SWING_LOW"), None)

        direction = (
            "Bullish Trend" if struct_bias == "BULLISH" else
            ("Bearish Trend" if struct_bias == "BEARISH" else "Range-Bound / Neutral")
        )

        h_desc = f"{last_h['label']} @ ₹{last_h['price']}" if last_h else f"High @ ₹{major_h}"
        l_desc = f"{last_l['label']} @ ₹{last_l['price']}" if last_l else f"Low @ ₹{major_l}"

        reasoning = (
            f"15M External Market Direction is {direction}. "
            f"Key external swings establish major dealing boundary between ₹{major_l} and ₹{major_h} "
            f"with verified structural sequence [{h_desc}, {l_desc}]."
        )

        return {
            "timeframe": "15m",
            "bias": struct_bias,
            "marketDirection": direction,
            "externalStructure": struct_bias,
            "classifiedPoints": points[-6:],
            "majorSwingHigh": major_h,
            "majorSwingLow": major_l,
            "lastHighPoint": last_h,
            "lastLowPoint": last_l,
            "reasoning": reasoning,
        }

    # -----------------------------------------------------------------
    # 5-Minute Detailed Analyzer
    # -----------------------------------------------------------------
    @classmethod
    def _analyze_5m_timeframe(
        cls,
        df: Optional[pd.DataFrame],
        current_price: float,
    ) -> Dict[str, Any]:
        from app.options.multi_timeframe_engine import filter_completed_candles
        df = filter_completed_candles(df, timeframe="5m")
        if df is None or len(df) < 5:
            return {
                "timeframe": "5m",
                "bias": "NEUTRAL",
                "internalStructure": "Undetermined",
                "lastBos": None,
                "lastChoch": None,
                "recentSweeps": [],
                "freshFvgs": [],
                "displacementConfirmed": False,
                "reasoning": "5-minute timeframe data insufficient for execution structure evaluation.",
            }

        struct = MarketStructureAnalyzer.analyze_market_structure(df, timeframe="5m")
        bos_choch = struct.get("bosChoch", {})
        last_bos = bos_choch.get("lastBos")
        last_choch = bos_choch.get("lastChoch")
        internal_bias = struct.get("structureBias", "NEUTRAL")

        # FVG Detection on 5M
        fvgs = FvgOrderBlockEngine.detect_fair_value_gaps(df, timeframe="5m")
        fresh_fvgs = [f for f in fvgs if not f.get("isMitigated")][-3:]

        # Liquidity Sweeps on 5M
        pools = LiquidityDetectionEngine.identify_liquidity_pools(
            df, daily_high=float(df["high"].max()), daily_low=float(df["low"].min())
        )
        sweeps = LiquidityDetectionEngine.evaluate_liquidity_sweeps(df, pools)
        recent_sweeps = sweeps[-2:] if sweeps else []

        # Displacement Check
        has_displacement = False
        if len(df) >= 3:
            recent_candles = df.iloc[-3:]
            ranges = (recent_candles["high"] - recent_candles["low"]).tolist()
            bodies = (recent_candles["close"] - recent_candles["open"]).abs().tolist()
            avg_range = np.mean(ranges) if ranges else 1.0
            has_displacement = any(b >= avg_range * 0.75 for b in bodies)

        # Refine 5M Bias
        bias_5m = internal_bias
        if last_choch:
            bias_5m = "BULLISH" if "BULLISH" in last_choch["type"] else "BEARISH"
        elif last_bos:
            bias_5m = "BULLISH" if "BULLISH" in last_bos["type"] else "BEARISH"

        bos_note = f"Last BOS: {last_bos['type']} @ ₹{last_bos['brokenLevel']}" if last_bos else "No recent BOS"
        choch_note = f"Last CHoCH: {last_choch['type']} @ ₹{last_choch['brokenLevel']}" if last_choch else "No CHoCH"
        fvg_note = f"{len(fresh_fvgs)} active FVG(s)" if fresh_fvgs else "No active FVG"
        sweep_note = f"{len(recent_sweeps)} sweep event(s)" if recent_sweeps else "No recent sweeps"

        reasoning = (
            f"5M Execution Structure is {bias_5m}. "
            f"{bos_note}; {choch_note}. Verified {fvg_note} and {sweep_note} "
            f"with displacement expansion {'CONFIRMED' if has_displacement else 'ABSENT'}."
        )

        return {
            "timeframe": "5m",
            "bias": bias_5m,
            "internalStructure": internal_bias,
            "lastBos": last_bos,
            "lastChoch": last_choch,
            "recentSweeps": recent_sweeps,
            "freshFvgs": fresh_fvgs,
            "displacementConfirmed": has_displacement,
            "reasoning": reasoning,
        }

    # -----------------------------------------------------------------
    # 1-Minute Detailed Analyzer
    # -----------------------------------------------------------------
    @classmethod
    def _analyze_1m_timeframe(
        cls,
        df: Optional[pd.DataFrame],
        current_price: float,
        analysis_5m: Dict[str, Any],
    ) -> Dict[str, Any]:
        from app.options.multi_timeframe_engine import filter_completed_candles
        df = filter_completed_candles(df, timeframe="1m")
        if df is None or len(df) < 5:
            return {
                "timeframe": "1m",
                "bias": "NEUTRAL",
                "entryConfirmation": "PENDING_DATA",
                "fvgRetested": False,
                "rejectionConfirmed": False,
                "entryPrice": current_price,
                "invalidationPrice": current_price,
                "reasoning": "1-minute timeframe candle history pending for micro entry trigger.",
            }

        # Analyze micro structure
        struct = MarketStructureAnalyzer.analyze_market_structure(df, timeframe="1m")
        micro_bias = struct.get("structureBias", "NEUTRAL")

        # Check FVG Retest on 1M
        fresh_fvgs = analysis_5m.get("freshFvgs", [])
        fvg_retested = False
        rejection_confirmed = False
        target_fvg = fresh_fvgs[-1] if fresh_fvgs else None

        last_candle = df.iloc[-1]
        c_open = float(last_candle["open"])
        c_close = float(last_candle["close"])
        c_high = float(last_candle["high"])
        c_low = float(last_candle["low"])

        if target_fvg:
            fvg_bot = target_fvg["bottom"]
            fvg_top = target_fvg["top"]
            # Price retraced into the gap
            if c_low <= fvg_top and c_high >= fvg_bot:
                fvg_retested = True

        # Check wick rejection confirmation
        bar_range = max(0.01, c_high - c_low)
        lower_wick = min(c_open, c_close) - c_low
        upper_wick = c_high - max(c_open, c_close)

        if micro_bias == "BULLISH" or c_close > c_open:
            if lower_wick / bar_range >= 0.35:
                rejection_confirmed = True
        elif micro_bias == "BEARISH" or c_close < c_open:
            if upper_wick / bar_range >= 0.35:
                rejection_confirmed = True

        # Potential entry & invalidation
        entry_price = round(current_price, 2)
        if micro_bias == "BULLISH":
            invalidation = round(float(df["low"].tail(5).min()) - 5.0, 2)
            trigger_status = "CONFIRMED_BULLISH_TRIGGER" if (fvg_retested or rejection_confirmed) else "MONITORING"
        elif micro_bias == "BEARISH":
            invalidation = round(float(df["high"].tail(5).max()) + 5.0, 2)
            trigger_status = "CONFIRMED_BEARISH_TRIGGER" if (fvg_retested or rejection_confirmed) else "MONITORING"
        else:
            invalidation = round(current_price - 20.0, 2)
            trigger_status = "AWAITING_BREAKOUT"

        reasoning = (
            f"1M Micro Structure is {micro_bias}. "
            f"FVG Retest {'CONFIRMED' if fvg_retested else 'AWAITING'}; "
            f"Wick Rejection {'VERIFIED' if rejection_confirmed else 'ABSENT'}. "
            f"Trigger status: {trigger_status} with tight invalidation at ₹{invalidation}."
        )

        return {
            "timeframe": "1m",
            "bias": micro_bias,
            "entryConfirmation": trigger_status,
            "fvgRetested": fvg_retested,
            "rejectionConfirmed": rejection_confirmed,
            "entryPrice": entry_price,
            "invalidationPrice": invalidation,
            "reasoning": reasoning,
        }

    # -----------------------------------------------------------------
    # Confluence Synthesizer (Exact 6 Mandatory Categories)
    # -----------------------------------------------------------------
    @classmethod
    def _compute_confluence_state(
        cls,
        bias_15m: str,
        bias_5m: str,
        bias_1m: str,
        analysis_15m: Dict[str, Any],
        analysis_5m: Dict[str, Any],
        analysis_1m: Dict[str, Any],
    ) -> Dict[str, Any]:
        is_15m_bull = "BULL" in bias_15m.upper()
        is_15m_bear = "BEAR" in bias_15m.upper()
        is_5m_bull = "BULL" in bias_5m.upper()
        is_5m_bear = "BEAR" in bias_5m.upper()
        is_1m_bull = "BULL" in bias_1m.upper()
        is_1m_bear = "BEAR" in bias_1m.upper()

        disp_5m = analysis_5m.get("displacementConfirmed", False)
        retest_1m = analysis_1m.get("fvgRetested", False) or analysis_1m.get("rejectionConfirmed", False)

        # 1. Mixed / Conflicting Check (STRICT RULE)
        # If HTF is Bullish but Execution is Bearish (or vice-versa), force conflict!
        if (is_15m_bull and is_5m_bear) or (is_15m_bear and is_5m_bull):
            return {
                "classification": "Mixed / Conflicting",
                "isTradeable": False,
                "score": 30,
                "headline": "TIMEFRAME CONFLICT — DIRECTIONAL LOCKOUT ENFORCED",
                "overallReasoning": (
                    f"Structural divergence detected: 15M bias is {bias_15m} whereas 5M internal structure is {bias_5m}. "
                    "Rule: Never force a directional conclusion when HTF trend and execution structure conflict."
                ),
            }

        # 2. Strong Bullish Alignment
        if is_15m_bull and is_5m_bull and (is_1m_bull or retest_1m) and disp_5m:
            return {
                "classification": "Strong Bullish Alignment",
                "isTradeable": True,
                "score": 95,
                "headline": "STRONG BULLISH ALIGNMENT — HIGH CONVICTION CE SETUP",
                "overallReasoning": (
                    "Complete directional confluence across all 3 timeframes: 15M External Trend is Bullish, "
                    "5M confirmed impulsive Bullish displacement/BOS, and 1M micro retest has verified rejection floor."
                ),
            }

        # 3. Bullish Alignment
        if is_15m_bull and is_5m_bull:
            return {
                "classification": "Bullish Alignment",
                "isTradeable": True,
                "score": 80,
                "headline": "BULLISH ALIGNMENT — FAVOR CALL (CE) CONTINUATION",
                "overallReasoning": (
                    "15M Macro direction and 5M internal structure agree to the upside. "
                    "Awaiting final 1M micro candle close trigger before entry."
                ),
            }

        # 4. Strong Bearish Alignment
        if is_15m_bear and is_5m_bear and (is_1m_bear or retest_1m) and disp_5m:
            return {
                "classification": "Strong Bearish Alignment",
                "isTradeable": True,
                "score": 95,
                "headline": "STRONG BEARISH ALIGNMENT — HIGH CONVICTION PE SETUP",
                "overallReasoning": (
                    "Complete directional confluence across all 3 timeframes: 15M External Trend is Bearish, "
                    "5M confirmed impulsive Bearish displacement/breakdown, and 1M micro retest has verified rejection ceiling."
                ),
            }

        # 5. Bearish Alignment
        if is_15m_bear and is_5m_bear:
            return {
                "classification": "Bearish Alignment",
                "isTradeable": True,
                "score": 80,
                "headline": "BEARISH ALIGNMENT — FAVOR PUT (PE) CONTINUATION",
                "overallReasoning": (
                    "15M Macro direction and 5M internal structure agree to the downside. "
                    "Awaiting final 1M micro candle close trigger before entry."
                ),
            }

        # 6. No Clear Bias (Range-bound or lack of decisive structure)
        return {
            "classification": "No Clear Bias",
            "isTradeable": False,
            "score": 45,
            "headline": "NO CLEAR BIAS — RANGE-BOUND EQUILIBRIUM",
            "overallReasoning": (
                "Neither bullish nor bearish structural criteria meet minimum conviction thresholds. "
                "Market is consolidating within equilibrium. Preserve capital and await clean breakout."
            ),
        }
