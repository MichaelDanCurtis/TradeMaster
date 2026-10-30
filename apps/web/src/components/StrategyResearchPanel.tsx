"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { StrategyEvidencePanel } from "@/components/StrategyEvidencePanel";
import { StrategyDatasetPanel } from "@/components/StrategyDatasetPanel";
import { StrategyExtractionPolicy } from "@/components/StrategyExtractionPolicy";
import { StrategyDesignerPanel } from "@/components/StrategyDesignerPanel";
import {
  evidenceLabel, researchRequest, type Experiment, type PlanInput, type ResearchPlan,
  type Snapshot, type Strategy, type StrategyDetail, type StrategyDraft, type StrategySpec, type ResearchRuntime, type ResearchProvider, type ExtractionPolicy,
} from "@/lib/research-api";

const emptyDraft: StrategyDraft = { name: "", hypothesis: "", rationale: "" };

export function StrategyResearchPanel({ onRequestReview }: { onRequestReview?: (selection: { version_id: string; experiment_id: string }) => void }) {
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [selected, setSelected] = useState("");
  const [draft, setDraft] = useState(emptyDraft);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const reload = useCallback(async (signal?: AbortSignal) => {
    const result = await researchRequest<{ strategies: Strategy[] }>("/strategies", undefined, "GET", signal);
    setStrategies(result.strategies);
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    reload(controller.signal).catch((e) => { if (!controller.signal.aborted) setError(String(e.message)); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [reload]);

  async function create(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      const strategy = await researchRequest<Strategy>("/strategies", draft);
      await reload(); setSelected(strategy.strategy_id); setDraft(emptyDraft);
    } catch (e) { setError(e instanceof Error ? e.message : "Could not save hypothesis"); }
    finally { setBusy(false); }
  }

  return (
    <section className="strategy-research" aria-label="Strategy research">
      <header><span className="panel-kicker">Executable research</span><h2>Make an idea earn its place.</h2><p>Define a hypothesis, freeze the rules, and compare the evidence before requesting paper execution.</p></header>
      {error ? <p className="strategy-error" role="alert">{error}</p> : null}
      <div className="strategy-layout">
        <aside className="strategy-card">
          <h3>Your strategies</h3>
          {loading ? <p role="status">Loading research…</p> : strategies.length === 0 ? <p>No strategies yet. Save your first hypothesis below.</p> : <ul className="strategy-list">{strategies.map((strategy) => <li key={strategy.strategy_id}><button type="button" aria-pressed={selected === strategy.strategy_id} onClick={() => setSelected(strategy.strategy_id)}>{strategy.name}</button></li>)}</ul>}
          <form onSubmit={create} className="strategy-form">
            <h3>New hypothesis</h3>
            <label>Name<input required maxLength={180} value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} /></label>
            <label>What do you want to test?<textarea required rows={3} value={draft.hypothesis} onChange={(e) => setDraft({ ...draft, hypothesis: e.target.value })} /></label>
            <label>Why might it work?<textarea required rows={3} value={draft.rationale} onChange={(e) => setDraft({ ...draft, rationale: e.target.value })} /></label>
            <button className="primary-button" disabled={busy} type="submit">{busy ? "Saving…" : "Save hypothesis"}</button>
          </form>
        </aside>
        {selected ? <StrategyEditor key={selected} strategyId={selected} onChanged={reload} onRequestReview={onRequestReview} /> : <div className="strategy-card"><h3>Research with a record</h3><p>Each version preserves its rules and sources. Every experiment stays in the history, including failed and cancelled attempts.</p><p>No returns have been measured yet.</p></div>}
      </div>
    </section>
  );
}

function StrategyEditor({ strategyId, onChanged, onRequestReview }: { strategyId: string; onChanged: () => Promise<void>; onRequestReview?: (selection: { version_id: string; experiment_id: string }) => void }) {
  const [detail, setDetail] = useState<StrategyDetail | null>(null);
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [snapshotId, setSnapshotId] = useState("");
  const [planId, setPlanId] = useState("");
  const [evaluation, setEvaluation] = useState("development");
  const [engine, setEngine] = useState("local_replay");
  const [runtime, setRuntime] = useState<ResearchRuntime | null>(null);
  const jobKey = useRef<string | null>(null);
  const refresh = useCallback(async (signal?: AbortSignal) => {
    const [nextDetail, nextRuns, nextSnapshots, nextRuntime] = await Promise.all([
      researchRequest<StrategyDetail>(`/strategies/${strategyId}`, undefined, "GET", signal),
      researchRequest<{ experiments: Experiment[] }>(`/strategies/${strategyId}/experiments`, undefined, "GET", signal),
      researchRequest<{ snapshots: Snapshot[] }>("/snapshots", undefined, "GET", signal),
      researchRequest<ResearchRuntime>("/runtime", undefined, "GET", signal),
    ]);
    setDetail(nextDetail); setExperiments(nextRuns.experiments); setSnapshots(nextSnapshots.snapshots);
    setRuntime(nextRuntime);
  }, [strategyId]);

  useEffect(() => {
    const controller = new AbortController();
    refresh(controller.signal).catch((e) => { if (!controller.signal.aborted) setError(e.message); });
    return () => controller.abort();
  }, [refresh]);
  const pending = experiments.some((run) => run.state === "queued" || run.state === "running");
  useEffect(() => {
    if (!pending) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try { await refresh(controller.signal); }
      catch (e) { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : "Status unavailable"); }
      if (!controller.signal.aborted) timer = setTimeout(poll, 3000);
    }
    timer = setTimeout(poll, 3000);
    return () => { controller.abort(); clearTimeout(timer); };
  }, [pending, refresh]);

  async function action(work: () => Promise<unknown>, message: string) {
    setBusy(true); setError(""); setNotice("");
    try { await work(); await refresh(); setNotice(message); }
    catch (e) { setError(e instanceof Error ? e.message : "Research action failed"); }
    finally { setBusy(false); }
  }

  async function queue(event: FormEvent) {
    event.preventDefault();
    const payload = { plan_id: planId, snapshot_id: snapshotId, evaluation, engine };
    jobKey.current ??= crypto.randomUUID();
    await action(async () => {
      await researchRequest("/experiments", { ...payload, idempotency_key: jobKey.current });
      jobKey.current = null;
    }, "Experiment registered. Its worker status will update here.");
  }

  if (!detail) return <div className="strategy-card">{error ? <p role="alert">{error}</p> : <p role="status">Loading strategy…</p>}</div>;
  const selectedSnapshot = snapshots.find((s) => s.snapshot_id === snapshotId);
  const selectedPlan = detail.plans.find((p) => p.plan_id === planId);
  const callsOnFixture = !!selectedPlan?.payload.extraction && selectedSnapshot?.evidence_kind === "fixture";
  return (
    <div className="strategy-main">
      {error ? <p className="strategy-error" role="alert">{error}</p> : null}
      {notice ? <p role="status">{notice}</p> : null}
      <article className="strategy-card"><h3>{detail.strategy.name}</h3><p>{detail.strategy.hypothesis}</p><p>{detail.strategy.rationale}</p>
        <h4>How this can lose</h4>
        {detail.versions.some((version) => version.payload.spec.rules.kind === "diversified_trend") ? <p>Trend rules can suffer repeated losses in sideways markets, react late to reversals, and hold assets that fall together. Cash reserves and position caps do not guarantee a maximum loss.</p> : null}
        {detail.versions.some((version) => version.payload.spec.rules.kind === "guidance_cash_quality") ? <p>Raised guidance can already be priced in or later withdrawn. Cash improvements can be temporary, and classification errors, earnings gaps, halts and unavailable exits can overwhelm the expected benefit.</p> : null}
        {!detail.versions.length ? <p>The investment mechanism is untested. Specify the rules and the conditions that could cause losses before freezing an experiment.</p> : null}
        <h4>What would invalidate the idea</h4>
        <p>Failure to meet the frozen plan&apos;s after-cost comparison and drawdown criteria counts against the idea. Missing observations, incompatible source periods or uncertain availability leave it unproven. A historical model result alone cannot establish prospective value.</p>
        <h4>Evidence and next decision</h4>
        <p>{experiments.filter((experiment) => experiment.state === "completed").length} completed experiment(s) across this hypothesis; every failed and cancelled attempt remains below. Completion does not establish eligibility.</p>
        <p>{!detail.versions.length ? "Freeze a bounded strategy version, then declare its controls and acceptance criteria." : !detail.plans.length ? "Freeze the dates, controls, costs and acceptance criteria before inspecting results." : !experiments.length ? "Select a compatible snapshot and run the frozen plan. Start with development data; the final holdout is consumed when dispatched." : "Inspect each version’s evidence, missing inputs and cost sensitivity below. Revise an unsupported idea or request explicit paper review when its evidence qualifies."}</p>
        <details><summary>Revise hypothesis</summary><DraftEditor key={detail.strategy.revision} strategy={detail.strategy} busy={busy} onSave={(draft) => action(async () => { await researchRequest(`/strategies/${strategyId}`, { draft, expected_revision: detail.strategy.revision }, "PUT"); await onChanged(); }, "Draft revised. Frozen versions retain their original hypothesis.")} /></details>
      </article>
      <StrategyDesignerPanel detail={detail} busy={busy} onRefresh={refresh}
        onSaveDraft={(draft) => action(async () => { await researchRequest(`/strategies/${strategyId}`, { draft, expected_revision: detail.strategy.revision }, "PUT"); await onChanged(); }, "Reviewed hypothesis saved. Existing versions retain their original hypothesis.")}
        onFreeze={(specs, designId) => action(async () => {
          await researchRequest(`/strategies/${strategyId}/versions/batch`, { versions: specs.map((spec) => ({ spec, design_id: designId, parent_version_id: detail.versions.at(-1)?.version_id ?? null })) });
        }, "Reviewed proposal frozen with its design provenance. It still requires an independent test plan and evaluation.")} />
      <VersionEditor busy={busy} versionCount={detail.versions.length} onFreeze={(specs) => action(async () => {
        const [schema, providers] = await Promise.all([
          specs.some((spec) => spec.model) ? researchRequest<{ prompt_hash: string; schema_hash: string }>("/evidence/schema") : null,
          specs.some((spec) => spec.model?.provider_config_hash) ? researchRequest<{ providers: ResearchProvider[] }>("/evidence/providers") : null,
        ]);
        for (const spec of specs) {
          if (!spec.model?.provider_config_hash) continue;
          const current = providers?.providers.find((p) => p.role === "research_extractor");
          if (!current?.available || current.provider_config_hash !== spec.model.provider_config_hash || current.model_id !== spec.model.model_id || current.provider_id !== spec.model.provider_id) throw new Error("Evidence model configuration changed. Use the configured evidence model again before freezing.");
        }
        await researchRequest(`/strategies/${strategyId}/versions/batch`, { versions: specs.map((spec) => ({ spec: spec.model && schema ? { ...spec, model: { ...spec.model, prompt_hash: schema.prompt_hash, schema_hash: schema.schema_hash } } : spec, parent_version_id: detail.versions.at(-1)?.version_id ?? null })) });
      }, specs.length === 3 ? "Three matched guidance arms frozen together." : "Strategy version frozen.")} />
      {detail.versions.length ? <PlanEditor key={`${strategyId}-${detail.versions.length}-${detail.family?.family_id ?? "unfrozen"}`} detail={detail} busy={busy} onFreeze={(plan) => action(async () => { const saved = await researchRequest<ResearchPlan>("/plans", plan); setPlanId(saved.plan_id); }, "Test plan frozen. The research family budget is shared across revisions.")} /> : null}
      <StrategyDatasetPanel onImported={async (snapshot) => { await refresh(); setSnapshotId(snapshot.snapshot_id); jobKey.current = null; }} />
      <form onSubmit={queue} className="strategy-card strategy-form"><h3>Run an experiment</h3>
        {runtime ? <p role="status"><span className="strategy-badge">{runtime.available ? "Worker connected" : "Worker offline"}</span> {runtime.message}</p> : null}
        <label>Research engine<select value={engine} onChange={(e) => { setEngine(e.target.value); jobKey.current = null; }}><option value="local_replay">Local deterministic replay</option><option value="lean" disabled={!runtime?.engine_capabilities?.some((item) => item.engine === "lean" && item.available)}>LEAN · native simulated execution</option></select></label>
        <p>{engine === "lean" ? "Uses the pinned offline LEAN image, the same strategy rules and explicit session calendar. Native fills and account values are checked against the research ledger." : "Uses the local replay engine with the frozen fees, slippage and opening-window assumptions."}</p>
        {runtime?.engine_capabilities?.find((item) => item.engine === "lean" && !item.available) ? <p>LEAN: {runtime.engine_capabilities.find((item) => item.engine === "lean")?.message}</p> : null}
        <label>Frozen test plan<select required value={planId} onChange={(e) => { setPlanId(e.target.value); jobKey.current = null; }}><option value="">Choose a plan</option>{detail.plans.map((p, i) => <option key={p.plan_id} value={p.plan_id}>Plan {i + 1} · {p.payload.version_ids.length} variant(s)</option>)}</select></label>
        <label>Data snapshot<select required value={snapshotId} onChange={(e) => { setSnapshotId(e.target.value); jobKey.current = null; }}><option value="">Choose a snapshot</option>{snapshots.map((s) => <option key={s.snapshot_id} value={s.snapshot_id}>{evidenceLabel(s.evidence_kind)} · {s.payload.provider} · {s.payload.coverage_start} to {s.payload.coverage_end}</option>)}</select></label>
        {snapshots.length === 0 ? <p>No data snapshots are available. Import a dataset before evaluating this strategy.</p> : null}
        {selectedSnapshot ? <p>{selectedSnapshot.payload.provenance} {selectedSnapshot.payload.limitations.join(" ")}</p> : null}
        {selectedPlan?.payload.extraction ? <p>This plan enables up to {selectedPlan.payload.extraction.max_calls} new evidence calls, using its frozen model, prices and shared research budget.</p> : <p>This plan makes no new model calls. It replays preserved evidence.</p>}
        {callsOnFixture ? <p role="alert" className="strategy-error">Synthetic fixtures use preserved responses. Choose a plan with new calls disabled or an eligible source snapshot.</p> : null}
        <label>Evaluation period<select value={evaluation} onChange={(e) => { setEvaluation(e.target.value); jobKey.current = null; }}><option value="development">Development</option><option value="validation">Validation</option><option value="holdout">Final holdout — consumed on dispatch</option></select></label>
        <button className="primary-button" disabled={busy || !planId || !snapshotId || callsOnFixture} type="submit">Queue experiment</button>
      </form>
      <section aria-label="Complete experiment history"><h3>All attempts</h3>{experiments.length ? experiments.map((experiment) => <StrategyEvidencePanel key={experiment.experiment_id} experiment={experiment} busy={busy} onRequestReview={onRequestReview} onCancel={() => action(() => researchRequest(`/experiments/${experiment.experiment_id}/cancel`, {}), "Cancelled. Trial history is retained.")} />) : <p>No experiments yet.</p>}</section>
    </div>
  );
}

