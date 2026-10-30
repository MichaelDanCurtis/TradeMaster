import type {
  AgentPackCatalog,
  AgentPackImportResult,
  AgentOperation,
  AgentOperationAuthority,
  AgentOperationCatalog,
  AgentOperationStatus,
  AgentOperationType,
  AgentTrigger,
  AgentTriggerCatalog,
  AgentWorkflowCatalog,
  AgentWorkflowEdge,
  AgentWorkflowNode,
  AgentWorkflowRecord,
  ApprovalLedgerCatalog,
  ApprovalLedgerEntry,
  BrokerMode,
  DiscoverCandidatesCatalog,
  ExecutionAlgorithm,
  ExecutionAlgorithmCatalogue,
  ExecutionAlgorithmPlan,
  ExecutionProgramCatalog,
  ExecutionProgramEventCatalog,
  ExecutionProgramEventRecord,
  ExecutionProgramRecord,
  ExecutionMode,
  FundingAllocationReviewCatalog,
  FundingAllocationReviewRecord,
  ImportedAgentCatalog,
  ImportedSkillCatalog,
  McpConnectorCatalog,
  NewsCatalog,
  OpenTradesCatalog,
  OrderPreview,
  PaperBrokerOrder,
  PaperExecutionHistory,
  OrderSide,
  PortfolioAccountsCatalog,
  PortfolioHoldingsCatalog,
  PortfolioReviewCatalog,
  PortfolioReviewRecord,
  ProviderCatalog,
  ProviderConfig,
  ProviderConfigCatalog,
  ProviderRoleAssignment,
  ProviderRoleAssignmentCatalog,
  ProviderRoleKey,
  QuickScanCatalog,
  ReportSchedule,
  ReportScheduleBulkTrigger,
  ReportScheduleCatalog,
  ReportScheduleTrigger,
  RoomDecisionAction,
  RoomId,
  RoomPolicyCatalog,
  RoomToolDecision,
  RuntimeStatus,
  RunCreated,
  RunEvent,
  RunsCatalog,
  RunSummary,
  RunTrace,
  ScanStarted,
  ScanVerdictsCatalog,
  SnapshotManifestRecord,
  SnapshotVerification,
  TradeThesis,
  TradeThesisCatalog,
  WatcherCatalog,
  WatcherCheckResult,
  WatcherConditionType,
  WatcherFireCatalog,
  WatcherRecord
} from "./types";

const CONFIGURED_API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8797";

async function failureDetail(response: Response, fallback: string): Promise<string> {
  const body = await response.json().catch(() => null);
  return typeof body?.detail === "string" ? body.detail : `${fallback}: ${response.status}`;
}

export function apiBase(): string {
  if (typeof window === "undefined") {
    return CONFIGURED_API_BASE;
  }

  const url = new URL(CONFIGURED_API_BASE);
  if ((url.hostname === "127.0.0.1" || url.hostname === "localhost") && window.location.hostname !== url.hostname) {
    url.hostname = window.location.hostname;
  }

  return url.toString().replace(/\/$/, "");
}

async function errorMessage(response: Response, fallback: string): Promise<string> {
  try {
    const body: unknown = await response.json();
    if (body && typeof body === "object" && "detail" in body) {
      const detail = (body as { detail?: unknown }).detail;
      if (typeof detail === "string" && detail.length > 0) {
        return detail;
      }
    }
  } catch {
    return fallback;
  }
  return fallback;
}

