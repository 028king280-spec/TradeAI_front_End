# AIVOLVE Phase 4 — Step 4.8 Strategy Performance & Evidence Review (`STE48-REVIEW-c0b4a81e7effd2`)

## 1. Executive Summary & Evidence Verdict
- **Execution Mode:** `PAPER_TRADING_ONLY`
- **Engine Version:** `4.8.0`
- **Review Fingerprint:** `c0b4a81e7effd277ade50b4c5324d0a7b670ac1030e4c1c949a00796dc33d634`
- **Overall Evidence Verdict:** **INSUFFICIENT_EVIDENCE**
- **Overall Sample Size Classification:** `INSUFFICIENT_SAMPLE`
- **Statistical Significance Claimed:** `False`
- **Auto Optimization Performed:** `False` | **Strategy Parameters Modified:** `False`
- **Disclaimer:** Research evidence classification only — NOT a live trade recommendation; no strategy parameters, weights, or risk limits were modified.
- **Key Verdict Reasons:**
  - Evaluated 5 VERIFIED run(s), 0 PARTIAL research-only run(s), and 2 REJECTED/LOCKED run(s).
  - INDEX_POINTS_ONLY: 5 closed trade(s) < minimum sufficient threshold (30); statistical reliability cannot be claimed (INSUFFICIENT_SAMPLE).
  - SYNTHETIC_OPTION_INR_ONLY (5 trades) is research-only via Black-Scholes; real historical options remain BLOCKED.

## 2. Data Sources & Step 4.6 Eligibility Matrix
- **Isolated Backtest DB:** `D:\ReactJs\aivolve-trading-ai\backend\data\backtest\backtest_foundation.db`
- **Step 4.7 Runs Evaluated:** `7`

| Instrument | Timeframe | Quality | Eligibility | Complete Sessions | Incomplete Excluded | Total Bars |
| --- | --- | --- | --- | ---: | ---: | ---: |
| NIFTY 50 | 1m | PARTIAL | PARTIAL_RESEARCH_ONLY | 10 | 8 | 6638 |
| NIFTY 50 | 3m | PARTIAL | PARTIAL_RESEARCH_ONLY | 10 | 21 | 3791 |
| NIFTY 50 | 5m | PARTIAL | PARTIAL_RESEARCH_ONLY | 10 | 33 | 3159 |
| NIFTY 50 | 15m | VERIFIED | VERIFIED_FULL_SESSION_ELIGIBLE | 106 | 0 | 2650 |
| NIFTY 50 | 1h | VERIFIED | VERIFIED_FULL_SESSION_ELIGIBLE | 245 | 0 | 1710 |
| NIFTY 50 | 1d | VERIFIED | VERIFIED_FULL_SESSION_ELIGIBLE | 711 | 0 | 711 |
| BANK NIFTY | 1m | PARTIAL | PARTIAL_RESEARCH_ONLY | 0 | 8 | 2888 |
| BANK NIFTY | 3m | PARTIAL | PARTIAL_RESEARCH_ONLY | 0 | 21 | 2541 |
| BANK NIFTY | 5m | PARTIAL | PARTIAL_RESEARCH_ONLY | 0 | 33 | 2409 |
| BANK NIFTY | 15m | PARTIAL | PARTIAL_RESEARCH_ONLY | 81 | 1 | 2049 |
| BANK NIFTY | 1h | PARTIAL | PARTIAL_RESEARCH_ONLY | 244 | 1 | 1709 |
| BANK NIFTY | 1d | VERIFIED | VERIFIED_FULL_SESSION_ELIGIBLE | 711 | 0 | 711 |
| FINNIFTY | 1m | PARTIAL | PARTIAL_RESEARCH_ONLY | 0 | 8 | 2888 |
| FINNIFTY | 3m | PARTIAL | PARTIAL_RESEARCH_ONLY | 0 | 21 | 2541 |
| FINNIFTY | 5m | PARTIAL | PARTIAL_RESEARCH_ONLY | 0 | 33 | 2409 |
| FINNIFTY | 15m | PARTIAL | PARTIAL_RESEARCH_ONLY | 81 | 1 | 2049 |
| FINNIFTY | 1h | PARTIAL | PARTIAL_RESEARCH_ONLY | 244 | 1 | 1709 |
| FINNIFTY | 1d | VERIFIED | VERIFIED_FULL_SESSION_ELIGIBLE | 711 | 0 | 711 |
| SENSEX | 1m | UNAVAILABLE | GOVERNANCE_LOCKED | 0 | 0 | 0 |
| SENSEX | 3m | UNAVAILABLE | GOVERNANCE_LOCKED | 0 | 0 | 0 |
| SENSEX | 5m | UNAVAILABLE | GOVERNANCE_LOCKED | 0 | 0 | 0 |
| SENSEX | 15m | UNAVAILABLE | GOVERNANCE_LOCKED | 0 | 0 | 0 |
| SENSEX | 1h | UNAVAILABLE | GOVERNANCE_LOCKED | 0 | 0 | 0 |
| SENSEX | 1d | UNAVAILABLE | GOVERNANCE_LOCKED | 0 | 0 | 0 |

