from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from tradingagents.research.contracts import ExperimentInput, FreezeVersion, ResearchPlanInput, StrategyDraft, StrategySpec
from tradingagents.research.models import ExperimentRecord
from tradingagents.research.repository import ConflictError, ResearchRepository
from tradingagents.ui.models import now_utc
from tests.research.conftest import plan_payload, spec_payload


def test_frozen_versions_survive_draft_edits_and_database_restart(repository, setup_research):
    strategy, version, *_ = setup_research
    repository.revise_draft(strategy.strategy_id, StrategyDraft(name="New", hypothesis="New idea", rationale="A revision"), expected_revision=1)
    new_repo = ResearchRepository(repository.sessions)
    result = new_repo.strategy(strategy.strategy_id)
    assert result["versions"][0].payload["hypothesis"] == "Persistent price moves"
    assert result["strategy"].hypothesis == "New idea"
    with repository.sessions() as session, pytest.raises(IntegrityError, match="immutable"):
        session.execute(text("UPDATE research_strategy_versions SET content_hash='changed' WHERE version_id=:id"), {"id": version.version_id})
        session.commit()


def test_concurrent_idempotency_is_atomic(repository, setup_research):
    strategy, _, _, _, request = setup_research
    with ThreadPoolExecutor(max_workers=6) as pool:
        ids = list(pool.map(lambda _: repository.queue_experiment(request).experiment_id, range(6)))
    assert len(set(ids)) == 1
    assert len(repository.experiments(strategy.strategy_id)) == 1
    with pytest.raises(ConflictError, match="different inputs"):
        repository.queue_experiment(request.model_copy(update={"evaluation": "validation"}))


def test_cancel_does_not_refund_trials_or_holdout(repository, setup_research):
    _, _, _, _, request = setup_research
    request = request.model_copy(update={"evaluation": "holdout"})
    run = repository.queue_experiment(request)
    repository.cancel(run.experiment_id)
    with pytest.raises(ConflictError, match="holdout already consumed"):
        repository.queue_experiment(request.model_copy(update={"idempotency_key": "another"}))
    assert repository.experiment(run.experiment_id).trial_count == 3


def test_revisions_cannot_reset_research_budget(repository, setup_research):
    strategy, version, *_ = setup_research
    payload = plan_payload(strategy.strategy_id, version.version_id)
    payload["family_id"] = "new_family"
    with pytest.raises(ConflictError, match="existing research family"):
        repository.freeze_plan(ResearchPlanInput.model_validate(payload))
    payload["family_id"] = "trend_family"
    payload["max_trials"] = 100
    with pytest.raises(ConflictError, match="reset"):
        repository.freeze_plan(ResearchPlanInput.model_validate(payload))


def test_trial_cap_counts_all_variants_and_cost_scenarios(repository, setup_research):
    *_, request = setup_research
    for n in range(10):
        repository.queue_experiment(request.model_copy(update={"idempotency_key": str(n)}))
    with pytest.raises(ConflictError, match="trial budget"):
        repository.queue_experiment(request.model_copy(update={"idempotency_key": "over"}))


def test_lease_recovery_rejects_stale_worker_and_keeps_attempts(repository, setup_research):
    *_, request = setup_research
    run = repository.queue_experiment(request)
    assert repository.claim("old").experiment_id == run.experiment_id
    assert repository.claim("new") is None
    with repository.transaction() as session:
        row = session.get(ExperimentRecord, run.experiment_id)
        row.lease_until = now_utc() - timedelta(seconds=1)
        session.add(row)
    recovered = repository.claim("new")
    assert recovered.attempts == 2
    with pytest.raises(ConflictError, match="lease"):
        repository.finish(run.experiment_id, "old", failure="late result")
    repository.finish(run.experiment_id, "new", failure="runner unavailable")
    assert repository.experiment(run.experiment_id).failure_reason == "runner unavailable"
    assert len(repository.events(run.experiment_id)) == 4


def test_metered_calls_are_budgeted_before_dispatch(repository, setup_research):
    *_, request = setup_research
    run = repository.queue_experiment(request)
    repository.claim("worker")
    repository.charge(run.experiment_id, "worker", Decimal("9"))
    with pytest.raises(ConflictError, match="cost budget"):
        repository.charge(run.experiment_id, "worker", Decimal("2"))
    assert repository.experiment(run.experiment_id).cost_usd == "9"


def test_parent_cannot_cross_strategies(repository, setup_research):
    _, version, *_ = setup_research
    other = repository.create_strategy(StrategyDraft(name="Other", hypothesis="Another", rationale="Another"))
    with pytest.raises(ConflictError, match="another strategy"):
        repository.freeze_version(other.strategy_id, FreezeVersion(spec=StrategySpec.model_validate(spec_payload()), parent_version_id=version.version_id))
