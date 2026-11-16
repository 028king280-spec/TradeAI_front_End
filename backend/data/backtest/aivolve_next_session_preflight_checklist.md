# AIVOLVE v3.0 — Next-Session Market Opening Preflight Verification Checklist

**Document Version:** 1.0 (Institutional Operational Readiness)  
**Target Market Session:** Next NSE Regular Trading Day (09:15 to 15:30 IST)  
**Execution Mode:** STRICT `PAPER_TRADING_ONLY` (Zero Live Broker Orders, Zero Real Capital)  
**Governing Standard:** Phase 4.10 Controlled Paper Observation Gate  

---

## 1. Preflight Verification Checklist (Execution Sequence: 09:00 - 09:18 IST)

The following operational checklist must be executed sequentially before requesting authorization for controlled live paper observation:

| Step # | Time Window (IST) | Check / Gate | Target Expected Result | Verification Endpoint / Method | Gate Status |
| :---: | :---: | :--- | :--- | :--- | :---: |
| **1** | 09:00 - 09:05 | **Angel One Authentication** | Active JWT session, client `S1821785`, zero token expiry | `GET /api/market/status` $\to$ `feedConnected: true` | [ ] PENDING |
| **2** | 09:05 - 09:08 | **Instrument Master Scrip Map** | Fresh contract tokens indexed for current weekly expiry | `GET /api/market/status` $\to$ `indexedContracts > 140,000` | [ ] PENDING |
| **3** | 09:08 - 09:14 | **Pre-Market Opening Outlook** | GIFT Nifty drift, overnight range & expected opening zone | `GET /api/options/NIFTY%2050/next-session/opening-outlook` | [ ] PENDING |
| **4** | 09:15:00 | **Market Calendar State** | Transition from `CLOSED` to `OPEN` (Trading hours) | `MarketCalendar.is_market_open() == True` | [ ] PENDING |
| **5** | 09:15 - 09:16 | **WebSocket Mode 3 Tick Reception** | Stream status transitions from `CONNECTED_WAITING_TICKS` to `STREAMING` | `GET /api/live/status` $\to$ `status: STREAMING`, `is_healthy: true` | [ ] PENDING |
| **6** | 09:15 - 09:16 | **Tick Freshness & Latency** | `seconds_since_last_tick < 3.0s`, zero future ticks ($>+5$s), zero duplicates | `GET /api/live/efficiency` $\to$ `stale_ticks: 0`, `duplicate_packets: 0` | [ ] PENDING |
| **7** | 09:16 - 09:17 | **Underlying Live Quote Streaming** | NIFTY spot verified live with non-zero volume & opening range | `GET /api/live/quote/NIFTY%2050` $\to$ `dataStatus: LIVE` | [ ] PENDING |
| **8** | 09:16 - 09:17 | **Canonical ATM Option Quotes** | Current weekly ATM CE & PE live LTP, bid/ask spread $< ₹2.00$, Greeks active | `GET /api/options/NIFTY%2050/option-chain` $\to$ `quoteStatus: AVAILABLE` | [ ] PENDING |
| **9** | 09:16 - 09:18 | **Candle Completion Integrity** | 1m/5m completed bar checks; incomplete bars quarantined | `filter_completed_candles()` $\to$ `failures: 0` | [ ] PENDING |
| **10**| 09:18+ | **Signal Qualification Gate** | If setup conditions not met, log `NO_TRADE` with explicit reason | `/api/options/NIFTY%2050/analysis` $\to$ `hasQualifiedSetups` | [ ] PENDING |

---

## 2. Hard Governance Rules & Invariants

1. **Strict Fail-Closed Mandate:**  
   If any check (Steps 1 through 9) fails or reports `DEGRADED`, `STALE`, or `DATA_OFFLINE`, paper execution remains **strictly blocked**.
2. **No Fallback / No Synthetic Substitution:**  
   Never substitute EOD settlement quotes, cached REST prices, historical replay data, or Black-Scholes theoretical estimates as active market quotes.
3. **Continuous `NO_TRADE` Recording:**  
   During range-bound, choppy, or non-confluent market states, the engine must continue recording `NO_TRADE` decisions with explicit structural rejection reasons.
4. **Explicit User Authorization Gate:**  
   Do not enable automated or manual paper execution until this preflight checklist is executed and explicit authorization is granted by the user.
5. **Phase 5 Prohibition:**  
   Phase 5 (ML/Neural Network Live Training & Execution) remains **STRICTLY NOT STARTED**.
6. **BSE SENSEX:**  
   BSE SENSEX remains strictly **`GOVERNANCE_LOCKED`**.

---

## 3. Cryptographic Baseline Verification at Stand-Down

All 6 institutional persistence files are verified 100% identical to accepted immutable baselines:
- `backend/aivolve_trading.db`: `C85C49BE76DEE405...` (**MATCH**)
- `backend/app/data/governance_ledger.db`: `4B12B3BAB44BF913...` (**MATCH**)
- `backend/app/data/paper_trading_records.json`: `00F968EF85095EB7...` (**MATCH**)
- `backend/app/data/ml_trade_dataset.json`: `87EEA8802835BB4F...` (**MATCH**)
- `backend/app/data/what_ai_learned.json`: `3ED015726DFF3090...` (**MATCH**)
- `backend/app/data/ml_strategy_weights.json`: `C3C495F36214BD7F...` (**MATCH**)

