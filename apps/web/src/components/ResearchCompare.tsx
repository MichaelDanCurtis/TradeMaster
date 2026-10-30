"use client";

/**
 * ResearchCompare — two-symbol side-by-side answer surface for the Research tab.
 *
 * Picked from ResearchWorkspace via the "Compare" toggle in its header. Lets
 * users pit two tickers head-to-head:
 *
 *   • per side: symbol picker, price card, 30-day mini chart, agent verdict,
 *               recent news (4 items)
 *   • full-width correlation strip below the two panes (Pearson on daily
 *     returns + β in both directions + overlay chart of the two normalized
 *     series starting at 100)
 *
 * Each pane fetches independently; one side erroring does not block the
 * other. Correlation is purely client-side math over the two market
 * snapshots; nothing new is required from the backend.
 */
import { useEffect, useMemo, useState } from "react";

import { listRunEvents, listRuns, listSymbolNews } from "@/lib/api";
import type { MarketDataSnapshot, NormalizedMarketBar } from "@/lib/market-data";
import type { NewsItem, RunEvent, RunSummary } from "@/lib/types";

// -----------------------------------------------------------------------------
// Public contract
// -----------------------------------------------------------------------------

export type ResearchCompareProps = {
  leftSymbol: string;
  rightSymbol: string;
  onClose: () => void;
  onChangeLeft: (sym: string) => void;
  onChangeRight: (sym: string) => void;
  onOpenSymbolDetail?: (sym: string) => void;
  /** Watchlist symbols to surface as suggestions in each picker. */
  suggestions?: string[];
};

// -----------------------------------------------------------------------------
// Side state types
// -----------------------------------------------------------------------------

type SnapshotState =
  | { phase: "loading" }
  | { phase: "loaded"; snapshot: MarketDataSnapshot }
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

type NewsState =
  | { phase: "loading" }
  | { phase: "loaded"; items: NewsItem[] }
  | { phase: "error"; message: string };

// -----------------------------------------------------------------------------
// Root
// -----------------------------------------------------------------------------

export function ResearchCompare({
  leftSymbol,
  rightSymbol,
  onClose,
  onChangeLeft,
  onChangeRight,
  onOpenSymbolDetail,
  suggestions
}: ResearchCompareProps) {
  // Per-side snapshots live in the parent so the correlation strip can read
  // both. Verdict + news state stays internal to each pane.
  const [leftSnap, setLeftSnap] = useState<SnapshotState>({ phase: "loading" });
  const [rightSnap, setRightSnap] = useState<SnapshotState>({ phase: "loading" });

  return (
    <section
      className="room-workspace-root research-compare-root-shell"
      aria-label="Research compare"
    >
      <header className="research-compare-topbar">
        <button
          type="button"
          className="secondary-button compact"
          onClick={onClose}
          aria-label="Back to single-symbol research"
        >
          ← Back to single
        </button>
        <span className="panel-kicker research-compare-kicker">Compare</span>
      </header>

      <div className="research-compare-root">
        <ComparePane
          side="left"
          symbol={leftSymbol}
          onChange={onChangeLeft}
          onOpenSymbolDetail={onOpenSymbolDetail}
          onSnapshot={setLeftSnap}
          snapshotState={leftSnap}
          suggestions={suggestions}
        />
        <ComparePane
          side="right"
          symbol={rightSymbol}
          onChange={onChangeRight}
          onOpenSymbolDetail={onOpenSymbolDetail}
          onSnapshot={setRightSnap}
          snapshotState={rightSnap}
          suggestions={suggestions}
        />
      </div>

      <CorrelationStrip
        leftSymbol={leftSymbol}
        rightSymbol={rightSymbol}
        leftSnap={leftSnap}
        rightSnap={rightSnap}
      />
    </section>
  );
}

// -----------------------------------------------------------------------------
// Per-side pane: picker + price + chart + verdict + news
// -----------------------------------------------------------------------------

