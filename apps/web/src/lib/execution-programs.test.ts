import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  buildExecutionProgramPreview,
  executionProgramTemplates,
  type ExecutionTriggerType
} from "./execution-programs.ts";

describe("execution program previews", () => {
  it("exposes deterministic brokerage-floor execution program templates", () => {
    assert.deepEqual(
      executionProgramTemplates.map((template) => template.id),
      [
        "staged_accumulation",
        "bracket_order",
        "trailing_stop",
        "dca_ladder",
        "rebalance",
        "hedge",
        "tax_loss_harvest"
      ]
    );
    assert.ok(executionProgramTemplates.every((template) => template.approvalRequired));
    assert.ok(executionProgramTemplates.every((template) => template.paperOnly));
  });

  it("builds a paper and approval-gated preview with every required trigger type represented", () => {
    const preview = buildExecutionProgramPreview({
      algorithmId: "staged_accumulation",
      symbol: " msft "
    });

    const triggerTypes = new Set<ExecutionTriggerType>(preview.triggerPoints.map((trigger) => trigger.type));

    assert.equal(preview.symbol, "MSFT");
    assert.equal(preview.algorithm.id, "staged_accumulation");
    assert.equal(preview.state.mode, "paper");
    assert.equal(preview.state.approvalGate, "required");
    assert.equal(preview.state.liveSubmissionEnabled, false);
    assert.deepEqual(
      Array.from(triggerTypes),
      ["time", "price", "volume", "sentiment_flip", "report_event", "risk_threshold", "compliance_flag"]
    );
    assert.ok(preview.circuitBreakers.some((breaker) => breaker.includes("Kill-switch")));
    assert.ok(preview.expectedEvents.some((event) => event.phase === "approval_required"));
    assert.ok(preview.missingProviderFacts.includes("Broker paper-trading account ID and execution venue capabilities."));
  });

  it("falls back to a staged accumulation preview when an unknown algorithm is requested", () => {
    const preview = buildExecutionProgramPreview({
      algorithmId: "does_not_exist",
      symbol: ""
    });

    assert.equal(preview.symbol, "WATCHLIST");
    assert.equal(preview.algorithm.id, "staged_accumulation");
    assert.equal(preview.expectedEvents[0]?.summary, "Preview created locally without broker submission.");
  });
});
