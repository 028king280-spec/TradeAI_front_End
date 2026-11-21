import os
import hashlib

target = "C85C49BE76DEE40557C4B9AAF308B4E3BEACA03CD4B1CD1CE90D051566EABF44"

for root, dirs, files in os.walk(r"d:\ReactJs"):
    if "node_modules" in dirs:
        dirs.remove("node_modules")
    if ".git" in dirs:
        dirs.remove(".git")
    if ".next" in dirs:
        dirs.remove(".next")
    for f in files:
        if f.endswith(".db") or f.endswith(".bak") or f.endswith(".sqlite") or "aivolve" in f:
            p = os.path.join(root, f)
            try:
                with open(p, "rb") as fp:
                    h = hashlib.sha256(fp.read()).hexdigest().upper()
                if h == target:
                    print("MATCH FOUND:", p)
            except Exception:
                pass
print("Scan complete.")
