"""
AIVOLVE Quantitative Institutional Trading Architecture v3.0
Phase 3 Step 3.4 — Fair Value Gap (FVG) & Inverse Fair Value Gap (IFVG) Engine.

Deterministic, point-in-time detection and lifecycle management of 3-candle price
imbalances (FVG) and their structural role-reversals (IFVG) across Indian equity indices.

Key Invariants:
1. Pure Mathematical 3-Candle Structure:
   - Bullish FVG: Low(C3) > High(C1) with confirmed bullish displacement on C2.
   - Bearish FVG: High(C3) < Low(C1) with confirmed bearish displacement on C2.
2. Raw Price Preservation:
   - Zone boundaries [Z_low, Z_high] and Consequent Encroachment (50% CE) preserve
     unquantized raw OHLC floats without tick quantization or rounding.
3. Strict Temporal Alignment & Anti-Lookahead:
   - candle_open_time = bar start timestamp.
   - candle_close_time = bar completion timestamp (accounting for 1H session clamp at 15:30 IST).
   - available_at = confirmation candle completion time (candle_close_time of C3).
   - Point-in-time slicing strictly filters completed bars: candle_close_time <= as_of_time.
   - Forming candles are strictly excluded.
4. Fail-Closed Volatility & Data Quality:
   - Conditional ATR evaluation (skipped when min_gap_atr_multiple == 0.0; mandatory when > 0.0).
   - Rejects STALE, DEGRADED, REPAIRED, SYNTHETIC, and invalid OHLC geometries.
   - Verified exchange calendar check for holidays and session bounds.
5. Invalidation & Inversion Precedence:
   - Completed candle close beyond zone boundary strictly supersedes intra-bar wick mitigation.
   - Active/partially mitigated breached gaps invert to IFVGs (retaining parent linkage).
   - Single Inversion Guarantee: IFVGs never produce secondary inversions.
6. Collision-Resistant Event IDs:
   - Incorporates full 64-hex SHA-256 configuration fingerprint.
7. Strictly PAPER TRADING ONLY.
"""

from typing import Dict, Any, List, Optional, Tuple, Set
from datetime import datetime, timezone, time, timedelta
import zoneinfo
import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from app.options.ict_smc.ict_models import (
    ICTEvent,
    ICTEventType,
    EventDirection,
    LiquidityLifecycleState,
    FVGEvidence,
    FVGEvent,
    FVGConfiguration,
    FVG_ACTIVE_STATES,
    VALID_FVG_TRANSITIONS,
    VALID_IFVG_TRANSITIONS,
    validate_fvg_transition,
    validate_ifvg_transition,
    compute_configuration_fingerprint,
    generate_deterministic_fvg_event_id,
    _ensure_timezone_aware,
    IST_ZONE,
)
from app.options.ict_smc.market_structure import (
    DISQUALIFYING_FEED_STATUSES,
    VALID_FEED_STATUSES,
)

# Indian Regular Trading Session constants
SESSION_START_TIME = time(9, 15)
SESSION_END_TIME = time(15, 30)

TIMEFRAME_DURATIONS: Dict[str, timedelta] = {
    "1m": timedelta(minutes=1),
    "3m": timedelta(minutes=3),
    "5m": timedelta(minutes=5),
    "15m": timedelta(minutes=15),
    "1h": timedelta(hours=1),
}


class TimeframeFVGReport(BaseModel):
    """
    Structured report containing point-in-time FVG and IFVG intelligence for a timeframe.
    """
    index: str
    timeframe: str
    data_quality: str
    fvg_events: List[ICTEvent] = Field(default_factory=list)
    active_fvgs: List[ICTEvent] = Field(default_factory=list)
    mitigated_fvgs: List[ICTEvent] = Field(default_factory=list)
    invalidated_fvgs: List[ICTEvent] = Field(default_factory=list)
    ifvg_events: List[ICTEvent] = Field(default_factory=list)
    active_ifvgs: List[ICTEvent] = Field(default_factory=list)
    latest_bullish_fvg: Optional[ICTEvent] = None
    latest_bearish_fvg: Optional[ICTEvent] = None
    as_of_time: Optional[datetime] = None
    configuration_version: str = "3.4.0"
    configuration_fingerprint: str


