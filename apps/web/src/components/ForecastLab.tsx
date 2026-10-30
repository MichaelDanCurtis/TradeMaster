"use client";

import { useEffect, useRef, useState } from "react";
import { apiBase } from "@/lib/api";
import "./ResearchDesk.css";
import "./ForecastLab.css";

type Metric = { mae_usd: number; baseline_mae_usd: number; drift_mae_usd: number; interval_coverage_pct: number; observations: number; mean_interval_width_usd?: number; interval_score_usd?: number };
type Comparison = Metric & { variant: string; windows: number; windows_beating_flat: number; mae_reduction_pct: number | null };
type Case = { variant?: string; cutoff: string; dates: string[]; values: number[]; target_dates: string[]; baseline: number[]; drift_baseline: number[]; actual: number[] | null };
type Prediction = { forecast: number[]; quantiles: number[][]; inference_seconds: number };
type Runtime = { device: string; load_seconds: number; peak_process_rss_mb: number; mps_allocated_mb: number | null; results: Prediction[] };
type Result = { symbol: string; issued_at: string; prospective_eligible: boolean; evidence_scope: string; mode: string; feed: string; input_hash: string; cases: Case[]; runtime: Runtime; metrics: Metric[]; comparison?: Comparison[]; limitations: string[]; model: { model_id: string; revision: string; code_revision: string; license_url: string } };
type Job = { id: string; state: string; created_at: string; updated_at: string; request: { symbol: string; horizon: number; inputs: string; mode: string; device: string }; input_hash: string | null; result_hash: string | null; error: string | null };
type Score = Partial<Metric> & { state: string; reason?: string; target_end?: string; actual?: number[]; observed_at?: string; case_metrics?: Metric[]; comparison?: Comparison[] };
type Detail = Job & { result: Result | null; scores: { id: string; result: Score }[] };
type Status = { state: string; message: string; jobs: Job[]; mlx?: { installed: boolean; message: string }; outcome_worker?: { enabled: boolean; state: string; checked_at: string | null; error: string | null }; manifest?: { model_id: string; benchmarks: Record<string, { load_seconds: number; inference_seconds: number; peak_process_rss_mb: number; scope: string }> } };

async function request<T>(path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${apiBase()}/api/discover/forecast${path}`, {
    method: body === undefined ? "GET" : "POST", signal,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body), cache: "no-store"
  });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Forecast request failed (${response.status})`);
  return data as T;
}
const active = (state: string) => ["queued", "collecting", "running"].includes(state);
const number = (value: number | undefined, digits = 2) => value === undefined ? "—" : value.toLocaleString(undefined, { maximumFractionDigits: digits });
const stamp = (value: string) => new Date(value).toLocaleString();
const variantName = (value?: string) => value === "compare" ? "Paired comparison" : value === "market_volume" ? "Stock + SPY + volume" : "Stock only";

