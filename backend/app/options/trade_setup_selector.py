"""
AIVOLVE Institutional Quantitative Trading Intelligence v3.0
Phase 2 Step 3: Trade Setup Selector & Dynamic Risk Engineering

Synthesizes Multi-Timeframe Confluence with Core Market Regime to qualify:
- BUY_CE: High-conviction Call option paper buying setup.
- BUY_PE: High-conviction Put option paper buying setup.
- WAIT: Setup developing or awaiting micro trigger / confirmation.
- NO_TRADE: Sideways consolidation, conflicting timeframes, degraded data, or invalid risk.

Strict Paper-Trading-Only Execution Gate:
- Requires HTF + ITF directional agreement.
- Requires confirmed LTF execution trigger.
- Enforces strict dynamic stop-loss & multi-target geometric validity.
- Preserves Phase 1 data-quality gates and independent index states.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

from app.options.market_state_engine import MarketRegime, MarketState
from app.options.multi_timeframe_engine import evaluate_multi_timeframe_confluence
from app.data.market_calendar import MarketCalendar


# ---------------------------------------------------------------------------
# Dynamic Index Risk Bounds
# ---------------------------------------------------------------------------
INDEX_RISK_CONSTRAINTS: Dict[str, Dict[str, float]] = {
    "NIFTY 50": {"min_sl_pts": 15.0, "max_sl_pts": 65.0, "default_atr": 35.0},
    "NIFTY": {"min_sl_pts": 15.0, "max_sl_pts": 65.0, "default_atr": 35.0},
    "BANK NIFTY": {"min_sl_pts": 40.0, "max_sl_pts": 180.0, "default_atr": 90.0},
    "BANKNIFTY": {"min_sl_pts": 40.0, "max_sl_pts": 180.0, "default_atr": 90.0},
    "FINNIFTY": {"min_sl_pts": 15.0, "max_sl_pts": 60.0, "default_atr": 35.0},
    "SENSEX": {"min_sl_pts": 50.0, "max_sl_pts": 220.0, "default_atr": 110.0},
}

DEFAULT_SETUP_CONFIG: Dict[str, Any] = {
    "min_confluence_score": 70.0,
    "min_wait_score": 50.0,
    "min_reward_to_risk": 1.5,
    "target_1_rr": 1.5,
    "target_2_rr": 2.5,
    "target_3_rr": 3.5,
    "atr_sl_mult": 1.25,
}


def _get_index_risk_limits(symbol: str) -> Dict[str, float]:
    """Retrieves index-specific stop-loss bounds."""
    clean = symbol.upper().strip()
    if clean in INDEX_RISK_CONSTRAINTS:
        return INDEX_RISK_CONSTRAINTS[clean]
    for key in sorted(INDEX_RISK_CONSTRAINTS.keys(), key=len, reverse=True):
        if key in clean:
            return INDEX_RISK_CONSTRAINTS[key]
    return {"min_sl_pts": 20.0, "max_sl_pts": 100.0, "default_atr": 40.0}


# ---------------------------------------------------------------------------
# Dynamic Stop-Loss and Multi-Target Calculator
# -------------------------------------------------------------
def calculate_dynamic_risk_levels(
    symbol: str,
    direction: str,
    entry_price: float,
    invalidation_level: float,
    atr_5m: float,
    config: Optional[Dict[str, Any]] = None,
    rejection_reasons: Optional[List[str]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Computes institutional risk levels:
    - Stop-loss derived from structural swing invalidation + ATR volatility padding.
    - Strict boundary enforcement:
      * If raw structural distance > max_sl_pts: setup rejected with "Structural invalidation distance exceeds risk tolerance".
      * Never truncates SL inside the structural invalidation level merely to satisfy max_sl_pts.
      * Minimum SL padding applied only when resulting SL remains structurally valid.
    - Multi-targets derived from structural reward-to-risk (T1: 1.5R, T2: 2.5R, T3: 3.5R).
    - Returns None if risk parameters are mathematically invalid.
    """
    cfg = config or DEFAULT_SETUP_CONFIG
    limits = _get_index_risk_limits(symbol)
    min_sl = limits["min_sl_pts"]
    max_sl = limits["max_sl_pts"]

    # Reject invalid, missing or non-positive entry, ATR and structural inputs
    if entry_price <= 0 or not isinstance(entry_price, (int, float)):
        msg = "Invalid non-positive entry price"
        calculate_dynamic_risk_levels.last_rejection_reason = msg
        if rejection_reasons is not None:
            rejection_reasons.append(msg)
        return None

    if atr_5m <= 0 or not isinstance(atr_5m, (int, float)):
        msg = "Invalid non-positive ATR value"
        calculate_dynamic_risk_levels.last_rejection_reason = msg
        if rejection_reasons is not None:
            rejection_reasons.append(msg)
        return None

    if direction == "BULLISH":
        # 1. Calculate raw structural SL distance first
        if invalidation_level > 0 and invalidation_level < entry_price:
            raw_sl = invalidation_level
            raw_distance = entry_price - raw_sl
        else:
            raw_sl = entry_price - (atr_5m * cfg["atr_sl_mult"])
            raw_distance = atr_5m * cfg["atr_sl_mult"]

        # 2 & 3. Compare raw distance with index-specific maximum; reject if exceeded
        if raw_distance > max_sl:
            msg = "Structural invalidation distance exceeds risk tolerance"
            calculate_dynamic_risk_levels.last_rejection_reason = msg
            if rejection_reasons is not None:
                rejection_reasons.append(msg)
            return None

        # 5 & 6. Minimum SL padding (extends further below invalidation, preserving structural safety)
        sl_distance = max(min_sl, raw_distance)
        sl_price = round(entry_price - sl_distance, 1)
        risk_per_unit = round(entry_price - sl_price, 1)

        if sl_price >= entry_price or risk_per_unit <= 0:
            msg = "Calculated stop-loss is above or equal to entry price"
            calculate_dynamic_risk_levels.last_rejection_reason = msg
            if rejection_reasons is not None:
                rejection_reasons.append(msg)
            return None

        target_1 = round(entry_price + (risk_per_unit * cfg["target_1_rr"]), 1)
        target_2 = round(entry_price + (risk_per_unit * cfg["target_2_rr"]), 1)
        target_3 = round(entry_price + (risk_per_unit * cfg["target_3_rr"]), 1)

        # Geometric Validation: SL < Entry < T1 < T2 < T3
        if not (sl_price < entry_price < target_1 < target_2 < target_3):
            msg = "Invalid stop-loss or target geometry for BUY_CE"
            calculate_dynamic_risk_levels.last_rejection_reason = msg
            if rejection_reasons is not None:
                rejection_reasons.append(msg)
            return None

        rr_ratio = round((target_1 - entry_price) / risk_per_unit, 2)
        inval_desc = f"5M candle close below swing invalidation ₹{sl_price:.1f} (Structure Shift)"

        return {
            "type": "CALL_OPTION_BUY",
            "entry_price": entry_price,
            "stop_loss": sl_price,
            "target_1": target_1,
            "target_2": target_2,
            "target_3": target_3,
            "risk_per_unit": risk_per_unit,
            "reward_risk_ratio": rr_ratio,
            "invalidation_condition": inval_desc,
        }

    elif direction == "BEARISH":
        # 1. Calculate raw structural SL distance first
        if invalidation_level > 0 and invalidation_level > entry_price:
            raw_sl = invalidation_level
            raw_distance = raw_sl - entry_price
        else:
            raw_sl = entry_price + (atr_5m * cfg["atr_sl_mult"])
            raw_distance = atr_5m * cfg["atr_sl_mult"]

        # 2 & 3. Compare raw distance with index-specific maximum; reject if exceeded
        if raw_distance > max_sl:
            msg = "Structural invalidation distance exceeds risk tolerance"
            calculate_dynamic_risk_levels.last_rejection_reason = msg
            if rejection_reasons is not None:
                rejection_reasons.append(msg)
            return None

        # 5 & 6. Minimum SL padding (extends further above invalidation, preserving structural safety)
        sl_distance = max(min_sl, raw_distance)
        sl_price = round(entry_price + sl_distance, 1)
        risk_per_unit = round(sl_price - entry_price, 1)

        if sl_price <= entry_price or risk_per_unit <= 0:
            msg = "Calculated stop-loss is below or equal to entry price"
            calculate_dynamic_risk_levels.last_rejection_reason = msg
            if rejection_reasons is not None:
                rejection_reasons.append(msg)
            return None

        target_1 = round(entry_price - (risk_per_unit * cfg["target_1_rr"]), 1)
        target_2 = round(entry_price - (risk_per_unit * cfg["target_2_rr"]), 1)
        target_3 = round(entry_price - (risk_per_unit * cfg["target_3_rr"]), 1)

        # Geometric Validation: SL > Entry > T1 > T2 > T3
        if not (sl_price > entry_price > target_1 > target_2 > target_3):
            msg = "Invalid stop-loss or target geometry for BUY_PE"
            calculate_dynamic_risk_levels.last_rejection_reason = msg
            if rejection_reasons is not None:
                rejection_reasons.append(msg)
            return None

        rr_ratio = round((entry_price - target_1) / risk_per_unit, 2)
        inval_desc = f"5M candle close above swing invalidation ₹{sl_price:.1f} (Structure Shift)"

        return {
            "type": "PUT_OPTION_BUY",
            "entry_price": entry_price,
            "stop_loss": sl_price,
            "target_1": target_1,
            "target_2": target_2,
            "target_3": target_3,
            "risk_per_unit": risk_per_unit,
            "reward_risk_ratio": rr_ratio,
            "invalidation_condition": inval_desc,
        }

    return None


