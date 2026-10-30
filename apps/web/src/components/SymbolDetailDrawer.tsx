"use client";

/**
 * SymbolDetailDrawer — the universal "tell me about this ticker" surface.
 *
 * Mounted once in MarketShell. Slides in from the right whenever something
 * sets `symbol` to a non-null value (a watchlist row, a holdings card, a
 * mover chip, a news item, a pending intent, an agent row, …).
 *
 * Contract — the drawer fetches its own data on open. Callers pass:
 *   - `symbol`                 — null hides the drawer; non-null opens it
 *   - `onClose`                — clears the drawer
 *   - `onOpenResearch`         — caller is expected to switch to the Research tab
 *   - `onOpenQuantWithIntent`  — caller switches to Quant; side hint is for future
 *                                 trade-ticket preload (no Quant prefill API yet)
 *
 * Sections (top → bottom):
 *   1. header        — symbol + company name + live dot + open-in-research + close
 *   2. price card    — big last, inline change, day-range bar, vol + range strip
 *   3. mini chart    — bespoke <MiniChart>, 140px, color by net change
 *   4. agent verdict — colored verdict pill + confidence bar + thesis preview
 *   5. your position — 2-col grid (qty/avg/cost vs value/PnL) + manage CTA
 *   6. recent news   — Finnhub via /api/news, with row tints + ext-link affordance
 *   7. action row    — sticky Buy / Sell + watcher link
 *
 * Each section has its own loading / empty / error state so a single
 * upstream failure doesn't blank the whole panel.
 */

import { useEffect, useMemo, useState } from "react";

import { CreateWatcherModal } from "@/components/CreateWatcherModal";
import {
  listPortfolioHoldings,
  listRunEvents,
  listRuns,
  listSymbolNews
} from "@/lib/api";
import { WATCHLIST } from "@/data/watchlist";
import type {
  MarketDataSnapshot,
  NormalizedMarketBar
} from "@/lib/market-data";
import type {
  NewsItem,
  PortfolioHolding,
  RunEvent,
  RunSummary
} from "@/lib/types";

export type SymbolDetailDrawerProps = {
  /** Symbol to display; `null` hides the drawer. */
  symbol: string | null;
  onClose: () => void;
  /** Switch to Research tab focused on this symbol. */
  onOpenResearch: (symbol: string) => void;
  /** Switch to Quant tab; side is a hint for future ticket prefill. */
  onOpenQuantWithIntent: (input: { symbol: string; side: "buy" | "sell" }) => void;
};

// -----------------------------------------------------------------------------
// Formatters
// -----------------------------------------------------------------------------

const fmtMoneyAbs = (n: number) =>
  n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 });

const fmtMoneySigned = (n: number) =>
  (n >= 0 ? "+" : "") +
  n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 });

const fmtPctSigned = (n: number) => `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`;

function fmtVolume(value: number): string {
  if (value >= 1_000_000_000) return `${(value / 1_000_000_000).toFixed(1)}B`;
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
  return value.toString();
}

function fmtRelativeTime(iso: string | null): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";

  const diffMs = Date.now() - date.getTime();
  const hours = Math.floor(diffMs / (60 * 60 * 1000));
  const days = Math.floor(diffMs / (24 * 60 * 60 * 1000));

  if (hours < 1) return "just now";
  if (hours < 24) return `${hours}h ago`;
  if (days < 7) return `${days}d ago`;
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function fmtNewsTime(iso: string | null): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";

  const now = Date.now();
  const sameDay =
    new Date(now).toDateString() === date.toDateString();

  if (sameDay) {
    return date.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
  }
  return date.toLocaleDateString("en-US", { weekday: "short" }) +
    " " +
    date.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
}

// Find the company name from the local watchlist; fall back to the raw symbol.
function lookupName(symbol: string): string {
  const upper = symbol.toUpperCase();
  const hit = WATCHLIST.find((entry) => entry.symbol.toUpperCase() === upper);
  return hit?.name ?? symbol;
}

