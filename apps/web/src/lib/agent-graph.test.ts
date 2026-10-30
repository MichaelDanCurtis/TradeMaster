import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { deriveAgentGraphNodes } from "./agent-graph.ts";
import type { RunEvent } from "./types.ts";

describe("agent graph derivation", () => {
  it("maps run events into visible agent graph states", () => {
    const events: RunEvent[] = [
      makeEvent(1, "run.created", null),
      makeEvent(2, "run.started", null),
      makeEvent(3, "agent.started", "Market Analyst"),
      makeEvent(4, "tool.called", "Market Analyst"),
      makeEvent(5, "report.updated", "Market Analyst"),
      makeEvent(6, "agent.started", "News Analyst"),
      makeEvent(7, "agent.started", "Bull Researcher"),
      makeEvent(8, "report.updated", "Bull Researcher"),
      makeEvent(9, "agent.started", "Trader"),
      makeEvent(10, "report.updated", "Trader"),
      makeEvent(11, "agent.started", "Portfolio Manager"),
      makeEvent(12, "decision.created", "Portfolio Manager"),
      makeEvent(13, "trade.previewed", "Broker"),
      makeEvent(14, "run.completed", null)
    ];

    const nodes = deriveAgentGraphNodes(events);
    const byId = Object.fromEntries(nodes.map((node) => [node.id, node]));

    assert.equal(byId.start.status, "complete");
    assert.equal(byId.market.status, "complete");
    assert.equal(byId.news.status, "running");
    assert.equal(byId.social.status, "idle");
    assert.equal(byId.bull.status, "complete");
    assert.equal(byId.bear.status, "idle");
    assert.equal(byId.trader.status, "complete");
    assert.equal(byId.portfolio.status, "complete");
    assert.equal(byId.broker.status, "waiting");
    assert.equal(byId.completed.status, "complete");
    assert.equal(byId.market.detail, "Updated report");
  });
});

function makeEvent(sequence: number, type: string, node: string | null): RunEvent {
  return {
    created_at: "2026-05-02T18:00:00Z",
    message: `${type} ${node ?? "run"}`,
    node,
    payload: {},
    run_id: "run_123",
    sequence,
    type
  };
}
