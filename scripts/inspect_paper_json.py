import json

path = 'd:\\ReactJs\\aivolve-trading-ai\\backend\\app\\data\\paper_trading_records.json'
with open(path, 'r', encoding='utf-8') as f:
    data = json.load(f)

print("Starting Balance:", data.get('startingBalance'))
print("Current Balance:", data.get('balance'))
print("Realized Gross PnL:", data.get('totalRealizedGrossPnl'))
print("Realized Net PnL:", data.get('totalRealizedNetPnl'))
print("Trading Costs:", data.get('totalTradingCosts'))
print("Wins:", data.get('winCount'), "Losses:", data.get('lossCount'))

closed_trades = data.get('closedTrades', [])
print(f"\nTotal Closed Trades: {len(closed_trades)}")
for idx, t in enumerate(closed_trades):
    print(f"{idx+1}. ID: {t.get('id')} | Contract: {t.get('contractSymbol')} | Entry: {t.get('entryPremium')} | Exit: {t.get('exitPremium')} | Gross: {t.get('grossPnl')} | Net: {t.get('netPnl')} | Reason: {t.get('exitReason')} | ClosedAt: {t.get('closedAt')}")

open_positions = data.get('openPositions', [])
print(f"\nTotal Open Positions: {len(open_positions)}")
for idx, p in enumerate(open_positions):
    print(f"{idx+1}. ID: {p.get('id')} | Contract: {p.get('contractSymbol')} | Entry: {p.get('entryPremium')} | CMP: {p.get('currentPremium')} | Unrealized: {p.get('unrealizedGrossPnl')} | OpenedAt: {p.get('entryTimestamp')}")
