"use client";

import { useEffect, useMemo, useRef } from "react";
import { ColorType, createChart, type CandlestickData, type Time } from "lightweight-charts";

const BASE_SERIES: CandlestickData<Time>[] = [
  { time: "2026-04-24", open: 880, high: 902, low: 871, close: 895 },
  { time: "2026-04-25", open: 895, high: 910, low: 888, close: 904 },
  { time: "2026-04-28", open: 904, high: 918, low: 899, close: 912 },
  { time: "2026-04-29", open: 912, high: 920, low: 893, close: 900 },
  { time: "2026-04-30", open: 900, high: 930, low: 896, close: 924 }
];

const SYMBOL_OFFSETS: Record<string, number> = {
  AAPL: -710,
  MSFT: -480,
  NVDA: 0,
  SPY: -390
};

function getSeriesForSymbol(symbol: string): CandlestickData<Time>[] {
  const offset = SYMBOL_OFFSETS[symbol] ?? 0;

  return BASE_SERIES.map((bar) => ({
    ...bar,
    open: bar.open + offset,
    high: bar.high + offset,
    low: bar.low + offset,
    close: bar.close + offset
  }));
}

export function ChartWorkspace({ symbol }: { symbol: string }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const seriesData = useMemo(() => getSeriesForSymbol(symbol), [symbol]);
  const lastBar = seriesData[seriesData.length - 1];

  useEffect(() => {
    const container = containerRef.current;

    if (!container) {
      return;
    }

    const chart = createChart(container, {
      height: container.clientHeight,
      width: container.clientWidth,
      layout: {
        background: { type: ColorType.Solid, color: "#0f1720" },
        textColor: "#d8e1ea"
      },
      grid: {
        vertLines: { color: "#1f2a35" },
        horzLines: { color: "#1f2a35" }
      },
      crosshair: {
        mode: 1
      },
      rightPriceScale: { borderColor: "#2b3745" },
      timeScale: { borderColor: "#2b3745", timeVisible: true }
    });

    const series = chart.addCandlestickSeries({
      upColor: "#2fbf71",
      downColor: "#f05d5e",
      borderVisible: false,
      wickUpColor: "#2fbf71",
      wickDownColor: "#f05d5e"
    });

    series.setData(seriesData);
    chart.timeScale().fitContent();

    const resizeObserver = new ResizeObserver(([entry]) => {
      if (!entry) {
        return;
      }

      chart.applyOptions({
        height: Math.floor(entry.contentRect.height),
        width: Math.floor(entry.contentRect.width)
      });
    });

    resizeObserver.observe(container);

    return () => {
      resizeObserver.disconnect();
      chart.remove();
    };
  }, [seriesData]);

  return (
    <section className="chart-workspace">
      <header className="workspace-header">
        <div>
          <span className="workspace-kicker">Market workspace</span>
          <h1>{symbol}</h1>
        </div>
        <div className="quote-strip" aria-label={`${symbol} quote snapshot`}>
          <span>Last</span>
          <strong>{lastBar.close.toFixed(2)}</strong>
          <span className={lastBar.close >= lastBar.open ? "positive" : "negative"}>
            {lastBar.close >= lastBar.open ? "+" : ""}
            {(lastBar.close - lastBar.open).toFixed(2)}
          </span>
        </div>
      </header>
      <div ref={containerRef} className="chart-surface" />
    </section>
  );
}
