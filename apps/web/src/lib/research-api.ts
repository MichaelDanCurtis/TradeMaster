import { apiBase } from "./api";

export type StrategyDraft = { name: string; hypothesis: string; rationale: string };
export type Strategy = StrategyDraft & { strategy_id: string; revision: number; created_at: string };
export type RiskPolicy = {
  max_position_fraction: string; max_group_fraction: string; cash_reserve_fraction: string;
  max_turnover_fraction: string; max_drawdown_fraction: string;
};
export type StrategySpec = {
  universe: { instrument_id: string; symbol: string; risk_group: string; currency: "USD" }[];
  rules: { kind: "diversified_trend"; lookbacks_sessions: number[]; volatility_sessions: number; decision_latency_seconds?: number } |
    { kind: "guidance_cash_quality"; arm: "guidance_control" | "numeric_quality" | "astra_challenger"; hold_sessions: number; decision_latency_seconds?: number; entry_validity_sessions?: number };
  risk: RiskPolicy;
  model?: { provider_id: string; model_id: string; prompt_hash: string; schema_hash: string; provider_config_hash?: string | null; historical_latency_seconds?: number } | null;
};
export type ResearchProvider = { role: "research_designer" | "research_extractor"; available: boolean; provider_id?: string; model_id?: string; provider_config_hash?: string; billing_mode?: "api_metered" | "codex_subscription"; message: string };
export type ExtractionPolicy = {
  billing_mode?: "api_metered" | "codex_subscription";
  max_calls: number; max_input_tokens: number; max_output_tokens: number;
  input_usd_per_million: string; output_usd_per_million: string; pricing_reference: string;
  timeout_seconds: number; availability_mode: "historical" | "observed";
};
export type ModelCall = {
  call_id: string; notice_id: string; state: "reserved" | "dispatched" | "completed" | "unknown";
  request: { model: NonNullable<StrategySpec["model"]>; policy: ExtractionPolicy };
  input_as_of: string; reserved_cost_usd: string; charged_cost_usd: string;
  output_artifact: string | null; failure_reason: string | null;
};
export type ModelReceipt = {
  actual_provider_id: string; actual_model_id: string; input_tokens: number | null; output_tokens: number | null;
  cost_usd: string; cost_basis: string; validation_errors: string[]; raw_output: string;
  classification: unknown; availability: { mode: string; available_at: string };
};
export type StrategyVersion = { version_id: string; content_hash: string; created_at: string; payload: { spec: StrategySpec; hypothesis: string } };
export type ResearchPlan = { plan_id: string; family_id: string; created_at: string; payload: PlanInput };
export type StrategyDetail = { strategy: Strategy; versions: StrategyVersion[]; plans: ResearchPlan[];
  family?: { family_id: string; max_trials: number; compute_budget_usd: string } | null;
  family_usage?: { trials: number; cost_usd: string };
};
export type Snapshot = { snapshot_id: string; evidence_kind: string; payload: { provider: string; provenance: string; instrument_ids: string[]; coverage_start: string; coverage_end: string; availability: string; limitations: string[] } };
export type PlanInput = {
  strategy_id: string; family_id: string; version_ids: string[];
  split: { train_start: string; train_end: string; validation_start: string; validation_end: string; holdout_start: string; holdout_end: string; embargo_sessions: number };
  initial_capital_usd: string; cash_annual_yield_fraction?: string; max_trials: number; compute_budget_usd: string; max_runtime_seconds: number;
  extraction?: ExtractionPolicy | null;
  equity_reference?: { instrument: StrategySpec["universe"][number]; initial_allocation_fraction: string; rationale: string; method?: "buy_and_hold" } | null;
  scenarios: { name: string; slippage_bps: string; commission_usd: string; commission_bps?: string; execution_delay_sessions: number }[];
  criteria: { min_observations: number; min_net_excess_return_fraction: string; max_drawdown_fraction: string; rationale: string; min_guidance_event_clusters?: number; min_human_labels?: number; min_classifier_accuracy_lower_bound?: string };
};
export type Experiment = {
  experiment_id: string; plan_id: string; snapshot_id: string; state: "queued" | "running" | "completed" | "failed" | "cancelled";
  engine: string; evaluation: string; trial_count: number; attempts: number; cost_usd: string; created_at: string; failure_reason: string | null;
  result: null | { evidence_status: string; explanation: string; engine_build: string; report: EvidenceReport; artifacts: Record<string, string> };
};

