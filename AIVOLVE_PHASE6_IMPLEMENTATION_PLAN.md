# AIVOLVE v3.0 — Phase 6: Macro & Event Intelligence Implementation Plan

**Document Version:** 3.0.0  
**Phase:** Phase 6 — Macro, Event & Overnight Drift Engine (Engine 8)  
**Target Milestone:** Offline Architectural Delivery & Test Verification  
**Author:** Senior Quantitative Architect & Institutional Systems Engineer  
**Execution Status:** **PLANNING ONLY — PENDING USER APPROVAL PRIOR TO IMPLEMENTATION**  
**Trading Mode:** `STRICTLY PAPER_TRADING_ONLY`  

---

## 1. Executive Implementation Strategy

Phase 6 implements the **Macro & Event Intelligence Engine (Engine 8)** to insulate simulated paper capital from binary macroeconomic shocks and post-announcement implied volatility crush.

To uphold the project's strict architectural invariants, Phase 6 is designed as a **zero-mutation, modular enhancement**:
1. It introduces standalone calendar models and proximity evaluators.
2. It interacts with `SignalClassifier` and `PaperTradingEngine` via non-invasive, fail-closed hooks.
3. It keeps macro datasets strictly segregated from the six cryptographically protected baseline files.
4. **Zero implementation code will be written until this plan is formally reviewed and approved by the user.**

---

## 2. Requirement Implementation Classification Matrix

Every requirement identified in the Phase 6 specification is classified into its governing operational state:

| Requirement / Module | Specific Technical Task | Implementation Classification | Dependency / Governance Guard |
| :--- | :--- | :---: | :--- |
| **REQ-6.1: Institutional Calendar Schema** | Define Pydantic/dataclass schema for `MacroEvent` with ID, timestamp, tier, underlyings, and source. | `OFFLINE_IMPLEMENTABLE` | Self-contained in Python dataclasses. |
| **REQ-6.2: Verified 2026–2027 Calendar Store** | Create versioned `macro_calendar.json` with official RBI MPC, Union Budget, and US FOMC dates. | `OFFLINE_IMPLEMENTABLE` | Uses published official exchange/central bank schedules. Isolated from baseline DBs. |
| **REQ-6.3: Event Proximity Engine** | Calculate $t_{\text{now}} - T_{\text{event}}$, outputting `NORMAL`, `PRE_EVENT_WARNING`, `EVENT_BLACKOUT`, `VOLATILITY_REALIGNMENT`. | `OFFLINE_IMPLEMENTABLE` | Timezone-normalized math via `MarketCalendar`. |
| **REQ-6.4: Fail-Closed Blackout Signal Override** | Hook proximity check into `SignalClassifier.classify()`; force `WAIT`/`NO_TRADE` during $\pm 15$m Tier 1 blackout. | `OFFLINE_IMPLEMENTABLE` | Pure function modification in `label_engine.py`. |
| **REQ-6.5: Paper Execution Blackout Rejection** | Prevent opening new simulated orders in `PaperTradingEngine` during active macro blackouts. | `OFFLINE_IMPLEMENTABLE` | Fail-closed check inside `PaperTradingEngine.open_position()`. |
| **REQ-6.6: Position Sizing & Target Buffering** | Scale position sizing to $50\%$ and disallow far-OTM long options during Pre-Event Warning window ($T-60$m to $T-15$m). | `OFFLINE_IMPLEMENTABLE` | Modifies lot allocation in risk calculations. |
| **REQ-6.7: Overnight Drift Hardening** | In `opening_outlook.py`, remove silent heuristic fallbacks; flag `GIFT_NIFTY_UNAVAILABLE` when external feed drops. | `ALREADY_IMPLEMENTED` / `OFFLINE_IMPLEMENTABLE` | Mathematical formulas exist; needs fail-closed status cleanup. |
| **REQ-6.8: Live Macro Calendar Feed Ingestion** | Ingest real-time economic calendar updates from external financial APIs. | `REQUIRES_EXTERNAL_DATA` | Requires trusted commercial macroeconomic API key; gated from offline builds. |
| **REQ-6.9: Live Session Event Reaction Tracking** | Capture actual tick-level option premium volatility and spread widening during live RBI/FOMC releases. | `REQUIRES_LIVE_MARKET_DATA` | Can only occur during an active live exchange session on an event date. |
| **REQ-6.10: Macro Volatility Policy Changes** | Approving changes to the $\pm 15$ minute blackout duration or impact tiering assignments. | `REQUIRES_GOVERNANCE_APPROVAL` | Any threshold modification requires explicit user sign-off. |
| **REQ-6.11: Frontend Macro Calendar Display** | Build interactive `MacroCalendarCard.tsx` on Next.js dashboard with countdown timers. | `OFFLINE_IMPLEMENTABLE` | Exposes `/api/macro/calendar` endpoint. |
| **REQ-6.12: Dedicated Phase 6 Automated Test Suite**| Create `tests/test_macro_event_engine_phase6.py` covering calendar ingestion, proximity math, and blackout triggers. | `OFFLINE_IMPLEMENTABLE` | Fully deterministic pytest suite. |

---

