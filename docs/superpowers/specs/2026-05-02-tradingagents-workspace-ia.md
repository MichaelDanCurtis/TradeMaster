# TradingAgents Workspace IA

Date: 2026-05-02
Status: Draft for review

## Decision

The Operator Terminal becomes a multi-workspace agent operating layer instead of a Webull replacement. Webull is the primary trading cockpit for manual charts, account review, and eventual execution. This app manages agents, research, approvals, auditability, and feedback loops around that trading surface.

The left watchlist rail remains persistent across workspaces and carries the selected symbol context. Top-level workspaces change the job the user is doing for that symbol.

Settings is not a full workspace tab. It becomes a small utility control for provider and brokerage configuration. Agent communication, agent alerts, user collaboration, and action requests move into a dedicated Agents workspace.

## Navigation

Top-level workspaces:

- Agents
- Deep Research
- Market Context
- Historicals
- Webull Handoff

Utility surfaces:

- Settings button for market data providers, Webull/OpenAPI configuration, brokerage adapters, credentials, account connection state, and paper/live mode gates.
- Toaster notification layer for ephemeral system messages and urgent status updates.

The selected symbol persists as users move between workspaces. A user can select NVDA in the watchlist, respond to an agent alert, open Deep Research reports, inspect Market Context, review a Webull handoff, and later compare predictions against actuals without losing that symbol context.

## Agents

Agents is the default home and operational communication workspace. It should feel closer to Outlook, Teams, or Slack than a settings screen.

Layout:

- Left column inside the workspace: agents, platform channels, and investment groups.
- Center column: durable message stream, alerts, agent questions, user replies, and agent-generated A2UI surfaces.
- Right column: contextual action panel for the selected conversation.

Agents can use the center conversation area to render constrained A2UI surfaces when they need richer interaction than plain text. Examples include event-linked chart snippets, report approval cards, research-narrowing controls, paper-order previews, Webull handoff cards, and confidence breakdowns.

The right action panel should support direct responses such as proceed, pause, reject, ask follow-up, create report, preview handoff, or add note. These actions should map to explicit backend intents and remain approval-gated where they can affect trading or persisted decisions.

This workspace can also host platform messaging and multi-user investment groups. Groups allow people to coordinate around a stock, a date, a report, or a trade idea while keeping the conversation attached to the trading context. The product should own this messaging experience rather than depending on Slack for v1.

## Market Context

Market Context is the evidence workspace. It should show the user's active watchlist and selected symbol context without trying to replace Webull's full trading dashboard.

Core areas:

- Persistent watchlist on the left.
- Main chart for the selected symbol.
- Standard chart modes, range selector, prior-period overlay, and benchmark or symbol comparison overlays.
- Current research stance below the chart.
- News and event feed below the stance.

News items should be linked to chart markers. The chart should display markers for the top relevant news events, such as a report published on April 18 at 3:00 PM. This lets the user visually associate price movement with external events. The first implementation can use stubbed news events with timestamps and sentiment, but the data shape should support live provider events later.

The charting goal is evidence-grade review, not a full Webull clone. The chart engine should support candles, volume, line/area/baseline views, comparison overlays, event markers, and crosshair inspection. Full trading-chart workflows remain in Webull.

## Deep Research

Deep Research is where the TradingAgents methodology lives as durable reports, runs, and decision history. It should feel like reviewing serious research artifacts, not chatting with the system.

Core areas:

- Report list for the selected symbol.
- Current and historical report summaries.
- Decision ledger with stance, recommendation, risk notes, approval state, and paper-trade linkage.
- Expandable report detail.
- Agent DAG view showing how the run moved through market, news, social, fundamentals, bull/bear research, risk, portfolio, and broker stages.

The agent DAG should be inspectable. A user can click an individual agent node to see its synthesis, source inputs, confidence, output artifact, and how that output influenced the final decision.

## Notifications

The app should include a toaster-style notification layer for ephemeral events:

- run started
- run completed
- provider degraded
- broker disconnected
- paper order submitted
- approval required
- new agent message
- data freshness warning

Notifications should not replace the Agents workspace. A toaster message is a short-lived alert. The durable message, context, and response flow live in Agents.

## Webull Handoff

Webull Handoff is the portfolio, order-intent, and execution-readiness workspace. It should show account state, recent handoff records, and approval status while treating Webull as the eventual execution environment.

Core areas:

- Top positions.
- Portfolio balance and cash or buying power snapshot.
- Recent orders.
- Open intents and approvals.
- Webull handoff or paper ticket preview on the right.
- Review step before any broker-facing action.

