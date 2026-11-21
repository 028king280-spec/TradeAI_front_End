import sqlite3
import json

conn = sqlite3.connect('d:/ReactJs/aivolve-trading-ai/backend/aivolve_trading.db')
cursor = conn.cursor()

print("=== BANK NIFTY EVALUATIONS TODAY ===")
cursor.execute("SELECT id, symbol, evaluated_at, action, qualified, rejection_reasons FROM signal_evaluations WHERE symbol='BANK NIFTY' ORDER BY id DESC LIMIT 10")
for r in cursor.fetchall():
    print("Main Signal Eval:", r[1], r[2], "Action:", r[3], "Qual:", r[4], "Reasons:", r[5])

print("\n=== BANK NIFTY RESEARCH EVALUATIONS TODAY ===")
cursor.execute("SELECT id, symbol, evaluated_at, qualified, payload FROM research_setup_evaluations WHERE symbol='BANK NIFTY' ORDER BY id DESC LIMIT 5")
for r in cursor.fetchall():
    payload = json.loads(r[4]) if r[4] else {}
    print("Research Eval:", r[1], r[2], "Qual:", r[3], "Score:", payload.get("score"), "Reasons:", payload.get("reasons"), "Stages:", payload.get("stages"))

conn.close()
