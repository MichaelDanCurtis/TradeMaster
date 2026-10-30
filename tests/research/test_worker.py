from datetime import timedelta
from decimal import Decimal
import subprocess
from threading import Thread
import time

import pytest

from tradingagents.research.contracts import ExperimentInput, FreezeVersion, ResearchPlanInput, StrategyDraft
from tradingagents.research.data.fixtures import save_trend_fixture
from tradingagents.research.data.store import ArtifactStore
from tradingagents.research.evaluation.comparison import EvidenceReport, compare, evaluation_window
from tradingagents.research.engines.replay import LocalReplayEngine
from tradingagents.research.repository import ConflictError
from tradingagents.research.worker import ResearchWorker
from tests.research.conftest import plan_payload
from tests.research.test_replay import request_fixture
from tests.research.test_trend import fixture_spec


def queue_fixture(repository, tmp_path, *, engine="local_replay", timeout=30):
    store = ArtifactStore(tmp_path / "artifacts")
    snapshot = repository.register_snapshot(save_trend_fixture(store))
    strategy = repository.create_strategy(StrategyDraft(name="Fixture", hypothesis="Synthetic replay acceptance", rationale="No investment inference"))
    version = repository.freeze_version(strategy.strategy_id, FreezeVersion(spec=fixture_spec()))
    payload = plan_payload(strategy.strategy_id, version.version_id)
    payload["max_runtime_seconds"] = timeout
    plan = repository.freeze_plan(ResearchPlanInput.model_validate(payload))
    job = repository.queue_experiment(ExperimentInput(plan_id=plan.plan_id, snapshot_id=snapshot.snapshot_id, idempotency_key="worker-test", engine=engine))
    return store, job, version


def test_worker_subprocess_persists_verified_report_all_cost_scenarios_and_trial_history(repository, tmp_path):
    store, job, version = queue_fixture(repository, tmp_path)
    worker = ResearchWorker(repository, store, attempt_cost_usd=Decimal(".10"))
    assert worker.run_once() == job.experiment_id
    result = repository.experiment(job.experiment_id)
    assert result.state == "completed", result.failure_reason
    assert result.result["evidence_status"] == "fixture_only"
    assert Decimal(result.cost_usd) == Decimal(".10")
    report = EvidenceReport.model_validate(result.result["report"])
    assert len(report.runs) == 9
    assert {r.scenario for r in report.runs} == {"base", "double_cost", "delayed"}
    assert {r.control for r in report.runs} == {"cash", "fixed_basket", "strategy"}
    assert report.assessments[0].version_id == version.version_id
    for digest in result.result["artifacts"].values():
        assert store.json(digest)
    assert [e.event_type for e in repository.events(job.experiment_id)] == ["queued", "claimed", "completed"]
    assert worker.run_once() is None
    assert repository.runtime()["available"]


def test_unsupported_engine_fails_explicitly_without_substitute_results(repository, tmp_path, monkeypatch):
    monkeypatch.setattr("tradingagents.research.engines.lean.availability", lambda: {"available": False, "message": "Pinned image unavailable"})
    store, job, _ = queue_fixture(repository, tmp_path, engine="lean")
    ResearchWorker(repository, store).run_once()
    record = repository.experiment(job.experiment_id)
    assert record.state == "failed" and record.result is None
    assert "EngineUnavailable" in record.failure_reason and "no substitute" in record.failure_reason
    assert record.trial_count == 3


def test_tampered_dataset_fails_before_any_evidence_is_stored(repository, tmp_path):
    store, job, _ = queue_fixture(repository, tmp_path)
    _, _, manifest, _ = repository.inputs(job.experiment_id)
    store.path(manifest.artifacts["dataset"]).write_text("{}")
    ResearchWorker(repository, store).run_once()
    record = repository.experiment(job.experiment_id)
    assert record.state == "failed" and record.result is None
    assert "no longer matches" in record.failure_reason


def slow_process(monkeypatch):
    original = subprocess.Popen
    started = []
    def spawn(command, **kwargs):
        process = original([command[0], "-c", "import time; time.sleep(30)"], **kwargs)
        started.append(process)
        return process
    monkeypatch.setattr("tradingagents.research.worker.subprocess.Popen", spawn)
    return started


def test_runtime_budget_kills_process_and_persists_failure(repository, tmp_path, monkeypatch):
    store, job, _ = queue_fixture(repository, tmp_path, timeout=1)
    processes = slow_process(monkeypatch)
    ResearchWorker(repository, store, poll_seconds=.02).run_once()
    record = repository.experiment(job.experiment_id)
    assert record.state == "failed" and "runtime budget" in record.failure_reason
    assert processes and processes[0].poll() is not None


def test_cancelled_running_process_is_stopped_and_cannot_publish_late_result(repository, tmp_path, monkeypatch):
    store, job, _ = queue_fixture(repository, tmp_path)
    processes = slow_process(monkeypatch)
    thread = Thread(target=ResearchWorker(repository, store, poll_seconds=.02).run_once)
    thread.start()
    deadline = time.monotonic() + 5
    while not processes and time.monotonic() < deadline:
        time.sleep(.01)
    assert processes, "worker did not start a subprocess"
    repository.cancel(job.experiment_id)
    thread.join(timeout=5)
    assert not thread.is_alive() and processes[0].poll() is not None
    record = repository.experiment(job.experiment_id)
    assert record.state == "cancelled" and record.result is None


def test_immutable_trial_penalty_and_identical_calendar_are_required():
    request = request_fixture()
    result = LocalReplayEngine().run(request)
    report = compare(result, result, trials=3, trial_ceiling=30)
    assert report.net_excess_return_fraction == 0
    assert report.mean_daily_excess_lower is None and "Insufficient" in report.uncertainty
    different = result.model_copy(deep=True)
    different.equity[0].at += timedelta(days=1)
    with pytest.raises(ValueError, match="identical investable"):
        compare(result, different, trials=3, trial_ceiling=30)


def test_embargo_counts_actual_sessions_and_cannot_leak_into_next_partition(repository, tmp_path):
    store, job, _ = queue_fixture(repository, tmp_path)
    _, plan, manifest, _ = repository.inputs(job.experiment_id)
    dataset = store.dataset(manifest)
    plan.split.embargo_sessions = 5
    start, end = evaluation_window(plan, dataset, "validation")
    after_train = [s.date for s in dataset.sessions if s.date > plan.split.train_end]
    assert start == after_train[5] and end == plan.split.validation_end


def test_repository_rejects_forged_fixture_eligibility(repository, tmp_path):
    from tradingagents.research.contracts import ExperimentResult, content_hash
    from tradingagents.research.evaluation.comparison import evaluate
    store, job, _ = queue_fixture(repository, tmp_path)
    repository.claim("test")
    _, plan, manifest, specs = repository.inputs(job.experiment_id)
    result = evaluate(engine=LocalReplayEngine(), plan=plan, manifest=manifest, specs=specs,
        evaluation="development", inspected_trials=3, store=store)
    result.report["assessments"][0]["evidence_status"] = "eligible_for_paper_review"
    result.evidence_status = "eligible_for_paper_review"
    result.artifacts["report"] = content_hash(result.report)
    with pytest.raises(ConflictError, match="fixture results"):
        repository.finish(job.experiment_id, "test", result=ExperimentResult.model_validate(result.model_dump(mode="json")))
