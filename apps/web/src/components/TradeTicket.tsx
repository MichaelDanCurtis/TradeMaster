"use client";

import { useEffect, useState } from "react";

import { approveTrade, submitTrade } from "@/lib/api";
import type { OrderPreview } from "@/lib/types";

export function TradeTicket({ preview }: { preview: OrderPreview }) {
  const [status, setStatus] = useState("previewed");
  const [brokerOrderId, setBrokerOrderId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    setStatus("previewed");
    setBrokerOrderId(null);
    setError(null);
    setIsSubmitting(false);
  }, [preview.intent_id]);

  async function approveAndSubmit() {
    setError(null);
    setIsSubmitting(true);

    try {
      await approveTrade(preview.intent_id);
      const order = await submitTrade(preview.intent_id);
      setStatus(order.status);
      setBrokerOrderId(order.broker_order_id);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Trade submission failed");
    } finally {
      setIsSubmitting(false);
    }
  }

  const isSubmitted = status === "submitted";

  return (
    <section className="trade-ticket">
      <header className="ticket-header">
        <div>
          <span className="mode-pill">Paper trading</span>
          <h2>Trade ticket</h2>
        </div>
        <span className={isSubmitted ? "ticket-status submitted" : "ticket-status"}>{status}</span>
      </header>
      <dl>
        <div>
          <dt>Symbol</dt>
          <dd>{preview.symbol}</dd>
        </div>
        <div>
          <dt>Side</dt>
          <dd>{preview.side.toUpperCase()}</dd>
        </div>
        <div>
          <dt>Notional</dt>
          <dd>${preview.notional.toLocaleString()}</dd>
        </div>
        <div>
          <dt>Estimated quantity</dt>
          <dd>{preview.estimated_quantity}</dd>
        </div>
      </dl>
      <button className="primary-button" type="button" onClick={approveAndSubmit} disabled={isSubmitting || isSubmitted}>
        {isSubmitted ? "Submitted" : isSubmitting ? "Submitting..." : "Approve and submit paper order"}
      </button>
      {brokerOrderId ? <p className="muted">Broker order: {brokerOrderId}</p> : null}
      {error ? <p className="error">{error}</p> : null}
    </section>
  );
}