export async function createRun(input: {
  ticker: string;
  tradeDate: string;
  brokerMode: BrokerMode;
  executionMode?: ExecutionMode;
}): Promise<RunCreated> {
  const response = await fetch(`${apiBase()}/api/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      ticker: input.ticker,
      trade_date: input.tradeDate,
      broker_mode: input.brokerMode,
      execution_mode: input.executionMode ?? "simulated"
    })
  });

  if (!response.ok) {
    throw new Error(`Failed to create run: ${response.status}`);
  }

  return response.json();
}

export async function listRuns(input: { ticker?: string; limit?: number } = {}): Promise<RunSummary[]> {
  const searchParams = new URLSearchParams();
  if (input.ticker) {
    searchParams.set("ticker", input.ticker);
  }
  if (input.limit !== undefined) {
    searchParams.set("limit", String(input.limit));
  }
  const suffix = searchParams.size > 0 ? `?${searchParams.toString()}` : "";
  const response = await fetch(`${apiBase()}/api/runs${suffix}`);

  if (!response.ok) {
    throw new Error(`Failed to list runs: ${response.status}`);
  }

  // Backend now returns the catalog shape {runs: [...]} — matches the
  // sibling /api/report-schedules, /api/agent-triggers, etc. Older payloads
  // were a bare array; the fallback keeps the client working against any
  // pinned-version backend during a rolling restart.
  const data: RunsCatalog | RunSummary[] = await response.json();
  return Array.isArray(data) ? data : data.runs;
}

export async function getScanVerdicts(input: { symbols?: string[]; limit?: number } = {}): Promise<ScanVerdictsCatalog> {
  const searchParams = new URLSearchParams();
  if (input.symbols && input.symbols.length > 0) {
    searchParams.set("symbols", input.symbols.join(","));
  }
  if (input.limit !== undefined) {
    searchParams.set("limit", String(input.limit));
  }
  const suffix = searchParams.size > 0 ? `?${searchParams.toString()}` : "";
  const response = await fetch(`${apiBase()}/api/scans/verdicts${suffix}`);

  if (!response.ok) {
    const message = await errorMessage(response, `Failed to fetch scan verdicts: ${response.status}`);
    throw new Error(message);
  }

  return response.json();
}

export async function getDiscoverCandidates(
  input: { limit?: number; exclude?: string[]; minPrice?: number } = {}
): Promise<DiscoverCandidatesCatalog> {
  const searchParams = new URLSearchParams();
  if (input.limit !== undefined) {
    searchParams.set("limit", String(input.limit));
  }
  if (input.exclude && input.exclude.length > 0) {
    searchParams.set("exclude", input.exclude.join(","));
  }
  if (input.minPrice !== undefined) {
    searchParams.set("min_price", String(input.minPrice));
  }
  const suffix = searchParams.size > 0 ? `?${searchParams.toString()}` : "";
  const response = await fetch(`${apiBase()}/api/discover/candidates${suffix}`);

  if (!response.ok) {
    const message = await errorMessage(response, `Failed to fetch discovery candidates: ${response.status}`);
    const error = new Error(message) as Error & { status?: number };
    error.status = response.status;
    throw error;
  }

  return response.json();
}

export async function runQuickScan(symbols: string[]): Promise<QuickScanCatalog> {
  const response = await fetch(`${apiBase()}/api/quickscan`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ symbols })
  });

  if (!response.ok) {
    const message = await errorMessage(response, `Failed to run quick scan: ${response.status}`);
    throw new Error(message);
  }

  return response.json();
}

export async function getLatestQuickScans(
  input: { symbols?: string[]; limit?: number } = {}
): Promise<QuickScanCatalog> {
  const searchParams = new URLSearchParams();
  if (input.symbols && input.symbols.length > 0) {
    searchParams.set("symbols", input.symbols.join(","));
  }
  if (input.limit !== undefined) {
    searchParams.set("limit", String(input.limit));
  }
  const suffix = searchParams.size > 0 ? `?${searchParams.toString()}` : "";
  const response = await fetch(`${apiBase()}/api/quickscan/latest${suffix}`);

  if (!response.ok) {
    const message = await errorMessage(response, `Failed to fetch quick scans: ${response.status}`);
    throw new Error(message);
  }

  return response.json();
}

export async function startScan(symbols: string[]): Promise<ScanStarted> {
  const response = await fetch(`${apiBase()}/api/scans`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ symbols })
  });

  if (!response.ok) {
    const message = await errorMessage(response, `Failed to start scan: ${response.status}`);
    throw new Error(message);
  }

  return response.json();
}

export async function listReportSchedules(input: { symbol?: string; enabled?: boolean } = {}): Promise<ReportScheduleCatalog> {
  const searchParams = new URLSearchParams();
  if (input.symbol) {
    searchParams.set("symbol", input.symbol);
  }
  if (input.enabled !== undefined) {
    searchParams.set("enabled", String(input.enabled));
  }
  const suffix = searchParams.size > 0 ? `?${searchParams.toString()}` : "";
  const response = await fetch(`${apiBase()}/api/report-schedules${suffix}`);

  if (!response.ok) {
    throw new Error(`Failed to list report schedules: ${response.status}`);
  }

  return response.json();
}

export async function createReportSchedule(input: {
  name: string;
  symbol: string;
  cadence: ReportSchedule["cadence"];
  brokerMode?: BrokerMode;
  executionMode?: ExecutionMode;
  enabled?: boolean;
  payload?: Record<string, unknown>;
}): Promise<ReportSchedule> {
  const response = await fetch(`${apiBase()}/api/report-schedules`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name: input.name,
      symbol: input.symbol,
      cadence: input.cadence,
      broker_mode: input.brokerMode ?? "disabled",
      execution_mode: input.executionMode ?? "real",
      enabled: input.enabled ?? true,
      payload: input.payload ?? {}
    })
  });

  if (!response.ok) {
    throw new Error(`Failed to create report schedule: ${response.status}`);
  }

  return response.json();
}

export async function triggerReportSchedule(scheduleId: string): Promise<ReportScheduleTrigger> {
  const response = await fetch(`${apiBase()}/api/report-schedules/${scheduleId}/trigger`, {
    method: "POST"
  });

  if (!response.ok) {
    throw new Error(`Failed to trigger report schedule: ${response.status}`);
  }

  return response.json();
}

export async function triggerEnabledReportSchedules(input: { symbol?: string } = {}): Promise<ReportScheduleBulkTrigger> {
  const searchParams = new URLSearchParams();
  if (input.symbol) {
    searchParams.set("symbol", input.symbol);
  }
  const suffix = searchParams.size > 0 ? `?${searchParams.toString()}` : "";
  const response = await fetch(`${apiBase()}/api/report-schedules/trigger-enabled${suffix}`, {
    method: "POST"
  });

  if (!response.ok) {
    throw new Error(`Failed to trigger enabled report schedules: ${response.status}`);
  }

  return response.json();
}

export async function listRoomPolicies(): Promise<RoomPolicyCatalog> {
  const response = await fetch(`${apiBase()}/api/room-policies`);

  if (!response.ok) {
    throw new Error(`Failed to list room policies: ${response.status}`);
  }

  return response.json();
}

export async function evaluateRoomTool(input: { roomId: RoomId | string; toolGrant: string }): Promise<RoomToolDecision> {
  const response = await fetch(`${apiBase()}/api/room-policies/evaluate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      room_id: input.roomId,
      tool_grant: input.toolGrant
    })
  });

  if (!response.ok) {
    throw new Error(`Failed to evaluate room policy: ${response.status}`);
  }

  return response.json();
}

export async function listApprovalLedger(input: { roomId?: RoomId; entityId?: string } = {}): Promise<ApprovalLedgerCatalog> {
  const searchParams = new URLSearchParams();
  if (input.roomId) {
    searchParams.set("room_id", input.roomId);
  }
  if (input.entityId) {
    searchParams.set("entity_id", input.entityId);
  }
  const suffix = searchParams.size > 0 ? `?${searchParams.toString()}` : "";
  const response = await fetch(`${apiBase()}/api/approval-ledger${suffix}`);

  if (!response.ok) {
    throw new Error(`Failed to list approval ledger: ${response.status}`);
  }

  return response.json();
}

