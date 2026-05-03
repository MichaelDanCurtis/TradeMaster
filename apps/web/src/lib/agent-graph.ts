import type { RunEvent } from "./types";

export type AgentGraphStatus = "complete" | "failed" | "idle" | "running" | "waiting";

export type AgentGraphNode = {
  id: string;
  label: string;
  detail: string;
  status: AgentGraphStatus;
};

const AGENT_GRAPH_TEMPLATE: AgentGraphNode[] = [
  { detail: "Queued", id: "start", label: "Run", status: "idle" },
  { detail: "OHLCV and indicators", id: "market", label: "Market", status: "idle" },
  { detail: "Headlines and filings", id: "news", label: "News", status: "idle" },
  { detail: "Sentiment scan", id: "social", label: "Social", status: "idle" },
  { detail: "Financial context", id: "fundamentals", label: "Fundamentals", status: "idle" },
  { detail: "Bull/bear synthesis", id: "research", label: "Research", status: "idle" },
  { detail: "Risk debate", id: "risk", label: "Risk", status: "idle" },
  { detail: "Decision", id: "portfolio", label: "Portfolio", status: "idle" },
  { detail: "Approval required", id: "broker", label: "Broker", status: "idle" },
  { detail: "Final report", id: "completed", label: "Done", status: "idle" }
];

const NODE_TO_ID: Record<string, string> = {
  Broker: "broker",
  "Fundamentals Analyst": "fundamentals",
  "Market Analyst": "market",
  "News Analyst": "news",
  "Portfolio Manager": "portfolio",
  "Research Manager": "research",
  "Risk Manager": "risk",
  "Social Analyst": "social"
};

export function deriveAgentGraphNodes(events: RunEvent[]): AgentGraphNode[] {
  const nodes = AGENT_GRAPH_TEMPLATE.map((node) => ({ ...node }));
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const latestEvents = [...events].sort((a, b) => a.sequence - b.sequence);

  for (const event of latestEvents) {
    if (event.type === "run.created" || event.type === "run.started") {
      updateNode(byId, "start", "complete", "Started");
      continue;
    }

    if (event.type === "run.failed") {
      updateNode(byId, "completed", "failed", "Failed");
      continue;
    }

    if (event.type === "run.completed") {
      updateNode(byId, "completed", "complete", "Completed");
      continue;
    }

    if (event.type === "trade.previewed") {
      updateNode(byId, "broker", "waiting", "Paper ticket ready");
      continue;
    }

    if (!event.node) continue;

    const nodeId = NODE_TO_ID[event.node];
    if (!nodeId) continue;

    if (event.type === "agent.started") {
      updateNode(byId, nodeId, "running", "Running");
    } else if (event.type === "tool.called") {
      updateNode(byId, nodeId, "running", "Calling tool");
    } else if (event.type === "report.updated") {
      updateNode(byId, nodeId, "complete", "Updated report");
    } else if (event.type === "decision.created") {
      updateNode(byId, nodeId, "complete", "Decision ready");
    }
  }

  return nodes;
}

function updateNode(
  nodes: Map<string, AgentGraphNode>,
  id: string,
  status: AgentGraphStatus,
  detail: string
): void {
  const node = nodes.get(id);

  if (!node) return;

  node.status = status;
  node.detail = detail;
}
