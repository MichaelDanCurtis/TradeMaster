import assert from "node:assert/strict";
import { afterEach, describe, it } from "node:test";

import { checkProviderHealth } from "./api.ts";
import type { ProviderConfig } from "./types.ts";

const originalFetch = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = originalFetch;
});

describe("api client", () => {
  it("posts provider health checks and returns the updated provider config", async () => {
    const calls: Array<{ input: string | URL | Request; init?: RequestInit }> = [];
    const provider = makeProviderConfig({
      health: { secret: { backend: "env", available: true } }
    });
    globalThis.fetch = async (input, init) => {
      calls.push({ input, init });
      return new Response(JSON.stringify(provider), {
        status: 200,
        headers: { "content-type": "application/json" }
      });
    };

    const updated = await checkProviderHealth("alpaca-market-data");

    assert.equal(String(calls[0].input), "http://127.0.0.1:8787/api/provider-configs/alpaca-market-data/health-check");
    assert.equal(calls[0].init?.method, "POST");
    assert.deepEqual(updated.health, { secret: { backend: "env", available: true } });
  });
});

function makeProviderConfig(overrides: Partial<ProviderConfig>): ProviderConfig {
  return {
    capabilities: ["historical-bars"],
    config: {},
    control_surface: "agent-data",
    enabled: true,
    health: {},
    name: "Alpaca Market Data",
    primary_use: "Agent market data",
    provider_id: "alpaca-market-data",
    role: "market-data",
    secret_ref: "env:TRADEMASTER_ALPACA_CREDS",
    status: "available",
    write_authority: "read-only",
    ...overrides
  };
}
