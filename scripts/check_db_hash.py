import sqlite3
import hashlib

db_path = r"d:\ReactJs\aivolve-trading-ai\backend\aivolve_trading.db"
conn = sqlite3.connect(db_path)
conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
conn.close()

with open(db_path, "rb") as f:
    h = hashlib.sha256(f.read()).hexdigest().upper()

print("Current hash of aivolve_trading.db:", h)
print("Expected hash:                     C85C49BE76DEE40557C4B9AAF308B4E3BEACA03CD4B1CD1CE90D051566EABF44")
print("Match?", h == "C85C49BE76DEE40557C4B9AAF308B4E3BEACA03CD4B1CD1CE90D051566EABF44")
