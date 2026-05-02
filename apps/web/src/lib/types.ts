export type RunStatus = "queued" | "running" | "completed" | "failed" | "canceled";
export type BrokerMode = "disabled" | "paper" | "live_preview";
export type OrderSide = "buy" | "sell";

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
