import asyncio
import os
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from app.options.paper_trading.paper_engine import paper_engine

def run_test():
    print("=== 1. CHECK INITIAL PORTFOLIO ===")
    p0 = paper_engine.get_dashboard_metrics()
    print(f"Current Balance: ₹{p0['currentBalance']:,.2f}")
    print(f"Total Closed Trades: {p0['totalPaperTrades']}")
    print(f"Open Positions Count: {p0['openTradesCount']}")
    
    print("\n=== 2. OPEN SIMULATED PAPER TRADE (PUT SETUP) ===")
    # NIFTY 24550 PE
    res_open = paper_engine.open_position(
        instrument="NIFTY 50",
        contract_symbol="NIFTY06NOV2624550PE",
        bias="PE",
        strike=24550.0,
        expiry="06NOV2026",
        entry_premium=120.50,
        position_type="BUY",
        lots=1,
        lot_size=65,
        stop_loss=102.50,
        target_1=156.60,
        target_2=186.70,
        target_3=222.90,
        strategy="Model B (Bearish Supply Rejection & Retest)",
        ict_setup="Bearish BSL Liquidity Sweep at High + FVG Displacement",
        market_features={"marketState": "BEARISH", "dropAtr": 3.05, "pcr": 0.97}
    )
    print("Open Success:", res_open.get("success"))
    print("Open Message:", res_open.get("message"))
    pos = res_open.get("position", {})
    pos_id = pos.get("id")
    contract_sym = pos.get("contractSymbol")
    print(f"Active Position ID: {pos_id} | Contract: {contract_sym} | Entry: ₹{pos.get('entryPremium')}")
    
    print("\n=== 3. UPDATE MFE / MAE ON ACTIVE POSITION ===")
    # Simulate price moving towards Target 1 (e.g. Premium rallies from 120.50 to 148.00)
    mon = paper_engine.update_live_monitoring(
        contract_symbol=contract_sym,
        current_ltp=148.00,
        bar_high=150.00,
        bar_low=119.00
    )
    if mon:
        print(f"Live Premium: ₹{mon.get('currentPremium')} | Rem Qty: {mon.get('remainingQuantity')}")
        print(f"Max Favorable Excursion (MFE): +₹{mon.get('mfeRupees'):,.2f} (+{mon.get('mfePts')} pts)")
        print(f"Max Adverse Excursion (MAE): ₹{mon.get('maeRupees'):,.2f} (-{mon.get('maePts')} pts)")
    
    print("\n=== 4. CLOSE SIMULATED POSITION AT PROFIT (TARGET 1 REACHED) ===")
    res_close = paper_engine.close_position(
        position_id=pos_id,
        exit_price=156.60,
        exit_reason="Target 1 Hit (+30% gain booked)"
    )
    print("Close Success:", res_close.get("success"))
    print("Close Message:", res_close.get("message"))
    closed_pos = res_close.get("trade", {})
    print(f"Gross P&L: ₹{closed_pos.get('grossPnl', 0):,.2f}")
    print(f"Net P&L (after SEBI/STT/GST charges): ₹{closed_pos.get('netPnl', 0):,.2f}")
    print(f"Total Trading Costs: ₹{closed_pos.get('totalCosts', 0):,.2f}")
    
    ai_eval = res_close.get("aiEvaluation")
    if ai_eval:
        print(f"AI Post-Trade Score: {ai_eval.get('overallScore')}/100")
        print(f"AI Grade: {ai_eval.get('grade')}")
        print(f"AI Summary: {ai_eval.get('aiSummary')}")
    
    print("\n=== 5. CHECK UPDATED PORTFOLIO METRICS ===")
    p2 = paper_engine.get_dashboard_metrics()
    print(f"Updated Balance: ₹{p2['currentBalance']:,.2f}")
    print(f"Net Realized P&L: ₹{p2['netPnl']:,.2f}")
    print(f"Win Rate: {p2['winRate']}%")
    print(f"Profit Factor: {p2['profitFactor']}")
    print(f"Total Closed Trades: {p2['totalPaperTrades']}")

if __name__ == '__main__':
    run_test()
