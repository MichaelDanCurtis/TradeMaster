"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { CommandPalette } from "@/components/CommandPalette";
import { PortfolioStrip } from "@/components/PortfolioStrip";
import { PortfolioWorkspace } from "@/components/PortfolioWorkspace";
import type { PendingQuantIntent } from "@/components/QuantWorkbench";
import type { StrategyReviewSelection } from "@/lib/deployments";
import { QuantWorkspace } from "@/components/QuantWorkspace";
import { ResearchWorkspace } from "@/components/ResearchWorkspace";
import { SettingsWorkspace } from "@/components/SettingsDrawer";
import { SymbolDetailDrawer } from "@/components/SymbolDetailDrawer";
import { TabNav } from "@/components/TabNav";
import { ToastStack } from "@/components/ToastStack";
import { WatchStatusStrip } from "@/components/WatchStatusStrip";
import { WatchlistRail } from "@/components/WatchlistRail";
import { WelcomeCallout } from "@/components/WelcomeCallout";
import { WATCHLIST } from "@/data/watchlist";
import { WatcherEndpointMissingError, listWatcherFires } from "@/lib/api";
import type { WatcherFire, WatchlistItem } from "@/lib/types";
import {
  addWatchlistItem,
  hydrateWatchlistItems,
  loadPersistedWatchlistItems,
  persistWatchlistItems,
  removeWatchlistItem
} from "@/lib/watchlist";
import type { MarketTickerItem, TerminalNotification, WorkspaceId } from "@/lib/workspace-data";
import {
  dismissNotification,
  selectSymbol,
  setWorkspace,
  visibleNotifications,
  type WorkspaceShellState
} from "@/lib/workspace-state";

