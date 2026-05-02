"use client";

import { useEffect, useRef, useState } from "react";

import { RunTimeline } from "@/components/RunTimeline";
import { createRun, listRunEvents, previewTrade } from "@/lib/api";
import type { OrderPreview, RunEvent } from "@/lib/types";

export function AgentCockpit({ symbol }: { symbol: string }) {
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [runId, setRunId] = useState<string | null>(null);
  const [preview, setPreview] = useState<OrderPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const requestIdRef = useRef(0);

  useEffect(() => {
    requestIdRef.current += 1;
    setEvents([]);
    setRunId(null);
    setPreview(null);
    setError(null);
    setIsRunning(false);
  }, [symbol]);

  async function startRun() {
    const requestedSymbol = symbol;
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;

    setError(null);
    setEvents([]);
    setRunId(null);
    setPreview(null);
    setIsRunning(true);

    try {
      const created = await createRun({
        ticker: requestedSymbol,
        tradeDate: new Date().toISOString().slice(0, 10),
        brokerMode: "paper"
      });
      if (requestIdRef.current !== requestId) return;
      setRunId(created.run_id);

      const nextEvents = await listRunEvents(created.run_id);
      if (requestIdRef.current !== requestId) return;
      setEvents(nextEvents);

      const tradePreview = await previewTrade({
        runId: created.run_id,
        symbol: requestedSymbol,
        side: "buy",
        notional: 1000
      });
      if (requestIdRef.current !== requestId) return;
      setPreview(tradePreview);
    } catch (caught) {
      if (requestIdRef.current !== requestId) return;
      setError(caught instanceof Error ? caught.message : "Run failed");
    } finally {
      if (requestIdRef.current === requestId) {
        setIsRunning(false);
      }
    }
  }

  return (
    <aside className="agent-cockpit">
      <header>
        <span>Agent Cockpit</span>
        <strong>{symbol}</strong>
      </header>
      <button className="primary-button" type="button" onClick={startRun} disabled={isRunning}>
        {isRunning ? "Running..." : "Run report"}
      </button>
      {runId ? <p className="muted">Run: {runId}</p> : null}
      {error ? <p className="error">{error}</p> : null}
      <RunTimeline events={events} />
      {preview ? (
        <section className="trade-preview">
          <h2>Paper trade preview</h2>
          <p>
            {preview.side.toUpperCase()} {preview.symbol} ${preview.notional.toLocaleString()}
          </p>
          <p className="muted">
            Est. {preview.estimated_quantity} shares at ${preview.estimated_price}
          </p>
        </section>
      ) : null}
    </aside>
  );
}
