"use client";

import { useEffect, useMemo, useState } from "react";

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

export function DeepResearchWorkspace({ symbol }: { symbol: string }) {
  const reports = useMemo(() => getResearchReports(symbol), [symbol]);
  const brief = useMemo(() => getPrivateOfficeBrief(symbol), [symbol]);
  const teams = useMemo(() => getPrivateOfficeTeams(symbol), [symbol]);
  const runQueue = useMemo(() => getPrivateOfficeRunQueue(symbol), [symbol]);
  const [selectedReportId, setSelectedReportId] = useState<string | null>(null);
  const selectedReport =
    reports.find((report) => report.id === selectedReportId) ?? reports[0] ?? null;

  useEffect(() => {
    setSelectedReportId(reports[0]?.id ?? null);
  }, [reports]);

  return (
    <section className="deep-research-workspace" aria-label="Deep Research private office workspace">
      <ReportList reports={reports} selectedReportId={selectedReport?.id ?? null} onSelectReport={setSelectedReportId} />
      <PrivateOfficeCanvas brief={brief} teams={teams} report={selectedReport} symbol={symbol} />
      <RunningReportsPanel queue={runQueue} symbol={symbol} />
    </section>
  );
}

function ReportList({
  reports,
  selectedReportId,
  onSelectReport
}: {
  reports: ResearchReport[];
  selectedReportId: string | null;
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
        {reports.map((report) => (
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
          </button>
        ))}
      </div>
    </aside>
  );
}

function PrivateOfficeCanvas({
  brief,
  teams,
  report,
  symbol
}: {
  brief: PrivateOfficeBrief;
  teams: PrivateOfficeTeam[];
  report: ResearchReport | null;
  symbol: string;
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
      {report ? <ReportA2UIPanel report={report} /> : <p className="empty-state">No research reports are available.</p>}
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

function ReportA2UIPanel({ report }: { report: ResearchReport }) {
  return (
    <section className="report-a2ui-panel">
      <header>
        <div>
          <span className={`stance-badge ${report.stance}`}>{report.stance}</span>
          <h2>{report.title}</h2>
        </div>
        <div className="research-meta-strip">
          <span>{formatDate(report.createdAt)}</span>
          <span>{report.horizon}</span>
          <span>{Math.round(report.confidence * 100)}% confidence</span>
        </div>
      </header>
      <p>{report.summary}</p>
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
