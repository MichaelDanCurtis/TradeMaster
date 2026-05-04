"use client";

import { useEffect, useMemo, useState } from "react";

import { AgentRunGraph } from "@/components/AgentRunGraph";
import { RunTimeline } from "@/components/RunTimeline";
import { createRun, exportRunTrace, getRunTrace, listRunEvents } from "@/lib/api";
import {
  getPrivateOfficeBrief,
  getPrivateOfficeRunQueue,
  getPrivateOfficeTeams,
  getResearchReports
} from "@/lib/workspace-data";
import type {
  PrivateOfficeBrief,
  PrivateOfficeRunQueueItem,
  PrivateOfficeTeam,
  ResearchReport
} from "@/lib/workspace-data";
import type { RunEvent, RunTrace } from "@/lib/types";

export function DeepResearchWorkspace({ symbol }: { symbol: string }) {
  const reports = useMemo(() => getResearchReports(symbol), [symbol]);
  const brief = useMemo(() => getPrivateOfficeBrief(symbol), [symbol]);
  const teams = useMemo(() => getPrivateOfficeTeams(symbol), [symbol]);
  const runQueue = useMemo(() => getPrivateOfficeRunQueue(symbol), [symbol]);
  const [selectedReportId, setSelectedReportId] = useState<string | null>(null);
  const [runIds, setRunIds] = useState<Record<string, string>>({});
  const [eventsByReport, setEventsByReport] = useState<Record<string, RunEvent[]>>({});
  const [traceByReport, setTraceByReport] = useState<Record<string, RunTrace>>({});
  const [busyReportId, setBusyReportId] = useState<string | null>(null);
  const [exportingReportId, setExportingReportId] = useState<string | null>(null);
  const [traceError, setTraceError] = useState<string | null>(null);
  const selectedReport =
    reports.find((report) => report.id === selectedReportId) ?? reports[0] ?? null;

  useEffect(() => {
    setSelectedReportId(reports[0]?.id ?? null);
    setRunIds({});
    setEventsByReport({});
    setTraceByReport({});
    setTraceError(null);
  }, [reports]);

  async function startReportRun(report: ResearchReport) {
    setBusyReportId(report.id);
    setTraceError(null);
    setEventsByReport((current) => ({ ...current, [report.id]: [] }));

    try {
      const created = await createRun({
        ticker: report.symbol,
        tradeDate: report.createdAt.slice(0, 10),
        brokerMode: "disabled"
      });
      setRunIds((current) => ({ ...current, [report.id]: created.run_id }));
      const [events, trace] = await Promise.all([
        listRunEvents(created.run_id),
        getRunTrace(created.run_id)
      ]);
      setEventsByReport((current) => ({ ...current, [report.id]: events }));
      setTraceByReport((current) => ({ ...current, [report.id]: trace }));
    } catch (caught) {
      setTraceError(caught instanceof Error ? caught.message : "Unable to start report trace");
    } finally {
      setBusyReportId(null);
    }
  }

  async function exportSelectedTrace(report: ResearchReport) {
    const runId = runIds[report.id] ?? traceByReport[report.id]?.run_id;
    if (!runId) {
      setTraceError("Run the report before exporting a trace.");
      return;
    }

    setExportingReportId(report.id);
    setTraceError(null);
    try {
      const exported = await exportRunTrace(runId);
      setTraceByReport((current) => ({ ...current, [report.id]: exported }));
    } catch (caught) {
      setTraceError(caught instanceof Error ? caught.message : "Unable to export trace");
    } finally {
      setExportingReportId(null);
    }
  }

  return (
    <section className="deep-research-workspace" aria-label="Deep Research private office workspace">
      <ReportList
        reports={reports}
        selectedReportId={selectedReport?.id ?? null}
        traceByReport={traceByReport}
        runIds={runIds}
        onSelectReport={setSelectedReportId}
      />
      <PrivateOfficeCanvas
        brief={brief}
        teams={teams}
        report={selectedReport}
        symbol={symbol}
        runId={selectedReport ? runIds[selectedReport.id] ?? null : null}
        events={selectedReport ? eventsByReport[selectedReport.id] ?? [] : []}
        trace={selectedReport ? traceByReport[selectedReport.id] ?? null : null}
        traceError={traceError}
        isRunning={selectedReport ? busyReportId === selectedReport.id : false}
        isExporting={selectedReport ? exportingReportId === selectedReport.id : false}
        onStartReportRun={startReportRun}
        onExportTrace={exportSelectedTrace}
      />
      <RunningReportsPanel queue={runQueue} symbol={symbol} />
    </section>
  );
}

