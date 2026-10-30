# Wealth Agents Agents Console And Goals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the Agents tab into the private-office communications console and add a seeded material-goal dossier for the yacht acquisition path.

**Architecture:** Extend the existing `workspace-data.ts` seed layer with channel, message, action, and goal-dossier records. Replace the Agents workspace UI with a team-channel console that uses that seed data, keeping all behavior local and deterministic. Style the new console in the existing CSS file without adding new dependencies.

**Tech Stack:** Next.js App Router, React client components, TypeScript, `node:test`, existing global CSS.

---

## File Structure

- Modify `apps/web/src/lib/workspace-data.ts`: add private-office channel and goal-dossier types, seed data, and defensive-copy accessors.
- Modify `apps/web/src/lib/workspace-data.test.ts`: add tests for private-office channels, action triage, and the yacht goal dossier.
- Modify `apps/web/src/components/AgentsWorkspace.tsx`: render private-office team channels, message stream, action triage, and selected goal dossier.
- Modify `apps/web/src/app/globals.css`: add console, channel, triage, and goal-dossier styling.

## Task 1: Add Channel And Goal Data

**Files:**
- Modify: `apps/web/src/lib/workspace-data.ts`
- Modify: `apps/web/src/lib/workspace-data.test.ts`

- [ ] **Step 1: Write failing tests**

Add imports:

```ts
getPrivateOfficeChannelActions,
getPrivateOfficeChannelMessages,
getPrivateOfficeChannels,
getPrivateOfficeGoalDossier,
```

Add tests:

```ts
it("returns private-office team channels with triage metadata", () => {
  const channels = getPrivateOfficeChannels("NVDA");
  const ids = channels.map((channel) => channel.id);

  assert.deepEqual(ids.slice(0, 4), ["advisor", "goals", "capital-committee", "communications"]);
  assert.ok(channels.some((channel) => channel.notifyMichael === true));
  assert.ok(channels.some((channel) => channel.delivery === "internal"));
  assert.ok(channels.every((channel) => channel.a2uiSurface.length > 0));
});

it("returns private-office channel messages and actions", () => {
  const messages = getPrivateOfficeChannelMessages("goals", "NVDA");
  const actions = getPrivateOfficeChannelActions("goals", "NVDA");

  assert.ok(messages.some((message) => message.author === "Goal Steward"));
  assert.ok(actions.some((action) => action.status === "requires-approval"));
  assert.ok(actions.some((action) => action.delivery === "internal"));
});

it("returns independent yacht goal dossier data", () => {
  const dossier = getPrivateOfficeGoalDossier("NVDA");

  assert.ok(dossier.goalName.toLowerCase().includes("yacht"));
  assert.ok(dossier.assetTarget.includes("68"));
  assert.ok(dossier.blockers.some((blocker) => blocker.owner === "Tax & Structure Body"));
  assert.ok(dossier.capitalPath.some((item) => item.includes("NVDA")));

  dossier.blockers[0].detail = "mutated";
  dossier.capitalPath.push("mutated");

  const fresh = getPrivateOfficeGoalDossier("NVDA");
  assert.notEqual(fresh.blockers[0].detail, "mutated");
  assert.ok(!fresh.capitalPath.includes("mutated"));
});
```

- [ ] **Step 2: Run test and verify failure**

Run:

```bash
npm --workspace apps/web run test -- workspace-data
```

Expected: FAIL because the new exports do not exist.

- [ ] **Step 3: Implement seed types and accessors**

Add exported types for `PrivateOfficeChannel`, `PrivateOfficeChannelMessage`, `PrivateOfficeChannelAction`, and `PrivateOfficeGoalDossier`. Add deterministic seed data for Advisor, Goals, Capital Committee, Communications, Property, Tax & Structure, Research Bodies, and Document Vault. Add accessors that replace `{symbol}` and return defensive copies.

- [ ] **Step 4: Run test and verify pass**

Run:

```bash
npm --workspace apps/web run test -- workspace-data
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -f apps/web/src/lib/workspace-data.ts apps/web/src/lib/workspace-data.test.ts
git commit -m "feat: add private office channels and goal dossier"
```

## Task 2: Replace Agents Workspace With Private-Office Console

**Files:**
- Modify: `apps/web/src/components/AgentsWorkspace.tsx`

- [ ] **Step 1: Replace data imports**

Use the private-office channel and goal accessors instead of the old stock-conversation accessors.

- [ ] **Step 2: Render three console columns**

Left column: team channels with urgency, delivery, unread count, and notify state.

Center column: selected channel message stream with A2UI surface cards for morning brief, goal dossier, approval triage, and document checklist.

Right column: action triage and the yacht goal dossier.

- [ ] **Step 3: Keep selection behavior stable**

Default to the first channel and reset selection when the selected symbol changes.

- [ ] **Step 4: Run checks**

Run:

```bash
npm --workspace apps/web run test -- workspace-data
npm run web:lint
npm run web:build
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/components/AgentsWorkspace.tsx
git commit -m "feat: add private office agents console"
```

## Task 3: Style Agents Console And Goal Dossier

**Files:**
- Modify: `apps/web/src/app/globals.css`

- [ ] **Step 1: Add console styles**

Add styles for private-office channel buttons, message cards, A2UI surface chips, action triage cards, goal dossier, blocker rows, and capital path rows.

- [ ] **Step 2: Add responsive behavior**

Keep three columns on desktop, stack action panel below on medium screens, and preserve readable text on mobile widths.

- [ ] **Step 3: Run checks**

Run:

```bash
npm run web:lint
npm run web:build
git diff --check
```

Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
git add apps/web/src/app/globals.css
git commit -m "style: polish private office agents console"
```

## Task 4: Final Verification

**Files:**
- No planned code changes.

- [ ] **Step 1: Run full verification**

Run:

```bash
npm --workspace apps/web run test
npm run web:lint
npm run web:build
PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest -p no:cacheprovider tests/ui -q
git diff --check
```

Expected: all PASS.

- [ ] **Step 2: Restart local server from this worktree**

Run:

```bash
tmux kill-session -t wealth-agents-web 2>/dev/null || true
tmux new-session -d -s wealth-agents-web "cd '/path/to/TradeMaster/.worktrees/wealth-agents-v11' && npm --workspace apps/web run start -- --hostname 0.0.0.0 --port 3000"
sleep 1
curl -I http://127.0.0.1:3000/
```

Expected: HTTP 200.

## Self-Review

Spec coverage:

- Agent team channels: Task 1 and Task 2.
- Communications triage: Task 1 and Task 2.
- Goal dossier: Task 1 and Task 2.
- Web/macOS/iOS architecture: unchanged from prior spec; this is web-first.
- Hermes boundary: represented through Communications channel copy, not integrated.

Placeholder scan: no TBD/TODO/fill-in language remains.

Type consistency: channel, message, action, and goal dossier types are introduced in Task 1 and consumed in Task 2.

