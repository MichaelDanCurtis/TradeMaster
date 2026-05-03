"use client";

import { useEffect, useMemo, useState } from "react";

import { AgentCockpit } from "@/components/AgentCockpit";
import { getResearchReports } from "@/lib/workspace-data";
import type { ResearchReport } from "@/lib/workspace-data";

export function DeepResearchWorkspace({ symbol }: { symbol: string }) {
  const reports = useMemo(() => getResearchReports(symbol), [symbol]);
  const [selectedReportId, setSelectedReportId] = useState<string | null>(null);
  const selectedReport =
    reports.find((report) => report.id === selectedReportId) ?? reports[0] ?? null;

  useEffect(() => {
    setSelectedReportId(reports[0]?.id ?? null);
  }, [reports]);

  return (
    <section className="deep-research-workspace" aria-label="Deep Research workspace">
      <ReportList reports={reports} selectedReportId={selectedReport?.id ?? null} onSelectReport={setSelectedReportId} />
      <ReportDetail report={selectedReport} />
      <AgentCockpit symbol={symbol} showTradeTicket={false} />
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

function ReportDetail({ report }: { report: ResearchReport | null }) {
  if (!report) {
    return (
      <section className="research-detail">
        <p className="empty-state">No research reports are available for this symbol.</p>
      </section>
    );
  }

  return (
    <article className="research-detail">
      <header className="workspace-header research-detail-header">
        <div>
          <span className="panel-kicker">Selected report</span>
          <h1>{report.symbol}</h1>
        </div>
        <div className="research-meta-strip">
          <span>{formatDate(report.createdAt)}</span>
          <span>{report.horizon}</span>
          <span>{Math.round(report.confidence * 100)}% confidence</span>
        </div>
      </header>
      <section className="research-summary-panel">
        <div>
          <span className={`stance-badge ${report.stance}`}>{report.stance}</span>
          <h2>{report.title}</h2>
        </div>
        <p>{report.summary}</p>
      </section>
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
    </article>
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
