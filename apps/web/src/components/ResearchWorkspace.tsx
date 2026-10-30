"use client";

/**
 * ResearchWorkspace — symbol-first answer surface for the Research tab.
 *
 * Replaces the old "click Run → wait → read text wall" interface with a
 * single-screen answer:
 *
 *   1. Verdict card        (rating · confidence · stance + catalyst chips)
 *   2. Action row          (Open in Quant · Set watcher · Read full)
 *   3. 3-pillar Why?       (Macro · Fundamental · Sentiment)
 *   4. Recent runs         (delta-vs-prior, expandable)
 *   5. Bull / Bear pair    (the most valuable committee output)
 *   6. Inspect deeper      (<details>: wraps the legacy DeepResearchWorkspace)
 *
 * The TradingAgents graph runner (createRun + waitForRunEvents) is preserved
 * but moved behind the "Run new committee" button so the page reads as the
 * answer first and the mechanics second. The legacy DeepResearchWorkspace
 * is mounted untouched inside a collapsed disclosure for power users.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import dynamic from "next/dynamic";
import "./StrategyResearch.css";

import { DeepResearchWorkspace } from "@/components/DeepResearchWorkspace";
import { ResearchExplorer } from "@/components/ResearchExplorer";
import { ResearchCompare } from "@/components/ResearchCompare";
import { WATCHLIST } from "@/data/watchlist";
import { deriveAgentReports, type AgentReport } from "@/lib/agent-reports";
import { createRun, listRunEvents, listRuns, waitForRunEvents } from "@/lib/api";
import { englishOrNotice } from "@/lib/language";
import type { RunEvent, RunSummary, WatchlistItem } from "@/lib/types";
import type { StrategyReviewSelection } from "@/lib/deployments";

const OpportunityInbox = dynamic(() => import("@/components/OpportunityInbox").then(module => module.OpportunityInbox), { loading: () => <p role="status">Loading opportunity inbox…</p> });
const ResearchDesk = dynamic(() => import("@/components/ResearchDesk").then(module => module.ResearchDesk), { loading: () => <p role="status">Loading research desk…</p> });
const PortfolioStress = dynamic(() => import("@/components/PortfolioStress").then(module => module.PortfolioStress), { loading: () => <p role="status">Loading portfolio stress testing…</p> });
const ThesisChallenge = dynamic(() => import("@/components/ThesisChallenge").then(module => module.ThesisChallenge), { loading: () => <p role="status">Loading thesis challenge…</p> });
const ForecastTournament = dynamic(() => import("@/components/ForecastTournament").then(module => module.ForecastTournament), { loading: () => <p role="status">Loading forecast tournament…</p> });
const ForecastLab = dynamic(() => import("@/components/ForecastLab").then(module => module.ForecastLab), { loading: () => <p role="status">Loading Forecast Lab…</p> });

type ResearchMode = "single" | "compare";

type PillarLane = "macro" | "fundamental" | "sentiment";

const StrategyResearchPanel = dynamic(() => import("@/components/StrategyResearchPanel").then((module) => module.StrategyResearchPanel), { loading: () => <p role="status">Loading strategy research…</p> });

export function ResearchWorkspace(props: { symbol: string; initialView?: "explorer" | "symbol" | "strategies"; watchlistItems?: WatchlistItem[]; onAddToWatchlist?: (symbol: string) => void; onResearchSymbol?: (symbol: string) => void; onOpenQuant: () => void; onRequestStrategyReview?: (selection: StrategyReviewSelection) => void }) {
  const [view, setView] = useState<"explorer" | "symbol" | "strategies" | "desk" | "forecast" | "opportunities" | "tournament" | "challenge" | "stress">(props.initialView ?? "explorer");
  useEffect(() => { if (props.initialView) setView(props.initialView); }, [props.initialView]);
  const [deskSymbol, setDeskSymbol] = useState(props.symbol);
  useEffect(() => { setDeskSymbol(props.symbol); }, [props.symbol]);
  return <div>
    <div className="strategy-view-switch" role="group" aria-label="Research view">
      <button type="button" aria-pressed={view === "explorer"} onClick={() => setView("explorer")}>Research explorer</button>
      <button type="button" aria-pressed={view === "opportunities"} onClick={() => setView("opportunities")}>Opportunity inbox</button>
      <button type="button" aria-pressed={view === "desk"} onClick={() => setView("desk")}>Research desk</button>
      <button type="button" aria-pressed={view === "stress"} onClick={() => setView("stress")}>Portfolio stress</button>
      <button type="button" aria-pressed={view === "challenge"} onClick={() => setView("challenge")}>Thesis challenge</button>
      <button type="button" aria-pressed={view === "tournament"} onClick={() => setView("tournament")}>Forecast tournament</button>
      <button type="button" aria-pressed={view === "forecast"} onClick={() => setView("forecast")}>Forecast Lab</button>
      <button type="button" aria-pressed={view === "symbol"} onClick={() => setView("symbol")}>Symbol research</button>
      <button type="button" aria-pressed={view === "strategies"} onClick={() => setView("strategies")}>Strategy research</button>
    </div>
    {view === "stress" ? <PortfolioStress /> : view === "challenge" ? <ThesisChallenge /> : view === "tournament" ? <ForecastTournament /> : view === "opportunities" ? <OpportunityInbox watchlist={(props.watchlistItems ?? []).map(item => item.symbol)} onCompany={(symbol) => { setDeskSymbol(symbol); setView("desk"); }} /> : view === "forecast" ? <ForecastLab symbol={props.symbol} /> : view === "desk" ? <ResearchDesk symbol={deskSymbol} /> : view === "explorer" ? <ResearchExplorer watchlistItems={props.watchlistItems ?? []} onAddToWatchlist={props.onAddToWatchlist} onResearch={(symbol) => { props.onResearchSymbol?.(symbol); setView("symbol"); }} /> : view === "symbol" ? <SymbolResearchWorkspace {...props} /> : <StrategyResearchPanel onRequestReview={props.onRequestStrategyReview} />}
  </div>;
}

type VerdictView = {
  rating: string | null;
  action: string | null;
  confidence: number | null;
  thesis: string | null;
  catalysts: string[];
  fallback: boolean;
  riskNotes: string | null;
};

type RunOutcome = {
  rating: string | null;
  action: string | null;
  confidence: number | null;
  thesis: string | null;
};

function SymbolResearchWorkspace({
  symbol,
  onOpenQuant
}: {
  symbol: string;
  // "Open quant" used to mean "open brokerage floor"; the wire prop on
  // DeepResearchWorkspace remains `onOpenBrokerage` for now (its internal
  // copy still says "open brokerage") but the user-visible meaning is now
  // "switch to the Quant tab where execution lives".
  onOpenQuant: () => void;
}) {
  const [latestEvents, setLatestEvents] = useState<RunEvent[]>([]);
  const [recentRuns, setRecentRuns] = useState<RunSummary[]>([]);
  const [latestRun, setLatestRun] = useState<RunSummary | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isRunning, setIsRunning] = useState(false);
  const [runStartTs, setRunStartTs] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expandedRunId, setExpandedRunId] = useState<string | null>(null);
  const [showAllRuns, setShowAllRuns] = useState(false);
  const [showFullThesis, setShowFullThesis] = useState(false);
  const [mode, setMode] = useState<ResearchMode>("single");
  // Right-hand symbol for compare mode. Default to the first watchlist entry
  // that isn't the currently selected (left) symbol so the user lands on a
  // real side-by-side instead of NVDA vs NVDA.
  const [compareRight, setCompareRight] = useState<string>(() => pickDefaultRight(symbol));
  const elapsedRef = useRef<number>(0);
  const [, forceTick] = useState(0);

  // Re-render once per second while a run is in flight so the elapsed timer
  // ticks up. The timer state itself lives in `runStartTs`; this is purely a
  // repaint pulse.
  useEffect(() => {
    if (!isRunning) {
      return;
    }
    const interval = window.setInterval(() => {
      elapsedRef.current = Date.now();
      forceTick((value) => value + 1);
    }, 1000);
    return () => window.clearInterval(interval);
  }, [isRunning]);

  // If the new left symbol matches the right side, pick a different right so
  // compare always shows two distinct tickers.
  useEffect(() => {
    if (symbol && symbol.toUpperCase() === compareRight.toUpperCase()) {
      const fallback = pickDefaultRight(symbol);
      if (fallback.toUpperCase() !== compareRight.toUpperCase()) {
        setCompareRight(fallback);
      }
    }
  }, [symbol, compareRight]);

  useEffect(() => {
    let isCurrent = true;

    async function loadForSymbol() {
      if (!symbol) {
        return;
      }
      setIsLoading(true);
      setError(null);
      setLatestEvents([]);
      setLatestRun(null);
      setExpandedRunId(null);
      setShowFullThesis(false);

      try {
        const runs = await listRuns({ ticker: symbol, limit: 10 });
        if (!isCurrent) {
          return;
        }
        setRecentRuns(runs);
        const newest = runs[0] ?? null;
        setLatestRun(newest);
        if (newest) {
          const events = await listRunEvents(newest.run_id);
          if (!isCurrent) {
            return;
          }
          setLatestEvents(events);
        }
      } catch (caught) {
        if (isCurrent) {
          setError(caught instanceof Error ? caught.message : "Unable to load research for this symbol");
        }
      } finally {
        if (isCurrent) {
          setIsLoading(false);
        }
      }
    }

    void loadForSymbol();
    return () => {
      isCurrent = false;
    };
  }, [symbol]);

  const verdict = useMemo(() => deriveVerdict(latestEvents), [latestEvents]);
  const reports = useMemo(() => deriveAgentReports(latestEvents), [latestEvents]);
  const pillars = useMemo(() => derivePillars(reports), [reports]);
  const bullView = useMemo(() => pickReport(reports, ["bull"]), [reports]);
  const bearView = useMemo(() => pickReport(reports, ["bear"]), [reports]);

  async function runNewCommittee() {
    if (!symbol) {
      return;
    }
    setIsRunning(true);
    setRunStartTs(Date.now());
    setError(null);
    setLatestEvents([]);
    setShowFullThesis(false);

    try {
      const created = await createRun({
        brokerMode: "disabled",
        executionMode: "real",
        ticker: symbol,
        tradeDate: new Date().toISOString().slice(0, 10)
      });
      const finalEvents = await waitForRunEvents(created.run_id, {
        onEvents: (polled) => setLatestEvents(polled)
      });
      setLatestEvents(finalEvents);
      const runs = await listRuns({ ticker: symbol, limit: 10 });
      setRecentRuns(runs);
      const newest = runs[0] ?? null;
      setLatestRun(newest);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to run research committee");
    } finally {
      setIsRunning(false);
      setRunStartTs(null);
    }
  }

  if (!symbol) {
    return (
      <section className="room-workspace-root research-workspace-root" aria-label="Research workspace">
        <div className="research-empty-card">
          <span className="panel-kicker">Research</span>
          <h1>Pick a ticker to research</h1>
          <p>Choose a symbol from the watchlist on the left, or hit Cmd+K to search.</p>
        </div>
      </section>
    );
  }

  const visibleRuns = showAllRuns ? recentRuns : recentRuns.slice(0, 2);
  const hasAnyRun = latestRun !== null || latestEvents.length > 0;
  const lastRunOutcome = latestRunOutcome(latestRun, verdict);
  const priorRun = recentRuns[1] ?? null;
  const confidenceDelta = computeConfidenceDelta(latestEvents, priorRun);

  if (mode === "compare") {
    return (
      <ResearchCompare
        leftSymbol={symbol}
        rightSymbol={compareRight}
        onClose={() => setMode("single")}
        onChangeLeft={() => {
          /* left side is owned by global watchlist selection — leave to caller */
        }}
        onChangeRight={(next) => setCompareRight(next)}
        suggestions={WATCHLIST.map((entry) => entry.symbol)}
      />
    );
  }

  return (
    <section className="room-workspace-root research-workspace-root" aria-label="Research workspace">
      <header className="research-page-header">
        <div>
          <span className="panel-kicker">Research</span>
          <h1>
            <em>{symbol}</em>
            <span className="research-page-header-subline">{describeFreshness(latestRun, isRunning, runStartTs)}</span>
          </h1>
        </div>
        <div className="research-page-actions">
          <div
            className="research-mode-toggle"
            role="tablist"
            aria-label="Research view mode"
          >
            <button
              type="button"
              role="tab"
              aria-selected={true}
              className="research-mode-toggle-btn active"
            >
              Single
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={false}
              className="research-mode-toggle-btn"
              onClick={() => setMode("compare")}
            >
              Compare
            </button>
          </div>
          <button
            type="button"
            className="primary-button compact"
            onClick={() => void runNewCommittee()}
            disabled={isRunning}
          >
            {isRunning ? "Committee running…" : "Run new committee"}
          </button>
        </div>
      </header>

      {error ? <p className="research-error">{error}</p> : null}

      {!hasAnyRun && !isLoading && !isRunning ? (
        <EmptyResearch symbol={symbol} onRunCommittee={() => void runNewCommittee()} />
      ) : null}

      {isRunning ? (
        <RunningCommitteeCard symbol={symbol} startTs={runStartTs} events={latestEvents} />
      ) : null}

      {hasAnyRun ? (
        <>
          <VerdictCard
            symbol={symbol}
            verdict={verdict}
            lastRun={latestRun}
            outcome={lastRunOutcome}
            onOpenQuant={onOpenQuant}
            onReadFull={() => setShowFullThesis((prior) => !prior)}
            showingFullThesis={showFullThesis}
          />

          {showFullThesis && verdict.thesis ? (
            <section className="research-full-thesis-card">
              <span className="panel-kicker">Full committee thesis</span>
              <p>{verdict.thesis}</p>
              {verdict.riskNotes ? <p className="research-thesis-risk">{verdict.riskNotes}</p> : null}
            </section>
          ) : null}

          <PillarGrid pillars={pillars} />

          <RecentRunsList
            runs={visibleRuns}
            totalRuns={recentRuns.length}
            currentRunId={latestRun?.run_id ?? null}
            expandedRunId={expandedRunId}
            onToggle={(runId) => setExpandedRunId((prior) => (prior === runId ? null : runId))}
            onShowMore={() => setShowAllRuns(true)}
            showingAll={showAllRuns}
            confidenceDelta={confidenceDelta}
          />

          <BullBearPair bull={bullView} bear={bearView} />
        </>
      ) : null}

      <details className="research-inspect-disclosure">
        <summary>
          Inspect deeper · run graph, agent timeline, LangFuse export
        </summary>
        <div className="research-inspect-disclosure-body">
          <DeepResearchWorkspace symbol={symbol} onOpenBrokerage={onOpenQuant} />
        </div>
      </details>
    </section>
  );
}

