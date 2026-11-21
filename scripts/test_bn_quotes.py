import sys
sys.path.append('d:/ReactJs/aivolve-trading-ai/backend')
import asyncio
from app.data.providers.factory import get_market_data_provider
from app.data.instrument_master import get_instrument_master

async def main():
    provider = get_market_data_provider()
    print("Provider:", provider.get_provider_name(), "Authenticated:", getattr(provider, 'is_authenticated', False))
    master = get_instrument_master()
    ladder = master.get_option_chain_contracts("BANK NIFTY", 63500, 100, num_strikes=5)
    print("Ladder contracts found:", len(ladder))
    tokens = []
    for pair in ladder:
        if pair.get("ce_contract"):
            tokens.append(str(pair["ce_contract"]["token"]))
            print("  CE:", pair["ce_contract"]["symbol"], "Token:", pair["ce_contract"]["token"])
        if pair.get("pe_contract"):
            tokens.append(str(pair["pe_contract"]["token"]))
            print("  PE:", pair["pe_contract"]["symbol"], "Token:", pair["pe_contract"]["token"])
    if hasattr(provider, 'get_batch_quotes'):
        quotes = await provider.get_batch_quotes("NFO", tokens)
        print("Fetched quotes count:", len(quotes))
        for tok, q in list(quotes.items())[:4]:
            print(f"  Token {tok}: ltp={q.get('lastPrice') or q.get('ltp')}, oi={q.get('openInterest')}")

asyncio.run(main())
