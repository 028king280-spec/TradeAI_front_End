import json
import os
import glob

print("=== SEARCHING FOR BASELINE DATA FILES ACROSS REPOSITORY ===")
for pattern in ["*paper_trading_records*", "*review*", "*ml_training*", "*backtest*", "*.db"]:
    matches = glob.glob(f"**/{pattern}", recursive=True)
    for m in matches:
        print(f"  Found: {m} ({os.path.getsize(m)} bytes)")

print("\n=== REVIEW TRADES AUDIT ===")
for r_name in ["review_2026-11-19.json", "review_2026-11-20.json"]:
    p = os.path.join("backend/app/data/daily_post_market_reviews", r_name)
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8") as f:
            d = json.load(f)
        trades = d.get("trades", [])
        print(f"\n--- {r_name}: Total {len(trades)} Trades ---")
        for t in trades:
            tid = t.get("trade_id")
            sym = t.get("contract_symbol")
            ep = t.get("entry_premium")
            xp = t.get("exit_premium")
            mfe = t.get("mfe_pts")
            mae = t.get("mae_pts")
            net = t.get("net_pnl")
            out = t.get("outcome_classification")
            prov = t.get("provenance_classification")
            etime = t.get("entry_time")
            xtime = t.get("exit_time")
            print(f"  {tid} | {sym:24} | Entry: {ep:>6.2f} ({etime}) | Exit: {xp:>6.2f} ({xtime}) | MFE: +{mfe:>5.1f} | MAE: -{mae:>5.1f} | Net: {net:>8.2f} | {out:18} | {prov}")
