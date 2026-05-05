import {
  createSimulatedHistoricalSnapshot,
  type MarketDataSnapshot,
  type MarketFeed,
  type MarketInterval,
  type MarketRange,
  type NormalizedMarketBar
} from "./market-data.ts";
import type { MarketTickerItem } from "./workspace-data.ts";

export type BackendFetch = (input: string | URL, init?: RequestInit) => Promise<Response>;

type BackendBar = {
  close: number;
  high: number;
  low: number;
  open: number;
  symbol: string;
  timestamp: string;
  trade_count?: number | null;
  volume: number;
  vwap?: number | null;
};

type BackendQuote = {
  ask_price: number;
  ask_size: number;
  bid_price: number;
  bid_size: number;
  symbol: string;
  timestamp: string;
};

type ProviderBackedOptions = {
  apiBase?: string;
  feed?: string;
  fetcher?: BackendFetch;
  providerId?: string;
};

const DEFAULT_API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8787";
const DEFAULT_PROVIDER_ID = "alpaca-market-data";
const DEFAULT_FEED = "iex";

const RANGE_REQUESTS: Record<
  MarketRange,
  {
    interval: MarketInterval;
    limit: number;
    lookbackMs: number;
    timeframe: "1Min" | "5Min" | "15Min" | "1Hour" | "1Day";
  }
> = {
  "1D": { interval: "1m", limit: 390, lookbackMs: 24 * 60 * 60_000, timeframe: "1Min" },
  "5D": { interval: "15m", limit: 130, lookbackMs: 5 * 24 * 60 * 60_000, timeframe: "15Min" },
  "1M": { interval: "1d", limit: 22, lookbackMs: 31 * 24 * 60 * 60_000, timeframe: "1Day" },
  "YTD": { interval: "1d", limit: 220, lookbackMs: 365 * 24 * 60 * 60_000, timeframe: "1Day" },
  "1Y": { interval: "1d", limit: 252, lookbackMs: 365 * 24 * 60 * 60_000, timeframe: "1Day" },
  "3Y": { interval: "1d", limit: 756, lookbackMs: 3 * 365 * 24 * 60 * 60_000, timeframe: "1Day" },
  "5Y": { interval: "1d", limit: 1260, lookbackMs: 5 * 365 * 24 * 60 * 60_000, timeframe: "1Day" },
  "10Y": { interval: "1d", limit: 2520, lookbackMs: 10 * 365 * 24 * 60 * 60_000, timeframe: "1Day" }
};

export async function fetchProviderBackedMarketSnapshot(
  symbol: string,
  range: MarketRange,
  options: ProviderBackedOptions = {}
): Promise<MarketDataSnapshot> {
  const normalizedSymbol = normalizeSymbol(symbol);
  const requestConfig = RANGE_REQUESTS[range];
  const fetcher = options.fetcher ?? fetch;
  const feed = options.feed ?? DEFAULT_FEED;
  const apiBase = options.apiBase ?? DEFAULT_API_BASE;
  const providerId = options.providerId ?? DEFAULT_PROVIDER_ID;
  const end = new Date();
  const start = new Date(end.getTime() - requestConfig.lookbackMs);

  try {
    const barsUrl = buildBackendUrl(apiBase, `/api/market-data/${providerId}/bars`, {
      end: end.toISOString(),
      feed,
      limit: String(requestConfig.limit),
      start: start.toISOString(),
      symbol: normalizedSymbol,
      timeframe: requestConfig.timeframe
    });
    const quoteUrl = buildBackendUrl(apiBase, `/api/market-data/${providerId}/quote`, {
      feed,
      symbol: normalizedSymbol
    });
    const [barsResponse, quoteResponse] = await Promise.all([fetcher(barsUrl), fetcher(quoteUrl)]);

    if (!barsResponse.ok || !quoteResponse.ok) {
      return createSimulatedHistoricalSnapshot(normalizedSymbol, range);
    }

    const barsPayload = (await barsResponse.json()) as { bars?: BackendBar[] };
    const quotePayload = (await quoteResponse.json()) as { quote?: BackendQuote };
    const backendBars = barsPayload.bars ?? [];
    const backendQuote = quotePayload.quote;

    if (backendBars.length === 0 || backendQuote === undefined) {
      return createSimulatedHistoricalSnapshot(normalizedSymbol, range);
    }

    return normalizeBackendSnapshot(backendBars, backendQuote, requestConfig.interval, feed);
  } catch {
    return createSimulatedHistoricalSnapshot(normalizedSymbol, range);
  }
}

export function createTickerItemsFromSnapshots(
  snapshots: MarketDataSnapshot[],
  labelBySymbol: Record<string, string> = {}
): MarketTickerItem[] {
  return snapshots.map((snapshot) => {
    const firstBar = snapshot.bars[0];
    const lastBar = snapshot.bars.at(-1) ?? firstBar;
    const open = firstBar?.open ?? snapshot.quote.dayOpen;
    const last = snapshot.quote.last;
    const change = roundMetric(last - open);
    const changePercent = open === 0 ? 0 : roundMetric((change / open) * 100);

    return {
      change,
      changePercent,
      id: snapshot.symbol.toLowerCase(),
      label: labelBySymbol[snapshot.symbol] ?? snapshot.symbol,
      sparkline: snapshot.bars.slice(-12).map((bar) => bar.close),
      value: lastBar?.close ?? last
    };
  });
}

function normalizeBackendSnapshot(
  backendBars: BackendBar[],
  backendQuote: BackendQuote,
  interval: MarketInterval,
  feed: string
): MarketDataSnapshot {
  const bars = backendBars.map((bar) => normalizeBackendBar(bar, interval, feed));
  const firstBar = bars[0];
  const lastBar = bars.at(-1) ?? firstBar;
  const dayHigh = Math.max(...bars.map((bar) => bar.high));
  const dayLow = Math.min(...bars.map((bar) => bar.low));
  const dayVolume = bars.reduce((sum, bar) => sum + bar.volume, 0);

  return {
    bars,
    feed,
    generatedAt: new Date(backendQuote.timestamp).toISOString(),
    interval,
    provider: "alpaca",
    quote: {
      ask: backendQuote.ask_price,
      bid: backendQuote.bid_price,
      dayHigh,
      dayLow,
      dayOpen: firstBar.open,
      dayVolume,
      feed,
      last: lastBar.close,
      provider: "alpaca",
      symbol: backendQuote.symbol.toUpperCase(),
      timestamp: new Date(backendQuote.timestamp).toISOString()
    },
    symbol: backendQuote.symbol.toUpperCase()
  };
}

function normalizeBackendBar(bar: BackendBar, interval: MarketInterval, feed: string): NormalizedMarketBar {
  return {
    close: bar.close,
    feed: feed as MarketFeed,
    high: bar.high,
    interval,
    low: bar.low,
    open: bar.open,
    provider: "alpaca",
    symbol: bar.symbol.toUpperCase(),
    timestamp: new Date(bar.timestamp).toISOString(),
    tradeCount: bar.trade_count ?? undefined,
    volume: bar.volume,
    vwap: bar.vwap ?? undefined
  };
}

function buildBackendUrl(apiBase: string, pathname: string, params: Record<string, string>): URL {
  const url = new URL(pathname, apiBase);

  Object.entries(params).forEach(([key, value]) => {
    url.searchParams.set(key, value);
  });

  return url;
}

function normalizeSymbol(symbol: string): string {
  return symbol.trim().toUpperCase();
}

function roundMetric(value: number): number {
  return Number(value.toFixed(3));
}
