from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from tradingagents.research.contracts import CostScenario, ExperimentInput, FreezeVersion, ResearchPlanInput, StrategyDraft
from tradingagents.research.data.guidance_fixture import guidance_fixture, fixture_guidance_spec, save_guidance_fixture
from tradingagents.research.data.store import ArtifactStore
from tradingagents.research.engines.base import ReplayRequest
from tradingagents.research.engines.replay import LocalReplayEngine
from tradingagents.research.evaluation.cohorts import guidance_cohorts
from tradingagents.research.evaluation.labels import evaluate_labels
from tradingagents.research.worker import ResearchWorker
from tests.research.conftest import plan_payload

ARMS = ("guidance_control", "numeric_quality", "astra_challenger")


def request(arm="guidance_control"):
    return ReplayRequest(dataset=guidance_fixture(), spec=fixture_guidance_spec(arm), start=date(2020, 2, 1), end=date(2020, 4, 30),
        initial_capital_usd=10000, cash_annual_yield_fraction=0, scenario=CostScenario(name="base", commission_usd=1, slippage_bps=5))


def test_three_arms_isolate_cash_quality_and_evidence_without_resizing_survivors():
    results = {arm: LocalReplayEngine().run(request(arm)) for arm in ARMS}
    buys = {arm: {f.instrument_id: f for f in result.fills if f.quantity > 0} for arm, result in results.items()}
    assert set(buys[ARMS[0]]) == {"sim-clean", "sim-oneoff", "sim-unknown", "sim-weak"}
    assert set(buys[ARMS[1]]) == {"sim-clean", "sim-oneoff", "sim-unknown"}
    assert set(buys[ARMS[2]]) == {"sim-clean"}
    for arm in ARMS:
        clean = buys[arm]["sim-clean"]
        assert clean.quantity == 19
        assert clean.signal_at.date() == date(2020, 2, 10)
        assert clean.executed_at.date() == date(2020, 2, 11)
        assert clean.signal_at < clean.executed_at < clean.observed_at
        assert len([f for f in results[arm].fills if f.instrument_id == "sim-clean"]) == 2
        assert next(f for f in results[arm].fills if f.quantity < 0).executed_at.date() == date(2020, 3, 3)
    assert buys[ARMS[2]]["sim-clean"].signal_at > buys[ARMS[0]]["sim-clean"].signal_at
    assert results[ARMS[2]].equity[-1].cash_usd == D("10030.8893021")


@pytest.mark.parametrize("delay", [0, 1])
def test_hold_is_measured_from_first_actual_fill_and_repeat_never_restarts_it(delay):
    req = request()
    req.spec.rules.hold_sessions = 5
    req.scenario.execution_delay_sessions = delay
    result = LocalReplayEngine().run(req)
    calendar = [s.date for s in req.dataset.sessions]
    clean = [f for f in result.fills if f.instrument_id == "sim-clean"]
    assert len(clean) == 2
    assert calendar.index(clean[1].executed_at.date()) - calendar.index(clean[0].executed_at.date()) == 5 + delay
    assert any(e.notice_id == "clean-repeat" and e.status == "already_held" for e in result.guidance_events)


def test_partition_boundary_purges_incomplete_event_horizons():
    req = request()
    req.end = date(2020, 2, 28)
    result = LocalReplayEngine().run(req)
    assert not result.fills
    assert sum(e.status == "purged" for e in result.guidance_events) == 8


def test_unfilled_entry_does_not_retry_without_another_event():
    req = request()
    req.dataset.bars = [b for b in req.dataset.bars if not (b.instrument_id == "sim-clean" and b.session == date(2020, 2, 11))]
    # Remove subsequent source events so any buy is an illicit retry.
    req.dataset.guidance_notices = [n for n in req.dataset.guidance_notices if not n.notice_id.endswith("-repeat")]
    result = LocalReplayEngine().run(req)
    assert not [f for f in result.fills if f.instrument_id == "sim-clean"]
    assert len([e for e in result.events if e.kind == "unfilled" and e.instrument_id == "sim-clean"]) == 1


