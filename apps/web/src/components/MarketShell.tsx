"use client";

import { useState } from "react";

import { ChartWorkspace } from "@/components/ChartWorkspace";
import { WatchlistRail } from "@/components/WatchlistRail";
import { WATCHLIST } from "@/data/watchlist";

export function MarketShell() {
  const [selectedSymbol, setSelectedSymbol] = useState(WATCHLIST[0].symbol);

  return (
    <main className="market-shell">
      <WatchlistRail items={WATCHLIST} selectedSymbol={selectedSymbol} onSelect={setSelectedSymbol} />
      <ChartWorkspace symbol={selectedSymbol} />
      <aside className="agent-rail">
        <div className="rail-header">Agent cockpit</div>
        <div className="agent-placeholder">
          <span>Status</span>
          <strong>Ready</strong>
        </div>
      </aside>
    </main>
  );
}
