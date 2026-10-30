export type ExecutionProgramId =
  | "staged_accumulation"
  | "bracket_order"
  | "trailing_stop"
  | "dca_ladder"
  | "rebalance"
  | "hedge"
  | "tax_loss_harvest";

export type ExecutionTriggerType =
  | "time"
  | "price"
  | "volume"
  | "sentiment_flip"
  | "report_event"
  | "risk_threshold"
  | "compliance_flag";

export type ExecutionProgramTemplate = {
  id: ExecutionProgramId;
  name: string;
  desk: string;
  objective: string;
  cadence: string;
  approvalRequired: boolean;
  paperOnly: boolean;
};

export type ExecutionProgramState = {
  approvalGate: "required";
  liveSubmissionEnabled: false;
  mode: "paper";
  status: "preview_ready";
};

export type ExecutionTriggerPoint = {
  type: ExecutionTriggerType;
  label: string;
  condition: string;
};

export type ExecutionProgramEvent = {
  phase: "preview_created" | "provider_fact_check" | "approval_required" | "paper_route" | "monitoring";
  summary: string;
};

export type ExecutionProgramPreview = {
  algorithm: ExecutionProgramTemplate;
  circuitBreakers: string[];
  expectedEvents: ExecutionProgramEvent[];
  missingProviderFacts: string[];
  state: ExecutionProgramState;
  symbol: string;
  triggerPoints: ExecutionTriggerPoint[];
};

export const executionProgramTemplates: ExecutionProgramTemplate[] = [
  {
    approvalRequired: true,
    cadence: "Four staged paper slices over the selected session window.",
    desk: "Brokerage floor",
    id: "staged_accumulation",
    name: "Staged accumulation",
    objective: "Accumulate exposure in deterministic increments while monitoring liquidity and policy gates.",
    paperOnly: true
  },
  {
    approvalRequired: true,
    cadence: "Entry preview plus paired paper take-profit and stop-loss brackets.",
    desk: "Brokerage floor",
    id: "bracket_order",
    name: "Bracket order",
    objective: "Model entry, upside exit, and downside protection before an operator approves any route.",
    paperOnly: true
  },
  {
    approvalRequired: true,
    cadence: "Paper stop anchor follows favorable price movement after preview creation.",
    desk: "Risk desk",
    id: "trailing_stop",
    name: "Trailing stop",
    objective: "Preview downside control that tightens only after price movement supports it.",
    paperOnly: true
  },
  {
    approvalRequired: true,
    cadence: "Equal notional paper checks across scheduled time buckets.",
    desk: "Portfolio desk",
    id: "dca_ladder",
    name: "DCA ladder",
    objective: "Spread paper entries across a ladder without reacting to discretionary impulses.",
    paperOnly: true
  },
  {
    approvalRequired: true,
    cadence: "Portfolio drift check followed by paper rebalance legs.",
    desk: "Portfolio desk",
    id: "rebalance",
    name: "Rebalance",
    objective: "Preview allocation drift corrections while preserving provider and compliance blockers.",
    paperOnly: true
  },
  {
    approvalRequired: true,
    cadence: "Paper hedge ratio check when exposure, volatility, or event risk crosses threshold.",
    desk: "Risk desk",
    id: "hedge",
    name: "Hedge",
    objective: "Model offsetting exposure before risk desk and operator approval.",
    paperOnly: true
  },
  {
    approvalRequired: true,
    cadence: "Tax-lot scan followed by paper replacement and wash-sale checks.",
    desk: "Tax desk",
    id: "tax_loss_harvest",
    name: "Tax-loss harvest",
    objective: "Preview loss capture candidates without assuming tax-lot authority is connected.",
    paperOnly: true
  }
];

const fallbackTemplate = executionProgramTemplates[0];

export function buildExecutionProgramPreview({
  algorithmId,
  symbol
}: {
  algorithmId: string;
  symbol: string;
}): ExecutionProgramPreview {
  const normalizedSymbol = normalizeSymbol(symbol);
  const algorithm = executionProgramTemplates.find((template) => template.id === algorithmId) ?? fallbackTemplate;

  return {
    algorithm,
    circuitBreakers: buildCircuitBreakers(normalizedSymbol, algorithm),
    expectedEvents: buildExpectedEvents(normalizedSymbol, algorithm),
    missingProviderFacts: buildMissingProviderFacts(algorithm),
    state: {
      approvalGate: "required",
      liveSubmissionEnabled: false,
      mode: "paper",
      status: "preview_ready"
    },
    symbol: normalizedSymbol,
    triggerPoints: buildTriggerPoints(normalizedSymbol, algorithm)
  };
}

