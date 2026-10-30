import { englishOrNotice } from "./language.ts";
import type { RunEvent } from "./types";

export type AgentReport = {
  advisoryLabel: "Advisory research - not an order";
  id: string;
  agentName: string;
  body: string;
  createdAt: string;
  section: string;
  sourceLabel: "Deterministic fallback" | "LLM synthesis";
};

export function deriveAgentReports(events: RunEvent[]): AgentReport[] {
  return events
    .filter((event) => event.type === "report.updated")
    .map((event, index) => {
      const section = stringPayload(event, "section") ?? event.node ?? "report";
      return {
        advisoryLabel: "Advisory research - not an order",
        id: `${event.run_id}-${index}-${section}`,
        agentName: event.node ?? "TradingAgents",
        body: englishOrNotice(reportBody(event)),
        createdAt: event.created_at,
        section,
        sourceLabel: event.payload.fallback === true ? "Deterministic fallback" : "LLM synthesis"
      };
    });
}

function reportBody(event: RunEvent): string {
  return (
    stringPayload(event, "report") ??
    stringPayload(event, "thesis") ??
    stringPayload(event, "risk_notes") ??
    stringPayload(event, "rationale") ??
    event.message
  );
}

function stringPayload(event: RunEvent, key: string): string | null {
  const value = event.payload[key];
  return typeof value === "string" && value.trim() ? value.trim() : null;
}