function VerdictCard({
  symbol,
  verdict,
  lastRun,
  outcome,
  onOpenQuant,
  onReadFull,
  showingFullThesis
}: {
  symbol: string;
  verdict: VerdictView;
  lastRun: RunSummary | null;
  outcome: RunOutcome;
  onOpenQuant: () => void;
  onReadFull: () => void;
  showingFullThesis: boolean;
}) {
  const ratingLabel = outcome.rating ?? "Awaiting verdict";
  const actionLabel = outcome.action ?? null;
  const confidenceLabel = formatConfidence(outcome.confidence);
  const ratingClass = ratingTone(outcome.rating);
  const stance =
    verdict.thesis !== null
      ? truncateBody(verdict.thesis, 220)
      : "No thesis text was returned for the most recent run. Run a new committee for a fresh read.";

  return (
    <section className={`research-verdict-card ${ratingClass}`}>
      <div className="research-verdict-top">
        <div>
          <span className="research-verdict-kicker">Verdict</span>
          <h2>
            <span className="research-verdict-rating">{ratingLabel}</span>
            {actionLabel ? <span className="research-verdict-action">· {actionLabel}</span> : null}
            {confidenceLabel ? <span className="research-verdict-confidence">· {confidenceLabel}</span> : null}
          </h2>
        </div>
        <div className="research-verdict-meta">
          <span className="research-verdict-source">{verdict.fallback ? "Deterministic fallback" : "LLM synthesis"}</span>
          <span>Updated {formatUpdatedAt(lastRun?.updated_at)}</span>
        </div>
      </div>
      <p className="research-verdict-stance">{stance}</p>
      {verdict.catalysts.length > 0 ? (
        <ul className="research-catalyst-chips" aria-label="Catalysts">
          {verdict.catalysts.slice(0, 6).map((catalyst, index) => (
            <li key={`${catalyst}-${index}`}>
              <span>{catalyst}</span>
            </li>
          ))}
        </ul>
      ) : null}
      <div className="research-verdict-actions">
        <button
          type="button"
          className="primary-button compact"
          onClick={onOpenQuant}
          aria-label={`Open ${symbol} in Quant`}
        >
          Open {symbol} in Quant →
        </button>
        <button type="button" className="secondary-button compact" onClick={onReadFull} disabled={!verdict.thesis}>
          {showingFullThesis ? "Hide full thesis" : "Read full thesis"}
        </button>
      </div>
    </section>
  );
}

