"use client";

import { useEffect, useState } from "react";
import { listDeploymentPerformance, type DeploymentPerformanceReport } from "@/lib/accounting";

const money=(value:string|null|undefined)=>value==null ? "Unavailable" : Number(value).toLocaleString("en-US",{style:"currency",currency:"USD",maximumFractionDigits:6});
const percent=(value:string|null|undefined)=>value==null ? "Unavailable" : `${(Number(value)*100).toLocaleString("en-US",{maximumFractionDigits:4})}%`;
const date=(value:string)=>new Date(value).toLocaleString();

export function DeploymentPerformancePanel({accountKey,refreshKey}:{accountKey:string;refreshKey?:string}) {
  const [report,setReport]=useState<DeploymentPerformanceReport|null>(null);
  const [error,setError]=useState("");
  const [selected,setSelected]=useState("");
  const [loading,setLoading]=useState(true);
  const [refresh,setRefresh]=useState(0);
  useEffect(()=>{
    const controller=new AbortController();setLoading(true);setError("");
    listDeploymentPerformance(accountKey,controller.signal).then((value)=>{
      if(controller.signal.aborted)return;
      setReport(value);setSelected((current)=>value.deployments.some((d)=>d.deployment_id===current)?current:value.deployments[0]?.deployment_id??"");
    }).catch((e)=>{if(!controller.signal.aborted)setError(e instanceof Error?e.message:"Deployment performance unavailable");})
      .finally(()=>{if(!controller.signal.aborted)setLoading(false);});
    return ()=>controller.abort();
  },[accountKey,refreshKey,refresh]);
  const deployment=report?.deployments.find((d)=>d.deployment_id===selected);
  const performance=deployment?.performance;
  return <section className="paper-accounting-card" aria-label="Deployment performance">
    <h2>Deployment capital and returns</h2>
    <p>Each deployment has an internal cash allocation, owned positions, and attributed profit or loss. Account deposits stay unallocated until a funding approval assigns capital.</p>
    <button type="button" className="secondary-button" disabled={loading} onClick={()=>setRefresh((n)=>n+1)}>Refresh deployment returns</button>
    {loading?<p role="status">Loading deployment accounting…</p>:null}
    {error?<p role="alert">{error}</p>:null}
    {!loading&&!error&&!report?.deployments.length?<p>No deployments in this account.</p>:null}
    {report?.deployments.length?<label className="paper-accounting-select">Deployment return history<select value={selected} onChange={(e)=>setSelected(e.target.value)}>{report.deployments.map((d)=><option value={d.deployment_id} key={d.deployment_id}>{d.name} · {d.state.replaceAll("_"," ")}</option>)}</select></label>:null}
    {performance&&deployment?<>
      <p><strong>{performance.status.replaceAll("_"," ")}</strong>{report?.observed_at?` · account observed ${date(report.observed_at)}`:""}. {performance.closed?"The capital allocation has been closed.":""}</p>
      <dl className="paper-accounting-metrics">
        <div><dt>Deployment equity</dt><dd>{money(performance.equity_usd)}</dd></div>
        <div><dt>Attributed cash</dt><dd>{money(performance.cash_usd)}</dd></div>
        <div><dt>Owned positions</dt><dd>{money(performance.market_value_usd)}</dd></div>
        <div><dt>Investment P&amp;L</dt><dd>{money(performance.investment_pnl_usd)}</dd></div>
        <div><dt>Time-weighted return</dt><dd>{percent(performance.time_weighted_return_fraction)}</dd></div>
        <div><dt>Observed maximum drawdown</dt><dd>{percent(performance.maximum_drawdown_fraction)}</dd></div>
      </dl>
      {performance.limitations.map((limitation,i)=><p key={i}>{limitation}</p>)}
      <details><summary>Capital allocation history ({performance.capital_flows.length})</summary><p>These are approved internal allocations, not broker transfers. A negative amount releases cash. A held-position valuation taken before approval is shown as context; it is not treated as an exact mark at the flow time.</p>
        {performance.capital_flows.length?<div className="paper-accounting-table"><table><thead><tr><th>Effective</th><th>Action</th><th>Cash allocation</th><th>Pre-flow equity</th><th>Valuation</th><th>Actor</th></tr></thead><tbody>{performance.capital_flows.map((flow)=><tr key={flow.flow_id}><td>{date(flow.effective_at)}</td><td>{flow.action}</td><td>{money(flow.amount_usd)}</td><td>{money(flow.equity_before_flow_usd)}</td><td>{flow.exact_valuation?"Exact for unitization":"Exact flow mark unavailable"}</td><td>{flow.actor}</td></tr>)}</tbody></table></div>:<p>No allocation receipts exist for this deployment.</p>}
      </details>
      <details><summary>Deployment equity history ({performance.equity_history.length})</summary>
        {performance.equity_history.length?<div className="paper-accounting-table"><table><thead><tr><th>Observed</th><th>Source</th><th>Equity</th><th>Net allocations</th><th>Investment P&amp;L</th><th>Return</th></tr></thead><tbody>{performance.equity_history.slice(-250).map((point,i)=><tr key={`${point.observed_at}-${i}`}><td>{date(point.observed_at)}</td><td>{point.source.replaceAll("_"," ")}</td><td>{money(point.equity_usd)}</td><td>{money(point.net_allocations_usd)}</td><td>{money(point.investment_pnl_usd)}</td><td>{percent(point.time_weighted_return_fraction)}</td></tr>)}</tbody></table></div>:<p>No valued deployment history is available.</p>}
        {performance.equity_history.length>250?<p>Showing the latest 250 points; returns use the complete saved history.</p>:null}
      </details>
      <details><summary>Calculation provenance</summary><p>Frozen version: {deployment.version_id}</p><p>Reconciliation: {report?.reconciliation_id??"Unavailable"}</p><p style={{overflowWrap:"anywhere"}}>Input fingerprint: {deployment.input_hash}</p></details>
    </>:null}
  </section>;
}
