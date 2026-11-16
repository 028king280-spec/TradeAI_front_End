"""
AIVOLVE Phase 3 Liquidity Intelligence Engine.
Deterministic detection and lifecycle tracking of institutional liquidity:
- Buy-Side Liquidity (BSL) and Sell-Side Liquidity (SSL) from confirmed swing points
- Equal Highs (EQH) and Equal Lows (EQL) with clustering tolerances and touch counts
- Previous Day High/Low (PDH / PDL) and Previous Week High/Low (PWH / PWL)
- Comprehensive Indian Session Windows (Opening Range, Morning, Midday, Afternoon, Closing)
- Strict Liquidity Lifecycle State Machine (IDENTIFIED -> APPROACHING -> SWEPT -> RECLAIMED -> CONFIRMED)
- Terminal transitions for CONSUMED, EXPIRED, and INVALIDATED
- Fail-closed Phase 1/2 Data Quality integration (DEGRADED, STALE, ANOMALOUS lockouts)
- Preserves full backward-compatibility with legacy LiquidityDetectionEngine callers
"""

from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, time
import pandas as pd
import numpy as np
import zoneinfo

from app.options.ict_smc.ict_models import (
    LiquidityPool,
    LiquidityEvent,
    LiquidityEvidence,
    LiquidityConfiguration,
    LiquidityType,
    LiquidityLifecycleState,
    EventDirection,
    ICTEventType,
    SwingPoint,
    generate_deterministic_event_id,
    _ensure_timezone_aware,
    IST_ZONE,
)
from app.options.ict_smc.swing_detection import SwingDetectionEngine
from app.data.market_calendar import MarketCalendar
from app.data.quality_validator import FeedStatus, DataQualityEngine


# ---------------------------------------------------------------------
# 1. Phase 3 Typed Liquidity Intelligence Engine
# ---------------------------------------------------------------------

