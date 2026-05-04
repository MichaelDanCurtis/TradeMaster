import type {
  BrokerMode,
  OrderPreview,
  OrderSide,
  ProviderCatalog,
  ProviderConfig,
  ProviderConfigCatalog,
  RunCreated,
  RunEvent,
  SnapshotManifestRecord
} from "./types";

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

export async function listProviders(): Promise<ProviderCatalog> {
  const response = await fetch(`${API_BASE}/api/providers`);

  if (!response.ok) {
    throw new Error(`Failed to list providers: ${response.status}`);
  }

  return response.json();
}

export async function listProviderConfigs(): Promise<ProviderConfigCatalog> {
  const response = await fetch(`${API_BASE}/api/provider-configs`);

  if (!response.ok) {
    throw new Error(`Failed to list provider configs: ${response.status}`);
  }

  return response.json();
}

export async function updateProviderConfig(
  providerId: string,
  input: {
    enabled?: boolean;
    secretRef?: string | null;
  }
): Promise<ProviderConfig> {
  const response = await fetch(`${API_BASE}/api/provider-configs/${providerId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      enabled: input.enabled,
      secret_ref: input.secretRef
    })
  });

  if (!response.ok) {
    throw new Error(`Failed to update provider config: ${response.status}`);
  }

  return response.json();
}

export async function checkProviderHealth(providerId: string): Promise<ProviderConfig> {
  const response = await fetch(`${API_BASE}/api/provider-configs/${providerId}/health-check`, {
    method: "POST"
  });

  if (!response.ok) {
    throw new Error(`Failed to check provider health: ${response.status}`);
  }

  return response.json();
}

export async function createSnapshot(input: {
  encryptionMode: string;
  offsiteTarget?: string | null;
}): Promise<SnapshotManifestRecord> {
  const response = await fetch(`${API_BASE}/api/snapshots`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      encryption_mode: input.encryptionMode,
      offsite_target: input.offsiteTarget ?? null
    })
  });

  if (!response.ok) {
    throw new Error(`Failed to create snapshot: ${response.status}`);
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
