import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

describe("execution program panel", () => {
  it("imports durable execution program API methods and keeps live submission disabled", () => {
    const source = readFileSync(new URL("./ExecutionProgramPanel.tsx", import.meta.url), "utf-8");

    assert.match(source, /Execution Program Monitor/);
    assert.match(source, /listExecutionPrograms/);
    assert.match(source, /createExecutionProgram/);
    assert.match(source, /listExecutionProgramEvents/);
    assert.match(source, /appendExecutionProgramEvent/);
    assert.match(source, /buildExecutionProgramPreview/);
    assert.match(source, /Algorithm/);
    assert.match(source, /Triggers/);
    assert.match(source, /Circuit breakers/);
    assert.match(source, /Lifecycle timeline/);
    assert.match(source, /Paper mode/);
    assert.match(source, /Approval required/);
    assert.match(source, /No live trade submission/);
    assert.match(source, /Save paper preview/);
    assert.match(source, /preview_created/);
    assert.match(source, /symbol: string/);
    assert.doesNotMatch(source, /submitLiveTrade/);
    assert.doesNotMatch(source, /brokerMode: "live"/);
  });

  it("surfaces saved and recent execution program state plus missing provider facts", () => {
    const source = readFileSync(new URL("./ExecutionProgramPanel.tsx", import.meta.url), "utf-8");

    assert.match(source, /savedPrograms/);
    assert.match(source, /recentPrograms/);
    assert.match(source, /Recent saved programs/);
    assert.match(source, /Saved paper preview/);
    assert.match(source, /Durable API unavailable/);
    assert.match(source, /Missing provider facts/);
  });
});
