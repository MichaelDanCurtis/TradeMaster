"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { ResearchRequestError, researchRequest, type ResearchProvider, type StrategyDetail, type StrategyDraft, type StrategySpec } from "@/lib/research-api";

type Proposal = { status: "supported" | "unsupported" | "abstain"; draft: StrategyDraft; economic_mechanism: string;
  falsification_tests: string[]; required_data: string[]; failure_modes: string[]; implementation_notes: string; spec: StrategySpec | null };
type Design = { design_id: string; state: string; created_at: string; deadline_at: string; request_hash: string;
  reserved_cost_usd: string; charged_cost_usd: string; failure_reason: string | null;
  request: { input: { model_id: string; provider_id: string; prompt_hash: string; schema_hash: string; policy?: {billing_mode?: string} } };
  receipt: { proposal: Proposal | null; actual_model_id: string; actual_provider_id: string; raw_output: string;
    input_tokens: number | null; output_tokens: number | null; validation_errors: string[] } | null };
type Pin = { provider: ResearchProvider; prompt_hash: string; schema_hash: string };

export function StrategyDesignerPanel({ detail, onRefresh, onSaveDraft, onFreeze, busy }: {
  detail: StrategyDetail; onRefresh: () => Promise<void>; onSaveDraft: (draft: StrategyDraft) => Promise<void>;
  onFreeze: (specs: StrategySpec[], designId: string) => Promise<void>; busy: boolean;
}) {
  const last = detail.versions.at(-1)?.payload.spec;
  const [brief, setBrief] = useState(detail.strategy.hypothesis);
  const [universe, setUniverse] = useState(last?.universe.map((i) => `${i.symbol} | ${i.instrument_id} | ${i.risk_group}`).join("\n") ?? "");
  const [kind, setKind] = useState(last?.rules.kind ?? "diversified_trend");
  const [risk, setRisk] = useState(last?.risk ?? { max_position_fraction: ".25", max_group_fraction: ".5", cash_reserve_fraction: ".1", max_turnover_fraction: "1", max_drawdown_fraction: ".15" });
  const [trials, setTrials] = useState(detail.family?.max_trials ?? 30);
  const [budget, setBudget] = useState(detail.family?.compute_budget_usd ?? "20");
  const [inputRate, setInputRate] = useState("");
  const [outputRate, setOutputRate] = useState("");
  const [pricing, setPricing] = useState("");
  const [pin, setPin] = useState<Pin | null>(null);
  const [evidencePin, setEvidencePin] = useState<ResearchProvider | null>(null);
  const [designs, setDesigns] = useState<Design[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [reviewDraft, setReviewDraft] = useState<StrategyDraft | null>(null);
  const [reviewSpec, setReviewSpec] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const request = useRef<Record<string, unknown> | null>(null);
  const sid = detail.strategy.strategy_id;
  const reload = useCallback(async (signal?: AbortSignal) => {
    const result = await researchRequest<{ designs: Design[] }>(`/strategies/${sid}/designs`, undefined, "GET", signal);
    setDesigns(result.designs);
  }, [sid]);
  useEffect(() => {
    const controller = new AbortController();
    reload(controller.signal).catch((e) => { if (!controller.signal.aborted) setError(e.message); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [reload]);
  const pending = designs.some((d) => d.state === "reserved" || d.state === "dispatched");
  useEffect(() => {
    if (!pending) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try { await reload(controller.signal); await onRefresh(); }
      catch (e) { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : "Designer status unavailable"); }
      if (!controller.signal.aborted) timer = setTimeout(poll, 2000);
    };
    timer = setTimeout(poll, 2000);
    return () => { controller.abort(); clearTimeout(timer); };
  }, [pending, reload, onRefresh]);
  const selectedDesign = designs.find((d) => d.design_id === selected);
  const proposal = selectedDesign?.receipt?.proposal;
  const subscription = pin?.provider.billing_mode === "codex_subscription";
  const maximum = Math.ceil(65536 * Number(inputRate) + 8192 * Number(outputRate)) / 1000000;

  async function configure() {
    setWorking(true); setError(""); setPin(null);
    try {
      const [providers, schema] = await Promise.all([
        researchRequest<{ providers: ResearchProvider[] }>("/evidence/providers"),
        researchRequest<{ prompt_hash: string; schema_hash: string }>("/designer/schema"),
      ]);
      const provider = providers.providers.find((p) => p.role === "research_designer");
      if (!provider?.available) throw new Error(provider?.message ?? "Assign a research designer provider in Settings");
      setPin({ provider, ...schema });
    } catch (e) { setError(e instanceof Error ? e.message : "Designer unavailable"); }
    finally { setWorking(false); }
  }

  async function submit(event: FormEvent) {
    event.preventDefault(); setWorking(true); setError("");
    try {
      if (!request.current) {
        if (!pin) throw new Error("Review the configured designer first");
        const instruments = universe.split("\n").filter((s) => s.trim()).map((line) => {
          const [symbol = "", instrument_id = "", risk_group = ""] = line.split("|").map((s) => s.trim());
          return { symbol: symbol.toUpperCase(), instrument_id, risk_group, currency: "USD" };
        });
        request.current = { idempotency_key: crypto.randomUUID(), expected_revision: detail.strategy.revision,
          family_id: detail.family?.family_id ?? sid, max_trials: detail.family?.max_trials ?? trials,
          compute_budget_usd: detail.family?.compute_budget_usd ?? budget, brief,
          constraints: { universe: instruments, risk, rules: kind === "diversified_trend" ? { kind } : { kind, arm: "numeric_quality" } },
          provider_id: pin.provider.provider_id, model_id: pin.provider.model_id, provider_config_hash: pin.provider.provider_config_hash,
          prompt_hash: pin.prompt_hash, schema_hash: pin.schema_hash,
          policy: { max_calls: 1, max_input_tokens: 65536, max_output_tokens: 8192, timeout_seconds: 60,
            billing_mode: pin.provider.billing_mode ?? "api_metered",
            input_usd_per_million: subscription ? "0" : inputRate, output_usd_per_million: subscription ? "0" : outputRate,
            pricing_reference: subscription ? "Codex ChatGPT subscription; usage observed, no per-call API invoice or guaranteed token cap" : pricing, availability_mode: "observed" },
        };
      }
      await researchRequest(`/strategies/${sid}/designs`, request.current);
      request.current = null; setUncertain(false);
      await reload(); await onRefresh();
    } catch (e) {
      const unknown = !(e instanceof ResearchRequestError && e.status < 500);
      setUncertain(unknown); if (!unknown) request.current = null;
      setError(e instanceof Error ? e.message : "Design request outcome unknown");
    }
    finally { setWorking(false); }
  }

  async function freeze() {
    setWorking(true); setError("");
    try {
      if (!selectedDesign || proposal?.status !== "supported") throw new Error("Select a supported proposal");
      const spec = JSON.parse(reviewSpec) as StrategySpec;
      if (spec.rules.kind === "guidance_cash_quality") {
        const [providers, schema] = await Promise.all([
          researchRequest<{ providers: ResearchProvider[] }>("/evidence/providers"),
          researchRequest<{ prompt_hash: string; schema_hash: string }>("/evidence/schema"),
        ]);
        const provider = providers.providers.find((p) => p.role === "research_extractor");
        if (!provider?.available || !provider.provider_id || !provider.model_id || !provider.provider_config_hash) throw new Error("Configure an evidence extractor before freezing three matched guidance arms");
        if (!evidencePin || evidencePin.provider_config_hash !== provider.provider_config_hash) throw new Error("Review the configured evidence classifier before freezing these arms");
        await onFreeze((["guidance_control", "numeric_quality", "astra_challenger"] as const).map((arm) => ({ ...spec,
          rules: { ...spec.rules, kind: "guidance_cash_quality", hold_sessions: spec.rules.kind === "guidance_cash_quality" ? spec.rules.hold_sessions : 30, arm },
          model: arm === "astra_challenger" ? { provider_id: provider.provider_id!, model_id: provider.model_id!, provider_config_hash: provider.provider_config_hash, prompt_hash: schema.prompt_hash, schema_hash: schema.schema_hash, historical_latency_seconds: 60 } : null,
        })), selectedDesign.design_id);
      } else {
        await onFreeze([spec], selectedDesign.design_id);
      }
    } catch (e) { setError(e instanceof Error ? e.message : "Reviewed rules are invalid"); }
    finally { setWorking(false); }
  }

  async function reviewExtractor() {
    setWorking(true); setError(""); setEvidencePin(null);
    try {
      const result = await researchRequest<{ providers: ResearchProvider[] }>("/evidence/providers");
      const provider = result.providers.find((p) => p.role === "research_extractor");
      if (!provider?.available) throw new Error(provider?.message ?? "Configure an evidence extractor in Settings");
      setEvidencePin(provider);
    } catch (e) { setError(e instanceof Error ? e.message : "Evidence classifier unavailable"); }
    finally { setWorking(false); }
  }

  return <section className="strategy-card strategy-form" aria-label="Strategy designer"><h3>Design a testable strategy</h3>
    <p>Ask the configured research model to develop this hypothesis, identify failure modes, and propose supported rules. Every proposal is unevaluated.</p>
    {error ? <p role="alert" className="strategy-error">{error}</p> : null}
    <form className="strategy-form" onSubmit={submit}>
      <fieldset disabled={working || pending || uncertain || busy} className="strategy-form"><legend>Review the design request</legend>
        <label>Research brief<textarea required maxLength={12000} rows={3} value={brief} onChange={(e) => setBrief(e.target.value)} /></label>
        <label>Supported template<select value={kind} onChange={(e) => setKind(e.target.value as typeof kind)}><option value="diversified_trend">Diversified trend</option><option value="guidance_cash_quality">Guidance and cash quality</option></select></label>
        <label>Designer universe — symbol | dataset instrument ID | risk group<textarea required rows={3} value={universe} onChange={(e) => setUniverse(e.target.value)} /></label>
        <div className="strategy-form-grid">{(Object.keys(risk) as (keyof typeof risk)[]).map((key) => <label key={key}>{key.replaceAll("_", " ")}<input required type="number" min={0} max={key === "max_turnover_fraction" ? 2 : 1} step="0.001" value={risk[key]} onChange={(e) => setRisk({ ...risk, [key]: e.target.value })} /></label>)}</div>
        <p>Fractions: 0.25 means 25%. The model must preserve this universe and these limits. Drawdown intervention cannot guarantee a maximum loss.</p>
        <div className="strategy-form-grid">
          <label>Designer family trial ceiling<input required type="number" min={1} max={1000} disabled={!!detail.family} value={detail.family?.max_trials ?? trials} onChange={(e) => setTrials(Number(e.target.value))} /></label>
          <label>Designer family cost ceiling (USD)<input required type="number" min="0.000001" step="0.000001" disabled={!!detail.family} value={detail.family?.compute_budget_usd ?? budget} onChange={(e) => setBudget(e.target.value)} /></label>
          {pin && !subscription ? <><label>Designer input price (USD per million tokens)<input required type="number" min={0} step="0.000001" value={inputRate} onChange={(e) => setInputRate(e.target.value)} /></label>
          <label>Designer output price (USD per million tokens)<input required type="number" min={0} step="0.000001" value={outputRate} onChange={(e) => setOutputRate(e.target.value)} /></label></> : null}
        </div>
        {pin && !subscription ? <label>Designer price source and date<input required maxLength={4000} value={pricing} onChange={(e) => setPricing(e.target.value)} /></label> : null}
        <button type="button" className="secondary-button" onClick={() => void configure()}>Review configured designer</button>
      </fieldset>
      {pin ? <p>Configured {subscription ? "Codex" : "API"} model: <strong>{pin.provider.model_id}</strong> · provider {pin.provider.provider_id}. The receipt will confirm the responding model.</p> : <p>Select the configured designer to review the model and usage mode before making a call.</p>}
      {subscription ? <p>Uses your Codex ChatGPT sign-in and subscription limits. One attempt, a 60-second local deadline, and a bounded saved answer. Observed input/output review thresholds are 65,536 / 8,192 tokens; these are not provider-enforced caps. Usage can exceed a threshold before interruption takes effect. No API token charge is recorded; subscription usage is not free or unlimited. Each attempt consumes one family trial.</p> : <p>One call reserves up to ${maximum.toFixed(6)} at your declared prices, with 65,536 input tokens, 8,192 output tokens and a 60-second provider timeout. Each attempt consumes one family trial, including failures and abstentions. These ceilings also apply to later experiments.</p>}
      {detail.family_usage ? <p>Family usage: {detail.family_usage.trials} trials · ${detail.family_usage.cost_usd} charged or reserved. Configured costs are estimates, not a provider invoice.</p> : null}
      <button className="secondary-button" type="submit" disabled={working || busy || pending || (!pin && !uncertain)}>{working ? "Requesting…" : uncertain ? "Recover the same request" : subscription ? "Request one Codex design" : "Request one metered design"}</button>
      {uncertain ? <button type="button" className="secondary-button" disabled={working} onClick={() => { request.current = null; setUncertain(false); setError(""); void reload().catch((e) => setError(e.message)); }}>Review history before a new request</button> : null}
    </form>
    <h4>Design history</h4>
    {loading ? <p role="status">Loading designs…</p> : designs.length ? designs.map((design) => <article key={design.design_id}>
      <p><strong>{design.receipt?.proposal?.status ?? design.state}</strong> · {design.request.input.model_id} · {design.request.input.policy?.billing_mode === "codex_subscription" ? "Codex subscription usage" : `$${design.charged_cost_usd} charged or reserved`} · {new Date(design.created_at).toLocaleString()}</p>
      {design.failure_reason ? <p>{design.failure_reason}</p> : null}
      {design.receipt?.validation_errors.map((message, i) => <p key={i}>{message}</p>)}
      {design.receipt?.proposal ? <button className="secondary-button" type="button" onClick={() => { setSelected(design.design_id); setReviewDraft(design.receipt!.proposal!.draft); setReviewSpec(JSON.stringify(design.receipt!.proposal!.spec, null, 2)); }}>Review proposal</button> : null}
      <details><summary>Preserved model receipt</summary><p>Request {design.request_hash}</p><p>Actual model: {design.receipt?.actual_model_id ?? "Unconfirmed"}. Input/output tokens: {design.receipt?.input_tokens ?? "unknown"} / {design.receipt?.output_tokens ?? "unknown"}.</p><pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{design.receipt?.raw_output ?? "No response has been preserved."}</pre></details>
    </article>) : <p>No model designs yet. Saving and freezing a hypothesis does not require a model call.</p>}
    {proposal && reviewDraft ? <article className="strategy-form"><h4>Review the proposal · {proposal.status}</h4>
      <p>{proposal.economic_mechanism}</p>
      {([['Falsification tests', proposal.falsification_tests], ['Required data', proposal.required_data], ['Failure modes', proposal.failure_modes]] as [string, string[]][]).map(([label, items]) => <div key={label}><h5>{label}</h5><ul>{items.map((item, i) => <li key={i}>{item}</li>)}</ul></div>)}
      <p>{proposal.implementation_notes}</p>
      {(["name", "hypothesis", "rationale"] as const).map((key) => <label key={key}>Reviewed {key}<textarea maxLength={key === "name" ? 180 : 12000} value={reviewDraft[key]} onChange={(e) => setReviewDraft({ ...reviewDraft, [key]: e.target.value })} /></label>)}
      <button type="button" className="secondary-button" disabled={busy || working} onClick={() => void onSaveDraft(reviewDraft)}>Save reviewed hypothesis</button>
      {proposal.spec ? <><label>Reviewed executable rules<textarea rows={16} spellCheck={false} value={reviewSpec} onChange={(e) => setReviewSpec(e.target.value)} /></label>
        {proposal.spec.rules.kind === "guidance_cash_quality" ? <><button type="button" className="secondary-button" disabled={busy || working} onClick={() => void reviewExtractor()}>Review configured evidence classifier</button><p>{evidencePin ? `Evidence classifier: ${evidencePin.model_id} · provider ${evidencePin.provider_id}` : "Review the actual evidence classifier before freezing three matched arms."}</p></> : null}
        <p>The new version retains the saved hypothesis and this design receipt as provenance. Guidance freezes three matched arms using the configured evidence extractor. Review and save the hypothesis before freezing.</p>
        <button type="button" className="secondary-button" disabled={busy || working || (["name", "hypothesis", "rationale"] as const).some((key) => detail.strategy[key] !== reviewDraft[key])} onClick={() => void freeze()}>Freeze reviewed proposal</button></> : <p>This proposal has no supported executable specification.</p>}
    </article> : null}
  </section>;
}