function ComparePane({
  side,
  symbol,
  onChange,
  onOpenSymbolDetail,
  onSnapshot,
  snapshotState,
  suggestions
}: {
  side: "left" | "right";
  symbol: string;
  onChange: (sym: string) => void;
  onOpenSymbolDetail?: (sym: string) => void;
  onSnapshot: (state: SnapshotState) => void;
  snapshotState: SnapshotState;
  suggestions?: string[];
}) {
  // Drive snapshot fetch from this pane so the picker stays the single source
  // of truth for "current side symbol".
  useEffect(() => {
    if (!symbol) {
      onSnapshot({ phase: "loading" });
      return;
    }
    const controller = new AbortController();
    onSnapshot({ phase: "loading" });

    fetchSnapshot(symbol, "1M", controller.signal)
      .then((snapshot) => {
        if (controller.signal.aborted) return;
        onSnapshot({ phase: "loaded", snapshot });
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        onSnapshot({
          phase: "error",
          message: error instanceof Error ? error.message : "Snapshot unavailable"
        });
      });

    return () => controller.abort();
    // onSnapshot is stable enough — the parent passes a setState binding
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbol]);

  return (
    <section className={`research-compare-side research-compare-side-${side}`} aria-label={`${side} pane`}>
      <SymbolPicker
        side={side}
        current={symbol}
        onChange={onChange}
        suggestions={suggestions}
      />
      <PricePane symbol={symbol} state={snapshotState} onOpenDetail={onOpenSymbolDetail} />
      <MiniChartPane symbol={symbol} state={snapshotState} />
      <VerdictPane symbol={symbol} />
      <NewsPane symbol={symbol} />
    </section>
  );
}

// -----------------------------------------------------------------------------
// Symbol picker — small input with on-Enter submit + watchlist suggestions
// -----------------------------------------------------------------------------

function SymbolPicker({
  side,
  current,
  onChange,
  suggestions
}: {
  side: "left" | "right";
  current: string;
  onChange: (sym: string) => void;
  suggestions?: string[];
}) {
  const [draft, setDraft] = useState(current);
  useEffect(() => {
    setDraft(current);
  }, [current]);

  function submit() {
    const next = draft.trim().toUpperCase();
    if (next && next !== current) {
      onChange(next);
    }
  }

  const trimmedDraft = draft.trim().toUpperCase();
  const visibleSuggestions = (suggestions ?? []).filter(
    (sym) => sym.toUpperCase() !== current.toUpperCase()
  );

  return (
    <div className="research-compare-picker" aria-label={`${side} symbol picker`}>
      <label className="research-compare-picker-label">
        <span>{side === "left" ? "Left" : "Right"} symbol</span>
        <input
          type="text"
          className="research-compare-picker-input"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onBlur={submit}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              submit();
            }
          }}
          spellCheck={false}
          autoCorrect="off"
          autoCapitalize="characters"
          aria-label={`${side} symbol`}
        />
      </label>
      {visibleSuggestions.length > 0 ? (
        <ul className="research-compare-picker-suggestions" aria-label="Suggestions">
          {visibleSuggestions.slice(0, 6).map((sym) => {
            const isActive = sym.toUpperCase() === trimmedDraft;
            return (
              <li key={sym}>
                <button
                  type="button"
                  className={`research-compare-picker-chip${isActive ? " active" : ""}`}
                  onClick={() => {
                    setDraft(sym);
                    onChange(sym);
                  }}
                >
                  {sym}
                </button>
              </li>
            );
          })}
        </ul>
      ) : null}
    </div>
  );
}

// -----------------------------------------------------------------------------
// Price card
// -----------------------------------------------------------------------------

function PricePane({
  symbol,
  state,
  onOpenDetail
}: {
  symbol: string;
  state: SnapshotState;
  onOpenDetail?: (sym: string) => void;
}) {
  if (state.phase === "loading") {
    return (
      <article className="research-compare-card research-compare-price" aria-busy="true">
        <span className="research-compare-skel" style={{ width: "60%", height: 22 }} />
        <span className="research-compare-skel" style={{ width: "40%", height: 14 }} />
      </article>
    );
  }
  if (state.phase === "error") {
    return (
      <article className="research-compare-card research-compare-price">
        <p className="research-compare-empty">Price unavailable. {state.message}</p>
      </article>
    );
  }

  const bars = state.snapshot.bars;
  const last = state.snapshot.quote.last;
  const prevClose = bars.length >= 2 ? bars[bars.length - 2].close : state.snapshot.quote.dayOpen;
  const change = last - prevClose;
  const pct = prevClose === 0 ? 0 : (change / prevClose) * 100;
  const direction = change >= 0 ? "is-positive" : "is-negative";

  return (
    <article className="research-compare-card research-compare-price">
      <div className="research-compare-price-row">
        <button
          type="button"
          className="research-compare-symbol"
          onClick={() => onOpenDetail?.(symbol)}
          aria-label={`Open ${symbol} detail`}
        >
          {symbol}
        </button>
        <span className="research-compare-last">${last.toFixed(2)}</span>
      </div>
      <div className={`research-compare-change ${direction}`}>
        <span>{change >= 0 ? "+" : ""}{change.toFixed(2)}</span>
        <span>{change >= 0 ? "+" : ""}{pct.toFixed(2)}%</span>
      </div>
    </article>
  );
}

