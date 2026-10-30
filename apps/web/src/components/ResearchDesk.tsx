"use client";
import { useEffect, useRef, useState } from "react";
import { apiBase } from "@/lib/api";
import { ExplorerBriefPanel } from "./ExplorerBriefPanel";
import "./ResearchDesk.css";

type Fact = { value: number; unit: string; start: string | null; end: string; filed: string; tag: string; accession: string };
type Filing = { form: string; filed: string; description: string; url: string; accession: string };
type Company = { symbol: string; collected_at: string; profile: Record<string, string>; sec_name?: string; security_type: string; security_description?:string; filing_excerpts?:{form:string;filed:string;url:string;text:string;excerpt_scope:string}[]; metrics: Record<string, number | null>; financials: Record<string, Fact>; filings: Filing[]; gaps: string[]; sources: {url:string;sha256:string;retrieved_at:string}[] };
type Saved<T> = { id: string; symbol: string; created_at: string; payload: T };
type Checks = {state:string;checks:{name:string;value:number|null;threshold:number;state:string}[]};
type Monitor = { snapshot_id:string;thesis:string;invalidation:string;active:boolean;min_growth:number;min_margin:number };
type Review = { monitor_id:string;state:string;snapshot_id:string;changes:{metric:string;before:number|null;after:number|null}[];new_filings:Filing[];checks:Checks;interpretation:string };
type Experiment = {state:string;message?:string;promotion_eligible:false;manifest_hash?:string;period?:string;assumptions?:string[];results?:{cost:string;control:string;net_return_pct:string;max_drawdown_pct:string;fills:number;risk_pauses:number;result_hash:string}[]};
type Trial = {research_data_readiness?:{state:string;checked_at?:string;criteria_hash?:string;review_hash?:string;calendar_sessions?:number;bars_per_feed?:Record<string,number>;dividends_missing_currency?:number;known_effective_window_omissions?:number|null;remaining:string[];scope:string};generated_at:string;operational_evidence_complete:boolean;account_reconciled:boolean;trial_pnl_usd:string|null;trial_metrics:{reason:string|null;maximum_drawdown_usd:string|null};sessions:{session_date:string;state:string}[];orders:{order_id:string;local_state:string;broker_receipt:{state:string;broker_order_id:string}|null}[];limitations:string[]};
type Allocation = {observed_at:string;cash_before_usd:string;cash_after_usd:string;known_open_buy_commitments_usd:string;cash_after_known_commitments_usd:string;cash_coverage:string;weight_before_pct:string;weight_after_pct:string;holdings:{symbol:string;value_after_usd:string;weight_after_pct:string}[];limitations:string[];open_orders:unknown[];local_pending_buys:{symbol:string;amount_usd:string;state:string}[];scheduled_buys:{symbol:string;schedule_id:string;amount_usd:string}[];deployment_budgets:{name:string;state:string;capital_usd:string}[]};
const tabs = ["Company evidence", "Financial screens", "Thesis monitors", "Development experiment", "Paper trial", "Portfolio impact"];
const label = (s: string) => s.replaceAll("_", " ");
const number = (v: string | number | null | undefined) => v === null || v === undefined ? "Unavailable" : Number(v).toLocaleString(undefined,{maximumFractionDigits:2});
const stamp = (s: string) => new Date(s).toLocaleString();
async function request<T>(path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const response=await fetch(`${apiBase()}/api/discover/desk${path}`,{method:body===undefined?"GET":"POST",headers:body===undefined?undefined:{"Content-Type":"application/json"},body:body===undefined?undefined:JSON.stringify(body),signal,cache:"no-store"});
  const data=await response.json();if(!response.ok)throw new Error(typeof data.detail==="string"?data.detail:`Request failed (${response.status})`);return data;
}
function CheckList({checks}:{checks:Checks}) {return <ul>{checks.checks.map(c=><li key={c.name}>{c.name}: <strong>{number(c.value)}</strong> · greater than {number(c.threshold)} · {c.state}</li>)}</ul>}
function Filings({items}:{items:Filing[]}) {return <ul>{items.map(f=><li key={f.accession}><a href={f.url} target="_blank" rel="noreferrer">{f.form} · {f.filed} · {f.description || "SEC filing"}</a></li>)}</ul>}

