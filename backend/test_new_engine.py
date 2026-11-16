import asyncio
import os
import sys

# Force UTF-8 stdout
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from app.data.providers.factory import get_market_data_provider
from app.options.candle_processor import process_candlestick_series
from app.options.market_state_engine import evaluate_index_market_state
from app.options.setup_selector import evaluate_options_trade_setups
from app.options.option_chain import generate_index_option_chain
from app.options.paper_trading.paper_engine import paper_engine

async def test():
    p = get_market_data_provider()
    for sym in ['NIFTY 50', 'SENSEX']:
        q = await p.get_quote(sym)
        c_df = await p.get_intraday_candles(sym, '5m')
        c_inf = process_candlestick_series(c_df, sym, '5m')
        ltp = float(q.get("currentPrice") or q.get("ltp", 0.0))
        chg = float(q.get("change", 0.0))
        chain = generate_index_option_chain(sym, ltp, chg, filter_mode="ATM")
        
        st = evaluate_index_market_state(sym, q, candles_df=c_df, candles_info=c_inf)
        print(f"=== {sym} STATE & SETUPS ===")
        print(f"State: {st.get('marketState')} | Badge: {st.get('statusBadge')}")
        print(f"Headline: {st.get('headline')}")
        print(f"Reason: {st.get('primaryReason')}")
        
        setups = evaluate_options_trade_setups(
            symbol=sym,
            underlying_ltp=ltp,
            sentiment="NEUTRAL",
            sentiment_score=50,
            strikes_data=chain["strikes"],
            atr_14=float(c_inf.get("atr") or 100.0),
            candles_df=c_df,
            market_state=st.get("marketState")
        )
        print(f"Primary Bias: {setups.get('primaryBias')}")
        print(f"Has Qualified: {setups.get('hasQualifiedSetups')}")
        print(f"Status Message: {setups.get('statusMessage')}")
        top_s = setups.get('setups', [])[0] if setups.get('setups') else None
        if top_s:
            print(f"Top Setup: {top_s.get('biasLabel')} | Strike: {top_s.get('strike')} | Premium: {top_s.get('currentPremium')}")
            print(f"Entry: {top_s.get('entryRange')} | SL: {top_s.get('stopLoss')} | T1: {top_s.get('target1')} (Hit Chance: {top_s.get('t1Probability')}%)")

if __name__ == '__main__':
    asyncio.run(test())
