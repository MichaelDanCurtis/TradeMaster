export type MarketProviderId =
  | "alpaca"
  | "databento"
  | "etrade"
  | "ibkr"
  | "massive"
  | "plaid"
  | "simulated"
  | "tradier"
  | "webull";

export type MarketProviderRole = "brokerage" | "market-data" | "portfolio";

export type MarketProviderCapability =
  | "account-positions"
  | "delayed-bars"
  | "historical-bars"
  | "live-quotes"
  | "paper-trading"
  | "portfolio-holdings"
  | "real-time-bars"
  | "tick-history"
  | "trade-execution"
  | "trade-stream";

export type MarketInterval = "1s" | "5s" | "10s" | "1m" | "5m" | "15m" | "1h" | "1d";
export type MarketRange = "1M" | "YTD" | "1Y" | "3Y" | "5Y" | "10Y";

export type MarketFeed = "boats" | "iex" | "otc" | "sandbox" | "sip" | "simulated";

export type MarketProviderDescriptor = {
  id: MarketProviderId;
  name: string;
  roles: MarketProviderRole[];
  capabilities: MarketProviderCapability[];
  status: "available" | "planned";
  primaryUse: string;
};

export type NormalizedMarketBar = {
  symbol: string;
  provider: MarketProviderId;
  feed: MarketFeed | string;
  interval: MarketInterval;
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  tradeCount?: number;
  vwap?: number;
};

export type VolumeProfileBin = {
  priceStart: number;
  priceEnd: number;
  priceMid: number;
  volume: number;
  volumeShare: number;
};

export type PerformancePoint = {
  timestamp: string;
  value: number;
};

export type ComparisonPoint = {
  timestamp: string;
  subject: number;
  benchmark: number;
};

export type PerformanceSpread = {
  subjectReturn: number;
  benchmarkReturn: number;
  relativeSpread: number;
};

export type NormalizedQuote = {
  symbol: string;
  provider: MarketProviderId;
  feed: MarketFeed | string;
  timestamp: string;
  last: number;
  bid: number;
  ask: number;
  dayOpen: number;
  dayHigh: number;
  dayLow: number;
  dayVolume: number;
};

export type MarketDataSnapshot = {
  symbol: string;
  provider: MarketProviderId;
  feed: MarketFeed | string;
  interval: MarketInterval;
  generatedAt: string;
  bars: NormalizedMarketBar[];
  quote: NormalizedQuote;
};

export type AlpacaBarPayload = {
  S?: string;
  c: number;
  h: number;
  l: number;
  n?: number;
  o: number;
  t: string;
  v: number;
  vw?: number;
};

type SymbolProfile = {
  basePrice: number;
  drift: number;
  volatility: number;
  volumeBase: number;
};

