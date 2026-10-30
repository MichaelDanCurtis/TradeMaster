// Frontend mirror of tradingagents/graph/role_models.py.
//
// The resolution rules MUST match the Python resolver verbatim --
// override -> tier default -> fallback. If you change one side, change
// both, or the UI will display a model the graph won't actually use.

export const COORDINATOR_ROLES = new Set<string>([
  "research_manager",
  "trader",
  "portfolio_manager",
  "research_designer"
]);

export type RoleKey =
  | "market_analyst"
  | "social_analyst"
  | "news_analyst"
  | "fundamentals_analyst"
  | "bull_researcher"
  | "bear_researcher"
  | "research_manager"
  | "trader"
  | "aggressive_analyst"
  | "neutral_analyst"
  | "conservative_analyst"
  | "portfolio_manager"
  | "reflector"
  | "signal_processor"
  | "research_designer"
  | "research_extractor";

export const ALL_ROLES: readonly RoleKey[] = [
  "market_analyst",
  "social_analyst",
  "news_analyst",
  "fundamentals_analyst",
  "bull_researcher",
  "bear_researcher",
  "research_manager",
  "trader",
  "aggressive_analyst",
  "neutral_analyst",
  "conservative_analyst",
  "portfolio_manager",
  "reflector",
  "signal_processor",
  "research_designer",
  "research_extractor"
];

export const ROLE_LABELS: Record<RoleKey, string> = {
  market_analyst: "Market Analyst",
  social_analyst: "Social Analyst",
  news_analyst: "News Analyst",
  fundamentals_analyst: "Fundamentals Analyst",
  bull_researcher: "Bull Researcher",
  bear_researcher: "Bear Researcher",
  research_manager: "Research Manager",
  trader: "Trader",
  aggressive_analyst: "Aggressive Risk Analyst",
  neutral_analyst: "Neutral Risk Analyst",
  conservative_analyst: "Conservative Risk Analyst",
  portfolio_manager: "Portfolio Manager",
  reflector: "Reflector",
  signal_processor: "Signal Processor",
  research_designer: "Strategy Research Designer",
  research_extractor: "Research Evidence Extractor"
};

export type RoleModelsConfig = {
  coordinator?: string;
  agent?: string;
  overrides?: Record<string, string>;
};

export function resolveRoleModel(
  roleKey: string,
  roleModels: RoleModelsConfig | null | undefined,
  fallbackModel: string
): string {
  if (roleModels) {
    const overrides = roleModels.overrides ?? {};
    const override = overrides[roleKey];
    if (typeof override === "string" && override.length > 0) {
      return override;
    }
    const tier = COORDINATOR_ROLES.has(roleKey) ? "coordinator" : "agent";
    const tierDefault = roleModels[tier];
    if (typeof tierDefault === "string" && tierDefault.length > 0) {
      return tierDefault;
    }
  }
  return fallbackModel;
}
