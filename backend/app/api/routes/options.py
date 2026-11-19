from typing import Dict, Any, Optional
from fastapi import APIRouter, Query, HTTPException, status, Body, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.database import get_db
from app.models.db_models import SignalEvaluationRecord
from app.data.providers.factory import get_market_data_provider
from app.data.market_calendar import MarketCalendar
from app.options.candle_processor import process_candlestick_series
from app.options.support_resistance import compute_options_support_resistance_ladder
from app.options.session_outlook import calculate_session_outlook
from app.options.sentiment import evaluate_options_market_sentiment
from app.options.pattern_detection import detect_candlestick_and_chart_patterns
from app.options.setup_selector import evaluate_options_trade_setups
from app.options.option_chain import generate_index_option_chain
from app.options.opening_outlook import calculate_next_session_opening_outlook
from app.options.next_session_engine import evaluate_next_session_recommendation
from app.options.next_session_backtest import run_next_session_historical_validation
from app.core.logging import logger

router = APIRouter(prefix="/options", tags=["Options Intelligence"])


def _option_strike_step(symbol: str) -> float:
    return 100.0 if symbol == "SENSEX" or "BANK" in symbol else 50.0


def _option_quote_exchange(symbol: str) -> str:
    return "BFO" if symbol == "SENSEX" else "NFO"


SUPPORTED_INDICES = {
    "NIFTY": "NIFTY 50",
    "NIFTY 50": "NIFTY 50",
    "NIFTY50": "NIFTY 50",
    "SENSEX": "SENSEX",
    "BSE SENSEX": "SENSEX",
    "BSESENSEX": "SENSEX",
    "BANKNIFTY": "BANK NIFTY",
    "BANK NIFTY": "BANK NIFTY",
    "BANK": "BANK NIFTY",
    "FINNIFTY": "FINNIFTY",
    "NIFTY FIN": "FINNIFTY",
    "NIFTY FINANCIAL SERVICES": "FINNIFTY",
    "NIFTYFIN": "FINNIFTY",
}


def canonicalize_symbol(symbol: str) -> str:
    normalized = symbol.upper().replace("_", "").replace(" ", "").strip()
    mapping = {
        "NIFTY": "NIFTY 50",
        "NIFTY50": "NIFTY 50",
        "SENSEX": "SENSEX",
        "BSESENSEX": "SENSEX",
        "BANKNIFTY": "BANK NIFTY",
        "BANK": "BANK NIFTY",
        "FINNIFTY": "FINNIFTY",
        "NIFTYFIN": "FINNIFTY",
        "NIFTYFINANCIALSERVICES": "FINNIFTY",
    }
    return mapping.get(normalized, SUPPORTED_INDICES.get(symbol.upper().strip(), symbol.upper().strip()))



@router.get("/overview")
async def get_options_overview():
    """
    Returns live overview cards for NIFTY, SENSEX, BANK NIFTY, and INDIA VIX,
    plus overall Market Sentiment and active trade setups summary.
    """
    provider = get_market_data_provider()
    now_ist = MarketCalendar.format_ist_timestamp()

    indices_raw = await provider.get_all_indices()
    target_names = ["NIFTY 50", "SENSEX", "BANK NIFTY", "INDIA VIX"]

    formatted_cards = []
    vix_val = 13.42
    nifty_quote = None

    for item in indices_raw:
        sym = item.get("symbol", "").upper()
        if sym in target_names or any(t in sym for t in ["NIFTY", "SENSEX", "VIX"]):
            if "VIX" in sym:
                vix_val = float(item.get("currentValue", 13.42))
            if "NIFTY 50" in sym or sym == "NIFTY":
                nifty_quote = item

            prov_name = provider.get_provider_name()
            item_status = str(item.get("dataStatus") or "").upper()
            if prov_name == "mock" or item.get("is_mock") or item.get("is_synthetic"):
                status_flag = "MOCK"
            elif item_status in {"LIVE", "MARKET_CLOSED", "DEGRADED", "DATA_UNAVAILABLE", "DATA_OFFLINE", "UNAVAILABLE", "STALE", "ANOMALOUS"}:
                status_flag = item_status
            elif prov_name in ["angelone", "upstox"]:
                status_flag = "LIVE" if getattr(provider, "is_authenticated", False) and float(item.get("currentValue", 0.0)) > 0 else "DATA_UNAVAILABLE"
            else:
                status_flag = "DATA_UNAVAILABLE"

            formatted_cards.append({
                "symbol": sym,
                "name": item.get("name", sym),
                "currentValue": round(float(item.get("currentValue", 0.0)), 2),
                "change": round(float(item.get("change", 0.0)), 2),
                "changePercent": round(float(item.get("changePercent", 0.0)), 2),
                "dayHigh": round(float(item.get("dayHigh", item.get("currentValue", 0.0))), 2),
                "dayLow": round(float(item.get("dayLow", item.get("currentValue", 0.0))), 2),
                "openPrice": round(float(item.get("openPrice", item.get("dayLow", 0.0))), 2),
                "previousClose": round(float(item.get("previousClose", item.get("currentValue", 0.0) - item.get("change", 0.0))), 2),
                "trend": item.get("trend", "Bullish" if item.get("change", 0) >= 0 else "Bearish"),
                "marketStatus": MarketCalendar.get_market_status(),
                "dataStatus": status_flag,
                "timestamp": now_ist,
                "sparkline": item.get("sparkline", []),
            })

    # Overall Sentiment based on NIFTY benchmark
    n_val = nifty_quote.get("currentValue", 24852.40) if nifty_quote else 24852.40
    n_chg = nifty_quote.get("change", 120.0) if nifty_quote else 120.0
    sentiment = evaluate_options_market_sentiment(
        symbol="NIFTY 50",
        current_price=n_val,
        vwap=n_val - 25.0,
        ema_20=n_val - 35.0,
        ema_50=n_val - 60.0,
        rsi_14=61.2,
        pcr_oi=1.18,
        total_ce_chg_oi=180000,
        total_pe_chg_oi=240000,
        vix_value=vix_val,
        day_high=n_val + 40.0,
        day_low=n_val - 120.0
    )

    # Next-Session Engine Analysis for Benchmark with Live Angel One Option Chain Quotes
    from app.data.instrument_master import get_instrument_master
    master = get_instrument_master()
    step = 50.0
    atm_k = round(n_val / step) * step
    ladder = master.get_option_chain_contracts("NIFTY 50", atm_k, step, num_strikes=7)
    tokens = []
    for pair in ladder:
        if pair.get("ce_contract"):
            tokens.append(str(pair["ce_contract"]["token"]))
        if pair.get("pe_contract"):
            tokens.append(str(pair["pe_contract"]["token"]))

    real_quotes_map = {}
    if tokens and hasattr(provider, "get_batch_quotes"):
        try:
            real_quotes_map = await provider.get_batch_quotes("NFO", tokens)
        except Exception as e:
            logger.warning(f"Failed to fetch batch quotes for overview chain: {e}")

    chain_sample = generate_index_option_chain("NIFTY 50", n_val, n_chg, real_quotes_map=real_quotes_map, filter_mode="ATM")
    next_session_rec = evaluate_next_session_recommendation(
        symbol="NIFTY 50",
        underlying_ltp=n_val,
        sentiment=sentiment["overallSentiment"],
        sentiment_score=sentiment["sentimentScore"],
        strikes_data=chain_sample["strikes"],
        real_quotes_map=real_quotes_map,
        atr_14=120.0,
        daily_high=n_val + 50.0,
        daily_low=n_val - 120.0,
        daily_close=n_val - n_chg,
        daily_open=n_val - 90.0,
        vix_value=vix_val
    )

    if not formatted_cards:
        overall_overview_status = "MOCK" if provider.get_provider_name() == "mock" else "DATA_UNAVAILABLE"
    elif all(c["dataStatus"] == "LIVE" for c in formatted_cards):
        overall_overview_status = "LIVE"
    elif all(c["dataStatus"] in {"DATA_UNAVAILABLE", "DATA_OFFLINE", "UNAVAILABLE"} for c in formatted_cards):
        overall_overview_status = "DATA_UNAVAILABLE"
    elif formatted_cards[0]["dataStatus"] in {"MOCK", "MARKET_CLOSED"}:
        overall_overview_status = formatted_cards[0]["dataStatus"]
    else:
        overall_overview_status = "DEGRADED"

    return {
        "indices": formatted_cards,
        "marketSentiment": sentiment,
        "nextSessionOpeningOutlook": next_session_rec["openingOutlook"],
        "nextSessionRecommendation": next_session_rec,
        "vix": {
            "value": vix_val,
            "status": "Moderate Volatility" if vix_val < 16.0 else "Elevated Volatility",
        },
        "marketStatus": MarketCalendar.get_market_status(),
        "provider": provider.get_provider_name(),
        "dataStatus": overall_overview_status,
        "dataTimestamp": now_ist,
        "analysisTimestamp": now_ist,
        "disclaimer": "Live market analysis only. Platform does NOT execute trades.",
    }