// Map a free-form verdict action to a colored pill bucket.
function pillVariant(action: string | null, rating: string | null): "buy" | "hold" | "sell" {
  const value = `${action ?? ""} ${rating ?? ""}`.toLowerCase();
  if (/sell|short|reduce|trim|underperform|negative/.test(value)) return "sell";
  if (/buy|long|accumulate|add|overweight|positive|outperform/.test(value)) return "buy";
  return "hold";
}

// -----------------------------------------------------------------------------
// Per-section state types
// -----------------------------------------------------------------------------

type SnapshotState =
  | { phase: "loading" }
  | { phase: "loaded"; snapshot: MarketDataSnapshot; prevClose: number | null }
  | { phase: "error"; message: string };

type VerdictState =
  | { phase: "loading" }
  | { phase: "none" }
  | {
      phase: "loaded";
      run: RunSummary;
      rating: string | null;
      action: string | null;
      thesis: string | null;
      confidence: number | null;
      decisionAt: string | null;
    }
  | { phase: "error"; message: string };

type PositionState =
  | { phase: "loading" }
  | { phase: "none" }
  | {
      phase: "loaded";
      holding: PortfolioHolding;
      pnl: number | null;
      pnlPct: number | null;
    }
  | { phase: "error"; message: string }
  | { phase: "no-creds" };

type NewsState =
  | { phase: "loading" }
  | { phase: "loaded"; items: NewsItem[] }
  | { phase: "no-key" }
  | { phase: "error"; message: string };

type MiniChartState =
  | { phase: "loading" }
  | { phase: "loaded"; bars: NormalizedMarketBar[] }
  | { phase: "error" };

// -----------------------------------------------------------------------------
// Root component
// -----------------------------------------------------------------------------

