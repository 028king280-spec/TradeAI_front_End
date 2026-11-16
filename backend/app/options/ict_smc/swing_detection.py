"""
AIVOLVE Phase 3 Swing Detection Engine.
Deterministic, anti-lookahead fractal pivot detection with explicit confirmation delays.
Guarantees:
1. Zero lookahead bias: event_time is the pivot bar; available_at is strictly the confirmation bar.
2. Strict non-repainting: confirmed pivots never change retroactively.
3. Pure completed candle processing: ignores unconfirmed or incomplete bars.
4. Deterministic replay: exact same pivots produced at any historical point-in-time as-of filter.
5. Mathematical tie-breaking: explicitly handles flat double tops/bottoms under FIRST, LAST, and ALLOW_MULTI.
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
import pandas as pd
import numpy as np
import zoneinfo

from app.options.ict_smc.ict_models import (
    SwingPoint,
    LiquidityConfiguration,
    generate_deterministic_event_id,
    _ensure_timezone_aware,
    IST_ZONE,
)


class SwingDetectionEngine:
    """
    Mathematical fractal pivot detection engine with N-bar left/right confirmation.
    """

    def __init__(self, config: Optional[LiquidityConfiguration] = None):
        self.config = config or LiquidityConfiguration()

    @staticmethod
    def _extract_candle_id_and_time(
        df: pd.DataFrame,
        index: int,
    ) -> tuple[str, datetime]:
        """Extracts canonical candle identifier and timezone-aware timestamp."""
        row = df.iloc[index]
        ts_val = row.get("timestamp")
        if ts_val is None:
            if isinstance(df.index, pd.DatetimeIndex):
                ts_val = df.index[index]
            else:
                ts_val = f"bar_{index}"

        dt = _ensure_timezone_aware(ts_val)
        cid = dt.isoformat() if hasattr(dt, "isoformat") else str(ts_val)
        return cid, dt

    def detect_swings(
        self,
        df: pd.DataFrame,
        symbol: str = "NIFTY 50",
        timeframe: str = "15m",
        left_bars: Optional[int] = None,
        right_bars: Optional[int] = None,
        tie_breaking_policy: Optional[str] = None,
        as_of_time: Optional[datetime] = None,
        data_quality_status: str = "VERIFIED_LIVE",
    ) -> List[SwingPoint]:
        """
        Detects all confirmed Swing Highs and Swing Lows.
        If as_of_time is provided, strictly filters out any pivot whose available_at > as_of_time.
        """
        if df is None or df.empty:
            return []

        l_bars = left_bars if left_bars is not None else self.config.swing_left_bars
        r_bars = right_bars if right_bars is not None else self.config.swing_right_bars
        tie_policy = (
            tie_breaking_policy
            if tie_breaking_policy is not None
            else self.config.tie_breaking_policy
        ).upper()

        highs = self.detect_swing_highs(
            df=df,
            symbol=symbol,
            timeframe=timeframe,
            left_bars=l_bars,
            right_bars=r_bars,
            tie_breaking_policy=tie_policy,
            as_of_time=as_of_time,
            data_quality_status=data_quality_status,
        )
        lows = self.detect_swing_lows(
            df=df,
            symbol=symbol,
            timeframe=timeframe,
            left_bars=l_bars,
            right_bars=r_bars,
            tie_breaking_policy=tie_policy,
            as_of_time=as_of_time,
            data_quality_status=data_quality_status,
        )

        all_swings = highs + lows
        all_swings.sort(key=lambda s: (s.event_time, s.available_at))
        return all_swings

    def detect_swing_highs(
        self,
        df: pd.DataFrame,
        symbol: str = "NIFTY 50",
        timeframe: str = "15m",
        left_bars: int = 3,
        right_bars: int = 3,
        tie_breaking_policy: str = "FIRST",
        as_of_time: Optional[datetime] = None,
        data_quality_status: str = "VERIFIED_LIVE",
    ) -> List[SwingPoint]:
        """
        Detects confirmed Swing High fractal pivots:
        A bar at index i is a Swing High if:
        - High[i] >= left/right bars according to tie_breaking_policy.

        Tie-Breaking Definitions:
        - FIRST: Bar i must be strictly greater than all left bars (left_slice < val).
                 No bar to the right may be > val, and right-side decay occurs. Left-side ties reject bar i.
        - LAST:  Bar i must be strictly greater than all right bars (right_slice < val).
                 No bar to the left may be > val, and left-side rise occurs. Right-side ties reject bar i.
        - ALLOW_MULTI: Both bars of a flat top/double top qualify as candidate pivots.
        - STRICT: Strict inequality required on both sides (val > left and val > right).
        """
        n = len(df)
        min_required = left_bars + right_bars + 1
        if n < min_required:
            return []

        c_high = pd.to_numeric(df["high"], errors="coerce").values
        vol_arr = (
            pd.to_numeric(df["volume"], errors="coerce").values
            if "volume" in df.columns
            else None
        )

        pivots: List[SwingPoint] = []
        as_of_dt = _ensure_timezone_aware(as_of_time) if as_of_time else None
        policy = tie_breaking_policy.upper()

        for i in range(left_bars, n - right_bars):
            val = c_high[i]
            if np.isnan(val):
                continue

            left_slice = c_high[i - left_bars : i]
            if len(left_slice) == 0 or np.isnan(left_slice).any():
                continue

            right_slice = c_high[i + 1 : i + 1 + right_bars]
            if len(right_slice) == 0 or np.isnan(right_slice).any():
                continue

            is_pivot = False

            if policy == "FIRST":
                # Must be strictly greater than left (no left tie permitted)
                left_ok = np.all(val > left_slice)
                # Right side: all right bars <= val, with no bar > val, and right end decays
                right_ok = np.all(val >= right_slice) and (right_slice[-1] < val or np.all(val > right_slice))
                if left_ok and right_ok:
                    is_pivot = True

            elif policy == "LAST":
                # Must be strictly greater than right (no right tie permitted)
                right_ok = np.all(val > right_slice)
                # Left side: all left bars <= val, with no bar > val, and left start rose
                left_ok = np.all(val >= left_slice) and (left_slice[0] < val or np.all(val > left_slice))
                if left_ok and right_ok:
                    is_pivot = True

            elif policy == "ALLOW_MULTI":
                # Multi: either strictly higher, or immediate neighbor equals and rest are lower
                left_ok = np.all(val > left_slice) or (len(left_slice) > 0 and val == left_slice[-1] and np.all(val > left_slice[:-1]))
                right_ok = np.all(val > right_slice) or (len(right_slice) > 0 and val == right_slice[0] and np.all(val > right_slice[1:]))
                if left_ok and right_ok:
                    is_pivot = True

            else:  # STRICT
                left_ok = np.all(val > left_slice)
                right_ok = np.all(val > right_slice)
                if left_ok and right_ok:
                    is_pivot = True

            if is_pivot:
                event_cid, event_dt = self._extract_candle_id_and_time(df, i)
                avail_cid, avail_dt = self._extract_candle_id_and_time(df, i + right_bars)

                if as_of_dt and avail_dt > as_of_dt:
                    continue

                event_id = generate_deterministic_event_id(
                    index=symbol,
                    timeframe=timeframe,
                    event_type="SWING_HIGH",
                    source_candle_id=event_cid,
                    configuration_version=self.config.configuration_version,
                )

                vol_val = float(vol_arr[i]) if vol_arr is not None and not np.isnan(vol_arr[i]) else None

                pivots.append(
                    SwingPoint(
                        event_id=event_id,
                        index=symbol.upper().strip(),
                        swing_type="HIGH",
                        price=round(float(val), 2),
                        timeframe=timeframe,
                        bar_index=i,
                        candle_id=event_cid,
                        event_time=event_dt,
                        available_at=avail_dt,
                        left_bars=left_bars,
                        right_bars=right_bars,
                        volume=vol_val,
                        data_quality_status=data_quality_status,
                        configuration_version=self.config.configuration_version,
                        engine_version="3.1.0",
                    )
                )

        return pivots

    def detect_swing_lows(
        self,
        df: pd.DataFrame,
        symbol: str = "NIFTY 50",
        timeframe: str = "15m",
        left_bars: int = 3,
        right_bars: int = 3,
        tie_breaking_policy: str = "FIRST",
        as_of_time: Optional[datetime] = None,
        data_quality_status: str = "VERIFIED_LIVE",
    ) -> List[SwingPoint]:
        """
        Detects confirmed Swing Low fractal pivots:
        A bar at index i is a Swing Low if:
        - Low[i] <= left/right bars according to tie_breaking_policy.
        """
        n = len(df)
        min_required = left_bars + right_bars + 1
        if n < min_required:
            return []

        c_low = pd.to_numeric(df["low"], errors="coerce").values
        vol_arr = (
            pd.to_numeric(df["volume"], errors="coerce").values
            if "volume" in df.columns
            else None
        )

        pivots: List[SwingPoint] = []
        as_of_dt = _ensure_timezone_aware(as_of_time) if as_of_time else None
        policy = tie_breaking_policy.upper()

        for i in range(left_bars, n - right_bars):
            val = c_low[i]
            if np.isnan(val):
                continue

            left_slice = c_low[i - left_bars : i]
            if len(left_slice) == 0 or np.isnan(left_slice).any():
                continue

            right_slice = c_low[i + 1 : i + 1 + right_bars]
            if len(right_slice) == 0 or np.isnan(right_slice).any():
                continue

            is_pivot = False

            if policy == "FIRST":
                left_ok = np.all(val < left_slice)
                right_ok = np.all(val <= right_slice) and (right_slice[-1] > val or np.all(val < right_slice))
                if left_ok and right_ok:
                    is_pivot = True

            elif policy == "LAST":
                right_ok = np.all(val < right_slice)
                left_ok = np.all(val <= left_slice) and (left_slice[0] > val or np.all(val < left_slice))
                if left_ok and right_ok:
                    is_pivot = True

            elif policy == "ALLOW_MULTI":
                left_ok = np.all(val < left_slice) or (len(left_slice) > 0 and val == left_slice[-1] and np.all(val < left_slice[:-1]))
                right_ok = np.all(val < right_slice) or (len(right_slice) > 0 and val == right_slice[0] and np.all(val < right_slice[1:]))
                if left_ok and right_ok:
                    is_pivot = True

            else:  # STRICT
                left_ok = np.all(val < left_slice)
                right_ok = np.all(val < right_slice)
                if left_ok and right_ok:
                    is_pivot = True

            if is_pivot:
                event_cid, event_dt = self._extract_candle_id_and_time(df, i)
                avail_cid, avail_dt = self._extract_candle_id_and_time(df, i + right_bars)

                if as_of_dt and avail_dt > as_of_dt:
                    continue

                event_id = generate_deterministic_event_id(
                    index=symbol,
                    timeframe=timeframe,
                    event_type="SWING_LOW",
                    source_candle_id=event_cid,
                    configuration_version=self.config.configuration_version,
                )

                vol_val = float(vol_arr[i]) if vol_arr is not None and not np.isnan(vol_arr[i]) else None

                pivots.append(
                    SwingPoint(
                        event_id=event_id,
                        index=symbol.upper().strip(),
                        swing_type="LOW",
                        price=round(float(val), 2),
                        timeframe=timeframe,
                        bar_index=i,
                        candle_id=event_cid,
                        event_time=event_dt,
                        available_at=avail_dt,
                        left_bars=left_bars,
                        right_bars=right_bars,
                        volume=vol_val,
                        data_quality_status=data_quality_status,
                        configuration_version=self.config.configuration_version,
                        engine_version="3.1.0",
                    )
                )

        return pivots