function PillarGrid({
  pillars
}: {
  pillars: Record<PillarLane, { headline: string | null; agent: string | null }>;
}) {
  return (
    <section className="research-pillar-section">
      <div className="research-section-header">
        <span className="panel-kicker">Why?</span>
        <h2>Committee summary</h2>
      </div>
      <div className="research-pillar-grid">
        <PillarCard label="Macro" tone="macro" headline={pillars.macro.headline} agent={pillars.macro.agent} />
        <PillarCard
          label="Fundamental"
          tone="fundamental"
          headline={pillars.fundamental.headline}
          agent={pillars.fundamental.agent}
        />
        <PillarCard
          label="Sentiment"
          tone="sentiment"
          headline={pillars.sentiment.headline}
          agent={pillars.sentiment.agent}
        />
      </div>
    </section>
  );
}

function PillarCard({
  label,
  tone,
  headline,
  agent
}: {
  label: string;
  tone: PillarLane;
  headline: string | null;
  agent: string | null;
}) {
  return (
    <article className={`research-pillar-card research-pillar-card-${tone}`}>
      <span className="research-pillar-label">{label}</span>
      <p className="research-pillar-headline">{headline ?? "No agent report for this lane yet."}</p>
      {agent ? <span className="research-pillar-source">{agent}</span> : null}
    </article>
  );
}

