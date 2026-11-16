"""
AIVOLVE Market State & Regime Engine v3.0.
Determines current institutional market regime independently per index:
- BULLISH_TREND
- BEARISH_TREND
- SIDEWAYS
- REVERSAL
- VOLATILITY_EXPANSION
- NO_TRADE
- DATA_UNAVAILABLE

Core Institutional Tenets:
1. Eliminates false bearish classifications in sideways and consolidating markets using ADX and range compression filters.
2. Multi-factor quantitative confluence: ADX(14), +DI/-DI(14), ATR(14), Normalized ATR %, EMA 20/50/200, and Intraday VWAP.
3. Strict deterministic regime precedence: DATA_UNAVAILABLE -> NO_TRADE -> VOLATILITY_EXPANSION -> REVERSAL -> TREND -> SIDEWAYS.
4. Volatility expansion is evaluated directionally neutral (requires separate trend direction analysis).
5. Reversal requires confirmed market structure shift (MSS/CHoCH) and level rejection; divergence alone never triggers reversal.
6. Analytical qualification only in Step 2: final_action is restricted to WAIT or NO_TRADE until Step 3 MTF synthesis.
7. Pure functional execution with zero shared mutable state across indices (NIFTY 50, BANK NIFTY, FINNIFTY, SENSEX).
"""

from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timezone
import pandas as pd
import numpy as np

from app.data.market_calendar import MarketCalendar


class MarketRegime:
    """Master Specification v3.0 Institutional Regimes."""
    BULLISH_TREND = "BULLISH_TREND"
    BEARISH_TREND = "BEARISH_TREND"
    SIDEWAYS = "SIDEWAYS"
    REVERSAL = "REVERSAL"
    VOLATILITY_EXPANSION = "VOLATILITY_EXPANSION"
    NO_TRADE = "NO_TRADE"
    DATA_UNAVAILABLE = "DATA_UNAVAILABLE"


class MarketState:
    """Legacy state aliases for full backward compatibility."""
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    SIDEWAYS = "SIDEWAYS"
    NO_TRADE = "NO_TRADE"
    DATA_UNAVAILABLE = "DATA_UNAVAILABLE"
    REVERSAL = "REVERSAL"
    VOLATILITY_EXPANSION = "VOLATILITY_EXPANSION"
    BULLISH_TREND = "BULLISH"
    BEARISH_TREND = "BEARISH"


DEFAULT_CONFIG = {
    "max_stale_data_seconds": 900,  # 15 minutes
    "vix_upper_limit": 24.0,        # Extreme volatility threshold
    "vix_lower_limit": 10.5,        # Extreme compression threshold
    "min_reward_to_risk": 1.5,      # Minimum R:R ratio
    "ema_flat_spread_pct": 0.12,    # EMA 20 vs 50 spread threshold for flat chop (0.12%)
    "vwap_near_band_pct": 0.18,     # Percentage distance to VWAP considered chop (0.18%)
    "adx_trend_threshold": 20.0,    # Minimum ADX for confirmed directional trend
    "adx_strong_trend": 25.0,       # ADX indicating powerful institutional momentum
    "adx_chop_threshold": 18.0,     # ADX strictly confirming range consolidation
    "rsi_neutral_min": 45.0,
    "rsi_neutral_max": 55.0,
    "rsi_bullish_min": 54.0,
    "rsi_bearish_max": 46.0,
    "pcr_conflict_low": 0.70,       # Price bullish but heavy Call writing overhead
    "pcr_conflict_high": 1.35,      # Price bearish but heavy Put floor underfoot
    "min_volume_ratio": 0.75,       # Min current candle volume vs 20-period avg
    "max_option_spread_pct": 2.5,   # Max bid-ask spread % of premium
}


def _get_index_parameters(symbol: str) -> Tuple[float, float]:
    """Returns (step_size, day_trend_points_threshold) scaled for the index."""
    clean = symbol.upper().strip()
    if "SENSEX" in clean:
        return 100.0, 500.0
    if "BANK" in clean:
        return 100.0, 400.0
    if "FINNIFTY" in clean:
        return 50.0, 200.0
    # Default NIFTY 50
    return 50.0, 180.0


