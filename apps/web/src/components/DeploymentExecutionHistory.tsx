"use client";

import { useEffect,useState } from "react";
import { attributedDeployments,executionAttribution,type AttributedDeployment,type ExecutionAttribution } from "@/lib/execution-attribution";

const words=(value:string)=>value.replaceAll("_"," ");
const money=(value:string|null)=>value===null?"Unavailable":Number(value).toLocaleString(undefined,{style:"currency",currency:"USD",maximumFractionDigits:4});
const when=(value:string|null)=>value?new Date(value).toLocaleString():"Not recorded";

export function DeploymentExecutionHistory({deploymentId,accountKey,refreshKey}:{deploymentId?:string;accountKey?:string;refreshKey?:string}) {
  const [deployments,setDeployments]=useState<AttributedDeployment[]>([]);
  const [selected,setSelected]=useState("");
  const [report,setReport]=useState<ExecutionAttribution|null>(null);
  const [before,setBefore]=useState("");
  const [revision,setRevision]=useState(0);
  const [busy,setBusy]=useState(false);
  const [loadingDeployments,setLoadingDeployments]=useState(Boolean(accountKey&&!deploymentId));
  const [error,setError]=useState("");
  const identifier=deploymentId??selected;
  useEffect(()=>{
    if(deploymentId||!accountKey)return;
    const controller=new AbortController();setLoadingDeployments(true);setError("");setBefore("");
    attributedDeployments(accountKey,controller.signal).then(({deployments:rows})=>{if(!controller.signal.aborted){setDeployments(rows);setSelected((current)=>rows.some((row)=>row.deployment_id===current)?current:rows[0]?.deployment_id??"");}})
      .catch((e)=>{if(!controller.signal.aborted)setError(e instanceof Error?e.message:"Deployment list unavailable");})
      .finally(()=>{if(!controller.signal.aborted)setLoadingDeployments(false);});
    return ()=>controller.abort();
  },[accountKey,deploymentId,refreshKey]);
  useEffect(()=>{
    if(!identifier){setReport(null);setBusy(false);return;}
    const controller=new AbortController();setBusy(true);setError("");setReport(null);
    executionAttribution(identifier,accountKey,before||undefined,controller.signal).then((value)=>{if(!controller.signal.aborted)setReport(value);})
      .catch((e)=>{if(!controller.signal.aborted)setError(e instanceof Error?e.message:"Execution history unavailable");})
      .finally(()=>{if(!controller.signal.aborted)setBusy(false);});
    return ()=>controller.abort();
  },[identifier,accountKey,before,revision,refreshKey]);
  return <section className="paper-accounting-card deployment-execution-history" aria-label="Strategy execution attribution" aria-busy={busy||loadingDeployments}>
    <h2>From proposed holdings to actual fills</h2>
    <p>Follow each portfolio decision through human review and the broker boundary. Quantities approved, claimed for dispatch, and reconciled as fills remain separate.</p>
    {!deploymentId&&deployments.length?<label>Strategy deployment<select value={selected} disabled={busy||loadingDeployments} onChange={(event)=>{setSelected(event.target.value);setBefore("");}}>{deployments.map((item)=><option key={item.deployment_id} value={item.deployment_id}>{item.name} · {words(item.state)}</option>)}</select></label>:null}
    {!deploymentId&&!loadingDeployments&&!deployments.length&&!error?<p>No strategy deployment history for this account.</p>:null}
    {error?<p role="alert">{error}</p>:null}
    {busy||loadingDeployments?<p role="status">Loading saved execution evidence…</p>:null}
    {identifier?<div className="paper-accounting-actions"><button type="button" className="secondary-button" disabled={busy} onClick={()=>{setBefore("");setRevision((value)=>value+1);}}>Refresh latest execution history</button></div>:null}
    {report?<>
      <h3>{report.deployment_name}</h3>
      <p>{report.account_reconciled?"Account receipt reconciled":"Account reconciliation required"} · observed {when(report.account_observed_at)}. {report.evidence_kind==="fixture"?"Fixture simulation; no investment evidence.":report.evidence_kind==="broker_paper"?"Broker paper observations.":"No account evidence yet."}</p>
      {report.rows.length?<div className="paper-accounting-table" style={{overflowX:"auto"}}><table><caption>Each row belongs to one evaluation; repeated targets must not be added together.</caption><thead><tr><th>Symbol / side</th><th>Proposed holdings</th><th>Ever approved</th><th>Dispatch approved</th><th>Reconciled fills</th><th>Outcome</th></tr></thead><tbody>{report.rows.map((row)=><tr key={`${row.evaluation_id}:${row.instrument_id}`}>
        <th scope="row">{row.symbol} · {row.side}</th><td>{row.observed_quantity_at_evaluation} → {row.proposed_quantity} (change {row.proposed_delta})</td><td>{row.ever_approved_quantity??"Not approved"}</td><td>{row.dispatch_approved_quantity??"Not claimed"}</td><td>{row.reconciled_fill_quantity??"Unavailable"}</td><td>{words(row.outcome)}</td>
      </tr>)}</tbody></table></div>:<p>No symbol targets in these evaluations.</p>}
      {report.rows.map((row)=><details key={`${row.evaluation_id}:${row.instrument_id}`}><summary>{row.symbol} · {when(row.timeline.evaluated_at)} · timing and execution evidence</summary>
        <p>Outcome: {words(row.outcome)}. Unfilled proposed shares: {row.unfilled_proposed_quantity??"Unavailable"}. Latest order acknowledgment reports {row.broker_observed_filled_quantity??"no recorded"} filled shares; reconciled activity reports {row.reconciled_fill_quantity??"unavailable"}.</p>
        <p>Average fill: {money(row.average_fill_price_usd)}. Recorded fill fees: {money(row.fill_fees_usd)}. Price difference versus decision reference, plus those fees: {money(row.filled_price_difference_plus_fees_usd)}. Positive is adverse for either side. This covers filled shares only and is not realized P&amp;L or a causal estimate of delay cost.</p>
        <dl className="paper-accounting-metrics">{Object.entries(row.timeline).map(([key,value])=><div key={key}><dt>{words(key)}</dt><dd>{when(value)}</dd></div>)}</dl>
        <ul>{Object.entries(row.delays).map(([key,value])=><li key={key}>{words(key.replace(/_seconds$/,""))}: {value===null?"Unavailable":`${value.toLocaleString(undefined,{maximumFractionDigits:3})} seconds`}.</li>)}</ul>
        {row.events.length?<details><summary>Saved order events ({row.events.length})</summary><ol>{row.events.map((event)=><li key={event.event_id}>{when(event.created_at)} · {words(event.kind)}{event.actor?` · ${event.actor}`:""}{event.observed_status?` · ${words(event.observed_status)}`:""}</li>)}</ol></details>:null}
        {row.protective_fills?.length?<section aria-label="Reconciled protective fills"><h4>Protective exits linked to this entry</h4><p>These broker child fills are separate from the original entry quantity and its execution-price comparison.</p><ul>{row.protective_fills.map(fill=><li key={fill.source_id}>{when(fill.effective_at)} · {words(fill.protection_role)} · {fill.quantity} shares at {money(fill.price_usd)}, fee {money(fill.fee_usd)}</li>)}</ul></section>:null}
        {row.limitations.length?<ul>{row.limitations.map((note)=><li key={note}>{note}</li>)}</ul>:null}
      </details>)}
      <details><summary>Evaluations on this page ({report.evaluations.length})</summary><ul>{report.evaluations.map((item)=><li key={item.evaluation_id}>{when(item.created_at)} · {item.status}: {item.reason}</li>)}</ul></details>
      {report.next_cursor?<button type="button" className="secondary-button" disabled={busy} onClick={()=>setBefore(report.next_cursor!)}>Older evaluations</button>:null}
      <details><summary>Sources and interpretation</summary><ul>{report.limitations.map((note)=><li key={note}>{note}</li>)}</ul><p>Version {report.version_id}. Account receipt {report.reconciliation_id??"unavailable"}. Input fingerprint {report.input_hash}. Generated {when(report.generated_at)}.</p></details>
    </>:null}
  </section>;
}
