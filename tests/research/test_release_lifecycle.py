"""Synthetic funded release path, never provider or investment validation.

The eligibility stub and protocol-shaped account exist only in this test.
Unstubbed fixture rejection is covered by test_deployment.py. Reopening the
application preserves the broker fixture to model a remote economic order.
"""
from decimal import Decimal

from fastapi.testclient import TestClient

from tradingagents.research.deployment_performance import account_deployment_performance
from tradingagents.research.execution_repository import PaperExecutionRepository
from tradingagents.research.execution_service import PaperExecutionService
from tradingagents.ui.api import create_app
from tests.research.test_deployment import desk, activate, action, target_order


def test_funded_partial_fill_lost_ack_restart_pause_review_resume(desk, monkeypatch):
    repo, broker, fresh, _, sessions, *_ = desk
    active = activate(desk, monkeypatch, key="Synthetic funded release")
    boundary, order, exact = target_order(desk, active, quantity=30)
    _, snapshot = fresh()
    attempt, claimed = boundary.claim(order.order_id, snapshot)
    assert claimed
    broker.submit_exact_order(order.intent_id, exact)
    broker.fill(order.intent_id, 10)
    # The process disappeared before recording any broker acknowledgement.
    assert boundary.attempt_for_order(order.order_id).state == "dispatching"
    assert broker.economic_orders == 1

    native_snapshot, native_batch = broker.paper_snapshot, broker.account_activities
    monkeypatch.setattr(broker, "paper_snapshot", lambda: native_snapshot().model_copy(update={"evidence_kind": "broker_paper"}))
    monkeypatch.setattr(broker, "account_activities", lambda start, end: native_batch(start, end).model_copy(update={"evidence_kind": "broker_paper"}))
    original_cancel = broker.cancel_exact_order
    monkeypatch.setattr(broker, "cancel_exact_order", lambda *_: None)  # No cancellation acknowledgement.
    url = str(sessions.kw["bind"].url)
    base = f"/api/research/deployments/{active.deployment_id}"
    headers = {"X-Trademaster-Room": "market"}
    with TestClient(create_app(url, broker_providers={"fixture-paper-broker": broker})) as client:
        paused = client.post(base + "/pause", headers=headers, json=action(active).model_dump(mode="json"))
        assert paused.status_code == 200, paused.text
        assert paused.json()["deployment"]["active_terms_id"] == active.active_terms_id
        assert paused.json()["cancellations"][0]["state"] == "pending_cancel"
        assert broker.positions["SIM-EQ"].quantity == 10 and broker.economic_orders == 1

    # Recreate the app and repository against the same SQLite database. Submit
    # on the original ticket can only GET/reconcile its persisted attempt.
    restarted = PaperExecutionRepository(sessions)
    recovered = PaperExecutionService(restarted, broker).submit(restarted.for_intent(order.intent_id))
    assert recovered.state == "partially_filled" and broker.economic_orders == 1
    original_cancel(order.intent_id)
    with TestClient(create_app(url, broker_providers={"fixture-paper-broker": broker})) as client:
        record = client.get(base).json()["deployment"]
        stale_approval = {"actor": "test operator", "reason": "Cannot reuse old activation", "expected_revision": record["revision"],
            "review_id": active.active_review_id, "expected_hash": "0" * 64}
        assert client.post(base + "/resume", headers=headers, json=stale_approval).status_code == 409
        review = client.post(base + "/review", headers=headers, json={"actor": "test operator", "reason": "Review confirmed cancellation and retained position", "expected_revision": record["revision"]})
        assert review.status_code == 200, review.text
        review = review.json()
        assert review["payload"]["eligible"] and not review["payload"]["allocation"]["creates_flow"]
        detail = client.get(base).json()
        assert detail["orders"][0]["state"] == "canceled"
        assert Decimal(detail["attributed_positions"][0]["quantity"]) == 10
        approval = {"actor": "test operator", "reason": "Approve current exact review", "expected_revision": review["deployment_revision"],
            "review_id": review["review_id"], "expected_hash": review["content_hash"]}
        resumed = client.post(base + "/resume", headers=headers, json=approval)
        assert resumed.status_code == 200, resumed.text
        assert resumed.json()["state"] == "paper_active"
        assert resumed.json()["active_terms_id"] == active.active_terms_id
        assert client.post(base + "/resume", headers=headers, json=approval).status_code == 409
        assert broker.economic_orders == 1 and broker.positions["SIM-EQ"].quantity == 10
        final = client.get(base).json()
        assert [event["action"] for event in final["events"]][-3:] == ["paused", "review_prepared", "resumed"]
    fresh()
    performance = account_deployment_performance(sessions, active.account_key)["deployments"][0]["performance"]
    assert Decimal(performance["equity_usd"]) == 10000
    assert len(performance["capital_flows"]) == 1
    assert Decimal(performance["time_weighted_return_fraction"]) == 0
