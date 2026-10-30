"use client";
import { useEffect, useRef, useState } from "react";
import { ExplorerBriefPanel } from "./ExplorerBriefPanel";
import { DiscoveryCatalog } from "./DiscoveryCatalog";
import { HistoricalReplay } from "./HistoricalReplay";
import { opportunityRequest as request, parseBasket, validBasket, type Candidate, type Inbox, type Scan, type TriageState } from "@/lib/opportunity-lab";
import "./ResearchDesk.css";
import "./OpportunityInbox.css";

const stamp = (s: string) => new Date(s).toLocaleString();
const pretty = (s: string) => s.replaceAll("_", " ");

export function OpportunityInbox({watchlist, onCompany}: {watchlist: string[]; onCompany: (symbol: string) => void}) {
  const [data, setData] = useState<Inbox | null>(null);
  const [symbols, setSymbols] = useState("");
  const [growth, setGrowth] = useState("10");
  const [margin, setMargin] = useState("0");
  const [fcf, setFcf] = useState(true);
  const [scanId, setScanId] = useState("");
  const [resultPage, setResultPage] = useState(0);
  const [filter, setFilter] = useState("all");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [brief, setBrief] = useState<{symbol: string; revision: number} | null>(null);
  const [replay, setReplay] = useState<{symbol: string; scanId?: string; id?: string} | null>(null);
  const pending = useRef(false);
  const briefTarget = useRef<HTMLDivElement>(null);
  useEffect(() => { if (brief) briefTarget.current?.scrollIntoView({block: "start"}); }, [brief]);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    let delay = 4000;
    async function load() {
      try {
        const result = await request<Inbox>("", undefined, controller.signal);
        if (controller.signal.aborted) return;
        setData(result);
        delay = result.scans.some(s => ["queued", "running"].includes(s.payload.state)) ? 4000 : 15000;
        setSymbols(current => current || (result.scans[0]?.payload.symbols ?? result.starter_symbols).join(", "));
      } catch (e) { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : "Could not load the inbox"); }
      if (!controller.signal.aborted) timer = setTimeout(load, delay);
    }
    void load();
    return () => {mounted.current = false; controller.abort(); clearTimeout(timer);};
  }, []);
  async function act(name: string, fn: () => Promise<void>) {
    if (pending.current) return;
    pending.current = true; setBusy(name); setError("");
    try {await fn(); const result = await request<Inbox>(); if (mounted.current) setData(result);}
    catch (e) {if (mounted.current) setError(e instanceof Error ? e.message : "Request failed");}
    finally {pending.current = false; if (mounted.current) setBusy("");}
  }
  const scan = data?.scans.find(s => s.id === scanId) ?? data?.scans[0];
  const running = data?.scans.some(s => ["queued", "running"].includes(s.payload.state));
  const basket = parseBasket(symbols);
  const thresholdsValid = growth.trim() !== "" && margin.trim() !== "" && Number.isFinite(Number(growth)) && Number(growth) >= -100 && Number(growth) <= 1000 && Number.isFinite(Number(margin)) && Number(margin) >= -1000 && Number(margin) <= 100;
  const stateOf = (symbol: string) => data?.triage.find(t => t.symbol === symbol)?.payload.state ?? "new";
  const candidates = scan?.payload.results.filter(c => filter === "all" || (filter === "reasons" ? c.priority > 0 : stateOf(c.symbol) === filter)) ?? [];
  if (replay) return <HistoricalReplay key={`${replay.symbol}-${replay.id ?? "new"}`} selection={replay} onBack={() => setReplay(null)} />;
  return <section className="research-desk opportunity-inbox" aria-label="Opportunity inbox">
    <header><span className="panel-kicker">Discover · investigate · rehearse</span><h1>Opportunity inbox</h1><p>Look for financial strength, changes since your last capture, and recent filings. Keep the evidence behind every idea.</p></header>
    {error && <p className="desk-error" role="alert">{error}</p>}
    {busy && <p role="status">{busy}…</p>}
    <DiscoveryCatalog criteria={{symbols:basket,min_growth:Number(growth),min_margin:Number(margin),require_fcf:fcf}} valid={validBasket(basket)&&thresholdsValid} disabled={!!busy||!!running} onBasket={s=>setSymbols(s.join(", "))} onScan={s=>{setScanId(s.id);setResultPage(0);setData(d=>d?{...d,scans:[s,...d.scans.filter(x=>x.id!==s.id)]}:d);}} />
    <details open={!scan}><summary>Scan basket and criteria</summary>
      <p>{data?.scope ?? "Loading saved research…"}</p>
      <div className="desk-actions"><button disabled={!data || !!busy} onClick={() => setSymbols(data!.starter_symbols.join(", "))}>Use 32-company starting basket</button><button disabled={!watchlist.length || !!busy} onClick={() => setSymbols([...new Set(watchlist)].join(", "))}>Use my watchlist</button></div>
      <label>Companies to scan<textarea value={symbols} onChange={e => setSymbols(e.target.value)} aria-describedby="basket-help" /></label>
      <p id="basket-help">{basket.length} unique symbols · 1–500 allowed. The starting basket spans several sectors; membership and common-stock status need review.</p>
      <div className="opportunity-fields"><label>Revenue growth greater than (%)<input type="number" value={growth} min={-100} max={1000} onChange={e => setGrowth(e.target.value)} /></label><label>Net margin greater than (%)<input type="number" value={margin} min={-1000} max={100} onChange={e => setMargin(e.target.value)} /></label><label className="opportunity-check"><input type="checkbox" checked={fcf} onChange={e => setFcf(e.target.checked)} />Require positive annual free cash flow</label></div>
      <button disabled={!!busy || !!running || !validBasket(basket) || !thresholdsValid} onClick={() => void act("Starting company scan", async () => {const result = await request<Scan>("/scans", {symbols: basket, min_growth: Number(growth), min_margin: Number(margin), require_fcf: fcf}); setScanId(result.id);setResultPage(0);})}>Scan and save evidence</button>
      <p>One company at a time using the existing Finnhub and SEC connections. Large baskets can take several minutes. A refresh starts only when you request it.</p>
    </details>
    <div className="opportunity-fields">
      <label>Saved scan<select value={scan?.id ?? ""} onChange={e => {setScanId(e.target.value);setResultPage(0);}}><option value="" disabled>Select a scan</option>{data?.scans.map(s => <option key={s.id} value={s.id}>{stamp(s.created_at)} · {s.payload.symbols.length} companies · {s.payload.state}</option>)}</select></label>
      <label>Show<select value={filter} onChange={e => {setFilter(e.target.value);setResultPage(0);}}>{["all", "reasons", "new", "investigate", "watch", "dismissed"].map(s => <option key={s} value={s}>{s === "reasons" ? "Has research reasons" : pretty(s)}</option>)}</select></label>
    </div>
    {scan ? <>
      <div className="opportunity-progress" role="status"><strong>{pretty(scan.payload.state)} · {scan.payload.processed}/{scan.payload.symbols.length} companies processed</strong><p>{scan.payload.active_symbol ? `Reading ${scan.payload.active_symbol}. ` : ""}{scan.payload.results.length} saved results · {scan.payload.failures.length} failed collections</p><progress value={scan.payload.processed} max={scan.payload.symbols.length} aria-label="Companies processed" />{["queued", "running"].includes(scan.payload.state) && <button disabled={!!busy} onClick={() => void act("Stopping scan after the current read", async () => {await request(`/scans/${scan.id}/cancel`, {});})}>Stop scan</button>}</div>
      {["canceled","interrupted"].includes(scan.payload.state) && scan.payload.processed < scan.payload.symbols.length && <button disabled={!!busy||!!running||!!scan.payload.active_symbol} onClick={()=>void act("Resuming remaining company reads",async()=>{await request(`/scans/${scan.id}/resume`,{});})}>Resume remaining symbols</button>}
      {scan.payload.failures.map(f => <p key={f.symbol} className="desk-error">{f.symbol}: {f.message}</p>)}
      <p>Saved criteria: growth &gt; {scan.payload.request.min_growth}% · margin &gt; {scan.payload.request.min_margin}% · positive annual free cash flow {scan.payload.request.require_fcf ? "required" : "not required"}.</p>
      <p>Sorted by number of research reasons. Missing facts do not pass checks. A recent filing is a reason to read, not a bullish signal.</p>
      {candidates.length === 0 && <p>No results match this view yet. Check the scan progress or change the filter.</p>}
      {scan.payload.recipe_id && <p>Saved recipe <code>{scan.payload.recipe_id}</code> · <code>{scan.payload.recipe_hash}</code></p>}
      {candidates.length > 25 && <div className="desk-actions"><button disabled={resultPage===0} onClick={()=>setResultPage(p=>p-1)}>Previous results</button><span>Results {resultPage*25+1}–{Math.min((resultPage+1)*25,candidates.length)} of {candidates.length}</span><button disabled={(resultPage+1)*25>=candidates.length} onClick={()=>setResultPage(p=>p+1)}>Next results</button></div>}
      {candidates.slice(resultPage*25,(resultPage+1)*25).map(candidate => <CandidateCard key={`${scan.id}-${candidate.symbol}`} candidate={candidate} state={stateOf(candidate.symbol)} note={data?.triage.find(t => t.symbol === candidate.symbol)?.payload.note ?? ""} disabled={!!busy}
        onSave={(state, note) => void act("Saving research disposition", async () => {await request("/triage", {scan_id: scan.id, symbol: candidate.symbol, state, note});})}
        onCompany={() => onCompany(candidate.symbol)} onBrief={() => setBrief({symbol: candidate.symbol, revision: Date.now()})} onReplay={() => setReplay({symbol: candidate.symbol, scanId: scan.id})} />)}
    </> : <p>No saved scans yet. Choose a basket above to create your first evidence inbox.</p>}
    {brief && <div ref={briefTarget}><ExplorerBriefPanel selection={brief} /></div>}
    <article><h2>Historical replay room</h2><p>Record a thesis and what would invalidate it, then reveal historical prices one exchange session at a time.</p><button onClick={() => setReplay({symbol: basket[0] ?? "NVDA"})}>New historical replay</button>
      {data && data.replays.length > 0 && <ul>{data.replays.map(r => <li key={r.id}><button onClick={() => setReplay({symbol: r.symbol, id: r.id})}>Resume {r.symbol} · {r.cutoff} · {r.step}/{r.horizon} revealed</button></li>)}</ul>}
    </article>
  </section>;
}