## 3. Step 4.7 Revalidation Runs Reviewed
| Revalidation ID | Instrument | Primary TF | MTF Stack | Status | Eligibility | Sessions Eval | Excl Sessions | Signals | Eligible | Closed (Pts / ExpINR / SynBS) |
| --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| REVALRUN-5acfd6e991b165 | NIFTY 50 | 5m | 1h,15m,5m,3m,1m | COMPLETED | VERIFIED_FULL_SESSION_ELIGIBLE | 10 | 0 | 123 | 5 | 5 / 5 / 5 |
| REVALRUN-927d1cd9892346 | NIFTY 50 | 5m | 1h,15m,5m | REJECTED_DATASET_QUALITY | REJECTED_MIXED_QUALITY | 0 | 0 | 0 | 0 | 0 / 0 / 0 |
| REVALRUN-442271a91c3db2 | NIFTY 50 | 15m | 1h,15m | NO_ELIGIBLE_SIGNALS | VERIFIED_FULL_SESSION_ELIGIBLE | 70 | 0 | 35 | 0 | 0 / 0 / 0 |
| REVALRUN-26a8286a1c6174 | NIFTY 50 | 15m | 1h,15m | NO_ELIGIBLE_SIGNALS | VERIFIED_FULL_SESSION_ELIGIBLE | 35 | 0 | 18 | 0 | 0 / 0 / 0 |
| REVALRUN-00a88ca2c2e504 | BANK NIFTY | 15m | 1h,15m | NO_ELIGIBLE_SIGNALS | VERIFIED_FULL_SESSION_ELIGIBLE | 35 | 0 | 18 | 0 | 0 / 0 / 0 |
| REVALRUN-36fe1046093de8 | FINNIFTY | 15m | 1h,15m | NO_ELIGIBLE_SIGNALS | VERIFIED_FULL_SESSION_ELIGIBLE | 35 | 0 | 18 | 0 | 0 / 0 / 0 |
| REVALRUN-72d70f7c4e93a3 | SENSEX | 5m | 1h,15m,5m,3m,1m | GOVERNANCE_LOCKOUT | GOVERNANCE_LOCKED | 0 | 0 | 0 | 0 | 0 / 0 / 0 |

## 4. Domain-Isolated Performance Overview (Never Combined Across Domains)
| Accounting Domain | Provenance | Synthetic | Actual Hist Options | Closed Trades | Win Rate % | Net PnL | Profit Factor | Expectancy | Max DD | Sample Size | Verdict |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| INDEX_POINTS_ONLY | UNDERLYING_INDEX_POINTS_ONLY | False | BLOCKED | 5 | 40.00% | -8.65 pts | 0.83 | -1.73 pts | 35.10 pts | INSUFFICIENT_SAMPLE | INSUFFICIENT_EVIDENCE |
| INDEX_POINTS_AND_EXPLICIT_INR | UNDERLYING_INDEX_POINTS_WITH_EXPLICIT_INR_MULTIPLIER | False | BLOCKED | 5 | 40.00% | -648.75 INR | 0.83 | -129.75 INR | 2632.50 INR | INSUFFICIENT_SAMPLE | INSUFFICIENT_EVIDENCE |
| SYNTHETIC_OPTION_INR_ONLY | SYNTHETIC_MODELLED_OPTION_PNL | True | BLOCKED | 5 | 40.00% | -1082.66 INR | 0.52 | -216.53 INR | 1628.32 INR | INSUFFICIENT_SAMPLE | INSUFFICIENT_EVIDENCE |

## 5. Detailed Domain Metrics, Transaction Costs, Slippage & Drawdown
### 5.1 `INDEX_POINTS_ONLY` (`UNDERLYING_INDEX_POINTS_ONLY`)
- Eligible Runs: `5` (`REVALRUN-5acfd6e991b165, REVALRUN-442271a91c3db2, REVALRUN-26a8286a1c6174, REVALRUN-00a88ca2c2e504, REVALRUN-36fe1046093de8`) | Sessions: `185` | Signals: `212` | Closed Trades: `5` | Freq/Session: `0.0270`
- Consecutive Wins/Losses: `1` / `2` | Avg Hold (min): `18.00` | Ledger Reconciled: `True`
- **Index Points:** Gross=-3.60 | Total Slippage/Costs=5.05 | Net=-8.65 | AvgWin=21.15 | AvgLoss=-16.98 | R:R=1.25 | PF=0.83 | Expectancy=-1.73 | MaxDD=35.10 | Recovery=-0.25
- Verdict: `INSUFFICIENT_EVIDENCE` (INDEX_POINTS_ONLY: 5 closed trade(s) < minimum sufficient threshold (30); statistical reliability cannot be claimed (INSUFFICIENT_SAMPLE).)

