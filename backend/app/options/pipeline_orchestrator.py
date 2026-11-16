"""
AIVOLVE Institutional Quantitative Trading Intelligence v3.0
Phase 2 Step 4.3: Production API Integration & End-to-End Signal Pipeline Orchestrator

Integrates the accepted quantitative engines into a strict 12-stage sequential workflow:
  Stage 1:  Market data retrieval (Quote, 1H, 15M, 5M, 1M candles)
  Stage 2:  Market data quality validation (DataQualityEngine.validate_quote)
  Stage 3:  Candle completeness & freshness validation (_is_candle_complete, OHLC invariants)
  Stage 4:  Quantitative feature calculation (ATR, VWAP, EMA 20/50/200, ADX)
  Stage 5:  Market regime classification (evaluate_index_market_state)
  Stage 6:  Multi-timeframe confluence analysis (evaluate_multi_timeframe_confluence)
  Stage 7:  Trade setup qualification (select_trade_setup)
  Stage 8:  Options chain validation (generate_index_option_chain)
  Stage 9:  Contract selection (select_option_contract + Ed25519 SENSEX governance)
  Stage 10: Option premium risk calculation (calculate_option_risk_plan)
  Stage 11: Final signal qualification (fail-closed if any stage fails)
  Stage 12: Paper signal persistence & lifecycle tracking (idempotent SignalRecord registration)

STRICT BOUNDARY: Strictly paper trading intelligence. Never executes live broker orders.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
import math
import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from app.data.quality_validator import DataQualityEngine, FeedStatus
from app.data.market_calendar import MarketCalendar
from app.options.candle_processor import process_candlestick_series
from app.options.market_state_engine import (
    evaluate_index_market_state,
    MarketRegime,
    MarketState,
)
from app.options.multi_timeframe_engine import (
    evaluate_multi_timeframe_confluence,
    _is_candle_complete,
)
from app.options.trade_setup_selector import select_trade_setup, DEFAULT_SETUP_CONFIG
from app.options.contract_selector import select_option_contract, normalize_index_symbol
from app.options.option_risk_engine import calculate_option_risk_plan
from app.options.option_chain import generate_index_option_chain
from app.data.providers.factory import get_market_data_provider
from app.services.outcome_tracker import OutcomeTrackerService
from app.models.db_models import SignalRecord
from app.core.logging import logger


class PipelineStage:
    STAGE_1_MARKET_DATA_RETRIEVAL = "1_market_data_retrieval"
    STAGE_2_DATA_QUALITY_AUDIT = "2_data_quality_audit"
    STAGE_3_CANDLE_COMPLETENESS = "3_candle_completeness"
    STAGE_4_QUANTITATIVE_FEATURES = "4_quantitative_features"
    STAGE_5_REGIME_CLASSIFICATION = "5_regime_classification"
    STAGE_6_MTF_CONFLUENCE = "6_mtf_confluence"
    STAGE_7_TRADE_SETUP_QUALIFICATION = "7_trade_setup_qualification"
    STAGE_8_OPTION_CHAIN_VALIDATION = "8_option_chain_validation"
    STAGE_9_CONTRACT_SELECTION = "9_contract_selection"
    STAGE_10_OPTION_RISK_CALCULATION = "10_option_risk_calculation"
    STAGE_11_FINAL_QUALIFICATION = "11_final_qualification"
    STAGE_12_PAPER_PERSISTENCE = "12_paper_persistence"


def canonicalize_symbol(symbol: str) -> str:
    """Canonicalizes symbol into recognized Indian index benchmark format."""
    s = symbol.upper().strip().replace(" ", "").replace("-", "")
    if "BANK" in s:
        return "BANK NIFTY"
    if "FIN" in s:
        return "FINNIFTY"
    if "SENSEX" in s:
        return "SENSEX"
    return "NIFTY 50"


def _filter_completed_candles(
    df: Optional[pd.DataFrame],
    timeframe: Optional[str] = None,
    now_ist: Optional[datetime] = None,
) -> Optional[pd.DataFrame]:
    """
    Excludes live forming, incomplete, and future lookahead candles so that
    structure shifts and trigger evaluations rely exclusively on confirmed closed bars.
    """
    from app.options.multi_timeframe_engine import filter_completed_candles
    return filter_completed_candles(df, timeframe=timeframe, now_ist=now_ist)


def format_to_frontend_options_setups(
    pipeline_result: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Transforms pipeline output into the exact TodayOptionsSetupsResult schema expected
    by the frontend and options routes, enriched with authoritative risk metrics.
    """
    clean_sym = pipeline_result.get("symbol", "NIFTY 50")
    action = pipeline_result.get("action", "NO_TRADE")
    rejection_reasons = pipeline_result.get("rejection_reasons", [])
    now_ist = MarketCalendar.format_ist_timestamp()

    is_qualified = bool(
        pipeline_result.get("is_trade_qualified", False)
        and action in ("BUY_CE", "BUY_PE")
    )

    if not is_qualified:
        status_msg = "NO TRADE — CONDITIONS UNSUITABLE"
        advice = "Wait for clear market structure alignment, confirmed closed candles, and verified quotes."
        if action == "WAIT":
            status_msg = "WAIT — AWAITING MICRO TRIGGER / CONFIRMATION"
            advice = "Market bias is developing. Awaiting confirmed lower timeframe structure trigger before execution."

        return {
            "symbol": clean_sym,
            "hasQualifiedSetups": False,
            "statusMessage": status_msg,
            "disqualificationReasons": rejection_reasons or ["Market conditions not qualified for option buying."],
            "timestamp": now_ist,
            "setups": [],
            "advice": advice,
            "pipelineMetadata": {
                "action": action,
                "marketRegime": pipeline_result.get("market_state", {}).get("market_regime", "NO_TRADE"),
                "confluenceScore": pipeline_result.get("mtf_confluence", {}).get("confluence_score", 0.0),
                "directionalBias": pipeline_result.get("mtf_confluence", {}).get("directional_bias", "NEUTRAL"),
                "isTradeQualified": False,
                "rejectionReasons": rejection_reasons,
            },
        }

    # Format Qualified Setup
    trade_setup = pipeline_result.get("trade_setup", {})
    contract = pipeline_result.get("selected_contract", {})
    risk_plan = pipeline_result.get("risk_plan", {})
    market_state = pipeline_result.get("market_state", {})
    mtf = pipeline_result.get("mtf_confluence", {})

    opt_bias = "CE" if action == "BUY_CE" else "PE"
    strike = float(contract.get("strike", 0.0))
    entry_premium = float(risk_plan.get("entry_premium") or contract.get("ask", 0.0))
    stop_loss = float(risk_plan.get("stop_loss_premium", 0.0))
    t1 = float(risk_plan.get("target_1_premium", 0.0))
    t2 = float(risk_plan.get("target_2_premium", 0.0))
    t3 = float(risk_plan.get("target_3_premium", 0.0))
    rr_t1 = float(risk_plan.get("reward_risk_target_1", 1.5))
    rr_t2 = float(risk_plan.get("reward_risk_target_2", 2.5))
    rr_t3 = float(risk_plan.get("reward_risk_target_3", 3.5))

    delta = float(contract.get("delta") or (0.50 if opt_bias == "CE" else -0.50))
    gamma = float(contract.get("gamma") or 0.001)
    theta = float(contract.get("theta") or -1.5)
    vega = float(contract.get("vega") or 10.0)
    iv = float(contract.get("implied_volatility") or 14.5)
    lot_size = int(contract.get("lot_size", 65 if "NIFTY" in clean_sym else 15))
    max_risk_per_lot = float(risk_plan.get("max_risk_per_lot", (entry_premium - stop_loss) * lot_size))
    potential_gain_per_lot = float(risk_plan.get("potential_gain_per_lot_t1", (t1 - entry_premium) * lot_size))

    supporting_reasons = [
        f"Regime: {market_state.get('market_regime')} with Confluence Score {mtf.get('confluence_score')}/100",
        f"Contract: {contract.get('contract_symbol')} (Delta {abs(delta):.2f}, Moneyness {contract.get('moneyness')})",
        f"Strike Spacing: {contract.get('derived_strike_spacing')} pts dynamically derived from listed chain",
        f"Execution Model: Entry strictly at Ask (₹{entry_premium:.2f}), Exit scenario at Bid less slippage",
        f"Reward-to-Risk: T1 1:{rr_t1:.2f}, T2 1:{rr_t2:.2f}, T3 1:{rr_t3:.2f}",
        f"Institutional Governance: {contract.get('liquidity_policy_status', 'APPROVED')} ({contract.get('liquidity_policy_source', 'Default Centralized Policy')})",
    ]

    setup_dict: Dict[str, Any] = {
        "index": clean_sym,
        "bias": opt_bias,
        "biasLabel": f"{'CALL (CE)' if opt_bias == 'CE' else 'PUT (PE)'} — {market_state.get('market_regime', 'TREND')}",
        "moneyness": contract.get("moneyness", "ATM"),
        "smcModel": mtf.get("itf_structure", {}).get("details", ["Institutional Confluence"])[0] if mtf.get("itf_structure", {}).get("details") else "Order Block / Liquidity Sweep",
        "contractSymbol": contract.get("contract_symbol", f"{clean_sym} {int(strike)} {opt_bias}"),
        "strike": strike,
        "expiry": contract.get("expiry", "Current"),
        "currentPremium": entry_premium,
        "entryRange": f"₹{entry_premium:.2f} (Ask execution)",
        "stopLoss": stop_loss,
        "target1": t1,
        "target2": t2,
        "target3": t3,
        "targetProbabilities": {
            "target1": {
                "price": t1,
                "gainPct": round(((t1 - entry_premium) / entry_premium) * 100.0, 1) if entry_premium > 0 else 0.0,
                "probabilityPct": 0,
                "likelihood": "SCENARIO_TARGET_1",
                "badge": f"RR 1:{rr_t1:.1f}",
                "description": f"Scenario Repricing at Target 1 (BS with +3% IV Expansion, Ask/Bid adjusted)",
            },
            "target2": {
                "price": t2,
                "gainPct": round(((t2 - entry_premium) / entry_premium) * 100.0, 1) if entry_premium > 0 else 0.0,
                "probabilityPct": 0,
                "likelihood": "SCENARIO_TARGET_2",
                "badge": f"RR 1:{rr_t2:.1f}",
                "description": f"Scenario Repricing at Target 2 (BS with +5% IV Expansion, Ask/Bid adjusted)",
            },
            "target3": {
                "price": t3,
                "gainPct": round(((t3 - entry_premium) / entry_premium) * 100.0, 1) if entry_premium > 0 else 0.0,
                "probabilityPct": 0,
                "likelihood": "SCENARIO_TARGET_3",
                "badge": f"RR 1:{rr_t3:.1f}",
                "description": f"Scenario Repricing at Target 3 (BS with +5% IV Expansion, Ask/Bid adjusted)",
            },
        },
        "riskRewardRatio": f"1:{rr_t1:.2f}",
        "maxRiskPerLot": max_risk_per_lot,
        "potentialGainPerLot": potential_gain_per_lot,
        "greeks": {
            "delta": delta,
            "gamma": gamma,
            "thetaPerDay": theta,
            "vega": vega,
        },
        "iv": iv,
        "liquidity": f"OI: {contract.get('oi', 0)}, Vol: {contract.get('volume', 0)}, Spread: {contract.get('spread_pct', 0.0):.2f}%",
        "openInterest": int(contract.get("oi") or 0),
        "changeInOi": int(contract.get("change_in_oi") or 0),
        "underlyingTrigger": trade_setup.get("invalidation_condition", "5M candle close"),
        "invalidationCondition": trade_setup.get("invalidation_condition", "5M candle close"),
        "supportingReasons": supporting_reasons,
        "disclaimer": "Paper trading simulation only. Non-linear Black-Scholes scenario repricing with uncalibrated holding horizons. No live broker execution.",
    }

    return {
        "symbol": clean_sym,
        "hasQualifiedSetups": True,
        "statusMessage": f"QUALIFIED {action} SETUP DETECTED",
        "disqualificationReasons": [],
        "timestamp": now_ist,
        "setups": [setup_dict],
        "advice": f"Paper trade qualification confirmed for {action} on {contract.get('contract_symbol')}. Strict stop-loss at ₹{stop_loss:.2f}.",
        "pipelineMetadata": {
            "action": action,
            "marketRegime": market_state.get("market_regime"),
            "confluenceScore": mtf.get("confluence_score", 0.0),
            "directionalBias": mtf.get("directional_bias"),
            "derivedStrikeSpacing": contract.get("derived_strike_spacing"),
            "capitalAllocationStatus": risk_plan.get("capital_allocation_status"),
            "governanceStatus": contract.get("liquidity_policy_status"),
            "isTradeQualified": True,
            "rejectionReasons": [],
        },
    }