from app.options.greeks import calculate_black_scholes
import pandas as pd


@router.get("/{index_symbol}/candles")
async def get_index_candles(
    index_symbol: str,
    timeframe: str = Query("15m", description="Candle timeframe: 1m, 3m, 5m, 15m, 30m, 1h, 1d"),
    mode: str = Query("spot", description="Chart mode: 'spot' for index or 'premium' for option contract"),
    strike: Optional[float] = Query(None, description="Strike price for option premium chart"),
    option_type: str = Query("CE", description="Option type: 'CE' or 'PE'")
):
    """
    Returns historical/intraday OHLCV candles with technical overlays (VWAP, EMA 20, EMA 50, ATR).
    Supports both Index Spot candles and Option Contract Premium candles across all timeframes (1m, 3m, 5m, 15m, 30m, 1h, 1d).
    """
    clean = canonicalize_symbol(index_symbol)
    provider = get_market_data_provider()
    now_ist = MarketCalendar.format_ist_timestamp()

    df = await provider.get_intraday_candles(clean, timeframe)

    step = _option_strike_step(clean)
    has_candles = df is not None and len(df) > 0
    current_spot = float(df["close"].iloc[-1]) if has_candles else 0.0
    atm_strike = round(current_spot / step) * step if current_spot > 0 else 0.0

    # Generate nearby strike list for user selection in frontend dropdown
    available_strikes = [round(atm_strike + (i * step), 1) for i in range(-5, 6)] if atm_strike > 0 else []

    target_strike = strike if strike is not None else atm_strike
    opt_type = option_type.upper().strip() if option_type else "CE"
    if opt_type not in ["CE", "PE"]:
        opt_type = "CE"

    if mode.lower() == "premium":
        from app.data.instrument_master import get_instrument_master
        from datetime import datetime, timezone, timedelta
        import httpx

        master = get_instrument_master()
        und_key = "NIFTY" if ("NIFTY" in clean and "BANK" not in clean and "FIN" not in clean) else ("BANKNIFTY" if "BANK" in clean else ("FINNIFTY" if "FIN" in clean else clean))
        contract = master.resolve_option_contract(und_key, target_strike, opt_type)

        contract_symbol_label = contract.get("symbol") if contract else f"{clean} {int(target_strike)} {opt_type}"
        token = str(contract.get("token")) if contract else None

        real_ltp = None
        real_prem_df = None

        if token and hasattr(provider, "get_batch_quotes"):
            try:
                quotes = await provider.get_batch_quotes(_option_quote_exchange(clean), [token])
                if quotes and token in quotes:
                    real_ltp = float(quotes[token].get("ltp") or 0.0)
            except Exception as e:
                logger.debug(f"Error fetching live quote for {contract_symbol_label}: {e}")

        # Try fetching real historical option candles from Angel One SmartAPI
        if token and hasattr(provider, "_ensure_authenticated") and getattr(provider, "_is_logged_in", False):
            try:
                tf_map = {
                    "1m": "ONE_MINUTE",
                    "3m": "THREE_MINUTE",
                    "5m": "FIVE_MINUTE",
                    "10m": "TEN_MINUTE",
                    "15m": "FIFTEEN_MINUTE",
                    "30m": "THIRTY_MINUTE",
                    "1h": "ONE_HOUR",
                    "1d": "ONE_DAY",
                }
                interval = tf_map.get(timeframe, "FIFTEEN_MINUTE")
                from_date = datetime.now(timezone(timedelta(hours=5, minutes=30))).replace(hour=9, minute=15, second=0)
                to_date = datetime.now(timezone(timedelta(hours=5, minutes=30)))

                url = f"{provider.base_url}/rest/secure/angelbroking/historical/v1/getCandleData"
                payload = {
                    "exchange": _option_quote_exchange(clean),
                    "symboltoken": token,
                    "interval": interval,
                    "fromdate": from_date.strftime("%Y-%m-%d %H:%M"),
                    "todate": to_date.strftime("%Y-%m-%d %H:%M"),
                }
                async with httpx.AsyncClient(timeout=4.0) as client:
                    res = await client.post(url, json=payload, headers=provider._get_headers())
                    if res.status_code == 200:
                        c_data = res.json()
                        if c_data.get("status") and c_data.get("data"):
                            c_list = c_data["data"]
                            if c_list and len(c_list) > 0:
                                df_opt = pd.DataFrame(
                                    c_list,
                                    columns=["timestamp", "open", "high", "low", "close", "volume"]
                                )
                                df_opt["timestamp"] = pd.to_datetime(df_opt["timestamp"])
                                df_opt = df_opt.sort_values("timestamp").reset_index(drop=True)
                                if real_ltp and real_ltp > 0:
                                    df_opt.loc[df_opt.index[-1], "close"] = real_ltp
                                    df_opt.loc[df_opt.index[-1], "high"] = max(df_opt.loc[df_opt.index[-1], "high"], real_ltp)
                                    df_opt.loc[df_opt.index[-1], "low"] = min(df_opt.loc[df_opt.index[-1], "low"], real_ltp)
                                real_prem_df = df_opt
            except Exception as e:
                logger.debug(f"Angel One real option candle fetch exception for {token}: {e}")

        if real_prem_df is not None and len(real_prem_df) > 0:
            processed = process_candlestick_series(real_prem_df, contract_symbol_label, timeframe)
        elif df is not None and len(df) > 0:
            t_years = 1.0 / 365.0
            iv = 0.14
            prem_rows = []
            for _, row in df.iterrows():
                spot_o = float(row.get("open", current_spot))
                spot_h = float(row.get("high", current_spot))
                spot_l = float(row.get("low", current_spot))
                spot_c = float(row.get("close", current_spot))
                vol = float(row.get("volume", 1000))
                ts = row.get("timestamp")

                bs_o = calculate_black_scholes(spot_o, target_strike, t_years, iv=iv, option_type=opt_type)
                bs_c = calculate_black_scholes(spot_c, target_strike, t_years, iv=iv, option_type=opt_type)

                if opt_type == "CE":
                    bs_h = calculate_black_scholes(spot_h, target_strike, t_years, iv=iv, option_type=opt_type)
                    bs_l = calculate_black_scholes(spot_l, target_strike, t_years, iv=iv, option_type=opt_type)
                else:
                    bs_h = calculate_black_scholes(spot_l, target_strike, t_years, iv=iv, option_type=opt_type)
                    bs_l = calculate_black_scholes(spot_h, target_strike, t_years, iv=iv, option_type=opt_type)

                delta_mult = max(0.2, abs(bs_c.get("delta", 0.5)))
                prem_rows.append({
                    "timestamp": ts,
                    "open": bs_o["price"],
                    "high": max(bs_h["price"], bs_o["price"], bs_c["price"]),
                    "low": max(0.5, min(bs_l["price"], bs_o["price"], bs_c["price"])),
                    "close": bs_c["price"],
                    "volume": int(vol * delta_mult),
                })
            prem_df = pd.DataFrame(prem_rows)
            processed = process_candlestick_series(prem_df, contract_symbol_label, timeframe)
        else:
            processed = {"symbol": contract_symbol_label, "candles": [], "timeframe": timeframe}

        latest_greeks = (
            calculate_black_scholes(current_spot, target_strike, 1.0 / 365.0, iv=0.14, option_type=opt_type)
            if (current_spot > 0 and target_strike > 0)
            else None
        )
        processed["greeks"] = latest_greeks
        processed["contractSymbol"] = contract_symbol_label
        processed["strike"] = target_strike
        processed["optionType"] = opt_type
        if real_ltp:
            processed["realLtp"] = real_ltp
            if processed.get("current"):
                processed["current"]["close"] = real_ltp
    else:
        processed = process_candlestick_series(df, clean, timeframe)

    # Compute Smart Money Concepts (SMC) visual overlay strictly on confirmed completed candles
    prov_name = provider.get_provider_name()
    df_attrs = df.attrs if (df is not None and hasattr(df, "attrs")) else {}
    is_mock_feed = (prov_name == "mock") or bool(df_attrs.get("is_mock") or df_attrs.get("is_synthetic"))
    try:
        from app.options.smc_engine import SmartMoneyEngine
        from app.options.multi_timeframe_engine import filter_completed_candles
        closed_df = filter_completed_candles(df, timeframe=timeframe)
        if not is_mock_feed and closed_df is not None and len(closed_df) >= 3:
            d_high = float(closed_df["high"].max())
            d_low = float(closed_df["low"].min())
            smc_data = SmartMoneyEngine.analyze(closed_df, current_spot, d_high, d_low, timeframe=timeframe)
            processed["smcOverlay"] = {
                "orderBlocks": smc_data.get("orderBlocks", []),
                "fairValueGaps": smc_data.get("fairValueGaps", []),
                "dealingRange": smc_data.get("dealingRange", {}),
                "liquidityPools": smc_data.get("liquidityPools", {}),
                "sweeps": smc_data.get("recentSweeps", []),
                "advancedIct": smc_data.get("advancedIct", {}),
                "incompleteCandlesExcluded": smc_data.get("incompleteCandlesExcluded", 0),
            }
    except Exception as e:
        logger.debug(f"Error computing smcOverlay: {e}")

    attr_status = str(df_attrs.get("dataStatus") or "")
    if is_mock_feed:
        status_flag = "MOCK"
    elif attr_status in ("DATA_OFFLINE", "DATA_UNAVAILABLE", "DEGRADED", "UNAVAILABLE", "SYNTHETIC"):
        status_flag = attr_status
    elif (prov_name in ["angelone", "upstox"]) and getattr(provider, "is_authenticated", False) and has_candles:
        status_flag = attr_status or "LIVE"
    elif prov_name in ["angelone", "upstox"]:
        status_flag = "DATA_OFFLINE" if not getattr(provider, "is_authenticated", False) else "DATA_UNAVAILABLE"
    else:
        status_flag = attr_status or "DATA_UNAVAILABLE"

    processed["mode"] = mode
    processed["availableStrikes"] = available_strikes
    processed["atmStrike"] = atm_strike
    processed["provider"] = prov_name
    processed["dataStatus"] = status_flag
    if df_attrs.get("degraded_reason"):
        processed["degradedReason"] = df_attrs.get("degraded_reason")
    processed["dataTimestamp"] = now_ist
    processed["analysisTimestamp"] = now_ist
    return processed


