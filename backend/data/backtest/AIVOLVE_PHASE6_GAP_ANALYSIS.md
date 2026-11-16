# AIVOLVE v3.0 — Phase 6: Macro & Event Intelligence Gap Analysis

**Document Version:** 3.0.0  
**Phase:** Phase 6 — Macro, Event & Overnight Drift Engine (Engine 8)  
**Analysis Date:** 2026-11-14T14:35:00+05:30  
**Auditor Roles:** Senior Quantitative Architect & Institutional Systems Engineer  
**Scope:** Architectural Audit of Existing Capabilities vs Phase 6 Specification  

---

## 1. Executive Summary

This gap analysis compares the existing AIVOLVE v3.0 codebase against the newly articulated **Phase 6: Macro & Event Intelligence Specification** (`AIVOLVE_PHASE6_SPECIFICATION.md`).

AIVOLVE currently possesses robust real-time news parsing (`financial_news_provider.py`), market session state management (`market_calendar.py`), and mathematical overnight gap formulation (`opening_outlook.py`). However, **it lacks a structured, deterministic macroeconomic event calendar, scheduled release proximity tracking, and automated event blackout gating**.

---

## 2. Detailed Component-by-Component Gap Matrix

| Architectural Dimension | Existing Implementation in Repository | Target Phase 6 Specification Requirement | Gap Classification | Technical Remediation Needed |
| :--- | :--- | :--- | :--- | :--- |
| **1. Macro Calendar Storage & Schema** | `app/data/market_calendar.py` tracks only NSE exchange holidays and trading session hours. | Versioned, audited economic calendar (`app/data/macro_calendar.json` / SQLite) storing domestic and global release schedules. | **MISSING** | Create `MacroCalendarStore` with schema validation for event ID, scheduled timestamp, impact tier, and affected underlyings. |
| **2. Event Impact Classification** | `financial_news_provider.py` classifies RSS headline sentiment (Bullish/Bearish) and impact (High/Medium/Low) using regex keywords. | Structured, deterministic classification of scheduled macroeconomic releases into Tier 1 (Critical), Tier 2 (High), and Tier 3 (Medium). | **PARTIALLY_IMPLEMENTED** | Refactor keyword heuristic into authoritative schedule-driven `MacroEventTier` mapping (e.g. RBI MPC = Tier 1). |
| **3. Real-Time Event Proximity Engine** | None. Signal generation and order entry have zero awareness of scheduled announcement timing. | Real-time calculation of $t_{\text{now}} - T_{\text{event}}$. Gating: Pre-Event ($T-60$m to $T-15$m), Blackout ($T-15$m to $T+15$m), Realignment ($T+15$m to $T+60$m). | **MISSING** | Implement `EventProximityEngine` with sub-second distance calculation and market session alignment. |
| **4. Event Blackout Risk Gating** | `PaperTradingEngine` and `SignalClassifier` execute whenever technical/MTF/SMC conditions pass. | Unconditional fail-closed override to `WAIT` / `NO_TRADE` during Tier 1 Event Blackout window ($\pm 15$ minutes of announcement). | **MISSING** | Add `is_event_blackout` check into `SignalClassifier.classify()` and `PaperTradingEngine.open_position()`. |
| **5. Overnight Drift & Dispersion** | `opening_outlook.py` mathematically computes overnight volatility $\sigma_{\text{overnight}}$ via VIX and ATR, but uses fallback heuristics for GIFT Nifty. | Strict fail-closed GIFT Nifty drift integration; fallback marked explicitly as `GIFT_NIFTY_UNAVAILABLE` without fabricated drift. | **PARTIALLY_IMPLEMENTED** | Harden `calculate_next_session_opening_outlook()` to eliminate silent fallback drift when GIFT Nifty feed is missing. |
| **6. Data Provenance & Anti-Fabrication** | Financial news uses RSS feeds; sentiment uses deterministic weights. | Every calendar event must carry verified source attribution (`RBI_OFFICIAL`, `MOSPI`, `US_BLS`). Zero default/fabricated numbers. | **PARTIALLY_IMPLEMENTED** | Enforce source provenance checks and strict `DATA_UNAVAILABLE` status when upstream feeds drop. |
| **7. Feature Pipeline Integration** | `FeaturePipelineValidator` requires 14 numeric features; macro proximity is not in the feature vector. | Macro context (`event_tier`, `minutes_to_next_tier1`, `is_blackout`) available as contextual metadata without altering protected 14-feature baseline. | **MISSING** | Expose macro context through `marketFeaturesAtEntry["macroContext"]` to preserve Phase 5.2A schema backward compatibility. |
| **8. Frontend UI Visibility** | Next.js `/sentiment` shows RSS news feed; `/observer` shows signals; `/health` shows socket status. | Interactive Macro Economic Calendar card displaying upcoming releases, impact badges, and countdown timers. | **MISSING** | Build `MacroCalendarCard.tsx` in frontend and expose `/api/macro/calendar` endpoint. |
| **9. Test & Regression Coverage** | Zero tests exist for macroeconomic events, proximity math, or blackout gating. | Complete deterministic test suite covering event ingestion, proximity calculation, blackout overrides, and clean market trading. | **MISSING** | Create dedicated `tests/test_macro_event_engine_phase6.py`. |

---

## 3. Reusable Components & Dependencies

The following existing modules can be reused directly without re-engineering:

1. **`app.data.market_calendar.MarketCalendar`:**
   - Already provides timezone-aware IST timestamp normalization (`Asia/Kolkata`), market open/close validation, and holiday schedules.
2. **`app.data.quality_validator.FeedStatus`:**
   - Provides standardized status enums (`VERIFIED_LIVE`, `DATA_OFFLINE`, `DATA_UNAVAILABLE`) to tag macro data feeds.
3. **`app.options.opening_outlook.calculate_next_session_opening_outlook`:**
   - Contains the verified mathematical formula for overnight standard deviation ($\sigma_{\text{overnight}} = S_t \times \frac{\text{VIX}}{100} \times \frac{1}{\sqrt{252}} \times 0.45$).
4. **`app.options.paper_trading.label_engine.SignalClassifier`:**
   - Pure function design cleanly accepts external `macro_status` context to append structured rejection reasons.
5. **`app.options.paper_trading.paper_engine.PaperTradingEngine`:**
   - Position opening logic already includes validation gates (`_save_lock`, market open check) where macro blackout checks can cleanly hook in.

---

## 4. Key Risks & Technical Debt Identified

1. **External API Fragility:**
   - Public economic calendars (e.g. Investing.com, TradingEconomics) require paid APIs or web scraping, which violate stability and anti-scraping rules.
   - *Mitigation:* Deliver an audited, verified offline institutional calendar dataset (`macro_calendar.json`) covering 2026–2027 RBI MPC, Union Budget, and US FOMC dates, combined with an extensible REST endpoint for verified live updates.
2. **Baseline Hash Invariant Risk:**
   - Modifying `aivolve_trading.db`, `governance_ledger.db`, or `ml_trade_dataset.json` would violate the protected baseline integrity.
   - *Mitigation:* Maintain macro calendar data in a completely segregated file (`app/data/macro_calendar.json`), ensuring zero bytes of baseline files are modified.
3. **Over-Gating Risk:**
   - If blackout windows are configured too broadly (e.g., full day), trading will be starved of opportunities.
   - *Mitigation:* Restrict strict blackouts strictly to Tier 1 events (RBI MPC, Budget, FOMC) within a tight $\pm 15$ minute window, leaving Tier 2/3 events to position-sizing reductions ($50\%$) rather than full trade halts.

