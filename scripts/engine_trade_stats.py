import sqlite3
import json
from collections import Counter

conn = sqlite3.connect('d:/ReactJs/aivolve-trading-ai/backend/aivolve_trading.db')
cursor = conn.cursor()

print("=== 1. PAPER TRADING STATE (OPERATOR ACCOUNT) ===")
with open('d:/ReactJs/aivolve-trading-ai/backend/app/data/paper_trading_records.json', 'r') as f:
    pt_data = json.load(f)

all_pt_trades = pt_data.get('closedTrades', []) + pt_data.get('openPositions', [])
pt_engines = Counter()
pt_pnl_by_engine = {}

for t in all_pt_trades:
    strat = t.get('strategy') or t.get('ictSetup') or 'Production MTF Engine'
    pt_engines[strat] += 1
    pnl = t.get('netPnl') or t.get('unrealizedGrossPnl') or 0.0
    pt_pnl_by_engine[strat] = pt_pnl_by_engine.get(strat, 0.0) + pnl

print("Total Operator Trades:", len(all_pt_trades))
for strat, count in pt_engines.items():
    print(f"  - {strat}: {count} trades | Net PnL: ₹{pt_pnl_by_engine[strat]:.2f}")

print("\n=== 2. RESEARCH PAPER TRADING (RESEARCH ENGINE) ===")
cursor.execute("SELECT engine_id, COUNT(*), SUM(net_pnl_paise)/100.0 FROM research_paper_trades GROUP BY engine_id")
for row in cursor.fetchall():
    print(f"  - Engine: {row[0]} | Total Automated Trades: {row[1]} | Net PnL: ₹{row[2]:.2f}")

print("\n=== 3. SIGNAL EVALUATIONS IN DB (BY ENGINE & ACTION) ===")
cursor.execute("SELECT action, qualified, COUNT(*) FROM signal_evaluations GROUP BY action, qualified")
for row in cursor.fetchall():
    print(f"  - Action: {row[0]} | Qualified: {bool(row[1])} | Evaluations: {row[2]}")

print("\n=== 4. RESEARCH EVALUATIONS IN DB ===")
cursor.execute("SELECT engine_id, qualified, COUNT(*) FROM research_setup_evaluations GROUP BY engine_id, qualified")
for row in cursor.fetchall():
    print(f"  - Engine: {row[0]} | Qualified: {bool(row[1])} | Evaluations: {row[2]}")

print("\n=== 5. SIGNALS TABLE BREAKDOWN ===")
cursor.execute("SELECT strategy_version, status, COUNT(*) FROM signals GROUP BY strategy_version, status")
for row in cursor.fetchall():
    print(f"  - Strategy: {row[0]} | Status: {row[1]} | Count: {row[2]}")

conn.close()
