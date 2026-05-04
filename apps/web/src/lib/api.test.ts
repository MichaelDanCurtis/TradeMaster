import assert from "node:assert/strict";
import { afterEach, describe, it } from "node:test";

import { checkProviderHealth, exportRunTrace, getRunTrace } from "./api.ts";
import type { ProviderConfig, RunTrace } from "./types.ts";

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

  it("fetches a run trace without mutating it", async () => {
    const calls: Array<{ input: string | URL | Request; init?: RequestInit }> = [];
    const trace = makeRunTrace({ status: "completed" });
    globalThis.fetch = async (input, init) => {
      calls.push({ input, init });
      return new Response(JSON.stringify(trace), {
        status: 200,
        headers: { "content-type": "application/json" }
      });
    };

    const fetched = await getRunTrace("run_123");

    assert.equal(String(calls[0].input), "http://127.0.0.1:8787/api/runs/run_123/trace");
    assert.equal(calls[0].init, undefined);
    assert.equal(fetched.status, "completed");
  });

  it("exports a run trace to LangFuse and keeps secrets out of the response", async () => {
    const calls: Array<{ input: string | URL | Request; init?: RequestInit }> = [];
    const trace = makeRunTrace({
      provider: "langfuse-observability",
      status: "exported",
      external_trace_id: "0123456789abcdef0123456789abcdef",
      metadata: {
        exported_to: "langfuse",
        external_trace_url: "https://cloud.langfuse.com/project/local/traces/0123456789abcdef0123456789abcdef"
      }
    });
    globalThis.fetch = async (input, init) => {
      calls.push({ input, init });
      return new Response(JSON.stringify(trace), {
        status: 200,
        headers: { "content-type": "application/json" }
      });
    };

    const exported = await exportRunTrace("run_123");

    assert.equal(String(calls[0].input), "http://127.0.0.1:8787/api/runs/run_123/trace/export");
    assert.equal(calls[0].init?.method, "POST");
    assert.equal(exported.provider, "langfuse-observability");
    assert.equal(exported.metadata.exported_to, "langfuse");
    assert.equal(String(exported.metadata).includes("sk-lf"), false);
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

function makeRunTrace(overrides: Partial<RunTrace>): RunTrace {
  return {
    cost: {},
    created_at: "2026-05-04T12:00:00.000Z",
    external_trace_id: null,
    metadata: {
      ticker: "NVDA",
      execution_mode: "simulated"
    },
    provider: "local",
    run_id: "run_123",
    status: "completed",
    trace_id: "trace_123",
    updated_at: "2026-05-04T12:00:00.000Z",
    ...overrides
  };
}