// -----------------------------------------------------------------------------
// Mini chart (30 days)
// -----------------------------------------------------------------------------

function MiniChartPane({ symbol, state }: { symbol: string; state: SnapshotState }) {
  const geom = useMemo(() => {
    if (state.phase !== "loaded" || state.snapshot.bars.length < 2) return null;
    const bars = state.snapshot.bars;
    const closes = bars.map((b) => b.close);
    const min = Math.min(...closes);
    const max = Math.max(...closes);
    const span = max - min || 1;

    const points = bars.map((bar, i) => {
      const x = (i / (bars.length - 1)) * 100;
      const y = 40 - ((bar.close - min) / span) * 36 - 2;
      return { x, y };
    });
    const net = bars[bars.length - 1].close - bars[0].close;
    const direction: "up" | "down" | "flat" =
      net > 0 ? "up" : net < 0 ? "down" : "flat";
    return { points, direction };
  }, [state]);

  if (state.phase === "loading") {
    return (
      <article className="research-compare-card research-compare-chart" aria-busy="true">
        <span className="research-compare-skel" style={{ width: "100%", height: 80 }} />
      </article>
    );
  }
  if (state.phase === "error" || !geom) {
    return (
      <article className="research-compare-card research-compare-chart">
        <p className="research-compare-empty">Chart unavailable.</p>
      </article>
    );
  }

  const pathD = `M ${geom.points.map((p) => `${p.x.toFixed(2)},${p.y.toFixed(2)}`).join(" L ")}`;
  const dirClass =
    geom.direction === "down" ? "is-negative" : geom.direction === "up" ? "is-positive" : "is-flat";

  return (
    <article className="research-compare-card research-compare-chart">
      <svg
        aria-label={`${symbol} 30-day chart`}
        className={`research-compare-chart-svg ${dirClass}`}
        preserveAspectRatio="none"
        role="img"
        viewBox="0 0 100 40"
      >
        <path className="research-compare-chart-line" d={pathD} />
      </svg>
    </article>
  );
}

// -----------------------------------------------------------------------------
// Agent verdict (latest run + decision.created event)
// -----------------------------------------------------------------------------

function VerdictPane({ symbol }: { symbol: string }) {
  const [state, setState] = useState<VerdictState>({ phase: "loading" });

  useEffect(() => {
    if (!symbol) return;
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
            rating: run.final_rating ?? extractStringField(decision, "rating"),
            action: run.final_action ?? extractStringField(decision, "action"),
            thesis: extractStringField(decision, "thesis"),
            confidence: extractConfidence(decision),
            decisionAt: decision?.created_at ?? run.updated_at
          });
        } catch (error) {
          if (!isCurrent) return;
          setState({
            phase: "error",
            message: error instanceof Error ? error.message : "Verdict unavailable"
          });
        }
      })
      .catch((error: unknown) => {
        if (!isCurrent) return;
        setState({
          phase: "error",
          message: error instanceof Error ? error.message : "Verdict unavailable"
        });
      });

    return () => {
      isCurrent = false;
    };
  }, [symbol]);

  if (state.phase === "loading") {
    return (
      <article className="research-compare-card research-compare-verdict" aria-busy="true">
        <span className="research-compare-kicker-row">Agent verdict</span>
        <span className="research-compare-skel" style={{ width: "70%", height: 14 }} />
        <span className="research-compare-skel" style={{ width: "100%", height: 12 }} />
      </article>
    );
  }
  if (state.phase === "error") {
    return (
      <article className="research-compare-card research-compare-verdict">
        <span className="research-compare-kicker-row">Agent verdict</span>
        <p className="research-compare-empty">{state.message}</p>
      </article>
    );
  }
  if (state.phase === "none") {
    return (
      <article className="research-compare-card research-compare-verdict">
        <span className="research-compare-kicker-row">Agent verdict</span>
        <p className="research-compare-empty">
          No research run yet — run committee for {symbol}.
        </p>
      </article>
    );
  }

  const tone = ratingTone(state.rating);
  const confidenceLabel = state.confidence !== null ? `${Math.round(state.confidence)}%` : null;
  return (
    <article className={`research-compare-card research-compare-verdict ${tone}`}>
      <span className="research-compare-kicker-row">Agent verdict</span>
      <p className="research-compare-verdict-line">
        <strong className="research-compare-verdict-rating">{state.rating ?? state.action ?? "—"}</strong>
        {confidenceLabel ? <span> · {confidenceLabel} confidence</span> : null}
        <span className="research-compare-verdict-when"> · {formatRel(state.decisionAt)}</span>
      </p>
      {state.thesis ? (
        <p className="research-compare-verdict-thesis">{truncate(state.thesis, 180)}</p>
      ) : null}
    </article>
  );
}

