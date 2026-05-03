# Operator Terminal Redesign

## Decision

Keep the existing React/Next.js frontend for this pass. Vite is not required for A2UI, and the current problem is visual/product quality rather than the React runtime. The frontend should be redesigned in place around the Operator Terminal direction selected in the visual companion.

## Product Target

The first screen should feel like a real trading/research terminal, not a scaffold. The interface should make three zones immediately clear:

- Left: watchlist and market selection.
- Center: chart-first market workspace with compact quote context and report summary.
- Right: agent cockpit, run progress, decision state, and approval-gated paper ticket.

The design should remain explicitly fake/paper-only. Any trade action stays behind a visible approval button and the backend broker-mode guard remains authoritative.

## Visual Direction

- Dark professional terminal palette with restrained contrast.
- Dense but readable spacing.
- Compact top status bar with product name, environment, API state, and broker mode.
- Tight watchlist rows with symbol, company, price, and change.
- Chart area should dominate the center view.
- Agent cockpit should look operational: run controls, stage list, final report/decision, and paper ticket.
- Avoid marketing cards, large empty panels, decorative gradients, or explanatory onboarding copy.

## Component Changes

- `MarketShell` becomes a complete terminal frame with a top bar and three-column body.
- `WatchlistRail` gets denser market terminal rows and section metadata.
- `ChartWorkspace` gets terminal headers, timeframe controls, market stats, and a decision/report strip.
- `AgentCockpit` gets clearer cockpit sections, run state, and timeline grouping.
- `RunTimeline` renders compact event rows with type/node/status hierarchy.
- `TradeTicket` remains explicit approval-only and visually marked as paper trading.
- `globals.css` is rewritten toward the terminal visual system with responsive behavior.

## Verification

- `npm run web:build`
- `npm run web:lint`
- Browser smoke: select symbol, verify chart/cockpit update, run report, verify timeline and paper ticket, approve paper order, verify fake order id.
