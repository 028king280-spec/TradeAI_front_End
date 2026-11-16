# AIVOLVE v3.0 — Phase 7: Dynamic Risk Management Implementation Roadmap

**Document Version:** 3.0.0  
**Phase:** Phase 7 — Dynamic Risk Management & Capital Defense Engine (Engine 10)  
**Governing Standard:** AIVOLVE Master Development Specification v3.0 (Engine 10 / Blueprint Phase 07)  
**Operating Mode:** STRICTLY `PAPER_TRADING_ONLY` (Implementation Plan & Authorization Roadmap)  
**Target Instruments:** NIFTY 50, BANK NIFTY, FINNIFTY (SENSEX `GOVERNANCE_LOCKED`)  
**Date:** 14 November 2026 (Saturday Standby Session)  

---

## 1. Executive Summary & Implementation Strategy

Phase 7 operationalizes the real-time capital preservation mandate of the AIVOLVE system. To maintain absolute stability, deterministic repeatability, and zero regression against Phases 1 through 6, Phase 7 implementation is structured into **six discrete, modular steps**.

Each step will be implemented sequentially with isolated unit tests and complete mathematical verification before proceeding to the next.

```
========================================================================================
                       PHASE 7 MODULAR IMPLEMENTATION SEQUENCE
========================================================================================

  [ Step 7.1: Risk Models & Contracts ]
         │ (Pydantic schemas, risk states, zero-invention policy types)
         ▼
  [ Step 7.2: Portfolio Risk Governor ]
         │ (Intraday drawdown circuit breaker, portfolio heat limits, correlation caps)
         ▼
  [ Step 7.3: Portfolio Greeks Aggregator ]
         │ (Net Delta, Gamma, Theta decay burden ₹/day, Vega exposure across positions)
         ▼
  [ Step 7.4: Central Dynamic Risk Engine ]
         │ (Pre-trade orchestrator unifying option_risk_engine, macro, & portfolio state)
         ▼
  [ Step 7.5: Paper Engine Integration ]
         │ (Pre-order risk gating hook in paper_engine.py with fail-closed defense)
         ▼
  [ Step 7.6: Isolated Test Suite & Verification ]
         │ (Comprehensive unit & regression tests, baseline hash re-audit)
         ▼
  [ Phase 7 Acceptance & Sign-off ]
========================================================================================
```

---

## 2. Requirement Classification Matrix

Every requirement from Engine 10 of the Master Blueprint v3.0 is classified into one of the standardized operational readiness categories:

| Req ID | Requirement Description | Technical Component | Classification Status | Justification / Governing Condition |
| :--- | :--- | :--- | :--- | :--- |
| **REQ-7.1** | Non-Linear Scenario Repricing | `option_risk_engine.py` | `COMPLETED_AND_VERIFIED` | Full Black-Scholes scenario repricing verified with adverse IV stress and holding decay. |
| **REQ-7.2** | Conservative Fill & Friction Model | `option_risk_engine.py` | `COMPLETED_AND_VERIFIED` | Ask entry, Bid scenario exit, half-spread and slippage isolation verified without double-counting. |
| **REQ-7.3** | Independent R:R Qualification | `option_risk_engine.py` | `COMPLETED_AND_VERIFIED` | $RR_{T1} \ge 0.50, RR_{T2} \ge 1.25, RR_{T3} \ge 1.50$ verified with zero concealment. |
| **REQ-7.4** | Zero-Invention Position Sizing | `option_risk_engine.py` | `COMPLETED_AND_VERIFIED` | Sizing derived strictly from authorized risk/capital budget; defaults to `UNAVAILABLE`. |
| **REQ-7.5** | Real-Time Intraday Drawdown Breaker | `portfolio_risk_governor.py` | `OFFLINE_IMPLEMENTABLE` | Offline testable with simulated sequence of winning and losing trades. |
| **REQ-7.6** | Multi-Index Exposure & Heat Limits | `portfolio_risk_governor.py` | `OFFLINE_IMPLEMENTABLE` | Offline testable with multi-index synthetic order batches across NIFTY and BANK NIFTY. |
| **REQ-7.7** | Portfolio Greeks Aggregator | `portfolio_greeks_engine.py` | `OFFLINE_IMPLEMENTABLE` | Mathematical aggregation of Greeks across open simulated position dictionaries. |
| **REQ-7.8** | Dynamic Stop Ratchet & Breakeven Lock | `paper_engine.py` | `COMPLETED_AND_VERIFIED` | 50% partial exit at T1 and runner SL ratchet to entry premium verified in paper engine. |
| **REQ-7.9** | Real-Time Excursion Tracking (MFE/MAE) | `paper_engine.py` | `COMPLETED_AND_VERIFIED` | Continuous adverse and favorable excursion calculation verified in trade lifecycle. |
| **REQ-7.10** | Statutory Cost & Conservation Ledger | `cost_calculator.py` | `COMPLETED_AND_VERIFIED` | Full statutory Indian tax schedule and double-entry conservation verified. |