export async function recordApprovalLedgerEntry(input: {
  roomId: RoomId;
  source: string;
  entityType: string;
  entityId: string;
  action: RoomDecisionAction;
  actor: string;
  summary: string;
  payload?: Record<string, unknown>;
}): Promise<ApprovalLedgerEntry> {
  const response = await fetch(`${apiBase()}/api/approval-ledger`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      action: input.action,
      actor: input.actor,
      entity_id: input.entityId,
      entity_type: input.entityType,
      payload: input.payload ?? {},
      room_id: input.roomId,
      source: input.source,
      summary: input.summary
    })
  });

  if (!response.ok) {
    throw new Error(`Failed to record approval ledger entry: ${response.status}`);
  }

  return response.json();
}

export async function listAgentTriggers(input: { roomId?: RoomId; symbol?: string; enabled?: boolean } = {}): Promise<AgentTriggerCatalog> {
  const searchParams = new URLSearchParams();
  if (input.roomId) {
    searchParams.set("room_id", input.roomId);
  }
  if (input.symbol) {
    searchParams.set("symbol", input.symbol);
  }
  if (input.enabled !== undefined) {
    searchParams.set("enabled", String(input.enabled));
  }
  const suffix = searchParams.size > 0 ? `?${searchParams.toString()}` : "";
  const response = await fetch(`${apiBase()}/api/agent-triggers${suffix}`);

  if (!response.ok) {
    throw new Error(`Failed to list agent triggers: ${response.status}`);
  }

  return response.json();
}

export async function createAgentTrigger(input: {
  name: string;
  roomId: RoomId;
  triggerType: AgentTrigger["trigger_type"];
  targetAgent: string;
  symbol?: string | null;
  condition?: Record<string, unknown>;
  workflowId?: string | null;
  enabled?: boolean;
  payload?: Record<string, unknown>;
}): Promise<AgentTrigger> {
  const response = await fetch(`${apiBase()}/api/agent-triggers`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      condition: input.condition ?? {},
      enabled: input.enabled ?? true,
      name: input.name,
      payload: input.payload ?? {},
      room_id: input.roomId,
      symbol: input.symbol ?? null,
      target_agent: input.targetAgent,
      trigger_type: input.triggerType,
      workflow_id: input.workflowId ?? null
    })
  });

  if (!response.ok) {
    throw new Error(`Failed to create agent trigger: ${response.status}`);
  }

  return response.json();
}

export async function listPortfolioHoldings(
  providerId: string = "alpaca-paper-broker"
): Promise<PortfolioHoldingsCatalog> {
  const response = await fetch(
    `${apiBase()}/api/portfolio-data/${encodeURIComponent(providerId)}/holdings`
  );

  if (!response.ok) {
    const message = await errorMessage(response, "Failed to fetch holdings");
    const error = new Error(message) as Error & { status?: number };
    error.status = response.status;
    throw error;
  }

  return response.json();
}

export async function listPortfolioAccounts(
  providerId: string = "alpaca-paper-broker"
): Promise<PortfolioAccountsCatalog> {
  const response = await fetch(
    `${apiBase()}/api/portfolio-data/${encodeURIComponent(providerId)}/accounts`
  );

  if (!response.ok) {
    const message = await errorMessage(response, "Failed to fetch accounts");
    const error = new Error(message) as Error & { status?: number };
    error.status = response.status;
    throw error;
  }

  return response.json();
}

export async function listOpenTrades(input: {
  symbol?: string;
  limit?: number;
} = {}): Promise<OpenTradesCatalog> {
  const searchParams = new URLSearchParams();
  if (input.symbol) {
    searchParams.set("symbol", input.symbol);
  }
  if (input.limit !== undefined) {
    searchParams.set("limit", String(input.limit));
  }
  const suffix = searchParams.size > 0 ? `?${searchParams.toString()}` : "";
  const response = await fetch(`${apiBase()}/api/trades/open${suffix}`);

  if (!response.ok) {
    const message = await errorMessage(response, "Failed to fetch open trades");
    const error = new Error(message) as Error & { status?: number };
    error.status = response.status;
    throw error;
  }

  return response.json();
}

export async function listSymbolNews(input: {
  symbol: string;
  sinceHours?: number;
  limit?: number;
}): Promise<NewsCatalog> {
  const searchParams = new URLSearchParams();
  searchParams.set("symbol", input.symbol);
  if (input.sinceHours !== undefined) {
    searchParams.set("since_hours", String(input.sinceHours));
  }
  if (input.limit !== undefined) {
    searchParams.set("limit", String(input.limit));
  }
  const response = await fetch(`${apiBase()}/api/news?${searchParams.toString()}`);

  if (!response.ok) {
    const message = await errorMessage(response, "Failed to fetch news");
    const error = new Error(message) as Error & { status?: number };
    error.status = response.status;
    throw error;
  }

  return response.json();
}

export async function listAgentOperations(input: {
  agentId?: string;
  authority?: AgentOperationAuthority;
  limit?: number;
  operationType?: AgentOperationType;
  roomId?: RoomId | string;
  status?: AgentOperationStatus;
  symbol?: string;
} = {}): Promise<AgentOperationCatalog> {
  const searchParams = new URLSearchParams();
  if (input.limit !== undefined) {
    searchParams.set("limit", String(input.limit));
  }
  if (input.agentId) {
    searchParams.set("agent_id", input.agentId);
  }
  if (input.roomId) {
    searchParams.set("room_id", input.roomId);
  }
  if (input.symbol) {
    searchParams.set("symbol", input.symbol);
  }
  if (input.operationType) {
    searchParams.set("operation_type", input.operationType);
  }
  if (input.status) {
    searchParams.set("status", input.status);
  }
  if (input.authority) {
    searchParams.set("authority", input.authority);
  }
  const suffix = searchParams.size > 0 ? `?${searchParams.toString()}` : "";
  const response = await fetch(`${apiBase()}/api/agent-operations${suffix}`);

  if (!response.ok) {
    throw new Error(`Failed to list agent operations: ${response.status}`);
  }

  return response.json();
}

