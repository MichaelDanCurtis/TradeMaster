"use client";
import { useEffect, useRef, useState } from "react";
import { apiBase } from "@/lib/api";
import "./ResearchDesk.css";
import "./ForecastLab.css";

type Cell = {symbol: string; horizon: number; state: string; job_id: string | null; error: string | null};
type Case = {job_id: string; symbol: string; horizon: number; variant: string; cutoff: string; condition: {label: string}; mae_pct: number; flat_mae_pct: number; drift_mae_pct: number; coverage_pct: number; inference_seconds: number};
type Row = {horizon: number; variant: string; condition: string; windows: number; symbols: number; observations: number; mae_pct: number; flat_mae_pct: number; drift_mae_pct: number; improvement_vs_flat_pct: number | null; improvement_vs_drift_pct: number | null; wins_vs_flat: number; wins_vs_drift: number; coverage_pct: number; band_width_pct: number; interval_score_pct: number; inference_seconds: number};
type Batch = {id: string; created_at: string; payload: {state: string; message: string; recipe_hash: string; summary_hash?: string; request: {symbols: string[]; horizons: number[]; inputs: string; device: string; feed: string}; cells: Cell[]; cases: Case[]}};
type Detail = Batch & {coverage_complete: boolean; leaderboard: Row[]; recipe: {period: string; scoring: string; conditions: string; evidence_scope: string; frozen_at: string}; child_statuses?: Record<string, {state: string; error: string | null}>};
const active = (s: string) => ["queued", "running"].includes(s);
const pretty = (s: string) => s.replaceAll("_", " ");
const num = (v: number | null | undefined) => v === null || v === undefined ? "Undefined" : v.toLocaleString(undefined, {maximumFractionDigits: 3});
const variant = (s: string) => s === "stock" ? "Stock only" : "Stock + SPY + volume";
const base = () => `${apiBase()}/api/discover/forecast/tournaments`;
async function request<T>(path = "", body?: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(base() + path, {method: body === undefined ? "GET" : "POST", signal, cache: "no-store", headers: body === undefined ? undefined : {"Content-Type": "application/json"}, body: body === undefined ? undefined : JSON.stringify(body)});
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Tournament request failed (${response.status})`);
  return data;
}

export function ForecastTournament() {
  const [symbols, setSymbols] = useState("NVDA, AAPL, MSFT");
  const [horizons, setHorizons] = useState("both");
  const [inputs, setInputs] = useState("compare");
  const [device, setDevice] = useState("cpu");
  const [feed, setFeed] = useState("sip");
  const [batches, setBatches] = useState<Batch[]>([]);
  const [selected, setSelected] = useState("");
  const [detail, setDetail] = useState<Detail | null>(null);
  const [filter, setFilter] = useState("all");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const pending = useRef(false);
  const mounted = useRef(true);
  const submission = useRef<{settings: string; key: string} | null>(null);
  useEffect(() => {
    mounted.current = true;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function load() {
      let running = false;
      try {
        const [catalog, saved] = await Promise.all([request<{tournaments: Batch[]}>("", undefined, controller.signal), selected ? request<Detail>(`/${selected}`, undefined, controller.signal) : Promise.resolve(null)]);
        if (controller.signal.aborted) return;
        setBatches(catalog.tournaments); running = catalog.tournaments.some(b => active(b.payload.state));
        if (saved) setDetail(saved); else if (catalog.tournaments.length) setSelected(catalog.tournaments[0].id);
      } catch (e) {if (!controller.signal.aborted) setError(e instanceof Error ? e.message : "Could not load tournament evidence");}
      if (!controller.signal.aborted) timer = setTimeout(load, running ? 2000 : 15000);
    }
    void load();
    return () => {mounted.current = false; controller.abort(); clearTimeout(timer);};
  }, [selected]);
  async function act(fn: () => Promise<void>) {
    if (pending.current) return;
    pending.current = true; setBusy(true); setError("");
    try {await fn();} catch (e) {if (mounted.current) setError(e instanceof Error ? e.message : "Tournament request failed");}
    finally {pending.current = false; if (mounted.current) setBusy(false);}
  }
  const basket = [...new Set(symbols.toUpperCase().split(/[\s,]+/).filter(Boolean))];
  const valid = basket.length > 0 && basket.length <= 6 && basket.every(s => /^[A-Z][A-Z0-9.\-]{0,11}$/.test(s));
  const planned = basket.length * (horizons === "both" ? 2 : 1);
  async function start() {
    const settings = {symbols: basket, horizons: horizons === "both" ? [5, 20] : [Number(horizons)], inputs, device, feed};
    const encoded = JSON.stringify(settings);
    if (submission.current?.settings !== encoded) submission.current = {settings: encoded, key: crypto.randomUUID()};
    const batch = await request<Batch>("", {...settings, request_key: submission.current.key});
    if (!mounted.current) return;
    submission.current = null; setBatches(p => [batch, ...p.filter(b => b.id !== batch.id)]); setSelected(batch.id); setDetail(null); setFilter("all");
  }
  const conditions = [...new Set(["all", ...(detail?.leaderboard.map(r => r.condition) ?? [])])];
  const rows = detail?.leaderboard.filter(r => r.condition === filter) ?? [];
  const completed = detail?.payload.cells.filter(c => c.state === "completed").length ?? 0;
  const failed = detail?.payload.cells.filter(c => ["failed", "interrupted"].includes(c.state)).length ?? 0;
  return <section className="research-desk forecast-lab" aria-label="TimesFM tournament">
    <header><span className="panel-kicker">Measure before relying on a forecast</span><h1>TimesFM tournament</h1><p>Compare forecasts with last-price and linear-drift baselines across companies and horizons. Retain weak results and failures alongside strong ones.</p></header>
    {error && <p role="alert" className="desk-error">{error}</p>}{busy && <p role="status">Saving tournament request…</p>}
    <details open={!detail}><summary>New tournament definition</summary>
      <label>Stocks (up to six)<input value={symbols} onChange={e => setSymbols(e.target.value)} /></label>
      <div className="desk-actions">
        <label>Forecast horizons<select value={horizons} onChange={e => setHorizons(e.target.value)}><option value="both">5 and 20 sessions</option><option value="5">5 sessions</option><option value="20">20 sessions</option></select></label>
        <label>Input comparison<select value={inputs} onChange={e => setInputs(e.target.value)}><option value="compare">Stock vs stock + SPY + volume</option><option value="stock">Stock only</option></select></label>
        <label>Execution device<select value={device} onChange={e => setDevice(e.target.value)}><option value="cpu">CPU</option><option value="mps">PyTorch Metal</option><option value="mlx">MLX Metal</option></select></label>
        <label>Historical feed<select value={feed} onChange={e => setFeed(e.target.value)}><option value="sip">SIP</option><option value="iex">IEX</option></select></label>
      </div>
      <p>{planned} local jobs · {planned * 3 * (inputs === "compare" ? 2 : 1)} forecast windows. One job at a time. Each job uses 256 past sessions and three fixed late-2023 cutoffs; the 2024 validation and later holdout are untouched.</p>
      <p>The definition, model, code, scoring rules and condition thresholds are frozen before work starts. This is exploratory historical research with unknown model pretraining overlap.</p>
      <button disabled={busy || !valid || batches.some(b => active(b.payload.state))} onClick={() => void act(start)}>Freeze and run tournament</button>
    </details>
    <label>Saved tournament<select value={selected} onChange={e => {setSelected(e.target.value); setDetail(null); setFilter("all");}}><option value="" disabled>Select a tournament</option>{batches.map(b => <option key={b.id} value={b.id}>{new Date(b.created_at).toLocaleString()} · {b.payload.request.symbols.join(", ")} · {pretty(b.payload.state)}</option>)}</select></label>
    {detail ? <>
      <article><h2>{pretty(detail.payload.state)}</h2><p role="status">{detail.payload.message}</p><p>{completed}/{detail.payload.cells.length} jobs scored · {failed} failed or interrupted · {detail.payload.cases.length} scored forecast windows</p><progress value={completed + failed} max={detail.payload.cells.length} aria-label="Tournament jobs settled" />
        <p>{detail.coverage_complete ? "All planned comparisons are present. These historical results do not establish an investment edge." : "Provisional results: the planned comparison is incomplete. Missing or failed jobs are not zero-error forecasts."}</p>
        {active(detail.payload.state) && <button disabled={busy} onClick={() => void act(async () => {await request(`/${detail.id}/stop`, {}); const fresh = await request<Detail>(`/${detail.id}`); if (mounted.current) {setDetail(fresh); setBatches(p => p.map(b => b.id === fresh.id ? fresh : b));}})}>Stop after current job</button>}
      </article>
      <label>Historical conditions<select value={filter} onChange={e => setFilter(e.target.value)}>{conditions.map(c => <option key={c} value={c}>{c === "all" ? "All observed conditions" : c}</option>)}</select></label>
      <p>Errors are percentages of the last context price, averaged equally per stock/window. Lower is better. Separate horizons may share target days and must not be counted as independent samples.</p>
      <div className="desk-table"><table><caption>Forecast and baseline comparisons</caption><thead><tr><th>Horizon / inputs</th><th>Windows</th><th>TimesFM error %</th><th>Last-price error %</th><th>Drift error %</th><th>Improvement vs last price</th><th>Wins vs last price / drift</th><th>80% band coverage</th><th>Band width %</th><th>Interval score %</th><th>Inference / window</th></tr></thead><tbody>{rows.map(r => <tr key={`${r.horizon}-${r.variant}`}><td>{r.horizon} sessions<br />{variant(r.variant)}</td><td>{r.windows} · {r.symbols} stocks</td><td>{num(r.mae_pct)}</td><td>{num(r.flat_mae_pct)}</td><td>{num(r.drift_mae_pct)}</td><td>{num(r.improvement_vs_flat_pct)}{r.improvement_vs_flat_pct !== null ? "%" : ""}</td><td>{r.wins_vs_flat}/{r.windows} · {r.wins_vs_drift}/{r.windows}</td><td>{num(r.coverage_pct)}%</td><td>{num(r.band_width_pct)}</td><td>{num(r.interval_score_pct)}</td><td>{num(r.inference_seconds)} s</td></tr>)}</tbody></table></div>
      {!rows.length && <p>No scored cases for this condition yet.</p>}
      <p>Interval score penalizes both overly wide bands and missed outcomes; lower is better. Inference timing excludes weight loading, data collection, and queue time.</p>
      <details><summary>Every planned job and retained failure</summary><ul>{detail.payload.cells.map(c => <li key={`${c.symbol}-${c.horizon}`}><strong>{c.symbol} · {c.horizon} sessions · {pretty(c.state)}</strong>{c.error && <p className="desk-error">{c.error}</p>}{c.job_id && <p>Runner state: {detail.child_statuses?.[c.job_id]?.state ?? c.state} · {(detail.child_statuses?.[c.job_id]?.state ?? c.state) === "completed" ? <a href={`${apiBase()}/api/discover/forecast/jobs/${c.job_id}/evidence.zip`}>Child evidence ZIP</a> : "Evidence ZIP available after completion"}</p>}</li>)}</ul></details>
      <details><summary>Window-by-window results</summary><div className="desk-table"><table><thead><tr><th>Stock / cutoff</th><th>Horizon / inputs</th><th>Prior condition</th><th>TimesFM / last price / drift error %</th></tr></thead><tbody>{detail.payload.cases.map(c => <tr key={`${c.job_id}-${c.variant}-${c.cutoff}`}><td>{c.symbol} · {c.cutoff}</td><td>{c.horizon} · {variant(c.variant)}</td><td>{c.condition.label}</td><td>{num(c.mae_pct)} / {num(c.flat_mae_pct)} / {num(c.drift_mae_pct)}</td></tr>)}</tbody></table></div></details>
      <details><summary>Frozen rules and provenance</summary><p>{detail.recipe.period}</p><p>{detail.recipe.scoring}</p><p>{detail.recipe.conditions}</p><p>{detail.recipe.evidence_scope}</p><p>Definition saved {new Date(detail.recipe.frozen_at).toLocaleString()} · <code>{detail.payload.recipe_hash}</code></p>{detail.payload.summary_hash && <p>Summary <code>{detail.payload.summary_hash}</code></p>}<a href={`${base()}/${detail.id}/export.json`}>Download tournament results and definition</a></details>
    </> : <p>{selected ? "Loading the selected tournament…" : "No tournament selected. Freeze a small batch to begin."}</p>}
  </section>;
}
