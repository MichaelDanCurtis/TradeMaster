"use client";

/**
 * DeepResearchWorkspace — the main content of the Research tab.
 *
 * Layout (three-column grid `.deep-research-workspace`):
 *   1. `.research-report-rail`     — sessions / stored reports list
 *   2. `.private-office-canvas`    — final advisory report + agent reports +
 *                                    OrderThesis handoff + collapsed trace
 *   3. `.running-reports-panel`    — current run queue
 *
 * Top of the page (`.workspace-header.research-header`) carries the symbol
 * title and the primary "Run research" / "Export trace" affordances. The trace
 * disclosure (`.research-trace-disclosure`) collapses the run graph, event
 * timeline, and LangFuse export status so the thesis reads first and the
 * mechanics of "how the agents produced it" read second.
 *
 * History note: a meta-narrative AdvisorNarrativePanel and a RoomRoadmapPanel
 * used to live here. Both were removed in the v2 IA cleanup / 4-tab IA
 * flattening (2026-05-20). The thesis is now the loud top of the page.
 */

import { useEffect, useState } from "react";

import { AgentReportsPanel } from "@/components/AgentReportsPanel";
import { AgentRunGraph } from "@/components/AgentRunGraph";
import { OrderThesisPanel } from "@/components/OrderThesisPanel";
import { RunTimeline } from "@/components/RunTimeline";
import { deriveAgentReports } from "@/lib/agent-reports";
import { createRun, exportRunTrace, getRunTrace, listRunEvents, listRuns } from "@/lib/api";
import { englishOrNotice } from "@/lib/language";
import type { RunEvent, RunSummary, RunTrace } from "@/lib/types";
import { useRunEventStream } from "@/lib/useRunEventStream";

