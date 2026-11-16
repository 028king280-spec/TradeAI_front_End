# AIVOLVE v3.0 — PHASE 5.2B: LABEL ENGINEERING & WALK-FORWARD PARTITIONING REPORT

**Audit Date:** 14 November 2026, 12:55 IST  
**System Status:** `PAPER_TRADING_ONLY` | Read-Only Audit & Label Engineering  
**Scope Authorization:** Phase 5.2B ONLY (Label Engineering, Outcome Calculation & Walk-Forward Partitioning)  
**Governance Officer:** Financial Risk & Quantitative Systems Audit  

---

## 1. Executive Summary & Governance Preflight

Phase 5.2B has implemented a deterministic label engineering engine, established strict architectural separation between signal decisions and realized trade outcomes, designed a walk-forward train/validation/OOS temporal partition architecture with chronological purging and embargo, and implemented an automated anti-leakage audit guard.

### Governance Preflight Checklist
| Gate / Rule | Required State | Actual State | Audit Status |
| :--- | :--- | :--- | :--- |
| **Execution Mode** | `PAPER_TRADING_ONLY` | `PAPER_TRADING_ONLY` | **PASSED** |
| **Live Broker Orders** | Forbidden (0 orders) | Verified 0 live orders, 0 real capital | **PASSED** |
| **Model Training Authorization** | Forbidden in Phase 5.2B | Zero models trained, zero weights updated | **PASSED** |
| **Model Weights Modification** | Forbidden | `ml_strategy_weights.json` unmodified | **PASSED** |
| **BSE SENSEX Gate** | `GOVERNANCE_LOCKED` | Unmodified, strictly NIFTY options | **PASSED** |
| **ICT Calibration State** | `UNAVAILABLE / NOT_CALIBRATED` | Maintained uncalibrated flag on incomplete data | **PASSED** |
| **Dataset Immutability** | 348 Historical Records Preserved | Hash verified identical | **PASSED** |
| **6 Protected Baseline Hashes** | Unmodified | 6/6 Exact SHA-256 Match | **PASSED** |

---

## 2. Deterministic Signal Decision Classification

### 2.1 Signal Space & Enums
Signal decisions are categorized into four mutually exclusive, deterministic classes:
- **`BUY_CE`**: Qualified long Call option setup meeting multi-timeframe confluence and institutional liquidity/discount criteria.
- **`BUY_PE`**: Qualified long Put option setup meeting multi-timeframe confluence and institutional liquidity/premium criteria.
- **`WAIT`**: Ambiguous, consolidating, choppy, or developing market state where trade entry edge has not matured.
- **`NO_TRADE`**: Unaligned market conditions, conflicting indicators, degraded data feed, session closure, or risk gate lockouts.

### 2.2 Classification Rules at Prediction Time $T_{\text{decision}}$
The `SignalClassifier` evaluates market observations strictly at decision time:
1. **Market Session & Feed Status:** If market regular session is closed ($T < \text{09:15}$ or $T > \text{15:30}$ IST) or feeds are unverified mock data in production, returns `NO_TRADE`.
2. **Bullish Alignment (`BUY_CE`):** Requires $\text{MTF Confluence Score} \ge 70.0$, dealing range in institutional `DISCOUNT` (or confirmed liquidity sweep / FVG reclamation).
3. **Bearish Alignment (`BUY_PE`):** Requires $\text{MTF Confluence Score} \ge 70.0$, dealing range in institutional `PREMIUM` (or confirmed buy-side sweep / FVG mitigation).
4. **Chop / Consolidation (`WAIT`):** If condition is sideways/range-bound without decisive displacement or liquidity sweep, classifies as `WAIT`.
5. **Zero Lookahead:** The classifier strictly strips and ignores future outcome fields (`exitPrice`, `netPnl`, `exitReason`, etc.). A valid setup at $T_{\text{entry}}$ retains its signal classification regardless of subsequent market movements.

---

## 3. Strict Architectural Separation: Signal Labels vs Realized Outcome Labels

A common vulnerability in quantitative trading ML is the conflation of the intentional signal (known at $T_{\text{entry}}$) with the realized outcome (known at $T_{\text{exit}}$). Phase 5.2B establishes rigid data structure separation:

