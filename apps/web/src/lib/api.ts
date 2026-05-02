import type { BrokerMode, OrderPreview, OrderSide, RunCreated, RunEvent } from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8787";

export async function createRun(input: {
  ticker: string;
  tradeDate: string;
  brokerMode: BrokerMode;
}): Promise<RunCreated> {
  const response = await fetch(`${API_BASE}/api/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      ticker: input.ticker,
      trade_date: input.tradeDate,
      broker_mode: input.brokerMode
    })
  });

  if (!response.ok) {
    throw new Error(`Failed to create run: ${response.status}`);
  }

  return response.json();
}

export async function listRunEvents(runId: string): Promise<RunEvent[]> {
  const response = await fetch(`${API_BASE}/api/runs/${runId}/events`);

  if (!response.ok) {
    throw new Error(`Failed to list run events: ${response.status}`);
  }

  return response.json();
}

export function openRunEventSource(runId: string): EventSource {
  return new EventSource(`${API_BASE}/api/runs/${runId}/stream`);
}

export async function previewTrade(input: {
  runId: string;
  symbol: string;
  side: OrderSide;
  notional: number;
}): Promise<OrderPreview> {
  const response = await fetch(`${API_BASE}/api/trades/preview`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      run_id: input.runId,
      symbol: input.symbol,
      side: input.side,
      notional: input.notional
    })
  });

  if (!response.ok) {
    throw new Error(`Failed to preview trade: ${response.status}`);
  }

  return response.json();
}

export async function approveTrade(intentId: string): Promise<{ intent_id: string; status: string }> {
  const response = await fetch(`${API_BASE}/api/trades/${intentId}/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ actor: "local-user" })
  });

  if (!response.ok) {
    throw new Error(`Failed to approve trade: ${response.status}`);
  }

  return response.json();
}

export async function submitTrade(intentId: string): Promise<{
  intent_id: string;
  broker: string;
  environment: string;
  status: string;
  broker_order_id: string;
}> {
  const response = await fetch(`${API_BASE}/api/trades/${intentId}/submit`, {
    method: "POST"
  });

  if (!response.ok) {
    throw new Error(`Failed to submit trade: ${response.status}`);
  }

  return response.json();
}
