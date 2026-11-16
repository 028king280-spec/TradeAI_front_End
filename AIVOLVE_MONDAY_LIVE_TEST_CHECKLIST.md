# AIVOLVE v3.0 — Monday Live Session Operational Checklist

**Target Session Date:** Monday, 16 November 2026  
**Session Hours:** 09:00 — 15:45 IST  
**Execution Lead:** Principal Quantitative Systems Architect & Trading Operations  
**Authorized Instruments:** NIFTY 50, BANK NIFTY, FINNIFTY  
**Locked Instruments:** SENSEX (`GOVERNANCE_LOCKED` / `UNCONFIGURED`)  
**Authorized Operating Mode:** `STRICTLY PAPER_TRADING_ONLY`  

---

## 1. Zero-Tolerance Safety Invariants

Before initiating the operational sequence, verify the five mandatory invariants:

- [ ] **1. Mode Enforcement:** Operating mode is strictly `PAPER_TRADING_ONLY`.
- [ ] **2. Zero Live Capital:** Real broker order routing is completely disabled. Capital at risk is exactly ₹0.00.
- [ ] **3. Zero Model Training:** ML training routines are gated (`NOT_EXECUTED`).
- [ ] **4. Strategy Weights Frozen:** `ml_strategy_weights.json` remains identical to baseline hash `C3C495F3...`.
- [ ] **5. Inactive Socket Guard:** A connected WebSocket lacking incoming ticks is strictly classified as `UNHEALTHY` / `DEGRADED`. Never treat an idle socket as healthy live streaming.

---

## 2. Minute-by-Minute Operational Timeline

### 08:45 — 09:00 IST: Pre-Session System Initialization
- [ ] **Step 0.1:** Verify developer workstation network connection and NTP time synchronization ($\Delta t < 200$ ms).
- [ ] **Step 0.2:** Launch Backend API Server:
  ```powershell
  cd d:\ReactJs\aivolve-trading-ai\backend
  .venv\Scripts\uvicorn app.main:app --port 8000 --reload
  ```
- [ ] **Step 0.3:** Launch Frontend Next.js Dashboard:
  ```powershell
  cd d:\ReactJs\aivolve-trading-ai
  npm run dev
  ```
- [ ] **Step 0.4:** Verify all 6 protected baseline hashes:
  ```powershell
  cd d:\ReactJs\aivolve-trading-ai\backend
  .venv\Scripts\python scratch/verify_baseline_hashes.py
  ```
  *(Must return `ALL_MATCH: True`)*.

---

### 09:00 — 09:14 IST: Preflight Authentication & Feed Qualification
- [ ] **Step 1.1:** Execute Angel One SmartAPI authentication:
  - Generate fresh JWT token using API Key, Client Code, Password, and TOTP.
  - Verify auth token expiration window ($\ge 8$ hours).
- [ ] **Step 1.2:** Refresh Instrument Master:
  - Download latest `OpenAPIScripMaster.json`.
  - Verify active weekly and monthly expiries for NIFTY, BANKNIFTY, FINNIFTY.
  - Confirm SENSEX remains `UNCONFIGURED`.
- [ ] **Step 1.3:** Connect SmartStream WebSocket Feed Handler:
  - Connect to Angel One binary WebSocket cluster.
  - Subscribe to underlying index spot feeds (NIFTY: `99926000`, BANKNIFTY: `99926009`, FINNIFTY: `99926037`).
- [ ] **Step 1.4:** Execute Preflight Health Audit:
  - Run preflight check via `MondayLiveSessionProtocol.run_preflight_audit()`.
  - Confirm exchange status returns `PRE_MARKET_QUALIFIED`.

---

### 09:15 — 09:30 IST: Market Opening & Independent Index Gating
- [ ] **Step 2.1:** At 09:15:00 IST, confirm exchange opening state:
  - Verify `MarketCalendar.is_market_open()` evaluates to `True`.
- [ ] **Step 2.2:** Verify actual incoming WebSocket ticks:
  - Ensure ticks arrive at $> 1$ tick/sec on NIFTY, BANKNIFTY, and FINNIFTY.
  - Verify feed latency ($< 1,000$ ms per tick).
- [ ] **Step 2.3:** Perform Independent Index Data Quality Gate:
  - **NIFTY 50:** Verify bid/ask spread $< 2.5\%$, score $\ge 70$, FeedStatus = `VERIFIED_LIVE`.
  - **BANK NIFTY:** Verify bid/ask spread $< 2.5\%$, score $\ge 70$, FeedStatus = `VERIFIED_LIVE`.
  - **FINNIFTY:** Verify bid/ask spread $< 2.5\%$, score $\ge 70$, FeedStatus = `VERIFIED_LIVE`.
  - *Note: If any single index fails quality checks, mark it `DEGRADED` and proceed only with healthy indices.*
