import { test } from "node:test";
import assert from "node:assert/strict";
import { filterExplorer, type ExplorerCandidate } from "./research-explorer.ts";

const rows: ExplorerCandidate[] = [
  { symbol: "AAA", price: 12, change_pct: 5, volume: 100, sources: ["gainer", "most_active"] },
  { symbol: "BBB", price: null, change_pct: null, volume: 200, sources: ["most_active"] },
  { symbol: "CCC", price: 2, change_pct: -5, volume: null, sources: ["loser"] },
];
const defaults = { lens: "all" as const, query: "", minPrice: 5, includeUnknown: true, savedOnly: false, watched: new Set(["BBB"]) };
test("unknown prices cannot pass a strict price screen", () => {
  assert.deepEqual(filterExplorer(rows, { ...defaults, includeUnknown: false }).map((row) => row.symbol), ["AAA"]);
  assert.equal(filterExplorer(rows, defaults).length, 2);
});
test("source membership includes candidates appearing on multiple lists", () => {
  assert.deepEqual(filterExplorer(rows, { ...defaults, lens: "most_active" }).map((row) => row.symbol), ["AAA", "BBB"]);
  assert.deepEqual(filterExplorer(rows, { ...defaults, lens: "loser", minPrice: 0 }).map((row) => row.symbol), ["CCC"]);
});
test("watchlist and ticker search compose without inventing candidates", () => {
  assert.deepEqual(filterExplorer(rows, { ...defaults, savedOnly: true, query: " bbb " }).map((row) => row.symbol), ["BBB"]);
  assert.equal(filterExplorer(rows, { ...defaults, query: "NVDA" }).length, 0);
});