### 5.2 `INDEX_POINTS_AND_EXPLICIT_INR` (`UNDERLYING_INDEX_POINTS_WITH_EXPLICIT_INR_MULTIPLIER`)
- Eligible Runs: `5` (`REVALRUN-5acfd6e991b165, REVALRUN-442271a91c3db2, REVALRUN-26a8286a1c6174, REVALRUN-00a88ca2c2e504, REVALRUN-36fe1046093de8`) | Sessions: `185` | Signals: `212` | Closed Trades: `5` | Freq/Session: `0.0270`
- Consecutive Wins/Losses: `1` / `2` | Avg Hold (min): `18.00` | Ledger Reconciled: `True`
- **Index Points:** Gross=-3.60 | Total Slippage/Costs=5.05 | Net=-8.65 | AvgWin=21.15 | AvgLoss=-16.98 | R:R=1.25 | PF=0.83 | Expectancy=-1.73 | MaxDD=35.10 | Recovery=-0.25
- **INR (EXPLICIT MULTIPLIER):** Gross=-270.00 | Total Slippage/Costs=378.75 | Net=-648.75 (-0.03%) | AvgWin=1586.25 | AvgLoss=-1273.75 | R:R=1.25 | PF=0.83 | Expectancy=-129.75 | MaxDD=2632.50 (0.13%) | Recovery=-0.25
- Verdict: `INSUFFICIENT_EVIDENCE` (INDEX_POINTS_AND_EXPLICIT_INR: 5 closed trade(s) < minimum sufficient threshold (30); statistical reliability cannot be claimed (INSUFFICIENT_SAMPLE).)

### 5.3 `SYNTHETIC_OPTION_INR_ONLY` (`SYNTHETIC_MODELLED_OPTION_PNL`)
- Eligible Runs: `5` (`REVALRUN-5acfd6e991b165, REVALRUN-442271a91c3db2, REVALRUN-26a8286a1c6174, REVALRUN-00a88ca2c2e504, REVALRUN-36fe1046093de8`) | Sessions: `185` | Signals: `212` | Closed Trades: `5` | Freq/Session: `0.0270`
- Consecutive Wins/Losses: `1` / `2` | Avg Hold (min): `15.00` | Ledger Reconciled: `True`
- **INR (SYNTHETIC BS RESEARCH ONLY):** Gross=-362.50 | Total Slippage/Costs=720.16 | Net=-1082.66 (-0.05%) | AvgWin=584.50 | AvgLoss=-750.55 | R:R=0.78 | PF=0.52 | Expectancy=-216.53 | MaxDD=1628.32 (0.08%) | Recovery=-0.66
- Verdict: `INSUFFICIENT_EVIDENCE` (SYNTHETIC_OPTION_INR_ONLY: 5 closed trade(s) < minimum sufficient threshold (30); statistical reliability cannot be claimed (INSUFFICIENT_SAMPLE).)

## 6. Chronological IS / OOS Split & Step 4.5 Robustness Digests
### `INDEX_POINTS_ONLY`
- IS/OOS Split (`2026-06-08T10:35:00+05:30..2026-06-16T09:35:00+05:30` vs `2026-06-16T10:05:00+05:30..2026-06-19T15:20:00+05:30`, NoLookahead=`True`): IS trades=2, OOS trades=3, IS Net=-33.90, OOS Net=25.25
- Step 4.5 Digest: Overall=`COMPLETED`, Slippage=`COMPLETED`, Cost=`NOT_APPLICABLE_IN_DOMAIN`, Regime=`COMPLETED`, OOS=`COMPLETED` (no_lookahead=`True`), MC=`COMPLETED` (250 iters, P(>0)=0.2480), AutoOpt=`False`

### `INDEX_POINTS_AND_EXPLICIT_INR`
- IS/OOS Split (`2026-06-08T10:35:00+05:30..2026-06-16T09:35:00+05:30` vs `2026-06-16T10:05:00+05:30..2026-06-19T15:20:00+05:30`, NoLookahead=`True`): IS trades=2, OOS trades=3, IS Net=-33.90, OOS Net=25.25
- Step 4.5 Digest: Overall=`COMPLETED`, Slippage=`COMPLETED`, Cost=`COMPLETED`, Regime=`COMPLETED`, OOS=`COMPLETED` (no_lookahead=`True`), MC=`COMPLETED` (250 iters, P(>0)=0.2480), AutoOpt=`False`

### `SYNTHETIC_OPTION_INR_ONLY`
- IS/OOS Split (`2026-06-08T10:35:00+05:30..2026-06-16T09:35:00+05:30` vs `2026-06-16T10:05:00+05:30..2026-06-19T15:20:00+05:30`, NoLookahead=`True`): IS trades=2, OOS trades=3, IS Net=-1510.91, OOS Net=428.26
- Step 4.5 Digest: Overall=`COMPLETED`, Slippage=`COMPLETED`, Cost=`COMPLETED`, Regime=`COMPLETED`, OOS=`COMPLETED` (no_lookahead=`True`), MC=`COMPLETED` (250 iters, P(>0)=0.2400), AutoOpt=`False`

