"use client";

import { useMemo, useState } from "react";

import { InfoModal } from "@/components/InfoModal";
import { createPortfolioReview, recordApprovalLedgerEntry } from "@/lib/api";
import {
  buildPortfolioReviewThesis,
  type PortfolioReviewInput,
  type PortfolioReviewThesis
} from "@/lib/portfolio-review";
import type { RoomDecisionAction } from "@/lib/types";

const reviewActions: RoomDecisionAction[] = ["accept", "reject", "revise", "defer", "escalate"];

const defaultReviewInput = (symbol: string): PortfolioReviewInput => ({
  constraints: "",
  goals: "",
  horizon: "3-6 months",
  liquidityNeeds: "",
  riskPosture: "balanced",
  sectors: "",
  symbol
});

export function PortfolioReviewPanel({
  symbol,
  onOpenResearch
}: {
  symbol: string;
  onOpenResearch: () => void;
}) {
  const [reviewInput, setReviewInput] = useState<PortfolioReviewInput>(() => defaultReviewInput(symbol));
  const [reviewSaveStatus, setReviewSaveStatus] = useState<{
    state: "idle" | "saving" | "saved" | "failed";
    action: "generated" | RoomDecisionAction | null;
    message: string;
  }>({
    action: null,
    message: "Local advisory draft. Provider-backed holdings, cash, and balances are not connected here.",
    state: "idle"
  });
  const [reviewThesis, setReviewThesis] = useState<PortfolioReviewThesis | null>(null);
  const [showReviewDetails, setShowReviewDetails] = useState(false);
  const [decisionStatus, setDecisionStatus] = useState<{
    action: RoomDecisionAction;
    state: "saving" | "saved" | "failed";
  } | null>(null);

  const activeInput = useMemo(
    () => ({
      ...reviewInput,
      symbol
    }),
    [reviewInput, symbol]
  );

  function updateReviewInput<K extends keyof PortfolioReviewInput>(key: K, value: PortfolioReviewInput[K]) {
    setReviewInput((currentInput) => ({
      ...currentInput,
      [key]: value
    }));
  }

  async function persistPortfolioReview(thesis: PortfolioReviewThesis, action: "generated" | RoomDecisionAction) {
    setReviewSaveStatus({
      action,
      message: "Saving portfolio review record. Provider facts remain unavailable until a portfolio provider responds.",
      state: "saving"
    });

    try {
      await createPortfolioReview({
        constraints: activeInput.constraints,
        goals: activeInput.goals,
        horizon: activeInput.horizon,
        liquidityNeeds: activeInput.liquidityNeeds,
        missingProviderFacts: [
          "provider-backed holdings",
          "portfolio balances",
          "cash buying power"
        ],
        payload: {
          action,
          local_model: "portfolio-review",
          review_input: activeInput,
          source: "portfolio-review",
          summary: thesis.summary,
          thesis
        },
        riskPosture: activeInput.riskPosture,
        sectorFocus: activeInput.sectors,
        status: action === "generated" ? "draft" : action,
        symbol,
        thesis: thesis as unknown as Record<string, unknown>
      });
      setReviewSaveStatus({
        action,
        message: "Portfolio review record saved. This saved thesis still depends on provider-backed holdings, cash, and account facts.",
        state: "saved"
      });
    } catch {
      setReviewSaveStatus({
        action,
        message: "Portfolio review API unavailable. Keeping this local advisory thesis in the browser for now.",
        state: "failed"
      });
    }
  }

  function generatePortfolioThesis() {
    const thesis = buildPortfolioReviewThesis(activeInput);
    setReviewThesis(thesis);
    setDecisionStatus(null);
    void persistPortfolioReview(thesis, "generated");
  }

  async function recordReviewDecision(action: RoomDecisionAction) {
    const thesis = reviewThesis ?? buildPortfolioReviewThesis(activeInput);
    setDecisionStatus({ action, state: "saving" });
    void persistPortfolioReview(thesis, action);

    try {
      await recordApprovalLedgerEntry({
        action,
        actor: "local-user",
        entityId: `${symbol.toLowerCase()}-portfolio-review`,
        entityType: "portfolio_review",
        payload: {
          review_input: activeInput,
          thesis
        },
        roomId: "dashboard",
        source: "portfolio-review",
        summary: `Portfolio review ${action} for ${symbol}`
      });
      setReviewThesis(thesis);
      setDecisionStatus({ action, state: "saved" });
    } catch {
      setDecisionStatus({ action, state: "failed" });
    }
  }

  const visibleThesis = reviewThesis ?? buildPortfolioReviewThesis(activeInput);

  return (
    <article className="dashboard-home-panel portfolio-review-panel">
      <div className="dashboard-panel-title">
        <span className="panel-kicker">Portfolio review</span>
        <span className="panel-control-dot" aria-hidden="true" />
      </div>
      <div className="portfolio-review-header">
        <div>
          <h2>Investment counselor meeting</h2>
          <p>
            Capture goals, risk posture, sector focus, and constraints before sending individual names into deep research.
          </p>
        </div>
        <span>{symbol}</span>
      </div>
      <div className="portfolio-review-form" aria-label="Portfolio review inputs">
        <label>
          Goals and time horizon
          <textarea
            value={reviewInput.goals}
            onChange={(event) => updateReviewInput("goals", event.target.value)}
            placeholder="Example: build liquid capital for a major asset purchase, preserve cash runway, compound over five years."
          />
        </label>
        <div className="portfolio-review-row">
          <label>
            Horizon
            <select
              value={reviewInput.horizon}
              onChange={(event) => updateReviewInput("horizon", event.target.value)}
            >
              <option>Next 4 weeks</option>
              <option>3-6 months</option>
              <option>6-12 months</option>
              <option>1-3 years</option>
              <option>3-10 years</option>
            </select>
          </label>
          <label>
            Risk posture
            <select
              value={reviewInput.riskPosture}
              onChange={(event) => updateReviewInput("riskPosture", event.target.value as PortfolioReviewInput["riskPosture"])}
            >
              <option value="capital-preservation">Capital preservation</option>
              <option value="balanced">Balanced</option>
              <option value="growth">Growth</option>
              <option value="high-risk">High-risk</option>
            </select>
          </label>
        </div>
        <label>
          Sector focus
          <input
            value={reviewInput.sectors}
            onChange={(event) => updateReviewInput("sectors", event.target.value)}
            placeholder="AI semiconductors, healthcare, index core"
          />
        </label>
        <label>
          Constraints and liquidity
          <textarea
            value={`${reviewInput.constraints}${reviewInput.constraints && reviewInput.liquidityNeeds ? "\n" : ""}${reviewInput.liquidityNeeds}`}
            onChange={(event) => {
              const [constraints, ...liquidityParts] = event.target.value.split("\n");
              updateReviewInput("constraints", constraints ?? "");
              updateReviewInput("liquidityNeeds", liquidityParts.join(" "));
            }}
            placeholder="Constraints on line one. Liquidity needs on line two."
          />
        </label>
        <button className="primary-button" type="button" onClick={generatePortfolioThesis}>
          Generate portfolio thesis
        </button>
      </div>
      <section className="portfolio-thesis-output" aria-label="Portfolio review thesis">
        <div className="portfolio-review-output-header">
          <span className="panel-kicker">Counselor output</span>
          <button className="micro-action-button" type="button" onClick={() => setShowReviewDetails(true)}>
            View review details
          </button>
        </div>
        <h3>{visibleThesis.title}</h3>
        <p>{visibleThesis.summary}</p>
        <div className="portfolio-review-summary-row" aria-label="Portfolio review summary">
          <span>{visibleThesis.tracks.length} advisor desks</span>
          <span>{visibleThesis.missingProviderFacts.length} provider facts missing</span>
          <span>{visibleThesis.researchCandidates.length} research candidate</span>
        </div>
      </section>
      <section className="portfolio-research-queue" aria-label="Research queue">
        <div className="dashboard-panel-title">
          <span className="panel-kicker">Research queue</span>
          <button className="micro-action-button" type="button" onClick={onOpenResearch}>
            Open Research Office
          </button>
        </div>
        <div>
          {visibleThesis.researchCandidates.map((candidate) => (
            <span key={candidate.symbol} title={candidate.reason}>
              {candidate.symbol}
            </span>
          ))}
        </div>
      </section>
      <section className="portfolio-review-decisions" aria-label="Portfolio review decisions">
        <div className="dashboard-command-actions">
          {reviewActions.map((action) => (
            <button
              className="micro-action-button"
              disabled={decisionStatus?.state === "saving"}
              key={action}
              onClick={() => void recordReviewDecision(action)}
              type="button"
            >
              {action}
            </button>
          ))}
        </div>
        {decisionStatus ? (
          <p className={decisionStatus.state === "failed" ? "error" : "dashboard-approval-state"} role="status">
            {decisionStatus.state === "saved"
              ? `Review decision saved: ${decisionStatus.action}`
              : decisionStatus.state === "failed"
                ? `Unable to save review decision: ${decisionStatus.action}`
                : `Saving review decision: ${decisionStatus.action}`}
          </p>
        ) : null}
        <p
          className={reviewSaveStatus.state === "failed" ? "error" : "dashboard-approval-state"}
          role="status"
        >
          {reviewSaveStatus.message}
        </p>
      </section>
      {showReviewDetails ? (
        <InfoModal title="Portfolio review details" onClose={() => setShowReviewDetails(false)}>
          <section className="portfolio-thesis-output" aria-label="Portfolio review detail thesis">
            <span className="panel-kicker">{visibleThesis.title}</span>
            <p>{visibleThesis.summary}</p>
            <div className="portfolio-review-track-grid">
              {visibleThesis.tracks.map((track) => (
                <div key={track.team}>
                  <strong>{track.team}</strong>
                  <span>{track.focus}</span>
                  <small>{track.output}</small>
                </div>
              ))}
            </div>
          </section>
          <section className="portfolio-provider-facts" aria-label="Provider facts still needed">
            <div className="dashboard-panel-title">
              <span className="panel-kicker">Provider facts still needed</span>
            </div>
            <ul>
              {visibleThesis.missingProviderFacts.map((fact) => (
                <li key={fact}>{fact}</li>
              ))}
            </ul>
          </section>
        </InfoModal>
      ) : null}
    </article>
  );
}
