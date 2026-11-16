# AIVOLVE v3.0 — Phase 7: Dynamic Risk Management & Capital Defense Specification

**Document Version:** 3.0.0  
**Phase:** Phase 7 — Dynamic Risk Management & Capital Defense Engine (Engine 10)  
**Governing Standard:** AIVOLVE Master Development Specification v3.0 (Engine 10 / Blueprint Phase 07)  
**Execution Policy:** STRICTLY `PAPER_TRADING_ONLY` (Read-Only Specification & Architectural Planning)  
**Target Instruments:** NIFTY 50, BANK NIFTY, FINNIFTY (SENSEX `GOVERNANCE_LOCKED`)  
**Specification Date:** 14 November 2026 (Saturday Standby Session)  

---

## 1. Executive Summary & Objective

In accordance with the **AIVOLVE Master Development Specification v3.0** (Engine 10: *Dynamic Risk Management Engine*), Phase 7 defines the mathematical, algorithmic, and governance specifications for the real-time capital preservation architecture of the AIVOLVE trading intelligence platform.

### Core Blueprint Mandates
1. **Principle 1:** *"Capital preservation comes before trade frequency."*
2. **Principle 6:** *"No automatic live broker execution."*
3. **Principle 8:** *"Every simulated execution must be auditable."*
4. **Principle 10:** *"Never overwrite historical trading records."*

In benchmark Indian equity index options (NIFTY, BANK NIFTY, FINNIFTY), option buyers face asymmetric, non-linear risk decay:
- **Non-Linear Premium Decay:** Premium loss acceleration near strike invalidation and accelerated theta decay into expiry cannot be approximated by linear underlying delta multiples.
- **Intraday Drawdown Cascades:** Sequential losses during choppy or expanding market regimes rapidly erode capital if trade frequency and cumulative daily loss are not strictly bounded.
- **Multi-Index Correlated Concentration:** Simultaneous long exposures across highly correlated underlying assets (e.g. NIFTY 50 and BANK NIFTY, $\rho > 0.75$) multiply directional drawdown during sudden market shocks.
- **Execution Friction & Spread Crossing:** Bid-ask spread crossing and execution slippage represent deterministic friction that must be accounted for at entry and exit to prevent illusionary theoretical edge.

The primary objective of Phase 7 is to provide **deterministic portfolio risk budgeting, non-linear scenario repricing, intraday drawdown circuit breakers, multi-index exposure governance, and dynamic trailing stop mechanisms** that mathematically enforce capital defense across all simulated and observation trades.

---

## 2. Scope Boundaries & Governance Invariants

### 2.1 In-Scope Scope Boundaries
- **Non-Linear Scenario Repricing:** Black-Scholes-Merton scenario repricing for stop-loss and multiple profit targets under holding-time decay and volatility stress.
- **Conservative Execution & Friction Modeling:** Strict entry execution at Ask, exit modeling at scenario Bid (mid minus half-spread) less execution slippage, eliminating double-counting.
- **Reward-to-Risk (R:R) Quantification:** Independent, uncompromised hurdle validation for $RR_{T1}$, $RR_{T2}$, and $RR_{T3}$.
- **Intraday Drawdown Circuit Breaker:** Real-time tracking of cumulative daily realized and floating P&L against an approved daily risk budget, halting new order generation upon breach.
- **Multi-Index Correlated Exposure Limits:** Enforcing maximum concurrent positions, maximum capital allocation (portfolio heat), and directional correlation caps across NIFTY 50, BANK NIFTY, and FINNIFTY.
- **Portfolio-Level Greeks Monitoring:** Tracking net aggregate portfolio Delta, Gamma, Theta decay burden (₹/day), and Vega exposure across all open positions.
- **Dynamic Trailing Stop & Partial Exits:** Automated 50% partial exit at Target 1 with runner stop-loss ratcheted to breakeven (entry premium).
- **Statutory Cost Conservation:** Integration with the full Indian statutory fee schedule (STT, Exchange, GST, SEBI turnover, Stamp duty, Brokerage).

