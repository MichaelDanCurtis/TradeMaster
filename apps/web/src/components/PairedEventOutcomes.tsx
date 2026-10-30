"use client";

import {useEffect,useRef,useState} from "react";
import {researchRequest,type PairedEventSummary,type PairedEventRow,type EventArmOutcome} from "@/lib/research-api";

type Index={pages:{artifact_hash:string;offset:number;rows:number}[];limitations:string[]};
const money=(value:string)=>Number(value).toLocaleString(undefined,{style:"currency",currency:"USD",maximumFractionDigits:4});
const label=(value:string)=>value.replaceAll("_"," ");
const when=(value:string|null)=>value?new Date(value).toLocaleString():"No fill";

export function PairedEventOutcomes({experimentId,summary,title}:{experimentId:string;summary:PairedEventSummary;title:string}) {
  const [index,setIndex]=useState<Index|null>(null);
  const [page,setPage]=useState(0);
  const [rows,setRows]=useState<PairedEventRow[]|null>(null);
  const [selectedNotice,setSelectedNotice]=useState<string|null>(null);
  const selected=rows?.find(row=>row.notice_id===selectedNotice);
  const detailRef=useRef<HTMLElement>(null);
  useEffect(()=>{if(selected)detailRef.current?.focus();},[selected]);
  const [error,setError]=useState("");
  useEffect(()=>{
    const controller=new AbortController();
    researchRequest<Index>(`/experiments/${experimentId}/artifacts/${summary.artifact_hash}`,undefined,"GET",controller.signal)
      .then(value=>{if(!controller.signal.aborted)setIndex(value);})
      .catch(e=>{if(!controller.signal.aborted)setError(e instanceof Error?e.message:"Paired event index unavailable");});
    return ()=>controller.abort();
  },[experimentId,summary.artifact_hash]);
  const digest=index?.pages[page]?.artifact_hash;
  useEffect(()=>{
    if(!digest)return;
    const controller=new AbortController();setRows(null);setError("");
    researchRequest<{rows:PairedEventRow[]}>(`/experiments/${experimentId}/artifacts/${digest}`,undefined,"GET",controller.signal)
      .then(value=>{if(!controller.signal.aborted)setRows(value.rows);})
      .catch(e=>{if(!controller.signal.aborted)setError(e instanceof Error?e.message:"Paired events unavailable");});
    return ()=>controller.abort();
  },[experimentId,digest]);
  return <section aria-label="Paired event outcomes">
    <h4>{title} · Paired event outcomes</h4>
    <p>{summary.method}</p>
    <p>{summary.events} notices across {summary.issuer_period_clusters} issuer/forecast-period clusters. Both entered: {summary.both_entered}; challenger only: {summary.challenger_only}; control only: {summary.control_only}; neither entered: {summary.neither_entered}.</p>
    <p>{summary.reconciled?"Reconciled":"Unreconciled"}: event P&amp;L difference {money(summary.event_pnl_difference_usd)} + account cash-yield difference {money(summary.cash_yield_difference_usd)} = portfolio P&amp;L difference {money(summary.portfolio_pnl_difference_usd)}. Recurring model costs are shown in the arm comparison above.</p>
    {error?<p role="alert">{error}</p>:null}
    {!index||(!rows&&!!digest&&!error)?<p role="status">Loading saved event outcomes…</p>:null}
    {index&&!index.pages.length?<p>No in-window notices were recorded.</p>:null}
    {index?.pages.length?<div className="strategy-actions">
      <button type="button" className="secondary-button compact" disabled={page===0||!rows} onClick={()=>{setSelectedNotice(null);setPage(value=>value-1);}}>Previous event page</button>
      <span>Page {page+1} of {index.pages.length}</span>
      <button type="button" className="secondary-button compact" disabled={page+1>=index.pages.length||!rows} onClick={()=>{setSelectedNotice(null);setPage(value=>value+1);}}>Next event page</button>
    </div>:null}
    {selected?<section ref={detailRef} tabIndex={-1} className="strategy-event-detail" aria-label={`Event details: ${selected.notice_id}`}>
      <h5>{selected.instrument_id} · {selected.notice_id} · Timing, capital and decisions</h5>
      <button type="button" className="secondary-button compact" onClick={()=>setSelectedNotice(null)}>Close event details</button>
      <p>Forecast period: {selected.period_start} to {selected.period_end}. {selected.matched_fill_times?"Both arms share entry and final exit times.":"Fill timing is unmatched or one arm did not enter."}</p>
      <ArmDetail name="Challenger" outcome={selected.challenger}/><ArmDetail name="Control" outcome={selected.control}/>
    </section>:null}
    {rows?<div className="strategy-table-scroll" role="region" aria-label="Notice-by-notice comparison" tabIndex={0}><table className="strategy-table">
      <caption>Actual simulated investment contributions; excluded events have no invented trade return</caption>
      <thead><tr><th>Notice</th><th>Challenger</th><th>Challenger P&amp;L</th><th>Control</th><th>Control P&amp;L</th><th>Difference</th><th>Evidence</th></tr></thead>
      <tbody>{rows.map(row=><tr key={row.notice_id}>
        <th scope="row">{row.instrument_id}<br/>{row.notice_id}<br/>{new Date(row.available_at).toLocaleDateString()}</th>
        <td>{label(row.challenger.state)}</td><td>{money(row.challenger.investment_pnl_usd)}</td>
        <td>{label(row.control.state)}</td><td>{money(row.control.investment_pnl_usd)}</td><td>{money(row.pnl_difference_usd)}</td>
        <td><button type="button" className="secondary-button compact" aria-pressed={selectedNotice===row.notice_id} onClick={()=>setSelectedNotice(row.notice_id)}>Inspect event: {row.notice_id}</button></td>
      </tr>)}</tbody>
    </table></div>:null}
    {index?<details><summary>Event attribution assumptions</summary><ul>{index.limitations.map(line=><li key={line}>{line}</li>)}</ul></details>:null}
  </section>;
}

