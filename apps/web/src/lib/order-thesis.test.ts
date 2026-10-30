import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  buildOrderThesisDraft,
  orderThesisDecisionActions,
  orderThesisStatusFlow
} from "./order-thesis.ts";

describe("order thesis handoff model", () => {
  it("builds a broker-reviewable advisory order thesis without creating a broker order", () => {
    const thesis = buildOrderThesisDraft({
      action: "accumulate",
      catalysts: ["Datacenter margin expansion", "Blackwell supply ramp"],
      conviction: "high",
      horizon: "3-6 months",
      invalidation: "Revenue growth slows below hyperscaler demand expectations.",
      riskNotes: "Position sizing should account for valuation compression and export restrictions.",
      sourceReportId: "run-nvda-001",
      symbol: "nvda",
      thesisText: "Research agents see durable AI accelerator demand and improving software attach."
    });

    assert.equal(thesis.symbol, "NVDA");
    assert.equal(thesis.label, "Advisory research-to-brokerage handoff");
    assert.equal(thesis.isBrokerOrder, false);
    assert.equal(thesis.status, "proposed");
    assert.deepEqual(thesis.statusFlow, ["proposed", "sent_to_broker"]);
    assert.deepEqual(thesis.decisionActions, ["accept", "revise", "defer", "escalate", "reject"]);
    assert.equal(thesis.sourceReportId, "run-nvda-001");
    assert.match(thesis.summary, /not a broker order/i);
    assert.match(thesis.summary, /research-to-brokerage handoff/i);
    assert.match(thesis.preview, /NVDA/);
    assert.match(thesis.preview, /accumulate/);
    assert.match(thesis.preview, /Datacenter margin expansion/);
    assert.match(thesis.preview, /Revenue growth slows/);
    assert.match(thesis.preview, /Brokerage\/execution agents must convert/);
  });

  it("normalizes empty draft fields into reviewable placeholders", () => {
    const thesis = buildOrderThesisDraft({
      action: "",
      catalysts: [],
      conviction: "",
      horizon: "",
      invalidation: "",
      riskNotes: "",
      symbol: " aapl ",
      thesisText: ""
    });

    assert.equal(thesis.symbol, "AAPL");
    assert.equal(thesis.action, "Needs research action");
    assert.equal(thesis.horizon, "Needs investment horizon");
    assert.equal(thesis.conviction, "Needs conviction level");
    assert.deepEqual(thesis.catalysts, ["Catalysts need broker-review detail."]);
    assert.match(thesis.preview, /Invalidation: Needs invalidation condition/);
    assert.match(thesis.preview, /Risk notes: Needs risk review notes/);
  });

  it("exports fixed status flow and decision metadata for brokerage review", () => {
    assert.deepEqual(orderThesisStatusFlow, ["proposed", "sent_to_broker"]);
    assert.deepEqual(orderThesisDecisionActions, ["accept", "revise", "defer", "escalate", "reject"]);
  });
});
