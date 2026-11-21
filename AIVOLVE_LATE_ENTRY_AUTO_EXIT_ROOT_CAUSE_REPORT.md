# AIVOLVE v3.0 — LATE SESSION ENTRY & AUTOMATIC EXIT SAFETY AUDIT
**Forensic Root-Cause Investigation, Schedule Reconciliation, and Mathematical Entry Cutoff Enforcement**

**Project**: `D:/ReactJs/aivolve-trading-ai`  
**Date**: 21 November 2026  
**Status**: APPROVED & FULLY REMEDIATED (44/44 Safety Tests Passing)  
**Governance Level**: Fail-Closed Institutional Quantitative Safety Policy  

---

## 1. EXECUTIVE SUMMARY & USER QUERY RESOLUTION

### User Query: *"isme aapne aap bik kyu jaraha hai"* (Why is it getting sold automatically?)
A paper trade position was opened at **15:09:23 IST** and automatically closed **37 seconds later at 15:10:00 IST**, causing confusion as to why the system "sold the position by itself":
- **Contract**: `NIFTY23NOV2625800CE`
- **Entry Premium**: ₹113.50 (Bought at 03:09:23 pm IST)
- **Reported Exit**: 15:10:00 IST (Automatic square-off)
- **Holding Time**: **37 seconds**

### The Actual Forensic Root Cause
1. **The Exit Was NOT a Bug or Erroneous Stop-Loss Trigger**:
   - The trade was NOT stopped out (`STOP_LOSS_HIT` was ₹102.30; market price was ₹115.85, which was in profit).
   - The exit was triggered by an automated **End-of-Day (EOD) Theta Protection Square-Off rule scheduled at 15:10 IST**. In options trading, holding long intraday options past 15:10 IST exposes capital to aggressive gamma collapse and institutional auction volatility.
2. **The Real Architectural Vulnerability Was a Missing Late-Session Entry Gate**:
   - The paper trading engine allowed new orders to open whenever `MarketCalendar.is_market_open()` was True (09:15 to 15:30 IST).
   - It possessed **no late-session entry cutoff gate**.
   - As a result, the user interface allowed buying an option at **15:09:23 IST**—just **37 seconds** before the system's scheduled **15:10:00 IST EOD square-off**!
3. **Status Masking in Legacy Code**:
   - In `close_position()`, exits with reasons containing `"eod"` or `"square_off"` had been defaulting to `MANUALLY_CLOSED`, masking the automated schedule nature from the operator journal.

---

## 2. LIFECYCLE TRACE OF TARGET TRADE (`NIFTY23NOV2625800CE`)

| Field | Forensic Value | Governance Verification |
| :--- | :--- | :--- |
| **Contract Symbol** | `NIFTY23NOV2625800CE` | Verified NSE NIFTY Weekly Option |
| **Strike & Bias** | 25800 CE | Call Setup Active |
| **Entry Timestamp** | `15:09:23 IST` (03:09:23 pm) | Verified from User Screenshot |
| **Entry Premium** | ₹113.50 | Ask-calibrated Entry Zone |
| **Stop Loss** | ₹102.30 (-11.2 pts / -9.9%) | Active Capital Protection |
| **Target 1 (+30%)** | ₹150.61 (82% probability) | Intended Horizon: 30–45 mins |
| **Target 2 (+55%)** | ₹173.20 (54% probability) | Intended Horizon: 45–75 mins |
| **Live CMP at Screenshot** | ₹115.85 (+₹152.75 / +2.1%) | Position was in floating profit |
| **Exit Trigger Timestamp** | `15:10:00 IST` | Mandatory EOD Square-Off Trigger |
| **Effective Holding Window** | **37 seconds** | **Grossly Insufficient Runway** |
| **Actual Exit Reason** | `EOD Square-Off (15:10 IST Theta Protection)` | Scheduled EOD Capital Defense |

---

## 3. COMPREHENSIVE SCHEDULE AUDIT & TIMING INCONSISTENCIES

An audit of all scheduling rules across the repository revealed severe timing mismatches between strategy expectations and execution schedules:

```mermaid
flowchart TD
    subgraph Market Timeline (IST)
        A["09:15 IST<br/>Market Open"] --> B["14:15 IST<br/>Kill Zone Closing Window"]
        B --> C["14:50 IST<br/>NEW ENTRY CUTOFF (Enforced)"]
        C --> D["15:10 IST<br/>Mandatory EOD Square-Off"]
        D --> E["15:25 IST<br/>Research Job Square-Off"]
        E --> F["15:30 IST<br/>Exchange Cash Close"]
    end

    subgraph Strategy Horizon
        G["OptionRiskEngine Target 1:<br/>Requires 30 - 45 mins holding"]
        H["Late Entry at 15:09:23 IST:<br/>Only 37 seconds remaining!"]
    end

    H -.->|Clashes with| D
    G -.->|Violated by| H
```

### Inconsistency Table

