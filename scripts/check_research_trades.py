import sqlite3
import json

conn = sqlite3.connect('d:\\ReactJs\\aivolve-trading-ai\\backend\\aivolve_trading.db')
cur = conn.cursor()
cur.execute('PRAGMA table_info(research_paper_trades);')
cols = [col[1] for col in cur.fetchall()]
print("Columns in research_paper_trades:", cols)

cur.execute('SELECT * FROM research_paper_trades ORDER BY rowid DESC LIMIT 10;')
rows = cur.fetchall()
print(f"Total rows fetched: {len(rows)}")
for r in rows:
    trade = dict(zip(cols, r))
    print(f"\nID: {trade.get('id')} | Sym: {trade.get('contract_symbol')} | Status: {trade.get('status')} | Outcome: {trade.get('outcome')} | Reason: {trade.get('exit_reason')}")
    print(f"  Entry: {trade.get('entry_premium')} | Exit: {trade.get('exit_premium')} | PnL: {trade.get('pnl_inr')} | Closed: {trade.get('closed_at')}")
conn.close()
