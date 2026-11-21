import urllib.request
import json

req = urllib.request.Request('http://127.0.0.1:8000/api/options/BANKNIFTY/analysis')
with urllib.request.urlopen(req, timeout=30) as resp:
    data = json.loads(resp.read().decode('utf-8'))
    print("BANK NIFTY Spot:", data.get("underlyingPrice"))
    print("Market State:", data.get("marketState", {}).get("market_regime"))
    print("Confluence:", data.get("researchSetup", {}).get("score"))
    print("Qualified:", data.get("researchSetup", {}).get("qualified"))
    print("Setup:", data.get("researchSetup", {}).get("setup"))
    print("Today Options Setups:", data.get("todayOptionsSetups"))