```
┌────────────────────────────────────────────────────────────────────────┐
│                   AIVOLVE 5.2B LABEL ARCHITECTURE                      │
├───────────────────────────────────┬────────────────────────────────────┤
│ SignalLabel (Time T_decision)     │ RealizedOutcomeLabel (Time T_exit) │
├───────────────────────────────────┼────────────────────────────────────┤
│ • signal_type: BUY_CE / BUY_PE /  │ • trade_id: Unique identifier      │
│   WAIT / NO_TRADE                 │ • entry_time, exit_time            │
│ • decision_time: IST datetime     │ • holding_duration_seconds         │
│ • direction: CE / PE / NEUTRAL    │ • entry_price, exit_price          │
│ • confidence: Float [0.0, 1.0]    │ • gross_pnl, total_charges         │
│ • setup_name: ICT / Model setup   │ • net_pnl: Exact statutory net     │
│ • is_actionable: Boolean          │ • binary_target: 1 (Win), 0 (Loss) │
│ • market_status: OPEN / CLOSED    │ • multiclass_target: WIN /         │
│ • reasons: Traceable audit list   │   SCRATCH / LOSS                   │
│                                   │ • mfe_pts, mae_pts, return_on_risk │
│                                   │ • status: CLOSED / UNRESOLVED      │
│                                   │ • is_genuine: True (real quotes)   │
└───────────────────────────────────┴────────────────────────────────────┘
```

---

## 4. Genuine Future Outcome Calculation

### 4.1 Causality Enforcement
- **Temporal Monotonicity:** Enforces $T_{\text{exit}} \ge T_{\text{entry}}$. Any record where $T_{\text{exit}} < T_{\text{entry}}$ triggers a fail-closed `ValueError("Temporal causality violation")`.
- **Unresolved Positions:** Open trades or trades missing exit price/timestamp are classified with `status="UNRESOLVED"`, `outcome_class=OutcomeClass.UNRESOLVED`, and `is_genuine=False`. Unresolved trades are barred from training target generation.

### 4.2 Exact Statutory Cost & Target Modeling
- Transaction costs are computed using `IndianDerivativesCostCalculator`:
  $$\text{Charges} = \text{Brokerage} + \text{STT} + \text{Exchange Turnover} + \text{GST} + \text{SEBI} + \text{Stamp Duty} + \text{Slippage}$$
  $$\text{Net PnL} = \text{Gross PnL} - \text{Charges}$$
- **Binary Classification Target:**
  $$Y_{\text{binary}} = \begin{cases} 1 & \text{if } \text{Net PnL} > 0.0 \\ 0 & \text{if } \text{Net PnL} \le 0.0 \end{cases}$$
- **Triclass Target (Friction-Adjusted):**
  $$Y_{\text{multi}} = \begin{cases} 2 \text{ (WIN)} & \text{if } \text{Net PnL} > \text{Friction Threshold (₹50)} \\ 1 \text{ (SCRATCH)} & \text{if } |\text{Net PnL}| \le \text{Friction Threshold (₹50)} \\ 0 \text{ (LOSS)} & \text{if } \text{Net PnL} < -\text{Friction Threshold (₹50)} \end{cases}$$
- **Return on Risk ($R$):**
  $$R = \frac{\text{Net PnL}}{(\text{Entry Price} - \text{Stop Loss}) \times \text{Quantity}}$$

---

## 5. Walk-Forward Partition Architecture with Purging & Embargo

Standard K-fold cross-validation is fundamentally flawed for financial time series due to temporal leakage and autocorrelation. Phase 5.2B implements the **Marcos López de Prado Walk-Forward Methodology**:

```
Timeline:  [═════════ Train ═════════][Purged][══ Embargo ══][════ Validation ════] ... [══ OOS Holdout ══]
           T0                        T_train_end            T_val_start          T_val_end
```

### 5.1 Chronological Purging
- When training on $[T_0, T_{\text{train\_end}}]$ and evaluating on $[T_{\text{val\_start}}, T_{\text{val\_end}}]$, any trade entering before $T_{\text{train\_end}}$ whose position was held past $T_{\text{val\_start}}$ ($T_{\text{exit}} \ge T_{\text{val\_start}}$) has an outcome contaminated by market prices in the validation period.
- **Purge Action:** Such trades are removed from `train_indices` and isolated into `purged_indices`.