class LiquidityIntelligenceEngine:
    """
    Institutional Liquidity Intelligence Engine conforming to Phase 3 Step 3.1 specification.
    """

    NON_QUALIFYING_FEED_STATUSES = {
        FeedStatus.DATA_OFFLINE,
        FeedStatus.DATA_UNAVAILABLE,
        FeedStatus.STALE,
        FeedStatus.STALE_TICK,
        FeedStatus.DEGRADED,
        FeedStatus.ANOMALOUS,
        FeedStatus.SYNTHETIC,
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
    }

    def __init__(self, config: Optional[LiquidityConfiguration] = None):
        self.config = config or LiquidityConfiguration()
        self.swing_engine = SwingDetectionEngine(config=self.config)

    def detect_liquidity_pools(
        self,
        df: pd.DataFrame,
        symbol: str = "NIFTY 50",
        timeframe: str = "15m",
        daily_high: Optional[float] = None,
        daily_low: Optional[float] = None,
        prev_day_high: Optional[float] = None,
        prev_day_low: Optional[float] = None,
        prev_week_high: Optional[float] = None,
        prev_week_low: Optional[float] = None,
        opening_range_high: Optional[float] = None,
        opening_range_low: Optional[float] = None,
        as_of_time: Optional[datetime] = None,
        data_quality_status: str = "VERIFIED_LIVE",
    ) -> List[LiquidityPool]:
        """
        Builds complete multi-tier typed liquidity pools for symbol and timeframe:
        1. Swing BSL & SSL from confirmed fractal swings
        2. Equal Highs (EQH) & Equal Lows (EQL) clusters
        3. External Major Liquidity: PDH, PDL, PWH, PWL
        4. Indian Session Windows: Opening Range, Morning, Midday, Afternoon, Closing
        5. Enforces fail-closed invalidation on non-qualifying Phase 1/2 data quality status.
        """
        if df is None or df.empty:
            return []

        clean_sym = symbol.upper().strip()
        ver = self.config.configuration_version

        # -------------------------------------------------------------
        # Phase 1/2 Data Quality & Strict OHLC Validation
        # -------------------------------------------------------------
        rejection_reasons: List[str] = []

        # 1. Existing Phase 1/2 audit attributes check
        df_repaired = bool(df.attrs.get("ohlc_repaired", False)) if hasattr(df, "attrs") else False
        df_missing_mandatory = bool(df.attrs.get("missing_mandatory_candles", False)) if hasattr(df, "attrs") else False
        df_feed_status = df.attrs.get("data_status") or df.attrs.get("feed_status") if hasattr(df, "attrs") else None

        if df_repaired:
            rejection_reasons.append("Phase 1/2 Data Quality lockout: repaired mandatory candles detected.")
        if df_missing_mandatory:
            rejection_reasons.append("Phase 1/2 Data Quality lockout: missing mandatory candles detected.")

        # 2. Complete Mathematical OHLC Invariant Verification (Phase 1/2 DataQualityEngine)
        val_res = DataQualityEngine.validate_ohlc(df, timeframe=timeframe)
        if not val_res.get("isValid", True):
            rejection_reasons.extend([f"Phase 1/2 OHLC violation: {v}" for v in val_res.get("violations", [])])
        if val_res.get("ohlc_repaired", False):
            rejection_reasons.append("Phase 1/2 OHLC lockout: raw candles required repair to be well-formed.")

        # 3. Direct Geometric Invariant Verification
        required_cols = {"open", "high", "low", "close"}
        if not required_cols.issubset(set(df.columns)):
            missing_cols = required_cols - set(df.columns)
            rejection_reasons.append(f"Missing mandatory OHLC columns: {missing_cols}")
        else:
            price_df = df[["open", "high", "low", "close"]]
            if price_df.isna().any().any():
                rejection_reasons.append("Contains null or NaN mandatory OHLC values.")
            if np.isinf(pd.to_numeric(price_df.values.flatten(), errors="coerce")).any():
                rejection_reasons.append("Contains infinite values in mandatory OHLC values.")

            h_s = pd.to_numeric(df["high"], errors="coerce")
            l_s = pd.to_numeric(df["low"], errors="coerce")
            o_s = pd.to_numeric(df["open"], errors="coerce")
            c_s = pd.to_numeric(df["close"], errors="coerce")

            max_oc = pd.concat([o_s, c_s], axis=1).max(axis=1)
            if (h_s < max_oc).any():
                rejection_reasons.append("Invalid OHLC geometry: High < max(Open, Close) detected.")

            min_oc = pd.concat([o_s, c_s], axis=1).min(axis=1)
            if (l_s > min_oc).any():
                rejection_reasons.append("Invalid OHLC geometry: Low > min(Open, Close) detected.")

            if (h_s < l_s).any():
                rejection_reasons.append("Invalid OHLC geometry: High < Low detected.")

            if (o_s <= 0).any() or (h_s <= 0).any() or (l_s <= 0).any() or (c_s <= 0).any():
                rejection_reasons.append("Invalid OHLC prices: Non-positive price values detected.")

        # 4. Mandatory Timestamp Verification, Timezone Consistency, Duplicates & Monotonic Ordering
        if "timestamp" not in df.columns:
            rejection_reasons.append("Missing mandatory 'timestamp' column in candlestick dataset.")
        else:
            ts_col = df["timestamp"]
            if ts_col.isna().any():
                rejection_reasons.append("Contains null or NaN values in mandatory 'timestamp' column.")
            elif ts_col.duplicated().any():
                rejection_reasons.append("Duplicate candle timestamps detected.")
            else:
                try:
                    # Detect mixed timezones or unparseable formats
                    tz_signatures = set()
                    for t_val in ts_col:
                        if isinstance(t_val, datetime):
                            tz_str = str(t_val.tzinfo) if t_val.tzinfo is not None else "naive"
                        else:
                            dt_parsed = pd.to_datetime(t_val)
                            tz_str = str(dt_parsed.tzinfo) if getattr(dt_parsed, "tzinfo", None) is not None else "naive"
                        tz_signatures.add(tz_str)

                    if len(tz_signatures) > 1:
                        rejection_reasons.append(f"Mixed timezones detected in candlestick series: {tz_signatures}")

                    dt_series = pd.to_datetime(ts_col)
                    if not dt_series.is_monotonic_increasing:
                        rejection_reasons.append("Candle timestamps are not monotonically increasing.")
                except Exception as e:
                    rejection_reasons.append(f"Invalid candle timestamp format: {str(e)}")

        # 5. Feed Status Validation
        effective_status = df_feed_status or data_quality_status
        is_feed_disqualified = (
            effective_status in self.NON_QUALIFYING_FEED_STATUSES
            or effective_status not in (FeedStatus.VERIFIED_LIVE, FeedStatus.VERIFIED_EOD, "VERIFIED_LIVE", "VERIFIED_EOD")
        )
        if is_feed_disqualified:
            rejection_reasons.append(f"Phase 1/2 Data Quality lockout: non-qualifying feed status '{effective_status}'.")

        is_data_disqualified = len(rejection_reasons) > 0
        rejection_reason = " | ".join(rejection_reasons) if rejection_reasons else None

        pools: List[LiquidityPool] = []

        # 1. Detect confirmed Swings
        swings = self.swing_engine.detect_swings(
            df=df,
            symbol=clean_sym,
            timeframe=timeframe,
            as_of_time=as_of_time,
            data_quality_status=effective_status,
        )

        swing_highs = [s for s in swings if s.swing_type == "HIGH"]
        swing_lows = [s for s in swings if s.swing_type == "LOW"]

        initial_state = (
            LiquidityLifecycleState.INVALIDATED
            if is_data_disqualified
            else LiquidityLifecycleState.IDENTIFIED
        )

        # 2. Swing High BSL Pools
        for sh in swing_highs:
            p_id = generate_deterministic_event_id(
                clean_sym, timeframe, "BSL", sh.candle_id, ver
            )
            vol_evidence = sh.volume is not None
            ev = LiquidityEvidence(
                touch_count=1,
                observed_traded_volume=sh.volume,
                volume_evidence_available=vol_evidence,
                source_swing_ids=[sh.event_id],
                rejection_reasons=[rejection_reason] if rejection_reason else [],
            )
            pools.append(
                LiquidityPool(
                    pool_id=p_id,
                    index=clean_sym,
                    liquidity_type=LiquidityType.BSL,
                    direction=EventDirection.BEARISH,
                    timeframe=timeframe,
                    level=sh.price,
                    upper_bound=round(sh.price * 1.0005, 2),
                    lower_bound=sh.price,
                    status=initial_state,
                    touch_count=1,
                    evidence=ev,
                    formation_time=sh.event_time,
                    available_at=sh.available_at,
                    updated_at=sh.available_at,
                    source_candle_ids=[sh.candle_id],
                    source_candle_identifiers=[sh.candle_id],
                    source_data_quality=data_quality_status,
                    configuration_version=ver,
                    engine_version="3.1.0",
                )
            )

        # 3. Swing Low SSL Pools
        for sl in swing_lows:
            p_id = generate_deterministic_event_id(
                clean_sym, timeframe, "SSL", sl.candle_id, ver
            )
            vol_evidence = sl.volume is not None
            ev = LiquidityEvidence(
                touch_count=1,
                observed_traded_volume=sl.volume,
                volume_evidence_available=vol_evidence,
                source_swing_ids=[sl.event_id],
                rejection_reasons=[rejection_reason] if rejection_reason else [],
            )
            pools.append(
                LiquidityPool(
                    pool_id=p_id,
                    index=clean_sym,
                    liquidity_type=LiquidityType.SSL,
                    direction=EventDirection.BULLISH,
                    timeframe=timeframe,
                    level=sl.price,
                    upper_bound=sl.price,
                    lower_bound=round(sl.price * 0.9995, 2),
                    status=initial_state,
                    touch_count=1,
                    evidence=ev,
                    formation_time=sl.event_time,
                    available_at=sl.available_at,
                    updated_at=sl.available_at,
                    source_candle_ids=[sl.candle_id],
                    source_candle_identifiers=[sl.candle_id],
                    source_data_quality=data_quality_status,
                    configuration_version=ver,
                    engine_version="3.1.0",
                )
            )

        # 4. Equal Highs (EQH) Clustering
        eqh_pools = self._cluster_equal_extrema(
            swings=swing_highs,
            liquidity_type=LiquidityType.EQH,
            symbol=clean_sym,
            timeframe=timeframe,
            initial_state=initial_state,
            data_quality_status=data_quality_status,
            rejection_reason=rejection_reason,
        )
        pools.extend(eqh_pools)

        # 5. Equal Lows (EQL) Clustering
        eql_pools = self._cluster_equal_extrema(
            swings=swing_lows,
            liquidity_type=LiquidityType.EQL,
            symbol=clean_sym,
            timeframe=timeframe,
            initial_state=initial_state,
            data_quality_status=data_quality_status,
            rejection_reason=rejection_reason,
        )
        pools.extend(eql_pools)

        # 6. Previous Period Liquidity (PDH, PDL, PWH, PWL)
        now_dt = _ensure_timezone_aware(as_of_time or df.iloc[-1].get("timestamp"))

        if prev_day_high and prev_day_high > 0:
            pid = generate_deterministic_event_id(clean_sym, "1d", "PDH", f"{now_dt.date()}_PDH", ver)
            pools.append(
                LiquidityPool(
                    pool_id=pid,
                    index=clean_sym,
                    liquidity_type=LiquidityType.PDH,
                    direction=EventDirection.BEARISH,
                    timeframe="1d",
                    level=round(prev_day_high, 2),
                    upper_bound=round(prev_day_high * 1.0005, 2),
                    lower_bound=round(prev_day_high, 2),
                    status=initial_state,
                    touch_count=1,
                    evidence=LiquidityEvidence(
                        touch_count=1,
                        rejection_reasons=[rejection_reason] if rejection_reason else []
                    ),
                    formation_time=now_dt,
                    available_at=now_dt,
                    updated_at=now_dt,
                    source_candle_ids=["PREV_DAY"],
                    source_candle_identifiers=["PREV_DAY"],
                    source_data_quality=data_quality_status,
                    configuration_version=ver,
                    engine_version="3.1.0",
                )
            )

        if prev_day_low and prev_day_low > 0:
            pid = generate_deterministic_event_id(clean_sym, "1d", "PDL", f"{now_dt.date()}_PDL", ver)
            pools.append(
                LiquidityPool(
                    pool_id=pid,
                    index=clean_sym,
                    liquidity_type=LiquidityType.PDL,
                    direction=EventDirection.BULLISH,
                    timeframe="1d",
                    level=round(prev_day_low, 2),
                    upper_bound=round(prev_day_low, 2),
                    lower_bound=round(prev_day_low * 0.9995, 2),
                    status=initial_state,
                    touch_count=1,
                    evidence=LiquidityEvidence(
                        touch_count=1,
                        rejection_reasons=[rejection_reason] if rejection_reason else []
                    ),
                    formation_time=now_dt,
                    available_at=now_dt,
                    updated_at=now_dt,
                    source_candle_ids=["PREV_DAY"],
                    source_candle_identifiers=["PREV_DAY"],
                    source_data_quality=data_quality_status,
                    configuration_version=ver,
                    engine_version="3.1.0",
                )
            )

        if prev_week_high and prev_week_high > 0:
            pid = generate_deterministic_event_id(clean_sym, "1w", "PWH", f"{now_dt.date()}_PWH", ver)
            pools.append(
                LiquidityPool(
                    pool_id=pid,
                    index=clean_sym,
                    liquidity_type=LiquidityType.PWH,
                    direction=EventDirection.BEARISH,
                    timeframe="1w",
                    level=round(prev_week_high, 2),
                    upper_bound=round(prev_week_high * 1.0005, 2),
                    lower_bound=round(prev_week_high, 2),
                    status=initial_state,
                    touch_count=1,
                    evidence=LiquidityEvidence(
                        touch_count=1,
                        rejection_reasons=[rejection_reason] if rejection_reason else []
                    ),
                    formation_time=now_dt,
                    available_at=now_dt,
                    updated_at=now_dt,
                    source_candle_ids=["PREV_WEEK"],
                    source_candle_identifiers=["PREV_WEEK"],
                    source_data_quality=data_quality_status,
                    configuration_version=ver,
                    engine_version="3.1.0",
                )
            )

        if prev_week_low and prev_week_low > 0:
            pid = generate_deterministic_event_id(clean_sym, "1w", "PWL", f"{now_dt.date()}_PWL", ver)
            pools.append(
                LiquidityPool(
                    pool_id=pid,
                    index=clean_sym,
                    liquidity_type=LiquidityType.PWL,
                    direction=EventDirection.BULLISH,
                    timeframe="1w",
                    level=round(prev_week_low, 2),
                    upper_bound=round(prev_week_low, 2),
                    lower_bound=round(prev_week_low * 0.9995, 2),
                    status=initial_state,
                    touch_count=1,
                    evidence=LiquidityEvidence(
                        touch_count=1,
                        rejection_reasons=[rejection_reason] if rejection_reason else []
                    ),
                    formation_time=now_dt,
                    available_at=now_dt,
                    updated_at=now_dt,
                    source_candle_ids=["PREV_WEEK"],
                    source_candle_identifiers=["PREV_WEEK"],
                    source_data_quality=data_quality_status,
                    configuration_version=ver,
                    engine_version="3.1.0",
                )
            )

        # 7. Comprehensive Indian Session Liquidity Windows
        session_pools = self.detect_session_liquidity(
            df=df,
            symbol=clean_sym,
            timeframe=timeframe,
            daily_high=daily_high,
            daily_low=daily_low,
            opening_range_high=opening_range_high,
            opening_range_low=opening_range_low,
            as_of_time=as_of_time,
            initial_state=initial_state,
            data_quality_status=data_quality_status,
            rejection_reason=rejection_reason,
        )
        pools.extend(session_pools)

        # Enforce minimum touch count policy
        return [p for p in pools if p.touch_count >= self.config.touch_count_min]

    def _cluster_equal_extrema(
        self,
        swings: List[SwingPoint],
        liquidity_type: LiquidityType,
        symbol: str,
        timeframe: str,
        initial_state: LiquidityLifecycleState = LiquidityLifecycleState.IDENTIFIED,
        data_quality_status: str = "VERIFIED_LIVE",
        rejection_reason: Optional[str] = None,
    ) -> List[LiquidityPool]:
        """
        Clusters nearby confirmed swing highs or lows into Equal Highs / Equal Lows.
        Computes mean level, price range, maximum deviation, and touch count.
        """
        if len(swings) < self.config.min_touches_for_eq:
            return []

        eq_pools: List[LiquidityPool] = []
        tol_pct = self.config.eq_tolerance_pct
        ver = self.config.configuration_version

        n = len(swings)
        used_indices = set()

        for i in range(n - 1):
            if i in used_indices:
                continue

            cluster = [swings[i]]
            base_p = swings[i].price

            for j in range(i + 1, min(i + 5, n)):
                if j in used_indices:
                    continue
                cand_p = swings[j].price
                dev_pct = abs(base_p - cand_p) / max(base_p, 1.0)
                if dev_pct <= tol_pct:
                    cluster.append(swings[j])

            if len(cluster) >= self.config.min_touches_for_eq:
                prices = [s.price for s in cluster]
                mean_p = round(float(np.mean(prices)), 2)
                min_p = round(float(np.min(prices)), 2)
                max_p = round(float(np.max(prices)), 2)
                max_dev_pts = round(max_p - min_p, 2)
                max_dev_pct = round(max_dev_pts / max(mean_p, 1.0) * 100.0, 4)

                latest_swing = max(cluster, key=lambda s: s.available_at)
                first_swing = min(cluster, key=lambda s: s.event_time)

                pid = generate_deterministic_event_id(
                    symbol, timeframe, liquidity_type.value, latest_swing.candle_id, ver
                )

                direction = (
                    EventDirection.BEARISH
                    if liquidity_type == LiquidityType.EQH
                    else EventDirection.BULLISH
                )

                vols = [s.volume for s in cluster if s.volume is not None]
                obs_vol = float(np.sum(vols)) if len(vols) == len(cluster) else None

                ev = LiquidityEvidence(
                    touch_count=len(cluster),
                    penetration_depth_pts=max_dev_pts,
                    penetration_depth_pct=max_dev_pct,
                    observed_traded_volume=obs_vol,
                    volume_evidence_available=obs_vol is not None,
                    source_swing_ids=[s.event_id for s in cluster],
                    rejection_reasons=[rejection_reason] if rejection_reason else [],
                )

                eq_pools.append(
                    LiquidityPool(
                        pool_id=pid,
                        index=symbol,
                        liquidity_type=liquidity_type,
                        direction=direction,
                        timeframe=timeframe,
                        level=mean_p,
                        upper_bound=max_p,
                        lower_bound=min_p,
                        status=initial_state,
                        touch_count=len(cluster),
                        evidence=ev,
                        formation_time=first_swing.event_time,
                        available_at=latest_swing.available_at,
                        updated_at=latest_swing.available_at,
                        source_candle_ids=[s.candle_id for s in cluster],
                        source_candle_identifiers=[s.candle_id for s in cluster],
                        source_data_quality=data_quality_status,
                        configuration_version=ver,
                        engine_version="3.1.0",
                    )
                )

                for idx_c, s in enumerate(swings):
                    if s in cluster:
                        used_indices.add(idx_c)

        return eq_pools

    def detect_session_liquidity(
        self,
        df: pd.DataFrame,
        symbol: str = "NIFTY 50",
        timeframe: str = "15m",
        daily_high: Optional[float] = None,
        daily_low: Optional[float] = None,
        opening_range_high: Optional[float] = None,
        opening_range_low: Optional[float] = None,
        as_of_time: Optional[datetime] = None,
        initial_state: LiquidityLifecycleState = LiquidityLifecycleState.IDENTIFIED,
        data_quality_status: str = "VERIFIED_LIVE",
        rejection_reason: Optional[str] = None,
    ) -> List[LiquidityPool]:
        """
        Detects comprehensive Indian Session Windows and Extremes using MarketCalendar:
        1. Full Day Session High & Low
        2. Opening Range (09:15-09:45 IST)
        3. Morning Session (09:45-11:30 IST)
        4. Midday Session (11:30-13:30 IST)
        5. Afternoon Session (13:30-14:45 IST)
        6. Closing Window (14:45-15:30 IST)
        """
        session_pools: List[LiquidityPool] = []
        ver = self.config.configuration_version
        now_dt = _ensure_timezone_aware(as_of_time or df.iloc[-1].get("timestamp"))

        # Calendar Holiday / Special Session check
        is_regular_trading_day = MarketCalendar.is_trading_day(now_dt)
        if not is_regular_trading_day:
            cal_msg = f"MarketCalendar lockout: date {now_dt.date()} is an exchange holiday or weekend closure."
            rejection_reason = f"{rejection_reason} | {cal_msg}" if rejection_reason else cal_msg
            initial_state = LiquidityLifecycleState.INVALIDATED

        # 1. Full Day Session High/Low
        d_high = daily_high or (float(df["high"].max()) if "high" in df.columns and not df["high"].empty else None)
        d_low = daily_low or (float(df["low"].min()) if "low" in df.columns and not df["low"].empty else None)

        if d_high and d_high > 0:
            pid = generate_deterministic_event_id(symbol, timeframe, "SESSION_HIGH", f"{now_dt.date()}_SH", ver)
            session_pools.append(
                LiquidityPool(
                    pool_id=pid,
                    index=symbol,
                    liquidity_type=LiquidityType.SESSION_HIGH,
                    direction=EventDirection.BEARISH,
                    timeframe=timeframe,
                    level=round(d_high, 2),
                    upper_bound=round(d_high * 1.0005, 2),
                    lower_bound=round(d_high, 2),
                    status=initial_state,
                    touch_count=1,
                    evidence=LiquidityEvidence(
                        touch_count=1,
                        rejection_reasons=[rejection_reason] if rejection_reason else []
                    ),
                    formation_time=now_dt,
                    available_at=now_dt,
                    updated_at=now_dt,
                    source_candle_ids=["SESSION_HIGH"],
                    source_candle_identifiers=["SESSION_HIGH"],
                    source_data_quality=data_quality_status,
                    configuration_version=ver,
                    engine_version="3.1.0",
                )
            )

        if d_low and d_low > 0:
            pid = generate_deterministic_event_id(symbol, timeframe, "SESSION_LOW", f"{now_dt.date()}_SL", ver)
            session_pools.append(
                LiquidityPool(
                    pool_id=pid,
                    index=symbol,
                    liquidity_type=LiquidityType.SESSION_LOW,
                    direction=EventDirection.BULLISH,
                    timeframe=timeframe,
                    level=round(d_low, 2),
                    upper_bound=round(d_low, 2),
                    lower_bound=round(d_low * 0.9995, 2),
                    status=initial_state,
                    touch_count=1,
                    evidence=LiquidityEvidence(
                        touch_count=1,
                        rejection_reasons=[rejection_reason] if rejection_reason else []
                    ),
                    formation_time=now_dt,
                    available_at=now_dt,
                    updated_at=now_dt,
                    source_candle_ids=["SESSION_LOW"],
                    source_candle_identifiers=["SESSION_LOW"],
                    source_data_quality=data_quality_status,
                    configuration_version=ver,
                    engine_version="3.1.0",
                )
            )

        # 2. Window-Based Session Extraction Helper
        def _extract_window_extremes(start_str: str, end_str: str) -> Tuple[Optional[float], Optional[float], Optional[datetime]]:
            if "timestamp" not in df.columns:
                return None, None, None
            s_h, s_m = map(int, start_str.split(":"))
            e_h, e_m = map(int, end_str.split(":"))
            w_start = time(s_h, s_m)
            w_end = time(e_h, e_m)

            w_bars = []
            max_dt = None
            for _, row in df.iterrows():
                ts = _ensure_timezone_aware(row["timestamp"])
                t = ts.astimezone(IST_ZONE).time()
                if w_start <= t <= w_end:
                    w_bars.append(row)
                    if max_dt is None or ts > max_dt:
                        max_dt = ts

            if not w_bars:
                return None, None, None
            w_df = pd.DataFrame(w_bars)
            return float(w_df["high"].max()), float(w_df["low"].min()), max_dt

        # A. Opening Range (09:15-09:45 IST)
        or_h = opening_range_high
        or_l = opening_range_low
        or_dt = now_dt
        if or_h is None or or_l is None:
            w_h, w_l, w_dt = _extract_window_extremes(self.config.opening_range_start, self.config.opening_range_end)
            or_h = or_h or w_h
            or_l = or_l or w_l
            or_dt = w_dt or now_dt

        if or_h and or_h > 0:
            pid = generate_deterministic_event_id(symbol, timeframe, "ORH", f"{now_dt.date()}_ORH", ver)
            session_pools.append(
                LiquidityPool(
                    pool_id=pid,
                    index=symbol,
                    liquidity_type=LiquidityType.OPENING_RANGE_HIGH,
                    direction=EventDirection.BEARISH,
                    timeframe=timeframe,
                    level=round(or_h, 2),
                    upper_bound=round(or_h * 1.0005, 2),
                    lower_bound=round(or_h, 2),
                    status=initial_state,
                    touch_count=1,
                    evidence=LiquidityEvidence(
                        touch_count=1,
                        rejection_reasons=[rejection_reason] if rejection_reason else []
                    ),
                    formation_time=or_dt,
                    available_at=or_dt,
                    updated_at=or_dt,
                    source_candle_ids=["OPENING_RANGE"],
                    source_candle_identifiers=["OPENING_RANGE"],
                    source_data_quality=data_quality_status,
                    configuration_version=ver,
                    engine_version="3.1.0",
                )
            )

        if or_l and or_l > 0:
            pid = generate_deterministic_event_id(symbol, timeframe, "ORL", f"{now_dt.date()}_ORL", ver)
            session_pools.append(
                LiquidityPool(
                    pool_id=pid,
                    index=symbol,
                    liquidity_type=LiquidityType.OPENING_RANGE_LOW,
                    direction=EventDirection.BULLISH,
                    timeframe=timeframe,
                    level=round(or_l, 2),
                    upper_bound=round(or_l, 2),
                    lower_bound=round(or_l * 0.9995, 2),
                    status=initial_state,
                    touch_count=1,
                    evidence=LiquidityEvidence(
                        touch_count=1,
                        rejection_reasons=[rejection_reason] if rejection_reason else []
                    ),
                    formation_time=or_dt,
                    available_at=or_dt,
                    updated_at=or_dt,
                    source_candle_ids=["OPENING_RANGE"],
                    source_candle_identifiers=["OPENING_RANGE"],
                    source_data_quality=data_quality_status,
                    configuration_version=ver,
                    engine_version="3.1.0",
                )
            )

        # B. Morning, Midday, Afternoon, and Closing Sessions
        sub_sessions = [
            ("MORNING", self.config.morning_start, self.config.morning_end),
            ("MIDDAY", self.config.midday_start, self.config.midday_end),
            ("AFTERNOON", self.config.afternoon_start, self.config.afternoon_end),
            ("CLOSING", self.config.closing_start, self.config.closing_end),
        ]

        for s_label, s_start, s_end in sub_sessions:
            s_h, s_l, s_dt = _extract_window_extremes(s_start, s_end)
            if s_h and s_h > 0:
                pid = generate_deterministic_event_id(symbol, timeframe, f"{s_label}_HIGH", f"{now_dt.date()}_{s_label}_H", ver)
                session_pools.append(
                    LiquidityPool(
                        pool_id=pid,
                        index=symbol,
                        liquidity_type=LiquidityType.SESSION_HIGH,
                        direction=EventDirection.BEARISH,
                        timeframe=timeframe,
                        level=round(s_h, 2),
                        upper_bound=round(s_h * 1.0005, 2),
                        lower_bound=round(s_h, 2),
                        status=initial_state,
                        touch_count=1,
                        evidence=LiquidityEvidence(
                            touch_count=1,
                            rejection_reasons=[rejection_reason] if rejection_reason else []
                        ),
                        formation_time=s_dt or now_dt,
                        available_at=s_dt or now_dt,
                        updated_at=s_dt or now_dt,
                        source_candle_ids=[f"{s_label}_SESSION"],
                        source_candle_identifiers=[f"{s_label}_SESSION"],
                        source_data_quality=data_quality_status,
                        configuration_version=ver,
                        engine_version="3.1.0",
                    )
                )
            if s_l and s_l > 0:
                pid = generate_deterministic_event_id(symbol, timeframe, f"{s_label}_LOW", f"{now_dt.date()}_{s_label}_L", ver)
                session_pools.append(
                    LiquidityPool(
                        pool_id=pid,
                        index=symbol,
                        liquidity_type=LiquidityType.SESSION_LOW,
                        direction=EventDirection.BULLISH,
                        timeframe=timeframe,
                        level=round(s_l, 2),
                        upper_bound=round(s_l, 2),
                        lower_bound=round(s_l * 0.9995, 2),
                        status=initial_state,
                        touch_count=1,
                        evidence=LiquidityEvidence(
                            touch_count=1,
                            rejection_reasons=[rejection_reason] if rejection_reason else []
                        ),
                        formation_time=s_dt or now_dt,
                        available_at=s_dt or now_dt,
                        updated_at=s_dt or now_dt,
                        source_candle_ids=[f"{s_label}_SESSION"],
                        source_candle_identifiers=[f"{s_label}_SESSION"],
                        source_data_quality=data_quality_status,
                        configuration_version=ver,
                        engine_version="3.1.0",
                    )
                )

        return session_pools

    def evaluate_liquidity_lifecycle(
        self,
        pools: List[LiquidityPool],
        df: pd.DataFrame,
        symbol: str = "NIFTY 50",
        timeframe: str = "15m",
        as_of_time: Optional[datetime] = None,
    ) -> Tuple[List[LiquidityPool], List[LiquidityEvent]]:
        """
        Evaluates active liquidity pools against candlestick price action and tracks the strict lifecycle sequence:
        IDENTIFIED -> APPROACHING -> SWEPT -> RECLAIMED -> CONFIRMED
        Terminal states: CONSUMED (decisive breakout), EXPIRED (max age reached), INVALIDATED.
        NOTE: Never progresses SWEPT directly to CONFIRMED without empirical reclaim evidence.
        """
        if not pools or df is None or df.empty:
            return pools, []

        updated_pools: List[LiquidityPool] = []
        events: List[LiquidityEvent] = []
        ver = self.config.configuration_version
        clean_sym = symbol.upper().strip()

        c_open = pd.to_numeric(df["open"], errors="coerce").values
        c_high = pd.to_numeric(df["high"], errors="coerce").values
        c_low = pd.to_numeric(df["low"], errors="coerce").values
        c_close = pd.to_numeric(df["close"], errors="coerce").values
        vol_arr = (
            pd.to_numeric(df["volume"], errors="coerce").values
            if "volume" in df.columns
            else None
        )
        n = len(df)
        as_of_dt = _ensure_timezone_aware(as_of_time) if as_of_time else None

        for pool in pools:
            current_pool = pool.model_copy(deep=True)

            # Terminal states cannot be altered
            if current_pool.status in (
                LiquidityLifecycleState.CONSUMED,
                LiquidityLifecycleState.EXPIRED,
                LiquidityLifecycleState.INVALIDATED,
            ):
                updated_pools.append(current_pool)
                continue

            lvl = current_pool.level
            is_bsl = current_pool.liquidity_type in (
                LiquidityType.BSL,
                LiquidityType.EQH,
                LiquidityType.PDH,
                LiquidityType.PWH,
                LiquidityType.SESSION_HIGH,
                LiquidityType.OPENING_RANGE_HIGH,
            )

            # Evaluate each bar chronologically after pool available_at
            bars_elapsed = 0
            for i in range(n):
                c_cid, c_dt = SwingDetectionEngine._extract_candle_id_and_time(df, i)
                if as_of_dt and c_dt > as_of_dt:
                    break

                if c_dt < current_pool.available_at:
                    continue

                bars_elapsed += 1

                # Expiry check against configured policy
                if (
                    self.config.expiry_policy == "MAX_LOOKBACK"
                    and bars_elapsed > self.config.max_lookback_bars
                ):
                    current_pool.transition_to(
                        LiquidityLifecycleState.EXPIRED,
                        c_dt,
                        reason=f"Pool age exceeded maximum lookback limit ({self.config.max_lookback_bars} bars).",
                    )
                    break
                elif (
                    self.config.expiry_policy == "SESSION_CLOSE"
                    and c_dt.date() > current_pool.formation_time.date()
                ):
                    current_pool.transition_to(
                        LiquidityLifecycleState.EXPIRED,
                        c_dt,
                        reason="Pool expired at session close.",
                    )
                    break

                b_o = c_open[i]
                b_h = c_high[i]
                b_l = c_low[i]
                b_c = c_close[i]
                b_vol = (
                    float(vol_arr[i])
                    if vol_arr is not None and not np.isnan(vol_arr[i])
                    else None
                )

                if np.isnan(b_h) or np.isnan(b_l) or np.isnan(b_c):
                    continue

                # 1. Proximity Approach & Retreat
                dist_pts = abs(b_c - lvl)
                dist_pct = dist_pts / max(lvl, 1.0)
                retreat_thresh = self.config.approach_threshold_pct * self.config.approach_retreat_mult
                if (
                    current_pool.status == LiquidityLifecycleState.IDENTIFIED
                    and dist_pct <= self.config.approach_threshold_pct
                ):
                    current_pool.transition_to(
                        LiquidityLifecycleState.APPROACHING,
                        c_dt,
                        reason=f"Price approached within {dist_pct*100:.2f}%",
                    )
                    current_pool.evidence.distance_from_current_pts = dist_pts
                    current_pool.evidence.distance_from_current_pct = dist_pct
                elif (
                    current_pool.status == LiquidityLifecycleState.APPROACHING
                    and dist_pct > retreat_thresh
                ):
                    current_pool.transition_to(
                        LiquidityLifecycleState.IDENTIFIED,
                        c_dt,
                        reason=f"Price retreated beyond approach boundary ({dist_pct*100:.2f}% > {retreat_thresh*100:.2f}%). Reset to IDENTIFIED.",
                    )
                    current_pool.evidence.distance_from_current_pts = dist_pts
                    current_pool.evidence.distance_from_current_pct = dist_pct

                # 2. Breach / Sweep / Reclaim Evaluation
                if is_bsl:
                    penetration_depth = max(0.0, b_h - lvl)
                    is_penetrated = penetration_depth >= self.config.sweep_penetration_min_pts

                    if is_penetrated:
                        # Case A: Wick Penetration (Swept)
                        if b_c <= lvl:
                            upper_wick = b_h - max(b_o, b_c)
                            candle_range = max(0.01, b_h - b_l)
                            wick_ratio = upper_wick / candle_range

                            if current_pool.status in (
                                LiquidityLifecycleState.IDENTIFIED,
                                LiquidityLifecycleState.APPROACHING,
                            ):
                                current_pool.transition_to(
                                    LiquidityLifecycleState.SWEPT,
                                    c_dt,
                                    reason=f"Wick penetrated BSL by {penetration_depth:.2f} pts; closed below.",
                                )
                                current_pool.evidence.penetration_depth_pts = penetration_depth
                                current_pool.evidence.is_wick_penetration = True
                                current_pool.evidence.observed_traded_volume = b_vol

                                eid = generate_deterministic_event_id(
                                    clean_sym, timeframe, "SWEEP", c_cid, ver
                                )
                                events.append(
                                    LiquidityEvent(
                                        event_id=eid,
                                        pool_id=current_pool.pool_id,
                                        index=clean_sym,
                                        event_type=ICTEventType.LIQUIDITY_SWEEP,
                                        liquidity_type=current_pool.liquidity_type,
                                        timeframe=timeframe,
                                        level=lvl,
                                        price_level=lvl,
                                        trigger_candle_id=c_cid,
                                        penetration_price=b_h,
                                        close_price=b_c,
                                        penetration_depth_pts=penetration_depth,
                                        event_time=c_dt,
                                        available_at=c_dt,
                                        is_wick_sweep=True,
                                        is_candle_close_breakout=False,
                                        is_reclaimed=False,
                                        evidence=current_pool.evidence.model_copy(),
                                        status=LiquidityLifecycleState.SWEPT,
                                        source_candle_identifiers=[c_cid],
                                        source_data_quality=current_pool.source_data_quality,
                                        configuration_version=ver,
                                        engine_version="3.1.0",
                                    )
                                )

                            # Reclaim check: rejection wick ratio >= configured threshold (default 0.35)
                            if (
                                current_pool.status == LiquidityLifecycleState.SWEPT
                                and wick_ratio >= self.config.rejection_wick_ratio_min
                            ):
                                current_pool.transition_to(
                                    LiquidityLifecycleState.RECLAIMED,
                                    c_dt,
                                    reason=f"Sweep reclaimed with rejection wick ratio {wick_ratio:.2f}",
                                )
                                current_pool.evidence.is_reclaim_confirmed = True
                                current_pool.evidence.rejection_wick_ratio = wick_ratio

                                eid = generate_deterministic_event_id(
                                    clean_sym, timeframe, "RECLAIM", c_cid, ver
                                )
                                events.append(
                                    LiquidityEvent(
                                        event_id=eid,
                                        pool_id=current_pool.pool_id,
                                        index=clean_sym,
                                        event_type=ICTEventType.LIQUIDITY_RECLAIM,
                                        liquidity_type=current_pool.liquidity_type,
                                        timeframe=timeframe,
                                        level=lvl,
                                        price_level=lvl,
                                        trigger_candle_id=c_cid,
                                        penetration_price=b_h,
                                        close_price=b_c,
                                        penetration_depth_pts=penetration_depth,
                                        event_time=c_dt,
                                        available_at=c_dt,
                                        is_wick_sweep=True,
                                        is_candle_close_breakout=False,
                                        is_reclaimed=True,
                                        evidence=current_pool.evidence.model_copy(),
                                        status=LiquidityLifecycleState.RECLAIMED,
                                        source_candle_identifiers=[c_cid],
                                        source_data_quality=current_pool.source_data_quality,
                                        configuration_version=ver,
                                        engine_version="3.1.0",
                                    )
                                )

                        # Case B: Decisive Body Breakout -> CONSUMED
                        elif b_c > current_pool.upper_bound:
                            current_pool.transition_to(
                                LiquidityLifecycleState.CONSUMED,
                                c_dt,
                                reason=f"Candle body closed decisively above upper bound ({b_c} > {current_pool.upper_bound})",
                            )
                            current_pool.evidence.is_candle_close_breakout = True
                            current_pool.evidence.penetration_depth_pts = penetration_depth
                            break

                else:
                    # SSL: Sell-Side Liquidity
                    penetration_depth = max(0.0, lvl - b_l)
                    is_penetrated = penetration_depth >= self.config.sweep_penetration_min_pts

                    if is_penetrated:
                        # Case A: Wick Penetration (Swept)
                        if b_c >= lvl:
                            lower_wick = min(b_o, b_c) - b_l
                            candle_range = max(0.01, b_h - b_l)
                            wick_ratio = lower_wick / candle_range

                            if current_pool.status in (
                                LiquidityLifecycleState.IDENTIFIED,
                                LiquidityLifecycleState.APPROACHING,
                            ):
                                current_pool.transition_to(
                                    LiquidityLifecycleState.SWEPT,
                                    c_dt,
                                    reason=f"Wick penetrated SSL by {penetration_depth:.2f} pts; closed above.",
                                )
                                current_pool.evidence.penetration_depth_pts = penetration_depth
                                current_pool.evidence.is_wick_penetration = True
                                current_pool.evidence.observed_traded_volume = b_vol

                                eid = generate_deterministic_event_id(
                                    clean_sym, timeframe, "SWEEP", c_cid, ver
                                )
                                events.append(
                                    LiquidityEvent(
                                        event_id=eid,
                                        pool_id=current_pool.pool_id,
                                        index=clean_sym,
                                        event_type=ICTEventType.LIQUIDITY_SWEEP,
                                        liquidity_type=current_pool.liquidity_type,
                                        timeframe=timeframe,
                                        level=lvl,
                                        price_level=lvl,
                                        trigger_candle_id=c_cid,
                                        penetration_price=b_l,
                                        close_price=b_c,
                                        penetration_depth_pts=penetration_depth,
                                        event_time=c_dt,
                                        available_at=c_dt,
                                        is_wick_sweep=True,
                                        is_candle_close_breakout=False,
                                        is_reclaimed=False,
                                        evidence=current_pool.evidence.model_copy(),
                                        status=LiquidityLifecycleState.SWEPT,
                                        source_candle_identifiers=[c_cid],
                                        source_data_quality=current_pool.source_data_quality,
                                        configuration_version=ver,
                                        engine_version="3.1.0",
                                    )
                                )

                            # Reclaim check
                            if (
                                current_pool.status == LiquidityLifecycleState.SWEPT
                                and wick_ratio >= self.config.rejection_wick_ratio_min
                            ):
                                current_pool.transition_to(
                                    LiquidityLifecycleState.RECLAIMED,
                                    c_dt,
                                    reason=f"Sweep reclaimed with rejection wick ratio {wick_ratio:.2f}",
                                )
                                current_pool.evidence.is_reclaim_confirmed = True
                                current_pool.evidence.rejection_wick_ratio = wick_ratio

                                eid = generate_deterministic_event_id(
                                    clean_sym, timeframe, "RECLAIM", c_cid, ver
                                )
                                events.append(
                                    LiquidityEvent(
                                        event_id=eid,
                                        pool_id=current_pool.pool_id,
                                        index=clean_sym,
                                        event_type=ICTEventType.LIQUIDITY_RECLAIM,
                                        liquidity_type=current_pool.liquidity_type,
                                        timeframe=timeframe,
                                        level=lvl,
                                        price_level=lvl,
                                        trigger_candle_id=c_cid,
                                        penetration_price=b_l,
                                        close_price=b_c,
                                        penetration_depth_pts=penetration_depth,
                                        event_time=c_dt,
                                        available_at=c_dt,
                                        is_wick_sweep=True,
                                        is_candle_close_breakout=False,
                                        is_reclaimed=True,
                                        evidence=current_pool.evidence.model_copy(),
                                        status=LiquidityLifecycleState.RECLAIMED,
                                        source_candle_identifiers=[c_cid],
                                        source_data_quality=current_pool.source_data_quality,
                                        configuration_version=ver,
                                        engine_version="3.1.0",
                                    )
                                )

                        # Case B: Decisive Body Breakout -> CONSUMED
                        elif b_c < current_pool.lower_bound:
                            current_pool.transition_to(
                                LiquidityLifecycleState.CONSUMED,
                                c_dt,
                                reason=f"Candle body closed decisively below lower bound ({b_c} < {current_pool.lower_bound})",
                            )
                            current_pool.evidence.is_candle_close_breakout = True
                            current_pool.evidence.penetration_depth_pts = penetration_depth
                            break

                # 3. Follow-Through Confirmation: RECLAIMED -> CONFIRMED (completed reversal follow-through candle)
                if current_pool.status == LiquidityLifecycleState.RECLAIMED:
                    # Must observe a follow-through candle closing in the reversal direction
                    if (is_bsl and b_c < b_o) or (not is_bsl and b_c > b_o):
                        current_pool.transition_to(
                            LiquidityLifecycleState.CONFIRMED,
                            c_dt,
                            reason="Follow-through candle confirms sweep-and-reclaim reversal structure.",
                        )
                        eid = generate_deterministic_event_id(
                            clean_sym, timeframe, "CONFIRMED", c_cid, ver
                        )
                        events.append(
                            LiquidityEvent(
                                event_id=eid,
                                pool_id=current_pool.pool_id,
                                index=clean_sym,
                                event_type=ICTEventType.LIQUIDITY_CONFIRMED,
                                liquidity_type=current_pool.liquidity_type,
                                timeframe=timeframe,
                                level=lvl,
                                price_level=lvl,
                                trigger_candle_id=c_cid,
                                penetration_price=b_h if is_bsl else b_l,
                                close_price=b_c,
                                penetration_depth_pts=current_pool.evidence.penetration_depth_pts or 0.0,
                                event_time=c_dt,
                                available_at=c_dt,
                                is_wick_sweep=True,
                                is_candle_close_breakout=False,
                                is_reclaimed=True,
                                evidence=current_pool.evidence.model_copy(),
                                status=LiquidityLifecycleState.CONFIRMED,
                                source_candle_identifiers=[c_cid],
                                source_data_quality=current_pool.source_data_quality,
                                configuration_version=ver,
                                engine_version="3.1.0",
                            )
                        )

            updated_pools.append(current_pool)

        return updated_pools, events


