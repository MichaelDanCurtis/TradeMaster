"use client";

/**
 * MorningScanPanel — the flagship ideas surface at the top of Portfolio →
 * Overview. Each morning the agent committee ranks the user's universe into:
 *
 *   - BUY CANDIDATES: buy-rated verdicts for symbols NOT currently held,
 *     sorted by confidence then recency.
 *   - HOLDINGS REVIEW: a verdict row for every held symbol (sell flags get an
 *     "Review exit in Quant" affordance; unscanned holdings get a per-row Scan button).
 *
 * Data comes from GET /api/scans/verdicts; "Run morning scan" POSTs /api/scans
 * for up to 10 symbols (held first) and then polls every 10s until all started
 * runs produce fresh verdicts or 15 minutes elapse. Committee runs take
 * minutes, so the copy sets that expectation explicitly.
 *
 * Discover mode: the "Discover" button pulls whole-market candidates from
 * GET /api/discover/candidates (Alpaca screener: gainers/losers/most-actives,
 * excluding held + watched symbols) into an inline picker strip. Selected
 * symbols run through the same beginScan/polling machinery; their verdicts
 * surface in BUY CANDIDATES with a "discovered" tag and a "+ watch" button.
 *
 * Find opportunities (flagship): a fast gpt-4o-mini sweep over the whole
 * universe (watchlist ∪ holdings + screener candidates, capped at 30) via
 * POST /api/quickscan in sequential batches of 6. Results rank on the
 * OPPORTUNITY BOARD above the committee columns, conviction-desc; [Deep dive]
 * hands any row to the full committee machinery below.
 */

import { useEffect, useMemo, useRef, useState } from "react";

import { verdictActionKind } from "@/components/VerdictChip";
import {
  getDiscoverCandidates,
  getLatestQuickScans,
  getScanVerdicts,
  runQuickScan,
  startScan
} from "@/lib/api";
import type { DiscoverCandidate, QuickScanResult, ScanVerdict } from "@/lib/types";

const POLL_INTERVAL_MS = 10_000;
const SCAN_TIMEOUT_MS = 15 * 60 * 1000;
const SCAN_BATCH_MAX = 10;
// Discover mode: how many screener candidates to pull, how many arrive
// pre-checked, and the floor that culls penny-stock movers.
const DISCOVER_FETCH_LIMIT = 15;
const DISCOVER_PRECHECK_COUNT = 5;
const DISCOVER_MIN_PRICE = 5;
// Tolerance for client-vs-server clock skew when deciding whether a verdict's
// run_created_at is "fresh" (i.e. newer than the moment the scan started).
const CLOCK_SKEW_MS = 30_000;
// Find-opportunities sweep: batches of 6 match the server's
// ThreadPoolExecutor(max_workers=6); batches run sequentially client-side so
// board rows land progressively instead of after one long wait.
const SWEEP_BATCH_SIZE = 6;
const SWEEP_UNIVERSE_CAP = 30;
const SWEEP_DISCOVER_LIMIT = 15;
// Opportunity board shows this many rows before the "show all N" toggle.
const BOARD_COLLAPSED_ROWS = 12;

// -----------------------------------------------------------------------------
// Helpers
// -----------------------------------------------------------------------------

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

/** Graph-runner verdicts carry confidence as a 0..1 fraction; render as %. */
function formatConfidence(confidence: number | null): string | null {
  if (confidence === null || Number.isNaN(confidence)) return null;
  const pct = confidence > 1 ? confidence : confidence * 100;
  return `${Math.round(pct)}%`;
}