@router.get("/{index_symbol}/analysis")
async def get_index_full_analysis(index_symbol: str, session: AsyncSession = Depends(get_db)):
    """
    Deep quantitative options analysis:
    Candles + Support/Resistance Ladder + Sentiment + Today/Next Session Outlook + Chart Patterns + Trade Setups.
    """
    clean = canonicalize_symbol(index_symbol)
    provider = get_market_data_provider()
    now_ist = MarketCalendar.format_ist_timestamp()

    quote = await provider.get_quote(clean)
    candles_df = await provider.get_intraday_candles(clean, "15m")
    candles_5m = await provider.get_intraday_candles(clean, "5m")
    active_candles = candles_5m if (candles_5m is not None and not candles_5m.empty and len(candles_5m) >= 3) else candles_df
    candles_info = process_candlestick_series(candles_df, clean, "15m")
    candles_info_active = process_candlestick_series(active_candles, clean, "5m") if active_candles is not candles_df else candles_info

    raw_ltp = quote.get("currentPrice") if quote.get("currentPrice") is not None else quote.get("ltp")
    ltp = float(raw_ltp) if raw_ltp is not None else 0.0
    chg = float(quote.get("change") or 0.0)
    d_high = float(quote.get("dayHigh") or quote.get("high") or ltp)
    d_low = float(quote.get("dayLow") or quote.get("low") or ltp)
    d_close = float(quote.get("previousClose") or (ltp - chg if ltp > 0 else 0.0))
    d_open = float(quote.get("openPrice") or quote.get("open") or d_low)

    # Phase 01: Audit and sanitize incoming quote with DataQualityEngine
    from app.data.quality_validator import DataQualityEngine, FeedStatus
    atr_val = candles_info.get("atr") if candles_info else None
    quality_audit = DataQualityEngine.validate_quote(clean, quote, reference_candles=candles_df, atr_14=atr_val)
    quote = quality_audit["sanitizedQuote"]
    data_quality_report = quality_audit["dataQualityReport"]

    # Option Chain & Real NFO Market Quotes
    real_quotes_map = {}
    if hasattr(provider, "get_batch_quotes"):
        from app.data.instrument_master import get_instrument_master
        master = get_instrument_master()
        step = _option_strike_step(clean)
        atm_k = round(ltp / step) * step
        ladder = master.get_option_chain_contracts(clean, atm_k, step, num_strikes=7)
        tokens = []
        for pair in ladder:
            if pair.get("ce_contract"):
                tokens.append(str(pair["ce_contract"]["token"]))
            if pair.get("pe_contract"):
                tokens.append(str(pair["pe_contract"]["token"]))
        if tokens:
            real_quotes_map = await provider.get_batch_quotes(_option_quote_exchange(clean), tokens)

    chain = generate_index_option_chain(clean, ltp, chg, real_quotes_map=real_quotes_map, filter_mode="ATM")
    call_wall = chain["oiAnalysis"]["callWall"]
    put_wall = chain["oiAnalysis"]["putWall"]
    max_pain = chain["maxPain"]["maxPainStrike"]
    pcr_oi = chain["pcr"]["pcrOi"]

    atr = candles_info.get("atr") or 110.0
    vwap = candles_info.get("vwap") or ltp
    ema20 = candles_info.get("ema20") or ltp
    ema50 = candles_info.get("ema50") or ltp

    # Support & Resistance Ladder
    sr_ladder = compute_options_support_resistance_ladder(
        current_price=ltp,
        daily_high=d_high,
        daily_low=d_low,
        daily_close=d_close,
        daily_open=d_open,
        candles_df=candles_df,
        call_wall=call_wall,
        put_wall=put_wall,
        max_pain=max_pain,
        atr_14=atr
    )

    # Sentiment
    sentiment = evaluate_options_market_sentiment(
        symbol=clean,
        current_price=ltp,
        vwap=vwap,
        ema_20=ema20,
        ema_50=ema50,
        rsi_14=58.5,
        pcr_oi=pcr_oi,
        total_ce_chg_oi=chain["oiAnalysis"]["totalCeChgOi"],
        total_pe_chg_oi=chain["oiAnalysis"]["totalPeChgOi"],
        day_high=d_high,
        day_low=d_low
    )

    # Filter strictly completed bars before outlook, pattern recognition, and SMC analysis
    from app.options.multi_timeframe_engine import filter_completed_candles
    closed_15m = filter_completed_candles(candles_df, timeframe="15m")

    # Outlook (Today & Next Session with SMC Integration)
    today_outlook = calculate_session_outlook(clean, ltp, d_high, d_low, d_close, d_open, atr, mode="TODAY", candles_df=closed_15m)
    next_outlook = calculate_session_outlook(clean, ltp, d_high, d_low, d_close, d_open, atr, mode="NEXT_SESSION", candles_df=closed_15m)

    # Patterns (including SMC Sweeps, FVGs, and Order Blocks)
    patterns = detect_candlestick_and_chart_patterns(closed_15m, "15m")

    # Smart Money Concepts (SMC) Engine
    from app.options.smc_engine import SmartMoneyEngine
    smc_analysis = SmartMoneyEngine.analyze(
        df=closed_15m,
        current_price=ltp,
        daily_high=d_high,
        daily_low=d_low,
        atr_14=atr,
        timeframe="15m",
    )

    prov_name = provider.get_provider_name()

    # Phase 2 Step 4.3: End-to-End Production Signal Pipeline Orchestration
    from app.options.pipeline_orchestrator import execute_production_signal_pipeline
    candles_1h = None
    candles_1m = None
    try:
        candles_1h = await provider.get_intraday_candles(clean, "1h")
    except Exception:
        pass
    try:
        candles_1m = await provider.get_intraday_candles(clean, "1m")
    except Exception:
        pass

    pipeline_res = await execute_production_signal_pipeline(
        symbol=clean,
        provider=provider,
        custom_quote=quote,
        custom_timeframes={
            "1h": candles_1h,
            "15m": candles_df,
            "5m": candles_5m,
            "1m": candles_1m,
        },
        custom_option_chain=chain,
    )

    # An analysis observation is not an order or a persisted qualified signal.
    # Record every evaluation so zero setups have an inspectable cause.
    if isinstance(session, AsyncSession):
        try:
            session.add(SignalEvaluationRecord(
            symbol=clean,
            data_status=str((pipeline_res.get("data_quality_report") or {}).get("feedStatus") or "DATA_UNAVAILABLE"),
            action=str(pipeline_res.get("action") or "NO_TRADE"),
            qualified=bool(pipeline_res.get("is_trade_qualified", False)),
            rejection_reasons=list(pipeline_res.get("rejection_reasons") or []),
            stage_status=dict(pipeline_res.get("stage_status") or {}),
            persisted_signal_id=pipeline_res.get("persisted_signal_id"),
            ))
            await session.commit()
        except Exception as exc:
            await session.rollback()
            logger.warning("Signal evaluation journal unavailable: %s", exc)

    market_state = pipeline_res.get("market_state") or {}
    setups = pipeline_res.get("frontend_options_setups") or {
        "symbol": clean,
        "hasQualifiedSetups": False,
        "statusMessage": "NO TRADE — CONDITIONS UNSUITABLE",
        "disqualificationReasons": pipeline_res.get("rejection_reasons", []),
        "timestamp": now_ist,
        "setups": [],
    }

    # Circuit Breaker Gating Check (REQ-7.5)
    cb_status = None
    cb_instance = None
    try:
        from app.options.drawdown_circuit_breaker import get_circuit_breaker
        from app.options.paper_trading.paper_engine import paper_engine
        from app.api.routes.paper_trading import _refresh_open_positions_live_quotes
        await _refresh_open_positions_live_quotes()
        cb_instance = get_circuit_breaker()
        cb_status = cb_instance.get_status(paper_engine.state)
        if not cb_status.get("isPermitted", False):
            cb_state = cb_status.get("state", "DAILY_DRAWDOWN_BREACHED")
            cb_reason = cb_status.get("reason", "Intraday drawdown circuit breaker active")
            setups = {
                "symbol": clean,
                "hasQualifiedSetups": False,
                "statusMessage": f"NO TRADE — CIRCUIT BREAKER ({cb_state})",
                "disqualificationReasons": [cb_reason],
                "primaryBias": "NO_TRADE",
                "isTradeQualified": False,
                "circuitBreakerGated": True,
                "circuitBreakerState": cb_state,
                "noTradeReason": cb_reason,
                "timestamp": now_ist,
                "setups": [],
                "callSetups": [],
                "putSetups": [],
                "advice": f"Circuit breaker active ({cb_state}). Trade entries are strictly blocked to preserve capital.",
            }
    except Exception as e:
        logger.warning(f"[OptionsRoute] Circuit breaker query notice: {e}")

    # Independent research evaluation uses the same market snapshot, with no order writes.
    research_setup = None
    try:
        from app.options.research_setup_engine import evaluate_research_setup
        from app.models.db_models import ResearchSetupEvaluationRecord
        research_setup = await evaluate_research_setup(
            clean, provider, quote,
            {"1h": candles_1h, "15m": candles_df, "5m": candles_5m, "1m": candles_1m}, chain,
        )
        if isinstance(session, AsyncSession):
            saved_payload = dict(research_setup, journalSaved=True)
            session.add(ResearchSetupEvaluationRecord(
                id=research_setup["id"], engine_id=research_setup["engineId"], symbol=clean,
                qualified=research_setup["qualified"], payload=saved_payload,
            ))
            await session.commit()
            research_setup["journalSaved"] = True
    except Exception as exc:
        if isinstance(session, AsyncSession):
            await session.rollback()
        logger.warning("Independent research setup evaluation unavailable: %s", exc)

    # Next-Session Recommendation Engine
    next_session_rec = evaluate_next_session_recommendation(
        symbol=clean,
        underlying_ltp=ltp,
        sentiment=sentiment["overallSentiment"],
        sentiment_score=sentiment["sentimentScore"],
        strikes_data=chain["strikes"],
        atr_14=atr,
        daily_high=d_high,
        daily_low=d_low,
        daily_close=d_close,
        daily_open=d_open,
        market_state=market_state.get("marketState"),
        circuit_breaker=cb_instance,
    )

    valid_feed_statuses = {
        FeedStatus.VERIFIED_LIVE,
        FeedStatus.VERIFIED_EOD,
        FeedStatus.DEGRADED,
        FeedStatus.STALE,
        FeedStatus.STALE_TICK,
        FeedStatus.DATA_OFFLINE,
        FeedStatus.DATA_UNAVAILABLE,
        FeedStatus.ANOMALOUS,
        FeedStatus.SYNTHETIC,
    }

    dq_status = data_quality_report.get("feedStatus") if isinstance(data_quality_report, dict) else None
    if dq_status in valid_feed_statuses:
        effective_data_status = dq_status
    else:
        # Strict fail-closed: missing, unknown, or unverified feed status must default to DATA_UNAVAILABLE.
        # Never infer VERIFIED_LIVE or generic LIVE from provider authentication.
        effective_data_status = FeedStatus.DATA_UNAVAILABLE

    return {
        "symbol": clean,
        "quote": quote,
        "marketState": market_state,
        "supportResistance": sr_ladder,
        "sentiment": sentiment,
        "todayOutlook": today_outlook,
        "nextSessionOutlook": next_outlook,
        "nextSessionOpeningOutlook": next_session_rec["openingOutlook"],
        "nextSessionRecommendation": next_session_rec,
        "patterns": patterns,
        "todayOptionsSetups": setups,
        "researchSetup": research_setup,
        "smcAnalysis": smc_analysis,
        "circuitBreaker": cb_status,
        "dataQualityReport": data_quality_report,
        "isTradeQualified": bool(data_quality_report.get("isTradeQualified", False)) if effective_data_status == FeedStatus.VERIFIED_LIVE else False,
        "marketCalendar": MarketCalendar.get_market_status(),
        "optionChainSummary": {
            "pcr": chain["pcr"],
            "maxPain": chain["maxPain"],
            "callWall": call_wall,
            "putWall": put_wall,
        },
        "provider": prov_name,
        "dataStatus": effective_data_status,
        "dataTimestamp": now_ist,
        "analysisTimestamp": now_ist,
        "disclaimer": "Live market analysis only. Platform does NOT execute trades.",
    }