| Subsystem | File Path | Existing Schedule / Horizon | Conflict / Gap |
| :--- | :--- | :--- | :--- |
| **Market Calendar** | `app/data/market_calendar.py` | 09:15 to 15:30 IST | Lacked any late-session cutoff. |
| **Option Risk Engine** | `app/options/option_risk_engine.py` | T1: 30–45m, T2: 45–75m, SL: 30m | Required minimum 30 min runway. |
| **Session Engine** | `app/options/session_engine.py` | `KZ_CLOSING_SQUAREOFF`: 14:15–15:30 | Identified closing window, but did not gate paper entry. |
| **Policy G / Shadow Daemon** | `app/options/paper_trading/shadow_forward_pipeline.py` | Tier 4 EOD Square-Off: **15:10 IST** | Forcibly squares off all open options at 15:10 IST. |
| **Research Paper Job** | `app/jobs/research_paper_job.py` | EOD Square-off: **15:25 IST** | Discrepancy with 15:10 IST rule. |
| **Paper Trading Engine** | `paper_engine.py` | Allowed orders until 15:30:00 IST | **Zero entry cutoff prior to market close.** |

---

## 4. MATHEMATICAL FORMULATION OF THE NEW ENTRY CUTOFF GATE

To prevent positions from opening without sufficient runway to reach Target 1 before mandatory square-off, we implemented a deterministic, configurable gate:

$$\text{Mandatory EOD Square-Off Time} = \mathbf{15:10\text{ IST}}$$
$$\text{Configured Minimum Holding Window} = \mathbf{20.0\text{ minutes}}$$
$$\text{Enforced Entry Cutoff Time} = 15:10\text{ IST} - 20\text{ minutes} = \mathbf{14:50\text{ IST}}$$

### Decision Matrix

| Order Submission Time (IST) | Remaining Time to 15:10 EOD | Engine Decision | HTTP / Code Response |
| :--- | :--- | :--- | :--- |
| **14:40:00 IST** | 30.0 minutes | **ADMITTED** | `success: True` |
| **14:49:59 IST** | 20.01 minutes | **ADMITTED** | `success: True` |
| **14:50:00 IST** | 20.0 minutes | **REJECTED** | `INSUFFICIENT_HOLDING_TIME_BEFORE_EOD_SQUAREOFF` |
| **15:09:23 IST** (User Case) | 0.62 minutes (37s) | **REJECTED** | `INSUFFICIENT_HOLDING_TIME_BEFORE_EOD_SQUAREOFF` |
| **15:15:00 IST** | Past EOD | **REJECTED** | `INSUFFICIENT_HOLDING_TIME_BEFORE_EOD_SQUAREOFF` |
| **15:31:00 IST** | Exchange Closed | **REJECTED** | `marketStatus: CLOSED` |

> [!IMPORTANT]
> **Sandbox / Replay Simulation Bypass**: For historical walk-forward backtesting, research replay, and unit tests, passing `market_features={"allowAfterHoursSimulation": True}` or `"isReplay": True` cleanly bypasses the live cutoff check so researchers can test setup execution at any timestamp.

---

## 5. ARCHITECTURAL FIXES IMPLEMENTED

### A. Backend Engine Hardening (`backend/app/options/paper_trading/paper_engine.py`)
1. **Configurable Cutoff State**:
   ```python
   self.session_cutoff_config = {
       "enabled": True,
       "min_holding_window_minutes": 20.0,
       "eod_square_off_time": "15:10",
       "exchange_market_close": "15:30",
       "enforce_eod_squareoff": True,
   }
   ```
2. **Session Cutoff Gate in `open_position()`**:
   Evaluates `get_session_cutoff_status(eval_dt)`. Rejects entries at or after 14:50 IST with code `INSUFFICIENT_HOLDING_TIME_BEFORE_EOD_SQUAREOFF`.
3. **Automated EOD Exit in `update_live_monitoring()`**:
   Detects when quote timestamp reaches/exceeds 15:10 IST. Closes open positions with reason `EOD Square-Off (15:10 IST Theta Protection)`.
4. **Official Status Classification in `close_position()`**:
   - `EOD_SQUARE_OFF`: When exit reason contains `"eod"`, `"square_off"`, `"session_end"`.
   - `TIME_DECAY_EXIT`: When exit reason contains `"theta"`, `"time_decay"`.
   - `STOP_LOSS_HIT`: Stop loss executions.
   - `TARGET_1_HIT` / `TARGET_2_HIT`: Profit target hits.
5. **Execution Realism & Non-Fabricated Timestamp Separation**:
   - `lastVerifiedQuoteTimestamp`: Timestamp of the last genuine exchange tick.
   - `fillTimestamp`: Exact simulation execution timestamp.
   - `ledgerCleanupTimestamp`: Host server post-market ledger write timestamp.

