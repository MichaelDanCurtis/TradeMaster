import assert from "node:assert/strict";
import { afterEach, describe, it } from "node:test";

import {
  checkProviderHealth,
  completeAgentOperation,
  createAgentOperation,
  createAgentTrigger,
  createAgentWorkflow,
  appendExecutionProgramEvent,
  createExecutionProgram,
  createFundingAllocationReview,
  createPortfolioReview,
  createReportSchedule,
  createTradeThesis,
  createSnapshot,
  evaluateRoomTool,
  exportRunTrace,
  getRunTrace,
  importAgentPack,
  listAgentPacks,
  listAgentOperations,
  listAgentTriggers,
  listApprovalLedger,
  listExecutionProgramEvents,
  listExecutionPrograms,
  listFundingAllocationReviews,
  listImportedAgents,
  listImportedSkills,
  listMcpConnectors,
  listPortfolioReviews,
  listRoomPolicies,
  listReportSchedules,
  listRuns,
  listTradeTheses,
  listProviderRoleAssignments,
  listAgentWorkflows,
  getRuntimeStatus,
  previewExecutionAlgorithm,
  previewTrade,
  recordApprovalLedgerEntry,
  triggerReportSchedule,
  triggerEnabledReportSchedules,
  createUserProvider,
  deleteUserProvider,
  updateDeveloperMode,
  updateResearchRunnerMode,
  updateProviderRoleAssignment,
  waitForRunEvents,
  verifySnapshot
} from "./api.ts";
import type {
  AgentPackRecord,
  ImportedAgentRecord,
  ImportedSkillRecord,
  AgentWorkflowRecord,
  McpConnectorRecord,
  ProviderConfig,
  ProviderRoleAssignment,
  RunTrace,
  SnapshotManifestRecord
} from "./types.ts";

