"""
AIVOLVE Phase 4 Step 4.3 — Deterministic Trade & Order Lifecycle State Machine.

Guarantees:
- Deterministic SHA-256 identifiers (no non-deterministic random UUIDs during replay).
- Strict monotonic trade lifecycle state transitions preventing resurrection or double-exit.
- Exact quantity accounting invariant (`exited_quantity + remaining_quantity == initial_quantity`).
"""

from __future__ import annotations

import hashlib
from typing import Dict, Set

from app.backtesting.simulation_models import TradeLifecycleState

VALID_TRADE_TRANSITIONS: Dict[TradeLifecycleState, Set[TradeLifecycleState]] = {
    TradeLifecycleState.PENDING: {
        TradeLifecycleState.OPEN,
        TradeLifecycleState.CANCELLED,
        TradeLifecycleState.REJECTED,
    },
    TradeLifecycleState.OPEN: {
        TradeLifecycleState.PARTIALLY_EXITED,
        TradeLifecycleState.CLOSED,
    },
    TradeLifecycleState.PARTIALLY_EXITED: {
        TradeLifecycleState.PARTIALLY_EXITED,
        TradeLifecycleState.CLOSED,
    },
    TradeLifecycleState.CLOSED: set(),
    TradeLifecycleState.CANCELLED: set(),
    TradeLifecycleState.REJECTED: set(),
}

TERMINAL_TRADE_STATES: Set[TradeLifecycleState] = {
    TradeLifecycleState.CLOSED,
    TradeLifecycleState.CANCELLED,
    TradeLifecycleState.REJECTED,
}


def deterministic_id(prefix: str, *parts: object, length: int = 16) -> str:
    """Produces deterministic upper-hex IDs without wall-clock or UUID4 entropy."""
    joined = "|".join(str(p) for p in parts)
    digest = hashlib.sha256(joined.encode("utf-8")).hexdigest()[:length].upper()
    return f"{prefix}-{digest}"


def validate_trade_transition(
    current_state: TradeLifecycleState,
    target_state: TradeLifecycleState,
) -> None:
    """Fails closed on any forbidden trade lifecycle transition."""
    allowed = VALID_TRADE_TRANSITIONS.get(current_state, set())
    if target_state not in allowed:
        raise ValueError(
            f"Invalid trade lifecycle transition: {current_state.value} -> {target_state.value}."
        )


def assert_exit_quantity_valid(
    *,
    trade_id: str,
    state: TradeLifecycleState,
    initial_quantity: int,
    exited_quantity: int,
    remaining_quantity: int,
    exit_qty: int,
) -> int:
    """
    Validates an exit leg quantity against remaining open quantity and lifecycle state.
    Prevents any partial/final exit over-fill or double-counting.
    """
    if state in TERMINAL_TRADE_STATES:
        raise ValueError(f"Trade '{trade_id}' is already in terminal state '{state.value}'; cannot exit.")
    if state == TradeLifecycleState.PENDING:
        raise ValueError(f"Trade '{trade_id}' has not been opened; cannot exit.")
    if exited_quantity + remaining_quantity != initial_quantity:
        raise ValueError(
            f"Trade '{trade_id}' quantity invariant corrupted: "
            f"exited({exited_quantity}) + remaining({remaining_quantity}) != initial({initial_quantity})."
        )
    if exit_qty <= 0:
        raise ValueError(f"Exit quantity must be positive for trade '{trade_id}', got {exit_qty}.")
    if exit_qty > remaining_quantity:
        raise ValueError(
            f"Double-exit / over-exit prevented on trade '{trade_id}': "
            f"requested {exit_qty}, remaining {remaining_quantity}."
        )
    return remaining_quantity - exit_qty

