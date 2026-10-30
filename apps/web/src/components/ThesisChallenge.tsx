"use client";
import { useEffect, useRef, useState } from "react";
import { apiBase } from "@/lib/api";
import "./ResearchDesk.css";
import "./ForecastLab.css";

type Citation = {source_id:string;quote:string|null;region?:string|null};
type Assessment = {claim_id:string;verdict:string;reasoning:string;citations:Citation[];evidence_to_change_assessment:string};
type Proposal = {summary:string;assessments:Assessment[];falsification_tests:{claim_id:string;observation_required:string;consequence:string}[];missing_evidence:string[];limitations:string[]};
type Brief = {brief_id:string;symbol:string;model_id:string;state:string;created_at:string;message:string;packet_hash:string|null;
  packet:{purpose?:string;parent_brief_id?:string;parent_packet_hash?:string;target_claims?:{claim_id:string;text:string}[];scope:string;sources:{source_id:string;title:string;text:string;url:string|null;retrieved_at:string;published_at:string|null}[]}|null;
  receipt:{proposal:Proposal|null;actual_model_id:string;input_tokens:number|null;output_tokens:number|null;validation_errors:string[]}|null};
type Status = {available:boolean;provider_config_hash?:string;model_id?:string;message:string};
const active = (state:string) => ["queued","collecting","synthesizing"].includes(state);
const base = () => `${apiBase()}/api/discover/briefs`;
async function request<T>(path:string,body?:unknown,signal?:AbortSignal):Promise<T> {
  const response=await fetch(base()+path,{method:body===undefined?"GET":"POST",cache:"no-store",signal,headers:body===undefined?undefined:{"Content-Type":"application/json"},body:body===undefined?undefined:JSON.stringify(body)});
  const data=await response.json();if(!response.ok)throw new Error(typeof data.detail==="string"?data.detail:`Request failed (${response.status})`);return data;
}
export function ThesisChallenge() {
  const [originals,setOriginals]=useState<Brief[]>([]);const [challenges,setChallenges]=useState<Brief[]>([]);
  const [status,setStatus]=useState<Status|null>(null);const [parent,setParent]=useState("");const [selected,setSelected]=useState("");
  const [error,setError]=useState("");const [loading,setLoading]=useState(true);const [busy,setBusy]=useState(false);
  const sourceDetails=useRef<HTMLDetailsElement>(null);
  const mounted=useRef(true);const pending=useRef(false);const key=useRef<{inputs:string;value:string}|null>(null);
  useEffect(()=>{
    mounted.current=true;const controller=new AbortController();let timer:ReturnType<typeof setTimeout>;
    async function load(){
      try{
        const [provider,briefs,reviews]=await Promise.all([request<Status>("/status",undefined,controller.signal),request<{briefs:Brief[]}>("",undefined,controller.signal),request<{briefs:Brief[]}>("?purpose=challenge",undefined,controller.signal)]);
        if(controller.signal.aborted)return;setStatus(provider);setOriginals(briefs.briefs);setChallenges(reviews.briefs);setError("");
      }catch(e){if(!controller.signal.aborted)setError(e instanceof Error?e.message:"Could not read challenge history");}
      finally{if(!controller.signal.aborted){setLoading(false);timer=setTimeout(load,3000);}}
    }
    void load();return()=>{mounted.current=false;controller.abort();clearTimeout(timer);};
  },[]);
  const eligible=originals.filter(b=>b.state==="completed");
  const original=eligible.find(b=>b.brief_id===parent)??eligible[0];
  const current=challenges.find(b=>b.brief_id===selected)??challenges[0];const proposal=current?.receipt?.proposal;
  const running=[...originals,...challenges].some(b=>active(b.state));
  async function start(){
    if(pending.current||!original||!status?.provider_config_hash)return;
    pending.current=true;setBusy(true);setError("");
    const inputs={symbol:original.symbol,challenge_brief_id:original.brief_id,provider_config_hash:status.provider_config_hash};
    const encoded=JSON.stringify(inputs);if(key.current?.inputs!==encoded)key.current={inputs:encoded,value:crypto.randomUUID()};
    try{
      const row=await request<Brief>("",{...inputs,idempotency_key:key.current.value});
      if(mounted.current){setChallenges(rows=>[row,...rows.filter(r=>r.brief_id!==row.brief_id)]);setSelected(row.brief_id);key.current=null;}
    }catch(e){if(mounted.current)setError(e instanceof Error?e.message:"Challenge request failed");}
    finally{pending.current=false;if(mounted.current)setBusy(false);}
  }
  return <section className="research-desk forecast-lab" aria-label="Independent thesis challenge">
    <h2>Challenge the thesis</h2><p>A separate Astra call checks each saved claim for contrary evidence, unsupported assumptions, and conditions that would change the assessment.</p>
    <p>Uses the original evidence and its original dates. A second pass with the same model is not an independent source, and cannot establish that a thesis is true.</p>
    {loading&&<p role="status">Loading saved briefs…</p>}{error&&<p role="alert">{error}</p>}
    <label>Original research brief<select value={original?.brief_id??""} disabled={busy||loading} onChange={e=>setParent(e.target.value)}>
      {!eligible.length&&<option value="">No completed brief available</option>}{eligible.map(b=><option key={b.brief_id} value={b.brief_id}>{b.symbol} · {new Date(b.created_at).toLocaleString()}</option>)}</select></label>
    {!loading&&!eligible.length&&<p>Create a brief in Research explorer or Opportunity inbox first.</p>}
    <p>{status?.message}</p><button disabled={busy||loading||running||!original||!status?.available} onClick={()=>void start()}>{busy?"Saving challenge…":"Run independent Astra challenge"}</button>
    {running&&<p role="status">A research call is active. Its saved status will update here.</p>}
    <h3>Saved challenges</h3><label>Review history<select value={current?.brief_id??""} onChange={e=>setSelected(e.target.value)}>{!challenges.length&&<option value="">No challenges yet</option>}{challenges.map(b=><option value={b.brief_id} key={b.brief_id}>{b.symbol} · {b.state} · {new Date(b.created_at).toLocaleString()}</option>)}</select></label>
    {current&&<article><h3>{current.symbol} · {current.state.replaceAll("_"," ")}</h3><p role="status">{current.message}</p>
      <p>Model: {current.receipt?.actual_model_id??"No completed model receipt"} · Input tokens: {current.receipt?.input_tokens??"Unconfirmed"} · Output tokens: {current.receipt?.output_tokens??"Unconfirmed"}</p>
      {current.packet_hash&&<a href={`${base()}/${current.brief_id}/evidence.zip`} download>Download original evidence and challenge</a>}
      {proposal&&<><p>{proposal.summary}</p>{proposal.assessments.map(a=><article key={a.claim_id}><h4>{a.verdict==="supported"?"Supported within this evidence packet":a.verdict.replaceAll("_"," ")}</h4><p><strong>Original claim:</strong> {current.packet?.target_claims?.find(c=>c.claim_id===a.claim_id)?.text??a.claim_id}</p><p>{a.reasoning}</p>
        <ul>{a.citations.map((c,i)=><li key={i}>{c.region?`Visual interpretation: ${c.region}`:<q>{c.quote}</q>} — <a onClick={()=>{if(sourceDetails.current)sourceDetails.current.open=true;}} href={`#challenge-${current.brief_id}-${c.source_id}`}>{c.source_id}</a></li>)}</ul>
        <p><strong>What could change this:</strong> {a.evidence_to_change_assessment}</p></article>)}
        <h4>Tests that could invalidate the thesis</h4>{proposal.falsification_tests.map((t,i)=><p key={i}><strong>{t.observation_required}</strong> {t.consequence}</p>)}
        <h4>Missing evidence</h4><ul>{proposal.missing_evidence.map((v,i)=><li key={i}>{v}</li>)}</ul><h4>Limits of this review</h4><ul>{proposal.limitations.map((v,i)=><li key={i}>{v}</li>)}</ul></>}
      <details ref={sourceDetails}><summary>Frozen evidence and source dates</summary><p>{current.packet?.scope}</p><p>Original brief: {current.packet?.parent_brief_id}</p><p>Original packet hash: <code>{current.packet?.parent_packet_hash}</code></p>
        {current.packet?.sources.map(s=><article id={`challenge-${current.brief_id}-${s.source_id}`} key={s.source_id}><h4>{s.title}</h4><p>Published: {s.published_at??"Unknown"} · Retrieved: {s.retrieved_at}</p>{s.url&&/^https?:\/\//.test(s.url)&&<a href={s.url} target="_blank" rel="noreferrer">Open source</a>}<p style={{whiteSpace:"pre-wrap",overflowWrap:"anywhere"}}>{s.text}</p></article>)}</details>
    </article>}
  </section>;
}
