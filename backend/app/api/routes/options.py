from typing import Dict, Any, Optional
from fastapi import APIRouter, Query, HTTPException, status
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
}


def canonicalize_symbol(symbol: str) -> str:
    normalized = symbol.upper().replace("_", " ").replace(" ", "").strip()
    mapping = {
        "NIFTY": "NIFTY 50",
        "NIFTY50": "NIFTY 50",
        "SENSEX": "SENSEX",
        "BSESENSEX": "SENSEX",
        "BANKNIFTY": "BANK NIFTY",
        "BANK": "BANK NIFTY",
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

            # Status flag: never claim LIVE if provider is mock
            prov_name = provider.get_provider_name()
            status_flag = "LIVE" if (prov_name in ["angelone", "upstox"]) and getattr(provider, "is_authenticated", False) else "MOCK"

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

    # Next-Session Engine Analysis for Benchmark
    chain_sample = generate_index_option_chain("NIFTY 50", n_val, n_chg, filter_mode="ATM")
    next_session_rec = evaluate_next_session_recommendation(
        symbol="NIFTY 50",
        underlying_ltp=n_val,
        sentiment=sentiment["overallSentiment"],
        sentiment_score=sentiment["sentimentScore"],
        strikes_data=chain_sample["strikes"],
        atr_14=120.0,
        daily_high=n_val + 50.0,
        daily_low=n_val - 120.0,
        daily_close=n_val - n_chg,
        daily_open=n_val - 90.0,
        vix_value=vix_val
    )

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
        "dataStatus": formatted_cards[0]["dataStatus"] if formatted_cards else "MOCK",
        "dataTimestamp": now_ist,
        "analysisTimestamp": now_ist,
        "disclaimer": "Live market analysis only. Platform does NOT execute trades.",
    }


@router.get("/{index_symbol}/candles")
async def get_index_candles(
    index_symbol: str,
    timeframe: str = Query("15m", description="Candle timeframe: 1m, 3m, 5m, 15m, 30m, 1h, 1d")
):
    """
    Returns historical/intraday OHLCV candles with technical overlays (VWAP, EMA 20, EMA 50, ATR).
    """
    clean = canonicalize_symbol(index_symbol)
    provider = get_market_data_provider()
    now_ist = MarketCalendar.format_ist_timestamp()

    df = await provider.get_intraday_candles(clean, timeframe)
    processed = process_candlestick_series(df, clean, timeframe)

    prov_name = provider.get_provider_name()
    status_flag = "LIVE" if (prov_name in ["angelone", "upstox"]) and getattr(provider, "is_authenticated", False) else "MOCK"

    processed["provider"] = prov_name
    processed["dataStatus"] = status_flag
    processed["dataTimestamp"] = now_ist
    processed["analysisTimestamp"] = now_ist
    return processed


