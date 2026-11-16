# Future Execution Simulator Design Specification (Step 4.3+ Blueprint Only)

> **Governance Notice:** This document specifies the architectural interface and mathematical accounting rules for the **future** Phase 4 Execution Simulator. **No trade execution, order placement, fill matching, or P&L calculation is implemented in Step 4.2.**

Typed schema contracts and the `FutureExecutionSimulatorProtocol` interface live in `app/backtesting/models.py`.

---

## 1. Next Completed Bar Execution Policy (`ExecutionTimingPolicy.NEXT_COMPLETED_BAR_OPEN`)
- **Signal Evaluation Instant (`t_k`)**: Frozen Phase 3 intelligence reports (`MTFConfluenceReport`) are emitted strictly at the **closing timestamp `t_k`** of completed setup candles.
- **No Same-Bar Close Lookahead**: Decisions observed at `t_k` **MUST NOT** fill at bar `k`'s open, high, low, or close.
- **Entry Fill Window (`t_{k+1}`)**: Orders triggered after evaluating candle `k` enter execution queues for the **immediately following completed bar `k+1`** (filling at `open[k+1]` plus adverse spread/slippage if within permitted entry zone, or expiring/marking `MISSED` if opening price gaps past `entry_zone_max` per configured missed-entry threshold).
- **Exit Evaluations**: Evaluated chronologically across completed subsequent bars `[k+1, k+2, ...]` (and capped strictly before market EOD square-off if intraday).

---

## 2. Entry and Exit Fill Model (`FillPriceModelSpec`)
- **Conservative Option Premium Spread Handling**:
  - Long option buys enter at `ask` (when real Bid/Ask quotes are present) or `fill_ref + half_spread + slippage_pts`.
  - Long option exits settle at `bid` or `trigger_price - half_spread - slippage_pts`.
- **Exchange Tick Alignment**: Every simulated trigger/fill price aligns to instrument `tick_size` (`₹0.05` on NSE/BSE index options) using conservative adverse rounding (`ceil` on buy entry, `floor` on sell exit).
- **Zero Synthetic Spread Fabrication**: When Bid/Ask is absent (`OHLC-only`), spread assumptions must be declared explicitly inside `FillPriceModelSpec` and tagged in output manifests rather than claimed as exchange-observed Bid/Ask.

---

## 3. Intrabar Stop-Loss / Target Ambiguity (`IntrabarAmbiguityPolicy`)
- In bar-based OHLC simulation, when **both** Stop-Loss (`SL`) and Profit Target (`T1`/`T2`/`T3`) fall inside a single completed bar's `[low, high]` interval (and entry already existed prior to or at bar open):
  - **`CONSERVATIVE_SL_FIRST_WITH_AMBIGUOUS_TAG` (Default)**: Account conservatively assumes worst-case (`SL` triggered first) in conservative equity accounting **and** emits a mandatory `AMBIGUOUS_INTRABAR_TOUCH` outcome counter so reports never conceal unresolved bar ordering.
  - **`MARK_AMBIGUOUS_NO_FILL`**: Records the trade in an explicit `AMBIGUOUS` denominator bucket excluded from clean win-rate claims (matching `OutcomeTrackerService` transparency rules).
- No simulator may resolve ambiguous bars optimistically in favor of Profit Targets.

---

## 4. Brokerage, Statutory Costs and Slippage (`CostAndSlippageSpec`)
- Reuses verified NSE option tax rates (`IndianDerivativesCostCalculator`), extended with segment selection (`NFO` vs `BFO` for approved BSE derivatives):
  - **Brokerage**: `₹20.0` per executed order (`₹40` standard entry + exit; prorated per partial target leg).
  - **STT**: Sell-side option premium charge (`0.10%` current NSE sell premium turnover).
  - **Exchange Transaction Fee**: Segment-accurate rate on total premium turnover (`NSE NFO` vs `BSE BFO`).
  - **GST**: `18%` applied on `(brokerage + exchange_txn_charges + clearing_charges)`.
  - **SEBI Turnover Fee**: `0.000001` (`₹10 / Crore`) across total turnover.
  - **Stamp Duty**: `0.00003` (`0.003%`) on buy-side value.
  - **Slippage**: Explicit `slippage_points_per_leg * quantity` deducted per executed side.
- **Cash Balance Invariant (Fixes Legacy `PaperTradingEngine` Defect)**:
  - Simulated cash equity **MUST** follow: `ending_cash = starting_cash + sum(gross_realized_pnl) - sum(total_statutory_costs_and_slippage)`. Never credit exit proceeds without deducting full costs.

---

## 5. Segregated Simulation Domains (`SimulationDomainMode`)
AIVOLVE Phase 4 strictly prohibits mixing underlying index points with option INR premiums inside one PnL ledger:
1. **`UNDERLYING_POINTS_ONLY`**: Simulates structural Phase 3 directional hypotheses purely in underlying index points (gross points, MFE/MAE, ATR-normalized R-multiples, slippage in index points), **without claiming option-contract INR returns**.
2. **`OPTIONS_PREMIUM_SIMULATION`**: Simulates actual contract sizing (`lot_size * lots`), margin usage, capital allocation, and INR statutory charges over contract-level prices.

---

## 6. Explicit Option Data Provenance (`OptionDataMode`)
When `SimulationDomainMode == OPTIONS_PREMIUM_SIMULATION`, every trade & run manifest **MUST** carry a non-nullable `OptionDataMode`:
1. **`REAL_OPTION_OHLC`**: Driven strictly by genuine archived contract OHLCV / Bid-Ask observations for the historically active strike & expiry. Missing historical contracts MUST fail closed (`DATA_UNAVAILABLE` / `BLOCKED`) and **NEVER** fall back silently.
2. **`SYNTHETIC_BS_MODEL`**: Uses Black-Scholes analytical pricing/repricing over spot OHLCV when historical option bars are unavailable. Permitted **only** when explicitly requested by caller configuration, prominently watermarked `SYNTHETIC_BS_MODEL` across all reports, and segregated from live-parity institutional validation metrics.

