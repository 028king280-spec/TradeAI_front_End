import asyncio
from app.data.providers.factory import get_market_data_provider
from app.options.candle_processor import process_candlestick_series
from app.options.market_state_engine import evaluate_index_market_state

async def debug():
    p = get_market_data_provider()
    for sym in ['NIFTY 50', 'SENSEX']:
        q = await p.get_quote(sym)
        c_df = await p.get_intraday_candles(sym, '5m')
        c_inf = process_candlestick_series(c_df, sym, '5m')
        
        st = evaluate_index_market_state(sym, q, candles_df=c_df, candles_info=c_inf)
        print(f"=== DEBUG: {sym} ===")
        print(f"MarketState: {st.get('marketState')}")
        print(f"Headline: {st.get('headline')}")
        print(f"PrimaryReason: {st.get('primaryReason')}")
        factors = st.get('evaluationFactors', {})
        print("Confirmation factors:", factors.get('breakoutBreakdownConfirmation'))

if __name__ == '__main__':
    asyncio.run(debug())

