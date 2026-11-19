import sys
sys.path.insert(0, '.')
import json
import os
from app.data.instrument_master import get_instrument_master

master = get_instrument_master()

import sys, asyncio
sys.path.insert(0, '.')
from app.data.instrument_master import get_instrument_master
from app.data.providers.factory import get_market_data_provider

async def main():
    m = get_instrument_master()
    c = m._options_by_symbol.get('BANKNIFTY23NOV2662500PE')
    print("Contract in master:", c)
    if c:
        tok = str(c.get('token'))
        p = get_market_data_provider()
        res = await p.get_batch_quotes('NFO', [tok])
        print("Live Quote from broker for 62500 PE:", res)

asyncio.run(main())
