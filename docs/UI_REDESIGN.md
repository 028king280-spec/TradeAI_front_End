# AIVOLVE workspace UI redesign

The approved graphite-and-teal design is applied to the application, with a shared shell, grouped navigation, typography, surface tokens and light/dark appearance. `/design-preview` retains the illustrative reference; production routes continue to use their existing services and controls.

## Layout and behavior

- Overview: backend-supplied index cards, the existing live chart, market-context copilot and market watch. Signals, structure, outlook, learning and paper trading are separated into keyboard-accessible tabs.
- Index terminal, option chain, stock explorer and stock detail: common page headings and theme tokens; existing index, expiry, strike-range and stock controls remain available.
- Paper trading: account/positions, signals/execution and system-health tabs. Empty accounts no longer report a fabricated 100% win rate or fixed profit factor.
- Performance, AI insights, sentiment, outlook, patterns, research and alerts: consistent page chrome, surfaces and typography. Research uploads, alert configuration, journal controls, signal modals and CSV exports retain their existing operations.
- Observer: a dedicated diagnostics page using `/api/live/status` and the shared market snapshot instead of redirecting to sentiment.
- Search: workspace-page links and stock-directory matches, Ctrl/Cmd+K, Escape and click-outside dismissal. Search suggestions do not display unverified prices.
- Mobile navigation: focus entry, Escape dismissal, focus return, background scroll lock and inert underlying content. The drawer closes when returning to desktop width.

## Data and execution boundaries

The header polls `/api/market/live` without a mock fallback. Its initial, demo, end-of-day, unavailable and disconnected states remain distinct; errors clear the previous live snapshot. Index cards carry their own provenance labels. Missing quotes display a dash. The overview does not substitute a different index's quote when the selected index is missing.

Existing browser API calls for performance, research and signal modals now use `/api/...`, through the Next.js backend rewrite. The Turbopack root follows the checkout path instead of a developer's Windows directory. No backend risk limits, broker routing, model weights or persisted trading datasets are changed.

## Validation

- Next.js production build and TypeScript checks passed.
- New shared-shell, navigation, market-feed, heading, quote-card, tab and observer code passed targeted ESLint checks.
- DOM integration checks exercised the real shell's routing state, theme persistence, workspace search, Ctrl+K focus, keyboard tab navigation, mobile-menu dismissal/background inert state, unavailable quotes and live-to-demo-to-offline transitions.
- Full-repository lint was compared against the starting commit: 129 existing errors before the change, 128 after the initial redesign pass; no new error signatures were introduced. Existing lint failures remain outside this visual change.
- Browser screenshot/layout inspection and genuine live-backend end-to-end testing were not completed in this environment. Responsive CSS is implemented, but visual acceptance at desktop, tablet and mobile widths remains a review item.

Run locally with `npm ci`, start the existing FastAPI backend on port 8000, then run `npm run dev`. Review `/` for the integrated workspace and `/design-preview` for the reference design.
