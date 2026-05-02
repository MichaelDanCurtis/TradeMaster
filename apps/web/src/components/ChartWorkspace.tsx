"use client";

import { useMemo, useState } from "react";

import {
  createHeikinAshiBars,
  createSimulatedMarketSnapshot,
  createVolumeProfileBins,
  getMarketProviderCatalog,
  type MarketInterval,
  type NormalizedMarketBar
} from "@/lib/market-data";

type RenderedBar = NormalizedMarketBar & {
  bodyHeight: number;
  bodyWidth: number;
  bodyY: number;
  color: string;
  radius: number;
  volumeHeight: number;
  volumeY: number;
  vwapY: number;
  wickY1: number;
  wickY2: number;
  x: number;
  yClose: number;
  yOpen: number;
};

type AxisTick = {
  label: string;
  y: number;
};

type TimeTick = {
  label: string;
  x: number;
};

type ChartView = "area" | "bars" | "candles" | "heikin-ashi" | "line" | "volume-profile";

const INTERVALS: Array<{ interval: MarketInterval; label: string; enabled: boolean; note: string }> = [
  { enabled: false, interval: "1s", label: "1s", note: "trade aggregation" },
  { enabled: false, interval: "5s", label: "5s", note: "trade aggregation" },
  { enabled: false, interval: "10s", label: "10s", note: "trade aggregation" },
  { enabled: true, interval: "1m", label: "1m", note: "Alpaca bars" },
  { enabled: true, interval: "5m", label: "5m", note: "Alpaca bars" },
  { enabled: true, interval: "15m", label: "15m", note: "Alpaca bars" },
  { enabled: true, interval: "1h", label: "1h", note: "Alpaca bars" },
  { enabled: true, interval: "1d", label: "1d", note: "historical" }
];

const CHART_VIEWS: Array<{ label: string; value: ChartView }> = [
  { label: "Candles", value: "candles" },
  { label: "Bars", value: "bars" },
  { label: "Line", value: "line" },
  { label: "Area", value: "area" },
  { label: "Heikin Ashi", value: "heikin-ashi" },
  { label: "Volume Profile", value: "volume-profile" }
];

const CHART_HEIGHT = 520;
const CHART_WIDTH = 1040;
const PLOT_PADDING = {
  bottom: 38,
  left: 38,
  right: 82,
  top: 28
};
const PRICE_PLOT_HEIGHT = 342;
const VOLUME_PLOT_TOP = 404;
const VOLUME_PLOT_HEIGHT = 74;

function getRenderedBars(seriesData: NormalizedMarketBar[]): RenderedBar[] {
  const minValue = Math.min(...seriesData.map((bar) => bar.low));
  const maxValue = Math.max(...seriesData.map((bar) => bar.high));
  const valueRange = maxValue - minValue || 1;
  const plotWidth = CHART_WIDTH - PLOT_PADDING.left - PLOT_PADDING.right;
  const step = plotWidth / Math.max(seriesData.length - 1, 1);
  const bodyWidth = Math.max(2.6, Math.min(7.2, step * 0.68));
  const maxVolume = Math.max(...seriesData.map((bar) => bar.volume));
  const scaleY = (value: number) => PLOT_PADDING.top + ((maxValue - value) / valueRange) * PRICE_PLOT_HEIGHT;
  const scaleVolume = (volume: number) => (volume / maxVolume) * VOLUME_PLOT_HEIGHT;

  return seriesData.map((bar, index) => {
    const x = PLOT_PADDING.left + index * step;
    const yOpen = scaleY(bar.open);
    const yClose = scaleY(bar.close);
    const bodyY = Math.min(yOpen, yClose);
    const bodyHeight = Math.max(Math.abs(yClose - yOpen), 2.4);
    const radius = Math.min(3.2, bodyWidth / 2, bodyHeight / 2);
    const volumeHeight = scaleVolume(bar.volume);

    return {
      ...bar,
      bodyHeight,
      bodyWidth,
      bodyY,
      color: bar.close >= bar.open ? "#33d17a" : "#ff6b6b",
      radius,
      volumeHeight,
      volumeY: VOLUME_PLOT_TOP + VOLUME_PLOT_HEIGHT - volumeHeight,
      vwapY: scaleY(bar.vwap ?? bar.close),
      wickY1: scaleY(bar.high),
      wickY2: scaleY(bar.low),
      x,
      yClose,
      yOpen
    };
  });
}

