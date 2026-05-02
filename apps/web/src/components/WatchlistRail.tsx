"use client";

import { ProviderPanel } from "@/components/ProviderPanel";
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
      <header className="panel-header">
        <div>
          <span className="panel-kicker">Markets</span>
          <h2>Watchlist</h2>
        </div>
        <span className="panel-count">{items.length}</span>
      </header>
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
      <section className="rail-micro-panel">
        <span>Universe</span>
        <strong>Large cap signal scan</strong>
      </section>
      <ProviderPanel />
    </aside>
  );
}