const PROVIDER_CATALOG: Record<MarketProviderId, MarketProviderDescriptor> = {
  alpaca: {
    id: "alpaca",
    name: "Alpaca",
    roles: ["market-data", "brokerage"],
    capabilities: ["historical-bars", "real-time-bars", "live-quotes", "paper-trading", "trade-execution"],
    status: "planned",
    primaryUse: "First paper broker and first live market-data adapter."
  },
  databento: {
    id: "databento",
    name: "Databento",
    roles: ["market-data"],
    capabilities: ["historical-bars", "live-quotes", "tick-history", "trade-stream"],
    status: "planned",
    primaryUse: "Institutional historical and tick-level data for backtesting and microstructure work."
  },
  etrade: {
    id: "etrade",
    name: "E*TRADE",
    roles: ["brokerage", "market-data"],
    capabilities: ["account-positions", "live-quotes", "trade-execution"],
    status: "planned",
    primaryUse: "Future broker/account adapter after the Alpaca paper workflow is stable."
  },
  ibkr: {
    id: "ibkr",
    name: "Interactive Brokers",
    roles: ["brokerage", "market-data"],
    capabilities: ["historical-bars", "live-quotes", "real-time-bars", "trade-execution"],
    status: "planned",
    primaryUse: "Future advanced broker adapter for broader asset coverage."
  },
  massive: {
    id: "massive",
    name: "Massive",
    roles: ["market-data"],
    capabilities: ["historical-bars", "real-time-bars", "live-quotes", "trade-stream"],
    status: "planned",
    primaryUse: "Dedicated market-data adapter for richer charts and non-broker data coverage."
  },
  plaid: {
    id: "plaid",
    name: "Plaid Investments",
    roles: ["portfolio"],
    capabilities: ["account-positions", "portfolio-holdings"],
    status: "planned",
    primaryUse: "Portfolio, holdings, securities, and transaction context rather than candle charts."
  },
  simulated: {
    id: "simulated",
    name: "Simulated Feed",
    roles: ["market-data"],
    capabilities: ["delayed-bars", "historical-bars", "live-quotes"],
    status: "available",
    primaryUse: "Deterministic local market data for UI, demos, and tests."
  },
  tradier: {
    id: "tradier",
    name: "Tradier",
    roles: ["brokerage", "market-data"],
    capabilities: ["delayed-bars", "live-quotes", "paper-trading", "trade-execution"],
    status: "planned",
    primaryUse: "Future broker adapter with sandbox support, especially if options workflows expand."
  },
  webull: {
    id: "webull",
    name: "Webull OpenAPI",
    roles: ["market-data", "brokerage"],
    capabilities: ["historical-bars", "live-quotes", "real-time-bars", "trade-execution"],
    status: "planned",
    primaryUse: "Primary trading surface integration path: market data first, account/order automation later behind approvals."
  }
};

const SYMBOL_PROFILES: Record<string, SymbolProfile> = {
  AAPL: { basePrice: 190.44, drift: -0.003, volatility: 0.74, volumeBase: 146000 },
  MSFT: { basePrice: 420.09, drift: 0.009, volatility: 1.04, volumeBase: 98000 },
  NVDA: { basePrice: 900.12, drift: 0.018, volatility: 2.35, volumeBase: 212000 },
  SPY: { basePrice: 520.16, drift: 0.004, volatility: 0.86, volumeBase: 310000 }
};

const INTERVAL_CONFIG: Record<MarketInterval, { count: number; minutes: number }> = {
  "1s": { count: 240, minutes: 1 / 60 },
  "5s": { count: 240, minutes: 5 / 60 },
  "10s": { count: 240, minutes: 10 / 60 },
  "1m": { count: 180, minutes: 1 },
  "5m": { count: 156, minutes: 5 },
  "15m": { count: 104, minutes: 15 },
  "1h": { count: 96, minutes: 60 },
  "1d": { count: 160, minutes: 390 }
};

const RANGE_CONFIG: Record<MarketRange, { count: number; label: string }> = {
  "1M": { count: 22, label: "1 month" },
  "YTD": { count: 86, label: "year to date" },
  "1Y": { count: 252, label: "1 year" },
  "3Y": { count: 756, label: "3 years" },
  "5Y": { count: 1260, label: "5 years" },
  "10Y": { count: 2520, label: "10 years" }
};

const SIMULATED_SESSION_END = Date.UTC(2026, 4, 1, 20, 0, 0);

export function getMarketProviderCatalog(): Record<MarketProviderId, MarketProviderDescriptor> {
  return PROVIDER_CATALOG;
}

export function normalizeAlpacaBar(
  payload: AlpacaBarPayload,
  interval: MarketInterval,
  feed: MarketFeed | string,
  fallbackSymbol = "UNKNOWN"
): NormalizedMarketBar {
  return {
    close: payload.c,
    feed,
    high: payload.h,
    interval,
    low: payload.l,
    open: payload.o,
    provider: "alpaca",
    symbol: payload.S ?? fallbackSymbol,
    timestamp: new Date(payload.t).toISOString(),
    tradeCount: payload.n,
    volume: payload.v,
    vwap: payload.vw
  };
}

