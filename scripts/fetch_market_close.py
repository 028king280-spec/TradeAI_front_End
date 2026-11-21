import urllib.request
import json

def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'AIVOLVE-Inspector'})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode('utf-8'))

print("=== FINAL CLOSING NUMBERS (20 NOV 2026) ===")
ov = fetch('http://127.0.0.1:8000/api/options/overview')
for idx in ov.get('indices', []):
    print(f"{idx.get('symbol')}: {idx.get('currentValue')} | Change: {idx.get('change')} ({idx.get('percentChange')}%) | Regime: {idx.get('regime')}")