class FVGEngine:
    """
    Institutional Fair Value Gap & Inverse Fair Value Gap Intelligence Engine.
    Executes deterministic, mathematical, point-in-time detection and lifecycle tracking.
    Strictly PAPER TRADING ONLY.
    """

    def __init__(self, config: Optional[FVGConfiguration] = None):
        self.config = config or FVGConfiguration()
        self._fingerprint = compute_configuration_fingerprint(self.config)

    @property
    def configuration_fingerprint(self) -> str:
        """Returns the full 64-hex SHA-256 configuration fingerprint."""
        return self._fingerprint

    @staticmethod
    def compute_candle_close_time(open_time: datetime, timeframe: str) -> datetime:
        """
        Computes the exact candle completion time (candle_close_time) from candle_open_time.
        Accounts for the Indian regular trading session end at 15:30 IST:
        Specifically, for 1h candles opening at 15:15 IST, completion is clamped to 15:30 IST.
        """
        tz_open = _ensure_timezone_aware(open_time)
        clean_tf = str(timeframe).lower().strip()
        dur = TIMEFRAME_DURATIONS.get(clean_tf, timedelta(minutes=15))
        nominal_close = tz_open + dur

        # Indian session clamp: No candle may extend beyond 15:30 IST on the same trading day
        ist_open = tz_open.astimezone(IST_ZONE)
        session_close_dt = ist_open.replace(hour=15, minute=30, second=0, microsecond=0)

        # If candle opens during market hours and nominal close exceeds 15:30 IST, clamp
        if ist_open.time() >= SESSION_START_TIME and ist_open.time() < SESSION_END_TIME:
            if nominal_close > session_close_dt:
                return session_close_dt

        return nominal_close

    def _validate_input_quality(
        self,
        df: pd.DataFrame,
        data_quality_status: str,
        as_of_time: Optional[datetime] = None,
    ) -> None:
        """
        Validates feed status, repair metadata, OHLC geometric invariants, and exchange calendar.
        Fails closed on any data corruption, synthetic injection, or calendar unavailability.
        """
        # 1. Feed status check
        status_clean = str(data_quality_status).upper().strip()
        if status_clean in DISQUALIFYING_FEED_STATUSES or status_clean not in VALID_FEED_STATUSES:
            raise ValueError(
                f"FVG detection locked out: feed quality status '{data_quality_status}' "
                f"is not verified live."
            )

        # 2. DataFrame presence & emptiness
        if df is None or df.empty:
            return

        # 3. Phase 1/2 repair lockout
        if hasattr(df, "attrs") and df.attrs:
            if df.attrs.get("quality_status") == "REPAIRED" or df.attrs.get("imputed_bars_count", 0) > 0:
                raise ValueError(
                    "FVG detection locked out: input series contains repaired or imputed mandatory candles."
                )

        # 4. Mandatory column presence
        req_cols = {"open", "high", "low", "close"}
        missing_cols = req_cols - set(df.columns)
        if missing_cols:
            raise ValueError(f"Missing mandatory OHLC columns: {missing_cols}")

        # 5. Timestamp validation
        if "timestamp" in df.columns:
            ts_series = df["timestamp"]
            if ts_series.isnull().any():
                raise ValueError("DataFrame contains null values in mandatory 'timestamp' column.")

        # 6. Exchange Trading Calendar verification
        if as_of_time is not None:
            as_of_dt = _ensure_timezone_aware(as_of_time).astimezone(IST_ZONE)
            try:
                from app.data.market_calendar import MarketCalendar
                if not MarketCalendar.is_trading_day(as_of_dt):
                    # Check if market calendar confirms a special trading session (e.g. Muhurat trading)
                    # If not a verified trading session, fail closed
                    raise ValueError(
                        f"FVG detection locked out: date '{as_of_dt.date()}' is not a verified exchange trading session."
                    )
            except ImportError:
                raise ValueError("FVG detection locked out: verified exchange trading calendar module is unavailable.")
            except ValueError:
                raise
            except Exception as e:
                raise ValueError(f"FVG detection locked out: exchange calendar verification failed: {e}")

    @staticmethod
    def _compute_atr(
        highs: np.ndarray,
        lows: np.ndarray,
        closes: np.ndarray,
        period: int = 14,
    ) -> Optional[np.ndarray]:
        """
        Calculates 14-period Wilder RMA True Range / ATR array over a contiguous completed series.
        Requires at least period + 1 completed candles (15 candles).
        Returns None if history is insufficient or contains zero/NaN volatility.
        Never fabricates partial averages or clamps to arbitrary constants.
        """
        n = len(highs)
        if n < period + 1:
            return None

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
        # Seed Wilder's RMA with 14-period simple average from index 1 to 14
        atr[period] = np.mean(tr[1 : period + 1])
        for i in range(period + 1, n):
            atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period

        # Check for invalid zero or NaN values
        if np.any(np.isnan(atr[period:])) or np.all(atr[period:] <= 0.0):
            return None

        return atr

    def detect_gaps(
        self,
        df: pd.DataFrame,
        symbol: str = "NIFTY 50",
        timeframe: str = "15m",
        as_of_time: Optional[datetime] = None,
        data_quality_status: str = "VERIFIED_LIVE",
    ) -> Tuple[List[FVGEvent], List[ICTEvent], List[FVGEvent], List[ICTEvent]]:
        """
        Detects qualifying Bullish and Bearish FVGs and IFVGs over completed candles,
        evaluating their mitigation and inversion lifecycle up to as_of_time.
        Returns: (typed_fvgs, canonical_fvgs, typed_ifvgs, canonical_ifvgs).
        """
        # 1. Quality & safety validation
        self._validate_input_quality(df=df, data_quality_status=data_quality_status, as_of_time=as_of_time)

        if df is None or df.empty or len(df) < 3:
            return [], [], [], []

        # 2. Extract series arrays
        clean_tf = str(timeframe).lower().strip()
        n_raw = len(df)

        raw_opens = df["open"].to_numpy(dtype=float)
        raw_highs = df["high"].to_numpy(dtype=float)
        raw_lows = df["low"].to_numpy(dtype=float)
        raw_closes = df["close"].to_numpy(dtype=float)

        raw_ids = [str(df.iloc[k].get("candle_id", f"c_{k}")) for k in range(n_raw)]

        # Extract tz-aware open timestamps and compute accurate completion timestamps
        raw_open_ts: List[datetime] = []
        raw_close_ts: List[datetime] = []
        for k in range(n_raw):
            val = df.iloc[k].get("timestamp")
            ots = _ensure_timezone_aware(val if val is not None else datetime.now(timezone.utc))
            raw_open_ts.append(ots)
            raw_close_ts.append(self.compute_candle_close_time(ots, clean_tf))

        # 3. As-Of Point-in-Time Filtering: STRICTLY require candle_close_time <= as_of_time
        # In-progress / forming candles are strictly excluded
        as_of_dt = _ensure_timezone_aware(as_of_time) if as_of_time else None
        valid_indices: List[int] = []
        for k in range(n_raw):
            if as_of_dt is not None:
                if raw_close_ts[k] > as_of_dt:
                    continue  # Incomplete / forming bar relative to as_of_time
            valid_indices.append(k)

        if len(valid_indices) < 3:
            return [], [], [], []

        c_open = raw_opens[valid_indices]
        c_high = raw_highs[valid_indices]
        c_low = raw_lows[valid_indices]
        c_close = raw_closes[valid_indices]
        c_ids = [raw_ids[k] for k in valid_indices]
        c_open_ts = [raw_open_ts[k] for k in valid_indices]
        c_close_ts = [raw_close_ts[k] for k in valid_indices]

        n = len(valid_indices)

        # 4. Check OHLC geometric invariants on completed series
        for k in range(n):
            if c_high[k] < c_low[k] or not (c_low[k] <= c_open[k] <= c_high[k]) or not (c_low[k] <= c_close[k] <= c_high[k]):
                raise ValueError(f"Invalid OHLC candle geometry at bar {c_ids[k]}: H={c_high[k]}, L={c_low[k]}, O={c_open[k]}, C={c_close[k]}")

        # 5. Compute ATR array over completed series if required
        atr_arr = self._compute_atr(c_high, c_low, c_close, period=self.config.atr_period)

        typed_fvgs: List[FVGEvent] = []
        typed_ifvgs: List[FVGEvent] = []
        emitted_fvg_keys: Set[str] = set()

        # 6. Detection Loop: Scan 3-candle windows [C_{i-2}, C_{i-1}, C_i]
        for i in range(2, n):
            c1_idx = i - 2
            c2_idx = i - 1
            c3_idx = i

            c1_h = c_high[c1_idx]
            c1_l = c_low[c1_idx]
            c2_o = c_open[c2_idx]
            c2_h = c_high[c2_idx]
            c2_l = c_low[c2_idx]
            c2_c = c_close[c2_idx]
            c3_l = c_low[c3_idx]
            c3_h = c_high[c3_idx]

            c2_range = c2_h - c2_l
            if c2_range <= 0.0:
                continue  # Flat tick / illiquid bar disqualified

            # --- A. Bullish FVG Evaluation ---
            if c3_l > c1_h:
                # 1. Directional impulse requirement on C2: Strict positive body
                if c2_c <= c2_o:
                    continue  # Bullish FVG requires bullish body on C2

                # 2. Body-to-range ratio requirement
                body_ratio = (c2_c - c2_o) / c2_range
                if body_ratio < self.config.min_displacement_body_ratio:
                    continue

                # 3. Raw price boundary derivation (zero tick quantization or rounding)
                zone_h = float(c3_l)
                zone_l = float(c1_h)
                gap_pts = round(zone_h - zone_l, 4)

                if gap_pts < self.config.min_gap_size_pts:
                    continue

                # 4. Conditional ATR qualification
                gap_atr_mult: Optional[float] = None
                atr_status = "SKIPPED_CONFIGURED_ZERO"

                if self.config.min_gap_atr_multiple > 0.0:
                    if atr_arr is None or i >= len(atr_arr) or atr_arr[i] <= 0.0 or np.isnan(atr_arr[i]):
                        continue  # Incomplete ATR history / zero ATR fails closed
                    cur_atr = float(atr_arr[i])
                    gap_atr_mult = round(gap_pts / cur_atr, 4)
                    if gap_pts < (self.config.min_gap_atr_multiple * cur_atr):
                        continue  # Below configured ATR threshold
                    atr_status = "COMPUTED"
                else:
                    if atr_arr is not None and i < len(atr_arr) and atr_arr[i] > 0.0:
                        gap_atr_mult = round(gap_pts / float(atr_arr[i]), 4)
                        atr_status = "COMPUTED_INFORMATIONAL"

                # 5. Deterministic Event ID generation with 64-hex configuration fingerprint
                event_id = generate_deterministic_fvg_event_id(
                    index=symbol,
                    timeframe=clean_tf,
                    event_type="FVG",
                    source_candle_id=c_ids[c2_idx],
                    config_fingerprint=self._fingerprint,
                )

                if event_id in emitted_fvg_keys:
                    continue
                emitted_fvg_keys.add(event_id)

                ce_midpoint = (zone_h + zone_l) / 2.0
                evidence = FVGEvidence(
                    candle_1_id=c_ids[c1_idx],
                    candle_2_id=c_ids[c2_idx],
                    candle_3_id=c_ids[c3_idx],
                    gap_size_pts=gap_pts,
                    gap_atr_multiple=gap_atr_mult,
                    atr_status=atr_status,
                    consequent_encroachment=ce_midpoint,
                    displacement_body_ratio=round(body_ratio, 4),
                    mitigation_percentage=0.0,
                    mitigated_at=None,
                    invalidation_condition=f"Completed candle close < {zone_l - self.config.invalidation_buffer_pts}",
                    invalidation_reason=None,
                    touch_count=0,
                    is_inverted=False,
                )

                fvg_event = FVGEvent(
                    event_id=event_id,
                    index=symbol.upper().strip(),
                    event_type=ICTEventType.FVG,
                    direction=EventDirection.BULLISH,
                    timeframe=clean_tf,
                    zone_high=zone_h,
                    zone_low=zone_l,
                    mean_threshold=ce_midpoint,
                    event_status=LiquidityLifecycleState.CONFIRMED,
                    event_time=c_open_ts[c2_idx],      # Footprint origin timestamp
                    available_at=c_close_ts[c3_idx],   # Confirmation bar completion timestamp
                    created_at=c_close_ts[c3_idx],
                    confirmed_at=c_close_ts[c3_idx],
                    source_candle_identifiers=[c_ids[c1_idx], c_ids[c2_idx], c_ids[c3_idx]],
                    data_quality=data_quality_status,
                    evidence=evidence,
                    configuration_version=self.config.configuration_version,
                    engine_version=self.config.engine_version,
                )
                typed_fvgs.append(fvg_event)

            # --- B. Bearish FVG Evaluation ---
            elif c3_h < c1_l:
                # 1. Directional impulse requirement on C2: Strict negative body
                if c2_c >= c2_o:
                    continue  # Bearish FVG requires bearish body on C2

                # 2. Body-to-range ratio requirement
                body_ratio = (c2_o - c2_c) / c2_range
                if body_ratio < self.config.min_displacement_body_ratio:
                    continue

                # 3. Raw price boundary derivation
                zone_h = float(c1_l)
                zone_l = float(c3_h)
                gap_pts = round(zone_h - zone_l, 4)

                if gap_pts < self.config.min_gap_size_pts:
                    continue

                # 4. Conditional ATR qualification
                gap_atr_mult: Optional[float] = None
                atr_status = "SKIPPED_CONFIGURED_ZERO"

                if self.config.min_gap_atr_multiple > 0.0:
                    if atr_arr is None or i >= len(atr_arr) or atr_arr[i] <= 0.0 or np.isnan(atr_arr[i]):
                        continue
                    cur_atr = float(atr_arr[i])
                    gap_atr_mult = round(gap_pts / cur_atr, 4)
                    if gap_pts < (self.config.min_gap_atr_multiple * cur_atr):
                        continue
                    atr_status = "COMPUTED"
                else:
                    if atr_arr is not None and i < len(atr_arr) and atr_arr[i] > 0.0:
                        gap_atr_mult = round(gap_pts / float(atr_arr[i]), 4)
                        atr_status = "COMPUTED_INFORMATIONAL"

                # 5. Deterministic Event ID generation
                event_id = generate_deterministic_fvg_event_id(
                    index=symbol,
                    timeframe=clean_tf,
                    event_type="FVG",
                    source_candle_id=c_ids[c2_idx],
                    config_fingerprint=self._fingerprint,
                )

                if event_id in emitted_fvg_keys:
                    continue
                emitted_fvg_keys.add(event_id)

                ce_midpoint = (zone_h + zone_l) / 2.0
                evidence = FVGEvidence(
                    candle_1_id=c_ids[c1_idx],
                    candle_2_id=c_ids[c2_idx],
                    candle_3_id=c_ids[c3_idx],
                    gap_size_pts=gap_pts,
                    gap_atr_multiple=gap_atr_mult,
                    atr_status=atr_status,
                    consequent_encroachment=ce_midpoint,
                    displacement_body_ratio=round(body_ratio, 4),
                    mitigation_percentage=0.0,
                    mitigated_at=None,
                    invalidation_condition=f"Completed candle close > {zone_h + self.config.invalidation_buffer_pts}",
                    invalidation_reason=None,
                    touch_count=0,
                    is_inverted=False,
                )

                fvg_event = FVGEvent(
                    event_id=event_id,
                    index=symbol.upper().strip(),
                    event_type=ICTEventType.FVG,
                    direction=EventDirection.BEARISH,
                    timeframe=clean_tf,
                    zone_high=zone_h,
                    zone_low=zone_l,
                    mean_threshold=ce_midpoint,
                    event_status=LiquidityLifecycleState.CONFIRMED,
                    event_time=c_open_ts[c2_idx],
                    available_at=c_close_ts[c3_idx],
                    created_at=c_close_ts[c3_idx],
                    confirmed_at=c_close_ts[c3_idx],
                    source_candle_identifiers=[c_ids[c1_idx], c_ids[c2_idx], c_ids[c3_idx]],
                    data_quality=data_quality_status,
                    evidence=evidence,
                    configuration_version=self.config.configuration_version,
                    engine_version=self.config.engine_version,
                )
                typed_fvgs.append(fvg_event)

        # 7. Lifecycle State Machine & Inversion Evaluation Loop across subsequent completed candles
        ts_to_idx = {c_close_ts[k]: k for k in range(n)}

        for m in range(n):
            dt_close = c_close_ts[m]
            dt_open = c_open_ts[m]
            bar_o = c_open[m]
            bar_h = c_high[m]
            bar_l = c_low[m]
            bar_c = c_close[m]
            bar_cid = c_ids[m]

            # --- Evaluate FVGs ---
            for fvg in typed_fvgs:
                # Anti-lookahead: Confirmation candle itself cannot mitigate or invalidate
                if dt_close <= fvg.available_at:
                    continue

                # Once in absorbing terminal state, immutability applies
                if fvg.event_status in (
                    LiquidityLifecycleState.MITIGATED,
                    LiquidityLifecycleState.INVALIDATED,
                    LiquidityLifecycleState.EXPIRED,
                ):
                    continue

                zh = fvg.zone_high
                zl = fvg.zone_low
                ce = fvg.mean_threshold
                span = max(0.0001, zh - zl)

                if fvg.direction == EventDirection.BULLISH:
                    # Precedence Rule 1: Invalidation on completed candle close strictly supersedes mitigation
                    if bar_c < (zl - self.config.invalidation_buffer_pts):
                        pre_breach_status = fvg.event_status
                        fvg.event_status = LiquidityLifecycleState.INVALIDATED
                        fvg.invalidated_at = dt_close
                        fvg.evidence.invalidation_reason = f"Completed candle closed below lower boundary {zl} at {bar_c}"

                        # Inversion Trigger: Only active FVGs (CONFIRMED, APPROACHING, PARTIALLY_MITIGATED)
                        # that have not already been inverted can convert into an IFVG.
                        # Terminal states (MITIGATED, INVALIDATED, EXPIRED) and unconfirmed IDENTIFIED cannot invert.
                        if (
                            self.config.enable_ifvg_conversion
                            and not fvg.evidence.is_inverted
                            and pre_breach_status in FVG_ACTIVE_STATES
                        ):
                            fvg.evidence.is_inverted = True
                            ifvg_id = generate_deterministic_fvg_event_id(
                                index=symbol,
                                timeframe=clean_tf,
                                event_type="IFVG",
                                source_candle_id=fvg.event_id,
                                config_fingerprint=self._fingerprint,
                            )
                            ifvg_ev = FVGEvidence(
                                candle_1_id=fvg.evidence.candle_1_id,
                                candle_2_id=fvg.evidence.candle_2_id,
                                candle_3_id=fvg.evidence.candle_3_id,
                                gap_size_pts=fvg.evidence.gap_size_pts,
                                gap_atr_multiple=fvg.evidence.gap_atr_multiple,
                                atr_status=fvg.evidence.atr_status,
                                consequent_encroachment=ce,
                                displacement_body_ratio=fvg.evidence.displacement_body_ratio,
                                mitigation_percentage=0.0,
                                mitigated_at=None,
                                invalidation_condition=f"Completed candle close > {zh + self.config.invalidation_buffer_pts}",
                                invalidation_reason=None,
                                touch_count=0,
                                is_inverted=True,
                                source_fvg_id=fvg.event_id,
                                inversion_candle_id=bar_cid,
                                inversion_close=bar_c,
                                inversion_time=dt_open,
                            )
                            ifvg_event = FVGEvent(
                                event_id=ifvg_id,
                                index=symbol.upper().strip(),
                                event_type=ICTEventType.IFVG,
                                direction=EventDirection.BEARISH,
                                timeframe=clean_tf,
                                zone_high=zh,
                                zone_low=zl,
                                mean_threshold=ce,
                                event_status=LiquidityLifecycleState.CONFIRMED,
                                event_time=dt_open,
                                available_at=dt_close,
                                created_at=dt_close,
                                confirmed_at=dt_close,
                                source_candle_identifiers=fvg.source_candle_identifiers + [bar_cid],
                                data_quality=data_quality_status,
                                evidence=ifvg_ev,
                                configuration_version=self.config.configuration_version,
                                engine_version=self.config.engine_version,
                            )
                            typed_ifvgs.append(ifvg_event)
                        continue

                    # Mitigation Check: Wick enters zone interior (bar_l < zone_high)
                    if bar_l < zh:
                        fvg.evidence.touch_count += 1
                        pen_depth = zh - max(zl, bar_l)
                        depth_pct = round(min(100.0, max(0.0, (pen_depth / span) * 100.0)), 2)
                        fvg.evidence.mitigation_percentage = max(fvg.evidence.mitigation_percentage, depth_pct)

                        # Full mitigation boundary check
                        if self.config.full_mitigation_policy == "CONSEQUENT_ENCROACHMENT":
                            is_full = (depth_pct >= 50.0 or bar_l <= ce or bar_l <= zl)
                        else:  # FULL_FILL
                            is_full = (depth_pct >= 100.0 or bar_l <= zl)

                        if is_full:
                            fvg.event_status = LiquidityLifecycleState.MITIGATED
                            fvg.evidence.mitigated_at = dt_close
                        else:
                            fvg.event_status = LiquidityLifecycleState.PARTIALLY_MITIGATED

                    elif bar_l == zh:
                        # Exact boundary touch at 0% penetration
                        fvg.evidence.touch_count += 1
                        fvg.event_status = LiquidityLifecycleState.APPROACHING

                    else:
                        # Approach check (bar_l > zh)
                        app_delta = max(self.config.approach_threshold_pts, zh * self.config.approach_threshold_pct)
                        if bar_l <= (zh + app_delta):
                            fvg.event_status = LiquidityLifecycleState.APPROACHING
                        elif fvg.event_status == LiquidityLifecycleState.APPROACHING:
                            # Retreat check with hysteresis factor
                            retreat_delta = app_delta * self.config.approach_retreat_mult
                            if bar_l > (zh + retreat_delta):
                                fvg.event_status = LiquidityLifecycleState.CONFIRMED

                elif fvg.direction == EventDirection.BEARISH:
                    # Precedence Rule 1: Invalidation on completed candle close strictly supersedes mitigation
                    if bar_c > (zh + self.config.invalidation_buffer_pts):
                        pre_breach_status = fvg.event_status
                        fvg.event_status = LiquidityLifecycleState.INVALIDATED
                        fvg.invalidated_at = dt_close
                        fvg.evidence.invalidation_reason = f"Completed candle closed above upper boundary {zh} at {bar_c}"

                        # Inversion Trigger: Only active FVGs (CONFIRMED, APPROACHING, PARTIALLY_MITIGATED)
                        # that have not already been inverted can convert into an IFVG.
                        # Terminal states (MITIGATED, INVALIDATED, EXPIRED) and unconfirmed IDENTIFIED cannot invert.
                        if (
                            self.config.enable_ifvg_conversion
                            and not fvg.evidence.is_inverted
                            and pre_breach_status in FVG_ACTIVE_STATES
                        ):
                            fvg.evidence.is_inverted = True
                            ifvg_id = generate_deterministic_fvg_event_id(
                                index=symbol,
                                timeframe=clean_tf,
                                event_type="IFVG",
                                source_candle_id=fvg.event_id,
                                config_fingerprint=self._fingerprint,
                            )
                            ifvg_ev = FVGEvidence(
                                candle_1_id=fvg.evidence.candle_1_id,
                                candle_2_id=fvg.evidence.candle_2_id,
                                candle_3_id=fvg.evidence.candle_3_id,
                                gap_size_pts=fvg.evidence.gap_size_pts,
                                gap_atr_multiple=fvg.evidence.gap_atr_multiple,
                                atr_status=fvg.evidence.atr_status,
                                consequent_encroachment=ce,
                                displacement_body_ratio=fvg.evidence.displacement_body_ratio,
                                mitigation_percentage=0.0,
                                mitigated_at=None,
                                invalidation_condition=f"Completed candle close < {zl - self.config.invalidation_buffer_pts}",
                                invalidation_reason=None,
                                touch_count=0,
                                is_inverted=True,
                                source_fvg_id=fvg.event_id,
                                inversion_candle_id=bar_cid,
                                inversion_close=bar_c,
                                inversion_time=dt_open,
                            )
                            ifvg_event = FVGEvent(
                                event_id=ifvg_id,
                                index=symbol.upper().strip(),
                                event_type=ICTEventType.IFVG,
                                direction=EventDirection.BULLISH,
                                timeframe=clean_tf,
                                zone_high=zh,
                                zone_low=zl,
                                mean_threshold=ce,
                                event_status=LiquidityLifecycleState.CONFIRMED,
                                event_time=dt_open,
                                available_at=dt_close,
                                created_at=dt_close,
                                confirmed_at=dt_close,
                                source_candle_identifiers=fvg.source_candle_identifiers + [bar_cid],
                                data_quality=data_quality_status,
                                evidence=ifvg_ev,
                                configuration_version=self.config.configuration_version,
                                engine_version=self.config.engine_version,
                            )
                            typed_ifvgs.append(ifvg_event)
                        continue

                    # Mitigation Check: Wick enters zone interior (bar_h > zone_low)
                    if bar_h > zl:
                        fvg.evidence.touch_count += 1
                        pen_depth = min(zh, bar_h) - zl
                        depth_pct = round(min(100.0, max(0.0, (pen_depth / span) * 100.0)), 2)
                        fvg.evidence.mitigation_percentage = max(fvg.evidence.mitigation_percentage, depth_pct)

                        # Full mitigation boundary check
                        if self.config.full_mitigation_policy == "CONSEQUENT_ENCROACHMENT":
                            is_full = (depth_pct >= 50.0 or bar_h >= ce or bar_h >= zh)
                        else:  # FULL_FILL
                            is_full = (depth_pct >= 100.0 or bar_h >= zh)

                        if is_full:
                            fvg.event_status = LiquidityLifecycleState.MITIGATED
                            fvg.evidence.mitigated_at = dt_close
                        else:
                            fvg.event_status = LiquidityLifecycleState.PARTIALLY_MITIGATED

                    elif bar_h == zl:
                        # Exact boundary touch at 0% penetration
                        fvg.evidence.touch_count += 1
                        fvg.event_status = LiquidityLifecycleState.APPROACHING

                    else:
                        # Approach check (bar_h < zl)
                        app_delta = max(self.config.approach_threshold_pts, zl * self.config.approach_threshold_pct)
                        if bar_h >= (zl - app_delta):
                            fvg.event_status = LiquidityLifecycleState.APPROACHING
                        elif fvg.event_status == LiquidityLifecycleState.APPROACHING:
                            # Retreat check with hysteresis
                            retreat_delta = app_delta * self.config.approach_retreat_mult
                            if bar_h < (zl - retreat_delta):
                                fvg.event_status = LiquidityLifecycleState.CONFIRMED

                # Expiry check across active states
                conf_idx = ts_to_idx.get(fvg.available_at, 0)
                if (m - conf_idx) >= self.config.max_active_candles:
                    fvg.event_status = LiquidityLifecycleState.EXPIRED

            # --- Evaluate IFVGs ---
            for ifvg in typed_ifvgs:
                if dt_close <= ifvg.available_at:
                    continue

                if ifvg.event_status in (
                    LiquidityLifecycleState.MITIGATED,
                    LiquidityLifecycleState.INVALIDATED,
                    LiquidityLifecycleState.EXPIRED,
                ):
                    continue

                zh = ifvg.zone_high
                zl = ifvg.zone_low
                ce = ifvg.mean_threshold
                span = max(0.0001, zh - zl)

                if ifvg.direction == EventDirection.BEARISH:
                    # Bearish IFVG retested from below (acts as resistance at zl)
                    # Invalidation: completed candle closes above far boundary zh
                    if bar_c > (zh + self.config.invalidation_buffer_pts):
                        ifvg.event_status = LiquidityLifecycleState.INVALIDATED
                        ifvg.invalidated_at = dt_close
                        ifvg.evidence.invalidation_reason = f"Completed candle closed above upper boundary {zh} at {bar_c}"
                        continue  # No secondary inversion!

                    # Retest mitigation (wick enters from below)
                    if bar_h > zl:
                        ifvg.evidence.touch_count += 1
                        pen_depth = min(zh, bar_h) - zl
                        depth_pct = round(min(100.0, max(0.0, (pen_depth / span) * 100.0)), 2)
                        ifvg.evidence.mitigation_percentage = max(ifvg.evidence.mitigation_percentage, depth_pct)

                        if self.config.full_mitigation_policy == "CONSEQUENT_ENCROACHMENT":
                            is_full = (depth_pct >= 50.0 or bar_h >= ce or bar_h >= zh)
                        else:
                            is_full = (depth_pct >= 100.0 or bar_h >= zh)

                        if is_full:
                            ifvg.event_status = LiquidityLifecycleState.MITIGATED
                            ifvg.evidence.mitigated_at = dt_close
                        else:
                            ifvg.event_status = LiquidityLifecycleState.PARTIALLY_MITIGATED

                elif ifvg.direction == EventDirection.BULLISH:
                    # Bullish IFVG retested from above (acts as support at zh)
                    # Invalidation: completed candle closes below far boundary zl
                    if bar_c < (zl - self.config.invalidation_buffer_pts):
                        ifvg.event_status = LiquidityLifecycleState.INVALIDATED
                        ifvg.invalidated_at = dt_close
                        ifvg.evidence.invalidation_reason = f"Completed candle closed below lower boundary {zl} at {bar_c}"
                        continue  # No secondary inversion!

                    # Retest mitigation (wick enters from above)
                    if bar_l < zh:
                        ifvg.evidence.touch_count += 1
                        pen_depth = zh - max(zl, bar_l)
                        depth_pct = round(min(100.0, max(0.0, (pen_depth / span) * 100.0)), 2)
                        ifvg.evidence.mitigation_percentage = max(ifvg.evidence.mitigation_percentage, depth_pct)

                        if self.config.full_mitigation_policy == "CONSEQUENT_ENCROACHMENT":
                            is_full = (depth_pct >= 50.0 or bar_l <= ce or bar_l <= zl)
                        else:
                            is_full = (depth_pct >= 100.0 or bar_l <= zl)

                        if is_full:
                            ifvg.event_status = LiquidityLifecycleState.MITIGATED
                            ifvg.evidence.mitigated_at = dt_close
                        else:
                            ifvg.event_status = LiquidityLifecycleState.PARTIALLY_MITIGATED

                # IFVG Expiry check
                ifvg_conf_idx = ts_to_idx.get(ifvg.available_at, 0)
                if (m - ifvg_conf_idx) >= self.config.max_active_candles:
                    ifvg.event_status = LiquidityLifecycleState.EXPIRED

        # 8. Convert to canonical 17-field ICTEvent objects
        canonical_fvgs = [f.to_ict_event() for f in typed_fvgs]
        canonical_ifvgs = [f.to_ict_event() for f in typed_ifvgs]

        return typed_fvgs, canonical_fvgs, typed_ifvgs, canonical_ifvgs

    def analyze_timeframe(
        self,
        df: pd.DataFrame,
        symbol: str = "NIFTY 50",
        timeframe: str = "15m",
        as_of_time: Optional[datetime] = None,
        data_quality_status: str = "VERIFIED_LIVE",
    ) -> TimeframeFVGReport:
        """
        Executes complete point-in-time FVG & IFVG analysis for a single timeframe.
        """
        typed_fvgs, canonical_fvgs, typed_ifvgs, canonical_ifvgs = self.detect_gaps(
            df=df,
            symbol=symbol,
            timeframe=timeframe,
            as_of_time=as_of_time,
            data_quality_status=data_quality_status,
        )

        active_f = [ev for ev in canonical_fvgs if ev.event_status in FVG_ACTIVE_STATES]
        mitigated_f = [ev for ev in canonical_fvgs if ev.event_status == LiquidityLifecycleState.MITIGATED]
        invalidated_f = [ev for ev in canonical_fvgs if ev.event_status == LiquidityLifecycleState.INVALIDATED]

        active_if = [ev for ev in canonical_ifvgs if ev.event_status in FVG_ACTIVE_STATES]

        bullish_fvgs = [ev for ev in canonical_fvgs if ev.direction == EventDirection.BULLISH]
        bearish_fvgs = [ev for ev in canonical_fvgs if ev.direction == EventDirection.BEARISH]

        as_of_dt = _ensure_timezone_aware(as_of_time) if as_of_time else None

        return TimeframeFVGReport(
            index=symbol.upper().strip(),
            timeframe=timeframe.lower().strip(),
            data_quality=data_quality_status,
            fvg_events=canonical_fvgs,
            active_fvgs=active_f,
            mitigated_fvgs=mitigated_f,
            invalidated_fvgs=invalidated_f,
            ifvg_events=canonical_ifvgs,
            active_ifvgs=active_if,
            latest_bullish_fvg=bullish_fvgs[-1] if bullish_fvgs else None,
            latest_bearish_fvg=bearish_fvgs[-1] if bearish_fvgs else None,
            as_of_time=as_of_dt,
            configuration_version=self.config.configuration_version,
            configuration_fingerprint=self._fingerprint,
        )

    def analyze_multi_timeframe(
        self,
        timeframe_dfs: Dict[str, pd.DataFrame],
        symbol: str = "NIFTY 50",
        as_of_time: Optional[datetime] = None,
        data_quality_status: str = "VERIFIED_LIVE",
    ) -> Dict[str, TimeframeFVGReport]:
        """
        Processes FVG/IFVG analysis across supported timeframes (1h, 15m, 5m, 3m, 1m) in strict isolation.
        Zero cross-timeframe data leakage or lookahead.
        """
        reports: Dict[str, TimeframeFVGReport] = {}
        for tf, df in timeframe_dfs.items():
            tf_clean = str(tf).lower().strip()
            reports[tf_clean] = self.analyze_timeframe(
                df=df,
                symbol=symbol,
                timeframe=tf_clean,
                as_of_time=as_of_time,
                data_quality_status=data_quality_status,
            )
        return reports

