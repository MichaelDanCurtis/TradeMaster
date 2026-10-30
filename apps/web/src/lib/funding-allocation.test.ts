import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  buildFundingAllocationReview,
  getFundingAllocationTrack,
  type FundingAllocationTrackType
} from "./funding-allocation.ts";

describe("funding allocation review model", () => {
  it("builds independent review tracks for private-office approval", () => {
    const review = buildFundingAllocationReview({
      notional: 250000,
      symbol: " nvda "
    });
    const expectedTrackTypes: FundingAllocationTrackType[] = [
      "cash-source",
      "liabilities",
      "tax-questions",
      "mandate-fit",
      "compliance-gate",
      "provider-gaps"
    ];

    assert.equal(review.title, "Funding Allocation Review for NVDA");
    assert.equal(review.symbol, "NVDA");
    assert.equal(review.notionalLabel, "$250,000");
    assert.match(review.summary, /Private-office review/);
    assert.match(review.summary, /before broker execution/);
    assert.deepEqual(
      review.tracks.map((track) => track.type),
      expectedTrackTypes
    );
    assert.equal(getFundingAllocationTrack(review, "cash-source").title, "Funding source");
    assert.equal(getFundingAllocationTrack(review, "liabilities").title, "Liability checks");
    assert.equal(getFundingAllocationTrack(review, "tax-questions").title, "Tax questions");
    assert.equal(getFundingAllocationTrack(review, "compliance-gate").title, "Compliance gate");
    assert.ok(review.approvalNextSteps.some((step) => step.includes("before any broker execution")));
  });

  it("never pretends Plaid, banking, brokerage, or tax data exists", () => {
    const review = buildFundingAllocationReview({
      symbol: "AAPL"
    });
    const providerGapTrack = getFundingAllocationTrack(review, "provider-gaps");

    assert.equal(review.notionalLabel, "Notional pending");
    assert.match(review.summary, /does not include live Plaid, banking, brokerage, or tax facts/i);
    assert.ok(
      review.missingProviderFacts.includes(
        "Verified cash balances, account ownership, and cash source from Plaid or another connected banking provider."
      )
    );
    assert.ok(review.missingProviderFacts.some((fact) => fact.includes("Tax lots")));
    assert.ok(review.missingProviderFacts.some((fact) => fact.includes("Brokerage buying power")));
    assert.equal(providerGapTrack.finding, "Plaid, banking, brokerage, tax, and compliance provider facts are absent.");
    assert.deepEqual(providerGapTrack.requiredFacts, review.missingProviderFacts);
  });
});
