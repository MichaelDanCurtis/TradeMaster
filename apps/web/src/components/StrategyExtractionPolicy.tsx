"use client";

import type { ExtractionPolicy } from "@/lib/research-api";

const emptyPolicy: ExtractionPolicy = {
  max_calls: 10, max_input_tokens: 32768, max_output_tokens: 2048,
  input_usd_per_million: "", output_usd_per_million: "", pricing_reference: "",
  timeout_seconds: 60, availability_mode: "historical",
};

export function StrategyExtractionPolicy({ value, onChange, available, familyBudget }: {
  value: ExtractionPolicy | null; onChange: (policy: ExtractionPolicy | null) => void; available: boolean; familyBudget: string;
}) {
  const callReserve = value ? Math.ceil((value.max_input_tokens * Number(value.input_usd_per_million) + value.max_output_tokens * Number(value.output_usd_per_million))) / 1_000_000 : 0;
  const maximum = callReserve * (value?.max_calls ?? 0);
  const subscription = value?.billing_mode === "codex_subscription";
  return <fieldset className="strategy-form"><legend>New evidence calls</legend>
    <label className="strategy-checkbox"><input type="checkbox" checked={value !== null} disabled={!available && value === null} onChange={(e) => onChange(e.target.checked ? { ...emptyPolicy } : null)} />Enable metered model calls when this plan runs</label>
    <p>{available ? "Off by default. Existing exact responses are reused, including failures and unfavorable answers." : "Freeze a guidance version using the configured evidence model to enable new calls. Imported responses and labelled examples can be replayed without calls."}</p>
    {value ? <>
      {!available ? <p role="alert" className="strategy-error">The selected variants do not all have a pinned provider. Select the pinned versions or disable new calls.</p> : null}
      <label>Usage mode<select value={value.billing_mode ?? "api_metered"} onChange={(e)=>onChange({...value,billing_mode:e.target.value as ExtractionPolicy["billing_mode"],input_usd_per_million:e.target.value==="codex_subscription"?"0":"",output_usd_per_million:e.target.value==="codex_subscription"?"0":"",pricing_reference:e.target.value==="codex_subscription"?"Codex ChatGPT subscription; observed usage, no per-call API invoice or guaranteed token cap":""})}><option value="api_metered">API token pricing</option><option value="codex_subscription">Codex ChatGPT subscription</option></select></label>
      <div className="strategy-form-grid">
        <label>Maximum calls per experiment<input required type="number" min={1} max={1000} value={value.max_calls} onChange={(e) => onChange({ ...value, max_calls: Number(e.target.value) })} /></label>
        <label>Maximum seconds per call<input required type="number" min={1} max={300} value={value.timeout_seconds} onChange={(e) => onChange({ ...value, timeout_seconds: Number(e.target.value) })} /></label>
        <label>Input token reservation per call<input required type="number" min={1024} max={200000} value={value.max_input_tokens} onChange={(e) => onChange({ ...value, max_input_tokens: Number(e.target.value) })} /></label>
        <label>{subscription ? "Observed output-token review threshold" : "Maximum output tokens per call"}<input required type="number" min={128} max={8192} value={value.max_output_tokens} onChange={(e) => onChange({ ...value, max_output_tokens: Number(e.target.value) })} /></label>
        {!subscription ? <><label>Input price (USD per million tokens)<input required type="number" min={0} step="0.000001" value={value.input_usd_per_million} onChange={(e) => onChange({ ...value, input_usd_per_million: e.target.value })} /></label>
        <label>Output price (USD per million tokens)<input required type="number" min={0} step="0.000001" value={value.output_usd_per_million} onChange={(e) => onChange({ ...value, output_usd_per_million: e.target.value })} /></label></> : null}
      </div>
      {!subscription ? <label>Price source and date<input required maxLength={4000} placeholder="Provider price page and the date you checked it" value={value.pricing_reference} onChange={(e) => onChange({ ...value, pricing_reference: e.target.value })} /></label> : null}
      <label>When may the strategy use the response?<select value={value.availability_mode} onChange={(e) => onChange({ ...value, availability_mode: e.target.value as ExtractionPolicy["availability_mode"] })}><option value="historical">Historical simulation · exploratory only</option><option value="observed">Actual arrival · prospective evaluation</option></select></label>
      {subscription ? <p role="status">Uses Codex subscription allowance. Call count, local timeout, and saved-response size are bounded. Token thresholds stop further work when observed; they do not guarantee a provider token cap. Subscription usage is not included in the family’s API/compute dollar total.</p> : <p role="status">Reserve up to ${callReserve.toFixed(6)} per call; ${maximum.toFixed(6)} per experiment at these prices. Shared family limit: ${Number(familyBudget).toFixed(2)}.</p>}
      {maximum > Number(familyBudget) ? <p role="alert" className="strategy-error">The call reservation exceeds the family limit.</p> : null}
      <p>{subscription ? "Subscription usage may exceed a threshold before interruption takes effect. Missing usage invalidates the evidence." : "Prices are your frozen assumptions, not a provider invoice. Missing usage retains the full reservation. A provider exceeding its bound stops further calls."} Interrupted calls are recorded as unknown and are not resubmitted automatically.</p>
    </> : null}
  </fieldset>;
}
