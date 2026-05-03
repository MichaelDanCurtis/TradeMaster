"use client";

import { useMemo, useState } from "react";

import {
  calculatePerformanceSpread,
  createComparisonSeries,
  createHeikinAshiBars,
  createPriorPeriodBars,
  createSimulatedHistoricalSnapshot,
  createVolumeProfileBins,
  getMarketProviderCatalog,
  normalizePerformanceSeries,
  type ComparisonPoint,
  type MarketRange,
  type NormalizedMarketBar
} from "@/lib/market-data";
import type { NewsEvent } from "@/lib/workspace-data";

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

type ChartEventMarker = {
  event: NewsEvent;
  labelX: number;
  showLabel: boolean;
  x: number;
  y: number;
};

type ChartView =
  | "area"
  | "bars"
  | "baseline"
  | "candles"
  | "heikin-ashi"
  | "hollow-candles"
  | "line"
  | "step-line"
  | "volume-profile";

const CHART_VIEWS: Array<{ label: string; value: ChartView }> = [
  { label: "Candles", value: "candles" },
  { label: "Hollow", value: "hollow-candles" },
  { label: "Bars", value: "bars" },
  { label: "Line", value: "line" },
  { label: "Step", value: "step-line" },
  { label: "Area", value: "area" },
  { label: "Baseline", value: "baseline" },
  { label: "Heikin Ashi", value: "heikin-ashi" },
  { label: "Volume Profile", value: "volume-profile" }
];

const RANGE_OPTIONS: Array<{ label: string; value: MarketRange }> = [
  { label: "1M", value: "1M" },
  { label: "YTD", value: "YTD" },
  { label: "1Y", value: "1Y" },
  { label: "3Y", value: "3Y" },
  { label: "5Y", value: "5Y" },
  { label: "10Y", value: "10Y" }
];

const COMPARE_OPTIONS = ["SPY", "AAPL", "MSFT", "NVDA"];
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
const MAX_CHART_EVENTS = 20;
const LABELED_CHART_EVENTS = 5;

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

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

function getTimeTicks(renderedBars: RenderedBar[], range: MarketRange): TimeTick[] {
  const targetCount = 6;
  const stride = Math.max(1, Math.floor((renderedBars.length - 1) / (targetCount - 1)));
  const selected = renderedBars.filter((_, index) => index % stride === 0).slice(0, targetCount - 1);
  const bars = [...selected, renderedBars[renderedBars.length - 1]];

  return bars.map((bar) => ({
    label: formatTimeLabel(bar.timestamp, range),
    x: bar.x
  }));
}

