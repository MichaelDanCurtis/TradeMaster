import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

describe("market ticker markup", () => {
  it("keeps sparkline accessible names out of SVG title nodes", () => {
    const source = readFileSync(new URL("./MarketTicker.tsx", import.meta.url), "utf-8");

    assert.equal(source.includes("<title>"), false);
  });
});
