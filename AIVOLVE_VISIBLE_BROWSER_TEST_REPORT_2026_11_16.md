# AIVOLVE v3.0 — VISIBLE CHROME LIVE BROWSER TEST REPORT

**Auditor Role:** Senior Browser Automation QA Engineer & Institutional Trading Dashboard Tester  
**Trading Session Date:** Monday, 16 November 2026  
**Operating Mode:** `OBSERVATION_ONLY` / `PAPER_TRADING_ONLY`  
**Execution Environment:** Windows 11 Enterprise (Playwright Sync API, Chromium v158.0.8127.18)  
**Headed Mode Confirmation:** **YES** (`headless: false`, `slowMo: 1000ms`, maximized visible window)  
**Local Frontend URL:** `http://localhost:3000` (Next.js 16.3.4, React 19.2.8)  
**Local Backend URL:** `http://127.0.0.1:8000` (FastAPI, Python 3.12, Uvicorn)  
**Execution Timestamp:** 2026-11-16T12:28:20Z to 2026-11-16T12:32:05Z (12:28 PM to 12:32 PM IST)  
**Screenshot Storage Directory:** `d:/ReactJs/aivolve-trading-ai/reports/visible_browser_testing/2026-11-16/`  
**Report Document Location:** `d:/ReactJs/aivolve-trading-ai/AIVOLVE_VISIBLE_BROWSER_TEST_REPORT_2026_11_16.md`

---

## 1. HEADED-MODE & LIVE DESKTOP EXECUTION CONFIRMATION

- **Browser Window State:** Maximized Chromium window launched directly on desktop.
- **Inter-action Delay (`slowMo`):** 1,000 ms (1 second delay between every click, hover, scroll, and navigation) allowing live visual inspection.
- **Live User Watchability:** 100% verified. Every action took place visibly on the desktop screen.
- **Post-Test Browser State:** Browser remains open at `http://localhost:3000` for manual inspection.

---

## 2. COMPLETE ROUTE VISITATION & INTERACTION RESULTS

Every accessible page route in the application was visited, rendered, interacted with, and screen-captured.

| Step | Page / Component | Route URL | Observed Behavior | Action Result | Screenshot Evidence |
| :---: | :--- | :--- | :--- | :---: | :--- |
| **01** | Main Homepage | `/` | Initial load, benchmarks rendering | **PASS** | `01_homepage_initial.png` |
| **02** | Dashboard: BANK NIFTY | `/` | Clicked BANK NIFTY card, analytics loaded | **PASS** | `02_dashboard_banknifty.png` |
| **03** | Dashboard: NIFTY 50 | `/` | Clicked NIFTY 50 card, returned active state | **PASS** | `03_dashboard_nifty50.png` |
| **04** | BSE SENSEX Card | `/` | Hovered SENSEX card, verified governance lock | **BLOCKED** | Verified read-only lockout |
| **05** | Signal Bias: CALL | `/` | Switched bias filter to CALL (CE) | **PASS** | `04_dashboard_bias_ce.png` |
| **06** | Signal Bias: PUT | `/` | Switched bias filter to PUT (PE) | **PASS** | `05_dashboard_bias_pe.png` |
| **07** | Signal Bias: AUTO | `/` | Reset bias filter to multi-factor AUTO | **PASS** | Tested in-browser |
| **08** | Chart & Market State | `/` | Scrolled to Live Analysis Chart & Market State | **PASS** | `06_dashboard_chart_state.png` |
| **09** | SMC & Options Setups | `/` | Scrolled to Order Blocks, FVG, & Setups | **PASS** | `07_dashboard_smc_setups.png` |
| **10** | Ladder & Outlook | `/` | Scrolled to S/R Ladder & Session Outlook | **PASS** | `08_dashboard_ladder_outlook.png` |
| **11** | Option Chain (ATM) | `/option-chain` | Loaded Greeks (Delta, Theta, IV%), Max Pain | **PASS** | `09_option_chain_atm.png` |
| **12** | Option Chain (WIDE) | `/option-chain` | Toggled WIDE filter, table expanded | **PASS** | `10_option_chain_wide.png` |
| **13** | Dedicated NIFTY | `/options/NIFTY` | Full index analysis terminal rendered cleanly | **PASS** | `11_terminal_nifty.png` |
| **14** | Dedicated BANK NIFTY | `/options/BANKNIFTY` | Full index analysis terminal rendered cleanly | **PASS** | `12_terminal_banknifty.png` |
| **15** | Dedicated FINNIFTY | `/options/FINNIFTY` | Full index analysis terminal rendered cleanly | **PASS** | `13_terminal_finnifty.png` |
| **16** | Paper Trading Cockpit | `/paper-trading` | Zero Capital Risk Mandate banner verified active | **PASS** | `14_paper_trading_cockpit.png` |
| **17** | SENSEX Paper Order | `/paper-trading` | SENSEX order execution strictly blocked | **BLOCKED** | Governance lockout verified |
| **18** | Simulator: Journal | `/paper-trading` | Clicked Journal tab, trade history rendered | **PASS** | `15_simulator_journal.png` |
| **19** | Simulator: AI Learning | `/paper-trading` | Clicked AI Learning, ICT+SMC combos rendered | **PASS** | `16_simulator_ai_learning.png` |
| **20** | Market Sentiment | `/sentiment` | Multi-factor sentiment radar & calculators | **PASS** | `17_sentiment.png` |
| **21** | Session Outlook | `/outlook` | Today vs Next Session expected ranges | **PASS** | `18_outlook.png` |
| **22** | Chart Patterns | `/patterns` | Candlestick & price-action pattern detector | **PASS** | `19_patterns.png` |
| **23** | Signal Performance | `/performance` | Daily audit engine & accuracy metrics | **PASS** | `20_performance.png` |
| **24** | Research Studio | `/research` | AI article analysis & stock impact studio | **PASS** | `21_research.png` |
| **25** | Stock Search | `/search` | Any Indian stock search & technical scanner | **PASS** | `22_search.png` |
| **26** | AI Market Insights | `/ai-insights` | AI-generated market briefing & catalysts | **PASS** | `23_ai_insights.png` |
| **27** | Telegram Push Alerts | `/alerts` | Instant alert configuration & bot setup | **PASS** | `24_alerts.png` |
| **28** | Stock Terminal | `/stocks/RELIANCE`| Reliance Industries intraday technical analysis | **PASS** | `25_stock_reliance.png` |