function formatTimeLabel(timestamp: string, range: MarketRange): string {
  const date = new Date(timestamp);

  if (range === "1M" || range === "YTD") {
    return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  }

  return date.toLocaleDateString("en-US", { month: "short", year: "2-digit" });
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

function getStepLinePoints(renderedBars: RenderedBar[]): string {
  return renderedBars
    .flatMap((bar, index) => {
      if (index === 0) {
        return [`${bar.x.toFixed(2)},${bar.yClose.toFixed(2)}`];
      }

      const previous = renderedBars[index - 1];
      return [`${bar.x.toFixed(2)},${previous.yClose.toFixed(2)}`, `${bar.x.toFixed(2)},${bar.yClose.toFixed(2)}`];
    })
    .join(" ");
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

function getPerformanceY(points: Array<{ value: number }>, value: number): number {
  const values = points.map((point) => point.value);
  const minValue = Math.min(-1, ...values);
  const maxValue = Math.max(1, ...values);
  const valueRange = maxValue - minValue || 1;

  return PLOT_PADDING.top + ((maxValue - value) / valueRange) * PRICE_PLOT_HEIGHT;
}

function getPerformancePoints(points: Array<{ value: number }>, scalePoints: Array<{ value: number }> = points): string {
  const plotWidth = CHART_WIDTH - PLOT_PADDING.left - PLOT_PADDING.right;
  const step = plotWidth / Math.max(points.length - 1, 1);

  return points
    .map((point, index) => {
      const x = PLOT_PADDING.left + index * step;
      const y = getPerformanceY(scalePoints, point.value);

      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");
}

function getComparisonPoints(
  points: ComparisonPoint[],
  key: "benchmark" | "subject",
  scalePoints: Array<{ value: number }>
): string {
  const plotWidth = CHART_WIDTH - PLOT_PADDING.left - PLOT_PADDING.right;
  const step = plotWidth / Math.max(points.length - 1, 1);

  return points
    .map((point, index) => {
      const x = PLOT_PADDING.left + index * step;
      const y = getPerformanceY(scalePoints, point[key]);

      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");
}

function downsampleBars(bars: NormalizedMarketBar[], maxCount: number): NormalizedMarketBar[] {
  if (bars.length <= maxCount) return bars;

  const stride = Math.ceil(bars.length / maxCount);
  return bars.filter((_, index) => index % stride === 0).slice(0, maxCount);
}

function getClosestRenderedBar(event: NewsEvent, renderedBars: RenderedBar[]): RenderedBar {
  const eventTime = new Date(event.timestamp).getTime();

  return renderedBars.reduce((closestBar, currentBar) => {
    const closestDistance = Math.abs(new Date(closestBar.timestamp).getTime() - eventTime);
    const currentDistance = Math.abs(new Date(currentBar.timestamp).getTime() - eventTime);

    return currentDistance < closestDistance ? currentBar : closestBar;
  });
}

function getEventMarkers(newsEvents: NewsEvent[], renderedBars: RenderedBar[]): ChartEventMarker[] {
  return newsEvents
    .slice(0, MAX_CHART_EVENTS)
    .map((event, index) => {
      const closestBar = getClosestRenderedBar(event, renderedBars);
      const labelOffset = index % LABELED_CHART_EVENTS;
      const markerY = clamp(closestBar.wickY1 - 12 - labelOffset * 14, PLOT_PADDING.top + 14, PRICE_PLOT_HEIGHT);

      return {
        event,
        labelX: clamp(closestBar.x + (labelOffset - 2) * 18, 58, CHART_WIDTH - PLOT_PADDING.right - 42),
        showLabel: index < LABELED_CHART_EVENTS,
        x: closestBar.x,
        y: markerY
      };
    });
}

function formatEventTimestamp(timestamp: string): string {
  return new Date(timestamp).toLocaleString("en-US", {
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    month: "short"
  });
}

export function ChartWorkspace({ newsEvents = [], symbol }: { newsEvents?: NewsEvent[]; symbol: string }) {
  const [chartRange, setChartRange] = useState<MarketRange>("1M");
  const [chartView, setChartView] = useState<ChartView>("candles");
  const [compareEnabled, setCompareEnabled] = useState(false);
  const [compareSymbol, setCompareSymbol] = useState("SPY");
  const [priorPeriodEnabled, setPriorPeriodEnabled] = useState(false);
  const providerCatalog = useMemo(() => getMarketProviderCatalog(), []);
  const effectiveCompareSymbol =
    compareSymbol === symbol ? (COMPARE_OPTIONS.find((option) => option !== symbol) ?? "SPY") : compareSymbol;
  const snapshot = useMemo(() => createSimulatedHistoricalSnapshot(symbol, chartRange), [chartRange, symbol]);
  const comparisonSnapshot = useMemo(
    () => createSimulatedHistoricalSnapshot(effectiveCompareSymbol, chartRange),
    [chartRange, effectiveCompareSymbol]
  );
  const priorPeriodBars = useMemo(() => createPriorPeriodBars(symbol, chartRange), [chartRange, symbol]);
  const displayedBars = useMemo(
    () => (chartView === "heikin-ashi" ? createHeikinAshiBars(snapshot.bars) : snapshot.bars),
    [chartView, snapshot.bars]
  );
  const renderBars = useMemo(() => downsampleBars(displayedBars, 260), [displayedBars]);
  const renderedBars = useMemo(() => getRenderedBars(renderBars), [renderBars]);
  const priceTicks = useMemo(() => getPriceTicks(renderBars), [renderBars]);
  const timeTicks = useMemo(() => getTimeTicks(renderedBars, chartRange), [chartRange, renderedBars]);
  const eventMarkers = useMemo(() => getEventMarkers(newsEvents, renderedBars), [newsEvents, renderedBars]);
  const volumeProfileBins = useMemo(() => createVolumeProfileBins(renderBars, 18), [renderBars]);
  const performanceSeries = useMemo(() => normalizePerformanceSeries(snapshot.bars), [snapshot.bars]);
  const comparisonSeries = useMemo(
    () => createComparisonSeries(snapshot.bars, comparisonSnapshot.bars),
    [comparisonSnapshot.bars, snapshot.bars]
  );
  const priorPerformanceSeries = useMemo(() => normalizePerformanceSeries(priorPeriodBars), [priorPeriodBars]);
  const performanceScalePoints = useMemo(
    () => [
      ...performanceSeries,
      ...(compareEnabled
        ? comparisonSeries.flatMap((point) => [{ value: point.subject }, { value: point.benchmark }])
        : []),
      ...(priorPeriodEnabled ? priorPerformanceSeries : [])
    ],
    [compareEnabled, comparisonSeries, performanceSeries, priorPeriodEnabled, priorPerformanceSeries]
  );
  const performanceSpread = useMemo(() => calculatePerformanceSpread(comparisonSeries), [comparisonSeries]);
  const lastBar = snapshot.bars[snapshot.bars.length - 1];
  const firstBar = snapshot.bars[0];
  const sessionChange = lastBar.close - firstBar.open;
  const sessionChangePercent = (sessionChange / firstBar.open) * 100;
  const range = snapshot.quote.dayHigh - snapshot.quote.dayLow;
  const vwap = lastBar.vwap ?? lastBar.close;
  const linePoints = getLinePoints(renderedBars);
  const stepLinePoints = getStepLinePoints(renderedBars);
  const areaPath = getAreaPath(renderedBars);
  const showCandles =
    chartView === "candles" ||
    chartView === "heikin-ashi" ||
    chartView === "hollow-candles" ||
    chartView === "volume-profile";
  const showBars = chartView === "bars";
  const showLine = chartView === "line" || chartView === "area" || chartView === "baseline";
  const showArea = chartView === "area";
  const showStepLine = chartView === "step-line";
  const showBaseline = chartView === "baseline";
  const showVolumeProfile = chartView === "volume-profile";
  const selectedViewLabel = CHART_VIEWS.find((view) => view.value === chartView)?.label ?? "Candles";
  const performanceMode = compareEnabled || priorPeriodEnabled;
  const comparisonPoints = getComparisonPoints(comparisonSeries, "benchmark", performanceScalePoints);
  const priorPeriodPoints = getPerformancePoints(priorPerformanceSeries, performanceScalePoints);
  const subjectPerformancePoints = getPerformancePoints(performanceSeries, performanceScalePoints);

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
            {selectedViewLabel} {chartRange}
          </strong>
        </div>
        <div>
          <span>Coverage</span>
          <strong>Bars, quote, VWAP, volume</strong>
        </div>
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
      <div className="comparison-toolbar" aria-label="Chart comparison controls">
        <label>
          <span>Range</span>
          <select value={chartRange} onChange={(event) => setChartRange(event.target.value as MarketRange)}>
            {RANGE_OPTIONS.map((rangeOption) => (
              <option key={rangeOption.value} value={rangeOption.value}>
                {rangeOption.label}
              </option>
            ))}
          </select>
        </label>
        <label className="toggle-control">
          <input checked={compareEnabled} onChange={(event) => setCompareEnabled(event.target.checked)} type="checkbox" />
          <span>Compare</span>
        </label>
        <label>
          <span>Against</span>
          <select
            disabled={!compareEnabled}
            value={compareSymbol}
            onChange={(event) => setCompareSymbol(event.target.value)}
          >
            {COMPARE_OPTIONS.filter((option) => option !== symbol).map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>
        <label className="toggle-control">
          <input
            checked={priorPeriodEnabled}
            onChange={(event) => setPriorPeriodEnabled(event.target.checked)}
            type="checkbox"
          />
          <span>Prior period</span>
        </label>
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
            {performanceMode
              ? [-20, -10, 0, 10, 20].map((tick) => (
                  <text className="chart-axis-label" key={tick} x={CHART_WIDTH - 70} y={getPerformanceY(performanceScalePoints, tick) + 4}>
                    {tick}%
                  </text>
                ))
              : priceTicks.map((tick) => (
                  <text className="chart-axis-label" key={tick.label} x={CHART_WIDTH - 70} y={tick.y + 4}>
                    {tick.label}
                  </text>
                ))}
            {performanceMode ? (
              <>
                <line
                  className="baseline-zero"
                  x1={PLOT_PADDING.left}
                  x2={CHART_WIDTH - PLOT_PADDING.right}
                  y1={getPerformanceY(performanceScalePoints, 0)}
                  y2={getPerformanceY(performanceScalePoints, 0)}
                />
                <polyline className="performance-line subject" points={subjectPerformancePoints} />
                {compareEnabled ? <polyline className="performance-line benchmark" points={comparisonPoints} /> : null}
                {priorPeriodEnabled ? <polyline className="performance-line prior" points={priorPeriodPoints} /> : null}
              </>
            ) : null}
            {!performanceMode && showArea ? <path className="area-fill" d={areaPath} fill={`url(#areaFill-${symbol})`} /> : null}
            {!performanceMode && showLine ? <polyline className="price-line" points={linePoints} /> : null}
            {!performanceMode && showStepLine ? <polyline className="price-line step" points={stepLinePoints} /> : null}
            {!performanceMode && showBaseline ? (
              <line
                className="baseline-zero"
                x1={PLOT_PADDING.left}
                x2={CHART_WIDTH - PLOT_PADDING.right}
                y1={getPriceY(renderBars, firstBar.open)}
                y2={getPriceY(renderBars, firstBar.open)}
              />
            ) : null}
            {!performanceMode && showCandles
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
                      className={chartView === "hollow-candles" && bar.close >= bar.open ? "hollow-candle-body" : ""}
                      fill={chartView === "hollow-candles" && bar.close >= bar.open ? "transparent" : bar.color}
                      height={bar.bodyHeight}
                      rx={bar.radius}
                      ry={bar.radius}
                      stroke={chartView === "hollow-candles" ? bar.color : "none"}
                      strokeWidth={chartView === "hollow-candles" ? 1.4 : 0}
                      width={bar.bodyWidth}
                      x={bar.x - bar.bodyWidth / 2}
                      y={bar.bodyY}
                    />
                  </g>
                ))
              : null}
            {!performanceMode && showBars
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
            {!performanceMode
              ? renderedBars.map((bar) => (
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
                ))
              : null}
            {!performanceMode && showVolumeProfile
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
            {!performanceMode ? <polyline
              className="vwap-line"
              points={renderedBars.map((bar) => `${bar.x.toFixed(2)},${bar.vwapY.toFixed(2)}`).join(" ")}
            /> : null}
            {!performanceMode
              ? eventMarkers.map((marker) => (
                  <g
                    aria-label={`${marker.event.markerLabel}: ${marker.event.title}`}
                    className={`news-marker ${marker.event.sentiment}`}
                    key={marker.event.id}
                    role="img"
                  >
                    <title>
                      {marker.event.title} from {marker.event.source}. Relevance {marker.event.relevance}.
                    </title>
                    <line className="news-marker-stem" x1={marker.x} x2={marker.x} y1={marker.y + 5} y2={marker.y + 18} />
                    <circle className="news-marker-dot" cx={marker.x} cy={marker.y} r="4.4" />
                    {marker.showLabel ? (
                      <text className="news-marker-label" x={marker.labelX} y={marker.y - 8}>
                        {marker.event.markerLabel}
                      </text>
                    ) : null}
                  </g>
                ))
              : null}
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
            {compareEnabled ? (
              <text className="chart-volume-label" x={PLOT_PADDING.left + 220} y={VOLUME_PLOT_TOP - 28}>
                {symbol} {formatSigned(performanceSpread.subjectReturn)}% vs {effectiveCompareSymbol}{" "}
                {formatSigned(performanceSpread.benchmarkReturn)}%
              </text>
            ) : null}
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
          <span>{chartRange} Return</span>
          <strong>{formatSigned(sessionChangePercent)}%</strong>
        </div>
        <div>
          <span>Relative</span>
          <strong>{compareEnabled ? `${formatSigned(performanceSpread.relativeSpread)}%` : "Off"}</strong>
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

      {newsEvents.length > 0 ? (
        <section className="news-event-feed" aria-label={`${symbol} news and events`}>
          <div className="section-title">
            <span>News / events</span>
            <span>{Math.min(newsEvents.length, MAX_CHART_EVENTS)} mapped</span>
          </div>
          <div className="news-event-list">
            {newsEvents.slice(0, MAX_CHART_EVENTS).map((event) => (
              <article className="news-event-item" key={event.id}>
                <div className="news-event-heading">
                  <strong>{event.title}</strong>
                  <span className={`sentiment-badge ${event.sentiment}`}>{event.sentiment}</span>
                </div>
                <div className="news-event-meta">
                  <span>{event.source}</span>
                  <span>{formatEventTimestamp(event.timestamp)}</span>
                  <span>{event.relevance}% relevance</span>
                </div>
              </article>
            ))}
          </div>
        </section>
      ) : null}
    </section>
  );
}
