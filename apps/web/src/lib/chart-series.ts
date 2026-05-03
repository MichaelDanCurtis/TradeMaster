import type {
  BarData,
  CandlestickData,
  HistogramData,
  LineData,
  SeriesMarker,
  UTCTimestamp
} from "lightweight-charts";

import type { ComparisonPoint, NormalizedMarketBar, PerformancePoint } from "./market-data.ts";
import type { NewsEvent } from "./workspace-data.ts";

export const CHART_UP_COLOR = "#33d17a";
export const CHART_DOWN_COLOR = "#ff6b6b";
export const CHART_NEUTRAL_COLOR = "#e7c75f";
export const VOLUME_UP_COLOR = "rgba(51, 209, 122, 0.32)";
export const VOLUME_DOWN_COLOR = "rgba(255, 107, 107, 0.3)";

export function toCandlestickSeriesData(bars: NormalizedMarketBar[]): CandlestickData<UTCTimestamp>[] {
  return sortBarsByTime(bars).map((bar) => ({
    close: bar.close,
    color: bar.close >= bar.open ? CHART_UP_COLOR : CHART_DOWN_COLOR,
    high: bar.high,
    low: bar.low,
    open: bar.open,
    time: toChartTime(bar.timestamp),
    wickColor: bar.close >= bar.open ? CHART_UP_COLOR : CHART_DOWN_COLOR
  }));
}

export function toHollowCandlestickSeriesData(bars: NormalizedMarketBar[]): CandlestickData<UTCTimestamp>[] {
  return sortBarsByTime(bars).map((bar) => {
    const isUp = bar.close >= bar.open;
    const color = isUp ? CHART_UP_COLOR : CHART_DOWN_COLOR;

    return {
      borderColor: color,
      close: bar.close,
      color: isUp ? "rgba(51, 209, 122, 0.08)" : CHART_DOWN_COLOR,
      high: bar.high,
      low: bar.low,
      open: bar.open,
      time: toChartTime(bar.timestamp),
      wickColor: color
    };
  });
}

export function toBarSeriesData(bars: NormalizedMarketBar[]): BarData<UTCTimestamp>[] {
  return sortBarsByTime(bars).map((bar) => ({
    close: bar.close,
    high: bar.high,
    low: bar.low,
    open: bar.open,
    time: toChartTime(bar.timestamp)
  }));
}

export function toLineSeriesData(bars: NormalizedMarketBar[]): LineData<UTCTimestamp>[] {
  return sortBarsByTime(bars).map((bar) => ({
    time: toChartTime(bar.timestamp),
    value: bar.close
  }));
}

export function toVwapLineData(bars: NormalizedMarketBar[]): LineData<UTCTimestamp>[] {
  return sortBarsByTime(bars).map((bar) => ({
    time: toChartTime(bar.timestamp),
    value: bar.vwap ?? bar.close
  }));
}

export function toPerformanceLineData(points: PerformancePoint[]): LineData<UTCTimestamp>[] {
  return sortPointsByTime(points).map((point) => ({
    time: toChartTime(point.timestamp),
    value: point.value
  }));
}

export function toComparisonLineData(
  points: ComparisonPoint[],
  key: "benchmark" | "subject"
): LineData<UTCTimestamp>[] {
  return sortPointsByTime(points).map((point) => ({
    time: toChartTime(point.timestamp),
    value: point[key]
  }));
}

export function toVolumeHistogramData(bars: NormalizedMarketBar[]): HistogramData<UTCTimestamp>[] {
  return sortBarsByTime(bars).map((bar) => ({
    color: bar.close >= bar.open ? VOLUME_UP_COLOR : VOLUME_DOWN_COLOR,
    time: toChartTime(bar.timestamp),
    value: bar.volume
  }));
}

export function toNewsSeriesMarkers(
  newsEvents: NewsEvent[],
  bars: NormalizedMarketBar[],
  maxMarkers = 20
): SeriesMarker<UTCTimestamp>[] {
  const sortedBars = sortBarsByTime(bars);

  if (sortedBars.length === 0) {
    return [];
  }

  return newsEvents.slice(0, maxMarkers).map((event) => {
    const closestBar = getClosestBar(event.timestamp, sortedBars);
    const color = getSentimentColor(event.sentiment);

    return {
      color,
      id: event.id,
      position: "inBar",
      price: roundPrice(closestBar.high * 1.01),
      shape: "circle",
      size: 1.25,
      text: event.markerLabel,
      time: toChartTime(closestBar.timestamp)
    };
  });
}

export function toChartTime(timestamp: string): UTCTimestamp {
  return Math.floor(new Date(timestamp).getTime() / 1000) as UTCTimestamp;
}

function sortBarsByTime(bars: NormalizedMarketBar[]): NormalizedMarketBar[] {
  return [...bars].sort((left, right) => new Date(left.timestamp).getTime() - new Date(right.timestamp).getTime());
}

function sortPointsByTime<T extends { timestamp: string }>(points: T[]): T[] {
  return [...points].sort((left, right) => new Date(left.timestamp).getTime() - new Date(right.timestamp).getTime());
}

function getClosestBar(timestamp: string, bars: NormalizedMarketBar[]): NormalizedMarketBar {
  const targetTime = new Date(timestamp).getTime();

  return bars.reduce((closestBar, currentBar) => {
    const closestDistance = Math.abs(new Date(closestBar.timestamp).getTime() - targetTime);
    const currentDistance = Math.abs(new Date(currentBar.timestamp).getTime() - targetTime);

    return currentDistance < closestDistance ? currentBar : closestBar;
  });
}

function getSentimentColor(sentiment: NewsEvent["sentiment"]): string {
  switch (sentiment) {
    case "negative":
      return CHART_DOWN_COLOR;
    case "positive":
      return CHART_UP_COLOR;
    default:
      return CHART_NEUTRAL_COLOR;
  }
}

function roundPrice(value: number): number {
  return Number(value.toFixed(2));
}
