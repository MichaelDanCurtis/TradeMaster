"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { AgentReportsPanel } from "@/components/AgentReportsPanel";
import { AgentRunGraph } from "@/components/AgentRunGraph";
// AdvisorNarrativePanel removed in the v2 IA cleanup.
import { InfoModal } from "@/components/InfoModal";
import { RunTimeline } from "@/components/RunTimeline";
import { TradeTicket } from "@/components/TradeTicket";
import { deriveAgentReports } from "@/lib/agent-reports";
import { englishOrNotice } from "@/lib/language";
import {
  completeAgentOperation,
  createAgentOperation,
  createRun,
  getRuntimeStatus,
  previewTrade,
  waitForRunEvents
} from "@/lib/api";
import {
  AGENT_TEAM_LABELS,
  getAgentActionPlan,
  getTradingAgentsByTeam,
  TRADING_AGENT_REGISTRY,
  type AgentTeamId,
  type TradingAgentDescriptor
} from "@/lib/agent-registry";
import type { OrderPreview, RunEvent, RuntimeStatus } from "@/lib/types";

const TEAM_ORDER: AgentTeamId[] = ["analysts", "research", "risk", "execution"];

type OperatorActivityState = "queued" | "running" | "saved" | "local" | "failed";

type OperatorActivity = {
  id: string;
  agentName: string;
  agentClass: TradingAgentDescriptor["agentClass"];
  label: string;
  state: OperatorActivityState;
  detail: string;
};

type AgentDetailView = "agent" | "system" | "process" | null;

