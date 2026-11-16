"""
AIVOLVE Phase 4 Step 4.3 — Deterministic Bar-by-Bar Fill & Black-Scholes Research Engine.

Responsibilities:
- Parse integrity-audited historical DataFrames into strict `CompletedBar` sequences.
- Enforce next completed bar execution (`bar.open_time_ist >= signal_available_at_ist`),
  zero same-bar close execution, and rejection of incomplete bars.
- Round effective buy/sell fill prices adversely to tick size when enabled.
- Evaluate stop-loss, partial Target 1, final Target 2, gap fills, EOD square-off, and
  expiry closes without ever resolving intrabar SL/target ambiguities optimistically.
- Provide deterministic analytical Black-Scholes valuation (`math.erf`) strictly for
  `SYNTHETIC_BS_RESEARCH` (`SYNTHETIC_MODELLED_OPTION_PNL`).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, time as dt_time
from typing import List, Optional, Tuple

import pandas as pd

from app.backtesting.configuration import IST_ZONE
from app.backtesting.data_integrity import _strict_bool_completion, compute_candle_close_ist
from app.backtesting.simulation_models import (
    AmbiguityPolicy,
    ExitReason,
    GapPolicy,
    IntrabarAmbiguityEvidence,
    SignalDirection,
    SimulationSignal,
    SyntheticBSAssumptions,
    TriggerPriceDomain,
)


@dataclass(frozen=True)
class CompletedBar:
    """Single immutable verified historical candle bar."""

    index: int
    open_time_ist: datetime
    close_time_ist: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    is_complete: bool


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def price_synthetic_bs_option(
    *,
    spot: float,
    strike: float,
    valuation_time_ist: datetime,
    expiry_datetime_ist: datetime,
    risk_free_rate: float,
    dividend_yield: float,
    implied_volatility: float,
    option_type: str,
) -> float:
    """
    Deterministic European Black-Scholes-Merton analytical option pricer using
    exact IST time-to-expiry (in 365-day years). Strictly research-only for Mode B.
    """
    if not math.isfinite(spot) or spot <= 0.0:
        raise ValueError(f"spot must be finite and > 0, got {spot}")
    if not math.isfinite(strike) or strike <= 0.0:
        raise ValueError(f"strike must be finite and > 0, got {strike}")
    if not math.isfinite(implied_volatility) or implied_volatility <= 0.0:
        raise ValueError(f"implied_volatility must be > 0, got {implied_volatility}")

    val_ist = valuation_time_ist.astimezone(IST_ZONE)
    exp_ist = expiry_datetime_ist.astimezone(IST_ZONE)
    dt_sec = max(0.0, (exp_ist - val_ist).total_seconds())
    t_years = dt_sec / (365.0 * 86400.0)

    opt = option_type.strip().upper()
    if opt not in ("CE", "PE"):
        raise ValueError(f"option_type must be 'CE' or 'PE', got {option_type!r}")

    if t_years <= 0.0:
        return max(0.0, spot - strike) if opt == "CE" else max(0.0, strike - spot)

    sqrt_t = math.sqrt(t_years)
    vol_sqrt_t = implied_volatility * sqrt_t
    d1 = (
        math.log(spot / strike)
        + (risk_free_rate - dividend_yield + 0.5 * implied_volatility * implied_volatility) * t_years
    ) / vol_sqrt_t
    d2 = d1 - vol_sqrt_t

    disc_q = math.exp(-dividend_yield * t_years)
    disc_r = math.exp(-risk_free_rate * t_years)

    if opt == "CE":
        price = spot * disc_q * _norm_cdf(d1) - strike * disc_r * _norm_cdf(d2)
    else:
        price = strike * disc_r * _norm_cdf(-d2) - spot * disc_q * _norm_cdf(-d1)
    return max(0.0, float(price))


def apply_adverse_slippage_and_tick(
    *,
    raw_price: float,
    slippage_per_unit: float,
    is_buy: bool,
    tick_size: float,
    enforce_tick_rounding: bool,
) -> Tuple[float, float]:
    """
    Computes conservative effective fill price and realized slippage magnitude:
    - Buy orders suffer upward slippage and ceil-to-tick alignment.
    - Sell orders suffer downward slippage (floored at 0.0) and floor-to-tick alignment.
    Returns `(effective_fill_price, realized_slippage_per_unit)`.
    """
    if not math.isfinite(raw_price) or raw_price < 0.0:
        raise ValueError(f"raw_price must be non-negative finite float, got {raw_price}")
    if not math.isfinite(slippage_per_unit) or slippage_per_unit < 0.0:
        raise ValueError(f"slippage_per_unit must be non-negative finite float, got {slippage_per_unit}")

    if is_buy:
        shifted = raw_price + slippage_per_unit
        if enforce_tick_rounding:
            steps = math.ceil((shifted - 1e-12) / tick_size)
            eff = round(max(0.0, steps * tick_size), 6)
        else:
            eff = round(shifted, 6)
        realized_slip = round(max(0.0, eff - raw_price), 6)
        return eff, realized_slip

    shifted = max(0.0, raw_price - slippage_per_unit)
    if enforce_tick_rounding:
        steps = math.floor((shifted + 1e-12) / tick_size)
        eff = round(max(0.0, steps * tick_size), 6)
    else:
        eff = round(shifted, 6)
    realized_slip = round(max(0.0, raw_price - eff), 6)
    return eff, realized_slip


def extract_completed_bars(
    df: pd.DataFrame,
    *,
    timeframe: str,
    market_close_hhmm: str = "15:30",
) -> List[CompletedBar]:
    """
    Converts a verified DataFrame into strictly completed `CompletedBar` records,
    failing closed if any forming/incomplete bar or non-IST timestamp appears.
    """
    parts = market_close_hhmm.strip().split(":")
    close_dt_t = dt_time(int(parts[0]), int(parts[1]))
    has_complete_col = "is_complete" in df.columns
    has_closed_col = "is_closed" in df.columns

    bars: List[CompletedBar] = []
    for idx in range(len(df)):
        row = df.iloc[idx]
        if has_complete_col and _strict_bool_completion(row["is_complete"]) is not True:
            raise ValueError(
                f"Incomplete candle rejected at row {idx} (`is_complete={row['is_complete']!r}`)."
            )
        if has_closed_col and _strict_bool_completion(row["is_closed"]) is not True:
            raise ValueError(
                f"Incomplete candle rejected at row {idx} (`is_closed={row['is_closed']!r}`)."
            )

        raw_ts = row["timestamp"]
        ts_obj = pd.to_datetime(raw_ts) if type(raw_ts) is str else raw_ts
        py_dt = ts_obj.to_pydatetime() if isinstance(ts_obj, pd.Timestamp) else ts_obj
        if py_dt.tzinfo is None or py_dt.tzinfo.utcoffset(py_dt) is None:
            raise ValueError(f"Timestamp at row {idx} must be timezone-aware, got {raw_ts!r}.")
        open_ist = py_dt.astimezone(IST_ZONE)
        close_ist = compute_candle_close_ist(open_ist, timeframe, close_dt_t)

        bars.append(
            CompletedBar(
                index=idx,
                open_time_ist=open_ist,
                close_time_ist=close_ist,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]) if "volume" in df.columns else 0.0,
                is_complete=True,
            )
        )
    return bars


@dataclass(frozen=True)
class BarOptionValuation:
    """Synthetic option bar extremes computed via Black-Scholes from underlying OHLC."""

    v_open: float
    v_close: float
    v_adverse: float
    v_favourable: float
    v_low: float
    v_high: float


def value_bar_option_bs(
    bar: CompletedBar,
    assumptions: SyntheticBSAssumptions,
) -> BarOptionValuation:
    """
    Maps an underlying OHLC bar onto conservative European option values at bar open
    and close extremes. Never invents tick-level intrabar volatility shocks.
    """
    v_open = price_synthetic_bs_option(
        spot=bar.open,
        strike=assumptions.strike_price,
        valuation_time_ist=bar.open_time_ist,
        expiry_datetime_ist=assumptions.expiry_datetime_ist,
        risk_free_rate=assumptions.risk_free_rate,
        dividend_yield=assumptions.dividend_yield,
        implied_volatility=assumptions.implied_volatility,
        option_type=assumptions.option_type,
    )
    v_close = price_synthetic_bs_option(
        spot=bar.close,
        strike=assumptions.strike_price,
        valuation_time_ist=bar.close_time_ist,
        expiry_datetime_ist=assumptions.expiry_datetime_ist,
        risk_free_rate=assumptions.risk_free_rate,
        dividend_yield=assumptions.dividend_yield,
        implied_volatility=assumptions.implied_volatility,
        option_type=assumptions.option_type,
    )
    v_high_s = price_synthetic_bs_option(
        spot=bar.high,
        strike=assumptions.strike_price,
        valuation_time_ist=bar.close_time_ist,
        expiry_datetime_ist=assumptions.expiry_datetime_ist,
        risk_free_rate=assumptions.risk_free_rate,
        dividend_yield=assumptions.dividend_yield,
        implied_volatility=assumptions.implied_volatility,
        option_type=assumptions.option_type,
    )
    v_low_s = price_synthetic_bs_option(
        spot=bar.low,
        strike=assumptions.strike_price,
        valuation_time_ist=bar.close_time_ist,
        expiry_datetime_ist=assumptions.expiry_datetime_ist,
        risk_free_rate=assumptions.risk_free_rate,
        dividend_yield=assumptions.dividend_yield,
        implied_volatility=assumptions.implied_volatility,
        option_type=assumptions.option_type,
    )
    if assumptions.option_type == "CE":
        v_fav, v_adv = v_high_s, v_low_s
    else:
        v_fav, v_adv = v_low_s, v_high_s
    return BarOptionValuation(
        v_open=v_open,
        v_close=v_close,
        v_adverse=v_adv,
        v_favourable=v_fav,
        v_low=min(v_open, v_adv, v_fav, v_close),
        v_high=max(v_open, v_adv, v_fav, v_close),
    )


def find_next_eligible_bar_index(
    bars: List[CompletedBar],
    signal_available_at_ist: datetime,
) -> Optional[int]:
    """
    Strictly enforces next-bar execution: returns index of the earliest completed bar
    whose `open_time_ist >= signal_available_at_ist`. Never selects the bar that emitted
    the signal (`bar.open_time_ist < signal_available_at_ist`).
    """
    sig_ist = signal_available_at_ist.astimezone(IST_ZONE)
    for idx, bar in enumerate(bars):
        if bar.open_time_ist >= sig_ist:
            return idx
    return None


def evaluate_entry_candidate_on_bar(
    *,
    bar: CompletedBar,
    signal: SimulationSignal,
    gap_policy: GapPolicy,
) -> Tuple[bool, Optional[float], Optional[str]]:
    """
    Evaluates whether `signal` can enter on `bar` open.
    Returns `(should_enter, raw_entry_price, rejection_or_wait_reason)`.
    Note: caller distinguishes terminal gap rejection from wait expiration cleanly.
    """
    if not bar.is_complete:
        return False, None, "INCOMPLETE_BAR_REJECTED"

    if bar.open_time_ist < signal.signal_available_at_ist.astimezone(IST_ZONE):
        return False, None, "LOOKAHEAD_BLOCKED_PRE_SIGNAL_BAR"

    if signal.synthetic_bs_assumptions is not None:
        exp_ist = signal.synthetic_bs_assumptions.expiry_datetime_ist.astimezone(IST_ZONE)
        if bar.open_time_ist >= exp_ist:
            return False, None, "OPTION_EXPIRED_BEFORE_ENTRY"
        raw_entry = price_synthetic_bs_option(
            spot=bar.open,
            strike=signal.synthetic_bs_assumptions.strike_price,
            valuation_time_ist=bar.open_time_ist,
            expiry_datetime_ist=exp_ist,
            risk_free_rate=signal.synthetic_bs_assumptions.risk_free_rate,
            dividend_yield=signal.synthetic_bs_assumptions.dividend_yield,
            implied_volatility=signal.synthetic_bs_assumptions.implied_volatility,
            option_type=signal.synthetic_bs_assumptions.option_type,
        )
        if raw_entry <= 0.0:
            return False, None, "NON_POSITIVE_SYNTHETIC_OPTION_ENTRY_PREMIUM"
    else:
        raw_entry = bar.open

    # Adverse gap past SL at bar open prevents impossible fills
    check_price = raw_entry if signal.trigger_domain == TriggerPriceDomain.SYNTHETIC_OPTION_PREMIUM else bar.open
    is_pe_spot = (
        signal.trigger_domain == TriggerPriceDomain.UNDERLYING_POINTS
        and signal.synthetic_bs_assumptions is not None
        and signal.synthetic_bs_assumptions.option_type == "PE"
    )
    expect_up = (signal.direction == SignalDirection.LONG) and (not is_pe_spot)
    if expect_up and check_price <= signal.stop_loss:
        return False, None, f"GAP_PAST_STOP_LOSS_AT_ENTRY_OPEN ({check_price:.2f} <= {signal.stop_loss:.2f})"
    if (not expect_up) and check_price >= signal.stop_loss:
        return False, None, f"GAP_PAST_STOP_LOSS_AT_ENTRY_OPEN ({check_price:.2f} >= {signal.stop_loss:.2f})"

    if signal.entry_zone_min is not None and check_price < signal.entry_zone_min:
        reason = f"ENTRY_PRICE_BELOW_ZONE ({check_price:.2f} < {signal.entry_zone_min:.2f})"
        if gap_policy == GapPolicy.REJECT_ENTRY_ON_GAP:
            return False, None, f"GAP_REJECTED:{reason}"
        return False, None, f"WAIT:{reason}"

    if signal.entry_zone_max is not None and check_price > signal.entry_zone_max:
        reason = f"ENTRY_PRICE_ABOVE_ZONE ({check_price:.2f} > {signal.entry_zone_max:.2f})"
        if gap_policy == GapPolicy.REJECT_ENTRY_ON_GAP:
            return False, None, f"GAP_REJECTED:{reason}"
        return False, None, f"WAIT:{reason}"

    return True, float(raw_entry), None


@dataclass(frozen=True)
class ExitDecisionLeg:
    """Single deterministic exit action triggered on an active bar."""

    exit_fraction_type: str  # "PARTIAL" or "FULL"
    exit_reason: ExitReason
    raw_exit_price: float
    is_intrabar_ambiguous: bool = False
    ambiguity_evidence: Optional[IntrabarAmbiguityEvidence] = None


def evaluate_exit_triggers_on_bar(
    *,
    trade_id: str,
    bar: CompletedBar,
    is_entry_bar: bool,
    signal: SimulationSignal,
    remaining_qty: int,
    target_1_already_executed: bool,
    ambiguity_policy: AmbiguityPolicy,
    square_off_time: dt_time,
    is_last_bar_of_session: bool,
    is_last_bar_of_dataset: bool,
) -> List[ExitDecisionLeg]:
    """
    Evaluates exit events chronologically on bar `bar` for an open trade:
    1. Gap through stop-loss on post-entry bar open (`not is_entry_bar`)
    2. Intrabar SL and Target checks, triggering `INTRABAR_AMBIGUOUS` with conservative
       resolution whenever BOTH SL and any active target lie inside bar bounds
    3. Sequential partial Target 1 followed optionally by Target 2 inside clean bullish/bearish bars
    4. Synthetic expiry close or intraday EOD square-off
    """
    if remaining_qty <= 0:
        return []

    assumptions = signal.synthetic_bs_assumptions
    use_option_triggers = (
        assumptions is not None and signal.trigger_domain == TriggerPriceDomain.SYNTHETIC_OPTION_PREMIUM
    )

    if use_option_triggers:
        assert assumptions is not None
        opt_val = value_bar_option_bs(bar, assumptions)
        b_open = opt_val.v_open
        b_low = opt_val.v_low
        b_high = opt_val.v_high
        b_close = opt_val.v_close
    else:
        b_open = bar.open
        b_low = bar.low
        b_high = bar.high
        b_close = bar.close

    def _spot_to_exit_price(trigger_val: float, val_time: datetime) -> float:
        if assumptions is None:
            return float(trigger_val)
        if signal.trigger_domain == TriggerPriceDomain.SYNTHETIC_OPTION_PREMIUM:
            return float(trigger_val)
        return price_synthetic_bs_option(
            spot=float(trigger_val),
            strike=assumptions.strike_price,
            valuation_time_ist=val_time,
            expiry_datetime_ist=assumptions.expiry_datetime_ist,
            risk_free_rate=assumptions.risk_free_rate,
            dividend_yield=assumptions.dividend_yield,
            implied_volatility=assumptions.implied_volatility,
            option_type=assumptions.option_type,
        )

    is_pe_spot = (
        assumptions is not None
        and signal.trigger_domain == TriggerPriceDomain.UNDERLYING_POINTS
        and assumptions.option_type == "PE"
    )
    is_long = (signal.direction == SignalDirection.LONG) and (not is_pe_spot)
    sl = signal.stop_loss
    t1 = signal.target_1
    t2 = signal.target_2

    # 1. Check adverse gap-through-SL at post-entry bar open before intrabar range
    if not is_entry_bar:
        gap_sl = (b_open <= sl) if is_long else (b_open >= sl)
        if gap_sl:
            raw_px = b_open if use_option_triggers else _spot_to_exit_price(b_open, bar.open_time_ist)
            return [
                ExitDecisionLeg(
                    exit_fraction_type="FULL",
                    exit_reason=ExitReason.GAP_STOP_OUT,
                    raw_exit_price=raw_px,
                )
            ]

    # 2. Check intrabar range touches
    sl_touched = (b_low <= sl) if is_long else (b_high >= sl)
    t1_pending = not target_1_already_executed
    t1_touched = t1_pending and ((b_high >= t1) if is_long else (b_low <= t1))
    t2_touched = (t2 is not None) and ((b_high >= t2) if is_long else (b_low <= t2))
    any_active_target_touched = t1_touched or t2_touched

    if sl_touched and any_active_target_touched:
        touched_target = t1 if t1_touched else float(t2)  # type: ignore[arg-type]
        if ambiguity_policy == AmbiguityPolicy.MARK_AMBIGUOUS_WORST_CASE:
            worst_raw = min(sl, b_low, b_close) if is_long else max(sl, b_high, b_close)
            res_reason = ExitReason.INTRABAR_AMBIGUOUS_WORST_CASE
        else:
            # CONSERVATIVE_SL_FIRST_WITH_AMBIGUOUS_TAG or MARK_AMBIGUOUS_NO_FILL:
            # NEVER resolve optimistically in favor of targets; fill conservatively at SL.
            worst_raw = sl
            res_reason = ExitReason.INTRABAR_AMBIGUOUS_SL

        raw_px = worst_raw if use_option_triggers else _spot_to_exit_price(worst_raw, bar.close_time_ist)
        evidence = IntrabarAmbiguityEvidence(
            trade_id=trade_id,
            bar_open_ist=bar.open_time_ist.isoformat(),
            bar_close_ist=bar.close_time_ist.isoformat(),
            bar_open=float(bar.open),
            bar_high=float(bar.high),
            bar_low=float(bar.low),
            bar_close=float(bar.close),
            stop_loss_level=float(sl),
            target_level=float(touched_target),
            policy_applied=ambiguity_policy,
            resolved_exit_reason=res_reason,
            resolved_fill_price=float(raw_px),
            resolution_note=(
                f"INTRABAR_AMBIGUOUS: Completed OHLC bar spanned both SL ({sl}) and active target ({touched_target}); "
                f"applied conservative policy {ambiguity_policy.value}."
            ),
        )
        return [
            ExitDecisionLeg(
                exit_fraction_type="FULL",
                exit_reason=res_reason,
                raw_exit_price=raw_px,
                is_intrabar_ambiguous=True,
                ambiguity_evidence=evidence,
            )
        ]

    if sl_touched:
        raw_px = sl if use_option_triggers else _spot_to_exit_price(sl, bar.close_time_ist)
        return [
            ExitDecisionLeg(
                exit_fraction_type="FULL",
                exit_reason=ExitReason.STOP_LOSS,
                raw_exit_price=raw_px,
            )
        ]

    legs: List[ExitDecisionLeg] = []
    if t1_touched:
        # If gap open bypassed T1 favorably on non-entry bar, conservative/realistic trigger fills at max(T1, open) for LONG
        if not is_entry_bar and ((is_long and b_open > t1) or ((not is_long) and b_open < t1)):
            trig_t1 = b_open
            r_t1 = ExitReason.GAP_TARGET if t2 is None else ExitReason.TARGET_1
            t1_px = trig_t1 if use_option_triggers else _spot_to_exit_price(trig_t1, bar.open_time_ist)
        else:
            r_t1 = ExitReason.TARGET_1
            t1_px = t1 if use_option_triggers else _spot_to_exit_price(t1, bar.close_time_ist)

        legs.append(
            ExitDecisionLeg(
                exit_fraction_type="FULL" if t2 is None else "PARTIAL",
                exit_reason=r_t1,
                raw_exit_price=t1_px,
            )
        )
        if t2 is None:
            return legs

    if t2 is not None and t2_touched:
        if not is_entry_bar and ((is_long and b_open > t2) or ((not is_long) and b_open < t2)):
            t2_px = b_open if use_option_triggers else _spot_to_exit_price(b_open, bar.open_time_ist)
            r_t2 = ExitReason.GAP_TARGET
        else:
            t2_px = t2 if use_option_triggers else _spot_to_exit_price(t2, bar.close_time_ist)
            r_t2 = ExitReason.TARGET_2
        legs.append(
            ExitDecisionLeg(
                exit_fraction_type="FULL",
                exit_reason=r_t2,
                raw_exit_price=t2_px,
            )
        )
        return legs

    if legs:
        # Partial Target 1 executed; remaining quantity carries unless EOD/expiry below
        pass

    # 3. Mode B option expiry close or intraday session square-off
    if assumptions is not None:
        exp_ist = assumptions.expiry_datetime_ist.astimezone(IST_ZONE)
        if bar.close_time_ist >= exp_ist:
            legs.append(
                ExitDecisionLeg(
                    exit_fraction_type="FULL",
                    exit_reason=ExitReason.EXPIRY_CLOSE,
                    raw_exit_price=b_close if use_option_triggers else _spot_to_exit_price(bar.close, bar.close_time_ist),
                )
            )
            return legs

    if signal.intraday_square_off and (bar.close_time_ist.time() >= square_off_time or is_last_bar_of_session):
        legs.append(
            ExitDecisionLeg(
                exit_fraction_type="FULL",
                exit_reason=ExitReason.EOD_SQUARE_OFF,
                raw_exit_price=b_close if use_option_triggers else _spot_to_exit_price(bar.close, bar.close_time_ist),
            )
        )
        return legs

    if is_last_bar_of_dataset and not legs:
        legs.append(
            ExitDecisionLeg(
                exit_fraction_type="FULL",
                exit_reason=ExitReason.END_OF_DATA,
                raw_exit_price=b_close if use_option_triggers else _spot_to_exit_price(bar.close, bar.close_time_ist),
            )
        )
    return legs


def mark_to_market_price_on_bar(
    *,
    bar: CompletedBar,
    signal: SimulationSignal,
) -> float:
    """Computes current mark-to-market unit price at completed bar close."""
    assumptions = signal.synthetic_bs_assumptions
    if assumptions is None:
        return float(bar.close)
    return price_synthetic_bs_option(
        spot=float(bar.close),
        strike=assumptions.strike_price,
        valuation_time_ist=bar.close_time_ist,
        expiry_datetime_ist=assumptions.expiry_datetime_ist,
        risk_free_rate=assumptions.risk_free_rate,
        dividend_yield=assumptions.dividend_yield,
        implied_volatility=assumptions.implied_volatility,
        option_type=assumptions.option_type,
    )