// -----------------------------------------------------------------------------
// News pane
// -----------------------------------------------------------------------------

function NewsPane({ symbol }: { symbol: string }) {
  const [state, setState] = useState<NewsState>({ phase: "loading" });

  useEffect(() => {
    if (!symbol) return;
    let isCurrent = true;
    setState({ phase: "loading" });

    listSymbolNews({ symbol, sinceHours: 48, limit: 4 })
      .then((catalog) => {
        if (!isCurrent) return;
        setState({ phase: "loaded", items: catalog.items });
      })
      .catch((error: unknown) => {
        if (!isCurrent) return;
        setState({
          phase: "error",
          message: error instanceof Error ? error.message : "News feed unavailable"
        });
      });

    return () => {
      isCurrent = false;
    };
  }, [symbol]);

  if (state.phase === "loading") {
    return (
      <article className="research-compare-card research-compare-news" aria-busy="true">
        <span className="research-compare-kicker-row">Recent news</span>
        <span className="research-compare-skel" style={{ width: "90%", height: 12 }} />
        <span className="research-compare-skel" style={{ width: "80%", height: 12 }} />
      </article>
    );
  }
  if (state.phase === "error") {
    return (
      <article className="research-compare-card research-compare-news">
        <span className="research-compare-kicker-row">Recent news</span>
        <p className="research-compare-empty">News feed unavailable.</p>
      </article>
    );
  }
  if (state.items.length === 0) {
    return (
      <article className="research-compare-card research-compare-news">
        <span className="research-compare-kicker-row">Recent news</span>
        <p className="research-compare-empty">No recent headlines.</p>
      </article>
    );
  }

  return (
    <article className="research-compare-card research-compare-news">
      <span className="research-compare-kicker-row">Recent news</span>
      <ul className="research-compare-news-list">
        {state.items.map((item) => (
          <li key={item.id} className="research-compare-news-row">
            <span className="research-compare-news-when">{formatNewsWhen(item.published_at)}</span>
            <span className="research-compare-news-source">{item.source}</span>
            <span className="research-compare-news-headline">
              {item.url ? (
                <a href={item.url} target="_blank" rel="noopener noreferrer">
                  {truncate(item.headline, 80)}
                </a>
              ) : (
                truncate(item.headline, 80)
              )}
            </span>
          </li>
        ))}
      </ul>
    </article>
  );
}

// -----------------------------------------------------------------------------
// Correlation strip — Pearson, β both ways, overlay chart
// -----------------------------------------------------------------------------

