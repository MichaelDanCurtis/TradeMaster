"use client";
import { HistoricalReplayEvidence } from "./HistoricalReplayEvidence";
import {apiBase} from "@/lib/api";
import { useEffect, useRef, useState } from "react";
import { opportunityRequest as request, type Replay } from "@/lib/opportunity-lab";

export function HistoricalReplay({selection, onBack}: {selection: {symbol: string; scanId?: string; id?: string}; onBack: () => void}) {
  const [symbol, setSymbol] = useState(selection.symbol);
  const [cutoff, setCutoff] = useState("2023-06-01");
  const [horizon, setHorizon] = useState("20");
  const [feed, setFeed] = useState("sip");
  const [evidenceMode,setEvidenceMode]=useState("filings");
  const [replay, setReplay] = useState<Replay | null>(null);
  const [decision, setDecision] = useState("watch");
  const [thesis, setThesis] = useState("");
  const [invalidation, setInvalidation] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const pending = useRef(false);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    const controller = new AbortController();
    if (selection.id) {
      setBusy(true);
      request<Replay>(`/replays/${selection.id}`, undefined, controller.signal).then(r => {if (!controller.signal.aborted) setReplay(r);}).catch(e => {if (!controller.signal.aborted) setError(e.message);}).finally(() => {if (!controller.signal.aborted) setBusy(false);});
    }
    return () => {mounted.current = false; controller.abort();};
  }, [selection.id]);
  async function act(fn: () => Promise<Replay>) {
    if (pending.current) return;
    pending.current = true; setBusy(true); setError("");
    try {const result = await fn(); if (mounted.current) {setReplay(result); setThesis(""); setInvalidation("");}}
    catch (e) {
      if (mounted.current) {
        setError(e instanceof Error ? e.message : "Replay request failed");
        // An uncertain response may already have saved the decision. Refresh;
        // never retry the mutation automatically.
        if (replay) try {setReplay(await request<Replay>(`/replays/${replay.id}`));} catch { /* preserve the prior view */ }
      }
    } finally {pending.current = false; if (mounted.current) setBusy(false);}
  }
  const prices = replay?.bars.map(b => b.close) ?? [];
  const low = Math.min(...prices), high = Math.max(...prices);
  const points = prices.map((p, i) => `${10 + i / Math.max(1, prices.length - 1) * 780},${190 - (p - low) / (high - low || 1) * 170}`).join(" ");
  const valid = /^[A-Z][A-Z0-9.\-]{0,11}$/.test(symbol) && !!cutoff && Number.isInteger(Number(horizon)) && Number(horizon) >= 1 && Number(horizon) <= 60;
  return <section className="research-desk" aria-label="Historical replay room">
    <button onClick={onBack}>← Opportunity inbox</button><h1>Historical replay room</h1><p>Write down what you would investigate and what could change your mind. Save that decision to reveal the next session.</p>
    {error && <p role="alert" className="desk-error">{error}</p>}{busy && <p role="status">{replay ? "Saving decision and revealing one session…" : "Loading historical replay…"}</p>}
    {!replay && !selection.id && <article>
      <div className="opportunity-fields"><label>Replay symbol<input value={symbol} disabled={!!selection.scanId} onChange={e => setSymbol(e.target.value.toUpperCase())} /></label><label>Decision date (after close)<input type="date" value={cutoff} onChange={e => setCutoff(e.target.value)} /></label><label>Sessions to reveal<input type="number" min={1} max={60} value={horizon} onChange={e => setHorizon(e.target.value)} /></label><label>Market-data feed<select value={feed} onChange={e => setFeed(e.target.value)}><option value="sip">SIP</option><option value="iex">IEX</option></select></label></div>
      <label>Evidence mode<select value={evidenceMode} onChange={e=>setEvidenceMode(e.target.value)}><option value="filings">Historical filings and Astra assessment</option><option value="price">Price-only rehearsal</option></select></label><p>The selected date needs 60 preceding context sessions and a completed reveal horizon. Current company evidence stays outside the historical view.</p>
      <button disabled={busy || !valid} onClick={() => void act(() => request<Replay>("/replays", {symbol, cutoff, horizon: Number(horizon), feed, evidence_mode:evidenceMode, source_scan_id: selection.scanId ?? null}))}>Create historical replay</button>
    </article>}
    {replay && <>
      <div className="desk-stats"><div><span>Visible through</span><strong>{replay.visible_through}</strong></div><div><span>Sessions revealed</span><strong>{replay.step}/{replay.horizon}</strong></div><div><span>Close change since initial decision date</span><strong>{replay.revealed_price_change_pct === null ? "Not revealed" : `${replay.revealed_price_change_pct.toFixed(2)}%`}</strong></div></div>
      <article><h2>{replay.symbol} · split-adjusted close</h2><p>{replay.bars[0].date} to {replay.visible_through} · {replay.feed.toUpperCase()} · last close ${prices.at(-1)?.toFixed(2)}</p><svg viewBox="0 0 800 210" role="img" aria-label={`${replay.symbol} historical closing prices through ${replay.visible_through}`} className="replay-chart"><polyline points={points} fill="none" stroke="currentColor" strokeWidth="2" /><text x="12" y="208" fill="currentColor" fontSize="12">Visible price range: ${low.toFixed(2)}–${high.toFixed(2)}</text></svg>
      <details><summary>Visible daily prices</summary><div className="desk-table"><table><thead><tr><th>Date</th><th>Close (USD)</th><th>Volume</th></tr></thead><tbody>{replay.bars.map(b => <tr key={b.date}><td>{b.date}</td><td>{b.close.toFixed(2)}</td><td>{b.volume.toLocaleString()}</td></tr>)}</tbody></table></div></details></article>
      {replay.evidence_mode==="filings"&&!replay.complete&&<HistoricalReplayEvidence key={`${replay.id}-${replay.step}`} replay={replay} onUpdate={setReplay}/>}
      {!replay.complete ? <article><h2>Your decision as of {replay.visible_through}</h2><label>Research decision<select value={decision} onChange={e => setDecision(e.target.value)}><option value="investigate">Investigate</option><option value="watch">Watch</option><option value="pass">Pass</option></select></label><label>Thesis / reasoning<textarea value={thesis} onChange={e => setThesis(e.target.value)} minLength={10} maxLength={2000} placeholder="What does the visible evidence suggest?" /></label><label>What would change your mind?<textarea value={invalidation} onChange={e => setInvalidation(e.target.value)} minLength={10} maxLength={2000} placeholder="Write a specific observation that would invalidate your reasoning." /></label><button disabled={busy || (replay.evidence_mode==="filings"&&replay.historical_evidence?.assessment?.state!=="completed") || thesis.trim().length < 10 || invalidation.trim().length < 10} onClick={() => void act(() => request<Replay>(`/replays/${replay.id}/advance`, {expected_step: replay.step, decision, thesis, invalidation}))}>Save decision and reveal next session</button></article> : <article><h2>Replay complete</h2><p>All {replay.horizon} sessions are visible. Review your original reasoning against what followed; price changes are not simulated trading profits.</p></article>}
      <details open={replay.complete}><summary>Saved decision journal ({replay.decisions.length})</summary>{replay.decisions.map(d => <article key={d.receipt_hash}><h3>{d.visible_through} · {d.decision}</h3><p>{d.thesis}</p><p><strong>Would change my mind:</strong> {d.invalidation}</p><small>Recorded {new Date(d.recorded_at).toLocaleString()}</small>{d.historical_assessment&&<p><a href={`${apiBase()}/api/discover/briefs/${d.historical_assessment.brief_id}/evidence.zip`} download>Historical Astra assessment and original filings</a> · <code>{d.historical_assessment.packet_hash}</code></p>}<p><code>{d.receipt_hash}</code></p></article>)}</details>
      <details><summary>Data provenance and limits</summary><ul>{replay.limitations.map(s => <li key={s}>{s}</li>)}</ul><p>Captured {new Date(replay.captured_at).toLocaleString()} · <code>{replay.capture_hash}</code></p></details>
    </>}
  </section>;
}
