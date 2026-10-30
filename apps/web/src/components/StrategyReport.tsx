"use client";

import { useEffect, useId, useState } from "react";
import { evidenceLabel, researchRequest, type EvidenceReport, type ReplayArtifact, type RunSummary } from "@/lib/research-api";
import { PairedEventOutcomes } from "./PairedEventOutcomes";

const percentage = (value: number | null | undefined) => value == null ? "Undefined" : value !== 0 && Math.abs(value) < 0.000001 ? `${value < 0 ? "−" : "+"}<0.0001%` : `${(value * 100).toFixed(value !== 0 && Math.abs(value) < 0.00005 ? 4 : 2)}%`;
const money = (value: string | number) => Number(value).toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: Number(value) !== 0 && Math.abs(Number(value)) < .01 ? 6 : 2 });
const label = (value: string) => value === "equity_reference" ? "Equity reference" : value === "fixed_basket" ? "Fixed basket" : value === "double_cost" ? "Double costs" : value === "base" ? "Base costs" : evidenceLabel(value);

export function StrategyReport({ experimentId, report }: { experimentId: string; report: EvidenceReport }) {
  const [chosen, setChosen] = useState<RunSummary | null>(null);
  const [paired,setPaired] = useState<NonNullable<EvidenceReport["arm_comparisons"]>[number]|null>(null);
  const variant = (version: string) => `Variant ${report.assessments.findIndex((a) => a.version_id === version) + 1}`;
  const selectedControl = chosen ? report.runs.find((r) => r.version_id === chosen.version_id && r.scenario === chosen.scenario && r.control === "fixed_basket") : undefined;
  return <section className="strategy-report" aria-label="Research evidence report">
    <p><span className="strategy-badge">{evidenceLabel(report.snapshot_kind)}</span> <span className="strategy-badge">{report.engine_build.startsWith("lean-v1-") ? "LEAN simulated execution" : "Local replay"}</span> {report.evaluation_start} to {report.evaluation_end}. {report.inspected_family_trials} family trials inspected; frozen ceiling {report.family_trial_ceiling}.</p>
    {report.equity_reference ? <p>Equity reference: {report.equity_reference.instrument.symbol}, initially {percentage(Number(report.equity_reference.initial_allocation_fraction))} invested; the remainder stays in cash. {report.equity_reference.rationale} This comparison provides market context; differences in return are not risk-adjusted alpha.</p> : <p>No equity-market reference was frozen in this plan. This run cannot establish complete paper-review evidence.</p>}
    {report.arm_comparisons?.length ? <>
      <h4>What each filter adds</h4><p>Compare the numeric-quality arm with guidance alone, then the evidence arm with numeric quality. Different cash exposure remains visible; exclusion does not increase the other allocations.</p>
      <div className="strategy-table-scroll" role="region" aria-label="Incremental arm comparison" tabIndex={0}><table className="strategy-table"><caption>Incremental returns after trading costs and recurring extraction charges</caption><thead><tr><th>Comparison</th><th>Scenario</th><th>Trading excess</th><th>Extra extraction cost</th><th>Excess after extraction</th><th>Exposure difference</th><th>Entered clusters</th></tr></thead><tbody>{report.arm_comparisons.map((arm) => <tr key={`${arm.challenger_version_id}-${arm.scenario}`}>
        <th scope="row">{variant(arm.challenger_version_id)} vs {variant(arm.control_version_id)}</th><td>{label(arm.scenario)}</td><td>{percentage(arm.comparison.net_excess_return_fraction)}</td><td>{money(Number(arm.challenger_extraction_cost_usd)-Number(arm.control_extraction_cost_usd))}</td><td>{percentage(arm.excess_after_extraction_cost_fraction)}</td><td>{percentage(arm.comparison.exposure_difference_fraction)}</td><td>{arm.entered_event_clusters}</td>
      </tr>)}</tbody></table></div>
      <details><summary>Uncertainty and extraction costs</summary>{report.arm_comparisons.map((arm) => <p key={`${arm.challenger_version_id}-${arm.scenario}`}>{variant(arm.challenger_version_id)} vs {variant(arm.control_version_id)}, {label(arm.scenario)}: daily excess interval {percentage(arm.comparison.mean_daily_excess_lower)} to {percentage(arm.comparison.mean_daily_excess_upper)}. {arm.comparison.uncertainty} {arm.cost_note}</p>)}</details>
      <div className="strategy-actions">{report.arm_comparisons.map(arm=>arm.paired_events?<button type="button" className="secondary-button compact" key={`${arm.challenger_version_id}-${arm.scenario}`} onClick={()=>setPaired(arm)}>Inspect paired events: {variant(arm.challenger_version_id)} vs {variant(arm.control_version_id)} · {label(arm.scenario)}</button>:null)}</div>
      {paired?.paired_events?<PairedEventOutcomes key={paired.paired_events.artifact_hash} experimentId={experimentId} summary={paired.paired_events} title={`${variant(paired.challenger_version_id)} vs ${variant(paired.control_version_id)} · ${label(paired.scenario)}`}/>:null}
    </> : null}
    {Object.entries(report.classification_checks ?? {}).map(([version, result]) => <details key={version}><summary>{variant(version)} · Human-labelled evidence checks</summary>
      <p>{result.correct} of {result.labels} labels correct; {result.completed} responses completed, {result.invalid} invalid. Accuracy {percentage(result.accuracy)}; lower bound {percentage(result.accuracy_lower_bound)}. {result.method}</p>
      <div className="strategy-table-scroll"><table className="strategy-table"><caption>Human label (rows) against validated model response (columns)</caption><thead><tr><th>Human label</th>{["clean", "exclude", "unknown", "invalid", "missing"].map((key) => <th key={key}>{label(key)}</th>)}</tr></thead><tbody>{Object.entries(result.confusion).map(([expected, counts]) => <tr key={expected}><th scope="row">{label(expected)}</th>{["clean", "exclude", "unknown", "invalid", "missing"].map((key) => <td key={key}>{counts[key]}</td>)}</tr>)}</tbody></table></div>
    </details>)}
    <div className="strategy-table-scroll" role="region" aria-label="Scenario comparison" tabIndex={0}>
      <table className="strategy-table"><caption>After-cost returns, exposure and execution outcomes</caption><thead><tr><th scope="col">Run</th><th scope="col">Return</th><th scope="col">Excess vs basket</th><th scope="col">Difference vs equity</th><th scope="col">Drawdown</th><th scope="col">Exposure</th><th scope="col">Fees</th><th scope="col">Fills</th><th scope="col">Details</th></tr></thead><tbody>
        {report.runs.map((run, index) => <tr key={`${run.version_id}-${run.scenario}-${run.control}`}>
          <th scope="row">{variant(run.version_id)} · {label(run.scenario)} · {label(run.control)}</th>
          <td>{percentage(run.metrics.total_return_fraction)}</td><td>{run.comparison ? percentage(run.comparison.net_excess_return_fraction) : "Reference"}</td>
          <td>{run.equity_comparison ? percentage(run.equity_comparison.net_excess_return_fraction) : "—"}</td>
          <td>{percentage(run.metrics.max_drawdown_fraction)}</td><td>{percentage(run.metrics.mean_exposure_fraction)}</td><td>{money(run.metrics.fees_usd)}</td><td>{run.metrics.fills}</td>
          <td><button type="button" className="secondary-button compact" aria-label={`Inspect run ${index+1}: ${variant(run.version_id)}, ${label(run.scenario)}, ${label(run.control)}`} onClick={() => setChosen(run)}>Inspect</button></td>
        </tr>)}
      </tbody></table>
    </div>
    {chosen ? <RunDetail key={chosen.artifact_hash} experimentId={experimentId} summary={chosen} control={selectedControl} title={`${variant(chosen.version_id)} · ${label(chosen.scenario)} · ${label(chosen.control)}`} /> : <p>Select a run to inspect its equity, exact fills and missing inputs.</p>}
    {report.assessments.map((assessment) => <details key={assessment.version_id}><summary>{variant(assessment.version_id)} — {evidenceLabel(assessment.evidence_status)}</summary><ul className="strategy-checks">{assessment.checks.map((check) => <li key={check.name}><strong>{check.passed ? "Met" : "Not met"}: {evidenceLabel(check.name)}</strong><p>{check.detail}</p></li>)}</ul></details>)}
    <details><summary>Assumptions and limitations</summary><ul>{report.limitations.map((item) => <li key={item}>{item}</li>)}</ul></details>
  </section>;
}