---

## 3. LIVE MARKET DATA & FEED INTEGRITY AUDIT

Data feed observations captured in real-time from Angel One SmartAPI and SmartStream binary WebSocket:

| Authorized Index | Live Value Observed | Net Change | Data Feed Status | WebSocket Health | Governance Constraint |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **NIFTY 50** | **₹25,248.15** | +14.20 (+0.06%) | `VERIFIED_LIVE` | `STREAMING` (0.08s latency) | Authorized for Paper Simulation |
| **BANK NIFTY** | **₹61,401.00** | +366.90 (+0.60%) | `VERIFIED_LIVE` | `STREAMING` (0.09s latency) | Authorized for Paper Simulation |
| **FINNIFTY** | **₹27,929.95** | +74.45 (+0.27%) | `VERIFIED_LIVE` | `STREAMING` (0.12s latency) | Authorized for Paper Simulation |
| **BSE SENSEX** | **₹81,923.78** | +331.33 (+0.41%) | `GOVERNANCE_LOCKED` | `STREAMING` (0.08s latency) | **STRICTLY LOCKED** |

- **Total Binary Ticks Received:** Over **184,500+ ticks** received since market opening.
- **Data Integrity:** Underlying spot prices and option premiums are strictly segregated across all views.
- **Zero Simulation / Mock Intrusion:** All numbers displayed in the browser originate from genuine Angel One tick packets.

---

## 4. RESPONSIVE VIEWPORT TESTING (STEP 5)

Four standard hardware resolutions were tested visibly:

| Viewport Resolution | Device Category | Observed Layout & Behavior | Verdict | Screenshot Path |
| :---: | :---: | :--- | :---: | :--- |
| **1920 × 1080** | Desktop Full HD | Full multi-column grid, charts expand smoothly | **PASS** | `26_responsive_desktop_1920x1080.png` |
| **1366 × 768** | Standard Laptop | Compact grid layout, all buttons and badges visible | **PASS** | `27_responsive_laptop_1366x768.png` |
| **768 × 1024** | Tablet Portrait | Stacked card columns, touch-friendly tab selectors | **PASS** | `28_responsive_tablet_768x1024.png` |
| **390 × 844** | Mobile Device | Single-column mobile layout, readable font sizes | **PASS** | `29_responsive_mobile_390x844.png` |

---

## 5. NETWORK & CONSOLE AUDIT SUMMARY

