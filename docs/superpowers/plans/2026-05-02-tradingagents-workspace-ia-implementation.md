# TradingAgents Workspace IA Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure the Operator Terminal into persistent watchlist plus Dashboard, Deep Research, Agents, Transactions, and Historicals workspaces, with Settings as a provider/broker utility and toasters for ephemeral system messages.

**Architecture:** Keep the existing Next.js app shell and simulated data model. Add a small frontend domain layer for workspace IDs, seeded news, conversations, transaction summaries, historical outcomes, settings state, and notification state. Move the current chart and agent cockpit into explicit workspace components before connecting deeper live systems.

**Tech Stack:** Next.js 15, React 19, TypeScript, Node test runner, existing Python API for runs/providers/trade preview.

---

## File Structure

- Modify `apps/web/src/components/MarketShell.tsx`: own selected symbol, active workspace, settings open state, toast events, and top navigation.
- Modify `apps/web/src/components/WatchlistRail.tsx`: keep provider status out of the rail and keep it focused on market selection.
- Modify `apps/web/src/components/ChartWorkspace.tsx`: accept news events and render chart markers plus a news/event feed.
- Modify `apps/web/src/components/AgentCockpit.tsx`: add mode support so Deep Research can show run/report controls without embedding the trade ticket by default.
- Create `apps/web/src/components/WorkspaceNav.tsx`: top-level workspace tabs and settings utility button.
- Create `apps/web/src/components/SettingsDrawer.tsx`: compact provider/brokerage utility surface.
- Create `apps/web/src/components/ToastStack.tsx`: ephemeral notification layer.
- Create `apps/web/src/components/DashboardWorkspace.tsx`: chart, stance, and news/event dashboard composition.
- Create `apps/web/src/components/DeepResearchWorkspace.tsx`: report list, decision ledger, and agent DAG/run cockpit.
- Create `apps/web/src/components/AgentsWorkspace.tsx`: Outlook/Teams-like agent and group messenger console.
- Create `apps/web/src/components/TransactionsWorkspace.tsx`: portfolio, balances, recent orders, and approval-gated paper ticket surface.
- Create `apps/web/src/components/HistoricalsWorkspace.tsx`: prediction-vs-actual feedback workspace.
- Create `apps/web/src/lib/workspace-data.ts`: seeded domain data and selectors for workspaces.
- Create `apps/web/src/lib/workspace-data.test.ts`: tests for selectors, sorting, and symbol scoping.
- Create `apps/web/src/lib/workspace-state.ts`: pure state helpers for navigation, settings, and notifications.
- Create `apps/web/src/lib/workspace-state.test.ts`: tests for selected symbol persistence, settings behavior, and toast dismissal.
- Modify `apps/web/src/lib/types.ts`: add shared workspace/domain types when needed.
- Modify `apps/web/src/app/globals.css`: add workspace navigation, messenger, settings, toaster, transaction, historical, and news marker styling.

## Task 1: Workspace Domain Data

**Files:**
- Create: `apps/web/src/lib/workspace-data.ts`
- Create: `apps/web/src/lib/workspace-data.test.ts`
- Modify: `apps/web/src/lib/types.ts`

- [ ] **Step 1: Write failing tests for domain selectors**

Add `apps/web/src/lib/workspace-data.test.ts`:

```ts
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  getAgentConversations,
  getDashboardNewsEvents,
  getHistoricalOutcomes,
  getTransactionSnapshot
} from "./workspace-data.ts";

describe("workspace domain data", () => {
  it("returns the top relevant news events for the selected symbol in descending relevance order", () => {
    const events = getDashboardNewsEvents("NVDA");

    assert.equal(events.length, 20);
    assert.ok(events.every((event) => event.symbol === "NVDA"));
    assert.ok(events[0].relevance >= events[1].relevance);
    assert.match(events[0].timestamp, /^2026-/);
  });

  it("scopes conversations and groups to the selected symbol plus platform alerts", () => {
    const conversations = getAgentConversations("NVDA");
    const ids = conversations.map((conversation) => conversation.id);

    assert.ok(ids.includes("research-lead-nvda"));
    assert.ok(ids.includes("platform-alerts"));
    assert.ok(conversations.some((conversation) => conversation.type === "group"));
    assert.ok(conversations.every((conversation) => conversation.symbol === "NVDA" || conversation.symbol === null));
  });

  it("creates a transaction snapshot with paper mode and approval-gated order intent", () => {
    const snapshot = getTransactionSnapshot("NVDA");

    assert.equal(snapshot.mode, "paper");
    assert.equal(snapshot.orderIntent.symbol, "NVDA");
    assert.equal(snapshot.orderIntent.requiresApproval, true);
    assert.ok(snapshot.positions.length >= 3);
  });

  it("returns historical outcomes for the selected symbol only", () => {
    const outcomes = getHistoricalOutcomes("NVDA");

    assert.ok(outcomes.length >= 3);
    assert.ok(outcomes.every((outcome) => outcome.symbol === "NVDA"));
    assert.ok(outcomes.some((outcome) => outcome.reviewTags.includes("directionally-correct")));
  });
});
```

- [ ] **Step 2: Run tests and verify RED**

Run: `npm --workspace apps/web run test`

Expected: FAIL because `apps/web/src/lib/workspace-data.ts` does not exist.

- [ ] **Step 3: Implement domain types and selectors**

Add exported types and seeded data. Required type names:

```ts
export type WorkspaceId = "dashboard" | "research" | "agents" | "transactions" | "historicals";
export type NewsSentiment = "positive" | "neutral" | "negative";
export type AgentConversationType = "agent" | "group" | "platform";
export type NotificationSeverity = "info" | "success" | "warning" | "critical";
```

Required selectors:

```ts
export function getDashboardNewsEvents(symbol: string): NewsEvent[];
export function getAgentConversations(symbol: string): AgentConversation[];
export function getTransactionSnapshot(symbol: string): TransactionSnapshot;
export function getHistoricalOutcomes(symbol: string): HistoricalOutcome[];
export function getInitialNotifications(symbol: string): TerminalNotification[];
```

Implementation rules:

- `getDashboardNewsEvents` returns exactly 20 events for a symbol.
- News events must include timestamps from April/May 2026 so markers can appear on the current simulated charts.
- `getAgentConversations` returns symbol-specific conversations plus platform alerts.
- `getTransactionSnapshot` must be paper mode and include an approval-gated order intent.
- `getHistoricalOutcomes` must filter by symbol and include review tags.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `npm --workspace apps/web run test`

Expected: all lib tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/lib/types.ts apps/web/src/lib/workspace-data.ts apps/web/src/lib/workspace-data.test.ts
git commit -m "feat: add workspace domain data"
```

## Task 2: Shell Navigation, Settings State, and Notifications State

**Files:**
- Create: `apps/web/src/lib/workspace-state.ts`
- Create: `apps/web/src/lib/workspace-state.test.ts`
- Create: `apps/web/src/components/WorkspaceNav.tsx`
- Create: `apps/web/src/components/SettingsDrawer.tsx`
- Create: `apps/web/src/components/ToastStack.tsx`
- Modify: `apps/web/src/components/MarketShell.tsx`
- Modify: `apps/web/src/components/WatchlistRail.tsx`

- [ ] **Step 1: Write failing tests for pure workspace state**

Add `apps/web/src/lib/workspace-state.test.ts`:

```ts
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { dismissNotification, selectSymbol, setWorkspace, toggleSettings } from "./workspace-state.ts";

