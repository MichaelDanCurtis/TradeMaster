import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

describe("portfolio review panel", () => {
  it("turns the briefing room into an advisory portfolio review surface", () => {
    const source = readFileSync(new URL("./PortfolioReviewPanel.tsx", import.meta.url), "utf-8");

    assert.match(source, /Portfolio review/);
    assert.match(source, /Goals and time horizon/);
    assert.match(source, /Sector focus/);
    assert.match(source, /Constraints and liquidity/);
    assert.match(source, /Generate portfolio thesis/);
    assert.match(source, /Provider facts still needed/);
    assert.match(source, /Counselor output/);
    assert.match(source, /View review details/);
    assert.match(source, /Portfolio review details/);
    assert.match(source, /Research queue/);
    assert.match(source, /Open Research Office/);
    assert.match(source, /buildPortfolioReviewThesis/);
    assert.match(source, /createPortfolioReview/);
    assert.match(source, /recordApprovalLedgerEntry/);
    assert.match(source, /entityType: "portfolio_review"/);
    assert.match(source, /source: "portfolio-review"/);
    assert.match(source, /Review decision saved/);
  });

  it("persists generated and recorded portfolio reviews with honest provider-state copy", () => {
    const source = readFileSync(new URL("./PortfolioReviewPanel.tsx", import.meta.url), "utf-8");

    assert.match(source, /import \{ createPortfolioReview, recordApprovalLedgerEntry \} from "@\/lib\/api"/);
    assert.match(source, /persistPortfolioReview\(thesis, "generated"\)/);
    assert.match(source, /persistPortfolioReview\(thesis, action\)/);
    assert.match(source, /Portfolio review record saved/);
    assert.match(source, /Portfolio review API unavailable/);
    assert.match(source, /Provider facts remain unavailable/);
    assert.match(source, /provider-backed holdings, cash, and account facts/);
    assert.doesNotMatch(source, /\$[0-9]/);
    assert.doesNotMatch(source, /fake balance/i);
  });
});
