"use client";

import { useState } from "react";

import { AgentCockpit } from "@/components/AgentCockpit";
import { ChartWorkspace } from "@/components/ChartWorkspace";
import { WatchlistRail } from "@/components/WatchlistRail";
import { WATCHLIST } from "@/data/watchlist";

export function MarketShell() {
  const [selectedSymbol, setSelectedSymbol] = useState(WATCHLIST[0].symbol);

  return (
    <main className="market-shell">
      <WatchlistRail items={WATCHLIST} selectedSymbol={selectedSymbol} onSelect={setSelectedSymbol} />
      <ChartWorkspace symbol={selectedSymbol} />
      <AgentCockpit symbol={selectedSymbol} />
    </main>
  );
}