## 7. Market Regime Breakdown
| Market Regime | Signals | Eligible | BUY_CE | BUY_PE | WAIT | NO_TRADE | Missing Meta | INDEX_POINTS_ONLY | INDEX_POINTS_AND_EXPLICIT_INR (INR) | SYNTHETIC_OPTION_INR_ONLY (Modelled BS) | Sample | Verdict |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | --- | --- | --- |
| BEARISH_TREND | 8 | 0 | 0 | 0 | 2 | 6 | False | 0 trades | 0 trades | 0 trades | INSUFFICIENT_SAMPLE | INSUFFICIENT_EVIDENCE |
| BULLISH_TREND | 39 | 5 | 5 | 0 | 27 | 7 | False | n=5 | Net=-8.65 | WR=40.00% | PF=0.83 | Exp=-1.73 | n=5 | Net=-648.75 | WR=40.00% | PF=0.83 | Exp=-129.75 | n=5 | Net=-1082.66 | WR=40.00% | PF=0.52 | Exp=-216.53 | INSUFFICIENT_SAMPLE | INSUFFICIENT_EVIDENCE |
| NO_TRADE | 89 | 0 | 0 | 0 | 0 | 89 | False | 0 trades | 0 trades | 0 trades | INSUFFICIENT_SAMPLE | INSUFFICIENT_EVIDENCE |
| REVERSAL | 27 | 0 | 0 | 0 | 12 | 15 | False | 0 trades | 0 trades | 0 trades | INSUFFICIENT_SAMPLE | INSUFFICIENT_EVIDENCE |
| SIDEWAYS | 49 | 0 | 0 | 0 | 0 | 49 | False | 0 trades | 0 trades | 0 trades | INSUFFICIENT_SAMPLE | INSUFFICIENT_EVIDENCE |

## 8. Trading Session Breakdown
- Sessions Evaluated Total: `185` | Excluded Incomplete Sessions: `0`

| Trading Session | Signals | Eligible | BUY_CE | BUY_PE | WAIT | NO_TRADE | Missing Meta | INDEX_POINTS_ONLY | INDEX_POINTS_AND_EXPLICIT_INR (INR) | SYNTHETIC_OPTION_INR_ONLY (Modelled BS) | Sample | Verdict |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | --- | --- | --- |
| AFTERNOON_1330_1500 | 30 | 1 | 1 | 0 | 13 | 16 | False | n=1 | Net=-17.05 | WR=0.00% | PF=0.00 | Exp=-17.05 | n=1 | Net=-1278.75 | WR=0.00% | PF=0.00 | Exp=-1278.75 | n=1 | Net=-772.46 | WR=0.00% | PF=0.00 | Exp=-772.46 | INSUFFICIENT_SAMPLE | INSUFFICIENT_EVIDENCE |
| CLOSING_1500_1530 | 10 | 1 | 1 | 0 | 3 | 6 | False | n=1 | Net=21.40 | WR=100.00% | PF=N/A | Exp=21.40 | n=1 | Net=1605.00 | WR=100.00% | PF=N/A | Exp=1605.00 | n=1 | Net=497.24 | WR=100.00% | PF=N/A | Exp=497.24 | INSUFFICIENT_SAMPLE | INSUFFICIENT_EVIDENCE |
| MIDDAY_1130_1330 | 129 | 1 | 1 | 0 | 11 | 117 | False | n=1 | Net=-16.85 | WR=0.00% | PF=0.00 | Exp=-16.85 | n=1 | Net=-1263.75 | WR=0.00% | PF=0.00 | Exp=-1263.75 | n=1 | Net=-738.45 | WR=0.00% | PF=0.00 | Exp=-738.45 | INSUFFICIENT_SAMPLE | INSUFFICIENT_EVIDENCE |
| MORNING_1000_1130 | 29 | 2 | 2 | 0 | 8 | 19 | False | n=2 | Net=3.85 | WR=50.00% | PF=1.23 | Exp=1.92 | n=2 | Net=288.75 | WR=50.00% | PF=1.23 | Exp=144.38 | n=2 | Net=-68.99 | WR=50.00% | PF=0.91 | Exp=-34.49 | INSUFFICIENT_SAMPLE | INSUFFICIENT_EVIDENCE |
| OPENING_0915_1000 | 14 | 0 | 0 | 0 | 6 | 8 | False | 0 trades | 0 trades | 0 trades | INSUFFICIENT_SAMPLE | INSUFFICIENT_EVIDENCE |

## 9. Instrument Breakdown & SENSEX Governance Lockout
| Instrument | Signals | Eligible | BUY_CE | BUY_PE | WAIT | NO_TRADE | Missing Meta | INDEX_POINTS_ONLY | INDEX_POINTS_AND_EXPLICIT_INR (INR) | SYNTHETIC_OPTION_INR_ONLY (Modelled BS) | Sample | Verdict |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | --- | --- | --- |
| BANK NIFTY | 18 | 0 | 0 | 0 | 0 | 18 | False | 0 trades | 0 trades | 0 trades | INSUFFICIENT_SAMPLE | INSUFFICIENT_EVIDENCE |
| FINNIFTY | 18 | 0 | 0 | 0 | 0 | 18 | False | 0 trades | 0 trades | 0 trades | INSUFFICIENT_SAMPLE | INSUFFICIENT_EVIDENCE |
| NIFTY 50 | 176 | 5 | 5 | 0 | 41 | 130 | False | n=5 | Net=-8.65 | WR=40.00% | PF=0.83 | Exp=-1.73 | n=5 | Net=-648.75 | WR=40.00% | PF=0.83 | Exp=-129.75 | n=5 | Net=-1082.66 | WR=40.00% | PF=0.52 | Exp=-216.53 | INSUFFICIENT_SAMPLE | INSUFFICIENT_EVIDENCE |