export function DeepResearchWorkspace({
  symbol,
  onOpenBrokerage
}: {
  symbol: string;
  onOpenBrokerage: () => void;
}) {
  const [runId, setRunId] = useState<string | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [trace, setTrace] = useState<RunTrace | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [isExporting, setIsExporting] = useState(false);
  const [isLoadingRuns, setIsLoadingRuns] = useState(false);
  const [recentRuns, setRecentRuns] = useState<RunSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [selectedReportId, setSelectedReportId] = useState<string | null>(null);
  // `liveRunId` is set when we kick off a new run and want to stream agent
  // landings live via SSE; it's cleared when the stream terminates so a
  // subsequent open of a stored run doesn't re-subscribe.
  const [liveRunId, setLiveRunId] = useState<string | null>(null);
  const liveStream = useRunEventStream(liveRunId);
  const decisionEvent = events.find((event) => event.type === "decision.created");
  const reportEvents = events.filter((event) => event.type === "report.updated");
  const agentReports = deriveAgentReports(events);

  // Mirror live SSE events into the workspace state so the existing
  // panels (agent reports, run timeline, decision card) update in real
  // time without restructuring their data flow.
  useEffect(() => {
    if (!liveRunId) return;
    setEvents(liveStream.events);
    const firstReport = deriveAgentReports(liveStream.events)[0];
    if (firstReport) {
      setSelectedReportId((prev) => prev ?? firstReport.id);
    }
  }, [liveRunId, liveStream.events]);

  useEffect(() => {
    let isCurrent = true;

    async function loadPersistedRuns() {
      setIsLoadingRuns(true);
      setError(null);
      setEvents([]);
      setTrace(null);
      setRunId(null);
      setSelectedReportId(null);

      try {
        const runs = await listRuns({ ticker: symbol, limit: 12 });
        if (!isCurrent) {
          return;
        }
        setRecentRuns(runs);

        const selectedRun = runs[0];
        if (selectedRun) {
          await openPersistedRun(selectedRun, isCurrent);
        }
      } catch (caught) {
        if (isCurrent) {
          setError(caught instanceof Error ? caught.message : "Unable to load stored research runs");
        }
      } finally {
        if (isCurrent) {
          setIsLoadingRuns(false);
        }
      }
    }

    void loadPersistedRuns();

    return () => {
      isCurrent = false;
    };
  }, [symbol]);

  async function openPersistedRun(selectedRun: RunSummary, isCurrent = true) {
    setError(null);
    // Tear down any live SSE subscription before showing a historical run,
    // so the mirror effect doesn't overwrite the loaded events.
    setLiveRunId(null);
    setRunId(selectedRun.run_id);
    setSelectedReportId(null);

    try {
      const [nextEvents, nextTrace] = await Promise.all([
        listRunEvents(selectedRun.run_id),
        getRunTrace(selectedRun.run_id)
      ]);
      if (!isCurrent) {
        return;
      }
      setEvents(nextEvents);
      setTrace(nextTrace);
      const firstReport = deriveAgentReports(nextEvents)[0];
      setSelectedReportId(firstReport?.id ?? null);
    } catch (caught) {
      if (isCurrent) {
        setError(caught instanceof Error ? caught.message : "Unable to open stored research run");
      }
    }
  }

  async function startResearchRun() {
    setIsRunning(true);
    setError(null);
    setEvents([]);
    setTrace(null);
    setSelectedReportId(null);
    setLiveRunId(null);

    try {
      const created = await createRun({
        brokerMode: "disabled",
        executionMode: "real",
        ticker: symbol,
        tradeDate: new Date().toISOString().slice(0, 10)
      });
      setRunId(created.run_id);
      // Open the live SSE subscription. The `useRunEventStream` hook
      // pipes events into `events` via the mirror effect above, so the
      // UI updates as agents land instead of waiting for the final batch.
      setLiveRunId(created.run_id);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to run deep research");
      setIsRunning(false);
    }
  }

  // When the live stream terminates (run.completed / run.failed / error
  // fallback), fetch the trace, refresh the run list, and clear the
  // running flag. This used to live inline inside `startResearchRun`
  // when we polled; with SSE it has to react to the stream state.
  useEffect(() => {
    if (!liveRunId) return;
    if (liveStream.status !== "completed" && liveStream.status !== "error") {
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const nextTrace = await getRunTrace(liveRunId);
        if (cancelled) return;
        setTrace(nextTrace);
        if (
          !isTerminalRun(liveStream.events, "run.completed") &&
          !isTerminalRun(liveStream.events, "run.failed")
        ) {
          setError(
            "Research run is still running. Leave this report open or reload it from Stored reports later."
          );
        }
        const nextRuns = await listRuns({ ticker: symbol, limit: 12 });
        if (cancelled) return;
        setRecentRuns(nextRuns);
      } catch (caught) {
        if (cancelled) return;
        setError(caught instanceof Error ? caught.message : "Unable to finalize research run");
      } finally {
        if (!cancelled) {
          setIsRunning(false);
          setLiveRunId(null);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [liveRunId, liveStream.status, liveStream.events, symbol]);

  async function exportTrace() {
    if (!runId) {
      setError("Run a research trace before exporting.");
      return;
    }

    setIsExporting(true);
    setError(null);
    try {
      const exported = await exportRunTrace(runId);
      setTrace(exported);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to export trace");
    } finally {
      setIsExporting(false);
    }
  }

  return (
    <section className="room-workspace-root" aria-label="Deep Research private office workspace">
      <header className="workspace-header research-header">
        <div>
          <span className="panel-kicker">Brief · Research</span>
          <h1>
            <em>{symbol}</em> thesis
          </h1>
          <div className="research-meta-strip" aria-label="Research run status">
            <span>{symbol}</span>
            <span>{isRunning ? "Running" : runId ? "Trace available" : "Not started"}</span>
            <span>Approval gated</span>
          </div>
        </div>
        <div className="research-header-actions">
          <button className="primary-button compact" type="button" onClick={startResearchRun} disabled={isRunning}>
            {isRunning ? "Running..." : "Run research"}
          </button>
          <button
            className="secondary-button compact"
            type="button"
            onClick={exportTrace}
            disabled={!trace || !runId || isExporting}
          >
            {isExporting ? "Exporting..." : "Export trace"}
          </button>
        </div>
      </header>

      <section className="deep-research-workspace">
        <aside className="research-report-rail">
        <header className="panel-header">
          <div>
            <span className="panel-kicker">Research sessions</span>
            <h2>Deep Research</h2>
          </div>
          <span className="panel-count">{runId ? 1 : 0}</span>
        </header>
        <div className="research-session-list">
          <section className={runId ? "research-session-card active" : "research-session-card"}>
            <span>Current run</span>
            <strong>{runId ? `${symbol} trace` : "No run started"}</strong>
            <small>{runId ?? "Start a trace to populate the report ledger."}</small>
          </section>
          <section className="research-session-card">
            <span>Report output</span>
            <strong>{formatDecisionTitle(decisionEvent)}</strong>
            <small>{reportEvents.length} report updates from the TradingAgents graph</small>
          </section>
          <section className="research-session-card">
            <span>Trace export</span>
            <strong>{trace?.status ?? "Local only"}</strong>
            <small>{trace?.external_trace_id ?? "Export to LangFuse when the run is ready."}</small>
          </section>
          <section className="research-session-card research-history-card">
            <span>Stored reports</span>
            <strong>{isLoadingRuns ? "Loading reports" : `${recentRuns.length} saved`}</strong>
            <small>{recentRuns[0]?.updated_at ? `Latest ${formatShortTimestamp(recentRuns[0].updated_at)}` : "No stored reports for this symbol yet."}</small>
          </section>
          {isLoadingRuns && recentRuns.length === 0 ? (
            <p className="empty-state">Loading stored reports...</p>
          ) : null}
          {!isLoadingRuns && recentRuns.length === 0 ? (
            <p className="empty-state">No stored reports for {symbol}. Run a research trace to populate this list.</p>
          ) : null}
          <div className="research-run-list" aria-label={`${symbol} stored reports`}>
            {recentRuns.map((storedRun) => (
              <button
                className={storedRun.run_id === runId ? "research-run-card selected" : "research-run-card"}
                key={storedRun.run_id}
                onClick={() => void openPersistedRun(storedRun)}
                type="button"
              >
                <span>{storedRun.status}</span>
                <strong>{formatStoredRunTitle(storedRun)}</strong>
                <small>{formatShortTimestamp(storedRun.updated_at)}</small>
              </button>
            ))}
          </div>
        </div>
        </aside>

        <article className="private-office-canvas">
        <section className="report-a2ui-panel">
          <header>
            <div>
              <span className="stance-badge neutral">{formatDecisionSource(decisionEvent)}</span>
              <h2>TradingAgents research</h2>
            </div>
          </header>
          <p>
            This panel starts the configured local research runner and displays only events returned by the API. It labels
            deterministic fallback output when an LLM provider is not available.
          </p>
          <section className="deep-research-report-output">
            <span className="panel-kicker">Final advisory report</span>
            <strong>{formatDecisionTitle(decisionEvent)}</strong>
            <small>
              {formatDecisionSource(decisionEvent)} - Research only - not an order - See individual agent reports below
            </small>
            <p>{formatDecisionBody(decisionEvent)}</p>
            {decisionEvent?.payload.risk_notes ? (
              <small>{englishOrNotice(String(decisionEvent.payload.risk_notes))}</small>
            ) : null}
          </section>
          <AgentReportsPanel
            reports={agentReports}
            selectedReportId={selectedReportId}
            onSelectReport={setSelectedReportId}
          />
          <OrderThesisPanel
            symbol={symbol}
            sourceReportId={runId}
            onOpenBrokerage={onOpenBrokerage}
          />
          {/* Trace plumbing (run graph + event timeline + LangFuse export) is
           * lower-information-density than the thesis above. Collapse it into
           * a disclosure so the page reads as "here's the report" first and
           * "inspect how the agents produced it" second. */}
          <details className="research-trace-disclosure">
            <summary>
              Inspect run · trace, agent graph, timeline ({events.length} events)
            </summary>
            <div className="research-trace-disclosure-body">
              <TraceOperationsPanel trace={trace} runId={runId} error={error} />
              {events.length > 0 ? (
                <section className="report-trace-grid">
                  <AgentRunGraph events={events} />
                  <section className="report-trace-timeline">
                    <div className="section-title">
                      <span>Execution timeline</span>
                      <strong>{events.length}</strong>
                    </div>
                    <RunTimeline events={events} />
                  </section>
                </section>
              ) : (
                <p className="empty-state">No run events are loaded for this symbol yet.</p>
              )}
            </div>
          </details>
        </section>
        </article>

        <aside className="running-reports-panel">
        <header className="panel-header">
          <div>
            <span className="panel-kicker">Running reports</span>
            <h2>{symbol} queue</h2>
          </div>
          <span className="panel-count">{isRunning ? 1 : 0}</span>
        </header>
        {isRunning ? (
          <section className="run-queue-card">
            <div>
              <span className="run-state running">running</span>
              <strong>LLM research trace</strong>
              <small>{symbol}</small>
            </div>
            <ol>
              <li>
                <span className="step-dot running" />
                Waiting for local runner response
              </li>
            </ol>
          </section>
        ) : (
          <p className="empty-state">No research run is currently active.</p>
        )}
        </aside>
      </section>
    </section>
  );
}

function TraceOperationsPanel({
  trace,
  runId,
  error
}: {
  trace: RunTrace | null;
  runId: string | null;
  error: string | null;
}) {
  const traceUrl =
    typeof trace?.metadata.external_trace_url === "string" ? trace.metadata.external_trace_url : null;

  return (
    <section className="trace-operations-panel" aria-label="Report trace operations">
      <div className="trace-status-grid">
        <TraceMetric label="Local trace" value={trace?.status ?? (runId ? "pending" : "not started")} />
        <TraceMetric label="Run" value={runId ?? "not started"} />
        <TraceMetric label="Provider" value={trace?.provider ?? "local"} />
        <TraceMetric label="External trace" value={trace?.external_trace_id ?? "not exported"} />
      </div>
      {traceUrl ? (
        <a className="trace-link" href={traceUrl} target="_blank" rel="noreferrer">
          Open LangFuse trace
        </a>
      ) : null}
      {error ? <p className="error">{error}</p> : null}
    </section>
  );
}

function TraceMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="trace-metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function formatDecisionTitle(event: RunEvent | undefined): string {
  const rating = typeof event?.payload.rating === "string" ? event.payload.rating : null;
  const action = typeof event?.payload.action === "string" ? event.payload.action : null;

  return rating && action ? `${rating} / ${action}` : "Awaiting report";
}

function formatDecisionBody(event: RunEvent | undefined): string {
  return typeof event?.payload.thesis === "string"
    ? englishOrNotice(event.payload.thesis)
    : "Run a deep research trace to generate the visible report, ledger events, and exportable LangFuse trace.";
}

function formatDecisionSource(event: RunEvent | undefined): string {
  if (!event) {
    return "Awaiting runner";
  }
  return event.payload.fallback === true ? "Deterministic fallback" : "LLM synthesis";
}

function isTerminalRun(events: RunEvent[], terminalType: "run.completed" | "run.failed"): boolean {
  return events.some((event) => event.type === terminalType);
}

function formatStoredRunTitle(run: RunSummary): string {
  const stance = run.final_rating && run.final_action ? `${run.final_rating} / ${run.final_action}` : "Research trace";
  return `${run.ticker} ${stance}`;
}

function formatShortTimestamp(value: string): string {
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit"
  }).format(new Date(value));
}
