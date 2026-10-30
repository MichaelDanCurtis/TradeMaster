import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

describe("market shell workspace layout", () => {
  it("keeps deep research on the same watchlist rail and renders settings as a workspace", () => {
    const source = readFileSync(new URL("./MarketShell.tsx", import.meta.url), "utf-8");

    assert.match(source, /loadPersistedWatchlistItems/);
    assert.match(source, /persistWatchlistItems/);
    assert.match(source, /SettingsWorkspace/);
    assert.match(source, /<ResearchWorkspace/);
    assert.match(source, /<QuantWorkspace/);
    assert.match(source, /PortfolioWorkspace/);
    assert.doesNotMatch(source, /watchlist-collapsed/);
    assert.doesNotMatch(source, /<SettingsDrawer/);
  });

  it("wires watchlist removal through persisted shell state", () => {
    const source = readFileSync(new URL("./MarketShell.tsx", import.meta.url), "utf-8");

    assert.match(source, /removeWatchlistItem/);
    assert.match(source, /handleRemoveWatchlistSymbol/);
    assert.match(source, /onRemoveSymbol=\{handleRemoveWatchlistSymbol\}/);
    assert.match(source, /selectSymbol\(currentState, nextItems\[0\]\.symbol\)/);
  });

  it("loads persisted watchlist data after hydration to avoid server-client text mismatches", () => {
    const source = readFileSync(new URL("./MarketShell.tsx", import.meta.url), "utf-8");

    assert.match(source, /useState<WatchlistItem\[\]>\(WATCHLIST\)/);
    assert.match(source, /hasLoadedPersistedWatchlist/);
    assert.match(source, /setWatchlistItems\(loadPersistedWatchlistItems/);
    assert.match(source, /if \(!hasLoadedPersistedWatchlist\)/);
    assert.doesNotMatch(source, /useState<WatchlistItem\[\]>\(\(\) =>\s*loadPersistedWatchlistItems/);
  });

  it("routes the current four rooms and retains the shared watchlist outside settings", () => {
    const source = readFileSync(new URL("./MarketShell.tsx", import.meta.url), "utf-8");

    assert.match(source, /activeTab === "portfolio"/);
    assert.match(source, /watchlistItems=\{watchlistItems\}/);
    assert.match(source, /activeTab === "research"/);
    assert.match(source, /activeTab === "quant"/);
    assert.match(source, /activeTab === "settings"/);
    assert.match(source, /isSettings \? null : \(\s*<WatchlistRail/);
  });

  it("passes symbol research and pending approved-idea handoffs into Quant", () => {
    const source = readFileSync(new URL("./MarketShell.tsx", import.meta.url), "utf-8");

    assert.match(source, /ResearchWorkspace symbol=\{selectedSymbol\} onOpenQuant=\{onOpenQuant\}/);
    assert.match(source, /pendingIntent=\{pendingQuantIntent\}/);
    assert.match(source, /onConsumePendingIntent=\{onConsumePendingQuantIntent\}/);
    assert.match(source, /onOpenResearch=\{onOpenResearch\}/);
    assert.doesNotMatch(source, /submitTrade|submitApprovedOrder/);
  });
});
