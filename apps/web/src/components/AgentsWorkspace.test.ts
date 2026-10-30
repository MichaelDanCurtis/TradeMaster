import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

describe("agents workspace operator controls", () => {
  it("keeps selected-advisor research, reports and traces in the current workspace", () => {
    const source = readFileSync(new URL("./AgentsWorkspace.tsx", import.meta.url), "utf-8");

    assert.match(source, /Selected advisor/);
    assert.match(source, /onClick=\{startRun\} disabled=\{isRunning\}/);
    assert.match(source, /startRun/);
    assert.match(source, /research_report/);
    assert.match(source, /Final report/);
    assert.doesNotMatch(source, /<AdvisorNarrativePanel/);
    assert.match(source, /<AgentRunGraph events=\{events\}/);
    assert.match(source, /<RunTimeline events=\{events\}/);
  });

  it("explains research and execution agent classes", () => {
    const source = readFileSync(new URL("./AgentsWorkspace.tsx", import.meta.url), "utf-8");

    assert.match(source, /Research Agents/);
    assert.match(source, /Execution Agents/);
    assert.match(source, /researchAgentGroups/);
    assert.match(source, /executionAgentGroups/);
    assert.match(source, /PyReason/);
    assert.match(source, /LangGraph/);
  });

  it("shows each selected agent role, authority, and current state", () => {
    const source = readFileSync(new URL("./AgentsWorkspace.tsx", import.meta.url), "utf-8");

    assert.match(source, /Role/);
    assert.match(source, /Authority/);
    assert.match(source, /Current state/);
    assert.match(source, /formatAgentAuthority/);
    assert.match(source, /formatActivityState/);
  });

  it("creates visible queued activity through agent operations or local fallback", () => {
    const source = readFileSync(new URL("./AgentsWorkspace.tsx", import.meta.url), "utf-8");

    assert.match(source, /createAgentOperation/);
    assert.match(source, /completeAgentOperation/);
    assert.match(source, /operatorActivities/);
    assert.match(source, /queueLocalActivity/);
    assert.match(source, /Agent operations queue/);
    assert.match(source, /Preview execution/);
    assert.match(source, /"research_report"/);
    assert.match(source, /"execution_preview"/);
  });

  it("does not use live-trade language in the Agents workspace", () => {
    const source = readFileSync(new URL("./AgentsWorkspace.tsx", import.meta.url), "utf-8");

    assert.doesNotMatch(source, /live[- ]?trade/i);
    assert.doesNotMatch(source, /live broker/i);
    assert.doesNotMatch(source, /brokerMode: "live"/);
    assert.doesNotMatch(source, /submitTrade/);
  });

  it("lets operators read individual agent reports from a run", () => {
    const source = readFileSync(new URL("./AgentsWorkspace.tsx", import.meta.url), "utf-8");
    const panelSource = readFileSync(new URL("./AgentReportsPanel.tsx", import.meta.url), "utf-8");

    assert.match(source, /deriveAgentReports/);
    assert.match(source, /AgentReportsPanel/);
    assert.match(source, /selectedReportId/);
    assert.match(panelSource, /Individual agent reports/);
  });

  it("shows whether agent reports are using the full TradingAgents graph runner", () => {
    const source = readFileSync(new URL("./AgentsWorkspace.tsx", import.meta.url), "utf-8");

    assert.match(source, /getRuntimeStatus/);
    assert.match(source, /Full TradingAgents graph/);
    assert.match(source, /formatRunnerMode/);
    assert.match(source, /TRADEMASTER_ENABLE_REAL_RUNS=1/);
  });

  it("polls real graph runs instead of assuming createRun returns a final report", () => {
    const source = readFileSync(new URL("./AgentsWorkspace.tsx", import.meta.url), "utf-8");

    assert.match(source, /waitForRunEvents/);
    assert.match(source, /onEvents/);
    assert.match(source, /isTerminalRun/);
  });
});
