import asyncio
from app.data.providers.factory import get_market_data_provider

async def main():
    p = get_market_data_provider()
    for sym in ['NIFTY 50', 'SENSEX']:
        df = await p.get_intraday_candles(sym, '5m')
        q = await p.get_quote(sym)
        ltp = float(q.get("currentPrice") or q.get("ltp", 0.0))
        d_high = float(q.get("dayHigh", ltp))
        d_low = float(q.get("dayLow", ltp))
        
        recent_tail = df.tail(12)
        swing_high = float(recent_tail["high"].max())
        swing_low = float(recent_tail["low"].min())
        
        print(f"=== {sym} ===")
        print(f"Quote LTP: {ltp} | Quote DayHigh: {d_high} | Quote DayLow: {d_low}")
        print(f"Recent 1-Hour Swing High: {swing_high} | Swing Low: {swing_low}")
        print(f"Recent Drop from Swing High: {swing_high - ltp:.1f} pts")
        print(f"Recent Bounce from Swing Low: {ltp - swing_low:.1f} pts")

if __name__ == '__main__':
    asyncio.run(main())

