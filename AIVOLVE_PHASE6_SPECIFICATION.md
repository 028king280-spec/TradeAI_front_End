# AIVOLVE v3.0 — Phase 6: Macro & Event Intelligence Specification

**Document Version:** 3.0.0  
**Phase:** Phase 6 — Macro, Event & Overnight Drift Engine (Engine 8)  
**Governing Standard:** AIVOLVE Master Development Specification v3.0 (Engine 8 / Blueprint Phase 06)  
**Execution Policy:** STRICTLY `PAPER_TRADING_ONLY` (Read-Only Specification & Pre-Implementation Discovery)  
**Target Instruments:** NIFTY 50, BANK NIFTY, FINNIFTY (SENSEX `GOVERNANCE_LOCKED`)  

---

## 1. Executive Summary & Objective

In accordance with the **AIVOLVE Master Development Specification v3.0** (Engine 8: *Macro and Event Intelligence Engine*), Phase 6 introduces an institutional-grade, deterministic macroeconomic and scheduled event surveillance system tailored specifically for Indian benchmark equity index derivatives.

In index options trading, scheduled macroeconomic releases and unexpected geopolitical flashpoints introduce non-linear volatility regime shifts:
1. **Implied Volatility Expansion & Post-Event IV Crush:** Premiums inflate significantly leading into scheduled high-impact events (e.g., RBI MPC rate decisions, Union Budget) and collapse immediately upon announcement, inflicting catastrophic losses on naked option buyers regardless of directional correctness.
2. **Severe Liquidity Black Holes & Spread Widening:** Market makers pull bid/ask liquidity quotes $5$ to $15$ minutes prior to scheduled releases, causing extreme slippage and crossed order books.
3. **Overnight Drift & Gap Risk:** Overnight macroeconomic developments (US FOMC, US CPI, crude oil shocks, GIFT Nifty drift) generate gap openings that can breach stop-losses beyond modeled risk budgets.

The objective of Phase 6 is to provide **deterministic event intelligence, proximity filtering, and capital protection guards** so that the trading system either adjusts risk exposure or enforces a strict fail-closed `EVENT_BLACKOUT` (`WAIT` / `NO_TRADE`) during dangerous macro windows.

---

## 2. Scope & Core Principles

### 2.1 Scope Boundaries
- **In Scope:**
  - Standardized economic calendar data structures for domestic (India) and global macro events.
  - Deterministic event impact tiering (Tier 1 High, Tier 2 Medium, Tier 3 Low).
  - Pre-event, in-event, and post-event proximity monitoring windows.
  - Event-driven signal suppression and position sizing overrides (`EVENT_RISK_GATED`).
  - Overnight drift integration linking GIFT Nifty / global cues to expected session opening dispersions.
  - Complete data provenance, source tracking, and audit logging.
  - Backward compatibility with Phase 1–4 engines, Phase 5.2A feature pipelines, and Phase 5.2B label classifiers.
- **Strictly Out of Scope:**
  - Real capital deployment or live broker order routing (`PAPER_TRADING_ONLY` enforced).
  - Unverified news scraping from untrusted blogs or social media feeds.
  - Fabricating synthetic consensus, forecast, or actual macro numbers.
  - Model training or strategy weight modification.
  - Unapproved numerical thresholds or arbitrary indicator inventions.
  - Removing SENSEX governance lock (SENSEX remains `UNCONFIGURED`).

---

## 3. Macro Event Classification & Taxonomy

Events are categorized into standardized institutional classes with explicit market impact tiers:

```
[ Macro / Event Intelligence ]
          │
  ┌───────┴───────┬───────────────┬────────────────┐
  ▼               ▼               ▼                ▼
Domestic Macro   Global Macro    Corporate/Earnings  Market Infrastructure
(RBI, CPI, GDP) (FOMC, Crude, US) (Index Heavyweights) (Expiries, Special Sessions)
```

### 3.1 Domestic Indian Macroeconomic Events (Primary Market Driver)