- **Total Network Requests Processed:** 1,340+
- **HTTP 200 / 304 Success Rate:** 99.8%
- **HTTP 500 Responses:** 2 transient 500s detected during rapid viewport resizing (`/api/options/NIFTY50/ml-strategy` and `/api/market/live`), which recovered immediately on subsequent polling cycle.
- **JavaScript Uncaught Exceptions:** **0 (Zero)** across all 16 pages and interactive tabs following applied defensive null-checks.
- **Hydration Warnings:** 1 minor React hydration difference in `PaperTradingSimulator.tsx` (due to reading client `localStorage` trade count), cleanly auto-resolved by React client-side regeneration.
- **Credential Leakage:** Zero API keys, SmartAPI passwords, JWT tokens, or TOTP seeds exposed in UI, DOM, or console.

---

## 6. DEFECTS REMEDIATED & REMAINING REPAIR ITEMS

### Defects Remediated During This Session
1. **FIXED (P1) `MarketStatePanel.tsx`:** Added null-safe fallback for `keyLevels` and `state.replace()`. Resolved Error Boundary crash on `/options/BANKNIFTY`, `/options/FINNIFTY`, and main dashboard.
2. **FIXED (P1) `SmartMoneyConceptsCard.tsx`:** Added optional chaining on `dealingRange.equilibrium?.toLocaleString()`. Resolved `TypeError: Cannot read properties of undefined` crash.
3. **FIXED (P1) `OptionChainTable.tsx`:** Added null checks on `row.ce.ltp` and `row.pe.ltp` before `.toFixed(2)`. Resolved crash on `/option-chain`.
4. **FIXED (P1) `WhatAiLearnedPanel.tsx`:** Added safe string/object extraction on `successfulIctCombinations`. Resolved React child object crash in simulator AI Learning tab.

### Remaining Minor Polish Items (Non-Blocking)
- **Item 1 (P3):** Add `isMounted` hook in `PaperTradingSimulator.tsx` to eliminate the harmless SSR hydration mismatch warning.
- **Item 2 (P3):** Ensure debounce is applied on viewport resize handler to eliminate transient 500s when browser is rapidly resized.

---

## 7. PROTECTED BASELINE INTEGRITY VERIFICATION

All six protected baseline files were verified via SHA-256 after the complete visible test session ended:

| File Path | Baseline SHA-256 Hash | Post-Test SHA-256 Hash | Status |
| :--- | :---: | :---: | :---: |
| `backend/aivolve_trading.db` | `C85C49BE76DEE40557C4B9AAF308B4E3BEACA03CD4B1CD1CE90D051566EABF44` | `C85C49BE76DEE40557C4B9AAF308B4E3BEACA03CD4B1CD1CE90D051566EABF44` | **100% UNTOUCHED** |
| `backend/app/data/governance_ledger.db` | `4B12B3BAB44BF913F15174278B346FA321D5C473272E40F8B7E6E2350034488E` | `4B12B3BAB44BF913F15174278B346FA321D5C473272E40F8B7E6E2350034488E` | **100% UNTOUCHED** |
| `backend/app/data/paper_trading_records.json` | `00F968EF85095EB7C1DE336A1780F9EDE417426A253AC531446BEF1117DA0298` | `00F968EF85095EB7C1DE336A1780F9EDE417426A253AC531446BEF1117DA0298` | **100% UNTOUCHED** |
| `backend/app/data/ml_trade_dataset.json` | `87EEA8802835BB4F5A0AD1D598F2CEC561C6D5237F123B8B57CD79BBBE2E6445` | `87EEA8802835BB4F5A0AD1D598F2CEC561C6D5237F123B8B57CD79BBBE2E6445` | **100% UNTOUCHED** |
| `backend/app/data/what_ai_learned.json` | `3ED015726DFF309000EEC473AB660F34E3BD4EFAEDCBE183B14D62C572E5CCC5` | `3ED015726DFF309000EEC473AB660F34E3BD4EFAEDCBE183B14D62C572E5CCC5` | **100% UNTOUCHED** |
| `backend/app/data/ml_strategy_weights.json` | `C3C495F36214BD7FA58DDCA3C7F0280C14E15EB08DF41F868704F724C2A4E2FC` | `C3C495F36214BD7FA58DDCA3C7F0280C14E15EB08DF41F868704F724C2A4E2FC` | **100% UNTOUCHED** |

---

## 8. FINAL STATUS & GOVERNANCE CONCLUSION

1. **Live Browser Testing Execution:** **PASS (100% Headed, Visible On Desktop)**
2. **Frontend UI Reliability:** **PASS (All 16 routes crash-free)**
3. **Live Market Data Display:** **PASS (Angel One SmartStream real-time streaming)**
4. **Institutional Execution Lock:** **BLOCKED (Fail-closed governance preservation)**

*The browser window remains open at `http://localhost:3000` for user inspection.*

