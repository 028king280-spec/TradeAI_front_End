import json
import os

path = 'D:/ReactJs/aivolve-trading-ai/backend/app/data/paper_trading_records.json'
if os.path.exists(path):
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    print("Keys in records:", list(data.keys()))
    print("Initial Capital:", data.get("initialCapital"))
    print("Current Capital:", data.get("currentCapital"))
    print("Total Realized PnL:", data.get("totalRealizedPnl"))
    print("Open Positions:", len(data.get("openPositions", [])))
    for p in data.get("openPositions", []):
        print(f"  [OPEN] {p.get('id')} {p.get('contractSymbol')} Entry: {p.get('entryPremium')} CMP: {p.get('currentPremium')} Time: {p.get('entryTimestamp')}")
    print("Closed Trades:", len(data.get("closedTrades", [])))
    for t in data.get("closedTrades", []):
        print(f"  [CLOSED] {t.get('id')} {t.get('contractSymbol')} Entry: {t.get('entryPremium')} Exit: {t.get('exitPremium')} NetPnL: {t.get('netPnl')} Status: {t.get('status')} Reason: {t.get('exitReason')} Time: {t.get('entryTimestamp')} -> {t.get('exitTimestamp')}")
else:
    print("File not found:", path)

research_dir = 'D:/ReactJs/aivolve-trading-ai/backend/data'
if os.path.exists(research_dir):
    print("\nFiles in backend/data:", os.listdir(research_dir))
