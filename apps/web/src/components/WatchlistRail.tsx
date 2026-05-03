"use client";

import type { WatchlistItem } from "@/lib/types";

export function WatchlistRail({
  items,
  selectedSymbol,
  collapsed = false,
  onSelect
}: {
  items: WatchlistItem[];
  selectedSymbol: string;
  collapsed?: boolean;
  onSelect: (symbol: string) => void;
}) {
  return (
    <aside className={collapsed ? "watchlist-rail collapsed" : "watchlist-rail"} aria-label="Watchlist">
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
            title={collapsed ? `${item.symbol} ${item.name}` : undefined}
          >
            {collapsed ? (
              <span className="watchlist-compact-symbol">{item.symbol}</span>
            ) : (
              <>
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
              </>
            )}
          </button>
        ))}
      </div>
      <section className="rail-micro-panel">
        <span>Universe</span>
        <strong>Large cap signal scan</strong>
      </section>
    </aside>
  );
}