export function ForecastLab({ symbol: initialSymbol }: { symbol: string }) {
  const [symbol, setSymbol] = useState(initialSymbol || "NVDA");
  const [horizon, setHorizon] = useState(5);
  const [inputs, setInputs] = useState("compare");
  const [mode, setMode] = useState("prospective");
  const [feed, setFeed] = useState("sip");
  const [device, setDevice] = useState("cpu");
  const [status, setStatus] = useState<Status | null>(null);
  const [selected, setSelected] = useState("");
  const [detail, setDetail] = useState<Detail | null>(null);
  const [caseIndex, setCaseIndex] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [connectionError, setConnectionError] = useState("");
  const [score, setScore] = useState<Score | null>(null);
  const pending = useRef(false);
  const mounted = useRef(true);
  const submission = useRef<{ settings: string; key: string } | null>(null);
  useEffect(() => { setSymbol(initialSymbol || "NVDA"); }, [initialSymbol]);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function refresh() {
      let running = false;
      try {
        const [next, saved] = await Promise.all([
          request<Status>("/status", undefined, controller.signal),
          selected ? request<Detail>(`/jobs/${selected}`, undefined, controller.signal) : Promise.resolve(null)
        ]);
        if (controller.signal.aborted) return;
        setStatus(next);
        setConnectionError("");
        running = next.jobs.some(j => active(j.state));
        if (saved) setDetail(saved);
        else if (next.jobs.length) setSelected(next.jobs[0].id);
      } catch (e) {
        if (!controller.signal.aborted) setConnectionError(e instanceof Error ? e.message : "Could not read the forecast journal");
      }
      if (!controller.signal.aborted) timer = setTimeout(refresh, running ? 2000 : 15000);
    }
    void refresh();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [selected]);
  function selectJob(id: string) { setSelected(id); setDetail(null); setScore(null); setCaseIndex(0); }
  async function run() {
    if (pending.current) return;
    pending.current = true; setBusy(true); setError("");
    const settings = { symbol: symbol.trim().toUpperCase(), horizon, inputs, mode, feed, device };
    const encoded = JSON.stringify(settings);
    if (submission.current?.settings !== encoded) submission.current = { settings: encoded, key: crypto.randomUUID() };
    try {
      const job = await request<Job>("/jobs", { ...settings, request_key: submission.current.key });
      if (!mounted.current) return;
      submission.current = null;
      setStatus(s => s ? { ...s, jobs: [job, ...s.jobs.filter(j => j.id !== job.id)] } : s);
      selectJob(job.id);
    } catch (e) { if (mounted.current) setError(e instanceof Error ? e.message : "Could not start the forecast"); }
    finally { pending.current = false; if (mounted.current) setBusy(false); }
  }
  async function collectOutcomes() {
    if (!detail || pending.current) return;
    const id = detail.id;
    pending.current = true; setBusy(true); setError("");
    try {
      const outcome = await request<Score>(`/jobs/${id}/score`, {});
      if (mounted.current) setScore(outcome);
    } catch (e) { if (mounted.current) setError(e instanceof Error ? e.message : "Could not collect outcomes"); }
    finally { pending.current = false; if (mounted.current) setBusy(false); }
  }
  async function toggleOutcomes() {
    if (!status?.outcome_worker || pending.current) return;
    pending.current = true; setBusy(true); setError("");
    try {
      const value = await request<{ enabled: boolean }>("/outcome-settings", { enabled: !status.outcome_worker.enabled });
      if (mounted.current) setStatus(s => s?.outcome_worker ? { ...s, outcome_worker: { ...s.outcome_worker, enabled: value.enabled } } : s);
    } catch (e) { if (mounted.current) setError(e instanceof Error ? e.message : "Could not update outcome checks"); }
    finally { pending.current = false; if (mounted.current) setBusy(false); }
  }
  const result = detail?.result;
  const chosen = result?.cases[caseIndex];
  const prediction = result?.runtime.results[caseIndex];
  const persistedScore = detail?.scores[0]?.result;
  const latestScore = persistedScore?.state === "scored" ? persistedScore : score ?? persistedScore;
  const measured = result?.metrics[caseIndex] ?? (latestScore?.state === "scored" ? latestScore.case_metrics?.[caseIndex] ?? latestScore as Metric : undefined);
  const comparison = result?.comparison?.length ? result.comparison : latestScore?.comparison;
  const running = status?.jobs.some(j => active(j.state)) || (detail && active(detail.state));
  return <section className="research-desk forecast-lab" aria-label="Forecast Lab">
    <header><span className="panel-kicker">Local model · dated evidence · paper research</span><h1>Forecast Lab</h1><p>Does TimesFM-3 add information beyond a flat-price forecast? Make a prediction, preserve it, and measure what happened.</p></header>
    {error && <p role="alert" className="desk-error">{error}</p>}
    {connectionError && <p role="alert" className="desk-error">Connection interrupted: {connectionError}. Retrying automatically.</p>}
    <article><h2>Local runtime</h2><p role="status">{status ? `${status.state.replaceAll("_", " ")} · ${status.message}` : "Checking installed model…"}</p>
      {status?.manifest && <><p>{status.manifest.model_id}</p><div className="desk-stats">{Object.entries(status.manifest.benchmarks).map(([name, b]) => <div key={name}><span>{name === "mps" ? "Apple GPU" : "CPU"} · synthetic speed check</span><strong>{number(b.inference_seconds, 3)}s</strong><small>Load {number(b.load_seconds)}s · Peak process {number(b.peak_process_rss_mb / 1024)} GB</small></div>)}</div><p>Measured on this computer. Small cold-start jobs can run faster on CPU. Memory figures exclude some accelerator allocations.</p></>}
    </article>
    {status?.outcome_worker && <article><h2>Automatic outcome checks</h2><p>{status.outcome_worker.enabled ? `Enabled · ${status.outcome_worker.state}` : "Paused"} · Last check: {status.outcome_worker.checked_at ? stamp(status.outcome_worker.checked_at) : "Not observed yet"}</p><p>While the local API is running, saved forecasts are scored after their final target date. Checks only collect market observations; they do not generate forecasts or place orders. Missing data is retried after 24 hours.</p>{status.outcome_worker.error && <p role="alert" className="desk-error">{status.outcome_worker.error}</p>}<button disabled={busy} onClick={() => void toggleOutcomes()}>{status.outcome_worker.enabled ? "Pause automatic scoring" : "Resume automatic scoring"}</button></article>}
    <article><h2>New experiment</h2><div className="forecast-controls">
      <label>Stock symbol<input value={symbol} maxLength={12} onChange={e => setSymbol(e.target.value.toUpperCase())} /></label>
      <label>Horizon<select value={horizon} onChange={e => setHorizon(Number(e.target.value))}><option value={5}>5 trading sessions</option><option value={20}>20 trading sessions</option></select></label>
      <label>Inputs<select value={inputs} onChange={e => setInputs(e.target.value)}><option value="compare">Compare both on the same data</option><option value="stock">Stock closing prices</option><option value="market_volume">Stock + SPY + stock volume</option></select></label>
      <label>Experiment<select value={mode} onChange={e => setMode(e.target.value)}><option value="prospective">Save a forward forecast</option><option value="development">2023 development comparison</option></select></label>
      <label>Market data<select value={feed} onChange={e => setFeed(e.target.value)}><option value="sip">Alpaca SIP</option><option value="iex">Alpaca IEX</option></select></label>
      <label>Compute<select value={device} onChange={e => setDevice(e.target.value)}><option value="cpu">CPU</option><option value="mps">Apple GPU · PyTorch Metal</option><option value="mlx" disabled={!status?.mlx?.installed}>Apple GPU · MLX</option></select></label>
    </div>
      <p>MLX uses Apple Metal with FP32 weights for stock-only and stock + SPY + volume inputs. It accelerates inference; it does not establish better predictions. {status?.mlx?.installed ? "MLX environment present; the GPU is checked when a run starts." : "Optional MLX runtime is not installed."} First use can take longer to compile.</p>
      <p>{mode === "prospective" ? "Uses 256 sessions ending before the current New York date. A forecast qualifies as prospective only when saved before its first target session opens." : "Three chronological cutoffs in late 2023, with 256 prior sessions each. Future observations never enter the model. Pretraining overlap is unknown; this is exploratory evidence."}</p>
      <p>{inputs === "compare" ? "Both variants use one data capture, identical dates, and the same device. SPY and volume are supplied only for past dates in the second variant." : inputs === "market_volume" ? "SPY and volume are past-only inputs aligned to the same dates; their future values are never supplied." : "The stock-only run establishes a clean comparison before adding other inputs."} Split-adjusted prices · USD · no automatic feed or device fallback.</p>
      <button className="forecast-run" disabled={busy || !!running || !!connectionError || status?.state !== "installed" || !/^[A-Z][A-Z0-9.\-]{0,11}$/.test(symbol.trim())} onClick={() => void run()}>{busy ? "Working…" : running ? "Local forecast in progress…" : "Run and save forecast"}</button>
    </article>
    <div className="forecast-journal"><label>Saved forecast journal · 50 most recent<select value={selected} disabled={busy} onChange={e => selectJob(e.target.value)}><option value="">Select a saved forecast</option>{status?.jobs.map(j => <option key={j.id} value={j.id}>{j.request.symbol} · {j.request.horizon} sessions · {variantName(j.request.inputs)} · {j.request.mode === "development" ? "2023 replay" : "Forward"} · {j.state} · {stamp(j.created_at)}</option>)}</select></label>{status?.jobs.length === 0 && <p>No saved forecasts yet.</p>}</div>
    {detail && <article><h2>{detail.request.symbol} · {detail.state}</h2><p>Requested {stamp(detail.created_at)} · Updated {stamp(detail.updated_at)}</p>{active(detail.state) && <p role="status">{detail.state === "collecting" ? "Collecting and checking dated Alpaca bars and exchange sessions…" : detail.state === "running" ? "Running the local model with saved inputs…" : "Waiting for local input checks…"}</p>}{detail.error && <p role="alert" className="desk-error">{detail.error}</p>}
      {result && chosen && prediction && <>
        <p><strong>{result.evidence_scope}</strong></p><p>Saved {stamp(result.issued_at)} · Input cutoff {chosen.cutoff} · {result.feed.toUpperCase()} · {result.runtime.device === "mlx" ? "Apple GPU · MLX" : result.runtime.device === "mps" ? "Apple GPU · PyTorch Metal" : "CPU"}</p>
        {comparison?.length ? <ComparisonTable rows={comparison} /> : result.cases.length === 2 && detail.request.inputs === "compare" ? <><h3>Paired forward predictions</h3><div className="desk-table"><table><thead><tr><th>Inputs</th><th>Final point (USD)</th><th>Final 10th–90th percentiles</th></tr></thead><tbody>{result.cases.map((c,i) => <tr key={c.variant}><td>{variantName(c.variant)}</td><td>{number(result.runtime.results[i].forecast.at(-1))}</td><td>{number(result.runtime.results[i].quantiles.at(-1)?.[0])}–{number(result.runtime.results[i].quantiles.at(-1)?.[8])}</td></tr>)}</tbody></table></div><p>Both predictions were saved together. Their accuracy comparison is pending.</p></> : null}
        {result.cases.length > 1 && <label>Inspect variant and cutoff<select value={caseIndex} onChange={e => setCaseIndex(Number(e.target.value))}>{result.cases.map((c, i) => <option key={`${c.variant}-${c.cutoff}`} value={i}>{variantName(c.variant ?? detail.request.inputs)} · {c.cutoff}</option>)}</select></label>}
        <ForecastChart item={chosen} prediction={prediction} actual={chosen.actual ?? latestScore?.actual} />
        <div className="desk-stats"><div><span>Final-session point forecast</span><strong>${number(prediction.forecast.at(-1))}</strong></div><div><span>Flat-price baseline</span><strong>${number(chosen.baseline[0])}</strong></div><div><span>Inference / load</span><strong>{number(prediction.inference_seconds, 3)}s / {number(result.runtime.load_seconds)}s</strong></div></div>
        <p>The shaded 10th–90th percentile band is uncalibrated. This is a price prediction; it does not estimate trading profit.</p>
        {measured ? <div className="desk-stats"><div><span>Model mean absolute error</span><strong>${number(measured.mae_usd)}</strong></div><div><span>Flat baseline error</span><strong>${number(measured.baseline_mae_usd)}</strong></div><div><span>Drift baseline error</span><strong>${number(measured.drift_mae_usd)}</strong></div><div><span>Observed band coverage</span><strong>{number(measured.interval_coverage_pct)}%</strong><small>{measured.observations} daily outcomes</small></div></div> : <p>Outcomes pending · Last target session: {chosen.target_dates.at(-1)}. Pending outcomes are never counted as zero error.</p>}
        {measured?.interval_score_usd !== undefined && <p>Mean band width: ${number(measured.mean_interval_width_usd)} · Interval score: {number(measured.interval_score_usd)} (lower is better). This score penalizes both wide bands and missed outcomes.</p>}
        {result.mode === "prospective" && <><button disabled={busy || !!running} onClick={() => void collectOutcomes()}>Check observed outcomes</button>{latestScore && <p role="status">{latestScore.state.replaceAll("_", " ")}{latestScore.reason && ` · ${latestScore.reason}`}</p>}</>}
        <details><summary>Daily predictions and baselines</summary><div className="desk-table"><table><thead><tr><th>Session</th><th>Point (USD)</th><th>10th percentile</th><th>90th percentile</th><th>Flat</th><th>Drift</th><th>Observed</th></tr></thead><tbody>{chosen.target_dates.map((d, i) => <tr key={d}><td>{d}</td><td>{number(prediction.forecast[i])}</td><td>{number(prediction.quantiles[i][0])}</td><td>{number(prediction.quantiles[i][8])}</td><td>{number(chosen.baseline[i])}</td><td>{number(chosen.drift_baseline[i])}</td><td>{number((chosen.actual ?? latestScore?.actual)?.[i])}</td></tr>)}</tbody></table></div></details>
        <details><summary>Evidence and reproducibility</summary><ul>{result.limitations.map(l => <li key={l}>{l}</li>)}</ul><p>Input receipt <code>{detail.input_hash}</code></p><p>Result receipt <code>{detail.result_hash}</code></p><p>Model revision <code>{result.model.revision}</code></p><p>Implementation revision <code>{result.model.code_revision}</code></p><a href={result.model.license_url} target="_blank" rel="noreferrer">Model attribution and terms</a></details>
        <div className="desk-actions"><a href={`${apiBase()}/api/discover/forecast/jobs/${detail.id}/export.csv`} download>Download predictions CSV</a><a href={`${apiBase()}/api/discover/forecast/jobs/${detail.id}/evidence.zip`} download>Download evidence archive</a></div>
      </>}
    </article>}
  </section>;
}

