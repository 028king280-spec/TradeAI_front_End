import json

with open("d:/ReactJs/aivolve-trading-ai/backend/app/data/paper_trading_records.json", "r") as f:
    data = json.load(f)

closed = data.get("closedTrades", [])
target_ids = ["PT-87BAC4A8", "PT-B43E2C4B", "PT-FBEA215F", "PT-8F92618C", "PT-D8D780EB", "PT-21E1FBA1"]

print("="*80)
for t in closed:
    if t["id"] in target_ids:
        print(f"TRADE ID: {t['id']}")
        print(f"Contract: {t.get('contractSymbol')} (Strike: {t.get('strike')}, Bias: {t.get('bias')})")
        print(f"Entry: {t.get('entryTimestamp')} @ Rs {t.get('entryPremium')}")
        print(f"Exit: {t.get('exitTimestamp')} @ Rs {t.get('exitPremium')}")
        print(f"SL: {t.get('stopLoss')} | T1: {t.get('target1')} | T2: {t.get('target2')} | T3: {t.get('target3')}")
        print(f"Exit Reason: {t.get('exitReason')} | Status: {t.get('status')}")
        print(f"Gross PnL: Rs {t.get('grossPnl')} | Net PnL: Rs {t.get('netPnl')}")
        print(f"MFE: {t.get('mfePts')} pts (Rs {t.get('mfeRupees')}) | MAE: {t.get('maePts')} pts (Rs {t.get('maeRupees')})")
        print(f"Lowest Premium: Rs {t.get('lowestObservedPremium')} | Highest Premium: Rs {t.get('highestObservedPremium')}")
        print(f"Strategy: {t.get('strategy')} | ICT Setup: {t.get('ictSetup')}")
        print(f"Prediction ID: {t.get('predictionId')} | Signal ID: {t.get('signalId')}")
        print(f"Market Features: {t.get('marketFeaturesAtEntry')}")
        print("-" * 60)
