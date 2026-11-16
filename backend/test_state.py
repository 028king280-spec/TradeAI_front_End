import asyncio
from app.data.providers.factory import get_market_data_provider
from app.options.candle_processor import process_candlestick_series
from app.options.market_state_engine import evaluate_index_market_state
from app.options.setup_selector import evaluate_options_trade_setups

async def test():
    p = get_market_data_provider()
    for sym in ['NIFTY 50', 'SENSEX']:
        q = await p.get_quote(sym)
        c_df = await p.get_intraday_candles(sym, '5m')
        c_inf = process_candlestick_series(c_df, sym, '5m')
        
        st = evaluate_index_market_state(sym, q, c_df, c_inf)
        print(f"=== CURRENT LOGIC: {sym} ===")
        print(f"LTP: {q.get('currentPrice')} | DayHigh: {q.get('dayHigh')} | DayLow: {q.get('dayLow')}")
        print(f"MarketState: {st.get('marketState')} | StatusBadge: {st.get('statusBadge')}")
        print(f"Headline: {st.get('headline')}")
        print(f"PrimaryReason: {st.get('primaryReason')}")

if __name__ == '__main__':
    asyncio.run(test())

