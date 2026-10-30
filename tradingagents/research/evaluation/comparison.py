from __future__ import annotations

from datetime import date
from decimal import Decimal
from math import ceil
from random import Random
from statistics import mean
from typing import Literal

from pydantic import Field

from tradingagents.research.contracts import (
    Contract, Digest, ExperimentResult, GuidanceRules, Identifier, ResearchPlanInput,
    SnapshotManifest, StrategySpec, EquityReference, RiskPolicy, TrendRules, content_hash,
)
from tradingagents.research.data.store import ArtifactStore
from tradingagents.research.data.contracts import DatasetBundle, EvidenceObservation
from tradingagents.research.engines.base import Engine, EngineUnavailable, ReplayRequest, ReplayResult
from tradingagents.research.metrics import PerformanceMetrics, daily_returns, performance
from tradingagents.research.evaluation.cohorts import guidance_cohorts
from tradingagents.research.evaluation.labels import LabelEvaluation, evaluate_labels
from tradingagents.research.evaluation.paired_events import PairedEventSummary, paired_events, save_paired_events


class Comparison(Contract):
    net_excess_return_fraction: float | None
    exposure_difference_fraction: float | None
    mean_daily_excess_fraction: float | None
    mean_daily_excess_lower: float | None
    mean_daily_excess_upper: float | None
    uncertainty: str
    block_sessions: int
    inspected_family_trials: int
    family_trial_ceiling: int


class RunSummary(Contract):
    version_id: Identifier
    scenario: Identifier
    control: Literal["strategy", "fixed_basket", "cash", "equity_reference"]
    artifact_hash: Digest
    metrics: PerformanceMetrics
    comparison: Comparison | None = None
    equity_comparison: Comparison | None = None
    decisions: int
    missing_signal_decisions: int
    unfilled_orders: int
    risk_breach_sessions: int


class EvidenceCheck(Contract):
    name: str
    passed: bool
    detail: str


class VersionAssessment(Contract):
    version_id: Identifier
    evidence_status: Literal["fixture_only", "insufficient_evidence", "rejected", "eligible_for_paper_review"]
    checks: list[EvidenceCheck]


class ArmComparison(Contract):
    challenger_version_id: Identifier
    control_version_id: Identifier
    scenario: Identifier
    comparison: Comparison
    challenger_extraction_cost_usd: Decimal
    control_extraction_cost_usd: Decimal
    excess_after_extraction_cost_fraction: float | None
    entered_event_clusters: int
    paired_events: PairedEventSummary | None = None
    cost_note: str = "Preserved model-call costs for the evaluated source events, including unused/failed attempts; subtracted once from incremental period P&L. Replay does not invoke or rebill a model. Hardware/operator costs are excluded."


class EvidenceReport(Contract):
    schema_version: Literal[1] = 1
    engine_build: Identifier
    snapshot_manifest_hash: Digest
    snapshot_kind: Literal["fixture", "historical", "prospective"]
    evaluation: Literal["development", "validation", "holdout"]
    evaluation_start: date
    evaluation_end: date
    embargo_sessions: int
    inspected_family_trials: int
    family_trial_ceiling: int
    runs: list[RunSummary] = Field(min_length=1)
    assessments: list[VersionAssessment] = Field(min_length=1)
    limitations: list[str]
    arm_comparisons: list[ArmComparison] = Field(default_factory=list)
    classification_checks: dict[str, LabelEvaluation] = Field(default_factory=dict)
    evaluated_dataset_hash: Digest | None = None
    evidence_artifacts: list[Digest] = Field(default_factory=list)
    model_call_ids: list[Identifier] = Field(default_factory=list)
    model_call_costs: dict[Digest, Decimal] = Field(default_factory=dict)
    equity_reference: EquityReference | None = None


def equity_reference_request(request: ReplayRequest, reference: EquityReference) -> ReplayRequest:
    # Independent benchmark capital treatment, never a strategy allocation or
    # a signal from the equity reference. Preserve dates, timing and costs.
    spec = StrategySpec(universe=[reference.instrument],
        rules=TrendRules(kind="diversified_trend", decision_latency_seconds=request.spec.rules.decision_latency_seconds),
        risk=RiskPolicy(max_position_fraction=1, max_group_fraction=1, cash_reserve_fraction=0,
            max_turnover_fraction=1, max_drawdown_fraction=Decimal(".999999")))
    return request.model_copy(update={"spec": spec, "control": "equity_reference", "reference_allocation_fraction": reference.initial_allocation_fraction})


