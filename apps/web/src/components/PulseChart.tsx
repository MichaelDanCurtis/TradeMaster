"use client";
import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import { apiBase } from "@/lib/api";
import { age, pct, price, tone, volume } from "@/lib/market-pulse";
import type { MarketRange, NormalizedMarketBar } from "@/lib/market-data";
const EvidenceChart = dynamic(
  () =>
    import("@/components/EvidenceChart").then((module) => module.EvidenceChart),
  {
    ssr: false,
    loading: () => <p className="pulse-placeholder">Loading chart…</p>,
  },
);
const EMPTY: never[] = [];
type ChartResult = {
  symbol: string;
  range: string;
  feed: string | null;
  status: string;
  bars: NormalizedMarketBar[];
  as_of: string | null;
  retrieved_at: string;
};
export function PulseChart({ symbol, now }: { symbol: string; now: number }) {
  const [range, setRange] = useState<"1D" | "5D" | "1M" | "1Y">("1M");
  const [style, setStyle] = useState<"candles" | "line">("candles");
  const [result, setResult] = useState<ChartResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    fetch(
      `${apiBase()}/api/market-pulse/chart/${encodeURIComponent(symbol)}?range=${range}`,
      { signal: controller.signal },
    )
      .then(async (response) => {
        if (!response.ok) throw new Error("Chart request failed.");
        return response.json() as Promise<ChartResult>;
      })
      .then((value) => {
        if (!controller.signal.aborted && value.symbol === symbol) {
          setResult(value);
          setLoading(false);
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setError("Chart unavailable. Check the market-data connection.");
          setLoading(false);
        }
      });
    return () => controller.abort();
  }, [symbol, range, revision]);
  const current =
    !loading && !error && result?.symbol === symbol && result.range === range
      ? result
      : null;
  const bars = current?.bars ?? EMPTY;
  const first = bars[0],
    last = bars.at(-1);
  const change = first && last ? (last.close / first.open - 1) * 100 : null;
  return (
    <div className="pulse-chart-tab">
      <div className="pulse-chart-controls">
        <div aria-label="Chart range">
          {(["1D", "5D", "1M", "1Y"] as const).map((value) => (
            <button
              key={value}
              type="button"
              aria-pressed={range === value}
              onClick={() => setRange(value)}
            >
              {value}
            </button>
          ))}
        </div>
        <select
          aria-label="Chart style"
          value={style}
          onChange={(event) =>
            setStyle(event.target.value as "candles" | "line")
          }
        >
          <option value="candles">Candles</option>
          <option value="line">Line</option>
        </select>
        <button
          type="button"
          disabled={loading}
          onClick={() => setRevision((value) => value + 1)}
        >
          Refresh chart
        </button>
      </div>
      <div className="pulse-chart-summary">
        <strong>{price(last?.close)}</strong>
        <span className={tone(change)}>{pct(change)} over shown bars</span>
        <span>
          {current?.feed?.toUpperCase() ?? "—"} · {age(current?.as_of, now)}
        </span>
      </div>
      {loading ? (
        <p className="pulse-chart-empty" role="status">
          Loading {symbol} {range} bars…
        </p>
      ) : error || !bars.length ? (
        <p className="pulse-chart-empty" role="status">
          {error || "No bars available for this security and range."}
        </p>
      ) : (
        <EvidenceChart
          bars={bars}
          chartRange={range as MarketRange}
          chartView={style}
          compareEnabled={false}
          comparisonSeries={EMPTY}
          effectiveCompareSymbol="SPY"
          newsEvents={EMPTY}
          performanceSeries={EMPTY}
          priorPeriodEnabled={false}
          priorPerformanceSeries={EMPTY}
          symbol={symbol}
          volumeProfileBins={EMPTY}
        />
      )}
      {last && (
        <dl className="pulse-metrics">
          <div>
            <dt>Latest bar open</dt>
            <dd>{price(last.open)}</dd>
          </div>
          <div>
            <dt>High / low</dt>
            <dd>
              {price(last.high)} / {price(last.low)}
            </dd>
          </div>
          <div>
            <dt>Latest bar volume</dt>
            <dd>{volume(last.volume)}</dd>
          </div>
          <div>
            <dt>Bars shown</dt>
            <dd>{bars.length}</dd>
          </div>
        </dl>
      )}
      <p className="pulse-footnote">
        Scroll to zoom; drag to pan. Volume is from the configured feed.
        Unadjusted bars can jump at stock splits. 1D shows the latest available
        trading session, which may be a previous day.
      </p>
    </div>
  );
}
