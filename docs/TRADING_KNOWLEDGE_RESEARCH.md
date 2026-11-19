# Trading knowledge: research candidates

These notes are research inputs, not trained model weights, trading signals, or evidence of profitability. They do not alter the setup selector, model, or risk gates. Validate candidate rules on independently sourced, timestamped market and options data before any paper deployment.

## Sources and hypotheses

- [Zerodha Varsity: support and resistance](https://zerodha.com/varsity/chapter/support-resistance/): historical price levels can be used as potential zones of supply and demand. Hypothesis: evaluate breakouts and retests of levels calculated exclusively from prior closed candles. A level may fail; do not imply certain reversal.
- [Zerodha Varsity: range and breakout](https://zerodha.com/varsity/chapter/dow-theory-part-2/): breakouts can be evaluated alongside volume and price movement. For an index, obtain volume from a suitable instrument; do not invent index volume or substitute option volume without labeling. Compare breakout-only, retest, and failed-breakout outcomes as separate research cohorts.
- [Zerodha Varsity: moving averages](https://zerodha.com/varsity/chapter/moving-averages/): moving averages describe trend but can whipsaw in non-trending markets. Hypothesis: compare trend continuation candidates across independently classified trend and range regimes. The source's daily examples do not validate any specific intraday parameter.
- [NISM: equity derivatives FAQ](https://www.nism.ac.in/wp-content/uploads/2021/02/Equity-Derivatives-FAQ-document-1.pdf) and [Zerodha: option Greeks](https://support.zerodha.com/category/account-opening/glossary/futures-and-options/articles/what-are-option-greeks): option premium depends on multiple factors, including time and volatility. Record quote timestamp, bid/ask, expiry and available Greeks; do not treat underlying direction as an option profit guarantee. Check current exchange contract specifications independently.
- [CME: beyond the illusion of backtests](https://www.cmegroup.com/articles/2026/moving-beyond-the-illusion-of-backtests.html): evaluate out-of-sample, parameter sensitivity and transaction cost stress. Training, selection and untouched final evaluation must be separated chronologically.

## Data and validation requirements

Record each considered candidate at decision time, including rejected candidates and exact rejection stage; distinguish observation from executed paper orders. Store source, instrument, contract, timeframe, market/ingestion timestamps, quote freshness, historical-data version, features available then, model/rule version, risk decision, and later outcomes. Preserve corrections and avoid using future candles in features. A zero or unavailable premium is not an executable quote.

Assess data licensing and provenance, duplicates, missing bars, exchange calendar and contract changes. Split by time with a separate final holdout; avoid overlap of outcome horizons across boundaries. Report candidate counts, no-trade and rejected counts, directional results, closed paper trades, costs, net expectancy, drawdown and uncertainty. Compare against simple baselines, and test by session and regime with sample counts. Evaluate shadow candidates without bypassing existing governance or execution controls.

The previously inspected training file contained 348 records but only 10 distinct feature vectors, including 337 repetitions of one vector. It is not suitable evidence of real-market predictive performance. Collect validated diverse data before retraining or promoting an artifact.
