# AIVOLVE v3.0 — Phase 7: Dynamic Risk Management Gap Analysis

**Document Version:** 3.0.0  
**Phase:** Phase 7 — Dynamic Risk Management & Capital Defense Engine (Engine 10)  
**Governing Standard:** AIVOLVE Master Development Specification v3.0 (Engine 10 / Blueprint Phase 07)  
**Operating Mode:** STRICTLY `PAPER_TRADING_ONLY` (Read-Only Gap Analysis & Architecture Review)  
**Target Instruments:** NIFTY 50, BANK NIFTY, FINNIFTY (SENSEX `GOVERNANCE_LOCKED`)  
**Audit Date:** 14 November 2026 (Saturday Standby Session)  

---

## 1. Executive Summary

This document performs an exhaustive, component-by-component architectural gap analysis between the authoritative requirements of **Engine 10 (Dynamic Risk Management Engine)** in the AIVOLVE Master Blueprint v3.0 and the current state of the codebase.

The repository already possesses mature single-contract scenario pricing, statutory Indian tax modeling, and isolated portfolio accounting. However, significant architectural gaps exist in **centralized multi-index portfolio heat management, real-time intraday drawdown circuit breakers, and aggregate Greeks portfolio exposure defense**.

Furthermore, this audit identifies and documents a critical pre-live reliability defect in `backend/app/options/next_session_engine.py:333` (`DEFECT-PRELIVE-01`) regarding unhandled `NoneType` subscripting on option Greeks.

---

## 2. Existing Risk & Execution Architecture Audit

### 2.1 Inspection of Key System Modules

| File Path | Primary Function & Responsibilities | Current Operational State |
| :--- | :--- | :--- |
| `backend/app/options/option_risk_engine.py` (584 lines) | Non-linear Black-Scholes scenario repricing for $P_{SL}, P_{T1}, P_{T2}, P_{T3}$; conservative entry at Ask, exit at Bid less half-spread and slippage; tick rounding to 0.05 floor; independent $RR_{T1}, RR_{T2}, RR_{T3}$ hurdles; zero-invention position sizing. | **COMPLETED_AND_VERIFIED** for single-contract setup risk evaluation. Lacks portfolio-level context. |
| `backend/app/options/contract_selector.py` (88k bytes) | Dynamic strike derivation from InstrumentMaster; Delta filtering ($\Delta \in [0.35, 0.55]$); liquidity filters (minimum OI $\ge 50,000$, spread $\le 1.5\%$); cryptographic governance overrides. | **COMPLETED_AND_VERIFIED** for contract qualification and liquidity filtering. |
| `backend/app/options/paper_trading/paper_engine.py` (732 lines) | Simulated order lifecycle (PENDING, OPEN, TARGET_1_HIT, TARGET_2_HIT, STOP_LOSS_HIT, EXPIRED); crash-safe atomic persistence via `.tmp` file and `os.replace`; 50% partial exit at T1 with runner SL moved to entry; MFE/MAE tracking; retrospective drawdown calculation in `get_dashboard_metrics()`. | **COMPLETED_AND_VERIFIED** for trade lifecycle and storage. Lacks real-time intraday loss circuit breaker. |
| `backend/app/options/paper_trading/cost_calculator.py` (4.6k bytes) | Exact statutory Indian derivatives fee model: Flat ₹20 brokerage/leg, 0.1% sell-side STT, 0.05% exchange fee, 18% GST, ₹10/Cr SEBI turnover, 0.003% buy-side stamp duty. | **COMPLETED_AND_VERIFIED** with exact mathematical P&L conservation. |
| `backend/app/options/market_state_engine.py` (32k bytes) | Deterministic regime detection (BULLISH_TREND, BEARISH_TREND, SIDEWAYS, REVERSAL, VOLATILITY_EXPANSION, NO_TRADE, DATA_UNAVAILABLE) using ADX, ATR%, EMA ribbons, and VWAP. | **COMPLETED_AND_VERIFIED** as upstream regime provider for risk scaling. |
| `backend/app/options/paper_trading/feature_pipeline.py` (10k bytes) | Production feature validator ensuring zero look-ahead bias, chronological integrity, and strict rejection of synthetic fallbacks. | **COMPLETED_AND_VERIFIED** for entry-time ML feature capture. |
| `backend/app/backtesting/portfolio_ledger.py` (29k bytes) | Double-entry isolated portfolio accounting ledger guaranteeing zero mixing across `INDEX_POINTS_ONLY`, `INDEX_POINTS_AND_EXPLICIT_INR`, and `SYNTHETIC_OPTION_INR_ONLY`. | **COMPLETED_AND_VERIFIED** for historical backtesting and research replay. |
| `backend/app/backtesting/risk_analytics.py` (17k bytes) | Underwater episode tracking, Ulcer Index, maximum drawdown recovery factors, and consecutive loss streaks. | **COMPLETED_AND_VERIFIED** for backtest analytics. |

