import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

describe("watchlist rail controls", () => {
  it("provides an inline add-symbol form", () => {
    const source = readFileSync(new URL("./WatchlistRail.tsx", import.meta.url), "utf-8");

    assert.match(source, /onAddSymbol/);
    assert.match(source, /watchlist-add-form/);
    assert.match(source, /Add symbol/);
  });

  it("normalizes submitted symbols before requesting watchlist insertion", () => {
    const source = readFileSync(new URL("./WatchlistRail.tsx", import.meta.url), "utf-8");

    assert.match(source, /normalizeWatchlistSymbol/);
    assert.match(source, /const symbol = normalizeWatchlistSymbol\(draftSymbol\)/);
    assert.match(source, /onAddSymbol\(symbol\)/);
    assert.doesNotMatch(source, /onAddSymbol\(draftSymbol\)/);
  });

  it("provides a remove control for each expanded watchlist symbol", () => {
    const source = readFileSync(new URL("./WatchlistRail.tsx", import.meta.url), "utf-8");

    assert.match(source, /onRemoveSymbol/);
    assert.match(source, /watchlist-remove-button/);
    assert.match(source, /Remove \$\{item.symbol\}/);
  });

  it("keeps the watchlist rail compact and the remove affordance subdued", () => {
    const css = readFileSync(new URL("../app/globals.css", import.meta.url), "utf-8");

    assert.match(css, /grid-template-columns: 214px minmax\(440px, 1fr\)/);
    assert.match(css, /@media \(max-width: 1120px\)[\s\S]*grid-template-columns: 196px minmax\(320px, 1fr\)/);
    assert.match(css, /\.watchlist-item[\s\S]*grid-template-columns: minmax\(0, 1fr\) 22px/);
    assert.match(css, /\.watchlist-remove-button[\s\S]*width: 18px/);
    assert.match(css, /\.watchlist-remove-button[\s\S]*height: 18px/);
    assert.match(css, /\.watchlist-remove-button[\s\S]*opacity: 0\.48/);
  });
});