---

## 3. Step-by-Step Implementation Plan

### Step 7.1: Risk Data Models & Contracts (`risk_models.py`)
- **File:** `backend/app/options/risk_models.py`
- **Scope:**
  - Define `PortfolioRiskState` enum: `NORMAL`, `CAPITAL_WARNING`, `DAILY_DRAWDOWN_BREACHED`, `PORTFOLIO_HEAT_EXCEEDED`, `CORRELATED_EXPOSURE_LOCKED`.
  - Define `RiskPolicyConfig` schema containing all risk thresholds with explicit governance flags.
  - Define `PreTradeRiskEvaluation` request and response models.
  - Define `PortfolioGreeksSnapshot` model.
- **Verification:** Unit tests verifying schema serialization, validation, and immutability.

### Step 7.2: Portfolio Risk Governor (`portfolio_risk_governor.py`)
- **File:** `backend/app/options/portfolio_risk_governor.py`
- **Scope:**
  - Implement `PortfolioRiskGovernor` class.
  - Calculate cumulative daily realized P&L + floating P&L:
    $$L_{\text{net, daily}} = L_{\text{realized, daily}} + \sum \text{FloatingPnL}$$
  - Trigger intraday circuit breaker if $L_{\text{net, daily}} \le -B_{\text{daily, max}}$.
  - Enforce portfolio heat limit:
    $$\frac{\sum \text{MarginUsed}}{C_{\text{total}}} \le H_{\text{max}}$$
  - Enforce maximum concurrent open positions ($N_{\text{open}} \le N_{\text{max}}$).
  - Enforce correlated directional exposure caps (e.g. max 1 long directional bet across NIFTY 50 and BANK NIFTY).
- **Verification:** Unit tests with simulated drawdown breaches and correlated position blocks.

### Step 7.3: Portfolio Greeks Aggregator (`portfolio_greeks_engine.py`)
- **File:** `backend/app/options/portfolio_greeks_engine.py`
- **Scope:**
  - Implement `PortfolioGreeksEngine` class.
  - Aggregate net portfolio Delta, Gamma, Theta decay burden (₹/day), and Vega exposure across all open positions in `paper_trading_records.json`.
  - Provide portfolio stress evaluation under $\pm 1\%$ and $\pm 2\%$ underlying index shifts and $\pm 10\%$ IV shock.
- **Verification:** Mathematical verification against manually calculated Greeks sums.

### Step 7.4: Central Dynamic Risk Engine Orchestrator (`dynamic_risk_engine.py`)
- **File:** `backend/app/options/dynamic_risk_engine.py`
- **Scope:**
  - Unified facade integrating:
    1. Single-contract scenario risk plan (`option_risk_engine.py`).
    2. Macroeconomic proximity blackout checks (`macro_proximity_engine.py`).
    3. Portfolio-level drawdown and heat constraints (`portfolio_risk_governor.py`).
    4. Greek concentration limits (`portfolio_greeks_engine.py`).
  - Provide authoritative `evaluate_pre_trade_risk(setup, contract, portfolio_state, macro_calendar)` endpoint.
  - Guarantee deterministic fail-closed behavior: any missing data, expired quote, or breached limit returns `REJECTED` / `NO_TRADE`.
