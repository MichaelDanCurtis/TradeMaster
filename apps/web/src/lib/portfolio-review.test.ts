import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { buildPortfolioReviewThesis } from "./portfolio-review.ts";

describe("portfolio review model", () => {
  it("builds an advisory thesis from goals, sector focus, horizon, and constraints", () => {
    const thesis = buildPortfolioReviewThesis({
      constraints: "Keep emergency cash intact and avoid concentrated tax events.",
      goals: "Build enough liquid capital for a major boat purchase in 6-12 months.",
      horizon: "6-12 months",
      liquidityNeeds: "Need visible cash runway before adding risk.",
      riskPosture: "balanced",
      sectors: "AI semiconductors, healthcare, index core",
      symbol: "NVDA"
    });

    assert.equal(thesis.title, "Balanced portfolio review for 6-12 months");
    assert.match(thesis.summary, /boat purchase/);
    assert.match(thesis.summary, /AI semiconductors, healthcare, index core/);
    assert.ok(thesis.researchCandidates.some((candidate) => candidate.symbol === "NVDA"));
    assert.ok(thesis.researchCandidates.some((candidate) => candidate.symbol === "SMH"));
    assert.ok(thesis.researchCandidates.every((candidate) => candidate.reason.includes("Research candidate")));
    assert.ok(thesis.missingProviderFacts.includes("Current holdings, cost basis, and account allocation from a portfolio provider."));
    assert.ok(thesis.missingProviderFacts.includes("Cash, liabilities, recurring obligations, and funding runway from Plaid or equivalent banking data."));
    assert.ok(thesis.tracks.some((track) => track.team === "Goals team"));
    assert.ok(thesis.tracks.some((track) => track.team === "Risk and tax desk"));
  });

  it("does not pretend provider-backed portfolio facts are available", () => {
    const thesis = buildPortfolioReviewThesis({
      constraints: "",
      goals: "",
      horizon: "3-6 months",
      liquidityNeeds: "",
      riskPosture: "growth",
      sectors: "",
      symbol: "AAPL"
    });

    assert.match(thesis.summary, /provider-backed holdings and cash data are still required/i);
    assert.equal(thesis.researchCandidates[0]?.symbol, "AAPL");
    assert.ok(thesis.nextSteps.includes("Connect portfolio and banking providers before treating this as an allocation recommendation."));
  });
});
