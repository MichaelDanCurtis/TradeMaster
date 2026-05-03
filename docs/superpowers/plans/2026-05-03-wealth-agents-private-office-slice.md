# Wealth Agents Private Office Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reframe the current operator UI into the first Wealth Agents private-office slice with a Deep Research agent workspace, collapsed market rail, coherent agent-team taxonomy, and no accidental commitment to the abandoned temporary market-data provider route.

**Architecture:** Keep this as a frontend/domain-seed slice inside the existing Next app. Add private-office domain seed data in `workspace-data.ts`, render it through focused UI components in `DeepResearchWorkspace.tsx`, and update shell behavior so the market watchlist collapses when Deep Research owns the center canvas. Provider/live-data cleanup stays isolated from the UI changes.

**Tech Stack:** Next.js App Router, React client components, TypeScript, `node:test`, existing CSS in `apps/web/src/app/globals.css`.

---

## File Structure

- Modify `apps/web/src/lib/workspace-data.ts`: add Wealth Agents private-office data types, seeded team/body data, morning brief data, run queue data, and accessors.
- Modify `apps/web/src/lib/workspace-data.test.ts`: add tests proving private-office data is present, symbol-scoped, and defensive-copied.
- Modify `apps/web/src/components/MarketShell.tsx`: rebrand the shell and pass a collapsed watchlist flag when Deep Research is active.
- Modify `apps/web/src/components/WatchlistRail.tsx`: support a collapsed watch rail mode with compact symbol-only buttons.
- Modify `apps/web/src/components/DeepResearchWorkspace.tsx`: replace the old report-detail center with the private-office A2UI canvas, report library, agent team hierarchy, and run queue.
- Modify `apps/web/src/app/globals.css`: add the private-office layout, collapsed rail, A2UI-style panels, and responsive behavior.
- Modify/remove `apps/web/src/app/api/market-data/route.ts` and related live-data references if they still point at the temporary Yahoo route. The route must be Webull-ready or explicitly disabled until Webull credentials exist.

## Task 1: Add Wealth Agents Seed Domain

**Files:**
- Modify: `apps/web/src/lib/workspace-data.ts`
- Modify: `apps/web/src/lib/workspace-data.test.ts`

- [ ] **Step 1: Write failing tests for private-office seed data**

Add these imports to `apps/web/src/lib/workspace-data.test.ts`:

```ts
import {
  getPrivateOfficeBrief,
  getPrivateOfficeRunQueue,
  getPrivateOfficeTeams
} from "./workspace-data.ts";
```

Add this test block:

```ts
it("returns the Wealth Agents private-office team hierarchy", () => {
  const teams = getPrivateOfficeTeams("NVDA");
  const ids = teams.map((team) => team.id);

  assert.ok(ids.includes("goals"));
  assert.ok(ids.includes("advisor"));
  assert.ok(ids.includes("capital-committee"));
  assert.ok(ids.includes("property"));
  assert.ok(ids.includes("communications"));
  assert.ok(teams.some((team) => team.riskClass === "approval-gated"));
  assert.ok(teams.every((team) => team.a2uiSurfaces.length > 0));
});

it("returns a symbol-scoped private-office morning brief", () => {
  const brief = getPrivateOfficeBrief("NVDA");

  assert.equal(brief.symbol, "NVDA");
  assert.ok(brief.headline.includes("Private Office"));
  assert.ok(brief.priorityItems.length >= 4);
  assert.ok(brief.goalSignals.some((signal) => signal.goalName.includes("yacht")));
  assert.ok(brief.controlSignals.some((signal) => signal.team === "Communications Team"));
});

it("returns independent private-office arrays", () => {
  const teams = getPrivateOfficeTeams("NVDA");
  const brief = getPrivateOfficeBrief("NVDA");
  const queue = getPrivateOfficeRunQueue("NVDA");

  teams[0].responsibilities.push("mutated responsibility");
  brief.priorityItems.push("mutated priority");
  queue[0].steps[0].status = "mutated";

  assert.ok(!getPrivateOfficeTeams("NVDA")[0].responsibilities.includes("mutated responsibility"));
  assert.ok(!getPrivateOfficeBrief("NVDA").priorityItems.includes("mutated priority"));
  assert.notEqual(getPrivateOfficeRunQueue("NVDA")[0].steps[0].status, "mutated");
});
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
npm --workspace apps/web run test -- workspace-data
```

