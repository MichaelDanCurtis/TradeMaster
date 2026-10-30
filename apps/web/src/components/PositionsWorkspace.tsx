"use client";

/**
 * Book → Positions tab.
 *
 * Real Alpaca paper positions, each shown as a card with its attached
 * watchers. The watcher backend lands in Phase 3 — each position card lists
 * its WatcherChips and offers a "+ add watch" button that opens
 * CreateWatcherModal with the symbol pre-filled.
 *
 * Agent verdict overlay: once holdings load we fetch the latest completed
 * agent read per held symbol (GET /api/scans/verdicts) and render a
 * VerdictChip beside the symbol header. A SELL verdict also tints the
 * card's left border — the "agents say reconsider" signal.
 */

import { useEffect, useMemo, useState, type KeyboardEvent } from "react";

import { CreateWatcherModal } from "@/components/CreateWatcherModal";
import { VerdictChip, verdictActionKind } from "@/components/VerdictChip";
import { WatcherChip } from "@/components/WatcherChip";
import {
  WatcherEndpointMissingError,
  getScanVerdicts,
  listPortfolioHoldings,
  listWatchers
} from "@/lib/api";
import type { PortfolioHolding, ScanVerdict, WatcherRecord } from "@/lib/types";

type PositionsState =
  | { phase: "loading" }
  | { phase: "live"; holdings: PortfolioHolding[] }
  | { phase: "no-creds" }
  | { phase: "error"; message: string };

const fmtMoney = (n: number | null) =>
  n === null
    ? "—"
    : n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });

const fmtPct = (cost: number | null, market: number | null) => {
  if (cost === null || market === null || cost === 0) return "—";
  const pct = ((market - cost) / cost) * 100;
  return `${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%`;
};

type WatcherIndex = {
  bySymbol: Record<string, WatcherRecord[]>;
  endpointMissing: boolean;
};

const EMPTY_WATCHER_INDEX: WatcherIndex = { bySymbol: {}, endpointMissing: false };

type VerdictsState =
  | { phase: "loading" }
  | { phase: "loaded"; bySymbol: Record<string, ScanVerdict> }
  | { phase: "error" };

