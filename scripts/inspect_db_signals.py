import sqlite3
import json

conn = sqlite3.connect('d:/ReactJs/aivolve-trading-ai/backend/aivolve_trading.db')
cursor = conn.cursor()

def get_cols(table):
    cursor.execute(f"PRAGMA table_info({table});")
    return [c[1] for c in cursor.fetchall()]

print("research_setup_evaluations cols:", get_cols("research_setup_evaluations"))

cursor.execute("SELECT id, symbol, engine_id, qualified FROM research_setup_evaluations WHERE qualified=1 LIMIT 10")
for r in cursor.fetchall():
    print("Qualified Research:", r)

cursor.execute("SELECT id, symbol, contract_symbol, opened_at, closed_at, net_pnl_paise, exit_reason FROM research_paper_trades")
for r in cursor.fetchall():
    print("Research Paper Trade:", r)

cursor.execute("SELECT id, symbol, evaluated_at, action, qualified FROM signal_evaluations WHERE qualified=1 LIMIT 10")
for r in cursor.fetchall():
    print("Qualified Signal Eval:", r)

conn.close()