export function SymbolDetailDrawer({
  symbol,
  onClose,
  onOpenResearch,
  onOpenQuantWithIntent
}: SymbolDetailDrawerProps) {
  // Render an always-mounted shell so the slide-in transition can run on both
  // open and close. When `symbol` is null we still render the chrome at width
  // 0 with translateX(100%) so the animation is symmetric.
  const isOpen = symbol !== null;
  const displaySymbol = symbol ?? "";
  const displayName = symbol ? lookupName(symbol) : "";

  // Close on Esc when the drawer is open.
  useEffect(() => {
    if (!isOpen) return;
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        onClose();
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  return (
    <>
      <div
        aria-hidden="true"
        className={isOpen ? "symbol-detail-backdrop open" : "symbol-detail-backdrop"}
        onClick={onClose}
      />
      <aside
        aria-hidden={!isOpen}
        aria-label={isOpen ? `${displaySymbol} detail` : "Symbol detail"}
        className={isOpen ? "symbol-detail-drawer open" : "symbol-detail-drawer"}
        role="complementary"
      >
        <header className="symbol-detail-drawer-header">
          <div className="symbol-detail-drawer-title">
            <div className="sdd-title-row">
              <strong>{displaySymbol || "—"}</strong>
              {isOpen ? (
                <span
                  aria-label="Latest response loaded; not streaming"
                  className="sdd-live-dot"
                  title="Latest response loaded; not streaming"
                />
              ) : null}
            </div>
            <small>{displayName}</small>
          </div>
          <div className="symbol-detail-drawer-actions">
            {symbol ? (
              <button
                aria-label={`Open ${displaySymbol} in Research`}
                className="symbol-detail-drawer-iconbtn"
                onClick={() => onOpenResearch(symbol)}
                title="Open in Research"
                type="button"
              >
                {/* simple external-link glyph */}
                <span aria-hidden="true">↗</span>
              </button>
            ) : null}
            <button
              aria-label="Close symbol detail"
              className="symbol-detail-drawer-close"
              onClick={onClose}
              type="button"
            >
              <span aria-hidden="true">×</span>
            </button>
          </div>
        </header>

        <div className="symbol-detail-drawer-body">
          {symbol ? (
            <DrawerSections
              symbol={symbol}
              onOpenResearch={onOpenResearch}
              onOpenQuantWithIntent={onOpenQuantWithIntent}
            />
          ) : null}
        </div>
      </aside>
    </>
  );
}

// -----------------------------------------------------------------------------
// Sections — re-mounted on symbol change so each fetch resets cleanly
// -----------------------------------------------------------------------------

function DrawerSections({
  symbol,
  onOpenResearch,
  onOpenQuantWithIntent
}: {
  symbol: string;
  onOpenResearch: (symbol: string) => void;
  onOpenQuantWithIntent: (input: { symbol: string; side: "buy" | "sell" }) => void;
}) {
  // Forcing a key on each section bound to `symbol` makes the per-section
  // state hooks reset on symbol change without us threading deps everywhere.
  //
  // Stagger fade-in is purely CSS — see `.sdd-section[data-stagger]` which uses
  // animation-delay derived from this index attribute.
  return (
    <>
      <div className="sdd-scroll">
        <PriceCard key={`price-${symbol}`} symbol={symbol} index={0} />
        <ChartCard key={`chart-${symbol}`} symbol={symbol} index={1} />
        <VerdictCard
          key={`verdict-${symbol}`}
          symbol={symbol}
          onOpenResearch={onOpenResearch}
          index={2}
        />
        <PositionCard
          key={`pos-${symbol}`}
          symbol={symbol}
          onOpenQuantWithIntent={onOpenQuantWithIntent}
          index={3}
        />
        <NewsCard key={`news-${symbol}`} symbol={symbol} index={4} />
      </div>
      <ActionRow symbol={symbol} onOpenQuantWithIntent={onOpenQuantWithIntent} />
    </>
  );
}

// -----------------------------------------------------------------------------
// Skeleton — used as a shimmer placeholder while sections fetch
// -----------------------------------------------------------------------------

function Skeleton({ width = "100%", height = 12 }: { width?: string; height?: number }) {
  return (
    <span
      aria-hidden="true"
      className="sdd-skeleton"
      style={{ width, height: `${height}px` }}
    />
  );
}

// -----------------------------------------------------------------------------
// Price card — last, change, change %, vol, day range
// -----------------------------------------------------------------------------

function PriceCard({ symbol, index }: { symbol: string; index: number }) {
  const [state, setState] = useState<SnapshotState>({ phase: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    setState({ phase: "loading" });

    fetchSnapshot(symbol, "1M", controller.signal)
      .then((snapshot) => {
        const prevClose = secondToLastClose(snapshot.bars);
        setState({ phase: "loaded", snapshot, prevClose });
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setState({
          phase: "error",
          message: error instanceof Error ? error.message : "Snapshot unavailable"
        });
      });

    return () => controller.abort();
  }, [symbol]);

  if (state.phase === "loading") {
    return (
      <section className="sdd-section sdd-price" data-stagger={index}>
        <div className="sdd-price-row">
          <Skeleton width="140px" height={26} />
          <Skeleton width="100px" height={14} />
        </div>
        <Skeleton width="100%" height={6} />
        <div className="sdd-price-meta">
          <Skeleton width="80px" height={11} />
          <Skeleton width="160px" height={11} />
        </div>
      </section>
    );
  }

  if (state.phase === "error") {
    return (
      <section className="sdd-section sdd-price" data-stagger={index}>
        <p className="sdd-empty error">{state.message}</p>
      </section>
    );
  }

  const { snapshot, prevClose } = state;
  const last = snapshot.quote.last;
  const reference = prevClose ?? snapshot.quote.dayOpen;
  const change = last - reference;
  const changePct = reference === 0 ? 0 : (change / reference) * 100;
  const direction = change >= 0 ? "is-positive" : "is-negative";

  // Day-range bar position (clamped 0..100). When low==high we center the dot.
  const range = snapshot.quote.dayHigh - snapshot.quote.dayLow;
  const rangePct =
    range > 0
      ? Math.max(0, Math.min(100, ((last - snapshot.quote.dayLow) / range) * 100))
      : 50;

  return (
    <section className="sdd-section sdd-price" data-stagger={index}>
      <div className="sdd-price-row">
        <span className="sdd-mono sdd-price-large">${last.toFixed(2)}</span>
        <span className={`sdd-mono sdd-price-change ${direction}`}>
          {change >= 0 ? "+" : ""}
          {change.toFixed(2)} {fmtPctSigned(changePct)}
        </span>
      </div>
      <div
        aria-label={`Day range ${snapshot.quote.dayLow.toFixed(2)} to ${snapshot.quote.dayHigh.toFixed(2)}, last ${last.toFixed(2)}`}
        className="sdd-day-range-bar"
        role="img"
      >
        <span className="sdd-day-range-track" />
        <span
          className={`sdd-day-range-dot ${direction}`}
          style={{ left: `${rangePct}%` }}
        />
      </div>
      <div className="sdd-price-meta">
        <span className="sdd-mono">{snapshot.quote.dayLow.toFixed(2)}</span>
        <span className="sdd-price-meta-mid">
          Vol <span className="sdd-mono">{fmtVolume(snapshot.quote.dayVolume)}</span>
        </span>
        <span className="sdd-mono">{snapshot.quote.dayHigh.toFixed(2)}</span>
      </div>
    </section>
  );
}

// -----------------------------------------------------------------------------
// Chart — bespoke MiniChart, 140px tall, single line, color by net change
// -----------------------------------------------------------------------------

function ChartCard({ symbol, index }: { symbol: string; index: number }) {
  return (
    <section className="sdd-section sdd-chart" aria-label="Recent chart" data-stagger={index}>
      <MiniChart symbol={symbol} range="5D" />
    </section>
  );
}

/**
 * MiniChart — lightweight SVG line chart for the drawer.
 *
 * Why bespoke instead of reusing <ChartWorkspace>? ChartWorkspace ships with
 * its own toolbar, indicators, range tabs, and is sized for full-pane use.
 * Stripping it down to 140px tall with no interaction was uglier than just
 * drawing a single SVG polyline against the same /api/market-data endpoint.
 */
function MiniChart({ symbol, range }: { symbol: string; range: "5D" | "1M" }) {
  const [state, setState] = useState<MiniChartState>({ phase: "loading" });
  const [hover, setHover] = useState<{ idx: number; x: number; y: number } | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setState({ phase: "loading" });

    fetchSnapshot(symbol, range, controller.signal)
      .then((snapshot) => {
        setState({ phase: "loaded", bars: snapshot.bars });
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        // Swallow detail — the drawer's price card surfaces the real error.
        void error;
        setState({ phase: "error" });
      });

    return () => controller.abort();
  }, [symbol, range]);

  // Pre-compute the polyline + bounds once we have data.
  const geom = useMemo(() => {
    if (state.phase !== "loaded" || state.bars.length < 2) return null;
    const bars = state.bars;
    const closes = bars.map((b) => b.close);
    const min = Math.min(...closes);
    const max = Math.max(...closes);
    const span = max - min || 1;

    // Viewbox coordinate space: 100 wide × 40 tall. The SVG itself uses
    // preserveAspectRatio="none" so it stretches to fit the container.
    const points = bars.map((bar, i) => {
      const x = (i / (bars.length - 1)) * 100;
      const y = 40 - ((bar.close - min) / span) * 36 - 2; // 2px top/bottom inset
      return { x, y, close: bar.close, at: bar.timestamp };
    });

    const net = bars[bars.length - 1].close - bars[0].close;
    const direction: "up" | "down" | "flat" =
      net > 0 ? "up" : net < 0 ? "down" : "flat";
    const last = points[points.length - 1];
    return { points, direction, last, min, max };
  }, [state]);

  if (state.phase === "loading") {
    return (
      <div className="sdd-mini-chart-shell" aria-busy="true">
        <Skeleton width="100%" height={140} />
      </div>
    );
  }

  if (state.phase === "error" || !geom) {
    return (
      <div className="sdd-mini-chart-shell">
        <p className="sdd-empty">Chart unavailable.</p>
      </div>
    );
  }

  const pathD = `M ${geom.points.map((p) => `${p.x.toFixed(2)},${p.y.toFixed(2)}`).join(" L ")}`;
  const areaD = `${pathD} L 100,40 L 0,40 Z`;
  const dirClass =
    geom.direction === "down" ? "is-negative" : geom.direction === "up" ? "is-positive" : "is-flat";

  return (
    <div className="sdd-mini-chart-shell">
      <svg
        aria-label={`${symbol} ${range} price chart`}
        className={`sdd-mini-chart-svg ${dirClass}`}
        preserveAspectRatio="none"
        role="img"
        viewBox="0 0 100 40"
        onMouseLeave={() => setHover(null)}
        onMouseMove={(e) => {
          const rect = e.currentTarget.getBoundingClientRect();
          const px = ((e.clientX - rect.left) / rect.width) * 100;
          // Snap to nearest data point.
          let bestIdx = 0;
          let bestDist = Infinity;
          for (let i = 0; i < geom.points.length; i++) {
            const d = Math.abs(geom.points[i].x - px);
            if (d < bestDist) {
              bestDist = d;
              bestIdx = i;
            }
          }
          const p = geom.points[bestIdx];
          setHover({ idx: bestIdx, x: p.x, y: p.y });
        }}
      >
        <path className="sdd-mini-chart-area" d={areaD} />
        <path className="sdd-mini-chart-line" d={pathD} />
        {/* Last-point dot */}
        <circle
          className="sdd-mini-chart-dot"
          cx={geom.last.x}
          cy={geom.last.y}
          r="1.2"
        />
        {hover ? (
          <>
            <line
              className="sdd-mini-chart-crosshair"
              x1={hover.x}
              x2={hover.x}
              y1={0}
              y2={40}
            />
            <circle
              className="sdd-mini-chart-hover-dot"
              cx={hover.x}
              cy={hover.y}
              r="1.4"
            />
          </>
        ) : null}
      </svg>
      {hover ? (
        <div
          className="sdd-mini-chart-tooltip"
          style={{ left: `calc(${hover.x}% + 0px)` }}
        >
          <span className="sdd-mono">
            ${geom.points[hover.idx].close.toFixed(2)}
          </span>
          <span className="sdd-mini-chart-tooltip-when">
            {fmtTooltipWhen(geom.points[hover.idx].at)}
          </span>
        </div>
      ) : null}
    </div>
  );
}

