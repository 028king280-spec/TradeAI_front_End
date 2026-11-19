# Architecture audit remediation - 17 November 2026

## Batch 1: execution failure handling and data truthfulness

Connected open/close requests now preserve backend rejection. Transport or parsing failure returns an unconfirmed outcome without executing a local fallback. Failed reset no longer clears the local account. A zero net P&L remains zero rather than falling back to gross P&L.

Market API failures no longer return mock indices, candidates, driver/sector/history data, stock analysis or search quotes. Successful empty candidate arrays stay empty. The observer starts without sample data and clears its displayed snapshot when its request fails. Explicit standalone demo execution paths still require consolidation with the server authority.

Nonempty broker/AI credential defaults were removed from configuration. Any previously active exposed credentials must still be rotated at their providers; deleting source defaults does not revoke a key or remove Git history. No credentials were tested or rotated by this change.

The paper engine rejects nonpositive/nonintegral/bool quantities and invalid entry premiums/strikes before mutation. Failed serialization/file replacement restores the last successfully persisted in-memory state and version, preventing phantom positions after a failed open or close. Snapshot preparation occurs before disk replacement.

## Validation

- Node boundary tests: 10 passed (HTTP rejection, network ambiguity, failed exit/reset, empty/offline data).
- Backend full regression in an isolated checkout: 1,094 passed, 28 failed, 11 skipped. The same 28 test identifiers failed in the audit baseline; no new failing identifiers. Ten new entry/persistence tests passed.
- Production build and TypeScript passed; touched API/observer/test files pass targeted ESLint.
- Persisted user datasets and risk policies were not modified. Tests use temporary stores and blank provider credentials.

The suite still has baseline failures and Windows-only skips. A successful build is not a browser or live-provider sign-off.

## Audit closure status

| Finding | Status |
| --- | --- |
| A01 secrets | Source defaults removed; provider rotation/history remediation pending |
| A02 identity/ownership/model approvals | Open |
| A03 connected rejection fallback | Fixed for backend open/close/reset; standalone local execution and idempotent reconciliation remain open |
| A04 market fixture fallback | Removed from connected API/observer paths; whole-app provenance review remains open |
| A05 multi-process state ownership | Open |
| A06 cash/fees/equity reconciliation | Open; needs versioned accounting migration and compatibility tests |
| A07 failed-save memory divergence | Fixed for save failures; corrupt-file recovery and process coordination remain open |
| A08 entry validation | Domain quantity/entry-price invariants fixed; strict HTTP schemas and trusted quote binding remain open |
| A09-A12 ML metrics, temporal training, backtest and LLM evidence | Open |
| A13 deployment topology | Open |
| A14 readiness/CI/contracts | Open |

Next changes must establish authenticated account ownership and a canonical transactional ledger before accepting public execution. Preserve existing risk gates, SENSEX lock and paper-only boundaries. This batch is not institutional or production sign-off.
