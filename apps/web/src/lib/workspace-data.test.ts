import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  getAgentConversations,
  getAgentMessages,
  getConversationActions,
  getDashboardNewsEvents,
  getHistoricalOutcomes,
  getResearchReports,
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

  it("provides event marker labels for chart rendering", () => {
    const events = getDashboardNewsEvents("NVDA");

    assert.ok(events.every((event) => event.markerLabel.length >= 1));
    assert.ok(events.every((event) => event.relevance >= 0 && event.relevance <= 100));
  });

  it("returns symbol conversations and platform alerts for the agents workspace", () => {
    const conversations = getAgentConversations("NVDA");
    const ids = conversations.map((conversation) => conversation.id);

    assert.ok(ids.includes("research-lead-nvda"));
    assert.ok(ids.includes("platform-alerts"));
    assert.ok(conversations.some((conversation) => conversation.type === "group"));
    assert.ok(conversations.every((conversation) => conversation.symbol === "NVDA" || conversation.symbol === null));
  });

  it("returns durable agent messages and approval-gated actions for a conversation", () => {
    const messages = getAgentMessages("research-lead-nvda");
    const actions = getConversationActions("research-lead-nvda");

    assert.ok(messages.some((message) => message.a2uiSurface === "event-chart"));
    assert.ok(actions.some((action) => action.type === "preview-order" && action.requiresApproval === true));
  });

  it("returns independent agent message authors", () => {
    const messages = getAgentMessages("research-lead-nvda");
    messages[0].author.name = "Mutated Author";
    messages[0].author.type = "human";

    const freshMessages = getAgentMessages("research-lead-nvda");

    assert.notEqual(freshMessages[0].author.name, "Mutated Author");
    assert.notEqual(freshMessages[0].author.type, "human");
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

  it("returns deep research reports for the requested symbol", () => {
    const reports = getResearchReports("NVDA");

    assert.ok(reports.length >= 3);
    assert.ok(reports.every((report) => report.symbol === "NVDA"));
    assert.ok(reports.every((report) => report.ledgerState.length > 0));
  });

  it("returns independent deep research report arrays", () => {
    const reports = getResearchReports("NVDA");
    reports[0].ledgerState.push("mutated ledger entry");
    reports[0].riskNotes.push("mutated risk note");
    reports[0].synthesisSteps.push("mutated synthesis step");

    const freshReports = getResearchReports("NVDA");

    assert.ok(!freshReports[0].ledgerState.includes("mutated ledger entry"));
    assert.ok(!freshReports[0].riskNotes.includes("mutated risk note"));
    assert.ok(!freshReports[0].synthesisSteps.includes("mutated synthesis step"));
  });
});