Expected: FAIL because `getPrivateOfficeTeams`, `getPrivateOfficeBrief`, and `getPrivateOfficeRunQueue` are not exported.

- [ ] **Step 3: Add focused private-office types and accessors**

In `apps/web/src/lib/workspace-data.ts`, add:

```ts
export type PrivateOfficeRiskClass = "information" | "recommendation" | "paper" | "approval-gated";
export type PrivateOfficeTeamKind =
  | "goals"
  | "advisor"
  | "research"
  | "capital"
  | "control"
  | "property"
  | "communications";

export type PrivateOfficeTeam = {
  id: string;
  kind: PrivateOfficeTeamKind;
  name: string;
  mission: string;
  cadence: string;
  riskClass: PrivateOfficeRiskClass;
  responsibilities: string[];
  a2uiSurfaces: string[];
  currentFocus: string;
};

export type PrivateOfficeBrief = {
  symbol: string;
  headline: string;
  generatedAt: string;
  priorityItems: string[];
  goalSignals: Array<{
    goalName: string;
    status: string;
    detail: string;
  }>;
  controlSignals: Array<{
    team: string;
    severity: "info" | "watch" | "urgent";
    detail: string;
  }>;
};

export type PrivateOfficeRunQueueItem = {
  id: string;
  title: string;
  team: string;
  status: "running" | "queued" | "waiting" | "complete";
  startedAt: string;
  steps: Array<{
    label: string;
    status: "running" | "queued" | "waiting" | "complete";
  }>;
};
```

Then add seed arrays and exported accessors that return defensive copies:

```ts
export function getPrivateOfficeTeams(symbol: string): PrivateOfficeTeam[] {
  const normalizedSymbol = normalizeSymbol(symbol);

  return PRIVATE_OFFICE_TEAMS.map((team) => ({
    ...team,
    responsibilities: team.responsibilities.map((responsibility) =>
      responsibility.replaceAll("{symbol}", normalizedSymbol)
    ),
    a2uiSurfaces: [...team.a2uiSurfaces],
    currentFocus: team.currentFocus.replaceAll("{symbol}", normalizedSymbol)
  }));
}

export function getPrivateOfficeBrief(symbol: string): PrivateOfficeBrief {
  const normalizedSymbol = normalizeSymbol(symbol);

  return {
    ...PRIVATE_OFFICE_BRIEF,
    symbol: normalizedSymbol,
    priorityItems: PRIVATE_OFFICE_BRIEF.priorityItems.map((item) => item.replaceAll("{symbol}", normalizedSymbol)),
    goalSignals: PRIVATE_OFFICE_BRIEF.goalSignals.map((signal) => ({ ...signal })),
    controlSignals: PRIVATE_OFFICE_BRIEF.controlSignals.map((signal) => ({ ...signal }))
  };
}

export function getPrivateOfficeRunQueue(symbol: string): PrivateOfficeRunQueueItem[] {
  const normalizedSymbol = normalizeSymbol(symbol);

  return PRIVATE_OFFICE_RUN_QUEUE.map((item) => ({
    ...item,
    title: item.title.replaceAll("{symbol}", normalizedSymbol),
    steps: item.steps.map((step) => ({ ...step }))
  }));
}
```

- [ ] **Step 4: Run tests and verify they pass**

Run:

```bash
npm --workspace apps/web run test -- workspace-data
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/lib/workspace-data.ts apps/web/src/lib/workspace-data.test.ts
git commit -m "feat: add private office seed data"
```

## Task 2: Rebrand Shell And Collapse Watch Rail