function DraftEditor({ strategy, busy, onSave }: { strategy: Strategy; busy: boolean; onSave: (draft: StrategyDraft) => Promise<void> }) {
  const [draft, setDraft] = useState<StrategyDraft>({ name: strategy.name, hypothesis: strategy.hypothesis, rationale: strategy.rationale });
  return <form className="strategy-form" onSubmit={(e) => { e.preventDefault(); void onSave(draft); }}>
    <label>Name<input required value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} /></label>
    <label>Hypothesis<textarea required value={draft.hypothesis} onChange={(e) => setDraft({ ...draft, hypothesis: e.target.value })} /></label>
    <label>Rationale<textarea required value={draft.rationale} onChange={(e) => setDraft({ ...draft, rationale: e.target.value })} /></label>
    <button className="secondary-button" disabled={busy} type="submit">Save revision</button>
  </form>;
}

function VersionEditor({ busy, versionCount, onFreeze }: { busy: boolean; versionCount: number; onFreeze: (specs: StrategySpec[]) => Promise<void> }) {
  const [universeText, setUniverseText] = useState("SPY | us-spy | equity\nEFA | us-efa | equity\nIEF | us-ief | rates\nTIP | us-tip | rates\nGLD | us-gld | gold");
  const [kind, setKind] = useState("diversified_trend");
  const [position, setPosition] = useState(25);
  const [group, setGroup] = useState(50);
  const [reserve, setReserve] = useState(10);
  const [drawdown, setDrawdown] = useState(15);
  const [lookbacks, setLookbacks] = useState("63, 126, 252");
  const [volatility, setVolatility] = useState(63);
  const [latency, setLatency] = useState(1);
  const [hold, setHold] = useState(30);
  const [validity, setValidity] = useState(5);
  const [modelProvider, setModelProvider] = useState("");
  const [modelId, setModelId] = useState("");
  const [modelPin, setModelPin] = useState<string | null>(null);
  const [providerMessage, setProviderMessage] = useState("");
  const [loadingProvider, setLoadingProvider] = useState(false);
  async function selectConfiguredModel() {
    setLoadingProvider(true); setProviderMessage("");
    try {
      const result = await researchRequest<{ providers: ResearchProvider[] }>("/evidence/providers");
      const provider = result.providers.find((p) => p.role === "research_extractor");
      if (!provider?.available || !provider.provider_id || !provider.model_id || !provider.provider_config_hash) throw new Error(provider?.message ?? "No evidence model is configured");
      setModelProvider(provider.provider_id); setModelId(provider.model_id); setModelPin(provider.provider_config_hash); setProviderMessage(provider.message);
    } catch (e) { setProviderMessage(e instanceof Error ? e.message : "Could not read the evidence model"); }
    finally { setLoadingProvider(false); }
  }
  function freeze(event: FormEvent) {
    event.preventDefault();
    const universe = universeText.split("\n").filter((row) => row.trim()).map((row) => {
      const [symbol = "", instrument_id = "", risk_group = ""] = row.split("|").map((v) => v.trim());
      return { symbol: symbol.toUpperCase(), instrument_id, risk_group, currency: "USD" as const };
    });
    const risk = { max_position_fraction: String(position / 100), max_group_fraction: String(group / 100), cash_reserve_fraction: String(reserve / 100), max_turnover_fraction: "1", max_drawdown_fraction: String(drawdown / 100) };
    if (kind === "diversified_trend") {
      void onFreeze([{ universe, risk, rules: { kind, lookbacks_sessions: lookbacks.split(",").map(Number), volatility_sessions: volatility, decision_latency_seconds: latency } }]);
    } else {
      void onFreeze((["guidance_control", "numeric_quality", "astra_challenger"] as const).map((arm) => ({ universe, risk,
        rules: { kind: "guidance_cash_quality", arm, hold_sessions: hold, decision_latency_seconds: latency, entry_validity_sessions: validity },
        model: arm === "astra_challenger" ? { provider_id: modelProvider, model_id: modelId, provider_config_hash: modelPin, prompt_hash: "", schema_hash: "", historical_latency_seconds: 60 } : null })));
    }
  }
  return <form className="strategy-card strategy-form" onSubmit={freeze}><h3>Freeze strategy rules</h3><p>{versionCount} frozen version(s). These are research assumptions, editable before freezing.</p>
    <label>Strategy template<select value={kind} onChange={(e) => setKind(e.target.value)}><option value="diversified_trend">Diversified trend</option><option value="guidance_comparison">Guidance · three matched arms</option></select></label>
    <label>Universe — one symbol | dataset instrument ID | risk group per line<textarea required rows={5} value={universeText} onChange={(e) => setUniverseText(e.target.value)} /></label>
    <button type="button" className="secondary-button compact" onClick={() => { setUniverseText("SIM-EQ | us-sim-eq | equity\nSIM-BOND | us-sim-bond | rates"); setKind("diversified_trend"); }}>Use synthetic example universe</button>
    <button type="button" className="secondary-button compact" onClick={() => {
      setUniverseText("SIM-CLEAN | sim-clean | industrials\nSIM-ONEOFF | sim-oneoff | industrials\nSIM-WEAK | sim-weak | industrials\nSIM-UNKNOWN | sim-unknown | industrials");
      setKind("guidance_comparison"); setPosition(20); setGroup(80); setReserve(10); setDrawdown(20); setHold(30); setValidity(5); setLatency(1);
      setModelProvider("synthetic-fixture"); setModelId("labelled-fixture-classifier-v1"); setModelPin(null); setProviderMessage("");
    }}>Use labelled guidance example</button>
    {kind === "diversified_trend" ? <>
      <label>Momentum lookbacks, in trading sessions<input required value={lookbacks} onChange={(e) => setLookbacks(e.target.value)} /></label>
      <div className="strategy-form-grid"><label>Volatility window (sessions)<input required type="number" min={2} max={252} value={volatility} onChange={(e) => setVolatility(Number(e.target.value))} /></label><label>Decision delay after close (seconds)<input required type="number" min={0} max={3600} value={latency} onChange={(e) => setLatency(Number(e.target.value))} /></label></div>
    </> : <>
      <p>Compares guidance alone, independently calculated cash quality, and cash quality plus cited evidence. Each filter leaves excluded allocations in cash. All three arms freeze together.</p>
      <div className="strategy-form-grid"><label>Hold after actual entry (sessions)<input required type="number" min={1} max={252} value={hold} onChange={(e) => setHold(Number(e.target.value))} /></label><label>Event entry window (sessions)<input required type="number" min={1} max={30} value={validity} onChange={(e) => setValidity(Number(e.target.value))} /></label></div>
      <button type="button" className="secondary-button" disabled={loadingProvider || busy} onClick={() => void selectConfiguredModel()}>{loadingProvider ? "Reading model configuration…" : "Use configured evidence model"}</button>
      {providerMessage ? <p role="status">{providerMessage}</p> : null}
      <label>Evidence provider ID<input required value={modelProvider} onChange={(e) => { setModelProvider(e.target.value); setModelPin(null); setProviderMessage(""); }} /></label>
      <label>Pinned API model ID<input required value={modelId} onChange={(e) => { setModelId(e.target.value); setModelPin(null); setProviderMessage(""); }} /></label>
      <p>{modelPin ? "Provider, endpoint and API model are pinned. You can enable metered calls in the test plan." : "Manual model IDs replay preserved responses only. Use the configured evidence model to enable new calls."} Configure the Research extractor role in Settings. The labelled example uses hand-authored responses, not Astra output.</p>
      <p>Entry requires a $5 price floor and $1 million average daily dollar volume over 20 completed sessions. Cash quality requires eight comparable GAAP quarters, latest period no older than 180 days. Financials and real estate are excluded. Missing evidence abstains.</p>
    </>}
    <div className="strategy-form-grid">
      <label>Maximum per position (%)<input type="number" required min={1} max={100} value={position} onChange={(e) => setPosition(Number(e.target.value))} /></label>
      <label>Maximum per risk group (%)<input type="number" required min={1} max={100} value={group} onChange={(e) => setGroup(Number(e.target.value))} /></label>
      <label>Cash reserve (%)<input type="number" required min={0} max={99} value={reserve} onChange={(e) => setReserve(Number(e.target.value))} /></label>
      <label>Drawdown intervention (%)<input type="number" required min={1} max={99} value={drawdown} onChange={(e) => setDrawdown(Number(e.target.value))} /></label>
    </div><p>Long only. Weekly trend rebalancing and next-session execution. A drawdown intervention cannot guarantee a maximum loss.</p>
    <button type="submit" className="secondary-button" disabled={busy || loadingProvider}>{kind === "diversified_trend" ? "Freeze new version" : "Freeze three matched arms"}</button>
  </form>;
}

