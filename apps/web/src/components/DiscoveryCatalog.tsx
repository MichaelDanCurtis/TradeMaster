"use client";
import { useEffect, useRef, useState } from "react";
import { apiBase } from "@/lib/api";
import { opportunityRequest as request, type Saved, type Scan } from "@/lib/opportunity-lab";

type Universe = Saved<{member_count:number; input_rows:number; excluded_count:number; exchange_counts:Record<string,number>; artifact_hash:string; scope:string; source:{url:string;retrieved_at:string;sha256:string}}>;
type Recipe = Saved<{name:string; symbols:string[]; min_growth:number; min_margin:number; require_fcf:boolean; universe_id:string|null; artifact_hash:string}>;
type Catalog = {universes:Universe[]; recipes:Recipe[]};
type MemberPage = {entries:{symbol:string;name:string;cik:number;exchange:string}[]; matched_count:number; offset:number; limit:number;total_count:number};
export type RecipeCriteria = {symbols:string[];min_growth:number;min_margin:number;require_fcf:boolean};

export function DiscoveryCatalog({criteria, valid, disabled, onBasket, onScan}: {
  criteria:RecipeCriteria; valid:boolean; disabled:boolean;
  onBasket:(symbols:string[])=>void; onScan:(scan:Scan)=>void;
}) {
  const [catalog,setCatalog]=useState<Catalog>({universes:[],recipes:[]});
  const [universeId,setUniverseId]=useState("");
  const [exchange,setExchange]=useState("");
  const [offset,setOffset]=useState(0);
  const [size,setSize]=useState(100);
  const [page,setPage]=useState<MemberPage|null>(null);
  const [name,setName]=useState("");
  const [recipeId,setRecipeId]=useState("");
  const [busy,setBusy]=useState("");
  const [error,setError]=useState("");
  const [linked,setLinked]=useState(false);
  const pending=useRef(false);
  const universe=catalog.universes.find(u=>u.id===universeId);
  const recipe=catalog.recipes.find(r=>r.id===recipeId);
  useEffect(()=>{const c=new AbortController();request<Catalog>("/catalog",undefined,c.signal).then(setCatalog).catch(e=>{if(!c.signal.aborted)setError(e.message);});return()=>c.abort();},[]);
  useEffect(()=>{
    const c=new AbortController();setPage(null);
    if(universeId) request<MemberPage>(`/universes/${universeId}?exchange=${encodeURIComponent(exchange)}&offset=${offset}&limit=${size}`,undefined,c.signal).then(p=>{if(!c.signal.aborted)setPage(p);}).catch(e=>{if(!c.signal.aborted)setError(e.message);});
    return()=>c.abort();
  },[universeId,exchange,offset,size]);
  async function act(label:string,fn:()=>Promise<void>) {
    if(pending.current)return;pending.current=true;setBusy(label);setError("");
    try{await fn();setCatalog(await request<Catalog>("/catalog"));}
    catch(e){setError(e instanceof Error?e.message:"Request failed. Reload saved records before retrying.");}
    finally{pending.current=false;setBusy("");}
  }
  const blocked=!!busy||disabled;
  const evidence=(kind:string,id:string)=>`${apiBase()}/api/discover/opportunities/${kind}/${id}/evidence.json`;
  return <article aria-label="Discovery directory and screening recipes">
    <h2>Expand your search</h2><p>Browse a saved SEC directory, choose a batch of up to 500 symbols, and reuse your financial screening criteria.</p>
    {error&&<p role="alert" className="desk-error">{error}</p>}{busy&&<p role="status">{busy}…</p>}
    <button disabled={blocked} onClick={()=>void act("Capturing SEC directory",async()=>{const u=await request<Universe>("/universes",{});setUniverseId(u.id);setOffset(0);setLinked(false);})}>Capture current SEC directory</button>
    <label>Saved SEC directory<select value={universeId} disabled={blocked} onChange={e=>{setUniverseId(e.target.value);setOffset(0);setExchange("");setLinked(false);}}><option value="">Select a directory</option>{catalog.universes.map(u=><option key={u.id} value={u.id}>{new Date(u.created_at).toLocaleString()} · {u.payload.member_count.toLocaleString()} symbols</option>)}</select></label>
    {universe&&<>
      <p>{universe.payload.input_rows.toLocaleString()} source rows · {universe.payload.member_count.toLocaleString()} usable symbol mappings · {universe.payload.excluded_count} exclusion or duplicate records.</p>
      <p>{universe.payload.scope}</p>
      <div className="opportunity-fields"><label>Directory exchange<select value={exchange} disabled={blocked} onChange={e=>{setExchange(e.target.value);setOffset(0);}}><option value="">All reported exchanges</option>{Object.entries(universe.payload.exchange_counts).map(([x,n])=><option key={x} value={x}>{x} · {n}</option>)}</select></label>
      <label>Symbols per batch<select value={size} disabled={blocked} onChange={e=>{setSize(Number(e.target.value));setOffset(0);}}>{[50,100,250,500].map(n=><option key={n} value={n}>{n}</option>)}</select></label></div>
      {page?<><p>Alphabetical positions {page.entries.length?offset+1:0}–{offset+page.entries.length} of {page.matched_count.toLocaleString()} matching entries. Alphabetical order is not investment ranking.</p>
        <div className="desk-actions"><button disabled={blocked||offset===0} onClick={()=>setOffset(Math.max(0,offset-size))}>Previous directory batch</button><button disabled={blocked||offset+size>=page.matched_count} onClick={()=>setOffset(offset+size)}>Next directory batch</button><button disabled={blocked||!page.entries.length} onClick={()=>{onBasket(page.entries.map(e=>e.symbol));setLinked(true);}}>Use this directory batch</button></div>
        <details><summary>Inspect {page.entries.length} directory entries</summary><table><thead><tr><th>Symbol</th><th>Issuer</th><th>SEC CIK</th><th>Exchange</th></tr></thead><tbody>{page.entries.map(e=><tr key={e.symbol}><td>{e.symbol}</td><td>{e.name}</td><td>{e.cik}</td><td>{e.exchange}</td></tr>)}</tbody></table></details>
      </>:<p role="status">Loading directory batch…</p>}
      <a href={evidence("universes",universe.id)}>Download directory evidence and exclusions</a>
    </>}
    <h3>Saved screening recipes</h3><p>A recipe preserves the current basket and thresholds. Each run collects new company evidence and explains changes against the previous capture.</p>
    <p>Current basket: {criteria.symbols.length} symbols · growth &gt; {criteria.min_growth}% · margin &gt; {criteria.min_margin}% · positive annual free cash flow {criteria.require_fcf?"required":"not required"}. Edit the basket and criteria below before saving.</p>
    <label>Recipe name<input value={name} maxLength={100} onChange={e=>setName(e.target.value)} /></label>
    <label className="opportunity-check"><input type="checkbox" checked={linked} disabled={!universe||blocked} onChange={e=>setLinked(e.target.checked)} />Require every symbol to match the selected saved SEC directory</label>
    <button disabled={blocked||!valid||!name.trim()} onClick={()=>void act("Saving screening recipe",async()=>{const r=await request<Recipe>("/recipes",{...criteria,name,universe_id:linked?universeId:null});setRecipeId(r.id);})}>Save current basket and criteria as recipe</button>
    <label>Saved screening recipe<select value={recipeId} onChange={e=>setRecipeId(e.target.value)}><option value="">Select a recipe</option>{catalog.recipes.map(r=><option key={r.id} value={r.id}>{r.payload.name} · {r.payload.symbols.length} symbols · {new Date(r.created_at).toLocaleString()}</option>)}</select></label>
    {recipe&&<><p>{recipe.payload.symbols.length} symbols · growth &gt; {recipe.payload.min_growth}% · margin &gt; {recipe.payload.min_margin}% · positive annual free cash flow {recipe.payload.require_fcf?"required":"not required"}. {recipe.payload.universe_id?"Saved SEC issuer membership required.":"Manual basket; directory membership not verified."}</p>
      <details><summary>Recipe symbols and fingerprint</summary><p>{recipe.payload.symbols.join(", ")}</p><code>{recipe.payload.artifact_hash}</code></details>
      <div className="desk-actions"><button disabled={blocked} onClick={()=>void act("Starting saved recipe scan",async()=>onScan(await request<Scan>(`/recipes/${recipe.id}/scan`,{})))}>Run saved screening recipe</button><a href={evidence("recipes",recipe.id)}>Download frozen recipe</a></div>
    </>}
  </article>;
}
