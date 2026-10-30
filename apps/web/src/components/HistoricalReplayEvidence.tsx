"use client";
import {useEffect,useRef,useState} from "react";
import {apiBase} from "@/lib/api";
import {opportunityRequest,type Replay} from "@/lib/opportunity-lab";

type Claim={text:string;kind:string;citations:{source_id:string;quote:string|null;region?:string|null}[]};
export type HistoricalEvidenceView={id:string;state:string;message:string;step:number;decision_date:string;packet_hash:string|null;brief_id?:string;
 packet?:{availability_rule:string;scope:string;gaps:string[];facts:{metric:string;period_role:string;value:string;unit:string;start:string|null;end:string;filed:string;accession:string}[];sources:{source_id:string;title:string;text:string;published_at:string|null;retrieved_at:string;url:string|null}[]};
 assessment?:{brief_id:string;state:string;message:string;receipt:{proposal:{overview:Claim;catalysts:Claim[];bull_case:Claim[];bear_case:Claim[];rejection_tests:string[];gaps:string[];evidence_checks?:Claim[]}|null;actual_model_id:string;input_tokens:number|null;output_tokens:number|null}|null}};
type Status={available:boolean;provider_config_hash?:string;message:string};
const active=(s:string|undefined)=>!!s&&["collecting","queued","synthesizing"].includes(s);
export function HistoricalReplayEvidence({replay,onUpdate}:{replay:Replay;onUpdate:(r:Replay)=>void}){
 const [status,setStatus]=useState<Status|null>(null);const [busy,setBusy]=useState(false);const [error,setError]=useState("");
 const pending=useRef(false);const mounted=useRef(true);const key=useRef<{inputs:string;value:string}|null>(null);const sources=useRef<HTMLDetailsElement>(null);
 const evidence=replay.historical_evidence;const assessment=evidence?.assessment;
 const running=active(evidence?.state)||active(assessment?.state);
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;};},[]);
 useEffect(()=>{const controller=new AbortController();void fetch(`${apiBase()}/api/discover/briefs/status`,{signal:controller.signal,cache:"no-store"}).then(async r=>{if(!r.ok)throw new Error('Could not read research provider');return r.json() as Promise<Status>;}).then(s=>{if(!controller.signal.aborted)setStatus(s);}).catch(e=>{if(!controller.signal.aborted)setError(e.message);});return()=>controller.abort();},[]);
 useEffect(()=>{if(!running)return;const controller=new AbortController();let timer:ReturnType<typeof setTimeout>;async function poll(){try{const row=await opportunityRequest<Replay>(`/replays/${replay.id}`,undefined,controller.signal);if(!controller.signal.aborted)onUpdate(row);}catch(e){if(!controller.signal.aborted)setError(e instanceof Error?e.message:"Could not refresh historical assessment");}if(!controller.signal.aborted)timer=setTimeout(poll,2000);}timer=setTimeout(poll,2000);return()=>{controller.abort();clearTimeout(timer);};},[running,replay.id,onUpdate]);
 async function act(kind:"historical-evidence"|"assess"){
  if(pending.current)return;pending.current=true;setBusy(true);setError("");
  try{let body:unknown={expected_step:replay.step};if(kind==="assess"){
    const inputs=JSON.stringify({id:replay.id,step:replay.step,provider:status?.provider_config_hash,packet:evidence?.packet_hash});
    if(key.current?.inputs!==inputs)key.current={inputs,value:crypto.randomUUID()};
    body={expected_step:replay.step,provider_config_hash:status?.provider_config_hash,idempotency_key:key.current.value};
  }
  const row=await opportunityRequest<Replay>(`/replays/${replay.id}/${kind}`,body);if(mounted.current){onUpdate(row);if(kind==="assess")key.current=null;}
  }catch(e){if(mounted.current){setError(e instanceof Error?e.message:"Historical evidence request failed");try{const row=await opportunityRequest<Replay>(`/replays/${replay.id}`);if(mounted.current)onUpdate(row);}catch{/* keep prior view */}}}
  finally{pending.current=false;if(mounted.current)setBusy(false);}
 }
 const proposal=assessment?.receipt?.proposal;
 function claimCard(claim:Claim,index:number){return <article key={index}><p>{claim.text}</p><ul>{claim.citations.map((c,i)=><li key={i}><q>{c.quote}</q> — <a href={`#historical-${evidence?.id}-${c.source_id}`} onClick={()=>{if(sources.current)sources.current.open=true;}}>{c.source_id}</a></li>)}</ul></article>;}
 return <article aria-label="Historical filings and Astra assessment"><h2>Evidence available before {replay.visible_through}</h2><p>Original filings and their numeric facts, with a declared next-day availability rule. Later prices and current company metrics are excluded from this assessment.</p>
 {error&&<p role="alert">{error}</p>}{busy&&<p role="status">{evidence?.state==="ready"?"Saving Astra request…":"Collecting historical filing documents…"}</p>}
 {!replay.complete&&<div className="desk-actions"><button disabled={busy||running||evidence?.state==="ready"} onClick={()=>void act("historical-evidence")}>{evidence?.state==="failed"||evidence?.state==="interrupted"?"Retry historical collection":"Collect historical filings"}</button><button disabled={busy||running||evidence?.state!=="ready"||!status?.available||assessment?.state==="completed"} onClick={()=>void act("assess")}>Ask Astra about this historical packet</button></div>}
 <p>{evidence?.message??"Collect evidence for this decision date, then request its Astra assessment."}</p><p>{status?.message}</p>
 {assessment&&<><h3>Astra · {assessment.state.replaceAll("_"," ")}</h3><p role="status">{assessment.message}</p><p>Model: {assessment.receipt?.actual_model_id??"Unconfirmed"} · Input tokens: {assessment.receipt?.input_tokens??"Unconfirmed"} · Output tokens: {assessment.receipt?.output_tokens??"Unconfirmed"}</p>
 {proposal&&<><h4>Historical assessment</h4>{claimCard(proposal.overview,0)}<h4>Catalysts to investigate</h4>{proposal.catalysts.map(claimCard)}<h4>Bull case</h4>{proposal.bull_case.map(claimCard)}<h4>Bear case</h4>{proposal.bear_case.map(claimCard)}{proposal.evidence_checks?.length? <><h4>Evidence comparisons</h4>{proposal.evidence_checks.map(claimCard)}</>:null}<h4>What would change the assessment?</h4><ul>{proposal.rejection_tests.map((s,i)=><li key={i}>{s}</li>)}</ul><h4>Unanswered questions</h4><ul>{proposal.gaps.map((s,i)=><li key={i}>{s}</li>)}</ul></>}
 <a href={`${apiBase()}/api/discover/briefs/${assessment.brief_id}/evidence.zip`} download>Download historical packet, assessment and original filings</a></>}
 {evidence?.packet&&<><details><summary>Original financial facts ({evidence.packet.facts.length})</summary><p>Latest extracted period and comparable prior-year period. Period dates distinguish quarterly, annual and cumulative figures.</p><div className="desk-table"><table><thead><tr><th>Metric</th><th>Period role</th><th>USD</th><th>Period</th><th>Filed</th></tr></thead><tbody>{evidence.packet.facts.map((f,i)=><tr key={i}><th>{f.metric.replaceAll("_"," ")}</th><td>{f.period_role.replaceAll("_"," ")}</td><td>{Number(f.value).toLocaleString()}</td><td>{f.start??"As of"} – {f.end}</td><td>{f.filed}</td></tr>)}</tbody></table></div></details>
 <details ref={sources}><summary>Historical source excerpts and dates</summary>{evidence.packet.sources.map(s=><article id={`historical-${evidence.id}-${s.source_id}`} key={s.source_id}><h4>{s.title}</h4><p>Published: {s.published_at??"Unknown"} · Retrieved: {s.retrieved_at}</p>{s.url&&/^https:\/\//.test(s.url)&&<a href={s.url} target="_blank" rel="noreferrer">Open original source</a>}<p style={{whiteSpace:"pre-wrap",overflowWrap:"anywhere"}}>{s.text}</p></article>)}</details>
 <details><summary>Historical availability and limits</summary><p>{evidence.packet.availability_rule}</p><p>{evidence.packet.scope}</p><ul>{evidence.packet.gaps.map((s,i)=><li key={i}>{s}</li>)}</ul><p>Packet hash: <code>{evidence.packet_hash}</code></p></details></>}
 </article>;
}