def compare(strategy: ReplayResult, control: ReplayResult, *, trials: int, trial_ceiling: int, block_sessions: int = 5) -> Comparison:
    if [p.at for p in strategy.equity] != [p.at for p in control.equity]:
        raise ValueError("comparison must use identical investable sessions")
    left, right = daily_returns(strategy), daily_returns(control)
    excess = [a-b for a, b in zip(left, right)]
    metrics_left, metrics_right = performance(strategy), performance(control)
    lower = upper = None
    explanation = "Insufficient independent blocks for an uncertainty interval (need 20 complete blocks)"
    blocks = [excess[i:i+block_sessions] for i in range(0, len(excess)-block_sessions+1, block_sessions)]
    if len(blocks) >= 20:
        # Non-overlapping time blocks preserve dependence inside each block.
        # The ceiling is frozen before testing; adding failures/retries cannot
        # retroactively lower the multiple-testing penalty.
        samples = 1999
        tail = .025 / max(trial_ceiling, 1)
        if tail * (samples + 1) >= 1:
            rng = Random(0)
            block_means = [mean(b) for b in blocks]
            distribution = sorted(mean(rng.choices(block_means, k=len(block_means))) for _ in range(samples))
            lower = distribution[max(0, int(tail * samples)-1)]
            upper = distribution[min(samples-1, ceil((1-tail)*samples))]
            explanation = "Deterministic percentile block bootstrap; nominal 95% family interval with Bonferroni trial-ceiling adjustment. Assumes comparable blocks; dependence beyond the block length and structural breaks are not covered. Incomplete final block excluded."
        else:
            explanation = "Frozen trial ceiling exceeds bootstrap tail resolution; no significance claim"
    return Comparison(
        net_excess_return_fraction=(metrics_left.total_return_fraction - metrics_right.total_return_fraction) if left else None,
        exposure_difference_fraction=(metrics_left.mean_exposure_fraction - metrics_right.mean_exposure_fraction) if left else None,
        mean_daily_excess_fraction=mean(excess) if excess else None,
        mean_daily_excess_lower=lower, mean_daily_excess_upper=upper, uncertainty=explanation,
        block_sessions=block_sessions, inspected_family_trials=trials, family_trial_ceiling=trial_ceiling,
    )


def evaluation_window(plan: ResearchPlanInput, dataset, evaluation: str) -> tuple[date, date]:
    split = plan.split
    start, end, previous_end = {
        "development": (split.train_start, split.train_end, None),
        "validation": (split.validation_start, split.validation_end, split.train_end),
        "holdout": (split.holdout_start, split.holdout_end, split.validation_end),
    }[evaluation]
    if previous_end is not None and split.embargo_sessions:
        after = [s.date for s in dataset.sessions if s.date > previous_end]
        if len(after) <= split.embargo_sessions:
            raise EngineUnavailable("Dataset has no sessions after the frozen embargo")
        start = max(start, after[split.embargo_sessions])
    if start > end:
        raise EngineUnavailable("The embargo consumes the evaluation period")
    return start, end


