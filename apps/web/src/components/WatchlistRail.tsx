"use client";

import type { WatchlistItem } from "@/lib/types";

export function WatchlistRail({
  items,
  selectedSymbol,
  onSelect
}: {
  items: WatchlistItem[];
  selectedSymbol: string;
  onSelect: (symbol: string) => void;
}) {
  return (
    <aside className="watchlist-rail" aria-label="Watchlist">
      <div className="rail-header">Watchlist</div>
      <div className="watchlist-list">
        {items.map((item) => (
          <button
            className={item.symbol === selectedSymbol ? "watchlist-item selected" : "watchlist-item"}
            key={item.symbol}
            onClick={() => onSelect(item.symbol)}
            type="button"
          >
            <span className="watchlist-symbol">
              <strong>{item.symbol}</strong>
              <small>{item.name}</small>
            </span>
            <span className="watchlist-quote">
              <span>{item.price.toFixed(2)}</span>
              <span className={item.changePercent >= 0 ? "positive" : "negative"}>
                {item.changePercent >= 0 ? "+" : ""}
                {item.changePercent.toFixed(2)}%
              </span>
            </span>
          </button>
        ))}
      </div>
    </aside>
  );
}
