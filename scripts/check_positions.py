import urllib.request
import json

req = urllib.request.Request('http://127.0.0.1:8000/api/paper-trading/portfolio')
with urllib.request.urlopen(req) as resp:
    data = json.loads(resp.read().decode('utf-8'))
    for p in data.get('openPositions', []):
        print(f"ID: {p.get('id')} | Contract: {p.get('contractSymbol')} | Entry: {p.get('entryPremium')} | CMP: {p.get('currentPremium')} | Updated: {p.get('lastPriceUpdateTimestamp')}")