function ReportList({
  reports,
  selectedReportId,
  traceByReport,
  runIds,
  onSelectReport
}: {
  reports: ResearchReport[];
  selectedReportId: string | null;
  traceByReport: Record<string, RunTrace>;
  runIds: Record<string, string>;
  onSelectReport: (reportId: string) => void;
}) {
  return (
    <aside className="research-report-rail">
      <header className="panel-header">
        <div>
          <span className="panel-kicker">Reports</span>
          <h2>Deep Research</h2>
        </div>
        <span className="panel-count">{reports.length}</span>
      </header>
      <div className="research-report-list">
        {reports.map((report) => {
          const trace = traceByReport[report.id];
          const traceStatus = trace?.external_trace_id ? "LangFuse" : trace ? trace.status : runIds[report.id] ? "Pending" : "No trace";
          return (
            <button
              className={report.id === selectedReportId ? "research-report-item selected" : "research-report-item"}
              key={report.id}
              type="button"
              onClick={() => onSelectReport(report.id)}
            >
              <span>{formatDate(report.createdAt)}</span>
              <strong>{report.title}</strong>
              <small>{report.horizon}</small>
              <div>
                <span className={`stance-badge ${report.stance}`}>{report.stance}</span>
                <span>{Math.round(report.confidence * 100)}%</span>
              </div>
              <span className={trace?.external_trace_id ? "trace-status exported" : "trace-status"}>{traceStatus}</span>
            </button>
          );
        })}
      </div>
    </aside>
  );
}

function PrivateOfficeCanvas({
  brief,
  teams,
  report,
  symbol,
  runId,
  events,
  trace,
  traceError,
  isRunning,
  isExporting,
  onStartReportRun,
  onExportTrace
}: {
  brief: PrivateOfficeBrief;
  teams: PrivateOfficeTeam[];
  report: ResearchReport | null;
  symbol: string;
  runId: string | null;
  events: RunEvent[];
  trace: RunTrace | null;
  traceError: string | null;
  isRunning: boolean;
  isExporting: boolean;
  onStartReportRun: (report: ResearchReport) => void;
  onExportTrace: (report: ResearchReport) => void;
}) {
  return (
    <article className="private-office-canvas">
      <header className="workspace-header private-office-header">
        <div>
          <span className="panel-kicker">A2UI agent canvas</span>
          <h1>{brief.headline}</h1>
        </div>
        <div className="research-meta-strip">
          <span>{symbol}</span>
          <span>{formatDate(brief.generatedAt)}</span>
          <span>Approval gated</span>
        </div>
      </header>
      <section className="a2ui-morning-brief">
        <div className="section-title">
          <span>Morning synopsis</span>
          <strong>{brief.priorityItems.length}</strong>
        </div>
        <ol>
          {brief.priorityItems.map((item, index) => (
            <li key={item}>
              <span>{String(index + 1).padStart(2, "0")}</span>
              <p>{item}</p>
            </li>
          ))}
        </ol>
      </section>
      <section className="private-office-grid">
        <GoalSignalPanel brief={brief} />
        <ControlSignalPanel brief={brief} />
      </section>
      <TeamBodyGrid teams={teams} />
      {report ? (
        <ReportA2UIPanel
          report={report}
          runId={runId}
          events={events}
          trace={trace}
          traceError={traceError}
          isRunning={isRunning}
          isExporting={isExporting}
          onStartReportRun={onStartReportRun}
          onExportTrace={onExportTrace}
        />
      ) : (
        <p className="empty-state">No research reports are available.</p>
      )}
    </article>
  );
}

function GoalSignalPanel({ brief }: { brief: PrivateOfficeBrief }) {
  return (
    <section className="private-office-panel">
      <div className="section-title">
        <span>Goal signals</span>
        <strong>{brief.goalSignals.length}</strong>
      </div>
      <div className="signal-stack">
        {brief.goalSignals.map((signal) => (
          <article className="signal-card" key={signal.goalName}>
            <span>{signal.status}</span>
            <strong>{signal.goalName}</strong>
            <p>{signal.detail}</p>
          </article>
        ))}
      </div>
    </section>
  );
}

function ControlSignalPanel({ brief }: { brief: PrivateOfficeBrief }) {
  return (
    <section className="private-office-panel">
      <div className="section-title">
        <span>Control signals</span>
        <strong>{brief.controlSignals.length}</strong>
      </div>
      <div className="signal-stack">
        {brief.controlSignals.map((signal) => (
          <article className={`signal-card ${signal.severity}`} key={signal.team}>
            <span>{signal.severity}</span>
            <strong>{signal.team}</strong>
            <p>{signal.detail}</p>
          </article>
        ))}
      </div>
    </section>
  );
}

function TeamBodyGrid({ teams }: { teams: PrivateOfficeTeam[] }) {
  return (
    <section className="team-body-grid" aria-label="Wealth Agents team bodies">
      {teams.map((team) => (
        <article className={`team-body-card ${team.kind}`} key={team.id}>
          <header>
            <span>{team.kind}</span>
            <strong>{team.name}</strong>
          </header>
          <p>{team.mission}</p>
          <div className="team-meta-row">
            <span>{team.cadence}</span>
            <span>{team.riskClass}</span>
          </div>
          <ul>
            {team.responsibilities.slice(0, 2).map((responsibility) => (
              <li key={responsibility}>{responsibility}</li>
            ))}
          </ul>
          <footer>
            {team.a2uiSurfaces.slice(0, 3).map((surface) => (
              <span key={surface}>{surface}</span>
            ))}
          </footer>
        </article>
      ))}
    </section>
  );
}