function formatChangePct(value: number | null): string {
  if (value === null || Number.isNaN(value)) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(1)}%`;
}

function formatVolume(value: number | null): string {
  if (value === null || Number.isNaN(value)) return "—";
  if (value >= 1e9) return `${(value / 1e9).toFixed(1)}B`;
  if (value >= 1e6) return `${(value / 1e6).toFixed(1)}M`;
  if (value >= 1e3) return `${(value / 1e3).toFixed(1)}K`;
  return String(Math.round(value));
}

function dedupeUpper(symbols: string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of symbols) {
    const sym = raw.trim().toUpperCase();
    if (sym && !seen.has(sym)) {
      seen.add(sym);
      out.push(sym);
    }
  }
  return out;
}

function countFresh(verdicts: ScanVerdict[], scanSymbols: string[], startedAtMs: number): number {
  const cutoff = startedAtMs - CLOCK_SKEW_MS;
  return scanSymbols.filter((sym) => {
    const verdict = verdicts.find((v) => v.symbol.toUpperCase() === sym);
    if (!verdict) return false;
    const ts = new Date(verdict.run_created_at).getTime();
    return !Number.isNaN(ts) && ts > cutoff;
  }).length;
}

/**
 * Merge quick-scan reads into the board map, keeping the newer read per symbol
 * (hydration from /latest and live sweep results can interleave).
 */
function mergeQuickScanReads(
  prev: Record<string, QuickScanResult>,
  incoming: QuickScanResult[]
): Record<string, QuickScanResult> {
  if (incoming.length === 0) return prev;
  const next = { ...prev };
  for (const read of incoming) {
    const sym = read.symbol.toUpperCase();
    const existing = next[sym];
    const incomingTs = new Date(read.created_at).getTime() || 0;
    const existingTs = existing ? new Date(existing.created_at).getTime() || 0 : -1;
    if (incomingTs >= existingTs) {
      next[sym] = { ...read, symbol: sym };
    }
  }
  return next;
}

// -----------------------------------------------------------------------------
// State machines
// -----------------------------------------------------------------------------

type VerdictsState =
  | { phase: "loading" }
  | { phase: "loaded"; verdicts: ScanVerdict[] }
  | { phase: "error"; message: string };

type ScanState =
  | { phase: "idle" }
  | { phase: "starting" }
  | { phase: "scanning"; startedAtMs: number; symbols: string[]; failedCount: number }
  | { phase: "error"; message: string };

/** Discover strip — closed by default; opens inline below the panel header. */
type DiscoverState =
  | { phase: "closed" }
  | { phase: "loading" }
  | { phase: "loaded"; candidates: DiscoverCandidate[]; selected: Set<string> }
  | { phase: "error"; message: string };

/**
 * Find-opportunities sweep — client-driven sequential batching over
 * POST /api/quickscan. Independent of ScanState: a committee scan and a sweep
 * can run at the same time. `total` is 0 while the universe is being built.
 */
type SweepState =
  | { phase: "idle" }
  | { phase: "sweeping"; done: number; total: number }
  | { phase: "done" }
  | { phase: "error"; message: string };

// -----------------------------------------------------------------------------
// Root
// -----------------------------------------------------------------------------

export function MorningScanPanel({
  watchlistSymbols,
  heldSymbols,
  onApproveIdea,
  onOpenResearch,
  onAddToWatchlist
}: {
  watchlistSymbols: string[];
  heldSymbols: string[];
  /** Routes an approved idea into the Quant order ticket. Buttons hide when absent. */
  onApproveIdea?: (symbol: string, side: "buy" | "sell") => void;
  /** Opens the research surface for a symbol. Buttons hide when absent. */
  onOpenResearch?: (symbol: string) => void;
  /** Adds a discovered idea's symbol to the watchlist. Buttons hide when absent. */
  onAddToWatchlist?: (symbol: string) => void;
}) {
  const held = useMemo(() => dedupeUpper(heldSymbols), [heldSymbols]);
  const heldSet = useMemo(() => new Set(held), [held]);
  const watchSet = useMemo(() => new Set(dedupeUpper(watchlistSymbols)), [watchlistSymbols]);
  // Held symbols first so the 10-symbol scan batch prioritizes the portfolio.
  const unionSymbols = useMemo(
    () => dedupeUpper([...heldSymbols, ...watchlistSymbols]),
    [heldSymbols, watchlistSymbols]
  );

  const [verdictsState, setVerdictsState] = useState<VerdictsState>({ phase: "loading" });
  const [scanState, setScanState] = useState<ScanState>({ phase: "idle" });
  const [reloadNonce, setReloadNonce] = useState(0);
  const [discoverState, setDiscoverState] = useState<DiscoverState>({ phase: "closed" });
  // Symbols scanned via Discover this session. They're neither held nor
  // watched, so the verdict fetches below must request them explicitly or
  // their committee verdicts would never come back from the catalog endpoint.
  const [discoveredSymbols, setDiscoveredSymbols] = useState<string[]>([]);

  // --- Opportunity board (Find opportunities sweep) --------------------------
  const [sweepState, setSweepState] = useState<SweepState>({ phase: "idle" });
  /** Latest quick-scan read per symbol; the board ranks these conviction-desc. */
  const [boardReads, setBoardReads] = useState<Record<string, QuickScanResult>>({});
  /** True once the mount-time getLatestQuickScans hydration settled. */
  const [boardHydrated, setBoardHydrated] = useState(false);
  const [sweepFailedSymbols, setSweepFailedSymbols] = useState<string[]>([]);
  const [sweepFailedDismissed, setSweepFailedDismissed] = useState(false);
  /** Soft note when the screener leg of the sweep fails (union still swept). */
  const [sweepNote, setSweepNote] = useState<string | null>(null);
  const [showAllBoard, setShowAllBoard] = useState(false);
  // Synchronous double-start guard (setState is async, so a fast double-click
  // could pass a state-based check) + unmount guard so the awaited batch loop
  // stops touching state after the panel unmounts.
  const sweepRunningRef = useRef(false);
  const isMountedRef = useRef(true);

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  const fetchSymbols = useMemo(
    () => dedupeUpper([...unionSymbols, ...discoveredSymbols]),
    [unionSymbols, discoveredSymbols]
  );
  // Stable string key so effects don't refire on array identity churn.
  const fetchKey = fetchSymbols.join(",");

  // Initial load (and refetch when the symbol universe changes or on retry).
  useEffect(() => {
    let isCurrent = true;
    const symbols = fetchKey ? fetchKey.split(",") : [];
    setVerdictsState({ phase: "loading" });

    if (symbols.length === 0) {
      setVerdictsState({ phase: "loaded", verdicts: [] });
      return;
    }

    getScanVerdicts({ symbols })
      .then((catalog) => {
        if (!isCurrent) return;
        setVerdictsState({ phase: "loaded", verdicts: catalog.verdicts });
      })
      .catch((caught) => {
        if (!isCurrent) return;
        setVerdictsState({
          phase: "error",
          message: caught instanceof Error ? caught.message : "Unable to load scan verdicts"
        });
      });

    return () => {
      isCurrent = false;
    };
  }, [fetchKey, reloadNonce]);

  // Hydrate the opportunity board with the most recent stored quick reads for
  // the union universe (past discovered symbols aren't tracked client-side),
  // so yesterday's sweep shows immediately with its age before any new sweep.
  const unionKey = unionSymbols.join(",");
  useEffect(() => {
    let isCurrent = true;
    if (!unionKey) {
      setBoardHydrated(true);
      return;
    }
    getLatestQuickScans({ symbols: unionKey.split(",") })
      .then((catalog) => {
        if (!isCurrent) return;
        setBoardReads((prev) => mergeQuickScanReads(prev, catalog.results));
        setBoardHydrated(true);
      })
      .catch(() => {
        // Best-effort: a failed hydration just means the board starts empty;
        // the empty-state copy points at Find opportunities either way.
        if (!isCurrent) return;
        setBoardHydrated(true);
      });
    return () => {
      isCurrent = false;
    };
  }, [unionKey]);

  // While a scan is in flight, poll every 10s until every started symbol has a
  // verdict newer than the scan start, or until the 15-minute window closes.
  useEffect(() => {
    if (scanState.phase !== "scanning") return;
    const { startedAtMs, symbols: scanSymbols } = scanState;

    const intervalId = window.setInterval(() => {
      if (Date.now() - startedAtMs > SCAN_TIMEOUT_MS) {
        setScanState({ phase: "idle" });
        return;
      }
      const symbols = fetchKey ? fetchKey.split(",") : scanSymbols;
      getScanVerdicts({ symbols })
        .then((catalog) => {
          setVerdictsState({ phase: "loaded", verdicts: catalog.verdicts });
          if (countFresh(catalog.verdicts, scanSymbols, startedAtMs) >= scanSymbols.length) {
            setScanState({ phase: "idle" });
          }
        })
        .catch(() => {
          // Transient poll failure — keep the interval alive; the next tick retries.
        });
    }, POLL_INTERVAL_MS);

    return () => window.clearInterval(intervalId);
  }, [scanState, fetchKey]);

  const isScanBusy = scanState.phase === "starting" || scanState.phase === "scanning";

  // Shared scan-start machinery: both "Run morning scan" (watchlist union) and
  // Discover's "Scan N selected" funnel through here, so the in-flight symbol
  // list — which drives the progress count and the 10s polling — is tracked
  // identically for both entry points.
  const beginScan = (batch: string[], onStarted?: (startedSymbols: string[]) => void) => {
    if (isScanBusy || batch.length === 0) return;
    setScanState({ phase: "starting" });
    const startedAtMs = Date.now();
    startScan(batch)
      .then((result) => {
        const startedSymbols = dedupeUpper(result.started.map((entry) => entry.symbol));
        const failedCount = result.failed?.length ?? 0;
        if (startedSymbols.length === 0) {
          setScanState({
            phase: "error",
            message: result.failed?.[0]?.error ?? "No scans could be started."
          });
          return;
        }
        setScanState({ phase: "scanning", startedAtMs, symbols: startedSymbols, failedCount });
        onStarted?.(startedSymbols);
      })
      .catch((caught) => {
        setScanState({
          phase: "error",
          message: caught instanceof Error ? caught.message : "Unable to start morning scan"
        });
      });
  };

  const handleRunScan = () => {
    beginScan(unionSymbols.slice(0, SCAN_BATCH_MAX));
  };

  // ---------------------------------------------------------------------------
  // Discover mode
  // ---------------------------------------------------------------------------

  const handleOpenDiscover = () => {
    setDiscoverState({ phase: "loading" });
    getDiscoverCandidates({
      limit: DISCOVER_FETCH_LIMIT,
      exclude: unionSymbols,
      minPrice: DISCOVER_MIN_PRICE
    })
      .then((catalog) => {
        const selected = new Set(
          catalog.candidates
            .slice(0, DISCOVER_PRECHECK_COUNT)
            .map((candidate) => candidate.symbol.toUpperCase())
        );
        setDiscoverState({ phase: "loaded", candidates: catalog.candidates, selected });
      })
      .catch((caught: Error & { status?: number }) => {
        const message =
          caught.status === 403 || caught.status === 404
            ? "Enable Alpaca market data in Settings → Providers"
            : caught instanceof Error
              ? caught.message
              : "Unable to load discovery candidates";
        setDiscoverState({ phase: "error", message });
      });
  };

  const handleToggleDiscover = () => {
    if (discoverState.phase === "closed") {
      handleOpenDiscover();
    } else {
      setDiscoverState({ phase: "closed" });
    }
  };

  const handleToggleCandidate = (symbol: string) => {
    setDiscoverState((prev) => {
      if (prev.phase !== "loaded") return prev;
      const selected = new Set(prev.selected);
      if (selected.has(symbol)) {
        selected.delete(symbol);
      } else {
        // Each pick is a full committee run; cap the batch like the main scan.
        if (selected.size >= SCAN_BATCH_MAX) return prev;
        selected.add(symbol);
      }
      return { ...prev, selected };
    });
  };

  const handleDiscoverScan = () => {
    if (discoverState.phase !== "loaded") return;
    const chosen = dedupeUpper([...discoverState.selected]).slice(0, SCAN_BATCH_MAX);
    beginScan(chosen, (startedSymbols) => {
      setDiscoveredSymbols((prev) => dedupeUpper([...prev, ...startedSymbols]));
      setDiscoverState({ phase: "closed" });
    });
  };

  const handleScanSymbol = (symbol: string) => {
    if (scanState.phase === "starting") return;
    if (scanState.phase === "scanning" && scanState.symbols.includes(symbol)) return;
    const startedAtMs = Date.now();
    startScan([symbol])
      .then((result) => {
        if (result.started.length === 0) {
          setScanState({
            phase: "error",
            message: result.failed?.[0]?.error ?? `Unable to scan ${symbol}`
          });
          return;
        }
        setScanState((prev) =>
          prev.phase === "scanning"
            ? {
                ...prev,
                symbols: prev.symbols.includes(symbol) ? prev.symbols : [...prev.symbols, symbol]
              }
            : { phase: "scanning", startedAtMs, symbols: [symbol], failedCount: 0 }
        );
      })
      .catch((caught) => {
        setScanState({
          phase: "error",
          message: caught instanceof Error ? caught.message : `Unable to scan ${symbol}`
        });
      });
  };

  // ---------------------------------------------------------------------------
  // Find opportunities sweep
  // ---------------------------------------------------------------------------

  const isSweeping = sweepState.phase === "sweeping";

  const handleFindOpportunities = async () => {
    if (sweepRunningRef.current) return;
    sweepRunningRef.current = true;
    try {
      setSweepNote(null);
      setSweepFailedSymbols([]);
      setSweepFailedDismissed(false);
      setShowAllBoard(false);
      // total: 0 = "building the universe" (progress line shows no counts yet).
      setSweepState({ phase: "sweeping", done: 0, total: 0 });

      // 1. Universe: holdings ∪ watchlist, topped up with screener candidates.
      //    A screener failure only degrades the sweep — it never blocks it.
      let universe = [...unionSymbols];
      try {
        const catalog = await getDiscoverCandidates({
          limit: SWEEP_DISCOVER_LIMIT,
          exclude: unionSymbols,
          minPrice: DISCOVER_MIN_PRICE
        });
        universe = universe.concat(catalog.candidates.map((candidate) => candidate.symbol));
      } catch {
        if (!isMountedRef.current) return;
        setSweepNote("Screener unavailable — reading watchlist + holdings only.");
      }
      if (!isMountedRef.current) return;
      const symbols = dedupeUpper(universe).slice(0, SWEEP_UNIVERSE_CAP);
      if (symbols.length === 0) {
        setSweepState({
          phase: "error",
          message: "Nothing to read — add symbols to your watchlist or holdings first."
        });
        return;
      }
      setSweepState({ phase: "sweeping", done: 0, total: symbols.length });

      // 2. Sequential batches (each batch is parallel server-side); merge into
      //    the board after every batch so rows appear progressively.
      const failed: string[] = [];
      let readCount = 0;
      let done = 0;
      for (let i = 0; i < symbols.length; i += SWEEP_BATCH_SIZE) {
        const batch = symbols.slice(i, i + SWEEP_BATCH_SIZE);
        try {
          const outcome = await runQuickScan(batch);
          if (!isMountedRef.current) return;
          setBoardReads((prev) => mergeQuickScanReads(prev, outcome.results));
          readCount += outcome.results.length;
          failed.push(...(outcome.failed ?? []).map((entry) => entry.symbol));
        } catch {
          if (!isMountedRef.current) return;
          failed.push(...batch);
        }
        done += batch.length;
        setSweepState({ phase: "sweeping", done, total: symbols.length });
      }

      if (!isMountedRef.current) return;
      setSweepFailedSymbols(dedupeUpper(failed));
      if (readCount === 0 && failed.length > 0) {
        setSweepState({
          phase: "error",
          message: "The sweep couldn't read any symbols — the quick-scan service may be down."
        });
      } else {
        setSweepState({ phase: "done" });
      }
    } finally {
      sweepRunningRef.current = false;
    }
  };

  // Deep dive from a board row: same single-symbol committee path as the
  // holdings "Scan" button. Symbols outside the union must also be tracked as
  // discovered or the verdict fetch above would never request their results.
  const handleDeepDive = (symbol: string) => {
    if (!heldSet.has(symbol) && !watchSet.has(symbol)) {
      setDiscoveredSymbols((prev) =>
        prev.includes(symbol) ? prev : dedupeUpper([...prev, symbol])
      );
    }
    handleScanSymbol(symbol);
  };

  // ---------------------------------------------------------------------------
  // Derived display data
  // ---------------------------------------------------------------------------

  const verdicts = verdictsState.phase === "loaded" ? verdictsState.verdicts : [];

  const nonHeldVerdicts = verdicts.filter((v) => !heldSet.has(v.symbol.toUpperCase()));

  const buyCandidates = nonHeldVerdicts
    .filter((v) => verdictActionKind(v.action, v.rating) === "buy")
    .sort((a, b) => {
      const confA = a.confidence ?? -1;
      const confB = b.confidence ?? -1;
      if (confB !== confA) return confB - confA;
      return (
        (new Date(b.run_created_at).getTime() || 0) - (new Date(a.run_created_at).getTime() || 0)
      );
    });

  // Non-buy reads on non-held symbols (watchlist HOLDs, discovered SELLs, …).
  // Without this group a committee read that doesn't say BUY would vanish —
  // the user waits minutes for a discovered-symbol scan and sees nothing land.
  const passedReads = nonHeldVerdicts
    .filter((v) => verdictActionKind(v.action, v.rating) !== "buy")
    .sort(
      (a, b) =>
        (new Date(b.run_created_at).getTime() || 0) - (new Date(a.run_created_at).getTime() || 0)
    );

  const holdingsRows = held.map((sym) => ({
    symbol: sym,
    verdict: verdicts.find((v) => v.symbol.toUpperCase() === sym) ?? null
  }));

  const newestRunIso = verdicts.reduce<string | null>((newest, v) => {
    if (!newest) return v.run_created_at;
    return new Date(v.run_created_at).getTime() > new Date(newest).getTime()
      ? v.run_created_at
      : newest;
  }, null);

  const freshCount =
    scanState.phase === "scanning"
      ? countFresh(verdicts, scanState.symbols, scanState.startedAtMs)
      : 0;

  // Opportunity board rows: conviction desc, then recency, then symbol.
  const boardRows = Object.values(boardReads).sort((a, b) => {
    if (b.conviction !== a.conviction) return b.conviction - a.conviction;
    const tsA = new Date(a.created_at).getTime() || 0;
    const tsB = new Date(b.created_at).getTime() || 0;
    if (tsB !== tsA) return tsB - tsA;
    return a.symbol.localeCompare(b.symbol);
  });
  const visibleBoardRows = showAllBoard ? boardRows : boardRows.slice(0, BOARD_COLLAPSED_ROWS);

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <section className="morning-scan-panel" aria-label="Morning scan">
      <header className="morning-scan-header">
        <div className="morning-scan-heading">
          <h2 className="morning-scan-title">Morning scan</h2>
          {newestRunIso ? (
            <span className="morning-scan-meta">last scan {formatAge(newestRunIso)} ago</span>
          ) : null}
        </div>
        <div className="morning-scan-header-right">
          {scanState.phase === "scanning" ? (
            <span className="morning-scan-progress" role="status">
              <span>
                Scanning… {freshCount} of {scanState.symbols.length} complete
                {scanState.failedCount > 0 ? ` · ${scanState.failedCount} failed to start` : ""}
              </span>
              <small>Agents are reading filings + news; first verdicts land in a few minutes.</small>
            </span>
          ) : null}
          {scanState.phase === "error" ? (
            <span className="morning-scan-progress error" role="alert">
              {scanState.message}
            </span>
          ) : null}
          <button
            className="morning-scan-discover-button"
            disabled={discoverState.phase === "loading"}
            onClick={handleToggleDiscover}
            title="Pull candidate tickers from today's market movers"
            type="button"
          >
            {discoverState.phase === "closed" ? "Discover" : "Close discover"}
          </button>
          <button
            className="morning-scan-discover-button"
            disabled={isScanBusy || unionSymbols.length === 0}
            onClick={handleRunScan}
            title={
              unionSymbols.length === 0
                ? "Add symbols to your watchlist to run a scan"
                : `Run the full agent committee on ${Math.min(unionSymbols.length, SCAN_BATCH_MAX)} symbols (holdings first, ~minutes each)`
            }
            type="button"
          >
            {scanState.phase === "starting"
              ? "Starting…"
              : scanState.phase === "scanning"
                ? "Scanning…"
                : "Deep scan all"}
          </button>
          <button
            className="morning-scan-scan-button"
            disabled={isSweeping}
            onClick={() => {
              void handleFindOpportunities();
            }}
            title="Quick-read your whole universe (watchlist + holdings + screener) in about two minutes"
            type="button"
          >
            {isSweeping ? "Reading…" : "Find opportunities"}
          </button>
        </div>
      </header>

      {discoverState.phase !== "closed" ? (
        <div className="morning-scan-discover-strip">
          {discoverState.phase === "loading" ? (
            <p className="morning-scan-empty">Scanning the market for movers…</p>
          ) : null}
          {discoverState.phase === "error" ? (
            <p className="morning-scan-empty error">
              {discoverState.message}{" "}
              <button
                className="morning-scan-row-button"
                onClick={handleOpenDiscover}
                type="button"
              >
                Retry
              </button>
            </p>
          ) : null}
          {discoverState.phase === "loaded" && discoverState.candidates.length === 0 ? (
            <p className="morning-scan-empty">
              Screener returned nothing right now — markets may be quiet.
            </p>
          ) : null}
          {discoverState.phase === "loaded" && discoverState.candidates.length > 0 ? (
            <>
              <ul className="morning-scan-discover-list">
                {discoverState.candidates.map((candidate) => {
                  const sym = candidate.symbol.toUpperCase();
                  const isChecked = discoverState.selected.has(sym);
                  const sourceKind =
                    candidate.source === "gainer"
                      ? "gainer"
                      : candidate.source === "loser"
                        ? "loser"
                        : "active";
                  const changeClass =
                    candidate.change_pct === null
                      ? ""
                      : candidate.change_pct >= 0
                        ? " is-up"
                        : " is-down";
                  return (
                    <li className="morning-scan-discover-row" key={sym}>
                      <label>
                        <input
                          checked={isChecked}
                          disabled={
                            !isChecked && discoverState.selected.size >= SCAN_BATCH_MAX
                          }
                          onChange={() => handleToggleCandidate(sym)}
                          type="checkbox"
                        />
                        <strong className="morning-scan-symbol">{sym}</strong>
                      </label>
                      <span className={`morning-scan-discover-source-pill ${sourceKind}`}>
                        {candidate.source === "most_active" ? "most active" : candidate.source}
                      </span>
                      <span className={`morning-scan-discover-change${changeClass}`}>
                        {formatChangePct(candidate.change_pct)}
                      </span>
                      <span className="morning-scan-discover-volume">
                        {formatVolume(candidate.volume)} vol
                      </span>
                    </li>
                  );
                })}
              </ul>
              <div className="morning-scan-discover-footer">
                <span className="morning-scan-discover-microcopy">
                  Each scan is a full committee read (~minutes per symbol).
                </span>
                <button
                  className="morning-scan-scan-button"
                  disabled={discoverState.selected.size === 0 || isScanBusy}
                  onClick={handleDiscoverScan}
                  title={
                    isScanBusy
                      ? "A scan is already in flight — wait for it to finish"
                      : "Run the agent committee on the selected symbols"
                  }
                  type="button"
                >
                  Scan {discoverState.selected.size} selected
                </button>
                <button
                  className="morning-scan-row-button"
                  onClick={() => setDiscoverState({ phase: "closed" })}
                  type="button"
                >
                  Cancel
                </button>
              </div>
            </>
          ) : null}
        </div>
      ) : null}

      <div aria-label="Opportunity board" className="morning-scan-opp-board">
        <h3 className="morning-scan-column-header">Opportunity board</h3>
        {sweepState.phase === "sweeping" ? (
          <p className="morning-scan-opp-progress" role="status">
            Reading the market…
            {sweepState.total > 0
              ? ` ${Math.min(sweepState.done, sweepState.total)} of ${sweepState.total} symbols read`
              : ""}
          </p>
        ) : null}
        {sweepNote && sweepState.phase !== "error" ? (
          <p className="morning-scan-opp-note">{sweepNote}</p>
        ) : null}
        {sweepFailedSymbols.length > 0 && !sweepFailedDismissed && sweepState.phase !== "sweeping" ? (
          <p className="morning-scan-opp-note">
            {sweepFailedSymbols.length} couldn&apos;t be read
            <button
              className="morning-scan-opp-note-dismiss"
              onClick={() => setSweepFailedDismissed(true)}
              title={sweepFailedSymbols.join(", ")}
              type="button"
            >
              dismiss
            </button>
          </p>
        ) : null}
        {sweepState.phase === "error" ? (
          <p className="morning-scan-empty error" role="alert">
            {sweepState.message}{" "}
            <button
              className="morning-scan-row-button"
              onClick={() => {
                void handleFindOpportunities();
              }}
              type="button"
            >
              Retry
            </button>
          </p>
        ) : null}
        {boardRows.length === 0 && sweepState.phase === "idle" ? (
          <p className="morning-scan-empty">
            {boardHydrated
              ? "Hit Find opportunities and the screener reads your whole universe in about two minutes."
              : "Loading recent quick reads…"}
          </p>
        ) : null}
        {boardRows.length > 0 ? (
          <ul className="morning-scan-opp-list">
            {visibleBoardRows.map((read) => (
              <OpportunityRow
                isDeepDiveBusy={scanState.phase === "starting"}
                isDeepDiving={
                  scanState.phase === "scanning" && scanState.symbols.includes(read.symbol)
                }
                isHeld={heldSet.has(read.symbol)}
                isWatched={watchSet.has(read.symbol)}
                key={read.symbol}
                onAddToWatchlist={onAddToWatchlist}
                onApproveIdea={onApproveIdea}
                onDeepDive={handleDeepDive}
                read={read}
              />
            ))}
          </ul>
        ) : null}
        {boardRows.length > BOARD_COLLAPSED_ROWS ? (
          <button
            className="morning-scan-opp-showall"
            onClick={() => setShowAllBoard((prev) => !prev)}
            type="button"
          >
            {showAllBoard ? `show top ${BOARD_COLLAPSED_ROWS}` : `show all ${boardRows.length}`}
          </button>
        ) : null}
      </div>

      {verdictsState.phase === "loading" ? (
        <p className="morning-scan-empty">Loading the committee&apos;s latest verdicts…</p>
      ) : null}

      {verdictsState.phase === "error" ? (
        <p className="morning-scan-empty error">
          {verdictsState.message}{" "}
          <button
            className="morning-scan-row-button"
            onClick={() => setReloadNonce((n) => n + 1)}
            type="button"
          >
            Retry
          </button>
        </p>
      ) : null}

      {verdictsState.phase === "loaded" && verdicts.length === 0 ? (
        <p className="morning-scan-empty">
          {scanState.phase === "scanning"
            ? "Scan in progress — verdicts will appear here as each committee run completes."
            : "No research yet. Run your first morning scan and the committee will rank your watchlist."}
        </p>
      ) : null}

      {verdictsState.phase === "loaded" && verdicts.length > 0 ? (
        <div className="morning-scan-columns">
          <div className="morning-scan-column">
            <h3 className="morning-scan-column-header">Buy candidates</h3>
            {buyCandidates.length === 0 ? (
              <p className="morning-scan-empty">No buy-rated ideas right now.</p>
            ) : (
              <ul className="morning-scan-idea-list">
                {buyCandidates.map((verdict) => {
                  // Neither held nor watched ⇒ this idea came from Discover.
                  const isDiscovered =
                    !heldSet.has(verdict.symbol.toUpperCase()) &&
                    !watchSet.has(verdict.symbol.toUpperCase());
                  return (
                    <VerdictRow
                      approveLabel={onApproveIdea ? "Review in Quant" : undefined}
                      isDiscovered={isDiscovered}
                      key={verdict.symbol}
                      onAddToWatchlist={isDiscovered ? onAddToWatchlist : undefined}
                      onApprove={onApproveIdea ? () => onApproveIdea(verdict.symbol, "buy") : undefined}
                      onOpenResearch={onOpenResearch}
                      verdict={verdict}
                    />
                  );
                })}
              </ul>
            )}
            {passedReads.length > 0 ? (
              <>
                <h4 className="morning-scan-subheader">
                  Scanned · no buy signal ({passedReads.length})
                </h4>
                <ul className="morning-scan-idea-list">
                  {passedReads.map((verdict) => {
                    const isDiscovered = !watchSet.has(verdict.symbol.toUpperCase());
                    return (
                      <VerdictRow
                        isDiscovered={isDiscovered}
                        key={verdict.symbol}
                        muted
                        onAddToWatchlist={isDiscovered ? onAddToWatchlist : undefined}
                        onOpenResearch={onOpenResearch}
                        verdict={verdict}
                      />
                    );
                  })}
                </ul>
              </>
            ) : null}
          </div>

          <div className="morning-scan-column">
            <h3 className="morning-scan-column-header">Holdings review</h3>
            {holdingsRows.length === 0 ? (
              <p className="morning-scan-empty">No current holdings to review.</p>
            ) : (
              <ul className="morning-scan-idea-list">
                {holdingsRows.map((row) =>
                  row.verdict ? (
                    <VerdictRow
                      approveLabel={
                        onApproveIdea &&
                        verdictActionKind(row.verdict.action, row.verdict.rating) === "sell"
                          ? "Review exit in Quant"
                          : undefined
                      }
                      key={row.symbol}
                      onApprove={
                        onApproveIdea &&
                        verdictActionKind(row.verdict.action, row.verdict.rating) === "sell"
                          ? () => onApproveIdea(row.symbol, "sell")
                          : undefined
                      }
                      onOpenResearch={onOpenResearch}
                      verdict={row.verdict}
                    />
                  ) : (
                    <li className="morning-scan-idea-row is-muted" key={row.symbol}>
                      <div className="morning-scan-idea-main">
                        <strong className="morning-scan-symbol">{row.symbol}</strong>
                        <span className="morning-scan-not-scanned">not scanned yet</span>
                        <span className="morning-scan-row-actions">
                          <button
                            className="morning-scan-row-button"
                            disabled={
                              scanState.phase === "starting" ||
                              (scanState.phase === "scanning" &&
                                scanState.symbols.includes(row.symbol))
                            }
                            onClick={() => handleScanSymbol(row.symbol)}
                            type="button"
                          >
                            {scanState.phase === "scanning" &&
                            scanState.symbols.includes(row.symbol)
                              ? "Scanning…"
                              : "Scan"}
                          </button>
                        </span>
                      </div>
                    </li>
                  )
                )}
              </ul>
            )}
          </div>
        </div>
      ) : null}
    </section>
  );
}

// -----------------------------------------------------------------------------
// Row
// -----------------------------------------------------------------------------

function VerdictRow({
  verdict,
  approveLabel,
  isDiscovered = false,
  muted = false,
  onAddToWatchlist,
  onApprove,
  onOpenResearch
}: {
  verdict: ScanVerdict;
  approveLabel?: string;
  /** True when the symbol is neither held nor watched — i.e. came from Discover. */
  isDiscovered?: boolean;
  /** Quieter treatment for "scanned, no buy signal" rows. */
  muted?: boolean;
  /** Adds the symbol to the watchlist; only rendered on discovered rows. */
  onAddToWatchlist?: (symbol: string) => void;
  onApprove?: () => void;
  onOpenResearch?: (symbol: string) => void;
}) {
  const kind = verdictActionKind(verdict.action, verdict.rating);
  const confidence = formatConfidence(verdict.confidence);
  const pillLabel = (verdict.action ?? verdict.rating ?? "—").toUpperCase();
  const showWatchButton = isDiscovered && onAddToWatchlist;

  return (
    <li className={muted ? "morning-scan-idea-row is-muted" : "morning-scan-idea-row"}>
      <div className="morning-scan-idea-main">
        <strong className="morning-scan-symbol">{verdict.symbol}</strong>
        <span className={`morning-scan-action-pill is-${kind}`}>{pillLabel}</span>
        {isDiscovered ? <span className="morning-scan-tag-discovered">discovered</span> : null}
        {confidence ? <span className="morning-scan-confidence">{confidence}</span> : null}
        <span className="morning-scan-age" title={verdict.run_created_at}>
          {formatAge(verdict.run_created_at)}
        </span>
      </div>
      {verdict.thesis ? (
        <p className="morning-scan-thesis" title={verdict.thesis}>
          {verdict.thesis}
        </p>
      ) : null}
      {onApprove || onOpenResearch || showWatchButton ? (
        <div className="morning-scan-row-actions">
          {onApprove && approveLabel ? (
            <button className="morning-scan-row-button primary" onClick={onApprove} type="button">
              {approveLabel}
            </button>
          ) : null}
          {onOpenResearch ? (
            <button
              className="morning-scan-row-button"
              onClick={() => onOpenResearch(verdict.symbol)}
              type="button"
            >
              Research
            </button>
          ) : null}
          {showWatchButton ? (
            <button
              className="morning-scan-watch-button"
              onClick={() => onAddToWatchlist(verdict.symbol)}
              title="Add to watchlist"
              type="button"
            >
              + watch
            </button>
          ) : null}
        </div>
      ) : null}
    </li>
  );
}

// -----------------------------------------------------------------------------
// Opportunity board row (quick-scan read)
// -----------------------------------------------------------------------------

function OpportunityRow({
  read,
  isHeld,
  isWatched,
  isDeepDiveBusy,
  isDeepDiving,
  onAddToWatchlist,
  onApproveIdea,
  onDeepDive
}: {
  read: QuickScanResult;
  isHeld: boolean;
  isWatched: boolean;
  /** True while a committee start request is pending (Deep dive disabled). */
  isDeepDiveBusy: boolean;
  /** True while THIS symbol's committee run is in flight. */
  isDeepDiving: boolean;
  onAddToWatchlist?: (symbol: string) => void;
  onApproveIdea?: (symbol: string, side: "buy" | "sell") => void;
  onDeepDive: (symbol: string) => void;
}) {
  const conviction = Math.max(0, Math.min(100, Math.round(read.conviction)));
  // A held symbol the screener says to avoid is an exit idea, not a buy.
  const isExit = isHeld && read.stance === "avoid";
  const isDiscovered = !isHeld && !isWatched;
  const tooltip = read.risk ? `${read.thesis}\nRISK: ${read.risk}` : read.thesis;

  return (
    <li className="morning-scan-opp-row">
      <div className="morning-scan-opp-main">
        <strong className="morning-scan-symbol">{read.symbol}</strong>
        <span className={`morning-scan-opp-stance-pill is-${read.stance}`}>
          {read.stance}
          <span className="morning-scan-opp-stance-num">{conviction}</span>
        </span>
        {isHeld ? <span className="morning-scan-opp-held-tag">held</span> : null}
        {isDiscovered ? <span className="morning-scan-tag-discovered">discovered</span> : null}
        <span aria-hidden className="morning-scan-opp-conviction-bar">
          <span
            className={`morning-scan-opp-conviction-fill is-${read.stance}`}
            style={{ width: `${conviction}%` }}
          />
        </span>
        <span className="morning-scan-opp-thesis" title={tooltip}>
          {read.thesis}
        </span>
        {read.catalyst ? (
          <span className="morning-scan-opp-catalyst" title={read.catalyst}>
            catalyst: {read.catalyst}
          </span>
        ) : null}
        <span className="morning-scan-opp-age" title={read.created_at}>
          {formatAge(read.created_at)}
        </span>
      </div>
      <div className="morning-scan-opp-row-actions">
        <button
          className="morning-scan-row-button"
          disabled={isDeepDiveBusy || isDeepDiving}
          onClick={() => onDeepDive(read.symbol)}
          title="Run the full agent committee on this symbol (~minutes); the verdict lands in the columns below"
          type="button"
        >
          {isDeepDiving ? "Deep diving…" : "Deep dive"}
        </button>
        {onApproveIdea ? (
          <button
            className="morning-scan-row-button primary"
            onClick={() => onApproveIdea(read.symbol, isExit ? "sell" : "buy")}
            type="button"
          >
            {isExit ? "Review exit in Quant" : "Review in Quant"}
          </button>
        ) : null}
        {!isWatched && onAddToWatchlist ? (
          <button
            className="morning-scan-watch-button"
            onClick={() => onAddToWatchlist(read.symbol)}
            title="Add to watchlist"
            type="button"
          >
            + watch
          </button>
        ) : null}
      </div>
    </li>
  );
}
