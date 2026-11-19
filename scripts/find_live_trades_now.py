import urllib.request
import json
import sys

def fetch(url):
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'AIVOLVE-Scanner'})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode('utf-8'))
    except Exception as e:
        return {'error': str(e)}

print('=== 1. LIVE MARKET INDICES ===')
ov = fetch('http://127.0.0.1:8000/api/options/overview')
if 'indices' in ov:
    for idx in ov['indices']:
        sym = idx.get('symbol')
        ltp = idx.get('currentValue')
        chg = idx.get('change')
        pct = idx.get('changePercent')
        status = idx.get('marketStatus')
        d_status = idx.get('dataStatus')
        print(f"Index: {sym:<12} | LTP: {ltp} | Change: {chg} ({pct} pct) | Status: {status} ({d_status})")
    sent = ov.get('marketSentiment', {})
    print(f"Sentiment: {sent.get('overallSentiment')} | Score: {sent.get('sentimentScore')} | Trend: {sent.get('trendStrength')}")
    print(f"India VIX: {ov.get('vix', {}).get('value')} ({ov.get('vix', {}).get('status')})")
else:
    print("Overview response:", ov)

for index_name in ['NIFTY50', 'BANKNIFTY', 'SENSEX']:
    print(f"\n=== 2. TODAY {index_name} OPTIONS SETUPS ===")
    res = fetch(f'http://127.0.0.1:8000/api/options/{index_name}/setups')
    ts = res.get('todayOptionsSetups', {})
    has_q = ts.get('hasQualifiedSetups')
    regime = ts.get('marketRegime')
    reason = ts.get('noTradeReason')
    print(f"Market Regime: {regime} | Has Qualified Setups: {has_q}")
    if reason:
        print(f"Notice: {reason}")
    setups = ts.get('setups', [])
    print(f"Total Candidate Setups: {len(setups)}")
    for s in setups:
        b = s.get('bias')
        cs = s.get('contractSymbol')
        st = s.get('strike')
        p = s.get('currentPremium')
        sl = s.get('stopLoss')
        t1 = s.get('target1')
        t2 = s.get('target2')
        sc = s.get('qualificationScore')
        mod = s.get('smcModel')
        print(f"-> [{b}] {cs} (Strike: {st}) | Premium: Rs.{p} | SL: {sl} | T1: {t1} | T2: {t2} | Score: {sc} | Model: {mod}")

print('\n=== 3. LIVE SIGNALS TRACKER ===')
sigs = fetch('http://127.0.0.1:8000/api/signals/today')
data_sig = sigs.get('data', {})
tracked = data_sig.get('trackedOptionSetups', [])
print(f"Total Tracked Setups: {len(tracked)}")
for t in tracked:
    sym = t.get('symbol')
    bias = t.get('bias')
    status = t.get('signalStatus')
    cs = t.get('contractSymbol')
    entry = t.get('entryPrice')
    ltp = t.get('currentPremium')
    mfe = t.get('maxFavorableExcursionPts')
    mae = t.get('maxAdverseExcursionPts')
    print(f"-> [{bias}] {sym} ({cs}) Status: {status} | Entry: {entry} | LTP: {ltp} | MFE: +{mfe} pts | MAE: -{mae} pts")
