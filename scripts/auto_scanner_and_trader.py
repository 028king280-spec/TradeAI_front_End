import urllib.request
import json

def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'AIVOLVE-Trader'})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode('utf-8'))

print("=== CHECKING PORTFOLIO POSITIONS ===")
port = fetch('http://127.0.0.1:8000/api/paper-trading/portfolio')
open_pos = port.get('openPositions', [])
print(f"Total Open: {len(open_pos)}")
for p in open_pos:
    print(f"Trade {p.get('id')} | {p.get('contractSymbol')} | Entry: {p.get('entryPremium')} | CMP: {p.get('currentPremium')} | T1: {p.get('target1')} | T2: {p.get('target2')} | PnL: Rs {p.get('unrealizedGrossPnl')}")

print("\n=== SCANNING BANK NIFTY FOR FRESH TRADE ===")
bn = fetch('http://127.0.0.1:8000/api/options/BANKNIFTY/analysis')
bn_rs = bn.get('researchSetup', {})
bn_tos = bn.get('todayOptionsSetups', {})

print(f"Bank Nifty Research Score: {bn_rs.get('score')} | Action: {bn_rs.get('action')} | Qualified: {bn_rs.get('qualified')}")
print(f"Bank Nifty Main Engine: {bn_tos.get('statusMessage')} | Qualified: {bn_tos.get('hasQualifiedSetups')}")

if bn_rs.get('qualified') or bn_tos.get('hasQualifiedSetups'):
    print("BANK NIFTY TRADE QUALIFIED! Triggering paper order...")
else:
    print(f"Bank Nifty pending reasons: {bn_rs.get('reasons')}")

print("\n=== SCANNING NIFTY 50 FOR FRESH TRADE ===")
nf = fetch('http://127.0.0.1:8000/api/options/NIFTY50/analysis')
nf_rs = nf.get('researchSetup', {})
nf_tos = nf.get('todayOptionsSetups', {})
print(f"Nifty 50 Research Score: {nf_rs.get('score')} | Action: {nf_rs.get('action')} | Qualified: {nf_rs.get('qualified')}")
print(f"Nifty 50 Main Engine: {nf_tos.get('statusMessage')} | Qualified: {nf_tos.get('hasQualifiedSetups')}")
