import json
import sqlite3
import os

target_ids = [
    'PT-87BAC4A8',
    'PT-B43E2C4B',
    'PT-FBEA215F',
    'PT-8F92618C',
    'PT-D8D780EB',
    'PT-21E1FBA1'
]

json_path = 'd:\\ReactJs\\aivolve-trading-ai\\backend\\app\\data\\paper_trading_records.json'
with open(json_path, 'r', encoding='utf-8') as f:
    records = json.load(f)

closed = records.get('closedTrades', [])
open_trades = records.get('openPositions', [])
all_trades = {t.get('id'): t for t in closed + open_trades}

print("=== TARGET TRADES FROM paper_trading_records.json ===")
for tid in target_ids:
    t = all_trades.get(tid)
    if t:
        print(f"\n--- {tid} ---")
        for k, v in t.items():
            print(f"  {k}: {v}")
    else:
        print(f"\n--- {tid} NOT FOUND ---")

print("\n=== TOTALS ACROSS ALL 20 NOV TRADES ===")
# Let's inspect all trades in paper_trading_records.json to see gross, costs, net
for idx, t in enumerate(closed):
    print(f"{idx+1}. {t.get('id')} | {t.get('contractSymbol')} | Entry: {t.get('entryPremium')} | Exit: {t.get('exitPremium')} | Gross: {t.get('grossPnl')} | Costs: {t.get('tradingCosts')} | Net: {t.get('netPnl')} | Reason: {t.get('exitReason')}")