The initial implementation remains paper/local-only. Webull should be modeled as a planned market-data and brokerage adapter using official OpenAPI where available. Live execution remains disabled until a future approval-policy spec designs limits, audit logs, kill switches, and credential configuration.

## Historicals

Historicals is the feedback-loop workspace. It compares what TradingAgents predicted or recommended against what happened later.

Core areas:

- Position and price history for the selected symbol.
- Suggested entry, exit, target, and review points from TradingAgents.
- Actual market movement over the same horizon.
- List of acted-on research stances and predictions.
- Outcome review fields for whether the recommendation was early, late, directionally wrong, risk-blind, or correctly framed.

This workspace is the seed of the agent improvement loop. It should make prediction quality visible before attempting any autonomous behavior.

## Settings

Settings is a compact utility surface, not a day-to-day workflow tab.

Settings owns:

- Market data providers.
- News and event providers.
- Brokerage adapters.
- Webull OpenAPI configuration.
- Provider credentials.
- Connection health.
- Paper/live environment gates.
- Account-level safety limits.

Settings does not own agent communication, scheduled conversations, report review, or collaboration. Those belong in Agents or Deep Research depending on whether the interaction is live operational communication or durable research output.

## Webull Integration Boundary

Webull is the user's core trading application. This app should not scrape, iframe, or automate the Webull UI. Integration should use official Webull OpenAPI capabilities where available:

- HTTP market data for historical bars, snapshots, and on-demand context.
- Streaming market data for live monitoring when credentials and subscriptions are configured.
- Account/order APIs for future automation, disabled behind explicit approvals.

The first Webull integration should be market-data only. Agent-created trade intents can later become Webull handoff records, then approval-gated API actions, and only much later limited autonomous execution under strict policy.

## Data Shapes

New frontend/domain shapes implied by this IA:

- `WorkspaceId`: dashboard, research, agents, transactions, historicals. The existing `dashboard` id represents the Market Context workspace until a later route/id migration.
- `NewsEvent`: symbol, timestamp, title, source, url, sentiment, relevance, marker style.
- `AgentConversation`: id, type, participant ids, linked symbol, linked report id, unread count, last activity.
- `AgentMessage`: conversation id, author type, body, timestamp, attachments, A2UI payload id.
- `ActionRequest`: conversation id, action type, label, required approval, status, backend intent id.
- `Notification`: severity, title, body, linked workspace, linked entity id, ttl.
- `HistoricalOutcome`: symbol, report id, predicted stance, prediction date, horizon, actual outcome, review tags.

These shapes can start as local simulated data while preserving provider and backend boundaries for later integration.

## Implementation Phasing

Phase 1 should restructure the frontend shell around workspaces without trying to complete every business workflow:

- Add workspace navigation.
- Make Agents the default home.
- Keep the current watchlist rail persistent.
- Move the existing chart/research stance into Market Context.
- Move the existing agent graph/report run controls into Deep Research.
- Add a stub Agents workspace with Outlook/Teams-like layout.
- Add a stub Webull Handoff workspace using local paper/handoff state.
- Add a stub Historicals workspace with prediction-vs-actual seed data.
- Move provider status/config into a settings utility surface.
- Add a toaster notification layer with simulated events.

Phase 2 should connect the deeper workflows:

- News event markers on charts.
- Persistent report list and decision ledger.
- Clickable agent DAG details.
- Real agent conversation data model.
- Action requests from Agents into report/trade workflows.
- Historical feedback capture.
- Webull market-data adapter and chart provider selection.

Phase 3 should connect live providers and multi-user collaboration:

- Real news/event providers.
- Webull account snapshots and order history.
- Group conversations.
- Scheduled agents.
- Outcome analytics for improving agent behavior.

## Testing Strategy

Frontend tests:

- Workspace navigation keeps selected symbol intact.
- Settings opens as a utility surface and does not replace the active workspace.
- Agents is the default home.
- Market Context renders chart, stance, news list, and event markers.
- Deep Research renders report list and agent DAG.
- Agents renders conversation list, message stream, and action panel.
- Webull Handoff renders positions, orders, and approval-gated local handoff/ticket state.
- Historicals renders prediction-vs-actual seed data.
- Toaster displays and dismisses notifications.

Backend and integration tests can remain focused on existing provider, runner, and broker adapter contracts until the new data models are wired to persistence.

## Open Scope Boundaries

This spec does not require live market, news, brokerage, or collaboration data in the first implementation pass. It defines the interface architecture and stub surfaces that let those systems attach cleanly later.

The app must continue to present trading actions as paper-only unless a future spec explicitly designs live brokerage enablement and approval controls.