export function PositionsWorkspace({
  symbol,
  onOpenSymbolDetail
}: {
  symbol: string;
  /** When provided, clicking a position card opens the SymbolDetailDrawer. */
  onOpenSymbolDetail?: (symbol: string) => void;
}) {
  const [state, setState] = useState<PositionsState>({ phase: "loading" });
  const [watcherIndex, setWatcherIndex] = useState<WatcherIndex>(EMPTY_WATCHER_INDEX);
  const [verdicts, setVerdicts] = useState<VerdictsState>({ phase: "loading" });
  const [modalSymbol, setModalSymbol] = useState<string | null>(null);

  useEffect(() => {
    let isCurrent = true;
    setState({ phase: "loading" });

    listPortfolioHoldings("alpaca-paper-broker")
      .then((catalog) => {
        if (!isCurrent) return;
        setState({ phase: "live", holdings: catalog.holdings });
      })
      .catch((caught: Error & { status?: number }) => {
        if (!isCurrent) return;
        if (caught.status === 403 || caught.status === 404) {
          setState({ phase: "no-creds" });
        } else {
          setState({
            phase: "error",
            message: caught instanceof Error ? caught.message : "Holdings unavailable"
          });
        }
      });

    return () => {
      isCurrent = false;
    };
  }, []);

  useEffect(() => {
    let isCurrent = true;

    async function loadWatchers() {
      try {
        const catalog = await listWatchers({ limit: 200 });
        if (!isCurrent) return;
        const bySymbol: Record<string, WatcherRecord[]> = {};
        catalog.watchers.forEach((watcher) => {
          const key = watcher.symbol.toUpperCase();
          if (!bySymbol[key]) bySymbol[key] = [];
          bySymbol[key].push(watcher);
        });
        setWatcherIndex({ bySymbol, endpointMissing: false });
      } catch (caught) {
        if (!isCurrent) return;
        if (caught instanceof WatcherEndpointMissingError) {
          setWatcherIndex({ bySymbol: {}, endpointMissing: true });
          return;
        }
        // Non-fatal: positions still render without their watcher chips.
        setWatcherIndex({ bySymbol: {}, endpointMissing: false });
      }
    }

    void loadWatchers();
    return () => {
      isCurrent = false;
    };
  }, []);

  function upsertWatcher(next: WatcherRecord) {
    setWatcherIndex((prior) => {
      const key = next.symbol.toUpperCase();
      const existing = prior.bySymbol[key] ?? [];
      const filtered = existing.filter((entry) => entry.watcher_id !== next.watcher_id);
      return {
        endpointMissing: false,
        bySymbol: { ...prior.bySymbol, [key]: [...filtered, next] }
      };
    });
  }

  function removeWatcher(watcherId: string) {
    setWatcherIndex((prior) => {
      const bySymbol: Record<string, WatcherRecord[]> = {};
      Object.entries(prior.bySymbol).forEach(([key, watchers]) => {
        const filtered = watchers.filter((entry) => entry.watcher_id !== watcherId);
        if (filtered.length > 0) bySymbol[key] = filtered;
      });
      return { bySymbol, endpointMissing: prior.endpointMissing };
    });
  }

  const positionSymbols = useMemo(() => {
    if (state.phase !== "live") return [];
    return state.holdings
      .map((h) => h.symbol?.toUpperCase())
      .filter((value): value is string => Boolean(value));
  }, [state]);

  // Agent verdict overlay: once holdings are known, ask which of them the
  // agents have already read. Failures stay silent — cards simply render
  // without their verdict chips.
  useEffect(() => {
    if (positionSymbols.length === 0) return;
    let isCurrent = true;

    getScanVerdicts({ symbols: positionSymbols })
      .then((catalog) => {
        if (!isCurrent) return;
        const bySymbol: Record<string, ScanVerdict> = {};
        catalog.verdicts.forEach((verdict) => {
          bySymbol[verdict.symbol.toUpperCase()] = verdict;
        });
        setVerdicts({ phase: "loaded", bySymbol });
      })
      .catch(() => {
        if (!isCurrent) return;
        setVerdicts({ phase: "error" });
      });

    return () => {
      isCurrent = false;
    };
  }, [positionSymbols]);

  return (
    <section className="positions-workspace" aria-label="Positions">
      <header className="workspace-header positions-header">
        <div>
          <span className="panel-kicker">Book · Active positions</span>
          <h1>What I&apos;m holding</h1>
        </div>
        <div className="positions-header-status">
          {state.phase === "live" ? <span>{state.holdings.length} positions</span> : null}
          {state.phase === "loading" ? <span>loading…</span> : null}
        </div>
      </header>

      {state.phase === "loading" ? <p className="brief-empty">Loading positions from Alpaca…</p> : null}

      {state.phase === "no-creds" ? (
        <p className="brief-empty">
          Alpaca portfolio data is disabled. Enable in Studio → Providers and set the alpaca-paper-broker credential.
        </p>
      ) : null}

      {state.phase === "error" ? <p className="brief-empty error">{state.message}</p> : null}

      {state.phase === "live" && state.holdings.length === 0 ? (
        <p className="brief-empty">No open positions in the Alpaca paper account.</p>
      ) : null}

      {state.phase === "live" && state.holdings.length > 0 ? (
        <ul className="positions-list">
          {state.holdings.map((h) => {
            const isFocused = (h.symbol ?? "").toUpperCase() === symbol.toUpperCase();
            const pnlClass =
              h.value !== null && h.cost_basis !== null && h.value >= h.cost_basis
                ? "is-positive"
                : "is-negative";

            const cardSymbol = h.symbol ?? "";

            // Agent verdict for this holding — chips are skipped while the
            // verdicts fetch is loading and after a (silent) failure.
            const verdict =
              verdicts.phase === "loaded" ? verdicts.bySymbol[cardSymbol.toUpperCase()] : undefined;
            const agentSaysSell =
              verdict !== undefined && verdictActionKind(verdict.action, verdict.rating) === "sell";
            const cardClassName = [
              "position-card",
              isFocused ? "focused" : null,
              agentSaysSell ? "agent-sell-flag" : null
            ]
              .filter(Boolean)
              .join(" ");

            const headProps =
              onOpenSymbolDetail && cardSymbol
                ? {
                    onClick: () => onOpenSymbolDetail(cardSymbol),
                    role: "button" as const,
                    tabIndex: 0,
                    onKeyDown: (event: KeyboardEvent<HTMLElement>) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        onOpenSymbolDetail(cardSymbol);
                      }
                    },
                    "aria-label": `Open ${cardSymbol} detail`
                  }
                : {};

            return (
              <li key={h.security_id ?? h.symbol} className={cardClassName}>
                <header className="position-card-head" {...headProps}>
                  <div>
                    <span className="verdict-chip-slot">
                      <strong className="position-symbol">{h.symbol ?? "—"}</strong>
                      {verdicts.phase === "loaded" ? (
                        verdict ? (
                          <VerdictChip verdict={verdict} />
                        ) : (
                          <span className="verdict-chip-none">no agent read yet</span>
                        )
                      ) : null}
                    </span>
                    <small className="position-exchange">{h.name ?? ""}</small>
                  </div>
                  <div className="position-numbers">
                    <span className="brief-mono position-value">{fmtMoney(h.value)}</span>
                    <span className={`brief-mono position-pnl ${pnlClass}`}>{fmtPct(h.cost_basis, h.value)}</span>
                  </div>
                </header>

                <dl className="position-detail-row">
                  <div>
                    <dt>Qty</dt>
                    <dd className="brief-mono">{h.quantity.toFixed(4)}</dd>
                  </div>
                  <div>
                    <dt>Last</dt>
                    <dd className="brief-mono">{h.price === null ? "—" : `$${h.price.toFixed(2)}`}</dd>
                  </div>
                  <div>
                    <dt>Cost basis</dt>
                    <dd className="brief-mono">{fmtMoney(h.cost_basis)}</dd>
                  </div>
                </dl>

                <footer className="position-watchers">
                  <span className="panel-kicker">Watchers</span>
                  <div className="position-watcher-chips">
                    {(() => {
                      const symbolKey = cardSymbol.toUpperCase();
                      const attached = watcherIndex.bySymbol[symbolKey] ?? [];
                      if (watcherIndex.endpointMissing) {
                        return (
                          <span className="position-watcher-empty">
                            Watchers endpoint warming up
                          </span>
                        );
                      }
                      if (attached.length === 0) {
                        return (
                          <span className="position-watcher-empty">
                            No watchers attached
                          </span>
                        );
                      }
                      return attached.map((watcher) => (
                        <WatcherChip
                          key={watcher.watcher_id}
                          onChange={upsertWatcher}
                          onDelete={removeWatcher}
                          watcher={watcher}
                        />
                      ));
                    })()}
                    {cardSymbol && !watcherIndex.endpointMissing ? (
                      <button
                        aria-label={`Add watcher for ${cardSymbol}`}
                        className="position-watcher-add"
                        onClick={() => setModalSymbol(cardSymbol)}
                        type="button"
                      >
                        + add watch
                      </button>
                    ) : null}
                  </div>
                </footer>
              </li>
            );
          })}
        </ul>
      ) : null}

      <CreateWatcherModal
        initialSymbol={modalSymbol ?? ""}
        isOpen={modalSymbol !== null}
        lockedSymbol={modalSymbol}
        onClose={() => setModalSymbol(null)}
        onCreated={(watcher) => upsertWatcher(watcher)}
      />
    </section>
  );
}