function RecentRunsList({
  runs,
  totalRuns,
  currentRunId,
  expandedRunId,
  onToggle,
  onShowMore,
  showingAll,
  confidenceDelta
}: {
  runs: RunSummary[];
  totalRuns: number;
  currentRunId: string | null;
  expandedRunId: string | null;
  onToggle: (runId: string) => void;
  onShowMore: () => void;
  showingAll: boolean;
  confidenceDelta: number | null;
}) {
  if (runs.length === 0) {
    return null;
  }
  const remaining = totalRuns - runs.length;
  return (
    <section className="research-runs-section">
      <div className="research-section-header">
        <span className="panel-kicker">Recent runs</span>
        <h2>{totalRuns} on record</h2>
      </div>
      <ol className="research-runs-list">
        {runs.map((run, index) => {
          const isCurrent = run.run_id === currentRunId;
          const isExpanded = expandedRunId === run.run_id;
          const delta = isCurrent ? confidenceDelta : null;
          return (
            <li className={`research-run-card${isCurrent ? " research-run-card-current" : ""}`} key={run.run_id}>
              <header>
                <div>
                  <span className="research-run-time">{formatFullTimestamp(run.updated_at)}</span>
                  <strong>
                    <span className={`research-run-rating ${ratingTone(run.final_rating)}`}>
                      {run.final_rating ?? "Awaiting verdict"}
                    </span>
                    {run.final_action ? <span> · {run.final_action}</span> : null}
                  </strong>
                </div>
                <div className="research-run-meta">
                  {isCurrent ? <span className="research-run-tag">current</span> : null}
                  {delta !== null ? (
                    <span className={`research-run-delta ${delta >= 0 ? "positive" : "negative"}`}>
                      Δ vs prior {delta >= 0 ? `+${delta}` : delta} pts
                    </span>
                  ) : null}
                </div>
              </header>
              <button
                type="button"
                className="research-run-toggle"
                onClick={() => onToggle(run.run_id)}
                aria-expanded={isExpanded}
                aria-controls={`run-detail-${run.run_id}`}
              >
                {isExpanded ? "Hide report" : "Open report"}
              </button>
              {isExpanded ? (
                <div className="research-run-detail" id={`run-detail-${run.run_id}`}>
                  <RunDetailBody runId={run.run_id} fallbackRating={run.final_rating} fallbackAction={run.final_action} index={index} />
                </div>
              ) : null}
            </li>
          );
        })}
      </ol>
      {!showingAll && remaining > 0 ? (
        <button type="button" className="secondary-button compact research-show-more" onClick={onShowMore}>
          Show {remaining} more
        </button>
      ) : null}
    </section>
  );
}

