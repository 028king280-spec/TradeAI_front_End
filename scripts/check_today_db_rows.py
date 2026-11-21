import sqlite3

conn = sqlite3.connect(r"d:\ReactJs\aivolve-trading-ai\backend\aivolve_trading.db")
cur = conn.cursor()

cur.execute("SELECT count(*) FROM research_setup_evaluations WHERE evaluated_at LIKE '2026-11-20%';")
print("20 Nov research evaluations:", cur.fetchone()[0])

cur.execute("SELECT count(*) FROM signal_evaluations WHERE evaluated_at LIKE '2026-11-20%';")
print("20 Nov signal evaluations:", cur.fetchone()[0])

cur.execute("SELECT count(*) FROM research_paper_trades WHERE opened_at LIKE '2026-11-20%';")
print("20 Nov research paper trades:", cur.fetchone()[0])

conn.close()
