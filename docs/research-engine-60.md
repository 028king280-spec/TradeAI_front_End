# Second research setup engine

Profile: `research_60_target30_v1`. The production pipeline and its 70-point defaults are unchanged. Analysis runs the independent profile on the same quote/candle/chain snapshot with both confluence gates set to 60. Existing market-data, structural, contract/liquidity and risk checks still apply. A score of 60 is not a calibrated 60% probability.

A qualified second-engine setup uses a single target equal to entry ask premium × 1.30, rounded half-up to two decimals. The original structural stop is preserved. Gross premium reward/risk is recalculated and must be at least 1.5. Thus a 60-point score alone does not guarantee a setup. Fees and slippage are not deducted from the displayed target or gross reward/risk.

The dashboard Overview/Signals views and index analysis page display a separate research card. Evaluation runs when the existing analysis endpoint is requested, not on an independent background schedule. Research observations do not place orders, alter the production signal journal, affect the paper account, send alerts or train a model.

## Storage and retrieval

Restart the backend to create the additive `research_setup_evaluations` table through the existing metadata initialization. Each analysis observation has its own UUID, timestamp, profile version, qualification result, reasons, features and candidate premium geometry. Repeated polling produces separate observations, not additional independent trades or outcome labels. Existing signal/performance tables remain separate.

`GET /api/performance/research-evaluations?date=2026-11-17&symbol=NIFTY%2050&limit=100&offset=0` returns paginated observations for the selected IST day; count is independent of page size. A failed journal write is shown as unsaved in the UI. Research failures do not replace the production result.

## Validation

13 research tests (including actual pipeline score 65 rejected by production but passing both research score gates), 2 existing journal tests, 21 existing production pipeline tests; TypeScript and production build pass. Live-feed and interactive browser verification have not been performed.

## Remaining scope

Separate research paper entry/exit execution, completed outcome labels, dataset deduplication/split policy and automated model training are not part of this setup generator. Research-only labels and absence of execution buttons are intentional until lifecycle integration is implemented.
