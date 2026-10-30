import { apiBase } from "./api";

export type AccountingPosition = { symbol: string; quantity: string; market_value_usd: string; cost_basis_usd: string };
export type AccountingSnapshot = { provider_id: string; account_id: string; evidence_kind: "fixture" | "broker_paper"; equity_usd: string; cash_usd: string; observed_at: string; positions: AccountingPosition[]; limitations?: string[] };
export type AccountBaseline = { baseline_id: string; account_key: string; content_hash: string; snapshot: AccountingSnapshot; expires_at: string };
export type AccountingPoint = { observed_at: string; equity_usd: string; cash_usd: string; net_external_flows_usd: string; investment_pnl_usd: string | null; time_weighted_return_fraction: string | null; drawdown_fraction: string | null };
export type AccountingReport = {
  reconciled: boolean; baseline_at: string; observed_at: string; evidence_kind: "fixture" | "broker_paper";
  equity_usd: string; cash_usd: string; investment_pnl_usd: string | null; net_external_flows_usd: string;
  reporting_rounding_change_usd?: string;
  reporting_rounding_history?: {observed_at:string; reported_equity_usd:string; detailed_equity_usd:string; reporting_residual_usd:string; accepted:boolean}[];
  realized_pnl_usd: string; unrealized_pnl_usd: string; opening_unrealized_pnl_usd: string; income_usd: string; fees_usd: string;
  time_weighted_return_fraction: string | null; drawdown_fraction: string | null; maximum_drawdown_fraction: string | null;
  open_orders: { client_order_id: string; symbol: string; side: string; remaining_quantity: string; maximum_price_usd: string | null }[];
  outstanding_execution: { intent_id: string; state: string; broker_order_id: string | null; failure_reason: string | null }[];
  protective_orders?: { broker_order_id:string; parent_broker_order_id:string; symbol:string; protection_role:string;
    executor:string; status:string; remaining_quantity:string; filled_quantity:string; limit_price_usd:string|null;
    stop_price_usd:string|null; observed_at:string; approved_terms_match:boolean }[];
  activity_count: number; equity_history: AccountingPoint[];
  discrepancies: { code: string; detail?: string; source_id?: string; symbol?: string; expected_usd?: string; observed_usd?: string }[];
  limitations: string[];
  positions: { symbol: string; quantity: string; analytical_basis_usd: string; broker_basis_usd: string | null; owners: Record<string,string> }[];
  attribution: { owner: string; realized_pnl_usd: string; unrealized_pnl_usd: string; income_usd: string; fees_usd: string; period_pnl_usd: string }[];
  fills: { source_id: string; symbol: string; side: string; quantity: string; price_usd: string; fee_usd: string; executor: string; effective_at: string; broker_order_id: string; parent_broker_order_id?:string; protection_role?:string }[];
};
export type AccountReconciliation = { reconciliation_id: string; report: AccountingReport; observed_at: string; created_at: string };
export type ObservedPaperAccount = { enrollment: { account_key: string; account_id: string; provider_id: string; approved_at: string }; baseline: AccountBaseline; latest: AccountReconciliation | null };

async function call<T>(path: string, body?: unknown, post = false, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${apiBase()}/api/paper-accounting${path}`, {
    method: post ? "POST" : "GET", cache: "no-store", signal,
    headers: { "Content-Type": "application/json", "x-trademaster-room": "transactions" },
    body: body === undefined ? undefined : JSON.stringify(body)
  });
  if (!response.ok) {
    let detail = `Account observation failed (${response.status})`;
    try { const value = await response.json(); if (typeof value.detail === "string") detail = value.detail; } catch { /* Keep the status message. */ }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}
export const listObservedPaperAccounts = () => call<{accounts:ObservedPaperAccount[]}>("/accounts");
export const previewAccountBaseline = () => call<AccountBaseline>("/baselines/preview",undefined,true);
export const approveAccountBaseline = (baseline: AccountBaseline) => call(`/baselines/${baseline.baseline_id}/approve`,{actor:"local-user",expected_hash:baseline.content_hash},true);
export const reconcileObservedAccount = (key: string) => call<AccountReconciliation>(`/accounts/${encodeURIComponent(key)}/reconcile`,undefined,true);
export const listAccountReconciliations = (key: string) => call<{reconciliations:AccountReconciliation[]}>(`/accounts/${encodeURIComponent(key)}/history`);

export type SourceCorrectionReview={review_id:string;account_key:string;content_hash:string;expires_at:string;created_at:string;
  payload:{eligible:boolean;effect:string;changes:{source_id:string;previous_hash:string;selected_hash:string;previous_activity:Record<string,unknown>;selected_activity:Record<string,unknown>}[];
    before:Record<string,string|boolean|null>;after:Record<string,string|boolean|null>;excluded_observation_ids:string[];restored_observation_ids?:string[];
    newly_excluded_observations:{reconciliation_id:string;observed_at:string;cash_usd:string;equity_usd:string}[];
    discrepancies:{code:string;detail?:string}[];limitations:string[]}};
export type SourceCorrectionState={pending_source_ids:string[];reviews:SourceCorrectionReview[];
  approvals:{correction_id:string;review_id:string;actor:string;reason:string;created_at:string}[]};
export const sourceCorrections=(key:string,signal?:AbortSignal)=>call<SourceCorrectionState>(`/accounts/${encodeURIComponent(key)}/corrections`,undefined,false,signal);
export const previewSourceCorrections=(key:string,signal?:AbortSignal)=>call<SourceCorrectionReview>(`/accounts/${encodeURIComponent(key)}/corrections/preview`,undefined,true,signal);
export const approveSourceCorrections=(review:SourceCorrectionReview,reason:string,signal?:AbortSignal)=>call(`/accounts/${encodeURIComponent(review.account_key)}/corrections/${encodeURIComponent(review.review_id)}/approve`,{actor:"local-user",expected_hash:review.content_hash,reason},true,signal);

export type DeploymentPerformancePoint = { observed_at: string; source: string; equity_usd: string|null; cash_usd: string|null;
  market_value_usd: string|null; investment_pnl_usd: string|null; net_allocations_usd?: string;
  time_weighted_return_fraction: string|null; drawdown_fraction: string|null };
export type DeploymentPerformance = Partial<DeploymentPerformancePoint> & { status: string; closed?: boolean;
  maximum_drawdown_fraction: string|null; limitations: string[]; equity_history: DeploymentPerformancePoint[];
  capital_flows: { flow_id: string; effective_at: string; action: string; actor: string; amount_usd: string;
    exact_valuation?: boolean; equity_before_flow_usd?: string|null; reconciliation_id: string; reviewed_valuation_at: string }[] };
export type DeploymentPerformanceReport = { account_key: string; reconciliation_id: string|null; observed_at: string|null;
  deployments: { deployment_id: string; name: string; version_id: string; state: string; input_hash: string; performance: DeploymentPerformance }[] };
export const listDeploymentPerformance = (key: string, signal?: AbortSignal) => call<DeploymentPerformanceReport>(`/accounts/${encodeURIComponent(key)}/deployment-performance`,undefined,false,signal);
