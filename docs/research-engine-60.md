# Second research setup and paper engine

Profile: `research_60_target30_v1`. The production pipeline and its 70-point defaults are unchanged. Analysis runs an independent profile on the same market snapshot with both confluence gates at 60. Existing market-data, structure, contract/liquidity and risk checks apply. Score is not a calibrated win probability.

## Setups and simulated execution

The dashboard and index analysis display a separate research card. Evaluation runs when the analysis endpoint is requested; there is no autonomous setup scanner. Saved qualified observations now feed a background paper lifecycle job every 10 seconds during market hours. Browser closure stops new analysis-driven setups, but exits continue while the backend is running.

The second engine has a separate INR 100,000 virtual account, stored in paise. Entries buy one contract lot at fresh ask plus 5 basis points of modeled slippage, with INR 20 modeled entry fee. Target is filled entry premium × 1.30, rounded half-up to two decimals; original structural stop is retained. Premium reward/risk must remain at least 1.5. Entry quote must be at or after evaluation time, and ask must remain within 2% of the evaluated premium.

Exits use an observed executable bid, less 5 basis points slippage and INR 20 modeled exit fee. A bid at/above the target triggers `TARGET_30`, a bid at/below the stop triggers `STOP_LOSS`. After 15:25 IST a fresh quote triggers `SESSION_END`; entries are disabled. An unresolved position after missing end-of-day quotes closes on a subsequent valid market-session quote; no fabricated historical settlement is recorded. Model costs exclude GST and other statutory charges and are not broker-accurate fees.

A unique profile/day/contract ID prevents repeated polls, restarts or concurrent workers from reopening the same contract that day. A unique active slot allows one open position per underlying. Entry cash debit and trade insertion commit together. Conditional exit update and cash credit commit together, so concurrent closers cannot credit twice. Available cash excludes open-position capital; it is not total equity. Production paper balances and signal/performance tables are never written by this lifecycle.

## Quotes and outage behavior

Quote age must be at most 30 seconds, with verified source timestamp, real bid/ask depth and sufficient displayed size for one lot. Missing/fallback/stale/crossed/synthetic quotes, spread above 5%, or wrong contract/exchange reject fills. Angel One batch quotes now include additive source-depth/timestamp metadata without changing existing quote price fields. Other providers need equivalent verified metadata before they can execute research fills.

Missing quotes keep the position open with `DATA_GAP`. Recovery never backfills a missed intrapoll target/stop. A permanent `had_data_gap` flag survives recovery and closure; quote gaps above 30 seconds also flag it. Such outcomes require review before training. This is sampled paper execution, not a tick-perfect or live broker execution model.

## UI, storage and operations

Open **Paper trading → 60-point paper entries & exits** (`/paper-trading#research-paper`) for account cash, modeled realized P&L, quantity, entry, target, stop, exit reason, timestamps and monitoring status. The panel refreshes every 10 seconds and clearly marks fetch failures. Setup cards link to this account.

Restart backend after deployment: existing schema initialization creates `research_setup_evaluations`, `research_paper_accounts` and `research_paper_trades`. Keep the existing database persistent. `RESEARCH_PAPER_AUTO_ENTRY=true` is the default; put `RESEARCH_PAPER_AUTO_ENTRY=false` in backend `.env` and restart to disable new entries while continuing exit monitoring. Backend startup and scheduler must remain running. Configuration is server-side; no anonymous order/reset mutation endpoint was added.

- `GET /api/performance/research-evaluations?date=2026-11-17&symbol=NIFTY%2050&limit=100&offset=0`: IST-filtered observations with count independent of page size.
- `GET /api/performance/research-paper`: separate account, all-time realized modeled P&L, total count and latest 100 trades. Each trade links its evaluation ID and stores the original feature snapshot.

## Validation and limits

63 relevant backend tests passed offline, including 27 paper lifecycle tests, 13 research setup tests, 2 journal tests and 21 production pipeline regressions. Production build, TypeScript and new component lint checks passed. Offline tests cover exact cash/P&L, target/stop/session exits, wrong/stale/fallback quotes, insufficient cash, duplicate entry, concurrent closing, rollback on commit failure, restart recovery, quote ordering, persistent gap flags, and saved evaluation → scheduler → account HTTP response. Existing 70-point pipeline regression tests remain included. Browser-based visual verification and genuine provider-feed execution remain pending.

Only research paper trading is automated. No real broker order, WhatsApp delivery, partial/manual exit, or model retraining is added. Repeated observations are not independent trades; training datasets still need deduplication, reviewed outcome labels and time-based splits.
