import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  createHeikinAshiBars,
  createSimulatedMarketSnapshot,
  createVolumeProfileBins,
  getMarketProviderCatalog,
  type NormalizedMarketBar,
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

  it("derives Heikin Ashi bars from normalized OHLCV bars", () => {
    const sourceBars: NormalizedMarketBar[] = [
      makeBar({ close: 13, high: 14, low: 9, open: 10, timestamp: "2026-05-01T14:30:00.000Z" }),
      makeBar({ close: 15, high: 16, low: 11, open: 13, timestamp: "2026-05-01T14:31:00.000Z" }),
      makeBar({ close: 12, high: 15, low: 10, open: 15, timestamp: "2026-05-01T14:32:00.000Z" })
    ];

    const heikinAshiBars = createHeikinAshiBars(sourceBars);

    assert.deepEqual(
      heikinAshiBars.map((bar) => ({
        close: bar.close,
        high: bar.high,
        low: bar.low,
        open: bar.open,
        timestamp: bar.timestamp
      })),
      [
        { close: 11.5, high: 14, low: 9, open: 11.5, timestamp: "2026-05-01T14:30:00.000Z" },
        { close: 13.75, high: 16, low: 11, open: 11.5, timestamp: "2026-05-01T14:31:00.000Z" },
        { close: 13, high: 15, low: 10, open: 12.63, timestamp: "2026-05-01T14:32:00.000Z" }
      ]
    );
    assert.equal(heikinAshiBars[0].provider, "simulated");
    assert.equal(heikinAshiBars[0].volume, 1000);
  });

  it("builds volume profile bins across the traded price range", () => {
    const sourceBars: NormalizedMarketBar[] = [
      makeBar({ close: 12, high: 14, low: 10, open: 11, volume: 900 }),
      makeBar({ close: 15, high: 16, low: 12, open: 13, volume: 600 }),
      makeBar({ close: 18, high: 20, low: 15, open: 16, volume: 500 })
    ];

    const bins = createVolumeProfileBins(sourceBars, 5);

    assert.equal(bins.length, 5);
    assert.equal(bins.reduce((sum, bin) => sum + bin.volume, 0), 2000);
    assert.deepEqual(
      bins.map((bin) => ({ end: bin.priceEnd, start: bin.priceStart })),
      [
        { end: 12, start: 10 },
        { end: 14, start: 12 },
        { end: 16, start: 14 },
        { end: 18, start: 16 },
        { end: 20, start: 18 }
      ]
    );
    assert.equal(Math.max(...bins.map((bin) => bin.volumeShare)), 1);
  });
});

function makeBar(overrides: Partial<NormalizedMarketBar>): NormalizedMarketBar {
  return {
    close: 10,
    feed: "simulated",
    high: 10,
    interval: "1m",
    low: 10,
    open: 10,
    provider: "simulated",
    symbol: "NVDA",
    timestamp: "2026-05-01T14:30:00.000Z",
    volume: 1000,
    ...overrides
  };
}
