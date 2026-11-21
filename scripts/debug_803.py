# Let's inspect trades and check what sums to 803.75
import json

json_path = 'd:\\ReactJs\\aivolve-trading-ai\\backend\\app\\data\\paper_trading_records.json'
with open(json_path, 'r', encoding='utf-8') as f:
    records = json.load(f)

closed = records.get('closedTrades', [])
trades_20nov = closed[:11]

# Check combinations of costs or PnLs
for t in trades_20nov:
    print(t.get('id'), "gross:", t.get('grossPnl'), "net:", t.get('netPnl'), "cost:", t.get('grossPnl', 0) - t.get('netPnl', 0))

# Also check trades 12-23 (from 19 Nov)
print("\n19 Nov trades costs:")
for t in closed[11:]:
    print(t.get('id'), "cost:", t.get('grossPnl', 0) - t.get('netPnl', 0))