| Event Identifier | Description / Source Agency | Frequency | Impact Tier | Primary Affected Underlying | Typical Market Effect |
| :--- | :--- | :---: | :---: | :---: | :--- |
| `DOM-RBI-MPC` | RBI Monetary Policy Committee Rate Decision | Bi-monthly | **Tier 1 (Critical)** | BANK NIFTY, FINNIFTY, NIFTY 50 | Heavy IV expansion pre-event; sharp IV crush; interest-rate sensitive sector volatility. |
| `DOM-UNION-BUDGET` | Annual Union Budget of India (Ministry of Finance) | Annual (Feb 1) | **Tier 1 (Critical)** | ALL INDICES | Extreme multi-day volatility; large range expansion; sector-specific revaluations. |
| `DOM-ELECTION-GEN` | General Parliamentary / State Election Results (ECI) | Periodic | **Tier 1 (Critical)** | ALL INDICES | Binary gap openings; circuit breaker triggers; extreme trending or reversal days. |
| `DOM-CPI-INFL` | India Consumer Price Index (MoM/YoY) (MOSPI) | Monthly (12th) | **Tier 2 (High)** | BANK NIFTY, NIFTY 50 | Rate path expectations; bond yield adjustments; 20–50 pt immediate index reactions. |
| `DOM-GDP-QTR` | India Quarterly Gross Domestic Product (MOSPI) | Quarterly | **Tier 2 (High)** | NIFTY 50 | Macro health indicator; macro equity re-rating. |
| `DOM-IIP` | Index of Industrial Production (MOSPI) | Monthly (12th) | **Tier 3 (Medium)** | NIFTY 50 | Manufacturing and industrial demand indicator. |
| `DOM-WPI-INFL` | India Wholesale Price Index (Min of Commerce) | Monthly (14th) | **Tier 3 (Low)** | NIFTY 50 | Input cost pressures; wholesale inflation tracking. |

### 3.2 Global Macroeconomic & Geopolitical Events (Spillover & Gap Driver)

| Event Identifier | Description / Source Agency | Frequency | Impact Tier | Primary Affected Underlying | Typical Market Effect |
| :--- | :--- | :---: | :---: | :---: | :--- |
| `GLB-US-FOMC` | US Federal Reserve FOMC Rate Decision & Presser | 8x / Year | **Tier 1 (Critical)** | NIFTY 50, BANK NIFTY | Overnight global risk sentiment; currency valuation (USD/INR); FII liquidity flows. |
| `GLB-US-CPI` | US Consumer Price Index / Core CPI (BLS) | Monthly | **Tier 2 (High)** | NIFTY 50 | US Treasury yield reactions; global equity market opening gaps. |
| `GLB-US-NFP` | US Non-Farm Payrolls & Unemployment (BLS) | Monthly (1st Fri) | **Tier 2 (High)** | NIFTY 50 | Global growth expectations; dollar index (DXY) momentum. |
| `GLB-CRUDE-SURGE`| Brent Crude Oil Spot Price Shock ($> 3\%$ in 24h) | Event-driven | **Tier 2 (High)** | NIFTY 50 (Oil/Energy) | Current account deficit fears; inflation imported; pressure on Indian rupee. |
| `GLB-GEOPOL-ALERT`| Major geopolitical escalation / conflict outbreak | Event-driven | **Tier 1 (Critical)** | ALL INDICES | Global flight to safety (gold/dollar); heavy gap-down openings; VIX spike. |

### 3.3 Index Heavyweight Corporate Earnings (Micro-Structure Driver)

| Event Identifier | Description | Frequency | Impact Tier | Primary Affected Underlying | Typical Market Effect |
| :--- | :--- | :---: | :---: | :---: | :--- |
| `CORP-EARN-HDFC` | HDFC Bank Qtrly Earnings ($> 28\%$ BankNifty weight) | Quarterly | **Tier 2 (High)** | BANK NIFTY, FINNIFTY | Heavy opening gap; directional trend driver for banking sector. |
| `CORP-EARN-RELIANCE`| Reliance Industries Qtrly Earnings ($> 9\%$ Nifty weight)| Quarterly | **Tier 2 (High)** | NIFTY 50 | Major heavyweight directional impulse for NIFTY 50. |
| `CORP-EARN-ICICI` | ICICI Bank Qtrly Earnings ($> 22\%$ BankNifty weight) | Quarterly | **Tier 2 (High)** | BANK NIFTY | Banking index trend acceleration or resistance ceiling. |

---

## 4. Proximity Windows & Operational Gating Rules

Macro risk is non-stationary and strictly time-dependent relative to the scheduled announcement time $T_{\text{event}}$:

```
        T - 60m            T - 15m            T              T + 15m            T + 60m
───────────┼──────────────────┼───────────────┼─────────────────┼──────────────────┼───────────
  Normal   │   Pre-Event      │  BLACKOUT     │  IMPACT RELEASE │  VOLATILITY      │ Post-Event
  Trading  │   Volatility     │  (No Orders)  │  (High Slip)    │  REALIGNMENT     │ Normal
```

### 4.1 Proximity Window Definitions

1. **Pre-Event Warning Window ($T_{\text{event}} - 60\text{m}$ to $T_{\text{event}} - 15\text{m}$):**
   - Implied volatility starts pricing binary outcome.
   - *Engine Action:* Position sizing for new paper orders reduced by $50\%$. Tighten profit targets; disallow far-OTM long option purchases.