export async function createAgentOperation(input: {
  agentId: string;
  agentName: string;
  authority: AgentOperationAuthority;
  linkedExecutionProgramId?: string | null;
  linkedRunId?: string | null;
  operationType: AgentOperationType;
  payload?: Record<string, unknown>;
  roomId: RoomId | string;
  sourceWorkflowId?: string | null;
  symbol: string;
}): Promise<AgentOperation> {
  const response = await fetch(`${apiBase()}/api/agent-operations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      agent_id: input.agentId,
      agent_name: input.agentName,
      authority: input.authority,
      linked_execution_program_id: input.linkedExecutionProgramId ?? null,
      linked_run_id: input.linkedRunId ?? null,
      operation_type: input.operationType,
      payload: input.payload ?? {},
      room_id: input.roomId,
      source_workflow_id: input.sourceWorkflowId ?? null,
      symbol: input.symbol
    })
  });

  if (!response.ok) {
    throw new Error(await errorMessage(response, `Failed to create agent operation: ${response.status}`));
  }

  return response.json();
}

export async function completeAgentOperation(
  operationId: string,
  input: {
    linkedExecutionProgramId?: string | null;
    linkedRunId?: string | null;
    payload?: Record<string, unknown>;
  } = {}
): Promise<AgentOperation> {
  const response = await fetch(`${apiBase()}/api/agent-operations/${operationId}/complete`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      linked_execution_program_id: input.linkedExecutionProgramId ?? null,
      linked_run_id: input.linkedRunId ?? null,
      payload: input.payload ?? {}
    })
  });

  if (!response.ok) {
    throw new Error(await errorMessage(response, `Failed to complete agent operation: ${response.status}`));
  }

  return response.json();
}

export async function listTradeTheses(input: {
  symbol?: string;
  status?: TradeThesis["status"];
  targetRoom?: RoomId;
} = {}): Promise<TradeThesisCatalog> {
  const searchParams = new URLSearchParams();
  if (input.symbol) {
    searchParams.set("symbol", input.symbol);
  }
  if (input.status) {
    searchParams.set("status", input.status);
  }
  if (input.targetRoom) {
    searchParams.set("target_room", input.targetRoom);
  }
  const suffix = searchParams.size > 0 ? `?${searchParams.toString()}` : "";
  const response = await fetch(`${apiBase()}/api/trade-theses${suffix}`);

  if (!response.ok) {
    throw new Error(`Failed to list trade theses: ${response.status}`);
  }

  return response.json();
}

export async function createTradeThesis(input: {
  symbol: string;
  sourceReportId?: string | null;
  sourceRoom?: RoomId;
  targetRoom?: RoomId;
  direction: TradeThesis["direction"];
  horizon: string;
  conviction: number;
  thesis: string;
  catalysts?: string[];
  invalidation?: string[];
  riskNotes?: string | null;
  status?: TradeThesis["status"];
  payload?: Record<string, unknown>;
}): Promise<TradeThesis> {
  const response = await fetch(`${apiBase()}/api/trade-theses`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      catalysts: input.catalysts ?? [],
      conviction: input.conviction,
      direction: input.direction,
      horizon: input.horizon,
      invalidation: input.invalidation ?? [],
      payload: input.payload ?? {},
      risk_notes: input.riskNotes ?? null,
      source_report_id: input.sourceReportId ?? null,
      source_room: input.sourceRoom ?? "research",
      status: input.status ?? "proposed",
      symbol: input.symbol,
      target_room: input.targetRoom ?? "market",
      thesis: input.thesis
    })
  });

  if (!response.ok) {
    throw new Error(`Failed to create trade thesis: ${response.status}`);
  }

  return response.json();
}

export async function listPortfolioReviews(input: {
  limit?: number;
  symbol?: string;
  status?: string;
} = {}): Promise<PortfolioReviewCatalog> {
  const searchParams = new URLSearchParams();
  if (input.limit !== undefined) {
    searchParams.set("limit", String(input.limit));
  }
  if (input.symbol) {
    searchParams.set("symbol", input.symbol);
  }
  if (input.status) {
    searchParams.set("status", input.status);
  }
  const suffix = searchParams.size > 0 ? `?${searchParams.toString()}` : "";
  const response = await fetch(`${apiBase()}/api/portfolio-reviews${suffix}`);

  if (!response.ok) {
    throw new Error(`Failed to list portfolio reviews: ${response.status}`);
  }

  return response.json();
}

export async function createPortfolioReview(input: {
  constraints?: string | null;
  goals?: string | null;
  horizon?: string | null;
  liquidityNeeds?: string | null;
  missingProviderFacts?: string[];
  payload?: Record<string, unknown>;
  riskPosture?: string | null;
  roomId?: string;
  sectorFocus?: string | null;
  status?: string;
  symbol: string;
  thesis?: Record<string, unknown>;
}): Promise<PortfolioReviewRecord> {
  const response = await fetch(`${apiBase()}/api/portfolio-reviews`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      constraints: input.constraints ?? null,
      goals: input.goals ?? null,
      horizon: input.horizon ?? null,
      liquidity_needs: input.liquidityNeeds ?? null,
      missing_provider_facts: input.missingProviderFacts ?? [],
      symbol: input.symbol,
      room_id: input.roomId ?? "portfolio",
      risk_posture: input.riskPosture ?? null,
      sector_focus: input.sectorFocus ?? null,
      status: input.status ?? "draft",
      thesis: input.thesis ?? {},
      payload: input.payload ?? {}
    })
  });

  if (!response.ok) {
    throw new Error(`Failed to create portfolio review: ${response.status}`);
  }

  return response.json();
}

export async function listFundingAllocationReviews(input: {
  limit?: number;
  symbol?: string;
  status?: string;
} = {}): Promise<FundingAllocationReviewCatalog> {
  const searchParams = new URLSearchParams();
  if (input.limit !== undefined) {
    searchParams.set("limit", String(input.limit));
  }
  if (input.symbol) {
    searchParams.set("symbol", input.symbol);
  }
  if (input.status) {
    searchParams.set("status", input.status);
  }
  const suffix = searchParams.size > 0 ? `?${searchParams.toString()}` : "";
  const response = await fetch(`${apiBase()}/api/funding-allocation-reviews${suffix}`);

  if (!response.ok) {
    throw new Error(`Failed to list funding allocation reviews: ${response.status}`);
  }

  return response.json();
}

export async function createFundingAllocationReview(input: {
  approvalNextSteps?: string[];
  executionProgramId?: string | null;
  missingProviderFacts?: string[];
  notional?: number | null;
  payload?: Record<string, unknown>;
  sourceThesisId?: string | null;
  status?: string;
  symbol: string;
  tracks?: Record<string, unknown>[];
}): Promise<FundingAllocationReviewRecord> {
  const response = await fetch(`${apiBase()}/api/funding-allocation-reviews`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      approval_next_steps: input.approvalNextSteps ?? [],
      execution_program_id: input.executionProgramId ?? null,
      missing_provider_facts: input.missingProviderFacts ?? [],
      notional: input.notional ?? null,
      payload: input.payload ?? {},
      source_thesis_id: input.sourceThesisId ?? null,
      symbol: input.symbol,
      status: input.status ?? "draft",
      tracks: input.tracks ?? []
    })
  });

  if (!response.ok) {
    throw new Error(`Failed to create funding allocation review: ${response.status}`);
  }

  return response.json();
}

export async function listExecutionPrograms(input: {
  limit?: number;
  symbol?: string;
  state?: string;
} = {}): Promise<ExecutionProgramCatalog> {
  const searchParams = new URLSearchParams();
  if (input.limit !== undefined) {
    searchParams.set("limit", String(input.limit));
  }
  if (input.symbol) {
    searchParams.set("symbol", input.symbol);
  }
  if (input.state) {
    searchParams.set("state", input.state);
  }
  const suffix = searchParams.size > 0 ? `?${searchParams.toString()}` : "";
  const response = await fetch(`${apiBase()}/api/execution-programs${suffix}`);

  if (!response.ok) {
    throw new Error(`Failed to list execution programs: ${response.status}`);
  }

  return response.json();
}

export async function createExecutionProgram(input: {
  algorithmId: string;
  approvalStatus?: string;
  circuitBreakers?: Record<string, unknown>[];
  liveSubmissionEnabled?: boolean;
  missingProviderFacts?: string[];
  mode?: string;
  payload?: Record<string, unknown>;
  sourceThesisId?: string | null;
  state?: string;
  symbol: string;
  triggerPoints?: Record<string, unknown>[];
}): Promise<ExecutionProgramRecord> {
  const response = await fetch(`${apiBase()}/api/execution-programs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      algorithm: input.algorithmId,
      approval_status: input.approvalStatus ?? "required",
      circuit_breakers: input.circuitBreakers ?? [],
      live_submission_enabled: input.liveSubmissionEnabled ?? false,
      missing_provider_facts: input.missingProviderFacts ?? [],
      mode: input.mode ?? "paper",
      payload: input.payload ?? {},
      source_thesis_id: input.sourceThesisId ?? null,
      symbol: input.symbol,
      state: input.state ?? "preview_ready",
      trigger_points: input.triggerPoints ?? []
    })
  });

  if (!response.ok) {
    throw new Error(`Failed to create execution program: ${response.status}`);
  }

  return response.json();
}