export function MarketShell() {
  const [shellState, setShellState] = useState<WorkspaceShellState>({
    activeWorkspace: "portfolio",
    selectedSymbol: WATCHLIST[0].symbol
  });
  const [watchlistItems, setWatchlistItems] = useState<WatchlistItem[]>(WATCHLIST);
  const [hasLoadedPersistedWatchlist, setHasLoadedPersistedWatchlist] = useState(false);
  const [notifications, setNotifications] = useState<TerminalNotification[]>([]);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [dateLabel,setDateLabel]=useState("");
  useEffect(()=>{
    const update=()=>setDateLabel(new Date().toLocaleDateString("en-US",{weekday:"short",month:"short",day:"numeric"}));
    update();const timer=window.setInterval(update,30_000);
    return ()=>window.clearInterval(timer);
  },[]);
  // Watcher-fire poller bookkeeping. `since` tracks the most recent fire
  // we've toasted so we never duplicate; the ref lets the interval callback
  // read the latest value without retriggering the effect on every fire.
  const lastFireSeenRef = useRef<string | null>(null);
  const seenFireIdsRef = useRef<Set<string>>(new Set());
  // Universal "tell me about this ticker" drawer — opens from any ticker click
  // (watchlist row, holdings card, mover chip, agent row, news item, palette).
  // Null = hidden. Setting this also nudges the global symbol context so
  // Research/Quant follow the drawer's focus.
  const [detailSymbol, setDetailSymbol] = useState<string | null>(null);
  // Research→execution handoff. Set whenever the user approves an idea
  // (drawer Buy/Sell, Morning Scan approve); QuantWorkbench applies it once
  // (side + Simple Mode market ticket) and consumes it back to null.
  const [pendingQuantIntent, setPendingQuantIntent] = useState<PendingQuantIntent | null>(null);
  const [strategyReview,setStrategyReview] = useState<StrategyReviewSelection | null>(null);
  const [researchView, setResearchView] = useState<"explorer" | "symbol" | "strategies">("explorer");
  const watchlistSymbolKey = useMemo(
    () => watchlistItems.map((item) => item.symbol.toUpperCase()).join(","),
    [watchlistItems]
  );

  useEffect(() => {
    setWatchlistItems(loadPersistedWatchlistItems(window.localStorage, WATCHLIST));
    setHasLoadedPersistedWatchlist(true);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const tickerUrl = `/api/market-data/ticker?symbols=${encodeURIComponent(watchlistSymbolKey)}`;

    fetch(tickerUrl, { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(`Watchlist quote request failed: ${response.status}`);
        }

        return (await response.json()) as { items?: MarketTickerItem[] };
      })
      .then((payload) => {
        const tickerItems = payload.items;
        if (tickerItems && tickerItems.length > 0) {
          setWatchlistItems((currentItems) => hydrateWatchlistItems(currentItems, tickerItems));
        }
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          console.warn("Watchlist quote provider unavailable", error);
        }
      });

    return () => {
      controller.abort();
    };
  }, [watchlistSymbolKey]);

  useEffect(() => {
    if (!hasLoadedPersistedWatchlist) {
      return;
    }

    persistWatchlistItems(window.localStorage, watchlistItems);
  }, [hasLoadedPersistedWatchlist, watchlistItems]);

  // Watcher-fire poller — every 30s ask the backend for recent fires and
  // surface any unseen ones as toasts. Silent failure when the backend is
  // not up yet so the rest of the shell stays clean.
  useEffect(() => {
    let isCurrent = true;

    // Historical fires remain in storage; opening the desk should not replay an hour of alerts.
    lastFireSeenRef.current ??= new Date().toISOString();

    async function pollWatcherFires() {
      try {
        const since = lastFireSeenRef.current ?? new Date().toISOString();
        const catalog = await listWatcherFires({ since, limit: 20 });
        if (!isCurrent) return;
        const fresh = catalog.fires.filter((fire: WatcherFire) => !seenFireIdsRef.current.has(fire.fire_id));
        if (fresh.length === 0) return;

        fresh.forEach((fire) => {
          seenFireIdsRef.current.add(fire.fire_id);
          const firedAt = fire.fired_at;
          if (!lastFireSeenRef.current || firedAt > lastFireSeenRef.current) {
            lastFireSeenRef.current = firedAt;
          }
        });

        const incoming: TerminalNotification[] = fresh.map((fire) => ({
          id: `watcher-fire-${fire.fire_id}`,
          severity: "warning",
          title: `${fire.symbol} watcher fired`,
          body: `${fire.symbol} ${describeCondition(fire.condition_type, fire.threshold)} (observed ${fmtObserved(fire.condition_type, fire.observed_value)}) ${describeAge(fire.fired_at)}`,
          linkedWorkspace: "portfolio",
          linkedEntityId: fire.watcher_id,
          ttl: 30_000
        }));

        setNotifications((current) => {
          const existing = new Set(current.map((entry) => entry.id));
          const additions = incoming.filter((entry) => !existing.has(entry.id));
          return additions.length === 0 ? current : [...additions, ...current].slice(0, 4);
        });
      } catch (caught) {
        if (caught instanceof WatcherEndpointMissingError) {
          // Backend not up yet — stay quiet so the boot UX isn't noisy.
          return;
        }
        // Other errors are non-fatal; surface to console only.
        console.warn("Watcher-fire poll failed", caught);
      }
    }

    void pollWatcherFires();
    const id = window.setInterval(() => {
      void pollWatcherFires();
    }, 30_000);

    return () => {
      isCurrent = false;
      window.clearInterval(id);
    };
  }, []);

  // -------------------------------------------------------------------------
  // Global keyboard shortcuts (Cmd/Ctrl+K for the palette, Cmd/Ctrl+1..4 for
  // tabs, Esc to close the palette). Number / palette shortcuts are silenced
  // whenever the user is typing into an input or textarea so we never steal
  // keystrokes from the watchlist add box or the trade ticket.
  // -------------------------------------------------------------------------
  useEffect(() => {
    function isTypingInForm(): boolean {
      const active = document.activeElement;
      if (!active) return false;
      const tag = active.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
      if (active instanceof HTMLElement && active.isContentEditable) return true;
      return false;
    }

    function onKey(event: KeyboardEvent) {
      const accelerator = event.metaKey || event.ctrlKey;

      if (accelerator && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen((current) => !current);
        return;
      }

      if (event.key === "Escape" && paletteOpen) {
        event.preventDefault();
        setPaletteOpen(false);
        return;
      }

      if (!accelerator) return;
      if (isTypingInForm()) return;

      const shortcutMap: Record<string, WorkspaceId> = {
        "1": "portfolio",
        "2": "research",
        "3": "quant",
        "4": "settings"
      };
      const tab = shortcutMap[event.key];
      if (tab) {
        event.preventDefault();
        setShellState((currentState) => setWorkspace(currentState, tab));
      }
    }

    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [paletteOpen]);

  function handleSelectTab(tab: WorkspaceId) {
    setShellState((currentState) => setWorkspace(currentState, tab));
  }

  /**
   * Universal entry point for the SymbolDetailDrawer. Opens the drawer AND
   * updates the global symbol context so Research/Quant follow when the user
   * subsequently switches tabs (or clicks the drawer's own "open research" /
   * "manage in Quant" affordances).
   *
   * Called from: WatchlistRail row, BriefHoldings/Movers/Agents/Trades clicks,
   * PositionsWorkspace card clicks, CommandPalette symbol picks.
   */
  function handleOpenSymbolDetail(symbol: string) {
    setDetailSymbol(symbol);
    setShellState((currentState) => selectSymbol(currentState, symbol));
  }

  function handleCloseSymbolDetail() {
    setDetailSymbol(null);
  }

  function handleOpenResearchFromDrawer(symbol: string) {
    setResearchView("symbol");
    setShellState((currentState) =>
      setWorkspace(selectSymbol(currentState, symbol), "research")
    );
    setDetailSymbol(null);
  }

  function handleOpenQuantWithIntent(input: { symbol: string; side: "buy" | "sell" }) {
    // Approve→execution-floor handoff: switch to Quant, pin the symbol, and
    // queue the side as a pending intent. QuantWorkbench applies it once
    // (Simple Mode market ticket + side control) and then consumes it.
    // Fresh object per approval — QuantWorkbench keys application on identity.
    setPendingQuantIntent({ symbol: input.symbol.toUpperCase(), side: input.side });
    setShellState((currentState) =>
      setWorkspace(selectSymbol(currentState, input.symbol), "quant")
    );
    setDetailSymbol(null);
  }

  // Stable consume callback so QuantWorkbench's apply-effect doesn't churn.
  const handleConsumePendingQuantIntent = useCallback(() => {
    setPendingQuantIntent(null);
  }, []);

  function handleAddWatchlistSymbol(symbol: string) {
    setWatchlistItems((currentItems) => {
      const nextItems = addWatchlistItem(currentItems, symbol);
      const addedItem = nextItems.length > currentItems.length ? nextItems.at(-1) : null;

      if (addedItem) {
        setShellState((currentState) => selectSymbol(currentState, addedItem.symbol));
      }

      return nextItems;
    });
  }

  function handleRemoveWatchlistSymbol(symbol: string) {
    setWatchlistItems((currentItems) => {
      const nextItems = removeWatchlistItem(currentItems, symbol);

      if (nextItems === currentItems || nextItems.length === 0) {
        return currentItems;
      }

      if (shellState.selectedSymbol.toUpperCase() === symbol.toUpperCase()) {
        setShellState((currentState) => selectSymbol(currentState, nextItems[0].symbol));
      }

      return nextItems;
    });
  }

  // Command palette handlers. `onResearchSymbol` switches to Research and
  // pins the symbol; `onTradeSymbol` does the same for Quant. The drawer
  // handoff (`onOpenSymbolDetail`) is intentionally omitted here — a parallel
  // agent owns SymbolDetailDrawer; the palette falls back to research-on-symbol
  // when the prop is absent.
  function handlePaletteResearchSymbol(symbol: string) {
    setResearchView("symbol");
    setShellState((currentState) =>
      setWorkspace(selectSymbol(currentState, symbol), "research")
    );
  }

  function handlePaletteTradeSymbol(input: { symbol: string; side: "buy" | "sell" }) {
    setShellState((currentState) =>
      setWorkspace(selectSymbol(currentState, input.symbol), "quant")
    );
  }

  const activeTab = shellState.activeWorkspace;
  const isSettings = activeTab === "settings";

  return (
    <main className={isSettings ? "terminal-shell terminal-shell-settings" : "terminal-shell"}>
      <header className="terminal-topbar">
        <div className="brand-lockup">
          <span className="brand-mark">TM<span className="brand-mark-dot" aria-hidden="true">.</span></span>
          <div>
            <strong>TradeMaster</strong>
            <span>Personal Desk</span>
          </div>
        </div>
        <div className="topbar-status">
          <span
            className="status-pill online"
            title="The TradeMaster API process running locally. Stop it from your terminal to disconnect."
          >
            Local server
          </span>
          <span
            className="status-pill paper"
            title="Paper mode = simulated trades against Alpaca's paper account. No real money is moved. Every order also requires explicit approval."
          >
            Paper mode · approval gated
          </span>
          <span className="session-clock">
            {dateLabel}
          </span>
        </div>
      </header>
      <TabNav activeTab={activeTab} onSelectTab={handleSelectTab} />
      {isSettings ? null : <WatchStatusStrip onSelectSymbol={handleOpenSymbolDetail} />}
      {isSettings ? null : <PortfolioStrip />}
      <div className={isSettings ? "market-shell market-shell-full" : "market-shell"}>
        {isSettings ? null : (
          <WatchlistRail
            items={watchlistItems}
            selectedSymbol={shellState.selectedSymbol}
            onAddSymbol={handleAddWatchlistSymbol}
            onRemoveSymbol={handleRemoveWatchlistSymbol}
            onSelect={handleOpenSymbolDetail}
          />
        )}
        <div className="workspace-main-stack">
          <TabContent
            activeTab={activeTab}
            pendingQuantIntent={pendingQuantIntent}
            strategyReview={strategyReview}
            researchView={researchView}
            onOpenStrategyResearch={() => { setResearchView("strategies"); handleSelectTab("research"); }}
            onRequestStrategyReview={(selection)=>{setStrategyReview(selection);handleSelectTab("quant");}}
            selectedSymbol={shellState.selectedSymbol}
            watchlistItems={watchlistItems}
            onAddToWatchlist={handleAddWatchlistSymbol}
            onApproveIdea={(symbol, side) => handleOpenQuantWithIntent({ symbol, side })}
            onConsumePendingQuantIntent={handleConsumePendingQuantIntent}
            onOpenQuant={() => handleSelectTab("quant")}
            onOpenResearch={() => { setResearchView("symbol"); handleSelectTab("research"); }}
            onOpenResearchSymbol={handlePaletteResearchSymbol}
            onOpenSymbolDetail={handleOpenSymbolDetail}
          />
        </div>
      </div>
      <ToastStack
        notifications={visibleNotifications(shellState, notifications)}
        onDismiss={(notificationId) =>
          setNotifications((currentNotifications) => dismissNotification(currentNotifications, notificationId))
        }
      />
      <CommandPalette
        isOpen={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        onOpenSymbolDetail={handleOpenSymbolDetail}
        onResearchSymbol={handlePaletteResearchSymbol}
        onSelectTab={handleSelectTab}
        onTradeSymbol={handlePaletteTradeSymbol}
        watchlistItems={watchlistItems}
      />
      <SymbolDetailDrawer
        symbol={detailSymbol}
        onClose={handleCloseSymbolDetail}
        onOpenQuantWithIntent={handleOpenQuantWithIntent}
        onOpenResearch={handleOpenResearchFromDrawer}
      />
    </main>
  );
}

function TabContent({
  activeTab,
  pendingQuantIntent,
  strategyReview,
  researchView,
  onOpenStrategyResearch,
  onRequestStrategyReview,
  selectedSymbol,
  watchlistItems,
  onAddToWatchlist,
  onApproveIdea,
  onConsumePendingQuantIntent,
  onOpenQuant,
  onOpenResearch,
  onOpenResearchSymbol,
  onOpenSymbolDetail
}: {
  activeTab: WorkspaceId;
  pendingQuantIntent: PendingQuantIntent | null;
  strategyReview: StrategyReviewSelection | null;
  researchView: "explorer" | "symbol" | "strategies";
  onOpenStrategyResearch: () => void;
  onRequestStrategyReview: (selection: StrategyReviewSelection) => void;
  selectedSymbol: string;
  watchlistItems: WatchlistItem[];
  /** Adds a symbol to the watchlist (Morning Scan "+ watch" on discovered ideas). */
  onAddToWatchlist?: (symbol: string) => void;
  /** Approve a research idea — opens Quant with the trade pre-filled. */
  onApproveIdea: (symbol: string, side: "buy" | "sell") => void;
  onConsumePendingQuantIntent: () => void;
  onOpenQuant: () => void;
  onOpenResearch: () => void;
  /** Opens Research pinned to a specific symbol (Morning Scan "Research"). */
  onOpenResearchSymbol: (symbol: string) => void;
  onOpenSymbolDetail: (symbol: string) => void;
}) {
  if (activeTab === "portfolio") {
    return (
      <>
        <WelcomeCallout watchlistItems={watchlistItems} />
        <PortfolioWorkspace
          symbol={selectedSymbol}
          watchlistItems={watchlistItems}
          onAddToWatchlist={onAddToWatchlist}
          onApproveIdea={onApproveIdea}
          onOpenResearch={onOpenResearch}
          onOpenStrategyResearch={onOpenStrategyResearch}
          onOpenQuant={onOpenQuant}
          onOpenResearchSymbol={onOpenResearchSymbol}
          onOpenSymbolDetail={onOpenSymbolDetail}
        />
      </>
    );
  }
  if (activeTab === "research") {
    return <ResearchWorkspace symbol={selectedSymbol} onOpenQuant={onOpenQuant} initialView={researchView} onRequestStrategyReview={onRequestStrategyReview} watchlistItems={watchlistItems} onAddToWatchlist={onAddToWatchlist} onResearchSymbol={onOpenResearchSymbol} />;
  }
  if (activeTab === "quant") {
    return (
      <QuantWorkspace
        symbol={selectedSymbol}
        pendingIntent={pendingQuantIntent}
        strategyReview={strategyReview}
        onConsumePendingIntent={onConsumePendingQuantIntent}
      />
    );
  }

  return <SettingsWorkspace />;
}

// -----------------------------------------------------------------------------
// Watcher-fire toast helpers
// -----------------------------------------------------------------------------

function describeCondition(condition: WatcherFire["condition_type"], threshold: number): string {
  switch (condition) {
    case "price_above":
      return `is above $${threshold.toFixed(2)}`;
    case "price_below":
      return `is below $${threshold.toFixed(2)}`;
    case "change_pct_above":
      return `day Δ% rose above ${threshold.toFixed(2)}%`;
    case "change_pct_below":
      return `day Δ% fell below ${threshold.toFixed(2)}%`;
    case "volume_above":
      return `volume rose above ${threshold.toLocaleString("en-US")}`;
    default:
      return `crossed ${threshold}`;
  }
}

function fmtObserved(condition: WatcherFire["condition_type"], value: number): string {
  if (condition === "change_pct_above" || condition === "change_pct_below") {
    return `${value.toFixed(2)}%`;
  }
  if (condition === "volume_above") {
    return value.toLocaleString("en-US");
  }
  return `$${value.toFixed(2)}`;
}

function describeAge(iso: string): string {
  const firedAt = new Date(iso).getTime();
  if (Number.isNaN(firedAt)) return "moments ago";
  const seconds = Math.max(1, Math.floor((Date.now() - firedAt) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ago`;
}