function RunDetail({ experimentId, summary, control, title }: { experimentId: string; summary: RunSummary; control?: RunSummary; title: string }) {
  const [data, setData] = useState<ReplayArtifact | null>(null);
  const [reference, setReference] = useState<ReplayArtifact | null>(null);
  const [error, setError] = useState("");
  const controlHash = control?.artifact_hash;
  useEffect(() => {
    const controller = new AbortController();
    const load = (digest: string) => researchRequest<ReplayArtifact>(`/experiments/${experimentId}/artifacts/${digest}`, undefined, "GET", controller.signal);
    Promise.all([load(summary.artifact_hash), controlHash && controlHash !== summary.artifact_hash ? load(controlHash) : Promise.resolve(null)])
      .then(([next, baseline]) => { if (!controller.signal.aborted) { setData(next); setReference(baseline); } })
      .catch((e) => { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : "Evidence artifact unavailable"); });
    return () => controller.abort();
  }, [experimentId, summary.artifact_hash, controlHash]);
  return <section className="strategy-run-detail" aria-label={title}>
    <h4>{title}</h4>
    {error ? <p className="strategy-error" role="alert">{error}</p> : null}
    <dl className="strategy-facts">
      <div><dt>Observed sessions</dt><dd>{summary.metrics.observations}</dd></div><div><dt>Slippage cost</dt><dd>{money(summary.metrics.slippage_usd)}</dd></div>
      <div><dt>Sharpe ratio</dt><dd>{summary.metrics.sharpe_ratio?.toFixed(2) ?? "Undefined"}</dd></div><div><dt>Decisions without targets</dt><dd>{summary.missing_signal_decisions}</dd></div>
      <div><dt>Unfilled orders</dt><dd>{summary.unfilled_orders}</dd></div><div><dt>Sessions with stale valuations</dt><dd>{summary.metrics.stale_valuation_sessions}</dd></div>
      <div><dt>Sessions outside a risk limit</dt><dd>{summary.risk_breach_sessions}</dd></div><div><dt>Annualized volatility</dt><dd>{percentage(summary.metrics.annualized_volatility_fraction)}</dd></div>
      <div><dt>Longest underwater spell (sessions)</dt><dd>{summary.metrics.max_underwater_sessions ?? "Not recorded"}</dd></div><div><dt>Still underwater at end (sessions)</dt><dd>{summary.metrics.current_underwater_sessions ?? "Not recorded"}</dd></div>
      <div><dt>Worst session return</dt><dd>{summary.metrics.worst_session_return_fraction == null ? "Not recorded" : percentage(summary.metrics.worst_session_return_fraction)}</dd></div><div><dt>Mean of worst 5% of sessions</dt><dd>{summary.metrics.mean_worst_five_percent_fraction == null ? "Unavailable" : percentage(summary.metrics.mean_worst_five_percent_fraction)}</dd></div>
      <div><dt>Gross traded notional</dt><dd>{summary.metrics.gross_traded_notional_usd == null ? "Not recorded" : money(summary.metrics.gross_traded_notional_usd)}</dd></div><div><dt>Gross turnover / opening capital</dt><dd>{summary.metrics.gross_turnover_fraction == null ? "Not recorded" : percentage(summary.metrics.gross_turnover_fraction)}</dd></div>
    </dl>
    <p>Underwater spells count consecutive observed sessions below the previous equity high, including opening capital; a recovery session ends the spell. An unfinished spell is censored at the evaluation end. Tail loss is the mean of the worst rounded-up 5% of session returns, requires at least 20 sessions and is descriptive, not a future loss limit. Gross turnover adds absolute buy and sell fill notionals and divides by opening capital, without halving or annualizing; it excludes corporate actions and fees.</p>
    {Object.entries(summary.metrics.undefined).map(([metric, reason]) => <p key={metric}>{label(metric)}: {reason}.</p>)}
    {summary.comparison ? <p>Mean daily excess interval: {percentage(summary.comparison.mean_daily_excess_lower)} to {percentage(summary.comparison.mean_daily_excess_upper)}. {summary.comparison.uncertainty} Exposure difference: {percentage(summary.comparison.exposure_difference_fraction)}.</p> : null}
    {summary.equity_comparison ? <p>Equity reference: mean daily return difference interval {percentage(summary.equity_comparison.mean_daily_excess_lower)} to {percentage(summary.equity_comparison.mean_daily_excess_upper)}; exposure difference {percentage(summary.equity_comparison.exposure_difference_fraction)}. {summary.equity_comparison.uncertainty}</p> : null}
    {!data && !error ? <p role="status">Verifying and loading the immutable run artifact…</p> : null}
    {data ? <>
      <EquityChart data={data} reference={reference} />
      <PortfolioRiskHistory data={data} />
      {data.venue_equity?.length ? <details><summary>LEAN account verification ({data.venue_equity.length} sessions)</summary>
        <p>Native account cash, equity, receivables, quantities, fees and cost basis were checked against the research ledger at every session close. These are simulated execution records.</p>
        {data.venue_receipts?.length ? <div className="strategy-table-scroll"><table className="strategy-table"><caption>Latest 50 native LEAN order receipts</caption><thead><tr><th>Order</th><th>Instrument</th><th>Execution time</th><th>Shares</th><th>Price</th><th>Fee</th><th>Cash after fill</th></tr></thead><tbody>{data.venue_receipts.slice(-50).map((receipt) => <tr key={receipt.order_id}><td>{receipt.order_id}</td><td>{receipt.instrument_id}</td><td>{receipt.at}</td><td>{receipt.quantity}</td><td>{money(receipt.price_usd)}</td><td>{money(receipt.fee_usd)}</td><td>{money(receipt.cash_usd)}</td></tr>)}</tbody></table></div> : <p>No native orders filled in this path.</p>}
        <details><summary>Native account snapshots</summary><pre className="strategy-json">{JSON.stringify(data.venue_equity, null, 2)}</pre></details>
      </details> : null}
      {data.guidance_events?.length ? <details><summary>Guidance decisions and abstentions ({data.guidance_events.length})</summary><div className="strategy-table-scroll"><table className="strategy-table"><caption>Latest 100 event-state changes; the full history stays in the artifact.</caption><thead><tr><th>Event</th><th>Available decision time</th><th>Result</th><th>Why</th><th>Cash-quality evidence</th></tr></thead><tbody>{data.guidance_events.slice(-100).map((event, index) => <tr key={`${event.notice_id}-${event.at}-${index}`}>
        <th scope="row">{event.notice_id}</th><td>{event.at}</td><td>{label(event.status)}{event.evidence_verdict ? ` · ${label(event.evidence_verdict)}` : ""}</td><td>{event.reason}</td><td>{event.quality ? `${label(event.quality.status)}: ${event.quality.reason} Current cash margin ${percentage(event.quality.current_cash_margin == null ? null : Number(event.quality.current_cash_margin))}; prior ${percentage(event.quality.prior_cash_margin == null ? null : Number(event.quality.prior_cash_margin))}.` : "Not required or not yet evaluated"}</td>
      </tr>)}</tbody></table></div></details> : null}
      <details><summary>Equity and cash ledger ({data.equity.length} sessions)</summary><div className="strategy-table-scroll"><table className="strategy-table"><caption>Latest 30 sessions; full history is in the reproducibility artifact</caption><thead><tr><th>Date</th><th>Equity</th><th>Cash</th><th>Receivables</th><th>Positions</th></tr></thead><tbody>{data.equity.slice(-30).map((point) => <tr key={point.at}><td>{point.at.slice(0, 10)}</td><td>{money(point.equity_usd)}</td><td>{money(point.cash_usd)}</td><td>{money(point.receivables_usd)}</td><td>{Object.entries(point.quantities).filter(([, q]) => q).map(([id, q]) => `${id}: ${q}`).join(", ") || "Cash only"}</td></tr>)}</tbody></table></div></details>
      <details><summary>Orders filled ({data.fills.length})</summary>{data.fills.length ? <div className="strategy-table-scroll"><table className="strategy-table"><caption>Latest 50 fills. Execution time and data arrival time are separate.</caption><thead><tr><th>Instrument</th><th>Signal time</th><th>Execution time</th><th>Observed time</th><th>Shares</th><th>Price</th><th>Fee</th></tr></thead><tbody>{data.fills.slice(-50).map((fill) => <tr key={fill.fill_id}><td>{fill.instrument_id}</td><td>{fill.signal_at}</td><td>{fill.executed_at}</td><td>{fill.observed_at}</td><td>{fill.quantity}</td><td>{money(fill.price_usd)}</td><td>{money(fill.fee_usd)}</td></tr>)}</tbody></table></div> : <p>No orders filled. This is a valid research outcome.</p>}</details>
      <details><summary>Accounting and execution events ({data.events.length})</summary><ul>{data.events.slice(-100).map((event, index) => <li key={`${event.at}-${index}`}>{event.at.slice(0, 10)} · {label(event.kind)} · {event.detail}</li>)}</ul></details>
      <details><summary>Full immutable run artifact</summary><pre className="strategy-json">{JSON.stringify(data, null, 2)}</pre></details>
    </> : null}
  </section>;
}