2. **Event Blackout Window ($T_{\text{event}} - 15\text{m}$ to $T_{\text{event}} + 15\text{m}$):**
   - Highest risk of wild bid/ask widening, sudden spikes, and IV crush.
   - *Engine Action:* **STRICT FAIL-CLOSED ORDER BLACKOUT.**
     - `SignalClassifier` unconditionally forces `WAIT` or `NO_TRADE` with reason:  
       `"Tier 1 Macro Event Blackout Active: [EventID] within ±15 minutes."`
     - `PaperTradingEngine` rejects all incoming simulated orders with `EVENT_BLACKOUT_ACTIVE`.
     - Open trailing stop-losses remain monitored, but new entries are 100% prohibited.
3. **Volatility Realignment Window ($T_{\text{event}} + 15\text{m}$ to $T_{\text{event}} + 60\text{m}$):**
   - The initial binary reaction has occurred; market establishes directional structure.
   - *Engine Action:* Allow new entries **only if** confirmed by both:
     - Multi-timeframe trend alignment (MTF score $\ge 75$).
     - Bid/ask spread returned to normal bounds ($< 2.5\%$).

---

## 5. Overnight Drift & Opening Dispersion Engine

Macro events occurring outside NSE trading hours (09:15–15:30 IST) impact next-session opening prices via overnight drift.

### 5.1 Mathematical Formulations
1. **Overnight Volatility Dispersion:**
   $$\sigma_{\text{overnight}} = S_t \times \left(\frac{\text{VIX}}{100}\right) \times \frac{1}{\sqrt{252}} \times \kappa_{\text{overnight}}$$
   Where:
   - $S_t$ = Previous session closing price of index spot.
   - $\text{VIX}$ = Closing India VIX.
   - $\kappa_{\text{overnight}} = 0.45$ (empirical proportion of daily variance occurring overnight for Indian markets).

2. **Blended Opening Range Dispersion:**
   $$\Delta_{\text{open\_spread}} = (0.28 \times \text{ATR}_{14}) + (0.40 \times \sigma_{\text{overnight}})$$

3. **GIFT Nifty Overnight Drift Alignment:**
   - If genuine pre-market GIFT Nifty drift points $\delta_{\text{GIFT}}$ are verified:
     $$S_{\text{expected\_open}} = S_t + \delta_{\text{GIFT}}$$
   - If GIFT Nifty is offline/unverified:
     $$S_{\text{expected\_open}} = S_t + \text{DirectionalBias}(S_t, H, L) \times \Delta_{\text{open\_spread}}$$
     *(Never substitute unverified external numbers; if unavailable, mark `GIFT_NIFTY_UNAVAILABLE`)*.

---

## 6. Data Provenance, Authenticity & Anti-Fabrication Invariants

In compliance with Core Development Principle 3 (*"No fake live market data"*):

1. **Deterministic Calendar Persistence:**
   - Calendar records must be stored in audited, versioned JSON/SQLite storage (`app/data/macro_calendar.json`).
   - Each event record must contain:
     - `eventId`: Unique institutional identifier (e.g. `DOM-RBI-MPC-20261204`).
     - `name`: Human-readable name.
     - `scheduledTimeIST`: ISO 8601 timestamp normalized to `Asia/Kolkata` (`+05:30`).
     - `tier`: `TIER_1_CRITICAL` | `TIER_2_HIGH` | `TIER_3_MEDIUM`.
     - `underlyings`: List of affected underlying symbols (`["NIFTY", "BANKNIFTY", "FINNIFTY"]`).
     - `source`: Official published source (e.g., `RBI_OFFICIAL`, `MOSPI_OFFICIAL`, `FED_OFFICIAL`).
     - `status`: `SCHEDULED` | `ACTIVE` | `RELEASED` | `CANCELLED`.
2. **Zero Fabrication Mandate:**
   - Never inject invented macro consensus, forecast, or outcome numbers into ML features or decision logs.
   - If an external macro feed is disconnected or fails to return verified data, the engine must return `DATA_OFFLINE` or `DATA_UNAVAILABLE`.
   - Missing macro features must be logged as `UNAVAILABLE` without default numerical padding.
3. **Storage Isolation:**
   - Macro calendar data must reside in its own isolated schema, strictly separated from the six protected baseline files (`aivolve_trading.db`, `governance_ledger.db`, `paper_trading_records.json`, `ml_trade_dataset.json`, `what_ai_learned.json`, `ml_strategy_weights.json`).

