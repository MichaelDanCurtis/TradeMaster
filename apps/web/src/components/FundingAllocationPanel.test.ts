import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

describe("funding allocation panel", () => {
  it("imports durable funding review API methods and renders private-office sections", () => {
    const source = readFileSync(new URL("./FundingAllocationPanel.tsx", import.meta.url), "utf-8");

    assert.match(source, /Funding Allocation Review/);
    assert.match(source, /listFundingAllocationReviews/);
    assert.match(source, /createFundingAllocationReview/);
    assert.match(source, /Private-office funding review/);
    assert.match(source, /before broker execution/);
    assert.match(source, /Funding source/);
    assert.match(source, /Liability checks/);
    assert.match(source, /Tax questions/);
    assert.match(source, /Compliance gate/);
    assert.match(source, /Approval next steps/);
    assert.match(source, /Missing provider facts/);
    assert.match(source, /buildFundingAllocationReview/);
    assert.match(source, /getFundingAllocationTrack/);
    assert.match(source, /Save funding review/);
    assert.match(source, /Recent funding reviews/);
    assert.match(source, /Saved funding review/);
    assert.match(source, /local-only/);
    assert.match(source, /Provider facts unavailable/);
    assert.doesNotMatch(source, /recordApprovalLedgerEntry/);
    assert.doesNotMatch(source, /onOpenResearch/);
    assert.doesNotMatch(source, /submitLiveTrade/);
  });

  it("keeps the component prop surface to symbol and optional notional", () => {
    const source = readFileSync(new URL("./FundingAllocationPanel.tsx", import.meta.url), "utf-8");

    assert.match(source, /symbol: string;/);
    assert.match(source, /notional\?: number;/);
    assert.match(source, /buildFundingAllocationReview\(\{\s*notional,\s*symbol\s*\}\)/);
  });
});