function CorrelationStrip({
  leftSymbol,
  rightSymbol,
  leftSnap,
  rightSnap
}: {
  leftSymbol: string;
  rightSymbol: string;
  leftSnap: SnapshotState;
  rightSnap: SnapshotState;
}) {
  const result = useMemo(() => {
    if (leftSnap.phase !== "loaded" || rightSnap.phase !== "loaded") return null;
    return computeCorrelation(leftSnap.snapshot.bars, rightSnap.snapshot.bars);
  }, [leftSnap, rightSnap]);

  if (leftSnap.phase === "loading" || rightSnap.phase === "loading") {
    return (
      <section className="research-compare-correlation" aria-busy="true">
        <span className="research-compare-kicker-row">Correlation</span>
        <p className="research-compare-empty">Computing…</p>
      </section>
    );
  }
  if (!result) {
    return (
      <section className="research-compare-correlation">
        <span className="research-compare-kicker-row">Correlation</span>
        <p className="research-compare-empty">Insufficient overlapping data.</p>
      </section>
    );
  }

  const corrTone =
    result.correlation > 0.7
      ? "is-positive"
      : result.correlation < 0.3
        ? "is-negative"
        : "is-flat";

  return (
    <section className="research-compare-correlation">
      <header className="research-compare-correlation-header">
        <span className="research-compare-kicker-row">Correlation</span>
        <strong>
          {leftSymbol} vs {rightSymbol} · 30-day correlation:{" "}
          <span className={`research-compare-correlation-num ${corrTone}`}>
            {result.correlation.toFixed(2)}
          </span>
        </strong>
      </header>
      <div className="research-compare-correlation-body">
        <OverlayChart
          leftSymbol={leftSymbol}
          rightSymbol={rightSymbol}
          leftSeries={result.leftNormalized}
          rightSeries={result.rightNormalized}
        />
        <ul className="research-compare-correlation-stats">
          <li>
            <span className="research-compare-stat-label">β ({leftSymbol}→{rightSymbol})</span>
            <span className="research-compare-stat-value">{result.betaLeftToRight.toFixed(2)}</span>
          </li>
          <li>
            <span className="research-compare-stat-label">β ({rightSymbol}→{leftSymbol})</span>
            <span className="research-compare-stat-value">{result.betaRightToLeft.toFixed(2)}</span>
          </li>
          <li>
            <span className="research-compare-stat-label">N (days)</span>
            <span className="research-compare-stat-value">{result.sampleSize}</span>
          </li>
        </ul>
      </div>
    </section>
  );
}

function OverlayChart({
  leftSymbol,
  rightSymbol,
  leftSeries,
  rightSeries
}: {
  leftSymbol: string;
  rightSymbol: string;
  leftSeries: number[];
  rightSeries: number[];
}) {
  const geom = useMemo(() => {
    if (leftSeries.length < 2 || rightSeries.length < 2) return null;
    const all = [...leftSeries, ...rightSeries];
    const min = Math.min(...all);
    const max = Math.max(...all);
    const span = max - min || 1;
    const n = Math.min(leftSeries.length, rightSeries.length);
    const toPath = (series: number[]) =>
      series
        .slice(0, n)
        .map((value, i) => {
          const x = (i / (n - 1)) * 100;
          const y = 40 - ((value - min) / span) * 36 - 2;
          return `${i === 0 ? "M" : "L"} ${x.toFixed(2)},${y.toFixed(2)}`;
        })
        .join(" ");
    return { leftD: toPath(leftSeries), rightD: toPath(rightSeries) };
  }, [leftSeries, rightSeries]);

  if (!geom) {
    return <p className="research-compare-empty">Overlay unavailable.</p>;
  }

  return (
    <div className="research-compare-overlay">
      <svg
        aria-label={`${leftSymbol} and ${rightSymbol} normalized to 100`}
        className="research-compare-overlay-svg"
        preserveAspectRatio="none"
        role="img"
        viewBox="0 0 100 40"
      >
        <path className="research-compare-overlay-line research-compare-overlay-left" d={geom.leftD} />
        <path className="research-compare-overlay-line research-compare-overlay-right" d={geom.rightD} />
      </svg>
      <ul className="research-compare-overlay-legend">
        <li className="research-compare-overlay-legend-left">{leftSymbol}</li>
        <li className="research-compare-overlay-legend-right">{rightSymbol}</li>
      </ul>
    </div>
  );
}

// -----------------------------------------------------------------------------
// Math: returns + Pearson correlation + β
// -----------------------------------------------------------------------------

type CorrelationResult = {
  correlation: number;
  betaLeftToRight: number;
  betaRightToLeft: number;
  sampleSize: number;
  leftNormalized: number[];
  rightNormalized: number[];
};