function PortfolioRiskHistory({ data }: { data: ReplayArtifact }) {
  const observations = (data.decisions ?? []).filter((item) => item.decision.portfolio_risk);
  const [selected, setSelected] = useState("");
  const observation = observations.find((item) => item.decision_id === selected) ?? observations.at(-1);
  const risk = observation?.decision.portfolio_risk;
  if (!observation || !risk) return <p>No covariance risk estimate was recorded for this path. Estimates are available for newly run trend target decisions.</p>;
  return <details className="strategy-portfolio-risk"><summary>Portfolio risk at proposed weights ({observations.length} decisions)</summary>
    <label>Decision time <select value={observation.decision_id} onChange={(event) => setSelected(event.target.value)}>
      {observations.map((item) => <option key={item.decision_id} value={item.decision_id}>{item.at}</option>)}
    </select></label>
    <p>Uses {risk.observations} aligned returns from {risk.first_return_session} through {risk.last_return_session}, annualized with {risk.annualization_sessions} sessions. These are proposed weights before share rounding and fills.</p>
    <dl className="strategy-facts">
      <div><dt>Volatility including correlations</dt><dd>{percentage(risk.annualized_volatility_fraction)}</dd></div>
      <div><dt>If holdings were uncorrelated</dt><dd>{percentage(risk.annualized_volatility_assuming_independence_fraction)}</dd></div>
      <div><dt>Proposed capital invested</dt><dd>{percentage(Number(risk.invested_fraction))}</dd></div>
      <div><dt>Diversification ratio</dt><dd>{risk.diversification_ratio?.toFixed(2) ?? "Undefined"}</dd></div>
    </dl>
    <p>Correlation affects portfolio risk even when individual volatilities match. Negative contributions indicate a hedge within this sample; contributions can exceed 100%. Inverse-volatility sizing does not enforce a portfolio volatility target.</p>
    <div className="strategy-table-scroll"><table className="strategy-table"><caption>Contributions to proposed portfolio risk</caption><thead><tr><th>Instrument</th><th>Capital weight</th><th>Standalone volatility</th><th>Volatility contribution</th><th>Share of variance</th></tr></thead><tbody>
      {Object.entries(risk.contributions).map(([instrument, contribution]) => <tr key={instrument}><th scope="row">{instrument}</th><td>{percentage(Number(contribution.weight))}</td><td>{percentage(contribution.annualized_standalone_volatility_fraction)}</td><td>{percentage(contribution.annualized_volatility_contribution_fraction)}</td><td>{percentage(contribution.share_of_portfolio_variance)}</td></tr>)}
    </tbody></table></div>
    <p>Group shares of variance: {Object.entries(risk.group_variance_shares).map(([group, value]) => `${group}: ${percentage(value)}`).join(" · ")}.</p>
    <details><summary>Risk estimate method and limitations</summary><ul>{risk.limitations.map((item) => <li key={item}>{item}</li>)}</ul><p>Method: {risk.method}. Input fingerprint: <code>{risk.input_hash}</code>.</p></details>
  </details>;
}

