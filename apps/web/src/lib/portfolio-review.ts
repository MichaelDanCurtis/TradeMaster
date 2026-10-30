export type PortfolioRiskPosture = "capital-preservation" | "balanced" | "growth" | "high-risk";

export type PortfolioReviewInput = {
  constraints: string;
  goals: string;
  horizon: string;
  liquidityNeeds: string;
  riskPosture: PortfolioRiskPosture;
  sectors: string;
  symbol: string;
};

export type PortfolioReviewTrack = {
  team: string;
  focus: string;
  output: string;
};

export type PortfolioResearchCandidate = {
  symbol: string;
  reason: string;
};

export type PortfolioReviewThesis = {
  title: string;
  summary: string;
  missingProviderFacts: string[];
  tracks: PortfolioReviewTrack[];
  researchCandidates: PortfolioResearchCandidate[];
  nextSteps: string[];
};

const riskLabels: Record<PortfolioRiskPosture, string> = {
  "capital-preservation": "Capital preservation",
  balanced: "Balanced",
  growth: "Growth",
  "high-risk": "High-risk"
};

const sectorCandidateMap: Array<{ keywords: string[]; symbols: string[]; label: string }> = [
  { keywords: ["ai", "semiconductor", "semiconductors", "chip", "chips"], symbols: ["NVDA", "AMD", "AVGO", "SMH"], label: "AI and semiconductor exposure" },
  { keywords: ["health", "healthcare", "pharma", "pharmaceutical", "biotech"], symbols: ["LLY", "NVO", "XLV"], label: "healthcare and pharmaceutical exposure" },
  { keywords: ["index", "core", "broad", "market"], symbols: ["SPY", "QQQ", "VTI"], label: "core index exposure" },
  { keywords: ["energy", "oil", "gas"], symbols: ["XLE", "XOM"], label: "energy exposure" },
  { keywords: ["defense", "aerospace"], symbols: ["LMT", "RTX", "ITA"], label: "defense and aerospace exposure" },
  { keywords: ["cash", "treasury", "bonds", "income"], symbols: ["SGOV", "BIL", "TLT"], label: "cash and bond exposure" }
];

export function buildPortfolioReviewThesis(input: PortfolioReviewInput): PortfolioReviewThesis {
  const goals = cleanSentence(input.goals, "No material goals entered yet.");
  const sectors = cleanSentence(input.sectors, "No sector focus entered yet.");
  const constraints = cleanSentence(input.constraints, "No constraints entered yet.");
  const liquidityNeeds = cleanSentence(input.liquidityNeeds, "No liquidity needs entered yet.");
  const riskLabel = riskLabels[input.riskPosture];
  const researchCandidates = buildResearchCandidates(input.symbol, input.sectors);
  const missingProviderFacts = [
    "Current holdings, cost basis, and account allocation from a portfolio provider.",
    "Cash, liabilities, recurring obligations, and funding runway from Plaid or equivalent banking data.",
    "Tax lots, realized gains, wash-sale exposure, and entity ownership constraints from tax records.",
    "Broker authority, available buying power, and paper/live account routing from the brokerage provider."
  ];

  return {
    title: `${riskLabel} portfolio review for ${input.horizon}`,
    summary: [
      `${riskLabel} posture over ${input.horizon}.`,
      `Primary goals: ${goals}`,
      `Sector focus: ${sectors}`,
      `Constraints: ${constraints}`,
      `Liquidity posture: ${liquidityNeeds}`,
      "This is a briefing-room advisory thesis; provider-backed holdings and cash data are still required before it becomes an allocation recommendation."
    ].join(" "),
    missingProviderFacts,
    tracks: [
      {
        team: "Goals team",
        focus: "Translate material goals into target windows, funding requirements, and acceptable drawdown.",
        output: `Goal review anchored on ${input.horizon}.`
      },
      {
        team: "Portfolio counselor",
        focus: "Turn goals, cash runway, and risk posture into an investable allocation stance.",
        output: `${riskLabel} posture with provider facts required before sizing.`
      },
      {
        team: "Sector desk",
        focus: "Identify sectors and research candidates that match the stated thesis.",
        output: researchCandidates.map((candidate) => candidate.symbol).join(", ")
      },
      {
        team: "Risk and tax desk",
        focus: "Review concentration, liquidity, realized gains, entity ownership, and liability impact.",
        output: "Blocked on provider-backed holdings, banking, and tax-lot data."
      }
    ],
    researchCandidates,
    nextSteps: [
      "Connect portfolio and banking providers before treating this as an allocation recommendation.",
      "Send the highest-priority candidates to the Research Office for TradingAgents research.",
      "Convert accepted research into a brokerage-floor order thesis only after compliance and funding review."
    ]
  };
}

function buildResearchCandidates(symbol: string, sectorFocus: string): PortfolioResearchCandidate[] {
  const normalizedSymbol = symbol.trim().toUpperCase();
  const sectorText = sectorFocus.toLowerCase();
  const symbols = new Map<string, string>();

  if (normalizedSymbol.length > 0) {
    symbols.set(normalizedSymbol, "Research candidate from the active watchlist focus.");
  }

  for (const group of sectorCandidateMap) {
    if (group.keywords.some((keyword) => sectorText.includes(keyword))) {
      for (const candidateSymbol of group.symbols) {
        symbols.set(candidateSymbol, `Research candidate for ${group.label}.`);
      }
    }
  }

  if (symbols.size === 0) {
    symbols.set("SPY", "Research candidate for broad-market baseline comparison.");
  }

  return Array.from(symbols.entries()).map(([candidateSymbol, reason]) => ({
    symbol: candidateSymbol,
    reason
  }));
}

function cleanSentence(value: string, fallback: string): string {
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : fallback;
}
