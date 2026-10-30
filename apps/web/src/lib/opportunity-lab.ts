import type { HistoricalEvidenceView } from "@/components/HistoricalReplayEvidence";
import { apiBase } from "./api";

export type Saved<T> = { id: string; symbol: string; created_at: string; payload: T };
export type Candidate = {
  symbol: string; name: string; snapshot_id: string; previous_snapshot_id: string | null;
  collected_at: string; priority: number; security_type: string;
  screen: { state: string; checks: {name: string; value: number | null; threshold: number; state: string}[] };
  reasons: {kind: string; text: string}[]; gaps: string[];
  filings: {accession: string; url: string; form: string; filed: string}[];
  sources: {url: string; sha256: string; retrieved_at: string}[];
};
export type Scan = Saved<{
  recipe_id?: string | null; recipe_hash?: string | null; state: string; symbols: string[]; processed: number; active_symbol: string | null;
  request: {symbols: string[]; min_growth: number; min_margin: number; require_fcf: boolean};
  results: Candidate[]; failures: {symbol: string; message: string}[];
}>;
export type TriageState = "new" | "investigate" | "watch" | "dismissed";
export type Triage = Saved<{scan_id: string; symbol: string; state: TriageState; note: string}>;
export type ReplaySummary = {id: string; symbol: string; cutoff: string; step: number; horizon: number};
export type Replay = ReplaySummary & {
  evidence_mode?: "price" | "filings"; historical_evidence?: HistoricalEvidenceView | null;
  visible_through: string; complete: boolean; bars: {date: string; close: number; volume: number}[];
  decisions: {expected_step: number; decision: string; thesis: string; invalidation: string; visible_through: string; recorded_at: string; historical_assessment?: {brief_id:string;packet_hash:string}; receipt_hash: string}[];
  revealed_price_change_pct: number | null; feed: string; captured_at: string; capture_hash: string; limitations: string[];
};
export type Inbox = {starter_symbols: string[]; scans: Scan[]; triage: Triage[]; replays: ReplaySummary[]; scope: string};
export function parseBasket(value: string) {
  return [...new Set(value.toUpperCase().split(/[\s,]+/).filter(Boolean))];
}
export function validBasket(symbols: string[]) {
  return symbols.length > 0 && symbols.length <= 500 && symbols.every(s => /^[A-Z][A-Z0-9.\-]{0,11}$/.test(s));
}
export async function opportunityRequest<T>(path = "", body?: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${apiBase()}/api/discover/opportunities${path}`, {
    method: body === undefined ? "GET" : "POST", cache: "no-store", signal,
    headers: body === undefined ? undefined : {"Content-Type": "application/json"},
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Request failed (${response.status})`);
  return data;
}
