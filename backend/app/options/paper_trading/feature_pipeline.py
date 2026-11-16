"""
Phase 5.2A: Production-Grade Feature Pipeline Hardening & Leakage Prevention Engine.

Implements strict validation, rejection of fallbacks, provenance tracking,
temporal ordering, and isolated dataset routing for quantitative ML.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import math
import os
import re
from typing import Any, Dict, List, Optional, Set, Tuple
import zoneinfo

from app.data.market_calendar import MarketCalendar

IST_ZONE = zoneinfo.ZoneInfo("Asia/Kolkata")
SCHEMA_VERSION = "2.0.0"

# Strict 14 features schema definition
EXPECTED_FEATURE_NAMES = [
    "iv",               # Implied Volatility (0.01 - 3.0)
    "delta",            # Option Delta (-1.0 to +1.0)
    "theta",            # Option Theta (negative daily rupee decay)
    "gamma",            # Option Gamma (>= 0.0)
    "spread",           # Bid-Ask spread (> 0.0)
    "vix",              # India VIX (5.0 - 100.0)
    "atr",              # Underlying ATR 14 (> 0.0)
    "vwap_dist_pct",    # Distance from VWAP (%)
    "dealing_pos_pct",  # Dealing range position % (0.0 - 100.0)
    "mtf_score",        # Multi-timeframe confluence score (0.0 - 100.0)
    "is_sweep_reclaim", # 1.0 if sweep with reclaim, else 0.0
    "bos_disp_ratio",   # Displacement ratio (> 0.0)
    "fvg_gap_pts",      # FVG gap points (>= 0.0)
    "pcr_oi",           # Put-Call Ratio (> 0.0)
]


class DatasetDestination(str, Enum):
    PRODUCTION = "PRODUCTION"
    SYNTHETIC_BASELINE = "SYNTHETIC_BASELINE"
    EXCLUDED_TEST = "EXCLUDED_TEST"


@dataclass
class FeatureValidationResult:
    is_valid: bool
    feature_vector: Optional[List[float]] = None
    error_code: Optional[str] = None
    rejection_reasons: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class FeaturePipelineValidator:
    """
    Institutional Feature Validation & Causal Leakage Guard.
    Guarantees no fabricated, defaulted, incomplete, or look-ahead feature vectors
    can enter production ML datasets.
    """

    @classmethod
    def validate_and_extract(
        cls,
        trade: Dict[str, Any],
        is_production_mode: bool = True,
        strict_session_check: bool = True,
    ) -> FeatureValidationResult:
        rejection_reasons: List[str] = []

        # 1. Structure and Contract Sanity
        trade_id = trade.get("id") or trade.get("tradeId")
        if not trade_id:
            rejection_reasons.append("Missing unique trade identifier (id/tradeId).")

        contract_symbol = trade.get("contractSymbol") or trade.get("contract")
        if not contract_symbol:
            rejection_reasons.append("Missing contract symbol.")
        elif is_production_mode:
            # Check for test symbols
            if "TEST" in str(contract_symbol).upper():
                rejection_reasons.append(f"Test contract detected in production pipeline: '{contract_symbol}'.")
            # Verify valid symbol format (e.g. NIFTY17NOV2625150CE)
            if not re.match(r"^[A-Z0-9_\-]+(CE|PE)$", str(contract_symbol).upper()):
                rejection_reasons.append(f"Invalid option contract format: '{contract_symbol}'.")

        # 2. Market Features Existence Check (Strict NO Silent Fallback)
        features_dict = trade.get("marketFeaturesAtEntry")
        if not features_dict or not isinstance(features_dict, dict) or len(features_dict) == 0:
            rejection_reasons.append("marketFeaturesAtEntry is empty or missing. Silent fallbacks strictly forbidden.")
            return FeatureValidationResult(
                is_valid=False,
                error_code="FEATURE_EXTRACTION_FAILED",
                rejection_reasons=rejection_reasons,
            )

        # 3. Greeks Provenance
        greeks = features_dict.get("greeks")
        if not greeks or not isinstance(greeks, dict) or len(greeks) == 0:
            rejection_reasons.append("Option Greeks dictionary missing in marketFeaturesAtEntry.")
        else:
            # Check mandatory greeks
            for g_name in ["iv", "delta", "theta", "gamma"]:
                if g_name not in greeks or greeks[g_name] is None:
                    rejection_reasons.append(f"Mandatory Greek '{g_name}' is missing or None.")

        # 4. Mandatory Market & MTF Signals
        for m_key in ["vix", "atr", "vwapDistancePct", "dealingRangePct", "mtfConfluenceScore", "displacementRatio", "fvgGapPts", "pcr"]:
            if m_key not in features_dict or features_dict[m_key] is None:
                rejection_reasons.append(f"Mandatory feature key '{m_key}' is missing or None.")

        if "spread" not in trade or trade["spread"] is None:
            if "spread" not in features_dict or features_dict["spread"] is None:
                rejection_reasons.append("Bid-ask spread is missing or None.")

        # 5. Market Session & Timestamp Temporal Validity
        entry_ts_str = trade.get("entryTimestamp") or trade.get("timestamp")
        parsed_dt: Optional[datetime] = None
        if not entry_ts_str:
            rejection_reasons.append("Entry timestamp is missing.")
        else:
            try:
                # Support standard IST string or ISO-8601
                if "IST" in entry_ts_str:
                    clean_ts = entry_ts_str.replace(" IST", "").strip()
                    parsed_dt = datetime.strptime(clean_ts, "%d %b %Y, %I:%M %p").replace(tzinfo=IST_ZONE)
                else:
                    parsed_dt = datetime.fromisoformat(entry_ts_str)
                    if parsed_dt.tzinfo is None:
                        parsed_dt = parsed_dt.replace(tzinfo=timezone.utc).astimezone(IST_ZONE)
            except Exception as e:
                rejection_reasons.append(f"Invalid timestamp format '{entry_ts_str}': {e}")

        if parsed_dt:
            # Future timestamp guard
            now_ist = MarketCalendar.now_ist()
            if (parsed_dt - now_ist).total_seconds() > 5.0:
                rejection_reasons.append(f"Future timestamp leakage detected: entry '{parsed_dt}' is ahead of clock '{now_ist}'.")

            # Trading hours check if strict
            if strict_session_check and is_production_mode:
                if not MarketCalendar.is_market_open(parsed_dt):
                    rejection_reasons.append(f"Timestamp '{parsed_dt}' is outside regular exchange trading hours (09:15 - 15:30 IST).")

        # 6. Extract Values & Type/Range/Finite Verification
        if rejection_reasons:
            return FeatureValidationResult(
                is_valid=False,
                error_code="FEATURE_EXTRACTION_FAILED",
                rejection_reasons=rejection_reasons,
            )

        try:
            iv = float(greeks["iv"])
            delta = float(greeks["delta"])
            theta = float(greeks["theta"])
            gamma = float(greeks["gamma"])
            spread = float(trade.get("spread") or features_dict.get("spread"))
            vix = float(features_dict["vix"])
            atr = float(features_dict["atr"])
            vwap_dist = float(features_dict["vwapDistancePct"])
            dealing_pos = float(features_dict["dealingRangePct"])
            mtf_score = float(features_dict["mtfConfluenceScore"])
            is_sweep = 1.0 if ("Sweep" in trade.get("ictSetup", "") or features_dict.get("sweepReclaim")) else 0.0
            disp_ratio = float(features_dict["displacementRatio"])
            fvg_gap = float(features_dict["fvgGapPts"])
            pcr = float(features_dict["pcr"])

            raw_vector = [
                iv, delta, theta, gamma, spread, vix, atr,
                vwap_dist, dealing_pos, mtf_score, is_sweep,
                disp_ratio, fvg_gap, pcr
            ]

            # Finite and boundary validation
            for i, val in enumerate(raw_vector):
                feat_name = EXPECTED_FEATURE_NAMES[i]
                if math.isnan(val) or math.isinf(val):
                    rejection_reasons.append(f"Feature '{feat_name}' is NaN or Infinite: {val}")

            # Delta bounds check: call (0 to 1), put (-1 to 0)
            bias = str(trade.get("bias", "")).upper()
            if bias == "CE" and not (0.0 <= delta <= 1.0):
                rejection_reasons.append(f"Call delta out of theoretical bounds [0.0, 1.0]: {delta}")
            elif bias == "PE" and not (-1.0 <= delta <= 0.0):
                rejection_reasons.append(f"Put delta out of theoretical bounds [-1.0, 0.0]: {delta}")

            if iv <= 0.0:
                rejection_reasons.append(f"Implied volatility must be strictly positive: {iv}")
            if spread < 0.0:
                rejection_reasons.append(f"Bid-ask spread cannot be negative: {spread}")
            if vix <= 0.0:
                rejection_reasons.append(f"VIX must be strictly positive: {vix}")

            # Detect Identical Homogenized Fallback Vector
            fallback_pattern = [0.14, 0.5, -12.0, 0.002, 1.2, 13.5, 110.0, 0.002, 35.0, 85.0, 1.0, 1.5, 20.0, 1.1]
            if raw_vector == fallback_pattern or raw_vector == [0.14, -0.5, -12.0, 0.002, 1.2, 13.5, 110.0, 0.002, 65.0, 85.0, 1.0, 1.5, 20.0, 1.1]:
                rejection_reasons.append("Identical artificial fallback feature vector detected. Homogenized test vectors rejected.")

            if rejection_reasons:
                return FeatureValidationResult(
                    is_valid=False,
                    error_code="FEATURE_EXTRACTION_FAILED",
                    rejection_reasons=rejection_reasons,
                )

            return FeatureValidationResult(
                is_valid=True,
                feature_vector=raw_vector,
                metadata={
                    "schema_version": SCHEMA_VERSION,
                    "extracted_at": MarketCalendar.now_ist().isoformat(),
                    "trade_id": trade_id,
                    "contract": contract_symbol,
                    "feature_names": EXPECTED_FEATURE_NAMES,
                }
            )

        except (ValueError, TypeError) as e:
            return FeatureValidationResult(
                is_valid=False,
                error_code="NUMERIC_CONVERSION_ERROR",
                rejection_reasons=[f"Error converting feature to float: {e}"],
            )

