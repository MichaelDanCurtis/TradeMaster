"use client";

import { useEffect, useMemo, useState } from "react";

import { createTradeThesis, listTradeTheses } from "@/lib/api";
import {
  buildOrderThesisDraft,
  orderThesisDecisionActions,
  orderThesisStatusFlow,
  type OrderThesisDraft,
  type OrderThesisInput
} from "@/lib/order-thesis";
import type { TradeThesis } from "@/lib/types";

type OrderThesisPanelProps = {
  symbol: string;
  sourceReportId?: string | null;
  onOpenBrokerage: () => void;
};

const defaultDraftInput = (symbol: string, sourceReportId?: string | null): OrderThesisInput => ({
  action: "review",
  catalysts: ["Research report needs broker desk review."],
  conviction: "medium",
  horizon: "3-6 months",
  invalidation: "Research desk has not set an invalidation level yet.",
  riskNotes: "Brokerage desk must review sizing, liquidity, concentration, and compliance before execution intent.",
  sourceReportId,
  symbol,
  thesisText: "Research output is ready to be translated into a broker-reviewable thesis."
});

export function OrderThesisPanel({ symbol, sourceReportId = null, onOpenBrokerage }: OrderThesisPanelProps) {
  const [draftInput, setDraftInput] = useState<OrderThesisInput>(() => defaultDraftInput(symbol, sourceReportId));
  const [draft, setDraft] = useState<OrderThesisDraft | null>(null);
  const [recentTheses, setRecentTheses] = useState<TradeThesis[]>([]);
  const [isLoadingTheses, setIsLoadingTheses] = useState(false);
  const [isSavingThesis, setIsSavingThesis] = useState(false);
  const [thesisStatus, setThesisStatus] = useState<string | null>(null);
  const [thesisError, setThesisError] = useState<string | null>(null);

  const activeInput = useMemo(
    () => ({
      ...draftInput,
      sourceReportId,
      symbol
    }),
    [draftInput, sourceReportId, symbol]
  );
  const visibleDraft = draft ?? buildOrderThesisDraft(activeInput);

  useEffect(() => {
    let isCurrent = true;

    async function loadRecentTheses() {
      setIsLoadingTheses(true);
      setThesisError(null);

      try {
        const catalog = await listTradeTheses({ symbol, targetRoom: "market" });
        if (!isCurrent) {
          return;
        }
        setRecentTheses(filterThesesForSource(catalog.theses, sourceReportId));
      } catch {
        if (isCurrent) {
          setRecentTheses([]);
          setThesisError("Unable to load recent thesis handoffs. You can still draft locally.");
        }
      } finally {
        if (isCurrent) {
          setIsLoadingTheses(false);
        }
      }
    }

    void loadRecentTheses();

    return () => {
      isCurrent = false;
    };
  }, [sourceReportId, symbol]);

  function updateDraftInput<K extends keyof OrderThesisInput>(key: K, value: OrderThesisInput[K]) {
    setDraftInput((currentInput) => ({
      ...currentInput,
      [key]: value
    }));
  }

  function generateDraft() {
    setDraft(buildOrderThesisDraft(activeInput));
  }

  async function saveThesisHandoff() {
    const nextDraft = buildOrderThesisDraft(activeInput);
    setDraft(nextDraft);
    setIsSavingThesis(true);
    setThesisStatus(null);
    setThesisError(null);

    try {
      const savedThesis = await createTradeThesis({
        catalysts: nextDraft.catalysts,
        conviction: convictionToScore(nextDraft.conviction),
        direction: actionToDirection(nextDraft.action),
        horizon: nextDraft.horizon,
        invalidation: [nextDraft.invalidation],
        payload: {
          advisory: true,
          handoff: "research-to-brokerage",
          isBrokerOrder: false,
          preview: nextDraft.preview,
          researchAction: nextDraft.action
        },
        riskNotes: nextDraft.riskNotes,
        sourceReportId: sourceReportId ?? null,
        sourceRoom: "research",
        status: "proposed",
        symbol: nextDraft.symbol,
        targetRoom: "market",
        thesis: nextDraft.thesisText
      });
      setRecentTheses((currentTheses) => [savedThesis, ...filterThesesForSource(currentTheses, sourceReportId)]);
      setThesisStatus("Saved thesis handoff for broker review. Advisory only - no live submission.");
    } catch {
      setThesisError("Unable to save thesis handoff. Backend unavailable; preview remains local.");
    } finally {
      setIsSavingThesis(false);
    }
  }

  return (
    <article className="order-thesis-panel" aria-label="Order Thesis Handoff">
      <header className="panel-header">
        <div>
          <span className="panel-kicker">Advisory research-to-brokerage handoff</span>
          <h2>Order Thesis Handoff</h2>
        </div>
        <span className="stance-badge neutral">Research only - not a broker order</span>
      </header>

      <section className="order-thesis-form" aria-label="Order thesis draft fields">
        <div className="portfolio-review-row">
          <label>
            Rating/action
            <input
              value={draftInput.action}
              onChange={(event) => updateDraftInput("action", event.target.value)}
              placeholder="buy, hold, trim, accumulate, avoid"
            />
          </label>
          <label>
            Horizon
            <select value={draftInput.horizon} onChange={(event) => updateDraftInput("horizon", event.target.value)}>
              <option>Next 4 weeks</option>
              <option>3-6 months</option>
              <option>6-12 months</option>
              <option>1-3 years</option>
            </select>
          </label>
          <label>
            Conviction
            <select
              value={draftInput.conviction}
              onChange={(event) => updateDraftInput("conviction", event.target.value)}
            >
              <option>low</option>
              <option>medium</option>
              <option>high</option>
            </select>
          </label>
        </div>
        <label>
          Thesis text
          <textarea
            value={draftInput.thesisText}
            onChange={(event) => updateDraftInput("thesisText", event.target.value)}
            placeholder="Summarize the research desk thesis for brokerage review."
          />
        </label>
        <label>
          Catalysts
          <textarea
            value={draftInput.catalysts.join("\n")}
            onChange={(event) => updateDraftInput("catalysts", event.target.value.split("\n"))}
            placeholder="One catalyst per line."
          />
        </label>
        <label>
          Invalidation
          <textarea
            value={draftInput.invalidation}
            onChange={(event) => updateDraftInput("invalidation", event.target.value)}
            placeholder="Conditions that would invalidate the thesis."
          />
        </label>
        <label>
          Risk notes
          <textarea
            value={draftInput.riskNotes}
            onChange={(event) => updateDraftInput("riskNotes", event.target.value)}
            placeholder="Sizing, liquidity, compliance, concentration, and scenario risks."
          />
        </label>
        <button className="primary-button" type="button" onClick={generateDraft}>
          Generate thesis preview
        </button>
        <button className="primary-button" type="button" onClick={() => void saveThesisHandoff()} disabled={isSavingThesis}>
          {isSavingThesis ? "Saving..." : "Save thesis handoff"}
        </button>
        {thesisStatus ? <p className="muted">{thesisStatus}</p> : null}
        {thesisError ? <p className="muted">{thesisError}</p> : null}
      </section>

      <section className="order-thesis-preview" aria-label="Generated thesis preview">
        <div className="dashboard-panel-title">
          <span className="panel-kicker">Generated thesis preview</span>
          <span>{visibleDraft.symbol}</span>
        </div>
        <p>{visibleDraft.summary}</p>
        <pre>{visibleDraft.preview}</pre>
      </section>

      <section className="order-thesis-preview" aria-label="Recent thesis handoffs">
        <div className="dashboard-panel-title">
          <span className="panel-kicker">Recent thesis handoffs</span>
          <span>{isLoadingTheses ? "Loading" : `${recentTheses.length} saved`}</span>
        </div>
        {recentTheses.length > 0 ? (
          <div className="research-session-list">
            {recentTheses.map((thesis) => (
              <article className="trade-thesis-card" key={thesis.thesis_id}>
                <span>{thesis.status}</span>
                <strong>{thesis.symbol} {thesis.direction}</strong>
                <small>{thesis.source_report_id ?? "No source report linked"}</small>
                <p>{thesis.thesis}</p>
              </article>
            ))}
          </div>
        ) : (
          <p className="empty-state">No durable thesis handoffs are linked to this research source yet.</p>
        )}
      </section>

      <section
        className="order-thesis-metadata"
        aria-label="Order thesis metadata"
        data-status-flow="proposed sent_to_broker"
      >
        <div>
          <strong>Status flow</strong>
          <span>{orderThesisStatusFlow.join(" -> ")}</span>
        </div>
        <div data-actions="accept revise defer escalate reject">
          <strong>Decision actions</strong>
          <span>{orderThesisDecisionActions.join(" / ")}</span>
        </div>
        <div>
          <strong>Live trade submission</strong>
          <span>Disabled. Broker agents must create a separate execution intent.</span>
        </div>
      </section>

      <div className="dashboard-command-actions">
        <button className="micro-action-button" type="button" onClick={onOpenBrokerage}>
          Open Brokerage Floor
        </button>
      </div>
    </article>
  );
}

function filterThesesForSource(theses: TradeThesis[], sourceReportId: string | null): TradeThesis[] {
  if (!sourceReportId) {
    return theses;
  }
  return theses.filter((thesis) => thesis.source_report_id === sourceReportId);
}

function actionToDirection(action: string): TradeThesis["direction"] {
  const normalized = action.toLowerCase();
  if (normalized.includes("hedge")) {
    return "hedge";
  }
  if (normalized.includes("exit") || normalized.includes("avoid")) {
    return "exit";
  }
  if (normalized.includes("short") || normalized.includes("trim") || normalized.includes("reduce")) {
    return "short";
  }
  if (normalized.includes("buy") || normalized.includes("long") || normalized.includes("accumulate") || normalized.includes("add")) {
    return "long";
  }
  return "neutral";
}

function convictionToScore(conviction: string): number {
  const normalized = conviction.toLowerCase();
  if (normalized.includes("high")) {
    return 0.85;
  }
  if (normalized.includes("low")) {
    return 0.35;
  }
  const parsed = Number.parseFloat(conviction);
  if (Number.isFinite(parsed)) {
    return Math.max(0, Math.min(parsed > 1 ? parsed / 100 : parsed, 1));
  }
  return 0.6;
}
