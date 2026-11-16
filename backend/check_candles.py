import asyncio
from app.data.providers.factory import get_market_data_provider

async def main():
    p = get_market_data_provider()
    for sym in ['NIFTY 50', 'SENSEX']:
        df = await p.get_intraday_candles(sym, '5m')
        print(f"=== {sym} 5M CANDLES (LAST 8) ===")
        if df is not None and not df.empty:
            for idx, row in df.tail(8).iterrows():
                o, h, l, c = row['open'], row['high'], row['low'], row['close']
                ts = str(row.get('timestamp', ''))[-8:]
                color = "RED" if c < o else "GREEN"
                print(f"{ts} | O: {o:.1f} H: {h:.1f} L: {l:.1f} C: {c:.1f} | {color}")

if __name__ == '__main__':
    asyncio.run(main())

