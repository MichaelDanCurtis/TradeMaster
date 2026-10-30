import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { NormalizedMarketBar } from "./market-data.ts";

import {
  MarketDataProviderUnavailableError,
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

  it("throws a controlled unavailable error when backend provider access is unavailable", async () => {
    const fetcher: BackendFetch = async () =>
      jsonResponse({ detail: "Alpaca market data is disabled or missing a secret_ref" }, 403);

    await assert.rejects(
      () => fetchProviderBackedMarketSnapshot("NVDA", "1M", { fetcher }),
      MarketDataProviderUnavailableError
    );
  });

  it("requests the prior market period without returning generated fallback bars", async () => {
    const requestedUrls: string[] = [];
    const fetcher: BackendFetch = async (input) => {
      requestedUrls.push(String(input));
      if (String(input).includes("/bars")) {
        return jsonResponse({
          bars: [
            {
              close: 201,
              high: 202,
              low: 199,
              open: 200,
              symbol: "NVDA",
              timestamp: "2026-04-01T13:30:00Z",
              trade_count: 10,
              volume: 1000,
              vwap: 200.5
            }
          ]
        });
      }

      return jsonResponse({
        quote: {
          ask_price: 201.1,
          ask_size: 100,
          bid_price: 200.9,
          bid_size: 100,
          symbol: "NVDA",
          timestamp: "2026-04-01T20:00:00Z"
        }
      });
    };

    const snapshot = await fetchProviderBackedMarketSnapshot("NVDA", "1M", { fetcher, period: "previous" });
    const barsUrl = new URL(requestedUrls[0]);
    const start = new Date(barsUrl.searchParams.get("start") ?? "");
    const end = new Date(barsUrl.searchParams.get("end") ?? "");

    assert.equal(snapshot.provider, "alpaca");
    assert.ok(end.getTime() < Date.now());
    assert.ok(start.getTime() < end.getTime());
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

  it("uses the full session direction for ticker sparklines", () => {
    const bars = Array.from({ length: 16 }, (_, index) =>
      makeBar({
        close: 100 + index,
        open: index === 0 ? 96 : 100 + index - 1,
        timestamp: `2026-05-01T13:${String(30 + index).padStart(2, "0")}:00.000Z`
      })
    );
    const items = createTickerItemsFromSnapshots([
      {
        bars,
        feed: "iex",
        generatedAt: "2026-05-01T13:45:00.000Z",
        interval: "1m",
        provider: "alpaca",
        quote: {
          ask: 115.02,
          bid: 114.98,
          dayHigh: 116,
          dayLow: 96,
          dayOpen: 96,
          dayVolume: 10000,
          feed: "iex",
          last: 115,
          provider: "alpaca",
          symbol: "NVDA",
          timestamp: "2026-05-01T13:45:00.000Z"
        },
        symbol: "NVDA"
      }
    ]);

    assert.equal(items[0].sparkline[0], 96);
    assert.equal(items[0].sparkline.at(-1), 115);
    assert.ok(items[0].sparkline.length <= 12);
  });

  it("sorts provider bars chronologically before building snapshots", async () => {
    const fetcher: BackendFetch = async (input) => {
      if (String(input).includes("/bars")) {
        return jsonResponse({
          bars: [
            {
              close: 106,
              high: 107,
              low: 104,
              open: 104,
              symbol: "NVDA",
              timestamp: "2026-04-30T13:40:00Z",
              trade_count: 9420,
              volume: 6700000,
              vwap: 105.5
            },
            {
              close: 100,
              high: 101,
              low: 99,
              open: 99,
              symbol: "NVDA",
              timestamp: "2026-04-30T13:30:00Z",
              trade_count: 9342,
              volume: 6601542,
              vwap: 100
            }
          ]
        });
      }

      return jsonResponse({
        quote: {
          ask_price: 106.2,
          ask_size: 300,
          bid_price: 105.9,
          bid_size: 200,
          symbol: "NVDA",
          timestamp: "2026-04-30T13:40:01Z"
        }
      });
    };

    const snapshot = await fetchProviderBackedMarketSnapshot("nvda", "1D", { fetcher });

    assert.equal(snapshot.bars[0].timestamp, "2026-04-30T13:30:00.000Z");
    assert.equal(snapshot.quote.dayOpen, 99);
    assert.equal(snapshot.quote.last, 106);
  });
});

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    headers: { "content-type": "application/json" },
    status
  });
}

function makeBar(overrides: Partial<NormalizedMarketBar>): NormalizedMarketBar {
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
