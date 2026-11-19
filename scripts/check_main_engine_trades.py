import sqlite3
import json
import os

db_path = 'd:/ReactJs/aivolve-trading-ai/backend/aivolve_trading.db'
conn = sqlite3.connect(db_path)
c = conn.cursor()

def show_table(table_name):
    c.execute(f"PRAGMA table_info({table_name})")
    cols = [r[1] for r in c.fetchall()]
    print(f"\n=== {table_name} Columns ===")
    print(cols)
    c.execute(f"SELECT * FROM {table_name} ORDER BY 1 DESC LIMIT 5")
    rows = c.fetchall()
    print(f"Sample {table_name} (Last 5):")
    for r in rows:
        print(" ", dict(zip(cols, r)))

show_table('signals')
show_table('signal_evaluations')
show_table('research_paper_trades')

# Check paper_trading_records.json
rec_path = 'd:/ReactJs/aivolve-trading-ai/backend/app/data/paper_trading_records.json'
with open(rec_path, 'r', encoding='utf-8') as f:
    data = json.load(f)

print("\n=== PAPER TRADING RECORDS ===")
open_p = data.get('openPositions', [])
print(f"Open Positions: {len(open_p)}")
for p in open_p:
    print(f"  OPEN: {p.get('id')} | {p.get('contractSymbol')} | Entry: {p.get('entryPremium')} | Strategy: {p.get('strategy')}")

closed_p = data.get('recentClosedTrades', []) + data.get('closedTrades', [])
print(f"Closed Positions: {len(closed_p)}")
for p in closed_p:
    print(f"  CLOSED: {p.get('id')} | {p.get('contractSymbol')} | Entry: {p.get('entryPremium')} | Exit: {p.get('exitPremium')} | Net PnL: {p.get('netPnl')}")
