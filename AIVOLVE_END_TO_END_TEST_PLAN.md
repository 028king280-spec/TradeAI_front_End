# AIVOLVE v3.0 — End-to-End Test Plan & Offline Validation Architecture

**Document Version:** 3.0.0  
**Phase:** Phase D — End-to-End Test Framework & Stress Testing  
**Applicability:** Full Pipeline Offline Verification & CI/CD Testing  
**Trading Mode:** `STRICTLY PAPER_TRADING_ONLY`  

---

## 1. Objectives & Scope

The **AIVOLVE End-to-End Test Framework** provides an automated, deterministic, offline verification harness simulating every component of the autonomous trading lifecycle.

By replacing external network calls with mathematically controlled synthetic fixtures, the test plan ensures complete determinism while subjecting the trading logic, risk boundaries, data sanity filters, and accounting engines to severe edge cases and stress conditions.

### Core Testing Mandates
1. **Zero External Dependencies:** Every test must run cleanly offline on local developer machines or CI/CD without requiring live broker credentials or active market sessions.
2. **Fail-Closed Verification:** Any data corruption, missing mandatory features, inverted spreads, stale quotes, or governance violations must trigger an immediate, graceful fail-closed rejection.
3. **Mathematical Precision:** All statutory deductions (STT, GST, Exchange charges, SEBI fees, stamp duty) and ML performance metrics (ECE, Brier, F1) must evaluate with zero floating-point drift.
4. **Zero State Bleed:** Each test must run in isolated temporary environments (`tmp_path`) leaving protected baseline databases completely untouched.

---

## 2. Pipeline Architecture & Sequence Flow

The end-to-end test framework traverses twelve distinct pipeline stages sequentially:

```
[ Market Data Feed ]
        │
        ▼
[ 1. Data Quality & Freshness Gate ] ── (Rejects Stale, Freak Ticks, Crossed Spread)
        │
        ▼
[ 2. Feature Extraction & Schema Validation ] ── (Rejects Incomplete Greeks, NaNs, Leakage)
        │
        ▼
[ 3. Market Regime & MTF Analysis ] ── (Hierarchical 15m/5m/1m Alignment)
        │
        ▼
[ 4. ICT / SMC Setup Detection ] ── (Sweeps, FVGs, MSS, Order Blocks)
        │
        ▼
[ 5. Deterministic Signal Classification ] ── (BUY_CE, BUY_PE, WAIT, NO_TRADE)
        │
        ▼
[ 6. Contract Selection & Liquidity Gate ] ── (ATM/OTM Selection, SENSEX Lock)
        │
        ▼
[ 7. Risk Management & Capital Budgeting ] ── (Max Loss, Margin Sanity, Capital Bounds)
        │
        ▼
[ 8. Paper Trading Order Execution ] ── (Slippage Model, Fill Simulation, Balance Debit)
        │
        ▼
[ 9. Real-Time Position Monitoring ] ── (MFE, MAE, Unrealized PnL, Trailing SL)
        │
        ▼
[ 10. Multi-Stage Exits (Partial / Full) ] ── (50% at Target 1, Target 2, Stop Loss Hit)
        │
        ▼
[ 11. Statutory Derivative Accounting ] ── (SEBI/NSE Fee Schedules, Net PnL, ROI)
        │
        ▼
[ 12. Prediction & Analytics Framework ] ── (ECE, Brier, F1, PnL Attribution)
```

---

## 3. Test Scenarios & Specification Matrix

### Scenario 1: Full Lifecycle Successful Paper Workflow
- **File:** `tests/test_end_to_end_full_pipeline_phase_d.py::test_end_to_end_successful_paper_workflow`
- **Purpose:** Verifies that a clean, bullish setup executes end-to-end without warnings.
- **Workflow:**
  1. Synthetic 50-bar series generated with positive trend.
  2. DataQualityEngine confirms `VERIFIED_LIVE`.
  3. Regime resolves `BULLISH_TREND`; MTF score = 85.0.
  4. SignalClassifier outputs `BUY_CE` with confidence $\ge 0.80$.
  5. ContractSelector selects active NIFTY CE expiry.
  6. PaperTradingEngine opens 2 lots @ ₹100.00.
  7. Position monitored: price rises to ₹120.00 ($MFE \ge 15$ pts).
  8. Partial exit 1 lot (50%) @ ₹125.00 (Target 1); SL trailed to breakeven (₹100).
  9. Final exit remaining 1 lot @ ₹160.00 (Target 2).
  10. SEBI accounting confirms positive gross PnL and net PnL after ₹20 brokerage, STT, and GST.

### Scenario 2: Invalid Inputs & Anomaly Rejection
- **File:** `tests/test_end_to_end_full_pipeline_phase_d.py::test_end_to_end_invalid_inputs_rejection`
- **Purpose:** Asserts that malformed data cannot penetrate the risk gates.
- **Sub-Tests:**
  - Negative LTP ($\text{LTP} = -50.0$): Flagged `Invalid non-positive LTP`, score deducted by 60, `isTradeQualified = False`.
  - Inverted bid/ask ($\text{Bid} = 105 > \text{Ask} = 95$): Flagged `Crossed market`, score deducted by 25.

