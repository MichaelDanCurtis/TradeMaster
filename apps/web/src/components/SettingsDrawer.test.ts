import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

describe("settings provider routing", () => {
  it("lets the operator choose providers for agent roles", () => {
    const source = readFileSync(new URL("./SettingsDrawer.tsx", import.meta.url), "utf-8");

    assert.match(source, /listProviderRoleAssignments/);
    assert.match(source, /updateProviderRoleAssignment/);
    assert.match(source, /Provider role routing/);
    assert.match(source, /research_llm/);
    assert.match(source, /execution_llm/);
    assert.match(source, /market_data/);
    assert.match(source, /broker/);
    assert.match(source, /safety/);
  });

  it("shows runtime wiring status beside provider configuration", () => {
    const source = readFileSync(new URL("./SettingsDrawer.tsx", import.meta.url), "utf-8");

    assert.match(source, /getRuntimeStatus/);
    assert.match(source, /Runtime wiring/);
    assert.match(source, /Research runner/);
    assert.match(source, /Full graph/);
    assert.match(source, /formatFullGraphStatus/);
    assert.match(source, /TRADEMASTER_ENABLE_REAL_RUNS=1/);
    assert.match(source, /Fallback expected/);
    assert.match(source, /Execution policy/);
  });

  it("lets settings switch between safe synthesis and the full graph runner", () => {
    const source = readFileSync(new URL("./SettingsDrawer.tsx", import.meta.url), "utf-8");

    assert.match(source, /updateResearchRunnerMode/);
    assert.match(source, /Runner control/);
    assert.match(source, /Safe synthesis/);
    assert.match(source, /Full TradingAgents graph/);
    assert.match(source, /handleResearchRunnerModeChange/);
  });

  it("marks experimental Codex-style sources as developer mode", () => {
    const source = readFileSync(new URL("./SettingsDrawer.tsx", import.meta.url), "utf-8");

    assert.match(source, /isDeveloperModeProvider/);
    assert.match(source, /Developer mode/);
    assert.match(source, /Unsupported for full graph/);
  });

  it("surfaces a snapshot history list with per-record verify actions", () => {
    const source = readFileSync(new URL("./SettingsDrawer.tsx", import.meta.url), "utf-8");

    // RoomRoadmapPanel was removed in the 4-tab IA flattening
    // (2026-05-20); the snapshot history now lives in this section
    // instead.
    assert.match(source, /listSnapshots/);
    assert.match(source, /snapshot-history/);
    assert.match(source, /handleVerifySnapshot/);
  });
});
