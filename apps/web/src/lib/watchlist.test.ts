import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  addWatchlistItem,
  buildWatchlistTickerUrl,
  hydrateWatchlistItems,
  loadPersistedWatchlistItems,
  normalizeWatchlistSymbol,
  persistWatchlistItems,
  removeWatchlistItem
} from "./watchlist.ts";

const seededItems = [
  { symbol: "NVDA", name: "NVIDIA", price: 198.17, changePercent: -0.14 },
  { symbol: "AAPL", name: "Apple", price: 277.25, changePercent: -0.61 }
];

describe("watchlist helpers", () => {
  it("normalizes typed symbols into market symbols", () => {
    assert.equal(normalizeWatchlistSymbol(" spy "), "SPY");
    assert.equal(normalizeWatchlistSymbol("brk.b"), "BRK.B");
    assert.equal(normalizeWatchlistSymbol(""), null);
  });

  it("adds a new local watchlist item without duplicating existing symbols", () => {
    const withSpy = addWatchlistItem(seededItems, "spy");

    assert.equal(withSpy.length, 3);
    assert.deepEqual(withSpy.at(-1), { symbol: "SPY", name: "SPY", price: null, changePercent: null });
    assert.equal(addWatchlistItem(withSpy, "SPY"), withSpy);
  });

  it("persists added watchlist symbols across browser reloads", () => {
    const storage = new MemoryStorage();
    const withTesla = addWatchlistItem(seededItems, "tsla");

    persistWatchlistItems(storage, withTesla);

    assert.deepEqual(loadPersistedWatchlistItems(storage, seededItems), withTesla);
  });

  it("removes a watchlist symbol without mutating other persisted symbols", () => {
    const withTesla = addWatchlistItem(seededItems, "tsla");
    const withoutApple = removeWatchlistItem(withTesla, "aapl");

    assert.deepEqual(withoutApple, [
      seededItems[0],
      { symbol: "TSLA", name: "TSLA", price: null, changePercent: null }
    ]);
    assert.equal(removeWatchlistItem(withoutApple, "missing"), withoutApple);
  });

  it("builds a ticker quote request from the current watchlist symbols", () => {
    const withTesla = addWatchlistItem(seededItems, "tsla");

    assert.equal(buildWatchlistTickerUrl(withTesla), "/api/market-data/ticker?symbols=NVDA%2CAAPL%2CTSLA");
  });

  it("omits invalid and duplicate symbols from ticker quote requests", () => {
    assert.equal(
      buildWatchlistTickerUrl([
        seededItems[0],
        { symbol: "nvda", name: "Duplicate", price: null, changePercent: null },
        { symbol: "bad symbol", name: "Invalid", price: null, changePercent: null },
        { symbol: "tsla", name: "Tesla", price: null, changePercent: null }
      ]),
      "/api/market-data/ticker?symbols=NVDA%2CTSLA"
    );
  });

  it("hydrates newly added symbols from returned ticker quotes", () => {
    const withTesla = addWatchlistItem(seededItems, "tsla");

    assert.deepEqual(
      hydrateWatchlistItems(withTesla, [
        {
          change: 12.15,
          changePercent: 4.25,
          id: "tsla",
          label: "Tesla",
          sparkline: [284, 289, 296],
          value: 296.4
        }
      ]),
      [
        seededItems[0],
        seededItems[1],
        { symbol: "TSLA", name: "Tesla", price: 296.4, changePercent: 4.25 }
      ]
    );
  });

  it("falls back to the seeded watchlist when persisted data is corrupt", () => {
    const storage = new MemoryStorage();
    storage.setItem("trademaster.watchlist.v1", "{broken");

    assert.deepEqual(loadPersistedWatchlistItems(storage, seededItems), seededItems);
  });
});

class MemoryStorage implements Pick<Storage, "getItem" | "setItem"> {
  private readonly items = new Map<string, string>();

  getItem(key: string): string | null {
    return this.items.get(key) ?? null;
  }

  setItem(key: string, value: string): void {
    this.items.set(key, value);
  }
}
