export type RunStatus = "queued" | "running" | "completed" | "failed" | "canceled";
export type BrokerMode = "disabled" | "paper" | "live_preview";
export type ExecutionMode = "real" | "simulated";
export type OrderSide = "buy" | "sell";
export type ProviderRole = "brokerage" | "llm" | "market-data" | "observability" | "portfolio" | "safety";
export type ProviderStatus = "available" | "disabled" | "needs_key" | "planned";
export type ProviderControlSurface = "agent-data" | "ai-harness" | "human-cockpit" | "platform";
export type ProviderWriteAuthority = "live-trading" | "none" | "paper-trading" | "read-only";
export type RoomDecisionAction = "accept" | "reject" | "revise" | "defer" | "escalate";
// RoomId is intentionally NOT the same as the frontend WorkspaceId (see
// src/lib/workspace-data.ts). roomId is sent to the backend (approval ledger,
// agent triggers, trade theses) and is a stable wire contract. The frontend
// flattened to four tabs (portfolio / research / quant / settings) on
// 2026-05-20 but the backend room model — which still distinguishes
// dashboard/market/transactions/agents/builder for policy enforcement —
// did not migrate. Map frontend tab -> roomId at the call site if needed.
export type RoomId = "dashboard" | "portfolio" | "research" | "market" | "transactions" | "agents" | "builder" | "settings";

export type WatchlistItem = {
  symbol: string;
  name: string;
  price: number | null;
  changePercent: number | null;
};

export type RunCreated = {
  run_id: string;
  status: RunStatus;
};

export type RunSummary = {
  run_id: string;
  ticker: string;
  trade_date: string;
  status: RunStatus;
  final_rating: string | null;
  final_action: string | null;
  created_at: string;
  updated_at: string;
};

export type RunsCatalog = {
  runs: RunSummary[];
};

export type ScanVerdict = {
  symbol: string;
  rating: string | null;
  action: string | null;
  thesis: string | null;
  confidence: number | null;
  run_id: string;
  run_created_at: string;
};

export type ScanVerdictsCatalog = {
  verdicts: ScanVerdict[];
};

export type ScanStarted = {
  started: { symbol: string; run_id: string }[];
  failed?: { symbol: string; error: string }[];
};

export type QuickScanResult = {
  symbol: string;
  stance: "buy" | "hold" | "avoid";
  conviction: number;
  thesis: string;
  catalyst: string;
  risk: string;
  model: string;
  created_at: string;
};

export type QuickScanCatalog = {
  results: QuickScanResult[];
  failed?: { symbol: string; error: string }[];
};

export type DiscoverCandidate = {
  symbol: string;
  price: number | null;
  change_pct: number | null;
  volume: number | null;
  source: string;
  sources?: string[];
};

export type DiscoverCandidatesCatalog = {
  candidates: DiscoverCandidate[];
};

export type ReportSchedule = {
  schedule_id: string;
  name: string;
  symbol: string;
  cadence: "market_open" | "every_5_min" | "hourly" | "daily" | "manual";
  broker_mode: BrokerMode;
  execution_mode: ExecutionMode;
  enabled: boolean;
  last_run_id: string | null;
  payload: Record<string, unknown>;
  last_ran_at: string | null;
  next_run_at: string | null;
  created_at: string;
  updated_at: string;
};

export type ReportScheduleCatalog = {
  schedules: ReportSchedule[];
};

export type ReportScheduleTrigger = {
  schedule: ReportSchedule;
  run: RunCreated;
};

export type ReportScheduleBulkTrigger = {
  triggered_count: number;
  results: ReportScheduleTrigger[];
};

export type RoomPolicy = {
  room_id: RoomId;
  label: string;
  mission: string;
  tool_grants: string[];
  policies: string[];
  decision_actions: RoomDecisionAction[];
};

export type RoomPolicyCatalog = {
  rooms: RoomPolicy[];
};

export type RoomToolDecision = {
  room_id: string;
  tool_grant: string;
  allowed: boolean;
  reason: string;
};

export type ApprovalLedgerEntry = {
  approval_id: string;
  room_id: RoomId;
  source: string;
  entity_type: string;
  entity_id: string;
  action: RoomDecisionAction;
  actor: string;
  summary: string;
  payload: Record<string, unknown>;
  created_at: string;
};

export type ApprovalLedgerCatalog = {
  entries: ApprovalLedgerEntry[];
};