async def execute_production_signal_pipeline(
    symbol: str,
    provider: Optional[Any] = None,
    session: Optional[AsyncSession] = None,
    custom_timeframes: Optional[Dict[str, pd.DataFrame]] = None,
    custom_quote: Optional[Dict[str, Any]] = None,
    custom_option_chain: Optional[Dict[str, Any]] = None,
    available_capital: Optional[float] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Executes the comprehensive 12-stage production quantitative signal pipeline.
    Deterministic, fail-closed, purely analytical / paper-trading.
    """
    clean_sym = canonicalize_symbol(symbol)
    cfg = config or {}
    prov = provider or get_market_data_provider()
    stage_status: Dict[str, str] = {}
    rejection_reasons: List[str] = []

    # -------------------------------------------------------------------------
    # Stage 1: Market Data Retrieval
    # -------------------------------------------------------------------------
    stage_status[PipelineStage.STAGE_1_MARKET_DATA_RETRIEVAL] = "IN_PROGRESS"
    try:
        if custom_quote is not None:
            raw_quote = dict(custom_quote)
        else:
            raw_quote = await prov.get_quote(clean_sym)

        if custom_timeframes is not None:
            raw_timeframes = dict(custom_timeframes)
        else:
            raw_timeframes = {
                "1h": await prov.get_intraday_candles(clean_sym, "1h"),
                "15m": await prov.get_intraday_candles(clean_sym, "15m"),
                "5m": await prov.get_intraday_candles(clean_sym, "5m"),
                "1m": await prov.get_intraday_candles(clean_sym, "1m"),
            }
        stage_status[PipelineStage.STAGE_1_MARKET_DATA_RETRIEVAL] = "SUCCESS"
    except Exception as e:
        stage_status[PipelineStage.STAGE_1_MARKET_DATA_RETRIEVAL] = "FAILED"
        rejection_reasons.append(f"Stage 1 Error: Failed retrieving market data: {str(e)}")
        raw_quote = {}
        raw_timeframes = {}

    # -------------------------------------------------------------------------
    # Stage 2: Market Data Quality Validation
    # -------------------------------------------------------------------------
    stage_status[PipelineStage.STAGE_2_DATA_QUALITY_AUDIT] = "IN_PROGRESS"
    df_15m_ref = raw_timeframes.get("15m") if isinstance(raw_timeframes, dict) else None
    
    # Check synthetic/mock data rejection (quote or any timeframe DataFrame)
    raw_quote_status = str(raw_quote.get("dataStatus", "")).upper()
    raw_quote_provider = str(raw_quote.get("provider", "")).lower()
    has_mock_tf = False
    if isinstance(raw_timeframes, dict):
        for _tf_df in raw_timeframes.values():
            if _tf_df is not None and hasattr(_tf_df, "attrs") and isinstance(_tf_df.attrs, dict):
                _ds = str(_tf_df.attrs.get("dataStatus", "")).upper()
                _pr = str(_tf_df.attrs.get("provider", "")).lower()
                if _tf_df.attrs.get("is_mock") or _tf_df.attrs.get("is_synthetic") or _ds in {"MOCK", "SYNTHETIC"} or _pr == "mock":
                    has_mock_tf = True
                    break

    is_mock = bool(
        raw_quote.get("is_mock", False)
        or raw_quote.get("is_synthetic", False)
        or raw_quote_status in {"MOCK", "SYNTHETIC"}
        or raw_quote_provider == "mock"
        or has_mock_tf
    )
    if is_mock:
        stage_status[PipelineStage.STAGE_2_DATA_QUALITY_AUDIT] = "FAILED"
        rejection_reasons.append("Stage 2 Rejection: Synthetic or mock market data is strictly rejected in production.")
        synthetic_report = {
            "symbol": clean_sym,
            "dataQualityScore": 0,
            "feedStatus": FeedStatus.SYNTHETIC,
            "isTradeQualified": False,
            "isAnalysisQualified": False,
            "isAuditable": True,
            "anomaliesDetected": ["Synthetic or mock market data detected and blocked."],
            "source": raw_quote_provider or "mock",
        }
        return _build_fail_closed_result(
            clean_sym, stage_status, rejection_reasons, raw_quote, raw_timeframes, data_quality_report=synthetic_report
        )

    quality_audit = DataQualityEngine.validate_quote(
        clean_sym, raw_quote, reference_candles=df_15m_ref
    )
    sanitized_quote = quality_audit["sanitizedQuote"]
    data_quality_report = quality_audit["dataQualityReport"]

    feed_status = data_quality_report.get("feedStatus")
    if feed_status in [
        FeedStatus.DATA_UNAVAILABLE,
        FeedStatus.DATA_OFFLINE,
        FeedStatus.SYNTHETIC,
        FeedStatus.ANOMALOUS,
    ]:
        stage_status[PipelineStage.STAGE_2_DATA_QUALITY_AUDIT] = "FAILED"
        rejection_reasons.append(
            f"Stage 2 Rejection: Feed status '{feed_status}' failed data quality gating: {data_quality_report.get('anomaliesDetected')}"
        )
        return _build_fail_closed_result(
            clean_sym, stage_status, rejection_reasons, sanitized_quote, raw_timeframes, data_quality_report
        )

    ltp = float(sanitized_quote.get("currentPrice") or sanitized_quote.get("ltp") or 0.0)
    if ltp <= 0.0 or math.isnan(ltp) or math.isinf(ltp):
        stage_status[PipelineStage.STAGE_2_DATA_QUALITY_AUDIT] = "FAILED"
        rejection_reasons.append(f"Stage 2 Rejection: Invalid LTP ({ltp}) received.")
        return _build_fail_closed_result(
            clean_sym, stage_status, rejection_reasons, sanitized_quote, raw_timeframes, data_quality_report
        )

    if feed_status == FeedStatus.STALE:
        stage_status[PipelineStage.STAGE_2_DATA_QUALITY_AUDIT] = "FAILED"
        rejection_reasons.append(
            f"Stage 2 Rejection: Stale market data stream (latency: {data_quality_report.get('latencyMs')}ms)."
        )
        return _build_fail_closed_result(
            clean_sym, stage_status, rejection_reasons, sanitized_quote, raw_timeframes, data_quality_report
        )

    stage_status[PipelineStage.STAGE_2_DATA_QUALITY_AUDIT] = "SUCCESS"

    # -------------------------------------------------------------------------
    # Stage 3: Candle Completeness & Freshness Validation
    # -------------------------------------------------------------------------
    stage_status[PipelineStage.STAGE_3_CANDLE_COMPLETENESS] = "IN_PROGRESS"
    completed_timeframes: Dict[str, pd.DataFrame] = {}
    has_repaired_data = False
    repaired_details: List[str] = []

    for tf_key, tf_df in raw_timeframes.items():
        if tf_df is not None and not tf_df.empty:
            # Audit OHLC invariants
            ohlc_audit = DataQualityEngine.validate_ohlc(tf_df, timeframe=tf_key)
            if ohlc_audit.get("is_synthetic"):
                stage_status[PipelineStage.STAGE_3_CANDLE_COMPLETENESS] = "FAILED"
                rejection_reasons.append(
                    f"Stage 3 Rejection: Synthetic or mock candles detected on '{tf_key}'. Synthetic data never qualifies."
                )
                data_quality_report["feedStatus"] = FeedStatus.SYNTHETIC
                data_quality_report["isTradeQualified"] = False
                data_quality_report["anomaliesDetected"].extend(ohlc_audit.get("violations", []))
                return _build_fail_closed_result(
                    clean_sym, stage_status, rejection_reasons, sanitized_quote, raw_timeframes, data_quality_report, action="NO_TRADE"
                )

            is_repaired = bool(ohlc_audit.get("ohlc_repaired", False) or not ohlc_audit.get("isValid", True))

            if is_repaired:
                has_repaired_data = True
                v_list = ohlc_audit.get("violations", [])
                repaired_details.append(f"{tf_key}: {', '.join(v_list)}")

                # Required execution and structure timeframes (5m, 15m) MUST fail closed immediately
                # when invalid or repaired data is present, forcing NO_TRADE and preventing fabricated setups.
                if tf_key in ("5m", "15m"):
                    stage_status[PipelineStage.STAGE_3_CANDLE_COMPLETENESS] = "FAILED"
                    rejection_reasons.append(
                        f"Stage 3 Rejection: Repaired or invalid OHLC candles on required timeframe '{tf_key}': {', '.join(v_list)}. Repaired data cannot qualify live trades."
                    )
                    data_quality_report["feedStatus"] = FeedStatus.DEGRADED
                    data_quality_report["isTradeQualified"] = False
                    data_quality_report["anomaliesDetected"].extend(v_list)
                    return _build_fail_closed_result(
                        clean_sym, stage_status, rejection_reasons, sanitized_quote, raw_timeframes, data_quality_report, action="NO_TRADE"
                    )

            # Exclude all live forming, missing-flag, and future lookahead candles using IST boundaries
            completed_timeframes[tf_key] = _filter_completed_candles(ohlc_audit["sanitizedDf"], timeframe=tf_key)
        else:
            tf_attrs = tf_df.attrs if (tf_df is not None and hasattr(tf_df, "attrs") and isinstance(tf_df.attrs, dict)) else {}
            if tf_attrs.get("degraded_reason"):
                data_quality_report["anomaliesDetected"].append(f"{tf_key}: {tf_attrs['degraded_reason']}")
            if str(tf_attrs.get("dataStatus", "")).upper() in {"DEGRADED", "DATA_UNAVAILABLE", "DATA_OFFLINE"} and tf_key in ("5m", "15m"):
                data_quality_report["feedStatus"] = FeedStatus.DEGRADED
                data_quality_report["isTradeQualified"] = False
            completed_timeframes[tf_key] = None

    if has_repaired_data:
        # Repaired data in non-critical timeframes: downgrade feedStatus to DEGRADED and block live qualification
        data_quality_report["feedStatus"] = FeedStatus.DEGRADED
        data_quality_report["isTradeQualified"] = False
        data_quality_report["anomaliesDetected"].append(
            f"OHLC data repair detected: {'; '.join(repaired_details)}"
        )
        feed_status = FeedStatus.DEGRADED

    df_15m = completed_timeframes.get("15m")
    df_5m = completed_timeframes.get("5m")
    df_1h = completed_timeframes.get("1h")
    df_1m = completed_timeframes.get("1m")

    # Strict Lockout Policies:
    # 1. Missing 5M: Total execution lockout
    if df_5m is None or df_5m.empty or len(df_5m) < 4:
        stage_status[PipelineStage.STAGE_3_CANDLE_COMPLETENESS] = "FAILED"
        rejection_reasons.append(
            "Stage 3 Rejection: Total execution lockout — 5M intermediate structure timeframe is missing or has insufficient bars."
        )
        return _build_fail_closed_result(
            clean_sym, stage_status, rejection_reasons, sanitized_quote, completed_timeframes, data_quality_report
        )

    # 2. Missing 15M: Directional trade lockout
    if df_15m is None or df_15m.empty or len(df_15m) < 4:
        stage_status[PipelineStage.STAGE_3_CANDLE_COMPLETENESS] = "FAILED"
        rejection_reasons.append(
            "Stage 3 Rejection: Directional trade lockout — 15M higher timeframe is missing or has insufficient bars."
        )
        return _build_fail_closed_result(
            clean_sym, stage_status, rejection_reasons, sanitized_quote, completed_timeframes, data_quality_report
        )

    stage_status[PipelineStage.STAGE_3_CANDLE_COMPLETENESS] = "SUCCESS"

    # -------------------------------------------------------------------------
    # Stage 4: Quantitative Feature Calculation
    # -------------------------------------------------------------------------
    stage_status[PipelineStage.STAGE_4_QUANTITATIVE_FEATURES] = "IN_PROGRESS"
    candles_info_15m = process_candlestick_series(df_15m, symbol=clean_sym, timeframe="15m")
    candles_info_5m = process_candlestick_series(df_5m, symbol=clean_sym, timeframe="5m")
    stage_status[PipelineStage.STAGE_4_QUANTITATIVE_FEATURES] = "SUCCESS"

    # -------------------------------------------------------------------------
    # Stage 5: Market Regime Classification
    # -------------------------------------------------------------------------
    stage_status[PipelineStage.STAGE_5_REGIME_CLASSIFICATION] = "IN_PROGRESS"
    market_state = evaluate_index_market_state(
        symbol=clean_sym,
        quote=sanitized_quote,
        candles_df=df_15m,
        candles_info=candles_info_15m,
        vix_value=cfg.get("vix_value", 13.5),
        is_live_data=(feed_status in [FeedStatus.VERIFIED_LIVE, FeedStatus.VERIFIED_EOD]),
        config=cfg.get("market_state_config"),
    )

    regime = market_state.get("market_regime")
    if regime in [MarketRegime.NO_TRADE, MarketRegime.DATA_UNAVAILABLE]:
        stage_status[PipelineStage.STAGE_5_REGIME_CLASSIFICATION] = "FAILED"
        reasons = market_state.get("rejection_reasons") or [market_state.get("primaryReason", "Market state unsuitable")]
        rejection_reasons.extend(reasons)
        return _build_fail_closed_result(
            clean_sym, stage_status, rejection_reasons, sanitized_quote, completed_timeframes, data_quality_report, market_state
        )

    if regime == MarketRegime.SIDEWAYS:
        stage_status[PipelineStage.STAGE_5_REGIME_CLASSIFICATION] = "RESTRICTED_SIDEWAYS"
        rejection_reasons.append("Stage 5 Rejection: Index is in SIDEWAYS consolidation. Directional buying locked.")
        return _build_fail_closed_result(
            clean_sym, stage_status, rejection_reasons, sanitized_quote, completed_timeframes, data_quality_report, market_state
        )

    stage_status[PipelineStage.STAGE_5_REGIME_CLASSIFICATION] = "SUCCESS"

    # -------------------------------------------------------------------------
    # Stage 6: Multi-Timeframe Confluence Analysis
    # -------------------------------------------------------------------------
    stage_status[PipelineStage.STAGE_6_MTF_CONFLUENCE] = "IN_PROGRESS"
    mtf_confluence = evaluate_multi_timeframe_confluence(
        symbol=clean_sym,
        timeframe_candles=completed_timeframes,
        current_quote=sanitized_quote,
        vix_value=cfg.get("vix_value", 13.5),
        is_live_data=(feed_status == FeedStatus.VERIFIED_LIVE),
        data_quality_status=feed_status or "VERIFIED_LIVE",
        market_regime_state=market_state,
        config=cfg.get("mtf_config"),
    )

    if not mtf_confluence.get("can_activate_directional", True):
        stage_status[PipelineStage.STAGE_6_MTF_CONFLUENCE] = "LOCKED"
        reasons = mtf_confluence.get("rejection_reasons") or ["Directional activation locked by MTF policy"]
        rejection_reasons.extend(reasons)
        return _build_fail_closed_result(
            clean_sym, stage_status, rejection_reasons, sanitized_quote, completed_timeframes, data_quality_report, market_state, mtf_confluence
        )

    confluence_score = float(mtf_confluence.get("confluence_score", 0.0))
    min_score = float(cfg.get("min_confluence_score", 70.0))
    if confluence_score < min_score:
        stage_status[PipelineStage.STAGE_6_MTF_CONFLUENCE] = "BELOW_THRESHOLD"
        rejection_reasons.append(
            f"Stage 6 Rejection: MTF Confluence score ({confluence_score:.1f}/100) below minimum required ({min_score:.1f})."
        )
        action_fallback = "WAIT" if confluence_score >= 50.0 else "NO_TRADE"
        return _build_fail_closed_result(
            clean_sym, stage_status, rejection_reasons, sanitized_quote, completed_timeframes, data_quality_report, market_state, mtf_confluence, action=action_fallback
        )

    stage_status[PipelineStage.STAGE_6_MTF_CONFLUENCE] = "SUCCESS"

    # -------------------------------------------------------------------------
    # Stage 7: Trade Setup Qualification
    # -------------------------------------------------------------------------
    stage_status[PipelineStage.STAGE_7_TRADE_SETUP_QUALIFICATION] = "IN_PROGRESS"
    merged_setup_config = dict(DEFAULT_SETUP_CONFIG)
    if cfg.get("trade_setup_config") and isinstance(cfg.get("trade_setup_config"), dict):
        merged_setup_config.update(cfg.get("trade_setup_config"))

    trade_setup = select_trade_setup(
        symbol=clean_sym,
        quote=sanitized_quote,
        mtf_confluence=mtf_confluence,
        market_regime_state=market_state,
        vix_value=cfg.get("vix_value", 13.5),
        is_live_data=(feed_status == FeedStatus.VERIFIED_LIVE),
        config=merged_setup_config,
    )

    action = trade_setup.get("action", "NO_TRADE")
    if action not in ("BUY_CE", "BUY_PE"):
        reasons = trade_setup.get("rejection_reasons") or [f"Setup action '{action}' is not actionable for option buying"]
        rejection_reasons.extend(reasons)
        if any("geometry" in str(r).lower() for r in reasons):
            stage_status[PipelineStage.STAGE_7_TRADE_SETUP_QUALIFICATION] = "GEOMETRY_INVALID"
            action = "NO_TRADE"
        else:
            stage_status[PipelineStage.STAGE_7_TRADE_SETUP_QUALIFICATION] = "UNQUALIFIED"
        return _build_fail_closed_result(
            clean_sym, stage_status, rejection_reasons, sanitized_quote, completed_timeframes, data_quality_report, market_state, mtf_confluence, trade_setup=trade_setup, action=action
        )

    # Flatten nested trade_setup parameters so downstream contract & risk engines have direct access
    plan = trade_setup.get("trade_setup") or {}
    if plan and isinstance(plan, dict):
        trade_setup["entry_price"] = plan.get("entry_price")
        trade_setup["stop_loss"] = plan.get("stop_loss")
        trade_setup["target_1"] = plan.get("target_1")
        trade_setup["target_2"] = plan.get("target_2")
        trade_setup["target_3"] = plan.get("target_3")
        trade_setup["invalidation_condition"] = plan.get("invalidation_condition")
        trade_setup["reward_risk_ratio"] = plan.get("reward_risk_ratio")

    # Validate stop-loss and targets geometry
    sl = float(trade_setup.get("stop_loss") or 0.0)
    entry = float(trade_setup.get("entry_price") or ltp)
    t1 = float(trade_setup.get("target_1") or 0.0)
    t2 = float(trade_setup.get("target_2") or 0.0)
    t3 = float(trade_setup.get("target_3") or 0.0)

    if action == "BUY_CE" and not (sl < entry < t1 < t2 < t3):
        stage_status[PipelineStage.STAGE_7_TRADE_SETUP_QUALIFICATION] = "GEOMETRY_INVALID"
        rejection_reasons.append("Stage 7 Rejection: Invalid ascending stop/target geometry for BUY_CE.")
        return _build_fail_closed_result(
            clean_sym, stage_status, rejection_reasons, sanitized_quote, completed_timeframes, data_quality_report, market_state, mtf_confluence, trade_setup=trade_setup
        )

    if action == "BUY_PE" and not (sl > entry > t1 > t2 > t3):
        stage_status[PipelineStage.STAGE_7_TRADE_SETUP_QUALIFICATION] = "GEOMETRY_INVALID"
        rejection_reasons.append("Stage 7 Rejection: Invalid descending stop/target geometry for BUY_PE.")
        return _build_fail_closed_result(
            clean_sym, stage_status, rejection_reasons, sanitized_quote, completed_timeframes, data_quality_report, market_state, mtf_confluence, trade_setup=trade_setup
        )

    stage_status[PipelineStage.STAGE_7_TRADE_SETUP_QUALIFICATION] = "SUCCESS"

    # -------------------------------------------------------------------------
    # Stage 8: Options Chain Validation
    # -------------------------------------------------------------------------
    stage_status[PipelineStage.STAGE_8_OPTION_CHAIN_VALIDATION] = "IN_PROGRESS"
    if custom_option_chain is not None:
        chain = dict(custom_option_chain)
    else:
        chain = generate_index_option_chain(
            clean_sym,
            underlying_ltp=ltp,
            underlying_change=float(sanitized_quote.get("change", 0.0)),
            filter_mode="ATM",
        )

    if not chain or not isinstance(chain, dict) or not chain.get("strikes"):
        stage_status[PipelineStage.STAGE_8_OPTION_CHAIN_VALIDATION] = "FAILED"
        rejection_reasons.append("Stage 8 Rejection: Option chain data is missing, empty, or unreachable.")
        return _build_fail_closed_result(
            clean_sym, stage_status, rejection_reasons, sanitized_quote, completed_timeframes, data_quality_report, market_state, mtf_confluence, trade_setup=trade_setup, option_chain=chain
        )

    chain_audit = DataQualityEngine.validate_option_chain(clean_sym, chain.get("strikes", []), ltp)
    if not chain_audit.get("isValid", True):
        stage_status[PipelineStage.STAGE_8_OPTION_CHAIN_VALIDATION] = "FAILED"
        rejection_reasons.append(
            f"Stage 8 Rejection: Option chain validation failed: {chain_audit.get('anomalies')}"
        )
        return _build_fail_closed_result(
            clean_sym, stage_status, rejection_reasons, sanitized_quote, completed_timeframes, data_quality_report, market_state, mtf_confluence, trade_setup=trade_setup, option_chain=chain
        )

    stage_status[PipelineStage.STAGE_8_OPTION_CHAIN_VALIDATION] = "SUCCESS"

    # -------------------------------------------------------------------------
    # Stage 9: Contract Selection (Delta 0.35 - 0.55, SENSEX Governance)
    # -------------------------------------------------------------------------
    stage_status[PipelineStage.STAGE_9_CONTRACT_SELECTION] = "IN_PROGRESS"
    contract = select_option_contract(
        underlying_setup=trade_setup,
        symbol=clean_sym,
        underlying_spot=ltp,
        option_chain=chain,
        config=cfg.get("contract_selector_config"),
    )

    if contract.get("qualification_status") != "QUALIFIED":
        stage_status[PipelineStage.STAGE_9_CONTRACT_SELECTION] = "FAILED"
        reasons = contract.get("rejection_reasons") or ["Option contract rejected by liquidity or delta criteria"]
        rejection_reasons.extend(reasons)
        return _build_fail_closed_result(
            clean_sym, stage_status, rejection_reasons, sanitized_quote, completed_timeframes, data_quality_report, market_state, mtf_confluence, trade_setup=trade_setup, option_chain=chain, selected_contract=contract
        )

    # Specific SENSEX Governance Check
    if normalize_index_symbol(clean_sym) == "SENSEX":
        pol_status = contract.get("liquidity_policy_status")
        if pol_status != "APPROVED":
            stage_status[PipelineStage.STAGE_9_CONTRACT_SELECTION] = "FAILED"
            rejection_reasons.append(
                f"Stage 9 Rejection: SENSEX institutional approval policy is {pol_status}. Selection locked."
            )
            return _build_fail_closed_result(
                clean_sym, stage_status, rejection_reasons, sanitized_quote, completed_timeframes, data_quality_report, market_state, mtf_confluence, trade_setup=trade_setup, option_chain=chain, selected_contract=contract
            )

    stage_status[PipelineStage.STAGE_9_CONTRACT_SELECTION] = "SUCCESS"

    # -------------------------------------------------------------------------
    # Stage 10: Option Premium Risk Calculation
    # -------------------------------------------------------------------------
    stage_status[PipelineStage.STAGE_10_OPTION_RISK_CALCULATION] = "IN_PROGRESS"
    risk_plan = calculate_option_risk_plan(
        underlying_setup=trade_setup,
        selected_contract=contract,
        risk_config=cfg.get("risk_config"),
        available_capital=available_capital,
    )

    if risk_plan.get("qualification_status") != "QUALIFIED":
        stage_status[PipelineStage.STAGE_10_OPTION_RISK_CALCULATION] = "FAILED"
        reasons = risk_plan.get("rejection_reasons") or ["Risk plan qualification rejected"]
        rejection_reasons.extend(reasons)
        return _build_fail_closed_result(
            clean_sym, stage_status, rejection_reasons, sanitized_quote, completed_timeframes, data_quality_report, market_state, mtf_confluence, trade_setup=trade_setup, option_chain=chain, selected_contract=contract, risk_plan=risk_plan
        )

    # Normalize option risk metrics to top-level fields for downstream consumption
    risk_plan["stop_loss_premium"] = risk_plan.get("option_stop_loss")
    risk_plan["target_1_premium"] = risk_plan.get("option_target_1")
    risk_plan["target_2_premium"] = risk_plan.get("option_target_2")
    risk_plan["target_3_premium"] = risk_plan.get("option_target_3")
    
    rr_dict = risk_plan.get("reward_to_risk", {})
    risk_plan["reward_risk_target_1"] = rr_dict.get("rr_t1", 0.0)
    risk_plan["reward_risk_target_2"] = rr_dict.get("rr_t2", 0.0)
    risk_plan["reward_risk_target_3"] = rr_dict.get("rr_t3", 0.0)

    # Check minimum Reward-to-Risk ratio >= 1.5 on underlying trade setup
    underlying_rr = float(trade_setup.get("reward_risk_ratio") or 0.0)
    if underlying_rr < 1.5:
        stage_status[PipelineStage.STAGE_10_OPTION_RISK_CALCULATION] = "FAILED"
        rejection_reasons.append(f"Stage 10 Rejection: Target 1 Reward-to-Risk ({underlying_rr:.2f}) is below minimum 1.5.")
        return _build_fail_closed_result(
            clean_sym, stage_status, rejection_reasons, sanitized_quote, completed_timeframes, data_quality_report, market_state, mtf_confluence, trade_setup=trade_setup, option_chain=chain, selected_contract=contract, risk_plan=risk_plan
        )

    # Check capital budget allocation against 1 lot premium requirement
    lot_size = float(contract.get("lot_size") or 25)
    ask_price = float(contract.get("ask") or risk_plan.get("entry_premium") or 0.0)
    min_required_capital = round(lot_size * ask_price, 2)

    if available_capital is not None:
        if available_capital < min_required_capital or risk_plan.get("allocated_lots") == 0 or risk_plan.get("position_sizing_status") == "INSUFFICIENT_CAPITAL":
            stage_status[PipelineStage.STAGE_10_OPTION_RISK_CALCULATION] = "CAPITAL_INSUFFICIENT"
            rejection_reasons.append(
                f"Stage 10 Rejection: Insufficient capital for 1 lot (Available: ₹{available_capital:.2f}, Required: ₹{min_required_capital:.2f})."
            )
            return _build_fail_closed_result(
                clean_sym, stage_status, rejection_reasons, sanitized_quote, completed_timeframes, data_quality_report, market_state, mtf_confluence, trade_setup=trade_setup, option_chain=chain, selected_contract=contract, risk_plan=risk_plan
            )

    stage_status[PipelineStage.STAGE_10_OPTION_RISK_CALCULATION] = "SUCCESS"

    # -------------------------------------------------------------------------
    # Stage 11: Final Signal Qualification
    # -------------------------------------------------------------------------
    stage_status[PipelineStage.STAGE_11_FINAL_QUALIFICATION] = "QUALIFIED"
    is_trade_qualified = True

    # -------------------------------------------------------------------------
    # Stage 12: Paper Signal Persistence & Lifecycle Tracking (Idempotent)
    # -------------------------------------------------------------------------
    stage_status[PipelineStage.STAGE_12_PAPER_PERSISTENCE] = "SKIPPED"
    persisted_signal_id = None

    if session is not None and is_trade_qualified:
        stage_status[PipelineStage.STAGE_12_PAPER_PERSISTENCE] = "IN_PROGRESS"
        try:
            tracker = OutcomeTrackerService.get_instance()
            today_str = MarketCalendar.now_ist().strftime("%Y%m%d")
            sig_id = f"SIG-{clean_sym.replace(' ', '')}-{action}-{int(contract['strike'])}-{today_str}"
            
            allocated_lots = risk_plan.get("allocated_lots")
            if allocated_lots is None or int(allocated_lots) <= 0:
                allocated_lots_val = 1
            else:
                allocated_lots_val = int(allocated_lots)

            lot_size_raw = contract.get("lot_size")
            lot_size_val = int(lot_size_raw) if lot_size_raw is not None else 25

            sig_payload = {
                "id": sig_id,
                "symbol": clean_sym,
                "contract_symbol": contract["contract_symbol"],
                "instrument_token": str(contract.get("instrument_token", "0")),
                "strike": float(contract["strike"]),
                "expiry": contract["expiry"],
                "option_type": contract["option_type"],
                "underlying_price_at_signal": ltp,
                "signal_premium": float(risk_plan["entry_premium"]),
                "signal_bid": float(contract["bid"]),
                "signal_ask": float(contract["ask"]),
                "entry_zone_min": float(risk_plan["entry_premium"]),
                "entry_zone_max": round(float(risk_plan["entry_premium"]) * 1.02, 2),
                "entry_trigger_condition": trade_setup.get("invalidation_condition", ""),
                "stop_loss_premium": float(risk_plan["stop_loss_premium"]),
                "target_1_premium": float(risk_plan["target_1_premium"]),
                "target_2_premium": float(risk_plan["target_2_premium"]),
                "target_3_premium": float(risk_plan["target_3_premium"]),
                "sentiment": "BULLISH" if action == "BUY_CE" else "BEARISH",
                "analysis_score": int(mtf_confluence.get("confluence_score", 75)),
                "confidence": "High" if mtf_confluence.get("confluence_score", 0) >= 80 else "Moderate",
                "supporting_factors": [
                    f"Confluence Score: {mtf_confluence.get('confluence_score')}/100",
                    f"Regime: {market_state.get('market_regime')}",
                    f"Derived Strike Spacing: {contract.get('derived_strike_spacing')}",
                    f"RR: 1:{risk_plan.get('reward_risk_target_1')} (T1), 1:{risk_plan.get('reward_risk_target_2')} (T2)",
                ],
                "lot_size": lot_size_val,
                "allocated_lots": allocated_lots_val,
            }

            existing_rec = await session.get(SignalRecord, sig_id)
            is_dup = (existing_rec is not None)

            signal_record = await tracker.register_signal(session, sig_payload)
            await session.commit()
            persisted_signal_id = signal_record.id
            stage_status[PipelineStage.STAGE_12_PAPER_PERSISTENCE] = "DUPLICATE" if is_dup else "PERSISTED"
            is_duplicate_signal = is_dup
        except Exception as e:
            try:
                await session.rollback()
            except Exception:
                pass
            logger.warning(f"Error persisting paper signal in Stage 12: {e}")
            stage_status[PipelineStage.STAGE_12_PAPER_PERSISTENCE] = "PERSISTENCE_FAILED"

    # Assemble complete authoritative pipeline result
    pipeline_result = {
        "symbol": clean_sym,
        "action": action,
        "is_trade_qualified": is_trade_qualified,
        "is_duplicate": is_duplicate_signal if 'is_duplicate_signal' in locals() else False,
        "stage_status": stage_status,
        "rejection_reasons": rejection_reasons,
        "sanitized_quote": sanitized_quote,
        "data_quality_report": data_quality_report,
        "market_state": market_state,
        "mtf_confluence": mtf_confluence,
        "trade_setup": trade_setup,
        "option_chain": chain,
        "selected_contract": contract,
        "risk_plan": risk_plan,
        "persisted_signal_id": persisted_signal_id,
        "disclaimer": "Institutional paper trading simulation only. Zero live broker orders executed.",
    }

    pipeline_result["frontend_options_setups"] = format_to_frontend_options_setups(pipeline_result)
    return pipeline_result


def _build_fail_closed_result(
    symbol: str,
    stage_status: Dict[str, str],
    rejection_reasons: List[str],
    quote: Dict[str, Any],
    timeframes: Dict[str, Any],
    data_quality_report: Optional[Dict[str, Any]] = None,
    market_state: Optional[Dict[str, Any]] = None,
    mtf_confluence: Optional[Dict[str, Any]] = None,
    trade_setup: Optional[Dict[str, Any]] = None,
    option_chain: Optional[Dict[str, Any]] = None,
    selected_contract: Optional[Dict[str, Any]] = None,
    risk_plan: Optional[Dict[str, Any]] = None,
    action: str = "NO_TRADE",
) -> Dict[str, Any]:
    """Builds a deterministic, fail-closed result structure."""
    stage_status[PipelineStage.STAGE_11_FINAL_QUALIFICATION] = "REJECTED"
    stage_status[PipelineStage.STAGE_12_PAPER_PERSISTENCE] = "SKIPPED"

    res = {
        "symbol": symbol,
        "action": action,
        "is_trade_qualified": False,
        "stage_status": stage_status,
        "rejection_reasons": rejection_reasons,
        "sanitized_quote": quote,
        "data_quality_report": data_quality_report or {"feedStatus": "UNKNOWN", "isTradeQualified": False},
        "market_state": market_state or {"market_regime": MarketRegime.NO_TRADE},
        "mtf_confluence": mtf_confluence or {"confluence_score": 0.0, "can_activate_directional": False},
        "trade_setup": trade_setup or {"action": action},
        "option_chain": option_chain or {},
        "selected_contract": selected_contract or {"qualification_status": "REJECTED"},
        "risk_plan": risk_plan or {"qualification_status": "REJECTED"},
        "persisted_signal_id": None,
        "disclaimer": "Institutional paper trading simulation only. Zero live broker orders executed.",
    }
    res["frontend_options_setups"] = format_to_frontend_options_setups(res)
    return res
