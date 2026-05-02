export type MarketProviderId =
  | "alpaca"
  | "databento"
  | "etrade"
  | "ibkr"
  | "massive"
  | "plaid"
  | "simulated"
  | "tradier";

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
