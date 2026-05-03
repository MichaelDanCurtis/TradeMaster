"use client";

import { useEffect, useState } from "react";

import { AgentsWorkspace } from "@/components/AgentsWorkspace";
import { DashboardWorkspace } from "@/components/DashboardWorkspace";
import { DeepResearchWorkspace } from "@/components/DeepResearchWorkspace";
import { HistoricalsWorkspace } from "@/components/HistoricalsWorkspace";
import { MarketTicker } from "@/components/MarketTicker";
import { SettingsDrawer } from "@/components/SettingsDrawer";
import { ToastStack } from "@/components/ToastStack";
import { TransactionsWorkspace } from "@/components/TransactionsWorkspace";
import { WatchlistRail } from "@/components/WatchlistRail";
import { WorkspaceNav } from "@/components/WorkspaceNav";
import { WATCHLIST } from "@/data/watchlist";
import { getInitialNotifications, type TerminalNotification, type WorkspaceId } from "@/lib/workspace-data";
import { dismissNotification, selectSymbol, setWorkspace, toggleSettings, type WorkspaceShellState } from "@/lib/workspace-state";

export function MarketShell() {
  const [shellState, setShellState] = useState<WorkspaceShellState>({
    activeWorkspace: "agents",
    selectedSymbol: WATCHLIST[0].symbol,
    settingsOpen: false
  });
  const [notifications, setNotifications] = useState<TerminalNotification[]>(() =>
    getInitialNotifications(WATCHLIST[0].symbol)
  );

  useEffect(() => {
    setNotifications(getInitialNotifications(shellState.selectedSymbol));
  }, [shellState.selectedSymbol]);

  function handleSelectWorkspace(workspace: WorkspaceId) {
    setShellState((currentState) => setWorkspace(currentState, workspace));
  }

  function handleSelectSymbol(symbol: string) {
    setShellState((currentState) => selectSymbol(currentState, symbol));
  }

  function handleToggleSettings() {
    setShellState((currentState) => toggleSettings(currentState));
  }

  function handleCloseSettings() {
    setShellState((currentState) => ({ ...currentState, settingsOpen: false }));
  }

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
      <MarketTicker />
      <WorkspaceNav
        activeWorkspace={shellState.activeWorkspace}
        settingsOpen={shellState.settingsOpen}
        onSelectWorkspace={handleSelectWorkspace}
        onToggleSettings={handleToggleSettings}
      />
      <div className="market-shell">
        <WatchlistRail items={WATCHLIST} selectedSymbol={shellState.selectedSymbol} onSelect={handleSelectSymbol} />
        <WorkspaceContent activeWorkspace={shellState.activeWorkspace} selectedSymbol={shellState.selectedSymbol} />
      </div>
      <SettingsDrawer open={shellState.settingsOpen} onClose={handleCloseSettings} />
      <ToastStack
        notifications={notifications}
        onDismiss={(notificationId) =>
          setNotifications((currentNotifications) => dismissNotification(currentNotifications, notificationId))
        }
      />
    </main>
  );
}

function WorkspaceContent({
  activeWorkspace,
  selectedSymbol
}: {
  activeWorkspace: WorkspaceId;
  selectedSymbol: string;
}) {
  if (activeWorkspace === "dashboard") {
    return <DashboardWorkspace symbol={selectedSymbol} />;
  }

  if (activeWorkspace === "research") {
    return <DeepResearchWorkspace symbol={selectedSymbol} />;
  }

  if (activeWorkspace === "agents") {
    return <AgentsWorkspace symbol={selectedSymbol} />;
  }

  if (activeWorkspace === "transactions") {
    return <TransactionsWorkspace symbol={selectedSymbol} />;
  }

  return <HistoricalsWorkspace symbol={selectedSymbol} />;
}
