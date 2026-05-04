import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

describe("market ticker markup", () => {
  it("keeps sparkline accessible names out of SVG title nodes", () => {
    const source = readFileSync(new URL("./MarketTicker.tsx", import.meta.url), "utf-8");

    assert.equal(source.includes("<title>"), false);
  });

  it("renders a hidden duplicate segment for seamless ticker motion", () => {
    const source = readFileSync(new URL("./MarketTicker.tsx", import.meta.url), "utf-8");

    assert.match(source, /market-ticker-segment/);
    assert.match(source, /aria-hidden="true"/);
  });

  it("styles the ticker as a black animated tape with white primary text", () => {
    const source = readFileSync(new URL("../app/globals.css", import.meta.url), "utf-8");

    assert.match(source, /\.market-ticker-strip\s*{[^}]*background:\s*#000\b/s);
    assert.match(source, /@keyframes\s+ticker-marquee/);
    assert.match(source, /\.ticker-copy\s+(strong|span)[\s\S]*color:\s*#fff\b/);
    assert.match(source, /prefers-reduced-motion:\s*reduce/);
  });
});