## 3. Step-by-Step Implementation Sequence

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           PHASE 6 IMPLEMENTATION STAGES                          │
├─────────────────┬─────────────────┬─────────────────┬───────────────────────────┤
│    STAGE 6.1    │    STAGE 6.2    │    STAGE 6.3    │         STAGE 6.4         │
│  Calendar Store │ Proximity Engine│ Risk & Signal   │  Tests, UI & Verification │
│   & Data Model  │ & Window Logic  │  Integration    │   (Full Regression Run)   │
└─────────────────┴─────────────────┴─────────────────┴───────────────────────────┘
```

### Stage 6.1: Macroeconomic Calendar Data Architecture & Store
- **Files to Create:**
  - `backend/app/options/macro/macro_models.py`: Defines `MacroEventTier` (`TIER_1_CRITICAL`, `TIER_2_HIGH`, `TIER_3_MEDIUM`), `MacroEvent`, and `EventProximityStatus`.
  - `backend/app/options/macro/macro_calendar_store.py`: Thread-safe, audited calendar repository reading from `backend/app/data/macro_calendar.json`.
  - `backend/app/data/macro_calendar.json`: Verified official schedule for RBI MPC meetings, Union Budget, and US FOMC dates for 2026.
- **Invariants:** Storage is completely isolated from the six protected baseline files.

### Stage 6.2: Real-Time Event Proximity Engine
- **File to Create:**
  - `backend/app/options/macro/macro_proximity_engine.py`:
    - Evaluates all scheduled events against current IST timestamp (`MarketCalendar.now_ist()`).
    - Resolves nearest upcoming event for a given underlying (`NIFTY`, `BANKNIFTY`, `FINNIFTY`).
    - Determines proximity window:
      - `NORMAL` ($\Delta t > 60$ minutes).
      - `PRE_EVENT_WARNING` ($15 \le \Delta t \le 60$ minutes).
      - `EVENT_BLACKOUT` ($-15 \le \Delta t < 15$ minutes).
      - `VOLATILITY_REALIGNMENT` ($-60 \le \Delta t < -15$ minutes).
      - `POST_EVENT_NORMAL` ($\Delta t < -60$ minutes).

### Stage 6.3: Risk Gating & Signal Classifier Integration
- **Files to Update (Minimal Diff):**
  - `backend/app/options/paper_trading/label_engine.py` (`SignalClassifier`):
    - Inject optional `macro_proximity: Optional[EventProximityStatus] = None`.
    - If `macro_proximity.is_blackout` is `True`, unconditionally output `SignalDecision.WAIT` / `NO_TRADE` with reason:
      `"Tier 1 Macro Event Blackout Active: [EventName] at [ScheduledTime]"`
  - `backend/app/options/paper_trading/paper_engine.py` (`PaperTradingEngine`):
    - In `open_position()`, if active blackout is detected on the underlying, reject order with `success = False`, message `"Order rejected: Macro event blackout window in progress."`

### Stage 6.4: Overnight Drift Hardening & Pre-Market Assessment
- **File to Refactor:**
  - `backend/app/options/opening_outlook.py`:
    - Ensure that when GIFT Nifty drift is unavailable, the output explicitly flags `driftSource = "HISTORICAL_ATR_FALLBACK"` and `dataStatus = "DATA_UNAVAILABLE"` without fabricating live GIFT Nifty prices.

### Stage 6.5: Dedicated Automated Test Suite & Regression Verification
- **File to Create:**
  - `backend/tests/test_macro_event_engine_phase6.py`:
    - Test 1: Calendar store loads and validates 2026 RBI/Budget/FOMC schedules.
    - Test 2: Pre-event warning window ($T-30$m) correctly flagged.
    - Test 3: Event blackout window ($T-5$m and $T+5$m) strictly triggers `is_blackout = True`.
    - Test 4: `SignalClassifier` overrides bullish signal to `WAIT` during Tier 1 blackout.
    - Test 5: `PaperTradingEngine` rejects new position entry during active blackout.
    - Test 6: Tier 3 event does not trigger a full trading blackout.
    - Test 7: Post-event realignment window transitions cleanly after 15 minutes.
    - Test 8: Re-verify all 6 protected baseline SHA-256 hashes.
- **Full Regression Verification:**
  - Execute all 8 test suites (Phase 5.2A, 5.2B, 5.2C, Monday Live, Phase D, Paper Engine, P0 Reliability, and Phase 6). Target: **105+ tests passed, 0 failures, exit code 0**.

### Stage 6.6: Frontend Macro Calendar Display
- **Files to Create / Update:**
  - `backend/app/api/routes/macro.py`: Exposes `GET /api/macro/calendar` and `GET /api/macro/proximity`.
  - `src/components/trading/MacroCalendarCard.tsx`: Next.js component displaying next scheduled releases, impact badges, and live countdown timers.

---

## 4. Verification & Acceptance Criteria

Phase 6 will be deemed complete and accepted only when:
1. **Zero Baseline Mutation:** All six protected SHA-256 hashes match baseline 100%.
2. **100% Deterministic Test Pass:** `pytest tests/test_macro_event_engine_phase6.py` and all prior regression suites pass cleanly with exit code `0`.
3. **Fail-Closed Blackout Verified:** Simulated orders submitted during mock event blackout windows are 100% rejected.
4. **Zero Fabrication:** Macro events carry verified source metadata; missing feeds report `DATA_UNAVAILABLE`.
5. **Next.js Frontend Build Clean:** `npm run build` compiles with zero TypeScript errors.

---

## 5. Execution Hold & Stop Protocol

```
🛑 STOP — EXECUTION HALTED PENDING USER REVIEW & AUTHORIZATION

Per the Master Development Specification and Phase 6 governance instructions:
- This document constitutes the implementation plan for Phase 6.
- NO CODE HAS BEEN WRITTEN OR MODIFIED.
- NO TEST HAS BEEN ALTERED.
- ZERO BASELINE FILES HAVE BEEN TOUCHED.
- Phase 6 implementation will begin ONLY upon receiving your explicit authorization:
  "PROCEED WITH PHASE 6 IMPLEMENTATION".
```

