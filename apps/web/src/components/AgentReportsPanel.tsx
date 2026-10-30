import type { AgentReport } from "@/lib/agent-reports";

export function AgentReportsPanel({
  reports,
  selectedReportId,
  onSelectReport
}: {
  reports: AgentReport[];
  selectedReportId: string | null;
  onSelectReport: (reportId: string) => void;
}) {
  const selectedReport = reports.find((report) => report.id === selectedReportId) ?? reports[0] ?? null;

  return (
    <section className="agent-reports-panel" aria-label="Individual agent reports">
      <header>
        <div>
          <span className="panel-kicker">Individual agent reports</span>
          <h2>{selectedReport?.agentName ?? "No agent report selected"}</h2>
        </div>
        <span className="panel-count">{reports.length}</span>
      </header>
      {reports.length > 0 && selectedReport ? (
        <div className="agent-reports-grid">
          <nav className="agent-report-tabs" aria-label="Report list">
            <span className="panel-kicker">Report list</span>
            {reports.map((report) => (
              <button
                aria-current={report.id === selectedReport.id ? "true" : undefined}
                className={report.id === selectedReport.id ? "agent-report-tab selected" : "agent-report-tab"}
                key={report.id}
                onClick={() => onSelectReport(report.id)}
                type="button"
              >
                <strong>{report.agentName}</strong>
                <span>{report.section}</span>
              </button>
            ))}
          </nav>
          <article className="agent-report-reader" aria-label="Report details">
            <div className="agent-report-reader-meta">
              <span>Report details</span>
              <span>{selectedReport.section}</span>
              <span>{selectedReport.sourceLabel}</span>
              <span>{selectedReport.advisoryLabel}</span>
            </div>
            <p>{selectedReport.body}</p>
          </article>
        </div>
      ) : (
        <p className="empty-state">Run a research trace to read each agent report as it lands.</p>
      )}
    </section>
  );
}