export type ResearchRuntime = { available: boolean; queued: number; supported_engines: string[]; message: string; engine_capabilities?: { engine: string; available: boolean; message: string; image?: string }[] };
export type PerformanceMetrics = {
  observations: number; fills: number; total_return_fraction: number | null; annualized_return_fraction: number | null;
  annualized_volatility_fraction: number | null; sharpe_ratio: number | null; max_drawdown_fraction: number | null;
  max_underwater_sessions?: number | null; current_underwater_sessions?: number | null;
  worst_session_return_fraction?: number | null; mean_worst_five_percent_fraction?: number | null;
  gross_traded_notional_usd?: string | null; gross_turnover_fraction?: number | null;
  mean_exposure_fraction: number | null; fees_usd: string; slippage_usd: string; stale_valuation_sessions: number; undefined: Record<string, string>;
};
export type RunSummary = {
  version_id: string; scenario: string; control: "strategy" | "fixed_basket" | "cash" | "equity_reference"; artifact_hash: string;
  metrics: PerformanceMetrics; decisions: number; missing_signal_decisions: number; unfilled_orders: number; risk_breach_sessions: number;
  comparison: null | { net_excess_return_fraction: number | null; exposure_difference_fraction: number | null;
    mean_daily_excess_lower: number | null; mean_daily_excess_upper: number | null; uncertainty: string };
  equity_comparison?: RunSummary["comparison"];
};
export type EvidenceReport = {
  schema_version: 1; engine_build: string; snapshot_kind: string; evaluation_start: string; evaluation_end: string;
  inspected_family_trials: number; family_trial_ceiling: number; runs: RunSummary[]; limitations: string[];
  equity_reference?: PlanInput["equity_reference"];
  evaluated_dataset_hash?: string | null; evidence_artifacts?: string[]; model_call_ids?: string[]; model_call_costs?: Record<string, string>;
  assessments: { version_id: string; evidence_status: string; checks: { name: string; passed: boolean; detail: string }[] }[];
  arm_comparisons?: { challenger_version_id: string; control_version_id: string; scenario: string; comparison: NonNullable<RunSummary["comparison"]>;
    challenger_extraction_cost_usd: string; control_extraction_cost_usd: string; excess_after_extraction_cost_fraction: number | null; entered_event_clusters: number; cost_note: string; paired_events?: PairedEventSummary|null }[];
  classification_checks?: Record<string, { labels: number; completed: number; invalid: number; correct: number; accuracy: number | null; accuracy_lower_bound: number | null; confusion: Record<string, Record<string, number>>; method: string }>;
};
export type PairedEventSummary = {
  artifact_hash:string; page_artifact_hashes:string[]; events:number; issuer_period_clusters:number;
  both_entered:number; challenger_only:number; control_only:number; neither_entered:number; reconciled:boolean;
  challenger_event_pnl_usd:string; control_event_pnl_usd:string; event_pnl_difference_usd:string;
  cash_yield_difference_usd:string; portfolio_pnl_difference_usd:string; method:string;
};
export type EventArmOutcome = {
  state:string; entered:boolean; investment_pnl_usd:string; contribution_fraction:string; entry_notional_usd:string;
  remaining_quantity:number; entry_at:string|null; exit_at:string|null; entry_proposed:boolean;
  realized_pnl_usd?:string; unrealized_pnl_usd?:string; dividends_usd?:string; fees_usd?:string; slippage_usd?:string;
  held_closes?:number; stale_closes?:number; final_valuation_stale?:boolean;
  decisions:{at:string; status:string; reason:string; evidence_verdict?:string|null}[];
  fills:{fill_id:string; executed_at:string; quantity:number; price_usd:string; fee_usd:string; exit_reason?:string|null}[];
  corporate_actions:{action_id:string; kind:string; at:string; entitlement_usd?:string; cash_in_lieu_usd?:string; ratio?:string; payable_at?:string|null}[];
};
export type PairedEventRow = {
  notice_id:string; instrument_id:string; cluster_id:string; available_at:string; period_start:string; period_end:string;
  challenger:EventArmOutcome; control:EventArmOutcome; pnl_difference_usd:string; contribution_difference_fraction:string;
  matched_fill_times:boolean;
};
export type PortfolioRiskEstimate = {
  method: string; observations: number; first_return_session: string; last_return_session: string;
  annualization_sessions: number; input_hash: string; invested_fraction: string;
  annualized_volatility_fraction: number; annualized_volatility_assuming_independence_fraction: number;
  diversification_ratio: number | null;
  contributions: Record<string, { weight: string; annualized_standalone_volatility_fraction: number;
    annualized_covariance_with_portfolio: number; annualized_volatility_contribution_fraction: number | null; share_of_portfolio_variance: number | null }>;
  group_variance_shares: Record<string, number | null>; limitations: string[];
};
export type ReplayArtifact = {
  initial_capital_usd: string;
  decisions?: { decision_id: string; at: string; proposed_quantities: Record<string, number>;
    decision: { status: string; reason: string; portfolio_risk?: PortfolioRiskEstimate | null } }[];
  equity: { at: string; equity_usd: string; cash_usd: string; receivables_usd: string; quantities: Record<string, number>; stale_instruments: string[] }[];
  fills: { fill_id: string; instrument_id: string; signal_at: string; executed_at: string; observed_at: string; quantity: number; price_usd: string; fee_usd: string }[];
  events: { at: string; kind: string; detail: string; amount_usd: string }[];
  venue_receipts?: { order_id: number; instrument_id: string; at: string; quantity: number; price_usd: string; fee_usd: string; cash_usd: string; status: string }[];
  venue_equity?: { at: string; cash_usd: string; equity_usd: string; receivables_usd: string; quantities: Record<string, number>; cost_basis_usd: string }[];
  guidance_events?: { notice_id: string; instrument_id: string; at: string; action: string; status: string; reason: string; evidence_id: string | null; evidence_verdict: string | null;
    quality: { status: string; reason: string; current_revenue_usd: string | null; current_operating_cash_flow_usd: string | null; current_cash_margin: string | null; prior_cash_margin: string | null } | null }[];
};

