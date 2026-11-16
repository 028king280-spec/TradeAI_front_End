"""
AIVOLVE Quantitative Institutional Trading Architecture v3.0
Phase 3 Step 3.3 — Order Block Detection & Lifecycle Engine.

Deterministic, point-in-time detection and lifecycle management of institutional
Bullish and Bearish Order Blocks anchored to confirmed structural breaks (BOS/CHoCH/MSS).

Key Invariants:
1. Origin Candle Selection: Identifies the last qualifying opposing candle(s) preceding
   a confirmed structural breakout / displacement leg.
2. Zone Boundaries: Configurable Full-Range (wick-to-wick) or Body-Only (open-to-close).
   Mean threshold (50% Consequent Encroachment) computed deterministically.
3. Strict Lifecycle State Machine:
   IDENTIFIED -> CONFIRMED -> APPROACHING -> PARTIALLY_MITIGATED -> MITIGATED
   Terminal states: MITIGATED, INVALIDATED, EXPIRED.
4. Mitigation vs. Invalidation Separation:
   - Mitigation: Price traversing the configured mitigation depth into the order block zone.
   - Invalidation: Completed candle closing beyond the configured invalidation boundary.
5. Immutability & Anti-Lookahead:
   - event_time = origin candle timestamp (footprint printing).
   - available_at = break candle completion timestamp (confirmation delay).
   - confirmed_at remains immutable even when subsequently mitigated or invalidated.
   - Point-in-time filtering via as_of_time.
6. Fail-Closed Data Quality: Rejects STALE, DEGRADED, REPAIRED, and invalid OHLC geometries.
7. Strictly PAPER TRADING ONLY.
"""

from typing import Dict, Any, List, Optional, Tuple, Set
from datetime import datetime, timezone
import zoneinfo
import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from app.options.ict_smc.ict_models import (
    ICTEvent,
    ICTEventType,
    EventDirection,
    LiquidityLifecycleState,
    OrderBlockBoundaryType,
    OriginCandleSelectionPolicy,
    OrderBlockEvidence,
    OrderBlockEvent,
    OrderBlockConfiguration,
    generate_deterministic_event_id,
    validate_order_block_transition,
    IST_ZONE,
)
from app.options.ict_smc.market_structure import (
    MarketStructureEngine,
    TimeframeStructureReport,
    DISQUALIFYING_FEED_STATUSES,
    VALID_FEED_STATUSES,
    _ensure_timezone_aware,
)


class TimeframeOrderBlockReport(BaseModel):
    """
    Structured report containing point-in-time Order Block intelligence for a specific timeframe.
    """
    index: str
    timeframe: str
    data_quality: str
    order_block_events: List[ICTEvent] = Field(default_factory=list)
    active_order_blocks: List[ICTEvent] = Field(default_factory=list)
    mitigated_order_blocks: List[ICTEvent] = Field(default_factory=list)
    invalidated_order_blocks: List[ICTEvent] = Field(default_factory=list)
    latest_bullish_ob: Optional[ICTEvent] = None
    latest_bearish_ob: Optional[ICTEvent] = None
    as_of_time: Optional[datetime] = None
    configuration_version: str = "3.3.0"
    engine_version: str = "3.3.0"


