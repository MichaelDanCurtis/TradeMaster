"use client";

import {useEffect,useRef,useState} from "react";
import {sourceCorrections,previewSourceCorrections,approveSourceCorrections,type SourceCorrectionReview,type SourceCorrectionState} from "@/lib/accounting";

const words=(value:string)=>value.replaceAll("_"," ");
const money=(value:unknown)=>typeof value==="string"?Number(value).toLocaleString(undefined,{style:"currency",currency:"USD",maximumFractionDigits:6}):"Unavailable";
const when=(value:string)=>new Date(value).toLocaleString();

export function SourceCorrectionsPanel({accountKey,refreshKey}:{accountKey:string;refreshKey?:string}) {
  const [state,setState]=useState<SourceCorrectionState|null>(null);
  const [review,setReview]=useState<SourceCorrectionReview|null>(null);
  const [reason,setReason]=useState("");
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const [message,setMessage]=useState("");
  const actionController=useRef<AbortController|null>(null);
  useEffect(()=>{
    actionController.current?.abort();setBusy(false);setReview(null);setReason("");setMessage("");setError("");
    const controller=new AbortController();
    sourceCorrections(accountKey,controller.signal).then(value=>{if(!controller.signal.aborted)setState(value);})
      .catch(caught=>{if(!controller.signal.aborted)setError(caught instanceof Error?caught.message:"Source correction history unavailable");});
    return ()=>controller.abort();
  },[accountKey,refreshKey]);
  useEffect(()=>()=>actionController.current?.abort(),[]);
  async function act(approve:boolean) {
    actionController.current?.abort();const controller=new AbortController();actionController.current=controller;
    setBusy(true);setError("");setMessage("");
    try {
      if(approve&&review) {
        await approveSourceCorrections(review,reason,controller.signal);
        if(controller.signal.aborted)return;
        setReview(null);setReason("");setMessage("Correction approval saved. Reconcile the account again to publish an updated report; the current receipt remains unchanged.");
      } else {
        const next=await previewSourceCorrections(accountKey,controller.signal);
        if(controller.signal.aborted)return;
        setReview(next);setReason("");
      }
      const next=await sourceCorrections(accountKey,controller.signal);
      if(!controller.signal.aborted)setState(next);
    } catch(caught) {if(!controller.signal.aborted)setError(caught instanceof Error?caught.message:"Correction review failed");}
    finally {if(!controller.signal.aborted)setBusy(false);}
  }
  if(!state&&!error)return null;
  return <section className="paper-accounting-card" aria-label="Source correction review" aria-busy={busy}>
    <h2>Source corrections</h2>
    <p>Review conflicting broker activity before using a revised ledger. Original source versions and prior reports remain saved.</p>
    {error?<p role="alert">{error}</p>:null}{message?<p role="status">{message}</p>:null}
    {state?<p>{state.pending_source_ids.length?`${state.pending_source_ids.length} source event(s) require review.`:"No unresolved observed source revisions."}</p>:null}
    <button type="button" className="secondary-button" disabled={busy||!state?.pending_source_ids.length} onClick={()=>void act(false)}>Preview observed corrections</button>
    {review?<section aria-label="Displayed correction proposal">
      <h3>Review the exact changes</h3><p>{review.payload.effect}</p>
      <p>Review expires {when(review.expires_at)}. {review.payload.eligible?"The proposed source selection reconciles with the latest observed account balance.":"Discrepancies remain; this proposal cannot be approved."}</p>
      <SourceChanges changes={review.payload.changes}/>
      <h3>Calculation impact</h3>
      <p>Investment P&amp;L: {money(review.payload.before.investment_pnl_usd)} → {money(review.payload.after.investment_pnl_usd)}. Recorded fees: {money(review.payload.before.fees_usd)} → {money(review.payload.after.fees_usd)}. Missing performance remains unavailable.</p>
      <p>{review.payload.newly_excluded_observations.length} earlier balance observation(s) would be excluded from the new calculation because they reconcile under the prior source selection and conflict under this correction. Their receipts remain available. No replacement historical valuations are estimated.</p>
      {review.payload.newly_excluded_observations.length?<details><summary>Inspect affected historical observations</summary><ul>{review.payload.newly_excluded_observations.map(point=><li key={point.reconciliation_id}>{when(point.observed_at)} · cash {money(point.cash_usd)} · equity {money(point.equity_usd)} · receipt {point.reconciliation_id}</li>)}</ul></details>:null}
      {review.payload.restored_observation_ids?.length?<details><summary>Restore {review.payload.restored_observation_ids.length} historical observation(s) that reconcile again</summary><ul>{review.payload.restored_observation_ids.map(id=><li key={id}>Receipt {id}</li>)}</ul></details>:null}
      {review.payload.discrepancies.length?<ul>{review.payload.discrepancies.map((item,index)=><li key={`${item.code}-${index}`}>{words(item.code)}{item.detail?`: ${item.detail}`:""}</li>)}</ul>:null}
      <details><summary>Calculation limitations</summary><ul>{review.payload.limitations.map((line,index)=><li key={index}>{line}</li>)}</ul></details>
      <label className="paper-accounting-select">Reason for accepting these source corrections<textarea value={reason} onChange={event=>setReason(event.target.value)} maxLength={2000} disabled={busy}/></label>
      <div className="paper-accounting-actions"><button type="button" className="primary-button" disabled={busy||!review.payload.eligible||!reason.trim()} onClick={()=>void act(true)}>Approve displayed source corrections</button><button type="button" className="secondary-button" disabled={busy} onClick={()=>setReview(null)}>Dismiss correction proposal</button></div>
    </section>:null}
    {state?.approvals.length?<details><summary>Saved correction approvals ({state.approvals.length})</summary>{state.approvals.map(approval=>{
      const saved=state.reviews.find(item=>item.review_id===approval.review_id);
      return <details key={approval.correction_id}><summary>{when(approval.created_at)} · {approval.actor}: {approval.reason}</summary>
        {saved?<><SourceChanges changes={saved.payload.changes}/><p>Reviewed investment P&amp;L: {money(saved.payload.after.investment_pnl_usd)}. {saved.payload.newly_excluded_observations.length} historical balance observation(s) excluded and {saved.payload.restored_observation_ids?.length??0} restored by this review; original receipts remain saved.</p></>:<p>This review is outside the most recent 50 previews shown here; its immutable record remains saved.</p>}
      </details>;
    })}<p>Showing the most recent 50 approvals; original records remain in the ledger.</p></details>:null}
  </section>;
}

