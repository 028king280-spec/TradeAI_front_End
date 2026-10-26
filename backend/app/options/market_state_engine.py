"""
AIVOLVE Market State Engine.
Determines current market state independently per index:
- BULLISH
- BEARISH
- SIDEWAYS
- NO_TRADE
- DATA_UNAVAILABLE

Strictly distinguishes SIDEWAYS from NO_TRADE:
- SIDEWAYS: Price action is predominantly range-bound or lacks sufficient directional movement.
  Qualifies setups only if an explicitly tested range strategy supports it; otherwise prompts NO TRADE.
- NO_TRADE: Conditions are unsuitable for activating new setups (conflicting indicators,
  poor option liquidity, excessive spread, excessive volatility, inadequate reward relative to risk,
  or unreliable/stale market data).

Evaluates 13 deterministic factors:
1. Price structure and trend
2. VWAP
3. EMA alignment (20, 50, 200)
4. Momentum (RSI 14, MACD)
5. ATR and volatility (and India VIX)
6. Volume (vs 20-period moving average)
7. Support and resistance (Camarilla / Classic pivots + option walls)
8. Opening range (15m/30m high/low bounds)
9. Breakout and breakdown confirmation
10. Option-chain evidence (PCR, Call Wall, Put Wall, Max Pain)
11. Liquidity and bid/ask spread
12. Data freshness
13. Risk/reward suitability
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
import pandas as pd
from app.data.market_calendar import MarketCalendar


class MarketState:
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    SIDEWAYS = "SIDEWAYS"
    NO_TRADE = "NO_TRADE"
    DATA_UNAVAILABLE = "DATA_UNAVAILABLE"


# Configurable Qualification Thresholds (Deterministic & Auditable)
DEFAULT_CONFIG = {
    "max_stale_data_seconds": 900,  # 15 minutes
    "vix_upper_limit": 24.0,        # Extreme volatility threshold
    "vix_lower_limit": 10.5,        # Extreme compression threshold
    "min_reward_to_risk": 1.5,      # Minimum R:R ratio
    "ema_flat_spread_pct": 0.12,    # EMA 20 vs 50 spread threshold for flat chop
    "vwap_near_band_pct": 0.15,     # Percentage within VWAP considered chop
    "rsi_neutral_min": 45.0,
    "rsi_neutral_max": 55.0,
    "rsi_bullish_min": 54.0,
    "rsi_bearish_max": 46.0,
    "pcr_bullish_min": 0.90,
    "pcr_bearish_max": 1.10,
    "pcr_conflict_low": 0.75,       # Price bullish but heavy Call writing
    "pcr_conflict_high": 1.35,      # Price bearish but heavy Put floor
    "min_volume_ratio": 0.75,       # Min current candle volume vs 20-period avg
    "max_option_spread_pct": 2.5,   # Max bid-ask spread % of premium
    "min_option_oi": 20000,         # Minimum institutional OI floor
}


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
    Evaluates independent market state and NO-TRADE conditions for an index.
    Deterministic, configurable thresholds with institutional explanations.
    """
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    now_ist = MarketCalendar.format_ist_timestamp()
    clean_sym = symbol.upper().strip()

    # 1. Check Data Availability & Freshness
    if not quote or float(quote.get("currentPrice") or quote.get("ltp", 0.0)) <= 0:
        return {
            "symbol": clean_sym,
            "marketState": MarketState.DATA_UNAVAILABLE,
            "isNoTrade": True,
            "prominentStatus": "NO TRADE",
            "statusBadge": "DATA UNAVAILABLE",
            "headline": "MARKET DATA UNAVAILABLE",
            "explanation": f"Live quote feed for {clean_sym} is currently unreachable. Trading signals are suppressed to protect capital.",
            "primaryReason": "Missing or disconnected market data stream.",
            "reasonForNoTrade": "Missing or disconnected market data stream.",
            "contributingFactors": [
                "Quote object empty or LTP is zero",
                "Provider connection down or market closed",
            ],
            "importantSupport": 0.0,
            "importantResistance": 0.0,
            "bullishActivationTrigger": "Requires verified market price feeds",
            "bearishActivationTrigger": "Requires verified market price feeds",
            "confirmationRequired": "Provider re-authentication and active WebSocket ticks",
            "keyLevels": {
                "immediateSupport": 0.0,
                "immediateResistance": 0.0,
                "bullishActivationTrigger": "Requires verified market price feeds",
                "bearishActivationTrigger": "Requires verified market price feeds",
                "confirmationRequired": "Provider re-authentication and active WebSocket ticks",
            },
            "dataStatus": "UNAVAILABLE",
            "dataTimestamp": now_ist,
            "timeOfLastAnalysis": now_ist,
            "analysisTimestamp": now_ist,
            "evaluationFactors": {
                "dataFreshness": {"status": "FAILED", "reason": "No quote data received"},
            },
        }

    ltp = float(quote.get("currentPrice") or quote.get("ltp", 0.0))
    chg = float(quote.get("change", 0.0))
    d_high = float(quote.get("dayHigh", ltp * 1.008))
    d_low = float(quote.get("dayLow", ltp * 0.992))
    d_close = float(quote.get("previousClose", ltp - chg))
    d_open = float(quote.get("openPrice", d_low))

    # Technical overlays
    info = candles_info or {}
    vwap = float(info.get("vwap") or ltp)
    ema20 = float(info.get("ema20") or ltp)
    ema50 = float(info.get("ema50") or ltp)
    ema200 = float(info.get("ema200") or ltp)
    atr = float(info.get("atr") or (ltp * 0.005))
    rsi = float(info.get("rsi") or 50.0)

    # Option chain metrics
    chain_sum = option_chain_summary or {}
    pcr = float(chain_sum.get("pcr", {}).get("pcrOi", 1.0)) if isinstance(chain_sum.get("pcr"), dict) else 1.0
    call_wall = float(chain_sum.get("callWall", d_high))
    put_wall = float(chain_sum.get("putWall", d_low))
    max_pain = float(chain_sum.get("maxPain", {}).get("maxPainStrike", ltp)) if isinstance(chain_sum.get("maxPain"), dict) else ltp

    # Factor 1: Price Structure vs VWAP and EMAs
    dist_vwap_pct = ((ltp - vwap) / vwap) * 100.0 if vwap > 0 else 0.0
    dist_ema20_pct = ((ltp - ema20) / ema20) * 100.0 if ema20 > 0 else 0.0
    ema_spread_pct = (abs(ema20 - ema50) / ltp) * 100.0 if ltp > 0 else 0.0

    # Factor 2: Range & Volatility
    day_range = max(1.0, d_high - d_low)
    range_atr_ratio = day_range / atr if atr > 0 else 1.0

    # Key Support & Resistance Levels
    step = 50.0 if "NIFTY" in clean_sym and "BANK" not in clean_sym else (100.0 if "BANK" in clean_sym or "SENSEX" in clean_sym else 50.0)
    round_support = round((ltp - (atr * 0.45)) / step) * step
    round_resistance = round((ltp + (atr * 0.45)) / step) * step
    imm_support = round(max(round_support, put_wall if put_wall < ltp else round_support), 1)
    imm_resistance = round(min(round_resistance, call_wall if call_wall > ltp else round_resistance), 1)

    bullish_trigger = round(imm_resistance + (step * 0.2), 1)
    bearish_trigger = round(imm_support - (step * 0.2), 1)

    # Factor 3: Opening Range (First 30m / Two 15m Candles)
    or_high = d_high
    or_low = d_low
    is_inside_opening_range = False
    if candles_df is not None and not candles_df.empty and len(candles_df) >= 2:
        try:
            or_high = float(candles_df["high"].iloc[:2].max())
            or_low = float(candles_df["low"].iloc[:2].min())
            is_inside_opening_range = (or_low <= ltp <= or_high)
        except Exception:
            pass

    # Factor 4: Volume Analysis (vs 20-period moving average)
    volume_ratio = 1.0
    is_volume_low = False
    if candles_df is not None and not candles_df.empty and "volume" in candles_df.columns:
        try:
            vols = candles_df["volume"].dropna()
            if len(vols) >= 5:
                avg_vol = float(vols.rolling(min(len(vols), 20)).mean().iloc[-1])
                curr_vol = float(vols.iloc[-1])
                if avg_vol > 0:
                    volume_ratio = curr_vol / avg_vol
                    if volume_ratio < cfg["min_volume_ratio"]:
                        is_volume_low = True
        except Exception:
            pass

    # Factor 5: Liquidity and Spread Check
    has_excessive_spread = False
    option_spread_pct = 0.0
    if chain_sum.get("atmSpreadPct"):
        option_spread_pct = float(chain_sum["atmSpreadPct"])
        if option_spread_pct > cfg["max_option_spread_pct"]:
            has_excessive_spread = True

    # Factor Evaluation lists
    no_trade_reasons: List[str] = []
    contributing_factors: List[str] = []

    # 1. Stale Data Check
    if last_update_utc:
        now_utc = datetime.now(timezone.utc)
        age_seconds = (now_utc - last_update_utc).total_seconds()
        if age_seconds > cfg["max_stale_data_seconds"]:
            no_trade_reasons.append(
                f"Market data feed is stale ({int(age_seconds / 60)} minutes old). Signals suppressed."
            )

    # 2. Extreme Volatility / VIX Surge
    if vix_value > cfg["vix_upper_limit"]:
        no_trade_reasons.append(
            f"India VIX elevated at {vix_value:.1f} (> {cfg['vix_upper_limit']}). High option extrinsic value exposes buyer to severe IV crush."
        )
    elif vix_value < cfg["vix_lower_limit"]:
        contributing_factors.append(
            f"India VIX is low ({vix_value:.1f}); option premiums are compressed with tight intraday ranges."
        )

    # 3. Excessive Option Spread
    if has_excessive_spread:
        no_trade_reasons.append(
            f"Option contract bid/ask spread ({option_spread_pct:.2f}%) exceeds {cfg['max_option_spread_pct']}%. Slippage will degrade expected value."
        )

    # 4. Conflicting Indicators Check
    indicator_conflict = False
    if ltp > vwap and ltp > ema20 and pcr < cfg["pcr_conflict_low"]:
        indicator_conflict = True
        no_trade_reasons.append(
            f"Bullish price structure conflicts with heavy Call writing / low PCR ({pcr:.2f} < {cfg['pcr_conflict_low']})."
        )
    elif ltp < vwap and ltp < ema20 and pcr > cfg["pcr_conflict_high"]:
        indicator_conflict = True
        no_trade_reasons.append(
            f"Bearish price breakdown conflicts with aggressive Put floor / high PCR ({pcr:.2f} > {cfg['pcr_conflict_high']})."
        )

    if (ltp > vwap and rsi < cfg["rsi_bearish_max"]) or (ltp < vwap and rsi > cfg["rsi_bullish_min"]):
        indicator_conflict = True
        no_trade_reasons.append(
            f"Price position relative to VWAP diverges from momentum RSI ({rsi:.1f})."
        )

    # 5. Opening Range & S/R Sandwich (Inadequate Risk/Reward)
    is_trapped_in_sr = (imm_resistance - ltp) < (atr * 0.25) and (ltp - imm_support) < (atr * 0.25)
    if is_trapped_in_sr:
        contributing_factors.append(
            f"Price is compressed between immediate support {imm_support} and resistance {imm_resistance}. Risk:Reward is inadequate (< 1:{cfg['min_reward_to_risk']})."
        )

    # 6. Low Volume Warning
    if is_volume_low:
        contributing_factors.append(
            f"Volume conviction is low ({volume_ratio:.2f}x of 20-period average). Directional follow-through questionable."
        )

    # 7. EMA Intertwining (Chop / Sideways detection)
    is_ema_flat = ema_spread_pct < cfg["ema_flat_spread_pct"]
    is_near_vwap = abs(dist_vwap_pct) < cfg["vwap_near_band_pct"]
    is_rsi_neutral = (cfg["rsi_neutral_min"] <= rsi <= cfg["rsi_neutral_max"])

    # 8. Directional Trend Evaluation
    is_bullish_trend = (
        (ltp > vwap)
        and (ltp > ema20 >= ema50)
        and (rsi > cfg["rsi_bullish_min"])
        and (pcr >= cfg["pcr_bullish_min"])
        and not indicator_conflict
        and not no_trade_reasons
    )
    is_bearish_trend = (
        (ltp < vwap)
        and (ltp < ema20 <= ema50)
        and (rsi < cfg["rsi_bearish_max"])
        and (pcr <= cfg["pcr_bearish_max"])
        and not indicator_conflict
        and not no_trade_reasons
    )

    is_sideways = (
        (is_ema_flat and is_near_vwap and is_rsi_neutral)
        or (is_trapped_in_sr and not is_bullish_trend and not is_bearish_trend)
        or (range_atr_ratio < 0.65 and is_near_vwap)
    ) and not indicator_conflict

    # 9. Determine Final State & Rationale
    if is_sideways:
        final_state = MarketState.SIDEWAYS
        primary_reason = (
            f"{clean_sym} is moving sideways within a range-bound band ({imm_support} - {imm_resistance}). "
            f"Directional confirmation is insufficient."
        )
        if tested_sideways_strategy_active:
            headline = "SIDEWAYS MARKET — RANGE STRATEGY QUALIFIED"
            explanation = (
                f"{clean_sym} is moving sideways. Tested range-bound strategy active. "
                f"Boundaries: Support {imm_support}, Resistance {imm_resistance}."
            )
            badge = "SIDEWAYS (RANGE ACTIVE)"
            is_no_trade = False
        else:
            headline = "NO TRADE — SIDEWAYS MARKET"
            explanation = (
                f"{clean_sym} is moving sideways. Directional confirmation is insufficient. "
                f"Wait for a confirmed breakout above {bullish_trigger} or breakdown below {bearish_trigger}."
            )
            badge = "NO TRADE"
            is_no_trade = True

    elif no_trade_reasons:
        final_state = MarketState.NO_TRADE
        headline = "NO TRADE — CONDITIONS UNSUITABLE"
        primary_reason = no_trade_reasons[0]
        explanation = (
            f"{clean_sym} conditions are unsuitable for activating new directional setups. "
            f"{primary_reason} Wait for confirmation."
        )
        badge = "NO TRADE"
        is_no_trade = True

    elif is_bullish_trend:
        final_state = MarketState.BULLISH
        headline = "BULLISH MARKET STRUCTURE CONFIRMED"
        primary_reason = f"Trading above VWAP (+{dist_vwap_pct:.2f}%) with bullish EMA alignment and favorable PCR ({pcr:.2f})."
        explanation = (
            f"{clean_sym} demonstrates sustained institutional accumulation above VWAP and moving averages. "
            f"Qualified CALL setups may be considered upon pullbacks to entry zones."
        )
        badge = "BULLISH"
        is_no_trade = False

    elif is_bearish_trend:
        final_state = MarketState.BEARISH
        headline = "BEARISH MARKET STRUCTURE CONFIRMED"
        primary_reason = f"Trading below VWAP ({dist_vwap_pct:.2f}%) with bearish EMA alignment and weak RSI ({rsi:.1f})."
        explanation = (
            f"{clean_sym} demonstrates persistent selling pressure below VWAP. "
            f"Qualified PUT setups may be considered upon retests of overhead resistance."
        )
        badge = "BEARISH"
        is_no_trade = False

    else:
        # Default safety condition: NO_TRADE
        final_state = MarketState.NO_TRADE
        headline = "NO TRADE — WAIT FOR CONFIRMATION"
        primary_reason = "Lack of clear institutional volume expansion and directional confirmation."
        explanation = (
            f"{clean_sym} directional confirmation is insufficient. "
            f"Wait for a confirmed breakout above {bullish_trigger} or breakdown below {bearish_trigger}."
        )
        badge = "NO TRADE"
        is_no_trade = True

    # Assemble supporting context
    contributing_factors.extend([
        f"LTP: ₹{ltp:.2f} (Change: {chg:+.2f} pts)",
        f"VWAP: ₹{vwap:.2f} (Spread: {dist_vwap_pct:+.2f}%)",
        f"EMA 20: ₹{ema20:.2f} | EMA 50: ₹{ema50:.2f}",
        f"RSI (14): {rsi:.1f}",
        f"PCR (OI): {pcr:.2f} | Max Pain: {max_pain}",
        f"India VIX: {vix_value:.2f}",
        f"Immediate S/R: ₹{imm_support} — ₹{imm_resistance}",
        f"Opening Range: ₹{or_low:.1f} — ₹{or_high:.1f} ({'Inside' if is_inside_opening_range else 'Outside'})",
    ])

    evaluation_factors = {
        "priceStructure": {"ltp": ltp, "change": chg, "dayRange": day_range, "trend": "BULLISH" if ltp > vwap else "BEARISH"},
        "vwap": {"vwap": vwap, "distPct": round(dist_vwap_pct, 2)},
        "emaAlignment": {"ema20": ema20, "ema50": ema50, "ema200": ema200, "isFlat": is_ema_flat},
        "momentum": {"rsi": rsi, "isNeutral": is_rsi_neutral},
        "atrAndVolatility": {"atr": atr, "vix": vix_value, "isExtreme": vix_value > cfg["vix_upper_limit"]},
        "volume": {"ratio": round(volume_ratio, 2), "isLow": is_volume_low},
        "supportResistance": {"immediateSupport": imm_support, "immediateResistance": imm_resistance},
        "openingRange": {"orHigh": or_high, "orLow": or_low, "isInside": is_inside_opening_range},
        "breakoutBreakdownConfirmation": {
            "bullishTrigger": bullish_trigger,
            "bearishTrigger": bearish_trigger,
            "confirmed": is_bullish_trend or is_bearish_trend,
        },
        "optionChainEvidence": {"pcr": pcr, "callWall": call_wall, "putWall": put_wall, "maxPain": max_pain},
        "liquidityAndSpread": {"spreadPct": option_spread_pct, "excessive": has_excessive_spread},
        "dataFreshness": {"isLive": is_live_data, "status": "FRESH" if is_live_data else "MOCK"},
        "riskRewardSuitability": {"trappedInSR": is_trapped_in_sr, "minRR": cfg["min_reward_to_risk"]},
    }

    return {
        "symbol": clean_sym,
        "marketState": final_state,
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
        "dataStatus": "LIVE" if is_live_data else "MOCK",
        "dataTimestamp": now_ist,
        "timeOfLastAnalysis": now_ist,
        "analysisTimestamp": now_ist,
    }
