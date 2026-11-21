import json

with open('d:/ReactJs/aivolve-trading-ai/backend/app/data/paper_trading_records.json', 'r') as f:
    d = json.load(f)

for p in d.get('openPositions', []):
    print("Position:", p.get('id'), p.get('contractSymbol'))
    print("  Entry Premium:", p.get('entryPremium'))
    print("  Current Premium:", p.get('currentPremium'))
    print("  Stop Loss:", p.get('stopLoss'))
    print("  Target 1:", p.get('target1'))
    print("  Target 2:", p.get('target2'))
    print("  Target 3:", p.get('target3'))
    print("  Lots / Qty:", p.get('lots'), "/", p.get('quantity'))
    print("  Unrealized Gross PnL:", p.get('unrealizedGrossPnl'))
    print("  Highest Observed:", p.get('highestObservedPremium'))