function RunDetailBody({
  runId,
  fallbackRating,
  fallbackAction,
  index
}: {
  runId: string;
  fallbackRating: string | null;
  fallbackAction: string | null;
  index: number;
}) {
  const [body, setBody] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let isCurrent = true;
    setLoading(true);
    setErr(null);
    setBody(null);
    void (async () => {
      try {
        const events = await listRunEvents(runId);
        if (!isCurrent) return;
        const verdict = deriveVerdict(events);
        setBody(verdict.thesis ?? null);
      } catch (caught) {
        if (isCurrent) {
          setErr(caught instanceof Error ? caught.message : "Unable to load this run");
        }
      } finally {
        if (isCurrent) setLoading(false);
      }
    })();
    return () => {
      isCurrent = false;
    };
  }, [runId]);

  if (loading) {
    return <p className="research-run-loading">Loading report #{index + 1}…</p>;
  }
  if (err) {
    return <p className="research-error">{err}</p>;
  }
  if (!body) {
    return (
      <p className="research-run-empty">
        No thesis text on file. {fallbackRating ?? "—"} {fallbackAction ?? ""}
      </p>
    );
  }
  return <p>{body}</p>;
}

function BullBearPair({ bull, bear }: { bull: AgentReport | null; bear: AgentReport | null }) {
  if (!bull && !bear) {
    return null;
  }
  return (
    <section className="research-bull-bear-section">
      <div className="research-section-header">
        <span className="panel-kicker">Two sides</span>
        <h2>Bull vs Bear</h2>
      </div>
      <div className="research-bull-bear-grid">
        <article className="research-bull-card">
          <header>
            <span className="research-bb-label">Bull view</span>
            {bull ? <small>{bull.agentName}</small> : null}
          </header>
          {bull ? <p>{truncateBody(bull.body, 600)}</p> : <p className="research-empty-line">No bull researcher report on this run.</p>}
        </article>
        <article className="research-bear-card">
          <header>
            <span className="research-bb-label">Bear view</span>
            {bear ? <small>{bear.agentName}</small> : null}
          </header>
          {bear ? <p>{truncateBody(bear.body, 600)}</p> : <p className="research-empty-line">No bear researcher report on this run.</p>}
        </article>
      </div>
    </section>
  );
}

