"use client";

import { useState, type FormEvent } from "react";

import type { WatchlistItem } from "@/lib/types";
import { normalizeWatchlistSymbol } from "@/lib/watchlist";

export function WatchlistRail({
  items,
  selectedSymbol,
  collapsed = false,
  onSelect,
  onAddSymbol,
  onRemoveSymbol
}: {
  items: WatchlistItem[];
  selectedSymbol: string;
  collapsed?: boolean;
  onSelect: (symbol: string) => void;
  onAddSymbol: (symbol: string) => void;
  onRemoveSymbol: (symbol: string) => void;
}) {
  const [draftSymbol, setDraftSymbol] = useState("");

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const symbol = normalizeWatchlistSymbol(draftSymbol);

    if (!symbol) {
      return;
    }

    onAddSymbol(symbol);
    setDraftSymbol("");
  }

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
          <div className={item.symbol === selectedSymbol ? "watchlist-item selected" : "watchlist-item"} key={item.symbol}>
            {collapsed ? (
              <button
                className="watchlist-select-button compact"
                onClick={() => onSelect(item.symbol)}
                type="button"
                title={`${item.symbol} ${item.name}`}
              >
                <span className="watchlist-compact-symbol">{item.symbol}</span>
              </button>
            ) : (
              <>
                <button className="watchlist-select-button" onClick={() => onSelect(item.symbol)} type="button">
                  <span className="watchlist-symbol">
                    <strong>{item.symbol}</strong>
                    <small>{item.name}</small>
                  </span>
                  <span className="watchlist-quote">
                    <span>{item.price === null ? "--" : item.price.toFixed(2)}</span>
                    {item.changePercent === null ? (
                      <span>Awaiting quote</span>
                    ) : (
                      <span className={item.changePercent >= 0 ? "positive" : "negative"}>
                        {item.changePercent >= 0 ? "+" : ""}
                        {item.changePercent.toFixed(2)}%
                      </span>
                    )}
                  </span>
                </button>
                <button
                  aria-label={`Remove ${item.symbol}`}
                  className="watchlist-remove-button"
                  onClick={() => onRemoveSymbol(item.symbol)}
                  type="button"
                >
                  ×
                </button>
              </>
            )}
          </div>
        ))}
      </div>
      <section className="rail-micro-panel">
        <span>Universe</span>
        <strong>Large cap signal scan</strong>
      </section>
      {!collapsed ? (
        <form className="watchlist-add-form" onSubmit={handleSubmit}>
          <label htmlFor="watchlist-symbol-input">Add symbol</label>
          <div>
            <input
              id="watchlist-symbol-input"
              onChange={(event) => setDraftSymbol(event.target.value)}
              placeholder="TSLA"
              spellCheck={false}
              value={draftSymbol}
            />
            <button type="submit">Add</button>
          </div>
        </form>
      ) : null}
    </aside>
  );
}
