export type FundingAllocationTrackType =
  | "cash-source"
  | "liabilities"
  | "tax-questions"
  | "mandate-fit"
  | "compliance-gate"
  | "provider-gaps";

export type FundingAllocationInput = {
  symbol: string;
  notional?: number;
};

export type FundingAllocationTrack = {
  type: FundingAllocationTrackType;
  title: string;
  focus: string;
  finding: string;
  requiredFacts: string[];
};

export type FundingAllocationReview = {
  title: string;
  symbol: string;
  notionalLabel: string;
  summary: string;
  missingProviderFacts: string[];
  tracks: FundingAllocationTrack[];
  approvalNextSteps: string[];
};

export function buildFundingAllocationReview(input: FundingAllocationInput): FundingAllocationReview {
  const symbol = normalizeSymbol(input.symbol);
  const notionalLabel = formatNotional(input.notional);
  const missingProviderFacts = [
    "Verified cash balances, account ownership, and cash source from Plaid or another connected banking provider.",
    "Current liabilities, debt service, recurring obligations, and near-term liquidity demands from banking or credit data.",
    "Tax lots, realized gain exposure, entity ownership, wash-sale constraints, and estimated tax reserves from tax records.",
    "Brokerage buying power, margin status, mandate restrictions, and execution authority from the broker or custodian.",
    "Compliance attestations, sanctions/KYC status, restricted-list checks, and approval ledger evidence from the compliance system."
  ];

  return {
    title: `Funding Allocation Review for ${symbol}`,
    symbol,
    notionalLabel,
    summary: [
      `Private-office review for ${symbol}${input.notional ? ` at ${notionalLabel}` : ""}.`,
      "This review identifies what Operations and Private Office must confirm before broker execution.",
      "It does not include live Plaid, banking, brokerage, or tax facts until those providers are connected and verified."
    ].join(" "),
    missingProviderFacts,
    tracks: [
      {
        type: "cash-source",
        title: "Funding source",
        focus: "Confirm where cash comes from, who owns it, and whether it can be moved into the trade program.",
        finding: "Funding source is not approved because provider-backed cash facts are missing.",
        requiredFacts: [
          "Verified available cash by account.",
          "Named source of funds and account ownership.",
          "Transfer limits, settlement timing, and expected funding runway."
        ]
      },
      {
        type: "liabilities",
        title: "Liability checks",
        focus: "Check whether debt service, recurring obligations, or liquidity promises conflict with the proposed allocation.",
        finding: "Liability impact is unresolved without connected banking, credit, or obligation data.",
        requiredFacts: [
          "Outstanding liabilities and required payments.",
          "Recurring obligations and upcoming cash calls.",
          "Minimum liquidity reserve after the proposed allocation."
        ]
      },
      {
        type: "tax-questions",
        title: "Tax questions",
        focus: "Surface tax-lot, entity, realized gain, and reserve questions before capital is committed.",
        finding: "Tax posture is an open question because tax records are not present in this review.",
        requiredFacts: [
          "Tax lots and realized gains connected to funding assets.",
          "Entity ownership and beneficial-owner constraints.",
          "Estimated tax reserve required before execution."
        ]
      },
      {
        type: "mandate-fit",
        title: "Mandate fit",
        focus: "Confirm the proposed trade program matches the client mandate, risk posture, liquidity needs, and restrictions.",
        finding: "Mandate fit requires advisor and private-office confirmation before order routing.",
        requiredFacts: [
          "Approved mandate and investment policy constraints.",
          "Risk budget for the proposed notional.",
          "Any restricted sectors, issuers, or instruments."
        ]
      },
      {
        type: "compliance-gate",
        title: "Compliance gate",
        focus: "Hold execution until compliance approves source of funds, suitability, restricted-list status, and audit evidence.",
        finding: "Broker execution should remain blocked until compliance records an approval.",
        requiredFacts: [
          "KYC and sanctions status.",
          "Restricted-list and conflict checks.",
          "Approval ledger entry from an authorized reviewer."
        ]
      },
      {
        type: "provider-gaps",
        title: "Provider gaps",
        focus: "Make missing provider facts explicit so the review cannot be mistaken for live cash, tax, or broker data.",
        finding: "Plaid, banking, brokerage, tax, and compliance provider facts are absent.",
        requiredFacts: missingProviderFacts
      }
    ],
    approvalNextSteps: [
      "Collect provider-backed banking, liability, tax, broker, and compliance evidence.",
      "Have Private Office confirm source of funds, liquidity reserve, and mandate fit.",
      "Route to compliance for source-of-funds and suitability approval before any broker execution."
    ]
  };
}

export function getFundingAllocationTrack(
  review: FundingAllocationReview,
  type: FundingAllocationTrackType
): FundingAllocationTrack {
  const track = review.tracks.find((candidate) => candidate.type === type);

  if (!track) {
    throw new Error(`Funding allocation review is missing ${type} track.`);
  }

  return track;
}

function normalizeSymbol(symbol: string): string {
  const normalizedSymbol = symbol.trim().toUpperCase();
  return normalizedSymbol.length > 0 ? normalizedSymbol : "UNSPECIFIED";
}

function formatNotional(notional: number | undefined): string {
  if (typeof notional !== "number" || !Number.isFinite(notional) || notional <= 0) {
    return "Notional pending";
  }

  return new Intl.NumberFormat("en-US", {
    currency: "USD",
    maximumFractionDigits: 0,
    style: "currency"
  }).format(notional);
}