export async function listExecutionProgramEvents(programId: string): Promise<ExecutionProgramEventCatalog> {
  const response = await fetch(`${apiBase()}/api/execution-programs/${programId}/events`);

  if (!response.ok) {
    throw new Error(`Failed to list execution program events: ${response.status}`);
  }

  return response.json();
}

export async function appendExecutionProgramEvent(
  programId: string,
  input: {
    eventType: string;
    summary: string;
    payload?: Record<string, unknown>;
  }
): Promise<ExecutionProgramEventRecord> {
  const response = await fetch(`${apiBase()}/api/execution-programs/${programId}/events`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      event_type: input.eventType,
      summary: input.summary,
      payload: input.payload ?? {}
    })
  });

  if (!response.ok) {
    throw new Error(`Failed to append execution program event: ${response.status}`);
  }

  return response.json();
}

export async function previewExecutionAlgorithm(input: {
  algorithm: ExecutionAlgorithm;
  symbol: string;
  side: OrderSide;
  notional: number;
  referencePrice: number;
  roomId?: RoomId;
  parameters?: Record<string, unknown>;
}): Promise<ExecutionAlgorithmPlan> {
  const response = await fetch(`${apiBase()}/api/execution-algorithms/preview`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      algorithm: input.algorithm,
      symbol: input.symbol,
      side: input.side,
      notional: input.notional,
      reference_price: input.referencePrice,
      room_id: input.roomId ?? "market",
      parameters: input.parameters ?? null
    })
  });

  if (!response.ok) {
    throw new Error(`Failed to preview execution algorithm: ${response.status}`);
  }

  return response.json();
}

export async function listExecutionAlgorithms(): Promise<ExecutionAlgorithmCatalogue> {
  const response = await fetch(`${apiBase()}/api/execution-algorithms`);

  if (!response.ok) {
    throw new Error(`Failed to list execution algorithms: ${response.status}`);
  }

  return response.json();
}

export async function listRunEvents(runId: string): Promise<RunEvent[]> {
  const response = await fetch(`${apiBase()}/api/runs/${runId}/events`);

  if (!response.ok) {
    throw new Error(`Failed to list run events: ${response.status}`);
  }

  return response.json();
}

export async function waitForRunEvents(
  runId: string,
  options: {
    intervalMs?: number;
    maxAttempts?: number;
    onEvents?: (events: RunEvent[]) => void;
  } = {}
): Promise<RunEvent[]> {
  const intervalMs = options.intervalMs ?? 2000;
  const maxAttempts = options.maxAttempts ?? 120;
  let latestEvents: RunEvent[] = [];

  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    latestEvents = await listRunEvents(runId);
    options.onEvents?.(latestEvents);

    if (latestEvents.some((event) => event.type === "run.completed" || event.type === "run.failed")) {
      return latestEvents;
    }

    if (attempt < maxAttempts - 1) {
      await delay(intervalMs);
    }
  }

  return latestEvents;
}

