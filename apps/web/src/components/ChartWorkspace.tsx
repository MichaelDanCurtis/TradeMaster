"use client";

import { useMemo } from "react";

type ChartBar = {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
};

type RenderedBar = ChartBar & {
  bodyHeight: number;
  bodyY: number;
  color: string;
  radius: number;
  wickY1: number;
  wickY2: number;
  x: number;
  yClose: number;
  yOpen: number;
};

const BASE_SERIES: ChartBar[] = [
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

const TIMEFRAMES = ["1D", "5D", "1M", "6M", "YTD"];
const CHART_HEIGHT = 420;
const CHART_WIDTH = 920;
const CANDLE_WIDTH = 72;
const CANDLE_RADIUS = 5;
const PLOT_PADDING = {
  bottom: 42,
  left: 34,
  right: 72,
  top: 28
};

function getSeriesForSymbol(symbol: string): ChartBar[] {
  const offset = SYMBOL_OFFSETS[symbol] ?? 0;

  return BASE_SERIES.map((bar) => ({
    ...bar,
    open: bar.open + offset,
    high: bar.high + offset,
    low: bar.low + offset,
    close: bar.close + offset
  }));
}

function getRenderedBars(seriesData: ChartBar[]): RenderedBar[] {
  const minValue = Math.min(...seriesData.map((bar) => bar.low));
  const maxValue = Math.max(...seriesData.map((bar) => bar.high));
  const valueRange = maxValue - minValue || 1;
  const plotHeight = CHART_HEIGHT - PLOT_PADDING.top - PLOT_PADDING.bottom;
  const plotWidth = CHART_WIDTH - PLOT_PADDING.left - PLOT_PADDING.right;
  const step = plotWidth / Math.max(seriesData.length - 1, 1);
  const scaleY = (value: number) =>
    PLOT_PADDING.top + ((maxValue - value) / valueRange) * plotHeight;

  return seriesData.map((bar, index) => {
    const x = PLOT_PADDING.left + index * step;
    const yOpen = scaleY(bar.open);
    const yClose = scaleY(bar.close);
    const bodyY = Math.min(yOpen, yClose);
    const bodyHeight = Math.max(Math.abs(yClose - yOpen), 4);
    const radius = Math.min(CANDLE_RADIUS, CANDLE_WIDTH / 2, bodyHeight / 2);

    return {
      ...bar,
      bodyHeight,
      bodyY,
      color: bar.close >= bar.open ? "#33d17a" : "#ff6b6b",
      radius,
      wickY1: scaleY(bar.high),
      wickY2: scaleY(bar.low),
      x,
      yClose,
      yOpen
    };
  });
}

function getPriceTicks(seriesData: ChartBar[]): string[] {
  const minValue = Math.min(...seriesData.map((bar) => bar.low));
  const maxValue = Math.max(...seriesData.map((bar) => bar.high));
  const midValue = (minValue + maxValue) / 2;

  return [maxValue, midValue, minValue].map((value) => value.toFixed(0));
}

export function ChartWorkspace({ symbol }: { symbol: string }) {
  const seriesData = useMemo(() => getSeriesForSymbol(symbol), [symbol]);
  const renderedBars = useMemo(() => getRenderedBars(seriesData), [seriesData]);
  const priceTicks = useMemo(() => getPriceTicks(seriesData), [seriesData]);
  const lastBar = seriesData[seriesData.length - 1];
  const openChange = lastBar.close - lastBar.open;
  const range = lastBar.high - lastBar.low;

  return (
    <section className="chart-workspace">
      <header className="workspace-header">
        <div>
          <span className="panel-kicker">Market workspace</span>
          <h1>{symbol}</h1>
        </div>
        <div className="quote-strip" aria-label={`${symbol} quote snapshot`}>
          <span>Last</span>
          <strong>{lastBar.close.toFixed(2)}</strong>
          <span className={lastBar.close >= lastBar.open ? "positive" : "negative"}>
            {lastBar.close >= lastBar.open ? "+" : ""}
            {openChange.toFixed(2)}
          </span>
        </div>
      </header>
      <div className="workspace-toolbar" aria-label="Chart timeframe controls">
        {TIMEFRAMES.map((timeframe) => (
          <button className={timeframe === "1D" ? "timeframe active" : "timeframe"} key={timeframe} type="button">
            {timeframe}
          </button>
        ))}
      </div>
      <div className="chart-shell">
        <div className="chart-surface" aria-label={`${symbol} simulated candlestick chart`}>
          <svg
            className="candlestick-chart"
            role="img"
            viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`}
            xmlns="http://www.w3.org/2000/svg"
          >
            <title>{symbol} simulated candlestick chart</title>
            <defs>
              <linearGradient id={`chartGlow-${symbol}`} x1="0" x2="0" y1="0" y2="1">
                <stop offset="0%" stopColor="#172231" />
                <stop offset="100%" stopColor="#0c1219" />
              </linearGradient>
            </defs>
            <rect fill={`url(#chartGlow-${symbol})`} height={CHART_HEIGHT} width={CHART_WIDTH} />
            {[0, 1, 2, 3, 4].map((line) => {
              const y = PLOT_PADDING.top + line * 72;
              return <line className="chart-grid-line" key={`h-${line}`} x1="0" x2={CHART_WIDTH} y1={y} y2={y} />;
            })}
            {[0, 1, 2, 3, 4, 5].map((line) => {
              const x = PLOT_PADDING.left + line * 146;
              return <line className="chart-grid-line" key={`v-${line}`} x1={x} x2={x} y1="0" y2={CHART_HEIGHT} />;
            })}
            {priceTicks.map((tick, index) => (
              <text className="chart-axis-label" key={tick} x={CHART_WIDTH - 52} y={PLOT_PADDING.top + index * 174}>
                {tick}
              </text>
            ))}
            {renderedBars.map((bar) => (
              <g className="candle" key={bar.time}>
                <line
                  className="candle-wick"
                  stroke={bar.color}
                  x1={bar.x}
                  x2={bar.x}
                  y1={bar.wickY1}
                  y2={bar.wickY2}
                />
                <rect
                  fill={bar.color}
                  height={bar.bodyHeight}
                  rx={bar.radius}
                  ry={bar.radius}
                  width={CANDLE_WIDTH}
                  x={bar.x - CANDLE_WIDTH / 2}
                  y={bar.bodyY}
                />
                <text className="chart-time-label" x={bar.x} y={CHART_HEIGHT - 18}>
                  {bar.time.slice(5)}
                </text>
              </g>
            ))}
          </svg>
        </div>
      </div>
      <footer className="market-readout">
        <div>
          <span>Open</span>
          <strong>{lastBar.open.toFixed(2)}</strong>
        </div>
        <div>
          <span>High</span>
          <strong>{lastBar.high.toFixed(2)}</strong>
        </div>
        <div>
          <span>Low</span>
          <strong>{lastBar.low.toFixed(2)}</strong>
        </div>
        <div>
          <span>Range</span>
          <strong>{range.toFixed(2)}</strong>
        </div>
      </footer>
      <section className="report-strip">
        <div>
          <span className="panel-kicker">Research stance</span>
          <strong>Awaiting latest agent report</strong>
        </div>
        <p>Run the analyst team from the cockpit to populate a decision, trace, and approval-gated paper order.</p>
      </section>
    </section>
  );
}