- [ ] **Step 2.4:** Confirm Opening Range Breakout / Morning Session context:
  - First 15-minute candle forms (09:15–09:30 IST).
  - Incomplete candles strictly excluded from MTF and SMC calculations.

---

### 09:30 — 11:30 IST: Morning Session Active Observation
- [ ] **Step 3.1:** Engage Observation Engine:
  - Start continuous observation recording across verified indices.
  - Capture decision timestamps, features, market regime, and MTF confluence scores.
- [ ] **Step 3.2:** Deterministic Signal Classification:
  - Verify `SignalClassifier.classify()` outputs `BUY_CE`, `BUY_PE`, `WAIT`, or `NO_TRADE`.
  - If ICT score is missing, ensure it is recorded as `NOT_CALIBRATED` (no defaults fabricated).
- [ ] **Step 3.3:** Forward Horizon Tracking:
  - Ingest genuine option quotes at $t+5\text{m}$, $t+15\text{m}$, $t+30\text{m}$, and $t+60\text{m}$.
  - Enforce zero spot substitution: option outcomes must use genuine contract prices.
- [ ] **Step 3.4:** Paper Trading Execution Verification:
  - For qualifying signals, confirm `PaperTradingEngine` opens simulated positions.
  - Verify stop-loss and Target 1/2 calculations.
  - Ensure zero live orders are routed to Angel One.

---

### 11:30 — 13:30 IST: Midday Session Monitoring & Chop Filters
- [ ] **Step 4.1:** Verify regime transitions (detect range-bound consolidation).
- [ ] **Step 4.2:** Confirm `SignalClassifier` outputs `WAIT` during low-volume chop.
- [ ] **Step 4.3:** Monitor tick staleness:
  - If tick gap $> 15$ seconds, confirm FeedStatus transitions to `DEGRADED`.
  - If tick gap $> 60$ seconds, confirm FeedStatus transitions to `STALE` and trading halts.

---

### 13:30 — 15:15 IST: Afternoon Expansion & Trailing SL
- [ ] **Step 5.1:** European session opening overlap (13:30 IST).
- [ ] **Step 5.2:** Monitor open paper trading positions:
  - If Target 1 is hit: verify 50% partial exit is executed, SL trailed to breakeven.
  - If Stop-Loss is hit: verify immediate auto-exit with `STOP_LOSS_HIT`.
- [ ] **Step 5.3:** MFE / MAE tracking verified in real time on the `/paper-trading` UI dashboard.

---

### 15:15 — 15:30 IST: Intraday Close & Square-Off
- [ ] **Step 6.1:** 15:15 IST: Intraday paper trading entries halted (`SESSION_CLOSING`).
- [ ] **Step 6.2:** Auto square-off remaining open paper positions at 15:25 IST.
- [ ] **Step 6.3:** Reconcile all closed trades and verify SEBI statutory fee deductions.

---

### 15:35 — 16:00 IST: Post-Market Reconciliation & EOD Reporting
- [ ] **Step 7.1:** Execute EOD report generator:
  ```powershell
  cd d:\ReactJs\aivolve-trading-ai\backend
  .venv\Scripts\python -c "from app.options.paper_trading.monday_live_session_protocol import MondayLiveSessionProtocol; print(MondayLiveSessionProtocol.generate_eod_markdown_report())"
  ```
- [ ] **Step 7.2:** Verify generated observation dataset:
  - Inspect `backend/app/data/production_observations/live_session_observations.json`.
  - Confirm record counts, forward horizon completeness, and absence of NaN values.
- [ ] **Step 7.3:** Re-verify protected baseline hashes (all 6 must match).
- [ ] **Step 7.4:** Save and archive `AIVOLVE_MONDAY_LIVE_SESSION_REPORT_20261116.md`.

---

## 3. Emergency & Contingency Runbook

| Incident Scenario | Automated System Behavior | Operator Manual Action |
| :--- | :--- | :--- |
| **Angel One API Rate Limit (HTTP 429)** | Exponential backoff retry (1s, 2s, 4s). Feed set to `DEGRADED`. | Do not spam login. Wait for rate limit cool-off (60s). |
| **WebSocket Connection Drop** | Auto-reconnect up to 5 attempts. Feed set to `DATA_OFFLINE`. | Verify internet router. If broker server issue, wait for reconnect. |
| **Silent Stagnant Socket (No Ticks)** | DataQualityEngine flags `STALE_FEED` after 60s. Gating blocks orders. | Restart WebSocket stream client via `/api/health` panel. |
| **Freak Tick / Flash Spike** | Z-score anomaly filter detects $> 4\sigma$ outlier, flags `ANOMALOUS`. | Anomaly auto-quarantined. No manual intervention required. |
| **Corrupted / Inverted Spread** | `bid > ask` detected, score deducted, `isTradeQualified = False`. | Auto-sanitized. If persistent, index feed marked `DEGRADED`. |