## 10. Timeframe Breakdown
| Timeframe | Signals | Eligible | BUY_CE | BUY_PE | WAIT | NO_TRADE | Missing Meta | INDEX_POINTS_ONLY | INDEX_POINTS_AND_EXPLICIT_INR (INR) | SYNTHETIC_OPTION_INR_ONLY (Modelled BS) | Sample | Verdict |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | --- | --- | --- |
| 15m | 89 | 0 | 0 | 0 | 0 | 89 | False | 0 trades | 0 trades | 0 trades | INSUFFICIENT_SAMPLE | INSUFFICIENT_EVIDENCE |
| 5m | 123 | 5 | 5 | 0 | 41 | 77 | False | n=5 | Net=-8.65 | WR=40.00% | PF=0.83 | Exp=-1.73 | n=5 | Net=-648.75 | WR=40.00% | PF=0.83 | Exp=-129.75 | n=5 | Net=-1082.66 | WR=40.00% | PF=0.52 | Exp=-216.53 | INSUFFICIENT_SAMPLE | INSUFFICIENT_EVIDENCE |

## 11. Direction, Entry Reason & Exit Reason Analysis
### 11.1 Direction
| Direction | Signals | Eligible | BUY_CE | BUY_PE | WAIT | NO_TRADE | Missing Meta | INDEX_POINTS_ONLY | INDEX_POINTS_AND_EXPLICIT_INR (INR) | SYNTHETIC_OPTION_INR_ONLY (Modelled BS) | Sample | Verdict |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | --- | --- | --- |
| BUY_CE | 5 | 5 | 5 | 0 | 0 | 0 | False | n=5 | Net=-8.65 | WR=40.00% | PF=0.83 | Exp=-1.73 | n=5 | Net=-648.75 | WR=40.00% | PF=0.83 | Exp=-129.75 | n=5 | Net=-1082.66 | WR=40.00% | PF=0.52 | Exp=-216.53 | INSUFFICIENT_SAMPLE | INSUFFICIENT_EVIDENCE |
| NO_TRADE | 166 | 0 | 0 | 0 | 0 | 166 | False | 0 trades | 0 trades | 0 trades | INSUFFICIENT_SAMPLE | INSUFFICIENT_EVIDENCE |
| WAIT | 41 | 0 | 0 | 0 | 41 | 0 | False | 0 trades | 0 trades | 0 trades | INSUFFICIENT_SAMPLE | INSUFFICIENT_EVIDENCE |

### 11.2 Entry Reason
| Entry Reason | Signals | Eligible | BUY_CE | BUY_PE | WAIT | NO_TRADE | Missing Meta | INDEX_POINTS_ONLY | INDEX_POINTS_AND_EXPLICIT_INR (INR) | SYNTHETIC_OPTION_INR_ONLY (Modelled BS) | Sample | Verdict |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | --- | --- | --- |
| BUY_CE (QUALIFIED) | 5 | 5 | 5 | 0 | 0 | 0 | False | n=5 | Net=-8.65 | WR=40.00% | PF=0.83 | Exp=-1.73 | n=5 | Net=-648.75 | WR=40.00% | PF=0.83 | Exp=-129.75 | n=5 | Net=-1082.66 | WR=40.00% | PF=0.52 | Exp=-216.53 | INSUFFICIENT_SAMPLE | INSUFFICIENT_EVIDENCE |
| NO_TRADE (REJECTED) | 166 | 0 | 0 | 0 | 0 | 166 | False | 0 trades | 0 trades | 0 trades | INSUFFICIENT_SAMPLE | INSUFFICIENT_EVIDENCE |
| WAIT (WAITING_CONFIRMATION) | 41 | 0 | 0 | 0 | 41 | 0 | False | 0 trades | 0 trades | 0 trades | INSUFFICIENT_SAMPLE | INSUFFICIENT_EVIDENCE |

### 11.3 Exit Reason
| Exit Reason | Signals | Eligible | BUY_CE | BUY_PE | WAIT | NO_TRADE | Missing Meta | INDEX_POINTS_ONLY | INDEX_POINTS_AND_EXPLICIT_INR (INR) | SYNTHETIC_OPTION_INR_ONLY (Modelled BS) | Sample | Verdict |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | --- | --- | --- |
| STOP_LOSS | 0 | 0 | 0 | 0 | 0 | 0 | False | n=3 | Net=-50.95 | WR=0.00% | PF=0.00 | Exp=-16.98 | n=3 | Net=-3821.25 | WR=0.00% | PF=0.00 | Exp=-1273.75 | n=3 | Net=-2251.65 | WR=0.00% | PF=0.00 | Exp=-750.55 | INSUFFICIENT_SAMPLE | INSUFFICIENT_EVIDENCE |
| TARGET_1 | 0 | 0 | 0 | 0 | 0 | 0 | False | n=2 | Net=42.30 | WR=100.00% | PF=N/A | Exp=21.15 | n=2 | Net=3172.50 | WR=100.00% | PF=N/A | Exp=1586.25 | n=2 | Net=1169.00 | WR=100.00% | PF=N/A | Exp=584.50 | INSUFFICIENT_SAMPLE | INSUFFICIENT_EVIDENCE |

