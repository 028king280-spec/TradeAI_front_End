"""
AIVOLVE Signal Activation Engine.
Defines explicit signal lifecycle states, rigorous state transitions,
and deterministic qualification conditions for CALL and PUT option setups.

17 Lifecycle States:
1. NO_TRADE
2. WAITING_FOR_CONFIRMATION
3. CALL_SETUP_READY
4. PUT_SETUP_READY
5. CALL_ACTIVE
6. PUT_ACTIVE
7. ENTRY_TRIGGERED
8. TARGET_1_HIT
9. TARGET_2_HIT
10. TARGET_3_HIT
11. STOP_LOSS_HIT
12. EXITED
13. MISSED
14. EXPIRED
15. CANCELLED
16. DATA_GAP
17. AMBIGUOUS

Strictly distinguishes SETUP_READY from ENTRY_TRIGGERED:
- CALL_SETUP_READY / PUT_SETUP_READY: Meets preliminary technical & option qualification criteria.
- ENTRY_TRIGGERED: The defined entry conditions have ACTUALLY occurred in observed market data ticks.
  Never marks entry because a price was displayed on screen.
- If premium moves > 8% beyond the acceptable entry range before filling, marks MISSED.
"""

from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timezone
from app.data.market_calendar import MarketCalendar


class SignalState:
    NO_TRADE = "NO_TRADE"
    WAITING_FOR_CONFIRMATION = "WAITING_FOR_CONFIRMATION"
    CALL_SETUP_READY = "CALL_SETUP_READY"
    PUT_SETUP_READY = "PUT_SETUP_READY"
    CALL_ACTIVE = "CALL_ACTIVE"
    PUT_ACTIVE = "PUT_ACTIVE"
    ENTRY_TRIGGERED = "ENTRY_TRIGGERED"
    TARGET_1_HIT = "TARGET_1_HIT"
    TARGET_2_HIT = "TARGET_2_HIT"
    TARGET_3_HIT = "TARGET_3_HIT"
    STOP_LOSS_HIT = "STOP_LOSS_HIT"
    EXITED = "EXITED"
    MISSED = "MISSED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    DATA_GAP = "DATA_GAP"
    AMBIGUOUS = "AMBIGUOUS"


# Allowed state transitions graph
VALID_TRANSITIONS: Dict[str, List[str]] = {
    SignalState.NO_TRADE: [
        SignalState.WAITING_FOR_CONFIRMATION,
        SignalState.CALL_SETUP_READY,
        SignalState.PUT_SETUP_READY,
    ],
    SignalState.WAITING_FOR_CONFIRMATION: [
        SignalState.NO_TRADE,
        SignalState.CALL_SETUP_READY,
        SignalState.PUT_SETUP_READY,
        SignalState.CANCELLED,
        SignalState.EXPIRED,
        SignalState.DATA_GAP,
    ],
    SignalState.CALL_SETUP_READY: [
        SignalState.CALL_ACTIVE,
        SignalState.ENTRY_TRIGGERED,
        SignalState.MISSED,
        SignalState.CANCELLED,
        SignalState.EXPIRED,
        SignalState.DATA_GAP,
    ],
    SignalState.PUT_SETUP_READY: [
        SignalState.PUT_ACTIVE,
        SignalState.ENTRY_TRIGGERED,
        SignalState.MISSED,
        SignalState.CANCELLED,
        SignalState.EXPIRED,
        SignalState.DATA_GAP,
    ],
    SignalState.CALL_ACTIVE: [
        SignalState.ENTRY_TRIGGERED,
        SignalState.MISSED,
        SignalState.CANCELLED,
        SignalState.EXPIRED,
        SignalState.DATA_GAP,
    ],
    SignalState.PUT_ACTIVE: [
        SignalState.ENTRY_TRIGGERED,
        SignalState.MISSED,
        SignalState.CANCELLED,
        SignalState.EXPIRED,
        SignalState.DATA_GAP,
    ],
    SignalState.ENTRY_TRIGGERED: [
        SignalState.TARGET_1_HIT,
        SignalState.STOP_LOSS_HIT,
        SignalState.EXITED,
        SignalState.DATA_GAP,
        SignalState.AMBIGUOUS,
    ],
    SignalState.TARGET_1_HIT: [
        SignalState.TARGET_2_HIT,
        SignalState.STOP_LOSS_HIT,
        SignalState.EXITED,
        SignalState.DATA_GAP,
        SignalState.AMBIGUOUS,
    ],
    SignalState.TARGET_2_HIT: [
        SignalState.TARGET_3_HIT,
        SignalState.STOP_LOSS_HIT,
        SignalState.EXITED,
        SignalState.DATA_GAP,
        SignalState.AMBIGUOUS,
    ],
    SignalState.TARGET_3_HIT: [
        SignalState.EXITED,
    ],
    SignalState.STOP_LOSS_HIT: [
        SignalState.EXITED,
    ],
    SignalState.MISSED: [],
    SignalState.EXPIRED: [],
    SignalState.CANCELLED: [],
    SignalState.EXITED: [],
    SignalState.DATA_GAP: [
        SignalState.ENTRY_TRIGGERED,
        SignalState.TARGET_1_HIT,
        SignalState.TARGET_2_HIT,
        SignalState.TARGET_3_HIT,
        SignalState.STOP_LOSS_HIT,
        SignalState.AMBIGUOUS,
        SignalState.EXITED,
    ],
    SignalState.AMBIGUOUS: [
        SignalState.EXITED,
    ],
}