- **Verification:** Integration tests verifying pre-trade evaluation across all risk states.

### Step 7.5: Paper Trading Execution Integration
- **File:** `backend/app/options/paper_trading/paper_engine.py`
- **Scope:**
  - Add pre-execution risk validation hook in `open_position()`.
  - When a paper order is requested, query `DynamicRiskEngine.evaluate_pre_trade_risk()`.
  - If the portfolio circuit breaker is triggered or heat is exceeded, reject order placement with explicit reason code.
  - Preserve existing atomic file persistence and thread-safe locking.
- **Verification:** Test simulated trade rejection upon simulated daily drawdown breach.

### Step 7.6: Isolated Unit & Regression Suite (`test_dynamic_risk_engine_phase7.py`)
- **File:** `backend/tests/test_dynamic_risk_engine_phase7.py`
- **Scope:**
  - Comprehensive unit test suite covering:
    - Drawdown circuit breaker activation and recovery.
    - Portfolio heat limit enforcement.
    - Multi-index correlated directional block (NIFTY + BANK NIFTY).
    - Greeks portfolio aggregation.
    - Pre-trade orchestrator integration.
    - Zero side-effects on baseline persistence.
- **Verification:** Full regression run (127 existing tests + new Phase 7 tests = 100% pass).

---

## 4. Policy Threshold Governance & Pending Authorizations

In accordance with Step 4 of the prompt, the following numerical thresholds are proposed for the risk configuration schema, but **must remain strictly labeled `GOVERNANCE_PENDING`** until user approval:

| Policy Parameter | Proposed Default Value | Governance Status | Operational Impact |
| :--- | :---: | :---: | :--- |
| **Max Intraday Loss Budget ($B_{\text{daily, max}}$)** | ₹5,000 (or 5.0% of default ₹100k balance) | `GOVERNANCE_PENDING` | Halts simulated order execution for the remainder of the session when breached. |
| **Max Portfolio Heat ($H_{\text{max}}$)** | 20.0% of available capital | `GOVERNANCE_PENDING` | Restricts total committed option premium across all active positions to ₹20,000. |
| **Max Concurrent Positions ($N_{\text{max}}$)** | 2 active positions | `GOVERNANCE_PENDING` | Prevents over-trading and operational overwhelm during fast market moves. |
| **Correlated Directional Cluster Cap** | 1 position per direction | `GOVERNANCE_PENDING` | Blocks taking simultaneous CE (or PE) positions in both NIFTY and BANK NIFTY. |
| **Max Portfolio Theta Burden** | ₹-2,000 / day | `GOVERNANCE_PENDING` | Prevents overnight or multi-contract time-decay bleed. |

> [!WARNING]
> None of these numerical thresholds will be enforced in production or active live trading until explicitly authorized. During offline development, they will be tested using isolated mock configuration objects.

---

## 5. Pre-Live Defect Remediation Plan

The pre-live reliability defect (`DEFECT-PRELIVE-01: next_session_engine.py NoneType Greeks Subscript Exception`) is isolated from Phase 7:

```
[ Pre-Live Reliability Defect Remediation ]
Location: backend/app/options/next_session_engine.py:333-335
Action: Add safe null guards when calculate_black_scholes returns None.
Timing: Can be executed as an independent reliability bug fix prior to Monday live validation.
```

---

## 6. Execution Safety Commitments

1. **STRICT READ-ONLY:** No implementation code or test files will be authored until explicit user authorization is granted.
2. **PAPER_TRADING_ONLY:** Zero real broker order routing; zero real capital risk.
3. **SENSEX GOVERNANCE_LOCKED:** SENSEX remains permanently unconfigured.
4. **ML WEIGHT FREEZE:** Zero changes to `ml_strategy_weights.json`.
5. **BASELINE HASH PRESERVATION:** All six protected persistence baseline SHA-256 hashes will remain 100% identical.

