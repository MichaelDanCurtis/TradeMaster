import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  getAgentConversations,
  getDashboardNewsEvents,
  getHistoricalOutcomes,
  getTransactionSnapshot
} from "./workspace-data.ts";

describe("workspace seeded domain data", () => {
  it("returns relevant NVDA dashboard news events in descending order", () => {
    const events = getDashboardNewsEvents("NVDA");

    assert.equal(events.length, 20);
    assert.ok(events.every((event) => event.symbol === "NVDA"));
    assert.ok(events.every((event) => event.timestamp.startsWith("2026")));

    const relevances = events.map((event) => event.relevance);
    assert.deepEqual(
      relevances,
      [...relevances].sort((left, right) => right - left)
    );
  });

  it("returns symbol conversations and platform alerts for the agents workspace", () => {
    const conversations = getAgentConversations("NVDA");
    const ids = conversations.map((conversation) => conversation.id);

    assert.ok(ids.includes("research-lead-nvda"));
    assert.ok(ids.includes("platform-alerts"));
    assert.ok(conversations.some((conversation) => conversation.type === "group"));
    assert.ok(conversations.every((conversation) => conversation.symbol === "NVDA" || conversation.symbol === null));
  });

  it("returns an approval-gated paper transaction snapshot", () => {
    const snapshot = getTransactionSnapshot("NVDA");

    assert.equal(snapshot.mode, "paper");
    assert.equal(snapshot.orderIntent.symbol, "NVDA");
    assert.equal(snapshot.orderIntent.requiresApproval, true);
    assert.ok(snapshot.positions.length >= 3);
  });

  it("returns reviewed historical outcomes for the requested symbol", () => {
    const outcomes = getHistoricalOutcomes("NVDA");

    assert.ok(outcomes.length >= 3);
    assert.ok(outcomes.every((outcome) => outcome.symbol === "NVDA"));
    assert.ok(outcomes.some((outcome) => outcome.reviewTags.includes("directionally-correct")));
  });
});
