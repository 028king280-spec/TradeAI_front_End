import urllib.request
import json

def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'AIVOLVE-Inspector'})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode('utf-8'))

print("=== LATEST MARKET INDICES ===")
try:
    ov = fetch('http://127.0.0.1:8000/api/options/overview')
    for idx in ov.get('indices', []):
        sym = idx.get('symbol')
        val = idx.get('currentValue')
        chg = idx.get('change')
        pct = idx.get('percentChange')
        reg = idx.get('regime')
        print(f"  - {sym}: {val} (Change: {chg}, Pct: {pct}%) | Regime: {reg}")
except Exception as e:
    print(f"Error fetching overview: {e}")

print("\n=== SCANNING BANK NIFTY & NIFTY FOR NEW SETUPS ===")
for symbol in ['NIFTY', 'BANKNIFTY']:
    try:
        url = f'http://127.0.0.1:8000/api/options/symbol-deep-analysis?symbol={symbol}'
        res = fetch(url)
        ms = res.get('marketState', {})
        rs = res.get('researchSetup', {})
        tos = res.get('todayOptionsSetups', {})
        print(f"\n--- {symbol} ---")
        print(f"  Regime: {ms.get('market_regime')} | Trend: {ms.get('trend_direction')} | Strength: {ms.get('trend_strength')}")
        print(f"  Action: {ms.get('final_action')} | Headline: {ms.get('headline')}")
        print(f"  Bullish Trigger: {ms.get('bullishActivationTrigger')}")
        print(f"  Bearish Trigger: {ms.get('bearishActivationTrigger')}")
        print(f"  Research Engine Score: {rs.get('score')} | Qualified: {rs.get('qualified')} | Action: {rs.get('action')}")
        if rs.get('reasons'):
            print(f"    Reasons: {rs.get('reasons')}")
        print(f"  Main Engine Status: {tos.get('statusMessage')} | Qualified: {tos.get('hasQualifiedSetups')}")
        if tos.get('disqualificationReasons'):
            print(f"    Disqualification: {tos.get('disqualificationReasons')}")
    except Exception as e:
        print(f"Error checking {symbol}: {e}")
