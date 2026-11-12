/** Market observations and separately preserved, evidence-linked assessments. */
export type PulseQuote = {
  symbol: string;
  label: string;
  price: number | null;
  change_pct: number | null;
  price_at: string | null;
  previous_close: number | null;
  open: number | null;
  high: number | null;
  low: number | null;
  gap_pct: number | null;
  vwap_delta_pct: number | null;
  volume: number | null;
  spread_bps: number | null;
  quote_at: string | null;
  day_at: string | null;
  freshness: string;
};
export type PulseMover = {
  symbol: string;
  side: "gainers" | "losers";
  price: number;
  change_pct: number;
  as_of: string | null;
  snapshot: PulseQuote;
};
export type PulseBoard = {
  snapshot_id: string;
  captured_at: string;
  status: "available" | "partial" | "unavailable";
  feed: string;
  cached: boolean;
  ranking_basis: string;
  snapshot_basis: string;
  coverage: string;
  sources: { source: string; status: string; updated_at: string | null }[];
  benchmarks: PulseQuote[];
  sectors: PulseQuote[];
  gainers: PulseMover[];
  losers: PulseMover[];
  activity: (PulseQuote & { screener_volume: number | null })[];
};
export type PulseEvidence = {
  source_id: string;
  symbol: string;
  kind: string;
  title: string;
  publisher: string;
  published_at: string | null;
  retrieved_at: string;
  url: string | null;
  text: string;
};
export type PulseExplanation = {
  symbol: string;
  driver: string;
  evidence: "reported_event" | "possible_link" | "insufficient";
  summary: string;
  alternative: string;
  citations: { source_id: string; quote: string }[];
};
export type PulseAnalysis = {
  brief_id: string;
  state: string;
  message: string;
  model_id: string;
  created_at: string;
  packet: {
    snapshot_id: string;
    collected_at: string;
    movers: Omit<PulseMover, "snapshot">[];
    sources: PulseEvidence[];
    gaps: string[];
  } | null;
  receipt: {
    proposal: { explanations: PulseExplanation[] } | null;
    validation_errors: string[];
  } | null;
};
export type PulseProvider = {
  available: boolean;
  provider_config_hash?: string;
  model_id?: string;
  message: string;
};
export const analysisRunning = (analysis: PulseAnalysis | null) =>
  !!analysis &&
  ["queued", "collecting", "synthesizing"].includes(analysis.state);
export const pct = (value: number | null | undefined) =>
  value == null || !Number.isFinite(value)
    ? "—"
    : `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
export const price = (value: number | null | undefined) =>
  value == null || !Number.isFinite(value)
    ? "—"
    : value.toLocaleString("en-US", {
        minimumFractionDigits: 2,
        maximumFractionDigits: value < 1 ? 4 : 2,
      });
export const volume = (value: number | null | undefined) =>
  value == null || !Number.isFinite(value)
    ? "—"
    : Intl.NumberFormat("en-US", {
        notation: "compact",
        maximumFractionDigits: 1,
      }).format(value);
export const tone = (value: number | null | undefined) =>
  value == null || value === 0 ? "neutral" : value > 0 ? "up" : "down";
export function age(value: string | null | undefined, now: number): string {
  if (!value) return "No timestamp";
  const seconds = (now - Date.parse(value)) / 1000;
  if (!Number.isFinite(seconds) || seconds < -5) return "Invalid time";
  if (seconds < 60) return "<1m ago";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}
export function rankingReady(board: PulseBoard | null, now: number): boolean {
  if (!board || now - Date.parse(board.captured_at) > 900_000) return false;
  const rows = [...board.gainers.slice(0, 5), ...board.losers.slice(0, 5)];
  return (
    rows.length > 0 &&
    rows.every((row) => {
      const elapsed = now - Date.parse(row.as_of ?? "");
      return (
        Number.isFinite(elapsed) && elapsed >= -5000 && elapsed <= 4 * 86400_000
      );
    })
  );
}
export function sameCapture(
  board: PulseBoard | null,
  analysis: PulseAnalysis | null,
) {
  return (
    !!board &&
    !!analysis?.packet &&
    board.snapshot_id === analysis.packet.snapshot_id
  );
}
export function linkedSource(
  analysis: PulseAnalysis,
  sourceId: string,
): PulseEvidence | undefined {
  const source = analysis.packet?.sources.find(
    (item) => item.source_id === sourceId,
  );
  if (!source?.url) return undefined;
  try {
    const url = new URL(source.url);
    return ["https:", "http:"].includes(url.protocol) &&
      !url.username &&
      !url.password
      ? source
      : undefined;
  } catch {
    return undefined;
  }
}
