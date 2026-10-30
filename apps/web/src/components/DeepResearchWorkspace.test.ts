import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

describe("deep research workspace sidebar", () => {
  it("shows actionable report session navigation instead of an empty sidebar", () => {
    const source = readFileSync(new URL("./DeepResearchWorkspace.tsx", import.meta.url), "utf-8");

    assert.match(source, /research-session-list/);
    assert.match(source, /Current run/);
    assert.match(source, /Report output/);
    assert.match(source, /Stored reports/);
    assert.match(source, /research-meta-strip/);
    assert.doesNotMatch(source, /No persisted research reports are loaded/);
  });

  it("labels deterministic fallback research instead of implying every run used an LLM", () => {
    const source = readFileSync(new URL("./DeepResearchWorkspace.tsx", import.meta.url), "utf-8");

    assert.match(source, /formatDecisionSource/);
    assert.match(source, /Deterministic fallback/);
    assert.match(source, /LLM synthesis/);
    assert.doesNotMatch(source, /actual LLM-backed runner/);
  });

  it("renders a readable report inspector for individual agent updates", () => {
    const source = readFileSync(new URL("./DeepResearchWorkspace.tsx", import.meta.url), "utf-8");
    const panelSource = readFileSync(new URL("./AgentReportsPanel.tsx", import.meta.url), "utf-8");

    assert.match(source, /deriveAgentReports/);
    assert.match(source, /AgentReportsPanel/);
    assert.match(panelSource, /Individual agent reports/);
    assert.match(panelSource, /Report list/);
    assert.match(panelSource, /Report details/);
    assert.match(panelSource, /aria-current/);
    assert.match(source, /selectedReportId/);
  });

  it("labels the final report reader as advisory and separate from broker orders", () => {
    const source = readFileSync(new URL("./DeepResearchWorkspace.tsx", import.meta.url), "utf-8");

    assert.match(source, /Final advisory report/);
    assert.match(source, /Research only - not an order/);
    assert.match(source, /individual agent reports below/);
  });

  it("loads and opens persisted symbol reports from the research rail", () => {
    const source = readFileSync(new URL("./DeepResearchWorkspace.tsx", import.meta.url), "utf-8");

    assert.match(source, /listRuns/);
    assert.match(source, /recentRuns/);
    assert.match(source, /Stored reports/);
    assert.match(source, /openPersistedRun/);
    assert.match(source, /listRunEvents\(selectedRun.run_id\)/);
  });

  it("uses the shared live event stream and finalizes from terminal events", () => {
    const source = readFileSync(new URL("./DeepResearchWorkspace.tsx", import.meta.url), "utf-8");
    const stream = readFileSync(new URL("../lib/useRunEventStream.ts", import.meta.url), "utf-8");

    assert.match(source, /useRunEventStream\(liveRunId\)/);
    assert.match(source, /setEvents\(liveStream.events\)/);
    assert.match(source, /isTerminalRun/);
    assert.match(stream, /openRunEventSource\(runId\)/);
    assert.match(stream, /listRunEvents\(runId\)/);
    assert.match(stream, /source\?\.close\(\)/);
  });

  it("exposes a workspace-header research-header block with run and export controls", () => {
    const source = readFileSync(new URL("./DeepResearchWorkspace.tsx", import.meta.url), "utf-8");

    assert.match(source, /workspace-header research-header/);
    assert.match(source, /Run research/);
    assert.match(source, /Export trace/);
    // The redundant in-canvas private-office-header was consolidated into the
    // single top-of-page research-header. Guard against regressions that bring
    // back the duplicate header block.
    assert.doesNotMatch(source, /private-office-header/);
    assert.doesNotMatch(source, /A2UI agent canvas/);
  });

  it("collapses the trace plumbing behind a research-trace-disclosure", () => {
    const source = readFileSync(new URL("./DeepResearchWorkspace.tsx", import.meta.url), "utf-8");

    assert.match(source, /research-trace-disclosure/);
    assert.match(source, /<details className="research-trace-disclosure">/);
    assert.match(source, /Inspect run · trace, agent graph, timeline/);
  });

  it("can turn research output into an advisory order thesis handoff", () => {
    const source = readFileSync(new URL("./DeepResearchWorkspace.tsx", import.meta.url), "utf-8");

    assert.match(source, /OrderThesisPanel/);
    assert.match(source, /sourceReportId=\{runId\}/);
    assert.match(source, /onOpenBrokerage=\{onOpenBrokerage\}/);
    assert.match(source, /onOpenBrokerage: \(\) => void/);
    assert.doesNotMatch(source, /submitOrder|placeOrder|createOrder|submitTrade|placeTrade|createTrade/);
  });

  it("does not retain dead helpers from the prior v2 IA scrub", () => {
    const source = readFileSync(new URL("./DeepResearchWorkspace.tsx", import.meta.url), "utf-8");

    // `formatDecisionSummary` had zero callers after the IA flattening — it
    // was deleted along with its `stripMarkdown` helper. Guard against the
    // accidental return of dead code.
    assert.doesNotMatch(source, /formatDecisionSummary/);
    assert.doesNotMatch(source, /function stripMarkdown/);
  });
});
