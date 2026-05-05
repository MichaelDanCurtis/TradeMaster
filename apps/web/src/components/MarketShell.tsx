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
import type { WatchlistItem } from "@/lib/types";
import { getInitialNotifications, type MarketTickerItem, type TerminalNotification, type WorkspaceId } from "@/lib/workspace-data";
import {
  dismissNotification,
  selectSymbol,
  setWorkspace,
  toggleSettings,
  visibleNotifications,
  type WorkspaceShellState
} from "@/lib/workspace-state";

export function MarketShell() {
  const [shellState, setShellState] = useState<WorkspaceShellState>({
    activeWorkspace: "agents",
    selectedSymbol: WATCHLIST[0].symbol,
    settingsOpen: false
  });
  const [watchlistItems, setWatchlistItems] = useState<WatchlistItem[]>(() => WATCHLIST);
  const [notifications, setNotifications] = useState<TerminalNotification[]>(() =>
    getInitialNotifications(WATCHLIST[0].symbol)
  );

  useEffect(() => {
    const controller = new AbortController();

    fetch("/api/market-data/ticker", { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(`Watchlist quote request failed: ${response.status}`);
        }

        return (await response.json()) as { items?: MarketTickerItem[] };
      })
      .then((payload) => {
        if (payload.items && payload.items.length > 0) {
          setWatchlistItems(hydrateWatchlistItems(WATCHLIST, payload.items));
        }
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          console.warn("Watchlist quote provider fallback active", error);
        }
      });

    return () => {
      controller.abort();
    };
  }, []);

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
          <span className="brand-mark">WA</span>
          <div>
            <strong>Wealth Agents</strong>
            <span>Private Office</span>
          </div>
        </div>
        <div className="topbar-status">
          <span className="status-pill online">Local server</span>
          <span className="status-pill paper">Approval gated</span>
          <span className="session-clock">MacBook private office</span>
        </div>
      </header>
      <MarketTicker />
      <WorkspaceNav
        activeWorkspace={shellState.activeWorkspace}
        settingsOpen={shellState.settingsOpen}
        onSelectWorkspace={handleSelectWorkspace}
        onToggleSettings={handleToggleSettings}
      />
      <div className={shellState.activeWorkspace === "research" ? "market-shell watchlist-collapsed" : "market-shell"}>
        <WatchlistRail
          collapsed={shellState.activeWorkspace === "research"}
          items={watchlistItems}
          selectedSymbol={shellState.selectedSymbol}
          onSelect={handleSelectSymbol}
        />
        <WorkspaceContent activeWorkspace={shellState.activeWorkspace} selectedSymbol={shellState.selectedSymbol} />
      </div>
      <SettingsDrawer open={shellState.settingsOpen} onClose={handleCloseSettings} />
      <ToastStack
        notifications={visibleNotifications(shellState, notifications)}
        onDismiss={(notificationId) =>
          setNotifications((currentNotifications) => dismissNotification(currentNotifications, notificationId))
        }
      />
    </main>
  );
}

function hydrateWatchlistItems(baseItems: WatchlistItem[], tickerItems: MarketTickerItem[]): WatchlistItem[] {
  const tickerBySymbol = new Map(tickerItems.map((item) => [item.id.toUpperCase(), item]));

  return baseItems.map((item) => {
    const tickerItem = tickerBySymbol.get(item.symbol);

    if (!tickerItem) {
      return item;
    }

    return {
      ...item,
      changePercent: tickerItem.changePercent,
      price: tickerItem.value
    };
  });
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
