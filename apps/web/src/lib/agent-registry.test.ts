import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { getAgentActionPlan, getTradingAgentsByTeam, TRADING_AGENT_REGISTRY } from "./agent-registry.ts";

describe("trading agent registry", () => {
  it("exposes the real TradingAgents research hierarchy", () => {
    const names = TRADING_AGENT_REGISTRY.map((agent) => agent.name);

    assert.ok(names.includes("Market Analyst"));
    assert.ok(names.includes("Research Manager"));
    assert.ok(names.includes("Portfolio Manager"));
    assert.ok(names.includes("Trader"));
    assert.ok(names.includes("Bull Researcher"));
    assert.ok(names.includes("Bear Researcher"));
  });

  it("distinguishes active UI runner roles from full framework roles", () => {
    const activeAgents = TRADING_AGENT_REGISTRY.filter((agent) => agent.runtimeStatus === "active");
    const frameworkAgents = TRADING_AGENT_REGISTRY.filter((agent) => agent.runtimeStatus === "framework");

    assert.ok(activeAgents.length > 0);
    assert.ok(frameworkAgents.length > 0);
    assert.ok(getTradingAgentsByTeam("analysts").every((agent) => agent.teamId === "analysts"));
  });

  it("only marks currently wired agents as directly runnable", () => {
    const marketAnalyst = TRADING_AGENT_REGISTRY.find((agent) => agent.id === "market-analyst");
    const trader = TRADING_AGENT_REGISTRY.find((agent) => agent.id === "trader");
    const brokerGate = TRADING_AGENT_REGISTRY.find((agent) => agent.id === "broker-gate");

    assert.equal(marketAnalyst ? getAgentActionPlan(marketAnalyst).canRun : false, true);
    assert.equal(marketAnalyst ? getAgentActionPlan(marketAnalyst).primaryAction : "", "Run research");
    assert.equal(trader ? getAgentActionPlan(trader).canRun : true, false);
    assert.equal(trader ? getAgentActionPlan(trader).primaryAction : "", "Open builder");
    assert.equal(brokerGate ? getAgentActionPlan(brokerGate).primaryAction : "", "Preview execution");
  });

  it("separates research agents from deterministic execution agents", () => {
    const researchAgents = TRADING_AGENT_REGISTRY.filter((agent) => agent.agentClass === "research");
    const executionAgents = TRADING_AGENT_REGISTRY.filter((agent) => agent.agentClass === "execution");

    assert.ok(researchAgents.some((agent) => agent.id === "market-analyst"));
    assert.ok(executionAgents.some((agent) => agent.id === "alpaca-execution-agent"));
    assert.ok(executionAgents.every((agent) => agent.llmMode === "symbolic" || agent.llmMode === "deterministic"));
  });

  it("keeps registry copy away from live-trade claims", () => {
    const registryCopy = TRADING_AGENT_REGISTRY.map((agent) =>
      [agent.name, agent.purpose, agent.safetyProfile, agent.framework].join(" ")
    ).join("\n");

    assert.doesNotMatch(registryCopy, /live[- ]?trade/i);
    assert.doesNotMatch(registryCopy, /live broker/i);
    assert.doesNotMatch(registryCopy, /live-preview/i);
    assert.doesNotMatch(registryCopy, /submit trade/i);
  });
});