### B. REST API Endpoints (`backend/app/api/routes/paper_trading.py`)
- `GET /api/paper-trading/session-cutoff`: Returns live cutoff status, remaining minutes, and schedule.
- `POST /api/paper-trading/session-cutoff/configure`: Allows authorized operators to configure holding window and square-off time.

### C. Frontend Service & UI Guardrails
1. **`paperTradingService.ts`**:
   - Pre-validates IST clock before sending admission request.
   - Returns client-side error if attempting to open new positions after 14:50 IST.
2. **`SignalActivationPanel.tsx`**:
   - Displays a prominent amber warning banner after 14:50 IST:
     > ⚠️ **SESSION ENTRY CUTOFF ACTIVE (14:50 IST)**: New paper entries are blocked to prevent premature automatic EOD square-off (15:10 IST). Minimum 20-minute holding window enforced.
   - Disables `Kharido / Buy 1 Lot @ Live CMP` and `Buy @ Entry Zone` buttons after 14:50 IST with descriptive disabled tooltips.
3. **`PaperTradingSimulator.tsx`**:
   - Completed Trades Journal displays dedicated badges for `EOD SQUARE-OFF` (amber) and `THETA EXIT` (purple), eliminating ambiguity.

---

## 6. STOP-LOSS & TARGET 1 VERIFICATION

### Stop-Loss Protection Remains 100% Active
Under no circumstances are protective exits disabled to prevent premature selling. Existing open positions remain fully protected:
- If premium drops to or below ₹102.30 at any point during market hours, `STOP_LOSS_HIT` triggers immediately.
- Slippage below stop-loss is realistically modeled using $\min(\text{ltp}, \text{low}, \text{sl})$.

### Target 1 Logic Differentiation
- **Single-Lot Positions (`lots == 1`)**:
  Reaching Target 1 auto-trails stop-loss to entry cost (₹113.50), converting the trade into a **risk-free runner** for Target 2. The position is NOT liquidated at T1.
- **Multi-Lot Positions (`lots > 1`)**:
  Reaching Target 1 executes an automatic **50% partial exit** (booking profit), and trails the stop-loss on remaining lots to cost.

---

## 7. TEST & VERIFICATION RESULTS

### Test Suite Execution Summary
All 44 automated tests across the trading platform passed with 0 errors:

| Test Suite File | Tests | Status | Scope |
| :--- | :---: | :---: | :--- |
| `test_late_session_entry_and_auto_exit.py` | **12** | **PASSED** | Cutoff math, 14:40 entry, 14:49 entry, 14:50 cutoff reject, 15:09 reject, SL active, EOD square-off badge, T1 single/multi lot |
| `test_duplicate_prevention_and_safety.py` | **13** | **PASSED** | Concurrency, idempotency, duplicate strikes, cooldowns, timestamp separation |
| `test_shadow_forward_pipeline.py` | **7** | **PASSED** | Read-only observation pipeline, quota management, zero open position dependence |
| `test_independent_profit_validation.py` | **7** | **PASSED** | Empirical walk-forward, provenance audit, slippage/cost realism |
| `test_paper_trading_engine.py` | **5** | **PASSED** | Cost calculator, lifecycle, AI evaluator, ML feedback |
| **Total** | **44** | **100% PASSED** | Full regression and safety verification |

### Frontend TypeScript Verification
- Executed `npx.cmd tsc --noEmit`
- Result: **0 errors**, strict typecheck clean.

### Baseline Data Integrity Audit
All 4 protected baseline files verified via SHA-256 hash checks and remain 100% pristine:
- `backend/app/data/paper_trading_records.json`: `69c7f386f9a209b3806d33f3cd8d6f89d4150a576abdafa702db77aa365309c8` (UNTOUCHED)
- `backend/app/data/daily_post_market_reviews/review_2026-11-19.json`: `3229109910faa9ca9642f54e8bc78647e013046d94e73f729a03bf537efcb4b3` (UNTOUCHED)
- `backend/app/data/daily_post_market_reviews/review_2026-11-20.json`: `f6f8b83888f84325f381c82581bfb0962b6302f6b9f3996333d591445bea631a` (UNTOUCHED)
- `aivolve_trading.db`: `8870d868aa300a7ebc0c51b5f820d8a7c467e3c33f2634edd1d7329afdff519f` (UNTOUCHED)

---

## 8. SUMMARY FOR OPERATORS & USERS

1. **Why your trade sold automatically**:
   The trade was opened at 03:09:23 PM. The system has a strict rule to close all intraday option buys at 03:10:00 PM to protect against late-market theta decay and auction crashes. Because it was entered with only 37 seconds left, it got squared off as soon as the clock hit 03:10 PM.
2. **What has been fixed**:
   The system now **stops you from buying after 02:50 PM IST**. The buy buttons will be disabled with a clear warning explaining that there is not enough time left before the 03:10 PM automatic square-off.
3. **Stop losses are still safe**:
   Your protective stop-losses remain fully armed and will continue to protect your capital at all times.
