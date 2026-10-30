"use client";

import { useEffect, useRef, useState } from "react";
import { deploymentRequest, type DeploymentCandidate, type DeploymentDetail, type DeploymentRecord, type StrategyReviewSelection } from "@/lib/deployments";
import { evidenceLabel } from "@/lib/research-api";
import { DeploymentEvaluations } from "./DeploymentEvaluations";
import { DeploymentExecutionHistory } from "./DeploymentExecutionHistory";
import { DeploymentWorkerHealth } from "./DeploymentWorkerHealth";
import { apiBase } from "@/lib/api";
import "./StrategyDeployment.css";

const money=(value:string)=>Number(value).toLocaleString(undefined,{style:"currency",currency:"USD"});
const percent=(value:string)=>`${(Number(value)*100).toFixed(2)}%`;
type Account={provider_id:string;account_id:string;environment:"paper";evidence_kind:string};

export function StrategyDeploymentPanel({ selection }: { selection?: StrategyReviewSelection | null }) {
  const [rows,setRows]=useState<DeploymentRecord[]>([]);
  const [candidates,setCandidates]=useState<DeploymentCandidate[]>([]);
  const [account,setAccount]=useState<Account|null>(null);
  const [selected,setSelected]=useState("");
  const [candidateKey,setCandidateKey]=useState(selection?`${selection.experiment_id}:${selection.version_id}`:"");
  const [detail,setDetail]=useState<DeploymentDetail|null>(null);
  const [name,setName]=useState("");
  const [capital,setCapital]=useState("");
  const [fee,setFee]=useState("");
  const [feeReference,setFeeReference]=useState("");
  const [rationale,setRationale]=useState("");
  const [actor,setActor]=useState("operator");
  const [reason,setReason]=useState("");
  const [amendedCapital,setAmendedCapital]=useState("");
  const [busy,setBusy]=useState(false);
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");
  const requestKey=useRef<{signature:string;key:string}|null>(null);
  const candidate=candidates.find((item)=>`${item.experiment_id}:${item.version_id}`===candidateKey);
  const pendingEvaluation=detail?.evaluation_jobs?.some((job)=>["queued","running"].includes(job.state))??false;
  useEffect(()=>{ if (selection) setCandidateKey(`${selection.experiment_id}:${selection.version_id}`); },[selection]);
  useEffect(()=>{
    const controller=new AbortController();
    Promise.all([deploymentRequest<{deployments:DeploymentRecord[]}>("",undefined,controller.signal),deploymentRequest<{candidates:DeploymentCandidate[]}>("/candidates",undefined,controller.signal),deploymentRequest<Account>("/account",undefined,controller.signal).catch((e)=>{if(!controller.signal.aborted)setError(e instanceof Error?e.message:"Paper account unavailable");return null;})])
      .then(([saved,available,current])=>{if(!controller.signal.aborted){setRows(saved.deployments);setCandidates(available.candidates);setAccount(current);}})
      .catch((e)=>{if(!controller.signal.aborted)setError(e instanceof Error?e.message:"Deployment records unavailable");})
      .finally(()=>{if(!controller.signal.aborted)setLoading(false);});
    return ()=>controller.abort();
  },[]);
  useEffect(()=>{
    if(!selected){setDetail(null);return;}
    const controller=new AbortController();setDetail(null);
    deploymentRequest<DeploymentDetail>(`/${selected}`,undefined,controller.signal).then((value)=>{if(!controller.signal.aborted)setDetail(value);})
      .catch((e)=>{if(!controller.signal.aborted)setError(e instanceof Error?e.message:"Deployment unavailable");});
    return ()=>controller.abort();
  },[selected]);
  useEffect(()=>{
    if(!selected||busy||!pendingEvaluation)return;
    const controller=new AbortController();
    let timer:ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const value=await deploymentRequest<DeploymentDetail>(`/${selected}`,undefined,controller.signal);
        if(!controller.signal.aborted){setDetail(value);setRows((previous)=>previous.map((row)=>row.deployment_id===value.deployment.deployment_id?value.deployment:row));}
      }catch(e){if(!controller.signal.aborted)setError(e instanceof Error?e.message:"Evaluation status unavailable");}
      finally{if(!controller.signal.aborted)timer=setTimeout(poll,3000);}
    }
    timer=setTimeout(poll,3000);
    return ()=>{controller.abort();clearTimeout(timer);};
  },[selected,busy,pendingEvaluation]);
  async function refresh(identifier=selected) {
    const [saved,current]=await Promise.all([deploymentRequest<{deployments:DeploymentRecord[]}>(""),identifier?deploymentRequest<DeploymentDetail>(`/${identifier}`):Promise.resolve(null)]);
    setRows(saved.deployments);setDetail(current);
  }
  async function create() {
    if(!candidate||!account)return;
    setBusy(true);setError("");setNotice("");
    try {
      const payload={name,version_id:candidate.version_id,experiment_id:candidate.experiment_id,
        account:{provider_id:account.provider_id,account_id:account.account_id,environment:account.environment},
        terms:{capital_usd:capital,execution_policy:{...candidate.spec.risk,snapshot_max_age_seconds:15},fee_reserve_per_order_usd:fee,fee_assumption_reference:feeReference,funding_rationale:rationale}};
      const signature=JSON.stringify(payload);
      if(requestKey.current?.signature!==signature)requestKey.current={signature,key:crypto.randomUUID()};
      const record=await deploymentRequest<DeploymentRecord>("",{...payload,idempotency_key:requestKey.current.key});
      setSelected(record.deployment_id);await refresh(record.deployment_id);setNotice("Draft saved. Review account evidence and funding before activation.");
    }catch(e){setError(e instanceof Error?e.message:"Could not save deployment");}finally{setBusy(false);}
  }
  async function act(action:string,extra:Record<string,unknown>={}) {
    if(!detail)return;
    if(!actor.trim()||!reason.trim()){setError("Enter a reviewer and a reason for this decision.");return;}
    setBusy(true);setError("");setNotice("");
    try {
      const result=await deploymentRequest<{message?:string;cancellations?:{state:string}[]}>(`/${selected}/${action}`,{actor,reason,expected_revision:detail.deployment.revision,...extra});
      await refresh();setNotice(result.message??"Decision saved. The review history is retained.");
      if(result.cancellations?.some((item)=>item.state==="protective_entry_requires_review"||item.state==="cancellation_unavailable"))setNotice("Deployment paused. Some entry cancellations need review; existing positions and protective exits remain in place.");
    }catch(e){setError(e instanceof Error?e.message:"Deployment action failed");}finally{setBusy(false);}
  }
  async function orderAction(order:DeploymentDetail["orders"][number],action:"approve"|"submit"|"cancel"|"reconcile") {
    if(!actor.trim()){setError("Enter the reviewer for this exact order.");return;}
    setBusy(true);setError("");setNotice("");
    try {
      const response=await fetch(`${apiBase()}/api/trades/${order.intent_id}/${action}`,{method:"POST",headers:{"Content-Type":"application/json","X-Trademaster-Room":"market"},body:["approve","cancel"].includes(action)?JSON.stringify({actor,expected_order_hash:order.content_hash}):undefined});
      if(!response.ok){const body=await response.json();throw new Error(typeof body.detail==="string"?body.detail:`Order action failed (${response.status})`);}
      await refresh();setNotice(action==="approve"?"Exact order approved. Submission remains a separate action.":action==="submit"?"Submission result saved. Check its observed state; an unknown outcome requires reconciliation.":"Order state refreshed. Pending cancellation retains its reservation until the broker acknowledges it.");
    }catch(e){setError(e instanceof Error?e.message:"Exact order action failed");}finally{setBusy(false);}
  }
  const record=detail?.deployment;
  const review=detail?.reviews[0];
  const currentReview=review&&record?.state==="paper_review"&&review.deployment_revision===record.revision;
  const approval=review?{review_id:review.review_id,expected_hash:review.content_hash}:{};
  return <section id="strategy-deployments" className="deployment-panel" aria-label="Strategy deployments">
    <header><p>QUANT · STRATEGY DEPLOYMENTS</p><h2>Put evidence through paper review</h2><p>Pin a strategy version, review its account and funding, and retain a separate approval for every order.</p></header>
    <DeploymentWorkerHealth accountKey={record?.account_key}/>
    {loading?<p role="status">Loading deployment records…</p>:null}
    {error?<p className="deployment-error" role="alert">{error}</p>:null}
    {notice?<p role="status">{notice}</p>:null}
    <details open={!!selection||(!loading&&!rows.length)}><summary>Propose a paper deployment</summary>
      {!candidates.length?<p>Complete a research experiment to propose its version for review. Fixture and inconclusive results remain ineligible for activation.</p>:<form className="deployment-form" onSubmit={(event)=>{event.preventDefault();void create();}}>
        <label>Research candidate<select required value={candidateKey} onChange={(event)=>setCandidateKey(event.target.value)}><option value="">Choose a completed experiment</option>{candidates.map((item)=><option key={`${item.experiment_id}:${item.version_id}`} value={`${item.experiment_id}:${item.version_id}`}>{item.strategy_name} · {evidenceLabel(item.evidence_status)} · {new Date(item.created_at).toLocaleString()}</option>)}</select></label>
        {candidate?<p>{evidenceLabel(candidate.evidence_kind)} · {evidenceLabel(candidate.evidence_status)}. Version limits: {percent(candidate.spec.risk.max_position_fraction)} per position, {percent(candidate.spec.risk.max_group_fraction)} per group, {percent(candidate.spec.risk.cash_reserve_fraction)} cash reserve, {percent(candidate.spec.risk.max_drawdown_fraction)} drawdown intervention.</p>:null}
        <p>Account: {account?`${account.account_id} · ${account.evidence_kind==="fixture"?"Fixture simulation":"Broker paper"}`:"Unavailable"}. Opening baselines and account reconciliation are managed in Portfolio → Performance.</p>
        <label>Deployment name<input required value={name} onChange={(event)=>setName(event.target.value)}/></label>
        <label>Proposed funding envelope (USD)<input required type="number" min="0.01" step="0.01" value={capital} onChange={(event)=>setCapital(event.target.value)}/></label>
        <label>Fee reserve per order (USD)<input required type="number" min="0" step="0.01" value={fee} onChange={(event)=>setFee(event.target.value)}/></label>
        <label>Source for the fee assumption<input required value={feeReference} onChange={(event)=>setFeeReference(event.target.value)}/></label>
        <label>Why this funding allocation?<textarea required value={rationale} onChange={(event)=>setRationale(event.target.value)}/></label>
        <button type="submit" disabled={busy||!account||!candidate}>Save deployment draft</button>
      </form>}
    </details>
    <div className="deployment-actions"><button type="button" disabled={busy} onClick={()=>{setError("");void refresh().catch((e)=>setError(e.message));}}>Refresh saved deployments</button></div>
    {!loading&&!rows.length?<p>No deployment has been created. Research completion does not allocate capital automatically.</p>:null}
    {rows.length?<label>Saved deployment<select disabled={busy} value={selected} onChange={(event)=>setSelected(event.target.value)}><option value="">Choose a deployment</option>{rows.map((item)=><option key={item.deployment_id} value={item.deployment_id}>{item.name} · {evidenceLabel(item.state)}</option>)}</select></label>:null}
    {detail&&record?<section aria-label="Deployment review">
      <h3>{record.name} · {evidenceLabel(record.state)}</h3><p>Account {record.account.account_id}. Proposed envelope {money(detail.terms.payload.capital_usd)}. {detail.active_terms?`Committed envelope: ${money(detail.active_terms.payload.capital_usd)}.`:"No committed funding."} Pausing retains the committed allocation.</p>
      <p>Last account observation: {detail.observed_at?new Date(detail.observed_at).toLocaleString():"Not observed"} · {detail.account_reconciled?"Reconciled":"Needs reconciliation"}.</p>
      <div className="deployment-form"><label>Reviewer<input value={actor} onChange={(event)=>setActor(event.target.value)}/></label><label>Reason for this decision<textarea value={reason} onChange={(event)=>setReason(event.target.value)}/></label></div>
      <div className="deployment-actions">
        {["draft","paused","paper_review"].includes(record.state)?<button type="button" disabled={busy} onClick={()=>void act("review")}>Prepare current paper review</button>:null}
        {["paper_active","paused","paper_review"].includes(record.state)?<button type="button" disabled={busy} onClick={()=>void act("pause")}>Pause and review entry cancellations</button>:null}
      </div>
      {review?<div className="deployment-review">
        <h4>{currentReview?"Current funding review":"Previous funding review"}</h4><p>{review.payload.eligible?"Evidence and funding gates met; human approval is still required.":"This review does not qualify for activation."} Expires {new Date(review.expires_at).toLocaleString()}.</p>
        <p>{review.payload.account.evidence_kind==="fixture"?"Fixture simulation":"Broker paper"} · Equity {money(review.payload.account.equity_usd)} · Cash {money(review.payload.account.cash_usd)} · Drawdown {percent(review.payload.account.drawdown_fraction)}.</p>
        <p>Available envelope {money(review.payload.funding.available_envelope_usd)} after other commitments of {money(review.payload.funding.other_envelopes_usd)} and unallocated holdings of {money(review.payload.funding.unallocated_holdings_usd)}.</p>
        {review.payload.allocation ? <div><p>Current deployment equity: {money(review.payload.allocation.equity_usd)}; attributed cash: {money(review.payload.allocation.cash_usd)}. {review.payload.allocation.creates_flow ? `Approval records an internal cash allocation of ${money(review.payload.allocation.amount_usd)} (negative means a release).` : "This resume retains the existing allocation and its gains or losses."}</p><p>{review.payload.allocation.scope}. {review.payload.allocation.valuation_policy}.</p></div> : null}
        <ul>{review.payload.gates.map((gate)=><li key={gate.name}><strong>{gate.passed?"Met":"Not met"}: {evidenceLabel(gate.name)}</strong> — {gate.detail}</li>)}</ul>
        {currentReview?<div className="deployment-actions"><button type="button" disabled={busy||!review.payload.eligible||Date.parse(review.expires_at)<=Date.now()} onClick={()=>void act(record.active_terms_id?"resume":"activate",approval)}>{record.active_terms_id?"Approve review and resume":"Approve reviewed paper deployment"}</button>{(["reject","revise","defer"] as const).map((decision)=><button key={decision} type="button" disabled={busy} onClick={()=>void act("decision",{...approval,decision})}>{evidenceLabel(decision)} review</button>)}</div>:null}
        <details><summary>Exact reviewed terms and evidence fingerprint</summary><pre>{JSON.stringify(review,null,2)}</pre></details>
      </div>:null}
      {["draft","paused","paper_review"].includes(record.state)?<details><summary>Propose a capital change or retire</summary><label>New funding envelope (USD)<input type="number" min="0.01" step="0.01" value={amendedCapital} onChange={(event)=>setAmendedCapital(event.target.value)}/></label><div className="deployment-actions"><button type="button" disabled={busy||!amendedCapital} onClick={()=>void act("capital",{terms:{...detail.terms.payload,capital_usd:amendedCapital}})}>Propose revised funding</button><button type="button" disabled={busy} onClick={()=>void act("retire")}>Retire after account reconciliation</button></div><p>Revised capital requires a new review. Retirement requires no attributed holdings or outstanding orders and does not sell anything.</p></details>:null}
      <DeploymentEvaluations key={record.deployment_id} detail={detail} busy={busy} act={act}/>
      <DeploymentExecutionHistory key={`execution-${record.deployment_id}`} deploymentId={record.deployment_id} refreshKey={`${detail.observed_at}:${detail.events.length}:${detail.orders.map((order)=>order.state).join(",")}`}/>
      <h4>Exact order history and positions</h4>
      {detail.orders.length?<ul>{detail.orders.map((order)=><li key={order.order_id}><p>{order.order.symbol} · {order.order.side} {order.order.quantity} at {money(order.order.limit_price_usd)} · {evidenceLabel(order.state)}. Fee reserve {money(order.order.fee_reserve_usd)}. Approval expires {new Date(order.order.expires_at).toLocaleString()}.</p><div className="deployment-actions">
        {order.state==="previewed"?<button type="button" disabled={busy||Date.parse(order.order.expires_at)<=Date.now()} onClick={()=>void orderAction(order,"approve")}>Approve this exact order</button>:null}
        {order.state==="approved"?<button type="button" disabled={busy||(order.order.side==="buy"&&pendingEvaluation)||Date.parse(order.order.expires_at)<=Date.now()} onClick={()=>void orderAction(order,"submit")}>Submit approved paper order</button>:null}
        {!["filled","canceled","expired","rejected"].includes(order.state)?<button type="button" disabled={busy} onClick={()=>void orderAction(order,"cancel")}>Reject or request cancellation</button>:null}
        {!["previewed","approved","filled","canceled","expired","rejected"].includes(order.state)?<button type="button" disabled={busy} onClick={()=>void orderAction(order,"reconcile")}>Reconcile submission</button>:null}
      </div><details><summary>Exact order and approval fingerprint</summary><pre>{JSON.stringify(order,null,2)}</pre></details></li>)}</ul>:<p>No deployment order has been prepared.</p>}
      {detail.attributed_positions.length?<ul>{detail.attributed_positions.map((position)=><li key={position.symbol}>{position.symbol}: {position.owners[`deployment:${record.deployment_id}`]} attributed shares</li>)}</ul>:<p>No attributed holdings in the latest account observation.</p>}
      <details><summary>Decision history ({detail.events.length})</summary><ol>{detail.events.map((event)=><li key={event.event_id}>{new Date(event.created_at).toLocaleString()} · {evidenceLabel(event.action)} · {event.actor}: {event.reason}</li>)}</ol></details>
      <details><summary>Frozen strategy and experiment references</summary><p>Version {record.version_id}. Experiment {record.experiment_id}. Symbol programs linked: {detail.programs.length}.</p></details>
    </section>:null}
  </section>;
}
