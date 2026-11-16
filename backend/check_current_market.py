import asyncio
from app.data.providers.factory import get_market_data_provider
from app.options.candle_processor import process_candlestick_series
from app.options.market_state_engine import evaluate_index_market_state
from app.options.option_chain import generate_index_option_chain
from app.options.setup_selector import evaluate_options_trade_setups

async def main():
    p = get_market_data_provider()
    for sym in ["NIFTY 50", "SENSEX"]:
        q = await p.get_quote(sym)
        c5 = await p.get_intraday_candles(sym, "5m")
        c15 = await p.get_intraday_candles(sym, "15m")
        info = process_candlestick_series(c15, sym, "15m")
        ltp = float(q.get("currentPrice") or q.get("ltp", 0.0))
        chg = float(q.get("change", 0.0))
        d_high = float(q.get("dayHigh", ltp))
        d_low = float(q.get("dayLow", ltp))
        print(f"\n================ {sym} ================")
        print(f"LTP: {ltp}, DayHigh: {d_high}, DayLow: {d_low}, Change: {chg}")
        print("Last 4 5M Candles:")
        if c5 is not None and not c5.empty:
            print(c5.tail(4)[["timestamp", "open", "high", "low", "close"]])
        print("Candles Info: VWAP=", info.get("vwap"), "EMA20=", info.get("ema20"), "EMA50=", info.get("ema50"), "RSI=", info.get("rsi"))
        
        chain = generate_index_option_chain(sym, ltp, chg, filter_mode="ATM")
        state = evaluate_index_market_state(
            symbol=sym,
            quote=q,
            candles_df=c15,
            candles_info=info,
            option_chain_summary={
                "pcr": chain["pcr"],
                "maxPain": chain["maxPain"],
                "callWall": chain["oiAnalysis"]["callWall"],
                "putWall": chain["oiAnalysis"]["putWall"],
            },
            vix_value=13.5,
            is_live_data=True
        )
        print("MarketState:", state.get("marketState"), "Headline:", state.get("headline"))
        
        from app.options.sentiment import evaluate_options_market_sentiment
        sent = evaluate_options_market_sentiment(
            symbol=sym,
            current_price=ltp,
            vwap=float(info.get("vwap") or ltp),
            ema_20=float(info.get("ema20") or ltp),
            ema_50=float(info.get("ema50") or ltp),
            rsi_14=float(info.get("rsi") or 50.0),
            pcr_oi=chain["pcr"]["pcrOi"],
            total_ce_chg_oi=chain["oiAnalysis"]["totalCeChgOi"],
            total_pe_chg_oi=chain["oiAnalysis"]["totalPeChgOi"],
            day_high=d_high,
            day_low=d_low
        )
        print("Sentiment:", sent.get("overallSentiment"), "Score:", sent.get("sentimentScore"))
        
        setups = evaluate_options_trade_setups(
            symbol=sym,
            underlying_ltp=ltp,
            sentiment=sent["overallSentiment"],
            sentiment_score=sent["sentimentScore"],
            strikes_data=chain["strikes"],
            atr_14=float(info.get("atr") or 100.0),
            vwap=float(info.get("vwap") or ltp),
            candles_df=c15,
            daily_high=d_high,
            daily_low=d_low,
            market_state=state.get("marketState")
        )
        print("PrimaryBias:", setups.get("primaryBias"), "StatusMsg:", setups.get("statusMessage"))
        if setups.get("setups"):
            s0 = setups["setups"][0]
            print(f"Top Setup: Bias={s0.get('bias')}, Contract={s0.get('contractSymbol')}, LTP={s0.get('lastObservedLtp')}, T1={s0.get('target1')}")

if __name__ == "__main__":
    asyncio.run(main())

