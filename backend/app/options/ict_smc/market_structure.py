"""
AIVOLVE Phase 3 Step 3.2 — Market Structure & Change of Character Engine.
Provides deterministic, rule-based institutional market structure intelligence:
1. Swing Point Structural Classification (HH, HL, LH, LL, EH, EL).
2. Deterministic active/protected structural high and low selection.
3. Separation of initial structural establishment from continuation BOS and reversal CHoCH.
4. Break of Structure (BOS - Bullish & Bearish with completed candle-close requirement).
5. Change of Character (CHoCH - genuine structural trend reversal breaks).
6. Market Structure Shift (MSS - displacement-confirmed structural shifts linked to CHoCH).
7. Full event invalidation tracking while strictly preserving historical confirmation.
8. Multi-Timeframe structural tracking (1H, 15M, 5M, 3M, 1M) with complete isolation.
9. 100% Anti-lookahead and repainting protection.
10. Stage 3 Data Quality fail-closed lockout enforcement.
"""

from typing import List, Dict, Any, Optional, Tuple, Set
from datetime import datetime, timezone
import pandas as pd
import numpy as np
from pydantic import BaseModel, Field

from app.options.ict_smc.ict_models import (
    ICTEvent,
    ICTEventType,
    EventDirection,
    ICTTimeframe,
    LiquidityLifecycleState,
    StructuralSwingType,
    TrendBias,
    StructuralSwing,
    MarketStructureEvidence,
    MarketStructureEvent,
    MarketStructureConfiguration,
    SwingPoint,
    generate_deterministic_event_id,
    _ensure_timezone_aware,
    IST_ZONE,
)
from app.options.ict_smc.swing_detection import SwingDetectionEngine


DISQUALIFYING_FEED_STATUSES: Set[str] = {
    "DATA_OFFLINE",
    "DATA_UNAVAILABLE",
    "STALE",
    "STALE_TICK",
    "DEGRADED",
    "ANOMALOUS",
    "SYNTHETIC",
    "OFFLINE",
    "UNAVAILABLE",
    "MOCK",
    "UNKNOWN_BAD_FEED",
}

VALID_FEED_STATUSES: Set[str] = {
    "VERIFIED_LIVE",
    "LIVE",
    "OK",
    "CLEAN",
}


class TimeframeStructureReport(BaseModel):
    """
    Structured report containing point-in-time market structure intelligence for a timeframe.
    """
    index: str
    timeframe: str
    data_quality: str
    active_trend: TrendBias
    classified_swings: List[StructuralSwing] = Field(default_factory=list)
    structure_events: List[ICTEvent] = Field(default_factory=list)
    bos_count: int = 0
    choch_count: int = 0
    mss_count: int = 0
    last_swing_high: Optional[StructuralSwing] = None
    last_swing_low: Optional[StructuralSwing] = None
    active_protected_high: Optional[StructuralSwing] = None
    active_protected_low: Optional[StructuralSwing] = None
    active_target_high: Optional[StructuralSwing] = None
    active_target_low: Optional[StructuralSwing] = None
    latest_event: Optional[ICTEvent] = None
    as_of_time: Optional[datetime] = None
    configuration_version: str = "3.2.0"
    engine_version: str = "3.2.0"