class OrderBlockEngine:
    """
    Production-grade institutional Order Block detection and lifecycle engine.
    """

    def __init__(
        self,
        config: Optional[OrderBlockConfiguration] = None,
        market_structure_engine: Optional[MarketStructureEngine] = None,
    ):
        self.config = config or OrderBlockConfiguration()
        if market_structure_engine is not None:
            self.market_structure_engine = market_structure_engine
        else:
            from app.options.ict_smc.ict_models import MarketStructureConfiguration
            ms_cfg = MarketStructureConfiguration(
                swing_left_bars=self.config.swing_left_bars,
                swing_right_bars=self.config.swing_right_bars,
            )
            self.market_structure_engine = MarketStructureEngine(config=ms_cfg)

    @staticmethod
    def _validate_input_quality(
        df: pd.DataFrame,
        data_quality_status: str,
    ) -> None:
        """
        Validates feed status, repair metadata, and OHLC geometric invariants.
        Fails closed on any corruption, synthetic injection, or geometrical inconsistency.
        """
        status_clean = str(data_quality_status).upper().strip()
        if status_clean in DISQUALIFYING_FEED_STATUSES or status_clean not in VALID_FEED_STATUSES:
            raise ValueError(
                f"Order block detection locked out: feed quality status '{data_quality_status}' "
                f"is not verified live."
            )

        if df is None or df.empty:
            return

        if hasattr(df, "attrs") and df.attrs:
            if df.attrs.get("quality_status") == "REPAIRED" or df.attrs.get("imputed_bars_count", 0) > 0:
                raise ValueError(
                    "Order block detection locked out: input series contains repaired or imputed mandatory candles."
                )

        req_cols = {"open", "high", "low", "close"}
        missing_cols = req_cols - set(df.columns)
        if missing_cols:
            raise ValueError(f"Missing mandatory OHLC columns: {missing_cols}")

        if "timestamp" in df.columns:
            ts_series = df["timestamp"]
            if ts_series.isnull().any():
                raise ValueError("DataFrame contains null values in mandatory 'timestamp' column.")

            tz_set: Set[str] = set()
            for ts_val in ts_series.dropna():
                dt_aware = _ensure_timezone_aware(ts_val)
                tz_name = dt_aware.tzname() or str(dt_aware.tzinfo)
                tz_set.add(tz_name)
            if len(tz_set) > 1:
                raise ValueError(f"Mixed timezones detected in timestamp series: {tz_set}")

        opens = pd.to_numeric(df["open"], errors="coerce")
        highs = pd.to_numeric(df["high"], errors="coerce")
        lows = pd.to_numeric(df["low"], errors="coerce")
        closes = pd.to_numeric(df["close"], errors="coerce")

        if opens.isnull().any() or highs.isnull().any() or lows.isnull().any() or closes.isnull().any():
            raise ValueError("Non-numeric or NaN values present in mandatory OHLC price series.")

        if (opens <= 0).any() or (highs <= 0).any() or (lows <= 0).any() or (closes <= 0).any():
            raise ValueError("Non-positive price values detected in OHLC price series.")

        if (highs.values < lows.values).any():
            raise ValueError("OHLC invariant violated: high < low")

        max_oc = np.maximum(opens.values, closes.values)
        if (highs.values < max_oc - 1e-6).any():
            raise ValueError("OHLC invariant violated: high < max(open, close)")

        min_oc = np.minimum(opens.values, closes.values)
        if (lows.values > min_oc + 1e-6).any():
            raise ValueError("OHLC invariant violated: low > min(open, close)")

    @staticmethod
    def _compute_atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> np.ndarray:
        """Calculates 14-period True Range / ATR array."""
        n = len(highs)
        tr = np.zeros(n, dtype=float)
        for i in range(n):
            if i == 0:
                tr[i] = highs[i] - lows[i]
            else:
                tr[i] = max(
                    highs[i] - lows[i],
                    abs(highs[i] - closes[i - 1]),
                    abs(lows[i] - closes[i - 1]),
                )

        atr = np.zeros(n, dtype=float)
        if n >= period:
            atr[period - 1] = np.mean(tr[:period])
            for i in range(period, n):
                atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
            for i in range(period - 1):
                atr[i] = atr[period - 1]
        else:
            atr[:] = np.mean(tr) if n > 0 else 1.0
        return atr

    def detect_order_blocks(
        self,
        df: pd.DataFrame,
        structure_events: Optional[List[ICTEvent]] = None,
        symbol: str = "NIFTY 50",
        timeframe: str = "15m",
        as_of_time: Optional[datetime] = None,
        data_quality_status: str = "VERIFIED_LIVE",
    ) -> Tuple[List[OrderBlockEvent], List[ICTEvent]]:
        """
        Detects qualifying Bullish and Bearish Order Blocks anchored to confirmed structural breaks,
        and evaluates their mitigation and invalidation lifecycle up to as_of_time.
        """
        # 1. Quality & safety validation
        self._validate_input_quality(df=df, data_quality_status=data_quality_status)

        if df is None or df.empty or len(df) < 3:
            return [], []

        # 2. Point-in-time filtering
        as_of_dt = _ensure_timezone_aware(as_of_time) if as_of_time is not None else None
        work_df = df.copy()
        if as_of_dt is not None:
            work_df = work_df[work_df["timestamp"] <= as_of_dt].reset_index(drop=True)
            if work_df.empty or len(work_df) < 3:
                return [], []

        # Ensure lookback limit
        if len(work_df) > self.config.lookback_candles:
            work_df = work_df.iloc[-self.config.lookback_candles:].reset_index(drop=True)

        n = len(work_df)
        c_open = work_df["open"].values.astype(float)
        c_high = work_df["high"].values.astype(float)
        c_low = work_df["low"].values.astype(float)
        c_close = work_df["close"].values.astype(float)
        c_ts = [_ensure_timezone_aware(t) for t in work_df["timestamp"]]
        c_ids = [
            str(work_df.iloc[i].get("candle_id", c_ts[i].isoformat()))
            for i in range(n)
        ]

        # 3. Obtain confirming structural breaks (BOS, CHoCH, MSS)
        if structure_events is None:
            _, detected_events, _ = self.market_structure_engine.detect_structure_breaks(
                df=work_df,
                symbol=symbol,
                timeframe=timeframe,
                as_of_time=as_of_dt,
                data_quality_status=data_quality_status,
            )
            structure_events = detected_events

        # Filter to confirmed structural break events
        valid_break_types = {ICTEventType.BOS, ICTEventType.CHOCH, ICTEventType.MSS}
        breaks = [
            ev for ev in structure_events
            if ev.event_type in valid_break_types and ev.timeframe.lower() == timeframe.lower()
        ]

        if not breaks:
            return [], []

        # 4. Compute ATR for displacement assessment
        atr_arr = self._compute_atr(c_high, c_low, c_close, period=14)

        # 5. Build candle timestamp lookup
        ts_to_idx = {c_ts[i]: i for i in range(n)}
        cid_to_idx = {c_ids[i]: i for i in range(n)}

        typed_events: List[OrderBlockEvent] = []
        emitted_ob_keys: Set[str] = set()

        # Iterate over confirming structural breaks
        for s_event in breaks:
            break_time = s_event.available_at or s_event.event_time
            break_idx = ts_to_idx.get(break_time)

            if break_idx is None:
                # Try finding via break_candle_id in evidence
                ev_evidence = s_event.evidence if isinstance(s_event.evidence, dict) else {}
                bc_id = ev_evidence.get("break_candle_id")
                if bc_id and bc_id in cid_to_idx:
                    break_idx = cid_to_idx[bc_id]

            if break_idx is None or break_idx < 1:
                continue

            ev_evidence = s_event.evidence if isinstance(s_event.evidence, dict) else {}
            is_mss = s_event.event_type == ICTEventType.MSS or ev_evidence.get("displacement_confirmed", False)

            # -------------------------------------------------------------
            # A. Bullish Order Block (Preceding a Bullish Break)
            # -------------------------------------------------------------
            if s_event.direction == EventDirection.BULLISH:
                # Find origin bearish candle(s) preceding the upward thrust
                lookback_start = max(0, break_idx - 25)
                sub_lows = c_low[lookback_start:break_idx]
                if len(sub_lows) == 0:
                    continue

                min_rel_idx = int(np.argmin(sub_lows))
                lowest_idx = lookback_start + min_rel_idx

                # Identify origin candle based on selection policy
                origin_indices: List[int] = []
                policy = self.config.selection_policy.upper().strip()

                if policy == "EXTREME_CANDLE":
                    origin_indices = [lowest_idx]
                elif policy == "CONSECUTIVE_CLUSTER":
                    curr = lowest_idx
                    while curr >= lookback_start and c_close[curr] < c_open[curr]:
                        origin_indices.append(curr)
                        curr -= 1
                    if not origin_indices:
                        for j in range(break_idx - 1, lookback_start - 1, -1):
                            if c_close[j] < c_open[j]:
                                origin_indices = [j]
                                break
                    if not origin_indices:
                        origin_indices = [lowest_idx]
                else:
                    # Default: LAST_CANDLE
                    found = False
                    for j in range(break_idx - 1, lookback_start - 1, -1):
                        if c_close[j] < c_open[j]:
                            origin_indices = [j]
                            found = True
                            break
                    if not found:
                        origin_indices = [lowest_idx]

                main_origin_idx = origin_indices[0]
                origin_c_id = c_ids[main_origin_idx]
                origin_time = c_ts[main_origin_idx]

                # Displacement leg is strictly AFTER the origin candle: (main_origin_idx + 1 to break_idx)
                # The origin candle itself cannot independently qualify the displacement requirement.
                leg_indices = list(range(main_origin_idx + 1, break_idx + 1))
                if not leg_indices:
                    continue

                # Evaluate displacement across the displacement leg
                qualifying_disp_idx = break_idx
                disp_body_ratio = 0.0
                disp_atr_mult = 0.0
                has_displacement = is_mss

                # 1. Check breakout candle
                break_body = abs(c_close[break_idx] - c_open[break_idx])
                break_range = max(0.01, c_high[break_idx] - c_low[break_idx])
                b_ratio = round(break_body / break_range, 4)
                cur_atr = max(0.01, atr_arr[break_idx])
                b_atr_mult = round(break_range / cur_atr, 2)
                disp_body_ratio = b_ratio
                disp_atr_mult = b_atr_mult

                if (
                    b_ratio >= self.config.min_displacement_body_ratio
                    and break_range >= self.config.min_displacement_atr_multiple * cur_atr
                    and c_close[break_idx] > c_open[break_idx]
                ):
                    has_displacement = True
                    qualifying_disp_idx = break_idx

                # 2. Check any impulse candle strictly within the displacement leg
                if not has_displacement:
                    for k in leg_indices:
                        if c_close[k] > c_open[k]:
                            k_body = abs(c_close[k] - c_open[k])
                            k_range = max(0.01, c_high[k] - c_low[k])
                            k_ratio = round(k_body / k_range, 4)
                            k_atr = max(0.01, atr_arr[k])
                            if (
                                k_ratio >= self.config.min_displacement_body_ratio
                                and k_range >= self.config.min_displacement_atr_multiple * k_atr
                            ):
                                has_displacement = True
                                qualifying_disp_idx = k
                                disp_body_ratio = k_ratio
                                disp_atr_mult = round(k_range / k_atr, 2)
                                break

                # 3. Check cumulative multi-candle displacement leg if permitted
                if not has_displacement and self.config.allow_multi_candle_displacement and len(leg_indices) > 1:
                    # Mandatory directional validation: Bullish cumulative displacement requires close_k > open_(i+1)
                    if c_close[break_idx] > c_open[leg_indices[0]]:
                        cum_progress = c_close[break_idx] - c_open[leg_indices[0]]
                        cum_high = max(c_high[i] for i in leg_indices)
                        cum_low = min(c_low[i] for i in leg_indices)
                        cum_range = max(0.01, cum_high - cum_low)
                        cum_ratio = round(cum_progress / cum_range, 4)
                        cum_atr_mult = round(cum_range / cur_atr, 2)
                        if (
                            cum_ratio >= self.config.min_displacement_body_ratio
                            and cum_range >= self.config.min_displacement_atr_multiple * cur_atr
                        ):
                            has_displacement = True
                            qualifying_disp_idx = break_idx
                            disp_body_ratio = cum_ratio
                            disp_atr_mult = cum_atr_mult

                if self.config.require_displacement and not has_displacement:
                    continue

                disp_c_id = c_ids[qualifying_disp_idx]

                # Determine zone boundaries
                if self.config.boundary_type.upper().strip() == "BODY_ONLY":
                    zone_h = max(c_open[main_origin_idx], c_close[main_origin_idx])
                    zone_l = min(c_open[main_origin_idx], c_close[main_origin_idx])
                else:
                    # FULL_RANGE (across all cluster candles if multiple)
                    zone_h = float(max(c_high[i] for i in origin_indices))
                    zone_l = float(min(c_low[i] for i in origin_indices))

                mean_thresh = round((zone_h + zone_l) / 2.0, 2)
                body_h = float(max(c_open[main_origin_idx], c_close[main_origin_idx]))
                body_l = float(min(c_open[main_origin_idx], c_close[main_origin_idx]))

                # Check overlap deduplication against existing unmitigated bullish OBs
                overlap_key = f"{symbol}_{timeframe}_BULLISH_{round(zone_h, 1)}_{round(zone_l, 1)}"
                if overlap_key in emitted_ob_keys:
                    continue

                is_duplicate = False
                for existing in typed_events:
                    if existing.direction == EventDirection.BULLISH and existing.event_status == LiquidityLifecycleState.CONFIRMED:
                        ex_h, ex_l = existing.zone_high, existing.zone_low
                        inter = max(0.0, min(zone_h, ex_h) - max(zone_l, ex_l))
                        union = max(zone_h, ex_h) - min(zone_l, ex_l)
                        iou = inter / union if union > 0 else 0.0
                        if iou >= self.config.max_zone_overlap_pct:
                            if self.config.overlap_dedup_policy.upper() == "KEEP_FIRST":
                                is_duplicate = True
                                break

                if is_duplicate:
                    continue

                emitted_ob_keys.add(overlap_key)

                ob_id = generate_deterministic_event_id(
                    index=symbol,
                    timeframe=timeframe,
                    event_type="OBK",
                    source_candle_id=f"{origin_c_id}_{c_ids[break_idx]}",
                    configuration_version=self.config.configuration_version,
                )

                evidence = OrderBlockEvidence(
                    zone_high=round(zone_h, 2),
                    zone_low=round(zone_l, 2),
                    mean_threshold=mean_thresh,
                    body_high=round(body_h, 2),
                    body_low=round(body_l, 2),
                    boundary_type=self.config.boundary_type.upper().strip(),
                    origin_candle_id=origin_c_id,
                    origin_candle_time=origin_time,
                    origin_candle_open=round(c_open[main_origin_idx], 2),
                    origin_candle_high=round(c_high[main_origin_idx], 2),
                    origin_candle_low=round(c_low[main_origin_idx], 2),
                    origin_candle_close=round(c_close[main_origin_idx], 2),
                    displacement_candle_id=disp_c_id,
                    displacement_leg_candle_count=len(leg_indices),
                    source_structure_event_id=s_event.event_id,
                    source_structure_type=s_event.event_type.value,
                    displacement_body_ratio=disp_body_ratio,
                    displacement_atr_multiple=disp_atr_mult,
                    mitigation_percentage=0.0,
                    mitigated_at=None,
                    invalidation_condition=f"Completed candle close < {round(zone_l - self.config.invalidation_buffer_pts, 2)}",
                    invalidation_reason=None,
                    touch_count=0,
                    selection_policy=self.config.selection_policy.upper().strip(),
                    opposing_candle_count=len(origin_indices),
                )

                ob_event = OrderBlockEvent(
                    event_id=ob_id,
                    index=symbol.upper().strip(),
                    event_type=ICTEventType.ORDER_BLOCK,
                    direction=EventDirection.BULLISH,
                    timeframe=timeframe.lower().strip(),
                    zone_high=round(zone_h, 2),
                    zone_low=round(zone_l, 2),
                    mean_threshold=mean_thresh,
                    event_status=LiquidityLifecycleState.CONFIRMED,
                    event_time=origin_time,
                    available_at=c_ts[break_idx],
                    created_at=c_ts[break_idx],
                    confirmed_at=c_ts[break_idx],
                    source_candle_identifiers=[origin_c_id, c_ids[break_idx]],
                    data_quality=data_quality_status,
                    evidence=evidence,
                    configuration_version=self.config.configuration_version,
                    engine_version=self.config.engine_version,
                )
                typed_events.append(ob_event)

            # -------------------------------------------------------------
            # B. Bearish Order Block (Preceding a Bearish Break)
            # -------------------------------------------------------------
            elif s_event.direction == EventDirection.BEARISH:
                lookback_start = max(0, break_idx - 25)
                sub_highs = c_high[lookback_start:break_idx]
                if len(sub_highs) == 0:
                    continue

                max_rel_idx = int(np.argmax(sub_highs))
                highest_idx = lookback_start + max_rel_idx

                origin_indices: List[int] = []
                policy = self.config.selection_policy.upper().strip()

                if policy == "EXTREME_CANDLE":
                    origin_indices = [highest_idx]
                elif policy == "CONSECUTIVE_CLUSTER":
                    curr = highest_idx
                    while curr >= lookback_start and c_close[curr] > c_open[curr]:
                        origin_indices.append(curr)
                        curr -= 1
                    if not origin_indices:
                        for j in range(break_idx - 1, lookback_start - 1, -1):
                            if c_close[j] > c_open[j]:
                                origin_indices = [j]
                                break
                    if not origin_indices:
                        origin_indices = [highest_idx]
                else:
                    # Default: LAST_CANDLE
                    found = False
                    for j in range(break_idx - 1, lookback_start - 1, -1):
                        if c_close[j] > c_open[j]:
                            origin_indices = [j]
                            found = True
                            break
                    if not found:
                        origin_indices = [highest_idx]

                main_origin_idx = origin_indices[0]
                origin_c_id = c_ids[main_origin_idx]
                origin_time = c_ts[main_origin_idx]

                # Displacement leg is strictly AFTER the origin candle: (main_origin_idx + 1 to break_idx)
                # The origin candle itself cannot independently qualify the displacement requirement.
                leg_indices = list(range(main_origin_idx + 1, break_idx + 1))
                if not leg_indices:
                    continue

                # Evaluate displacement across the displacement leg
                qualifying_disp_idx = break_idx
                disp_body_ratio = 0.0
                disp_atr_mult = 0.0
                has_displacement = is_mss

                # 1. Check breakout candle
                break_body = abs(c_close[break_idx] - c_open[break_idx])
                break_range = max(0.01, c_high[break_idx] - c_low[break_idx])
                b_ratio = round(break_body / break_range, 4)
                cur_atr = max(0.01, atr_arr[break_idx])
                b_atr_mult = round(break_range / cur_atr, 2)
                disp_body_ratio = b_ratio
                disp_atr_mult = b_atr_mult

                if (
                    b_ratio >= self.config.min_displacement_body_ratio
                    and break_range >= self.config.min_displacement_atr_multiple * cur_atr
                    and c_close[break_idx] < c_open[break_idx]
                ):
                    has_displacement = True
                    qualifying_disp_idx = break_idx

                # 2. Check any impulse candle strictly within the displacement leg
                if not has_displacement:
                    for k in leg_indices:
                        if c_close[k] < c_open[k]:
                            k_body = abs(c_close[k] - c_open[k])
                            k_range = max(0.01, c_high[k] - c_low[k])
                            k_ratio = round(k_body / k_range, 4)
                            k_atr = max(0.01, atr_arr[k])
                            if (
                                k_ratio >= self.config.min_displacement_body_ratio
                                and k_range >= self.config.min_displacement_atr_multiple * k_atr
                            ):
                                has_displacement = True
                                qualifying_disp_idx = k
                                disp_body_ratio = k_ratio
                                disp_atr_mult = round(k_range / k_atr, 2)
                                break

                # 3. Check cumulative multi-candle displacement leg if permitted
                if not has_displacement and self.config.allow_multi_candle_displacement and len(leg_indices) > 1:
                    # Mandatory directional validation: Bearish cumulative displacement requires close_k < open_(i+1)
                    if c_close[break_idx] < c_open[leg_indices[0]]:
                        cum_progress = c_open[leg_indices[0]] - c_close[break_idx]
                        cum_high = max(c_high[i] for i in leg_indices)
                        cum_low = min(c_low[i] for i in leg_indices)
                        cum_range = max(0.01, cum_high - cum_low)
                        cum_ratio = round(cum_progress / cum_range, 4)
                        cum_atr_mult = round(cum_range / cur_atr, 2)
                        if (
                            cum_ratio >= self.config.min_displacement_body_ratio
                            and cum_range >= self.config.min_displacement_atr_multiple * cur_atr
                        ):
                            has_displacement = True
                            qualifying_disp_idx = break_idx
                            disp_body_ratio = cum_ratio
                            disp_atr_mult = cum_atr_mult

                if self.config.require_displacement and not has_displacement:
                    continue

                disp_c_id = c_ids[qualifying_disp_idx]

                if self.config.boundary_type.upper().strip() == "BODY_ONLY":
                    zone_h = max(c_open[main_origin_idx], c_close[main_origin_idx])
                    zone_l = min(c_open[main_origin_idx], c_close[main_origin_idx])
                else:
                    zone_h = float(max(c_high[i] for i in origin_indices))
                    zone_l = float(min(c_low[i] for i in origin_indices))

                mean_thresh = round((zone_h + zone_l) / 2.0, 2)
                body_h = float(max(c_open[main_origin_idx], c_close[main_origin_idx]))
                body_l = float(min(c_open[main_origin_idx], c_close[main_origin_idx]))

                overlap_key = f"{symbol}_{timeframe}_BEARISH_{round(zone_h, 1)}_{round(zone_l, 1)}"
                if overlap_key in emitted_ob_keys:
                    continue

                is_duplicate = False
                for existing in typed_events:
                    if existing.direction == EventDirection.BEARISH and existing.event_status == LiquidityLifecycleState.CONFIRMED:
                        ex_h, ex_l = existing.zone_high, existing.zone_low
                        inter = max(0.0, min(zone_h, ex_h) - max(zone_l, ex_l))
                        union = max(zone_h, ex_h) - min(zone_l, ex_l)
                        iou = inter / union if union > 0 else 0.0
                        if iou >= self.config.max_zone_overlap_pct:
                            if self.config.overlap_dedup_policy.upper() == "KEEP_FIRST":
                                is_duplicate = True
                                break

                if is_duplicate:
                    continue

                emitted_ob_keys.add(overlap_key)

                ob_id = generate_deterministic_event_id(
                    index=symbol,
                    timeframe=timeframe,
                    event_type="OBK",
                    source_candle_id=f"{origin_c_id}_{c_ids[break_idx]}",
                    configuration_version=self.config.configuration_version,
                )

                evidence = OrderBlockEvidence(
                    zone_high=round(zone_h, 2),
                    zone_low=round(zone_l, 2),
                    mean_threshold=mean_thresh,
                    body_high=round(body_h, 2),
                    body_low=round(body_l, 2),
                    boundary_type=self.config.boundary_type.upper().strip(),
                    origin_candle_id=origin_c_id,
                    origin_candle_time=origin_time,
                    origin_candle_open=round(c_open[main_origin_idx], 2),
                    origin_candle_high=round(c_high[main_origin_idx], 2),
                    origin_candle_low=round(c_low[main_origin_idx], 2),
                    origin_candle_close=round(c_close[main_origin_idx], 2),
                    displacement_candle_id=disp_c_id,
                    displacement_leg_candle_count=len(leg_indices),
                    source_structure_event_id=s_event.event_id,
                    source_structure_type=s_event.event_type.value,
                    displacement_body_ratio=disp_body_ratio,
                    displacement_atr_multiple=disp_atr_mult,
                    mitigation_percentage=0.0,
                    mitigated_at=None,
                    invalidation_condition=f"Completed candle close > {round(zone_h + self.config.invalidation_buffer_pts, 2)}",
                    invalidation_reason=None,
                    touch_count=0,
                    selection_policy=self.config.selection_policy.upper().strip(),
                    opposing_candle_count=len(origin_indices),
                )

                ob_event = OrderBlockEvent(
                    event_id=ob_id,
                    index=symbol.upper().strip(),
                    event_type=ICTEventType.ORDER_BLOCK,
                    direction=EventDirection.BEARISH,
                    timeframe=timeframe.lower().strip(),
                    zone_high=round(zone_h, 2),
                    zone_low=round(zone_l, 2),
                    mean_threshold=mean_thresh,
                    event_status=LiquidityLifecycleState.CONFIRMED,
                    event_time=origin_time,
                    available_at=c_ts[break_idx],
                    created_at=c_ts[break_idx],
                    confirmed_at=c_ts[break_idx],
                    source_candle_identifiers=[origin_c_id, c_ids[break_idx]],
                    data_quality=data_quality_status,
                    evidence=evidence,
                    configuration_version=self.config.configuration_version,
                    engine_version=self.config.engine_version,
                )
                typed_events.append(ob_event)

        # -----------------------------------------------------------------
        # 6. Evaluate Lifecycle Progression across Subsequent Candles
        # -----------------------------------------------------------------
        # For each candle m in the dataset, update lifecycle of OBs confirmed before m
        for m in range(n):
            dt_m = c_ts[m]
            bar_o = c_open[m]
            bar_h = c_high[m]
            bar_l = c_low[m]
            bar_c = c_close[m]

            for ob in typed_events:
                # Only evaluate after confirmation candle
                if ob.available_at >= dt_m:
                    continue

                # Once in terminal state, immutability applies
                if ob.event_status in (
                    LiquidityLifecycleState.MITIGATED,
                    LiquidityLifecycleState.INVALIDATED,
                    LiquidityLifecycleState.EXPIRED,
                ):
                    continue

                zh = ob.zone_high
                zl = ob.zone_low
                mean_t = ob.mean_threshold
                span = max(0.01, zh - zl)

                # Bullish Order Block Lifecycle Check
                if ob.direction == EventDirection.BULLISH:
                    # Precedence Rule 1: Invalidation on completed candle close takes strict precedence over mitigation.
                    if self.config.enable_invalidation_tracking and bar_c < (zl - self.config.invalidation_buffer_pts):
                        ob.event_status = LiquidityLifecycleState.INVALIDATED
                        ob.invalidated_at = dt_m
                        ob.evidence.invalidation_reason = (
                            f"Completed candle closed below zone low {zl} at {bar_c}"
                        )
                        continue

                    # Mitigation: wick strictly enters zone interior (low < zone_high)
                    if bar_l < zh:
                        ob.evidence.touch_count += 1
                        pen_depth = zh - max(zl, bar_l)
                        depth_pct = round(min(100.0, max(0.0, (pen_depth / span) * 100.0)), 2)
                        ob.evidence.mitigation_percentage = max(ob.evidence.mitigation_percentage, depth_pct)

                        is_full = (
                            depth_pct >= self.config.full_mitigation_threshold_pct
                            or (self.config.full_mitigation_requires_mean_threshold and bar_l <= mean_t)
                            or bar_l <= zl
                        )

                        if is_full:
                            ob.event_status = LiquidityLifecycleState.MITIGATED
                            ob.evidence.mitigated_at = dt_m
                        else:
                            ob.event_status = LiquidityLifecycleState.PARTIALLY_MITIGATED
                    elif bar_l == zh:
                        # Boundary touch exactly at 0% penetration: touch count increments, no partial mitigation
                        ob.evidence.touch_count += 1
                        ob.event_status = LiquidityLifecycleState.APPROACHING
                    else:
                        # Approaching check (bar_l > zh)
                        app_bound = zh * (1.0 + self.config.approach_threshold_pct)
                        if bar_l <= app_bound:
                            ob.event_status = LiquidityLifecycleState.APPROACHING
                        elif ob.event_status == LiquidityLifecycleState.APPROACHING:
                            # Retreat check
                            retreat_bound = zh * (1.0 + self.config.approach_threshold_pct * self.config.approach_retreat_mult)
                            if bar_l > retreat_bound:
                                ob.event_status = LiquidityLifecycleState.CONFIRMED

                # Bearish Order Block Lifecycle Check
                elif ob.direction == EventDirection.BEARISH:
                    # Precedence Rule 1: Invalidation on completed candle close takes strict precedence over mitigation.
                    if self.config.enable_invalidation_tracking and bar_c > (zh + self.config.invalidation_buffer_pts):
                        ob.event_status = LiquidityLifecycleState.INVALIDATED
                        ob.invalidated_at = dt_m
                        ob.evidence.invalidation_reason = (
                            f"Completed candle closed above zone high {zh} at {bar_c}"
                        )
                        continue

                    # Mitigation: wick strictly enters zone interior (high > zone_low)
                    if bar_h > zl:
                        ob.evidence.touch_count += 1
                        pen_depth = min(zh, bar_h) - zl
                        depth_pct = round(min(100.0, max(0.0, (pen_depth / span) * 100.0)), 2)
                        ob.evidence.mitigation_percentage = max(ob.evidence.mitigation_percentage, depth_pct)

                        is_full = (
                            depth_pct >= self.config.full_mitigation_threshold_pct
                            or (self.config.full_mitigation_requires_mean_threshold and bar_h >= mean_t)
                            or bar_h >= zh
                        )

                        if is_full:
                            ob.event_status = LiquidityLifecycleState.MITIGATED
                            ob.evidence.mitigated_at = dt_m
                        else:
                            ob.event_status = LiquidityLifecycleState.PARTIALLY_MITIGATED
                    elif bar_h == zl:
                        # Boundary touch exactly at 0% penetration: touch count increments, no partial mitigation
                        ob.evidence.touch_count += 1
                        ob.event_status = LiquidityLifecycleState.APPROACHING
                    else:
                        # Approaching check (bar_h < zl)
                        app_bound = zl * (1.0 - self.config.approach_threshold_pct)
                        if bar_h >= app_bound:
                            ob.event_status = LiquidityLifecycleState.APPROACHING
                        elif ob.event_status == LiquidityLifecycleState.APPROACHING:
                            retreat_bound = zl * (1.0 - self.config.approach_threshold_pct * self.config.approach_retreat_mult)
                            if bar_h < retreat_bound:
                                ob.event_status = LiquidityLifecycleState.CONFIRMED

                # Expiry check across all active states (age >= max_active_candles)
                ob_conf_idx = ts_to_idx.get(ob.available_at, 0)
                if (m - ob_conf_idx) >= self.config.max_active_candles:
                    ob.event_status = LiquidityLifecycleState.EXPIRED

        # Convert to canonical 17-field ICTEvent models
        canonical_events = [ob.to_ict_event() for ob in typed_events]
        return typed_events, canonical_events

    def analyze_timeframe(
        self,
        df: pd.DataFrame,
        structure_events: Optional[List[ICTEvent]] = None,
        symbol: str = "NIFTY 50",
        timeframe: str = "15m",
        as_of_time: Optional[datetime] = None,
        data_quality_status: str = "VERIFIED_LIVE",
    ) -> TimeframeOrderBlockReport:
        """
        Executes complete point-in-time Order Block analysis and produces structured TimeframeOrderBlockReport.
        """
        typed_obs, canonical_obs = self.detect_order_blocks(
            df=df,
            structure_events=structure_events,
            symbol=symbol,
            timeframe=timeframe,
            as_of_time=as_of_time,
            data_quality_status=data_quality_status,
        )

        active = [
            ev for ev in canonical_obs
            if ev.event_status in (
                LiquidityLifecycleState.CONFIRMED,
                LiquidityLifecycleState.APPROACHING,
                LiquidityLifecycleState.PARTIALLY_MITIGATED,
            )
        ]
        mitigated = [
            ev for ev in canonical_obs
            if ev.event_status == LiquidityLifecycleState.MITIGATED
        ]
        invalidated = [
            ev for ev in canonical_obs
            if ev.event_status == LiquidityLifecycleState.INVALIDATED
        ]

        bullish_obs = [ev for ev in canonical_obs if ev.direction == EventDirection.BULLISH]
        bearish_obs = [ev for ev in canonical_obs if ev.direction == EventDirection.BEARISH]

        return TimeframeOrderBlockReport(
            index=symbol.upper().strip(),
            timeframe=timeframe.lower().strip(),
            data_quality=data_quality_status,
            order_block_events=canonical_obs,
            active_order_blocks=active,
            mitigated_order_blocks=mitigated,
            invalidated_order_blocks=invalidated,
            latest_bullish_ob=bullish_obs[-1] if bullish_obs else None,
            latest_bearish_ob=bearish_obs[-1] if bearish_obs else None,
            as_of_time=as_of_time,
            configuration_version=self.config.configuration_version,
            engine_version=self.config.engine_version,
        )

    def analyze_multi_timeframe(
        self,
        data_by_timeframe: Dict[str, pd.DataFrame],
        symbol: str = "NIFTY 50",
        as_of_time: Optional[datetime] = None,
        data_quality_status: str = "VERIFIED_LIVE",
    ) -> Dict[str, TimeframeOrderBlockReport]:
        """
        Processes Order Blocks across all supported timeframes in strict isolation.
        Supported timeframes: 1h, 15m, 5m, 3m, 1m.
        """
        supported_tfs = {"1h", "15m", "5m", "3m", "1m"}
        reports: Dict[str, TimeframeOrderBlockReport] = {}

        for tf, df_tf in data_by_timeframe.items():
            tf_clean = tf.lower().strip()
            if tf_clean not in supported_tfs:
                continue

            report = self.analyze_timeframe(
                df=df_tf,
                symbol=symbol,
                timeframe=tf_clean,
                as_of_time=as_of_time,
                data_quality_status=data_quality_status,
            )
            reports[tf_clean] = report

        return reports
