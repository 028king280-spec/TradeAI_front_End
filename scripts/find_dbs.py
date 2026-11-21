import sqlite3
import glob

db_files = glob.glob('d:\\ReactJs\\aivolve-trading-ai\\backend\\**\\*.db', recursive=True)
print("Found DB files:", db_files)

for db in db_files:
    print(f"\nDB: {db}")
    try:
        conn = sqlite3.connect(db)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [t[0] for t in cur.fetchall()]
        print("Tables:", tables)
        conn.close()
    except Exception as e:
        print("Error:", e)
