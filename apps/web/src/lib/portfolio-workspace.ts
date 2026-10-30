export type PortfolioWorkspaceInput = {
  symbol: string;
};

export type PortfolioWorkspaceCoverage = {
  provider: string;
  scope: string;
  status: "connected-required" | "provider-required" | "review-required";
  note: string;
};

export type PortfolioWorkspaceMandate = {
  provider: string;
  owner: "Human managed" | "High-risk AI paper harness";
  lane: string;
  guardrail: string;
};

export type PortfolioWorkspaceDiscussionItem = {
  topic: string;
  prompt: string;
  providerFactsNeeded: string[];
};

export type PortfolioWorkspaceAction = {
  label: string;
  destination: "Research Office" | "Brokerage Floor" | "Provider Setup";
  rationale: string;
};

export type CurrentPortfolioWorkspace = {
  symbol: string;
  title: "Current Portfolio";
  accountCoverage: PortfolioWorkspaceCoverage[];
  holdingsCoverage: PortfolioWorkspaceCoverage[];
  missingProviderFacts: string[];
  mandates: PortfolioWorkspaceMandate[];
  allocationDiscussionItems: PortfolioWorkspaceDiscussionItem[];
  recommendedNextActions: PortfolioWorkspaceAction[];
};

export function buildCurrentPortfolioWorkspace(input: PortfolioWorkspaceInput): CurrentPortfolioWorkspace {
  const symbol = normalizePortfolioSymbol(input.symbol);

  return {
    symbol,
    title: "Current Portfolio",
    accountCoverage: [
      {
        provider: "Webull",
        scope: "Human-managed brokerage account",
        status: "provider-required",
        note: "Use provider data to confirm account authority, cash access, restrictions, and the human-managed investment lane."
      },
      {
        provider: "Alpaca",
        scope: "Paper trading and high-risk AI harness",
        status: "provider-required",
        note: "Use provider data to confirm paper/live mode, buying power, permissions, and whether AI actions remain approval-gated."
      }
    ],
    holdingsCoverage: [
      {
        provider: "Portfolio provider",
        scope: "Positions",
        status: "provider-required",
        note: "Needs provider-backed symbols, quantities, market values, cost basis, and tax-lot context before any allocation claim."
      },
      {
        provider: "Portfolio provider",
        scope: "Cash and unsettled activity",
        status: "provider-required",
        note: "Needs provider-backed cash, unsettled funds, open orders, deposits, withdrawals, and margin state."
      },
      {
        provider: "Research Office",
        scope: `${symbol} concentration review`,
        status: "review-required",
        note: "Use research coverage to decide whether the active symbol belongs in the human-managed lane, AI paper lane, or watch-only queue."
      }
    ],
    missingProviderFacts: [
      "Provider-backed cash, buying power, and account permissions.",
      "Provider-backed positions, quantities, market values, and cost basis.",
      "Provider-backed open orders, unsettled activity, deposits, withdrawals, and margin state.",
      "Provider-backed tax lots, realized gains, wash-sale exposure, and account registration details.",
      "Provider-backed confirmation of Webull human-management boundaries and Alpaca paper/live routing."
    ],
    mandates: [
      {
        provider: "Webull",
        owner: "Human managed",
        lane: "Primary current-portfolio review lane for real brokerage exposure.",
        guardrail: "Do not let AI generate or stage live orders without explicit human review and brokerage-floor handoff."
      },
      {
        provider: "Alpaca",
        owner: "High-risk AI paper harness",
        lane: "AI strategy experimentation, paper execution, and high-risk thesis rehearsal.",
        guardrail: "Keep the AI harness paper-first and approval-gated until provider permissions, policy, and risk review are complete."
      }
    ],
    allocationDiscussionItems: [
      {
        topic: "Account split",
        prompt: "Decide which holdings belong in the Webull human-managed lane versus the Alpaca AI paper harness.",
        providerFactsNeeded: ["Account list", "Paper/live mode", "Broker permissions"]
      },
      {
        topic: "Concentration and thesis drift",
        prompt: `Review whether ${symbol} is a concentrated position, a research candidate, or only a watchlist focus.`,
        providerFactsNeeded: ["Position weights", "Cost basis", "Research conviction"]
      },
      {
        topic: "Liquidity and risk capacity",
        prompt: "Separate deployable cash from emergency liquidity, unsettled funds, and high-risk experimentation capital.",
        providerFactsNeeded: ["Cash", "Unsettled funds", "Margin state"]
      },
      {
        topic: "Tax and order readiness",
        prompt: "Identify tax-lot and open-order blockers before any brokerage-floor order thesis.",
        providerFactsNeeded: ["Tax lots", "Realized gains", "Open orders"]
      }
    ],
    recommendedNextActions: [
      {
        label: `Research ${symbol} portfolio fit`,
        destination: "Research Office",
        rationale: "Build a provider-aware thesis before treating the active symbol as an allocation decision."
      },
      {
        label: "Review provider connection gaps",
        destination: "Provider Setup",
        rationale: "Resolve missing account, holding, permission, tax-lot, and paper/live routing facts."
      },
      {
        label: "Prepare approval-gated brokerage handoff",
        destination: "Brokerage Floor",
        rationale: "Only convert reviewed allocation decisions into brokerage-floor action after provider facts are present."
      }
    ]
  };
}

function normalizePortfolioSymbol(symbol: string): string {
  const normalized = symbol.trim().toUpperCase();
  return normalized.length > 0 ? normalized : "PORTFOLIO";
}