const originalFetch = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = originalFetch;
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" }
  });
}

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

    assert.equal(String(calls[0].input), "http://127.0.0.1:8797/api/provider-configs/alpaca-market-data/health-check");
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

    assert.equal(String(calls[0].input), "http://127.0.0.1:8797/api/runs/run_123/trace");
    assert.equal(calls[0].init, undefined);
    assert.equal(fetched.status, "completed");
  });

  it("lists stored runs for a symbol so the dashboard can hydrate its report inbox", async () => {
    const calls: Array<{ input: string | URL | Request; init?: RequestInit }> = [];
    const runs = [
      {
        run_id: "run_123",
        ticker: "NVDA",
        trade_date: "2026-05-06",
        status: "completed",
        final_rating: "Buy",
        final_action: "Buy",
        created_at: "2026-05-06T07:38:13.000Z",
        updated_at: "2026-05-06T07:38:15.000Z"
      }
    ];
    globalThis.fetch = async (input, init) => {
      calls.push({ input, init });
      // Backend wraps runs in a catalog envelope; client unwraps to a
      // bare array so existing call sites remain unchanged.
      return new Response(JSON.stringify({ runs }), {
        status: 200,
        headers: { "content-type": "application/json" }
      });
    };

    const fetched = await listRuns({ ticker: "NVDA", limit: 5 });

    assert.equal(String(calls[0].input), "http://127.0.0.1:8797/api/runs?ticker=NVDA&limit=5");
    assert.equal(calls[0].init, undefined);
    assert.equal(fetched[0].run_id, "run_123");
  });

  it("creates, lists, and triggers report schedules for the morning dashboard", async () => {
    const calls: Array<{ input: string | URL | Request; init?: RequestInit }> = [];
    const schedule = {
      schedule_id: "sched_123",
      name: "NVDA opening stance",
      symbol: "NVDA",
      cadence: "market_open",
      broker_mode: "disabled",
      execution_mode: "real",
      enabled: true,
      last_run_id: null,
      payload: {},
      last_ran_at: null,
      next_run_at: null,
      created_at: "2026-05-06T07:00:00.000Z",
      updated_at: "2026-05-06T07:00:00.000Z"
    };
    globalThis.fetch = async (input, init) => {
      calls.push({ input, init });
      if (String(input).endsWith("/api/report-schedules")) {
        return new Response(JSON.stringify(schedule), {
          status: 200,
          headers: { "content-type": "application/json" }
        });
      }
      if (String(input).includes("/trigger")) {
        return new Response(
          JSON.stringify({
            schedule: { ...schedule, last_run_id: "run_123" },
            run: { run_id: "run_123", status: "completed" }
          }),
          {
            status: 200,
            headers: { "content-type": "application/json" }
          }
        );
      }
      return new Response(JSON.stringify({ schedules: [schedule] }), {
        status: 200,
        headers: { "content-type": "application/json" }
      });
    };

    await createReportSchedule({ cadence: "market_open", name: "NVDA opening stance", symbol: "NVDA" });
    const listed = await listReportSchedules({ symbol: "NVDA" });
    const triggered = await triggerReportSchedule("sched_123");

    assert.equal(String(calls[0].input), "http://127.0.0.1:8797/api/report-schedules");
    assert.equal(calls[0].init?.method, "POST");
    assert.equal(String(calls[1].input), "http://127.0.0.1:8797/api/report-schedules?symbol=NVDA");
    assert.equal(String(calls[2].input), "http://127.0.0.1:8797/api/report-schedules/sched_123/trigger");
    assert.equal(listed.schedules[0].schedule_id, "sched_123");
    assert.equal(triggered.run.run_id, "run_123");
  });

  it("triggers all enabled report schedules for server-side morning runs", async () => {
    const calls: Array<{ input: string | URL | Request; init?: RequestInit }> = [];
    globalThis.fetch = async (input, init) => {
      calls.push({ input, init });
      return new Response(
        JSON.stringify({
          triggered_count: 1,
          results: [
            {
              schedule: { schedule_id: "sched_123", symbol: "NVDA" },
              run: { run_id: "run_123", status: "completed" }
            }
          ]
        }),
        {
          status: 200,
          headers: { "content-type": "application/json" }
        }
      );
    };

    const triggered = await triggerEnabledReportSchedules({ symbol: "NVDA" });

    assert.equal(String(calls[0].input), "http://127.0.0.1:8797/api/report-schedules/trigger-enabled?symbol=NVDA");
    assert.equal(calls[0].init?.method, "POST");
    assert.equal(triggered.triggered_count, 1);
    assert.equal(triggered.results[0].run.run_id, "run_123");
  });

  it("lists room policies and evaluates room tool grants", async () => {
    const calls: Array<{ input: string | URL | Request; init?: RequestInit }> = [];
    globalThis.fetch = async (input, init) => {
      calls.push({ input, init });
      return new Response(
        JSON.stringify(
          calls.length === 1
            ? {
                rooms: [
                  {
                    room_id: "research",
                    label: "Research Office",
                    mission: "Research only",
                    tool_grants: ["research-runner"],
                    policies: ["Research agents cannot submit broker orders."],
                    decision_actions: ["accept", "reject", "revise", "defer", "escalate"]
                  }
                ]
              }
            : {
                allowed: false,
                reason: "Research Office does not grant broker-paper-preview",
                room_id: "research",
                tool_grant: "broker-paper-preview"
              }
        ),
        {
          status: 200,
          headers: { "content-type": "application/json" }
        }
      );
    };

    const policies = await listRoomPolicies();
    const decision = await evaluateRoomTool({ roomId: "research", toolGrant: "broker-paper-preview" });

    assert.equal(String(calls[0].input), "http://127.0.0.1:8797/api/room-policies");
    assert.equal(String(calls[1].input), "http://127.0.0.1:8797/api/room-policies/evaluate");
    assert.equal(calls[1].init?.method, "POST");
    assert.equal(policies.rooms[0].label, "Research Office");
    assert.equal(decision.allowed, false);
  });

  it("records approval ledger entries and creates agent triggers", async () => {
    const calls: Array<{ input: string | URL | Request; init?: RequestInit }> = [];
    const approvalEntry = {
      action: "accept",
      actor: "mcurtis",
      approval_id: "ledger_123",
      created_at: "2026-05-10T08:00:00.000Z",
      entity_id: "rec_nvda_opening",
      entity_type: "recommendation",
      payload: { symbol: "NVDA" },
      room_id: "dashboard",
      source: "briefing-room",
      summary: "Accept morning recommendation."
    };
    const trigger = {
      condition: { sentiment: "negative" },
      created_at: "2026-05-10T08:00:00.000Z",
      enabled: true,
      last_fired_at: null,
      name: "Hourly negative sentiment wakeup",
      payload: {},
      room_id: "market",
      symbol: "NVDA",
      target_agent: "broker-risk-agent",
      trigger_id: "trigger_123",
      trigger_type: "sentiment_flip",
      updated_at: "2026-05-10T08:00:00.000Z",
      workflow_id: "workflow_broker_watch"
    };
    globalThis.fetch = async (input, init) => {
      calls.push({ input, init });
      if (String(input).includes("/approval-ledger") && init?.method === "POST") {
        return new Response(JSON.stringify(approvalEntry), {
          status: 200,
          headers: { "content-type": "application/json" }
        });
      }
      if (String(input).includes("/approval-ledger")) {
        return new Response(JSON.stringify({ entries: [approvalEntry] }), {
          status: 200,
          headers: { "content-type": "application/json" }
        });
      }
      if (String(input).includes("/agent-triggers") && init?.method === "POST") {
        return new Response(JSON.stringify(trigger), {
          status: 200,
          headers: { "content-type": "application/json" }
        });
      }
      return new Response(JSON.stringify({ triggers: [trigger] }), {
        status: 200,
        headers: { "content-type": "application/json" }
      });
    };

    const recorded = await recordApprovalLedgerEntry({
      action: "accept",
      actor: "mcurtis",
      entityId: "rec_nvda_opening",
      entityType: "recommendation",
      roomId: "dashboard",
      source: "briefing-room",
      summary: "Accept morning recommendation.",
      payload: { symbol: "NVDA" }
    });
    const ledger = await listApprovalLedger({ roomId: "dashboard" });
    const createdTrigger = await createAgentTrigger({
      condition: { sentiment: "negative" },
      name: "Hourly negative sentiment wakeup",
      roomId: "market",
      symbol: "NVDA",
      targetAgent: "broker-risk-agent",
      triggerType: "sentiment_flip",
      workflowId: "workflow_broker_watch"
    });
    const triggers = await listAgentTriggers({ symbol: "NVDA" });

    assert.equal(String(calls[0].input), "http://127.0.0.1:8797/api/approval-ledger");
    assert.equal(JSON.parse(String(calls[0].init?.body)).entity_id, "rec_nvda_opening");
    assert.equal(String(calls[1].input), "http://127.0.0.1:8797/api/approval-ledger?room_id=dashboard");
    assert.equal(String(calls[2].input), "http://127.0.0.1:8797/api/agent-triggers");
    assert.equal(String(calls[3].input), "http://127.0.0.1:8797/api/agent-triggers?symbol=NVDA");
    assert.equal(recorded.action, "accept");
    assert.equal(ledger.entries[0].entity_id, "rec_nvda_opening");
    assert.equal(createdTrigger.trigger_type, "sentiment_flip");
    assert.equal(triggers.triggers[0].target_agent, "broker-risk-agent");
  });

  it("creates, lists, and completes advisory agent operations", async () => {
    const calls: Array<{ input: string | URL | Request; init?: RequestInit }> = [];
    globalThis.fetch = async (input, init) => {
      calls.push({ input, init });
      const url = String(input);
      if (url.endsWith("/api/agent-operations") && init?.method === "POST") {
        return jsonResponse({
          operation_id: "agentop_123",
          agent_id: "market_analyst",
          agent_name: "Market Analyst",
          room_id: "research",
          symbol: "NVDA",
          operation_type: "research_report",
          status: "queued",
          authority: "research_only",
          source_workflow_id: null,
          linked_run_id: null,
          linked_execution_program_id: null,
          payload: {},
          started_at: null,
          completed_at: null,
          created_at: "2026-05-11T12:00:00.000Z",
          updated_at: "2026-05-11T12:00:00.000Z"
        });
      }
      if (url.includes("/api/agent-operations/agentop_123/complete")) {
        return jsonResponse({
          operation_id: "agentop_123",
          agent_id: "market_analyst",
          agent_name: "Market Analyst",
          room_id: "research",
          symbol: "NVDA",
          operation_type: "research_report",
          status: "completed",
          authority: "research_only",
          source_workflow_id: null,
          linked_run_id: "run_123",
          linked_execution_program_id: null,
          payload: { report: "ready" },
          started_at: null,
          completed_at: "2026-05-11T12:03:00.000Z",
          created_at: "2026-05-11T12:00:00.000Z",
          updated_at: "2026-05-11T12:03:00.000Z"
        });
      }
      return jsonResponse({
        operations: [
          {
            operation_id: "agentop_123",
            agent_id: "market_analyst",
            agent_name: "Market Analyst",
            room_id: "research",
            symbol: "NVDA",
            operation_type: "research_report",
            status: "completed",
            authority: "research_only",
            source_workflow_id: null,
            linked_run_id: "run_123",
            linked_execution_program_id: null,
            payload: {},
            started_at: null,
            completed_at: "2026-05-11T12:03:00.000Z",
            created_at: "2026-05-11T12:00:00.000Z",
            updated_at: "2026-05-11T12:03:00.000Z"
          }
        ]
      });
    };

    const created = await createAgentOperation({
      agentId: "market_analyst",
      agentName: "Market Analyst",
      authority: "research_only",
      operationType: "research_report",
      roomId: "research",
      symbol: "NVDA"
    });
    const completed = await completeAgentOperation("agentop_123", {
      linkedRunId: "run_123",
      payload: { report: "ready" }
    });
    const listed = await listAgentOperations({ status: "completed", symbol: "NVDA" });

    assert.equal(String(calls[0].input), "http://127.0.0.1:8797/api/agent-operations");
    assert.deepEqual(JSON.parse(String(calls[0].init?.body)), {
      agent_id: "market_analyst",
      agent_name: "Market Analyst",
      authority: "research_only",
      linked_execution_program_id: null,
      linked_run_id: null,
      operation_type: "research_report",
      payload: {},
      room_id: "research",
      source_workflow_id: null,
      symbol: "NVDA"
    });
    assert.equal(String(calls[1].input), "http://127.0.0.1:8797/api/agent-operations/agentop_123/complete");
    assert.deepEqual(JSON.parse(String(calls[1].init?.body)), {
      linked_execution_program_id: null,
      linked_run_id: "run_123",
      payload: { report: "ready" }
    });
    assert.equal(String(calls[2].input), "http://127.0.0.1:8797/api/agent-operations?symbol=NVDA&status=completed");
    assert.equal(created.operation_id, "agentop_123");
    assert.equal(completed.status, "completed");
    assert.equal(listed.operations[0].linked_run_id, "run_123");
  });

  it("creates and lists advisory trade theses for research-to-brokerage handoff", async () => {
    const calls: Array<{ input: string | URL | Request; init?: RequestInit }> = [];
    const thesis = {
      catalysts: ["Blackwell supply update"],
      conviction: 0.72,
      created_at: "2026-05-10T08:00:00.000Z",
      direction: "long",
      horizon: "2-4 weeks",
      invalidation: ["gross margin compression"],
      payload: { suggested_algorithm: "trailing_stop" },
      risk_notes: "Advisory only.",
      source_report_id: "run_nvda_overnight",
      source_room: "research",
      status: "proposed",
      symbol: "NVDA",
      target_room: "market",
      thesis: "AI infrastructure demand supports a measured long thesis.",
      thesis_id: "thesis_123",
      updated_at: "2026-05-10T08:00:00.000Z"
    };
    globalThis.fetch = async (input, init) => {
      calls.push({ input, init });
      if (init?.method === "POST") {
        return new Response(JSON.stringify(thesis), {
          status: 200,
          headers: { "content-type": "application/json" }
        });
      }
      return new Response(JSON.stringify({ theses: [thesis] }), {
        status: 200,
        headers: { "content-type": "application/json" }
      });
    };

    const created = await createTradeThesis({
      catalysts: ["Blackwell supply update"],
      conviction: 0.72,
      direction: "long",
      horizon: "2-4 weeks",
      invalidation: ["gross margin compression"],
      payload: { suggestedAlgorithm: "trailing_stop" },
      riskNotes: "Advisory only.",
      sourceReportId: "run_nvda_overnight",
      symbol: "NVDA",
      thesis: "AI infrastructure demand supports a measured long thesis."
    });
    const listed = await listTradeTheses({ symbol: "NVDA", status: "proposed" });

    assert.equal(String(calls[0].input), "http://127.0.0.1:8797/api/trade-theses");
    assert.equal(JSON.parse(String(calls[0].init?.body)).source_report_id, "run_nvda_overnight");
    assert.equal(JSON.parse(String(calls[0].init?.body)).target_room, "market");
    assert.equal(String(calls[1].input), "http://127.0.0.1:8797/api/trade-theses?symbol=NVDA&status=proposed");
    assert.equal(created.thesis_id, "thesis_123");
    assert.equal(listed.theses[0].source_room, "research");
  });

  it("previews deterministic execution algorithms", async () => {
    const calls: Array<{ input: string | URL | Request; init?: RequestInit }> = [];
    globalThis.fetch = async (input, init) => {
      calls.push({ input, init });
      return new Response(
        JSON.stringify({
          algorithm: "bracket_order",
          symbol: "NVDA",
          side: "buy",
          notional: 1000,
          reference_price: 200,
          estimated_quantity: 5,
          legs: [
            {
              estimated_quantity: 5,
              kind: "market_entry",
              notional: 1000,
              parameters: {},
              price: 200,
              side: "buy",
              symbol: "NVDA"
            }
          ],
          policy_notes: ["Paper preview only until human approval."]
        }),
        {
          status: 200,
          headers: { "content-type": "application/json" }
        }
      );
    };

    const plan = await previewExecutionAlgorithm({
      algorithm: "bracket_order",
      notional: 1000,
      referencePrice: 200,
      side: "buy",
      symbol: "NVDA"
    });

    assert.equal(String(calls[0].input), "http://127.0.0.1:8797/api/execution-algorithms/preview");
    assert.equal(calls[0].init?.method, "POST");
    assert.equal(JSON.parse(String(calls[0].init?.body)).room_id, "market");
    assert.equal(plan.algorithm, "bracket_order");
  });

  it("maps durable workflow records to the backend API contract", async () => {
    const calls: Array<{ input: string | URL | Request; init?: RequestInit }> = [];
    globalThis.fetch = async (input, init) => {
      calls.push({ input, init });
      const url = String(input);
      if (url.endsWith("/api/portfolio-reviews") && init?.method === "POST") {
        return jsonResponse({
          review_id: "portfolio_review_123",
          symbol: "NVDA",
          status: "draft",
          review: { title: "Portfolio Review" },
          payload: {},
          created_at: "2026-05-11T12:00:00.000Z",
          updated_at: "2026-05-11T12:00:00.000Z"
        });
      }
      if (url.includes("/api/portfolio-reviews")) {
        return jsonResponse({ reviews: [{ review_id: "portfolio_review_123", symbol: "NVDA", status: "draft" }] });
      }
      if (url.endsWith("/api/funding-allocation-reviews") && init?.method === "POST") {
        return jsonResponse({
          review_id: "funding_review_123",
          symbol: "NVDA",
          status: "pending_private_office",
          notional: 25000,
          review: { title: "Funding Allocation Review" },
          payload: {},
          created_at: "2026-05-11T12:00:00.000Z",
          updated_at: "2026-05-11T12:00:00.000Z"
        });
      }
      if (url.includes("/api/funding-allocation-reviews")) {
        return jsonResponse({ reviews: [{ review_id: "funding_review_123", symbol: "NVDA", status: "pending_private_office" }] });
      }
      if (url.endsWith("/api/execution-programs") && init?.method === "POST") {
        return jsonResponse({
          program_id: "program_123",
          symbol: "NVDA",
          state: "preview_ready",
          algorithm: "staged_accumulation",
          live_submission_enabled: false,
          payload: {},
          created_at: "2026-05-11T12:00:00.000Z",
          updated_at: "2026-05-11T12:00:00.000Z"
        });
      }
      if (url.includes("/api/execution-programs/program_123/events") && init?.method === "POST") {
        return jsonResponse({
          event_id: "event_123",
          program_id: "program_123",
          sequence: 2,
          event_type: "approval_required",
          summary: "Approval required before route.",
          payload: {},
          created_at: "2026-05-11T12:01:00.000Z"
        });
      }
      if (url.includes("/api/execution-programs/program_123/events")) {
        return jsonResponse({ events: [{ event_id: "event_123", program_id: "program_123", sequence: 1 }] });
      }
      return jsonResponse({ programs: [{ program_id: "program_123", symbol: "NVDA", state: "preview_ready" }] });
    };

    const portfolioCatalog = await listPortfolioReviews({ symbol: "NVDA", status: "draft" });
    const portfolioReview = await createPortfolioReview({
      symbol: "NVDA",
      status: "draft",
      thesis: { title: "Portfolio Review" },
      payload: { sourceRoom: "dashboard" }
    });
    const fundingCatalog = await listFundingAllocationReviews({ symbol: "NVDA", status: "pending_private_office" });
    const fundingReview = await createFundingAllocationReview({
      notional: 25000,
      tracks: [{ title: "Funding Allocation Review" }],
      status: "pending_private_office",
      symbol: "NVDA"
    });
    const programCatalog = await listExecutionPrograms({ symbol: "NVDA", state: "preview_ready" });
    const program = await createExecutionProgram({
      algorithmId: "staged_accumulation",
      state: "preview_ready",
      symbol: "NVDA"
    });
    const eventCatalog = await listExecutionProgramEvents("program_123");
    const event = await appendExecutionProgramEvent("program_123", {
      eventType: "approval_required",
      payload: { roomId: "market" },
      summary: "Approval required before route."
    });

    assert.equal(String(calls[0].input), "http://127.0.0.1:8797/api/portfolio-reviews?symbol=NVDA&status=draft");
    assert.equal(String(calls[1].input), "http://127.0.0.1:8797/api/portfolio-reviews");
    assert.equal(calls[1].init?.method, "POST");
    assert.deepEqual(JSON.parse(String(calls[1].init?.body)), {
      constraints: null,
      goals: null,
      horizon: null,
      liquidity_needs: null,
      missing_provider_facts: [],
      payload: { sourceRoom: "dashboard" },
      risk_posture: null,
      room_id: "portfolio",
      sector_focus: null,
      symbol: "NVDA",
      status: "draft",
      thesis: { title: "Portfolio Review" }
    });
    assert.equal(String(calls[2].input), "http://127.0.0.1:8797/api/funding-allocation-reviews?symbol=NVDA&status=pending_private_office");
    assert.equal(String(calls[3].input), "http://127.0.0.1:8797/api/funding-allocation-reviews");
    assert.equal(calls[3].init?.method, "POST");
    assert.deepEqual(JSON.parse(String(calls[3].init?.body)).notional, 25000);
    assert.equal(String(calls[4].input), "http://127.0.0.1:8797/api/execution-programs?symbol=NVDA&state=preview_ready");
    assert.equal(String(calls[5].input), "http://127.0.0.1:8797/api/execution-programs");
    assert.deepEqual(JSON.parse(String(calls[5].init?.body)), {
      algorithm: "staged_accumulation",
      approval_status: "required",
      circuit_breakers: [],
      live_submission_enabled: false,
      missing_provider_facts: [],
      mode: "paper",
      payload: {},
      source_thesis_id: null,
      state: "preview_ready",
      symbol: "NVDA",
      trigger_points: []
    });
    assert.equal(String(calls[6].input), "http://127.0.0.1:8797/api/execution-programs/program_123/events");
    assert.equal(String(calls[7].input), "http://127.0.0.1:8797/api/execution-programs/program_123/events");
    assert.equal(calls[7].init?.method, "POST");
    assert.deepEqual(JSON.parse(String(calls[7].init?.body)), {
      event_type: "approval_required",
      payload: { roomId: "market" },
      summary: "Approval required before route."
    });
    assert.equal(portfolioCatalog.reviews[0].review_id, "portfolio_review_123");
    assert.equal(portfolioReview.review_id, "portfolio_review_123");
    assert.equal(fundingCatalog.reviews[0].review_id, "funding_review_123");
    assert.equal(fundingReview.notional, 25000);
    assert.equal(programCatalog.programs[0].program_id, "program_123");
    assert.equal(program.live_submission_enabled, false);
    assert.equal(eventCatalog.events[0].event_id, "event_123");
    assert.equal(event.event_type, "approval_required");
  });

  it("surfaces trade preview policy veto details from the backend", async () => {
    globalThis.fetch = async () =>
      new Response(
        JSON.stringify({
          detail: "symbolic constraints vetoed order: max_position_percent"
        }),
        {
          status: 403,
          headers: { "content-type": "application/json" }
        }
      );

    await assert.rejects(
      () =>
        previewTrade({
          notional: 25_000,
          runId: "run_123",
          side: "buy",
          symbol: "NVDA"
        }),
      /symbolic constraints vetoed order: max_position_percent/
    );
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

    assert.equal(String(calls[0].input), "http://127.0.0.1:8797/api/runs/run_123/trace/export");
    assert.equal(calls[0].init?.method, "POST");
    assert.equal(exported.provider, "langfuse-observability");
    assert.equal(exported.metadata.exported_to, "langfuse");
    assert.equal(String(exported.metadata).includes("sk-lf"), false);
  });

  it("creates an encrypted snapshot with a backup key reference", async () => {
    const calls: Array<{ input: string | URL | Request; init?: RequestInit }> = [];
    const snapshot = makeSnapshot({
      encryption_mode: "local-aes-256-gcm",
      manifest: {
        ...makeSnapshot({}).manifest,
        encryption_mode: "local-aes-256-gcm",
        encrypted: true,
        backup_artifact: {
          algorithm: "AES-256-GCM",
          path: "/tmp/backups/snapshot_1.tmbackup",
          sha256: "a".repeat(64),
          size_bytes: 512
        }
      }
    });
    globalThis.fetch = async (input, init) => {
      calls.push({ input, init });
      return new Response(JSON.stringify(snapshot), {
        status: 200,
        headers: { "content-type": "application/json" }
      });
    };

    const created = await createSnapshot({
      backupKeyRef: "env:TRADEMASTER_BACKUP_KEY",
      offsiteTarget: "manual-offsite"
    });

    assert.equal(String(calls[0].input), "http://127.0.0.1:8797/api/snapshots");
    assert.equal(calls[0].init?.method, "POST");
    assert.deepEqual(JSON.parse(String(calls[0].init?.body)), {
      offsite_target: "manual-offsite",
      backup_key_ref: "env:TRADEMASTER_BACKUP_KEY"
    });
    assert.equal(created.manifest.backup_artifact?.algorithm, "AES-256-GCM");
  });

  it("verifies an encrypted snapshot without sending raw key material", async () => {
    const calls: Array<{ input: string | URL | Request; init?: RequestInit }> = [];
    globalThis.fetch = async (input, init) => {
      calls.push({ input, init });
      return new Response(
        JSON.stringify({
          valid: true,
          manifest: { snapshot_id: "snapshot_1" },
          files: [{ path: "ui.db", verified: true }]
        }),
        {
          status: 200,
          headers: { "content-type": "application/json" }
        }
      );
    };

    const verification = await verifySnapshot("snapshot_1", {
      backupKeyRef: "env:TRADEMASTER_BACKUP_KEY"
    });

    assert.equal(String(calls[0].input), "http://127.0.0.1:8797/api/snapshots/snapshot_1/verify");
    assert.equal(calls[0].init?.method, "POST");
    assert.deepEqual(JSON.parse(String(calls[0].init?.body)), {
      backup_key_ref: "env:TRADEMASTER_BACKUP_KEY"
    });
    assert.equal(String(calls[0].init?.body).includes("local backup key"), false);
    assert.equal(verification.valid, true);
  });

  it("creates and lists persisted agent workflow manifests", async () => {
    const calls: Array<{ input: string | URL | Request; init?: RequestInit }> = [];
    const workflow = makeAgentWorkflow({});
    globalThis.fetch = async (input, init) => {
      calls.push({ input, init });
      return new Response(
        JSON.stringify(calls.length === 1 ? workflow : { workflows: [workflow] }),
        {
          status: 200,
          headers: { "content-type": "application/json" }
        }
      );
    };

    const created = await createAgentWorkflow({
      agentClass: "research",
      edges: [{ source: "market-analyst", target: "research-manager" }],
      graphRuntime: "langgraph",
      name: "NVDA workflow",
      nodes: [{ id: "market-analyst", kind: "agent" }],
      requiredProviderRoles: { research_llm: "openai-llm", market_data: "alpaca-market-data" },
      status: "draft"
    });
    const listed = await listAgentWorkflows();

    assert.equal(String(calls[0].input), "http://127.0.0.1:8797/api/agent-workflows");
    assert.equal(calls[0].init?.method, "POST");
    assert.deepEqual(JSON.parse(String(calls[0].init?.body)).required_provider_roles, {
      research_llm: "openai-llm",
      market_data: "alpaca-market-data"
    });
    assert.equal(String(calls[1].input), "http://127.0.0.1:8797/api/agent-workflows");
    assert.equal(created.workflow_id, "workflow_123");
    assert.equal(listed.workflows[0].graph_runtime, "langgraph");
  });

  it("imports and lists normalized financial-services agent packs", async () => {
    const calls: Array<{ input: string | URL | Request; init?: RequestInit }> = [];
    const pack = makeAgentPack({});
    const agent = makeImportedAgent({});
    const skill = makeImportedSkill({});
    const connector = makeMcpConnector({});
    globalThis.fetch = async (input, init) => {
      calls.push({ input, init });
      const responseBody =
        calls.length === 1
          ? { pack_id: "anthropic-financial-services", agent_count: 1, skill_count: 1, connector_count: 1 }
          : calls.length === 2
            ? { packs: [pack] }
            : calls.length === 3
              ? { agents: [agent] }
              : calls.length === 4
                ? { skills: [skill] }
                : { connectors: [connector] };
      return new Response(JSON.stringify(responseBody), {
        status: 200,
        headers: { "content-type": "application/json" }
      });
    };

    const imported = await importAgentPack({
      packId: "anthropic-financial-services",
      sourcePath: "/tmp/financial-services",
      sourceUrl: "https://github.com/anthropics/financial-services",
      sourceCommit: "abc123"
    });
    const packs = await listAgentPacks();
    const agents = await listImportedAgents({ packId: "anthropic-financial-services" });
    const skills = await listImportedSkills({ packId: "anthropic-financial-services" });
    const connectors = await listMcpConnectors();

    assert.equal(String(calls[0].input), "http://127.0.0.1:8797/api/agent-packs/import");
    assert.equal(calls[0].init?.method, "POST");
    assert.deepEqual(JSON.parse(String(calls[0].init?.body)), {
      pack_id: "anthropic-financial-services",
      source_path: "/tmp/financial-services",
      source_url: "https://github.com/anthropics/financial-services",
      source_commit: "abc123"
    });
    assert.equal(String(calls[2].input), "http://127.0.0.1:8797/api/imported-agents?pack_id=anthropic-financial-services");
    assert.equal(imported.agent_count, 1);
    assert.equal(packs.packs[0].pack_id, "anthropic-financial-services");
    assert.equal(agents.agents[0].source_slug, "market-researcher");
    assert.equal(skills.skills[0].name, "sector-overview");
    assert.equal(connectors.connectors[0].connector_id, "factset");
  });

  it("lists and updates provider role assignments", async () => {
    const calls: Array<{ input: string | URL | Request; init?: RequestInit }> = [];
    globalThis.fetch = async (input, init) => {
      calls.push({ input, init });
      return new Response(
        JSON.stringify(
          calls.length === 1
            ? { assignments: [makeProviderRoleAssignment({ role_key: "research_llm", provider_id: "openai-llm" })] }
            : makeProviderRoleAssignment({ role_key: "research_llm", provider_id: "lm-studio-llm" })
        ),
        {
          status: 200,
          headers: { "content-type": "application/json" }
        }
      );
    };

    const listed = await listProviderRoleAssignments();
    const updated = await updateProviderRoleAssignment("research_llm", "lm-studio-llm");

    assert.equal(String(calls[0].input), "http://127.0.0.1:8797/api/provider-role-assignments");
    assert.equal(String(calls[1].input), "http://127.0.0.1:8797/api/provider-role-assignments/research_llm");
    assert.equal(calls[1].init?.method, "POST");
    assert.deepEqual(JSON.parse(String(calls[1].init?.body)), { provider_id: "lm-studio-llm" });
    assert.equal(listed.assignments[0].provider_id, "openai-llm");
    assert.equal(updated.provider_id, "lm-studio-llm");
  });

  it("fetches runtime status for provider wiring visibility", async () => {
    const calls: Array<{ input: string | URL | Request; init?: RequestInit }> = [];
    globalThis.fetch = async (input, init) => {
      calls.push({ input, init });
      return new Response(
        JSON.stringify({
          broker: { approval_required: true, provider_id: "alpaca-paper-broker" },
          execution_policy: { max_position_percent: 10, paper_mode_required: true },
          full_tradingagents_graph: { enabled: false },
          research_llm: {
            fallback_expected: false,
            provider_id: "lm-studio-llm",
            secret_ref_configured: true
          },
          research_runner: { mode: "llm-ui-runner", uses_provider_role: "research_llm" }
        }),
        {
          status: 200,
          headers: { "content-type": "application/json" }
        }
      );
    };

    const status = await getRuntimeStatus();

    assert.equal(String(calls[0].input), "http://127.0.0.1:8797/api/runtime/status");
    assert.equal(status.research_llm.provider_id, "lm-studio-llm");
    assert.equal(status.execution_policy.paper_mode_required, true);
  });

  it("posts research runner mode updates and returns runtime status", async () => {
    const calls: Array<{ input: string | URL | Request; init?: RequestInit }> = [];
    globalThis.fetch = async (input, init) => {
      calls.push({ input, init });
      return new Response(
        JSON.stringify({
          broker: { approval_required: true, provider_id: "alpaca-paper-broker" },
          execution_policy: { max_position_percent: 10, paper_mode_required: true },
          full_tradingagents_graph: { configured: true, enabled: true, env_flag: false },
          research_llm: {
            fallback_expected: false,
            provider_id: "lm-studio-llm",
            secret_ref_configured: false
          },
          research_runner: {
            configured_mode: "tradingagents-graph-runner",
            mode: "tradingagents-graph-runner",
            uses_provider_role: "research_llm"
          }
        }),
        {
          status: 200,
          headers: { "content-type": "application/json" }
        }
      );
    };

    const status = await updateResearchRunnerMode("tradingagents-graph-runner");

    assert.equal(String(calls[0].input), "http://127.0.0.1:8797/api/runtime/research-runner");
    assert.equal(calls[0].init?.method, "POST");
    assert.deepEqual(JSON.parse(String(calls[0].init?.body)), { mode: "tradingagents-graph-runner" });
    assert.equal(status.research_runner.configured_mode, "tradingagents-graph-runner");
  });

  it("posts user-defined provider creation with the API's expected snake_case body", async () => {
    const calls: Array<{ input: string | URL | Request; init?: RequestInit }> = [];
    globalThis.fetch = async (input, init) => {
      calls.push({ input, init });
      return new Response(
        JSON.stringify({
          provider_id: "user:glm",
          name: "GLM",
          role: "llm",
          status: "needs_key",
          capabilities: ["openai-compatible", "user-defined", "tool-calling"],
          primary_use: "User-defined openai-compatible provider at https://api.z.ai/api/paas/v4/.",
          control_surface: "platform",
          write_authority: "none",
          enabled: false,
          secret_ref: "env:ZHIPU_API_KEY",
          config: {
            user_defined: true,
            kind: "openai-compatible",
            provider: "openai-compatible",
            base_url: "https://api.z.ai/api/paas/v4/",
            model: "glm-4.6",
            auth_required: true,
            runner_supported: true,
            graph_runner_supported: true
          },
          health: { status: "not_checked" },
          created_at: "2026-05-10T00:00:00Z",
          updated_at: "2026-05-10T00:00:00Z"
        }),
        { status: 201, headers: { "content-type": "application/json" } }
      );
    };

    const created = await createUserProvider({
      name: "GLM",
      kind: "openai-compatible",
      baseUrl: "https://api.z.ai/api/paas/v4/",
      model: "glm-4.6",
      apiKeyEnv: "env:ZHIPU_API_KEY"
    });

    assert.equal(String(calls[0].input), "http://127.0.0.1:8797/api/provider-configs");
    assert.equal(calls[0].init?.method, "POST");
    const body = JSON.parse(String(calls[0].init?.body));
    assert.equal(body.name, "GLM");
    assert.equal(body.kind, "openai-compatible");
    assert.equal(body.base_url, "https://api.z.ai/api/paas/v4/");
    assert.equal(body.model, "glm-4.6");
    assert.equal(body.api_key_env, "env:ZHIPU_API_KEY");
    assert.equal(created.provider_id, "user:glm");
  });

  it("surfaces the server's 400 detail when create user provider fails", async () => {
    globalThis.fetch = async () =>
      new Response(JSON.stringify({ detail: "a provider named 'GLM' already exists" }), {
        status: 400,
        headers: { "content-type": "application/json" }
      });

    await assert.rejects(
      () =>
        createUserProvider({
          name: "GLM",
          kind: "openai-compatible",
          baseUrl: "https://x",
          model: "m"
        }),
      /already exists/
    );
  });

  it("deletes a user-defined provider via DELETE and returns void on 204", async () => {
    const calls: Array<{ input: string | URL | Request; init?: RequestInit }> = [];
    globalThis.fetch = async (input, init) => {
      calls.push({ input, init });
      return new Response(null, { status: 204 });
    };

    await deleteUserProvider("user:glm");

    assert.equal(String(calls[0].input), "http://127.0.0.1:8797/api/provider-configs/user:glm");
    assert.equal(calls[0].init?.method, "DELETE");
  });

  it("posts developer-mode toggle updates and returns runtime status", async () => {
    const calls: Array<{ input: string | URL | Request; init?: RequestInit }> = [];
    globalThis.fetch = async (input, init) => {
      calls.push({ input, init });
      return new Response(
        JSON.stringify({
          broker: { approval_required: true, provider_id: "alpaca-paper-broker" },
          developer_mode_enabled: true,
          execution_policy: { max_position_percent: 10, paper_mode_required: true },
          full_tradingagents_graph: { enabled: false },
          research_llm: {
            fallback_expected: false,
            provider_id: "lm-studio-llm",
            secret_ref_configured: true
          },
          research_runner: { mode: "llm-ui-runner", uses_provider_role: "research_llm" }
        }),
        { status: 200, headers: { "content-type": "application/json" } }
      );
    };

    const status = await updateDeveloperMode(true);

    assert.equal(String(calls[0].input), "http://127.0.0.1:8797/api/runtime/developer-mode");
    assert.equal(calls[0].init?.method, "POST");
    assert.deepEqual(JSON.parse(String(calls[0].init?.body)), { enabled: true });
    assert.equal(status.developer_mode_enabled, true);
  });

  it("polls run events until a terminal real-run event is visible", async () => {
    const calls: Array<{ input: string | URL | Request; init?: RequestInit }> = [];
    let attempt = 0;
    globalThis.fetch = async (input, init) => {
      calls.push({ input, init });
      attempt += 1;
      return new Response(
        JSON.stringify(
          attempt < 2
            ? [{ run_id: "run_123", sequence: 1, type: "run.started", message: "Started", payload: {} }]
            : [
                { run_id: "run_123", sequence: 1, type: "run.started", message: "Started", payload: {} },
                { run_id: "run_123", sequence: 2, type: "run.completed", message: "Done", payload: {} }
              ]
        ),
        {
          status: 200,
          headers: { "content-type": "application/json" }
        }
      );
    };

    const seen: number[] = [];
    const events = await waitForRunEvents("run_123", {
      intervalMs: 0,
      maxAttempts: 3,
      onEvents: (nextEvents) => seen.push(nextEvents.length)
    });

    assert.equal(calls.length, 2);
    assert.equal(String(calls[0].input), "http://127.0.0.1:8797/api/runs/run_123/events");
    assert.deepEqual(seen, [1, 2]);
    assert.equal(events.at(-1)?.type, "run.completed");
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

function makeSnapshot(overrides: Partial<SnapshotManifestRecord>): SnapshotManifestRecord {
  return {
    created_at: "2026-05-04T12:00:00.000Z",
    encryption_mode: "none",
    manifest: {
      created_at: "2026-05-04T12:00:00.000Z",
      database_path: "/tmp/ui.db",
      encrypted: false,
      encryption_mode: "none",
      files: [{ path: "/tmp/ui.db", sha256: "b".repeat(64), size_bytes: 256 }],
      offsite_target: null,
      snapshot_id: "snapshot_1",
      storage_profile: "sqlite-local"
    },
    offsite_target: null,
    snapshot_id: "snapshot_1",
    storage_profile: "sqlite-local",
    ...overrides
  };
}

function makeAgentWorkflow(overrides: Partial<AgentWorkflowRecord>): AgentWorkflowRecord {
  return {
    agent_class: "research",
    created_at: "2026-05-05T12:00:00.000Z",
    edges: [{ source: "market-analyst", target: "research-manager" }],
    graph_runtime: "langgraph",
    name: "NVDA workflow",
    nodes: [{ id: "market-analyst", kind: "agent" }],
    payload: {},
    required_provider_roles: { research_llm: "openai-llm" },
    status: "draft",
    updated_at: "2026-05-05T12:00:00.000Z",
    workflow_id: "workflow_123",
    ...overrides
  };
}

function makeAgentPack(overrides: Partial<AgentPackRecord>): AgentPackRecord {
  return {
    imported_at: "2026-05-10T12:00:00.000Z",
    license: "MIT",
    manifest: { name: "claude-for-financial-services" },
    pack_id: "anthropic-financial-services",
    source_commit: "abc123",
    source_url: "https://github.com/anthropics/financial-services",
    status: "imported",
    updated_at: "2026-05-10T12:00:00.000Z",
    ...overrides
  };
}

function makeImportedAgent(overrides: Partial<ImportedAgentRecord>): ImportedAgentRecord {
  return {
    agent_class: "research",
    agent_id: "anthropic-financial-services:market-researcher",
    commands: [],
    created_at: "2026-05-10T12:00:00.000Z",
    description: "Produces sector research.",
    guardrails: ["Cite every number."],
    name: "Market Researcher",
    output_schema: {},
    pack_id: "anthropic-financial-services",
    payload: { managed_model: "claude-opus-4-7" },
    required_connectors: ["factset"],
    required_provider_roles: { financial_data: "factset" },
    security_profile: { broker_tools_allowed: false },
    skills: ["sector-overview"],
    source_slug: "market-researcher",
    status: "imported",
    system_prompt: "You are the Market Researcher.",
    tool_policy: { call_mcp: true, read_files: true },
    updated_at: "2026-05-10T12:00:00.000Z",
    ...overrides
  };
}

function makeImportedSkill(overrides: Partial<ImportedSkillRecord>): ImportedSkillRecord {
  return {
    artifact_requirements: {},
    created_at: "2026-05-10T12:00:00.000Z",
    description: "Draft a sector overview.",
    instructions_markdown: "Build market size and growth.",
    name: "sector-overview",
    pack_id: "anthropic-financial-services",
    payload: {},
    references: [],
    scripts: [],
    skill_id: "anthropic-financial-services:sector-overview",
    source_path: "plugins/agent-plugins/market-researcher/skills/sector-overview/SKILL.md",
    status: "imported",
    updated_at: "2026-05-10T12:00:00.000Z",
    ...overrides
  };
}

function makeMcpConnector(overrides: Partial<McpConnectorRecord>): McpConnectorRecord {
  return {
    capabilities: ["mcp", "read-only-financial-data"],
    connector_id: "factset",
    created_at: "2026-05-10T12:00:00.000Z",
    enabled: false,
    health: { status: "not_checked" },
    name: "Factset",
    payload: {},
    provider_id: "factset",
    required_secret_ref: null,
    subscription_required: true,
    updated_at: "2026-05-10T12:00:00.000Z",
    url: "https://mcp.factset.com/mcp",
    ...overrides
  };
}

function makeProviderRoleAssignment(overrides: Partial<ProviderRoleAssignment>): ProviderRoleAssignment {
  return {
    created_at: "2026-05-05T12:00:00.000Z",
    provider_id: "openai-llm",
    role_key: "research_llm",
    surface: "ai-harness",
    updated_at: "2026-05-05T12:00:00.000Z",
    ...overrides
  };
}