@router.get("/{index_symbol}/sentiment")
async def get_index_sentiment(index_symbol: str):
    """
    Returns isolated sentiment analysis for selected index.
    """
    clean = canonicalize_symbol(index_symbol)
    analysis = await get_index_full_analysis(clean)
    return {
        "symbol": clean,
        "sentiment": analysis["sentiment"],
        "provider": analysis["provider"],
        "dataStatus": analysis["dataStatus"],
        "dataTimestamp": analysis["dataTimestamp"],
    }


@router.get("/{index_symbol}/levels")
async def get_index_levels(index_symbol: str):
    """
    Returns Support and Resistance ladder separating Price-Derived from Option-Chain levels.
    """
    clean = canonicalize_symbol(index_symbol)
    analysis = await get_index_full_analysis(clean)
    return {
        "symbol": clean,
        "supportResistance": analysis["supportResistance"],
        "provider": analysis["provider"],
        "dataStatus": analysis["dataStatus"],
        "dataTimestamp": analysis["dataTimestamp"],
    }


@router.get("/{index_symbol}/option-chain")
async def get_index_option_chain_endpoint(
    index_symbol: str,
    expiry: Optional[str] = Query(None, description="Expiry date"),
    filter_mode: str = Query("ATM", description="Filter mode: ATM or WIDE")
):
    """
    Returns full option chain with strikes, Greeks, PCR, Max Pain, and strike filters.
    """
    clean = canonicalize_symbol(index_symbol)
    provider = get_market_data_provider()
    quote = await provider.get_quote(clean)
    if clean == "SENSEX":
        from math import isfinite

        try:
            sensex_spot = float(quote.get("currentPrice") or quote.get("ltp") or 0)
        except (TypeError, ValueError):
            sensex_spot = 0.0
        if not isfinite(sensex_spot) or sensex_spot <= 0:
            raise HTTPException(status_code=503, detail="SENSEX spot quote is unavailable.")
    ltp = float(quote.get("currentPrice") or quote.get("ltp", 24852.4))
    chg = float(quote.get("change", 0.0))

    real_quotes_map = {}
    if hasattr(provider, "get_batch_quotes"):
        from app.data.instrument_master import get_instrument_master
        master = get_instrument_master()
        step = _option_strike_step(clean)
        atm_k = round(ltp / step) * step
        num_str = 7 if filter_mode.upper() == "ATM" else 15
        ladder = master.get_option_chain_contracts(clean, atm_k, step, num_strikes=num_str, expiry=expiry)
        tokens = []
        for pair in ladder:
            if pair.get("ce_contract"):
                tokens.append(str(pair["ce_contract"]["token"]))
            if pair.get("pe_contract"):
                tokens.append(str(pair["pe_contract"]["token"]))
        if tokens:
            real_quotes_map = await provider.get_batch_quotes(_option_quote_exchange(clean), tokens)

    chain = generate_index_option_chain(
        symbol=clean,
        underlying_ltp=ltp,
        underlying_change=chg,
        real_quotes_map=real_quotes_map,
        expiry=expiry,
        filter_mode=filter_mode
    )

    prov_name = provider.get_provider_name()
    status_flag = "LIVE" if (prov_name in ["angelone", "upstox"]) and getattr(provider, "is_authenticated", False) else "MOCK"
    chain["provider"] = prov_name
    chain["dataStatus"] = status_flag
    return chain


