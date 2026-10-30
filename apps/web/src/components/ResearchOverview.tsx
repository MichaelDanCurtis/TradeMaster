"use client";

import { useEffect, useState } from "react";
import { apiBase } from "@/lib/api";
import { evidenceLabel, type ResearchProvider, type ResearchRuntime } from "@/lib/research-api";

type Overview = {
  as_of: string; limit: number; runtime: ResearchRuntime; providers: ResearchProvider[];
  experiment_states: Record<string, number>;
  experiments: { experiment_id: string; strategy_id: string; name: string; state: string; evidence_kind: string; evidence_status: string | null; updated_at: string; data_gaps: string[]; message: string }[];
  deployments: { deployment_id: string; name: string; state: string; has_committed_funding: boolean; updated_at: string }[];
  accounts: { account_id: string; provider_id: string; state: string; observed_at: string | null; evidence_kind: string | null; discrepancies: number | null }[];
  budgets: { family_id: string; strategy_id: string; name: string; trials_used: number; max_trials: number; charged_cost_usd: string; budget_usd: string; remaining_usd: string; exhausted: boolean }[];
  totals: { experiments: number; deployments_needing_review: number; families: number; accounts: number };
  data_capabilities: { name: string; status: string; detail: string }[];
};

function useOverview(room: "dashboard" | "settings") {
  const [data, setData] = useState<Overview | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function load() {
      setLoading(true);
      try {
        const response = await fetch(`${apiBase()}/api/research/overview`, {
          headers: { "X-Trademaster-Room": room }, signal: controller.signal, cache: "no-store"
        });
        if (!response.ok) throw new Error(`Research overview unavailable (${response.status})`);
        const result = await response.json() as Overview;
        if (!controller.signal.aborted) { setData(result); setError(""); }
      } catch (caught) {
        if (!controller.signal.aborted) setError(caught instanceof Error ? caught.message : "Research overview unavailable");
      } finally {
        if (!controller.signal.aborted) { setLoading(false); timer = setTimeout(load, 30000); }
      }
    }
    void load();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [room, revision]);
  return { data, error, loading, refresh: () => setRevision((value) => value + 1) };
}

const dateLabel = (value: string | null) => value ? new Date(value).toLocaleString() : "Not observed";
const dollars = (value: string) => Number(value).toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 6 });

function ReadState({ data, error, loading, refresh }: ReturnType<typeof useOverview>) {
  return <>
    {error ? <p role="alert">{error}. {data ? "Showing the last successful read below." : "Saved records have not been loaded."}</p> : null}
    {loading && !data ? <p role="status">Loading saved research status…</p> : null}
    <div className="research-overview-actions"><span>{data ? `Read ${dateLabel(data.as_of)}` : "No status received"}</span>
      <button type="button" className="secondary-button compact" disabled={loading} onClick={refresh}>Refresh research status</button></div>
  </>;
}

