import sqlite3

conn = sqlite3.connect('d:\\ReactJs\\aivolve-trading-ai\\backend\\aivolve_trading.db')
cur = conn.cursor()
for table in ['research_setup_evaluations', 'signals', 'signal_evaluations']:
    print(f"\n--- Columns in {table} ---")
    cur.execute(f"PRAGMA table_info({table});")
    for col in cur.fetchall():
        print(f"  {col[1]} ({col[2]})")
conn.close()
