import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  createTickerItemsFromSnapshots,
  fetchProviderBackedMarketSnapshot,
  type BackendFetch
} from "./market-data-provider.ts";

describe("provider backed market data", () => {
  it("normalizes backend Alpaca bars and quotes into the web snapshot contract", async () => {
    const calls: string[] = [];
    const fetcher: BackendFetch = async (input) => {
      calls.push(String(input));
      if (String(input).includes("/bars")) {
        return jsonResponse({
          bars: [
            {
              close: 839.05,
              high: 841,
              low: 836.5,
              open: 838.12,
              symbol: "NVDA",
              timestamp: "2026-04-30T13:30:00Z",
              trade_count: 9342,
              volume: 6601542,
              vwap: 838.71
            },
            {
              close: 842.25,
              high: 843,
              low: 838.5,
              open: 839.05,
              symbol: "NVDA",
              timestamp: "2026-04-30T13:31:00Z",
              trade_count: 9420,
              volume: 6700000,
              vwap: 841.05
            }
          ]
        });
      }

      return jsonResponse({
        quote: {
          ask_price: 842.4,
          ask_size: 300,
          bid_price: 842.1,
          bid_size: 200,
          symbol: "NVDA",
          timestamp: "2026-04-30T13:31:01Z"
        }
      });
    };

    const snapshot = await fetchProviderBackedMarketSnapshot("nvda", "1D", { fetcher });

    assert.equal(snapshot.provider, "alpaca");
    assert.equal(snapshot.feed, "iex");
    assert.equal(snapshot.interval, "1m");
    assert.equal(snapshot.generatedAt, "2026-04-30T13:31:01.000Z");
    assert.equal(snapshot.quote.last, 842.25);
    assert.equal(snapshot.quote.bid, 842.1);
    assert.equal(snapshot.quote.ask, 842.4);
    assert.equal(snapshot.quote.dayOpen, 838.12);
    assert.equal(snapshot.quote.dayVolume, 13301542);
    assert.equal(snapshot.bars[0].tradeCount, 9342);
    assert.ok(calls[0].includes("timeframe=1Min"));
    assert.ok(calls[0].includes("feed=iex"));
    assert.ok(calls[1].includes("/quote"));
  });

  it("falls back to deterministic simulated snapshots when backend provider access is unavailable", async () => {
    const fetcher: BackendFetch = async () =>
      jsonResponse({ detail: "Alpaca market data is disabled or missing a secret_ref" }, 403);

    const snapshot = await fetchProviderBackedMarketSnapshot("NVDA", "1M", { fetcher });

    assert.equal(snapshot.provider, "simulated");
    assert.equal(snapshot.feed, "simulated");
    assert.equal(snapshot.symbol, "NVDA");
    assert.equal(snapshot.bars.length, 22);
  });

  it("builds ticker rows from normalized snapshots", () => {
    const items = createTickerItemsFromSnapshots(
      [
        {
          bars: [
            makeBar({ close: 100, open: 100, timestamp: "2026-05-01T13:30:00.000Z" }),
            makeBar({ close: 104, open: 100, timestamp: "2026-05-01T13:35:00.000Z" }),
            makeBar({ close: 106, open: 104, timestamp: "2026-05-01T13:40:00.000Z" })
          ],
          feed: "iex",
          generatedAt: "2026-05-01T13:40:00.000Z",
          interval: "5m",
          provider: "alpaca",
          quote: {
            ask: 106.02,
            bid: 105.98,
            dayHigh: 107,
            dayLow: 99,
            dayOpen: 100,
            dayVolume: 10000,
            feed: "iex",
            last: 106,
            provider: "alpaca",
            symbol: "NVDA",
            timestamp: "2026-05-01T13:40:00.000Z"
          },
          symbol: "NVDA"
        }
      ],
      { NVDA: "NVIDIA" }
    );

    assert.deepEqual(items, [
      {
        change: 6,
        changePercent: 6,
        id: "nvda",
        label: "NVIDIA",
        sparkline: [100, 104, 106],
        value: 106
      }
    ]);
  });
});

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    headers: { "content-type": "application/json" },
    status
  });
}

function makeBar(overrides: Record<string, unknown>) {
  return {
    close: 100,
    feed: "iex",
    high: 100,
    interval: "5m",
    low: 100,
    open: 100,
    provider: "alpaca",
    symbol: "NVDA",
    timestamp: "2026-05-01T13:30:00.000Z",
    volume: 1000,
    ...overrides
  };
}