export function ResearchDesk({symbol:initialSymbol}:{symbol:string}) {
  const [tab,setTab]=useState(0);const [symbol,setSymbol]=useState(initialSymbol || "PLTR");
  const [company,setCompany]=useState<Saved<Company>|null>(null);const [companies,setCompanies]=useState<Saved<Company>[]>([]);
  const [symbols,setSymbols]=useState("AAPL, MSFT, NVDA, PLTR");const [growth,setGrowth]=useState("10");const [margin,setMargin]=useState("0");
  const [screen,setScreen]=useState<{results:{snapshot:Saved<Company>;screen:Checks}[];scope:string}|null>(null);
  const [thesis,setThesis]=useState("");const [invalidation,setInvalidation]=useState("");
  const [monitors,setMonitors]=useState<Saved<Monitor>[]>([]);const [reviews,setReviews]=useState<Saved<Review>[]>([]);
  const [experiments,setExperiments]=useState<Saved<Experiment>[]>([]);const [trial,setTrial]=useState<Trial|null>(null);
  const [allocation,setAllocation]=useState<Saved<Allocation>|null>(null);const [amount,setAmount]=useState("1000");
  const [worker,setWorker]=useState<{state:string;checked_at:string|null;error:string|null}|null>(null);
  const [busy,setBusy]=useState("");const [error,setError]=useState("");const [notice,setNotice]=useState("");
  const [brief,setBrief]=useState<{symbol:string;revision:number}|null>(null);
  const mounted=useRef(true);const pending=useRef(false);
  useEffect(()=>{setSymbol(initialSymbol || "PLTR")},[initialSymbol]);
  useEffect(()=>{
    mounted.current=true;const controller=new AbortController();let timer:ReturnType<typeof setTimeout>;
    async function load(){
      try {
        const [c,m,r,e,w]=await Promise.all([
          request<{records:Saved<Company>[]}>('/records/company',undefined,controller.signal),request<{records:Saved<Monitor>[]}>('/records/monitor',undefined,controller.signal),
          request<{records:Saved<Review>[]}>('/records/review',undefined,controller.signal),request<{records:Saved<Experiment>[]}>('/records/experiment',undefined,controller.signal),
          request<{worker:typeof worker}>('/status',undefined,controller.signal)]);
        if(controller.signal.aborted)return;setCompanies(c.records);setMonitors(m.records);setReviews(r.records);setExperiments(e.records);setWorker(w.worker);
      } catch(e){if(!controller.signal.aborted)setError(e instanceof Error?e.message:"Could not load saved research")}
      if(!controller.signal.aborted)timer=setTimeout(load,30000);
    }
    void load();return()=>{mounted.current=false;controller.abort();clearTimeout(timer)};
  },[]);
  async function act(name:string,fn:()=>Promise<void>){if(pending.current)return;pending.current=true;setBusy(name);setError("");setNotice("");try{await fn()}catch(e){if(mounted.current)setError(e instanceof Error?e.message:"Research request failed")}finally{pending.current=false;if(mounted.current)setBusy("")}}
  const normalized=symbol.trim().toUpperCase();const valid=/^[A-Z][A-Z0-9.\-]{0,11}$/.test(normalized);
  const selected=company?.symbol===normalized?company:companies.find(c=>c.symbol===normalized)??null;
  const validThresholds=Number.isFinite(Number(growth))&&Number(growth)>=-100&&Number(growth)<=1000&&Number.isFinite(Number(margin))&&Number(margin)>=-1000&&Number(margin)<=100;
  const disabled=!!busy;
  return <section className="research-desk" aria-label="Research desk">
    <header><span className="panel-kicker">Evidence → thesis → experiment → review</span><h1>Research desk</h1><p>Build a dated case for an idea, test its rules, and inspect its place in the portfolio.</p></header>
    <nav aria-label="Research desk tools">{tabs.map((title,i)=><button key={title} aria-pressed={tab===i} onClick={()=>setTab(i)}>{i+1}. {title}</button>)}</nav>
    {error&&<p role="alert" className="desk-error">{error}</p>}{busy&&<p role="status">{busy}…</p>}{notice&&<p role="status">{notice}</p>}
    {(tab===0||tab===5)&&<label className="desk-field">Symbol<input value={symbol} maxLength={12} onChange={e=>setSymbol(e.target.value.toUpperCase())}/></label>}
    {tab===0&&<>
      <button disabled={disabled||!valid} onClick={()=>void act('Collecting company evidence',async()=>{const r=await request<Saved<Company>>(`/company/${normalized}`,{});setCompany(r);setCompanies(p=>[r,...p]);setNotice('Company evidence saved. You can now generate a brief using these facts.')} )}>Refresh company evidence</button>
      <p>Reads the existing Finnhub connection and SEC filings. Each refresh preserves the source receipts. No model runs until you request a brief.</p>
      {selected?<article><h2>{selected.payload.profile.name || selected.payload.sec_name || selected.symbol} <small>{selected.symbol}</small></h2>
        <p>Collected {stamp(selected.created_at)} · {selected.payload.profile.finnhubIndustry || "Industry unavailable"} · Security type: {label(selected.payload.security_type)}{selected.payload.security_description&&` · ${selected.payload.security_description}`}</p>
        <div className="desk-stats">{Object.entries(selected.payload.metrics).map(([k,v])=><div key={k}><span>{label(k)}{["revenue_growth","net_margin"].includes(k)?" (%)":k==="market_cap"?" (USD millions)":""}</span><strong>{number(v)}</strong></div>)}</div>
        <h3>Annual statements · USD</h3><div className="desk-table"><table><thead><tr><th>Fact</th><th>Value</th><th>Period end</th><th>Filed</th></tr></thead><tbody>{Object.entries(selected.payload.financials).map(([k,v])=><tr key={k}><td>{label(k)}</td><td>{number(v.value)}</td><td>{v.end}</td><td>{v.filed}</td></tr>)}</tbody></table></div>
        {!Object.keys(selected.payload.financials).length&&<p>No supported annual financial facts were returned.</p>}
        <h3>Filings and earnings disclosures</h3><p>Open the source to assess guidance and earnings language. Filing metadata alone does not establish a catalyst.</p><Filings items={selected.payload.filings}/>{selected.payload.filing_excerpts?.map((e,i)=><details key={i}><summary>{e.form} excerpt · filed {e.filed}</summary><p>{e.text}</p><p>{e.excerpt_scope} <a href={e.url} target="_blank" rel="noreferrer">Read source</a></p></details>)}
        <details><summary>Coverage gaps and source receipts</summary>{Object.entries(selected.payload.financials).map(([k,v])=><p key={k}>{label(k)}: {v.start || "Point in time"} through {v.end}; filed {v.filed}; accession {v.accession}; tag <code>{v.tag}</code></p>)}<ul>{selected.payload.gaps.map(g=><li key={g}>{g}</li>)}</ul>{selected.payload.sources.map((s,i)=><p key={i}><a href={s.url} target="_blank" rel="noreferrer">Source {i+1}</a> · {stamp(s.retrieved_at)}<br/><code>{s.sha256}</code></p>)}</details>
        <div className="desk-actions"><button onClick={()=>{setTab(2);setCompany(selected)}}>Save a thesis for {selected.symbol}</button><button onClick={()=>setBrief({symbol:selected.symbol,revision:Date.now()})}>Prepare evidence brief</button></div>
      </article>:<p>No saved company evidence for {normalized}. Refresh to collect it.</p>}
      {brief&&<ExplorerBriefPanel selection={brief}/>}
      <details><summary>Saved snapshots ({companies.length} recent)</summary>{companies.map(c=><p key={c.id}><button onClick={()=>{setSymbol(c.symbol);setCompany(c)}}>{c.symbol} · {stamp(c.created_at)}</button></p>)}</details>
    </>}
    {tab===1&&<>
      <h2>Cash-generating growth screen</h2><p>Scan up to 12 explicit symbols. All three conditions must pass: revenue growth, net margin, and positive annual free cash flow. Missing facts stay unknown.</p>
      <label className="desk-field">Symbols, separated by commas<input value={symbols} onChange={e=>setSymbols(e.target.value.toUpperCase())}/></label>
      <div className="desk-actions"><label>Revenue growth above (%)<input type="number" value={growth} onChange={e=>setGrowth(e.target.value)}/></label><label>Net margin above (%)<input type="number" value={margin} onChange={e=>setMargin(e.target.value)}/></label></div>
      <button disabled={disabled||!validThresholds} onClick={()=>void act('Screening companies; each source can take several seconds',async()=>{const values=symbols.split(/[\s,]+/).filter(Boolean);if(values.length<1||values.length>12||values.some(v=>!/^[A-Z][A-Z0-9.\-]{0,11}$/.test(v)))throw new Error('Enter 1–12 valid symbols');const r=await request<NonNullable<typeof screen>>('/screen',{symbols:values,min_growth:Number(growth),min_margin:Number(margin),require_fcf:true});setScreen(r);setCompanies(p=>[...r.results.map(v=>v.snapshot),...p])})}>Run financial screen</button>
      {screen&&<><p>{screen.scope}</p>{screen.results.map(r=><article key={r.snapshot.id}><h3>{r.snapshot.symbol} · {r.screen.state}</h3><CheckList checks={r.screen}/><button onClick={()=>{setCompany(r.snapshot);setSymbol(r.snapshot.symbol);setTab(0)}}>Inspect company evidence</button></article>)}</>}
    </>}
    {tab===2&&<>
      <h2>Keep the thesis accountable</h2><p>Daily checks run while the local API is running. Numeric conditions can flag a breach; written invalidation conditions remain questions for your review.</p>
      <p>Monitor worker: {worker?.state || "Checking"} · Last check: {worker?.checked_at?stamp(worker.checked_at):"not observed"}{worker?.error&&` · ${worker.error}`}</p>
      {selected?<article><h3>New thesis · {selected.symbol}</h3><p>Baseline: {stamp(selected.created_at)}</p><label>Your investment question<textarea value={thesis} onChange={e=>setThesis(e.target.value)} maxLength={2000}/></label><label>What would invalidate it?<textarea value={invalidation} onChange={e=>setInvalidation(e.target.value)} maxLength={2000}/></label>
        <div className="desk-actions"><label>Growth must stay above (%)<input type="number" value={growth} onChange={e=>setGrowth(e.target.value)}/></label><label>Margin must stay above (%)<input type="number" value={margin} onChange={e=>setMargin(e.target.value)}/></label></div><p>Positive annual free cash flow is also required.</p>
        <button disabled={disabled||thesis.trim().length<10||invalidation.trim().length<10||!validThresholds} onClick={()=>void act('Saving thesis monitor',async()=>{const r=await request<Saved<Monitor>>('/monitors',{snapshot_id:selected.id,thesis:thesis.trim(),invalidation:invalidation.trim(),min_growth:Number(growth),min_margin:Number(margin)});setMonitors(p=>[r,...p]);setThesis('');setInvalidation('');setNotice('Thesis saved; its first review is due on the next worker check.')})}>Save daily thesis monitor</button></article>:<p>Collect company evidence first to establish a baseline.</p>}
      {monitors.length===0&&<p>No saved thesis monitors.</p>}{monitors.map(m=>{const r=reviews.find(v=>v.payload.monitor_id===m.id);return <article key={m.id}><h3>{m.symbol} · {m.payload.active?"Daily checks enabled":"Paused"}</h3><p>{m.payload.thesis}</p><p><strong>Invalidation:</strong> {m.payload.invalidation}</p><div className="desk-actions"><button disabled={disabled} onClick={()=>void act('Reviewing thesis',async()=>{const r=await request<Saved<Review>>(`/monitors/${m.id}/review`,{});setReviews(p=>[r,...p])})}>Review now</button><button disabled={disabled} onClick={()=>void act('Updating monitor',async()=>{const r=await request<Saved<Monitor>>(`/monitors/${m.id}/toggle`,{});setMonitors(p=>p.map(v=>v.id===r.id?r:v))})}>{m.payload.active?"Pause":"Resume"}</button></div>
        {r?<><h4>{label(r.payload.state)} · {stamp(r.created_at)}</h4><CheckList checks={r.payload.checks}/>{r.payload.changes.map(c=><p key={c.metric}>{label(c.metric)}: {number(c.before)} → {number(c.after)}</p>)}<Filings items={r.payload.new_filings}/><p>{r.payload.interpretation}</p><details><summary>Review history</summary>{reviews.filter(v=>v.payload.monitor_id===m.id).map(v=><p key={v.id}>{stamp(v.created_at)} · {label(v.payload.state)} · <code>{v.payload.snapshot_id}</code></p>)}</details></>:<p>First review pending.</p>}</article>})}
    </>}
    {tab===3&&<>
      <h2>Put the trend proposal through a real-data experiment</h2><p>Uses captured Alpaca SIP bars, the saved Astra trend design, 2022 warmup, and 2023 development only. Compares strategy, fixed basket, and cash at base and doubled costs.</p><p>Historical availability, dividend timing, and instrument mapping are explicit reconstruction assumptions. The result cannot authorize deployment or qualify the paper trial.</p><p>A risk pause stops new entries; it does not liquidate holdings or guarantee a maximum loss.</p>
      <button disabled={disabled} onClick={()=>void act('Running six development comparisons',async()=>{const r=await request<Saved<Experiment>>('/experiment',{});setExperiments(p=>[r,...p.filter(v=>v.id!==r.id)])})}>Run development experiment</button>
      {experiments.length===0&&<p>No saved development experiment yet.</p>}{experiments.map(e=><article key={e.id}><h3>{label(e.payload.state)} · {e.payload.period || "Development replay"}</h3><p>{stamp(e.created_at)} · Deployment eligible: no</p>{e.payload.message&&<p>{e.payload.message}</p>}
        {e.payload.results&&<div className="desk-table"><table><thead><tr><th>Costs</th><th>Control</th><th>Net return</th><th>Max drawdown</th><th>Fills</th><th>Risk pauses</th></tr></thead><tbody>{e.payload.results.map(r=><tr key={r.cost+r.control}><td>{label(r.cost)}</td><td>{label(r.control)}</td><td>{number(r.net_return_pct)}%</td><td>{number(r.max_drawdown_pct)}%</td><td>{r.fills}</td><td>{r.risk_pauses}</td></tr>)}</tbody></table></div>}
        <details><summary>Assumptions and reproducibility</summary><ul>{e.payload.assumptions?.map(a=><li key={a}>{a}</li>)}</ul><p>Manifest <code>{e.payload.manifest_hash}</code></p>{e.payload.results?.map(r=><p key={r.result_hash}>{r.cost} / {r.control}: <code>{r.result_hash}</code></p>)}</details></article>)}
    </>}
    {tab===4&&<>
      <h2>Five-session Alpaca paper trial</h2><button disabled={disabled} onClick={()=>void act('Reading preserved trial receipts',async()=>setTrial(await request<Trial>('/trial')))}>Refresh trial evidence</button>
      {trial?<><p>Report {stamp(trial.generated_at)} · Operational evidence complete: {trial.operational_evidence_complete?"yes":"no"} · Account reconciled: {trial.account_reconciled?"yes":"no"}</p><div className="desk-stats"><div><span>Trial-attributed P&amp;L (USD)</span><strong>{number(trial.trial_pnl_usd)}</strong></div><div><span>Observed maximum drawdown (USD)</span><strong>{number(trial.trial_metrics.maximum_drawdown_usd)}</strong></div></div>{trial.trial_metrics.reason&&<p>{label(trial.trial_metrics.reason)}</p>}<ul>{trial.sessions.map(s=><li key={s.session_date}>{s.session_date} · {label(s.state)}</li>)}</ul>{trial.research_data_readiness&&<article aria-label="Trial research source readiness"><h3>Research source readiness</h3><p>{label(trial.research_data_readiness.state)}</p><p>{trial.research_data_readiness.scope}</p>{trial.research_data_readiness.checked_at&&<p>Checked {stamp(trial.research_data_readiness.checked_at)}</p>}{trial.research_data_readiness.bars_per_feed&&<p>{trial.research_data_readiness.calendar_sessions} calendar sessions · {Object.entries(trial.research_data_readiness.bars_per_feed).map(([feed,n])=>`${feed.toUpperCase()}: ${n.toLocaleString()} bars`).join(" · ")}</p>}<ul>{trial.research_data_readiness.remaining.map(g=><li key={g}>{g}</li>)}</ul>{trial.research_data_readiness.review_hash&&<details><summary>Criteria and source-review fingerprints</summary><p>Criteria <code>{trial.research_data_readiness.criteria_hash}</code></p><p>Review <code>{trial.research_data_readiness.review_hash}</code></p></details>}</article>}<h3>Exact order evidence</h3>{trial.orders.map(o=><article key={o.order_id}><code>{o.order_id}</code><p>Local: {o.local_state} · Broker: {o.broker_receipt?.state || "No submission receipt"}</p></article>)}<ul>{trial.limitations.map(l=><li key={l}>{l}</li>)}</ul></>:<p>Refresh to read the saved schedule, broker receipts, and session observations. This does not submit or approve an order.</p>}
    </>}
    {tab===5&&<>
      <h2>Preview a cash allocation</h2><p>See how a hypothetical purchase changes paper-account cash and direct position concentration. Reads the broker account without placing an order.</p><label className="desk-field">Hypothetical purchase (USD)<input type="number" min="0.01" max="10000000" step="0.01" value={amount} onChange={e=>setAmount(e.target.value)}/></label>
      <button disabled={disabled||!valid||!Number.isFinite(Number(amount))||Number(amount)<=0} onClick={()=>void act('Reading paper-account exposure',async()=>setAllocation(await request<Saved<Allocation>>('/allocation',{symbol:normalized,amount_usd:amount})))}>Preview portfolio impact</button>
      {allocation&&<article><h3>{allocation.symbol} · observed {stamp(allocation.payload.observed_at)}</h3><p>Direct position weight: {number(allocation.payload.weight_before_pct)}% → {number(allocation.payload.weight_after_pct)}%</p><p>Cash: ${number(allocation.payload.cash_before_usd)} → ${number(allocation.payload.cash_after_usd)}</p><p>Known broker open-buy commitments: ${number(allocation.payload.known_open_buy_commitments_usd)} · Cash after all listed commitments: ${number(allocation.payload.cash_after_known_commitments_usd)} · {label(allocation.payload.cash_coverage)}</p><div className="desk-table"><table><thead><tr><th>Holding</th><th>Value after (USD)</th><th>Weight after</th></tr></thead><tbody>{allocation.payload.holdings.map(h=><tr key={h.symbol}><td>{h.symbol}</td><td>{number(h.value_after_usd)}</td><td>{number(h.weight_after_pct)}%</td></tr>)}</tbody></table></div><h4>Other commitments</h4><ul>{allocation.payload.local_pending_buys.map((r,i)=><li key={i}>Reserved {r.symbol}: ${number(r.amount_usd)} · {r.state}</li>)}{allocation.payload.scheduled_buys.map((r,i)=><li key={i}>Scheduled {r.symbol}: ${number(r.amount_usd)}</li>)}</ul><h4>Active strategy budgets</h4>{allocation.payload.deployment_budgets.length===0?<p>No active strategy budgets recorded.</p>:<ul>{allocation.payload.deployment_budgets.map((r,i)=><li key={i}>{r.name}: ${number(r.capital_usd)} · {r.state}</li>)}</ul>}<ul>{allocation.payload.limitations.map(l=><li key={l}>{l}</li>)}</ul></article>}
    </>}
  </section>;
}
