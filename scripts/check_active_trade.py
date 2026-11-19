import sys
sys.path.insert(0, '.')
import asyncio
import urllib.request
import json
from app.data.providers.factory import get_market_data_provider

async def main():
    p = get_market_data_provider()
    await p._ensure_authenticated()
    q = await p.get_option_quote('BANKNIFTY', 62700, 'CE')
    ltp = q.get('ltp') if q else None
    bid = q.get('bid') if q else None
    ask = q.get('ask') if q else None

    # Refresh paper trading portfolio
    req = urllib.request.Request('http://127.0.0.1:8000/api/paper-trading/portfolio')
    with urllib.request.urlopen(req) as r:
        data = json.loads(r.read().decode())
        for pos in data.get('openPositions', []):
            entry = float(pos.get('entryPremium', 355.75))
            curr = float(ltp or pos.get('currentLtp', entry))
            lot_size = int(pos.get('lotSize', 30))
            pts = curr - entry
            pnl = pts * lot_size
            pct = (pts / entry) * 100.0 if entry > 0 else 0.0
            print(f"Contract: {pos.get('contractSymbol')}")
            print(f"Entry: Rs.{entry:.2f} | Current LTP: Rs.{curr:.2f} (Bid: Rs.{bid}, Ask: Rs.{ask})")
            print(f"Floating PnL: Rs.{pnl:+.2f} ({pts:+.2f} pts | {pct:+.2f}%)")
            print(f"Target 1: Rs.{pos.get('target1')} | Stop-Loss: Rs.{pos.get('stopLoss')}")

if __name__ == '__main__':
    asyncio.run(main())
