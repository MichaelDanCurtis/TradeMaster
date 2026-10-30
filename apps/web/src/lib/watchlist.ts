import type { WatchlistItem } from "./types.ts";
import type { MarketTickerItem } from "./workspace-data.ts";

const SYMBOL_PATTERN = /^[A-Z0-9.-]{1,12}$/;
export const WATCHLIST_STORAGE_KEY = "trademaster.watchlist.v1";

export function normalizeWatchlistSymbol(input: string): string | null {
  const symbol = input.trim().toUpperCase();

  if (!symbol || !SYMBOL_PATTERN.test(symbol)) {
    return null;
  }

  return symbol;
}

export function addWatchlistItem(items: WatchlistItem[], input: string): WatchlistItem[] {
  const symbol = normalizeWatchlistSymbol(input);

  if (!symbol || items.some((item) => item.symbol.toUpperCase() === symbol)) {
    return items;
  }

  return [
    ...items,
    {
      changePercent: null,
      name: symbol,
      price: null,
      symbol
    }
  ];
}

export function removeWatchlistItem(items: WatchlistItem[], input: string): WatchlistItem[] {
  const symbol = normalizeWatchlistSymbol(input);

  if (!symbol || !items.some((item) => item.symbol.toUpperCase() === symbol)) {
    return items;
  }

  return items.filter((item) => item.symbol.toUpperCase() !== symbol);
}

export function buildWatchlistTickerUrl(items: WatchlistItem[]): string {
  const symbols = Array.from(
    new Set(
      items
        .map((item) => normalizeWatchlistSymbol(item.symbol))
        .filter((symbol): symbol is string => symbol !== null)
    )
  );

  return `/api/market-data/ticker?symbols=${encodeURIComponent(symbols.join(","))}`;
}

export function hydrateWatchlistItems(baseItems: WatchlistItem[], tickerItems: MarketTickerItem[]): WatchlistItem[] {
  const tickerBySymbol = new Map(tickerItems.map((item) => [item.id.toUpperCase(), item]));

  return baseItems.map((item) => {
    const tickerItem = tickerBySymbol.get(item.symbol);

    if (!tickerItem) {
      return item;
    }

    return {
      ...item,
      changePercent: tickerItem.changePercent,
      name: tickerItem.label || item.name,
      price: tickerItem.value
    };
  });
}

export function loadPersistedWatchlistItems(
  storage: Pick<Storage, "getItem"> | undefined,
  fallbackItems: WatchlistItem[]
): WatchlistItem[] {
  if (!storage) {
    return fallbackItems;
  }

  try {
    const rawValue = storage.getItem(WATCHLIST_STORAGE_KEY);
    if (!rawValue) {
      return fallbackItems;
    }

    const parsed = JSON.parse(rawValue) as unknown;
    if (!Array.isArray(parsed)) {
      return fallbackItems;
    }

    const items = parsed
      .map((item) => normalizePersistedWatchlistItem(item))
      .filter((item): item is WatchlistItem => item !== null);

    return items.length > 0 ? items : fallbackItems;
  } catch {
    return fallbackItems;
  }
}

export function persistWatchlistItems(
  storage: Pick<Storage, "setItem"> | undefined,
  items: WatchlistItem[]
): void {
  if (!storage) {
    return;
  }

  storage.setItem(WATCHLIST_STORAGE_KEY, JSON.stringify(items));
}

function normalizePersistedWatchlistItem(value: unknown): WatchlistItem | null {
  if (typeof value !== "object" || value === null) {
    return null;
  }

  const candidate = value as Record<string, unknown>;
  const symbol = typeof candidate.symbol === "string" ? normalizeWatchlistSymbol(candidate.symbol) : null;
  if (!symbol) {
    return null;
  }

  return {
    changePercent: typeof candidate.changePercent === "number" ? candidate.changePercent : null,
    name: typeof candidate.name === "string" && candidate.name.trim() ? candidate.name : symbol,
    price: typeof candidate.price === "number" ? candidate.price : null,
    symbol
  };
}