### Scenario 3: Missing Mandatory Features (Fail-Closed)
- **File:** `tests/test_end_to_end_full_pipeline_phase_d.py::test_end_to_end_missing_data_fail_closed`
- **Purpose:** Prevents fallback fabrication when market Greek observations are incomplete.
- **Condition:** Pass option vector with `iv = 0.15` but missing `delta`, `theta`, and `gamma`.
- **Expected Outcome:** `is_valid = False`, `error_code = "FEATURE_EXTRACTION_FAILED"`, reasons contain `Mandatory Greek`.

### Scenario 4: Stale Tick & Latency Gating
- **File:** `tests/test_end_to_end_full_pipeline_phase_d.py::test_end_to_end_stale_data_rejection`
- **Purpose:** Ensures quotes delayed by $>60$ seconds are quarantined.
- **Condition:** Quote timestamp generated at $t - 120$ seconds during an active session.
- **Expected Outcome:** FeedStatus flags `STALE`, score deducted by 60, signals suppressed.

### Scenario 5: Capital Budgeting & Margin Rejection
- **File:** `tests/test_end_to_end_full_pipeline_phase_d.py::test_end_to_end_rejected_orders_capital_insufficient`
- **Purpose:** Guarantees accounts cannot over-leverage or produce negative cash balances.
- **Condition:** Account capital initialized to ₹5,000; order attempts to purchase 10 lots NIFTY CE requiring ₹1,30,000.
- **Expected Outcome:** `success = False`, message indicates `Insufficient balance`.

### Scenario 6: Governance-Locked Instrument Enforcement
- **File:** `tests/test_end_to_end_full_pipeline_phase_d.py::test_end_to_end_failed_execution_governance_locked`
- **Purpose:** Verifies that SENSEX derivatives cannot be traded under any circumstances.
- **Condition:** SENSEX liquidity policy status is `UNCONFIGURED`. Order submitted for SENSEX call option.
- **Expected Outcome:** Order rejected immediately; zero state mutated.

### Scenario 7: Position Lifecycle & Stop-Loss Hit Trigger
- **File:** `tests/test_end_to_end_full_pipeline_phase_d.py::test_end_to_end_stop_loss_exit_trigger`
- **Purpose:** Verifies automatic exit execution when market breaches protective stop-loss.
- **Condition:** Long 1 lot NIFTY CE @ ₹100, $\text{Stop-Loss} = ₹80$. Incoming candle bar dips to low of ₹75.
- **Expected Outcome:** `update_live_monitoring` auto-triggers `close_position`; status set to `STOP_LOSS_HIT`; exit price set to ₹80; loss recorded.

### Scenario 8: SEBI Statutory Accounting Precision
- **File:** `tests/test_end_to_end_full_pipeline_phase_d.py::test_end_to_end_accounting_precision`
- **Purpose:** Confirms statutory charge calculations strictly align with Indian exchange regulations.
- **Schedules Verified:**
  - Brokerage: Flat ₹20 per order ($\times 2 = ₹40.00$).
  - STT: 0.1% on sell-side option premium turnover.
  - Exchange Charges: 0.05% on total buy + sell turnover.
  - GST: 18% on (Brokerage + Exchange turnover charges).
  - SEBI Charges: ₹10 per crore of total turnover.
  - Stamp Duty: 0.003% on buy-side turnover.
- **Expected Outcome:** $\text{Net PnL} = \text{Gross PnL} - \text{Total Costs}$ within ₹0.01 precision.

### Scenario 9: Engine Restart & State Recovery
- **File:** `tests/test_end_to_end_full_pipeline_phase_d.py::test_end_to_end_restart_and_recovery`
- **Purpose:** Simulates unexpected crash and restart to confirm persistence.
- **Condition:** Open active position, write state, destroy engine instance, create fresh engine with same file.
- **Expected Outcome:** State reloads with 100% fidelity (identical balance, position ID, strike, and entry price).

### Scenario 10: Prediction & Performance Analytics Verification
- **File:** `tests/test_end_to_end_full_pipeline_phase_d.py::test_analytics_framework_computations`
- **Purpose:** Validates mathematical correctness of ML evaluation metrics.
- **Metrics Verified:**
  - Classification accuracy, precision, recall, and macro F1 score.
  - Expected Calibration Error (ECE) and Brier calibration score.
  - MFE / MAE distributions across forward horizons.
  - Profit factor and win/loss ratio.

---

## 4. Execution Commands

To execute the complete end-to-end test suite:

```bash
# In backend directory with virtual environment activated:
cd d:\ReactJs\aivolve-trading-ai\backend
.venv\Scripts\pytest tests/test_end_to_end_full_pipeline_phase_d.py -v
```

To execute the entire 97-test regression suite:

```bash
cd d:\ReactJs\aivolve-trading-ai\backend
.venv\Scripts\pytest tests/test_feature_pipeline_phase5_2a.py \
                     tests/test_label_engine_phase5_2b.py \
                     tests/test_observation_engine_phase5_2c.py \
                     tests/test_monday_live_session_protocol.py \
                     tests/test_end_to_end_full_pipeline_phase_d.py \
                     tests/test_paper_trading_engine.py \
                     tests/test_p0_live_data_reliability.py -v
```

