import sys
sys.path.insert(0, '.')
from app.data.instrument_master import get_instrument_master
master = get_instrument_master()
print('Total options loaded:', len(master._options_by_symbol))
bn_opts = [k for k in master._options_by_symbol.keys() if 'BANKNIFTY' in k]
print('Total BANKNIFTY options:', len(bn_opts))
strikes = sorted(list(set(float(master._options_by_symbol[k].get('strike', 0)) / 100.0 for k in bn_opts if master._options_by_symbol[k].get('strike'))))
print('Strike range in Rs min/max:', strikes[0] if strikes else None, strikes[-1] if strikes else None)
print('Strikes around 50k:', [s for s in strikes if 49000 <= s <= 53000][:10])
print('Strikes around 62k:', [s for s in strikes if 60000 <= s <= 65000][:10])

# Check real spot price from provider
from app.data.providers.factory import get_market_data_provider
import asyncio
async def check_spot():
    provider = get_market_data_provider()
    print('Provider class:', provider.__class__.__name__)
    if hasattr(provider, 'get_latest_quote'):
        q = await provider.get_latest_quote('BANK NIFTY')
        print('BANK NIFTY Quote from provider:', q)
    if hasattr(provider, 'get_index_quotes'):
        iq = await provider.get_index_quotes()
        for idx in iq:
            if 'BANK' in idx.get('symbol', ''):
                print('Index quote:', idx)

asyncio.run(check_spot())