export function computeCorrelation(
  leftBars: NormalizedMarketBar[],
  rightBars: NormalizedMarketBar[]
): CorrelationResult | null {
  // Align by timestamp so each pair of returns is a same-day pair.
  const rightByTs = new Map<string, NormalizedMarketBar>();
  for (const bar of rightBars) {
    rightByTs.set(bar.timestamp.slice(0, 10), bar);
  }
  const pairedLeft: NormalizedMarketBar[] = [];
  const pairedRight: NormalizedMarketBar[] = [];
  for (const bar of leftBars) {
    const key = bar.timestamp.slice(0, 10);
    const match = rightByTs.get(key);
    if (match) {
      pairedLeft.push(bar);
      pairedRight.push(match);
    }
  }

  // Trim to the most recent 30 daily observations on each side.
  const TAIL = 30;
  const leftTail = pairedLeft.slice(-TAIL);
  const rightTail = pairedRight.slice(-TAIL);

  if (leftTail.length < 10 || rightTail.length < 10) return null;

  const leftReturns = computeReturns(leftTail);
  const rightReturns = computeReturns(rightTail);
  const n = Math.min(leftReturns.length, rightReturns.length);
  if (n < 2) return null;

  const a = leftReturns.slice(-n);
  const b = rightReturns.slice(-n);

  const meanA = a.reduce((sum, value) => sum + value, 0) / n;
  const meanB = b.reduce((sum, value) => sum + value, 0) / n;

  let cov = 0;
  let varA = 0;
  let varB = 0;
  for (let i = 0; i < n; i++) {
    const dA = a[i] - meanA;
    const dB = b[i] - meanB;
    cov += dA * dB;
    varA += dA * dA;
    varB += dB * dB;
  }
  cov /= n;
  varA /= n;
  varB /= n;

  const denom = Math.sqrt(varA * varB);
  const correlation = denom === 0 ? 0 : cov / denom;
  const betaLeftToRight = varA === 0 ? 0 : cov / varA; // regress B on A
  const betaRightToLeft = varB === 0 ? 0 : cov / varB; // regress A on B

  return {
    correlation,
    betaLeftToRight,
    betaRightToLeft,
    sampleSize: n,
    leftNormalized: normalizeToBase(leftTail.map((bar) => bar.close), 100),
    rightNormalized: normalizeToBase(rightTail.map((bar) => bar.close), 100)
  };
}

function computeReturns(bars: NormalizedMarketBar[]): number[] {
  const out: number[] = [];
  for (let i = 1; i < bars.length; i++) {
    const prev = bars[i - 1].close;
    const curr = bars[i].close;
    if (prev > 0 && Number.isFinite(prev) && Number.isFinite(curr)) {
      out.push((curr - prev) / prev);
    }
  }
  return out;
}

function normalizeToBase(values: number[], base: number): number[] {
  if (values.length === 0) return [];
  const first = values[0];
  if (first === 0 || !Number.isFinite(first)) {
    return values.map(() => base);
  }
  return values.map((value) => (value / first) * base);
}

// -----------------------------------------------------------------------------
// Misc helpers
// -----------------------------------------------------------------------------

async function fetchSnapshot(
  symbol: string,
  range: "1M",
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

function extractStringField(event: RunEvent | undefined, key: string): string | null {
  if (!event) return null;
  const value = event.payload[key];
  return typeof value === "string" && value.length > 0 ? value : null;
}

function extractConfidence(event: RunEvent | undefined): number | null {
  if (!event) return null;
  const direct = event.payload.confidence;
  if (typeof direct === "number" && Number.isFinite(direct)) {
    return direct > 1 ? direct : direct * 100;
  }
  if (typeof direct === "string") {
    const parsed = Number.parseFloat(direct.replace(/%/g, ""));
    if (Number.isFinite(parsed)) {
      return parsed > 1 ? parsed : parsed * 100;
    }
  }
  return null;
}

function ratingTone(rating: string | null): string {
  if (!rating) return "research-compare-tone-neutral";
  const value = rating.toLowerCase();
  if (/sell|short|bear|reduce|underperform|negative/.test(value)) {
    return "research-compare-tone-bear";
  }
  if (/buy|long|bull|accumulate|overweight|positive|outperform/.test(value)) {
    return "research-compare-tone-bull";
  }
  return "research-compare-tone-neutral";
}

function formatRel(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const diff = Date.now() - d.getTime();
  const hours = Math.floor(diff / 3_600_000);
  if (hours < 1) return "just now";
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function formatNewsWhen(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const sameDay = new Date().toDateString() === d.toDateString();
  if (sameDay) {
    return d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
  }
  return d.toLocaleDateString("en-US", { weekday: "short" });
}

function truncate(value: string, max: number): string {
  if (value.length <= max) return value;
  return `${value.slice(0, max).trimEnd()}…`;
}