### 2.2 Strictly Out-of-Scope (Prohibited)
- **Zero Real Capital or Broker Orders:** Architecture strictly operates in `PAPER_TRADING_ONLY` mode. Real broker API order endpoints remain physically isolated and disabled.
- **Zero ML Model Retraining or Weight Updating:** Strategy weights and ML parameters remain cryptographically frozen at baseline hash `C3C495F36214BD7FA58DDCA3C7F0280C14E15EB08DF41F868704F724C2A4E2FC`.
- **Zero SENSEX Activation:** SENSEX remains strictly `GOVERNANCE_LOCKED` (`UNCONFIGURED`).
- **No Unapproved Numerical Threshold Inventions:** Specific policy limits (e.g. max daily loss ₹5,000, 20% portfolio heat) are modeled as configurable parameters. Any unapproved numerical value is strictly labeled `GOVERNANCE_PENDING` until authorized.
- **Zero Overwriting of Historical Logs:** Historical trade records in `paper_trading_records.json` and `governance_ledger.db` are append-only.

---

## 3. Mathematical & Algorithmic Formulations

```
========================================================================================
                      AIVOLVE PHASE 7 DYNAMIC RISK ENGINE FLOW
========================================================================================

  [ Underlying Setup ]   [ Option Contract ]   [ Portfolio State ]   [ Macro State ]
           │                      │                     │                   │
           └──────────────┬───────┴─────────────────────┴───────────────────┘
                          │
                          ▼
         ┌───────────────────────────────────┐
         │  1. Pre-Trade Portfolio Defense   │ ◄── Max Daily Loss Breached?
         │     & Circuit Breaker Gate        │ ◄── Max Portfolio Heat Exceeded?
         └─────────────────┬─────────────────┘ ◄── Correlated Index Cap Hit?
                           │ (PASS)
                           ▼
         ┌───────────────────────────────────┐
         │  2. Non-Linear Black-Scholes      │ ◄── Adverse IV Stress @ SL (-5%)
         │     Scenario Repricing Engine     │ ◄── Holding Time Decay Horizon
         └─────────────────┬─────────────────┘ ◄── Bid/Ask Half-Spread & Slippage
                           │
                           ▼
         ┌───────────────────────────────────┐
         │  3. Reward-to-Risk Hurdle Check   │ ◄── RR_T1 >= 0.50
         │     (Zero Concealment Policy)     │ ◄── RR_T2 >= 1.25 (Master Hurdle)
         └─────────────────┬─────────────────┘ ◄── RR_T3 >= 1.50
                           │ (PASS)
                           ▼
         ┌───────────────────────────────────┐
         │  4. Zero-Invention Position Sizer │ ◄── Allocated Lots = min(Risk, Cap)
         │     & Lot Allocation Engine       │ ◄── Max Lot Cap Guard
         └─────────────────┬─────────────────┘
                           │
                           ▼
         ┌───────────────────────────────────┐
         │  5. Active Position Monitoring    │ ◄── Real-time MFE / MAE Tracking
         │     & Dynamic Stop Ratchet        │ ◄── T1 Hit -> 50% Exit & SL to Cost
         └───────────────────────────────────┘
========================================================================================
```

### 3.1 Non-Linear Option Premium Repricing Formulation
Linear approximations ($\Delta P \approx \Delta \times \Delta S$) fail significantly under large underlying moves and holding-time decay. Phase 7 mandates exact European Black-Scholes-Merton scenario repricing:

$$C(S, K, t, r, q, \sigma) = S e^{-q t} N(d_1) - K e^{-r t} N(d_2)$$

$$P(S, K, t, r, q, \sigma) = K e^{-r t} N(-d_2) - S e^{-q t} N(-d_1)$$

Where:
$$d_1 = \frac{\ln(S / K) + \left(r - q + \frac{1}{2}\sigma^2\right)t}{\sigma \sqrt{t}}, \quad d_2 = d_1 - \sigma \sqrt{t}$$

For Indian benchmark index options:
- Dividend yield $q = 0.0$ (European cash-settled index options).
- Risk-free rate $r = 0.065$ (RBI 91-day T-Bill reference).
- Time to expiry $t$ dynamically decremented based on scenario holding horizons:
  $$t_{\text{scenario}} = \max\left(0, t_0 - \frac{H_{\text{scenario}} \times 60}{365 \times 86400}\right)$$
  - $H_{SL} = 30.0 \text{ min}$ (Stop-loss scenario horizon).
  - $H_{T1} = 45.0 \text{ min}$ (Target 1 scenario horizon).
  - $H_{T2} = 75.0 \text{ min}$ (Target 2 scenario horizon).
  - $H_{T3} = 120.0 \text{ min}$ (Target 3 scenario horizon).
  *(Note: Holding horizons are documented as uncalibrated quantitative scenario assumptions).*