function SourceChanges({changes}:{changes:SourceCorrectionReview["payload"]["changes"]}) {
  const fields:Record<string,string>={kind:"Activity type",effective_at:"Effective time",symbol:"Symbol",side:"Side",quantity:"Quantity",price_usd:"Fill price (USD)",cash_amount_usd:"Cash movement (USD)",fee_usd:"Embedded fill fee (USD)",split_ratio:"Split ratio",new_symbol:"Replacement symbol",entitlement_at:"Entitlement time",equity_before_flow_usd:"Equity before cash flow (USD)"};
  function format(field:string,value:unknown) {
    if(value==null)return "Not supplied";
    if(field.endsWith("_usd"))return money(String(value));
    if(field.endsWith("_at"))return when(String(value));
    return String(value);
  }
  return <>{changes.map(change=><details key={change.source_id} open><summary>Source event: {change.source_id}</summary>
    <div className="paper-accounting-table"><table><thead><tr><th>Field</th><th>Previously selected</th><th>Observed replacement</th></tr></thead><tbody>{Object.entries(fields).filter(([field])=>(change.previous_activity[field]!=null||change.selected_activity[field]!=null)&&(field!=="fee_usd"||change.previous_activity.kind==="fill"||change.selected_activity.kind==="fill")).map(([field,label])=><tr key={field}><th scope="row">{label}</th><td>{format(field,change.previous_activity[field])}</td><td>{format(field,change.selected_activity[field])}</td></tr>)}</tbody></table></div>
    <details><summary>Retained source payloads and fingerprints</summary><pre style={{maxHeight:400,overflow:"auto",whiteSpace:"pre-wrap",overflowWrap:"anywhere"}}>{JSON.stringify(change,null,2)}</pre></details>
  </details>)}</>;
}
