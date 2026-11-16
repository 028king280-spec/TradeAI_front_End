import asyncio
from app.data.providers.factory import get_market_data_provider

async def test_recency():
    p = get_market_data_provider()
    for sym in ['NIFTY 50', 'SENSEX']:
        c_df = await p.get_intraday_candles(sym, '5m')
        if c_df is not None and not c_df.empty:
            total_bars = len(c_df)
            max_idx = c_df["high"].idxmax()
            min_idx = c_df["low"].idxmin()
            
            # Position relative to tail (e.g. how many bars ago)
            # using integer loc
            high_loc = c_df.index.get_loc(max_idx) if max_idx in c_df.index else -1
            low_loc = c_df.index.get_loc(min_idx) if min_idx in c_df.index else -1
            
            bars_since_high = total_bars - 1 - high_loc
            bars_since_low = total_bars - 1 - low_loc
            
            print(f"=== {sym} EXTREMES RECENCY ===")
            print(f"Total bars: {total_bars}")
            print(f"Day High was at bar {high_loc} ({bars_since_high} bars ago, ~{bars_since_high*5} mins ago)")
            print(f"Day Low was at bar {low_loc} ({bars_since_low} bars ago, ~{bars_since_low*5} mins ago)")
            print(f"-> Most recent extreme: {'DAY HIGH (Rejection Dump)' if high_loc > low_loc else 'DAY LOW (Demand Bounce)'}")

if __name__ == '__main__':
    asyncio.run(test_recency())

