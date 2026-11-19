import sqlite3
import json

conn = sqlite3.connect('d:/ReactJs/aivolve-trading-ai/backend/aivolve_trading.db')
c = conn.cursor()

c.execute("SELECT COUNT(*), SUM(CASE WHEN qualified = 1 THEN 1 ELSE 0 END) FROM signal_evaluations")
tot, qual = c.fetchone()
print(f"Main Engine Evaluations in Journal: Total = {tot}, Qualified = {qual}")

c.execute("SELECT id, symbol, action, qualified, rejection_reasons, evaluated_at FROM signal_evaluations WHERE qualified = 1 ORDER BY id DESC")
rows = c.fetchall()
print(f"\nQualified Trades Count in Journal: {len(rows)}")
for r in rows:
    print(f"  ID: {r[0]} | Symbol: {r[1]} | Action: {r[2]} | Time: {r[5]}")

c.execute("SELECT id, symbol, action, qualified, rejection_reasons, evaluated_at FROM signal_evaluations ORDER BY id DESC LIMIT 10")
print("\nLast 10 Evaluations:")
for r in c.fetchall():
    print(f"  ID: {r[0]} | {r[1]} | Action: {r[2]} | Qual: {r[3]} | Reas: {r[4]}")
