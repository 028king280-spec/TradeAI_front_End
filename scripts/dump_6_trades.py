import json

json_path = 'd:\\ReactJs\\aivolve-trading-ai\\backend\\app\\data\\paper_trading_records.json'
with open(json_path, 'r', encoding='utf-8') as f:
    records = json.load(f)

closed = records.get('closedTrades', [])
target_ids = ['PT-87BAC4A8', 'PT-B43E2C4B', 'PT-FBEA215F', 'PT-8F92618C', 'PT-D8D780EB', 'PT-21E1FBA1']

target_trades = {t['id']: t for t in closed if t.get('id') in target_ids}

for tid in target_ids:
    t = target_trades.get(tid)
    print(f"==================== {tid} ====================")
    if not t:
        print("NOT FOUND")
        continue
    for k in sorted(t.keys()):
        print(f"  {k}: {t[k]}")
    print()
