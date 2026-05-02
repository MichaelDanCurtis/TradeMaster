import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  createSimulatedMarketSnapshot,
  getMarketProviderCatalog,
  normalizeAlpacaBar
} from "./market-data.ts";

describe("market data normalization", () => {
  it("normalizes Alpaca bars into the chart and research contract", () => {
    const bar = normalizeAlpacaBar(
      {
        S: "NVDA",
        c: 922.12,
        h: 923.1,
        l: 920.4,
        n: 418,
        o: 921.02,
        t: "2026-05-01T14:31:00Z",
        v: 82422,
        vw: 921.84
      },
      "1m",
      "sip"
    );

    assert.deepEqual(bar, {
      close: 922.12,
      feed: "sip",
      high: 923.1,
      interval: "1m",
      low: 920.4,
      open: 921.02,
      provider: "alpaca",
      symbol: "NVDA",
      timestamp: "2026-05-01T14:31:00.000Z",
      tradeCount: 418,
      volume: 82422,
      vwap: 921.84
    });
  });

  it("creates dense deterministic simulated snapshots for trader charts", () => {
    const first = createSimulatedMarketSnapshot("NVDA", "1m");
    const second = createSimulatedMarketSnapshot("NVDA", "1m");

    assert.equal(first.bars.length, 180);
    assert.deepEqual(first.bars, second.bars);
    assert.equal(first.quote.symbol, "NVDA");
    assert.equal(first.quote.provider, "simulated");
    assert.equal(first.bars[0].interval, "1m");
    assert.equal(first.bars.at(-1)?.timestamp, first.quote.timestamp);
  });

  it("keeps provider roles separate from the normalized rendering contract", () => {
    const catalog = getMarketProviderCatalog();

    assert.ok(catalog.alpaca.roles.includes("market-data"));
    assert.ok(catalog.alpaca.roles.includes("brokerage"));
    assert.deepEqual(catalog.massive.roles, ["market-data"]);
    assert.deepEqual(catalog.plaid.roles, ["portfolio"]);
    assert.ok(catalog.databento.capabilities.includes("tick-history"));
  });
});