**Files:**
- Modify: `apps/web/src/components/MarketShell.tsx`
- Modify: `apps/web/src/components/WatchlistRail.tsx`
- Modify: `apps/web/src/app/globals.css`

- [ ] **Step 1: Add collapsed watch rail prop**

Change `WatchlistRail` props:

```ts
export function WatchlistRail({
  items,
  selectedSymbol,
  collapsed = false,
  onSelect
}: {
  items: WatchlistItem[];
  selectedSymbol: string;
  collapsed?: boolean;
  onSelect: (symbol: string) => void;
}) {
```

Use `className={collapsed ? "watchlist-rail collapsed" : "watchlist-rail"}` and render compact symbols when collapsed:

```tsx
{collapsed ? (
  <span className="watchlist-compact-symbol">{item.symbol}</span>
) : (
  <>
    <span className="watchlist-symbol">
      <strong>{item.symbol}</strong>
      <small>{item.name}</small>
    </span>
    <span className="watchlist-quote">
      <span>{item.price.toFixed(2)}</span>
      <span className={item.changePercent >= 0 ? "positive" : "negative"}>
        {item.changePercent >= 0 ? "+" : ""}
        {item.changePercent.toFixed(2)}%
      </span>
    </span>
  </>
)}
```

- [ ] **Step 2: Rebrand shell and pass collapsed state**

In `MarketShell.tsx`, change brand copy:

```tsx
<span className="brand-mark">WA</span>
<div>
  <strong>Wealth Agents</strong>
  <span>Private Office</span>
</div>
```

Change topbar status:

```tsx
<span className="status-pill online">Local server</span>
<span className="status-pill paper">Approval gated</span>
<span className="session-clock">MacBook private office</span>
```

Pass collapsed flag:

```tsx
<WatchlistRail
  collapsed={shellState.activeWorkspace === "research"}
  items={WATCHLIST}
  selectedSymbol={shellState.selectedSymbol}
  onSelect={handleSelectSymbol}
/>
```

- [ ] **Step 3: Add CSS for collapsed rail**

Add:

```css
.market-shell:has(.watchlist-rail.collapsed) {
  grid-template-columns: 72px minmax(440px, 1fr);
}

.watchlist-rail.collapsed {
  padding: 10px 8px;
}

.watchlist-rail.collapsed .panel-header,
.watchlist-rail.collapsed .rail-micro-panel {
  display: none;
}

.watchlist-rail.collapsed .watchlist-list {
  gap: 8px;
}

.watchlist-rail.collapsed .watchlist-item {
  place-items: center;
  min-height: 44px;
  padding: 0;
}

.watchlist-compact-symbol {
  color: #dbe5ee;
  font-size: 11px;
  font-weight: 900;
}
```

- [ ] **Step 4: Verify lint and build after shell change**

Run:

```bash
npm run web:lint
npm run web:build
```

Expected: both PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/components/MarketShell.tsx apps/web/src/components/WatchlistRail.tsx apps/web/src/app/globals.css
git commit -m "feat: reframe shell for wealth agents"
```

## Task 3: Build Deep Research Private-Office Workspace

**Files:**
- Modify: `apps/web/src/components/DeepResearchWorkspace.tsx`
- Modify: `apps/web/src/app/globals.css`

- [ ] **Step 1: Import private-office data**

Add imports:

```ts
import {
  getPrivateOfficeBrief,
  getPrivateOfficeRunQueue,
  getPrivateOfficeTeams,
  getResearchReports
} from "@/lib/workspace-data";
import type { PrivateOfficeBrief, PrivateOfficeRunQueueItem, PrivateOfficeTeam, ResearchReport } from "@/lib/workspace-data";
```

- [ ] **Step 2: Load brief, teams, and queue**

Inside `DeepResearchWorkspace`:

```ts
const brief = useMemo(() => getPrivateOfficeBrief(symbol), [symbol]);
const teams = useMemo(() => getPrivateOfficeTeams(symbol), [symbol]);
const runQueue = useMemo(() => getPrivateOfficeRunQueue(symbol), [symbol]);
```

- [ ] **Step 3: Replace center detail with A2UI canvas**

Render:

```tsx
<section className="deep-research-workspace" aria-label="Deep Research private office workspace">
  <ReportList reports={reports} selectedReportId={selectedReport?.id ?? null} onSelectReport={setSelectedReportId} />
  <PrivateOfficeCanvas brief={brief} teams={teams} report={selectedReport} symbol={symbol} />
  <RunningReportsPanel queue={runQueue} symbol={symbol} />