export async function getRunTrace(runId: string): Promise<RunTrace> {
  const response = await fetch(`${apiBase()}/api/runs/${runId}/trace`);

  if (!response.ok) {
    throw new Error(`Failed to get run trace: ${response.status}`);
  }

  return response.json();
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => globalThis.setTimeout(resolve, ms));
}

export async function exportRunTrace(runId: string): Promise<RunTrace> {
  const response = await fetch(`${apiBase()}/api/runs/${runId}/trace/export`, {
    method: "POST"
  });

  if (!response.ok) {
    throw new Error(`Failed to export run trace: ${response.status}`);
  }

  return response.json();
}

export async function listProviders(): Promise<ProviderCatalog> {
  const response = await fetch(`${apiBase()}/api/providers`);

  if (!response.ok) {
    throw new Error(`Failed to list providers: ${response.status}`);
  }

  return response.json();
}

export async function listProviderConfigs(): Promise<ProviderConfigCatalog> {
  const response = await fetch(`${apiBase()}/api/provider-configs`);

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
    config?: Record<string, unknown>;
  }
): Promise<ProviderConfig> {
  const response = await fetch(`${apiBase()}/api/provider-configs/${providerId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      enabled: input.enabled,
      secret_ref: input.secretRef,
      config: input.config
    })
  });

  if (!response.ok) {
    throw new Error(`Failed to update provider config: ${response.status}`);
  }

  return response.json();
}

export async function checkProviderHealth(providerId: string): Promise<ProviderConfig> {
  const response = await fetch(`${apiBase()}/api/provider-configs/${providerId}/health-check`, {
    method: "POST"
  });

  if (!response.ok) {
    throw new Error(await failureDetail(response, "Failed to check provider health"));
  }

  return response.json();
}

export type UserProviderKind = "openai-compatible" | "anthropic-compatible";

export async function createUserProvider(input: {
  name: string;
  kind: UserProviderKind;
  baseUrl: string;
  model: string;
  apiKeyEnv?: string | null;
  roleModels?: Record<string, unknown>;
}): Promise<ProviderConfig> {
  const response = await fetch(`${apiBase()}/api/provider-configs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name: input.name,
      kind: input.kind,
      base_url: input.baseUrl,
      model: input.model,
      api_key_env: input.apiKeyEnv ?? null,
      role_models: input.roleModels ?? null
    })
  });

  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(detail?.detail ?? `Failed to create user provider: ${response.status}`);
  }

  return response.json();
}

export async function deleteUserProvider(providerId: string): Promise<void> {
  const response = await fetch(`${apiBase()}/api/provider-configs/${providerId}`, {
    method: "DELETE"
  });

  if (response.status === 204) return;
  const detail = await response.json().catch(() => ({}));
  throw new Error(detail?.detail ?? `Failed to delete user provider: ${response.status}`);
}

export type ProviderModelList = {
  provider_id: string;
  models: string[];
  source: "codex_cache" | "api" | "static" | "unavailable";
  detail?: string | null;
};

export async function listProviderModels(providerId: string): Promise<ProviderModelList> {
  const response = await fetch(`${apiBase()}/api/provider-configs/${providerId}/models`);
  if (!response.ok) {
    throw new Error(`Failed to list provider models: ${response.status}`);
  }
  return response.json();
}

export async function listProviderRoleAssignments(): Promise<ProviderRoleAssignmentCatalog> {
  const response = await fetch(`${apiBase()}/api/provider-role-assignments`);

  if (!response.ok) {
    throw new Error(`Failed to list provider role assignments: ${response.status}`);
  }

  return response.json();
}