function RunningCommitteeCard({
  symbol,
  startTs,
  events
}: {
  symbol: string;
  startTs: number | null;
  events: RunEvent[];
}) {
  const elapsedSec = startTs ? Math.max(0, Math.floor((Date.now() - startTs) / 1000)) : 0;
  const lastEvent = events[events.length - 1];
  return (
    <section className="research-running-card" aria-live="polite">
      <div className="research-running-indicator" aria-hidden="true">
        <span className="research-pulse-dot" />
      </div>
      <div className="research-running-body">
        <strong>Committee running on {symbol}</strong>
        <small>
          {events.length} event{events.length === 1 ? "" : "s"} · {elapsedSec}s elapsed
        </small>
        {lastEvent ? <p>{lastEvent.message}</p> : <p>Waiting for the first event…</p>}
      </div>
    </section>
  );
}

function EmptyResearch({ symbol, onRunCommittee }: { symbol: string; onRunCommittee: () => void }) {
  return (
    <section className="research-empty-card">
      <span className="panel-kicker">No research yet</span>
      <h2>
        <em>{symbol}</em> hasn&apos;t been put through committee
      </h2>
      <p>Run the 10-agent committee to get a verdict, key catalysts, and a Bull/Bear view in about a minute.</p>
      <button type="button" className="primary-button" onClick={onRunCommittee}>
        Run committee on {symbol}
      </button>
    </section>
  );
}

