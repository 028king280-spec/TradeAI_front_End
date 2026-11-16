import asyncio
from app.data.providers.factory import get_market_data_provider
from app.options.candle_processor import process_candlestick_series
from app.options.market_state_engine import evaluate_index_market_state
from app.options.setup_selector import evaluate_options_trade_setups
from app.options.option_chain import generate_index_option_chain
from app.options.sentiment import evaluate_options_market_sentiment

async def test():
    p = get_market_data_provider()
    for sym in ['NIFTY 50', 'SENSEX']:
        q = await p.get_quote(sym)
        c_df = await p.get_intraday_candles(sym, '5m')
        c_inf = process_candlestick_series(c_df, sym, '5m')
        ltp = float(q.get("currentPrice") or q.get("ltp", 0.0))
        chg = float(q.get("change", 0.0))
        
        chain = generate_index_option_chain(sym, ltp, chg, filter_mode="ATM")
        
        atr = float(c_inf.get("atr") or (ltp * 0.005))
        tail = c_df.tail(12) if c_df is not None and len(c_df) >= 6 else c_df
        swing_h = float(tail["high"].max()) if tail is not None else float(q.get("dayHigh", ltp))
        swing_l = float(tail["low"].min()) if tail is not None else float(q.get("dayLow", ltp))
        
        drop_h = swing_h - ltp
        bounce_l = ltp - swing_l
        
        print(f"=== {sym} TEST ===")
        print(f"LTP: {ltp} | 1h High: {swing_h:.1f} | 1h Low: {swing_l:.1f}")
        print(f"Drop from High: {drop_h:.1f} | Bounce from Low: {bounce_l:.1f} | ATR: {atr:.1f}")
        
        is_bearish_rej = (drop_h >= atr * 0.30) and (drop_h > bounce_l * 1.3 or ltp < (swing_h + swing_l) / 2.0)
        is_bullish_rec = (bounce_l >= atr * 0.30) and (bounce_l > drop_h * 1.3 or ltp > (swing_h + swing_l) / 2.0)
        
        print(f"Bearish Rejection: {is_bearish_rej} | Bullish Reclaim: {is_bullish_rec}")

if __name__ == '__main__':
    asyncio.run(test())

