import urllib.request
import json

for sym in ['NIFTY50', 'BANKNIFTY', 'NIFTY_BANK', 'BANK_NIFTY', 'NIFTYBANK', 'SENSEX']:
    try:
        req = urllib.request.Request(f'http://127.0.0.1:8000/api/options/{sym}/analysis')
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            print(f"{sym}: Status 200, keys: {list(data.keys())[:5]}, error: {data.get('error')}")
            if 'marketState' in data:
                print(f"   state: {data.get('marketState')}")
            if 'researchSetup' in data:
                print(f"   research: {data.get('researchSetup')}")
    except Exception as e:
        print(f"{sym}: Failed -> {e}")