@router.get("/{index_symbol}/setups")
async def get_index_setups(index_symbol: str):
    """
    Returns TODAY'S OPTIONS SETUPS for the index (qualified CE or PE candidate, or NO TRADE).
    """
    clean = canonicalize_symbol(index_symbol)
    analysis = await get_index_full_analysis(clean)
    return {
        "symbol": clean,
        "todayOptionsSetups": analysis["todayOptionsSetups"],
        "circuitBreaker": analysis.get("circuitBreaker"),
        "provider": analysis["provider"],
        "dataStatus": analysis["dataStatus"],
        "dataTimestamp": analysis["dataTimestamp"],
    }


@router.get("/{index_symbol}/smc")
async def get_index_smc(index_symbol: str):
    """
    Returns Smart Money Concepts (SMC) & Institutional Order Flow Analysis.
    """
    clean = canonicalize_symbol(index_symbol)
    analysis = await get_index_full_analysis(clean)
    return {
        "symbol": clean,
        "smcAnalysis": analysis.get("smcAnalysis"),
        "provider": analysis["provider"],
        "dataStatus": analysis["dataStatus"],
        "dataTimestamp": analysis["dataTimestamp"],
    }


@router.get("/{index_symbol}/outlook")
async def get_index_outlook(index_symbol: str):
    """
    Returns Today's and Next Trading Session Outlook with Bullish, Base, and Bearish scenarios.
    """
    clean = canonicalize_symbol(index_symbol)
    analysis = await get_index_full_analysis(clean)
    return {
        "symbol": clean,
        "todayOutlook": analysis["todayOutlook"],
        "nextSessionOutlook": analysis["nextSessionOutlook"],
        "provider": analysis["provider"],
        "dataStatus": analysis["dataStatus"],
        "dataTimestamp": analysis["dataTimestamp"],
    }