def evaluate(*, engine: Engine, plan: ResearchPlanInput, manifest: SnapshotManifest,
             specs: dict[str, StrategySpec], evaluation: str, inspected_trials: int,
             store: ArtifactStore, operating_cost: Decimal = Decimal(0), evidence_artifacts: list[str] | None = None,
             model_call_ids: list[str] | None = None, model_call_costs: dict[str, Decimal] | None = None) -> ExperimentResult:
    if set(specs) != set(plan.version_ids):
        raise ValueError("The engine must evaluate every frozen variant")
    cohorts = guidance_cohorts(specs)
    dataset = store.dataset(manifest)
    imported_evidence = list(dataset.evidence)
    supplemental = [EvidenceObservation.model_validate(store.json(digest)) for digest in (evidence_artifacts or [])]
    if supplemental:
        dataset = DatasetBundle.model_validate({**dataset.model_dump(), "evidence": [*dataset.evidence, *supplemental]})
    start, end = evaluation_window(plan, dataset, evaluation)
    summaries, assessments, limitations = [], [], []
    artifacts, strategy_runs, classifications = {}, {}, {}
    evaluated_dataset_hash = store.put_json(dataset) if supplemental else None
    if evaluated_dataset_hash:
        artifacts["evaluated_dataset"] = evaluated_dataset_hash
    for index, digest in enumerate(evidence_artifacts or []):
        artifacts[f"model_evidence_{index+1}"] = digest
    notices = {n.notice_id: n for n in dataset.guidance_notices}
    model_costs = {}
    for version_id, spec in specs.items():
        model_costs[version_id] = sum((e.cost_usd for e in imported_evidence if e.model == spec.model
            and start <= notices[e.notice_id].availability.available_at.date() <= end
            and e.availability.available_at.date() <= end), Decimal(0)) + (model_call_costs or {}).get(content_hash(spec.model), Decimal(0)) if spec.model else Decimal(0)
        if spec.model:
            classifications[version_id] = evaluate_labels(dataset, spec.model, start, end)
    for version_id in plan.version_ids:
        spec = specs[version_id]
        variant_summaries = []
        reference_summaries = []
        for scenario in plan.scenarios:
            request = ReplayRequest(dataset=dataset, spec=spec, start=start, end=end,
                initial_capital_usd=plan.initial_capital_usd, cash_annual_yield_fraction=plan.cash_annual_yield_fraction, scenario=scenario)
            runs = {control: engine.run(request.model_copy(update={"control": control})) for control in ("cash", "fixed_basket", "strategy")}
            if plan.equity_reference:
                runs["equity_reference"] = engine.run(equity_reference_request(request, plan.equity_reference))
            cash_returns = daily_returns(runs["cash"])
            for control, result in runs.items():
                artifact = store.put_json(result)
                # Short artifact names remain valid even for long external IDs.
                artifacts[f"run_{len(summaries)+1}"] = artifact
                summary = RunSummary(version_id=version_id, scenario=scenario.name, control=control,
                    artifact_hash=artifact, metrics=performance(result, cash_returns=cash_returns),
                    comparison=compare(result, runs["fixed_basket"], trials=inspected_trials, trial_ceiling=plan.max_trials,
                        block_sessions=max(5, spec.rules.hold_sessions + scenario.execution_delay_sessions) if isinstance(spec.rules, GuidanceRules) else 5) if control == "strategy" else None,
                    equity_comparison=compare(result, runs["equity_reference"], trials=inspected_trials, trial_ceiling=plan.max_trials,
                        block_sessions=max(5, spec.rules.hold_sessions + scenario.execution_delay_sessions) if isinstance(spec.rules, GuidanceRules) else 5) if control == "strategy" and plan.equity_reference else None,
                    decisions=len(result.decisions), missing_signal_decisions=sum(d.decision.status != "targets" for d in result.decisions),
                    unfilled_orders=sum(e.kind == "unfilled" for e in result.events), risk_breach_sessions=sum(bool(p.risk_breaches) for p in result.equity))
                summaries.append(summary)
                if control == "equity_reference":
                    reference_summaries.append(summary)
                if control == "strategy":
                    variant_summaries.append(summary)
                    strategy_runs[version_id, scenario.name] = result
                for limitation in result.limitations:
                    if limitation not in limitations:
                        limitations.append(limitation)
        base = next(s for s in variant_summaries if s.scenario == "base")
        checks = [
            EvidenceCheck(name="genuine_data", passed=manifest.evidence_kind != "fixture", detail=f"Dataset evidence is {manifest.evidence_kind}"),
            EvidenceCheck(name="held_out", passed=evaluation == "holdout", detail="Paper review requires a consumed, predeclared holdout"),
            EvidenceCheck(name="known_availability", passed=manifest.availability in {"verified_publication", "recorded_receipt"}, detail=f"Availability: {manifest.availability}"),
            EvidenceCheck(name="equity_reference", passed=bool(reference_summaries) and all(s.metrics.fills > 0 and s.metrics.stale_valuation_sessions == 0 and s.missing_signal_decisions == 0 and s.unfilled_orders == 0 for s in reference_summaries), detail="A predeclared equity reference with an executed entry and complete held-position marks is required in every cost scenario. Relative returns are context, not a claim of alpha or a requirement to outperform equities."),
            EvidenceCheck(name="observations", passed=all(s.metrics.observations >= plan.criteria.min_observations for s in variant_summaries), detail=f"At least {plan.criteria.min_observations} evaluated sessions in every scenario"),
            EvidenceCheck(name="coverage", passed=all(s.metrics.stale_valuation_sessions == 0 and (isinstance(spec.rules, GuidanceRules) or s.missing_signal_decisions == 0) and s.decisions > 0 for s in variant_summaries), detail="No stale held-position marks or absent decision schedule; guidance abstentions are retained separately, and event coverage is checked below"),
            EvidenceCheck(name="trades", passed=all(s.metrics.fills > 0 for s in variant_summaries), detail="Cash-only/no-trade outcomes do not establish a tradable edge"),
            EvidenceCheck(name="net_excess", passed=base.comparison.net_excess_return_fraction is not None and base.comparison.net_excess_return_fraction >= float(plan.criteria.min_net_excess_return_fraction), detail=f"Base period return minus fixed-basket control must be at least {plan.criteria.min_net_excess_return_fraction}"),
            EvidenceCheck(name="drawdown", passed=all(s.metrics.max_drawdown_fraction is not None and s.metrics.max_drawdown_fraction <= float(plan.criteria.max_drawdown_fraction) for s in variant_summaries), detail=f"All scenario drawdowns must remain within {plan.criteria.max_drawdown_fraction}"),
            EvidenceCheck(name="stressed_excess", passed=not plan.criteria.require_positive_stressed_excess or all(s.comparison.net_excess_return_fraction is not None and s.comparison.net_excess_return_fraction > 0 for s in variant_summaries if s.scenario != "base"), detail="Positive excess under predeclared cost/delay stresses when required"),
            EvidenceCheck(name="uncertainty", passed=base.comparison.mean_daily_excess_lower is not None and base.comparison.mean_daily_excess_lower > 0, detail=base.comparison.uncertainty),
        ]
        insufficient_names = {"held_out", "known_availability", "observations", "coverage", "trades", "uncertainty", "equity_reference"}
        if manifest.evidence_kind == "fixture":
            status = "fixture_only"
        elif any(not c.passed and c.name in insufficient_names for c in checks):
            status = "insufficient_evidence"
        elif all(c.passed for c in checks):
            status = "eligible_for_paper_review"
        else:
            status = "rejected"
        assessments.append(VersionAssessment(version_id=version_id, evidence_status=status, checks=checks))
    arms = []
    for cohort in cohorts:
        for challenger, control in (("numeric_quality", "guidance_control"), ("astra_challenger", "numeric_quality")):
            left_id, right_id = cohort[challenger], cohort[control]
            for scenario in plan.scenarios:
                left, right = strategy_runs[left_id, scenario.name], strategy_runs[right_id, scenario.name]
                comparison = compare(left, right, trials=inspected_trials, trial_ceiling=plan.max_trials,
                    block_sessions=max(5, specs[left_id].rules.hold_sessions + scenario.execution_delay_sessions))
                decisions = {d.decision_id: d for d in left.decisions}
                entered = {decisions[f.decision_id].entry_notice_ids[f.instrument_id] for f in left.fills if f.quantity > 0}
                clusters = {(notices[n].instrument_id, notices[n].period_start, notices[n].period_end) for n in entered}
                excess = comparison.net_excess_return_fraction
                event_summary, event_rows = paired_events(dataset, specs[left_id], left, right, start=start, end=end)
                paired, event_artifacts = save_paired_events(store, event_summary, event_rows,
                    {"challenger_version_id": left_id, "control_version_id": right_id, "scenario": scenario.name,
                     "initial_capital_usd": str(plan.initial_capital_usd), "snapshot_manifest_hash": content_hash(manifest),
                     "challenger_run_hash": content_hash(left), "control_run_hash": content_hash(right)})
                for digest in event_artifacts:
                    artifacts[f"paired_{len(artifacts)+1}"] = digest
                arms.append(ArmComparison(challenger_version_id=left_id, control_version_id=right_id, scenario=scenario.name,
                    comparison=comparison, challenger_extraction_cost_usd=model_costs[left_id], control_extraction_cost_usd=model_costs[right_id],
                    excess_after_extraction_cost_fraction=excess-float((model_costs[left_id]-model_costs[right_id])/plan.initial_capital_usd) if excess is not None else None,
                    entered_event_clusters=len(clusters), paired_events=paired))
    for assessment in assessments:
        spec = specs[assessment.version_id]
        if not isinstance(spec.rules, GuidanceRules):
            continue
        path = strategy_runs[assessment.version_id, "base"]
        decisions = {d.decision_id: d for d in path.decisions}
        entered = {decisions[f.decision_id].entry_notice_ids[f.instrument_id] for f in path.fills if f.quantity > 0}
        count = len({(notices[n].instrument_id, notices[n].period_start, notices[n].period_end) for n in entered})
        assessment.checks.append(EvidenceCheck(name="event_clusters", passed=count >= plan.criteria.min_guidance_event_clusters,
            detail=f"{count} distinct entered issuer/forecast-period clusters; need {plan.criteria.min_guidance_event_clusters}. Repeat announcements count once."))
        paired = [a.paired_events for a in arms if assessment.version_id in {a.challenger_version_id, a.control_version_id}]
        assessment.checks.append(EvidenceCheck(name="paired_event_accounting", passed=bool(paired) and all(p and p.reconciled for p in paired),
            detail="Every matched scenario retains paired notices, abstentions and actual fill/corporate-action contributions reconciled to portfolio P&L; cash yield and model costs remain separate."))
        incremental = [a for a in arms if a.challenger_version_id == assessment.version_id]
        if incremental:
            base_arm = next(a for a in incremental if a.scenario == "base")
            assessment.checks.extend([
                EvidenceCheck(name="incremental_net_excess", passed=all(a.excess_after_extraction_cost_fraction is not None and a.excess_after_extraction_cost_fraction > 0 for a in incremental), detail="Positive incremental excess over the preceding arm after recurring extraction costs, in every frozen scenario"),
                EvidenceCheck(name="incremental_uncertainty", passed=base_arm.comparison.mean_daily_excess_lower is not None and base_arm.comparison.mean_daily_excess_lower > 0, detail=base_arm.comparison.uncertainty),
            ])
        if spec.model:
            labels = classifications[assessment.version_id]
            relevant = [e for e in dataset.evidence if e.model == spec.model and start <= notices[e.notice_id].availability.available_at.date() <= end]
            assessment.checks.extend([
                EvidenceCheck(name="prospective_classifier", passed=manifest.evidence_kind == "prospective" and bool(relevant) and all(e.availability.mode == "observed" for e in relevant), detail="Historical LLM classification is exploratory; paper eligibility requires recorded prospective model arrivals"),
                EvidenceCheck(name="human_labels", passed=labels.labels >= plan.criteria.min_human_labels and labels.accuracy_lower_bound is not None and labels.accuracy_lower_bound >= float(plan.criteria.min_classifier_accuracy_lower_bound), detail=f"Independent human labels: {labels.labels}; minimum {plan.criteria.min_human_labels}, Wilson accuracy lower bound {labels.accuracy_lower_bound}, required {plan.criteria.min_classifier_accuracy_lower_bound}. Synthetic labels only check software."),
            ])
        insufficiency = {"held_out", "known_availability", "observations", "coverage", "trades", "uncertainty", "event_clusters", "incremental_uncertainty", "prospective_classifier", "human_labels", "equity_reference"}
        assessment.evidence_status = "fixture_only" if manifest.evidence_kind == "fixture" else "insufficient_evidence" if any(not c.passed and c.name in insufficiency for c in assessment.checks) else "eligible_for_paper_review" if all(c.passed for c in assessment.checks) else "rejected"
    report = EvidenceReport(engine_build=engine.build, snapshot_manifest_hash=content_hash(manifest), snapshot_kind=manifest.evidence_kind,
        evaluation=evaluation, evaluation_start=start, evaluation_end=end, embargo_sessions=plan.split.embargo_sessions,
        inspected_family_trials=inspected_trials, family_trial_ceiling=plan.max_trials, runs=summaries, assessments=assessments,
        arm_comparisons=arms, classification_checks=classifications,
        equity_reference=plan.equity_reference,
        evaluated_dataset_hash=evaluated_dataset_hash, evidence_artifacts=evidence_artifacts or [], model_call_ids=model_call_ids or [], model_call_costs=model_call_costs or {},
        limitations=[*manifest.limitations, *limitations, "Cash and fixed-basket controls share the strategy calendar and execution costs; exposure differences are reported separately", "Operating charges are recorded separately from trading P&L; local unmetered compute does not include hardware or operator time", "Preselected baskets may have selection/survivorship bias; evidence thresholds are research assumptions, not a return guarantee"])
    report_hash = store.put_json(report)
    artifacts["report"] = report_hash
    statuses = {a.evidence_status for a in assessments}
    status = next((s for s in ("eligible_for_paper_review", "fixture_only", "insufficient_evidence", "rejected") if s in statuses))
    return ExperimentResult(engine_build=engine.build, manifest_hash=content_hash(manifest), artifacts=artifacts,
        evidence_status=status, explanation="Evaluation complete. Eligibility is assessed separately for each immutable version; no result authorizes an order.",
        report=report.model_dump(mode="json"), operating_cost_usd=operating_cost)