// ───────────────────────────── helpers ─────────────────────────────

function deriveVerdict(events: RunEvent[]): VerdictView {
  const decision = events.find((event) => event.type === "decision.created");
  if (!decision) {
    return {
      rating: null,
      action: null,
      confidence: null,
      thesis: null,
      catalysts: [],
      fallback: false,
      riskNotes: null
    };
  }
  const payload = decision.payload;
  const rating = typeof payload.rating === "string" ? payload.rating : null;
  const action = typeof payload.action === "string" ? payload.action : null;
  const thesisRaw = typeof payload.thesis === "string" ? payload.thesis : null;
  const thesis = thesisRaw ? englishOrNotice(thesisRaw) : null;
  const confidence = extractConfidence(payload);
  const catalysts = extractCatalysts(payload);
  const fallback = payload.fallback === true;
  const riskNotesRaw = typeof payload.risk_notes === "string" ? payload.risk_notes : null;
  const riskNotes = riskNotesRaw ? englishOrNotice(riskNotesRaw) : null;
  return { rating, action, confidence, thesis, catalysts, fallback, riskNotes };
}

function extractConfidence(payload: Record<string, unknown>): number | null {
  const direct = payload.confidence;
  if (typeof direct === "number" && Number.isFinite(direct)) {
    return direct > 1 ? direct : direct * 100;
  }
  if (typeof direct === "string") {
    const parsed = Number.parseFloat(direct.replace(/%/g, ""));
    if (Number.isFinite(parsed)) {
      return parsed > 1 ? parsed : parsed * 100;
    }
  }
  const nestedPct = (payload.confidence_pct ?? payload.conviction ?? payload.conviction_pct) as unknown;
  if (typeof nestedPct === "number" && Number.isFinite(nestedPct)) {
    return nestedPct > 1 ? nestedPct : nestedPct * 100;
  }
  return null;
}

function extractCatalysts(payload: Record<string, unknown>): string[] {
  const raw = payload.catalysts;
  if (Array.isArray(raw)) {
    return raw
      .map((entry) => (typeof entry === "string" ? entry.trim() : ""))
      .filter((entry) => entry.length > 0);
  }
  if (typeof raw === "string") {
    return raw
      .split(/[,;\n]/)
      .map((entry) => entry.trim())
      .filter((entry) => entry.length > 0);
  }
  return [];
}

