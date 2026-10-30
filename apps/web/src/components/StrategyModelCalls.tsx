"use client";

import { useEffect, useState } from "react";
import { evidenceLabel, researchRequest, type Experiment, type ModelCall, type ModelReceipt } from "@/lib/research-api";

export function StrategyModelCalls({ experiment }: { experiment: Experiment }) {
  const [open, setOpen] = useState(false);
  const [calls, setCalls] = useState<ModelCall[] | null>(null);
  const [error, setError] = useState("");
  const { experiment_id: id, state, cost_usd: cost } = experiment;
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function refresh() {
      try {
        const response = await researchRequest<{ calls: ModelCall[] }>(`/experiments/${id}/model-calls`, undefined, "GET", controller.signal);
        if (!controller.signal.aborted) { setCalls(response.calls); setError(""); }
      } catch (e) { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : "Could not load model attempts"); }
      if (!controller.signal.aborted && (state === "running" || state === "queued")) timer = setTimeout(refresh, 3000);
    }
    void refresh();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [open, id, state, cost]);
  return <details onToggle={(e) => setOpen(e.currentTarget.open)}><summary>Model calls and charges</summary>
    {error ? <p role="alert" className="strategy-error">{error}</p> : null}
    {calls === null ? <p role="status">Loading attempts…</p> : calls.length === 0 ? <p>No new model calls were reserved for this experiment. Preserved dataset evidence, if any, is recorded in the report.</p> : <>
      <p>API charges use the plan’s frozen token prices. Codex subscription attempts record observed usage separately. Unknown outcomes are not retried automatically.</p>
      {calls.map((call, index) => <ModelAttempt key={call.call_id} call={call} index={index + 1} experimentId={id} />)}
    </>}
  </details>;
}

function ModelAttempt({ call, index, experimentId }: { call: ModelCall; index: number; experimentId: string }) {
  const [open, setOpen] = useState(false);
  const [receipt, setReceipt] = useState<ModelReceipt | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!open || !call.output_artifact) return;
    const controller = new AbortController();
    researchRequest<ModelReceipt>(`/experiments/${experimentId}/model-calls/${call.call_id}/evidence`, undefined, "GET", controller.signal)
      .then((result) => { if (!controller.signal.aborted) { setReceipt(result); setError(""); } })
      .catch((e) => { if (!controller.signal.aborted) setError(e.message); });
    return () => controller.abort();
  }, [open, experimentId, call.call_id, call.output_artifact]);
  return <section className="strategy-run-detail" aria-label={`Model attempt ${index}`}>
    <p><strong>Attempt {index} · {call.request.model.model_id}</strong> <span className="strategy-badge">{evidenceLabel(call.state)}</span></p>
    <dl className="strategy-facts">
      <div><dt>Requested provider</dt><dd>{call.request.model.provider_id}</dd></div>
      <div><dt>Source cutoff</dt><dd>{new Date(call.input_as_of).toLocaleString()}</dd></div>
      {call.request.policy.billing_mode === "codex_subscription" ? <div><dt>Usage mode</dt><dd>Codex subscription · no API invoice</dd></div> : <><div><dt>Initial reservation</dt><dd>${Number(call.reserved_cost_usd).toFixed(6)}</dd></div>
      <div><dt>Recorded charge</dt><dd>${Number(call.charged_cost_usd).toFixed(6)}</dd></div></>}
    </dl>
    {call.failure_reason ? <p>{call.failure_reason}</p> : null}
    {call.output_artifact ? <details onToggle={(e) => setOpen(e.currentTarget.open)}><summary>Inspect model receipt · attempt {index}</summary>
      {error ? <p className="strategy-error" role="alert">{error}</p> : null}
      {receipt ? <>
        <p>Reported model: {receipt.actual_model_id} · {receipt.actual_provider_id}. Input tokens: {receipt.input_tokens ?? "unavailable"}; output tokens: {receipt.output_tokens ?? "unavailable"}. Cost basis: {evidenceLabel(receipt.cost_basis)}.</p>
        <p>{evidenceLabel(receipt.availability.mode)} availability: {new Date(receipt.availability.available_at).toLocaleString()}.</p>
        {receipt.validation_errors.length ? <ul>{receipt.validation_errors.map((message, i) => <li key={i}>{message}</li>)}</ul> : <p>Response passed the evidence checks.</p>}
        <pre className="strategy-json">{JSON.stringify(receipt, null, 2)}</pre>
      </> : <p role="status">Loading preserved receipt…</p>}
    </details> : <p>{call.state === "unknown" ? "No receipt was recovered. Provider completion and usage remain unknown." : "No completed receipt yet."}</p>}
  </section>;
}
