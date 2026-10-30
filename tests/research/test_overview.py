from datetime import timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from tradingagents.research.contracts import ExperimentInput
from tradingagents.research.models import ExperimentRecord, StrategyDesignRecord
from tradingagents.research.overview import research_overview
from tradingagents.ui.models import now_utc
from tradingagents.ui.api import create_app
from tests.research.test_deployment import desk, activate, action


def test_empty_overview_has_no_performance_or_entitlement_claim(repository):
    overview = research_overview(repository.sessions)
    assert overview["experiments"] == overview["budgets"] == overview["accounts"] == overview["deployments"] == []
    assert overview["experiment_states"] == {}
    assert overview["totals"]["experiments"] == 0
    assert overview["data_capabilities"][-1]["status"] == "unverified"


def test_overview_counts_all_trials_costs_and_designer_reservations(repository, setup_research):
    strategy, version, plan, snapshot, request = setup_research
    first = repository.queue_experiment(request)
    repository.queue_experiment(request.model_copy(update={"idempotency_key": "second"}))
    with repository.sessions() as session:
        row = session.get(ExperimentRecord, first.experiment_id)
        row.cost_usd = "1.125"
        row.state = "failed"
        row.ended_at = now_utc()
        row.failure_reason = "Required input unavailable"
        session.add(row)
        session.add(StrategyDesignRecord(strategy_id=strategy.strategy_id, family_id=plan.family_id,
            idempotency_key="design-test", request_hash="a" * 64, request={}, reserved_cost_usd=".5", charged_cost_usd=".5",
            state="unknown", deadline_at=now_utc() + timedelta(minutes=1)))
        session.commit()
    overview = research_overview(repository.sessions, limit=1)
    assert overview["totals"]["experiments"] == 2 and len(overview["experiments"]) == 1
    assert overview["experiment_states"] == {"failed": 1, "queued": 1}
    assert overview["experiments"][0]["state"] == "failed"
    budget = overview["budgets"][0]
    assert budget["trials_used"] == first.trial_count * 2 + 1
    assert Decimal(budget["charged_cost_usd"]) == Decimal("1.625")
    assert Decimal(budget["remaining_usd"]) == Decimal(plan.payload["compute_budget_usd"]) - Decimal("1.625")


def test_negative_result_and_evidence_gaps_are_not_promoted(repository, setup_research):
    _, _, _, _, request = setup_research
    job = repository.queue_experiment(request)
    with repository.sessions() as session:
        row = session.get(ExperimentRecord, job.experiment_id)
        row.state = "completed"
        row.result = {"evidence_status": "insufficient_evidence", "explanation": "Coverage is insufficient",
            "report": {"assessments": [{"checks": [{"name": "coverage", "passed": False},
                {"name": "human_labels", "passed": False}, {"name": "known_availability", "passed": True}]}]}}
        session.add(row)
        session.commit()
    overview = research_overview(repository.sessions)
    row = overview["experiments"][0]
    assert row["state"] == "completed" and row["evidence_status"] == "insufficient_evidence"
    assert row["evidence_kind"] == "fixture" and row["data_gaps"] == ["coverage", "human_labels"]
    assert "approval" not in overview


def test_pause_and_latest_account_reconciliation_are_reflected_without_mutation(desk, monkeypatch):
    repo, _, fresh, _, sessions, *_ = desk
    record = activate(desk, monkeypatch)
    repo.pause(record.deployment_id, action(record))
    receipt, _ = fresh()
    before = repo.detail(record.deployment_id)
    overview = research_overview(sessions)
    assert overview["deployments"][0]["state"] == "paused"
    assert overview["deployments"][0]["has_committed_funding"]
    assert overview["accounts"][0]["state"] == "reconciled"
    assert overview["accounts"][0]["observed_at"] == receipt.observed_at
    assert repo.detail(record.deployment_id) == before


def test_dashboard_and_settings_only_gain_the_overview_read(tmp_path, monkeypatch):
    from tradingagents.research.engines import lean
    monkeypatch.setattr(lean, "cached_availability", lambda *_: {"available": False, "message": "Offline fixture"})
    app = create_app(f"sqlite:///{tmp_path / 'api.db'}")
    with TestClient(app) as client:
        for room in ("dashboard", "settings", "research"):
            response = client.get("/api/research/overview", headers={"X-Trademaster-Room": room})
            assert response.status_code == 200, response.text
            assert response.json()["runtime"]["queued"] == 0
        for room in ("dashboard", "settings"):
            headers = {"X-Trademaster-Room": room}
            assert client.get("/api/research/strategies", headers=headers).status_code == 403
            assert client.post("/api/research/strategies", json={"name": "No", "hypothesis": "No", "rationale": "No"}, headers=headers).status_code == 403
            assert client.post("/api/research/deployments/missing/pause", json={"actor": "x", "reason": "x", "expected_revision": 1}, headers=headers).status_code == 403
        assert client.get("/api/research/overview", headers={"X-Trademaster-Room": "unknown"}).status_code == 403


def test_latest_discrepancy_replaces_earlier_reconciled_status(desk):
    _, broker, fresh, _, sessions, *_ = desk
    first, _ = fresh()
    assert first.report["reconciled"]
    broker.cash_usd -= Decimal(100)  # Unexplained cash movement: no matching activity.
    latest, _ = fresh()
    assert not latest.report["reconciled"]
    account = research_overview(sessions)["accounts"][0]
    assert account["state"] == "discrepancy"
    assert account["observed_at"] == latest.observed_at
    assert account["discrepancies"] == len(latest.report["discrepancies"]) > 0


def test_overview_bound_is_explicit(repository):
    for value in (0, 51):
        with pytest.raises(ValueError):
            research_overview(repository.sessions, limit=value)