</section>
```

Add focused components:

```tsx
function PrivateOfficeCanvas({
  brief,
  teams,
  report,
  symbol
}: {
  brief: PrivateOfficeBrief;
  teams: PrivateOfficeTeam[];
  report: ResearchReport | null;
  symbol: string;
}) {
  return (
    <article className="private-office-canvas">
      <header className="workspace-header private-office-header">
        <div>
          <span className="panel-kicker">A2UI agent canvas</span>
          <h1>{brief.headline}</h1>
        </div>
        <div className="research-meta-strip">
          <span>{symbol}</span>
          <span>{formatDate(brief.generatedAt)}</span>
          <span>Approval gated</span>
        </div>
      </header>
      <section className="a2ui-morning-brief">
        <div className="section-title">
          <span>Morning synopsis</span>
          <strong>{brief.priorityItems.length}</strong>
        </div>
        <ol>
          {brief.priorityItems.map((item, index) => (
            <li key={item}>
              <span>{String(index + 1).padStart(2, "0")}</span>
              <p>{item}</p>
            </li>
          ))}
        </ol>
      </section>
      <section className="private-office-grid">
        <GoalSignalPanel brief={brief} />
        <ControlSignalPanel brief={brief} />
      </section>
      <TeamBodyGrid teams={teams} />
      {report ? <ReportA2UIPanel report={report} /> : null}
    </article>
  );
}
```

- [ ] **Step 4: Add running report queue**

Add:

```tsx
function RunningReportsPanel({ queue, symbol }: { queue: PrivateOfficeRunQueueItem[]; symbol: string }) {
  return (
    <aside className="running-reports-panel">
      <header className="panel-header">
        <div>
          <span className="panel-kicker">Running reports</span>
          <h2>{symbol} queue</h2>
        </div>
        <span className="panel-count">{queue.length}</span>
      </header>
      <div className="run-queue-list">
        {queue.map((item) => (
          <section className="run-queue-card" key={item.id}>
            <div>
              <span className={`run-state ${item.status}`}>{item.status}</span>
              <strong>{item.title}</strong>
              <small>{item.team}</small>
            </div>
            <ol>
              {item.steps.map((step) => (
                <li key={step.label}>
                  <span className={`step-dot ${step.status}`} />
                  {step.label}
                </li>
              ))}
            </ol>
          </section>
        ))}
      </div>
    </aside>
  );
}
```

- [ ] **Step 5: Add CSS for private-office workspace**

Add CSS classes for `.private-office-canvas`, `.running-reports-panel`, `.a2ui-morning-brief`, `.private-office-grid`, `.team-body-grid`, `.team-body-card`, `.run-queue-card`, and `.step-dot`. Keep cards at 7px radius or below to match the current design.

- [ ] **Step 6: Verify**

Run:

```bash
npm --workspace apps/web run test -- workspace-data
npm run web:lint
npm run web:build
```

Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/web/src/components/DeepResearchWorkspace.tsx apps/web/src/app/globals.css
git commit -m "feat: add private office deep research workspace"
```

## Task 4: Clean Temporary Market Data Route

**Files:**
- Modify/delete: `apps/web/src/app/api/market-data/route.ts`
- Modify/delete: `apps/web/src/lib/live-market-data.ts`
- Modify/delete: `apps/web/src/lib/live-market-data.test.ts`
- Modify: `apps/web/src/lib/market-data.ts`
- Modify: `apps/web/src/lib/market-data.test.ts`
- Modify: `apps/web/src/components/ChartWorkspace.tsx`

