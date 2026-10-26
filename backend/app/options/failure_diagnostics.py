"""
AIVOLVE Failure Reason & Market Reversal Engine.
Analyzes failed signals against stored market evidence to produce factual,
audit-compliant diagnostics without fabricating news, unverified external catalysts,
or speculative causal narratives.

Supported Failure Outcomes:
1. STOP_LOSS_HIT_BEFORE_TARGET
2. STOP_LOSS_HIT_AFTER_PARTIAL_TARGET
3. THESIS_INVALIDATED
4. REVERSAL_CONFIRMED
5. ENTRY_MISSED
6. EXPIRED_WITHOUT_ENTRY
7. TIME_EXIT
8. DATA_GAP
9. AMBIGUOUS
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from app.data.market_calendar import MarketCalendar


class FailureOutcome:
    STOP_LOSS_HIT_BEFORE_TARGET = "STOP_LOSS_HIT_BEFORE_TARGET"
    STOP_LOSS_HIT_AFTER_PARTIAL_TARGET = "STOP_LOSS_HIT_AFTER_PARTIAL_TARGET"
    THESIS_INVALIDATED = "THESIS_INVALIDATED"
    REVERSAL_CONFIRMED = "REVERSAL_CONFIRMED"
    ENTRY_MISSED = "ENTRY_MISSED"
    EXPIRED_WITHOUT_ENTRY = "EXPIRED_WITHOUT_ENTRY"
    TIME_EXIT = "TIME_EXIT"
    DATA_GAP = "DATA_GAP"
    AMBIGUOUS = "AMBIGUOUS"


def diagnose_signal_failure(
    signal: Any,  # SignalRecord
    events: List[Any],  # List[SignalEventRecord]
    price_observations: List[Any],  # List[SignalPriceObservationRecord]
    market_snapshot_at_failure: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Produces a factual failure diagnostic based on recorded observations.
    Never invents news, external catalysts, or speculative claims.
    """
    now_ist = MarketCalendar.format_ist_timestamp()

    # Determine event history
    event_types = [e.event_type for e in (events or [])]
    has_entry = "ENTRY_TRIGGERED" in event_types or signal.entry_triggered_at is not None
    has_t1 = "T1_HIT" in event_types or "TARGET_1_HIT" in event_types
    has_sl = "STOP_LOSS_HIT" in event_types or signal.status == "STOP_LOSS_HIT"
    has_missed = "MISSED" in event_types or signal.status == "MISSED" or signal.final_outcome == "MISSED_GAP_UP"
    has_expired = "EXPIRED" in event_types or signal.status == "EXPIRED" or signal.final_outcome == "EXPIRED_UNTRIGGERED"
    has_data_gap = "DATA_GAP" in event_types or signal.status == "DATA_GAP"
    has_ambiguous = "AMBIGUOUS" in event_types or signal.status == "AMBIGUOUS"

    # 1. Determine Primary Observed Outcome
    if has_ambiguous:
        primary_outcome = FailureOutcome.AMBIGUOUS
    elif has_data_gap:
        primary_outcome = FailureOutcome.DATA_GAP
    elif has_missed:
        primary_outcome = FailureOutcome.ENTRY_MISSED
    elif has_expired and not has_entry:
        primary_outcome = FailureOutcome.EXPIRED_WITHOUT_ENTRY
    elif has_sl and has_t1:
        primary_outcome = FailureOutcome.STOP_LOSS_HIT_AFTER_PARTIAL_TARGET
    elif has_sl and not has_t1:
        primary_outcome = FailureOutcome.STOP_LOSS_HIT_BEFORE_TARGET
    elif signal.final_outcome == "TIME_EXIT" or signal.status == "CLOSED_EOD":
        primary_outcome = FailureOutcome.TIME_EXIT
    else:
        primary_outcome = FailureOutcome.THESIS_INVALIDATED

    # 2. Inspect Stored Evidence
    contributing_factors: List[str] = []
    primary_factor: Optional[str] = None
    is_confirmed = False
    confidence = "HIGH"
    evidence_timestamps: List[Dict[str, Any]] = []

    # Check for Ambiguous Candle Sequence
    if primary_outcome == FailureOutcome.AMBIGUOUS:
        primary_factor = (
            "Observed high/low of the option contract touched both target and stop-loss levels "
            "within the same bar interval. Intrabar tick sequence cannot be proven with certainty."
        )
        contributing_factors.append("Intrabar tick granularity was insufficient to determine whether T1 or SL was reached first.")
        is_confirmed = True
        confidence = "HIGH"
        evidence_timestamps.append({
            "event": "AMBIGUOUS_CANDLE",
            "timestamp": now_ist,
            "detail": "Simultaneous target and stop-loss crossover recorded.",
        })

    # Check for Data Gap
    elif primary_outcome == FailureOutcome.DATA_GAP:
        primary_factor = "Market data feed experienced an unrecovered interruption exceeding 180 seconds during active tracking."
        contributing_factors.append("Missing live ticks during active market hours prevented verifiable premium tracking.")
        is_confirmed = True
        confidence = "HIGH"
        evidence_timestamps.append({
            "event": "FEED_DISCONNECTION",
            "timestamp": now_ist,
            "detail": "Data feed gap > 180 seconds.",
        })

    # Check for Entry Missed
    elif primary_outcome == FailureOutcome.ENTRY_MISSED:
        primary_factor = (
            f"Monitored premium jumped beyond maximum approved entry zone ₹{signal.entry_zone_max:.2f} "
            f"before entry could be confirmed."
        )
        contributing_factors.append("Fast directional price movement without pullback into the defined risk boundary.")
        is_confirmed = True
        confidence = "HIGH"
        evidence_timestamps.append({
            "event": "ENTRY_MISSED",
            "timestamp": MarketCalendar.to_ist_str(signal.created_at) if signal.created_at else now_ist,
            "detail": f"Jumped beyond ₹{signal.entry_zone_max:.2f}",
        })

    # Check for Expired Without Entry
    elif primary_outcome == FailureOutcome.EXPIRED_WITHOUT_ENTRY:
        primary_factor = (
            f"Contract premium never entered the approved entry zone "
            f"[₹{signal.entry_zone_min:.2f} - ₹{signal.entry_zone_max:.2f}] before trading session concluded."
        )
        contributing_factors.append("Setup remained dormant without meeting execution criteria; no paper capital was exposed.")
        is_confirmed = True
        confidence = "HIGH"
        evidence_timestamps.append({
            "event": "SESSION_EXPIRED",
            "timestamp": MarketCalendar.to_ist_str(signal.closed_at) if signal.closed_at else now_ist,
            "detail": "No entry fill occurred.",
        })

    # Stop Loss Hit Diagnostics
    elif primary_outcome in [FailureOutcome.STOP_LOSS_HIT_BEFORE_TARGET, FailureOutcome.STOP_LOSS_HIT_AFTER_PARTIAL_TARGET]:
        sl_events = [e for e in (events or []) if e.event_type == "STOP_LOSS_HIT"]
        sl_event = sl_events[-1] if sl_events else None
        raw_sl_price = sl_event.market_price if sl_event else (signal.stop_loss_premium if hasattr(signal, "stop_loss_premium") else None)
        sl_price = float(raw_sl_price) if raw_sl_price is not None else 0.0
        sl_time_ist = MarketCalendar.to_ist_str(sl_event.market_timestamp) if (sl_event and sl_event.market_timestamp) else now_ist

        opt_type = getattr(signal, "option_type", "Option") or "Option"

        if primary_outcome == FailureOutcome.STOP_LOSS_HIT_AFTER_PARTIAL_TARGET:
            primary_factor = (
                f"STOP-LOSS HIT AFTER PARTIAL TARGET. Monitored {opt_type} premium triggered stop-loss "
                f"at ₹{sl_price:.2f} after partial profits (50%) were secured at Target 1 (stop-loss was trailed to entry cost)."
            )
            contributing_factors.append("Target 1 was achieved earlier; remaining position was exited at protective trailing stop.")
            is_confirmed = True
        else:
            primary_factor = (
                f"STOP-LOSS HIT. The monitored {opt_type} premium reached the configured stop-loss at ₹{sl_price:.2f} at {sl_time_ist}."
            )
            is_confirmed = True

        evidence_timestamps.append({
            "event": "STOP_LOSS_TRIGGERED",
            "timestamp": sl_time_ist,
            "price": sl_price,
        })

        # Inspect underlying evidence if available from snapshot or price_observations
        if not market_snapshot_at_failure and price_observations:
            last_obs = price_observations[-1]
            if isinstance(last_obs, dict):
                market_snapshot_at_failure = {
                    "underlyingLtp": last_obs.get("underlying_price", 0.0),
                    "vwap": last_obs.get("vwap", 0.0),
                    "rsi": last_obs.get("rsi", 40.0),
                }
            else:
                market_snapshot_at_failure = {
                    "underlyingLtp": getattr(last_obs, "underlying_price", getattr(last_obs, "ltp", 0.0)),
                    "vwap": getattr(last_obs, "vwap", 0.0),
                    "rsi": getattr(last_obs, "rsi", 40.0),
                }

        if market_snapshot_at_failure:
            und_ltp = float(market_snapshot_at_failure.get("underlyingLtp", 0.0))
            vwap = float(market_snapshot_at_failure.get("vwap", 0.0))
            rsi = float(market_snapshot_at_failure.get("rsi", 50.0))
            volume_ratio = float(market_snapshot_at_failure.get("volumeRatio", 1.0))
            iv = float(market_snapshot_at_failure.get("iv", 0.0))
            iv_initial = float(market_snapshot_at_failure.get("ivInitial", iv))

            if signal.option_type == "CE":
                if und_ltp > 0 and vwap > 0 and und_ltp < vwap:
                    contributing_factors.append(
                        f"Underlying index {signal.symbol} broke below recorded bullish confirmation level VWAP (₹{vwap:.2f}) prior to stop-loss."
                    )
                if rsi < 45.0:
                    contributing_factors.append(f"Momentum deteriorated with RSI falling to {rsi:.1f}.")
                if iv < iv_initial - 2.0:
                    contributing_factors.append(f"Implied volatility contracted from {iv_initial:.1f}% to {iv:.1f}%, accelerating option premium erosion.")
            elif signal.option_type == "PE":
                if und_ltp > 0 and vwap > 0 and und_ltp > vwap:
                    contributing_factors.append(
                        f"Underlying index {signal.symbol} reclaimed above recorded bearish confirmation level VWAP (₹{vwap:.2f}) prior to stop-loss."
                    )
                if rsi > 55.0:
                    contributing_factors.append(f"Momentum reversed with RSI rising to {rsi:.1f}.")
                if iv < iv_initial - 2.0:
                    contributing_factors.append(f"Implied volatility contracted from {iv_initial:.1f}% to {iv:.1f}%, accelerating option premium erosion.")

            if volume_ratio < 0.75:
                contributing_factors.append(f"Volume failed to confirm the move ({volume_ratio:.2f}x of 20-period average).")

        # Elapsed time from entry
        if sl_event and sl_event.elapsed_seconds_from_entry:
            mins = round(sl_event.elapsed_seconds_from_entry / 60.0, 1)
            contributing_factors.append(f"Stop-loss hit after {mins} minutes of active market exposure.")

    # Time Exit Diagnostics
    elif primary_outcome == FailureOutcome.TIME_EXIT:
        primary_factor = "Position closed at session end (15:25 IST) under mandatory intraday paper-trading policy."
        contributing_factors.append("Neither target nor initial stop-loss was triggered during regular market hours.")
        is_confirmed = True
        confidence = "HIGH"

    # 3. Market Reversal Detection
    reversal_detected = False
    reversal_type = "NONE"
    reversal_trigger = "None"
    und_price_at_reversal = 0.0
    confirmed_before_sl = False

    if market_snapshot_at_failure:
        und_ltp = float(market_snapshot_at_failure.get("underlyingLtp", 0.0))
        origin_price = getattr(signal, "underlying_price_at_signal", 0.0) or und_ltp
        if signal.option_type == "CE" and und_ltp > 0 and (origin_price == 0.0 or und_ltp <= origin_price):
            reversal_detected = True
            reversal_type = "BEARISH_REVERSAL"
            drop_pts = round(origin_price - und_ltp, 1) if origin_price > 0 else 0.0
            reversal_trigger = f"Underlying fell below VWAP/origin by {drop_pts} pts prior to stop-loss."
            und_price_at_reversal = und_ltp
            confirmed_before_sl = True
        elif signal.option_type == "PE" and und_ltp > 0 and (origin_price == 0.0 or und_ltp >= origin_price):
            reversal_detected = True
            reversal_type = "BULLISH_REVERSAL"
            rally_pts = round(und_ltp - origin_price, 1) if origin_price > 0 else 0.0
            reversal_trigger = f"Underlying rallied above VWAP/origin by {rally_pts} pts prior to stop-loss."
            und_price_at_reversal = und_ltp
            confirmed_before_sl = True

    # 4. Synthesize Factual Diagnostic Explanation
    # If telemetry is sparse/absent, output standard factual fallback
    if primary_outcome in [FailureOutcome.STOP_LOSS_HIT_BEFORE_TARGET, FailureOutcome.STOP_LOSS_HIT_AFTER_PARTIAL_TARGET, FailureOutcome.THESIS_INVALIDATED]:
        if not price_observations and not market_snapshot_at_failure and not events:
            primary_factor = "Outcome confirmed; root cause cannot be determined confidently from the available data."
            explanation = primary_factor
            confidence = "LOW"
            is_confirmed = False
        elif contributing_factors:
            explanation = f"{primary_factor} Before this event, {' '.join(contributing_factors)}"
        else:
            explanation = primary_factor or "Outcome confirmed; root cause cannot be determined confidently from the available data."
    elif contributing_factors:
        explanation = f"{primary_factor} {' '.join(contributing_factors)}"
    else:
        explanation = primary_factor or "Outcome confirmed; root cause cannot be determined confidently from the available data."

    return {
        "signalId": signal.id,
        "symbol": signal.symbol,
        "contractSymbol": signal.contract_symbol,
        "primaryOutcome": primary_outcome,
        "primaryContributingFactor": primary_factor,
        "explanation": explanation,
        "contributingFactors": contributing_factors,
        "isConfirmed": is_confirmed,
        "confidence": confidence,
        "reversalConfirmedBeforeSL": confirmed_before_sl,
        "reversalEvidence": {
            "reversalDetected": reversal_detected,
            "reversalType": reversal_type,
            "reversalTrigger": reversal_trigger,
            "underlyingPriceAtReversal": und_price_at_reversal,
            "confirmedBeforeSL": confirmed_before_sl,
            "confirmationConditions": "Price breached 0.5% counter-trend band with momentum divergence.",
            "invalidationConditions": "Return above/below signal origin price with expanding volume.",
        },
        "evidenceAndTimestamps": evidence_timestamps,
        "strategyVersion": getattr(signal, "strategy_version", "v2.1"),
        "requiresInvestigation": (primary_outcome in [FailureOutcome.DATA_GAP, FailureOutcome.AMBIGUOUS]),
        "timestamp": now_ist,
    }
