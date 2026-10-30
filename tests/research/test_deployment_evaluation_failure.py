"""Failure and fresh-review recovery use only synthetic lifecycle fixtures."""
import pytest

from tests.research.test_deployment import desk,activate,action,approve
from tests.research.test_deployment_evaluation import current_fixture
from tradingagents.research.deployment_contracts import DeploymentEvaluationInput
from tradingagents.research.deployment_service import DeploymentService
from tradingagents.research.repository import ConflictError


@pytest.mark.parametrize("stage",["account_observation","source_or_calculation"])
def test_failed_evaluation_retains_funding_and_requires_fresh_review_to_recover(desk,monkeypatch,stage):
    active=activate(desk,monkeypatch)
    repo,broker,fresh,_,sessions,_,(research,store,_)=desk
    source,at=current_fixture(research,store)
    request=DeploymentEvaluationInput(**action(active).model_dump(),snapshot_id=source.snapshot_id,as_of=at)
    service=DeploymentService(sessions,broker)
    monkeypatch.setattr(service,"observe",lambda _:fresh()[0])
    if stage=="account_observation":
        original=service.observe
        monkeypatch.setattr(service,"observe",lambda _:(_ for _ in ()).throw(TimeoutError("private provider error should not be retained")))
    else:
        original=store.dataset
        monkeypatch.setattr(store,"dataset",lambda _:(_ for _ in ()).throw(FileNotFoundError("private filesystem path should not be retained")))
    result=service.evaluate(active.deployment_id,request,store)
    assert result["evaluation"] is None and result["failure"]["stage"]==stage
    detail=repo.detail(active.deployment_id);paused=detail["deployment"]
    assert paused.state=="paused" and paused.active_terms_id==active.active_terms_id
    assert not detail["evaluations"] and not detail["orders"] and broker.economic_orders==0
    assert detail["events"][-1].action=="evaluation_failed"
    assert "private" not in str(detail["events"][-1].payload)
    with pytest.raises(ConflictError): service.evaluate(active.deployment_id,request,store)
    monkeypatch.setattr(service if stage=="account_observation" else store,"observe" if stage=="account_observation" else "dataset",original)
    receipt,_=fresh();review=repo.review(active.deployment_id,action(paused),receipt.reconciliation_id)
    receipt,_=fresh();resumed=repo.activate(active.deployment_id,approve(review),receipt.reconciliation_id,resume=True)
    result=service.evaluate(active.deployment_id,request.model_copy(update={"expected_revision":resumed.revision}),store)
    assert result["evaluation"].payload["status"]=="targets"
    assert any(event.action=="evaluation_failed" for event in repo.detail(active.deployment_id)["events"])
    assert broker.economic_orders==0


def test_broker_constructor_failure_is_recorded_before_any_observation(desk,monkeypatch):
    from fastapi.testclient import TestClient
    from tradingagents.ui.api import create_app
    active=activate(desk,monkeypatch)
    repo,broker,_,_,sessions,_,(research,store,_)=desk
    source,at=current_fixture(research,store)
    monkeypatch.setenv("TRADEMASTER_RESEARCH_ARTIFACTS",str(store.root))
    app=create_app(str(sessions.kw["bind"].url),broker_providers={"fixture-paper-broker":broker})
    monkeypatch.setattr("tradingagents.ui.api._resolve_broker_adapter",lambda *_:(_ for _ in ()).throw(ValueError("private adapter configuration")))
    client=TestClient(app)
    request=DeploymentEvaluationInput(**action(active).model_dump(),snapshot_id=source.snapshot_id,as_of=at).model_dump(mode="json")
    path=f"/api/research/deployments/{active.deployment_id}/evaluate"
    assert client.post(path,json=request).status_code==403
    response=client.post(path,json=request,headers={"X-Trademaster-Room":"market"})
    assert response.status_code==200,response.text
    assert response.json()["failure"]["stage"]=="broker_construction"
    assert repo.detail(active.deployment_id)["deployment"].state=="paused"
    assert "private" not in response.text and broker.economic_orders==0
