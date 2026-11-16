import asyncio
from app.data.providers.factory import get_market_data_provider
from app.options.candle_processor import process_candlestick_series

async def test_reversal_detection():
    p = get_market_data_provider()
    for sym in ['NIFTY 50', 'SENSEX']:
        q = await p.get_quote(sym)
        c_df = await p.get_intraday_candles(sym, '5m')
        c_inf = process_candlestick_series(c_df, sym, '5m')
        
        ltp = float(q.get("currentPrice") or q.get("ltp", 0.0))
        d_high = float(q.get("dayHigh", ltp))
        d_low = float(q.get("dayLow", ltp))
        atr = float(c_inf.get("atr") or (ltp * 0.005))
        
        if c_df is not None and not c_df.empty and "high" in c_df.columns:
            effective_d_high = max(d_high, float(c_df["high"].max()))
            effective_d_low = min(d_low, float(c_df["low"].min()))
        else:
            effective_d_high = d_high
            effective_d_low = d_low
            
        drop_from_high = effective_d_high - ltp
        drop_atr_ratio = drop_from_high / atr if atr > 0 else 0.0
        
        # Check recent candles (last 4)
        recent_bearish = False
        if c_df is not None and len(c_df) >= 3:
            tail = c_df.tail(4)
            red_count = sum(1 for _, row in tail.iterrows() if row["close"] < row["open"])
            last_c = tail.iloc[-1]
            prev_c = tail.iloc[-2]
            closed_lower = last_c["close"] < prev_c["close"]
            recent_bearish = red_count >= 2 or closed_lower or (ltp < prev_c["low"])
            
        is_bearish_reversal = (drop_atr_ratio >= 0.28) and recent_bearish
        
        print(f"=== {sym} REVERSAL CHECK ===")
        print(f"LTP: {ltp} | Effective DayHigh: {effective_d_high} | Drop: {drop_from_high:.1f} pts ({drop_atr_ratio:.2f} ATR)")
        print(f"ATR: {atr:.1f} | Recent Bearish Candles: {recent_bearish}")
        print(f"-> IS BEARISH REVERSAL (PUT TRIGGER): {is_bearish_reversal}")

if __name__ == '__main__':
    asyncio.run(test_reversal_detection())

