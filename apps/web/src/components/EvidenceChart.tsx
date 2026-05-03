"use client";

import { useEffect, useRef } from "react";
import {
  AreaSeries,
  BarSeries,
  BaselineSeries,
  CandlestickSeries,
  ColorType,
  createChart,
  createSeriesMarkers,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  LineStyle,
  LineType,
  type IChartApi,
  type Time
} from "lightweight-charts";

import {
  CHART_DOWN_COLOR,
  CHART_NEUTRAL_COLOR,
  CHART_UP_COLOR,
  getInitialVisibleLogicalRange,
  toBarSeriesData,
  toCandlestickSeriesData,
  toComparisonLineData,
  toHollowCandlestickSeriesData,
  toLineSeriesData,
  toNewsSeriesMarkers,
  toPerformanceLineData,
  toVolumeHistogramData,
  toVwapLineData
} from "@/lib/chart-series";
import type { ComparisonPoint, MarketRange, NormalizedMarketBar, PerformancePoint, VolumeProfileBin } from "@/lib/market-data";
import type { NewsEvent } from "@/lib/workspace-data";

export type EvidenceChartView =
  | "area"
  | "bars"
  | "baseline"
  | "candles"
  | "heikin-ashi"
  | "hollow-candles"
  | "line"
  | "step-line"
  | "volume-profile";

type EvidenceChartProps = {
  bars: NormalizedMarketBar[];
  chartRange: MarketRange;
  chartView: EvidenceChartView;
  compareEnabled: boolean;
  comparisonSeries: ComparisonPoint[];
  effectiveCompareSymbol: string;
  newsEvents: NewsEvent[];
  performanceSeries: PerformancePoint[];
  priorPeriodEnabled: boolean;
  priorPerformanceSeries: PerformancePoint[];
  symbol: string;
  volumeProfileBins: VolumeProfileBin[];
};

export function EvidenceChart({
  bars,
  chartRange,
  chartView,
  compareEnabled,
  comparisonSeries,
  effectiveCompareSymbol,
  newsEvents,
  performanceSeries,
  priorPeriodEnabled,
  priorPerformanceSeries,
  symbol,
  volumeProfileBins
}: EvidenceChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const performanceMode = compareEnabled || priorPeriodEnabled;

  useEffect(() => {
    const container = containerRef.current;

    if (!container || bars.length === 0) {
      return;
    }

    const chart = createChart(container, {
      autoSize: true,
      crosshair: {
        mode: CrosshairMode.Normal
      },
      grid: {
        horzLines: { color: "rgba(105, 128, 150, 0.2)" },
        vertLines: { color: "rgba(105, 128, 150, 0.16)" }
      },
      handleScale: {
        axisDoubleClickReset: true,
        axisPressedMouseMove: true,
        mouseWheel: true,
        pinch: true
      },
      handleScroll: {
        horzTouchDrag: true,
        mouseWheel: false,
        pressedMouseMove: true,
        vertTouchDrag: true
      },
      layout: {
        attributionLogo: false,
        background: { color: "#0c1219", type: ColorType.Solid },
        fontFamily: "Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
        textColor: "#9fb2c6"
      },
      localization: {
        priceFormatter: (value: number) => (performanceMode ? `${value.toFixed(2)}%` : value.toFixed(2))
      },
      rightPriceScale: {
        borderColor: "rgba(126, 148, 170, 0.32)",
        scaleMargins: performanceMode ? { bottom: 0.12, top: 0.08 } : { bottom: 0.26, top: 0.08 }
      },
      timeScale: {
        barSpacing: chartRange === "1M" ? 22 : 8,
        borderColor: "rgba(126, 148, 170, 0.32)",
        minBarSpacing: 4,
        rightOffset: 8,
        secondsVisible: chartRange === "1M",
        timeVisible: true,
        tickMarkFormatter: (time: Time) => formatTickMark(String(time), chartRange)
      }
    });

    if (performanceMode) {
      renderPerformanceChart(chart, {
        compareEnabled,
        comparisonSeries,
        effectiveCompareSymbol,
        performanceSeries,
        priorPeriodEnabled,
        priorPerformanceSeries,
        symbol
      });
    } else {
      renderPriceChart(chart, {
        bars,
        chartView,
        newsEvents,
        symbol
      });
    }

    chart.timeScale().setVisibleLogicalRange(getInitialVisibleLogicalRange(bars.length, chartRange));

    return () => {
      chart.remove();
    };
  }, [
    bars,
    chartRange,
    chartView,
    compareEnabled,
    comparisonSeries,
    effectiveCompareSymbol,
    newsEvents,
    performanceMode,
    performanceSeries,
    priorPeriodEnabled,
    priorPerformanceSeries,
    symbol
  ]);

  return (
    <div className="evidence-chart-frame">
      <div
        aria-label={`${symbol} ${performanceMode ? "performance comparison" : chartView} chart`}
        className="evidence-chart"
        ref={containerRef}
      />
      {!performanceMode && chartView === "volume-profile" ? <VolumeProfileOverlay bins={volumeProfileBins} /> : null}
      <div className="chart-engine-legend">
        <span>{performanceMode ? "Percent return" : "OHLCV"}</span>
        <span>{performanceMode ? `${symbol}${compareEnabled ? ` vs ${effectiveCompareSymbol}` : ""}` : "VWAP + volume"}</span>
        <span>{Math.min(newsEvents.length, 20)} events</span>
      </div>
    </div>
  );
}