#### Implied Volatility Stress Adjustment
To reflect real-world option dynamics during adverse moves (IV crush upon breakdown failure or reversal):
- Adverse IV Stress at Stop-Loss: $\sigma_{SL} = \max(0.01, \sigma_0 \times (1.0 + \Delta\sigma_{SL}))$, where $\Delta\sigma_{SL} = -5\%$.
- Favorable IV Stress at Targets: $\sigma_{Target} = \max(0.01, \sigma_0 \times (1.0 + \Delta\sigma_{Target}))$, where $\Delta\sigma_{Target} = +2\%$.

### 3.2 Conservative Execution Pricing & Double-Counting Elimination
To ensure execution assumptions reflect true exchange friction without double-counting:

1. **Entry Fill Model:** Modeled strictly at quoted Ask:
   $$P_{\text{entry}} = \text{Ask}$$
2. **Exit Fill Model:** Modeled at scenario Bid less execution slippage:
   $$P_{\text{exit, raw}} = \text{BS}(S_{\text{scenario}}, K, t_{\text{scenario}}, r, \sigma_{\text{scenario}}, \text{type})$$
   $$\text{Half-Spread } \Delta_{\text{spread}} = \max\left(\text{TickSize}, \frac{\text{Ask} - \text{Bid}}{2}\right)$$
   $$P_{\text{exit, net}} = P_{\text{exit, raw}} - \Delta_{\text{spread}} - \text{SlippagePts}$$
3. **Conservative Tick Rounding:**
   $$\text{RoundFloor}(P, \text{Tick}) = \left\lfloor \frac{P}{\text{Tick}} + 10^{-9} \right\rfloor \times \text{Tick}$$
   Stop-loss and targets are floored to exchange tick ($0.05$) to understate exit proceeds and prevent optimistic fills:
   $$P_{SL} = \text{RoundFloor}(P_{SL, \text{net}}, 0.05)$$
   $$P_{T_i} = \text{RoundFloor}(P_{T_i, \text{net}}, 0.05)$$

### 3.3 Independent Reward-to-Risk Qualification
Risk per unit and target rewards are evaluated independently with **zero concealment**:

$$\text{Risk Per Unit} = P_{\text{entry}} - P_{SL}$$

$$\text{Reward}(T_i) = P_{T_i} - P_{\text{entry}}$$

$$RR(T_i) = \frac{\text{Reward}(T_i)}{\text{Risk Per Unit}}$$

Qualification Hurdles:
- $RR(T_1) \ge 0.50$ (Quick momentum scaling check).
- $RR(T_2) \ge 1.25$ (Authoritative trade qualification threshold).
- $RR(T_3) \ge 1.50$ (Extended trend runner hurdle).

If $RR(T_2) < 1.25$ or $P_{SL} \le 0$ or $P_{SL} \ge P_{\text{entry}}$, the trade is **REJECTED** with explicit rejection codes (`UNFAVORABLE_REWARD_TO_RISK`, `INVALID_OPTION_STOP_GEOMETRY`).

### 3.4 Zero-Invention Capital Allocation & Position Sizing
Position sizing enforces the zero-invention principle: if no risk budget is explicitly provided or authorized, position sizing status is set to `UNAVAILABLE` rather than inventing an assumed percentage.

When a risk budget $B_{\text{risk}}$ (INR) and capital $C_{\text{avail}}$ (INR) are authorized:

$$\text{Risk Per Lot} = \text{Risk Per Unit} \times \text{LotSize}$$

$$\text{Exposure Per Lot} = P_{\text{entry}} \times \text{LotSize}$$

$$\text{Lots}_{\text{risk}} = \left\lfloor \frac{B_{\text{risk}}}{\text{Risk Per Lot}} \right\rfloor, \quad \text{Lots}_{\text{capital}} = \left\lfloor \frac{C_{\text{avail}}}{\text{Exposure Per Lot}} \right\rfloor$$

$$\text{Allocated Lots} = \min\left(\text{Lots}_{\text{risk}}, \text{Lots}_{\text{capital}}, \text{MaxLotsCap}\right)$$

If $\text{Allocated Lots} < 1$, status is `INSUFFICIENT_CAPITAL` and order execution is rejected.

### 3.5 Intraday Drawdown Circuit Breaker
The portfolio risk engine tracks cumulative daily performance in real-time across both closed and open positions:

$$L_{\text{realized, daily}} = \sum_{t \in \text{ClosedToday}} \text{NetPnL}(t)$$

$$L_{\text{unrealized, daily}} = \sum_{p \in \text{OpenPositions}} \text{FloatingPnL}(p)$$

$$L_{\text{net, daily}} = L_{\text{realized, daily}} + L_{\text{unrealized, daily}}$$

$$\text{If } L_{\text{net, daily}} \le -B_{\text{daily, max}}: \quad \text{CircuitBreaker} = \text{TRIGGERED}$$

Upon trigger:
- Portfolio risk state transitions to `DAILY_DRAWDOWN_BREACHED`.
- All subsequent setup evaluations are forced to `NO_TRADE` with reason code `DAILY_LOSS_LIMIT_REACHED`.
- Existing open positions are managed according to active stop-loss rules (or defensive early exit if configured).

### 3.6 Multi-Index Correlated Exposure Limits
To defend against systemic equity market drops, portfolio heat and cross-index correlation are bounded:

1. **Portfolio Heat Limit:** Total premium capital deployed across all active positions cannot exceed the authorized portfolio heat fraction:
   $$\text{Portfolio Heat} = \frac{\sum_{p \in \text{OpenPositions}} \text{MarginUsed}(p)}{C_{\text{total}}} \le H_{\text{max}}$$
2. **Maximum Concurrent Open Positions:**
   $$N_{\text{open}} \le N_{\text{max, positions}}$$
3. **Correlated Directional Exposure Cap:**
   NIFTY 50 and BANK NIFTY exhibit strong historical correlation ($\rho \approx 0.80$). If an active bullish position exists in NIFTY 50, a second bullish position in BANK NIFTY cannot exceed the correlated cluster cap:
   $$N_{\text{correlated, directional}} \le N_{\text{cluster, max}}$$

### 3.7 Aggregate Portfolio Greeks Risk Monitoring
The engine aggregates Greeks across all active positions to monitor structural portfolio exposure:

$$\Delta_{\text{net, portfolio}} = \sum_{p \in \text{OpenPositions}} \Delta_p \times \text{Lots}_p \times \text{LotSize}_p$$

$$\Gamma_{\text{net, portfolio}} = \sum_{p \in \text{OpenPositions}} \Gamma_p \times \text{Lots}_p \times \text{LotSize}_p$$

$$\Theta_{\text{net, portfolio}} = \sum_{p \in \text{OpenPositions}} \Theta_p \times \text{Lots}_p \times \text{LotSize}_p \quad (\text{₹ / calendar day})$$

$$\nu_{\text{net, portfolio}} = \sum_{p \in \text{OpenPositions}} \nu_p \times \text{Lots}_p \times \text{LotSize}_p \quad (\text{₹ / 1\% IV shift})$$

### 3.8 Dynamic Trailing Stop & Profit Protection (Target 1 Runner Rule)
To prevent profitable positions from decaying into losses:
1. **Target 1 Execution:** When observed market high reaches $P_{T1}$:
   - 50% of position lots are closed at $P_{T1}$.
   - Realized profit and statutory costs for 50% are booked.
2. **Breakeven Stop Ratchet:** For the remaining 50% runner lots:
   $$SL_{\text{runner}} = P_{\text{entry}}$$
   The stop-loss is raised immediately from initial $P_{SL}$ to entry premium $P_{\text{entry}}$, mathematically locking the runner against net capital loss.
3. **Target 2 Full Exit:** When observed market high reaches $P_{T2}$, remaining 50% runner is closed in full.

### 3.9 Statutory Cost Conservation (NSE Derivatives Schedule)
Full double-entry cost reconciliation via `IndianDerivativesCostCalculator`:

$$\text{Brokerage} = 20.0 \times \text{OrderLegs}$$

$$\text{STT} = 0.001 \times P_{\text{exit}} \times Q \quad (\text{Sell-side option turnover})$$

$$\text{Exchange Fee} = 0.0005 \times (P_{\text{entry}} + P_{\text{exit}}) \times Q$$

$$\text{GST} = 0.18 \times (\text{Brokerage} + \text{Exchange Fee})$$

$$\text{SEBI Turnover} = 10^{-7} \times (P_{\text{entry}} + P_{\text{exit}}) \times Q$$

$$\text{Stamp Duty} = 0.00003 \times P_{\text{entry}} \times Q \quad (\text{Buy-side turnover})$$