- [ ] **Step 1: Find temporary provider references**

Run:

```bash
rg -n "Yahoo|yahoo|live-market-data|fetchYahoo|market-data\\?symbol" apps/web/src
```

Expected: list every temporary route/client/provider reference.

- [ ] **Step 2: Disable or pivot the route**

If Webull signing is not implemented yet, make `/api/market-data` return a clear disabled-provider response instead of calling Yahoo:

```ts
import { NextResponse } from "next/server";

export async function GET() {
  return NextResponse.json(
    {
      error: "Webull market-data credentials are not configured yet. The UI is using simulated private-office market context until Webull OpenAPI keys are added."
    },
    { status: 503 }
  );
}
```

- [ ] **Step 3: Remove Yahoo provider catalog entries**

Ensure `apps/web/src/lib/market-data.ts` includes Webull, Alpaca, Polygon, OpenBB, Benzinga, and SEC/alternative-data candidates as planned, but does not add Yahoo as an official provider.

- [ ] **Step 4: Update tests**

Remove Yahoo-specific tests. Add a provider assertion like:

```ts
assert.ok(getMarketProviderCatalog().some((provider) => provider.id === "webull"));
assert.ok(!getMarketProviderCatalog().some((provider) => provider.id === "yahoo"));
```

- [ ] **Step 5: Verify**

Run:

```bash
npm --workspace apps/web run test
npm run web:lint
npm run web:build
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/web/src/app/api/market-data/route.ts apps/web/src/lib/market-data.ts apps/web/src/lib/market-data.test.ts apps/web/src/components/ChartWorkspace.tsx
git add -f apps/web/src/lib/live-market-data.ts apps/web/src/lib/live-market-data.test.ts || true
git commit -m "chore: remove temporary yahoo market data path"
```

## Task 5: Final Verification And Server Restart

**Files:**
- No code changes unless verification finds a defect.

- [ ] **Step 1: Run full web and Python checks**

Run:

```bash
npm --workspace apps/web run test
npm run web:lint
npm run web:build
PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest -p no:cacheprovider tests/ui -q
git diff --check
```

Expected: all PASS.

- [ ] **Step 2: Restart local web server**

Run:

```bash
lsof -nP -iTCP:3000 -sTCP:LISTEN
```

If an old Next server is running, stop that process and start:

```bash
npm --workspace apps/web run start -- --hostname 0.0.0.0 --port 3000
```

Expected: app is available at `http://127.0.0.1:3000/`.

- [ ] **Step 3: Manual browser check**

Open `http://127.0.0.1:3000/`, click **Deep Research**, and verify:

- watch rail collapses to a compact symbol strip
- center is the A2UI private-office canvas
- report library remains on the left of the canvas
- running reports remain on the right
- shell says Wealth Agents / Private Office
- no UI surface claims live Webull data is enabled without keys

- [ ] **Step 4: Commit final fixes if needed**

If verification required changes:

```bash
git add <changed-files>
git commit -m "fix: polish private office workspace"
```

## Self-Review

Spec coverage:

- Wealth Agents as system of record: Task 2 and Task 3.
- Hermes separation: documented in the approved spec; not implemented in UI because no Hermes integration is needed in this first slice.
- MacBook server and backup: represented in shell status and private-office seed data; full backup implementation is a later slice.
- A2A/A2UI: Task 1 models A2UI surfaces; Task 3 renders A2UI-style surfaces. Actual A2A runtime is a later backend slice.
- iOS/macOS/web: documented in the approved spec; this plan implements the web first.
- Webull/API waiting state: Task 4 prevents the temporary Yahoo route from becoming product behavior.

Placeholder scan: no task uses TBD/TODO/fill-in language. Open implementation questions remain in the design spec, not this implementation plan.

Type consistency: `PrivateOfficeTeam`, `PrivateOfficeBrief`, and `PrivateOfficeRunQueueItem` are introduced in Task 1 and consumed in Task 3 with matching names.