function getPriceTicks(seriesData: NormalizedMarketBar[]): AxisTick[] {
  const minValue = Math.min(...seriesData.map((bar) => bar.low));
  const maxValue = Math.max(...seriesData.map((bar) => bar.high));

  return [0, 0.25, 0.5, 0.75, 1].map((ratio) => {
    const value = maxValue - (maxValue - minValue) * ratio;

    return {
      label: value.toFixed(2),
      y: PLOT_PADDING.top + PRICE_PLOT_HEIGHT * ratio
    };
  });
}

function getTimeTicks(renderedBars: RenderedBar[], interval: MarketInterval): TimeTick[] {
  const targetCount = 6;
  const stride = Math.max(1, Math.floor((renderedBars.length - 1) / (targetCount - 1)));
  const selected = renderedBars.filter((_, index) => index % stride === 0).slice(0, targetCount - 1);
  const bars = [...selected, renderedBars[renderedBars.length - 1]];

  return bars.map((bar) => ({
    label: formatTimeLabel(bar.timestamp, interval),
    x: bar.x
  }));
}

function formatTimeLabel(timestamp: string, interval: MarketInterval): string {
  const date = new Date(timestamp);

  if (interval === "1d") {
    return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  }

  return date.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" });
}

function formatVolume(value: number): string {
  if (value >= 1_000_000_000) {
    return `${(value / 1_000_000_000).toFixed(1)}B`;
  }

  if (value >= 1_000_000) {
    return `${(value / 1_000_000).toFixed(1)}M`;
  }

  if (value >= 1_000) {
    return `${(value / 1_000).toFixed(1)}K`;
  }

  return value.toString();
}

