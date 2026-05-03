import { deriveAgentGraphNodes } from "@/lib/agent-graph";
import type { RunEvent } from "@/lib/types";

export function AgentRunGraph({ events }: { events: RunEvent[] }) {
  const nodes = deriveAgentGraphNodes(events);

  return (
    <section className="agent-graph-panel">
      <div className="section-title">
        <span>Agent map</span>
        <strong>{nodes.filter((node) => node.status === "complete").length}</strong>
      </div>
      <div className="agent-graph" aria-label="TradingAgents execution graph">
        {nodes.map((node, index) => (
          <div className="agent-graph-step" key={node.id}>
            <article className={`agent-node ${node.status}`}>
              <span className="agent-node-status" />
              <strong>{node.label}</strong>
              <small>{node.detail}</small>
            </article>
            {index < nodes.length - 1 ? <span className={`agent-edge ${node.status}`} /> : null}
          </div>
        ))}
      </div>
    </section>
  );
}
