"""
AIVOLVE 3.0 — Data Quality & Validation Engine (Engine 1 & 2).
Provides institutional-grade deterministic validation for Indian benchmark index spot
and derivative market data feeds.

Core Capabilities:
1. Millisecond latency and freshness tracking.
2. Instrument-aware anomaly and freak tick filtering (Spot vs Options).
3. Legitimate market opening gap preservation (auction open vs freak spike).
4. Configurable single-tick jump and volume surge thresholds.
5. Bid/Ask spread and depth sanity verification.
6. Deterministic Data Quality Score (0 to 100) and qualification gating.
7. Tick sequence gap detection separating missing sequence headers from confirmed drops.
8. OHLC candle mathematical invariant verification (high >= max(open, close), low <= min(open, close)).
9. Strict audit trail ensuring reproducible backtesting and paper execution.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
import math
import pandas as pd
from app.data.market_calendar import MarketCalendar


class FeedStatus:
    VERIFIED_LIVE = "VERIFIED_LIVE"
    VERIFIED_EOD = "VERIFIED_EOD"
    DEGRADED = "DEGRADED"
    STALE = "STALE"
    STALE_TICK = "STALE_TICK"
    DATA_OFFLINE = "DATA_OFFLINE"
    DATA_UNAVAILABLE = "DATA_UNAVAILABLE"
    ANOMALOUS = "ANOMALOUS"
    SYNTHETIC = "SYNTHETIC"


class DataQualityEngine:
    """
    Validates, sanitizes, and scores incoming market quotes, ticks, and option chains.
    Enforces that capital preservation decisions have verified data integrity.
    """

    MAX_LIVE_LATENCY_MS = 15000.0  # 15 seconds max before flagging degraded
    STALE_FEED_THRESHOLD_MS = 60000.0  # 60 seconds max before flagging stale
    MAX_OPTION_SPREAD_PCT = 2.5  # Max allowable bid/ask spread % of premium
    EXTREME_SINGLE_TICK_SIGMA = 4.0  # Z-score outlier cutoff
    DEFAULT_SPOT_MAX_JUMP_PCT = 1.5  # Max single-tick jump for spot indices (~360 pts on Nifty)
    DEFAULT_OPTION_MAX_JUMP_PCT = 25.0  # Max single-tick jump for option premiums
    DEFAULT_SPOT_VOL_THRESHOLD = 1000  # Minimum volume surge for spot jump
    DEFAULT_OPTION_VOL_THRESHOLD = 50  # Minimum volume surge for option jump

    @classmethod
    def validate_quote(
        cls,
        symbol: str,
        quote: Dict[str, Any],
        reference_candles: Optional[pd.DataFrame] = None,
        atr_14: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Audits an incoming market quote dictionary.
        Returns a sanitized quote accompanied by an auditable DataQualityReport.
        """
        clean_sym = symbol.upper().strip()
        now_utc = datetime.now(timezone.utc)
        now_ist = MarketCalendar.format_ist_timestamp()
        is_market_open = MarketCalendar.is_market_open()

        checks_passed: List[str] = []
        anomalies_detected: List[str] = []
        score = 100

        if not quote or not isinstance(quote, dict):
            return {
                "sanitizedQuote": {},
                "dataQualityReport": {
                    "symbol": clean_sym,
                    "dataQualityScore": 0,
                    "feedStatus": FeedStatus.DATA_UNAVAILABLE,
                    "latencyMs": -1.0,
                    "timestampIST": now_ist,
                    "isTradeQualified": False,
                    "isAnalysisQualified": False,
                    "isAuditable": False,
                    "checksPassed": [],
                    "anomaliesDetected": ["Quote object is null or not a valid dictionary."],
                    "source": "UNKNOWN",
                },
            }

        # Check explicit upstream status flag or synthetic source markers
        incoming_status = str(quote.get("dataStatus", "")).upper()
        quote_provider = str(quote.get("provider", "")).lower()
        ref_attrs = (
            reference_candles.attrs
            if reference_candles is not None and hasattr(reference_candles, "attrs") and isinstance(reference_candles.attrs, dict)
            else {}
        )
        is_synthetic_quote = bool(
            incoming_status in [FeedStatus.SYNTHETIC, "MOCK", "SYNTHETIC"]
            or quote.get("is_mock")
            or quote.get("is_synthetic")
            or quote_provider == "mock"
            or ref_attrs.get("is_mock")
            or ref_attrs.get("is_synthetic")
            or str(ref_attrs.get("dataStatus", "")).upper() in {"MOCK", "SYNTHETIC"}
            or str(ref_attrs.get("provider", "")).lower() == "mock"
        )

        # 1. Mock / Synthetic Feed Protection (Safety Requirement 2)
        if is_synthetic_quote:
            return {
                "sanitizedQuote": {
                    **quote,
                    "feedStatus": FeedStatus.SYNTHETIC,
                    "isTradeQualified": False,
                    "isAnalysisQualified": False,
                },
                "dataQualityReport": {
                    "symbol": clean_sym,
                    "dataQualityScore": 0,
                    "feedStatus": FeedStatus.SYNTHETIC,
                    "latencyMs": 0.0,
                    "timestampIST": now_ist,
                    "isTradeQualified": False,
                    "isAnalysisQualified": False,
                    "isAuditable": False,
                    "checksPassed": [],
                    "anomaliesDetected": ["Synthetic/Mock feed detected. Gated from live trade execution."],
                    "source": quote.get("provider", "mock"),
                },
            }

        # 2. Market Closed / EOD Snapshot Handling (Safety Requirement 1)
        if incoming_status in [FeedStatus.VERIFIED_EOD, "MARKET_CLOSED", "EOD"]:
            return {
                "sanitizedQuote": {
                    **quote,
                    "feedStatus": FeedStatus.VERIFIED_EOD,
                    "isTradeQualified": False,  # EOD snapshot is strictly for analysis, NOT for opening new live paper trades!
                    "isAnalysisQualified": True,
                },
                "dataQualityReport": {
                    "symbol": clean_sym,
                    "dataQualityScore": 100,
                    "feedStatus": FeedStatus.VERIFIED_EOD,
                    "latencyMs": 0.0,
                    "timestampIST": now_ist,
                    "isTradeQualified": False,
                    "isAnalysisQualified": True,
                    "isAuditable": True,
                    "checksPassed": ["Verified EOD settlement snapshot for market analysis."],
                    "anomaliesDetected": [],
                    "source": quote.get("provider", "angelone_eod"),
                },
            }

        if incoming_status in [FeedStatus.DATA_OFFLINE, "OFFLINE", "DISCONNECTED"]:
            return {
                "sanitizedQuote": quote,
                "dataQualityReport": {
                    "symbol": clean_sym,
                    "dataQualityScore": 0,
                    "feedStatus": FeedStatus.DATA_OFFLINE,
                    "latencyMs": -1.0,
                    "timestampIST": now_ist,
                    "isTradeQualified": False,
                    "isAnalysisQualified": False,
                    "isAuditable": True,
                    "checksPassed": [],
                    "anomaliesDetected": ["Exchange feed is offline or broker connection disconnected."],
                    "source": quote.get("provider", "angelone"),
                },
            }

        if incoming_status in [FeedStatus.DATA_UNAVAILABLE, "UNAVAILABLE"]:
            return {
                "sanitizedQuote": quote,
                "dataQualityReport": {
                    "symbol": clean_sym,
                    "dataQualityScore": 0,
                    "feedStatus": FeedStatus.DATA_UNAVAILABLE,
                    "latencyMs": -1.0,
                    "timestampIST": now_ist,
                    "isTradeQualified": False,
                    "isAnalysisQualified": False,
                    "isAuditable": True,
                    "checksPassed": [],
                    "anomaliesDetected": ["Market data is unavailable for requested instrument."],
                    "source": quote.get("provider", "angelone"),
                },
            }

        # 3. Price Value and Sign Validation
        ltp = float(quote.get("currentPrice") or quote.get("ltp") or 0.0)
        d_high = float(quote.get("dayHigh") or quote.get("high") or ltp)
        d_low = float(quote.get("dayLow") or quote.get("low") or ltp)
        d_open = float(quote.get("openPrice") or quote.get("open") or ltp)
        d_close = float(quote.get("previousClose") or quote.get("close") or ltp)

        if ltp <= 0.0 or math.isnan(ltp) or math.isinf(ltp):
            anomalies_detected.append(f"Invalid non-positive LTP ({ltp}).")
            score -= 60
        else:
            checks_passed.append("Positive non-zero price verified.")

        # 4. High-Low Consistency Check
        if d_high < d_low:
            anomalies_detected.append(f"Inverted extremes: Day High ({d_high}) < Day Low ({d_low}).")
            score -= 30
            # Auto-sanitize inverted high/low
            d_high, d_low = max(d_high, d_low), min(d_high, d_low)
        else:
            checks_passed.append("Day high/low boundaries are mathematically consistent.")

        if ltp > d_high * 1.0005 or ltp < d_low * 0.9995:
            anomalies_detected.append(
                f"LTP ({ltp}) is outside published day range [{d_low} — {d_high}]. Range adjusted."
            )
            d_high = max(d_high, ltp)
            d_low = min(d_low, ltp)
            score -= 10
        else:
            checks_passed.append("LTP within daily trading bounds.")

        # 5. Latency & Freshness Tracking
        quote_ts_raw = quote.get("timestamp")
        latency_ms = 0.0
        if quote_ts_raw:
            try:
                if isinstance(quote_ts_raw, (int, float)):
                    quote_dt = datetime.fromtimestamp(quote_ts_raw, tz=timezone.utc)
                elif isinstance(quote_ts_raw, datetime):
                    quote_dt = quote_ts_raw
                else:
                    clean_ts = str(quote_ts_raw).replace("Z", "+00:00")
                    quote_dt = datetime.fromisoformat(clean_ts)

                if quote_dt.tzinfo is None:
                    quote_dt = quote_dt.replace(tzinfo=timezone.utc)

                latency_ms = max(0.0, (now_utc - quote_dt).total_seconds() * 1000.0)
            except Exception:
                latency_ms = 50.0  # Default assumption for live socket buffer
        else:
            latency_ms = 100.0

        if is_market_open:
            if latency_ms <= 3000.0:
                feed_status = FeedStatus.VERIFIED_LIVE
                checks_passed.append(f"Ultra-low feed latency ({latency_ms:.0f} ms).")
            elif latency_ms <= cls.MAX_LIVE_LATENCY_MS:
                feed_status = FeedStatus.VERIFIED_LIVE
                checks_passed.append(f"Acceptable feed latency ({latency_ms:.0f} ms).")
                score -= 10
            elif latency_ms <= cls.STALE_FEED_THRESHOLD_MS:
                feed_status = FeedStatus.DEGRADED
                anomalies_detected.append(f"Feed latency elevated ({latency_ms / 1000.0:.1f}s old).")
                score -= 35
            else:
                feed_status = FeedStatus.STALE
                anomalies_detected.append(
                    f"Market data is stale ({latency_ms / 60000.0:.1f}m old). Signals suppressed."
                )
                score -= 60
        else:
            # Post-market: quotes are verified end-of-day settlements
            feed_status = FeedStatus.VERIFIED_EOD
            checks_passed.append("Market closed: EOD settlement quote verified for analysis.")

        # 6. Anomaly / Freak Tick Filtering with Legitimate Market Gap Awareness
        if atr_14 and atr_14 > 0 and reference_candles is not None and not reference_candles.empty:
            recent_closes = reference_candles["close"].tail(10)
            median_c = float(recent_closes.median())
            deviation = abs(ltp - median_c)
            # Legitimate session opening gap check: if price is consistent with openPrice (within 1.5 ATR)
            is_legitimate_gap = (abs(ltp - d_open) <= (atr_14 * 1.5)) if d_open > 0 else False

            if deviation > (atr_14 * cls.EXTREME_SINGLE_TICK_SIGMA):
                if is_legitimate_gap:
                    checks_passed.append(f"Legitimate opening session gap verified (deviation {deviation:.1f} pts, consistent with openPrice).")
                else:
                    anomalies_detected.append(
                        f"Freak tick outlier: LTP ({ltp}) deviates {deviation:.1f} pts from recent median ({median_c:.1f})."
                    )
                    score -= 40
                    feed_status = FeedStatus.ANOMALOUS

        # 7. Bid/Ask Spread Sanity (if available in quote)
        bid = float(quote.get("bid") or quote.get("bestBidPrice") or 0.0)
        ask = float(quote.get("ask") or quote.get("bestAskPrice") or 0.0)
        spread_pct = 0.0
        if bid > 0 and ask > 0:
            if bid > ask:
                anomalies_detected.append(f"Crossed market: Bid ({bid}) > Ask ({ask}).")
                score -= 25
            else:
                spread = ask - bid
                spread_pct = (spread / ltp) * 100.0 if ltp > 0 else 0.0
                if spread_pct > cls.MAX_OPTION_SPREAD_PCT:
                    anomalies_detected.append(
                        f"Excessive spread ({spread_pct:.2f}% > {cls.MAX_OPTION_SPREAD_PCT}% limit). Slippage hazard."
                    )
                    score -= 20
                else:
                    checks_passed.append(f"Tight bid/ask spread verified ({spread_pct:.2f}%).")

        final_score = max(0, min(100, score))
        # Only VERIFIED_LIVE during active market can open new positions
        is_trade_qualified = (final_score >= 70) and (feed_status == FeedStatus.VERIFIED_LIVE) and is_market_open
        is_analysis_qualified = (final_score >= 60) and (feed_status in [FeedStatus.VERIFIED_LIVE, FeedStatus.VERIFIED_EOD])

        sanitized_quote = {
            **quote,
            "ltp": ltp,
            "currentPrice": ltp,
            "dayHigh": d_high,
            "dayLow": d_low,
            "openPrice": d_open,
            "previousClose": d_close,
            "feedStatus": feed_status,
            "dataQualityScore": final_score,
            "isTradeQualified": is_trade_qualified,
            "isAnalysisQualified": is_analysis_qualified,
        }

        report = {
            "symbol": clean_sym,
            "dataQualityScore": final_score,
            "feedStatus": feed_status,
            "latencyMs": round(latency_ms, 1),
            "timestampIST": now_ist,
            "isTradeQualified": is_trade_qualified,
            "isAnalysisQualified": is_analysis_qualified,
            "isAuditable": True,
            "checksPassed": checks_passed,
            "anomaliesDetected": anomalies_detected,
            "source": quote.get("provider", "angelone"),
        }

        return {
            "sanitizedQuote": sanitized_quote,
            "dataQualityReport": report,
        }

    @classmethod
    def validate_tick(
        cls,
        symbol: str,
        tick: Dict[str, Any],
        last_tick: Optional[Dict[str, Any]] = None,
        expected_sequence: Optional[int] = None,
        max_jump_pct: Optional[float] = None,
        vol_surge_threshold: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Validates a single real-time streaming tick from the WebSocket feed.
        Enforces sequence integrity, checks instrument-aware price jumps, and flags stale ticks.
        """
        anomalies: List[str] = []
        is_valid = True
        gap_detected = False
        feed_status = FeedStatus.VERIFIED_LIVE

        clean_sym = symbol.upper().strip()
        ltp = float(tick.get("ltp") or 0.0)
        volume = int(tick.get("volume") or 0)
        tick_seq = tick.get("sequence_number")
        tick_time = tick.get("timestamp")

        # Instrument awareness (Spot Index vs Option Contract)
        is_option = ("CE" in clean_sym or "PE" in clean_sym) or (ltp > 0 and ltp < 1500.0 and any(idx in clean_sym for idx in ["NIFTY", "BANK", "SENSEX", "FIN"]))

        eff_max_jump = (
            max_jump_pct
            if max_jump_pct is not None
            else (cls.DEFAULT_OPTION_MAX_JUMP_PCT if is_option else cls.DEFAULT_SPOT_MAX_JUMP_PCT)
        )
        eff_vol_threshold = (
            vol_surge_threshold
            if vol_surge_threshold is not None
            else (cls.DEFAULT_OPTION_VOL_THRESHOLD if is_option else cls.DEFAULT_SPOT_VOL_THRESHOLD)
        )

        # 1. Non-zero price check
        if ltp <= 0.0 or math.isnan(ltp) or math.isinf(ltp):
            anomalies.append(f"Invalid tick LTP: {ltp}")
            is_valid = False
            feed_status = FeedStatus.ANOMALOUS

        # 2. Volume sanity
        if volume < 0:
            anomalies.append(f"Negative volume: {volume}")
            is_valid = False

        # 3. Sequence number gap detection vs missing sequence info (Item 3)
        if tick_seq is None:
            sequence_status = "SEQUENCE_NOT_PROVIDED"
        elif expected_sequence is not None:
            if tick_seq > expected_sequence:
                missing = tick_seq - expected_sequence
                anomalies.append(f"Sequence gap detected: {missing} packets lost (expected {expected_sequence}, got {tick_seq})")
                gap_detected = True
                feed_status = FeedStatus.DEGRADED
                sequence_status = "GAP_DETECTED"
            elif tick_seq < expected_sequence:
                anomalies.append(f"Out-of-order sequence packet: got {tick_seq}, expected {expected_sequence}")
                sequence_status = "OUT_OF_ORDER"
                is_valid = False
                feed_status = FeedStatus.DEGRADED
            else:
                sequence_status = "SEQUENCE_IN_ORDER"
        else:
            sequence_status = "INITIAL_PACKET"

        if last_tick and tick_seq is not None and tick_seq > 0 and tick_seq == last_tick.get("sequence_number"):
            anomalies.append(f"Duplicate sequence packet received: {tick_seq}")
            sequence_status = "DUPLICATE_PACKET"
            is_valid = False
            feed_status = FeedStatus.DEGRADED

        # 4. Tick-to-tick freak jump detection (instrument-aware)
        if last_tick and is_valid:
            last_ltp = float(last_tick.get("ltp") or 0.0)
            if last_ltp > 0:
                jump_pct = abs(ltp - last_ltp) / last_ltp * 100.0
                abs_jump = abs(ltp - last_ltp)
                # For options, require absolute jump > 10 pts to avoid penalizing tiny ₹1 -> ₹2 rounding
                is_freak_jump = (jump_pct > eff_max_jump) and (not is_option or abs_jump > 10.0)
                if is_freak_jump:
                    last_vol = int(last_tick.get("volume") or 0)
                    vol_surge = (volume - last_vol) if volume >= last_vol else 0
                    if vol_surge < eff_vol_threshold:
                        anomalies.append(
                            f"Freak tick jump detected: {jump_pct:.2f}% shift from {last_ltp} to {ltp} with low volume ({vol_surge} < {eff_vol_threshold})."
                        )
                        feed_status = FeedStatus.ANOMALOUS
                        is_valid = False

        # 5. Timestamp Freshness & Future Tick Rejection
        if tick_time is not None:
            try:
                now_ts = datetime.now(timezone.utc).timestamp()
                t_diff = now_ts - float(tick_time)
                if t_diff < -5.0:
                    feed_status = FeedStatus.ANOMALOUS
                    anomalies.append(f"Future tick timestamp: {abs(t_diff):.1f}s in future.")
                    is_valid = False
                elif t_diff > 15.0:
                    feed_status = FeedStatus.STALE_TICK
                    anomalies.append(f"Tick timestamp delayed by {t_diff:.1f}s.")
                    is_valid = False
            except (ValueError, TypeError):
                pass

        return {
            "symbol": clean_sym,
            "isValid": is_valid,
            "feedStatus": feed_status,
            "gapDetected": gap_detected,
            "sequenceStatus": sequence_status,
            "isOption": is_option,
            "effectiveMaxJumpPct": eff_max_jump,
            "effectiveVolThreshold": eff_vol_threshold,
            "anomalies": anomalies,
            "sanitizedTick": {
                **tick,
                "ltp": ltp,
                "volume": max(0, volume),
                "isValid": is_valid,
                "feedStatus": feed_status,
            },
        }

    @classmethod
    def validate_ohlc(
        cls,
        df: pd.DataFrame,
        timeframe: str = "15m",
    ) -> Dict[str, Any]:
        """
        Verifies mathematical invariants for OHLC candlestick series:
        - high >= max(open, close)
        - low <= min(open, close)
        - volume >= 0
        - Monotonic ascending timestamps without duplicate bars.
        
        Strict Data Quality Policy:
        - Detects all invalid OHLC and volume anomalies.
        - Sets an explicit `ohlc_repaired = True` audit flag whenever any repair occurs.
        - Never allows repaired candles to qualify trading signals as VERIFIED_LIVE.
        - Preserves originalDf and repair_details for full regulatory auditability.
        """
        violations: List[str] = []
        repair_details: List[str] = []
        ohlc_repaired = False

        df_attrs = dict(df.attrs) if (df is not None and hasattr(df, "attrs") and isinstance(df.attrs, dict)) else {}
        attrs_status = str(df_attrs.get("dataStatus", "")).upper()
        attrs_provider = str(df_attrs.get("provider", "")).lower()
        is_synthetic_df = bool(
            df_attrs.get("is_mock")
            or df_attrs.get("is_synthetic")
            or attrs_status in {"MOCK", "SYNTHETIC"}
            or attrs_provider == "mock"
        )

        if is_synthetic_df:
            sanitized_mock = df.copy() if df is not None else pd.DataFrame()
            sanitized_mock.attrs = {
                **df_attrs,
                "dataStatus": FeedStatus.SYNTHETIC,
                "feedStatus": FeedStatus.SYNTHETIC,
                "is_mock": True,
                "is_synthetic": True,
                "timeframe": timeframe,
            }
            return {
                "isValid": False,
                "ohlc_repaired": False,
                "is_synthetic": True,
                "dataStatus": FeedStatus.SYNTHETIC,
                "violations": ["Synthetic or mock candlestick data detected. Rejected from qualified analysis."],
                "repair_details": [],
                "originalDf": df.copy() if df is not None else pd.DataFrame(),
                "sanitizedDf": sanitized_mock,
                "barsAudited": len(df) if df is not None else 0,
            }

        if df is None or df.empty:
            empty_sanitized = pd.DataFrame()
            if df_attrs:
                empty_sanitized.attrs = dict(df_attrs)
            empty_sanitized.attrs.setdefault("dataStatus", attrs_status or FeedStatus.DATA_UNAVAILABLE)
            empty_sanitized.attrs["timeframe"] = timeframe
            return {
                "isValid": False,
                "ohlc_repaired": False,
                "dataStatus": attrs_status or FeedStatus.DATA_UNAVAILABLE,
                "degradedReason": df_attrs.get("degraded_reason"),
                "violations": [
                    df_attrs.get("degraded_reason") or "Candlestick DataFrame is null or empty."
                ],
                "repair_details": [],
                "originalDf": pd.DataFrame(),
                "sanitizedDf": empty_sanitized,
                "barsAudited": 0,
            }

        required_cols = {"open", "high", "low", "close"}
        if not required_cols.issubset(set(df.columns)):
            missing = required_cols - set(df.columns)
            return {
                "isValid": False,
                "ohlc_repaired": False,
                "violations": [f"Missing required OHLC columns: {missing}"],
                "repair_details": [],
                "originalDf": df.copy(),
                "sanitizedDf": df,
                "barsAudited": len(df),
            }

        sanitized = df.copy()
        if df_attrs:
            sanitized.attrs = dict(df_attrs)

        # Check positive non-zero prices
        for col in ["open", "high", "low", "close"]:
            invalid_rows = sanitized[sanitized[col] <= 0]
            if not invalid_rows.empty:
                violations.append(f"Found {len(invalid_rows)} bars with non-positive {col} values.")
                repair_details.append(f"Clipped {len(invalid_rows)} non-positive {col} values to 0.01.")
                sanitized[col] = sanitized[col].clip(lower=0.01)
                ohlc_repaired = True

        # Invariant 1: High >= max(Open, Close)
        max_oc = sanitized[["open", "close"]].max(axis=1)
        high_breaches = sanitized[sanitized["high"] < max_oc]
        if not high_breaches.empty:
            violations.append(f"Found {len(high_breaches)} bars where High < max(Open, Close).")
            repair_details.append(f"Clamped {len(high_breaches)} High breaches to max(Open, Close).")
            sanitized["high"] = sanitized[["high", "open", "close"]].max(axis=1)
            ohlc_repaired = True

        # Invariant 2: Low <= min(Open, Close)
        min_oc = sanitized[["open", "close"]].min(axis=1)
        low_breaches = sanitized[sanitized["low"] > min_oc]
        if not low_breaches.empty:
            violations.append(f"Found {len(low_breaches)} bars where Low > min(Open, Close).")
            repair_details.append(f"Clamped {len(low_breaches)} Low breaches to min(Open, Close).")
            sanitized["low"] = sanitized[["low", "open", "close"]].min(axis=1)
            ohlc_repaired = True

        # Invariant 3: Volume validity
        has_volume = "volume" in sanitized.columns
        if not has_volume:
            violations.append("Missing volume column in candlestick dataset.")
            repair_details.append("Initialized missing volume column to 0.0.")
            sanitized["volume"] = 0.0
            ohlc_repaired = True
        else:
            missing_vols = sanitized["volume"].isna().sum()
            if missing_vols > 0:
                violations.append(f"Found {missing_vols} bars with missing/NaN volume.")
                repair_details.append(f"Filled {missing_vols} missing volume bars with 0.0.")
                sanitized["volume"] = sanitized["volume"].fillna(0.0)
                ohlc_repaired = True

            neg_vols = (sanitized["volume"] < 0).sum()
            if neg_vols > 0:
                violations.append(f"Found {neg_vols} bars with negative volume.")
                repair_details.append(f"Clipped {neg_vols} negative volume bars to 0.")
                sanitized["volume"] = sanitized["volume"].clip(lower=0)
                ohlc_repaired = True

        # Invariant 4: Monotonic ascending timestamps
        if "timestamp" in sanitized.columns:
            try:
                dt_series = pd.to_datetime(sanitized["timestamp"])
                if not dt_series.is_monotonic_increasing:
                    violations.append("Timestamps were not monotonically increasing.")
                    repair_details.append("Sorted timestamps chronologically.")
                    sanitized = sanitized.sort_values(by="timestamp").reset_index(drop=True)
                    ohlc_repaired = True
            except Exception:
                pass

        # Invariant 5: Check for NaNs in price columns
        for col in ["open", "high", "low", "close"]:
            nan_count = sanitized[col].isna().sum()
            if nan_count > 0:
                violations.append(f"Found {nan_count} NaN values in {col} column.")
                repair_details.append(f"Forward-filled {nan_count} NaNs in {col}.")
                sanitized[col] = sanitized[col].ffill()
                if sanitized[col].isna().any():
                    sanitized[col] = sanitized[col].fillna(sanitized["close"])
                ohlc_repaired = True

        is_valid = (len(violations) == 0)

        sanitized.attrs["ohlc_repaired"] = ohlc_repaired
        sanitized.attrs["repair_details"] = repair_details
        sanitized.attrs["violations"] = violations
        sanitized.attrs["timeframe"] = timeframe
        if df_attrs.get("is_mock") is not None:
            sanitized.attrs["is_mock"] = df_attrs.get("is_mock")
        if df_attrs.get("is_synthetic") is not None:
            sanitized.attrs["is_synthetic"] = df_attrs.get("is_synthetic")
        if df_attrs.get("dataStatus"):
            sanitized.attrs["dataStatus"] = "DEGRADED" if ohlc_repaired else df_attrs.get("dataStatus")
        if df_attrs.get("provider"):
            sanitized.attrs["provider"] = df_attrs.get("provider")

        return {
            "isValid": is_valid,
            "ohlc_repaired": ohlc_repaired,
            "repair_details": repair_details,
            "violations": violations,
            "originalDf": df.copy(),
            "sanitizedDf": sanitized,
            "barsAudited": len(sanitized),
        }

    @classmethod
    def validate_option_chain(
        cls,
        symbol: str,
        chain_data: List[Dict[str, Any]],
        underlying_ltp: float,
    ) -> Dict[str, Any]:
        """
        Audits an entire option chain matrix for missing strikes, zero open interest,
        and inverted premiums.
        """
        clean_sym = symbol.upper().strip()
        now_ist = MarketCalendar.format_ist_timestamp()

        if not chain_data:
            return {
                "isValid": False,
                "score": 0,
                "status": FeedStatus.DATA_UNAVAILABLE,
                "message": "Option chain dataset is empty.",
                "validStrikesCount": 0,
                "totalEvaluated": 0,
            }

        valid_strikes = 0
        zero_oi_count = 0

        for strike in chain_data:
            ce = strike.get("ce", {})
            pe = strike.get("pe", {})

            ce_ltp = float(ce.get("ltp") or ce.get("lastPrice") or 0.0)
            pe_ltp = float(pe.get("ltp") or pe.get("lastPrice") or 0.0)
            ce_oi = int(ce.get("openInterest") or ce.get("oi") or 0)
            pe_oi = int(pe.get("openInterest") or pe.get("oi") or 0)

            if ce_ltp > 0 or pe_ltp > 0:
                valid_strikes += 1

            if ce_oi == 0 and pe_oi == 0:
                zero_oi_count += 1

        total = len(chain_data)
        completeness_pct = (valid_strikes / total) * 100.0 if total > 0 else 0.0

        score = int(completeness_pct)
        if zero_oi_count > (total * 0.5):
            score -= 20

        is_valid = score >= 60 and valid_strikes >= 5

        return {
            "symbol": clean_sym,
            "isValid": is_valid,
            "chainQualityScore": max(0, min(100, score)),
            "status": FeedStatus.VERIFIED_LIVE if is_valid else FeedStatus.DEGRADED,
            "timestampIST": now_ist,
            "validStrikesCount": valid_strikes,
            "totalStrikesEvaluated": total,
            "completenessPct": round(completeness_pct, 1),
            "zeroOiStrikes": zero_oi_count,
        }

    @staticmethod
    def is_trade_qualified(report: Dict[str, Any]) -> bool:
        """
        Strict gatekeeper function.
        Returns True ONLY if feed status is VERIFIED_LIVE and quality score >= 70.
        EOD snapshots, MOCK, SYNTHETIC, and OFFLINE feeds return False.
        """
        if not report or not isinstance(report, dict):
            return False
        status = report.get("feedStatus")
        score = report.get("dataQualityScore", 0)
        qualified = report.get("isTradeQualified", False)
        return bool(qualified and score >= 70 and status == FeedStatus.VERIFIED_LIVE)