def can_transition(from_state: str, to_state: str) -> bool:
    """Checks whether the requested state transition is permissible."""
    allowed = VALID_TRANSITIONS.get(from_state, [])
    return to_state in allowed


def validate_state_transition(from_state: str, to_state: str) -> Tuple[bool, str]:
    """Validates transition and returns detailed explanation if invalid."""
    if from_state == to_state:
        return True, "No transition required (current state matches target)."
    allowed = VALID_TRANSITIONS.get(from_state, [])
    if to_state in allowed:
        return True, f"Valid transition from {from_state} to {to_state}."
    return False, f"Illegal state transition from {from_state} to {to_state}. Allowed targets: {allowed}."


def evaluate_setup_qualification(
    symbol: str,
    market_state_info: Dict[str, Any],
    candidate_contract: Dict[str, Any],
    underlying_ltp: float,
    atr_14: float,
    min_strategy_score: int = 65,
) -> Tuple[str, List[str], Dict[str, Any]]:
    """
    Evaluates whether a candidate option contract qualifies for CALL_SETUP_READY or PUT_SETUP_READY.
    Returns: (signal_state, disqualification_reasons, metadata)
    """
    state = market_state_info.get("marketState")
    disqualifications: List[str] = []

    # Check 1: Market State Alignment
    if state in ["DATA_UNAVAILABLE"]:
        disqualifications.append(f"Market state is {state}. Option setups require active data feed.")
        return SignalState.NO_TRADE, disqualifications, {}

    # Check 2: Minimum Strategy Score (Strictly verifies quantitative score without silent default)
    raw_score = candidate_contract.get("analysis_score") if candidate_contract.get("analysis_score") is not None else candidate_contract.get("strategyScore")
    if raw_score is None:
        disqualifications.append("Strategy quantitative analysis score is missing from candidate contract.")
        strat_score = 0
    else:
        strat_score = int(raw_score)
        if strat_score < min_strategy_score:
            disqualifications.append(f"Strategy quantitative score ({strat_score}) is below minimum threshold ({min_strategy_score}).")

    # Check 3: Option Contract Validity & Live Quotes
    premium = float(candidate_contract.get("signal_premium") or candidate_contract.get("ltp") or candidate_contract.get("currentPremium") or 0.0)
    if premium < 10.0:
        disqualifications.append(f"Option premium (₹{premium:.2f}) is too cheap (< ₹10), high risk of illiquidity and rapid theta decay.")

    bid = float(candidate_contract.get("signal_bid") or candidate_contract.get("bid") or premium)
    ask = float(candidate_contract.get("signal_ask") or candidate_contract.get("ask") or premium)
    spread = max(0.0, ask - bid)
    spread_pct = (spread / premium * 100.0) if premium > 0 else 0.0

    if spread_pct > 2.5:
        disqualifications.append(f"Excessive bid/ask spread ({spread_pct:.2f}% of premium > 2.5%). Slippage would impair expected return.")

    oi = int(candidate_contract.get("openInterest") or candidate_contract.get("oi") or 0)
    if oi > 0 and oi < 20000:
        disqualifications.append(f"Open interest ({oi:,}) is below the institutional liquidity floor (20,000 contracts).")

    # Check 4: Risk/Reward Profile
    entry_min = float(candidate_contract.get("entry_zone_min") or candidate_contract.get("suggestedEntryMin") or round(premium * 0.98, 1))
    entry_max = float(candidate_contract.get("entry_zone_max") or candidate_contract.get("suggestedEntryMax") or round(premium * 1.02, 1))
    stop_loss = float(candidate_contract.get("stop_loss_premium") or candidate_contract.get("stopLoss") or round(premium * 0.80, 1))
    target_1 = float(candidate_contract.get("target_1_premium") or candidate_contract.get("target1") or round(premium * 1.25, 1))
    target_2 = float(candidate_contract.get("target_2_premium") or candidate_contract.get("target2") or round(premium * 1.45, 1))
    target_3 = float(candidate_contract.get("target_3_premium") or candidate_contract.get("target3") or round(premium * 1.70, 1))

    risk = premium - stop_loss
    reward = target_2 - premium
    rr_ratio = reward / risk if risk > 0 else 0.0

    if rr_ratio < 1.5:
        disqualifications.append(f"Reward-to-risk ratio ({rr_ratio:.2f}) is below the required 1:1.5 threshold.")

    # Check 5: Check if already missed before activation
    if premium > entry_max * 1.08:
        disqualifications.append(f"Current premium ₹{premium:.2f} has already exceeded the maximum entry zone ₹{entry_max:.2f} by >8%.")
        return SignalState.MISSED, disqualifications, {}

    if disqualifications:
        return SignalState.NO_TRADE, disqualifications, {}

    # Qualify setup
    opt_type = str(
        candidate_contract.get("option_type")
        or candidate_contract.get("type")
        or candidate_contract.get("bias")
        or ("CE" if "CE" in candidate_contract.get("symbol", "") else "PE")
    ).upper()
    qualified_state = SignalState.CALL_SETUP_READY if opt_type == "CE" else SignalState.PUT_SETUP_READY
    meta = {
        "rr_ratio": round(rr_ratio, 2),
        "entry_zone": [entry_min, entry_max],
        "stop_loss": stop_loss,
        "targets": [target_1, target_2, target_3],
        "spread_pct": round(spread_pct, 2),
        "oi": oi,
        "strategyScore": strat_score,
    }
    return qualified_state, [], meta


