"use client";

import { useEffect, useMemo, useState } from "react";

import { EvidenceChart, type EvidenceChartView } from "@/components/EvidenceChart";
import {
  calculatePerformanceSpread,
  createComparisonSeries,
  createHeikinAshiBars,
  createPriorPeriodBars,
  createSimulatedHistoricalSnapshot,
  createVolumeProfileBins,
  getMarketProviderCatalog,
  normalizePerformanceSeries,
  type MarketDataSnapshot,
  type MarketRange
} from "@/lib/market-data";
import type { NewsEvent } from "@/lib/workspace-data";

const CHART_VIEWS: Array<{ label: string; value: EvidenceChartView }> = [
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
  { label: "1D", value: "1D" },
  { label: "5D", value: "5D" },
  { label: "1M", value: "1M" },
  { label: "YTD", value: "YTD" },
  { label: "1Y", value: "1Y" },
  { label: "3Y", value: "3Y" },
  { label: "5Y", value: "5Y" },
  { label: "10Y", value: "10Y" }
];

const COMPARE_OPTIONS = ["SPY", "AAPL", "MSFT", "NVDA"];
const MAX_CHART_EVENTS = 20;

type LiveDataState = {
  comparisonSnapshot: MarketDataSnapshot | null;
  error: string | null;
  snapshot: MarketDataSnapshot | null;
  status: "fallback" | "loading" | "live";
};

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
  const [chartView, setChartView] = useState<EvidenceChartView>("candles");
  const [compareEnabled, setCompareEnabled] = useState(false);
  const [compareSymbol, setCompareSymbol] = useState("SPY");
  const [priorPeriodEnabled, setPriorPeriodEnabled] = useState(false);
  const providerCatalog = useMemo(() => getMarketProviderCatalog(), []);
  const effectiveCompareSymbol =
    compareSymbol === symbol ? (COMPARE_OPTIONS.find((option) => option !== symbol) ?? "SPY") : compareSymbol;
  const simulatedSnapshot = useMemo(() => createSimulatedHistoricalSnapshot(symbol, chartRange), [chartRange, symbol]);
  const simulatedComparisonSnapshot = useMemo(
    () => createSimulatedHistoricalSnapshot(effectiveCompareSymbol, chartRange),
    [chartRange, effectiveCompareSymbol]
  );
  const [liveData, setLiveData] = useState<LiveDataState>({
    comparisonSnapshot: null,
    error: null,
    snapshot: null,
    status: "loading"
  });

  useEffect(() => {
    const controller = new AbortController();

    setLiveData({
      comparisonSnapshot: null,
      error: null,
      snapshot: null,
      status: "loading"
    });

    Promise.all([
      fetchMarketSnapshot(symbol, chartRange, controller.signal),
      fetchMarketSnapshot(effectiveCompareSymbol, chartRange, controller.signal)
    ])
      .then(([nextSnapshot, nextComparisonSnapshot]) => {
        setLiveData({
          comparisonSnapshot: nextComparisonSnapshot,
          error: null,
          snapshot: nextSnapshot,
          status: "live"
        });
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) {
          return;
        }

        setLiveData({
          comparisonSnapshot: null,
          error: error instanceof Error ? error.message : "Live data request failed",
          snapshot: null,
          status: "fallback"
        });
      });

    return () => {
      controller.abort();
    };
  }, [chartRange, effectiveCompareSymbol, symbol]);

  const snapshot = liveData.snapshot ?? simulatedSnapshot;
  const comparisonSnapshot = liveData.comparisonSnapshot ?? simulatedComparisonSnapshot;
  const priorPeriodBars = useMemo(() => createPriorPeriodBars(symbol, chartRange), [chartRange, symbol]);
  const displayedBars = useMemo(
    () => (chartView === "heikin-ashi" ? createHeikinAshiBars(snapshot.bars) : snapshot.bars),
    [chartView, snapshot.bars]
  );
  const volumeProfileBins = useMemo(() => createVolumeProfileBins(displayedBars, 18), [displayedBars]);
  const performanceSeries = useMemo(() => normalizePerformanceSeries(snapshot.bars), [snapshot.bars]);
  const comparisonSeries = useMemo(
    () => createComparisonSeries(snapshot.bars, comparisonSnapshot.bars),
    [comparisonSnapshot.bars, snapshot.bars]
  );
  const priorPerformanceSeries = useMemo(() => normalizePerformanceSeries(priorPeriodBars), [priorPeriodBars]);
  const performanceSpread = useMemo(() => calculatePerformanceSpread(comparisonSeries), [comparisonSeries]);
  const lastBar = snapshot.bars[snapshot.bars.length - 1];
  const firstBar = snapshot.bars[0];
  const sessionChange = lastBar.close - firstBar.open;
  const sessionChangePercent = (sessionChange / firstBar.open) * 100;
  const range = snapshot.quote.dayHigh - snapshot.quote.dayLow;
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
            {selectedViewLabel} {chartRange}
          </strong>
        </div>
        <div>
          <span>Coverage</span>
          <strong>
            {liveData.status === "loading"
              ? "Loading real bars"
              : liveData.status === "live"
                ? "Real OHLCV, delayed"
                : "Simulated fallback"}
          </strong>
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
        <EvidenceChart
          bars={displayedBars}
          chartRange={chartRange}
          chartView={chartView}
          compareEnabled={compareEnabled}
          comparisonSeries={comparisonSeries}
          effectiveCompareSymbol={effectiveCompareSymbol}
          newsEvents={newsEvents}
          performanceSeries={performanceSeries}
          priorPeriodEnabled={priorPeriodEnabled}
          priorPerformanceSeries={priorPerformanceSeries}
          symbol={symbol}
          volumeProfileBins={volumeProfileBins}
        />
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
        <p>
          {liveData.status === "fallback" && liveData.error
            ? `Live market data unavailable: ${liveData.error}. Simulated bars remain active.`
            : "Run the analyst team from the cockpit to populate a decision, trace, and approval-gated paper order."}
        </p>
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

async function fetchMarketSnapshot(
  symbol: string,
  range: MarketRange,
  signal: AbortSignal
): Promise<MarketDataSnapshot> {
  const response = await fetch(`/api/market-data?symbol=${encodeURIComponent(symbol)}&range=${range}`, {
    signal
  });

  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { error?: string } | null;
    throw new Error(payload?.error ?? `Market data request failed: ${response.status}`);
  }

  return response.json() as Promise<MarketDataSnapshot>;
}
