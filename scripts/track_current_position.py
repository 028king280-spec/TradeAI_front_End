import sys
sys.path.insert(0, '.')
import urllib.request
import json
import asyncio
from app.data.providers.factory import get_market_data_provider

def check_indices():
    try:
        req = urllib.request.Request('http://127.0.0.1:8000/api/options/overview')
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read().decode())
            for idx in data.get('indices', []):
                sym = idx.get('symbol', '')
                ltp = idx.get('currentValue', 0)
                chg = idx.get('change', 0)
                pct = idx.get('changePercent', 0)
                print(f"{sym:<12} | LTP: {ltp:>9.2f} | Change: {chg:>+7.2f} ({pct:>+5.2f}%)")
    except Exception as e:
        print('Indices error:', e)

async def check_option():
    try:
        p = get_market_data_provider()
        await p._ensure_authenticated()
        q = await p.get_option_quote('NIFTY', 25400, 'CE')
        if q:
            ltp = q.get('ltp')
            bid = q.get('bid')
            ask = q.get('ask')
            print(f"Contract: NIFTY23NOV2625400CE | LTP: Rs.{ltp} | Bid: Rs.{bid} | Ask: Rs.{ask}")
    except Exception as e:
        print('Option quote error:', e)

if __name__ == '__main__':
    print('=== LIVE MARKET UPDATE ===')
    check_indices()
    print('\n=== QUALIFIED CONTRACT UPDATE ===')
    asyncio.run(check_option())