@router.get("/{index_symbol}/analysis")
async def get_index_full_analysis(index_symbol: str):
    """
    Deep quantitative options analysis:
    Candles + Support/Resistance Ladder + Sentiment + Today/Next Session Outlook + Chart Patterns + Trade Setups.
    """
    clean = canonicalize_symbol(index_symbol)
    provider = get_market_data_provider()
    now_ist = MarketCalendar.format_ist_timestamp()

    quote = await provider.get_quote(clean)
    candles_df = await provider.get_intraday_candles(clean, "15m")
    candles_info = process_candlestick_series(candles_df, clean, "15m")

    ltp = float(quote.get("currentPrice") or quote.get("ltp", 24852.4))
    chg = float(quote.get("change", 0.0))
    d_high = float(quote.get("dayHigh", ltp * 1.008))
    d_low = float(quote.get("dayLow", ltp * 0.992))
    d_close = float(quote.get("previousClose", ltp - chg))
    d_open = float(quote.get("openPrice", d_low))

    # Option Chain & Real NFO Market Quotes
    real_quotes_map = {}
    if hasattr(provider, "get_batch_quotes"):
        from app.data.instrument_master import get_instrument_master
        master = get_instrument_master()
        step = 50.0 if "NIFTY" in clean and "BANK" not in clean and "FIN" not in clean else (100.0 if "BANK" in clean else 50.0)
        atm_k = round(ltp / step) * step
        ladder = master.get_option_chain_contracts(clean, atm_k, step, num_strikes=7)
        tokens = []
        for pair in ladder:
            if pair.get("ce_contract"):
                tokens.append(str(pair["ce_contract"]["token"]))
            if pair.get("pe_contract"):
                tokens.append(str(pair["pe_contract"]["token"]))
        if tokens:
            real_quotes_map = await provider.get_batch_quotes("NFO", tokens)

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

    # Outlook (Today & Next Session)
    today_outlook = calculate_session_outlook(clean, ltp, d_high, d_low, d_close, d_open, atr, mode="TODAY")
    next_outlook = calculate_session_outlook(clean, ltp, d_high, d_low, d_close, d_open, atr, mode="NEXT_SESSION")

    # Patterns
    patterns = detect_candlestick_and_chart_patterns(candles_df, "15m")

    # Options Setups
    setups = evaluate_options_trade_setups(
        symbol=clean,
        underlying_ltp=ltp,
        sentiment=sentiment["overallSentiment"],
        sentiment_score=sentiment["sentimentScore"],
        strikes_data=chain["strikes"],
        atr_14=atr,
        vwap=vwap
    )

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
        daily_open=d_open
    )

    prov_name = provider.get_provider_name()
    status_flag = "LIVE" if (prov_name in ["angelone", "upstox"]) and getattr(provider, "is_authenticated", False) else "MOCK"

    from app.options.market_state_engine import evaluate_index_market_state
    market_state = evaluate_index_market_state(
        symbol=clean,
        quote=quote,
        candles_df=candles_df,
        candles_info=candles_info,
        option_chain_summary={
            "pcr": chain["pcr"],
            "maxPain": chain["maxPain"],
            "callWall": call_wall,
            "putWall": put_wall,
        },
        vix_value=13.5,
        is_live_data=(status_flag == "LIVE")
    )

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
        "optionChainSummary": {
            "pcr": chain["pcr"],
            "maxPain": chain["maxPain"],
            "callWall": call_wall,
            "putWall": put_wall,
        },
        "provider": prov_name,
        "dataStatus": status_flag,
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
    ltp = float(quote.get("currentPrice") or quote.get("ltp", 24852.4))
    chg = float(quote.get("change", 0.0))

    real_quotes_map = {}
    if hasattr(provider, "get_batch_quotes"):
        from app.data.instrument_master import get_instrument_master
        master = get_instrument_master()
        step = 50.0 if "NIFTY" in clean and "BANK" not in clean and "FIN" not in clean else (100.0 if "BANK" in clean else 50.0)
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
            real_quotes_map = await provider.get_batch_quotes("NFO", tokens)

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
    ltp = float(quote.get("currentPrice") or quote.get("ltp", 24852.4))
    chg = float(quote.get("change", 0.0))
    d_high = float(quote.get("dayHigh", ltp * 1.008))
    d_low = float(quote.get("dayLow", ltp * 0.992))
    d_close = float(quote.get("previousClose", ltp - chg))
    d_open = float(quote.get("openPrice", d_low))

    chain = generate_index_option_chain(clean, ltp, chg, filter_mode="ATM")
    candles_df = await provider.get_intraday_candles(clean, "15m")
    candles_info = process_candlestick_series(candles_df, clean, "15m")
    atr = candles_info.get("atr") or 110.0
    vwap = candles_info.get("vwap") or ltp
    ema20 = candles_info.get("ema20") or ltp
    ema50 = candles_info.get("ema50") or ltp

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
        live_open_price=live_open_price
    )

    prov_name = provider.get_provider_name()
    status_flag = "LIVE" if prov_name == "upstox" and getattr(provider, "is_authenticated", False) else "MOCK"
    rec["provider"] = prov_name
    rec["dataStatus"] = status_flag
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