function formatSigned(value: number): string {
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}`;
}

function getLinePoints(renderedBars: RenderedBar[]): string {
  return renderedBars.map((bar) => `${bar.x.toFixed(2)},${bar.yClose.toFixed(2)}`).join(" ");
}

function getAreaPath(renderedBars: RenderedBar[]): string {
  const pricePlotBottom = PLOT_PADDING.top + PRICE_PLOT_HEIGHT;
  const linePoints = renderedBars.map((bar) => `L ${bar.x.toFixed(2)} ${bar.yClose.toFixed(2)}`).join(" ");
  const firstBar = renderedBars[0];
  const lastBar = renderedBars[renderedBars.length - 1];

  return [
    `M ${firstBar.x.toFixed(2)} ${pricePlotBottom}`,
    `L ${firstBar.x.toFixed(2)} ${firstBar.yClose.toFixed(2)}`,
    linePoints,
    `L ${lastBar.x.toFixed(2)} ${pricePlotBottom}`,
    "Z"
  ].join(" ");
}

function getPriceY(seriesData: NormalizedMarketBar[], value: number): number {
  const minValue = Math.min(...seriesData.map((bar) => bar.low));
  const maxValue = Math.max(...seriesData.map((bar) => bar.high));
  const valueRange = maxValue - minValue || 1;

  return PLOT_PADDING.top + ((maxValue - value) / valueRange) * PRICE_PLOT_HEIGHT;
}

export function ChartWorkspace({ symbol }: { symbol: string }) {
  const [interval, setInterval] = useState<MarketInterval>("1m");
  const [chartView, setChartView] = useState<ChartView>("candles");
  const providerCatalog = useMemo(() => getMarketProviderCatalog(), []);
  const snapshot = useMemo(() => createSimulatedMarketSnapshot(symbol, interval), [interval, symbol]);
  const displayedBars = useMemo(
    () => (chartView === "heikin-ashi" ? createHeikinAshiBars(snapshot.bars) : snapshot.bars),
    [chartView, snapshot.bars]
  );
  const renderedBars = useMemo(() => getRenderedBars(displayedBars), [displayedBars]);
  const priceTicks = useMemo(() => getPriceTicks(displayedBars), [displayedBars]);
  const timeTicks = useMemo(() => getTimeTicks(renderedBars, interval), [interval, renderedBars]);
  const volumeProfileBins = useMemo(() => createVolumeProfileBins(displayedBars, 18), [displayedBars]);
  const lastBar = snapshot.bars[snapshot.bars.length - 1];
  const firstBar = snapshot.bars[0];
  const sessionChange = lastBar.close - firstBar.open;
  const sessionChangePercent = (sessionChange / firstBar.open) * 100;
  const range = snapshot.quote.dayHigh - snapshot.quote.dayLow;
  const vwap = lastBar.vwap ?? lastBar.close;
  const linePoints = getLinePoints(renderedBars);
  const areaPath = getAreaPath(renderedBars);
  const showCandles = chartView === "candles" || chartView === "heikin-ashi" || chartView === "volume-profile";
  const showBars = chartView === "bars";
  const showLine = chartView === "line" || chartView === "area";
  const showArea = chartView === "area";
  const showVolumeProfile = chartView === "volume-profile";
  const selectedViewLabel = CHART_VIEWS.find((view) => view.value === chartView)?.label ?? "Candles";

  return (
    <section className="chart-workspace">
      <header className="workspace-header">
        <div>
          <span className="panel-kicker">Market workspace</span>
          <h1>{symbol}</h1>
        </div>
        <div className="quote-strip" aria-label={`${symbol} quote snapshot`}>
          <span>Last</span>
          <strong>{snapshot.quote.last.toFixed(2)}</strong>
          <span className={sessionChange >= 0 ? "positive" : "negative"}>
            {formatSigned(sessionChange)} ({formatSigned(sessionChangePercent)}%)
          </span>
        </div>
      </header>

      <div className="data-source-strip" aria-label="Market data provider status">
        <div>
          <span>Feed</span>
          <strong>{providerCatalog[snapshot.provider].name}</strong>
        </div>
        <div>
          <span>Mode</span>
          <strong>
            {selectedViewLabel} {snapshot.interval}
          </strong>
        </div>
        <div>
          <span>Coverage</span>
          <strong>Bars, quote, VWAP, volume</strong>
        </div>
      </div>

      <div className="workspace-toolbar" aria-label="Chart timeframe controls">
        {INTERVALS.map((timeframe) => (
          <button
            aria-disabled={!timeframe.enabled}
            className={[
              "timeframe",
              timeframe.interval === interval ? "active" : "",
              !timeframe.enabled ? "disabled" : ""
            ]
              .filter(Boolean)
              .join(" ")}
            key={timeframe.interval}
            onClick={() => {
              if (timeframe.enabled) {
                setInterval(timeframe.interval);
              }
            }}
            title={timeframe.note}
            type="button"
          >
            {timeframe.label}
          </button>
        ))}
      </div>

      <div className="view-toolbar" aria-label="Chart view controls">
        {CHART_VIEWS.map((view) => (
          <button
            className={view.value === chartView ? "view-mode active" : "view-mode"}
            key={view.value}
            onClick={() => setChartView(view.value)}
            type="button"
          >
            {view.label}
          </button>
        ))}
      </div>

      <div className="chart-shell">
        <div className="chart-surface" aria-label={`${symbol} normalized ${chartView} chart`}>
          <svg
            className="candlestick-chart"
            role="img"
            viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`}
            xmlns="http://www.w3.org/2000/svg"
          >
            <title>{symbol} normalized {chartView} chart</title>
            <defs>
              <linearGradient id={`chartGlow-${symbol}`} x1="0" x2="0" y1="0" y2="1">
                <stop offset="0%" stopColor="#172231" />
                <stop offset="100%" stopColor="#0c1219" />
              </linearGradient>
              <linearGradient id={`areaFill-${symbol}`} x1="0" x2="0" y1="0" y2="1">
                <stop offset="0%" stopColor="rgba(79, 140, 255, 0.42)" />
                <stop offset="100%" stopColor="rgba(79, 140, 255, 0.03)" />
              </linearGradient>
            </defs>
            <rect fill={`url(#chartGlow-${symbol})`} height={CHART_HEIGHT} width={CHART_WIDTH} />
            {[0, 1, 2, 3, 4].map((line) => {
              const y = PLOT_PADDING.top + line * (PRICE_PLOT_HEIGHT / 4);
              return <line className="chart-grid-line" key={`h-${line}`} x1="0" x2={CHART_WIDTH} y1={y} y2={y} />;
            })}
            {[0, 1, 2, 3, 4, 5].map((line) => {
              const x = PLOT_PADDING.left + line * ((CHART_WIDTH - PLOT_PADDING.left - PLOT_PADDING.right) / 5);
              return <line className="chart-grid-line" key={`v-${line}`} x1={x} x2={x} y1="0" y2={CHART_HEIGHT} />;
            })}
            <line
              className="chart-section-rule"
              x1={PLOT_PADDING.left}
              x2={CHART_WIDTH - PLOT_PADDING.right}
              y1={VOLUME_PLOT_TOP - 18}
              y2={VOLUME_PLOT_TOP - 18}
            />
            {priceTicks.map((tick) => (
              <text className="chart-axis-label" key={tick.label} x={CHART_WIDTH - 70} y={tick.y + 4}>
                {tick.label}
              </text>
            ))}
            {showArea ? <path className="area-fill" d={areaPath} fill={`url(#areaFill-${symbol})`} /> : null}
            {showLine ? <polyline className="price-line" points={linePoints} /> : null}
            {showCandles
              ? renderedBars.map((bar) => (
                  <g className={showVolumeProfile ? "candle muted" : "candle"} key={bar.timestamp}>
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
                      width={bar.bodyWidth}
                      x={bar.x - bar.bodyWidth / 2}
                      y={bar.bodyY}
                    />
                  </g>
                ))
              : null}
            {showBars
              ? renderedBars.map((bar) => {
                  const tickWidth = Math.max(4, bar.bodyWidth * 1.8);

                  return (
                    <g className="ohlc-bar" key={bar.timestamp} stroke={bar.color}>
                      <line x1={bar.x} x2={bar.x} y1={bar.wickY1} y2={bar.wickY2} />
                      <line x1={bar.x - tickWidth} x2={bar.x} y1={bar.yOpen} y2={bar.yOpen} />
                      <line x1={bar.x} x2={bar.x + tickWidth} y1={bar.yClose} y2={bar.yClose} />
                    </g>
                  );
                })
              : null}
            {renderedBars.map((bar) => (
              <rect
                className={bar.close >= bar.open ? "volume-bar positive" : "volume-bar negative"}
                height={bar.volumeHeight}
                key={`volume-${bar.timestamp}`}
                rx="1.8"
                ry="1.8"
                width={Math.max(1.8, bar.bodyWidth)}
                x={bar.x - Math.max(1.8, bar.bodyWidth) / 2}
                y={bar.volumeY}
              />
            ))}
            {showVolumeProfile
              ? volumeProfileBins.map((bin) => {
                  const yTop = getPriceY(displayedBars, bin.priceEnd);
                  const yBottom = getPriceY(displayedBars, bin.priceStart);
                  const width = 178 * bin.volumeShare;
                  const x = CHART_WIDTH - PLOT_PADDING.right - width;

                  return (
                    <rect
                      className="volume-profile-bin"
                      height={Math.max(3, yBottom - yTop - 1)}
                      key={`${bin.priceStart}-${bin.priceEnd}`}
                      rx="2"
                      ry="2"
                      width={width}
                      x={x}
                      y={yTop}
                    />
                  );
                })
              : null}
            <polyline
              className="vwap-line"
              points={renderedBars.map((bar) => `${bar.x.toFixed(2)},${bar.vwapY.toFixed(2)}`).join(" ")}
            />
            {timeTicks.map((tick) => (
              <text className="chart-time-label" key={`${tick.x}-${tick.label}`} x={tick.x} y={CHART_HEIGHT - 16}>
                {tick.label}
              </text>
            ))}
            <text className="chart-volume-label" x={PLOT_PADDING.left} y={VOLUME_PLOT_TOP - 28}>
              VOL {formatVolume(snapshot.quote.dayVolume)}
            </text>
            <text className="chart-volume-label" x={PLOT_PADDING.left + 116} y={VOLUME_PLOT_TOP - 28}>
              VWAP {vwap.toFixed(2)}
            </text>
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
          <strong>{snapshot.quote.dayHigh.toFixed(2)}</strong>
        </div>
        <div>
          <span>Low</span>
          <strong>{snapshot.quote.dayLow.toFixed(2)}</strong>
        </div>
        <div>
          <span>Range</span>
          <strong>{range.toFixed(2)}</strong>
        </div>
        <div>
          <span>Bid / Ask</span>
          <strong>
            {snapshot.quote.bid.toFixed(2)} / {snapshot.quote.ask.toFixed(2)}
          </strong>
        </div>
        <div>
          <span>Volume</span>
          <strong>{formatVolume(snapshot.quote.dayVolume)}</strong>
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
