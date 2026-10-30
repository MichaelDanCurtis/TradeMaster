from fastapi.testclient import TestClient

from tradingagents.research.repository import ResearchRepository
from tradingagents.ui.api import create_app
from tradingagents.ui.brokers.fake import FakePaperBroker
from tradingagents.ui.db import create_session_factory,init_db
from tests.research.test_worker import queue_fixture


def test_research_requests_review_but_cannot_activate_or_loosen_authority(tmp_path,monkeypatch):
    url=f"sqlite:///{tmp_path/'api.db'}"
    engine,sessions=create_session_factory(url);init_db(engine)
    _,job,version=queue_fixture(ResearchRepository(sessions),tmp_path)
    broker=FakePaperBroker()
    client=TestClient(create_app(url,broker_providers={"fixture-paper-broker":broker}))
    baseline=client.post("/api/paper-accounting/baselines/preview").json()
    assert client.post(f'/api/paper-accounting/baselines/{baseline["baseline_id"]}/approve',json={"actor":"operator","expected_hash":baseline["content_hash"]}).status_code==200
    payload={"name":"Review candidate","version_id":version.version_id,"experiment_id":job.experiment_id,
        "account":{"provider_id":"fake","account_id":"fixture-paper-account"},"idempotency_key":"api-review",
        "terms":{"capital_usd":"10000","execution_policy":{"max_position_fraction":".5","max_group_fraction":".6","max_turnover_fraction":"1","max_drawdown_fraction":".2","cash_reserve_fraction":".1"},
            "fee_reserve_per_order_usd":"1","fee_assumption_reference":"Fixture fee assumption","funding_rationale":"Bounded paper research review"}}
    assert client.post("/api/research/deployments",json={**payload,"state":"paper_active"}).status_code==422
    created=client.post("/api/research/deployments",json=payload)
    assert created.status_code==201,created.text
    record=created.json();base=f'/api/research/deployments/{record["deployment_id"]}'
    assert record["state"]=="draft" and record["active_terms_id"] is None
    assert client.post("/api/research/deployments",json=payload).json()["deployment_id"]==record["deployment_id"]
    action={"actor":"operator","reason":"Inspect the evidence and account","expected_revision":1}
    assert client.post(base+"/review",json=action).status_code==403
    market={"x-trademaster-room":"market"}
    reviewed=client.post(base+"/review",json=action,headers=market)
    assert reviewed.status_code==200,reviewed.text
    review=reviewed.json();assert not review["payload"]["eligible"]
    assert any(g["name"]=="broker_paper_account" and not g["passed"] for g in review["payload"]["gates"])
    approval={**action,"expected_revision":review["deployment_revision"],"review_id":review["review_id"],"expected_hash":review["content_hash"]}
    assert client.post(base+"/activate",json=approval).status_code==403
    denied=client.post(base+"/activate",json=approval,headers=market)
    assert denied.status_code==409 and "not met" in denied.json()["detail"]
    assert client.post(base+"/pause",json={**action,"expected_revision":2}).status_code==403
    detail=client.get(base).json()
    assert len(detail["reviews"])==1 and detail["deployment"]["state"]=="paper_review"
    assert not detail["orders"] and not detail["programs"] and broker.economic_orders==0
    rejected=client.post(base+"/decision",json={**approval,"decision":"reject","reason":"Fixture evidence cannot justify funding"},headers=market)
    assert rejected.status_code==200 and rejected.json()["state"]=="draft"
    history=client.get(base).json()
    assert len(history["reviews"])==1 and history["events"][-1]["action"]=="review_reject"
    reviewed=client.post(base+"/review",json={**action,"expected_revision":3},headers=market)
    assert reviewed.status_code==200
    # Even constructing the configured adapter can fail. Pause must commit
    # before that failure, rather than leave existing authority active.
    monkeypatch.setattr("tradingagents.ui.api._resolve_broker_adapter",lambda *_:(_ for _ in ()).throw(ValueError("invalid paper configuration")))
    paused=client.post(base+"/pause",json={**action,"expected_revision":4},headers=market)
    assert paused.status_code==200 and paused.json()["deployment"]["state"]=="paused"
    assert paused.json()["cancellations"][0]["state"]=="cancellation_unavailable"
    assert client.get(base).json()["deployment"]["state"]=="paused"