## 12. ICT / SMC & MTF Confluence 8-Pillar Evidence
- **ICT Score:** `None` (`UNAVAILABLE / NOT_CALIBRATED`) | **Weights/Thresholds Invented:** `False`
- Signals Inspected: `212` | Eligible Signals: `5` | Verdict: `INSUFFICIENT_EVIDENCE`

| Pillar | Events Observed | Bullish | Bearish | Conflicts | Signals Present | Eligible Signals | Closed Trades | Points Stats | Explicit INR Stats | Synthetic BS INR Stats | Sample | Verdict |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | --- | --- |
| LIQUIDITY_SWEEPS | 3032 | 1924 | 1108 | 365 | 211 | 5 | 5 | n=5 | Net=-8.65 | WR=40.00% | PF=0.83 | Exp=-1.73 | n=5 | Net=-648.75 | WR=40.00% | PF=0.83 | Exp=-129.75 | n=5 | Net=-1082.66 | WR=40.00% | PF=0.52 | Exp=-216.53 | INSUFFICIENT_SAMPLE | INSUFFICIENT_EVIDENCE |
| BOS | 797 | 600 | 197 | 0 | 191 | 5 | 5 | n=5 | Net=-8.65 | WR=40.00% | PF=0.83 | Exp=-1.73 | n=5 | Net=-648.75 | WR=40.00% | PF=0.83 | Exp=-129.75 | n=5 | Net=-1082.66 | WR=40.00% | PF=0.52 | Exp=-216.53 | INSUFFICIENT_SAMPLE | INSUFFICIENT_EVIDENCE |
| CHOCH_MSS | 1298 | 794 | 504 | 0 | 199 | 5 | 5 | n=5 | Net=-8.65 | WR=40.00% | PF=0.83 | Exp=-1.73 | n=5 | Net=-648.75 | WR=40.00% | PF=0.83 | Exp=-129.75 | n=5 | Net=-1082.66 | WR=40.00% | PF=0.52 | Exp=-216.53 | INSUFFICIENT_SAMPLE | INSUFFICIENT_EVIDENCE |
| ORDER_BLOCKS | 2531 | 1660 | 871 | 788 | 210 | 5 | 5 | n=5 | Net=-8.65 | WR=40.00% | PF=0.83 | Exp=-1.73 | n=5 | Net=-648.75 | WR=40.00% | PF=0.83 | Exp=-129.75 | n=5 | Net=-1082.66 | WR=40.00% | PF=0.52 | Exp=-216.53 | INSUFFICIENT_SAMPLE | INSUFFICIENT_EVIDENCE |
| FVG_IFVG | 4093 | 2791 | 1302 | 0 | 207 | 5 | 5 | n=5 | Net=-8.65 | WR=40.00% | PF=0.83 | Exp=-1.73 | n=5 | Net=-648.75 | WR=40.00% | PF=0.83 | Exp=-129.75 | n=5 | Net=-1082.66 | WR=40.00% | PF=0.52 | Exp=-216.53 | INSUFFICIENT_SAMPLE | INSUFFICIENT_EVIDENCE |
| PREMIUM_DISCOUNT | 743 | 373 | 370 | 156 | 211 | 5 | 5 | n=5 | Net=-8.65 | WR=40.00% | PF=0.83 | Exp=-1.73 | n=5 | Net=-648.75 | WR=40.00% | PF=0.83 | Exp=-129.75 | n=5 | Net=-1082.66 | WR=40.00% | PF=0.52 | Exp=-216.53 | INSUFFICIENT_SAMPLE | INSUFFICIENT_EVIDENCE |
| INDUCEMENT | 33 | 22 | 11 | 0 | 28 | 1 | 1 | n=1 | Net=21.40 | WR=100.00% | PF=N/A | Exp=21.40 | n=1 | Net=1605.00 | WR=100.00% | PF=N/A | Exp=1605.00 | n=1 | Net=497.24 | WR=100.00% | PF=N/A | Exp=497.24 | INSUFFICIENT_SAMPLE | INSUFFICIENT_EVIDENCE |
| MTF_CONFLUENCE | 123 | 68 | 8 | 9 | 123 | 5 | 5 | n=5 | Net=-8.65 | WR=40.00% | PF=0.83 | Exp=-1.73 | n=5 | Net=-648.75 | WR=40.00% | PF=0.83 | Exp=-129.75 | n=5 | Net=-1082.66 | WR=40.00% | PF=0.52 | Exp=-216.53 | INSUFFICIENT_SAMPLE | INSUFFICIENT_EVIDENCE |

## 13. ICT / SMC Setup Alignment & Conflict Profile
- **Alignment Distribution:** `{'BULLISH_ALIGNMENT': 5, 'INSUFFICIENT_DATA': 89, 'MIXED_ALIGNMENT': 118}`
- **Conflict Distribution:** `{'CROSS_TIMEFRAME_DIVERGENCE': 4, 'HTF_ITF_DIVERGENCE': 5, 'HTF_LIQUIDITY_CONFLICT': 19, 'LIQUIDITY_CONFLICT': 346, 'MISSING_TIMEFRAME_EVIDENCE': 267, 'OB_FVG_INVALIDATION': 788, 'PREMIUM_DISCOUNT_CONFLICT': 156, 'SESSION_CONTEXT_CONFLICT': 57}`

