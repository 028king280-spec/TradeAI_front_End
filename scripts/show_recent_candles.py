import asyncio
import sys
import os
sys.path.insert(0, os.path.abspath('backend'))
sys.path.insert(0, os.path.abspath('.'))

from app.data.market_data_service import market_data_service

async def show_recent_candles():
    for sym in ['NIFTY 50', 'BANKNIFTY']:
        df = await market_data_service.get_historical_candles(sym, '5m', limit=10)
        print(f"=== Recent 5m candles for {sym} ===")
        if df is not None and not df.empty:
            for idx, row in df.tail(6).iterrows():
                print(f"{row.name} | O:{row['open']:.1f} H:{row['high']:.1f} L:{row['low']:.1f} C:{row['close']:.1f} Vol:{row['volume']}")

if __name__ == "__main__":
    asyncio.run(show_recent_candles())
