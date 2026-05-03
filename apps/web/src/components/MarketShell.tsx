"use client";

import { useEffect, useState } from "react";

import { DashboardWorkspace } from "@/components/DashboardWorkspace";
import { SettingsDrawer } from "@/components/SettingsDrawer";
import { ToastStack } from "@/components/ToastStack";
import { WatchlistRail } from "@/components/WatchlistRail";
import { WorkspaceNav } from "@/components/WorkspaceNav";
import { WATCHLIST } from "@/data/watchlist";
import { getInitialNotifications, type TerminalNotification, type WorkspaceId } from "@/lib/workspace-data";
import { dismissNotification, selectSymbol, setWorkspace, toggleSettings, type WorkspaceShellState } from "@/lib/workspace-state";

const WORKSPACE_PLACEHOLDERS: Record<Exclude<WorkspaceId, "dashboard">, { eyebrow: string; title: string; body: string }> = {
  agents: {
    eyebrow: "Agent messaging",
    title: "Agents workspace",
    body: "The persistent watchlist and selected symbol are ready; the messenger console will replace this placeholder."
  },
  historicals: {
    eyebrow: "Prediction review",
    title: "Historicals workspace",
    body: "Historical outcomes and feedback loops will land here without changing the shell navigation contract."
  },
  research: {
    eyebrow: "Deep Research",
    title: "Deep Research workspace",
    body: "Run controls, report lists, and decision ledgers will move into this workspace in a later task."
  },
  transactions: {
    eyebrow: "Paper execution",
    title: "Transactions workspace",
    body: "Portfolio, balances, approvals, and paper ticket controls will replace this placeholder."
  }
};

export function MarketShell() {
  const [shellState, setShellState] = useState<WorkspaceShellState>({
    activeWorkspace: "dashboard",
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

  const placeholder = WORKSPACE_PLACEHOLDERS[activeWorkspace];

  return (
    <section className="workspace-placeholder" aria-label={`${placeholder.title} placeholder`}>
      <span className="panel-kicker">{placeholder.eyebrow}</span>
      <h1>{placeholder.title}</h1>
      <p>{placeholder.body}</p>
      <dl>
        <div>
          <dt>Selected symbol</dt>
          <dd>{selectedSymbol}</dd>
        </div>
        <div>
          <dt>Workspace</dt>
          <dd>{activeWorkspace}</dd>
        </div>
      </dl>
    </section>
  );
}