describe("workspace state helpers", () => {
  it("changes workspace without changing selected symbol", () => {
    const next = setWorkspace({ activeWorkspace: "dashboard", selectedSymbol: "NVDA", settingsOpen: false }, "agents");

    assert.deepEqual(next, { activeWorkspace: "agents", selectedSymbol: "NVDA", settingsOpen: false });
  });

  it("changes selected symbol without changing workspace", () => {
    const next = selectSymbol({ activeWorkspace: "research", selectedSymbol: "NVDA", settingsOpen: false }, "AAPL");

    assert.deepEqual(next, { activeWorkspace: "research", selectedSymbol: "AAPL", settingsOpen: false });
  });

  it("toggles settings without replacing active workspace", () => {
    const next = toggleSettings({ activeWorkspace: "transactions", selectedSymbol: "NVDA", settingsOpen: false });

    assert.deepEqual(next, { activeWorkspace: "transactions", selectedSymbol: "NVDA", settingsOpen: true });
  });

  it("dismisses a notification by id", () => {
    const notifications = [
      { id: "a", severity: "info" as const, title: "A", body: "A", linkedWorkspace: "dashboard" as const },
      { id: "b", severity: "warning" as const, title: "B", body: "B", linkedWorkspace: "agents" as const }
    ];

    assert.deepEqual(dismissNotification(notifications, "a").map((item) => item.id), ["b"]);
  });
});
```

- [ ] **Step 2: Run tests and verify RED**

Run: `npm --workspace apps/web run test`

Expected: FAIL because `workspace-state.ts` does not exist.

- [ ] **Step 3: Implement state helpers and shell UI**

Implement pure helpers:

```ts
export type WorkspaceShellState = {
  activeWorkspace: WorkspaceId;
  selectedSymbol: string;
  settingsOpen: boolean;
};
```

Update `MarketShell` to:

- Render top nav workspaces: Dashboard, Deep Research, Agents, Transactions, Historicals.
- Keep Settings as a utility button.
- Keep `WatchlistRail` persistent.
- Keep selected symbol unchanged when changing workspaces.
- Render `SettingsDrawer` as an overlay when `settingsOpen` is true.
- Render `ToastStack` with seeded notifications from `getInitialNotifications(selectedSymbol)`.

Update `WatchlistRail` to remove `ProviderPanel`; provider configuration moves to `SettingsDrawer`.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `npm --workspace apps/web run test`

Expected: all lib tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/components/MarketShell.tsx apps/web/src/components/WatchlistRail.tsx apps/web/src/components/WorkspaceNav.tsx apps/web/src/components/SettingsDrawer.tsx apps/web/src/components/ToastStack.tsx apps/web/src/lib/workspace-state.ts apps/web/src/lib/workspace-state.test.ts
git commit -m "feat: add workspace shell navigation"
```

## Task 3: Dashboard Workspace and News Markers

**Files:**
- Create: `apps/web/src/components/DashboardWorkspace.tsx`
- Modify: `apps/web/src/components/ChartWorkspace.tsx`
- Modify: `apps/web/src/app/globals.css`

- [ ] **Step 1: Add a failing selector assertion if needed**

Extend `workspace-data.test.ts` with:

```ts
it("provides event marker labels for chart rendering", () => {
  const events = getDashboardNewsEvents("NVDA");

  assert.ok(events.every((event) => event.markerLabel.length >= 1));
  assert.ok(events.every((event) => event.relevance >= 0 && event.relevance <= 100));
});
```

- [ ] **Step 2: Run tests and verify RED or existing coverage**

Run: `npm --workspace apps/web run test`

Expected: FAIL if `markerLabel` is missing; otherwise PASS and proceed because selector coverage already exists.

- [ ] **Step 3: Implement Dashboard composition**

Create `DashboardWorkspace`:

```tsx
import { ChartWorkspace } from "@/components/ChartWorkspace";
import { getDashboardNewsEvents } from "@/lib/workspace-data";

export function DashboardWorkspace({ symbol }: { symbol: string }) {
  return <ChartWorkspace newsEvents={getDashboardNewsEvents(symbol)} symbol={symbol} />;
}
```

Modify `ChartWorkspace` props:

```ts
export function ChartWorkspace({ newsEvents = [], symbol }: { newsEvents?: NewsEvent[]; symbol: string }) {
```

