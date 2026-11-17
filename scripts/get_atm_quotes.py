import asyncio
import sys
import os
sys.path.insert(0, os.path.abspath('backend'))
sys.path.insert(0, os.path.abspath('.'))
from app.data.providers.factory import get_market_data_provider
from app.data.instrument_master import get_instrument_master

async def main():
    p = get_market_data_provider()
    await p.login()
    m = get_instrument_master()
    for strike in [25350, 25400]:
        for opt in ['CE', 'PE']:
            c = m.resolve_option_contract('NIFTY', strike, opt)
            if c:
                token = str(c['token'])
                q = await p.get_batch_quotes('NFO', [token])
                q_data = q.get(token, {})
                print(f"{c['symbol']} ({opt}): LTP={q_data.get('ltp')} Bid={q_data.get('bid')} Ask={q_data.get('ask')} OI={q_data.get('openInterest')} Vol={q_data.get('volume')}")

if __name__ == '__main__':
    asyncio.run(main())
