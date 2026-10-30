import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { deriveAgentReports } from "./agent-reports.ts";
import type { RunEvent } from "./types.ts";

describe("agent report derivation", () => {
  it("turns report update events into readable individual agent reports", () => {
    const reports = deriveAgentReports([
      makeEvent({
        node: "Market Analyst",
        message: "Updated market report.",
        payload: { report: "VWAP reclaimed and volume confirmed the move.", section: "market" }
      }),
      makeEvent({
        node: "Risk Manager",
        message: "Attached risk notes.",
        payload: { risk_notes: "Limit sizing until drawdown guard clears.", section: "risk_review" }
      })
    ]);

    assert.deepEqual(
      reports.map((report) => [report.agentName, report.section, report.body]),
      [
        ["Market Analyst", "market", "VWAP reclaimed and volume confirmed the move."],
        ["Risk Manager", "risk_review", "Limit sizing until drawdown guard clears."]
      ]
    );
  });

  it("falls back to the event message when a runner has not attached report text yet", () => {
    const reports = deriveAgentReports([
      makeEvent({
        node: "Bull Researcher",
        message: "Prepared constructive case from analyst packets.",
        payload: { section: "bull_thesis", fallback: true }
      })
    ]);

    assert.equal(reports[0].body, "Prepared constructive case from analyst packets.");
    assert.equal(reports[0].sourceLabel, "Deterministic fallback");
  });

  it("labels every individual agent output as advisory research rather than an order", () => {
    const reports = deriveAgentReports([
      makeEvent({
        node: "Portfolio Manager",
        message: "Final decision ready.",
        payload: { report: "Maintain paper-only observation until risk review clears.", section: "decision" }
      })
    ]);

    assert.equal(reports[0].advisoryLabel, "Advisory research - not an order");
  });

  it("replaces non-English risk-note payloads with an English notice", () => {
    const reports = deriveAgentReports([
      makeEvent({
        node: "Risk Manager",
        message: "Risk notes attached.",
        payload: { risk_notes: "\u9ad8\u5ea6\u4f30\u503c\u654f\u611f\u6027", section: "risk_review" }
      })
    ]);

    assert.equal(
      reports[0].body,
      "Report text was returned in a non-English language. Re-run the report with the English-only research setting to regenerate this section."
    );
  });
});

function makeEvent(overrides: Partial<RunEvent>): RunEvent {
  return {
    created_at: "2026-05-06T12:00:00Z",
    message: "Updated report.",
    node: "Market Analyst",
    payload: {},
    run_id: "run_123",
    sequence: 1,
    type: "report.updated",
    ...overrides
  };
}