export class ResearchRequestError extends Error {
  constructor(message: string, readonly status: number) { super(message); }
}

export async function researchRequest<T>(path: string, input?: unknown, method = "POST", signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${apiBase()}/api/research${path}`, {
    method: input === undefined ? "GET" : method,
    headers: { "Content-Type": "application/json", "X-Trademaster-Room": "research" },
    body: input === undefined ? undefined : JSON.stringify(input), signal,
  });
  if (!response.ok) {
    let message = `Research request failed (${response.status})`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") message = body.detail;
      else if (Array.isArray(body.detail)) message = body.detail.map((item: { msg?: string; loc?: (string | number)[] }) => {
        const field = item.loc?.filter((part) => part !== "body").join(".");
        return field ? `${field}: ${item.msg ?? "Invalid value"}` : item.msg;
      }).filter(Boolean).join("; ");
    } catch { /* Preserve HTTP status for non-JSON responses. */ }
    throw new ResearchRequestError(message, response.status);
  }
  return response.json() as Promise<T>;
}

export function evidenceLabel(status: string): string {
  const labels: Record<string, string> = {
    fixture_only: "Fixture only", insufficient_evidence: "Insufficient evidence", rejected: "Rejected",
    eligible_for_paper_review: "Eligible for paper review", historical: "Historical data", fixture: "Synthetic fixture", prospective: "Prospective observations",
  };
  return labels[status] ?? status.replaceAll("_", " ");
}