function CandidateCard({candidate: c, state, note, disabled, onSave, onCompany, onBrief, onReplay}: {
  candidate: Candidate; state: TriageState; note: string; disabled: boolean;
  onSave: (state: TriageState, note: string) => void; onCompany: () => void; onBrief: () => void; onReplay: () => void;
}) {
  const [draft, setDraft] = useState(note);
  const [choice, setChoice] = useState(state);
  return <article aria-label={`${c.symbol} research candidate`}>
    <div className="opportunity-title"><h2>{c.symbol} <small>{c.name}</small></h2><span>{c.priority} research reason{c.priority === 1 ? "" : "s"} · {state}</span></div>
    <p>Captured {stamp(c.collected_at)} · Financial checks: <strong>{c.screen.state}</strong> · Security: {pretty(c.security_type)}</p>
    {c.reasons.length ? <ul>{c.reasons.map((r, i) => <li key={i}>{r.text}</li>)}</ul> : <p>No qualifying research reason in this capture.</p>}
    <details><summary>Evidence, checks, and gaps</summary><ul>{c.screen.checks.map(r => <li key={r.name}>{r.name}: {r.value === null ? "Unavailable" : r.value.toLocaleString()} · greater than {r.threshold} · {r.state}</li>)}</ul>
      {c.filings.map(f => <p key={f.accession}><a href={f.url} target="_blank" rel="noreferrer">{f.form} · filed {f.filed}</a></p>)}
      <ul>{c.gaps.map((g, i) => <li key={i}>{g}</li>)}</ul>
      <p>Snapshot <code>{c.snapshot_id}</code>{c.previous_snapshot_id && <> · Previous <code>{c.previous_snapshot_id}</code></>}</p>
      {c.sources.map((s, i) => <p key={`${s.sha256}-${i}`}><a href={s.url} target="_blank" rel="noreferrer">Source {i + 1}</a> · {stamp(s.retrieved_at)}<br /><code>{s.sha256}</code></p>)}
    </details>
    <div className="desk-actions"><button onClick={onCompany}>Company evidence</button><button onClick={onBrief}>Open Astra brief</button><button onClick={onReplay}>Rehearse a past decision</button></div>
    <details><summary>Disposition and research note</summary><label>Disposition<select value={choice} onChange={e => setChoice(e.target.value as TriageState)}>{["new", "investigate", "watch", "dismissed"].map(s => <option key={s}>{s}</option>)}</select></label><label>Research note<textarea maxLength={2000} value={draft} onChange={e => setDraft(e.target.value)} /></label><button disabled={disabled} onClick={() => onSave(choice, draft)}>Save disposition</button><p>“Watch” saves an inbox disposition. Use the research desk to configure a thesis monitor.</p></details>
  </article>;
}