---

## 3. Requirement-by-Requirement Gap Matrix

| Req ID | Master Blueprint Requirement | Existing Implementation Status | Gap Description & Deficiencies | Target Classification |
| :--- | :--- | :--- | :--- | :--- |
| **REQ-7.1** | Non-Linear Scenario Repricing | Implemented in `option_risk_engine.py` | Full Black-Scholes scenario repricing exists. Holding horizons are documented as uncalibrated assumptions. | `COMPLETED_AND_VERIFIED` |
| **REQ-7.2** | Conservative Fill & Friction Model | Implemented in `option_risk_engine.py` | Entry at Ask, exit at Bid less half-spread and slippage. No double-counting. | `COMPLETED_AND_VERIFIED` |
| **REQ-7.3** | Independent R:R Qualification | Implemented in `option_risk_engine.py` | Independent hurdles $RR_{T1} \ge 0.50, RR_{T2} \ge 1.25, RR_{T3} \ge 1.50$ enforced with zero concealment. | `COMPLETED_AND_VERIFIED` |
| **REQ-7.4** | Zero-Invention Position Sizing | Implemented in `option_risk_engine.py` | Enforces capital/risk budget limits. Sets status `UNAVAILABLE` when budget is unconfigured. | `COMPLETED_AND_VERIFIED` |
| **REQ-7.5** | Real-Time Intraday Drawdown Breaker | Missing | `paper_engine.py` only calculates drawdown retrospectively in analytics. It does NOT halt new order opening during the trading session when cumulative daily loss exceeds budget. | `OFFLINE_IMPLEMENTABLE` |
| **REQ-7.6** | Multi-Index Exposure & Heat Limits | Missing | Setups in NIFTY, BANK NIFTY, and FINNIFTY are currently evaluated in silos. No coordinator caps total deployed capital (portfolio heat) or blocks concurrent correlated directional bets. | `OFFLINE_IMPLEMENTABLE` |
| **REQ-7.7** | Portfolio Greeks Aggregator | Missing | Greeks are calculated for individual contracts, but no module computes net portfolio Delta, Gamma, Theta decay burden (₹/day), or Vega across all open positions. | `OFFLINE_IMPLEMENTABLE` |
| **REQ-7.8** | Dynamic Stop Ratchet & Breakeven Lock | Implemented in `paper_engine.py` | 50% partial exit at T1 and runner SL ratchet to entry premium is fully coded and tested. | `COMPLETED_AND_VERIFIED` |
| **REQ-7.9** | Real-Time Excursion Tracking (MFE/MAE) | Implemented in `paper_engine.py` | Continuous high/low tick monitoring computes `mfePts`, `mfeRupees`, `maePts`, `maeRupees` per active trade. | `COMPLETED_AND_VERIFIED` |
| **REQ-7.10** | Statutory Cost & Conservation Ledger | Implemented in `cost_calculator.py` | Full Indian statutory tax schedule (STT, Exchange, GST, SEBI, Stamp) accurately deducted. | `COMPLETED_AND_VERIFIED` |

