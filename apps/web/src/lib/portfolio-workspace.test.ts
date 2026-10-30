import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { buildCurrentPortfolioWorkspace } from "./portfolio-workspace.ts";

describe("current portfolio workspace model", () => {
  it("builds provider-backed portfolio review concepts without fake balances", () => {
    const workspace = buildCurrentPortfolioWorkspace({ symbol: "nvda" });

    assert.equal(workspace.symbol, "NVDA");
    assert.equal(workspace.title, "Current Portfolio");
    assert.ok(workspace.accountCoverage.some((item) => item.provider === "Webull"));
    assert.ok(workspace.accountCoverage.some((item) => item.provider === "Alpaca"));
    assert.ok(workspace.holdingsCoverage.some((item) => item.scope === "Positions"));
    assert.ok(workspace.missingProviderFacts.includes("Provider-backed cash, buying power, and account permissions."));
    assert.ok(workspace.missingProviderFacts.includes("Provider-backed positions, quantities, market values, and cost basis."));
    assert.ok(workspace.mandates.some((mandate) => mandate.provider === "Webull" && mandate.owner === "Human managed"));
    assert.ok(workspace.mandates.some((mandate) => mandate.provider === "Alpaca" && mandate.owner === "High-risk AI paper harness"));
    assert.ok(workspace.allocationDiscussionItems.some((item) => item.topic === "Account split"));
    assert.ok(workspace.recommendedNextActions.some((action) => action.destination === "Research Office"));
    assert.ok(workspace.recommendedNextActions.some((action) => action.destination === "Brokerage Floor"));
  });

  it("keeps the model independent from hard-coded dollar balances", () => {
    const workspace = buildCurrentPortfolioWorkspace({ symbol: "" });
    const serialized = JSON.stringify(workspace);

    assert.equal(workspace.symbol, "PORTFOLIO");
    assert.doesNotMatch(serialized, /\$[0-9]/);
    assert.doesNotMatch(serialized, /\bbalance\b/i);
    assert.match(serialized, /provider-backed/i);
    assert.match(serialized, /missing/i);
  });
});
