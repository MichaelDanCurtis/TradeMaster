import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

describe("execution agents workspace", () => {
  it("creates approval-gated paper execution previews instead of a static placeholder", () => {
    const source = readFileSync(new URL("./TransactionsWorkspace.tsx", import.meta.url), "utf-8");

    assert.match(source, /createRun/);
    assert.match(source, /createAgentTrigger/);
    assert.match(source, /previewTrade/);
    assert.match(source, /previewExecutionAlgorithm/);
    assert.match(source, /TradeTicket/);
    assert.match(source, /brokerMode: "paper"/);
    assert.match(source, /Preview \$\{symbol\} paper order/);
    assert.match(source, /<ExecutionProgramPanel symbol=\{symbol\}/);
    assert.match(source, /Algorithm legs/);
    assert.match(source, /Symbolic policy active/);
    assert.match(source, /Policy check passed/);
    assert.match(source, /Policy blocked/);
    assert.match(source, /Execution trigger armed/);
    assert.match(source, /risk_threshold/);
    assert.match(source, /execution-risk-agent/);
    assert.match(source, /Private Office/);
    assert.doesNotMatch(source, /<RoomRoadmapPanel/);
    assert.match(source, /FundingAllocationPanel/);
    assert.match(source, /notional=\{notional\}/);
    assert.doesNotMatch(source, /createFundingAllocationReview/);
    assert.doesNotMatch(source, /submitLiveTrade/);
    assert.doesNotMatch(source, /brokerMode: "live"/);
  });
});