export async function updateProviderRoleAssignment(
  roleKey: ProviderRoleKey,
  providerId: string
): Promise<ProviderRoleAssignment> {
  const response = await fetch(`${apiBase()}/api/provider-role-assignments/${roleKey}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ provider_id: providerId })
  });

  if (!response.ok) {
    throw new Error(await failureDetail(response, "Failed to update provider role assignment"));
  }

  return response.json();
}

export async function getRuntimeStatus(): Promise<RuntimeStatus> {
  const response = await fetch(`${apiBase()}/api/runtime/status`);

  if (!response.ok) {
    throw new Error(`Failed to get runtime status: ${response.status}`);
  }

  return response.json();
}

export async function updateResearchRunnerMode(
  mode: "llm-ui-runner" | "tradingagents-graph-runner"
): Promise<RuntimeStatus> {
  const response = await fetch(`${apiBase()}/api/runtime/research-runner`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode })
  });

  if (!response.ok) {
    throw new Error(`Failed to update research runner mode: ${response.status}`);
  }

  return response.json();
}

export async function updateDeveloperMode(enabled: boolean): Promise<RuntimeStatus> {
  const response = await fetch(`${apiBase()}/api/runtime/developer-mode`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled })
  });

  if (!response.ok) {
    throw new Error(`Failed to update developer mode: ${response.status}`);
  }

  return response.json();
}

export async function listAgentWorkflows(agentClass?: "research" | "execution"): Promise<AgentWorkflowCatalog> {
  const searchParams = new URLSearchParams();
  if (agentClass) {
    searchParams.set("agent_class", agentClass);
  }
  const suffix = searchParams.size > 0 ? `?${searchParams.toString()}` : "";
  const response = await fetch(`${apiBase()}/api/agent-workflows${suffix}`);

  if (!response.ok) {
    throw new Error(`Failed to list agent workflows: ${response.status}`);
  }

  return response.json();
}

export async function createAgentWorkflow(input: {
  name: string;
  agentClass: "research" | "execution";
  graphRuntime: "langgraph" | "langchain" | "manual";
  status?: string;
  nodes: AgentWorkflowNode[];
  edges: AgentWorkflowEdge[];
  requiredProviderRoles: Record<string, string>;
  payload?: Record<string, unknown>;
}): Promise<AgentWorkflowRecord> {
  const response = await fetch(`${apiBase()}/api/agent-workflows`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      agent_class: input.agentClass,
      edges: input.edges,
      graph_runtime: input.graphRuntime,
      name: input.name,
      nodes: input.nodes,
      payload: input.payload ?? {},
      required_provider_roles: input.requiredProviderRoles,
      status: input.status ?? "draft"
    })
  });

  if (!response.ok) {
    throw new Error(`Failed to create agent workflow: ${response.status}`);
  }

  return response.json();
}

export async function importAgentPack(input: {
  packId: string;
  sourcePath: string;
  sourceUrl?: string | null;
  sourceCommit?: string | null;
}): Promise<AgentPackImportResult> {
  const response = await fetch(`${apiBase()}/api/agent-packs/import`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      pack_id: input.packId,
      source_path: input.sourcePath,
      source_url: input.sourceUrl ?? null,
      source_commit: input.sourceCommit ?? null
    })
  });

  if (!response.ok) {
    throw new Error(`Failed to import agent pack: ${response.status}`);
  }

  return response.json();
}

export async function listAgentPacks(): Promise<AgentPackCatalog> {
  const response = await fetch(`${apiBase()}/api/agent-packs`);

  if (!response.ok) {
    throw new Error(`Failed to list agent packs: ${response.status}`);
  }

  return response.json();
}

export async function listImportedAgents(input: { packId?: string; agentClass?: string } = {}): Promise<ImportedAgentCatalog> {
  const searchParams = new URLSearchParams();
  if (input.packId) {
    searchParams.set("pack_id", input.packId);
  }
  if (input.agentClass) {
    searchParams.set("agent_class", input.agentClass);
  }
  const suffix = searchParams.size > 0 ? `?${searchParams.toString()}` : "";
  const response = await fetch(`${apiBase()}/api/imported-agents${suffix}`);

  if (!response.ok) {
    throw new Error(`Failed to list imported agents: ${response.status}`);
  }

  return response.json();
}

export async function listImportedSkills(input: { packId?: string } = {}): Promise<ImportedSkillCatalog> {
  const searchParams = new URLSearchParams();
  if (input.packId) {
    searchParams.set("pack_id", input.packId);
  }
  const suffix = searchParams.size > 0 ? `?${searchParams.toString()}` : "";
  const response = await fetch(`${apiBase()}/api/imported-skills${suffix}`);

  if (!response.ok) {
    throw new Error(`Failed to list imported skills: ${response.status}`);
  }

  return response.json();
}

export async function listMcpConnectors(): Promise<McpConnectorCatalog> {
  const response = await fetch(`${apiBase()}/api/mcp-connectors`);

  if (!response.ok) {
    throw new Error(`Failed to list MCP connectors: ${response.status}`);
  }

  return response.json();
}

export async function listSnapshots(): Promise<{ items: SnapshotManifestRecord[] }> {
  const response = await fetch(`${apiBase()}/api/snapshots`);

  if (!response.ok) {
    throw new Error(`Failed to list snapshots: ${response.status}`);
  }

  return response.json();
}

export async function createSnapshot(input: {
  encryptionMode?: string;
  offsiteTarget?: string | null;
  backupKeyRef?: string | null;
}): Promise<SnapshotManifestRecord> {
  const body: Record<string, string | null> = {
    offsite_target: input.offsiteTarget ?? null
  };
  if (input.encryptionMode !== undefined) {
    body.encryption_mode = input.encryptionMode;
  }
  if (input.backupKeyRef) {
    body.backup_key_ref = input.backupKeyRef;
  }
  const response = await fetch(`${apiBase()}/api/snapshots`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });

  if (!response.ok) {
    throw new Error(await failureDetail(response, "Failed to create snapshot"));
  }

  return response.json();
}

export async function verifySnapshot(
  snapshotId: string,
  input: { backupKeyRef: string }
): Promise<SnapshotVerification> {
  const response = await fetch(`${apiBase()}/api/snapshots/${snapshotId}/verify`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      backup_key_ref: input.backupKeyRef
    })
  });

  if (!response.ok) {
    throw new Error(await failureDetail(response, "Failed to verify snapshot"));
  }

  return response.json();
}

export function openRunEventSource(runId: string): EventSource {
  return new EventSource(`${apiBase()}/api/runs/${runId}/stream`);
}

export async function previewTrade(input: {
  runId?: string;
  symbol: string;
  side: OrderSide;
  notional: number;
  roomId?: RoomId;
  // Optional protective-stop envelope. `mode: "broker_protective"`
  // promotes the figures into a real Alpaca bracket / OTO order at
  // submit time; `mode: "advisory_only"` keeps them informational.
  riskControls?: {
    stop_loss: number | null;
    take_profit: number | null;
    mode: "advisory_only" | "broker_protective";
  };
}): Promise<OrderPreview> {
  const body: Record<string, unknown> = {
    run_id: input.runId,
    symbol: input.symbol,
    side: input.side,
    notional: input.notional,
    room_id: input.roomId ?? "market"
  };
  if (input.riskControls) {
    body.risk_controls = input.riskControls;
  }
  const response = await fetch(`${apiBase()}/api/trades/preview`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });

  if (!response.ok) {
    throw new Error(await errorMessage(response, `Failed to preview trade: ${response.status}`));
  }

  return response.json();
}

export async function approveTrade(intentId: string, expectedOrderHash?: string): Promise<{ intent_id: string; status: string }> {
  const response = await fetch(`${apiBase()}/api/trades/${intentId}/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ actor: "local-user", expected_order_hash: expectedOrderHash })
  });
  if (!response.ok) throw new Error(await errorMessage(response, `Failed to approve trade: ${response.status}`));
  return response.json();
}

/** Cancel a preview or request broker cancellation; pending reservations remain until confirmed. */
export async function cancelTrade(intentId: string): Promise<{ intent_id: string; status: string }> {
  const response = await fetch(`${apiBase()}/api/trades/${intentId}/cancel`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ actor: "local-user" })
  });
  if (!response.ok) throw new Error(await errorMessage(response, `Failed to cancel trade: ${response.status}`));
  return response.json();
}

