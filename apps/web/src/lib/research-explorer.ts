export type ExplorerCandidate = {
  symbol: string; price: number | null; change_pct: number | null; volume: number | null; sources: string[];
};
export type ExplorerCatalog = {
  observed_at: string; provider: string; candidates: ExplorerCandidate[];
  sources: { source: string; status: string; observed_at: string; provider_updated_at: string | null; message: string }[];
};
export type ExplorerLens = "all" | "gainer" | "loser" | "most_active";
export const explorerLenses: { id: ExplorerLens; title: string; description: string; question: string }[] = [
  { id: "all", title: "Explore the market", description: "A balanced view of strength, declines and activity.", question: "What explains this move, and what evidence would contradict the investment case?" },
  { id: "gainer", title: "Follow strength", description: "Stocks on the provider’s top gainers list.", question: "Is there a durable earnings or business catalyst, or is this a short-lived price spike?" },
  { id: "loser", title: "Investigate declines", description: "Sharp declines that deserve a closer look.", question: "Is this a temporary setback or a deterioration in the business? A decline alone does not make a stock cheap." },
  { id: "most_active", title: "Follow activity", description: "Stocks among the most actively traded by share volume.", question: "What is driving participation? Check dollar liquidity and volume against its own history before calling it unusual." },
];

export function filterExplorer(candidates: ExplorerCandidate[], options: {
  lens: ExplorerLens; query: string; minPrice: number; includeUnknown: boolean; savedOnly: boolean; watched: Set<string>;
}) {
  return candidates.filter((row) =>
    (options.lens === "all" || row.sources.includes(options.lens)) &&
    row.symbol.includes(options.query.trim().toUpperCase()) &&
    (row.price === null ? options.includeUnknown : row.price >= options.minPrice) &&
    (!options.savedOnly || options.watched.has(row.symbol))
  );
}

export const sourceLabel = (source: string) => ({ gainer: "Top gainer", loser: "Top decliner", most_active: "High share volume" }[source] ?? source);
