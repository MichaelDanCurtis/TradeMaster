export type RunStatus = "queued" | "running" | "completed" | "failed" | "canceled";
export type BrokerMode = "disabled" | "paper" | "live_preview";
export type OrderSide = "buy" | "sell";
export type ProviderRole = "brokerage" | "llm" | "market-data" | "portfolio";
export type ProviderStatus = "available" | "disabled" | "needs_key" | "planned";

export type WatchlistItem = {
  symbol: string;
  name: string;
  price: number;
  changePercent: number;
};

export type RunCreated = {
  run_id: string;
  status: RunStatus;
};

export type RunEvent = {
  run_id: string;
  sequence: number;
  type: string;
  node: string | null;
  message: string;
  payload: Record<string, unknown>;
  created_at: string;
};

export type ProviderDescriptor = {
  id: string;
  name: string;
  role: ProviderRole;
  status: ProviderStatus;
  capabilities: string[];
  primary_use: string;
};

export type ProviderCatalog = {
  providers: ProviderDescriptor[];
};

export type OrderPreview = {
  intent_id: string;
  broker: string;
  environment: string;
  symbol: string;
  side: OrderSide;
  notional: number;
  estimated_price: number;
  estimated_quantity: number;
};