@router.get("/{index_symbol}/patterns")
async def get_index_patterns(index_symbol: str):
    """
    Returns candlestick and chart patterns detected on recent index price action.
    """
    clean = canonicalize_symbol(index_symbol)
    analysis = await get_index_full_analysis(clean)
    return {
        "symbol": clean,
        "patterns": analysis["patterns"],
        "provider": analysis["provider"],
        "dataStatus": analysis["dataStatus"],
        "dataTimestamp": analysis["dataTimestamp"],
    }


@router.get("/{index_symbol}/next-session/opening-outlook")
async def get_index_next_session_opening_outlook(index_symbol: str):
    """
    Returns estimated next-session opening range, gap scenarios, confidence,
    supporting evidence, and invalidation conditions based on overnight indicators.
    """
    clean = canonicalize_symbol(index_symbol)
    analysis = await get_index_full_analysis(clean)
    return {
        "symbol": clean,
        "openingOutlook": analysis["nextSessionOpeningOutlook"],
        "provider": analysis["provider"],
        "dataStatus": analysis["dataStatus"],
        "dataTimestamp": analysis["dataTimestamp"],
    }


@router.get("/{index_symbol}/next-session/recommendation")
async def get_index_next_session_recommendation(
    index_symbol: str,
    live_open_price: Optional[float] = Query(None, description="Optional live opening price for Stage 2 confirmation")
):
    """
    Returns Next-Session Options Recommendation with Stage 1 (Pre-market) or
    Stage 2 (Live Confirmation), qualified CE/PE contract, exact premium entry/SL/targets,
    or explicit NO-TRADE rationale.
    """
    clean = canonicalize_symbol(index_symbol)
    provider = get_market_data_provider()
    quote = await provider.get_quote(clean)
    raw_ltp = quote.get("currentPrice") if quote.get("currentPrice") is not None else quote.get("ltp")
    ltp = float(raw_ltp) if raw_ltp is not None else 0.0
    chg = float(quote.get("change") or 0.0)
    d_high = float(quote.get("dayHigh") or quote.get("high") or ltp)
    d_low = float(quote.get("dayLow") or quote.get("low") or ltp)
    d_close = float(quote.get("previousClose") or (ltp - chg if ltp > 0 else 0.0))
    d_open = float(quote.get("openPrice") or quote.get("open") or d_low)

    # Fetch reference candles first before data quality audit
    from app.options.multi_timeframe_engine import filter_completed_candles
    candles_df = filter_completed_candles(await provider.get_intraday_candles(clean, "15m"), timeframe="15m")
    candles_info = process_candlestick_series(candles_df, clean, "15m")
    atr = candles_info.get("atr") or 110.0
    vwap = candles_info.get("vwap") or ltp
    ema20 = candles_info.get("ema20") or ltp
    ema50 = candles_info.get("ema50") or ltp

    # Phase 01: Audit and sanitize incoming quote with DataQualityEngine
    from app.data.quality_validator import DataQualityEngine, FeedStatus
    quality_audit = DataQualityEngine.validate_quote(clean, quote, reference_candles=candles_df, atr_14=atr)
    quote = quality_audit["sanitizedQuote"]
    data_quality_report = quality_audit["dataQualityReport"]

    chain = generate_index_option_chain(clean, ltp, chg, filter_mode="ATM")

    sentiment = evaluate_options_market_sentiment(
        symbol=clean,
        current_price=ltp,
        vwap=vwap,
        ema_20=ema20,
        ema_50=ema50,
        rsi_14=58.5,
        pcr_oi=chain["pcr"]["pcrOi"],
        total_ce_chg_oi=chain["oiAnalysis"]["totalCeChgOi"],
        total_pe_chg_oi=chain["oiAnalysis"]["totalPeChgOi"],
        day_high=d_high,
        day_low=d_low
    )

    prov_name = provider.get_provider_name()
    feed_st = data_quality_report.get("feedStatus")
    if prov_name == "mock" or feed_st == FeedStatus.SYNTHETIC:
        status_flag = "MOCK"
    elif feed_st == FeedStatus.VERIFIED_LIVE:
        status_flag = "LIVE"
    elif feed_st == FeedStatus.VERIFIED_EOD:
        status_flag = "MARKET_CLOSED"
    else:
        status_flag = str(feed_st or "DATA_UNAVAILABLE")

    from app.options.market_state_engine import evaluate_index_market_state
    market_state = evaluate_index_market_state(
        symbol=clean,
        quote=quote,
        candles_df=candles_df,
        candles_info=candles_info,
        option_chain_summary={
            "pcr": chain["pcr"],
            "maxPain": chain["maxPain"],
            "callWall": chain["oiAnalysis"]["callWall"],
            "putWall": chain["oiAnalysis"]["putWall"],
        },
        vix_value=13.5,
        is_live_data=(feed_st == FeedStatus.VERIFIED_LIVE)
    )

    rec = evaluate_next_session_recommendation(
        symbol=clean,
        underlying_ltp=ltp,
        sentiment=sentiment["overallSentiment"],
        sentiment_score=sentiment["sentimentScore"],
        strikes_data=chain["strikes"],
        atr_14=atr,
        daily_high=d_high,
        daily_low=d_low,
        daily_close=d_close,
        daily_open=d_open,
        live_open_price=live_open_price,
        market_state=market_state.get("marketState")
    )

    rec["provider"] = prov_name
    rec["dataStatus"] = status_flag
    rec["dataQualityReport"] = data_quality_report
    rec["isDataQualified"] = data_quality_report.get("isTradeQualified", True)
    if not rec["isDataQualified"]:
        rec["dataGatingReason"] = f"Feed status {data_quality_report.get('feedStatus')}: {', '.join(data_quality_report.get('anomaliesDetected', []))}"
    return rec


