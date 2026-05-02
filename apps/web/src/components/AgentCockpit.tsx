"use client";

import { useEffect, useRef, useState } from "react";

import { AgentRunGraph } from "@/components/AgentRunGraph";
import { RunTimeline } from "@/components/RunTimeline";
import { TradeTicket } from "@/components/TradeTicket";
import { createRun, listRunEvents, previewTrade } from "@/lib/api";
import type { OrderPreview, RunEvent } from "@/lib/types";

export function AgentCockpit({ symbol }: { symbol: string }) {
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [runId, setRunId] = useState<string | null>(null);
  const [preview, setPreview] = useState<OrderPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const requestIdRef = useRef(0);
  const revealTimersRef = useRef<number[]>([]);
  const activePreview = preview?.symbol === symbol ? preview : null;

  useEffect(() => {
    requestIdRef.current += 1;
    clearRevealTimers();
    setEvents([]);
    setRunId(null);
    setPreview(null);
    setError(null);
    setIsRunning(false);

    return clearRevealTimers;
  }, [symbol]);

  async function startRun() {
    const requestedSymbol = symbol;
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;

    setError(null);
    clearRevealTimers();
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
      revealEvents(nextEvents, requestId);

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

  function clearRevealTimers() {
    revealTimersRef.current.forEach((timer) => window.clearTimeout(timer));
    revealTimersRef.current = [];
  }

  function revealEvents(nextEvents: RunEvent[], requestId: number) {
    clearRevealTimers();
    nextEvents.forEach((event, index) => {
      const timer = window.setTimeout(() => {
        if (requestIdRef.current !== requestId) return;

        setEvents((currentEvents) => [...currentEvents, event]);
      }, index * 160);
      revealTimersRef.current.push(timer);
    });
  }

  return (
    <aside className="agent-cockpit">
      <header className="panel-header cockpit-header">
        <div>
          <span className="panel-kicker">Agent cockpit</span>
          <h2>{symbol}</h2>
        </div>
        <span className={isRunning ? "run-state running" : "run-state"}>{isRunning ? "Running" : "Idle"}</span>
      </header>
      <section className="run-control-panel">
        <div>
          <span>Research package</span>
          <strong>Market, news, social, fundamentals</strong>
        </div>
        <button className="primary-button" type="button" onClick={startRun} disabled={isRunning}>
          {isRunning ? "Running..." : "Run report"}
        </button>
      </section>
      {runId ? <p className="run-id">Run {runId}</p> : null}
      {error ? <p className="error">{error}</p> : null}
      <AgentRunGraph events={events} />
      <section className="cockpit-section">
        <div className="section-title">
          <span>Execution trace</span>
          <strong>{events.length}</strong>
        </div>
        <RunTimeline events={events} />
      </section>
      <section className="decision-panel">
        <span className="panel-kicker">Decision ledger</span>
        <strong>{events.some((event) => event.type === "decision.created") ? "Overweight / Buy" : "No decision yet"}</strong>
        <p>Final reports will land here before any paper ticket can be approved.</p>
      </section>
      {activePreview ? <TradeTicket key={activePreview.intent_id} preview={activePreview} /> : null}
    </aside>
  );
}