export type AgentTrigger = {
  trigger_id: string;
  name: string;
  room_id: RoomId;
  trigger_type: "time" | "price" | "volume" | "sentiment_flip" | "report_event" | "risk_threshold" | "compliance_flag";
  target_agent: string;
  symbol: string | null;
  condition: Record<string, unknown>;
  workflow_id: string | null;
  enabled: boolean;
  last_fired_at: string | null;
  payload: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type AgentTriggerCatalog = {
  triggers: AgentTrigger[];
};

export type AgentOperationType =
  | "research_report"
  | "portfolio_review"
  | "execution_preview"
  | "trigger_evaluation"
  | "builder_workflow";

export type AgentOperationStatus = "queued" | "running" | "completed" | "failed";

export type AgentOperationAuthority = "research_only" | "paper_only" | "approval_required";

export type AgentOperation = {
  operation_id: string;
  agent_id: string;
  agent_name: string;
  room_id: RoomId | string;
  symbol: string;
  operation_type: AgentOperationType;
  status: AgentOperationStatus;
  authority: AgentOperationAuthority;
  source_workflow_id: string | null;
  linked_run_id: string | null;
  linked_execution_program_id: string | null;
  payload: Record<string, unknown>;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
};

export type NewsItem = {
  id: string;
  published_at: string | null;
  source: string;
  headline: string;
  summary: string;
  url: string;
  category: string;
  related: string;
  image: string | null;
};

export type NewsCatalog = {
  symbol: string;
  provider: string;
  since_hours: number;
  items: NewsItem[];
};

export type OpenTrade = {
  execution_schedule_id?: string | null;
  intent_id: string;
  run_id: string;
  symbol: string;
  side: "buy" | "sell" | string;
  notional: number;
  order_type: string;
  status: string;
  created_at: string;
  updated_at: string;
  broker: string | null;
  broker_environment: string | null;
  broker_status: string | null;
  broker_order_id: string | null;
};

export type OpenTradesCatalog = {
  items: OpenTrade[];
};

export type PortfolioAccount = {
  account_id: string;
  name: string;
  official_name: string | null;
  type: string;
  subtype: string | null;
  mask: string | null;
  current_balance: number | null;
  iso_currency_code: string | null;
};

export type PortfolioHolding = {
  account_id: string;
  security_id: string;
  symbol: string | null;
  name: string | null;
  quantity: number;
  price: number | null;
  value: number | null;
  cost_basis: number | null;
};

export type PortfolioAccountsCatalog = {
  accounts: PortfolioAccount[];
};

export type PortfolioHoldingsCatalog = {
  holdings: PortfolioHolding[];
};

export type AgentOperationCatalog = {
  operations: AgentOperation[];
};

export type TradeThesis = {
  thesis_id: string;
  symbol: string;
  source_report_id: string | null;
  source_room: RoomId;
  target_room: RoomId;
  direction: "long" | "short" | "neutral" | "hedge" | "exit";
  horizon: string;
  conviction: number;
  status: "proposed" | "accepted" | "rejected" | "revised" | "deferred" | "sent_to_broker";
  thesis: string;
  catalysts: string[];
  invalidation: string[];
  risk_notes: string | null;
  payload: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type TradeThesisCatalog = {
  theses: TradeThesis[];
};

export type PortfolioReviewRecord = {
  review_id: string;
  symbol: string;
  room_id: string;
  status: string;
  goals: string | null;
  horizon: string | null;
  risk_posture: string | null;
  sector_focus: string | null;
  constraints: string | null;
  liquidity_needs: string | null;
  thesis: Record<string, unknown>;
  missing_provider_facts: string[];
  payload: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type PortfolioReviewCatalog = {
  reviews: PortfolioReviewRecord[];
};

export type FundingAllocationReviewRecord = {
  review_id: string;
  symbol: string;
  source_thesis_id: string | null;
  execution_program_id: string | null;
  status: string;
  notional: number | null;
  tracks: Record<string, unknown>[];
  missing_provider_facts: string[];
  approval_next_steps: string[];
  payload: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type FundingAllocationReviewCatalog = {
  reviews: FundingAllocationReviewRecord[];
};

export type ExecutionProgramRecord = {
  program_id: string;
  symbol: string;
  source_thesis_id: string | null;
  state: string;
  algorithm: string;
  mode: string;
  approval_status: string;
  live_submission_enabled: boolean;
  trigger_points: Record<string, unknown>[];
  circuit_breakers: Record<string, unknown>[];
  missing_provider_facts: string[];
  payload: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type ExecutionProgramCatalog = {
  programs: ExecutionProgramRecord[];
};

export type ExecutionProgramEventRecord = {
  event_id: string;
  program_id: string;
  event_type: string;
  summary: string;
  payload: Record<string, unknown>;
  created_at: string;
};

export type ExecutionProgramEventCatalog = {
  events: ExecutionProgramEventRecord[];
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

export type RunTrace = {
  trace_id: string;
  run_id: string;
  provider: string;
  status: string;
  external_trace_id: string | null;
  metadata: Record<string, unknown>;
  cost: Record<string, unknown>;
  created_at: string;
  updated_at: string;
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

export type ProviderRoleKey =
  | "broker"
  | "execution_llm"
  | "market_data"
  | "observability"
  | "portfolio"
  | "research_llm"
  | "research_designer"
  | "research_extractor"
  | "safety";

export type ProviderRoleAssignment = {
  role_key: ProviderRoleKey;
  provider_id: string;
  surface: ProviderControlSurface;
  created_at: string;
  updated_at: string;
};

export type ProviderRoleAssignmentCatalog = {
  strategy_research_protocols?: string[];
  assignments: ProviderRoleAssignment[];
};

export type RuntimeStatus = {
  research_runner: {
    configured_mode?: "llm-ui-runner" | "tradingagents-graph-runner";
    mode: string;
    uses_provider_role: string;
  };
  research_llm: {
    provider_id: string;
    name?: string;
    enabled?: boolean;
    status?: string;
    secret_ref_configured: boolean;
    developer_mode?: boolean;
    fallback_expected: boolean;
    model?: unknown;
    base_url?: unknown;
  };
  full_tradingagents_graph: {
    configured?: boolean;
    enabled: boolean;
    env_flag?: boolean;
  };
  execution_policy: {
    paper_mode_required: boolean;
    max_position_percent: number;
    max_sector_percent?: number;
    max_daily_turnover_percent?: number;
    max_drawdown_percent?: number;
  };
  developer_mode_enabled: boolean;
  broker: {
    provider_id: string;
    name?: string;
    enabled?: boolean;
    status?: string;
    paper_only?: boolean;
    approval_required: boolean;
  };
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
    backup_artifact?: {
      algorithm: string;
      path: string;
      sha256: string;
      size_bytes: number;
      verification?: string;
    };
  };
  created_at: string;
};

export type SnapshotVerification = {
  valid: boolean;
  reason?: string;
  manifest?: Record<string, unknown>;
  files?: Array<{
    path: string;
    archive_name?: string;
    expected_sha256?: string;
    actual_sha256?: string;
    verified: boolean;
  }>;
};

export type AgentWorkflowNode = {
  id: string;
  kind: string;
  [key: string]: unknown;
};

export type AgentWorkflowEdge = {
  source: string;
  target: string;
  [key: string]: unknown;
};

export type AgentWorkflowRecord = {
  workflow_id: string;
  name: string;
  agent_class: "research" | "execution";
  graph_runtime: "langgraph" | "langchain" | "manual";
  status: string;
  nodes: AgentWorkflowNode[];
  edges: AgentWorkflowEdge[];
  required_provider_roles: Record<string, string>;
  payload: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type AgentWorkflowCatalog = {
  workflows: AgentWorkflowRecord[];
};

export type AgentPackRecord = {
  pack_id: string;
  source_url: string | null;
  source_commit: string | null;
  license: string | null;
  status: string;
  manifest: Record<string, unknown>;
  imported_at: string;
  updated_at: string;
};

export type AgentPackCatalog = {
  packs: AgentPackRecord[];
};

export type AgentPackImportResult = {
  pack_id: string;
  agent_count: number;
  skill_count: number;
  connector_count: number;
};

export type ImportedAgentRecord = {
  agent_id: string;
  pack_id: string;
  source_slug: string;
  name: string;
  description: string;
  agent_class: string;
  system_prompt: string;
  guardrails: string[];
  skills: string[];
  commands: string[];
  required_provider_roles: Record<string, string>;
  required_connectors: string[];
  tool_policy: Record<string, unknown>;
  output_schema: Record<string, unknown>;
  security_profile: Record<string, unknown>;
  status: string;
  payload: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type ImportedAgentCatalog = {
  agents: ImportedAgentRecord[];
};

export type ImportedSkillRecord = {
  skill_id: string;
  pack_id: string;
  source_path: string;
  name: string;
  description: string;
  instructions_markdown: string;
  references: string[];
  scripts: string[];
  artifact_requirements: Record<string, unknown>;
  status: string;
  payload: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type ImportedSkillCatalog = {
  skills: ImportedSkillRecord[];
};

export type McpConnectorRecord = {
  connector_id: string;
  name: string;
  url: string;
  provider_id: string | null;
  required_secret_ref: string | null;
  capabilities: string[];
  health: Record<string, unknown>;
  enabled: boolean;
  subscription_required: boolean;
  payload: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type McpConnectorCatalog = {
  connectors: McpConnectorRecord[];
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
  exact_order?: ExactPaperOrder | null;
  order_hash?: string | null;
  account_id?: string | null;
  evidence_kind?: "fixture" | "broker_paper" | null;
};

export type ExactPaperOrder = {
  symbol: string;
  side: OrderSide;
  quantity: number;
  limit_price_usd: string;
  fee_reserve_usd: string;
  order_type: "limit";
  time_in_force: "day" | "gtc";
  stop_loss_usd: string | null;
  take_profit_usd: string | null;
  expires_at: string;
};

export type PaperOrderObservation = {
  filled_quantity: string;
  average_fill_price_usd: string | null;
  status: string;
  observed_at: string;
};

export type PaperBrokerOrder = {
  intent_id: string;
  broker: string;
  environment: string;
  status: string;
  broker_order_id: string;
  payload?: { observation?: PaperOrderObservation | null; failure_reason?: string | null };
};

export type PaperExecutionHistory = {
  order: { order_id: string; content_hash: string; state: string; order: ExactPaperOrder; preview_snapshot: { account_id: string; evidence_kind: "fixture" | "broker_paper" } } | null;
  attempt: { state: string; broker_order_id: string | null; observation: PaperOrderObservation | null; failure_reason: string | null } | null;
  events: { event_id: string; kind: string; created_at: string }[];
};

/**
 * Optional protective-stop envelope captured on the preview body and
 * persisted on the trade intent. `mode` decides whether the figures
 * stay informational (`advisory_only`, the legacy default) or get
 * promoted into a real Alpaca bracket / OTO order at submit time
 * (`broker_protective`).
 */
export type RiskControls = {
  stop_loss: number | null;
  take_profit: number | null;
  mode: "advisory_only" | "broker_protective";
};

// Originally a 3-name Literal. Widened to `string` to match the backend's
// 27-algorithm registry (see docs/ALGORITHM_LIBRARY.md). The backend validates
// the name at preview time and returns HTTP 400 on unknown names.
export type ExecutionAlgorithm = string;

export type ExecutionAlgorithmLeg = {
  kind: string;
  side: OrderSide;
  symbol: string;
  notional: number;
  estimated_quantity: number;
  price: number | null;
  parameters: Record<string, number | string>;
};

export type ExecutionAlgorithmPlan = {
  algorithm: ExecutionAlgorithm;
  symbol: string;
  side: OrderSide;
  notional: number;
  reference_price: number;
  estimated_quantity: number;
  legs: ExecutionAlgorithmLeg[];
  policy_notes: string[];
};

export type ExecutionAlgorithmCatalogueEntry = {
  name: string;
  category: string;
  description: string;
};

export type ExecutionAlgorithmCatalogueCategory = {
  id: string;
  label: string;
  count: number;
  algorithms: ExecutionAlgorithmCatalogueEntry[];
};

export type ExecutionAlgorithmCatalogue = {
  categories: ExecutionAlgorithmCatalogueCategory[];
  total: number;
};

// -----------------------------------------------------------------------------
// Watcher primitive (Phase 3) — per-symbol price/volume rules with a fires log.
// Backend lives at /api/watchers + /api/watcher-fires. See Phase 3 watcher
// spec for the full lifecycle (armed → fired → cooldown).
// -----------------------------------------------------------------------------

export type WatcherConditionType =
  | "price_above"
  | "price_below"
  | "change_pct_above"
  | "change_pct_below"
  | "volume_above";

export type WatcherRecord = {
  watcher_id: string;
  name: string;
  symbol: string;
  condition_type: WatcherConditionType;
  threshold: number;
  enabled: boolean;
  payload: Record<string, unknown>;
  linked_position_id: string | null;
  linked_run_id: string | null;
  last_fired_at: string | null;
  fire_count: number;
  created_at: string;
  updated_at: string;
};

export type WatcherCatalog = {
  watchers: WatcherRecord[];
};

export type WatcherFire = {
  fire_id: string;
  watcher_id: string;
  symbol: string;
  condition_type: WatcherConditionType;
  threshold: number;
  observed_value: number;
  fired_at: string;
  payload: Record<string, unknown>;
};

export type WatcherFireCatalog = {
  fires: WatcherFire[];
};

export type WatcherCheckResult = {
  fire?: WatcherFire | null;
  in_cooldown?: boolean;
  watcher_id: string;
  fired: boolean;
  observed_value: number;
};
