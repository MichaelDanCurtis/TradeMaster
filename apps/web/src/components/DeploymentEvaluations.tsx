"use client";

import { useEffect, useState } from "react";
import { deploymentRequest, type DeploymentDetail } from "@/lib/deployments";
import { DeploymentRisk } from "./DeploymentRisk";

type Observation = { snapshot_id: string; created_at: string; payload: { provider: string; coverage_end: string } };

export function DeploymentEvaluations({ detail, busy, act }: { detail: DeploymentDetail; busy: boolean; act: (action:string,extra:Record<string,unknown>)=>Promise<void> }) {
  const [snapshots,setSnapshots]=useState<Observation[]>([]);
  const [snapshotId,setSnapshotId]=useState("");
  const [asOf,setAsOf]=useState("");
  const [limits,setLimits]=useState<Record<string,string>>({});
  const [error,setError]=useState("");
  const pending=detail.evaluation_jobs?.some((job)=>["queued","running"].includes(job.state))??false;
  useEffect(()=>{
    const controller=new AbortController();
    deploymentRequest<{snapshots:Observation[]}>("/observations",undefined,controller.signal)
      .then((value)=>{if(!controller.signal.aborted)setSnapshots(value.snapshots);})
      .catch((e)=>{if(!controller.signal.aborted)setError(e instanceof Error?e.message:"Observation snapshots unavailable");});
    return ()=>controller.abort();
  },[]);
  return <section aria-label="Portfolio evaluations">
    <h4>Proposed portfolio → exact orders → actual fills</h4>
    <p>Evaluate the frozen strategy against an imported prospective observation snapshot. Whole-share targets use its known prices and the committed capital. Every exact order still needs human approval.</p>
    {error?<p role="alert">{error}</p>:null}
    {detail.deployment.state==="paper_active"?<form className="deployment-form" onSubmit={(event)=>{event.preventDefault();const button=(event.nativeEvent as SubmitEvent).submitter;void act(button instanceof HTMLButtonElement&&button.value==="queue"?"evaluation-jobs":"evaluate",{snapshot_id:snapshotId,as_of:asOf});}}>
      <label>Prospective observations<select required value={snapshotId} onChange={(event)=>setSnapshotId(event.target.value)}><option value="">Choose an imported snapshot</option>{snapshots.map((s)=><option key={s.snapshot_id} value={s.snapshot_id}>{s.payload.provider} · through {s.payload.coverage_end} · saved {new Date(s.created_at).toLocaleString()}</option>)}</select></label>
      <label>Decision cutoff (ISO timestamp with timezone)<input required placeholder="2026-09-04T20:00:01Z" value={asOf} onChange={(event)=>setAsOf(event.target.value)}/></label>
      <p>Trend uses the weekly closing session plus its frozen latency. Guidance also admits completed source observations after the close. Its calendar must cover the holding horizon, and existing holdings must have a reconciled opening fill.</p>
      <button disabled={busy||pending||!snapshotId} type="submit" value="now">Evaluate proposed holdings</button>
      <button disabled={busy||pending||!snapshotId} type="submit" value="queue">Queue for evaluation worker</button>
      <p>Queued work waits for the separately started evaluation worker. Each request pins this snapshot and cutoff; it does not schedule future observations or authorize orders.</p>
    </form>:null}
    {detail.evaluation_jobs?.length?<section aria-label="Evaluation jobs"><h4>Evaluation jobs</h4>
      {pending?<p role="status">Evaluation pending. New deployment buys are blocked until it completes or you resolve it.</p>:null}
      <ul>{detail.evaluation_jobs.map((job)=><li key={job.job_id}>
        <p>{new Date(job.created_at).toLocaleString()} · {job.state}{job.state==="queued"?" · Waiting for an evaluation worker":""}</p>
        {job.state==="running"?<p>Lease through {job.lease_until?new Date(job.lease_until).toLocaleTimeString():"unavailable"}. Publication deadline {job.deadline?new Date(job.deadline).toLocaleTimeString():"unavailable"}.</p>:null}
        {job.result?.message?<p>{job.result.message}</p>:null}
        {job.result?.failure?<p>Stopped at {job.result.failure.stage}: {job.result.failure.error_type}. Inspect the saved evidence and prepare a fresh funding review before resuming.</p>:null}
        {["queued","running"].includes(job.state)?<button type="button" disabled={busy} onClick={()=>void act(`evaluation-jobs/${job.job_id}/cancel`,{})}>{job.state==="running"?"Cancel evaluation and pause entries":"Cancel queued evaluation"}</button>:null}
      </li>)}</ul>
    </section>:null}
    {!detail.evaluations?.length?<p>No portfolio evaluation has been saved.</p>:detail.evaluations.map((evaluation,index)=><details key={evaluation.evaluation_id} open={index===0}>
      <summary>{new Date(evaluation.created_at).toLocaleString()} · {evaluation.payload.status}</summary>
      <p>{evaluation.payload.reason} Decision cutoff: {evaluation.payload.as_of}.</p>
      {evaluation.payload.execution_opens_at?<p>Execution window: {new Date(evaluation.payload.execution_opens_at).toLocaleString()} – {new Date(evaluation.payload.execution_deadline!).toLocaleTimeString()}. Missed windows require a new evaluation; limits are never silently repriced.</p>:null}
      <div style={{overflowX:"auto"}}><table><thead><tr><th>Symbol</th><th>Observed shares</th><th>Proposed shares</th><th>Change</th><th>Known price</th><th>Exact order</th></tr></thead><tbody>{evaluation.payload.portfolio.map((row)=>{
        const key=`${evaluation.evaluation_id}:${row.instrument_id}`;
        return <tr key={row.instrument_id}><td>{row.symbol}</td><td>{row.current_quantity}</td><td>{row.desired_quantity}</td><td>{row.delta_quantity}</td><td>${row.reference_price_usd}</td><td>{index===0&&row.delta_quantity!==0?<form onSubmit={(event)=>{event.preventDefault();void act("targets",{evaluation_id:evaluation.evaluation_id,instrument_id:row.instrument_id,limit_price_usd:limits[key]});}}><label>Limit for {row.symbol}<input required type="number" min="0.01" step="0.01" value={limits[key]??""} onChange={(event)=>setLimits({...limits,[key]:event.target.value})}/></label><button type="submit" disabled={busy||(row.delta_quantity>0&&(pending||detail.deployment.state!=="paper_active"))||!evaluation.payload.execution_deadline||Date.parse(evaluation.payload.execution_deadline)<=Date.now()}>Prepare {row.delta_quantity>0?"buy":"sell"} ticket</button></form>:"—"}</td></tr>;
      })}</tbody></table></div>
      <p>Planned sales must fill and reconcile before buys. Cash and buying power are checked again for each exact ticket.</p>
      <DeploymentRisk evaluation={evaluation}/>
      {evaluation.payload.guidance_state?<details><summary>Guidance decisions and actual-fill clocks</summary>
        <ul>{evaluation.payload.guidance_events?.map((event)=><li key={`${event.notice_id}:${event.status}`}>{event.notice_id} · {event.status}: {event.reason}</li>)}</ul>
        {Object.entries(evaluation.payload.guidance_state.holding_clocks).map(([instrument,clock])=><p key={instrument}>{instrument}: holding began with the actual fill at {new Date(clock.entry_at).toLocaleString()}, linked to notice {clock.notice_id}.</p>)}
        <p>Consumed notices: {evaluation.payload.guidance_state.consumed_notices.join(", ")||"None"}. Preparing an entry consumes its attempt even if it is rejected or never submitted.</p>
        {evaluation.payload.cancel_entries?.length?<p>Request cancellation of pending entries for: {evaluation.payload.cancel_entries.join(", ")}. The broker must acknowledge cancellation before its reservation is released.</p>:null}
      </details>:null}
      {evaluation.payload.limitations?<ul>{evaluation.payload.limitations.map((line)=><li key={line}>{line}</li>)}</ul>:null}
      <details><summary>Saved evaluation and provenance</summary><pre>{JSON.stringify(evaluation,null,2)}</pre></details>
    </details>)}
    <h4>Actual broker fills</h4>
    {detail.actual_fills?.length?<ul>{detail.actual_fills.map((fill)=><li key={fill.source_id}>{new Date(fill.effective_at).toLocaleString()} · {fill.symbol} · {fill.side} {fill.quantity} at ${fill.price_usd} · fee ${fill.fee_usd}</li>)}</ul>:<p>No attributed broker fill is present in the latest reconciliation. Proposed or approved shares are not fills.</p>}
  </section>;
}
