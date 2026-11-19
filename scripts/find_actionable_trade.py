import urllib.request
import json

def fetch(url):
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'AIVOLVE-TradeFinder'})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode('utf-8'))
    except Exception as e:
        return {'error': str(e)}

def main():
    for sym in ['NIFTY50', 'BANKNIFTY', 'FINNIFTY', 'SENSEX']:
        print(f"\n==================== {sym} ====================")
        # 1. Overview
        an = fetch(f'http://127.0.0.1:8000/api/options/{sym}/analysis')
        spot = an.get('underlyingPrice')
        atm = an.get('atmStrike')
        print(f"Spot: {spot} | ATM: {atm}")
        
        # 2. Next Session Recommendation
        rec = fetch(f'http://127.0.0.1:8000/api/options/{sym}/next-session/recommendation')
        if rec.get('status') == 'SUCCESS':
            r = rec.get('recommendation', {})
            print(f"  >>> NEXT SESSION RECOMMENDATION <<<")
            print(f"  Bias: {r.get('bias')} | Contract: {r.get('contractSymbol')}")
            print(f"  LTP: Rs.{r.get('livePrice')} | Suggested Entry: {r.get('suggestedEntry')}")
            print(f"  SL: Rs.{r.get('stopLoss')} | T1: Rs.{r.get('target1')} | T2: Rs.{r.get('target2')} | T3: Rs.{r.get('target3')}")
            print(f"  Risk/Reward: 1:{r.get('riskRewardRatio')} | Confidence: {r.get('confidence')}")
            print(f"  Do-Not-Chase: Rs.{r.get('doNotChaseThreshold')}")
        else:
            print(f"  Next Session: {rec.get('message') or rec.get('error')}")

        # 3. Research Setup (60-pt)
        res = an.get('researchSetup', {})
        if res.get('qualified'):
            st = res.get('setup', {})
            print(f"  >>> 60-PT RESEARCH TRADE <<<")
            print(f"  Contract: {st.get('contractSymbol')} | Entry: Rs.{st.get('entryPremium')} | SL: Rs.{st.get('stopLoss')} | Target: Rs.{st.get('targetPremium')} (+{st.get('targetGainPct')}%)")
        else:
            print(f"  Research 60-pt Score: {res.get('score')} | Action: {res.get('action')} | Reasons: {res.get('reasons')}")

        # 4. Today Options Setups (80-pt)
        prod = an.get('todayOptionsSetups', {})
        if prod.get('hasQualifiedSetups'):
            for s in prod.get('setups', []):
                print(f"  >>> 80-PT PRODUCTION TRADE <<<: {s.get('bias')} {s.get('contractSymbol')} @ Rs.{s.get('currentPremium')} | SL: {s.get('stopLoss')} | T1: {s.get('target1')}")
        else:
            print(f"  Production 80-pt: {prod.get('noTradeReason') or 'No setup passed 80-pt'}")

if __name__ == '__main__':
    main()
