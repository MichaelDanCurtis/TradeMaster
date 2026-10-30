import type { AgentTrigger, ProviderRoleKey } from "./types.ts";

export type ProviderReadinessStatus = "red" | "yellow" | "green";
export type ProviderFactState = "available" | "not_configured" | "unavailable";
export type ProviderReadinessTarget = "portfolio" | "research" | "market" | "transactions" | "executionAgents";

export type ProviderFactKey =
  | "brokerPaperAccount"
  | "llmResearch"
  | "marketData"
  | "observability"
  | "portfolioFacts"
  | "safetyCompliance";

export type ProviderFactDefinition = {
  key: ProviderFactKey;
  label: string;
  roleKey: ProviderRoleKey;
  requiredEvidence: string;
};

export type ProviderFactAvailability = {
  state: ProviderFactState;
  providerId?: string;
  detail?: string;
};

export type ProviderFactSnapshot = Partial<Record<ProviderFactKey, ProviderFactAvailability>>;

export type MissingProviderFact = {
  key: ProviderFactKey;
  label: string;
  roleKey: ProviderRoleKey;
  state: Exclude<ProviderFactState, "available">;
  message: string;
  providerId?: string;
  detail?: string;
  suggestedSettingsRoute: string;
};

export type ProviderReadiness = {
  target: ProviderReadinessTarget;
  targetLabel: string;
  status: ProviderReadinessStatus;
  requiredFacts: ProviderFactDefinition[];
  missingFacts: MissingProviderFact[];
  suggestedSettingsRoute: string;
  summary: string;
};

export type ScheduledAgentCheckKey =
  | "marketOpenReport"
  | "hourlySentimentCheck"
  | "priceTrigger"
  | "volumeTrigger"
  | "riskTrigger"
  | "complianceTrigger";

export type ScheduledAgentCheck = {
  key: ScheduledAgentCheckKey;
  label: string;
  cadence: string;
  triggerTypes: AgentTrigger["trigger_type"][];
  targetAgent: string;
  readinessTarget: ProviderReadinessTarget;
  readinessStatus: ProviderReadinessStatus;
  executionBlocked: boolean;
  blockerSummary: string;
  detail: string;
};

export type ScheduledAgentMonitoring = {
  status: "ready" | "blocked";
  activeChecks: number;
  blockedChecks: number;
  checks: ScheduledAgentCheck[];
  summary: string;
};

const SETTINGS_PROVIDER_ROUTE = "/settings/providers";

const PROVIDER_FACTS: Record<ProviderFactKey, ProviderFactDefinition> = {
  brokerPaperAccount: {
    key: "brokerPaperAccount",
    label: "Broker paper account",
    roleKey: "broker",
    requiredEvidence: "Paper account identity, broker permissions, buying power, and venue capabilities."
  },
  llmResearch: {
    key: "llmResearch",
    label: "LLM research",
    roleKey: "research_llm",
    requiredEvidence: "Configured research model, provider health, model identity, and fallback expectations."
  },
  marketData: {
    key: "marketData",
    label: "Market data",
    roleKey: "market_data",
    requiredEvidence: "Quote, bar, spread, market-hours, and liquidity facts from a market data provider."
  },
  observability: {
    key: "observability",
    label: "Observability",
    roleKey: "observability",
    requiredEvidence: "Trace export, run identifiers, provider health, and audit visibility."
  },
  portfolioFacts: {
    key: "portfolioFacts",
    label: "Portfolio facts",
    roleKey: "portfolio",
    requiredEvidence: "Holdings, cash, buying power, open orders, tax lots, and account registration facts."
  },
  safetyCompliance: {
    key: "safetyCompliance",
    label: "Safety and compliance",
    roleKey: "safety",
    requiredEvidence: "Room policy, approval ledger, restricted-list, circuit-breaker, and compliance disposition facts."
  }
};

const TARGET_REQUIREMENTS: Record<
  ProviderReadinessTarget,
  {
    label: string;
    facts: ProviderFactKey[];
  }