function ReportA2UIPanel({
  report,
  runId,
  events,
  trace,
  traceError,
  isRunning,
  isExporting,
  onStartReportRun,
  onExportTrace
}: {
  report: ResearchReport;
  runId: string | null;
  events: RunEvent[];
  trace: RunTrace | null;
  traceError: string | null;
  isRunning: boolean;
  isExporting: boolean;
  onStartReportRun: (report: ResearchReport) => void;
  onExportTrace: (report: ResearchReport) => void;
}) {
  const traceUrl =
    typeof trace?.metadata.external_trace_url === "string" ? trace.metadata.external_trace_url : null;
  const traceStatus = trace?.status ?? (runId ? "pending" : "not started");
  const canExport = Boolean(trace && runId && !isRunning && !isExporting);

  return (
    <section className="report-a2ui-panel">
      <header>
        <div>
          <span className={`stance-badge ${report.stance}`}>{report.stance}</span>
          <h2>{report.title}</h2>
        </div>
        <div className="report-action-cluster">
          <div className="research-meta-strip">
            <span>{formatDate(report.createdAt)}</span>
            <span>{report.horizon}</span>
            <span>{Math.round(report.confidence * 100)}% confidence</span>
          </div>
          <div className="trace-action-row">
            <button className="trace-action primary" type="button" onClick={() => onStartReportRun(report)} disabled={isRunning}>
              {isRunning ? "Running..." : "Run trace"}
            </button>
            <button className="trace-action" type="button" onClick={() => onExportTrace(report)} disabled={!canExport}>
              {isExporting ? "Exporting..." : "Export"}
            </button>
          </div>
        </div>
      </header>
      <p>{report.summary}</p>
      <TraceOperationsPanel trace={trace} traceStatus={traceStatus} runId={runId} traceUrl={traceUrl} traceError={traceError} />
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
      ) : null}
      <section className="research-ledger-grid">
        <div className="research-ledger-panel">
          <div className="section-title">
            <span>Decision ledger</span>
            <strong>{report.ledgerState.length}</strong>
          </div>
          <ol className="decision-ledger-list">
            {report.ledgerState.map((entry, index) => (
              <li key={entry}>
                <span>{String(index + 1).padStart(2, "0")}</span>
                <p>{entry}</p>
              </li>
            ))}
          </ol>
        </div>
        <div className="research-side-panels">
          <ResearchListPanel title="Risk notes" items={report.riskNotes} />
          <ResearchListPanel title="Synthesis steps" items={report.synthesisSteps} />
        </div>
      </section>
    </section>
  );
}

function TraceOperationsPanel({
  trace,
  traceStatus,
  runId,
  traceUrl,
  traceError
}: {
  trace: RunTrace | null;
  traceStatus: string;
  runId: string | null;
  traceUrl: string | null;
  traceError: string | null;
}) {
  return (
    <section className="trace-operations-panel" aria-label="Report trace operations">
      <div className="trace-status-grid">
        <TraceMetric label="Local trace" value={traceStatus} />
        <TraceMetric label="Run" value={runId ?? "not started"} />
        <TraceMetric label="Provider" value={trace?.provider ?? "local"} />
        <TraceMetric label="External trace" value={trace?.external_trace_id ?? "not exported"} />
      </div>
      {traceUrl ? (
        <a className="trace-link" href={traceUrl} target="_blank" rel="noreferrer">
          Open LangFuse trace
        </a>
      ) : null}
      {traceError ? <p className="error">{traceError}</p> : null}
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

function RunningReportsPanel({ queue, symbol }: { queue: PrivateOfficeRunQueueItem[]; symbol: string }) {
  return (
    <aside className="running-reports-panel">
      <header className="panel-header">
        <div>
          <span className="panel-kicker">Running reports</span>
          <h2>{symbol} queue</h2>
        </div>
        <span className="panel-count">{queue.length}</span>
      </header>
      <div className="run-queue-list">
        {queue.map((item) => (
          <section className="run-queue-card" key={item.id}>
            <div>
              <span className={`run-state ${item.status}`}>{item.status}</span>
              <strong>{item.title}</strong>
              <small>{item.team}</small>
            </div>
            <ol>
              {item.steps.map((step) => (
                <li key={step.label}>
                  <span className={`step-dot ${step.status}`} />
                  {step.label}
                </li>
              ))}
            </ol>
          </section>
        ))}
      </div>
    </aside>
  );
}

function ResearchListPanel({ title, items }: { title: string; items: string[] }) {
  return (
    <section className="research-list-panel">
      <div className="section-title">
        <span>{title}</span>
        <strong>{items.length}</strong>
      </div>
      <ul>
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </section>
  );
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  }).format(new Date(value));
}