function renderPriceChart(
  chart: IChartApi,
  {
    bars,
    chartView,
    newsEvents,
    symbol
  }: Pick<EvidenceChartProps, "bars" | "chartView" | "newsEvents" | "symbol">
) {
  const priceLineColor = "#4f8cff";

  if (chartView === "bars") {
    const priceSeries = chart.addSeries(BarSeries, {
      downColor: CHART_DOWN_COLOR,
      openVisible: true,
      priceLineColor,
      thinBars: false,
      title: symbol,
      upColor: CHART_UP_COLOR
    });
    priceSeries.setData(toBarSeriesData(bars));
    createSeriesMarkers(priceSeries, toNewsSeriesMarkers(newsEvents, bars), { zOrder: "top" });
  } else if (chartView === "line" || chartView === "step-line") {
    const priceSeries = chart.addSeries(LineSeries, {
      color: priceLineColor,
      lineType: chartView === "step-line" ? LineType.WithSteps : LineType.Simple,
      lineWidth: 2,
      priceLineColor,
      title: symbol
    });
    priceSeries.setData(toLineSeriesData(bars));
    createSeriesMarkers(priceSeries, toNewsSeriesMarkers(newsEvents, bars), { zOrder: "top" });
  } else if (chartView === "area") {
    const priceSeries = chart.addSeries(AreaSeries, {
      bottomColor: "rgba(79, 140, 255, 0.04)",
      lineColor: priceLineColor,
      lineWidth: 2,
      priceLineColor,
      title: symbol,
      topColor: "rgba(79, 140, 255, 0.32)"
    });
    priceSeries.setData(toLineSeriesData(bars));
    createSeriesMarkers(priceSeries, toNewsSeriesMarkers(newsEvents, bars), { zOrder: "top" });
  } else if (chartView === "baseline") {
    const priceSeries = chart.addSeries(BaselineSeries, {
      baseValue: { price: bars[0].open, type: "price" },
      bottomFillColor1: "rgba(255, 107, 107, 0.04)",
      bottomFillColor2: "rgba(255, 107, 107, 0.22)",
      bottomLineColor: CHART_DOWN_COLOR,
      priceLineColor,
      title: symbol,
      topFillColor1: "rgba(51, 209, 122, 0.28)",
      topFillColor2: "rgba(51, 209, 122, 0.04)",
      topLineColor: CHART_UP_COLOR
    });
    priceSeries.setData(toLineSeriesData(bars));
    createSeriesMarkers(priceSeries, toNewsSeriesMarkers(newsEvents, bars), { zOrder: "top" });
  } else {
    const priceSeries = chart.addSeries(CandlestickSeries, {
      borderDownColor: CHART_DOWN_COLOR,
      borderUpColor: CHART_UP_COLOR,
      borderVisible: true,
      downColor: CHART_DOWN_COLOR,
      priceLineColor,
      title: symbol,
      upColor: CHART_UP_COLOR,
      wickVisible: true,
      wickDownColor: CHART_DOWN_COLOR,
      wickUpColor: CHART_UP_COLOR
    });
    priceSeries.setData(chartView === "hollow-candles" ? toHollowCandlestickSeriesData(bars) : toCandlestickSeriesData(bars));
    createSeriesMarkers(priceSeries, toNewsSeriesMarkers(newsEvents, bars), { zOrder: "top" });
  }

  const volumeSeries = chart.addSeries(HistogramSeries, {
    lastValueVisible: false,
    priceFormat: { type: "volume" },
    priceLineVisible: false,
    priceScaleId: "volume",
    title: "Volume"
  });
  volumeSeries.setData(toVolumeHistogramData(bars));
  chart.priceScale("volume").applyOptions({
    borderVisible: false,
    scaleMargins: { bottom: 0, top: 0.82 }
  });

  if (chartView !== "line" && chartView !== "area" && chartView !== "step-line") {
    const vwapSeries = chart.addSeries(LineSeries, {
      color: CHART_NEUTRAL_COLOR,
      lastValueVisible: false,
      lineStyle: LineStyle.Dashed,
      lineWidth: 1,
      priceLineVisible: false,
      title: "VWAP"
    });
    vwapSeries.setData(toVwapLineData(bars));
  }
}