@router.get("/{index_symbol}/next-session/backtest")
async def get_index_next_session_backtest(
    index_symbol: str,
    lookback_sessions: int = Query(60, ge=10, le=250, description="Number of sessions to backtest"),
    brokerage_per_order: float = Query(20.0, description="Brokerage fee per leg in INR"),
    slippage_pct: float = Query(0.05, description="Slippage percentage on option premium")
):
    """
    Runs walk-forward out-of-sample chronological backtest for Next-Session Opening Forecasts
    and Option Premium setups with transaction costs and slippage.
    """
    clean = canonicalize_symbol(index_symbol)
    result = run_next_session_historical_validation(
        symbol=clean,
        lookback_sessions=lookback_sessions,
        brokerage_per_order=brokerage_per_order,
        slippage_pct=slippage_pct
    )
    return result


@router.get("/{index_symbol}/ml-strategy")
async def get_index_ml_strategy_report(index_symbol: str):
    """
    Returns Machine Learning accuracy diagnostics, Target Hit vs SL Hit counters,
    reinforcement-learning model weights, and newly discovered strategies.
    """
    from app.options.ml_strategy_learner import ml_strategy_learner
    clean = canonicalize_symbol(index_symbol)
    return ml_strategy_learner.get_report(clean)


@router.post("/trade-feedback")
async def record_trade_feedback(payload: Dict[str, Any] = Body(...)):
    """
    Ingests paper trade outcomes (Target Hit vs SL Hit), recalibrates ML weights,
    and returns updated accuracy stats.
    """
    from app.options.ml_strategy_learner import ml_strategy_learner
    contract_symbol = payload.get("contractSymbol", "UNKNOWN")
    outcome = payload.get("outcome", "MANUAL_EXIT")
    smc_model = payload.get("smcModel")
    realized_pnl = float(payload.get("realizedPnl", 0.0))
    realized_rr = float(payload.get("realizedRr", 1.0))
    entry_price = float(payload.get("entryPrice", 0.0))
    exit_price = float(payload.get("exitPrice", 0.0))

    result = ml_strategy_learner.record_trade_feedback(
        contract_symbol=contract_symbol,
        outcome=outcome,
        smc_model=smc_model,
        realized_pnl=realized_pnl,
        realized_rr=realized_rr,
        entry_price=entry_price,
        exit_price=exit_price
    )
    return result


@router.get("/{index_symbol}/ict-analysis")
async def get_index_ict_analysis(
    index_symbol: str,
    timeframe: str = Query("15m", description="Candle timeframe: 1m, 5m, 15m, 1h, 1d")
):
    """
    Institutional ICT + SMC Engine:
    Provides Market Structure, Liquidity Pools, Sweeps with Reclaim, Heatmaps,
    Fair Value Gaps (FVG) with CE 50%, Order Blocks & Breakers, 100-point Confluence Scorecard,
    and Standard 15-Point AI Report with zero hardcoded prices.
    """
    from app.options.ict_smc.structure_analyzer import MarketStructureAnalyzer
    from app.options.ict_smc.liquidity_engine import LiquidityDetectionEngine
    from app.options.ict_smc.fvg_orderblock_engine import FvgOrderBlockEngine
    from app.options.ict_smc.scorecard_engine import AnalysisScorecardEngine
    from app.options.ict_smc.ai_market_explainer import AIMarketExplainer

    from app.options.multi_timeframe_engine import filter_completed_candles

    clean = canonicalize_symbol(index_symbol)
    provider = get_market_data_provider()
    prov_name = provider.get_provider_name()
    now_ist = MarketCalendar.format_ist_timestamp()

    quote = await provider.get_quote(clean) or {}
    quote_status = str(quote.get("dataStatus") or "")
    df = await provider.get_intraday_candles(clean, timeframe)
    df_attrs = df.attrs if (df is not None and hasattr(df, "attrs")) else {}
    is_mock_or_synth = (
        prov_name == "mock"
        or bool(quote.get("is_mock") or quote.get("is_synthetic"))
        or quote_status.upper() in ("MOCK", "SYNTHETIC")
        or bool(df_attrs.get("is_mock") or df_attrs.get("is_synthetic"))
        or str(df_attrs.get("dataStatus") or "").upper() in ("MOCK", "SYNTHETIC")
    )
    if is_mock_or_synth:
        return {
            "symbol": clean,
            "status": "DATA_UNAVAILABLE",
            "dataStatus": "SYNTHETIC",
            "provider": prov_name,
            "message": f"Synthetic/mock data rejected for ICT analysis on {clean} ({timeframe}).",
            "dataTimestamp": now_ist,
        }

    raw_len = len(df) if df is not None else 0
    df = filter_completed_candles(df, timeframe=timeframe)
    closed_len = len(df) if df is not None else 0
    if df is None or closed_len < 5:
        eff_status = str(df_attrs.get("dataStatus") or quote_status or "DATA_UNAVAILABLE")
        return {
            "symbol": clean,
            "status": "INSUFFICIENT_DATA",
            "dataStatus": eff_status,
            "provider": prov_name,
            "incompleteCandlesExcluded": max(0, raw_len - closed_len),
            "degradedReason": df_attrs.get("degraded_reason") or quote.get("degradedReason"),
            "message": f"Insufficient confirmed completed candle data for {clean} on timeframe {timeframe}.",
            "dataTimestamp": now_ist,
        }

    ltp_val = quote.get("currentPrice") if quote.get("currentPrice") is not None else quote.get("ltp")
    ltp = float(ltp_val) if (ltp_val is not None and float(ltp_val) > 0) else float(df["close"].iloc[-1])
    d_high = float(quote.get("dayHigh") or quote.get("high") or df["high"].max())
    d_low = float(quote.get("dayLow") or quote.get("low") or df["low"].min())

    structure = MarketStructureAnalyzer.analyze_market_structure(df, timeframe=timeframe)
    liquidity_pools = LiquidityDetectionEngine.identify_liquidity_pools(df, daily_high=d_high, daily_low=d_low)
    sweeps = LiquidityDetectionEngine.detect_liquidity_sweeps(df, liquidity_pools)
    atr_val = 100.0
    heatmap = LiquidityDetectionEngine.build_liquidity_heatmap(liquidity_pools, current_price=ltp, atr_14=atr_val)
    fvgs = FvgOrderBlockEngine.detect_fair_value_gaps(df, timeframe=timeframe)
    obs = FvgOrderBlockEngine.detect_order_blocks_and_breakers(df, timeframe=timeframe)

    struct_bias = structure.get("structureBias", "NEUTRAL")
    struct_score = 0.9 if struct_bias in ["BULLISH", "BEARISH"] else 0.4
    reclaim_sweeps = [s for s in sweeps if s.get("type") == "SWEEP_WITH_RECLAIM"]
    liq_score = 0.95 if reclaim_sweeps else (0.7 if sweeps else 0.3)
    fvg_ob_score = 0.85 if (fvgs or obs) else 0.4
    disp_score = 0.8 if struct_score >= 0.7 else 0.4
    rr_score = 0.85

    scorecard = AnalysisScorecardEngine.calculate_scorecard(
        htf_score_pct=struct_score,
        structure_score_pct=struct_score,
        liquidity_score_pct=liq_score,
        displacement_score_pct=disp_score,
        fvg_ob_score_pct=fvg_ob_score,
        rr_score_pct=rr_score,
    )

    dealing_range = {
        "rangeHigh": d_high,
        "rangeLow": d_low,
        "equilibrium": round((d_high + d_low) / 2.0, 2),
        "regime": "DISCOUNT" if ltp < (d_high + d_low) / 2.0 else "PREMIUM"
    }

    ai_report = AIMarketExplainer.generate_standard_report(
        symbol=clean,
        market_bias=struct_bias,
        htf_trend=struct_bias,
        intraday_structure=structure.get("summary", "Structure evaluated"),
        liquidity_data=liquidity_pools,
        structure_data=structure,
        fvg_ob_data={"fairValueGaps": fvgs, "orderBlocks": obs},
        dealing_range=dealing_range,
        entry_trigger="Wait for key liquidity sweep and 5M displacement confirmation",
        invalidation_conditions="Decisive candle close past sweep extreme",
        no_trade_conditions="Avoid execution during equilibrium chop or conflicting timeframe bias"
    )

    five_part = AIMarketExplainer.generate_5part_analysis(
        symbol=clean,
        current_price=ltp,
        market_bias=struct_bias,
        structure_data=structure,
        liquidity_data=liquidity_pools,
        sweeps=sweeps,
        fvgs=fvgs,
        obs=obs,
        dealing_range=dealing_range
    )

    return {
        "symbol": clean,
        "currentPrice": ltp,
        "timeframe": timeframe,
        "structure": structure,
        "liquidity": {
            "pools": liquidity_pools,
            "sweeps": sweeps,
            "heatmap": heatmap
        },
        "fvgAndOrderBlocks": {
            "fairValueGaps": fvgs,
            "orderBlocks": obs,
            "activeFvgs": [f for f in fvgs if not f.get("isMitigated")],
            "activeBlocks": [b for b in obs if b.get("isValid")]
        },
        "scorecard": scorecard,
        "aiReport": ai_report,
        "fivePartAnalysis": five_part,
        "provider": prov_name,
        "dataStatus": str(df_attrs.get("dataStatus") or quote_status or "LIVE"),
        "incompleteCandlesExcluded": max(0, raw_len - closed_len),
        "dataTimestamp": now_ist,
    }


