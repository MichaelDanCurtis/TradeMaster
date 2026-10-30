import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  evaluateProviderReadiness,
  getScheduledAgentMonitoring,
  requiredProviderFactsForTarget,
  type ProviderFactSnapshot
} from "./provider-readiness.ts";

const availableFacts: ProviderFactSnapshot = {
  brokerPaperAccount: { state: "available", providerId: "alpaca-paper-broker" },
  llmResearch: { state: "available", providerId: "openai-llm" },
  marketData: { state: "available", providerId: "alpaca-market-data" },
  observability: { state: "available", providerId: "langfuse-observability" },
  portfolioFacts: { state: "available", providerId: "plaid-portfolio" },
  safetyCompliance: { state: "available", providerId: "policy-gateway" }
};

describe("provider readiness", () => {
  it("marks Current Portfolio red when portfolio and broker account facts are not connected", () => {
    const readiness = evaluateProviderReadiness("portfolio", {
      marketData: { state: "available", providerId: "alpaca-market-data" },
      portfolioFacts: { state: "unavailable", providerId: "plaid-portfolio", detail: "health check failed" },
      safetyCompliance: { state: "available", providerId: "policy-gateway" }
    });

    assert.equal(readiness.targetLabel, "Current Portfolio");
    assert.equal(readiness.status, "red");
    assert.equal(readiness.suggestedSettingsRoute, "/settings/providers?role=portfolio");
    assert.deepEqual(
      readiness.missingFacts.map((fact) => [fact.key, fact.state]),
      [
        ["portfolioFacts", "unavailable"],
        ["brokerPaperAccount", "not_configured"]
      ]
    );
    assert.match(readiness.missingFacts[0].message, /unavailable/i);
    assert.doesNotMatch(readiness.missingFacts[0].message, /connected/i);
  });

  it("marks Research Office yellow when only observability is pending", () => {
    const readiness = evaluateProviderReadiness("research", {
      llmResearch: { state: "available", providerId: "openai-llm" },
      marketData: { state: "available", providerId: "alpaca-market-data" },
      observability: { state: "not_configured" },
      safetyCompliance: { state: "available", providerId: "policy-gateway" }
    });

    assert.equal(readiness.targetLabel, "Research Office");
    assert.equal(readiness.status, "yellow");
    assert.equal(readiness.suggestedSettingsRoute, "/settings/providers?role=observability");
    assert.deepEqual(readiness.missingFacts.map((fact) => fact.key), ["observability"]);
    assert.match(readiness.summary, /provider facts are still required/i);
  });

  it("marks Brokerage Floor green only when broker, market, portfolio, safety, and trace facts are available", () => {
    const readiness = evaluateProviderReadiness("market", availableFacts);

    assert.equal(readiness.targetLabel, "Brokerage Floor");
    assert.equal(readiness.status, "green");
    assert.deepEqual(readiness.missingFacts, []);
    assert.equal(readiness.suggestedSettingsRoute, "/settings/providers");
  });

  it("keeps Operations & Private Office yellow when safety compliance is missing", () => {
    const readiness = evaluateProviderReadiness("transactions", {
      observability: { state: "available", providerId: "langfuse-observability" },
      portfolioFacts: { state: "available", providerId: "plaid-portfolio" },
      safetyCompliance: { state: "not_configured" }
    });

    assert.equal(readiness.targetLabel, "Operations & Private Office");
    assert.equal(readiness.status, "yellow");
    assert.deepEqual(readiness.missingFacts.map((fact) => fact.key), ["safetyCompliance"]);
    assert.equal(readiness.suggestedSettingsRoute, "/settings/providers?role=safety");
  });

  it("models Execution Agents as red when market data is explicitly unavailable", () => {
    const readiness = evaluateProviderReadiness("executionAgents", {
      brokerPaperAccount: { state: "available", providerId: "alpaca-paper-broker" },
      marketData: { state: "unavailable", providerId: "alpaca-market-data", detail: "quote endpoint timed out" },
      observability: { state: "available", providerId: "langfuse-observability" },
      portfolioFacts: { state: "available", providerId: "plaid-portfolio" },
      safetyCompliance: { state: "available", providerId: "policy-gateway" }
    });

    assert.equal(readiness.targetLabel, "Execution Agents");
    assert.equal(readiness.status, "red");
    assert.deepEqual(readiness.missingFacts.map((fact) => [fact.key, fact.state]), [
      ["marketData", "unavailable"]
    ]);
    assert.equal(readiness.suggestedSettingsRoute, "/settings/providers?role=market_data");
  });

  it("returns the required provider facts for a target without reading runtime facts", () => {
    assert.deepEqual(
      requiredProviderFactsForTarget("executionAgents").map((fact) => fact.key),
      ["brokerPaperAccount", "marketData", "portfolioFacts", "observability", "safetyCompliance"]
    );
  });

  it("models scheduled agent checks as visibility-only trigger harness signals blocked by provider readiness", () => {
    const monitoring = getScheduledAgentMonitoring({
      brokerPaperAccount: { state: "available", providerId: "alpaca-paper-broker" },
      llmResearch: { state: "available", providerId: "openai-llm" },
      marketData: { state: "unavailable", providerId: "alpaca-market-data", detail: "market hours endpoint down" },
      observability: { state: "available", providerId: "langfuse-observability" },
      portfolioFacts: { state: "available", providerId: "plaid-portfolio" },
      safetyCompliance: { state: "not_configured" }
    });

    assert.equal(monitoring.status, "blocked");
    assert.equal(monitoring.activeChecks, 6);
    assert.equal(monitoring.blockedChecks, 6);
    assert.match(monitoring.summary, /provider readiness blocks execution/i);
    assert.deepEqual(
      monitoring.checks.map((check) => check.label),
      [
        "Market-open report",
        "Hourly sentiment check",
        "Price trigger",
        "Volume trigger",
        "Risk trigger",
        "Compliance trigger"
      ]
    );
    assert.deepEqual(monitoring.checks[0].triggerTypes, ["time", "report_event"]);
    assert.deepEqual(monitoring.checks[1].triggerTypes, ["time", "sentiment_flip"]);
    assert.deepEqual(monitoring.checks.slice(2).map((check) => check.triggerTypes[0]), [
      "price",
      "volume",
      "risk_threshold",
      "compliance_flag"
    ]);
    assert.ok(monitoring.checks.every((check) => check.executionBlocked));
    assert.match(monitoring.checks[0].blockerSummary, /Market data/);
    assert.match(monitoring.checks[5].blockerSummary, /Safety and compliance/);
  });
});