export function createSimulatedMarketSnapshot(symbol: string, interval: MarketInterval): MarketDataSnapshot {
  const bars = createSimulatedBars(symbol, interval);
  const lastBar = bars[bars.length - 1];
  const dayOpen = bars[0].open;
  const dayHigh = Math.max(...bars.map((bar) => bar.high));
  const dayLow = Math.min(...bars.map((bar) => bar.low));
  const dayVolume = bars.reduce((sum, bar) => sum + bar.volume, 0);
  const spread = Math.max(lastBar.close * 0.00018, 0.01);

  return {
    bars,
    feed: "simulated",
    generatedAt: lastBar.timestamp,
    interval,
    provider: "simulated",
    quote: {
      ask: roundPrice(lastBar.close + spread),
      bid: roundPrice(lastBar.close - spread),
      dayHigh: roundPrice(dayHigh),
      dayLow: roundPrice(dayLow),
      dayOpen: roundPrice(dayOpen),
      dayVolume,
      feed: "simulated",
      last: lastBar.close,
      provider: "simulated",
      symbol,
      timestamp: lastBar.timestamp
    },
    symbol
  };
}

export function createSimulatedHistoricalSnapshot(symbol: string, range: MarketRange): MarketDataSnapshot {
  const bars = createSimulatedHistoricalBars(symbol, range, 0);
  const lastBar = bars[bars.length - 1];
  const dayOpen = bars[0].open;
  const dayHigh = Math.max(...bars.map((bar) => bar.high));
  const dayLow = Math.min(...bars.map((bar) => bar.low));
  const dayVolume = bars.reduce((sum, bar) => sum + bar.volume, 0);
  const spread = Math.max(lastBar.close * 0.00018, 0.01);

  return {
    bars,
    feed: "simulated",
    generatedAt: lastBar.timestamp,
    interval: "1d",
    provider: "simulated",
    quote: {
      ask: roundPrice(lastBar.close + spread),
      bid: roundPrice(lastBar.close - spread),
      dayHigh: roundPrice(dayHigh),
      dayLow: roundPrice(dayLow),
      dayOpen: roundPrice(dayOpen),
      dayVolume,
      feed: "simulated",
      last: lastBar.close,
      provider: "simulated",
      symbol,
      timestamp: lastBar.timestamp
    },
    symbol
  };
}

export function createPriorPeriodBars(symbol: string, range: MarketRange): NormalizedMarketBar[] {
  return createSimulatedHistoricalBars(symbol, range, 1);
}

export function normalizePerformanceSeries(sourceBars: NormalizedMarketBar[]): PerformancePoint[] {
  const firstClose = sourceBars[0]?.close || 1;

  return sourceBars.map((bar) => ({
    timestamp: bar.timestamp,
    value: roundPercent(((bar.close - firstClose) / firstClose) * 100)
  }));
}

export function createComparisonSeries(
  subjectBars: NormalizedMarketBar[],
  benchmarkBars: NormalizedMarketBar[]
): ComparisonPoint[] {
  const subjectPerformance = normalizePerformanceSeries(subjectBars);
  const benchmarkPerformance = normalizePerformanceSeries(benchmarkBars);
  const pointCount = Math.min(subjectPerformance.length, benchmarkPerformance.length);

  return Array.from({ length: pointCount }, (_, index) => ({
    benchmark: benchmarkPerformance[index].value,
    subject: subjectPerformance[index].value,
    timestamp: subjectPerformance[index].timestamp
  }));
}

export function calculatePerformanceSpread(comparison: ComparisonPoint[]): PerformanceSpread {
  const lastPoint = comparison.at(-1) ?? { benchmark: 0, subject: 0 };

  return {
    benchmarkReturn: roundPercent(lastPoint.benchmark),
    relativeSpread: roundPercent(lastPoint.subject - lastPoint.benchmark),
    subjectReturn: roundPercent(lastPoint.subject)
  };
}

