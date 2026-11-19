import urllib.request
import json
import sys

def fetch(url):
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'AIVOLVE-Scanner'})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode('utf-8'))
    except Exception as e:
        return {'error': str(e)}

print("=== 1. LIVE INDICES OVERVIEW ===")
ov = fetch('http://127.0.0.1:8000/api/options/overview')
if 'indices' in ov:
    for idx in ov['indices']:
        sym = idx.get('symbol', '')
        ltp = idx.get('currentValue', 0)
        chg = idx.get('change', 0)
        pct = idx.get('changePercent', 0)
        st = idx.get('marketStatus', '')
        ds = idx.get('dataStatus', '')
        print(f"{sym:<12} | LTP: {ltp:>9.2f} | Change: {chg:>+7.2f} ({pct:>+5.2f}%) | Status: {st} ({ds})")
    vix = ov.get('vix', {})
    print(f"INDIA VIX: {vix.get('value')} ({vix.get('status')})")
    sent = ov.get('marketSentiment', {})
    print(f"Sentiment: {sent.get('overallSentiment')} (Score: {sent.get('sentimentScore')}) | Trend: {sent.get('trendStrength')}")

print("\n=== 2. DETAILED ANALYSIS & CONFLUENCE SCORES ===")
for sym in ['NIFTY50', 'BANKNIFTY', 'SENSEX']:
    an = fetch(f'http://127.0.0.1:8000/api/options/{sym}/analysis')
    ms = an.get('marketState', {})
    res = an.get('researchSetup', {})
    prod = an.get('todayOptionsSetups', {})
    print(f"\n--- {sym} ---")
    print(f"Market State: {ms.get('regime')} | Directional Bias: {ms.get('directionalBias')} | No-Trade Zone: {ms.get('isNoTradeZone')}")
    print(f"Key Levels: Spot={an.get('underlyingPrice')} | ATM={an.get('atmStrike')} | PCR={an.get('pcr', {}).get('pcrOi')}")
    print(f"Research Setup (60-pt): Qualified={res.get('qualified')} | Score={res.get('score')} | Action={res.get('action')}")
    if res.get('qualified'):
        st = res.get('setup', {})
        print(f"  >>> QUALIFIED 60-PT RESEARCH TRADE <<<")
        print(f"  Contract: {st.get('contractSymbol')} | Entry: Rs.{st.get('entryPremium')} | SL: Rs.{st.get('stopLoss')} | Target: Rs.{st.get('targetPremium')} (+{st.get('targetGainPct')}%) | R:R: {st.get('grossRewardRisk')}")
    else:
        reasons = res.get('reasons', [])
        print(f"  Research Status: WAITING FOR 60+ (Reasons: {reasons})")

    print(f"Production Setups (80-pt): Qualified={prod.get('hasQualifiedSetups')} | Total={len(prod.get('setups', []))}")
    if prod.get('hasQualifiedSetups'):
        for s in prod.get('setups', []):
            print(f"  >>> QUALIFIED 80-PT PROD TRADE <<<: {s.get('bias')} {s.get('contractSymbol')} @ Rs.{s.get('currentPremium')} | SL: {s.get('stopLoss')} | T1: {s.get('target1')} | Score: {s.get('qualificationScore')}")
    else:
        print(f"  Production Notice: {prod.get('noTradeReason') or 'No setup passed 80-pt institutional confluence hurdle.'}")

print("\n=== 3. LIVE SIGNALS TRACKER ===")
sig = fetch('http://127.0.0.1:8000/api/signals/today')
tracked = sig.get('data', {}).get('trackedOptionSetups', [])
print(f"Total Tracked Active Signals: {len(tracked)}")
for t in tracked:
    print(f"Signal: {t.get('symbol')} | Status: {t.get('status')} | Current PnL: {t.get('currentPnL')}")

print("\n=== 4. LIVE PAPER TRADING PORTFOLIO ===")
port = fetch('http://127.0.0.1:8000/api/paper-trading/portfolio')
if port.get('status') == 'SUCCESS':
    open_pos = port.get('openPositions', [])
    print(f"Open Positions: {len(open_pos)}")
    for p in open_pos:
        print(f"  {p.get('id')} | {p.get('contractSymbol')} | Entry: Rs.{p.get('entryPremium')} | CMP: Rs.{p.get('currentPremium')} | Gross PnL: Rs.{p.get('unrealizedGrossPnl')} | High: Rs.{p.get('highestObservedPremium')}")
else:
    print(f"Portfolio fetch error: {port}")

