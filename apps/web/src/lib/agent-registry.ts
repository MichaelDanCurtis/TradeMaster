export type AgentRuntimeStatus = "active" | "framework" | "planned";
export type AgentTeamId = "analysts" | "research" | "risk" | "execution";
export type AgentClass = "research" | "execution";
export type AgentLlmMode = "creative" | "structured" | "deterministic" | "symbolic";

export type TradingAgentDescriptor = {
  id: string;
  name: string;
  teamId: AgentTeamId;
  agentClass: AgentClass;
  llmMode: AgentLlmMode;
  runtimeStatus: AgentRuntimeStatus;
  purpose: string;
  framework: string;
  safetyProfile: string;
  inputs: string[];
  outputs: string[];
};

export type AgentActionPlan = {
  canRun: boolean;
  primaryAction: "Run research" | "Open builder" | "Preview execution";
  helperText: string;
};

export const TRADING_AGENT_REGISTRY: TradingAgentDescriptor[] = [
  {
    id: "market-analyst",
    name: "Market Analyst",
    teamId: "analysts",
    agentClass: "research",
    llmMode: "structured",
    runtimeStatus: "active",
    framework: "TradingAgents LangGraph node",
    safetyProfile: "Research only; no broker authority.",
    purpose: "Builds the technical and OHLCV market context for the selected ticker.",
    inputs: ["Alpaca bars", "VWAP", "volume", "price action"],
    outputs: ["market report"]
  },
  {
    id: "news-analyst",
    name: "News Analyst",
    teamId: "analysts",
    agentClass: "research",
    llmMode: "creative",
    runtimeStatus: "active",
    framework: "TradingAgents LangGraph node",
    safetyProfile: "Research only; hallucination risk is acceptable because it cannot execute trades.",
    purpose: "Prepares the headline, filing, and macro event context for synthesis.",
    inputs: ["news adapter", "filings", "macro events"],
    outputs: ["news report"]
  },
  {
    id: "social-analyst",
    name: "Social Analyst",
    teamId: "analysts",
    agentClass: "research",
    llmMode: "creative",
    runtimeStatus: "active",
    framework: "TradingAgents LangGraph node",
    safetyProfile: "Research only; sentiment is advisory input.",
    purpose: "Summarizes sentiment and attention signals that can affect conviction.",
    inputs: ["sentiment feeds", "attention signals"],
    outputs: ["sentiment report"]
  },
  {
    id: "fundamentals-analyst",
    name: "Fundamentals Analyst",
    teamId: "analysts",
    agentClass: "research",
    llmMode: "structured",
    runtimeStatus: "active",
    framework: "TradingAgents LangGraph node",
    safetyProfile: "Research only; no broker authority.",
    purpose: "Frames financial quality, valuation, and business context.",
    inputs: ["fundamentals data", "company context"],
    outputs: ["fundamentals report"]
  },
  {
    id: "bull-researcher",
    name: "Bull Researcher",
    teamId: "research",
    agentClass: "research",
    llmMode: "creative",
    runtimeStatus: "framework",
    framework: "TradingAgents debate node",
    safetyProfile: "Research only; used to challenge bearish assumptions.",
    purpose: "Argues the constructive case from the analyst packet in the full TradingAgents graph.",
    inputs: ["analyst reports", "bear counterpoints"],
    outputs: ["bull thesis"]
  },
  {
    id: "bear-researcher",
    name: "Bear Researcher",
    teamId: "research",
    agentClass: "research",
    llmMode: "creative",
    runtimeStatus: "framework",
    framework: "TradingAgents debate node",
    safetyProfile: "Research only; used to challenge bullish assumptions.",
    purpose: "Argues the downside case from the analyst packet in the full TradingAgents graph.",
    inputs: ["analyst reports", "bull counterpoints"],
    outputs: ["bear thesis"]
  },
  {
    id: "research-manager",
    name: "Research Manager",
    teamId: "research",
    agentClass: "research",
    llmMode: "structured",
    runtimeStatus: "active",
    framework: "TradingAgents structured-output node",
    safetyProfile: "Research synthesis only; hands off to execution review.",
    purpose: "Synthesizes analyst packets into a structured stance for the portfolio decision.",
    inputs: ["market report", "news report", "sentiment report", "fundamentals report"],
    outputs: ["investment stance"]
  },
  {
    id: "trader",
    name: "Trader",
    teamId: "execution",
    agentClass: "research",
    llmMode: "structured",
    runtimeStatus: "framework",
    framework: "TradingAgents structured-output node",
    safetyProfile: "Proposal only until deterministic execution agents approve constraints.",
    purpose: "Translates the research plan into a transaction proposal in the full graph.",
    inputs: ["research plan", "instrument context"],
    outputs: ["transaction proposal"]
  },
  {
    id: "risk-manager",
    name: "Risk Manager",
    teamId: "risk",
    agentClass: "execution",
    llmMode: "symbolic",
    runtimeStatus: "framework",
    framework: "TradingAgents risk node plus planned PyReason policy layer",
    safetyProfile: "Must enforce sizing, drawdown, volatility, and halt rules before execution.",
    purpose: "Reviews downside, sizing, liquidity, volatility, and mandate risk before execution.",
    inputs: ["trader proposal", "research plan", "portfolio constraints"],
    outputs: ["risk debate"]
  },
  {
    id: "portfolio-manager",
    name: "Portfolio Manager",
    teamId: "execution",
    agentClass: "execution",
    llmMode: "deterministic",
    runtimeStatus: "active",
    framework: "TradingAgents structured-output node",
    safetyProfile: "Approval-gated final decision; broker submission is outside this workspace.",
    purpose: "Creates the final advisory decision and keeps broker actions approval-gated.",
    inputs: ["research stance", "risk notes"],
    outputs: ["decision", "paper order intent"]
  },
  {
    id: "broker-gate",
    name: "Broker Gate",
    teamId: "execution",
    agentClass: "execution",
    llmMode: "deterministic",
    runtimeStatus: "active",
    framework: "Wealth Agents broker adapter boundary",
    safetyProfile: "Paper preview only until human approval and broker policy allow action.",
    purpose: "Previews paper orders and blocks submission until a human approves the trade ticket.",
    inputs: ["decision", "broker configuration"],
    outputs: ["paper order preview"]
  },
  {
    id: "alpaca-execution-agent",
    name: "Alpaca Execution Agent",
    teamId: "execution",
    agentClass: "execution",
    llmMode: "deterministic",
    runtimeStatus: "planned",
    framework: "Alpaca Python SDK adapter",
    safetyProfile: "Execution adapter; requires PyReason circuit breakers, paper mode, and explicit approval policy.",
    purpose: "Runs deterministic paper-preview order flows through Alpaca after policy checks pass.",
    inputs: ["approved order intent", "Alpaca account state", "circuit-breaker verdict"],
    outputs: ["paper order", "broker order status", "execution audit"]
  },
  {
    id: "pyreason-circuit-breaker-agent",
    name: "PyReason Circuit Breaker",
    teamId: "risk",
    agentClass: "execution",
    llmMode: "symbolic",
    runtimeStatus: "planned",
    framework: "PyReason temporal first-order logic",
    safetyProfile: "Hard temporal halt rules; can stop trading regardless of neural or LLM recommendation.",
    purpose: "Applies temporal symbolic rules for crash, volatility, drawdown, liquidity, and exposure limits.",
    inputs: ["market stress facts", "position state", "time-windowed volatility", "drawdown facts"],
    outputs: ["allow trading", "reduce risk", "halt trading", "explainable proof trace"]
  }
];

export const AGENT_TEAM_LABELS: Record<AgentTeamId, string> = {
  analysts: "Analyst Team",
  execution: "Execution Team",
  research: "Research Team",
  risk: "Risk Team"
};

export function getTradingAgentsByTeam(teamId: AgentTeamId): TradingAgentDescriptor[] {
  return TRADING_AGENT_REGISTRY.filter((agent) => agent.teamId === teamId);
}

export function getAgentActionPlan(agent: TradingAgentDescriptor): AgentActionPlan {
  if (agent.runtimeStatus === "active") {
    if (agent.agentClass === "execution") {
      return {
        canRun: true,
        primaryAction: "Preview execution",
        helperText: "This role can queue an approval-gated paper execution review. It does not submit broker orders."
      };
    }

    return {
      canRun: true,
      primaryAction: "Run research",
      helperText: "This role is wired into the current UI runner. Running it starts the approval-gated research pipeline."
    };
  }

  return {
    canRun: false,
    primaryAction: "Open builder",
    helperText: "This role exists in the full TradingAgents framework, but custom graph execution is not wired yet."
  };
}