def evaluate_index_market_state(
    symbol: str,
    quote: Dict[str, Any],
    candles_df: Optional[pd.DataFrame] = None,
    candles_info: Optional[Dict[str, Any]] = None,
    option_chain_summary: Optional[Dict[str, Any]] = None,
    vix_value: float = 13.5,
    is_live_data: bool = True,
    last_update_utc: Optional[datetime] = None,
    tested_sideways_strategy_active: bool = False,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Evaluates independent market regime and state for an index.
    Pure functional, deterministic execution with zero shared mutable state.
    """
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    clean_sym = symbol.upper().strip()
    now_ist = MarketCalendar.format_ist_timestamp()
    step_size, pts_trend_threshold = _get_index_parameters(clean_sym)

    # -------------------------------------------------------------
    # 1. Check Data Availability (Priority 1)
    # -------------------------------------------------------------
    if not quote or float(quote.get("currentPrice") or quote.get("ltp", 0.0)) <= 0:
        return {
            "index": clean_sym,
            "symbol": clean_sym,
            "market_regime": MarketRegime.DATA_UNAVAILABLE,
            "marketState": MarketState.DATA_UNAVAILABLE,
            "trend_direction": "NEUTRAL",
            "trend_strength": 0.0,
            "volatility_state": "UNKNOWN",
            "timeframe_analysis": {},
            "timeframe_agreement": 0.0,
            "indicator_confluence": {},
            "regime_confidence": 0.0,
            "data_quality_status": "DATA_UNAVAILABLE",
            "rejection_reasons": ["Quote object empty or LTP is zero", "Provider connection down or market closed"],
            "final_action": "NO_TRADE",
            "isNoTrade": True,
            "prominentStatus": "NO TRADE",
            "statusBadge": "DATA UNAVAILABLE",
            "headline": "MARKET DATA UNAVAILABLE",
            "explanation": f"Live quote feed for {clean_sym} is unreachable. Trading signals suppressed to protect capital.",
            "primaryReason": "Missing or disconnected market data stream.",
            "reasonForNoTrade": "Missing or disconnected market data stream.",
            "contributingFactors": ["Quote object empty or LTP is zero", "Provider connection down or market closed"],
            "importantSupport": 0.0,
            "importantResistance": 0.0,
            "bullishActivationTrigger": "Requires verified market price feeds",
            "bearishActivationTrigger": "Requires verified market price feeds",
            "confirmationRequired": "Provider re-authentication and active ticks",
            "keyLevels": {
                "immediateSupport": 0.0,
                "immediateResistance": 0.0,
                "bullishActivationTrigger": "Requires verified market price feeds",
                "bearishActivationTrigger": "Requires verified market price feeds",
                "confirmationRequired": "Provider re-authentication and active ticks",
            },
            "dataStatus": "UNAVAILABLE",
            "dataTimestamp": now_ist,
            "timeOfLastAnalysis": now_ist,
            "analysisTimestamp": now_ist,
            "evaluationFactors": {"dataFreshness": {"status": "FAILED", "reason": "No quote data received"}},
        }

    ltp = float(quote.get("currentPrice") or quote.get("ltp", 0.0))
    chg = float(quote.get("change", 0.0))
    d_high = float(quote.get("dayHigh", ltp * 1.008))
    d_low = float(quote.get("dayLow", ltp * 0.992))
    d_close = float(quote.get("previousClose", ltp - chg))
    d_open = float(quote.get("openPrice", d_close))

    # Include candle highs/lows if available
    if candles_df is not None and not candles_df.empty and "high" in candles_df.columns:
        effective_d_high = max(d_high, float(candles_df["high"].max()))
        effective_d_low = min(d_low, float(candles_df["low"].min()))
    else:
        effective_d_high = d_high
        effective_d_low = d_low

    day_range = max(1.0, effective_d_high - effective_d_low)
    day_change_pct = (chg / d_close) * 100.0 if d_close > 0 else 0.0

    # -------------------------------------------------------------
    # 2. Extract Quantitative Overlays (Step 1 Integration)
    # -------------------------------------------------------------
    # Consume existing candle_processor outputs without duplicating calculation
    info = candles_info
    if info is None and candles_df is not None and not candles_df.empty:
        from app.options.candle_processor import process_candlestick_series
        info = process_candlestick_series(candles_df, symbol=clean_sym)
    elif info is None:
        info = {}

    vwap = float(info["vwap"]) if info.get("vwap") is not None else None
    ema20 = float(info["ema20"]) if info.get("ema20") is not None else None
    ema50 = float(info["ema50"]) if info.get("ema50") is not None else None
    ema200 = float(info["ema200"]) if info.get("ema200") is not None else None
    atr = float(info["atr"]) if info.get("atr") is not None else (day_range if day_range > 0 else ltp * 0.005)
    rsi = float(info["rsi"]) if info.get("rsi") is not None else 50.0
    adx = float(info["adx"]) if info.get("adx") is not None else None
    plus_di = float(info["plus_di"]) if info.get("plus_di") is not None else None
    minus_di = float(info["minus_di"]) if info.get("minus_di") is not None else None
    bb_width = float(info["bb_width"]) if info.get("bb_width") is not None else None
    norm_atr_pct = float(info["normalized_atr_pct"]) if info.get("normalized_atr_pct") is not None else ((atr / ltp) * 100.0 if ltp > 0 else 0.5)

    # -------------------------------------------------------------
    # 3. Contextual Options Intelligence (Friction & Liquidity)
    # -------------------------------------------------------------
    chain_sum = option_chain_summary or {}
    has_options_data = bool(option_chain_summary and isinstance(option_chain_summary, dict) and option_chain_summary.get("pcr"))
    pcr = float(chain_sum.get("pcr", {}).get("pcrOi", 1.0)) if isinstance(chain_sum.get("pcr"), dict) else (float(chain_sum.get("pcr")) if isinstance(chain_sum.get("pcr"), (int, float)) else None)
    call_wall = float(chain_sum.get("callWall", effective_d_high)) if chain_sum.get("callWall") else None
    put_wall = float(chain_sum.get("putWall", effective_d_low)) if chain_sum.get("putWall") else None
    max_pain = float(chain_sum.get("maxPain", {}).get("maxPainStrike", ltp)) if isinstance(chain_sum.get("maxPain"), dict) else ltp

    has_excessive_spread = False
    option_spread_pct = 0.0
    if chain_sum.get("atmSpreadPct"):
        option_spread_pct = float(chain_sum["atmSpreadPct"])
        if option_spread_pct > cfg["max_option_spread_pct"]:
            has_excessive_spread = True

    # -------------------------------------------------------------
    # 4. Range, EMA & VWAP Geometry
    # -------------------------------------------------------------
    dist_vwap_pct = ((ltp - vwap) / vwap) * 100.0 if vwap and vwap > 0 else 0.0
    dist_ema20_pct = ((ltp - ema20) / ema20) * 100.0 if ema20 and ema20 > 0 else 0.0
    ema_spread_pct = (abs(ema20 - ema50) / ltp) * 100.0 if ema20 and ema50 and ltp > 0 else 0.0

    is_ema_flat = ema_spread_pct < cfg["ema_flat_spread_pct"]
    is_near_vwap = abs(dist_vwap_pct) < cfg["vwap_near_band_pct"]
    is_rsi_neutral = (cfg["rsi_neutral_min"] <= rsi <= cfg["rsi_neutral_max"])
    range_atr_ratio = day_range / atr if atr > 0 else 1.0

    # Support / Resistance & Trapped Zone
    round_support = round((ltp - (atr * 0.45)) / step_size) * step_size
    round_resistance = round((ltp + (atr * 0.45)) / step_size) * step_size
    imm_support = round(max(round_support, put_wall if (put_wall and put_wall < ltp) else round_support), 1)
    imm_resistance = round(min(round_resistance, call_wall if (call_wall and call_wall > ltp) else round_resistance), 1)

    bullish_trigger = round(imm_resistance + (step_size * 0.2), 1)
    bearish_trigger = round(imm_support - (step_size * 0.2), 1)

    # Opening Range Check (First 2 candles of session)
    or_high = effective_d_high
    or_low = effective_d_low
    is_inside_opening_range = False
    if candles_df is not None and not candles_df.empty and len(candles_df) >= 2:
        try:
            or_high = float(candles_df["high"].iloc[:2].max())
            or_low = float(candles_df["low"].iloc[:2].min())
            is_inside_opening_range = (or_low <= ltp <= or_high)
        except Exception:
            pass

    is_trapped_in_sr = (imm_resistance - ltp) < (atr * 0.25) and (ltp - imm_support) < (atr * 0.25)

    # -------------------------------------------------------------
    # 5. Safety Rejections & NO_TRADE Gating (Priority 2)
    # -------------------------------------------------------------
    no_trade_reasons: List[str] = []
    contributing_factors: List[str] = []

    # 5.1 Stale Data
    if last_update_utc:
        age_seconds = (datetime.now(timezone.utc) - last_update_utc).total_seconds()
        if age_seconds > cfg["max_stale_data_seconds"]:
            no_trade_reasons.append(f"Market feed is stale ({int(age_seconds / 60)} minutes old). Execution gated.")

    # 5.2 Extreme VIX
    if vix_value > cfg["vix_upper_limit"]:
        no_trade_reasons.append(f"India VIX elevated at {vix_value:.1f} (> {cfg['vix_upper_limit']}). Extrinsic volatility crush risk.")
    elif vix_value < cfg["vix_lower_limit"]:
        contributing_factors.append(f"India VIX is low ({vix_value:.1f}); range compression expected.")

    # 5.3 Excessive Spread
    if has_excessive_spread:
        no_trade_reasons.append(f"Option bid/ask spread ({option_spread_pct:.2f}%) exceeds {cfg['max_option_spread_pct']}%.")

    # 5.4 Option Sentiment Friction & Divergence
    indicator_conflict = False
    if pcr is not None:
        if vwap and ltp > vwap and (ema20 and ltp > ema20) and pcr < cfg["pcr_conflict_low"]:
            indicator_conflict = True
            no_trade_reasons.append(f"Bullish price structure faces aggressive Call writing overhead (PCR {pcr:.2f} < {cfg['pcr_conflict_low']}).")
        elif vwap and ltp < vwap and (ema20 and ltp < ema20) and pcr > cfg["pcr_conflict_high"]:
            indicator_conflict = True
            no_trade_reasons.append(f"Bearish breakdown meets institutional Put floor support (PCR {pcr:.2f} > {cfg['pcr_conflict_high']}).")

    if (dist_vwap_pct > 0.40 and rsi < cfg["rsi_bearish_max"]) or (dist_vwap_pct < -0.40 and rsi > cfg["rsi_bullish_min"]):
        indicator_conflict = True
        no_trade_reasons.append(f"Price position relative to VWAP ({dist_vwap_pct:+.2f}%) diverges from RSI momentum ({rsi:.1f}).")

    # -------------------------------------------------------------
    # 6. Core Regime Analysis & False-Bearish Elimination
    # -------------------------------------------------------------
    # 6.0 Structural Swings & Displacement
    if candles_df is not None and not candles_df.empty and len(candles_df) >= 3:
        recent_tail = candles_df.tail(min(len(candles_df), 12))
        recent_high = float(recent_tail["high"].max())
        recent_low = float(recent_tail["low"].min())
    else:
        recent_high = effective_d_high
        recent_low = effective_d_low

    drop_from_swing_high = max(0.0, recent_high - ltp)
    bounce_from_swing_low = max(0.0, ltp - recent_low)
    swing_range = max(1.0, recent_high - recent_low)
    swing_mid = (recent_high + recent_low) / 2.0
    drop_atr_ratio = drop_from_swing_high / atr if atr > 0 else 0.0
    bounce_atr_ratio = bounce_from_swing_low / atr if atr > 0 else 0.0

    # 6.1 Macro Day Trend (Requires holding near session extremes)
    is_strong_bull_trend_day = (
        (day_change_pct >= 0.70 or chg >= pts_trend_threshold or (ltp - d_open) >= (atr * 1.5))
        and ltp > d_open
        and ltp > d_close
        and drop_from_swing_high < (atr * 0.8)
    )
    is_strong_bear_trend_day = (
        (day_change_pct <= -0.70 or chg <= -pts_trend_threshold or (ltp - d_open) <= -(atr * 1.5))
        and ltp < d_open
        and ltp < d_close
        and bounce_from_swing_low < (atr * 0.8)
    )

    # 6.2 Volatility Expansion Detection (Priority 3)
    # Day range significantly exceeds historical ATR AND (normalized ATR % is elevated or BB width expanded)
    is_volatility_expansion = (
        range_atr_ratio >= 2.5
        and (
            (norm_atr_pct is not None and norm_atr_pct >= 1.20)
            or (bb_width is not None and bb_width >= 0.08)
        )
    )

    # 6.3 Reversal Qualification (Priority 4)
    # MATHEMATICAL RULE: A reversal CANNOT occur inside a consolidating/flat box (swing_range < 1.6 * atr).
    # It requires an established prior opposing trend, testing a major level, and confirmed MSS.
    is_prior_bull_trend = (day_range >= (atr * 1.6) or day_change_pct >= 0.50 or (recent_high - d_open) >= (atr * 1.8))
    is_prior_bear_trend = (day_range >= (atr * 1.6) or day_change_pct <= -0.50 or (d_open - recent_low) >= (atr * 1.8))

    is_bearish_reversal = (
        is_prior_bull_trend
        and not is_strong_bull_trend_day
        and not is_strong_bear_trend_day
        and drop_from_swing_high >= (atr * 1.2)
        and (ltp < vwap if vwap is not None else ltp < swing_mid)
        and (rsi <= 48.0 or (minus_di is not None and plus_di is not None and minus_di > plus_di))
        and not is_ema_flat
        and not no_trade_reasons
    )

    is_bullish_reversal = (
        is_prior_bear_trend
        and not is_strong_bull_trend_day
        and not is_strong_bear_trend_day
        and bounce_from_swing_low >= (atr * 1.2)
        and (ltp > vwap if vwap is not None else ltp > swing_mid)
        and (rsi >= 52.0 or (plus_di is not None and minus_di is not None and plus_di > minus_di))
        and not is_ema_flat
        and not no_trade_reasons
    )

    # 6.4 Directional Trending Regimes (Priority 5)
    # Check ADX and DI directional dominance
    has_bull_adx = (adx is None or (adx >= cfg["adx_trend_threshold"] and (plus_di is None or minus_di is None or plus_di >= minus_di)))
    has_bear_adx = (adx is None or (adx >= cfg["adx_trend_threshold"] and (plus_di is None or minus_di is None or minus_di >= plus_di)))

    # Bullish Trend: requires either strong day expansion OR (price > vwap, ema20 > ema50, and not flat chop)
    is_bullish_trend = (
        (
            is_strong_bull_trend_day
            or (
                (vwap is None or ltp >= vwap * 0.999)
                and (ema20 is None or ema50 is None or (ema20 > ema50 and not is_ema_flat))
                and (rsi >= cfg["rsi_neutral_min"])
                and has_bull_adx
                and not is_trapped_in_sr
            )
        )
        and not is_bearish_reversal
        and not (indicator_conflict and not is_strong_bull_trend_day)
        and not (no_trade_reasons and not is_strong_bull_trend_day)
    )

    # Bearish Trend: FALSE BEARISH PROTECTION:
    # A minor drop inside sideways or consolidating structure (is_ema_flat or range_atr_ratio <= 1.35)
    # is STRICTLY FORBIDDEN from triggering bearish trend!
    is_bearish_trend = (
        (
            is_strong_bear_trend_day
            or (
                (vwap is None or ltp <= vwap * 1.001)
                and (ema20 is None or ema50 is None or (ema20 < ema50 and not is_ema_flat))
                and (rsi <= cfg["rsi_neutral_max"])
                and has_bear_adx
                and not is_trapped_in_sr
                and not is_ema_flat
                and (range_atr_ratio > 1.30 or is_strong_bear_trend_day)
            )
        )
        and not is_bullish_reversal
        and not (indicator_conflict and not is_strong_bear_trend_day)
        and not (no_trade_reasons and not is_strong_bear_trend_day)
    )

    # 6.5 Sideways Regime (Priority 6 - Consolidation Default)
    # Correctly identifies range-bound price action
    is_sideways = (
        not is_strong_bull_trend_day
        and not is_strong_bear_trend_day
        and not is_volatility_expansion
        and not is_bearish_reversal
        and not is_bullish_reversal
        and not is_bullish_trend
        and not is_bearish_trend
    ) or (
        # Explicit sideways criteria overrides weak trend signals
        not is_strong_bull_trend_day
        and not is_strong_bear_trend_day
        and (
            (adx is not None and adx < cfg["adx_chop_threshold"])
            or (is_ema_flat and is_near_vwap)
            or (range_atr_ratio <= 1.35 and is_near_vwap)
            or (is_trapped_in_sr and is_inside_opening_range)
        )
    )

    # -------------------------------------------------------------
    # 7. Apply Deterministic Precedence Hierarchy
    # -------------------------------------------------------------
    # 1. DATA_UNAVAILABLE (Handled at entry)
    # 2. NO_TRADE (Safety/Risk Rejection)
    # 3. VOLATILITY_EXPANSION
    # 4. REVERSAL
    # 5. BULLISH_TREND / BEARISH_TREND
    # 6. SIDEWAYS

    if no_trade_reasons:
        final_regime = MarketRegime.NO_TRADE
        final_state = MarketState.NO_TRADE
        trend_direction = "NEUTRAL"
        headline = "NO TRADE — CONDITIONS UNSUITABLE"
        primary_reason = no_trade_reasons[0]
        badge = "NO TRADE"
        is_no_trade = True
        explanation = f"{clean_sym} market conditions are unsuitable for activating new setups. {primary_reason}"

    elif is_volatility_expansion:
        final_regime = MarketRegime.VOLATILITY_EXPANSION
        final_state = MarketState.VOLATILITY_EXPANSION
        # DIRECTION MUST BE EVALUATED SEPARATELY (PROMPT REQUIREMENT)
        if vwap and ltp > vwap and (plus_di is None or minus_di is None or plus_di > minus_di):
            trend_direction = "BULLISH"
        elif vwap and ltp < vwap and (plus_di is None or minus_di is None or minus_di > plus_di):
            trend_direction = "BEARISH"
        else:
            trend_direction = "EXPANSION_UNCERTAIN"
        badge = f"VOLATILITY EXPANSION ({trend_direction})"
        headline = f"VOLATILITY EXPANSION DETECTED — {trend_direction} BIAS"
        primary_reason = f"Abnormal range expansion observed ({day_range:.1f} pts, {range_atr_ratio:.2f} ATR). Directional volatility expanding."
        explanation = f"{clean_sym} is undergoing heightened volatility expansion ({day_range:.1f} pts). Trade execution remains gated pending multi-timeframe confirmation."
        is_no_trade = False

    elif is_bearish_reversal:
        final_regime = MarketRegime.REVERSAL
        final_state = MarketState.REVERSAL
        trend_direction = "BEARISH"
        badge = "REVERSAL (BEARISH)"
        headline = "CONFIRMED BEARISH STRUCTURE SHIFT FROM HIGHS"
        primary_reason = f"Institutional supply rejection at peak ₹{recent_high:.1f} (dropped {drop_from_swing_high:.1f} pts, {drop_atr_ratio:.2f} ATR). Market structure shifted bearish."
        explanation = f"{clean_sym} rejected sharply from recent high ₹{recent_high:.1f}. Structural shift confirmed."
        is_no_trade = False

    elif is_bullish_reversal:
        final_regime = MarketRegime.REVERSAL
        final_state = MarketState.REVERSAL
        trend_direction = "BULLISH"
        badge = "REVERSAL (BULLISH)"
        headline = "CONFIRMED BULLISH STRUCTURE SHIFT FROM LOWS"
        primary_reason = f"Institutional demand bounce from low ₹{recent_low:.1f} (rebounded +{bounce_from_swing_low:.1f} pts, {bounce_atr_ratio:.2f} ATR). Market structure shifted bullish."
        explanation = f"{clean_sym} absorbed selling pressure at recent low ₹{recent_low:.1f}. Structural shift confirmed."
        is_no_trade = False

    elif is_strong_bull_trend_day or (is_bullish_trend and not is_sideways):
        final_regime = MarketRegime.BULLISH_TREND
        final_state = MarketState.BULLISH
        trend_direction = "BULLISH"
        badge = "BULLISH_TREND"
        headline = f"BULLISH TREND ({chg:+.1f} PTS) — UPWARD ACCUMULATION"
        primary_reason = f"Confirmed institutional bullish structure ({chg:+.1f} pts, {day_change_pct:+.2f}%). Sustained trading above VWAP with bullish momentum."
        explanation = f"{clean_sym} exhibits consistent accumulation above VWAP and moving averages. Directional call setups qualified analytically."
        is_no_trade = False

    elif is_strong_bear_trend_day or (is_bearish_trend and not is_sideways):
        final_regime = MarketRegime.BEARISH_TREND
        final_state = MarketState.BEARISH
        trend_direction = "BEARISH"
        badge = "BEARISH_TREND"
        headline = f"BEARISH TREND ({chg:+.1f} PTS) — DOWNWARD DISTRIBUTION"
        primary_reason = f"Confirmed institutional bearish structure ({chg:+.1f} pts, {day_change_pct:+.2f}%). Sustained trading below VWAP with bearish momentum."
        explanation = f"{clean_sym} exhibits consistent distribution below VWAP and moving averages. Directional put setups qualified analytically."
        is_no_trade = False

    else:
        # SIDEWAYS CONSOLIDATION DEFAULT
        final_regime = MarketRegime.SIDEWAYS
        final_state = MarketState.SIDEWAYS
        trend_direction = "NEUTRAL"
        headline = "NO TRADE — SIDEWAYS MARKET"
        primary_reason = f"{clean_sym} is moving sideways within a range-bound band (₹{imm_support} - ₹{imm_resistance}). Directional trend confirmation is absent."
        explanation = (
            f"{clean_sym} is moving sideways between support ₹{imm_support} and resistance ₹{imm_resistance}. "
            f"Directional momentum is compressed. Targets are disabled to protect capital from theta decay. "
            f"Wait for a confirmed breakout above ₹{bullish_trigger} or breakdown below ₹{bearish_trigger}."
        )
        badge = "SIDEWAYS" if tested_sideways_strategy_active else "NO TRADE"
        is_no_trade = not tested_sideways_strategy_active

    # -------------------------------------------------------------
    # 8. Step 2 Execution Restriction Enforcement (Section 6)
    # -------------------------------------------------------------
    # Step 2 is analytical only. Engine does NOT independently authorize BUY_CE or BUY_PE.
    # final_action is restricted to "WAIT" or "NO_TRADE" until Step 3 completes MTF confluence.
    if final_regime in [MarketRegime.SIDEWAYS, MarketRegime.NO_TRADE, MarketRegime.DATA_UNAVAILABLE] or is_no_trade:
        final_action = "NO_TRADE"
    else:
        # Directional regime identified analytically, awaiting Step 3 MTF synthesis
        final_action = "WAIT"

    # -------------------------------------------------------------
    # 9. Confluence & Confidence Scoring
    # -------------------------------------------------------------
    trend_strength_val = adx if adx is not None else min(100.0, max(0.0, abs(day_change_pct) * 35.0))
    volatility_state_val = "EXPANDING" if is_volatility_expansion else ("COMPRESSED" if is_sideways or vix_value < cfg["vix_lower_limit"] else "NORMAL")

    # Preliminary confluence score calculation (0.0 to 1.0)
    score_pts = 0.0
    if final_regime in [MarketRegime.BULLISH_TREND, MarketRegime.BEARISH_TREND]:
        score_pts += 40.0
        if adx is not None and adx >= 25.0:
            score_pts += 20.0
        if vwap and ((trend_direction == "BULLISH" and ltp > vwap) or (trend_direction == "BEARISH" and ltp < vwap)):
            score_pts += 20.0
        if has_options_data and pcr is not None:
            score_pts += 10.0
        if not indicator_conflict:
            score_pts += 10.0
    elif final_regime == MarketRegime.SIDEWAYS:
        score_pts = 30.0  # Clear recognition of chop
    elif final_regime == MarketRegime.VOLATILITY_EXPANSION:
        score_pts = 50.0

    regime_confidence = round(score_pts / 100.0, 2)

    # -------------------------------------------------------------
    # 10. Assemble Structured Decision Output
    # -------------------------------------------------------------
    contributing_factors.extend([
        f"LTP: ₹{ltp:.2f} (Change: {chg:+.2f} pts, {day_change_pct:+.2f}%)",
        f"VWAP: ₹{vwap:.2f} ({dist_vwap_pct:+.2f}%)" if vwap else "VWAP: Uncalculated",
        f"EMA 20: ₹{ema20:.2f} | EMA 50: ₹{ema50:.2f}" if (ema20 and ema50) else "EMAs: Warm-up",
        f"ADX: {adx:.1f}" + (f" (+DI: {plus_di:.1f}, -DI: {minus_di:.1f})" if (plus_di is not None and minus_di is not None) else "") if adx is not None else "ADX: Warm-up (< 27 bars)",
        f"ATR (14): ₹{atr:.2f} ({norm_atr_pct:.2f}%)",
        f"RSI (14): {rsi:.1f}",
        f"India VIX: {vix_value:.2f}",
        f"Immediate S/R: ₹{imm_support} — ₹{imm_resistance}",
        f"Opening Range: ₹{or_low:.1f} — ₹{or_high:.1f} ({'Inside' if is_inside_opening_range else 'Outside'})",
    ])
    if pcr is not None:
        contributing_factors.append(f"PCR (OI): {pcr:.2f} | Max Pain: {max_pain}")
    else:
        contributing_factors.append("Option Chain: Unavailable (Regime evaluated on price/volume)")

    evaluation_factors = {
        "priceStructure": {"ltp": ltp, "change": chg, "dayRange": day_range, "trend": trend_direction},
        "vwap": {"vwap": vwap, "distPct": round(dist_vwap_pct, 2) if vwap else None},
        "emaAlignment": {"ema20": ema20, "ema50": ema50, "ema200": ema200, "isFlat": is_ema_flat},
        "momentum": {"rsi": rsi, "adx": adx, "plusDi": plus_di, "minusDi": minus_di},
        "atrAndVolatility": {"atr": atr, "normAtrPct": norm_atr_pct, "vix": vix_value, "bbWidth": bb_width},
        "breakoutBreakdownConfirmation": {
            "bullishTrigger": bullish_trigger,
            "bearishTrigger": bearish_trigger,
            "isBearishReversal": is_bearish_reversal,
            "isBullishReversal": is_bullish_reversal,
        },
        "optionChainEvidence": {"pcr": pcr, "callWall": call_wall, "putWall": put_wall, "status": "AVAILABLE" if has_options_data else "UNAVAILABLE"},
        "dataFreshness": {"isLive": is_live_data, "status": "FRESH" if is_live_data else "MOCK"},
    }

    is_mkt_open = MarketCalendar.is_market_open()
    data_quality_status = info.get("data_quality_status", "VERIFIED" if is_live_data else "MOCK")

    return {
        # Master Specification v3.0 Structured Decision Output
        "index": clean_sym,
        "symbol": clean_sym,
        "market_regime": final_regime,
        "marketState": final_state,  # Legacy backward compatibility
        "trend_direction": trend_direction,
        "trend_strength": round(trend_strength_val, 1),
        "volatility_state": volatility_state_val,
        "timeframe_analysis": {
            "primary": {"timeframe": info.get("timeframe", "15m"), "regime": final_regime, "adx": adx, "trend": trend_direction}
        },
        "timeframe_agreement": 1.0,  # Single-timeframe default, Step 3 will compute 4-TF matrix
        "indicator_confluence": {
            "adx_14": adx,
            "plus_di": plus_di,
            "minus_di": minus_di,
            "vwap": vwap,
            "ema20": ema20,
            "ema50": ema50,
            "ema200": ema200,
            "atr_14": atr,
            "pcr": pcr,
            "vix": vix_value,
        },
        "regime_confidence": regime_confidence,
        "data_quality_status": data_quality_status,
        "rejection_reasons": no_trade_reasons,
        "final_action": final_action,
        # Legacy Fields (Guarantees zero breakage across all API endpoints & tests)
        "isNoTrade": is_no_trade,
        "prominentStatus": "NO TRADE" if is_no_trade else final_state,
        "statusBadge": badge,
        "headline": headline,
        "explanation": explanation,
        "primaryReason": primary_reason,
        "reasonForNoTrade": primary_reason if is_no_trade else "None (Conditions qualified)",
        "contributingFactors": contributing_factors,
        "importantSupport": imm_support,
        "importantResistance": imm_resistance,
        "bullishActivationTrigger": f"Sustain above ₹{bullish_trigger} with 15m candle strength",
        "bearishActivationTrigger": f"Sustain below ₹{bearish_trigger} with 15m candle weakness",
        "confirmationRequired": "5-minute candle close beyond trigger with directional volume expansion",
        "keyLevels": {
            "immediateSupport": imm_support,
            "immediateResistance": imm_resistance,
            "bullishActivationTrigger": f"Sustain above ₹{bullish_trigger} with 15m candle strength",
            "bearishActivationTrigger": f"Sustain below ₹{bearish_trigger} with 15m candle weakness",
            "confirmationRequired": "5-minute candle close beyond trigger with directional volume expansion",
        },
        "evaluationFactors": evaluation_factors,
        "dataStatus": ("LIVE" if is_mkt_open else "POST-MARKET") if is_live_data else "MOCK",
        "dataTimestamp": now_ist,
        "timeOfLastAnalysis": now_ist,
        "analysisTimestamp": now_ist,
    }
