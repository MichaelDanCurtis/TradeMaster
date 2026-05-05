import assert from "node:assert/strict";
import { describe, it } from "node:test";

import type { NormalizedMarketBar } from "./market-data.ts";
import {
  getInitialVisibleLogicalRange,
  toBarSeriesData,
  toCandlestickSeriesData,
  toComparisonLineData,
  toNewsSeriesMarkers,
  toPerformanceLineData,
  toVolumeHistogramData
} from "./chart-series.ts";
import type { NewsEvent } from "./workspace-data.ts";

describe("chart series adapters", () => {
  it("sorts normalized bars into lightweight candlestick data", () => {
    const data = toCandlestickSeriesData([
      makeBar({ close: 12, high: 13, low: 9, open: 10, timestamp: "2026-05-01T14:31:00.000Z" }),
      makeBar({ close: 11, high: 12, low: 8, open: 9, timestamp: "2026-05-01T14:30:00.000Z" })
    ]);

    assert.deepEqual(
      data.map((point) => ({ close: point.close, open: point.open, time: point.time })),
      [
        { close: 11, open: 9, time: 1777645800 },
        { close: 12, open: 10, time: 1777645860 }
      ]
    );
  });

  it("uses OHLC bar data for the industry bar view", () => {
    const data = toBarSeriesData([
      makeBar({ close: 8, high: 13, low: 7, open: 12, timestamp: "2026-05-01T14:30:00.000Z" })
    ]);

    assert.deepEqual(data[0], {
      close: 8,
      high: 13,
      low: 7,
      open: 12,
      time: 1777645800
    });
  });

  it("colors volume by candle direction", () => {
    const data = toVolumeHistogramData([
      makeBar({ close: 11, open: 10, volume: 1200, timestamp: "2026-05-01T14:30:00.000Z" }),
      makeBar({ close: 9, open: 10, volume: 900, timestamp: "2026-05-01T14:31:00.000Z" })
    ]);

    assert.deepEqual(
      data.map((point) => ({ color: point.color, value: point.value })),
      [
        { color: "rgba(51, 209, 122, 0.32)", value: 1200 },
        { color: "rgba(255, 107, 107, 0.3)", value: 900 }
      ]
    );
  });

  it("maps percent overlays into aligned line data", () => {
    assert.deepEqual(toPerformanceLineData([{ timestamp: "2026-05-01T14:30:00.000Z", value: 3.4 }]), [
      { time: 1777645800, value: 3.4 }
    ]);
    assert.deepEqual(
      toComparisonLineData([{ benchmark: -1.5, subject: 4.25, timestamp: "2026-05-01T14:30:00.000Z" }], "benchmark"),
      [{ time: 1777645800, value: -1.5 }]
    );
  });

  it("pins news markers to the nearest available trading bar", () => {
    const bars = [
      makeBar({ high: 101, timestamp: "2026-05-01T14:30:00.000Z" }),
      makeBar({ high: 106, timestamp: "2026-05-01T14:35:00.000Z" })
    ];
    const markers = toNewsSeriesMarkers(
      [
        makeNews({ sentiment: "positive", timestamp: "2026-05-01T14:34:00.000Z" }),
        makeNews({ id: "negative", markerLabel: "N2", sentiment: "negative", timestamp: "2026-05-01T14:29:00.000Z" })
      ],
      bars
    );

    assert.deepEqual(
      markers.map((marker) => ({ color: marker.color, id: marker.id, price: marker.price, text: marker.text, time: marker.time })),
      [
        { color: "#33d17a", id: "news-1", price: 106.64, text: "N1", time: 1777646100 },
        { color: "#ff6b6b", id: "negative", price: 101.61, text: "N2", time: 1777645800 }
      ]
    );
  });

  it("limits marker text so labels remain readable on dense event clusters", () => {
    const bars = Array.from({ length: 8 }, (_, index) =>
      makeBar({ high: 101 + index, timestamp: `2026-05-01T14:${String(30 + index).padStart(2, "0")}:00.000Z` })
    );
    const events = Array.from({ length: 8 }, (_, index) =>
      makeNews({
        id: `news-${index}`,
        markerLabel: `N${index + 1}`,
        timestamp: `2026-05-01T14:${String(30 + index).padStart(2, "0")}:00.000Z`
      })
    );

    const markers = toNewsSeriesMarkers(events, bars, 20, 4);

    assert.deepEqual(
      markers.map((marker) => marker.text),
      ["N1", "N2", "N3", "N4", undefined, undefined, undefined, undefined]
    );
  });

  it("clusters multiple news events mapped to the same trading bar into one quiet marker", () => {
    const bars = [
      makeBar({ high: 101, timestamp: "2026-05-01T14:30:00.000Z" }),
      makeBar({ high: 106, timestamp: "2026-05-04T14:30:00.000Z" })
    ];
    const events = [
      makeNews({ id: "friday", markerLabel: "Fri", timestamp: "2026-05-01T15:00:00.000Z" }),
      makeNews({ id: "weekend", markerLabel: "Sun", timestamp: "2026-05-03T15:00:00.000Z" }),
      makeNews({ id: "monday", markerLabel: "Mon", timestamp: "2026-05-04T15:00:00.000Z" })
    ];

    const markers = toNewsSeriesMarkers(events, bars);

    assert.deepEqual(
      markers.map((marker) => ({ id: marker.id, size: marker.size, text: marker.text, time: marker.time })),
      [
        { id: "friday", size: 0.75, text: "Fri", time: 1777645800 },
        { id: "weekend", size: 0.75, text: undefined, time: 1777905000 }
      ]
    );
  });

  it("chooses an initial logical range that fills sparse one-month charts", () => {
    assert.deepEqual(getInitialVisibleLogicalRange(22, "1M"), { from: -1, to: 24 });
    assert.deepEqual(getInitialVisibleLogicalRange(2520, "10Y"), { from: 2297, to: 2522 });
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

function makeNews(overrides: Partial<NewsEvent>): NewsEvent {
  return {
    id: "news-1",
    markerLabel: "N1",
    relevance: 92,
    sentiment: "neutral",
    source: "Newswire",
    summary: "Research event",
    symbol: "NVDA",
    timestamp: "2026-05-01T14:30:00.000Z",
    title: "Market-moving update",
    url: "#",
    ...overrides
  };
}