def test_withdrawal_before_delayed_fill_cancels_the_existing_entry():
    req = request()
    req.scenario.execution_delay_sessions = 2
    withdrawal = next(n for n in req.dataset.guidance_notices if n.notice_id == "clean-withdrawal")
    at = next(n for n in req.dataset.guidance_notices if n.notice_id == "clean-raise").availability.available_at + timedelta(days=1)
    withdrawal.availability.available_at = at
    result = LocalReplayEngine().run(req)
    assert not [f for f in result.fills if f.instrument_id == "sim-clean"]
    assert len([e for e in result.events if e.instrument_id == "sim-clean" and e.kind == "order_cancelled"]) == 1


def test_three_arm_matching_is_enforced_before_research():
    specs = {arm: fixture_guidance_spec(arm) for arm in ARMS}
    assert len(guidance_cohorts(specs)) == 1
    specs[ARMS[1]].rules.hold_sessions = 10
    with pytest.raises(ValueError, match="identical universe"):
        guidance_cohorts(specs)


def test_later_incompatible_guidance_invalidates_a_pending_entry():
    req = request()
    req.scenario.execution_delay_sessions = 2
    later = next(n for n in req.dataset.guidance_notices if n.notice_id == "clean-repeat")
    earlier = next(n for n in req.dataset.guidance_notices if n.notice_id == "clean-raise")
    later.availability.available_at = earlier.availability.available_at + timedelta(days=1)
    later.reporting_basis = "adjusted"
    result = LocalReplayEngine().run(req)
    assert not [f for f in result.fills if f.instrument_id == "sim-clean"]
    assert any(e.kind == "order_cancelled" and e.instrument_id == "sim-clean" for e in result.events)


def test_human_labels_do_not_use_profit_or_allow_retries_to_hide_bad_output():
    dataset = guidance_fixture()
    model = fixture_guidance_spec(ARMS[2]).model
    result = evaluate_labels(dataset, model, date(2020, 2, 1), date(2020, 4, 30))
    assert result.labels == result.correct == result.completed == 8
    assert result.accuracy == 1 and result.accuracy_lower_bound < .8
    first = dataset.evidence[0]
    failed = first.model_copy(deep=True)
    failed.evidence_id = "earlier-failed-attempt"
    failed.call_started_at -= timedelta(seconds=1)
    failed.validation_errors = ["Malformed output"]
    dataset.evidence.append(failed)
    result = evaluate_labels(dataset, model, date(2020, 2, 1), date(2020, 4, 30))
    assert result.correct == 7 and result.invalid == 1


def test_worker_three_arm_fixture_records_incremental_costs_labels_and_artifacts(repository, tmp_path):
    store = ArtifactStore(tmp_path / "guidance-artifacts")
    snapshot = repository.register_snapshot(save_guidance_fixture(store))
    strategy = repository.create_strategy(StrategyDraft(name="Guidance fixture", hypothesis="Test three matched arms", rationale="Engineering only"))
    versions = [repository.freeze_version(strategy.strategy_id, FreezeVersion(spec=fixture_guidance_spec(arm))) for arm in ARMS]
    payload = plan_payload(strategy.strategy_id, versions[0].version_id)
    payload["version_ids"] = [v.version_id for v in versions]
    payload["max_trials"] = 30
    payload["split"] = {"train_start": "2019-01-01", "train_end": "2019-06-28", "validation_start": "2019-07-01", "validation_end": "2019-12-31", "holdout_start": "2020-01-01", "holdout_end": "2020-12-31"}
    plan = repository.freeze_plan(ResearchPlanInput.model_validate(payload))
    job = repository.queue_experiment(ExperimentInput(plan_id=plan.plan_id, snapshot_id=snapshot.snapshot_id, idempotency_key="three-arm", evaluation="holdout"))
    ResearchWorker(repository, store).run_once()
    record = repository.experiment(job.experiment_id)
    assert record.state == "completed", record.failure_reason
    report = record.result["report"]
    assert len(report["runs"]) == 27 and len(report["arm_comparisons"]) == 6
    assert all(a["evidence_status"] == "fixture_only" for a in report["assessments"])
    assert report["classification_checks"][versions[2].version_id]["correct"] == 8
    assert next(a for a in report["arm_comparisons"] if a["challenger_version_id"] == versions[2].version_id and a["scenario"] == "base")["comparison"]["net_excess_return_fraction"] < 0
    assert record.trial_count == 9
    for artifact in record.result["artifacts"].values():
        assert store.json(artifact)