function EquityChart({ data, reference }: { data: ReplayArtifact; reference: ReplayArtifact | null }) {
  const titleId = useId();
  if (!data.equity.length) return <p>No equity observations available.</p>;
  const values = [Number(data.initial_capital_usd), ...data.equity.map((p) => Number(p.equity_usd)), ...(reference?.equity.map((p) => Number(p.equity_usd)) ?? [])];
  const low = Math.min(...values), high = Math.max(...values), span = high - low || 1;
  const path = (run: ReplayArtifact) => [Number(run.initial_capital_usd), ...run.equity.map((p) => Number(p.equity_usd))].map((value, i, points) => `${i ? "L" : "M"}${60 + i / Math.max(points.length-1, 1) * 610},${190 - (value-low) / span * 150}`).join(" ");
  return <figure className="strategy-equity-chart"><svg viewBox="0 0 700 240" role="img" aria-labelledby={titleId}>
    <title id={titleId}>Account equity after execution costs. Selected run {money(data.initial_capital_usd)} to {money(data.equity.at(-1)!.equity_usd)}{reference ? `; fixed basket ends at ${money(reference.equity.at(-1)!.equity_usd)}` : ""}.</title>
    <line x1="60" y1="190" x2="670" y2="190" stroke="var(--panel-border-strong)" />
    <text x="60" y="25">{money(high)}</text><text x="60" y="215">{money(low)}</text>
    <text x="60" y="237">{data.equity[0].at.slice(0, 10)}</text><text x="670" y="237" textAnchor="end">{data.equity.at(-1)!.at.slice(0, 10)}</text>
    {reference ? <path d={path(reference)} fill="none" stroke="var(--text-secondary)" strokeWidth="2" strokeDasharray="6 4" /> : null}
    <path d={path(data)} fill="none" stroke="var(--accent-cyan)" strokeWidth="2.5" />
  </svg><figcaption>Selected run: solid line{reference ? " · Fixed basket: dashed line" : ""}. Equity includes receivables; the cash ledger identifies spendable funds.</figcaption></figure>;
}
