import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { getDashboardNewsEvents } from "./workspace-data.ts";
import { buildPortfolioAdvisorBrief } from "./advisor-brief.ts";

describe("portfolio advisor brief", () => {
  it("summarizes all watchlist symbols instead of only the selected stock", () => {
    const brief = buildPortfolioAdvisorBrief({
      newsBySymbol: {
        AAPL: getDashboardNewsEvents("AAPL"),
        MSFT: getDashboardNewsEvents("MSFT"),
        NVDA: getDashboardNewsEvents("NVDA")
      },
      selectedSymbol: "NVDA",
      watchlistItems: [
        { symbol: "NVDA", name: "NVIDIA", price: 220.79, changePercent: 1.51 },
        { symbol: "AAPL", name: "Apple", price: 294.91, changePercent: 0.95 },
        { symbol: "MSFT", name: "Microsoft", price: 407.48, changePercent: -1.52 }
      ]
    });

    assert.match(brief.summary, /3 watched names/);
    assert.match(brief.cards[0].body, /2 green/);
    assert.match(brief.cards[0].body, /1 red/);
    assert.match(brief.cards[1].title, /MSFT|NVDA|AAPL/);
    assert.ok(brief.statusItems.includes("3 symbols watched"));
  });

  it("keeps provider honesty when quotes or news are missing", () => {
    const brief = buildPortfolioAdvisorBrief({
      newsBySymbol: {},
      selectedSymbol: "NVDA",
      watchlistItems: [
        { symbol: "NVDA", name: "NVIDIA", price: null, changePercent: null }
      ]
    });

    assert.match(brief.summary, /waiting for provider-backed quotes/i);
    assert.match(brief.cards[1].body, /No news events are loaded/);
    assert.ok(brief.statusItems.includes("quotes pending"));
  });
});
