import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

describe("order thesis handoff panel", () => {
  it("renders an independent advisory handoff form without live trade submission", () => {
    const source = readFileSync(new URL("./OrderThesisPanel.tsx", import.meta.url), "utf-8");

    assert.match(source, /Order Thesis Handoff/);
    assert.match(source, /Advisory research-to-brokerage handoff/);
    assert.match(source, /Research only - not a broker order/);
    assert.match(source, /Generated thesis preview/);
    assert.match(source, /Open Brokerage Floor/);
    assert.match(source, /buildOrderThesisDraft/);
    assert.match(source, /createTradeThesis/);
    assert.match(source, /listTradeTheses/);
    assert.match(source, /onOpenBrokerage/);
    assert.match(source, /sourceReportId\?: string \| null/);
    assert.match(source, /sourceReportId: sourceReportId \?\? null/);
    assert.match(source, /sourceRoom: "research"/);
    assert.match(source, /targetRoom: "market"/);
    assert.match(source, /Save thesis handoff|Send to broker review/);
    assert.match(source, /Saved thesis handoff for broker review/);
    assert.match(source, /Recent thesis handoffs/);
    assert.match(source, /Unable to load recent thesis handoffs/);
    assert.match(source, /sent_to_broker/);
    assert.match(source, /accept/);
    assert.match(source, /revise/);
    assert.match(source, /defer/);
    assert.match(source, /escalate/);
    assert.match(source, /reject/);
    assert.doesNotMatch(source, /submitOrder|placeOrder|createOrder|submitTrade|placeTrade/);
  });
});