// NOTE: The Agent Builder surface was removed in the 4-tab IA flattening
// (2026-05-20). The `onOpenBuilder` prop is gone and any builder hand-off
// from this component is intentionally a no-op until a successor surface
// is introduced. The component itself is no longer routed to from the
// MarketShell but is kept for the test contract and the Quant scaffolding
// the parallel agent is building.
export function AgentsWorkspace({ symbol }: { symbol: string }) {
  const onOpenBuilder = () => {
    // Builder removed in the 4-tab IA flattening; no-op placeholder so any
    // residual handler call sites compile while the replacement is designed.
  };
  const [selectedAgentId, setSelectedAgentId] = useState(TRADING_AGENT_REGISTRY[0].id);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [runId, setRunId] = useState<string | null>(null);
  const [preview, setPreview] = useState<OrderPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [selectedReportId, setSelectedReportId] = useState<string | null>(null);
  const [runtimeStatus, setRuntimeStatus] = useState<RuntimeStatus | null>(null);
  const [operatorActivities, setOperatorActivities] = useState<OperatorActivity[]>([]);
  const [detailView, setDetailView] = useState<AgentDetailView>(null);
  const requestIdRef = useRef(0);
  const selectedAgent =
    TRADING_AGENT_REGISTRY.find((agent) => agent.id === selectedAgentId) ?? TRADING_AGENT_REGISTRY[0];
  const actionPlan = getAgentActionPlan(selectedAgent);
  const researchCount = TRADING_AGENT_REGISTRY.filter((agent) => agent.agentClass === "research").length;
  const executionCount = TRADING_AGENT_REGISTRY.filter((agent) => agent.agentClass === "execution").length;
  const decisionEvent = events.find((event) => event.type === "decision.created");
  const reportEvents = events.filter((event) => event.type === "report.updated");
  const agentReports = deriveAgentReports(events);
  const activePreview = preview?.symbol === symbol ? preview : null;
  const agentsByTeam = useMemo(
    () =>
      Object.fromEntries(TEAM_ORDER.map((teamId) => [teamId, getTradingAgentsByTeam(teamId)])) as Record<
        AgentTeamId,
        TradingAgentDescriptor[]
      >,
    []
  );
  const researchAgentGroups = useMemo(
    () => TEAM_ORDER.map((teamId) => ({ teamId, agents: getTradingAgentsByTeam(teamId).filter((agent) => agent.agentClass === "research") }))
      .filter((group) => group.agents.length > 0),
    []
  );
  const executionAgentGroups = useMemo(
    () => TEAM_ORDER.map((teamId) => ({ teamId, agents: getTradingAgentsByTeam(teamId).filter((agent) => agent.agentClass === "execution") }))
      .filter((group) => group.agents.length > 0),
    []
  );
  // narrativeCards removed in the v2 IA cleanup.

  useEffect(() => {
    requestIdRef.current += 1;
    setEvents([]);
    setRunId(null);
    setPreview(null);
    setError(null);
    setIsRunning(false);
    setSelectedReportId(null);
    setOperatorActivities([]);

    return undefined;
  }, [symbol]);

  useEffect(() => {
    let cancelled = false;
    getRuntimeStatus()
      .then((status) => {
        if (!cancelled) {
          setRuntimeStatus(status);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setRuntimeStatus(null);
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  async function startRun() {
    if (!actionPlan.canRun) {
      queueLocalActivity(
        selectedAgent,
        "Builder handoff queued",
        "local",
        `${selectedAgent.name} opened in Agent Builder for local editing.`
      );
      onOpenBuilder();
      return;
    }

    if (actionPlan.primaryAction === "Preview execution") {
      await previewExecution(selectedAgent);
      return;
    }

    const requestedSymbol = symbol;
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    const activityId = queueLocalActivity(
      selectedAgent,
      `${selectedAgent.name} research run`,
      "queued",
      `${requestedSymbol} research run queued locally.`
    );

    setError(null);
    setEvents([]);
    setRunId(null);
    setPreview(null);
    setSelectedReportId(null);
    setIsRunning(true);

    try {
      const operationRef = await createVisibleAgentOperation(selectedAgent, activityId, "research_report");
      updateLocalActivity(
        activityId,
        "running",
        operationRef
          ? `Agent operation ${operationRef} saved; running approval-gated research for ${requestedSymbol}.`
          : `Backend agent operations are unavailable; running ${requestedSymbol} research with local queue state.`
      );
      const created = await createRun({
        brokerMode: "paper",
        executionMode: "real",
        ticker: requestedSymbol,
        tradeDate: new Date().toISOString().slice(0, 10)
      });
      if (requestIdRef.current !== requestId) return;
      setRunId(created.run_id);

      const nextEvents = await waitForRunEvents(created.run_id, {
        onEvents: (polledEvents) => {
          if (requestIdRef.current !== requestId) return;
          setEvents(polledEvents);
          setSelectedReportId(deriveAgentReports(polledEvents)[0]?.id ?? null);
        }
      });
      if (requestIdRef.current !== requestId) return;
      setSelectedReportId(deriveAgentReports(nextEvents)[0]?.id ?? null);
      setEvents(nextEvents);

      if (isTerminalRun(nextEvents, "run.completed")) {
        const tradePreview = await previewTrade({
          notional: 1000,
          runId: created.run_id,
          side: "buy",
          symbol: requestedSymbol
        });
        if (requestIdRef.current !== requestId) return;
        setPreview(tradePreview);
        if (operationRef) {
          await completeAgentOperation(operationRef, {
            linkedRunId: created.run_id,
            payload: {
              intent_id: tradePreview.intent_id,
              paper_preview_ready: true,
              source: "agents_workspace"
            }
          });
        }
        updateLocalActivity(activityId, "saved", `Research completed for ${requestedSymbol}; paper preview is available.`);
      }
    } catch (caught) {
      if (requestIdRef.current !== requestId) return;
      setError(caught instanceof Error ? caught.message : "Run failed");
      updateLocalActivity(activityId, "failed", caught instanceof Error ? caught.message : "Run failed");
    } finally {
      if (requestIdRef.current === requestId) {
        setIsRunning(false);
      }
    }
  }

  async function previewExecution(agent: TradingAgentDescriptor) {
    const activityId = queueLocalActivity(
      agent,
      `${agent.name} execution preview`,
      "queued",
      `${symbol} paper execution review queued locally.`
    );
    setError(null);
    setIsRunning(true);

    try {
      const operationRef = await createVisibleAgentOperation(agent, activityId, "execution_preview");
      if (operationRef) {
        await completeAgentOperation(operationRef, {
          payload: {
            source: "agents_workspace",
            status: "paper_execution_review_ready"
          }
        });
      }
      updateLocalActivity(
        activityId,
        operationRef ? "saved" : "local",
        operationRef
          ? `Agent operation ${operationRef} saved for an approval-gated paper execution review.`
          : "Backend agent operations are unavailable; this paper execution review remains in the local queue."
      );
    } catch (caught) {
      updateLocalActivity(activityId, "failed", caught instanceof Error ? caught.message : "Execution preview failed");
    } finally {
      setIsRunning(false);
    }
  }

  async function createVisibleAgentOperation(
    agent: TradingAgentDescriptor,
    activityId: string,
    operationType: "research_report" | "execution_preview"
  ): Promise<string | null> {
    try {
      const operation = await createAgentOperation({
        agentId: agent.id,
        agentName: agent.name,
        authority: agent.agentClass === "execution" ? "approval_required" : "research_only",
        operationType,
        payload: {
          agent_class: agent.agentClass,
          authority_label: formatAgentAuthority(agent),
          current_state: formatStatus(agent.runtimeStatus),
          local_activity_id: activityId,
          source: "agents_workspace",
          workspace: "agents"
        },
        roomId: agent.agentClass === "execution" ? "market" : "research",
        symbol
      });
      return operation.operation_id;
    } catch {
      return null;
    }
  }

  function queueLocalActivity(
    agent: TradingAgentDescriptor,
    label: string,
    state: OperatorActivityState,
    detail: string
  ): string {
    const id = `${agent.id}-${Date.now()}-${requestIdRef.current}`;
    setOperatorActivities((current) => [
      {
        agentClass: agent.agentClass,
        agentName: agent.name,
        detail,
        id,
        label,
        state
      },
      ...current.slice(0, 5)
    ]);
    return id;
  }

  function updateLocalActivity(id: string, state: OperatorActivityState, detail: string) {
    setOperatorActivities((current) =>
      current.map((activity) => (activity.id === id ? { ...activity, detail, state } : activity))
    );
  }

  return (
    <section className="room-workspace-root" aria-label="TradingAgents console">
      <header className="workspace-header agents-header">
        <div>
          <span className="panel-kicker">Studio · Agents</span>
          <h1>
            <em>{symbol}</em> agent desk
          </h1>
        </div>
        <div className="agents-header-actions">
          <button className="primary-button compact" type="button" onClick={startRun} disabled={isRunning}>
            {isRunning ? "Running..." : actionPlan.primaryAction}
          </button>
          {/* "Open builder" button removed in the 4-tab IA flattening (2026-05-20). */}
        </div>
      </header>

      <section className="agents-workspace trading-agents-console">
        <aside className="agents-conversation-rail trading-agent-rail">
        <header className="panel-header">
          <div>
            <span className="panel-kicker">Agent registry</span>
            <h2>TradingAgents</h2>
          </div>
          <span className="panel-count">{TRADING_AGENT_REGISTRY.length}</span>
        </header>
        <div className="agent-registry-list">
          {TEAM_ORDER.map((teamId) => (
            <section className="agent-team-section" key={teamId}>
              <div className="agent-team-heading">
                <strong>{AGENT_TEAM_LABELS[teamId]}</strong>
                <span>{agentsByTeam[teamId].length}</span>
              </div>
              {agentsByTeam[teamId].map((agent) => (
                <button
                  aria-label={`${agent.name}: ${agent.purpose}`}
                  className={agent.id === selectedAgent.id ? "agent-registry-item selected" : "agent-registry-item"}
                  key={agent.id}
                  onClick={() => setSelectedAgentId(agent.id)}
                  type="button"
                >
                  <span>
                    <strong>{agent.name}</strong>
                  </span>
                  <AgentStatus status={agent.runtimeStatus} />
                </button>
              ))}
            </section>
          ))}
        </div>
        </aside>

        <article className="agents-message-stream trading-agent-canvas">
        <header className="message-stream-header private-message-header">
          <div>
            <span className="panel-kicker">Advisory surface</span>
            <h1>{symbol} agent advice</h1>
          </div>
          <span className={isRunning ? "run-state running" : events.length > 0 ? "run-state complete" : "run-state"}>
            {isRunning ? "Running" : events.length > 0 ? "Complete" : "Idle"}
          </span>
        </header>

        <section className="advisor-hero-panel">
          <div>
            <span className="panel-kicker">{AGENT_TEAM_LABELS[selectedAgent.teamId]}</span>
            <h2>{selectedAgent.name}</h2>
            <p>{actionPlan.helperText}</p>
          </div>
          <div className="advisor-hero-actions">
            <button className="primary-button" type="button" onClick={startRun} disabled={isRunning}>
              {isRunning ? "Running..." : actionPlan.primaryAction}
            </button>
            <button className="secondary-button" onClick={() => setDetailView("agent")} type="button">
              Why this agent
            </button>
          </div>
        </section>
        {runId ? <p className="run-id">Run {runId}</p> : null}
        {error ? <p className="error">{error}</p> : null}

        <section className="advisor-system-links" aria-label="Agent system details">
          <button className="secondary-button compact" onClick={() => setDetailView("system")} type="button">
            System wiring
          </button>
          <button className="secondary-button compact" onClick={() => setDetailView("process")} type="button">
            View process
          </button>
          <small>
            {researchCount} research agents / {executionCount} execution agents / {events.length} visible events
          </small>
        </section>

        <section className="agent-report-panel advisor-report-card">
          <header>
            <div>
              <span className="panel-kicker">Final report</span>
              <h2>{formatDecisionTitle(decisionEvent)}</h2>
            </div>
            <span className="panel-count">{reportEvents.length} updates</span>
          </header>
          <p>{formatDecisionBody(decisionEvent)}</p>
          {decisionEvent?.payload.risk_notes ? (
            <div className="agent-report-risk">
              <span>Risk notes</span>
              <p>{englishOrNotice(String(decisionEvent.payload.risk_notes))}</p>
            </div>
          ) : null}
        </section>

        {agentReports.length > 0 ? (
          <AgentReportsPanel
            reports={agentReports}
            selectedReportId={selectedReportId}
            onSelectReport={setSelectedReportId}
          />
        ) : null}

        <section className="agent-report-panel compact-activity-panel" aria-label="Agent operations queue">
          <div className="section-title">
            <span>Activity needing attention</span>
            <strong>{operatorActivities.length}</strong>
          </div>
          {operatorActivities.length > 0 ? (
            operatorActivities.slice(0, 3).map((activity) => (
              <article className="activity-row" key={activity.id}>
                <div>
                  <strong>{activity.label}</strong>
                  <small>
                    {activity.agentName} - {formatActivityState(activity.state)}
                  </small>
                </div>
                <span>{activity.agentClass === "research" ? "Research" : "Execution"}</span>
              </article>
            ))
          ) : (
            <p>No queued agent work. Select an agent and run a report when you want advice.</p>
          )}
        </section>

        {detailView === "system" ? (
          <InfoModal title="Agent system wiring" onClose={() => setDetailView(null)}>
            <section className="agent-runtime-summary">
              <div>
                <span>Research Agents</span>
                <strong>{researchCount}</strong>
              </div>
              <div>
                <span>Execution Agents</span>
                <strong>{executionCount}</strong>
              </div>
              <div>
                <span>Visible events</span>
                <strong>{events.length}</strong>
              </div>
            </section>
            <section className="agent-runner-mode-panel" aria-label="TradingAgents runner mode">
              <div>
                <span className="panel-kicker">Full TradingAgents graph</span>
                <strong>{formatFullGraphStatus(runtimeStatus)}</strong>
                <p>{formatRunnerMode(runtimeStatus)}</p>
              </div>
              <small>TRADEMASTER_ENABLE_REAL_RUNS=1</small>
            </section>
            <section className="agent-architecture-note">
              <div>
                <span className="panel-kicker">Research lane</span>
                <strong>Flexible LLM agents</strong>
                <p>
                  TradingAgents analysts, researchers, and synthesis roles can use OpenAI-style research models through
                  LangGraph and LangChain tools.
                </p>
              </div>
              <div>
                <span className="panel-kicker">Execution lane</span>
                <strong>Deterministic and symbolic agents</strong>
                <p>
                  Broker-facing agents use Mistral Medium 3.5, Alpaca adapters, and PyReason temporal rules before any
                  order is allowed.
                </p>
              </div>
            </section>
            <section className="agent-class-lanes" aria-label="Research and execution agents">
              <AgentClassLane
                groups={researchAgentGroups}
                onSelectAgent={setSelectedAgentId}
                selectedAgentId={selectedAgent.id}
                title="Research Agents"
              />
              <AgentClassLane
                groups={executionAgentGroups}
                onSelectAgent={setSelectedAgentId}
                selectedAgentId={selectedAgent.id}
                title="Execution Agents"
              />
            </section>
          </InfoModal>
        ) : null}

        {detailView === "process" ? (
          <InfoModal title="Run process" onClose={() => setDetailView(null)}>
            <AgentRunGraph events={events} />
            <section className="cockpit-section agent-visible-trace">
              <div className="section-title">
                <span>Execution trace</span>
                <strong>{events.length}</strong>
              </div>
              <RunTimeline events={events} />
            </section>
          </InfoModal>
        ) : null}
        </article>

        <aside className="agents-action-panel agent-operator-panel">
        <section className="selected-agent-panel">
          <header>
            <div>
              <span className="panel-kicker">Selected advisor</span>
              <h2>{selectedAgent.name}</h2>
            </div>
            <AgentStatus status={selectedAgent.runtimeStatus} />
          </header>
          <p>{selectedAgent.purpose}</p>
          <div className="advisor-action-stack">
            <button className="primary-button" type="button" onClick={startRun} disabled={isRunning}>
              {isRunning ? "Running..." : actionPlan.primaryAction}
            </button>
            <button className="secondary-button" onClick={() => setDetailView("agent")} type="button">
              Agent profile
            </button>
          </div>
        </section>

        {/* Builder handoff panel removed in the 4-tab IA flattening (2026-05-20). */}

        {activePreview ? <TradeTicket key={activePreview.intent_id} preview={activePreview} /> : null}

        {detailView === "agent" ? (
          <InfoModal title={`${selectedAgent.name} profile`} onClose={() => setDetailView(null)}>
            <section className="selected-agent-panel">
              <header>
                <div>
                  <span className="panel-kicker">{AGENT_TEAM_LABELS[selectedAgent.teamId]}</span>
                  <h2>{selectedAgent.name}</h2>
                </div>
                <AgentStatus status={selectedAgent.runtimeStatus} />
              </header>
              <p>{selectedAgent.purpose}</p>
              <dl className="agent-detail-list">
                <div>
                  <dt>Class</dt>
                  <dd>{selectedAgent.agentClass === "research" ? "Research Agent" : "Execution Agent"}</dd>
                </div>
                <div>
                  <dt>Authority</dt>
                  <dd>{formatAgentAuthority(selectedAgent)}</dd>
                </div>
                <div>
                  <dt>LLM mode</dt>
                  <dd>{selectedAgent.llmMode}</dd>
                </div>
                <div>
                  <dt>Framework</dt>
                  <dd>{selectedAgent.framework}</dd>
                </div>
                <div>
                  <dt>Safety</dt>
                  <dd>{selectedAgent.safetyProfile}</dd>
                </div>
              </dl>
              <div className="agent-io-grid">
                <AgentList title="Inputs" items={selectedAgent.inputs} />
                <AgentList title="Outputs" items={selectedAgent.outputs} />
              </div>
            </section>
          </InfoModal>
        ) : null}
        </aside>
      </section>
    </section>
  );
}

function AgentStatus({ status }: { status: TradingAgentDescriptor["runtimeStatus"] }) {
  return <span className={`agent-runtime-status ${status}`}>{formatStatus(status)}</span>;
}

function AgentClassLane({
  groups,
  onSelectAgent,
  selectedAgentId,
  title
}: {
  groups: { teamId: AgentTeamId; agents: TradingAgentDescriptor[] }[];
  onSelectAgent: (agentId: string) => void;
  selectedAgentId: string;
  title: "Research Agents" | "Execution Agents";
}) {
  return (
    <section className="agent-team-section">
      <div className="agent-team-heading">
        <strong>{title}</strong>
        <span>{groups.reduce((count, group) => count + group.agents.length, 0)}</span>
      </div>
      <div className="agent-registry-list">
        {groups.map((group) => (
          <div className="agent-io-grid" key={group.teamId}>
            {group.agents.map((agent) => (
              <button
                className={agent.id === selectedAgentId ? "agent-topology-card selected" : "agent-topology-card"}
                key={agent.id}
                onClick={() => onSelectAgent(agent.id)}
                type="button"
              >
                <span>Role</span>
                <strong>{agent.name}</strong>
                <small>{AGENT_TEAM_LABELS[agent.teamId]}</small>
                <span>Authority</span>
                <small>{formatAgentAuthority(agent)}</small>
                <span>Current state</span>
                <AgentStatus status={agent.runtimeStatus} />
              </button>
            ))}
          </div>
        ))}
      </div>
    </section>
  );
}

function AgentList({ title, items }: { title: string; items: string[] }) {
  return (
    <div>
      <strong>{title}</strong>
      <ul>
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

function formatDecisionTitle(event: RunEvent | undefined): string {
  const rating = typeof event?.payload.rating === "string" ? event.payload.rating : null;
  const action = typeof event?.payload.action === "string" ? event.payload.action : null;

  return rating && action ? `${rating} / ${action}` : "No completed report yet";
}

function formatDecisionBody(event: RunEvent | undefined): string {
  return typeof event?.payload.thesis === "string"
    ? englishOrNotice(event.payload.thesis)
    : "Run an active TradingAgents role to populate the final report, event trace, and approval-gated paper trade preview.";
}

function formatFullGraphStatus(status: RuntimeStatus | null): string {
  if (!status) return "Checking";
  return status.full_tradingagents_graph.enabled ? "Enabled" : "Safe mode";
}

function formatRunnerMode(status: RuntimeStatus | null): string {
  if (!status) return "Loading runtime wiring.";
  if (status.full_tradingagents_graph.enabled) {
    return `Reports are generated by ${status.research_runner.mode} using ${status.research_llm.provider_id}.`;
  }

  return `Reports are using ${status.research_runner.mode}. Restart with the full graph flag when provider routing is ready.`;
}

function formatAgentAuthority(agent: TradingAgentDescriptor): string {
  if (agent.agentClass === "research") {
    return "Research and recommendation only; no broker authority.";
  }

  if (agent.runtimeStatus === "active") {
    return "Paper preview and approval review only; broker action remains blocked.";
  }

  return "Design-time execution policy only until wired.";
}

function formatActivityState(state: OperatorActivityState): string {
  if (state === "queued") return "Queued";
  if (state === "running") return "Running";
  if (state === "saved") return "Saved";
  if (state === "local") return "Local fallback";

  return "Failed";
}

function isTerminalRun(events: RunEvent[], terminalType: "run.completed" | "run.failed"): boolean {
  return events.some((event) => event.type === terminalType);
}

function formatStatus(status: TradingAgentDescriptor["runtimeStatus"]): string {
  if (status === "active") return "Active";
  if (status === "framework") return "Builder";

  return "Planned";
}
