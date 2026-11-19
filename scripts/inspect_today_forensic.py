import json
import sqlite3
import os

print("=== INSPECTING PAPER_TRADING_RECORDS.JSON ===")
records_path = "d:/ReactJs/aivolve-trading-ai/backend/app/data/paper_trading_records.json"
if os.path.exists(records_path):
    with open(records_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    closed = data.get("closedTrades", [])
    open_pos = data.get("openPositions", [])
    print(f"Total closed trades: {len(closed)}")
    print(f"Total open positions: {len(open_pos)}")
    print(f"Account Balance: {data.get('balance')}")
    print(f"Starting Balance: {data.get('startingBalance')}")
    
    print("\n--- DETAILS OF CLOSED TRADES ---")
    for idx, t in enumerate(closed):
        print(f"[{idx+1}] ID: {t.get('id')}")
        print(f"    Symbol: {t.get('contractSymbol')} (Token: {t.get('instrumentToken')})")
        print(f"    Instrument: {t.get('instrument')} | Bias: {t.get('bias')} | Strike: {t.get('strike')}")
        print(f"    Qty: {t.get('quantity')} | Lots: {t.get('lots')} | LotSize: {t.get('lotSize')}")
        print(f"    Entry: {t.get('entryPremium')} @ {t.get('entryTimestamp')}")
        print(f"    Exit: {t.get('exitPremium')} @ {t.get('exitTimestamp')}")
        print(f"    SL: {t.get('stopLoss')} | T1: {t.get('target1')} | T2: {t.get('target2')} | T3: {t.get('target3')}")
        print(f"    Status: {t.get('status')} | Exit Reason: {t.get('exitReason')}")
        print(f"    Gross PnL: {t.get('grossPnl')} | Realized Costs: {t.get('realizedCosts')} | Net PnL: {t.get('netPnl')}")
        print(f"    Strategy: {t.get('strategy')} | ICT Setup: {t.get('ictSetup')}")
        print(f"    MFE: {t.get('mfePts')} pts (₹{t.get('mfeRupees')}) | MAE: {t.get('maePts')} pts (₹{t.get('maeRupees')})")
        print(f"    Market Features: {t.get('marketFeaturesAtEntry', {})}")
        print(f"    Partial Exits: {t.get('partialExits', [])}")
        print("")

print("\n=== INSPECTING AIVOLVE_TRADING.DB RESEARCH TRADES ===")
db_path = "d:/ReactJs/aivolve-trading-ai/backend/aivolve_trading.db"
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT * FROM research_paper_trades WHERE opened_at LIKE '%2026-11-19%'")
    rows = cur.fetchall()
    print(f"Today research paper trades count: {len(rows)}")
    col_names = [d[0] for d in cur.description]
    for idx, r in enumerate(rows):
        row_dict = dict(zip(col_names, r))
        print(f"[{idx+1}] Research Trade ID: {row_dict['id']}")
        print(f"    Contract: {row_dict['contract_symbol']} (Token: {row_dict['instrument_token']})")
        print(f"    Qty: {row_dict['quantity']} | Opened: {row_dict['opened_at']} | Closed: {row_dict['closed_at']}")
        print(f"    Entry: {row_dict['entry_paise']/100.0} | Stop: {row_dict['stop_paise']/100.0} | Target: {row_dict['target_paise']/100.0} | Exit: {row_dict['exit_paise']/100.0 if row_dict['exit_paise'] else None}")
        print(f"    Exit Reason: {row_dict['exit_reason']} | Status: {row_dict['status']}")
        print(f"    Entry Fee: {row_dict['entry_fee_paise']/100.0} | Exit Fee: {row_dict['exit_fee_paise']/100.0 if row_dict['exit_fee_paise'] else 0.0}")
        print(f"    Net PnL: {row_dict['net_pnl_paise']/100.0 if row_dict['net_pnl_paise'] else 0.0}")
        print("")
    conn.close()