function PlanEditor({ detail, busy, onFreeze }: { detail: StrategyDetail; busy: boolean; onFreeze: (plan: PlanInput) => Promise<void> }) {
  const previous = detail.plans.at(-1)?.payload;
  const guidance = detail.versions.at(-1)!.payload.spec.rules.kind === "guidance_cash_quality";
  const [versions, setVersions] = useState<string[]>(guidance ? detail.versions.slice(-3).map((v) => v.version_id) : [detail.versions.at(-1)!.version_id]);
  const [dates, setDates] = useState<Record<string, string>>({ train_start: "", train_end: "", validation_start: "", validation_end: "", holdout_start: "", holdout_end: "" });
  const [capital, setCapital] = useState("100000");
  const [trials, setTrials] = useState(detail.family?.max_trials ?? previous?.max_trials ?? 30);
  const [budget, setBudget] = useState(detail.family?.compute_budget_usd ?? previous?.compute_budget_usd ?? "20");
  const [slippage, setSlippage] = useState("5");
  const [commission, setCommission] = useState("1");
  const [minimum, setMinimum] = useState(60);
  const [excess, setExcess] = useState("1");
  const [rationale, setRationale] = useState("");
  const [embargo, setEmbargo] = useState(30);
  const [maxDrawdown, setMaxDrawdown] = useState(15);
  const [cashYield, setCashYield] = useState("0");
  const [clusters, setClusters] = useState(30);
  const [humanLabels, setHumanLabels] = useState(50);
  const [accuracyLower, setAccuracyLower] = useState(80);
  const [extraction, setExtraction] = useState<ExtractionPolicy | null>(null);
  const [runtimeSeconds, setRuntimeSeconds] = useState(300);
  const [referenceEnabled, setReferenceEnabled] = useState(!!previous?.equity_reference);
  const [referenceSymbol, setReferenceSymbol] = useState(previous?.equity_reference?.instrument.symbol ?? "");
  const [referenceId, setReferenceId] = useState(previous?.equity_reference?.instrument.instrument_id ?? "");
  const [referenceWeight, setReferenceWeight] = useState(Number(previous?.equity_reference?.initial_allocation_fraction ?? ".95") * 100);
  const [referenceReason, setReferenceReason] = useState(previous?.equity_reference?.rationale ?? "");
  const selectedModels = detail.versions.filter((v) => versions.includes(v.version_id)).flatMap((v) => v.payload.spec.model ? [v.payload.spec.model] : []);
  const canExtract = selectedModels.length > 0 && selectedModels.every((model) => !!model.provider_config_hash);
  function freeze(event: FormEvent) {
    event.preventDefault();
    void onFreeze({ strategy_id: detail.strategy.strategy_id, family_id: detail.family?.family_id ?? previous?.family_id ?? detail.strategy.strategy_id, version_ids: versions,
      split: { ...dates, embargo_sessions: embargo } as PlanInput["split"], initial_capital_usd: capital, cash_annual_yield_fraction: String(Number(cashYield) / 100), max_trials: trials, compute_budget_usd: budget, max_runtime_seconds: runtimeSeconds, extraction,
      equity_reference: referenceEnabled ? { instrument: { instrument_id: referenceId.trim(), symbol: referenceSymbol.trim().toUpperCase(), risk_group: "equity", currency: "USD" }, initial_allocation_fraction: String(referenceWeight / 100), rationale: referenceReason } : null,
      scenarios: [{ name: "base", slippage_bps: slippage, commission_usd: commission, execution_delay_sessions: 0 }, { name: "double_cost", slippage_bps: String(Number(slippage) * 2), commission_usd: String(Number(commission) * 2), execution_delay_sessions: 0 }, { name: "delayed", slippage_bps: slippage, commission_usd: commission, execution_delay_sessions: 1 }],
      criteria: { min_observations: minimum, min_net_excess_return_fraction: String(Number(excess) / 100), max_drawdown_fraction: String(maxDrawdown / 100), rationale,
        min_guidance_event_clusters: clusters, min_human_labels: humanLabels, min_classifier_accuracy_lower_bound: String(accuracyLower/100) },
    });
  }
  return <form className="strategy-card strategy-form" onSubmit={freeze}><h3>Freeze the test plan</h3>
    <fieldset><legend>Variants to compare</legend>{detail.versions.map((version, index) => <label className="strategy-checkbox" key={version.version_id}><input type="checkbox" checked={versions.includes(version.version_id)} onChange={(e) => setVersions(e.target.checked ? [...versions, version.version_id] : versions.filter((id) => id !== version.version_id))} />Version {index + 1} · {evidenceLabel(version.payload.spec.rules.kind === "guidance_cash_quality" ? version.payload.spec.rules.arm : version.payload.spec.rules.kind)}</label>)}</fieldset>
    {guidance ? <p>Select all three matched arms. The labelled guidance events occur in the example 2020 holdout; earlier example periods contain financial context only.</p> : null}
    <div className="strategy-form-grid">{Object.keys(dates).map((key) => <label key={key}>{key.replaceAll("_", " ")}<input required type="date" value={dates[key]} onChange={(e) => setDates({ ...dates, [key]: e.target.value })} /></label>)}</div>
    <button type="button" className="secondary-button compact" onClick={() => { setDates({ train_start: "2019-01-01", train_end: "2019-06-28", validation_start: "2019-07-01", validation_end: "2019-12-31", holdout_start: "2020-01-01", holdout_end: "2020-12-31" }); setRationale("Synthetic software acceptance only. These example thresholds do not establish investment performance."); }}>Use synthetic example dates</button>
    <div className="strategy-form-grid">
      <label>Simulated capital (USD)<input required type="number" min={1} value={capital} onChange={(e) => setCapital(e.target.value)} /></label>
      <label>Family trial limit<input required type="number" min={1} max={1000} disabled={!!detail.family || !!previous} value={trials} onChange={(e) => setTrials(Number(e.target.value))} /></label>
      <label>Research cost limit (USD)<input required type="number" min="0.000001" step="0.000001" disabled={!!detail.family || !!previous} value={budget} onChange={(e) => setBudget(e.target.value)} /></label>
      <label>Experiment runtime limit (seconds)<input required type="number" min={1} max={3600} value={runtimeSeconds} onChange={(e) => setRuntimeSeconds(Number(e.target.value))} /></label>
      <label>Slippage (basis points)<input required type="number" min={0} step="0.1" value={slippage} onChange={(e) => setSlippage(e.target.value)} /></label>
      <label>Commission per order (USD)<input required type="number" min={0} step="0.01" value={commission} onChange={(e) => setCommission(e.target.value)} /></label>
      <label>Minimum observations<input required type="number" min={2} value={minimum} onChange={(e) => setMinimum(Number(e.target.value))} /></label>
      <label>Minimum excess return (%)<input required type="number" step="0.1" value={excess} onChange={(e) => setExcess(e.target.value)} /></label>
      <label>Boundary embargo (sessions)<input required type="number" min={0} max={252} value={embargo} onChange={(e) => setEmbargo(Number(e.target.value))} /></label>
      <label>Drawdown review criterion (%)<input required type="number" min={1} max={99} value={maxDrawdown} onChange={(e) => setMaxDrawdown(Number(e.target.value))} /></label>
      <label>Assumed annual cash yield (%)<input required type="number" min={0} max={100} step="0.01" value={cashYield} onChange={(e) => setCashYield(e.target.value)} /></label>
    </div>
    {guidance ? <div className="strategy-form-grid">
      <label>Minimum issuer/forecast-period clusters<input required type="number" min={2} value={clusters} onChange={(e) => setClusters(Number(e.target.value))} /></label>
      <label>Minimum human labels<input required type="number" min={2} value={humanLabels} onChange={(e) => setHumanLabels(Number(e.target.value))} /></label>
      <label>Required classification accuracy lower bound (%)<input required type="number" min={0} max={100} value={accuracyLower} onChange={(e) => setAccuracyLower(Number(e.target.value))} /></label>
    </div> : null}
    {guidance ? <StrategyExtractionPolicy value={extraction} onChange={setExtraction} available={canExtract} familyBudget={budget} /> : null}
    <label>Why are these acceptance criteria appropriate?<textarea required rows={2} value={rationale} onChange={(e) => setRationale(e.target.value)} /></label>
    <p>Includes doubled costs and a one-session execution delay. Each variant and cost scenario consumes a trial; revisions share the same family budget. Uncertainty estimates require sufficient independent time blocks and may remain undefined.</p>
    <fieldset><legend>Equity-market reference</legend>
      <label><input type="checkbox" checked={referenceEnabled} onChange={(e) => setReferenceEnabled(e.target.checked)} /> Include a predeclared buy-and-hold reference</label>
      <p>Uses the same dates, starting capital, cash yield and cost scenarios. One purchase is sized after the first evaluated close, then held without rebalancing or dividend reinvestment. The dataset must cover this instrument. A missing or unfilled reference prevents paper-review eligibility.</p>
      {referenceEnabled ? <>
        <label>Reference symbol<input required value={referenceSymbol} onChange={(e) => setReferenceSymbol(e.target.value)} /></label>
        <label>Reference dataset instrument ID<input required value={referenceId} onChange={(e) => setReferenceId(e.target.value)} /></label>
        <label>Initial reference allocation (%)<input required type="number" min={0.01} max={99.99} step={0.01} value={referenceWeight} onChange={(e) => setReferenceWeight(Number(e.target.value))} /></label>
        <label>Why is this equity reference appropriate?<textarea required value={referenceReason} onChange={(e) => setReferenceReason(e.target.value)} /></label>
      </> : <p>Exploratory runs can omit it. Their evidence cannot qualify for paper review.</p>}
    </fieldset>
    <button type="submit" className="secondary-button" disabled={busy || versions.length === 0 || (!!extraction && !canExtract)}>Freeze test plan</button>
  </form>;
}