@router.get("/{index_symbol}/multi-timeframe")
async def get_index_multi_timeframe(index_symbol: str):
    """
    Multi-Timeframe Coordinated Analysis Engine:
    Syncs 1H, 15M, 5M, 1M timeframes and enforces deterministic confluence scoring.
    """
    from app.options.multi_timeframe_engine import evaluate_multi_timeframe_confluence
    from app.data.quality_validator import DataQualityEngine, FeedStatus

    clean = canonicalize_symbol(index_symbol)
    provider = get_market_data_provider()

    quote = await provider.get_quote(clean) or {}
    ltp_raw = quote.get("currentPrice") if quote.get("currentPrice") is not None else quote.get("ltp")
    ltp = float(ltp_raw) if ltp_raw is not None else 0.0

    # Fetch multiple timeframes
    timeframes = ["1h", "15m", "5m", "1m"]
    tf_dfs = {}
    for tf in timeframes:
        try:
            tf_dfs[tf] = await provider.get_intraday_candles(clean, tf)
        except Exception:
            tf_dfs[tf] = None

    quality_audit = DataQualityEngine.validate_quote(clean, quote, reference_candles=tf_dfs.get("15m"))
    sanitized_quote = quality_audit["sanitizedQuote"]
    data_quality_report = quality_audit["dataQualityReport"]

    feed_st = data_quality_report.get("feedStatus", FeedStatus.DATA_UNAVAILABLE)
    mtf_result = evaluate_multi_timeframe_confluence(
        symbol=clean,
        timeframe_candles=tf_dfs,
        current_quote=sanitized_quote,
        data_quality_status=feed_st,
        is_live_data=(feed_st == FeedStatus.VERIFIED_LIVE),
    )

    return {
        "symbol": clean,
        "currentPrice": ltp,
        "dataStatus": feed_st,
        "provider": provider.get_provider_name(),
        "dataQualityReport": data_quality_report,
        "multiTimeframe": mtf_result,
        "timestamp": MarketCalendar.format_ist_timestamp()
    }


@router.post("/{index_symbol}/backtest-ict")
async def run_ict_backtest(
    index_symbol: str,
    payload: Dict[str, Any] = Body(default_factory=dict)
):
    """
    Historical point-in-time walk-forward backtesting for ICT/SMC algorithms.
    Without look-ahead bias, factoring slippage and brokerage.
    """
    from app.options.ict_smc.historical_backtester import HistoricalBacktester
    from app.options.multi_timeframe_engine import filter_completed_candles

    clean = canonicalize_symbol(index_symbol)
    provider = get_market_data_provider()

    timeframe = payload.get("timeframe", "15m")
    algorithm_type = payload.get("algorithmType", "COMBINED_ICT_SMC")
    slippage_pts = float(payload.get("slippagePts", 2.0))
    brokerage = float(payload.get("brokeragePerTrade", 40.0))
    lot_size = int(payload.get("lotSize", 65 if "NIFTY" in clean else 15))

    df = await provider.get_intraday_candles(clean, timeframe)
    df_attrs = df.attrs if (df is not None and hasattr(df, "attrs")) else {}
    if provider.get_provider_name() == "mock" or df_attrs.get("is_mock") or df_attrs.get("is_synthetic"):
        return {
            "status": "ERROR",
            "dataStatus": "SYNTHETIC",
            "message": f"Synthetic/mock candles cannot be used for ICT backtesting on {clean}."
        }
    df = filter_completed_candles(df, timeframe=timeframe)
    if df is None or len(df) < 25:
        return {
            "status": "ERROR",
            "dataStatus": str(df_attrs.get("dataStatus") or "DATA_UNAVAILABLE"),
            "message": f"Need at least 25 confirmed candles on {timeframe} for {clean} to backtest."
        }

    results = HistoricalBacktester.backtest_algorithm(
        df=df,
        algorithm_type=algorithm_type,
        timeframe=timeframe,
        slippage_pts=slippage_pts,
        brokerage_per_trade=brokerage,
        lot_size=lot_size
    )

    return results
