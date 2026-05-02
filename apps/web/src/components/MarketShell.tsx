"use client";

import { useState } from "react";

import { AgentCockpit } from "@/components/AgentCockpit";
import { ChartWorkspace } from "@/components/ChartWorkspace";
import { WatchlistRail } from "@/components/WatchlistRail";
import { WATCHLIST } from "@/data/watchlist";

export function MarketShell() {
  const [selectedSymbol, setSelectedSymbol] = useState(WATCHLIST[0].symbol);

  return (
    <main className="terminal-shell">
      <header className="terminal-topbar">
        <div className="brand-lockup">
          <span className="brand-mark">TA</span>
          <div>
            <strong>TradingAgents</strong>
            <span>Operator Terminal</span>
          </div>
        </div>
        <div className="topbar-status">
          <span className="status-pill online">API online</span>
          <span className="status-pill paper">Paper mode</span>
          <span className="session-clock">Local research session</span>
        </div>
      </header>
      <div className="market-shell">
        <WatchlistRail items={WATCHLIST} selectedSymbol={selectedSymbol} onSelect={setSelectedSymbol} />
        <ChartWorkspace symbol={selectedSymbol} />
        <AgentCockpit symbol={selectedSymbol} />
      </div>
    </main>
  );
}
