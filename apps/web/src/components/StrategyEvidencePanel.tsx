"use client";

import { evidenceLabel, type Experiment } from "@/lib/research-api";
import { StrategyReport } from "@/components/StrategyReport";
import { StrategyModelCalls } from "@/components/StrategyModelCalls";

export function StrategyEvidencePanel({ experiment, onCancel, busy, onRequestReview }: { experiment: Experiment; onCancel: () => void; busy: boolean; onRequestReview?: (selection: { version_id: string; experiment_id: string }) => void }) {
  const result = experiment.result;
  return (
    <article className="strategy-card" aria-label="Experiment evidence">
      <header className="strategy-card-heading">
        <h3>{new Date(experiment.created_at).toLocaleString()}</h3>
        <span className="strategy-badge">{evidenceLabel(result?.evidence_status ?? experiment.state)}</span>
      </header>
      <p>{result?.explanation ?? experiment.failure_reason ?? (experiment.state === "queued" ? "Waiting for a research worker. No evaluation results yet." : experiment.state === "running" ? "Evaluation in progress." : "This attempt remains in the research history.")}</p>
      <dl className="strategy-facts">
        <div><dt>Evaluation period</dt><dd>{evidenceLabel(experiment.evaluation)}</dd></div>
        <div><dt>Trials charged</dt><dd>{experiment.trial_count}</dd></div>
        <div><dt>Worker attempts</dt><dd>{experiment.attempts}</dd></div>
        <div><dt>Recorded research charges</dt><dd>${Number(experiment.cost_usd).toFixed(6)}</dd></div>
      </dl>
      <StrategyModelCalls experiment={experiment} />
      {result?.report?.runs ? <StrategyReport experimentId={experiment.experiment_id} report={result.report} /> : null}
      {result&&onRequestReview?<div className="strategy-actions">{result.report.assessments.map((assessment,index)=><button key={assessment.version_id} type="button" className="secondary-button compact" onClick={()=>onRequestReview({version_id:assessment.version_id,experiment_id:experiment.experiment_id})}>Review variant {index+1} in Quant</button>)}<p>This opens a funding proposal. Fixture, rejected or incomplete evidence cannot activate a deployment.</p></div>:null}
      {result ? <details><summary>Reproducibility records</summary><pre className="strategy-json">{JSON.stringify(result, null, 2)}</pre></details> : null}
      {experiment.state === "queued" || experiment.state === "running" ? <button type="button" className="secondary-button compact" disabled={busy} onClick={onCancel}>Cancel experiment</button> : null}
    </article>
  );
}