function normalizeSymbol(symbol: string): string {
  const normalized = symbol.trim().toUpperCase();
  return normalized.length > 0 ? normalized : "WATCHLIST";
}

function buildTriggerPoints(symbol: string, algorithm: ExecutionProgramTemplate): ExecutionTriggerPoint[] {
  return [
    {
      condition: `${algorithm.cadence} The first paper checkpoint waits for the next allowed review window.`,
      label: "Review window opens",
      type: "time"
    },
    {
      condition: `${symbol} must remain inside the preview price band before any paper slice is marked eligible.`,
      label: "Price band",
      type: "price"
    },
    {
      condition: "Session volume must support the modeled notional without exceeding participation limits.",
      label: "Liquidity check",
      type: "volume"
    },
    {
      condition: "Research sentiment flipping against the thesis pauses the paper program for analyst review.",
      label: "Research sentiment flip",
      type: "sentiment_flip"
    },
    {
      condition: "Earnings, macro, or material report events move the preview into event-risk hold.",
      label: "Report event",
      type: "report_event"
    },
    {
      condition: "Portfolio exposure, drawdown, or volatility crossing desk limits blocks the next paper event.",
      label: "Risk threshold",
      type: "risk_threshold"
    },
    {
      condition: "Compliance flags require human disposition before the preview can continue.",
      label: "Compliance flag",
      type: "compliance_flag"
    }
  ];
}

function buildCircuitBreakers(symbol: string, algorithm: ExecutionProgramTemplate): string[] {
  return [
    `Kill-switch: stop the ${algorithm.name.toLowerCase()} paper program for ${symbol} if approval state changes.`,
    "Policy veto: halt when broker permissions, restricted-list status, or room policy fails.",
    "Provider stale data: pause if quote, position, buying-power, or tax-lot facts are unavailable.",
    "Risk limit: block follow-on events when exposure, concentration, or loss thresholds are breached."
  ];
}

function buildExpectedEvents(symbol: string, algorithm: ExecutionProgramTemplate): ExecutionProgramEvent[] {
  return [
    {
      phase: "preview_created",
      summary: "Preview created locally without broker submission."
    },
    {
      phase: "provider_fact_check",
      summary: `Check provider facts required to simulate ${algorithm.name.toLowerCase()} for ${symbol}.`
    },
    {
      phase: "approval_required",
      summary: "Operator approval is required before any paper route is considered active."
    },
    {
      phase: "paper_route",
      summary: "Approved events remain paper-only and do not submit live brokerage orders."
    },
    {
      phase: "monitoring",
      summary: "Trigger, circuit-breaker, and lifecycle state changes are recorded for inspection."
    }
  ];
}

function buildMissingProviderFacts(algorithm: ExecutionProgramTemplate): string[] {
  const algorithmSpecificFacts: Partial<Record<ExecutionProgramId, string>> = {
    bracket_order: "Broker-supported bracket semantics, stop type availability, and paper route validation.",
    dca_ladder: "Available cash schedule, recurring funding constraints, and paper buying-power projection.",
    hedge: "Portfolio beta, correlated hedge universe, option availability, and margin impact.",
    rebalance: "Target allocation, current holdings, unsettled activity, and drift tolerance.",
    staged_accumulation: "Session participation limit, average daily volume, and paper fill model.",
    tax_loss_harvest: "Tax lots, wash-sale windows, replacement universe, and realized gain budget.",
    trailing_stop: "Supported trailing stop units, reference price source, and paper stop update cadence."
  };

  return [
    "Broker paper-trading account ID and execution venue capabilities.",
    "Current quote, spread, liquidity, and market-hours state from the market data provider.",
    "Room policy approval ledger entry and compliance disposition.",
    algorithmSpecificFacts[algorithm.id] ?? "Algorithm-specific broker and risk facts."
  ];
}
