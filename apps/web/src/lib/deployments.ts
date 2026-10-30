import { apiBase } from "@/lib/api";
import type { StrategySpec, PortfolioRiskEstimate } from "@/lib/research-api";

export type StrategyReviewSelection = { version_id: string; experiment_id: string };
export type DeploymentCandidate = StrategyReviewSelection & { strategy_name: string; created_at: string; evidence_status: string; evidence_kind: string; spec: StrategySpec };
export type DeploymentTerms = { capital_usd: string; execution_policy: StrategySpec["risk"] & { snapshot_max_age_seconds?: number }; fee_reserve_per_order_usd: string; fee_assumption_reference: string; funding_rationale: string; per_order_human_approval?: true };
export type DeploymentRecord = { deployment_id: string; name: string; version_id: string; experiment_id: string; state: string; revision: number; active_terms_id: string | null; account_key: string; account: { provider_id: string; account_id: string; environment: "paper" } };
export type DeploymentWorkerRuntime = {
  connected: boolean; evaluation_worker_connected: boolean; queued: number; running: number; message: string;
  stale_after_seconds: number; order_authority: false;
  workers: {worker_id:string; mode:string; status:string; connected:boolean; last_seen_at:string; account_key:string|null;
    cycle_deadline:string|null; interval_seconds:number; cycle_timeout_seconds:number;
    last_result:{status:string; error_type?:string; message?:string; account?:{reconciliation_id:string; observed_at?:string; drawdown_available:boolean}}|null}[];
};
export type PromotionReview = { review_id: string; deployment_revision: number; content_hash: string; expires_at: string; payload: { eligible: boolean; terms: DeploymentTerms; account: { account_id: string; evidence_kind: string; equity_usd: string; cash_usd: string; drawdown_fraction: string }; allocation?: { amount_usd: string; equity_usd: string; cash_usd: string; creates_flow: boolean; scope: string; valuation_policy: string }; funding: { available_envelope_usd: string; other_envelopes_usd: string; unallocated_holdings_usd: string; own_holdings_usd: string }; gates: { name: string; passed: boolean; detail: string }[] } };
export type DeploymentPortfolioRow = { instrument_id: string; symbol: string; weight: string|null; reference_price_usd: string; current_quantity: number; desired_quantity: number; delta_quantity: number };
export type DeploymentEvaluationJob = { job_id: string; state: string; created_at: string; started_at: string|null; lease_until: string|null; deadline: string|null; result: { message?: string; failure?: { stage: string; error_type: string } }|null };
export type FundedPortfolioRisk = {
  status: string; reason: string; basis: string; as_of: string; capital_usd: string; lookback_return_sessions: number;
  gross_exposure_usd: string|null; unused_envelope_usd: string|null; reserve_headroom_usd: string|null;
  annualized_volatility_usd: string|null; capital_relative_volatility_fraction: string|null; covariance_denominator_usd: string|null;
  covariance: PortfolioRiskEstimate|null; limitations: string[];
  positions: { instrument_id: string; symbol: string; quantity: string; price_usd: string; exposure_usd: string; capital_fraction: string; limit_usd: string; over_limit: boolean }[];
  groups: { group: string; exposure_usd: string; capital_fraction: string; limit_usd: string; over_limit: boolean }[];
};
export type DeploymentEvaluation = { evaluation_id: string; created_at: string; payload: { funded_risk?: { observed: FundedPortfolioRisk; proposed: FundedPortfolioRisk|null }; decision?: { portfolio_risk?: PortfolioRiskEstimate|null }|null; status: string; reason: string; as_of: string; execution_opens_at: string|null; execution_deadline: string|null; portfolio: DeploymentPortfolioRow[]; snapshot_hash: string; build_hash: string; limitations?: string[]; guidance_events?: { notice_id:string; instrument_id:string; status:string; reason:string }[]; guidance_state?: { holding_clocks:Record<string,{notice_id:string;entry_at:string}>; consumed_notices:string[] }; cancel_entries?:string[] } };
export type DeploymentDetail = { evaluation_jobs?: DeploymentEvaluationJob[]; deployment: DeploymentRecord; terms: { payload: DeploymentTerms }; active_terms: { payload: DeploymentTerms } | null; reviews: PromotionReview[]; events: { event_id: string; action: string; actor: string; reason: string; created_at: string }[]; evaluations: DeploymentEvaluation[]; actual_fills: { source_id: string; symbol: string; side: string; quantity: string; price_usd: string; fee_usd: string; effective_at: string }[]; orders: { order_id: string; intent_id: string; content_hash: string; state: string; order: { symbol: string; side: string; quantity: number; limit_price_usd: string; fee_reserve_usd: string; expires_at: string } }[]; attributed_positions: { symbol: string; owners: Record<string,string> }[]; observed_at: string | null; account_reconciled: boolean; programs: { program_id: string }[] };
export async function deploymentRequest<T>(path: string, input?: unknown, signal?: AbortSignal): Promise<T> {
  const response=await fetch(`${apiBase()}/api/research/deployments${path}`, { method: input===undefined ? "GET":"POST", headers:{"Content-Type":"application/json","X-Trademaster-Room":"market"}, body:input===undefined?undefined:JSON.stringify(input),signal,cache:"no-store" });
  if (!response.ok) {
    let message=`Deployment request failed (${response.status})`;
    try { const body=await response.json(); if (typeof body.detail==="string") message=body.detail; else if (Array.isArray(body.detail)) message=body.detail.map((item:{msg:string})=>item.msg).join("; "); } catch { /* Keep HTTP status. */ }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}
