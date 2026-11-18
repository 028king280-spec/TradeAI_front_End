# SENSEX architecture and feature parity

Discovery checkpoint, 18 November 2026. This is an incomplete acceptance inventory.
Workspace checkout: TradeAI_front_End, branch codex/sensex-phase-1.
The supplied Windows project directory is not mounted in this workspace.

| Feature | NIFTY status | SENSEX status | Evidence | Remaining blocker |
| --- | --- | --- | --- | --- |
| Instrument discovery | IMPLEMENTED | TESTED_OFFLINE | app/data/instrument_master.py; test_sensex_instrument_resolution.py | Current broker master and live contract validation |
| Spot quotes | IMPLEMENTED | CONDITIONAL | angelone_provider.py and upstox_provider.py contain index mappings | Token, timestamps and live freshness validation |
| Options quote routing | IMPLEMENTED | IMPLEMENTED | api/routes/options.py routes SENSEX to BFO | Endpoint integration tests and live responses |
| Premium candles | IMPLEMENTED | IMPLEMENTED | api/routes/options.py uses BFO for SENSEX candles | Broker historical response validation |
| WebSocket subscriptions | IMPLEMENTED | CONDITIONAL | angelone_websocket.py includes SENSEX benchmark | SDK exchange mapping, collision and reconnect tests |
| Options intelligence | IMPLEMENTED | CONDITIONAL | options/option_chain.py shared chain engine | Lot-size fallbacks and unavailable-field audit |
| SMC and multi-timeframe features | IMPLEMENTED | CONDITIONAL | Shared pipeline_orchestrator.py | SENSEX-specific integration fixtures and isolation tests |
| Prediction horizons and outcome journal | CONDITIONAL | NOT_IMPLEMENTED | Discovery pending | Trace 5/15/30/60-minute prediction lifecycle and model applicability |
| Contract liquidity qualification | IMPLEMENTED | BLOCKED | contract_selector.py SENSEX policy is UNCONFIGURED | Authorized policy configuration; preserve production lock |
| Research setup profile | TESTED_OFFLINE | CONDITIONAL | test_research_setup_engine.py; shared evaluator | Full SENSEX candidate qualification tests |
| Research paper lifecycle | TESTED_OFFLINE | CONDITIONAL | test_research_paper_engine.py; jobs/research_paper.py groups quotes by exchange | SENSEX admission, accounting, partial exits and restart tests |
| Paper cockpit | IMPLEMENTED | BLOCKED | src/app/paper-trading/page.tsx explicitly locks SENSEX | Read-only forecast integration and isolated sandbox evidence |
| Other index selectors | IMPLEMENTED | CONDITIONAL | option-chain, patterns, sentiment and outlook pages list SENSEX | Switching, stale state, responsive and browser tests |
| Live validation | CONDITIONAL | BLOCKED | No live evidence collected | Authenticated broker runtime |
| Visible browser acceptance | CONDITIONAL | NOT_IMPLEMENTED | No browser run performed | Actual local frontend and visible browser session |
| Production activation | CONDITIONAL | BLOCKED | User explicitly requires separate governance approval | All mandatory acceptance evidence and approval |

## Baseline protection

Current checkpoint hashes are below. The established baseline hashes were not
supplied in the instruction file, so these observations do not establish historical
integrity before this checkpoint.

| Protected path | Current SHA-256 |
| --- | --- |
| backend/aivolve_trading.db | MISSING |
| backend/app/data/governance_ledger.db | 1254f93860afcbb443ed3812939a5f31cbdaba163897d6aea85517b85910c6c9 |
| backend/app/data/paper_trading_records.json | 64237bac9082156a9c0c8bfaef40a5f8d4eabded83b04e810c7acbee104e48d8 |
| backend/app/data/ml_trade_dataset.json | 8bae69bafb75430885b0c14a672e800b2359bf3b98d671cb2e0705526c538b9b |
| backend/app/data/what_ai_learned.json | daafbc7625fb12a200f051dbd772b08182b40116476bb1c5c17cd58ce02c1546 |
| backend/app/data/ml_strategy_weights.json | 543096b1f4c5a1fd216fa7bc446b6690bf300311b76e28d3b2ab0ad58e4be80e |

## Evidence available

Commit 031f320 contains BFO loading and routing fixes.
40 existing research setup and paper lifecycle tests passed.
One SENSEX instrument resolution test passed with synthetic test contracts.
These results establish only the tested offline behavior.

Overall acceptance remains NOT_ACCEPTED. Full architecture inventory,
implementation, authoritative exchange verification, regression and visible
browser acceptance are outstanding.
