"use client";

/**
 * Brief — Room 1 of the Morning Desk.
 *
 * Dense, calm overview: Holdings (live Alpaca) + Active Trades + Active Agents
 * + Today's Movers. All symbol clicks route to the global SymbolDetailDrawer
 * via onOpenSymbolDetail (mounted in MarketShell). No inline drill-down here.
 */

import { useEffect, useMemo, useState } from "react";

import { MorningScanPanel } from "@/components/MorningScanPanel";
import { BriefResearchOverview } from "@/components/ResearchOverview";
import {
  listAgentOperations,
  listOpenTrades,
  listPortfolioHoldings
} from "@/lib/api";
import type {
  AgentOperation,
  OpenTrade,
  PortfolioHolding,
  WatchlistItem
} from "@/lib/types";

// -----------------------------------------------------------------------------
// Formatters
// -----------------------------------------------------------------------------

const fmtMoney = (n: number) =>
  n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });

const fmtPct = (n: number) => `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`;

function formatAge(iso: string | null | undefined): string {
  if (!iso) return "—";
  const ts = new Date(iso).getTime();
  if (Number.isNaN(ts)) return "—";
  const deltaSec = Math.max(0, Math.round((Date.now() - ts) / 1000));
  if (deltaSec < 60) return `${deltaSec}s`;
  const min = Math.round(deltaSec / 60);
  if (min < 60) return `${min}m`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr}h`;
  const d = Math.round(hr / 24);
  return `${d}d`;
}

// -----------------------------------------------------------------------------
// Root
// -----------------------------------------------------------------------------

export function BriefWorkspace({
  symbol: _symbol,
  watchlistItems,
  onAddToWatchlist,
  onApproveIdea,
  onOpenResearch,
  onOpenStrategyResearch,
  onOpenQuant,
  onOpenPerformance,
  onOpenResearchSymbol,
  onOpenSymbolDetail
}: {
  symbol: string;
  watchlistItems: WatchlistItem[];
  /**
   * Adds a symbol to the watchlist — MarketShell wires this to its watchlist
   * state. Pass-through to MorningScanPanel's "+ watch" buttons on discovered
   * ideas (hidden when absent).
   */
  onAddToWatchlist?: (symbol: string) => void;
  /**
   * Approve a Morning Scan idea — MarketShell wires this to open the Quant
   * tab with the trade (symbol + side) pre-filled. Threaded straight into
   * MorningScanPanel's approve buttons (hidden when absent).
   */
  onApproveIdea?: (symbol: string, side: "buy" | "sell") => void;
  onOpenResearch: () => void;
  onOpenStrategyResearch?: () => void;
  onOpenQuant?: () => void;
  onOpenPerformance?: () => void;
  /**
   * Opens Research pinned to a specific symbol — used by the Morning Scan
   * panel's per-idea Research buttons so they land on the idea's ticker
   * rather than whatever symbol was last selected. Falls back to the
   * symbol-less onOpenResearch when absent.
   */
  onOpenResearchSymbol?: (symbol: string) => void;
  /**
   * When provided, symbol row/chip clicks open the global SymbolDetailDrawer.
   * MarketShell always wires this in production; if omitted (e.g. standalone
   * test), clicks become no-ops.
   */
  onOpenSymbolDetail?: (symbol: string) => void;
}) {
  const handleSymbolClick = (clickedSymbol: string) => {
    if (onOpenSymbolDetail) onOpenSymbolDetail(clickedSymbol);
  };

  const [agents, setAgents] = useState<AgentOperation[]>([]);
  const [agentsError, setAgentsError] = useState<string | null>(null);
  const [isLoadingAgents, setIsLoadingAgents] = useState(false);

  // Holdings are fetched here (not inside BriefHoldingsPanel) so the Morning
  // Scan panel can derive held symbols from the same single request.
  const [holdingsState, setHoldingsState] = useState<HoldingsState>({ phase: "loading" });

  useEffect(() => {
    let isCurrent = true;
    setHoldingsState({ phase: "loading" });

    listPortfolioHoldings("alpaca-paper-broker")
      .then((catalog) => {
        if (!isCurrent) return;
        setHoldingsState({ phase: "live", holdings: catalog.holdings });
      })
      .catch((caught: Error & { status?: number }) => {
        if (!isCurrent) return;
        const reason: "no-creds" | "api-error" =
          caught.status === 403 || caught.status === 404 ? "no-creds" : "api-error";
        setHoldingsState({
          phase: "fallback",
          reason,
          message: caught instanceof Error ? caught.message : "Holdings unavailable"
        });
      });

    return () => {
      isCurrent = false;
    };
  }, []);

  const heldSymbols = useMemo(
    () =>
      holdingsState.phase === "live"
        ? holdingsState.holdings
            .map((holding) => holding.symbol)
            .filter((sym): sym is string => Boolean(sym))
        : [],
    [holdingsState]
  );

  const watchlistSymbols = useMemo(
    () => watchlistItems.map((item) => item.symbol),
    [watchlistItems]
  );

  useEffect(() => {
    let isCurrent = true;
    setIsLoadingAgents(true);
    setAgentsError(null);

    listAgentOperations({ status: "running", limit: 8 })
      .then((catalog) => {
        if (!isCurrent) return;
        setAgents(catalog.operations);
        setIsLoadingAgents(false);
      })
      .catch((caught) => {
        if (!isCurrent) return;
        setAgentsError(caught instanceof Error ? caught.message : "Unable to load agents");
        setIsLoadingAgents(false);
      });

    return () => {
      isCurrent = false;
    };
  }, []);

  const movers = useMemo(() => {
    return [...watchlistItems]
      .filter((item) => item.changePercent !== null && item.changePercent !== 0)
      .sort((a, b) => Math.abs(b.changePercent ?? 0) - Math.abs(a.changePercent ?? 0))
      .slice(0, 10);
  }, [watchlistItems]);

  return (
    <section className="brief-workspace" aria-label="Brief">
      <header className="workspace-header brief-header">
        <div>
          <span className="panel-kicker">Morning Desk · Room 1</span>
          <h1>Brief</h1>
        </div>
        <div className="brief-header-status">
          <span>{watchlistItems.length} symbols tracked</span>
          <span>{watchlistItems.some((item) => item.price !== null) ? "Quotes shown in watchlist" : "Awaiting quotes"}</span>
        </div>
      </header>

      <BriefResearchOverview onOpenResearch={onOpenStrategyResearch ?? onOpenResearch} onOpenQuant={onOpenQuant} onOpenPerformance={onOpenPerformance}/>

      <MorningScanPanel
        watchlistSymbols={watchlistSymbols}
        heldSymbols={heldSymbols}
        onAddToWatchlist={onAddToWatchlist}
        onApproveIdea={onApproveIdea}
        // Prefer the symbol-aware research callback so "Research" on an idea
        // pins that ticker; the symbol-less fallback just opens the tab.
        onOpenResearch={onOpenResearchSymbol ?? onOpenResearch}
      />

      <div className="brief-overview-grid">
        <BriefHoldingsPanel state={holdingsState} watchlistItems={watchlistItems} onSelect={handleSymbolClick} />
        <div className="brief-side-stack">
          <BriefTradesPanel onSelect={handleSymbolClick} />
          <BriefAgentsPanel
            agents={agents}
            isLoading={isLoadingAgents}
            error={agentsError}
            onSelectSymbol={handleSymbolClick}
          />
        </div>
      </div>

      <BriefMoversPanel movers={movers} onSelect={handleSymbolClick} />
    </section>
  );
}

// -----------------------------------------------------------------------------
// Holdings
// -----------------------------------------------------------------------------

type HoldingsState =
  | { phase: "loading" }
  | { phase: "live"; holdings: PortfolioHolding[] }
  | { phase: "fallback"; reason: "no-creds" | "api-error"; message: string };

function BriefHoldingsPanel({
  state,
  watchlistItems,
  onSelect
}: {
  /** Lifted to BriefWorkspace so MorningScanPanel shares the same fetch. */
  state: HoldingsState;
  watchlistItems: WatchlistItem[];
  onSelect: (symbol: string) => void;
}) {
  const stockRows = (() => {
    if (state.phase === "live") {
      return state.holdings.map((h) => ({
        symbol: h.symbol ?? "—",
        name: h.name ?? "",
        value: h.value,
        // Alpaca /v2/positions doesn't include day change; leave blank.
        changePercent: null as number | null
      }));
    }
    // Watchlist fallback when Alpaca creds aren't configured.
    return watchlistItems.map((item) => ({
      symbol: item.symbol,
      name: item.name,
      value: null as number | null,
      changePercent: item.changePercent
    }));
  })();

  const totalValue = stockRows.reduce((acc, r) => acc + (r.value ?? 0), 0);
  const hasValue = stockRows.some((r) => r.value !== null);

  return (
    <article className="brief-holdings">
      <header className="brief-panel-header">
        <span className="panel-kicker">Holdings</span>
        <span className="brief-panel-header-right">
          {hasValue ? (
            <span className="brief-overall-value brief-mono">{fmtMoney(totalValue)}</span>
          ) : null}
          {state.phase === "loading" ? <span className="brief-mock-pill">loading</span> : null}
          {state.phase === "live" ? (
            <span className="brief-mock-pill" title="Holdings read from the Alpaca paper account when this view loaded; not a streaming feed">
              paper · Alpaca
            </span>
          ) : null}
          {state.phase === "fallback" && state.reason === "no-creds" ? (
            <span
              className="brief-mock-pill"
              title="Alpaca portfolio is disabled or has no secret_ref. Enable in Settings → Providers and set the alpaca-paper-broker credential."
            >
              watchlist · enable Alpaca
            </span>
          ) : null}
          {state.phase === "fallback" && state.reason === "api-error" ? (
            <span className="brief-mock-pill" title={state.message}>
              watchlist · API offline
            </span>
          ) : null}
        </span>
      </header>

      {stockRows.length === 0 ? (
        <p className="brief-empty">
          {state.phase === "live"
            ? "No positions in your Alpaca paper account. Open Quant → Simple Mode to place your first paper trade."
            : "No watchlist items to show. Add a symbol from the rail on the left."}
        </p>
      ) : (
        <ul className="brief-holdings-list">
          {stockRows.map((row) => {
            const isUp = (row.changePercent ?? 0) >= 0;
            return (
              <li key={row.symbol}>
                <button className="brief-holdings-row" onClick={() => onSelect(row.symbol)} type="button">
                  <span className="brief-holdings-sym">
                    <strong>{row.symbol}</strong>
                    <small>{row.name}</small>
                  </span>
                  <span className="brief-holdings-value brief-mono">
                    {row.value === null ? "—" : fmtMoney(row.value)}
                  </span>
                  <span className={`brief-holdings-change brief-mono ${isUp ? "is-positive" : "is-negative"}`}>
                    {row.changePercent === null ? "—" : fmtPct(row.changePercent)}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </article>
  );
}

// -----------------------------------------------------------------------------
// Active trades
// -----------------------------------------------------------------------------

type TradesState =
  | { phase: "loading" }
  | { phase: "loaded"; items: OpenTrade[] }
  | { phase: "error"; reason: string };

const TRADE_CAP = 5;

function BriefTradesPanel({ onSelect }: { onSelect: (symbol: string) => void }) {
  const [state, setState] = useState<TradesState>({ phase: "loading" });

  useEffect(() => {
    let isCurrent = true;
    setState({ phase: "loading" });

    listOpenTrades({ limit: 16 })
      .then((catalog) => {
        if (!isCurrent) return;
        setState({ phase: "loaded", items: catalog.items });
      })
      .catch((caught: Error) => {
        if (!isCurrent) return;
        setState({
          phase: "error",
          reason: caught instanceof Error ? caught.message : "API unavailable"
        });
      });

    return () => {
      isCurrent = false;
    };
  }, []);

  const sortedItems =
    state.phase === "loaded"
      ? [...state.items].sort((a, b) => {
          const ta = new Date(a.updated_at).getTime() || 0;
          const tb = new Date(b.updated_at).getTime() || 0;
          return tb - ta;
        })
      : [];
  const visibleItems = sortedItems.slice(0, TRADE_CAP);
  const overflowCount = Math.max(0, sortedItems.length - TRADE_CAP);

  return (
    <article className="brief-active-panel">
      <header className="brief-panel-header">
        <span className="panel-kicker">Saved open-order records</span>
        <span className="brief-panel-header-right">
          {state.phase === "loading" ? <span className="brief-mock-pill">loading</span> : null}
          {state.phase === "loaded" ? (
            <span className="brief-mock-pill" title="Saved local order statuses, not a fresh broker reconciliation">
              recorded
            </span>
          ) : null}
          {state.phase === "error" ? (
            <span className="brief-mock-pill" title={`API unavailable: ${state.reason}`}>
              API offline
            </span>
          ) : null}
        </span>
      </header>

      {state.phase === "loading" ? <p className="brief-empty">Loading open trades…</p> : null}

      {state.phase === "loaded" && visibleItems.length === 0 ? (
        <p className="brief-empty">No trades in flight.</p>
      ) : null}

      {state.phase === "error" ? <p className="brief-empty error">{state.reason}</p> : null}

      {visibleItems.length > 0 ? (
        <ul className="brief-trades-list">
          {visibleItems.map((t) => {
            const sideClass = t.side === "buy" ? "is-positive" : "is-negative";
            const displayStatus = t.broker_status ?? t.status;
            return (
              <li key={t.intent_id}>
                <button className="brief-trade-row" onClick={() => onSelect(t.symbol)} type="button">
                  <span className="brief-trade-sym">
                    <strong>{t.symbol}</strong>
                    <small className={sideClass}>
                      {t.side} {t.order_type} · {fmtMoney(t.notional)}
                    </small>
                  </span>
                  <span className="brief-trade-meta">
                    <span className="brief-mono">{displayStatus}</span>
                    <small>{formatAge(t.updated_at)}</small>
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      ) : null}

      {overflowCount > 0 ? (
        <p className="brief-panel-footer">
          <span className="brief-mono">+{overflowCount} more</span> · show all in Quant →
        </p>
      ) : null}
    </article>
  );
}

// -----------------------------------------------------------------------------
// Active agents
// -----------------------------------------------------------------------------

const AGENT_CAP = 5;

function BriefAgentsPanel({
  agents,
  isLoading,
  error,
  onSelectSymbol
}: {
  agents: AgentOperation[];
  isLoading: boolean;
  error: string | null;
  onSelectSymbol: (symbol: string) => void;
}) {
  const visibleAgents = agents.slice(0, AGENT_CAP);
  const overflowCount = Math.max(0, agents.length - AGENT_CAP);

  return (
    <article className="brief-active-panel">
      <header className="brief-panel-header">
        <span className="panel-kicker">Active agents</span>
        <span className="brief-panel-header-right">
          {isLoading ? (
            <span className="brief-mock-pill">loading</span>
          ) : agents.length > 0 ? (
            <span className="brief-pulse-dot" aria-hidden="true" />
          ) : null}
        </span>
      </header>
      {error ? <p className="brief-empty error">{error}</p> : null}
      {!error && !isLoading && agents.length === 0 ? (
        <p className="brief-empty">No agents running. Trigger a research run from the Research tab.</p>
      ) : null}
      {visibleAgents.length > 0 ? (
        <ul className="brief-agents-list">
          {visibleAgents.map((a) => (
            <li key={a.operation_id}>
              <button className="brief-agent-row" onClick={() => onSelectSymbol(a.symbol)} type="button">
                <span className="brief-agent-name">
                  <strong>{a.agent_name}</strong>
                  <small>
                    {a.operation_type.replaceAll("_", " ")} · {a.symbol}
                  </small>
                </span>
                <span className={`brief-agent-state mode-${a.authority === "research_only" ? "ok" : "tight"}`}>
                  {a.authority.replace("_", " ")}
                </span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      {overflowCount > 0 ? (
        <p className="brief-panel-footer">
          <span className="brief-mono">+{overflowCount} more</span>
        </p>
      ) : null}
    </article>
  );
}

// -----------------------------------------------------------------------------
// Today's movers
// -----------------------------------------------------------------------------

function BriefMoversPanel({
  movers,
  onSelect
}: {
  movers: WatchlistItem[];
  onSelect: (symbol: string) => void;
}) {
  // If there's nothing to show, omit the panel entirely (no empty header).
  if (movers.length === 0) return null;

  return (
    <article className="brief-movers">
      <header className="brief-panel-header">
        <span className="panel-kicker">Today&apos;s movers</span>
        <span className="brief-movers-meta">sorted by |change|</span>
      </header>
      <div className="brief-movers-grid">
        {movers.map((m) => {
          const isUp = (m.changePercent ?? 0) >= 0;
          return (
            <button
              key={m.symbol}
              className={`brief-mover-chip ${isUp ? "is-positive" : "is-negative"}`}
              onClick={() => onSelect(m.symbol)}
              type="button"
            >
              <strong>{m.symbol}</strong>
              <span className="brief-mono">{fmtPct(m.changePercent ?? 0)}</span>
            </button>
          );
        })}
      </div>
    </article>
  );
}