function fmtTooltipWhen(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

// -----------------------------------------------------------------------------
// Agent verdict — latest run + its decision.created event
// -----------------------------------------------------------------------------

function VerdictCard({
  symbol,
  onOpenResearch,
  index
}: {
  symbol: string;
  onOpenResearch: (symbol: string) => void;
  index: number;
}) {
  const [state, setState] = useState<VerdictState>({ phase: "loading" });

  useEffect(() => {
    let isCurrent = true;
    setState({ phase: "loading" });

    listRuns({ ticker: symbol, limit: 1 })
      .then(async (runs) => {
        if (!isCurrent) return;
        const run = runs[0];
        if (!run) {
          setState({ phase: "none" });
          return;
        }
        try {
          const events = await listRunEvents(run.run_id);
          if (!isCurrent) return;
          const decision = events.find((event) => event.type === "decision.created");
          setState({
            phase: "loaded",
            run,
            rating: extractStringField(decision, "rating") ?? run.final_rating,
            action: extractStringField(decision, "action") ?? run.final_action,
            thesis: extractStringField(decision, "thesis"),
            confidence: extractNumberField(decision, "confidence"),
            decisionAt: decision?.created_at ?? run.updated_at
          });
        } catch (caught) {
          if (!isCurrent) return;
          // Run exists but event fetch failed — fall back to the summary fields.
          setState({
            phase: "loaded",
            run,
            rating: run.final_rating,
            action: run.final_action,
            thesis: null,
            confidence: null,
            decisionAt: run.updated_at
          });
          // Swallow — the surface still renders something useful.
          void caught;
        }
      })
      .catch((caught: Error) => {
        if (!isCurrent) return;
        setState({
          phase: "error",
          message: caught instanceof Error ? caught.message : "Verdict unavailable"
        });
      });

    return () => {
      isCurrent = false;
    };
  }, [symbol]);

  return (
    <section className="sdd-section sdd-verdict" data-stagger={index}>
      <header className="sdd-section-header">
        <span className="panel-kicker">Agent verdict</span>
      </header>

      {state.phase === "loading" ? (
        <div className="sdd-verdict-skeleton">
          <Skeleton width="64px" height={22} />
          <Skeleton width="100%" height={6} />
          <Skeleton width="92%" height={11} />
          <Skeleton width="80%" height={11} />
        </div>
      ) : null}
      {state.phase === "error" ? <p className="sdd-empty error">{state.message}</p> : null}
      {state.phase === "none" ? (
        <div className="sdd-verdict-empty">
          <p className="sdd-empty">No research yet on {symbol}.</p>
          <button
            aria-label={`Run committee for ${symbol}`}
            className="secondary-button compact"
            onClick={() => onOpenResearch(symbol)}
            type="button"
          >
            Run committee →
          </button>
        </div>
      ) : null}

      {state.phase === "loaded" ? (
        <>
          <div className="sdd-verdict-headline">
            <span
              className={`sdd-verdict-pill sdd-verdict-pill-${pillVariant(
                state.action,
                state.rating
              )}`}
            >
              {(state.action ?? state.rating ?? "—").toString().toUpperCase()}
            </span>
            <span className="sdd-verdict-when">{fmtRelativeTime(state.decisionAt)}</span>
          </div>
          {state.confidence !== null ? (
            <div className="sdd-confidence">
              <div
                className="sdd-confidence-bar"
                role="progressbar"
                aria-label="Confidence"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={Math.round(state.confidence * 100)}
              >
                <div
                  className={`sdd-confidence-fill sdd-confidence-fill-${pillVariant(
                    state.action,
                    state.rating
                  )}`}
                  style={{ width: `${Math.max(0, Math.min(100, state.confidence * 100))}%` }}
                />
              </div>
              <span className="sdd-mono sdd-confidence-pct">
                {Math.round(state.confidence * 100)}%
              </span>
            </div>
          ) : null}
          {state.thesis ? (
            <p className="sdd-verdict-thesis">
              &ldquo;{state.thesis}&rdquo;
            </p>
          ) : (
            <p className="sdd-empty">Thesis not recorded for this run.</p>
          )}
          <a
            aria-label={`Open research for ${symbol}`}
            className="sdd-link"
            href="#"
            onClick={(e) => {
              e.preventDefault();
              onOpenResearch(symbol);
            }}
          >
            Open research →
          </a>
        </>
      ) : null}
    </section>
  );
}

// -----------------------------------------------------------------------------
// Position — your holding from Alpaca
// -----------------------------------------------------------------------------

function PositionCard({
  symbol,
  onOpenQuantWithIntent,
  index
}: {
  symbol: string;
  onOpenQuantWithIntent: (input: { symbol: string; side: "buy" | "sell" }) => void;
  index: number;
}) {
  const [state, setState] = useState<PositionState>({ phase: "loading" });

  useEffect(() => {
    let isCurrent = true;
    setState({ phase: "loading" });

    listPortfolioHoldings("alpaca-paper-broker")
      .then((catalog) => {
        if (!isCurrent) return;
        const upper = symbol.toUpperCase();
        const holding = catalog.holdings.find(
          (h) => (h.symbol ?? "").toUpperCase() === upper
        );
        if (!holding) {
          setState({ phase: "none" });
          return;
        }
        const pnl =
          holding.value !== null && holding.cost_basis !== null
            ? holding.value - holding.cost_basis
            : null;
        const pnlPct =
          holding.value !== null &&
          holding.cost_basis !== null &&
          holding.cost_basis !== 0
            ? ((holding.value - holding.cost_basis) / holding.cost_basis) * 100
            : null;
        setState({ phase: "loaded", holding, pnl, pnlPct });
      })
      .catch((caught: Error & { status?: number }) => {
        if (!isCurrent) return;
        if (caught.status === 403 || caught.status === 404) {
          setState({ phase: "no-creds" });
          return;
        }
        setState({
          phase: "error",
          message: caught instanceof Error ? caught.message : "Holdings unavailable"
        });
      });

    return () => {
      isCurrent = false;
    };
  }, [symbol]);

  return (
    <section className="sdd-section sdd-position" data-stagger={index}>
      <header className="sdd-section-header">
        <span className="panel-kicker">Your position</span>
      </header>

      {state.phase === "loading" ? (
        <div className="sdd-position-grid">
          <Skeleton width="60%" height={12} />
          <Skeleton width="60%" height={12} />
          <Skeleton width="60%" height={12} />
          <Skeleton width="60%" height={12} />
        </div>
      ) : null}
      {state.phase === "error" ? <p className="sdd-empty error">{state.message}</p> : null}
      {state.phase === "no-creds" ? (
        <p className="sdd-empty">Alpaca paper account not configured.</p>
      ) : null}
      {state.phase === "none" ? (
        <div className="sdd-position-empty">
          <p className="sdd-empty">You don&rsquo;t own {symbol} yet.</p>
          <button
            aria-label={`Buy ${symbol} in Quant`}
            className="secondary-button compact"
            onClick={() => onOpenQuantWithIntent({ symbol, side: "buy" })}
            type="button"
          >
            Buy in Quant →
          </button>
        </div>
      ) : null}

      {state.phase === "loaded" ? (
        <>
          <div className="sdd-position-grid">
            <div className="sdd-position-cell">
              <span className="sdd-position-label">Qty</span>
              <span className="sdd-mono sdd-position-value">
                {state.holding.quantity.toFixed(2)}
              </span>
            </div>
            <div className="sdd-position-cell">
              <span className="sdd-position-label">Value</span>
              <span className="sdd-mono sdd-position-value">
                {state.holding.value !== null ? fmtMoneyAbs(state.holding.value) : "—"}
              </span>
            </div>
            <div className="sdd-position-cell">
              <span className="sdd-position-label">Avg cost</span>
              <span className="sdd-mono sdd-position-value">
                {state.holding.cost_basis !== null && state.holding.quantity !== 0
                  ? fmtMoneyAbs(state.holding.cost_basis / state.holding.quantity)
                  : "—"}
              </span>
            </div>
            <div className="sdd-position-cell">
              <span className="sdd-position-label">P&amp;L</span>
              {state.pnl !== null && state.pnlPct !== null ? (
                <span
                  className={`sdd-mono sdd-position-value ${
                    state.pnl >= 0 ? "is-positive" : "is-negative"
                  }`}
                >
                  {fmtMoneySigned(state.pnl)} ({fmtPctSigned(state.pnlPct)})
                </span>
              ) : (
                <span className="sdd-mono sdd-position-value">—</span>
              )}
            </div>
          </div>
          <button
            aria-label={`Manage ${symbol} in Quant`}
            className="secondary-button compact sdd-position-manage"
            onClick={() => onOpenQuantWithIntent({ symbol, side: "sell" })}
            type="button"
          >
            Manage in Quant →
          </button>
        </>
      ) : null}
    </section>
  );
}

// -----------------------------------------------------------------------------
// Recent news — Finnhub
// -----------------------------------------------------------------------------

function NewsCard({ symbol, index }: { symbol: string; index: number }) {
  const [state, setState] = useState<NewsState>({ phase: "loading" });

  useEffect(() => {
    let isCurrent = true;
    setState({ phase: "loading" });

    listSymbolNews({ symbol, sinceHours: 48, limit: 5 })
      .then((catalog) => {
        if (!isCurrent) return;
        setState({ phase: "loaded", items: catalog.items });
      })
      .catch((caught: Error & { status?: number }) => {
        if (!isCurrent) return;
        if (caught.status === 503) {
          setState({ phase: "no-key" });
          return;
        }
        setState({
          phase: "error",
          message: caught instanceof Error ? caught.message : "News unavailable"
        });
      });

    return () => {
      isCurrent = false;
    };
  }, [symbol]);

  return (
    <section className="sdd-section sdd-news" data-stagger={index}>
      <header className="sdd-section-header">
        <span className="panel-kicker">Recent news</span>
      </header>

      {state.phase === "loading" ? (
        <div className="sdd-news-skeleton">
          <Skeleton width="100%" height={14} />
          <Skeleton width="92%" height={14} />
          <Skeleton width="88%" height={14} />
        </div>
      ) : null}
      {state.phase === "error" ? <p className="sdd-empty error">{state.message}</p> : null}
      {state.phase === "no-key" ? (
        <p className="sdd-empty">Set FINNHUB_API_KEY to enable news.</p>
      ) : null}
      {state.phase === "loaded" && state.items.length === 0 ? (
        <p className="sdd-empty">No news for {symbol} in the last 48 hours.</p>
      ) : null}

      {state.phase === "loaded" && state.items.length > 0 ? (
        <ul className="sdd-news-list">
          {state.items.map((n) => (
            <li className="sdd-news-row" key={n.id || `${n.published_at}-${n.headline}`}>
              <div className="sdd-news-meta">
                <span className="sdd-mono sdd-news-time">{fmtNewsTime(n.published_at)}</span>
                <span className="sdd-news-source">{n.source}</span>
              </div>
              {n.url ? (
                <a
                  aria-label={`Open story: ${n.headline}`}
                  className="sdd-news-headline"
                  href={n.url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  {n.headline}
                </a>
              ) : (
                <span className="sdd-news-headline">{n.headline}</span>
              )}
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

// -----------------------------------------------------------------------------
// Action row — Buy / Sell / Set watcher
// -----------------------------------------------------------------------------

function ActionRow({
  symbol,
  onOpenQuantWithIntent
}: {
  symbol: string;
  onOpenQuantWithIntent: (input: { symbol: string; side: "buy" | "sell" }) => void;
}) {
  const [watcherModalOpen, setWatcherModalOpen] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  useEffect(() => {
    if (!toast) return;
    const id = window.setTimeout(() => setToast(null), 3500);
    return () => window.clearTimeout(id);
  }, [toast]);

  return (
    <section className="sdd-actions sdd-actions-sticky" aria-label="Symbol actions">
      <div className="sdd-actions-buttons">
        <button
          aria-label={`Buy ${symbol}`}
          className="primary-button sdd-action-buy"
          onClick={() => onOpenQuantWithIntent({ symbol, side: "buy" })}
          type="button"
        >
          Buy
        </button>
        <button
          aria-label={`Sell ${symbol}`}
          className="primary-button sdd-action-sell"
          onClick={() => onOpenQuantWithIntent({ symbol, side: "sell" })}
          type="button"
        >
          Sell
        </button>
      </div>
      <button
        aria-label={`Set watcher for ${symbol}`}
        className="sdd-action-watcher-link"
        onClick={() => setWatcherModalOpen(true)}
        type="button"
      >
        Set watcher
      </button>
      {toast ? (
        <div className="sdd-watcher-toast" role="status">
          {toast}
        </div>
      ) : null}
      <CreateWatcherModal
        isOpen={watcherModalOpen}
        lockedSymbol={symbol}
        onClose={() => setWatcherModalOpen(false)}
        onCreated={(watcher) => {
          setToast(`Watcher armed for ${watcher.symbol}`);
        }}
      />
    </section>
  );
}

// -----------------------------------------------------------------------------
// Local helpers
// -----------------------------------------------------------------------------

async function fetchSnapshot(
  symbol: string,
  range: "1D" | "5D" | "1M" | "YTD" | "1Y" | "3Y" | "5Y" | "10Y",
  signal: AbortSignal
): Promise<MarketDataSnapshot> {
  const params = new URLSearchParams({ range, symbol });
  const response = await fetch(`/api/market-data?${params.toString()}`, { signal });

  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { error?: string } | null;
    throw new Error(payload?.error ?? `Market data request failed: ${response.status}`);
  }

  return response.json() as Promise<MarketDataSnapshot>;
}

function secondToLastClose(bars: NormalizedMarketBar[]): number | null {
  if (bars.length < 2) return null;
  return bars[bars.length - 2].close;
}

function extractStringField(event: RunEvent | undefined, key: string): string | null {
  if (!event) return null;
  const value = event.payload[key];
  return typeof value === "string" && value.length > 0 ? value : null;
}

function extractNumberField(event: RunEvent | undefined, key: string): number | null {
  if (!event) return null;
  const value = event.payload[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}