function derivePillars(reports: AgentReport[]): Record<PillarLane, { headline: string | null; agent: string | null }> {
  const macro = pickReport(reports, ["macro", "news"]);
  const fundamental = pickReport(reports, ["fundamental", "research_manager", "research manager", "manager"]);
  const sentiment = pickReport(reports, ["social", "sentiment", "bull", "bear"]);

  return {
    macro: pillarFromReport(macro),
    fundamental: pillarFromReport(fundamental),
    sentiment: pillarFromReport(sentiment)
  };
}

function pillarFromReport(report: AgentReport | null): { headline: string | null; agent: string | null } {
  if (!report) {
    return { headline: null, agent: null };
  }
  const firstLine = firstMeaningfulLine(report.body);
  return {
    headline: firstLine ? truncateBody(firstLine, 140) : null,
    agent: report.agentName
  };
}

function pickReport(reports: AgentReport[], keywords: string[]): AgentReport | null {
  const lowered = keywords.map((keyword) => keyword.toLowerCase());
  for (const report of reports) {
    const haystack = `${report.agentName} ${report.section}`.toLowerCase();
    if (lowered.some((keyword) => haystack.includes(keyword))) {
      return report;
    }
  }
  return null;
}

function firstMeaningfulLine(body: string): string | null {
  const lines = body
    .split(/\n+/)
    .map((line) => line.replace(/^[#>\-*\s]+/, "").trim())
    .filter((line) => line.length > 0);
  return lines[0] ?? null;
}

function truncateBody(body: string, max: number): string {
  if (body.length <= max) {
    return body;
  }
  return `${body.slice(0, max).trimEnd()}…`;
}

function ratingTone(rating: string | null | undefined): string {
  if (!rating) return "research-tone-neutral";
  const value = rating.toLowerCase();
  if (value.includes("buy") || value.includes("long") || value.includes("bull")) {
    return "research-tone-bull";
  }
  if (value.includes("sell") || value.includes("short") || value.includes("bear")) {
    return "research-tone-bear";
  }
  return "research-tone-neutral";
}

function formatConfidence(confidence: number | null): string | null {
  if (confidence === null) return null;
  const clamped = Math.max(0, Math.min(100, Math.round(confidence)));
  return `${clamped}% confidence`;
}

function formatUpdatedAt(value: string | undefined | null): string {
  if (!value) return "never";
  const diff = Date.now() - new Date(value).getTime();
  if (Number.isNaN(diff)) return "never";
  const minutes = Math.floor(diff / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric" }).format(new Date(value));
}

function formatFullTimestamp(value: string): string {
  return new Intl.DateTimeFormat("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit"
  }).format(new Date(value));
}

function describeFreshness(latestRun: RunSummary | null, isRunning: boolean, runStartTs: number | null): string {
  if (isRunning) {
    const elapsed = runStartTs ? Math.max(0, Math.floor((Date.now() - runStartTs) / 1000)) : 0;
    return `· committee running · ${elapsed}s`;
  }
  if (!latestRun) {
    return "· no prior research";
  }
  return `· last committee ${formatUpdatedAt(latestRun.updated_at)}`;
}

function latestRunOutcome(run: RunSummary | null, verdict: VerdictView): RunOutcome {
  return {
    rating: verdict.rating ?? run?.final_rating ?? null,
    action: verdict.action ?? run?.final_action ?? null,
    confidence: verdict.confidence,
    thesis: verdict.thesis
  };
}

function pickDefaultRight(leftSymbol: string): string {
  const leftUpper = leftSymbol.toUpperCase();
  for (const entry of WATCHLIST) {
    if (entry.symbol.toUpperCase() !== leftUpper) {
      return entry.symbol;
    }
  }
  return WATCHLIST[0]?.symbol ?? "SPY";
}

function computeConfidenceDelta(latestEvents: RunEvent[], priorRun: RunSummary | null): number | null {
  const latest = deriveVerdict(latestEvents).confidence;
  if (latest === null || priorRun === null) {
    return null;
  }
  // We don't have prior-run confidence on the RunSummary; without a fetch we
  // return null. Surface the delta only when we can prove it.
  return null;
}
