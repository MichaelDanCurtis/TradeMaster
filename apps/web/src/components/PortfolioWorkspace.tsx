"use client";

/**
 * PortfolioWorkspace — root container for the Portfolio tab.
 *
 * "Where you are today": current holdings, value, performance. Routes to one of
 * three internal sub-views (Overview / Positions / Performance) that delegate
 * to existing workspace components.
 */

import { useState } from "react";

import { BriefWorkspace } from "@/components/BriefWorkspace";
import { PerformanceWorkspace } from "@/components/PerformanceWorkspace";
import { PositionsWorkspace } from "@/components/PositionsWorkspace";
import type { WatchlistItem } from "@/lib/types";

type PortfolioSubView = "overview" | "positions" | "performance";

const SUB_VIEWS: { id: PortfolioSubView; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "positions", label: "Positions" },
  { id: "performance", label: "Performance" }
];

export function PortfolioWorkspace({
  symbol,
  watchlistItems,
  onAddToWatchlist,
  onApproveIdea,
  onOpenResearch,
  onOpenStrategyResearch,
  onOpenQuant,
  onOpenResearchSymbol,
  onOpenSymbolDetail
}: {
  symbol: string;
  watchlistItems: WatchlistItem[];
  /**
   * Adds a symbol to the watchlist (MarketShell's watchlist state). Threaded
   * to the Morning Scan panel's "+ watch" buttons on discovered ideas.
   */
  onAddToWatchlist?: (symbol: string) => void;
  /**
   * Approve a Morning Scan idea — MarketShell wires this to open the Quant
   * tab with the trade (symbol + side) pre-filled. Pass-through only.
   */
  onApproveIdea?: (symbol: string, side: "buy" | "sell") => void;
  onOpenResearch: () => void;
  onOpenStrategyResearch?: () => void;
  onOpenQuant?: () => void;
  /**
   * Opens Research pinned to a specific symbol. Pass-through to the Morning
   * Scan panel's per-idea Research buttons; falls back to onOpenResearch.
   */
  onOpenResearchSymbol?: (symbol: string) => void;
  /** Opens the SymbolDetailDrawer; threaded down to row/card clicks. */
  onOpenSymbolDetail?: (symbol: string) => void;
}) {
  const [subView, setSubView] = useState<PortfolioSubView>("overview");

  return (
    <section className="portfolio-workspace-root" aria-label="Portfolio workspace">
      <nav className="portfolio-subview-nav" role="tablist" aria-label="Portfolio sub-views">
        {SUB_VIEWS.map((view) => (
          <button
            aria-current={view.id === subView ? "page" : undefined}
            aria-selected={view.id === subView}
            className={view.id === subView ? "portfolio-subview-tab active" : "portfolio-subview-tab"}
            key={view.id}
            onClick={() => setSubView(view.id)}
            role="tab"
            type="button"
          >
            {view.label}
          </button>
        ))}
      </nav>
      <div className="portfolio-subview-content">
        {subView === "overview" ? (
          <BriefWorkspace
            symbol={symbol}
            watchlistItems={watchlistItems}
            onAddToWatchlist={onAddToWatchlist}
            onApproveIdea={onApproveIdea}
            onOpenResearch={onOpenResearch}
            onOpenStrategyResearch={onOpenStrategyResearch}
            onOpenQuant={onOpenQuant}
            onOpenPerformance={() => setSubView("performance")}
            onOpenResearchSymbol={onOpenResearchSymbol}
            onOpenSymbolDetail={onOpenSymbolDetail}
          />
        ) : null}
        {subView === "positions" ? (
          <PositionsWorkspace symbol={symbol} onOpenSymbolDetail={onOpenSymbolDetail} />
        ) : null}
        {subView === "performance" ? <PerformanceWorkspace symbol={symbol} /> : null}
      </div>
    </section>
  );
}