---

## 4. Architectural Gaps & Implementation Needs

```
                                  EXISTING vs REQUIRED RISK ARCHITECTURE
                                  
         [ CURRENT ARCHITECTURE ]                             [ REQUIRED PHASE 7 ARCHITECTURE ]
         
    +--------------------------------+                  +--------------------------------+
    |     option_risk_engine.py      |                  |     option_risk_engine.py      |
    | (Single contract BS repricing) |                  | (Single contract BS repricing) |
    +--------------------------------+                  +--------------------------------+
                   │                                                   │
                   ▼ (Direct order call)                               ▼ (Pre-trade evaluation)
    +--------------------------------+                  +────────────────────────────────+
    |        paper_engine.py         |                  |    *NEW* dynamic_risk_engine   |
    | (Checks only cash balance)     |                  | - Intraday Drawdown Breaker    |
    | (No portfolio-level defense)   |                  | - Multi-Index Exposure Caps    |
    +--------------------------------+                  | - Portfolio Heat Limit         |
                                                        | - Portfolio Greeks Monitor     |
                                                        +────────────────────────────────+
                                                                       │ (Approved orders only)
                                                                       ▼
                                                        +--------------------------------+
                                                        |        paper_engine.py         |
                                                        | (Execution with risk hooks)    |
                                                        +--------------------------------+
```

### 4.1 Gap 1: Absence of Central Dynamic Risk Coordinator (`dynamic_risk_engine.py`)
Currently, `option_risk_engine.py` is invoked per-contract, and `paper_engine.py` directly opens positions without consulting a centralized portfolio risk manager. There is no central service that validates whether the overall portfolio has reached its daily risk limit or whether a new trade breaches portfolio-level constraints.

### 4.2 Gap 2: Lack of Real-Time Intraday Drawdown Circuit Breaker in `paper_engine.py`
In `paper_engine.py:346-350`, `open_position()` only verifies that:
```python
if margin_required > self.state["balance"]:
    return {"success": False, "message": "Insufficient virtual balance"}
```
It does NOT check:
1. What is the cumulative realized net P&L closed today?
2. What is the total floating (unrealized) drawdown on currently open positions?
3. Does cumulative daily loss breach the daily risk budget $B_{\text{daily, max}}$?
Without this check, the paper trading simulator can continue taking trades into severe adverse market regimes, directly violating Master Blueprint Principle 1 (*"Capital preservation comes before trade frequency"*).

### 4.3 Gap 3: Absence of Multi-Index Correlated Exposure Governor
Each index setup is processed independently:
- A user or automated signal can open 1 lot of NIFTY CE and 1 lot of BANK NIFTY CE at the exact same minute.
- Because NIFTY and BANK NIFTY have an index correlation $\rho > 0.75$, this doubles directional market risk without any portfolio defense check.
- A dedicated `PortfolioRiskGovernor` is required to enforce:
  1. Maximum concurrent open positions (e.g. 2).
  2. Maximum portfolio heat fraction (e.g. max 20% of capital committed to option premiums).
  3. Correlated cluster limit (max 1 directional trade across NIFTY and BANK NIFTY).

### 4.4 Gap 4: Absence of Aggregate Portfolio Greeks Monitor
While single contracts report $\Delta, \Gamma, \Theta, \nu$, there is no unified aggregation across open positions. A trader or paper session holding multiple contracts can unknowingly accumulate excessive negative theta decay burden (e.g. ₹-2,500/day on a ₹100,000 account) or excessive positive vega exposure before a scheduled high-impact macro release.

### 4.5 Gap 5: Risk Configuration Parameter Governance
Numerical thresholds (such as 2% max daily loss, 20% portfolio heat, 2 concurrent positions) must not be hardcoded or invented without institutional governance authorization.
In accordance with Step 4, all such parameters must:
1. Be defined in a structured configuration schema.
2. Default safely to `GOVERNANCE_PENDING` or conservative fallback values.
3. Require explicit administrative or governance authorization before activation in live/paper trading.