export function createHeikinAshiBars(sourceBars: NormalizedMarketBar[]): NormalizedMarketBar[] {
  let previousHeikinAshiOpen: number | null = null;
  let previousHeikinAshiClose: number | null = null;

  return sourceBars.map((bar) => {
    const heikinAshiClose = roundPrice((bar.open + bar.high + bar.low + bar.close) / 4);
    const heikinAshiOpen = roundPrice(
      previousHeikinAshiOpen === null || previousHeikinAshiClose === null
        ? (bar.open + bar.close) / 2
        : (previousHeikinAshiOpen + previousHeikinAshiClose) / 2
    );
    const heikinAshiHigh = roundPrice(Math.max(bar.high, heikinAshiOpen, heikinAshiClose));
    const heikinAshiLow = roundPrice(Math.min(bar.low, heikinAshiOpen, heikinAshiClose));

    previousHeikinAshiOpen = heikinAshiOpen;
    previousHeikinAshiClose = heikinAshiClose;

    return {
      ...bar,
      close: heikinAshiClose,
      high: heikinAshiHigh,
      low: heikinAshiLow,
      open: heikinAshiOpen,
      vwap: bar.vwap === undefined ? undefined : roundPrice(bar.vwap)
    };
  });
}

export function createVolumeProfileBins(sourceBars: NormalizedMarketBar[], binCount: number): VolumeProfileBin[] {
  const safeBinCount = Math.max(1, Math.floor(binCount));
  const minPrice = Math.min(...sourceBars.map((bar) => bar.low));
  const maxPrice = Math.max(...sourceBars.map((bar) => bar.high));
  const priceRange = maxPrice - minPrice || 1;
  const binSize = priceRange / safeBinCount;
  const bins = Array.from({ length: safeBinCount }, (_, index) => {
    const priceStart = minPrice + index * binSize;
    const priceEnd = index === safeBinCount - 1 ? maxPrice : priceStart + binSize;

    return {
      priceEnd,
      priceMid: priceStart + (priceEnd - priceStart) / 2,
      priceStart,
      volume: 0,
      volumeShare: 0
    };
  });

  sourceBars.forEach((bar) => {
    const barRange = bar.high - bar.low;

    if (barRange <= 0) {
      const target = bins.find((bin) => bar.close >= bin.priceStart && bar.close <= bin.priceEnd) ?? bins[0];
      target.volume += bar.volume;
      return;
    }

    bins.forEach((bin) => {
      const overlapStart = Math.max(bar.low, bin.priceStart);
      const overlapEnd = Math.min(bar.high, bin.priceEnd);
      const overlap = Math.max(0, overlapEnd - overlapStart);

      if (overlap > 0) {
        bin.volume += bar.volume * (overlap / barRange);
      }
    });
  });

  const maxVolume = Math.max(...bins.map((bin) => bin.volume), 1);

  return bins.map((bin) => ({
    priceEnd: roundPrice(bin.priceEnd),
    priceMid: roundPrice(bin.priceMid),
    priceStart: roundPrice(bin.priceStart),
    volume: Math.round(bin.volume),
    volumeShare: Number((bin.volume / maxVolume).toFixed(4))
  }));
}

function createSimulatedHistoricalBars(symbol: string, range: MarketRange, priorYearOffset: number): NormalizedMarketBar[] {
  const profile = SYMBOL_PROFILES[symbol] ?? makeProfile(symbol);
  const config = RANGE_CONFIG[range];
  const seed = hashSymbol(`${symbol}:${range}:${priorYearOffset}`);
  const bars: NormalizedMarketBar[] = [];
  const trendBoost = symbol === "SPY" ? 0.014 : 0.022 + pseudoRandom(seed) * 0.026;
  const endTime = Date.UTC(2026 - priorYearOffset, 4, 1, 20, 0, 0);
  let previousClose = profile.basePrice * (1 - trendBoost * Math.log10(config.count + 10));

  for (let index = 0; index < config.count; index += 1) {
    const trend = trendBoost * (index / Math.max(config.count - 1, 1));
    const longWave = Math.sin((index + seed) / 31) * profile.volatility * 0.42;
    const mediumWave = Math.cos((index + seed) / 11) * profile.volatility * 0.22;
    const noise = (pseudoRandom(seed + index * 19) - 0.5) * profile.volatility * 0.7;
    const open = previousClose;
    const close = Math.max(1, open + trend + longWave * 0.48 + mediumWave * 0.36 + noise * 0.56);
    const wick = profile.volatility * (0.07 + pseudoRandom(seed + index * 29) * 0.16);
    const high = Math.max(open, close) + wick;
    const low = Math.max(0.01, Math.min(open, close) - wick);
    const timestamp = new Date(endTime - (config.count - 1 - index) * 86_400_000);
    const volumePulse = 0.74 + Math.abs(Math.sin((index + seed) / 21)) * 0.82;
    const volume = Math.round(profile.volumeBase * volumePulse * 210);

    bars.push({
      close: roundPrice(close),
      feed: "simulated",
      high: roundPrice(high),
      interval: "1d",
      low: roundPrice(low),
      open: roundPrice(open),
      provider: "simulated",
      symbol,
      timestamp: timestamp.toISOString(),
      tradeCount: Math.round(volume / 180),
      volume,
      vwap: roundPrice((open + high + low + close * 2) / 5)
    });

    previousClose = close;
  }

  return bars;
}

