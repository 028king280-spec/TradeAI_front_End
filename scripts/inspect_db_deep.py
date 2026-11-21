import sqlite3
import json

conn = sqlite3.connect('d:\\ReactJs\\aivolve-trading-ai\\backend\\aivolve_trading.db')
cur = conn.cursor()

print("=== CHECKING SIGNALS TABLE ===")
cur.execute("SELECT id, symbol, contract_symbol, strike, option_type, status, created_at, entry_triggered_at, entry_observed_price, stop_loss_premium, target_1_premium, target_2_premium, closed_at, final_outcome, gross_pnl_points, net_pnl_inr FROM signals ORDER BY created_at DESC LIMIT 15;")
rows = cur.fetchall()
print(f"Total signals in table: {len(rows)}")
for r in rows:
    print(r)

print("\n=== SEARCHING FOR CONTRACTS IN SIGNALS TABLE ===")
for sym in ['NIFTY23NOV2625750CE', 'NIFTY23NOV2625700CE', 'NIFTY23NOV2625750PE', 'NIFTY23NOV2625700PE']:
    cur.execute("SELECT id, contract_symbol, strike, option_type, status, created_at, entry_triggered_at, closed_at FROM signals WHERE contract_symbol = ?;", (sym,))
    s_rows = cur.fetchall()
    print(f"Contract {sym}: {len(s_rows)} signals found")
    for sr in s_rows:
        print(" ", sr)

print("\n=== CHECKING SIGNAL_EVENTS ===")
cur.execute("SELECT count(*) FROM signal_events;")
print("Signal events count:", cur.fetchone()[0])

print("\n=== CHECKING SIGNAL_SNAPSHOTS ===")
cur.execute("SELECT count(*) FROM signal_snapshots;")
print("Signal snapshots count:", cur.fetchone()[0])

print("\n=== CHECKING MARKET CANDLES ===")
cur.execute("SELECT count(*), min(timestamp), max(timestamp) FROM market_candles WHERE timestamp LIKE '2026-11-20%';")
print("Market candles on 20 Nov 2026:", cur.fetchone())

conn.close()