export async function submitTrade(intentId: string): Promise<PaperBrokerOrder> {
  const response = await fetch(`${apiBase()}/api/trades/${intentId}/submit`, { method: "POST" });
  if (!response.ok) throw new Error(await errorMessage(response, `Failed to submit trade: ${response.status}`));
  return response.json();
}

export async function getPaperExecution(intentId: string): Promise<PaperExecutionHistory> {
  const response = await fetch(`${apiBase()}/api/trades/${intentId}/execution`, { cache: "no-store" });
  if (!response.ok) throw new Error(await errorMessage(response, "Failed to load paper execution"));
  return response.json();
}

export async function reconcilePaperOrder(intentId: string): Promise<PaperBrokerOrder> {
  const response = await fetch(`${apiBase()}/api/trades/${intentId}/reconcile`, { method: "POST" });
  if (!response.ok) throw new Error(await errorMessage(response, "Failed to reconcile paper order"));
  return response.json();
}

// -----------------------------------------------------------------------------
// Watcher API — per-symbol price/volume rules. Backend (Phase 3) may finish
// after the UI, so the client treats 404 as "endpoint not available yet" and
// surfaces a typed error with `status` set, mirroring the listOpenTrades /
// listPortfolioHoldings shape.
// -----------------------------------------------------------------------------

export class WatcherEndpointMissingError extends Error {
  status: number;
  constructor(status: number, message = "Watchers endpoint not available yet") {
    super(message);
    this.name = "WatcherEndpointMissingError";
    this.status = status;
  }
}

export async function listWatchers(input: {
  symbol?: string;
  enabled?: boolean;
  limit?: number;
} = {}): Promise<WatcherCatalog> {
  const searchParams = new URLSearchParams();
  if (input.symbol) {
    searchParams.set("symbol", input.symbol);
  }
  if (input.enabled !== undefined) {
    searchParams.set("enabled", String(input.enabled));
  }
  if (input.limit !== undefined) {
    searchParams.set("limit", String(input.limit));
  }
  const suffix = searchParams.size > 0 ? `?${searchParams.toString()}` : "";
  const response = await fetch(`${apiBase()}/api/watchers${suffix}`);

  if (response.status === 404) {
    throw new WatcherEndpointMissingError(404);
  }

  if (!response.ok) {
    throw new Error(`Failed to list watchers: ${response.status}`);
  }

  return response.json();
}

export async function createWatcher(input: {
  name: string;
  symbol: string;
  conditionType: WatcherConditionType;
  threshold: number;
  enabled?: boolean;
  cooldownSeconds?: number;
  linkedPositionId?: string | null;
  linkedRunId?: string | null;
}): Promise<WatcherRecord> {
  const response = await fetch(`${apiBase()}/api/watchers`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name: input.name,
      symbol: input.symbol,
      condition_type: input.conditionType,
      threshold: input.threshold,
      enabled: input.enabled ?? true,
      cooldown_seconds: input.cooldownSeconds ?? 300,
      linked_position_id: input.linkedPositionId ?? null,
      linked_run_id: input.linkedRunId ?? null
    })
  });

  if (response.status === 404) {
    throw new WatcherEndpointMissingError(404);
  }

  if (!response.ok) {
    throw new Error(await errorMessage(response, `Failed to create watcher: ${response.status}`));
  }

  return response.json();
}

export async function getWatcher(watcherId: string): Promise<WatcherRecord> {
  const response = await fetch(`${apiBase()}/api/watchers/${watcherId}`);

  if (!response.ok) {
    throw new Error(`Failed to get watcher: ${response.status}`);
  }

  return response.json();
}

export async function updateWatcher(
  watcherId: string,
  input: {
    name?: string;
    threshold?: number;
    enabled?: boolean;
  }
): Promise<WatcherRecord> {
  const body: Record<string, unknown> = {};
  if (input.name !== undefined) body.name = input.name;
  if (input.threshold !== undefined) body.threshold = input.threshold;
  if (input.enabled !== undefined) body.enabled = input.enabled;

  const response = await fetch(`${apiBase()}/api/watchers/${watcherId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });

  if (!response.ok) {
    throw new Error(await errorMessage(response, `Failed to update watcher: ${response.status}`));
  }

  return response.json();
}

export async function deleteWatcher(watcherId: string): Promise<{ watcher_id: string; deleted: boolean }> {
  const response = await fetch(`${apiBase()}/api/watchers/${watcherId}`, {
    method: "DELETE"
  });

  if (!response.ok) {
    throw new Error(`Failed to delete watcher: ${response.status}`);
  }

  return response.json();
}

export async function listWatcherFires(input: {
  watcherId?: string;
  symbol?: string;
  since?: string;
  limit?: number;
} = {}): Promise<WatcherFireCatalog> {
  const searchParams = new URLSearchParams();
  if (input.watcherId) {
    searchParams.set("watcher_id", input.watcherId);
  }
  if (input.symbol) {
    searchParams.set("symbol", input.symbol);
  }
  if (input.since) {
    searchParams.set("since", input.since);
  }
  if (input.limit !== undefined) {
    searchParams.set("limit", String(input.limit));
  }
  const suffix = searchParams.size > 0 ? `?${searchParams.toString()}` : "";
  const response = await fetch(`${apiBase()}/api/watcher-fires${suffix}`);

  if (response.status === 404) {
    throw new WatcherEndpointMissingError(404);
  }

  if (!response.ok) {
    throw new Error(`Failed to list watcher fires: ${response.status}`);
  }

  return response.json();
}

export async function checkWatcher(watcherId: string): Promise<WatcherCheckResult> {
  const response = await fetch(`${apiBase()}/api/watchers/${watcherId}/check`, {
    method: "POST"
  });

  if (!response.ok) {
    throw new Error(await failureDetail(response, "Failed to check watcher"));
  }

  return response.json();
}