| Phase 3 Alignment | Signals | Eligible | BUY_CE | BUY_PE | WAIT | NO_TRADE | Missing Meta | INDEX_POINTS_ONLY | INDEX_POINTS_AND_EXPLICIT_INR (INR) | SYNTHETIC_OPTION_INR_ONLY (Modelled BS) | Sample | Verdict |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | --- | --- | --- |
| BULLISH_ALIGNMENT | 5 | 0 | 0 | 0 | 5 | 0 | False | 0 trades | 0 trades | 0 trades | INSUFFICIENT_SAMPLE | INSUFFICIENT_EVIDENCE |
| INSUFFICIENT_DATA | 89 | 0 | 0 | 0 | 0 | 89 | False | 0 trades | 0 trades | 0 trades | INSUFFICIENT_SAMPLE | INSUFFICIENT_EVIDENCE |
| MIXED_ALIGNMENT | 118 | 5 | 5 | 0 | 36 | 77 | False | n=5 | Net=-8.65 | WR=40.00% | PF=0.83 | Exp=-1.73 | n=5 | Net=-648.75 | WR=40.00% | PF=0.83 | Exp=-129.75 | n=5 | Net=-1082.66 | WR=40.00% | PF=0.52 | Exp=-216.53 | INSUFFICIENT_SAMPLE | INSUFFICIENT_EVIDENCE |

## 14. Signal Quality Funnel, NO_TRADE Frequency & Chronology Audit
- Total Signals: `212` | Action Distribution: `{'BUY_CE': 5, 'NO_TRADE': 166, 'WAIT': 41}`
- Eligible: `5` (`2.36%`) | NO_TRADE Rate: `78.30%` | WAIT Rate: `19.34%`
- Executed Points Trades: `5` | Unexecuted Eligible Signals: `0`
- Chronological No-Lookahead Verified: `True` (Violations: `0`)
- Missing Metadata Counts: `{}`
- Rejection Reasons: `{'HTF/ITF Conflict: HTF is BULLISH while 5M structure is BEARISH.': 22, 'ITF/LTF Conflict: 5M structure is BEARISH while micro trigger is BULLISH.': 2, 'ITF/LTF Conflict: 5M structure is BULLISH while micro trigger is BEARISH.': 2, 'Multi-timeframe activation lockout in effect (15M or 5M unavailable).': 22, 'Stage 3 Rejection: 5M completed slice missing or < 4 bars.': 89, 'Stage 5 Rejection: SIDEWAYS regime locks directional option buying.': 49, 'UNKNOWN': 45}`

## 15. Strategy Verdict Summary & Per-Dimension Assessments
| Assessment Area | Verdict | Sample Size | Stat. Sig. Claimed | Key Reasons |
| --- | --- | --- | --- | --- |
| Instrument:BANK NIFTY | INSUFFICIENT_EVIDENCE | INSUFFICIENT_SAMPLE | False | instrument=BANK NIFTY: 0 closed trade(s) < minimum sufficient threshold (30); statistical reliability cannot be claimed (INSUFFICIENT_SAMPLE). |
| Instrument:FINNIFTY | INSUFFICIENT_EVIDENCE | INSUFFICIENT_SAMPLE | False | instrument=FINNIFTY: 0 closed trade(s) < minimum sufficient threshold (30); statistical reliability cannot be claimed (INSUFFICIENT_SAMPLE). |
| Instrument:NIFTY 50 | INSUFFICIENT_EVIDENCE | INSUFFICIENT_SAMPLE | False | instrument=NIFTY 50: 5 closed trade(s) < minimum sufficient threshold (30); statistical reliability cannot be claimed (INSUFFICIENT_SAMPLE). |
| Instrument:SENSEX | DATA_QUALITY_BLOCKED | INSUFFICIENT_SAMPLE | False | Status=GOVERNANCE_LOCKOUT, Eligibility=GOVERNANCE_LOCKED. |
| MarketRegime | INSUFFICIENT_EVIDENCE | INSUFFICIENT_SAMPLE | False | BEARISH_TREND: signals=8, trades=0, verdict=INSUFFICIENT_EVIDENCE; BULLISH_TREND: signals=39, trades=5, verdict=INSUFFICIENT_EVIDENCE |
| TradingSession | INSUFFICIENT_EVIDENCE | INSUFFICIENT_SAMPLE | False | AFTERNOON_1330_1500: signals=30, trades=1, verdict=INSUFFICIENT_EVIDENCE; CLOSING_1500_1530: signals=10, trades=1, verdict=INSUFFICIENT_EVIDENCE |
| ICT_SMC_Setup | INSUFFICIENT_EVIDENCE | INSUFFICIENT_SAMPLE | False | Maximum closed trades linked to any ICT/SMC pillar is 5 (< 30); ICT score remains UNAVAILABLE / NOT_CALIBRATED and no setup profitability is claimed. |
| RiskAndDrawdown | INSUFFICIENT_EVIDENCE | INSUFFICIENT_SAMPLE | False | INDEX_POINTS_ONLY max_dd=35.10 pts, max_consec_losses=2.; INDEX_POINTS_AND_EXPLICIT_INR max_dd=INR 2632.50 (0.131625%). |