# ---------------------------------------------------------------------------
# Master Trade Setup Selector
# ---------------------------------------------------------------------------
def select_trade_setup(
    symbol: str,
    quote: Dict[str, Any],
    mtf_confluence: Dict[str, Any],
    market_regime_state: Optional[Dict[str, Any]] = None,
    option_chain_summary: Optional[Dict[str, Any]] = None,
    vix_value: float = 13.5,
    is_live_data: bool = True,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Evaluates multi-timeframe inputs and selects actionable paper trading setups.
    Enforces deterministic qualification for BUY_CE, BUY_PE, WAIT, and NO_TRADE.
    """
    cfg = config or DEFAULT_SETUP_CONFIG
    clean_sym = symbol.upper().strip()
    ltp = float(quote.get("currentPrice") or quote.get("ltp", 0.0))

    rejection_reasons: List[str] = list(mtf_confluence.get("rejection_reasons", []))
    contributing_factors: List[str] = []

    confluence_score = float(mtf_confluence.get("confluence_score", 0.0))
    directional_bias = mtf_confluence.get("directional_bias", "NEUTRAL")
    can_activate = bool(mtf_confluence.get("can_activate_directional", True))
    timeframe_conflicts = mtf_confluence.get("timeframe_conflicts", [])
    missing_tfs = mtf_confluence.get("missing_timeframes", [])
    ltf_trigger = mtf_confluence.get("ltf_trigger", {})
    itf_struct = mtf_confluence.get("itf_structure", {})
    atr_5m = float(itf_struct.get("atr_5m", _get_index_risk_limits(clean_sym)["default_atr"]))

    # Step 2 Market Regime Integration
    regime = None
    if market_regime_state:
        regime = market_regime_state.get("market_regime")

    contributing_factors.append(f"MTF Confluence Score: {confluence_score:.1f}/100.0 (Directional Bias: {directional_bias})")
    if regime:
        contributing_factors.append(f"Market Regime: {regime} (Step 2 Engine)")

    # -------------------------------------------------------------
    # 1. Gate 1: Safety & Rejection Checks
    # -------------------------------------------------------------
    if not is_live_data and not mtf_confluence.get("is_replay"):
        rejection_reasons.append("Non-live unverified data stream rejected by Phase 1 safety gates.")

    if regime is not None and regime in [MarketRegime.SIDEWAYS, MarketRegime.NO_TRADE, MarketRegime.DATA_UNAVAILABLE]:
        rejection_reasons.append(f"Market regime '{regime}' is unsuitable for directional options buying.")

    if timeframe_conflicts:
        rejection_reasons.extend(timeframe_conflicts)

    if not can_activate:
        rejection_reasons.append("Multi-timeframe activation lockout in effect (15M or 5M unavailable).")

    # -------------------------------------------------------------
    # 2. Gate 2: Directional Qualification Logic
    # -------------------------------------------------------------
    trade_setup: Optional[Dict[str, Any]] = None
    final_action = "NO_TRADE"
    qualification_status = "REJECTED"

    is_bullish_qualified = (
        not rejection_reasons
        and directional_bias == "BULLISH"
        and confluence_score >= cfg["min_confluence_score"]
        and ltf_trigger.get("triggered") is True
        and ltf_trigger.get("direction") == "BULLISH"
    )

    is_bearish_qualified = (
        not rejection_reasons
        and directional_bias == "BEARISH"
        and confluence_score >= cfg["min_confluence_score"]
        and ltf_trigger.get("triggered") is True
        and ltf_trigger.get("direction") == "BEARISH"
    )

    # -------------------------------------------------------------
    # 3. Dynamic Risk Level Engineering
    # -------------------------------------------------------------
    if is_bullish_qualified:
        entry_price = float(ltf_trigger.get("entry_price", ltp))
        inval_price = float(ltf_trigger.get("invalidation_price") or itf_struct.get("swing_low", 0.0))
        risk_plan = calculate_dynamic_risk_levels(clean_sym, "BULLISH", entry_price, inval_price, atr_5m, cfg)

        if risk_plan is not None and risk_plan["reward_risk_ratio"] >= cfg["min_reward_to_risk"]:
            trade_setup = risk_plan
            final_action = "BUY_CE"
            qualification_status = "QUALIFIED"
            contributing_factors.append(f"BUY_CE Setup Qualified: Entry ₹{risk_plan['entry_price']} | SL ₹{risk_plan['stop_loss']} | T1 ₹{risk_plan['target_1']} (R:R {risk_plan['reward_risk_ratio']})")
        else:
            reason = getattr(calculate_dynamic_risk_levels, "last_rejection_reason", None) or "Calculated stop-loss or reward-to-risk ratio is mathematically invalid."
            rejection_reasons.append(reason)
            final_action = "NO_TRADE"

    elif is_bearish_qualified:
        entry_price = float(ltf_trigger.get("entry_price", ltp))
        inval_price = float(ltf_trigger.get("invalidation_price") or itf_struct.get("swing_high", 0.0))
        risk_plan = calculate_dynamic_risk_levels(clean_sym, "BEARISH", entry_price, inval_price, atr_5m, cfg)

        if risk_plan is not None and risk_plan["reward_risk_ratio"] >= cfg["min_reward_to_risk"]:
            trade_setup = risk_plan
            final_action = "BUY_PE"
            qualification_status = "QUALIFIED"
            contributing_factors.append(f"BUY_PE Setup Qualified: Entry ₹{risk_plan['entry_price']} | SL ₹{risk_plan['stop_loss']} | T1 ₹{risk_plan['target_1']} (R:R {risk_plan['reward_risk_ratio']})")
        else:
            reason = getattr(calculate_dynamic_risk_levels, "last_rejection_reason", None) or "Calculated stop-loss or reward-to-risk ratio is mathematically invalid."
            rejection_reasons.append(reason)
            final_action = "NO_TRADE"

    # -------------------------------------------------------------
    # 4. Gate 3: WAIT Qualification (Developing Setups)
    # -------------------------------------------------------------
    has_safety_rejection = (
        not is_live_data
        or (regime is not None and regime in [MarketRegime.SIDEWAYS, MarketRegime.NO_TRADE, MarketRegime.DATA_UNAVAILABLE])
        or bool(timeframe_conflicts)
        or not can_activate
    )

    if final_action == "NO_TRADE" and not has_safety_rejection:
        # If HTF/ITF bias is clear but LTF trigger is pending, or score is moderate
        if directional_bias in ["BULLISH", "BEARISH"] and confluence_score >= cfg["min_wait_score"]:
            final_action = "WAIT"
            qualification_status = "WAITING_CONFIRMATION"
            if not ltf_trigger.get("triggered"):
                contributing_factors.append(f"WAIT: Directional bias is {directional_bias}, awaiting LTF 1M/5M entry trigger confirmation.")
            elif "1H" in missing_tfs:
                contributing_factors.append("WAIT: 1H timeframe missing (confluence score capped at 60). Awaiting HTF alignment.")

    return {
        "symbol": clean_sym,
        "action": final_action,
        "qualification_status": qualification_status,
        "directional_bias": directional_bias,
        "confluence_score": confluence_score,
        "market_regime": regime,
        "trade_setup": trade_setup,
        "rejection_reasons": rejection_reasons,
        "contributing_factors": contributing_factors,
        "timeframe_summary": {
            "htf": mtf_confluence.get("htf_bias", {}).get("direction"),
            "itf_5m": itf_struct.get("direction"),
            "ltf": ltf_trigger.get("direction"),
            "missing": missing_tfs,
            "fallbacks": mtf_confluence.get("active_fallbacks", []),
        },
        "is_paper_trading": True,
        "timestamp": MarketCalendar.format_ist_timestamp(),
    }
