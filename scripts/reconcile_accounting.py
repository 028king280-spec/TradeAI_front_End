import json

json_path = 'd:\\ReactJs\\aivolve-trading-ai\\backend\\app\\data\\paper_trading_records.json'
with open(json_path, 'r', encoding='utf-8') as f:
    records = json.load(f)

closed = records.get('closedTrades', [])

# Trades executed on 20 Nov 2026 (Indices 1 to 11 in list)
trades_20nov = closed[:11]

print("=== 20 NOV TRADES AUDIT ===")
total_gross = 0.0
total_costs = 0.0
total_net = 0.0

for t in trades_20nov:
    tid = t.get('id')
    sym = t.get('contractSymbol')
    entry = t.get('entryPremium', 0.0)
    exit_p = t.get('exitPremium', 0.0)
    gross = t.get('grossPnl', 0.0)
    costs = t.get('totalCosts') or t.get('tradingCosts') or (gross - t.get('netPnl', gross))
    net = t.get('netPnl', 0.0)
    
    total_gross += gross
    total_costs += costs
    total_net += net
    print(f"{tid:12} | {sym:22} | Entry: {entry:6.2f} | Exit: {exit_p:6.2f} | Gross: {gross:+8.2f} | Costs: {costs:6.2f} | Net: {net:+8.2f} | Reason: {t.get('exitReason')}")

print("-" * 80)
print(f"SUM OF ALL 11 TRADES ON 20 NOV:")
print(f"Gross: Rs {total_gross:+0.2f}")
print(f"Costs: Rs {total_costs:0.2f}")
print(f"Net:   Rs {total_net:+0.2f}")

# What if we exclude PT-8E78B1DB (stale 06NOV contract)?
print("\n--- EXCLUDING PT-8E78B1DB (stale/legacy test) ---")
g10 = sum(t.get('grossPnl', 0.0) for t in trades_20nov[1:])
n10 = sum(t.get('netPnl', 0.0) for t in trades_20nov[1:])
c10 = sum((t.get('grossPnl', 0.0) - t.get('netPnl', 0.0)) for t in trades_20nov[1:])
print(f"Gross: Rs {g10:+0.2f} | Costs: Rs {c10:0.2f} | Net: Rs {n10:+0.2f}")

# What if we exclude PT-89B18A85 (stale BN test)?
trades_9 = [t for t in trades_20nov if t.get('id') not in ('PT-8E78B1DB', 'PT-89B18A85')]
g9 = sum(t.get('grossPnl', 0.0) for t in trades_9)
n9 = sum(t.get('netPnl', 0.0) for t in trades_9)
c9 = sum((t.get('grossPnl', 0.0) - t.get('netPnl', 0.0)) for t in trades_9)
print(f"\n--- EXCLUDING BOTH STALE TESTS (PT-8E78B1DB & PT-89B18A85) ---")
print(f"Gross: Rs {g9:+0.2f} | Costs: Rs {c9:0.2f} | Net: Rs {n9:+0.2f}")

print("\n--- CHECKING THE LISTED GROSS P&L: 3,945.50 ---")
# Where does 3,945.50 come from?
# 4749.25 - 803.75 = 3945.50!
# What trade or combination equals 803.75?
print(f"4749.25 - 3945.50 = {4749.25 - 3945.50}")
print(f"1849.42 - 1045.67 = {1849.42 - 1045.67}")