> = {
  executionAgents: {
    label: "Execution Agents",
    facts: ["brokerPaperAccount", "marketData", "portfolioFacts", "observability", "safetyCompliance"]
  },
  market: {
    label: "Brokerage Floor",
    facts: ["brokerPaperAccount", "marketData", "portfolioFacts", "observability", "safetyCompliance"]
  },
  portfolio: {
    label: "Current Portfolio",
    facts: ["portfolioFacts", "marketData", "brokerPaperAccount", "safetyCompliance"]
  },
  research: {
    label: "Research Office",
    facts: ["llmResearch", "marketData", "observability", "safetyCompliance"]
  },
  transactions: {
    label: "Operations & Private Office",
    facts: ["portfolioFacts", "observability", "safetyCompliance"]
  }
};

const SCHEDULED_AGENT_CHECKS: Array<
  Omit<ScheduledAgentCheck, "readinessStatus" | "executionBlocked" | "blockerSummary">
> = [
  {
    cadence: "Market open",
    detail: "Scheduled market-open reports can wake research review after market data, trace, model, and policy facts are ready.",
    key: "marketOpenReport",
    label: "Market-open report",
    readinessTarget: "research",
    targetAgent: "scheduled-perception-agent",
    triggerTypes: ["time", "report_event"]
  },
  {
    cadence: "Hourly",
    detail: "Hourly sentiment checks watch cheap perception signals before a research or broker handoff.",
    key: "hourlySentimentCheck",
    label: "Hourly sentiment check",
    readinessTarget: "research",
    targetAgent: "sentiment-perception-agent",
    triggerTypes: ["time", "sentiment_flip"]
  },
  {
    cadence: "Event",
    detail: "Price conditions are monitored as trigger-harness facts, not as order instructions.",
    key: "priceTrigger",
    label: "Price trigger",
    readinessTarget: "executionAgents",
    targetAgent: "execution-risk-agent",
    triggerTypes: ["price"]
  },
  {
    cadence: "Event",
    detail: "Volume changes can wake liquidity review while brokerage execution stays approval-gated.",
    key: "volumeTrigger",
    label: "Volume trigger",
    readinessTarget: "executionAgents",
    targetAgent: "liquidity-monitor-agent",
    triggerTypes: ["volume"]
  },
  {
    cadence: "Event",
    detail: "Risk thresholds can wake paper-route review only after required provider facts are present.",
    key: "riskTrigger",
    label: "Risk trigger",
    readinessTarget: "executionAgents",
    targetAgent: "execution-risk-agent",
    triggerTypes: ["risk_threshold"]
  },
  {
    cadence: "Event",
    detail: "Compliance flags wake private review and must keep execution blocked until safety facts are ready.",
    key: "complianceTrigger",
    label: "Compliance trigger",
    readinessTarget: "executionAgents",
    targetAgent: "compliance-monitor-agent",
    triggerTypes: ["compliance_flag"]
  }
];

export function requiredProviderFactsForTarget(target: ProviderReadinessTarget): ProviderFactDefinition[] {
  return TARGET_REQUIREMENTS[target].facts.map((factKey) => ({ ...PROVIDER_FACTS[factKey] }));
}

export function evaluateProviderReadiness(
  target: ProviderReadinessTarget,
  facts: ProviderFactSnapshot = {}
): ProviderReadiness {
  const targetRequirement = TARGET_REQUIREMENTS[target];
  const requiredFacts = requiredProviderFactsForTarget(target);
  const missingFacts = requiredFacts.flatMap((fact) => {
    const availability = facts[fact.key] ?? { state: "not_configured" };

    if (availability.state === "available") {
      return [];
    }

    return [buildMissingProviderFact(fact, availability)];
  });
  const status = summarizeReadinessStatus(missingFacts);
  const suggestedSettingsRoute = missingFacts[0]?.suggestedSettingsRoute ?? SETTINGS_PROVIDER_ROUTE;

  return {
    target,
    targetLabel: targetRequirement.label,
    status,
    requiredFacts,
    missingFacts,
    suggestedSettingsRoute,
    summary: buildSummary(targetRequirement.label, status, missingFacts)
  };
}