### 5.2 Embargo Enforcement
- Financial series exhibit serial autocorrelation. Observations occurring immediately after the training cutoff share market microstructure momentum with the training data.
- **Embargo Action:** An embargo window $\Delta t_{\text{embargo}}$ (e.g. 30 minutes or 1 trading day) is placed immediately after $T_{\text{train\_end}}$. Prospective validation samples entering during $[T_{\text{train\_end}}, T_{\text{train\_end}} + \Delta t_{\text{embargo}}]$ are quarantined into `embargoed_indices`.

### 5.3 Pure Holdout Out-Of-Sample (OOS) Partition
- The final fraction of the timeline (default 20%) is strictly reserved as an untouchable holdout partition (`oos_indices`).
- No sample from the development period may spill its exit into the OOS period ($T_{\text{exit}} < T_{\text{oos\_start}}$).

---

## 6. Anti-Leakage Audit Guard (`LeakageGuard`)

`LeakageGuard` performs automated verification across all partition splits:
1. **Zero Index Overlap:** Asserts $\text{Train} \cap \text{Val} = \emptyset$, $\text{Train} \cap \text{OOS} = \emptyset$, $\text{Val} \cap \text{OOS} = \emptyset$.
2. **Purge Compliance:** Asserts $\forall i \in \text{Train}, T_{\text{exit}, i} < T_{\text{val\_start}}$.
3. **Embargo Compliance:** Asserts $\forall j \in \text{Val}, T_{\text{entry}, j} \ge T_{\text{train\_end}} + \Delta t_{\text{embargo}}$.
4. **OOS Temporal Isolation:** Asserts $\forall k \in (\text{Train} \cup \text{Val}), T_{\text{exit}, k} < T_{\text{oos\_start}}$.

---

## 7. Automated Test Results

### 7.1 Dedicated Phase 5.2B Test Suite (`tests/test_label_engine_phase5_2b.py`)
```
============================= test session starts =============================
platform win32 -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0
rootdir: D:\ReactJs\aivolve-trading-ai\backend
configfile: pytest.ini
collected 12 items

tests/test_label_engine_phase5_2b.py::test_signal_classification_deterministic PASSED [  8%]
tests/test_label_engine_phase5_2b.py::test_signal_classification_ignores_future_metrics PASSED [ 16%]
tests/test_label_engine_phase5_2b.py::test_signal_session_and_unverified_data_fails_closed PASSED [ 25%]
tests/test_label_engine_phase5_2b.py::test_realized_outcome_label_calculation PASSED [ 33%]
tests/test_label_engine_phase5_2b.py::test_outcome_calculation_unresolved_trade PASSED [ 41%]
tests/test_label_engine_phase5_2b.py::test_outcome_calculation_causality_rejection PASSED [ 50%]
tests/test_label_engine_phase5_2b.py::test_outcome_calculation_invalid_price_or_qty_rejection PASSED [ 58%]
tests/test_label_engine_phase5_2b.py::test_walk_forward_partition_structure PASSED [ 66%]
tests/test_label_engine_phase5_2b.py::test_chronological_purging_mechanism PASSED [ 75%]
tests/test_label_engine_phase5_2b.py::test_embargo_quarantine_mechanism PASSED [ 83%]
tests/test_label_engine_phase5_2b.py::test_leakage_guard_audits_clean_and_contaminated_splits PASSED [ 91%]
tests/test_label_engine_phase5_2b.py::test_historical_348_records_read_only_integrity PASSED [100%]

============================= 12 passed in 1.10s ==============================
```

### 7.2 Full Regression Test Suite Execution
```
tests/test_feature_pipeline_phase5_2a.py (Phase 5.2A Pipeline):        11 / 11 PASSED (100%)
tests/test_label_engine_phase5_2b.py (Phase 5.2B Label Engine):         12 / 12 PASSED (100%)
tests/test_paper_trading_engine.py (Paper Trading Engine):               5 /  5 PASSED (100%)
tests/test_p0_live_data_reliability.py (P0 Live Reliability):          40 / 40 PASSED (100%)
────────────────────────────────────────────────────────────────────────────────────────
TOTAL REGRESSION SUITE:                                                 68 / 68 PASSED (100%)
```

---

## 8. Protected Baseline SHA-256 Hash Verification

All six critical governance files were audited. Every hash matches the accepted baseline exactly:

