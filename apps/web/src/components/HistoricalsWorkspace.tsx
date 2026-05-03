"use client";

import { getHistoricalOutcomes, type HistoricalOutcome } from "@/lib/workspace-data";

export function HistoricalsWorkspace({ symbol }: { symbol: string }) {
  const outcomes = getHistoricalOutcomes(symbol);
  const accuracyCount = outcomes.filter((outcome) => isDirectionallyCorrect(outcome)).length;

  return (
    <section className="historicals-workspace" aria-label="Historicals workspace">
      <header className="workspace-header historicals-header">
        <div>
          <span className="panel-kicker">Prediction review</span>
          <h1>{symbol} historicals</h1>
        </div>
        <div className="historicals-score">
          <span>Directional hit rate</span>
          <strong>
            {accuracyCount}/{outcomes.length}
          </strong>
        </div>
      </header>

      <section className="historical-timeline-panel" aria-label="Prediction versus actual timeline">
        <header className="panel-header">
          <div>
            <span className="panel-kicker">Prediction vs actual</span>
            <h2>Reviewed outcomes</h2>
          </div>
          <span className="panel-count">{outcomes.length}</span>
        </header>
        <div className="historical-axis" aria-hidden="true">
          <span>-8%</span>
          <span>0</span>
          <span>+8%</span>
        </div>
        <div className="historical-outcome-list">
          {outcomes.map((outcome) => (
            <HistoricalOutcomeRow key={outcome.reportId} outcome={outcome} />
          ))}
        </div>
      </section>

      <div className="historical-review-grid">
        <section className="historical-panel">
          <header className="panel-header">
            <div>
              <span className="panel-kicker">Acted-on stances</span>
              <h2>Research posture</h2>
            </div>
          </header>
          <div className="stance-review-list">
            {outcomes.map((outcome) => (
              <article className="stance-review-row" key={`${outcome.reportId}-stance`}>
                <span className={`stance-badge ${getStanceTone(outcome.predictedStance)}`}>
                  {outcome.predictedStance}
                </span>
                <div>
                  <strong>{outcome.horizon}</strong>
                  <p>{outcome.actualOutcome}</p>
                </div>
              </article>
            ))}
          </div>
        </section>

        <section className="historical-panel">
          <header className="panel-header">
            <div>
              <span className="panel-kicker">Feedback notes</span>
              <h2>Review ledger</h2>
            </div>
          </header>
          <div className="feedback-note-list">
            {outcomes.map((outcome) => (
              <article className="feedback-note" key={`${outcome.reportId}-note`}>
                <div className="feedback-note-heading">
                  <strong>{formatDate(outcome.predictionDate)}</strong>
                  <span>{formatReturnDelta(outcome)}</span>
                </div>
                <div className="review-tag-list">
                  {outcome.reviewTags.map((tag) => (
                    <span key={tag}>{tag}</span>
                  ))}
                </div>
                <p>{outcome.notes}</p>
              </article>
            ))}
          </div>
        </section>
      </div>
    </section>
  );
}

function HistoricalOutcomeRow({ outcome }: { outcome: HistoricalOutcome }) {
  return (
    <article className="historical-outcome-row">
      <div className="outcome-date">
        <strong>{formatDate(outcome.predictionDate)}</strong>
        <span>{outcome.horizon}</span>
      </div>
      <div className="outcome-bars">
        <ReturnBar label="Expected" value={outcome.expectedReturn} tone="expected" />
        <ReturnBar label="Actual" value={outcome.actualReturn} tone="actual" />
      </div>
      <div className="outcome-summary">
        <strong>{outcome.predictedStance}</strong>
        <span>{outcome.actualOutcome}</span>
      </div>
    </article>
  );
}

function ReturnBar({ label, value, tone }: { label: string; value: number; tone: "expected" | "actual" }) {
  const offset = 50;
  const width = Math.min(Math.abs(value) * 4.5, 46);
  const left = value >= 0 ? offset : offset - width;

  return (
    <div className="return-bar-row">
      <span>{label}</span>
      <div className="return-bar-track">
        <span
          className={`return-bar ${tone} ${value >= 0 ? "positive" : "negative"}`}
          style={{ left: `${left}%`, width: `${width}%` }}
        />
      </div>
      <strong className={value >= 0 ? "positive" : "negative"}>{formatSignedPercent(value)}</strong>
    </div>
  );
}

function isDirectionallyCorrect(outcome: HistoricalOutcome): boolean {
  return outcome.reviewTags.includes("directionally-correct") || outcome.reviewTags.includes("risk-managed");
}

function getStanceTone(stance: string): "bullish" | "neutral" | "bearish" {
  if (stance === "constructive") return "bullish";
  if (stance === "cautious") return "bearish";

  return "neutral";
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric"
  }).format(new Date(`${value}T00:00:00.000Z`));
}

function formatSignedPercent(value: number): string {
  const formatted = `${Math.abs(value).toFixed(1)}%`;

  return value >= 0 ? `+${formatted}` : `-${formatted}`;
}

function formatReturnDelta(outcome: HistoricalOutcome): string {
  const delta = outcome.actualReturn - outcome.expectedReturn;

  return `${formatSignedPercent(delta)} vs expected`;
}