export function getScheduledAgentMonitoring(facts: ProviderFactSnapshot = {}): ScheduledAgentMonitoring {
  const readinessByTarget: Partial<Record<ProviderReadinessTarget, ProviderReadiness>> = {};
  const checks = SCHEDULED_AGENT_CHECKS.map((check) => {
    const readiness =
      readinessByTarget[check.readinessTarget] ?? evaluateProviderReadiness(check.readinessTarget, facts);
    readinessByTarget[check.readinessTarget] = readiness;
    const executionBlocked = readiness.status !== "green";

    return {
      ...check,
      blockerSummary: executionBlocked ? summarizeReadinessBlockers(readiness) : "Provider readiness available.",
      executionBlocked,
      readinessStatus: readiness.status
    };
  });
  const blockedChecks = checks.filter((check) => check.executionBlocked).length;

  return {
    activeChecks: checks.length,
    blockedChecks,
    checks,
    status: blockedChecks > 0 ? "blocked" : "ready",
    summary:
      blockedChecks > 0
        ? `Provider readiness blocks execution for ${blockedChecks} active scheduled/triggered checks.`
        : "All active scheduled/triggered checks have provider readiness."
  };
}

function buildMissingProviderFact(
  fact: ProviderFactDefinition,
  availability: ProviderFactAvailability
): MissingProviderFact {
  const state = availability.state === "unavailable" ? "unavailable" : "not_configured";

  return {
    detail: availability.detail,
    key: fact.key,
    label: fact.label,
    message: buildMissingFactMessage(fact, { ...availability, state }),
    providerId: availability.providerId,
    roleKey: fact.roleKey,
    state,
    suggestedSettingsRoute: settingsRouteForRole(fact.roleKey)
  };
}

function buildMissingFactMessage(
  fact: ProviderFactDefinition,
  availability: ProviderFactAvailability & { state: Exclude<ProviderFactState, "available"> }
): string {
  if (availability.state === "unavailable") {
    const providerContext = availability.providerId ? ` from ${availability.providerId}` : "";
    const detail = availability.detail ? ` ${availability.detail}` : "";
    return `${fact.label} is unavailable${providerContext}.${detail} Required evidence: ${fact.requiredEvidence}`;
  }

  return `${fact.label} is not configured. Required evidence: ${fact.requiredEvidence}`;
}

function summarizeReadinessStatus(missingFacts: MissingProviderFact[]): ProviderReadinessStatus {
  if (missingFacts.length === 0) {
    return "green";
  }

  return missingFacts.some((fact) => fact.state === "unavailable") ? "red" : "yellow";
}

function buildSummary(
  targetLabel: string,
  status: ProviderReadinessStatus,
  missingFacts: MissingProviderFact[]
): string {
  if (status === "green") {
    return `${targetLabel} has all required provider facts available.`;
  }

  const missingLabels = missingFacts.map((fact) => fact.label).join(", ");
  const unavailableCount = missingFacts.filter((fact) => fact.state === "unavailable").length;
  const unavailablePrefix = unavailableCount > 0 ? `${unavailableCount} unavailable; ` : "";

  return `${targetLabel} provider facts are still required: ${unavailablePrefix}${missingLabels}.`;
}

function summarizeReadinessBlockers(readiness: ProviderReadiness): string {
  const missingLabels = readiness.missingFacts.map((fact) => fact.label).join(", ");
  return missingLabels
    ? `${readiness.targetLabel}: ${missingLabels}`
    : `${readiness.targetLabel}: provider readiness available`;
}

function settingsRouteForRole(roleKey: ProviderRoleKey): string {
  return `${SETTINGS_PROVIDER_ROUTE}?role=${roleKey}`;
}