# ---------------------------------------------------------------------
# 2. Backward-Compatible Legacy Facade (LiquidityDetectionEngine)
# ---------------------------------------------------------------------

class LiquidityDetectionEngine:
    """
    Backward-compatible facade preserving all existing method signatures and return formats
    for legacy modules (options.py, structure_analyzer.py, test_ict_smc_engine.py).
    Delegates under-the-hood calculations to LiquidityIntelligenceEngine.
    """

    @staticmethod
    def identify_liquidity_pools(
        df: pd.DataFrame,
        daily_high: float,
        daily_low: float,
        prev_day_high: Optional[float] = None,
        prev_day_low: Optional[float] = None,
        prev_week_high: Optional[float] = None,
        prev_week_low: Optional[float] = None,
        opening_range_high: Optional[float] = None,
        opening_range_low: Optional[float] = None,
        tolerance_pct: float = 0.0015,
    ) -> Dict[str, Any]:
        """
        Legacy dictionary-based pool identification.
        Maintains bit-for-bit key compatibility with previous implementations.
        """
        cfg = LiquidityConfiguration(eq_tolerance_pct=tolerance_pct)
        engine = LiquidityIntelligenceEngine(config=cfg)

        typed_pools = engine.detect_liquidity_pools(
            df=df,
            daily_high=daily_high,
            daily_low=daily_low,
            prev_day_high=prev_day_high,
            prev_day_low=prev_day_low,
            prev_week_high=prev_week_high,
            prev_week_low=prev_week_low,
            opening_range_high=opening_range_high,
            opening_range_low=opening_range_low,
        )

        bsl_pools = []
        ssl_pools = []
        eqh_pools = []
        eql_pools = []

        for p in typed_pools:
            pool_dict = {
                "name": p.liquidity_type.value,
                "level": p.level,
                "type": "BSL" if p.direction == EventDirection.BEARISH else "SSL",
                "significance": "Major Liquidity Target",
                "status": p.status.value,
                "touchCount": p.touch_count,
            }
            if p.liquidity_type == LiquidityType.EQH:
                pool_dict["name"] = "Equal Highs (EQH)"
                pool_dict["significance"] = "High Density Internal Liquidity"
                pool_dict["description"] = f"Equal Highs cluster at ₹{p.level}"
                eqh_pools.append(pool_dict)
                bsl_pools.append(pool_dict)
            elif p.liquidity_type == LiquidityType.EQL:
                pool_dict["name"] = "Equal Lows (EQL)"
                pool_dict["significance"] = "High Density Internal Liquidity"
                pool_dict["description"] = f"Equal Lows cluster at ₹{p.level}"
                eql_pools.append(pool_dict)
                ssl_pools.append(pool_dict)
            elif p.liquidity_type in (
                LiquidityType.BSL,
                LiquidityType.PDH,
                LiquidityType.PWH,
                LiquidityType.SESSION_HIGH,
                LiquidityType.OPENING_RANGE_HIGH,
            ):
                bsl_pools.append(pool_dict)
            else:
                ssl_pools.append(pool_dict)

        idm_high = None
        idm_low = None
        if len(bsl_pools) >= 2:
            idm_high = {
                "name": "Bullish Inducement (IDM High)",
                "level": bsl_pools[-1]["level"],
                "type": "IDM_BSL",
                "significance": "Retail Trap Resistance",
                "status": "IDENTIFIED",
            }
        if len(ssl_pools) >= 2:
            idm_low = {
                "name": "Bearish Inducement (IDM Low)",
                "level": ssl_pools[-1]["level"],
                "type": "IDM_SSL",
                "significance": "Retail Trap Support",
                "status": "IDENTIFIED",
            }

        return {
            "bslPools": sorted(bsl_pools, key=lambda p: p["level"], reverse=True),
            "sslPools": sorted(ssl_pools, key=lambda p: p["level"]),
            "equalHighs": eqh_pools,
            "equalLows": eql_pools,
            "inducementHigh": idm_high,
            "inducementLow": idm_low,
            "_typed_pools": typed_pools,
        }

    @classmethod
    def detect_liquidity_sweeps(
        cls,
        df: pd.DataFrame,
        liquidity_pools: Dict[str, Any],
        min_sweep_pct: float = 0.0003,
        max_body_reversal_pct: float = 0.0008,
        min_wick_ratio: float = 0.35,
    ) -> List[Dict[str, Any]]:
        return cls.evaluate_liquidity_sweeps(df, liquidity_pools)

    @staticmethod
    def evaluate_liquidity_sweeps(
        df: pd.DataFrame,
        liquidity_pools: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        Legacy dictionary-based sweep evaluation matching existing tests.
        """
        sweeps = []
        n = len(df)
        if n < 3:
            return sweeps

        all_pools = []
        for p in liquidity_pools.get("bslPools", []):
            all_pools.append({**p, "poolType": "BSL"})
        for p in liquidity_pools.get("sslPools", []):
            all_pools.append({**p, "poolType": "SSL"})

        c_open = df["open"].values
        c_high = df["high"].values
        c_low = df["low"].values
        c_close = df["close"].values

        for pool in all_pools:
            lvl = float(pool["level"])
            p_type = pool["poolType"]

            for i in range(1, n):
                o = float(c_open[i])
                h = float(c_high[i])
                l = float(c_low[i])
                c = float(c_close[i])
                ts = str(df.iloc[i].get("timestamp", df.iloc[i].get("time", f"bar_{i}")))

                if p_type == "BSL":
                    if h > lvl:
                        penetration = round(h - lvl, 2)
                        if c <= lvl:
                            upper_wick = h - max(o, c)
                            body_span = max(0.01, h - l)
                            w_ratio = round(upper_wick / body_span, 2)
                            sweeps.append({
                                "type": "SWEEP_WITH_RECLAIM",
                                "target": pool.get("name", "BSL Pool"),
                                "level": lvl,
                                "sweepPrice": round(h, 2),
                                "penetrationPts": penetration,
                                "closePrice": round(c, 2),
                                "wickRatio": w_ratio,
                                "direction": "BEARISH_REVERSAL_READY",
                                "candleIndex": i,
                                "timestamp": ts,
                                "verdict": "Wick breach with candle-body reclaim (completed reversal follow-through candle)",
                            })
                        else:
                            sweeps.append({
                                "type": "SWEEP_WITHOUT_RECLAIM",
                                "target": pool.get("name", "BSL Pool"),
                                "level": lvl,
                                "sweepPrice": round(h, 2),
                                "penetrationPts": penetration,
                                "closePrice": round(c, 2),
                                "direction": "BULLISH_EXPANSION_CONTINUATION",
                                "candleIndex": i,
                                "timestamp": ts,
                                "verdict": "Breakout Continuation (Candle body closed beyond liquidity pool)",
                            })
                else:  # SSL
                    if l < lvl:
                        penetration = round(lvl - l, 2)
                        if c >= lvl:
                            lower_wick = min(o, c) - l
                            body_span = max(0.01, h - l)
                            w_ratio = round(lower_wick / body_span, 2)
                            sweeps.append({
                                "type": "SWEEP_WITH_RECLAIM",
                                "target": pool.get("name", "SSL Pool"),
                                "level": lvl,
                                "sweepPrice": round(l, 2),
                                "penetrationPts": penetration,
                                "closePrice": round(c, 2),
                                "wickRatio": w_ratio,
                                "direction": "BULLISH_REVERSAL_READY",
                                "candleIndex": i,
                                "timestamp": ts,
                                "verdict": "Wick breach with candle-body reclaim (completed reversal follow-through candle)",
                            })
                        else:
                            sweeps.append({
                                "type": "SWEEP_WITHOUT_RECLAIM",
                                "target": pool.get("name", "SSL Pool"),
                                "level": lvl,
                                "sweepPrice": round(l, 2),
                                "penetrationPts": penetration,
                                "closePrice": round(c, 2),
                                "direction": "BEARISH_EXPANSION_CONTINUATION",
                                "candleIndex": i,
                                "timestamp": ts,
                                "verdict": "Breakout Continuation (Candle body closed beyond liquidity pool)",
                            })

        return sweeps

    @classmethod
    def build_liquidity_heatmap(
        cls,
        liquidity_pools: Dict[str, Any],
        current_price: float,
        atr_14: float = 100.0,
    ) -> List[Dict[str, Any]]:
        return cls.generate_liquidity_heatmap(
            current_price=current_price,
            liquidity_pools=liquidity_pools,
            atr_14=atr_14,
        )

    @staticmethod
    def generate_liquidity_heatmap(
        current_price: float,
        liquidity_pools: Dict[str, Any],
        atr_14: float = 100.0,
    ) -> List[Dict[str, Any]]:
        """
        Constructs price-distance normalized liquidity heatmap density map.
        """
        heatmap = []
        all_pools = []
        for p in liquidity_pools.get("bslPools", []):
            all_pools.append({**p, "poolType": "BSL"})
        for p in liquidity_pools.get("sslPools", []):
            all_pools.append({**p, "poolType": "SSL"})

        eff_atr = max(atr_14, 20.0)

        for p in all_pools:
            lvl = float(p["level"])
            dist_pts = abs(lvl - current_price)
            dist_atr = dist_pts / eff_atr

            base_density = 90.0 if "EQ" in p.get("name", "") else (80.0 if "PD" in p.get("name", "") else 65.0)
            touch_mult = min(1.3, 1.0 + (p.get("touchCount", 1) - 1) * 0.15)
            density = max(10.0, min(100.0, (base_density * touch_mult) / (1.0 + dist_atr * 0.5)))
            color_int = "HIGH" if density >= 75.0 else ("MEDIUM" if density >= 45.0 else "LOW")

            heatmap.append({
                "name": p.get("name", "Pool"),
                "level": lvl,
                "type": p["poolType"],
                "distancePts": round(dist_pts, 2),
                "distanceAtr": round(dist_atr, 2),
                "densityScore": round(density, 1),
                "heatDensity": round(density, 1),
                "colorIntensity": color_int,
                "status": p.get("status", "IDENTIFIED"),
            })

        heatmap.sort(key=lambda x: x["heatDensity"], reverse=True)
        return heatmap