def evaluate_entry_trigger(
    signal_state: str,
    observed_market_price: float,
    entry_zone_min: float,
    entry_zone_max: float,
) -> Tuple[str, Optional[str]]:
    """
    Evaluates whether an observed market price tick triggers the actual paper entry,
    remains setup-ready, or has been missed.
    Never assumes entry merely because setup was ready.
    """
    if signal_state not in [SignalState.CALL_SETUP_READY, SignalState.PUT_SETUP_READY, SignalState.CALL_ACTIVE, SignalState.PUT_ACTIVE]:
        return signal_state, None

    # Check Entry Zone condition
    if entry_zone_min <= observed_market_price <= entry_zone_max:
        return SignalState.ENTRY_TRIGGERED, f"Observed price ₹{observed_market_price:.2f} entered approved entry zone [₹{entry_zone_min} - ₹{entry_zone_max}]."

    # Check if price jumped too far beyond entry zone (>8% beyond max)
    if observed_market_price > entry_zone_max * 1.08:
        return SignalState.MISSED, f"Observed price ₹{observed_market_price:.2f} exceeded max approved entry zone ₹{entry_zone_max} by >8%."

    # Still waiting for pullback into entry zone
    return signal_state, None


def get_frontend_signal_badge(
    signal_state: str,
    option_type: Optional[str] = None
) -> Dict[str, Any]:
    """
    Returns visual badge indicators strictly matching Requirement 2:
    - CALL SETUP ACTIVE
    - PUT SETUP ACTIVE
    - NO TRADE — WAIT FOR CONFIRMATION
    - ENTRY TRIGGERED
    """
    if signal_state in [SignalState.CALL_SETUP_READY, SignalState.CALL_ACTIVE]:
        return {
            "badgeText": "CALL SETUP ACTIVE",
            "variant": "BULLISH",
            "colorClass": "bg-emerald-500/20 text-emerald-400 border-emerald-500/40",
            "pulse": True,
        }
    elif signal_state in [SignalState.PUT_SETUP_READY, SignalState.PUT_ACTIVE]:
        return {
            "badgeText": "PUT SETUP ACTIVE",
            "variant": "BEARISH",
            "colorClass": "bg-rose-500/20 text-rose-400 border-rose-500/40",
            "pulse": True,
        }
    elif signal_state == SignalState.ENTRY_TRIGGERED:
        return {
            "badgeText": "ENTRY TRIGGERED",
            "variant": "ACTIVE",
            "colorClass": "bg-blue-500/20 text-blue-400 border-blue-500/40",
            "pulse": True,
        }
    elif signal_state in [SignalState.TARGET_1_HIT, SignalState.TARGET_2_HIT, SignalState.TARGET_3_HIT]:
        return {
            "badgeText": f"PROFIT TARGET REACHED ({signal_state.replace('_HIT', '')})",
            "variant": "PROFIT",
            "colorClass": "bg-emerald-500/20 text-emerald-400 border-emerald-500/40",
            "pulse": False,
        }
    elif signal_state == SignalState.STOP_LOSS_HIT:
        return {
            "badgeText": "STOP-LOSS HIT",
            "variant": "LOSS",
            "colorClass": "bg-rose-500/20 text-rose-400 border-rose-500/40",
            "pulse": False,
        }
    else:
        return {
            "badgeText": "NO TRADE — WAIT FOR CONFIRMATION",
            "variant": "NEUTRAL",
            "colorClass": "bg-amber-500/15 text-amber-400 border-amber-500/30",
            "pulse": False,
        }