## 16. Known Data Quality & Sample-Size Limitations
- [Data Quality] Step 4.6 PARTIAL datasets cannot support full-session performance claims: NIFTY 50 1m (8 incomplete / 10 complete sessions); NIFTY 50 3m (21 incomplete / 10 complete sessions); NIFTY 50 5m (33 incomplete / 10 complete sessions); BANK NIFTY 1m (8 incomplete / 0 complete sessions); BANK NIFTY 3m (21 incomplete / 0 complete sessions); BANK NIFTY 5m (33 incomplete / 0 complete sessions); BANK NIFTY 15m (1 incomplete / 81 complete sessions); BANK NIFTY 1h (1 incomplete / 244 complete sessions)...
- [Data Quality] Actual historical option OHLC/bid-ask/OI data remains BLOCKED; all SYNTHETIC_OPTION_INR_ONLY results use SYNTHETIC_MODELLED_OPTION_PNL (causal Black-Scholes approximations) and must never be presented as actual historical option fills.
- [Data Quality] SENSEX remains governance-locked across all backtesting layers per Step 4.2/4.6/4.7 rules.
- [Data Quality] Phase 3 ICT/SMC score remains UNAVAILABLE / NOT_CALIBRATED; Phase 2 MTF weights remain frozen and unchanged.
- [Data Quality] [REVALRUN-5acfd6e991b165] Historical option OHLC and bid/ask chains remain UNAVAILABLE on Angel One SmartAPI; actual historical options execution is BLOCKED.
- [Data Quality] [REVALRUN-927d1cd9892346] MIXED_DATASET_QUALITY_FORBIDDEN: Cannot silently combine VERIFIED and PARTIAL datasets without explicit allow_partial_research_only=True.
- [Data Quality] [REVALRUN-442271a91c3db2] Historical option OHLC and bid/ask chains remain UNAVAILABLE on Angel One SmartAPI; actual historical options execution is BLOCKED.
- [Data Quality] [REVALRUN-26a8286a1c6174] Historical option OHLC and bid/ask chains remain UNAVAILABLE on Angel One SmartAPI; actual historical options execution is BLOCKED.
- [Data Quality] [REVALRUN-00a88ca2c2e504] Historical option OHLC and bid/ask chains remain UNAVAILABLE on Angel One SmartAPI; actual historical options execution is BLOCKED.
- [Data Quality] [REVALRUN-36fe1046093de8] Historical option OHLC and bid/ask chains remain UNAVAILABLE on Angel One SmartAPI; actual historical options execution is BLOCKED.
- [Data Quality] [REVALRUN-72d70f7c4e93a3] GOVERNANCE_LOCKOUT: Zero registered trusted governance authorities in governance ledger; SENSEX locked.
- [Sample Size] Closed trades = 5 (INSUFFICIENT_SAMPLE); minimum sufficient threshold = 30, moderate = 100, strong = 300.
- [Sample Size] Statistical significance is explicitly NOT claimed (`statistical_significance_claimed=False`).
- [Sample Size] Actionable qualification rate = 2.36% (5/212 signals).

## 17. Persistence Isolation, Protected 6-File SHA-256 Hashes & Test Summary
- Isolation Summary: `{'isolated_backtest_db_path': 'D:\\ReactJs\\aivolve-trading-ai\\backend\\data\\backtest\\backtest_foundation.db', 'production_db_untouched': True, 'governance_ledger_untouched': True, 'paper_and_ml_artifacts_untouched': True, 'all_6_protected_hashes_matched': True, 'sensex_governance_locked': True, 'actual_historical_options_status': 'BLOCKED', 'execution_mode': 'PAPER_TRADING_ONLY'}`
- Automated Test Results Summary: `{'phase4_combined_steps_4_2_to_4_8': {'files': 9, 'passed': 125, 'failed': 0, 'skipped': 0, 'duration_sec': 249.21}, 'step4_8_dedicated_included_in_above': {'file': 'tests/test_backtest_step4_8_strategy_evidence.py', 'passed': 6, 'failed': 0, 'skipped': 0}, 'phase1_to_3_selected': {'files': 14, 'passed': 519, 'failed': 0, 'skipped': 0, 'duration_sec': 163.84}, 'failed': 0}`

| Protected File | Exists | SHA-256 Matched | Observed SHA-256 |
| --- | --- | --- | --- |
| aivolve_trading.db | True | True | `C85C49BE76DEE40557C4B9AAF308B4E3BEACA03CD4B1CD1CE90D051566EABF44` |
| governance_ledger.db | True | True | `4B12B3BAB44BF913F15174278B346FA321D5C473272E40F8B7E6E2350034488E` |
| paper_trading_records.json | True | True | `00F968EF85095EB7C1DE336A1780F9EDE417426A253AC531446BEF1117DA0298` |
| ml_trade_dataset.json | True | True | `87EEA8802835BB4F5A0AD1D598F2CEC561C6D5237F123B8B57CD79BBBE2E6445` |
| what_ai_learned.json | True | True | `3ED015726DFF309000EEC473AB660F34E3BD4EFAEDCBE183B14D62C572E5CCC5` |
| ml_strategy_weights.json | True | True | `C3C495F36214BD7FA58DDCA3C7F0280C14E15EB08DF41F868704F724C2A4E2FC` |