function renderPerformanceChart(
  chart: IChartApi,
  {
    compareEnabled,
    comparisonSeries,
    effectiveCompareSymbol,
    performanceSeries,
    priorPeriodEnabled,
    priorPerformanceSeries,
    symbol
  }: Pick<
    EvidenceChartProps,
    | "compareEnabled"
    | "comparisonSeries"
    | "effectiveCompareSymbol"
    | "performanceSeries"
    | "priorPeriodEnabled"
    | "priorPerformanceSeries"
    | "symbol"
  >
) {
  const subjectSeries = chart.addSeries(LineSeries, {
    color: "#4f8cff",
    lineWidth: 2,
    priceFormat: { minMove: 0.01, precision: 2, type: "price" },
    title: `${symbol} return`
  });
  subjectSeries.setData(toPerformanceLineData(performanceSeries));
  subjectSeries.createPriceLine({
    axisLabelVisible: true,
    color: "rgba(242, 246, 250, 0.34)",
    lineStyle: LineStyle.Dashed,
    lineWidth: 1,
    price: 0,
    title: "0%"
  });

  if (compareEnabled) {
    const benchmarkSeries = chart.addSeries(LineSeries, {
      color: CHART_NEUTRAL_COLOR,
      lineWidth: 2,
      priceFormat: { minMove: 0.01, precision: 2, type: "price" },
      title: `${effectiveCompareSymbol} return`
    });
    benchmarkSeries.setData(toComparisonLineData(comparisonSeries, "benchmark"));
  }

  if (priorPeriodEnabled) {
    const priorSeries = chart.addSeries(LineSeries, {
      color: "#a78bfa",
      lineStyle: LineStyle.Dashed,
      lineWidth: 2,
      priceFormat: { minMove: 0.01, precision: 2, type: "price" },
      title: "Prior period"
    });
    priorSeries.setData(toPerformanceLineData(priorPerformanceSeries));
  }
}

function VolumeProfileOverlay({ bins }: { bins: VolumeProfileBin[] }) {
  return (
    <div aria-hidden="true" className="volume-profile-overlay">
      {bins.map((bin) => (
        <span
          key={`${bin.priceStart}-${bin.priceEnd}`}
          style={{
            width: `${Math.max(7, bin.volumeShare * 100)}%`
          }}
        />
      ))}
    </div>
  );
}

function formatTickMark(time: string, range: MarketRange): string {
  const numericTime = Number(time);
  const date = Number.isFinite(numericTime) ? new Date(numericTime * 1000) : new Date(time);

  if (Number.isNaN(date.getTime())) {
    return "";
  }

  if (range === "1M" || range === "YTD") {
    return date.toLocaleDateString("en-US", { day: "numeric", month: "short" });
  }

  return date.toLocaleDateString("en-US", { month: "short", year: "2-digit" });
}