function createSimulatedBars(symbol: string, interval: MarketInterval): NormalizedMarketBar[] {
  const profile = SYMBOL_PROFILES[symbol] ?? makeProfile(symbol);
  const config = INTERVAL_CONFIG[interval];
  const seed = hashSymbol(`${symbol}:${interval}`);
  const bars: NormalizedMarketBar[] = [];
  let previousClose = profile.basePrice - config.count * profile.drift * 0.32;

  for (let index = 0; index < config.count; index += 1) {
    const wave = Math.sin((index + seed) / 9) * profile.volatility;
    const fastWave = Math.cos((index + seed) / 4.7) * profile.volatility * 0.38;
    const microMove = (pseudoRandom(seed + index * 17) - 0.5) * profile.volatility * 0.8;
    const open = previousClose;
    const close = Math.max(1, open + profile.drift + (wave + fastWave + microMove) * 0.18);
    const wick = profile.volatility * (0.35 + pseudoRandom(seed + index * 31) * 0.75);
    const high = Math.max(open, close) + wick;
    const low = Math.max(0.01, Math.min(open, close) - wick * (0.72 + pseudoRandom(seed + index * 43) * 0.38));
    const volumePulse = 0.58 + Math.abs(Math.sin((index + seed) / 13)) * 0.95;
    const volume = Math.round(profile.volumeBase * volumePulse * intervalVolumeMultiplier(interval));
    const tradeCount = Math.max(1, Math.round(volume / (92 + pseudoRandom(seed + index * 5) * 220)));
    const vwap = (open + high + low + close * 2) / 5;
    const timestamp = new Date(SIMULATED_SESSION_END - (config.count - 1 - index) * config.minutes * 60_000);

    bars.push({
      close: roundPrice(close),
      feed: "simulated",
      high: roundPrice(high),
      interval,
      low: roundPrice(low),
      open: roundPrice(open),
      provider: "simulated",
      symbol,
      timestamp: timestamp.toISOString(),
      tradeCount,
      volume,
      vwap: roundPrice(vwap)
    });

    previousClose = close;
  }

  return bars;
}

function intervalVolumeMultiplier(interval: MarketInterval): number {
  switch (interval) {
    case "1s":
      return 0.035;
    case "5s":
      return 0.09;
    case "10s":
      return 0.14;
    case "5m":
      return 3.8;
    case "15m":
      return 9.5;
    case "1h":
      return 32;
    case "1d":
      return 210;
    default:
      return 1;
  }
}

function makeProfile(symbol: string): SymbolProfile {
  const seed = hashSymbol(symbol);
  const basePrice = 80 + (seed % 700);

  return {
    basePrice,
    drift: (pseudoRandom(seed) - 0.48) * 0.04,
    volatility: 0.6 + pseudoRandom(seed + 7) * 2.8,
    volumeBase: 70000 + (seed % 180000)
  };
}

function hashSymbol(value: string): number {
  let hash = 0;

  for (let index = 0; index < value.length; index += 1) {
    hash = (hash * 31 + value.charCodeAt(index)) >>> 0;
  }

  return hash;
}

function pseudoRandom(seed: number): number {
  const value = Math.sin(seed * 12.9898) * 43758.5453;

  return value - Math.floor(value);
}

function roundPrice(value: number): number {
  return Number(value.toFixed(2));
}

function roundPercent(value: number): number {
  return Number(value.toFixed(2));
}
