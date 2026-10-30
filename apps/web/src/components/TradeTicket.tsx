"use client";

import { useEffect, useState } from "react";

import { approveTrade, cancelTrade, getPaperExecution, reconcilePaperOrder, submitTrade } from "@/lib/api";
import type { OrderPreview, PaperExecutionHistory } from "@/lib/types";

const terminalStates = new Set(["filled", "canceled", "expired", "rejected"]);

export function TradeTicket({ preview }: { preview: OrderPreview }) {
  const [history, setHistory] = useState<PaperExecutionHistory | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    setHistory(null);
    setError(null);
    setLoading(true);
    getPaperExecution(preview.intent_id).then((value) => {
      if (active) setHistory(value);
    }).catch((caught) => {
      if (active) setError(caught instanceof Error ? caught.message : "Execution history unavailable");
    }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [preview.intent_id]);

  const exact = history?.order?.order ?? preview.exact_order;
  const status = history?.order?.state ?? (loading ? "loading" : "unavailable");
  const attempt = history?.attempt;
  const observation = attempt?.observation;
  const isTerminal = terminalStates.has(status);
  const canApprove = Boolean(history?.order && exact && !attempt && ["previewed", "approved"].includes(status));
  const maxNotional = exact ? exact.quantity * Number(exact.limit_price_usd) : null;

  async function act(action: "submit" | "reconcile" | "cancel" | "refresh") {
    setError(null);
    setBusy(true);
    try {
      if (action === "submit") {
        if (!history?.order) throw new Error("Reload the exact preview before approval");
        await approveTrade(preview.intent_id, history.order.content_hash);
        await submitTrade(preview.intent_id);
      } else if (action === "reconcile") {
        await reconcilePaperOrder(preview.intent_id);
      } else if (action === "cancel") {
        await cancelTrade(preview.intent_id);
      }
      setHistory(await getPaperExecution(preview.intent_id));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Paper order action failed");
      // A transport error does not prove submission failed. Reload durable
      // state and expose reconciliation, never automatically submit again.
      try { setHistory(await getPaperExecution(preview.intent_id)); }
      catch { setHistory(null); }
    } finally { setBusy(false); }
  }

  return (
    <section className="trade-ticket" aria-busy={busy || loading}>
      <header className="ticket-header">
        <div>
          <span className="mode-pill">{preview.evidence_kind === "fixture" ? "Fixture simulation" : preview.evidence_kind === "broker_paper" ? "Broker paper trading" : "Unverified paper preview"}</span>
          <h2>Exact paper order</h2>
        </div>
        <span className="ticket-status" role="status">{status.replaceAll("_", " ")}</span>
      </header>
      <dl>
        <div><dt>Symbol / side</dt><dd>{preview.symbol} · {preview.side.toUpperCase()}</dd></div>
        <div><dt>Account</dt><dd>{preview.account_id ?? "Unavailable"}</dd></div>
        <div><dt>Quantity</dt><dd>{exact ? `${exact.quantity} whole shares` : "Fresh exact preview required"}</dd></div>
        <div><dt>Limit price</dt><dd>{exact ? `$${exact.limit_price_usd}` : "Unavailable"}</dd></div>
        <div><dt>Limit notional / fee reserve</dt><dd>{maxNotional !== null && exact ? `$${maxNotional.toFixed(2)} / $${exact.fee_reserve_usd}` : "Unavailable"}</dd></div>
        {exact && <>
          <div><dt>Time in force</dt><dd>{exact.time_in_force.toUpperCase()}</dd></div>
          <div><dt>Submit before</dt><dd>{new Date(exact.expires_at).toLocaleString()}</dd></div>
          {exact.stop_loss_usd && <div><dt>Protective stop</dt><dd>${exact.stop_loss_usd}</dd></div>}
          {exact.take_profit_usd && <div><dt>Take profit</dt><dd>${exact.take_profit_usd}</dd></div>}
        </>}
        {observation && <div><dt>Filled / average price</dt><dd>{observation.filled_quantity} shares / {observation.average_fill_price_usd ? `$${observation.average_fill_price_usd}` : "No fill"}</dd></div>}
      </dl>
      {preview.evidence_kind === "fixture" && <p className="muted">Local test account. These orders and fills are simulated fixtures and provide no broker execution evidence.</p>}
      {exact && <p className="muted">Approval freezes these terms. Submission rechecks current account limits. The deadline applies to submission; an accepted GTC order stays open until filled or canceled.</p>}
      {status === "unknown" && <p role="alert">Broker outcome unknown. Cash and shares remain reserved. Reconcile to look up this order without submitting another.</p>}
      {status === "pending_cancel" && <p role="status">Cancellation requested. Remaining cash or shares stay reserved until the broker confirms.</p>}
      {attempt?.failure_reason && <p className="muted">{attempt.failure_reason}</p>}
      {canApprove && <button className="primary-button" type="button" onClick={() => act("submit")} disabled={busy || loading}>Approve and submit exact paper order</button>}
      {attempt && !isTerminal && <button type="button" onClick={() => act("reconcile")} disabled={busy || loading}>Reconcile with broker</button>}
      {history?.order && !isTerminal && <button type="button" onClick={() => act("cancel")} disabled={busy || loading}>{attempt ? "Request cancellation" : "Cancel preview"}</button>}
      <button type="button" onClick={() => act("refresh")} disabled={busy || loading}>Refresh saved status</button>
      {attempt?.broker_order_id && <p className="muted">Broker order: {attempt.broker_order_id}</p>}
      {error && <p className="error" role="alert">{error}</p>}
      {history?.events.length ? <details><summary>Order history ({history.events.length})</summary><ol>{history.events.map((event) => <li key={event.event_id}>{new Date(event.created_at).toLocaleString()} · {event.kind.replaceAll("_", " ")}</li>)}</ol></details> : null}
    </section>
  );
}
