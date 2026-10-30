"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { cancelTrade, getPaperExecution, listOpenTrades } from "@/lib/api";
import { TradeTicket } from "@/components/TradeTicket";
import type { OpenTrade, OrderPreview } from "@/lib/types";

type LoadState = "loading" | "ready" | "error";
type ActionPhase = "idle" | "approving" | "approved" | "canceling" | "canceled" | "error";

const POLL_INTERVAL_MS = 10_000;

// "Needs human action" subset — these are the statuses where the operator
// can still approve or reject before the broker takes over.
const PENDING_STATUSES: ReadonlySet<string> = new Set([
  "previewed",
  "accepted",
  "pending_new", "approved", "dispatching", "new", "partially_filled", "unknown", "pending_cancel"
]);

// Status tokens we color the card's left border by. Anything outside this
// set falls back to a muted slate border.
type BorderToken = "previewed" | "accepted" | "rejected" | "failed" | "pending";

/** Persisted previews and outstanding broker orders, with exact review before approval. */
export function PendingIntentsLadder() {
  const [reviewPreview, setReviewPreview] = useState<OrderPreview | null>(null);
  const [intents, setIntents] = useState<OpenTrade[]>([]);
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [actionState, setActionState] = useState<Record<string, ActionPhase>>({});
  const [now, setNow] = useState<number>(() => Date.now());

  // Tracks whether the component is still mounted; flipped to false in the
  // effect cleanup so we don't call setState after unmount. Using a ref
  // keeps fetchIntents stable and lets the interval skip late resolutions.
  const mountedRef = useRef(true);

  const fetchIntents = useCallback(async () => {
    try {
      const catalog = await listOpenTrades({ limit: 20 });
      if (!mountedRef.current) return;
      const filtered = (catalog.items ?? []).filter((intent) =>
        PENDING_STATUSES.has(intent.status)
      );
      setIntents(filtered);
      setLoadState("ready");
      setErrorMessage(null);
    } catch (err) {
      if (!mountedRef.current) return;
      setLoadState("error");
      setErrorMessage(err instanceof Error ? err.message : "Trades unavailable");
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;

    void fetchIntents();
    const interval = window.setInterval(() => {
      if (!mountedRef.current) return;
      void fetchIntents();
    }, POLL_INTERVAL_MS);

    // Refresh "x ago" every second so cards age in real time.
    const tick = window.setInterval(() => {
      if (!mountedRef.current) return;
      setNow(Date.now());
    }, 1000);

    return () => {
      mountedRef.current = false;
      window.clearInterval(interval);
      window.clearInterval(tick);
    };
  }, [fetchIntents]);

  async function reviewExactOrder(intent: OpenTrade) {
    setActionState((current) => ({ ...current, [intent.intent_id]: "approving" }));
    try {
      const history = await getPaperExecution(intent.intent_id);
      if (!history.order) throw new Error("This legacy intent needs a fresh exact preview in the workbench before approval");
      if (!mountedRef.current) return;
      const exact = history.order.order;
      setReviewPreview({ intent_id: intent.intent_id, broker: intent.broker ?? "paper", environment: "paper",
        symbol: exact.symbol, side: exact.side, notional: intent.notional,
        estimated_price: Number(exact.limit_price_usd), estimated_quantity: exact.quantity,
        exact_order: exact, order_hash: history.order.content_hash,
        account_id: history.order.preview_snapshot.account_id, evidence_kind: history.order.preview_snapshot.evidence_kind });
      setActionState((current) => ({ ...current, [intent.intent_id]: "idle" }));
    } catch (err) {
      if (!mountedRef.current) return;
      setActionState((current) => ({ ...current, [intent.intent_id]: "error" }));
      setErrorMessage(err instanceof Error ? err.message : "Exact review unavailable");
    }
  }

  async function rejectIntent(intentId: string) {
    // Cancel the intent on the backend; the next poll cycle drops it from
    // the ladder. Errors flow through the existing actionState/errorMessage
    // pair so the card surfaces the failure without breaking the list.
    setActionState((current) => ({ ...current, [intentId]: "canceling" }));
    try {
      const result = await cancelTrade(intentId);
      if (!mountedRef.current) return;
      setActionState((current) => ({ ...current, [intentId]: result.status === "canceled" ? "canceled" : "idle" }));
      await fetchIntents();
    } catch (err) {
      if (!mountedRef.current) return;
      setActionState((current) => ({ ...current, [intentId]: "error" }));
      setErrorMessage(err instanceof Error ? err.message : "Cancel failed");
    }
  }

  /**
   * Sort intents most-urgent-first: oldest pending first, then by
   * urgency rank (previewed → accepted → pending_new → other).
   * The backend may return them in arbitrary order; we want the ladder
   * to behave like a queue.
   */
  const sortedIntents = useMemo(() => {
    const rank: Record<string, number> = { previewed: 0, accepted: 1, pending_new: 2 };
    return [...intents].sort((a, b) => {
      const ra = rank[a.status] ?? 3;
      const rb = rank[b.status] ?? 3;
      if (ra !== rb) return ra - rb;
      // Within a status, oldest first (older created_at first).
      return Date.parse(a.created_at) - Date.parse(b.created_at);
    });
  }, [intents]);

  const ageLabels = useMemo(() => {
    const result: Record<string, string> = {};
    for (const intent of sortedIntents) {
      result[intent.intent_id] = formatAge(intent.created_at, now);
    }
    return result;
  }, [sortedIntents, now]);

  // Oldest pending age, in minutes, for the header subtitle.
  const oldestLabel = useMemo(() => {
    if (sortedIntents.length === 0) return null;
    let oldest = Number.POSITIVE_INFINITY;
    for (const intent of sortedIntents) {
      const t = Date.parse(intent.created_at);
      if (!Number.isNaN(t) && t < oldest) oldest = t;
    }
    if (!Number.isFinite(oldest)) return null;
    return formatAge(new Date(oldest).toISOString(), now);
  }, [sortedIntents, now]);

  const headerMeta =
    sortedIntents.length > 0 ? (
      <div className="quant-pending-meta">
        <span className="quant-pending-meta-count">
          {sortedIntents.length} <span className="quant-pending-meta-dim">saved unresolved</span>
        </span>
        {oldestLabel ? (
          <>
            <span className="quant-pending-meta-sep">·</span>
            <span className="quant-pending-meta-oldest">oldest {oldestLabel}</span>
          </>
        ) : null}
      </div>
    ) : null;

  if (loadState === "loading") {
    return (
      <section className="quant-pending-ladder" aria-label="Pending intents">
        <header className="quant-pending-header">
          <div className="quant-pending-header-left">
            <span className="panel-kicker">Recorded order status</span>
            <h2>Saved order records</h2>
          </div>
          {headerMeta}
        </header>
        <p className="quant-pending-status">Loading…</p>
      </section>
    );
  }

  if (loadState === "error") {
    return (
      <section className="quant-pending-ladder" aria-label="Pending intents">
        <header className="quant-pending-header">
          <div className="quant-pending-header-left">
            <span className="panel-kicker">Recorded order status</span>
            <h2>Saved order records</h2>
          </div>
          {headerMeta}
        </header>
        <p className="quant-pending-status error">{errorMessage ?? "Unavailable"}</p>
      </section>
    );
  }

  if (sortedIntents.length === 0) {
    return (
      <section className="quant-pending-ladder" aria-label="Pending intents">
        <header className="quant-pending-header">
          <div className="quant-pending-header-left">
            <span className="panel-kicker">Recorded order status</span>
            <h2>Saved order records</h2>
          </div>
          {headerMeta}
        </header>
        <p className="quant-pending-status">
          No pending intents. Trades you preview from the workbench will queue here for approval.
        </p>
      </section>
    );
  }

  return (
    <section className="quant-pending-ladder" aria-label="Pending intents">
      <header className="quant-pending-header">
        <div className="quant-pending-header-left">
          <span className="panel-kicker">Recorded order status</span>
          <h2>Saved order records</h2>
        </div>
        {headerMeta}
      </header>
      <ul className="quant-pending-cards" role="list">
        {sortedIntents.map((intent) => {
          const phase = actionState[intent.intent_id] ?? "idle";
          const borderToken = borderTokenForStatus(intent.status, phase);
          const side = intent.side.toLowerCase();
          const sideLabel = side === "buy" ? "BUY" : side === "sell" ? "SELL" : intent.side.toUpperCase();
          const isCanceling = phase === "canceling";
          const isApproving = phase === "approving";
          const isLocked =
            isCanceling || isApproving || phase === "approved" || phase === "canceled";
          return (
            <li
              key={intent.intent_id}
              className={`quant-pending-card quant-pending-card-elevated quant-pending-card-border-${borderToken}`}
            >
              <header className="quant-pending-card-header">
                <strong className="quant-pending-card-symbol">{intent.symbol}</strong>
                <span className="quant-pending-card-age">{ageLabels[intent.intent_id]}</span>
              </header>
              <div className="quant-pending-card-body-row">
                <span className={`quant-pending-card-side quant-pending-card-side-${side}`}>
                  {sideLabel}
                </span>
                <span className="quant-pending-card-notional">
                  ${intent.notional.toLocaleString()}
                </span>
                <span className="quant-pending-card-order-type">{intent.order_type}</span>
              </div>
              <div className="quant-pending-card-meta">
                <span className={`quant-pending-card-status status-${intent.status}`}>
                  {intent.status.replaceAll("_", " ")}
                </span>
              </div>
              <div className="quant-pending-card-actions">
                {intent.execution_schedule_id ? <a href="#execution-scheduler" className="micro-action-button">Review in scheduler</a> : <button
                  type="button"
                  className="micro-action-button primary-button quant-pending-card-approve"
                  onClick={() => reviewExactOrder(intent)}
                  disabled={isLocked}
                >
                  {isApproving
                    ? "Loading review…"
                    : phase === "approved"
                      ? "Submitted"
                      : "Review exact order"}
                </button>}
                <button
                  type="button"
                  className="micro-action-button quant-pending-card-reject"
                  onClick={() => {
                    void rejectIntent(intent.intent_id);
                  }}
                  disabled={isLocked}
                >
                  {isCanceling ? "Canceling…" : phase === "canceled" ? "Canceled" : "Request cancellation"}
                </button>
              </div>
              {phase === "error" ? (
                <p className="quant-pending-card-error">{errorMessage ?? "Submit failed"}</p>
              ) : null}
            </li>
          );
        })}
      </ul>
      {reviewPreview ? <TradeTicket key={reviewPreview.intent_id} preview={reviewPreview} /> : null}
    </section>
  );
}

/**
 * Map the (status, phase) pair to one of our border-color tokens.
 * Phase wins when set (e.g. a canceled card stays "rejected"-colored
 * for the brief window before it drops out of the list).
 */
function borderTokenForStatus(status: string, phase: ActionPhase): BorderToken {
  if (phase === "error") return "failed";
  if (phase === "canceled" || phase === "canceling") return "rejected";
  if (status === "previewed") return "previewed";
  if (status === "accepted") return "accepted";
  if (status === "pending_new") return "pending";
  return "pending";
}

/**
 * Format a created_at ISO string into a compact "Ns ago / Nm ago"
 * label relative to `now`. Falls back to the raw string on parse
 * failure rather than crashing.
 */
function formatAge(createdAt: string, now: number): string {
  const created = Date.parse(createdAt);
  if (Number.isNaN(created)) return createdAt;
  const deltaSec = Math.max(0, Math.floor((now - created) / 1000));
  if (deltaSec < 60) return `${deltaSec}s ago`;
  const deltaMin = Math.floor(deltaSec / 60);
  if (deltaMin < 60) return `${deltaMin}m ago`;
  const deltaHr = Math.floor(deltaMin / 60);
  if (deltaHr < 24) return `${deltaHr}h ago`;
  const deltaDay = Math.floor(deltaHr / 24);
  return `${deltaDay}d ago`;
}
