import urllib.request
import json
import sqlite3

def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'AIVOLVE-Inspector'})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode('utf-8'))

print("=== CURRENT PAPER PORTFOLIO ===")
port = fetch('http://127.0.0.1:8000/api/paper-trading/portfolio')
print("Status:", port.get('status'))
print("Account:", port.get('account'))
open_pos = port.get('openPositions', [])
print(f"Open Positions ({len(open_pos)}):")
for p in open_pos:
    print(f"  - ID: {p.get('id')} | Contract: {p.get('contractSymbol')} | Entry: {p.get('entryPremium')} | CMP: {p.get('currentPremium')} | PnL: {p.get('unrealizedGrossPnl')}")

closed_pos = port.get('closedPositions', [])
print(f"\nClosed Positions ({len(closed_pos)}):")
for p in closed_pos[-6:]:
    print(f"  - ID: {p.get('id')} | Contract: {p.get('contractSymbol')} | Entry: {p.get('entryPremium')} | Exit: {p.get('exitPremium')} | PnL: {p.get('netPnl')} | Exit Reason: {p.get('exitReason')}")

print("\n=== RESEARCH PAPER TRADES DB ===")
conn = sqlite3.connect('d:\\ReactJs\\aivolve-trading-ai\\backend\\aivolve_trading.db')
cur = conn.cursor()
cur.execute("SELECT id, contract_symbol, entry_price, exit_price, pnl_inr, outcome, exit_reason, closed_at FROM research_paper_trades ORDER BY rowid DESC LIMIT 10")
for r in cur.fetchall():
    print(r)
conn.close()