$$\text{Total Costs} = \text{Brokerage} + \text{STT} + \text{Exchange Fee} + \text{GST} + \text{SEBI Turnover} + \text{Stamp Duty}$$

$$\text{Net P&L} = (P_{\text{exit}} - P_{\text{entry}}) \times Q - \text{Total Costs}$$

---

## 4. Phase 7 Requirement Breakdown & Blueprint Mapping

Every requirement is mapped to its exact specification origin in the Master Development Blueprint v3.0:

| Requirement ID | Component / Capability | Master Blueprint v3.0 Source | Description |
| :--- | :--- | :--- | :--- |
| **REQ-7.1** | Non-Linear Scenario Repricing | Blueprint Line 4509 (Engines 6, 7, 10) | Black-Scholes repricing for $P_{SL}, P_{T1}, P_{T2}, P_{T3}$ with holding decay and IV stress. |
| **REQ-7.2** | Conservative Fill & Friction Model | Blueprint Line 4509 (Engines 10, 17) | Entry strictly at Ask, exit at Bid less half-spread and slippage. No double-counting. |
| **REQ-7.3** | Independent R:R Qualification | Blueprint Line 4509 (Engine 10, Decision Outputs) | Separate evaluation of $RR_{T1}, RR_{T2}, RR_{T3}$; zero concealment of target hurdles. |
| **REQ-7.4** | Zero-Invention Position Sizing | Blueprint Line 4509 (Principle 1, Engine 10) | Capital and risk budgeting; status `UNAVAILABLE` if unconfigured. |
| **REQ-7.5** | Real-Time Intraday Drawdown Breaker | Blueprint Line 4509 (Principle 1, Engine 10) | Daily cumulative PnL tracking and circuit breaker halting new orders upon budget breach. |
| **REQ-7.6** | Multi-Index Exposure & Heat Limits | Blueprint Line 4509 (Engines 10, 17) | Global portfolio heat caps and cross-index correlated position limits (NIFTY/BANKNIFTY). |
| **REQ-7.7** | Portfolio Greeks Aggregator | Blueprint Line 4509 (Engines 7, 10) | Aggregate Net Delta, Gamma, Theta decay burden (₹/day), and Vega exposure monitoring. |
| **REQ-7.8** | Dynamic Stop Ratchet & Breakeven Lock | Blueprint Line 4509 (Engines 10, 17) | 50% partial exit at T1, runner stop-loss ratcheted to cost ($P_{\text{entry}}$). |
| **REQ-7.9** | Real-Time Excursion Tracking (MFE/MAE) | Blueprint Line 4509 (Self-Learning, Engine 10) | Continuous high/low tracking of adverse and favorable excursion per open trade. |
| **REQ-7.10** | Statutory Cost & Conservation Ledger | Blueprint Line 4509 (Principle 8, Engine 10) | Full statutory Indian tax deduction and double-entry P&L conservation. |

---

## 5. Acceptance Criteria & Quality Gates

To achieve Phase 7 completion, the implementation must satisfy all of the following deterministic criteria:
1. **Mathematical Invariant:** $P_{SL} < P_{\text{entry}} < P_{T1} \le P_{T2} \le P_{T3}$ strictly verified for all qualified trades.
2. **Hurdle Enforcement:** No trade qualifies if $RR_{T2} < 1.25$ or $P_{SL} \le 0$.
3. **Double-Counting Invariant:** Half-spread deduction and execution slippage must be independently tracked and verifiable in the audit payload.
4. **Drawdown Protection Gate:** Simulated order generation must fail closed (`NO_TRADE`, `DAILY_DRAWDOWN_BREACHED`) whenever cumulative daily loss breaches the daily risk budget.
5. **Correlation Defense Gate:** Concurrent long call/put orders across NIFTY and BANK NIFTY must be blocked if correlated cluster cap is reached.
6. **Breakeven Invariant:** Following Target 1 hit, the runner position's stop-loss must equal $P_{\text{entry}}$ in the persistence record.
7. **Zero Side-Effects:** Zero alterations to the 6 protected baseline hashes, zero live broker execution, zero ML weight modifications, and SENSEX remains strictly `GOVERNANCE_LOCKED`.
8. **Regression Suite Integrity:** 100% pass rate across all existing regression suites (127/127 tests) plus complete isolated coverage for all new Phase 7 risk components.