| Protected File Path | Baseline SHA-256 Hash | Current Verified Hash | Status |
| :--- | :--- | :--- | :---: |
| `backend/aivolve_trading.db` | `C85C49BE76DEE40557C4B9AAF308B4E3BEACA03CD4B1CD1CE90D051566EABF44` | `C85C49BE76DEE40557C4B9AAF308B4E3BEACA03CD4B1CD1CE90D051566EABF44` | **100% MATCH** |
| `backend/app/data/governance_ledger.db` | `4B12B3BAB44BF913F15174278B346FA321D5C473272E40F8B7E6E2350034488E` | `4B12B3BAB44BF913F15174278B346FA321D5C473272E40F8B7E6E2350034488E` | **100% MATCH** |
| `backend/app/data/paper_trading_records.json` | `00F968EF85095EB7C1DE336A1780F9EDE417426A253AC531446BEF1117DA0298` | `00F968EF85095EB7C1DE336A1780F9EDE417426A253AC531446BEF1117DA0298` | **100% MATCH** |
| `backend/app/data/ml_trade_dataset.json` | `87EEA8802835BB4F5A0AD1D598F2CEC561C6D5237F123B8B57CD79BBBE2E6445` | `87EEA8802835BB4F5A0AD1D598F2CEC561C6D5237F123B8B57CD79BBBE2E6445` | **100% MATCH** |
| `backend/app/data/what_ai_learned.json` | `3ED015726DFF309000EEC473AB660F34E3BD4EFAEDCBE183B14D62C572E5CCC5` | `3ED015726DFF309000EEC473AB660F34E3BD4EFAEDCBE183B14D62C572E5CCC5` | **100% MATCH** |
| `backend/app/data/ml_strategy_weights.json` | `C3C495F36214BD7FA58DDCA3C7F0280C14E15EB08DF41F868704F724C2A4E2FC` | `C3C495F36214BD7FA58DDCA3C7F0280C14E15EB08DF41F868704F724C2A4E2FC` | **100% MATCH** |

---

## 9. Proposed Phase 5.3 Specification: Baseline Model Training Governance

With Feature Hardening (Phase 5.2A) and Label Engineering / Walk-Forward Partitioning (Phase 5.2B) complete, the system is prepared for **Phase 5.3: Supervised Baseline Model Training & Cross-Validation**:

1. **Model Scope:**
   - Interpretable, regularized baseline architectures:
     - Regularized Logistic Regression / ElasticNet.
     - Constrained Random Forest (max depth $\le 5$, min samples leaf $\ge 15$).
     - Shallow Gradient Boosted Trees (XGBoost / LightGBM with conservative learning rate $\eta \le 0.05$).
2. **Cross-Validation Execution:**
   - Train strictly within walk-forward folds generated by `WalkForwardPartitionEngine`.
   - Never evaluate or select hyper-parameters on the holdout Out-Of-Sample partition.
3. **Evaluation Metrics:**
   - Out-of-fold Precision, Recall, F1-Score, Brier Score, and ROC-AUC.
   - PnL Simulation: Cumulative returns, Sharpe ratio, Sortino ratio, Max Drawdown net of statutory fees.
4. **Governance Invariants:**
   - Zero model weights updated in production until full audit sign-off.
   - Zero live broker orders; execution mode remains strictly `PAPER_TRADING_ONLY`.

---

## 10. Final Verdict & Governance Decision

```
╔═══════════════════════════════════════════════════════════════════════╗
║                      PHASE 5.2B AUDIT VERDICT                         ║
╠═══════════════════════════════════════════════════════════════════════╣
║ Deterministic Signal Classifier:              VERIFIED COMPLETE       ║
║ Signal Label vs Outcome Label Separation:     VERIFIED COMPLETE       ║
║ Genuine Post-Trade Outcome Calculation:       VERIFIED COMPLETE       ║
║ Causality & Unresolved Position Guards:       VERIFIED COMPLETE       ║
║ Walk-Forward Partitioning Engine:             VERIFIED COMPLETE       ║
║ Chronological Purging & Embargo Guards:       VERIFIED COMPLETE       ║
║ Anti-Leakage Audit Guard (LeakageGuard):      VERIFIED COMPLETE       ║
║ Dedicated Test Suite (12/12 tests):          100% PASS               ║
║ Full Regression Suite (68/68 tests):          100% PASS               ║
║ Protected 6 Baseline Hashes:                 100% UNMODIFIED         ║
╠═══════════════════════════════════════════════════════════════════════╣
║ RECOMMENDATION FOR PHASE 5.3:                GO                      ║
╚═══════════════════════════════════════════════════════════════════════╝
```

**Next Step:** Await explicit user authorization before initiating Phase 5.3.

