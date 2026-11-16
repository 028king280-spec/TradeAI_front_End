# AIVOLVE v3.0 — CE vs PE Comparative Performance Analysis

**Analysis Date:** 13 November 2026, 04:45 PM IST  
**Execution Policy:** STRICT `PAPER_TRADING_ONLY`  
**Data Repository:** `backend/app/data/paper_trading_records.json`  

---

## 1. Independent Metric Breakdown

Per strict institutional governance rules, trade distribution percentage is calculated strictly as:
$$\text{Trade Share \%} = \frac{\text{Eligible Trades Count}}{\text{Total Eligible Trades}} \times 100$$
Win rate is computed strictly on **closed trades only**. Under no circumstances is trade share equated to win probability.

| Performance Metric | CE (Call Options) | PE (Put Options) | Combined / Baseline |
| :--- | :---: | :---: | :---: |
| **Total Eligible Trades Taken** | 1 | 0 | 1 |
| **Trade Share (%)** | **100.0%** (1 / 1) | **0.0%** (0 / 1) | 100.0% |
| **Closed Trades** | 1 | 0 | 1 |
| **Winning Trades** | 1 | 0 | 1 |
| **Losing Trades** | 0 | 0 | 0 |
| **Win Rate (%)** | **100.0%** | **N/A (No Trades)** | 100.0% |
| **Gross Realized P&L** | +₹5,525.00 | ₹0.00 | +₹5,525.00 |
| **Total Trading Costs** | ₹149.75 | ₹0.00 | ₹149.75 |
| **Net Realized P&L** | **+₹5,375.25** | **₹0.00** | **+₹5,375.25** |
| **Average Profit per Trade** | +₹5,375.25 | ₹0.00 | +₹5,375.25 |
| **Average Loss per Trade** | ₹0.00 | ₹0.00 | ₹0.00 |
| **Profit Factor** | $\infty$ (No losses) | N/A | $\infty$ |
| **Average Holding Duration** | < 1 min | N/A | < 1 min |
| **Max Drawdown Experienced** | 0.0% | 0.0% | 0.0% |
| **Statistical Status** | **INSUFFICIENT_SAMPLE** | **NO_SAMPLE** | **INSUFFICIENT_SAMPLE** |

---

## 2. Comparative Findings & Analysis

1. **Trade Distribution:**
   - CE accounts for 100% of recorded paper activity.
   - PE accounts for 0% of recorded paper activity (**NO_SAMPLE**).
2. **Directional Performance:**
   - The single eligible setup triggered was an ICT Bullish Sell-Side Liquidity (SSL) Sweep followed by a 50% Fair Value Gap (FVG) retest, directing the execution engine exclusively into the CE contract (`NIFTY06NOV2624000CE`).
   - The CE trade successfully achieved both Target 1 (125.0) and Target 2 (160.0), netting +₹5,375.25.
3. **Statistical Sample Limitation:**
   - **Verdict:** `INSUFFICIENT_SAMPLE` for CE, `NO_SAMPLE` for PE.
   - With 0 PE trades and only 1 CE trade, it is statistically invalid to conclude that CE options structurally outperform PE options in the underlying strategy.
   - Minimum sample requirement for comparative hypothesis testing ($p < 0.05$): $\ge 30$ independent closed trades per side.
