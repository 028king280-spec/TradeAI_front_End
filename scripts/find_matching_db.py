import hashlib
import glob

for p in glob.glob(r"d:\ReactJs\**\aivolve_trading.db", recursive=True):
    with open(p, "rb") as f:
        h = hashlib.sha256(f.read()).hexdigest().upper()
    print(p, h)
