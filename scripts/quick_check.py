import urllib.request
import json

def test_sym(sym):
    print(f"Fetching {sym}...")
    try:
        req = urllib.request.Request(f'http://127.0.0.1:8000/api/options/{sym}/analysis')
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            print("Keys:", list(data.keys()))
            print("Symbol:", data.get("symbol"))
            print("Underlying Price:", data.get("underlyingPrice"))
            print("Market State:", data.get("marketState"))
            print("Research Setup:", data.get("researchSetup"))
            print("Today Options Setups:", data.get("todayOptionsSetups"))
    except Exception as e:
        print(f"Error: {e}")

test_sym("BANKNIFTY")
test_sym("NIFTY50")