function ArmDetail({name,outcome}:{name:string;outcome:EventArmOutcome}) {
  return <section aria-label={`${name} event details`}>
    <h5>{name} · {label(outcome.state)}</h5>
    <p>Entry: {when(outcome.entry_at)}. Exit: {outcome.entered&&!outcome.exit_at?"Still open":when(outcome.exit_at)}.</p>
    <p>Entry notional {money(outcome.entry_notional_usd)}; {outcome.remaining_quantity} shares remain. Contribution to initial portfolio capital: {(Number(outcome.contribution_fraction)*100).toFixed(4)}%. This is not a return on a hypothetical trade.</p>
    {outcome.entered?<p>Realized {money(outcome.realized_pnl_usd??"0")}; unrealized {money(outcome.unrealized_pnl_usd??"0")}; entitled dividends {money(outcome.dividends_usd??"0")}; fees {money(outcome.fees_usd??"0")}. Slippage {money(outcome.slippage_usd??"0")} is already included in fill prices. Held at {outcome.held_closes} session closes; {outcome.stale_closes} stale valuations.{outcome.final_valuation_stale?" The ending position mark is stale.":""}</p>:<p>{outcome.entry_proposed?"An entry was proposed but no fill was recorded.":"No entry was filled or sized for this notice."}</p>}
    <ul>{outcome.fills.map(fill=><li key={fill.fill_id}>{when(fill.executed_at)} · {fill.quantity} shares at {money(fill.price_usd)}, fee {money(fill.fee_usd)}{fill.exit_reason?` · ${fill.exit_reason}`:""}</li>)}</ul>
    <ul>{outcome.corporate_actions.map(action=><li key={action.action_id}>{label(action.kind)} · {when(action.at)}{action.ratio?` · ratio ${action.ratio}`:""}{action.entitlement_usd?` · entitlement ${money(action.entitlement_usd)}`:""}{action.cash_in_lieu_usd?` · fractional-share compensation ${money(action.cash_in_lieu_usd)}`:""}</li>)}</ul>
    <ul>{outcome.decisions.map((event,index)=><li key={`${event.at}-${index}`}>{when(event.at)} · {label(event.status)}: {event.reason}{event.evidence_verdict?` (evidence: ${event.evidence_verdict})`:""}</li>)}</ul>
  </section>;
}