Render chart markers by mapping news event timestamps onto the chart x-scale. If exact timestamp alignment is not possible, map each news event to the closest rendered bar by timestamp distance. Render the top 20 markers as small labeled dots above the price plot. Render a compact `News / events` list below the research stance.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `npm --workspace apps/web run test`

Expected: all lib tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/components/DashboardWorkspace.tsx apps/web/src/components/ChartWorkspace.tsx apps/web/src/app/globals.css apps/web/src/lib/workspace-data.test.ts
git commit -m "feat: add dashboard news markers"
```

## Task 4: Deep Research Workspace

**Files:**
- Create: `apps/web/src/components/DeepResearchWorkspace.tsx`
- Modify: `apps/web/src/components/AgentCockpit.tsx`
- Modify: `apps/web/src/app/globals.css`

- [ ] **Step 1: Write failing data test for research report seeds**

Extend `workspace-data.test.ts`:

```ts
import { getResearchReports } from "./workspace-data.ts";

it("returns research reports with ledger states for the selected symbol", () => {
  const reports = getResearchReports("NVDA");

  assert.ok(reports.length >= 3);
  assert.ok(reports.every((report) => report.symbol === "NVDA"));
  assert.ok(reports.every((report) => report.ledgerState.length > 0));
});
```

- [ ] **Step 2: Run tests and verify RED**

Run: `npm --workspace apps/web run test`

Expected: FAIL because `getResearchReports` is not implemented.

- [ ] **Step 3: Implement research data and component**

Add `getResearchReports(symbol)` to `workspace-data.ts`.

Create `DeepResearchWorkspace` with:

- left report list for selected symbol
- center report detail and decision ledger
- right `AgentCockpit` for run controls and agent DAG

Modify `AgentCockpit` to accept:

```ts
export function AgentCockpit({ showTradeTicket = true, symbol }: { showTradeTicket?: boolean; symbol: string }) {
```

Deep Research should pass `showTradeTicket={false}` so transactions own trade execution surfaces.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `npm --workspace apps/web run test`

Expected: all lib tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/components/DeepResearchWorkspace.tsx apps/web/src/components/AgentCockpit.tsx apps/web/src/app/globals.css apps/web/src/lib/workspace-data.ts apps/web/src/lib/workspace-data.test.ts
git commit -m "feat: add deep research workspace"
```

## Task 5: Agents Messenger Workspace

**Files:**
- Create: `apps/web/src/components/AgentsWorkspace.tsx`
- Modify: `apps/web/src/app/globals.css`
- Modify: `apps/web/src/lib/workspace-data.ts`
- Modify: `apps/web/src/lib/workspace-data.test.ts`

- [ ] **Step 1: Write failing message/action test**

Extend `workspace-data.test.ts`:

```ts
import { getAgentMessages, getConversationActions } from "./workspace-data.ts";

it("returns messages and action requests for an agent conversation", () => {
  const messages = getAgentMessages("research-lead-nvda");
  const actions = getConversationActions("research-lead-nvda");

  assert.ok(messages.some((message) => message.a2uiSurface === "event-chart"));
  assert.ok(actions.some((action) => action.type === "preview-order" && action.requiresApproval));
});
```

- [ ] **Step 2: Run tests and verify RED**

Run: `npm --workspace apps/web run test`

Expected: FAIL because message/action selectors are missing.

- [ ] **Step 3: Implement Agents workspace**

Implement selectors:

```ts
export function getAgentMessages(conversationId: string): AgentMessage[];
export function getConversationActions(conversationId: string): ActionRequest[];
```

Create `AgentsWorkspace` with:

- conversation list for agents, groups, and platform alerts
- center message stream
- A2UI-style embedded surface card in the message stream
- right action panel with proceed, ask follow-up, create report, and preview order actions

Keep this as seeded local UI; do not wire a real chat backend.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `npm --workspace apps/web run test`

Expected: all lib tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/components/AgentsWorkspace.tsx apps/web/src/app/globals.css apps/web/src/lib/workspace-data.ts apps/web/src/lib/workspace-data.test.ts
git commit -m "feat: add agents messenger workspace"
```

## Task 6: Transactions and Historicals Workspaces

**Files:**
- Create: `apps/web/src/components/TransactionsWorkspace.tsx`
- Create: `apps/web/src/components/HistoricalsWorkspace.tsx`
- Modify: `apps/web/src/app/globals.css`
- Modify: `apps/web/src/components/TradeTicket.tsx`

- [ ] **Step 1: Use existing data tests**

Task 1 already covers `getTransactionSnapshot` and `getHistoricalOutcomes`. Run them before implementation.

Run: `npm --workspace apps/web run test`

Expected: PASS before component work.

- [ ] **Step 2: Implement Transactions workspace**

Create a workspace with:

- portfolio balance
- top positions
- recent orders
- open approval intent
- right-side paper trade ticket

Modify `TradeTicket` only if needed to accept seeded order previews cleanly without API coupling. Keep approve/submit behavior approval-gated.

- [ ] **Step 3: Implement Historicals workspace**

Create a workspace with:

- prediction-vs-actual chart-like timeline
- acted-on research stances
- review tags
- feedback note panels

Use seeded `HistoricalOutcome` data only.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `npm --workspace apps/web run test`

Expected: all lib tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/components/TransactionsWorkspace.tsx apps/web/src/components/HistoricalsWorkspace.tsx apps/web/src/components/TradeTicket.tsx apps/web/src/app/globals.css
git commit -m "feat: add transactions and historicals workspaces"
```

## Task 7: Integrate Workspaces, Polish CSS, and Verify

**Files:**
- Modify: `apps/web/src/components/MarketShell.tsx`
- Modify: `apps/web/src/app/globals.css`

- [ ] **Step 1: Wire workspace switch**

`MarketShell` should render:

```tsx
const workspaceContent = {
  dashboard: <DashboardWorkspace symbol={selectedSymbol} />,
  research: <DeepResearchWorkspace symbol={selectedSymbol} />,
  agents: <AgentsWorkspace symbol={selectedSymbol} />,
  transactions: <TransactionsWorkspace symbol={selectedSymbol} />,
  historicals: <HistoricalsWorkspace symbol={selectedSymbol} />
}[activeWorkspace];
```

The page grid should remain watchlist left plus active workspace center/right. The Settings drawer and ToastStack should sit above every workspace.

- [ ] **Step 2: CSS polish**

Ensure:

- no nested card-on-card page sections
- workspace tabs fit on desktop
- the watchlist remains readable
- Agents uses a messenger layout
- Dashboard chart remains visually dominant
- Settings drawer is compact and utility-focused
- toast notifications do not block primary controls

- [ ] **Step 3: Full frontend verification**

Run:

```bash
npm --workspace apps/web run test
npm run web:lint
npm run web:build
```

Expected: all commands pass.

- [ ] **Step 4: Browser smoke**

Restart the web server if needed:

```bash
npm --workspace apps/web run start -- --hostname 0.0.0.0 --port 3000
```

Smoke checks:

- Dashboard loads at `http://127.0.0.1:3000/`.
- Watchlist selection changes symbol without leaving the active workspace.
- Each workspace tab changes the center view.
- Settings opens as a drawer and closes without changing workspace.
- Toast notifications appear and can be dismissed.
- Dashboard shows news markers and event list.
- Agents shows conversation list, message stream, and action panel.
- Transactions shows portfolio/order surfaces.
- Historicals shows prediction-vs-actual feedback surfaces.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/components/MarketShell.tsx apps/web/src/app/globals.css
git commit -m "feat: integrate workspace terminal shell"
```

## Self-Review

Spec coverage:

- Dashboard: covered by Task 3.
- Deep Research: covered by Task 4.
- Agents: covered by Task 5.
- Transactions: covered by Task 6.
- Historicals: covered by Task 6.
- Settings utility: covered by Task 2.
- Toaster notifications: covered by Task 2.
- Persistent watchlist and selected symbol: covered by Task 2 and Task 7.

No live market, news, brokerage, or collaboration provider work is included in this pass. That matches the approved scope.
