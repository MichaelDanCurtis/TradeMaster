export type RunStatus = "queued" | "running" | "completed" | "failed" | "canceled";
export type BrokerMode = "disabled" | "paper" | "live_preview";
export type OrderSide = "buy" | "sell";
export type ProviderRole = "brokerage" | "llm" | "market-data" | "portfolio";
export type ProviderStatus = "available" | "disabled" | "needs_key" | "planned";
export type ProviderControlSurface = "agent-data" | "ai-harness" | "human-cockpit" | "platform";
export type ProviderWriteAuthority = "live-trading" | "none" | "paper-trading" | "read-only";

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
  control_surface: ProviderControlSurface;
  write_authority: ProviderWriteAuthority;
};

export type ProviderCatalog = {
  providers: ProviderDescriptor[];
};

export type ProviderConfig = {
  provider_id: string;
  name: string;
  role: ProviderRole;
  status: ProviderStatus;
  capabilities: string[];
  primary_use: string;
  control_surface: ProviderControlSurface;
  write_authority: ProviderWriteAuthority;
  enabled: boolean;
  secret_ref: string | null;
  config: Record<string, unknown>;
  health: Record<string, unknown>;
};

export type ProviderConfigCatalog = {
  providers: ProviderConfig[];
};

export type SnapshotManifestRecord = {
  snapshot_id: string;
  storage_profile: string;
  encryption_mode: string;
  offsite_target: string | null;
  manifest: {
    snapshot_id: string;
    created_at: string;
    storage_profile: string;
    database_path: string;
    encryption_mode: string;
    encrypted: boolean;
    offsite_target: string | null;
    files: Array<{
      path: string;
      sha256: string;
      size_bytes: number;
    }>;
  };
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
