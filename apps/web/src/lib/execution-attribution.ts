import { apiBase } from "@/lib/api";

export type ExecutionAttributionRow = {
  evaluation_id:string;instrument_id:string;symbol:string;side:string;outcome:string;
  observed_quantity_at_evaluation:number;proposed_quantity:number;proposed_delta:number;
  ever_approved_quantity:number|null;dispatch_approved_quantity:number|null;reconciled_fill_quantity:string|null;unfilled_proposed_quantity:string|null;
  broker_observed_filled_quantity:string|null;average_fill_price_usd:string|null;fill_fees_usd:string|null;
  decision_reference_price_usd:string|null;filled_price_difference_usd:string|null;filled_price_difference_plus_fees_usd:string|null;
  timeline:Record<string,string|null>;delays:Record<string,number|null>;limitations:string[];
  events:{event_id:string;kind:string;created_at:string;actor:string|null;observed_status:string|null}[];
  protective_fills?:{source_id:string;protection_role:string;quantity:string;price_usd:string;fee_usd:string;effective_at:string}[];
};
export type ExecutionAttribution = {
  deployment_id:string;deployment_name:string;version_id:string;generated_at:string;account_observed_at:string|null;
  account_reconciled:boolean;reconciliation_id:string|null;evidence_kind:string|null;input_hash:string;
  evaluations:{evaluation_id:string;created_at:string;status:string;reason:string}[];
  next_cursor:string|null;rows:ExecutionAttributionRow[];limitations:string[];
};
export type AttributedDeployment={deployment_id:string;name:string;state:string;version_id:string};

async function read<T>(path:string,room:string,signal?:AbortSignal):Promise<T> {
  const response=await fetch(`${apiBase()}${path}`,{headers:{"X-Trademaster-Room":room},cache:"no-store",signal});
  if(!response.ok){let message=`Execution history unavailable (${response.status})`;try{const body=await response.json();if(typeof body.detail==="string")message=body.detail;}catch{/* Preserve the HTTP error. */}throw new Error(message);}
  return response.json() as Promise<T>;
}
export function attributedDeployments(accountKey:string,signal?:AbortSignal) {
  return read<{deployments:AttributedDeployment[]}>(`/api/paper-accounting/accounts/${encodeURIComponent(accountKey)}/deployments`,"transactions",signal);
}
export function executionAttribution(deploymentId:string,accountKey?:string,before?:string,signal?:AbortSignal) {
  const root=accountKey?`/api/paper-accounting/accounts/${encodeURIComponent(accountKey)}/deployments`:'/api/research/deployments';
  return read<ExecutionAttribution>(`${root}/${encodeURIComponent(deploymentId)}/execution-attribution${before?`?before=${encodeURIComponent(before)}`:""}`,accountKey?"transactions":"market",signal);
}