function ComparisonTable({ rows }: { rows: Comparison[] }) {
  return <section aria-label="Forecast accuracy comparison"><h3>Accuracy across saved windows</h3><p>Lower error is better. Positive error reduction means improvement over a flat-price forecast. Daily outcomes within a window are correlated; these counts do not establish statistical confidence.</p><div className="desk-table"><table><thead><tr><th>Inputs</th><th>Model error (USD)</th><th>Flat error</th><th>Drift error</th><th>Error reduction</th><th>Windows beating flat</th><th>Band coverage</th><th>Interval score ↓</th></tr></thead><tbody>{rows.map(r => <tr key={r.variant}><td>{variantName(r.variant)}</td><td>{number(r.mae_usd)}</td><td>{number(r.baseline_mae_usd)}</td><td>{number(r.drift_mae_usd)}</td><td>{r.mae_reduction_pct === null ? "Undefined: baseline error is zero" : `${number(r.mae_reduction_pct)}%`}</td><td>{r.windows_beating_flat}/{r.windows}</td><td>{number(r.interval_coverage_pct)}%</td><td>{number(r.interval_score_usd)}</td></tr>)}</tbody></table></div></section>;
}

function ForecastChart({ item, prediction, actual }: { item: Case; prediction: Prediction; actual?: number[] | null }) {
  const history = item.values.slice(-30);
  const offset = history.length - 1;
  const total = offset + prediction.forecast.length;
  const lows = prediction.quantiles.map(q => q[0]);
  const highs = prediction.quantiles.map(q => q[8]);
  const all = [...history, ...lows, ...highs, ...(actual ?? [])];
  const min = Math.min(...all), max = Math.max(...all);
  const spread = Math.max(max - min, 1);
  const x = (i: number) => 60 + i / total * 800;
  const y = (v: number) => 245 - (v - min) / spread * 200;
  const points = (values: number[], start: number) => values.map((v, i) => `${x(start + i)},${y(v)}`).join(" ");
  const band = [...lows.map((v, i) => `${x(offset + 1 + i)},${y(v)}`), ...highs.map((v, i) => `${x(offset + 1 + i)},${y(v)}`).reverse()].join(" ");
  return <figure className="forecast-chart"><svg viewBox="0 0 900 290" role="img" aria-label={`Daily price forecast from ${item.cutoff} to ${item.target_dates.at(-1)}; daily values are available in the table below`}>
    {[0, 1, 2, 3, 4].map(i => <g key={i}><line x1="60" x2="860" y1={45 + i * 50} y2={45 + i * 50} className="forecast-grid" /><text x="4" y={49 + i * 50}>{number(min + spread * (1 - i / 4))}</text></g>)}
    <polygon points={band} className="forecast-band" />
    <line x1={x(offset)} x2={x(offset)} y1="30" y2="250" className="forecast-cutoff" />
    <polyline points={points(history, 0)} className="forecast-history" />
    <polyline points={points([history.at(-1)!, ...prediction.forecast], offset)} className="forecast-point" />
    <polyline points={points([history.at(-1)!, ...item.baseline], offset)} className="forecast-baseline" />
    {actual && <polyline points={points([history.at(-1)!, ...actual], offset)} className="forecast-actual" />}
    <text x="60" y="278">{item.dates.at(-30)}</text><text x={x(offset)} y="278" textAnchor="middle">{item.cutoff}</text><text x="860" y="278" textAnchor="end">{item.target_dates.at(-1)}</text>
  </svg><figcaption>Gray: observed history · Cyan: point forecast · Shading: model quantiles · Dashed: flat baseline{actual ? " · Amber: outcomes" : ""}</figcaption></figure>;
}