export function BriefResearchOverview({ onOpenResearch, onOpenQuant, onOpenPerformance }: {
  onOpenResearch: () => void; onOpenQuant?: () => void; onOpenPerformance?: () => void;
}) {
  const state = useOverview("dashboard");
  const data = state.data;
  return <section className="research-overview brief-panel" aria-label="Strategy research briefing">
    <header><span className="panel-kicker">Research and paper oversight</span><h2>What needs your attention</h2></header>
    <ReadState {...state}/>
    {data ? <>
      {!data.runtime.available && (data.experiment_states.queued ?? 0) > 0 ? <p className="research-overview-alert">{data.experiment_states.queued} experiment(s) waiting. No recent research worker heartbeat.</p> : null}
      <div className="research-overview-grid">
        <section><h3>Recent experiments</h3>
          {data.experiments.length ? <ul>{data.experiments.slice(0, 5).map((row) => <li key={row.experiment_id}>
            <strong>{row.name}</strong><span>{evidenceLabel(row.state)} · {evidenceLabel(row.evidence_kind)}{row.evidence_status ? ` · ${evidenceLabel(row.evidence_status)}` : ""}</span>
            <p>{row.message}</p>{row.data_gaps.length ? <p>Evidence gaps: {row.data_gaps.map(evidenceLabel).join(", ")}.</p> : null}
            <small>{dateLabel(row.updated_at)}</small>
          </li>)}</ul> : <p>No experiments yet. A saved hypothesis is the starting point.</p>}
          {data.totals.experiments > 5 ? <p>Showing the latest 5 of {data.totals.experiments}. Research retains every attempt.</p> : null}
          <button type="button" className="secondary-button compact" onClick={onOpenResearch}>Open strategy research</button>
        </section>
        <section><h3>Deployment reviews</h3>
          {data.deployments.length ? <ul>{data.deployments.slice(0, 5).map((row) => <li key={row.deployment_id}>
            <strong>{row.name}</strong><span>{evidenceLabel(row.state)} · {row.has_committed_funding ? "Committed allocation retained" : "No committed funding"}</span>
          </li>)}</ul> : <p>No saved deployments awaiting review.</p>}
          {data.totals.deployments_needing_review > 5 ? <p>{data.totals.deployments_needing_review} deployments need review; showing the latest 5.</p> : null}
          {onOpenQuant ? <button type="button" className="secondary-button compact" onClick={onOpenQuant}>Review deployments in Quant</button> : null}
          <h3>Account observations</h3>
          {data.accounts.length ? <ul>{data.accounts.map((row) => <li key={`${row.provider_id}:${row.account_id}`}>
            <strong>{row.account_id}</strong><span>{evidenceLabel(row.state)} · {row.evidence_kind ? evidenceLabel(row.evidence_kind) : "No observation evidence"}</span>
            {row.discrepancies ? <p>{row.discrepancies} reconciliation discrepancy(s).</p> : null}<small>{dateLabel(row.observed_at)}</small>
          </li>)}</ul> : <p>No paper-account baseline has been enrolled.</p>}
          {data.totals.accounts > data.accounts.length ? <p>Showing {data.accounts.length} of {data.totals.accounts} enrolled accounts.</p> : null}
          {onOpenPerformance ? <button type="button" className="secondary-button compact" onClick={onOpenPerformance}>Inspect accounting in Performance</button> : null}
        </section>
      </div>
      <p className="research-overview-note">Saved observations describe their recorded time. A completed experiment does not approve a strategy or an order.</p>
    </> : null}
  </section>;
}

export function ResearchSystemStatus() {
  const state = useOverview("settings");
  const data = state.data;
  return <section className="research-overview settings-panel" aria-label="Quant research resources">
    <header><span className="settings-panel-kicker">Executable strategy research</span><h3>Quant worker, data and budgets</h3></header>
    <ReadState {...state}/>
    {data ? <>
      <p>{data.runtime.message} Queued experiments: {data.runtime.queued}.</p>
      <ul>{data.runtime.engine_capabilities?.map((engine) => <li key={engine.engine}><strong>{evidenceLabel(engine.engine)} · {engine.available ? "Engine available" : "Engine unavailable"}</strong><span>{engine.message}</span></li>)}</ul>
      <div className="research-overview-grid"><section><h4>Model roles</h4><ul>{data.providers.map((provider) => <li key={provider.role}>
        <strong>{evidenceLabel(provider.role)} · {provider.available ? "Configured" : "Needs configuration"}</strong>
        {provider.model_id ? <span>{provider.provider_id} · {provider.model_id}</span> : null}<p>{provider.message}</p>
      </li>)}</ul><p>Configuration is checked locally. Credentials and frozen model versions are checked again before a budgeted call.</p></section>
      <section><h4>Data capabilities</h4><ul>{data.data_capabilities.map((item) => <li key={item.name}><strong>{item.name} · {evidenceLabel(item.status)}</strong><p>{item.detail}</p></li>)}</ul></section></div>
      <h4>Research family budgets</h4>
      {data.budgets.length ? <div className="research-overview-table"><table><thead><tr><th>Strategy / family</th><th>Trials used</th><th>Charged / reserved</th><th>Budget remaining</th><th>Status</th></tr></thead><tbody>{data.budgets.map((row) => <tr key={row.family_id}>
        <td>{row.name}<details><summary>Family reference</summary><code>{row.family_id}</code></details></td><td>{row.trials_used} / {row.max_trials}</td><td>{dollars(row.charged_cost_usd)}</td><td>{dollars(row.remaining_usd)} of {dollars(row.budget_usd)}</td><td>{row.exhausted ? "Budget exhausted" : "Within budget"}</td>
      </tr>)}</tbody></table></div> : <p>No research-family budget has been frozen yet.</p>}
      {data.totals.families > data.budgets.length ? <p>Showing {data.budgets.length} of {data.totals.families} families. Open Research for the complete strategy history.</p> : null}
      <p className="research-overview-note">Metered charges include retained reservations and designer calls. They are not provider invoices. Change a hypothesis or plan in Research; this view grants no execution authority.</p>
    </> : null}
  </section>;
}