class MarketStructureEngine:
    """
    Institutional Market Structure and Change of Character Intelligence Engine.
    """

    def __init__(
        self,
        config: Optional[MarketStructureConfiguration] = None,
        swing_engine: Optional[SwingDetectionEngine] = None,
    ):
        self.config = config or MarketStructureConfiguration()
        self.swing_engine = swing_engine or SwingDetectionEngine()

    @staticmethod
    def _validate_input_quality(
        df: pd.DataFrame,
        data_quality_status: str,
    ) -> None:
        """
        Validates feed status, repair metadata, and OHLC geometric invariants.
        Fails closed on any corruption, synthetic injection, or geometrical inconsistency.
        """
        # 1. Feed status check
        status_clean = str(data_quality_status).upper().strip()
        if status_clean in DISQUALIFYING_FEED_STATUSES or status_clean not in VALID_FEED_STATUSES:
            raise ValueError(
                f"Market structure detection locked out: feed quality status '{data_quality_status}' "
                f"is not verified live."
            )

        # 2. DataFrame presence & emptiness
        if df is None or df.empty:
            return

        # 3. Phase 1/2 repair lockout
        if hasattr(df, "attrs") and df.attrs:
            if df.attrs.get("quality_status") == "REPAIRED" or df.attrs.get("imputed_bars_count", 0) > 0:
                raise ValueError(
                    "Market structure detection locked out: input series contains repaired or imputed mandatory candles."
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

            # Validate timezone uniformity
            tz_set: Set[str] = set()
            for ts_val in ts_series.dropna():
                dt_aware = _ensure_timezone_aware(ts_val)
                tz_name = dt_aware.tzname() or str(dt_aware.tzinfo)
                tz_set.add(tz_name)
            if len(tz_set) > 1:
                raise ValueError(f"Mixed timezones detected in timestamp series: {tz_set}")

        # 6. OHLC numeric & geometric invariants
        opens = pd.to_numeric(df["open"], errors="coerce")
        highs = pd.to_numeric(df["high"], errors="coerce")
        lows = pd.to_numeric(df["low"], errors="coerce")
        closes = pd.to_numeric(df["close"], errors="coerce")

        if opens.isnull().any() or highs.isnull().any() or lows.isnull().any() or closes.isnull().any():
            raise ValueError("Non-numeric or NaN values present in mandatory OHLC price series.")

        if (opens <= 0).any() or (highs <= 0).any() or (lows <= 0).any() or (closes <= 0).any():
            raise ValueError("Non-positive price values detected in OHLC price series.")

        # Invariant: high >= low (checked first)
        if (highs.values < lows.values).any():
            raise ValueError("OHLC invariant violated: high < low")

        # Invariant: high >= max(open, close)
        max_oc = np.maximum(opens.values, closes.values)
        if (highs.values < max_oc - 1e-6).any():
            raise ValueError("OHLC invariant violated: high < max(open, close)")

        # Invariant: low <= min(open, close)
        min_oc = np.minimum(opens.values, closes.values)
        if (lows.values > min_oc + 1e-6).any():
            raise ValueError("OHLC invariant violated: low > min(open, close)")

    @staticmethod
    def _compute_atr_series(df: pd.DataFrame, period: int = 14) -> np.ndarray:
        """Computes rolling Average True Range (ATR) with minimum periods 1."""
        n = len(df)
        if n == 0:
            return np.array([])

        highs = pd.to_numeric(df["high"], errors="coerce").values
        lows = pd.to_numeric(df["low"], errors="coerce").values
        closes = pd.to_numeric(df["close"], errors="coerce").values

        tr = np.zeros(n, dtype=float)
        tr[0] = max(0.01, highs[0] - lows[0])

        for i in range(1, n):
            h_l = highs[i] - lows[i]
            h_cp = abs(highs[i] - closes[i - 1])
            l_cp = abs(lows[i] - closes[i - 1])
            tr[i] = max(0.01, max(h_l, h_cp, l_cp))

        atr = pd.Series(tr).rolling(window=period, min_periods=1).mean().values
        return atr

    def classify_swings(
        self,
        swings: List[SwingPoint],
        as_of_time: Optional[datetime] = None,
    ) -> List[StructuralSwing]:
        """
        Classifies confirmed swing points into Higher Highs (HH), Higher Lows (HL),
        Lower Highs (LH), Lower Lows (LL), Equal Highs (EH), and Equal Lows (EL).
        Maintains strict chronological sequence and anti-lookahead filtering.
        """
        if not swings:
            return []

        as_of_dt = _ensure_timezone_aware(as_of_time) if as_of_time else None

        valid_swings = [
            s for s in swings
            if (not as_of_dt or s.available_at <= as_of_dt)
        ]
        valid_swings.sort(key=lambda s: (s.event_time, s.available_at))

        classified_swings: List[StructuralSwing] = []
        confirmed_highs: List[StructuralSwing] = []
        confirmed_lows: List[StructuralSwing] = []

        tol_pct = self.config.equal_tolerance_pct

        for sw in valid_swings:
            stype = sw.swing_type.upper().strip()

            if stype == "HIGH":
                if not confirmed_highs:
                    classification = StructuralSwingType.INITIAL
                    prev_id = None
                    price_diff = 0.0
                    price_diff_pct = 0.0
                else:
                    prev_high = confirmed_highs[-1]
                    prev_id = prev_high.event_id
                    price_diff = round(sw.price - prev_high.price, 2)
                    price_diff_pct = round(abs(price_diff) / max(0.01, prev_high.price), 6)

                    if price_diff_pct <= tol_pct:
                        classification = StructuralSwingType.EH
                    elif price_diff > 0:
                        classification = StructuralSwingType.HH
                    else:
                        classification = StructuralSwingType.LH

                s_swing = StructuralSwing(
                    event_id=sw.event_id,
                    index=sw.index,
                    timeframe=sw.timeframe,
                    swing_type="HIGH",
                    classification=classification,
                    price=sw.price,
                    bar_index=sw.bar_index,
                    candle_id=sw.candle_id,
                    event_time=sw.event_time,
                    available_at=sw.available_at,
                    source_swing_id=sw.event_id,
                    previous_same_extrema_id=prev_id,
                    price_diff=price_diff,
                    price_diff_pct=price_diff_pct,
                    data_quality_status=sw.data_quality_status,
                    configuration_version=self.config.configuration_version,
                    engine_version=self.config.engine_version,
                )
                confirmed_highs.append(s_swing)
                classified_swings.append(s_swing)

            elif stype == "LOW":
                if not confirmed_lows:
                    classification = StructuralSwingType.INITIAL
                    prev_id = None
                    price_diff = 0.0
                    price_diff_pct = 0.0
                else:
                    prev_low = confirmed_lows[-1]
                    prev_id = prev_low.event_id
                    price_diff = round(sw.price - prev_low.price, 2)
                    price_diff_pct = round(abs(price_diff) / max(0.01, prev_low.price), 6)

                    if price_diff_pct <= tol_pct:
                        classification = StructuralSwingType.EL
                    elif price_diff > 0:
                        classification = StructuralSwingType.HL
                    else:
                        classification = StructuralSwingType.LL

                s_swing = StructuralSwing(
                    event_id=sw.event_id,
                    index=sw.index,
                    timeframe=sw.timeframe,
                    swing_type="LOW",
                    classification=classification,
                    price=sw.price,
                    bar_index=sw.bar_index,
                    candle_id=sw.candle_id,
                    event_time=sw.event_time,
                    available_at=sw.available_at,
                    source_swing_id=sw.event_id,
                    previous_same_extrema_id=prev_id,
                    price_diff=price_diff,
                    price_diff_pct=price_diff_pct,
                    data_quality_status=sw.data_quality_status,
                    configuration_version=self.config.configuration_version,
                    engine_version=self.config.engine_version,
                )
                confirmed_lows.append(s_swing)
                classified_swings.append(s_swing)

        classified_swings.sort(key=lambda s: (s.event_time, s.available_at))
        return classified_swings

    def detect_structure_breaks(
        self,
        df: pd.DataFrame,
        symbol: str = "NIFTY 50",
        timeframe: str = "15m",
        as_of_time: Optional[datetime] = None,
        data_quality_status: str = "VERIFIED_LIVE",
    ) -> Tuple[List[StructuralSwing], List[ICTEvent], TrendBias]:
        """
        Executes point-in-time market structure break detection:
        - Detects confirmed swing pivots with confirmation delay.
        - Classifies swings into structural hierarchy (HH, HL, LH, LL, EH, EL).
        - Selects active target levels and protected structural levels deterministically.
        - Separates initial structural establishment from continuation BOS and reversal CHoCH.
        - Detects displacement-confirmed Market Structure Shifts (MSS), linked to CHoCH.
        - Prevents duplicate events for previously broken structural levels.
        - Tracks event invalidation while preserving historical confirmation.
        - Rejects wick-only penetrations from confirmed BOS/CHoCH.
        - Ensures zero look-ahead bias and non-repainting determinism.
        """
        self._validate_input_quality(df=df, data_quality_status=data_quality_status)

        if df is None or df.empty:
            return [], [], TrendBias.NEUTRAL

        as_of_dt = _ensure_timezone_aware(as_of_time) if as_of_time else None

        # 1. Detect confirmed swings using Step 3.1 engine
        swings = self.swing_engine.detect_swings(
            df=df,
            symbol=symbol,
            timeframe=timeframe,
            left_bars=self.config.swing_left_bars,
            right_bars=self.config.swing_right_bars,
            tie_breaking_policy=self.config.tie_breaking_policy,
            as_of_time=as_of_dt,
            data_quality_status=data_quality_status,
        )

        # 2. Classify confirmed swings
        classified_swings = self.classify_swings(swings=swings, as_of_time=as_of_dt)

        if not classified_swings:
            return [], [], TrendBias.NEUTRAL

        atr_series = self._compute_atr_series(df, period=14)

        # 3. Candle-by-candle chronological break tracking
        n = len(df)
        c_open = pd.to_numeric(df["open"], errors="coerce").values
        c_high = pd.to_numeric(df["high"], errors="coerce").values
        c_low = pd.to_numeric(df["low"], errors="coerce").values
        c_close = pd.to_numeric(df["close"], errors="coerce").values

        events: List[ICTEvent] = []
        broken_swing_ids: Set[str] = set()

        current_trend = TrendBias.NEUTRAL

        # Active protected and target swing references
        active_target_high: Optional[StructuralSwing] = None
        active_protected_low: Optional[StructuralSwing] = None
        active_target_low: Optional[StructuralSwing] = None
        active_protected_high: Optional[StructuralSwing] = None

        def _get_candle_meta(idx: int) -> Tuple[str, datetime]:
            row = df.iloc[idx]
            ts_val = row.get("timestamp")
            if ts_val is None:
                if isinstance(df.index, pd.DatetimeIndex):
                    ts_val = df.index[idx]
                else:
                    ts_val = f"bar_{idx}"
            dt = _ensure_timezone_aware(ts_val)
            cid = dt.isoformat() if hasattr(dt, "isoformat") else str(ts_val)
            return cid, dt

        # Iterate completed candles
        for k in range(n):
            cid_k, dt_k = _get_candle_meta(k)
            if as_of_dt and dt_k > as_of_dt:
                break

            # Swings available at or before this candle's completion
            avail_swings = [s for s in classified_swings if s.available_at <= dt_k]
            if not avail_swings:
                continue

            avail_highs = [s for s in avail_swings if s.swing_type == "HIGH"]
            avail_lows = [s for s in avail_swings if s.swing_type == "LOW"]

            # Update active targets and protected levels when new swings confirm
            if avail_highs:
                latest_confirmed_h = avail_highs[-1]
                if current_trend == TrendBias.BULLISH:
                    if latest_confirmed_h.event_id not in broken_swing_ids:
                        active_target_high = latest_confirmed_h
                elif current_trend == TrendBias.BEARISH:
                    if latest_confirmed_h.event_id not in broken_swing_ids:
                        active_protected_high = latest_confirmed_h
                else:
                    # In NEUTRAL trend, latest high is baseline target
                    if latest_confirmed_h.event_id not in broken_swing_ids:
                        active_target_high = latest_confirmed_h

            if avail_lows:
                latest_confirmed_l = avail_lows[-1]
                if current_trend == TrendBias.BEARISH:
                    if latest_confirmed_l.event_id not in broken_swing_ids:
                        active_target_low = latest_confirmed_l
                elif current_trend == TrendBias.BULLISH:
                    if latest_confirmed_l.event_id not in broken_swing_ids:
                        active_protected_low = latest_confirmed_l
                else:
                    # In NEUTRAL trend, latest low is baseline target
                    if latest_confirmed_l.event_id not in broken_swing_ids:
                        active_target_low = latest_confirmed_l

            # Establish initial trend if two swings of each type are present and unestablished
            if current_trend == TrendBias.NEUTRAL and len(avail_highs) >= 2 and len(avail_lows) >= 2:
                latest_h = avail_highs[-1]
                latest_l = avail_lows[-1]
                if latest_h.classification == StructuralSwingType.HH and latest_l.classification in (StructuralSwingType.HL, StructuralSwingType.INITIAL):
                    current_trend = TrendBias.BULLISH
                    active_target_high = latest_h
                    active_protected_low = latest_l
                elif latest_h.classification in (StructuralSwingType.LH, StructuralSwingType.INITIAL) and latest_l.classification == StructuralSwingType.LL:
                    current_trend = TrendBias.BEARISH
                    active_target_low = latest_l
                    active_protected_high = latest_h

            bar_open = float(c_open[k])
            bar_high = float(c_high[k])
            bar_low = float(c_low[k])
            bar_close = float(c_close[k])
            bar_range = max(0.01, bar_high - bar_low)
            body_size = abs(bar_close - bar_open)
            body_ratio = round(body_size / bar_range, 4)
            current_atr = float(atr_series[k]) if k < len(atr_series) else 10.0
            atr_mult = round(bar_range / max(0.01, current_atr), 2)

            has_displacement = (
                body_ratio >= self.config.mss_min_body_ratio
                and bar_range >= (self.config.mss_min_atr_multiple * current_atr)
            )

            # -----------------------------------------------------------------
            # 1. Check Bullish Break: Target High (BOS) or Protected High (CHoCH)
            # -----------------------------------------------------------------
            candidate_high = active_protected_high if current_trend == TrendBias.BEARISH else active_target_high
            if candidate_high and candidate_high.event_id not in broken_swing_ids:
                if bar_high > candidate_high.price:
                    is_close_break = bar_close > candidate_high.price
                    if is_close_break or not self.config.require_candle_close:
                        depth = round(bar_close - candidate_high.price, 2) if is_close_break else round(bar_high - candidate_high.price, 2)
                        prev_trend_val = current_trend.value

                        if current_trend == TrendBias.BULLISH:
                            ev_type = ICTEventType.BOS
                            break_class = "CONTINUATION_BOS"
                            new_trend = TrendBias.BULLISH
                            prot_level = active_protected_low.price if active_protected_low else None
                            prot_id = active_protected_low.event_id if active_protected_low else None
                        elif current_trend == TrendBias.BEARISH:
                            ev_type = ICTEventType.CHOCH
                            break_class = "REVERSAL_CHOCH"
                            new_trend = TrendBias.BULLISH
                            current_trend = TrendBias.BULLISH
                            # Update protected level after bullish CHoCH: latest low becomes protected low
                            active_protected_low = avail_lows[-1] if avail_lows else None
                            active_protected_high = None
                            prot_level = active_protected_low.price if active_protected_low else None
                            prot_id = active_protected_low.event_id if active_protected_low else None
                        else:
                            # Initial structural establishment
                            ev_type = ICTEventType.BOS
                            break_class = "INITIAL_ESTABLISHMENT"
                            new_trend = TrendBias.BULLISH
                            current_trend = TrendBias.BULLISH
                            active_protected_low = avail_lows[-1] if avail_lows else None
                            prot_level = active_protected_low.price if active_protected_low else None
                            prot_id = active_protected_low.event_id if active_protected_low else None

                        ev_id = generate_deterministic_event_id(
                            index=symbol,
                            timeframe=timeframe,
                            event_type=ev_type.value,
                            source_candle_id=f"{candidate_high.candle_id}_{cid_k}",
                            configuration_version=self.config.configuration_version,
                        )

                        mss_ev_id = None
                        if ev_type == ICTEventType.CHOCH and has_displacement:
                            mss_ev_id = generate_deterministic_event_id(
                                index=symbol,
                                timeframe=timeframe,
                                event_type=ICTEventType.MSS.value,
                                source_candle_id=f"{candidate_high.candle_id}_{cid_k}",
                                configuration_version=self.config.configuration_version,
                            )

                        evidence = MarketStructureEvidence(
                            broken_level=candidate_high.price,
                            broken_swing_id=candidate_high.event_id,
                            broken_swing_type=candidate_high.classification.value,
                            broken_swing_time=candidate_high.event_time,
                            break_candle_id=cid_k,
                            break_candle_time=dt_k,
                            break_candle_open=bar_open,
                            break_candle_high=bar_high,
                            break_candle_low=bar_low,
                            break_candle_close=bar_close,
                            penetration_depth_pts=depth,
                            is_body_close=is_close_break,
                            body_to_range_ratio=body_ratio,
                            atr=round(current_atr, 2),
                            atr_multiple=atr_mult,
                            previous_trend=prev_trend_val,
                            new_trend=new_trend.value,
                            prior_liquidity_swept=False,
                            displacement_confirmed=has_displacement,
                            break_classification=break_class,
                            protected_level=prot_level,
                            protected_swing_id=prot_id,
                            linked_event_id=mss_ev_id,
                        )

                        ms_event = MarketStructureEvent(
                            event_id=ev_id,
                            index=symbol.upper().strip(),
                            event_type=ev_type,
                            direction=EventDirection.BULLISH,
                            timeframe=timeframe,
                            broken_level=candidate_high.price,
                            event_status=LiquidityLifecycleState.CONFIRMED,
                            event_time=dt_k,
                            available_at=dt_k,
                            created_at=dt_k,
                            confirmed_at=dt_k,
                            source_candle_identifiers=[candidate_high.candle_id, cid_k],
                            data_quality=data_quality_status,
                            evidence=evidence,
                            configuration_version=self.config.configuration_version,
                            engine_version=self.config.engine_version,
                        )
                        events.append(ms_event.to_ict_event())
                        broken_swing_ids.add(candidate_high.event_id)
                        active_target_high = None

                        # If CHoCH with displacement, emit linked MSS event
                        if ev_type == ICTEventType.CHOCH and has_displacement and mss_ev_id:
                            mss_evidence = evidence.model_copy(deep=True)
                            mss_evidence.linked_event_id = ev_id

                            mss_event = MarketStructureEvent(
                                event_id=mss_ev_id,
                                index=symbol.upper().strip(),
                                event_type=ICTEventType.MSS,
                                direction=EventDirection.BULLISH,
                                timeframe=timeframe,
                                broken_level=candidate_high.price,
                                event_status=LiquidityLifecycleState.CONFIRMED,
                                event_time=dt_k,
                                available_at=dt_k,
                                created_at=dt_k,
                                confirmed_at=dt_k,
                                source_candle_identifiers=[candidate_high.candle_id, cid_k],
                                data_quality=data_quality_status,
                                evidence=mss_evidence,
                                configuration_version=self.config.configuration_version,
                                engine_version=self.config.engine_version,
                            )
                            events.append(mss_event.to_ict_event())

            # -----------------------------------------------------------------
            # 2. Check Bearish Break: Target Low (BOS) or Protected Low (CHoCH)
            # -----------------------------------------------------------------
            candidate_low = active_protected_low if current_trend == TrendBias.BULLISH else active_target_low
            if candidate_low and candidate_low.event_id not in broken_swing_ids:
                if bar_low < candidate_low.price:
                    is_close_break = bar_close < candidate_low.price
                    if is_close_break or not self.config.require_candle_close:
                        depth = round(candidate_low.price - bar_close, 2) if is_close_break else round(candidate_low.price - bar_low, 2)
                        prev_trend_val = current_trend.value

                        if current_trend == TrendBias.BEARISH:
                            ev_type = ICTEventType.BOS
                            break_class = "CONTINUATION_BOS"
                            new_trend = TrendBias.BEARISH
                            prot_level = active_protected_high.price if active_protected_high else None
                            prot_id = active_protected_high.event_id if active_protected_high else None
                        elif current_trend == TrendBias.BULLISH:
                            ev_type = ICTEventType.CHOCH
                            break_class = "REVERSAL_CHOCH"
                            new_trend = TrendBias.BEARISH
                            current_trend = TrendBias.BEARISH
                            # Update protected level after bearish CHoCH: latest high becomes protected high
                            active_protected_high = avail_highs[-1] if avail_highs else None
                            active_protected_low = None
                            prot_level = active_protected_high.price if active_protected_high else None
                            prot_id = active_protected_high.event_id if active_protected_high else None
                        else:
                            # Initial structural establishment
                            ev_type = ICTEventType.BOS
                            break_class = "INITIAL_ESTABLISHMENT"
                            new_trend = TrendBias.BEARISH
                            current_trend = TrendBias.BEARISH
                            active_protected_high = avail_highs[-1] if avail_highs else None
                            prot_level = active_protected_high.price if active_protected_high else None
                            prot_id = active_protected_high.event_id if active_protected_high else None

                        ev_id = generate_deterministic_event_id(
                            index=symbol,
                            timeframe=timeframe,
                            event_type=ev_type.value,
                            source_candle_id=f"{candidate_low.candle_id}_{cid_k}",
                            configuration_version=self.config.configuration_version,
                        )

                        mss_ev_id = None
                        if ev_type == ICTEventType.CHOCH and has_displacement:
                            mss_ev_id = generate_deterministic_event_id(
                                index=symbol,
                                timeframe=timeframe,
                                event_type=ICTEventType.MSS.value,
                                source_candle_id=f"{candidate_low.candle_id}_{cid_k}",
                                configuration_version=self.config.configuration_version,
                            )

                        evidence = MarketStructureEvidence(
                            broken_level=candidate_low.price,
                            broken_swing_id=candidate_low.event_id,
                            broken_swing_type=candidate_low.classification.value,
                            broken_swing_time=candidate_low.event_time,
                            break_candle_id=cid_k,
                            break_candle_time=dt_k,
                            break_candle_open=bar_open,
                            break_candle_high=bar_high,
                            break_candle_low=bar_low,
                            break_candle_close=bar_close,
                            penetration_depth_pts=depth,
                            is_body_close=is_close_break,
                            body_to_range_ratio=body_ratio,
                            atr=round(current_atr, 2),
                            atr_multiple=atr_mult,
                            previous_trend=prev_trend_val,
                            new_trend=new_trend.value,
                            prior_liquidity_swept=False,
                            displacement_confirmed=has_displacement,
                            break_classification=break_class,
                            protected_level=prot_level,
                            protected_swing_id=prot_id,
                            linked_event_id=mss_ev_id,
                        )

                        ms_event = MarketStructureEvent(
                            event_id=ev_id,
                            index=symbol.upper().strip(),
                            event_type=ev_type,
                            direction=EventDirection.BEARISH,
                            timeframe=timeframe,
                            broken_level=candidate_low.price,
                            event_status=LiquidityLifecycleState.CONFIRMED,
                            event_time=dt_k,
                            available_at=dt_k,
                            created_at=dt_k,
                            confirmed_at=dt_k,
                            source_candle_identifiers=[candidate_low.candle_id, cid_k],
                            data_quality=data_quality_status,
                            evidence=evidence,
                            configuration_version=self.config.configuration_version,
                            engine_version=self.config.engine_version,
                        )
                        events.append(ms_event.to_ict_event())
                        broken_swing_ids.add(candidate_low.event_id)
                        active_target_low = None

                        # If CHoCH with displacement, emit linked MSS event
                        if ev_type == ICTEventType.CHOCH and has_displacement and mss_ev_id:
                            mss_evidence = evidence.model_copy(deep=True)
                            mss_evidence.linked_event_id = ev_id

                            mss_event = MarketStructureEvent(
                                event_id=mss_ev_id,
                                index=symbol.upper().strip(),
                                event_type=ICTEventType.MSS,
                                direction=EventDirection.BEARISH,
                                timeframe=timeframe,
                                broken_level=candidate_low.price,
                                event_status=LiquidityLifecycleState.CONFIRMED,
                                event_time=dt_k,
                                available_at=dt_k,
                                created_at=dt_k,
                                confirmed_at=dt_k,
                                source_candle_identifiers=[candidate_low.candle_id, cid_k],
                                data_quality=data_quality_status,
                                evidence=mss_evidence,
                                configuration_version=self.config.configuration_version,
                                engine_version=self.config.engine_version,
                            )
                            events.append(mss_event.to_ict_event())

            # -----------------------------------------------------------------
            # 3. Check Invalidation of Active Events on Subsequent Price Action
            # -----------------------------------------------------------------
            if self.config.enable_invalidation_tracking:
                buffer_pts = self.config.invalidation_reclose_threshold_pts
                for ev in events:
                    if ev.event_status == LiquidityLifecycleState.CONFIRMED and ev.available_at < dt_k:
                        # Bullish break invalidated if subsequent candle closes back below broken level
                        if ev.direction == EventDirection.BULLISH and ev.price_level is not None:
                            if bar_close < (ev.price_level - buffer_pts):
                                ev.event_status = LiquidityLifecycleState.INVALIDATED
                                ev.invalidated_at = dt_k
                                ev.evidence["invalidation_reason"] = (
                                    f"Price closed back below broken level {ev.price_level} at {bar_close}"
                                )
                                # Historical confirmation timestamp remains strictly preserved

                        # Bearish break invalidated if subsequent candle closes back above broken level
                        elif ev.direction == EventDirection.BEARISH and ev.price_level is not None:
                            if bar_close > (ev.price_level + buffer_pts):
                                ev.event_status = LiquidityLifecycleState.INVALIDATED
                                ev.invalidated_at = dt_k
                                ev.evidence["invalidation_reason"] = (
                                    f"Price closed back above broken level {ev.price_level} at {bar_close}"
                                )
                                # Historical confirmation timestamp remains strictly preserved

        return classified_swings, events, current_trend

    def analyze_timeframe(
        self,
        df: pd.DataFrame,
        symbol: str = "NIFTY 50",
        timeframe: str = "15m",
        as_of_time: Optional[datetime] = None,
        data_quality_status: str = "VERIFIED_LIVE",
    ) -> TimeframeStructureReport:
        """
        Produces a complete, self-contained Market Structure Intelligence Report
        for a single timeframe without any cross-timeframe coupling.
        """
        swings, events, trend = self.detect_structure_breaks(
            df=df,
            symbol=symbol,
            timeframe=timeframe,
            as_of_time=as_of_time,
            data_quality_status=data_quality_status,
        )

        bos_c = sum(1 for e in events if e.event_type == ICTEventType.BOS)
        choch_c = sum(1 for e in events if e.event_type == ICTEventType.CHOCH)
        mss_c = sum(1 for e in events if e.event_type == ICTEventType.MSS)

        highs = [s for s in swings if s.swing_type == "HIGH"]
        lows = [s for s in swings if s.swing_type == "LOW"]

        # Deterministic protected and target swing determination for output report
        prot_high = highs[-1] if (trend == TrendBias.BEARISH and highs) else None
        prot_low = lows[-1] if (trend == TrendBias.BULLISH and lows) else None
        tgt_high = highs[-1] if (trend == TrendBias.BULLISH and highs) else None
        tgt_low = lows[-1] if (trend == TrendBias.BEARISH and lows) else None

        return TimeframeStructureReport(
            index=symbol.upper().strip(),
            timeframe=timeframe,
            data_quality=data_quality_status,
            active_trend=trend,
            classified_swings=swings,
            structure_events=events,
            bos_count=bos_c,
            choch_count=choch_c,
            mss_count=mss_c,
            last_swing_high=highs[-1] if highs else None,
            last_swing_low=lows[-1] if lows else None,
            active_protected_high=prot_high,
            active_protected_low=prot_low,
            active_target_high=tgt_high,
            active_target_low=tgt_low,
            latest_event=events[-1] if events else None,
            as_of_time=_ensure_timezone_aware(as_of_time) if as_of_time else None,
            configuration_version=self.config.configuration_version,
            engine_version=self.config.engine_version,
        )

    def analyze_multi_timeframe(
        self,
        data_by_tf: Dict[str, pd.DataFrame],
        symbol: str = "NIFTY 50",
        as_of_time: Optional[datetime] = None,
        data_quality_status: str = "VERIFIED_LIVE",
    ) -> Dict[str, TimeframeStructureReport]:
        """
        Executes strict multi-timeframe structural analysis across 1H, 15M, 5M, 3M, 1M.
        Guarantees complete isolation between timeframes: no swing points, events, or
        trend biases are mixed across timeframes.
        """
        results: Dict[str, TimeframeStructureReport] = {}
        supported_tfs = ["1h", "15m", "5m", "3m", "1m"]

        for tf in supported_tfs:
            if tf in data_by_tf:
                df_tf = data_by_tf[tf]
                report = self.analyze_timeframe(
                    df=df_tf,
                    symbol=symbol,
                    timeframe=tf,
                    as_of_time=as_of_time,
                    data_quality_status=data_quality_status,
                )
                results[tf] = report

        return results