---

## 5. Pre-Live Reliability Defect Record

### DEFECT-PRELIVE-01: next_session_engine.py NoneType Greeks Subscript Exception

> [!IMPORTANT]
> **Scope Isolation Disclaimer:** This defect resides in the existing pre-live options overview endpoint (`next_session_engine.py`). It is a legacy reliability bug and is strictly recorded here as an independent pre-live reliability defect; it is **NOT** a new Phase 7 feature.

#### 1. Defect Identification
- **Defect Identifier:** `DEFECT-PRELIVE-01`
- **Component:** `backend/app/options/next_session_engine.py`
- **Location:** Lines 331–336
- **Severity:** HIGH (Endpoint Crash / HTTP 500 in Offline / Edge States)
- **Classification:** Pre-Live Code Defect (Discovered during Phase 6 verification audit)

#### 2. Root Cause Analysis
In `next_session_engine.py:180-190`, `calculate_black_scholes` is called to compute options Greeks:
```python
greeks = calculate_black_scholes(
    spot=underlying_ltp,
    strike=target_strike,
    time_to_expiry_years=2.5 / 365.0,
    risk_free_rate=0.065,
    iv=contract_iv / 100.0,
    option_type=target_type
)
delta = abs(greeks["delta"]) if greeks else 0.5
theta_day = greeks["theta"] if greeks else -10.0
```
Lines 188 and 189 correctly apply safe fallback expressions (`if greeks else ...`) to prevent `TypeError` when `calculate_black_scholes` returns `None`.

However, downstream in lines 331–336, the dictionary construction directly subscripts `greeks` without any null-check:
```python
"greeks": {
    "delta": round(delta, 3),
    "gamma": round(greeks["gamma"], 5),     # <--- LINE 333: CRASH HERE
    "thetaPerDay": round(theta_day, 2),
    "vega": round(greeks["vega"], 2),       # <--- LINE 335: CRASH HERE
},
```
When `underlying_ltp <= 0`, `contract_iv <= 0`, or an invalid numerical condition causes `calculate_black_scholes` to return `None`, line 333 immediately throws:
```
TypeError: 'NoneType' object is not subscriptable
```
This causes an unhandled HTTP 500 error on `/api/options/{index}/overview` and `/api/options/{index}/next-session/recommendation`.

#### 3. Proposed Remediation Blueprint (Awaiting Authorization)
When authorized for remediation, lines 331–336 must be updated to use safe extraction with deterministic defaults:
```python
"greeks": {
    "delta": round(delta, 3),
    "gamma": round(greeks["gamma"], 5) if greeks and "gamma" in greeks else 0.0,
    "thetaPerDay": round(theta_day, 2),
    "vega": round(greeks["vega"], 2) if greeks and "vega" in greeks else 0.0,
},
```
This ensures graceful operation across pre-market, weekend offline standby, and incomplete option chain scenarios.

---

## 6. Conclusion & Readiness Summary

1. **Existing Foundations:** The codebase already possesses mathematically rigorous single-trade option risk modeling (`option_risk_engine.py`), statutory Indian cost accounting (`cost_calculator.py`), and crash-resilient trade persistence (`paper_engine.py`).
2. **Phase 7 Mandate:** Completing Phase 7 requires creating the portfolio defense layer:
   - `portfolio_risk_governor.py` (Intraday cumulative drawdown circuit breaker and portfolio heat manager).
   - `portfolio_greeks_engine.py` (Aggregate multi-index Greeks exposure monitor).
   - `dynamic_risk_engine.py` (Central orchestrator bridging setup selector, macro proximity, and paper engine).
3. **Execution Restriction:** All findings in this document are strictly read-only. No code or configuration changes have been executed.

