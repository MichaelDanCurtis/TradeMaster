"use client";

import { AgentCockpit } from "@/components/AgentCockpit";
import { ChartWorkspace } from "@/components/ChartWorkspace";
import { getDashboardNewsEvents } from "@/lib/workspace-data";

export function DashboardWorkspace({ symbol }: { symbol: string }) {
  return (
    <section className="dashboard-workspace" aria-label="Market context workspace">
      <ChartWorkspace newsEvents={getDashboardNewsEvents(symbol)} symbol={symbol} />
      <AgentCockpit symbol={symbol} />
    </section>
  );
}
