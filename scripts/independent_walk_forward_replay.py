import json
import math
import os
import sys

# Ensure backend in path
sys.path.insert(0, os.path.abspath("backend"))

from app.options.paper_trading.cost_calculator import IndianDerivativesCostCalculator
from app.options.paper_trading.profit_protection_research import (
    ProfitProtectionResearchEngine,
    ProfitProtectionPolicy,
    OptionTick,
    TradeSimulationResult
)

def run_independent_audit():
    print("================================================================================")
    print("AIVOLVE v3.0 — INDEPENDENT PROFIT PROTECTION VALIDATION & DATA AUDIT")
    print("================================================================================")

    # 1. TASK 1: DATA PROVENANCE AUDIT OF P1 BENCHMARK (profit_protection_research.py)
    print("\n--- TASK 1: AUDITING P1 BENCHMARK (profit_protection_research.py) ---")
    p1_results = ProfitProtectionResearchEngine.run_walk_forward_benchmark()
    p1_oos = p1_results["outOfSampleEvaluation"]
    
    print("P1 Claimed OOS (25 Setups):")
    for pol_name in ["STATIC_A", "BREAKEVEN_B", "ATR_TRAILING_C", "HYBRID_G"]:
        m = p1_oos[pol_name]
        print(f"  {pol_name:15} | WR: {m['winRatePercent']:>5.1f}% | PF: {m['profitFactor']:>5.2f} | Exp: ₹{m['expectancy']:>7.2f} | Net: ₹{m['totalNetPnl']:>9.2f} | MaxDD: ₹{m['maxDrawdown']:>8.2f} | Premature: {m['prematureExitRate']:>5.1f}%")

    print("\nAudit of P1 Data Generation Mechanism:")
    print("  Source Function: ProfitProtectionResearchEngine.run_walk_forward_benchmark._synthesize_ticks()")
    print("  Methodology: Synthetic parametric linear interpolation (8 up-ticks to MFE, 6 down-ticks to MAE/Retracement).")
    print("  Finding: 100% of the 25 OOS setups in the P1 benchmark were generated via synthetic tick models, NOT raw exchange order books.")
    print("  Conclusion: P1 benchmark demonstrates theoretical mathematical optimality under idealized linear paths, but CANNOT be cited as empirical exchange-proven validation.")

    # 2. TASK 2 & 3: INDEPENDENT REPLAY ON GENUINE HISTORICAL PAPER TRADES
    print("\n--- TASK 2 & 3: REPLAY ON GENUINE HISTORICAL DATA (paper_trading_records.json) ---")
    with open("backend/app/data/paper_trading_records.json", "r", encoding="utf-8") as f:
        ptr = json.load(f)
    
    closed_trades = ptr.get("closedTrades", [])
    print(f"Loaded {len(closed_trades)} genuine closed paper trades from verified ledger.")

    # Separate into In-Sample (18-19 Nov) and Out-Of-Sample (20 Nov)
    is_trades = []
    oos_trades = []
    for t in closed_trades:
        ts = t.get("entryTimestamp", "")
        if "20 Nov" in ts:
            oos_trades.append(t)
        else:
            is_trades.append(t)
            
    print(f"Sample Partitioning:")
    print(f"  In-Sample Calibration (18 Nov & 19 Nov): {len(is_trades)} trades")
    print(f"  Out-of-Sample Evaluation (20 Nov):        {len(oos_trades)} trades")

    # Evaluate Policies on Genuine Trades
    # For genuine trades, we know entryPremium, stopLoss, target1, target2, mfePts, maePts, lotSize, lots, quantity, and actual exit.
    def evaluate_trade_under_policies(trade):
        tid = trade.get("id")
        sym = trade.get("contractSymbol", "NIFTY")
        ep = float(trade.get("entryPremium", 100.0))
        sl = float(trade.get("initialStopLoss") or trade.get("stopLoss") or (ep - 12.0))
        t1 = float(trade.get("target1", ep * 1.30))
        t2 = float(trade.get("target2", ep * 1.55))
        mfe = float(trade.get("mfePts", 0.0))
        mae = float(trade.get("maePts", 0.0))
        lots = int(trade.get("initialLots") or trade.get("lots") or 1)
        lot_size = int(trade.get("lotSize", 65))
        qty = lots * lot_size
        actual_net = float(trade.get("netPnl", 0.0))
        actual_reason = trade.get("exitReason", "")
        actual_xp = float(trade.get("exitPremium", ep))
        
        # Build price path based on recorded MFE and MAE
        # Peak price = ep + mfe
        # Trough price = ep - mae
        # Final exit price = actual_xp
        peak = ep + mfe
        trough = ep - mae
        
        results = {}
        
        # Policy A: Static (Original)
        # Did it hit Target 2? Or Target 1? Or Stop Loss?
        # If actual trade exited via Target 2, Policy A got Target 2.
        # If actual trade was stopped out, Policy A got stopped out.
        # If it was manually closed, Policy A got actual_xp.
        results["STATIC_A"] = {
            "exitPrice": actual_xp,
            "netPnl": actual_net,
            "status": trade.get("status"),
            "exitReason": actual_reason,
        }
        
        # Policy B: Breakeven Stop (+1R / +15 pts MFE)
        # If mfe >= 12.0, SL moved to ep + 0.5.
        # Did price pull back below ep + 0.5 after hitting peak?
        # If actual trade finished with loss or manual close below ep + 0.5 and mfe >= 12.0:
        # Breakeven stopped it out at ep + 0.5 (fill at ep + 0.0 after 0.5 slippage)
        if mfe >= 12.0:
            if actual_xp < (ep + 0.5) or "Manual" in actual_reason or "Stop Loss" in actual_reason:
                b_xp = ep  # ep + 0.5 - 0.5 slippage
                b_costs = IndianDerivativesCostCalculator.calculate_trade_costs_and_pnl(
                    entry_price=ep, exit_price=b_xp, quantity=qty, position_type="BUY"
                )
                results["BREAKEVEN_B"] = {
                    "exitPrice": b_xp,
                    "netPnl": b_costs["netPnl"],
                    "status": "TRAILING_BE_HIT",
                    "exitReason": "Policy B Breakeven Hit",
                }
            else:
                results["BREAKEVEN_B"] = results["STATIC_A"]
        else:
            results["BREAKEVEN_B"] = results["STATIC_A"]
            
        # Policy C: ATR Trailing (Peak - 1.5 * ATR, approx 6.0 pts trail on NIFTY)
        # If mfe >= 6.0: candidate SL = peak - 6.0
        # If price reversed below candidate SL: fill at candidate SL - 0.5 slippage
        atr_trail = 6.0 if "NIFTY" in sym and "BANK" not in sym else 15.0
        if mfe >= atr_trail:
            cand_sl = peak - atr_trail
            if actual_xp <= cand_sl or actual_xp < peak:
                c_xp = round(cand_sl - 0.5, 2)
                c_costs = IndianDerivativesCostCalculator.calculate_trade_costs_and_pnl(
                    entry_price=ep, exit_price=c_xp, quantity=qty, position_type="BUY"
                )
                results["ATR_TRAILING_C"] = {
                    "exitPrice": c_xp,
                    "netPnl": c_costs["netPnl"],
                    "status": "ATR_TRAIL_HIT",
                    "exitReason": f"Policy C ATR Trail Hit @ ₹{cand_sl}",
                }
            else:
                results["ATR_TRAILING_C"] = results["STATIC_A"]
        else:
            results["ATR_TRAILING_C"] = results["STATIC_A"]

        # Policy G: Hybrid Multi-Tier (+1R BE -> +20 pt lock -> ATR trail)
        # Tier 1: mfe >= 12.0 -> SL = ep + 0.5
        # Tier 2: mfe >= 20.0 -> SL = ep + 10.0
        # Tier 3: mfe >= 20.0 and peak > ep + 20.0 -> SL = peak - 1.5 * atr
        g_sl = sl
        tier_label = "None"
        if mfe >= 20.0:
            tier_label = "Tier 2/3"
            trail_level = peak - atr_trail
            g_sl = max(ep + 10.0, trail_level)
        elif mfe >= 12.0:
            tier_label = "Tier 1"
            g_sl = ep + 0.5
            
        if g_sl > sl and actual_xp < g_sl:
            g_xp = round(g_sl - 0.5, 2)  # 0.5 pt slippage
            g_costs = IndianDerivativesCostCalculator.calculate_trade_costs_and_pnl(
                entry_price=ep, exit_price=g_xp, quantity=qty, position_type="BUY"
            )
            results["HYBRID_G"] = {
                "exitPrice": g_xp,
                "netPnl": g_costs["netPnl"],
                "status": f"HYBRID_{tier_label}_HIT",
                "exitReason": f"Policy G {tier_label} Protective Exit @ ₹{g_sl}",
            }
        else:
            results["HYBRID_G"] = results["STATIC_A"]
            
        return {
            "trade_id": tid,
            "symbol": sym,
            "entry": ep,
            "actual_exit": actual_xp,
            "mfe": mfe,
            "mae": mae,
            "qty": qty,
            "policies": results
        }

    # Run replay across IS and OOS
    def summarize_dataset(trades_list, label):
        print(f"\n=== SUMMARY FOR {label} ({len(trades_list)} TRADES) ===")
        replayed = [evaluate_trade_under_policies(t) for t in trades_list]
        
        summary = {}
        for pol in ["STATIC_A", "BREAKEVEN_B", "ATR_TRAILING_C", "HYBRID_G"]:
            net_pnls = [r["policies"][pol]["netPnl"] for r in replayed]
            wins = sum(1 for p in net_pnls if p > 0)
            losses = sum(1 for p in net_pnls if p <= 0)
            tot_win = sum(p for p in net_pnls if p > 0)
            tot_loss = abs(sum(p for p in net_pnls if p <= 0))
            tot_net = sum(net_pnls)
            pf = round(tot_win / max(1.0, tot_loss), 2)
            wr = round(wins / max(1, len(net_pnls)) * 100, 1)
            exp = round(tot_net / max(1, len(net_pnls)), 2)
            
            # Max DD
            equity = 0.0
            peak = 0.0
            max_dd = 0.0
            for p in net_pnls:
                equity += p
                if equity > peak:
                    peak = equity
                dd = peak - equity
                if dd > max_dd:
                    max_dd = dd
                    
            # 95% CI
            if len(net_pnls) > 1:
                var = sum((x - exp)**2 for x in net_pnls) / (len(net_pnls) - 1)
                se = math.sqrt(var / len(net_pnls))
                ci = [round(exp - 1.96 * se, 2), round(exp + 1.96 * se, 2)]
            else:
                ci = [exp, exp]
                
            summary[pol] = {
                "trades": len(net_pnls),
                "winRate": wr,
                "profitFactor": pf,
                "expectancy": exp,
                "totalNet": round(tot_net, 2),
                "maxDrawdown": round(max_dd, 2),
                "ci95": ci,
                "wins": wins,
                "losses": losses
            }
            print(f"  {pol:15} | WR: {wr:>5.1f}% ({wins}W/{losses}L) | PF: {pf:>5.2f} | Exp: ₹{exp:>7.2f} | Net: ₹{tot_net:>9.2f} | MaxDD: ₹{max_dd:>8.2f} | 95% CI: [{ci[0]}, {ci[1]}]")
            
        return summary, replayed

    is_sum, is_replayed = summarize_dataset(is_trades, "IN-SAMPLE (18 & 19 NOV 2026)")
    oos_sum, oos_replayed = summarize_dataset(oos_trades, "OUT-OF-SAMPLE (20 NOV 2026)")
    all_sum, all_replayed = summarize_dataset(closed_trades, "FULL HISTORICAL SAMPLE (23 TRADES)")

    print("\n--- FORENSIC DETAIL ON 20 NOVEMBER TARGET TRADES ---")
    for r in oos_replayed:
        tid = r["trade_id"]
        sym = r["symbol"]
        ep = r["entry"]
        mfe = r["mfe"]
        p_a = r["policies"]["STATIC_A"]["netPnl"]
        p_g = r["policies"]["HYBRID_G"]["netPnl"]
        g_reason = r["policies"]["HYBRID_G"]["exitReason"]
        diff = round(p_g - p_a, 2)
        print(f"  {tid} | {sym:22} | Entry: ₹{ep:>6.2f} | MFE: +{mfe:>4.1f} | Policy A: ₹{p_a:>8.2f} | Policy G: ₹{p_g:>8.2f} (Delta: +₹{diff:>7.2f}) | {g_reason}")

if __name__ == "__main__":
    run_independent_audit()
