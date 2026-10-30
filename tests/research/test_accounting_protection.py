from datetime import timedelta
from decimal import Decimal as D

import pytest
from pydantic import ValidationError

from tests.research.test_accounting_repository import ledger, enroll, reconciliation
from tradingagents.research.accounting_contracts import AccountActivity, AccountOrderFamily, ProtectiveChild
from tradingagents.research.accounting_repository import PaperAccountingRepository
from tradingagents.research.accounting_service import reconcile_snapshot
from tradingagents.research.execution_contracts import ExactPaperOrder, ExecutionPolicy, PaperOrderObservation
from tradingagents.research.execution_repository import PaperExecutionRepository, account_key
from tradingagents.research.repository import ConflictError
from tradingagents.ui.brokers.fake import FakePaperBroker
from tradingagents.ui.db import create_session_factory
from tradingagents.ui.events import RunConfig
from tradingagents.ui.models import now_utc
from tradingagents.ui.repository import UiRepository


def protected(ledger):
    repo, opening, _ = ledger
    enroll(ledger)
    ui = UiRepository(repo.sessions)
    run = ui.create_run(RunConfig(ticker="AAA", trade_date="2026-09-05", broker_mode="paper"))
    boundary = PaperExecutionRepository(repo.sessions)
    broker = FakePaperBroker(cash_usd="1000")
    exact = ExactPaperOrder(symbol="AAA", side="buy", quantity=2, limit_price_usd=100,
        stop_loss_usd=90, take_profit_usd=110, expires_at=now_utc()+timedelta(minutes=5))
    policy = ExecutionPolicy(max_position_fraction=1, max_group_fraction=1, max_turnover_fraction=2, max_drawdown_fraction=1)
    order = boundary.preview(None, exact, policy, broker.paper_snapshot(), run_id=run.run_id, budget=200)
    boundary.approve(order.order_id, "operator", order.content_hash)
    attempt, claimed = boundary.claim(order.order_id, broker.paper_snapshot())
    assert claimed
    parent = PaperOrderObservation(client_order_id=attempt.client_order_id, broker_order_id="parent", symbol="AAA",
        side="buy", quantity=2, filled_quantity=2, average_fill_price_usd=100, status="filled", observed_at=now_utc())
    boundary.observe(attempt.attempt_id, parent)
    def child(role, identifier, status, price, filled):
        leg = parent.model_copy(update={"broker_order_id":identifier, "client_order_id":identifier,
            "side":"sell", "status":status, "filled_quantity":D(filled), "average_fill_price_usd":D(price) if filled else None})
        return ProtectiveChild(role=role, observation=leg, **{"stop_price_usd" if role=="stop_loss" else "limit_price_usd":price})
    family = AccountOrderFamily(parent=parent, children=[child("stop_loss", "stop", "canceled",90,0), child("take_profit","profit","filled",110,2)])
    activities = [AccountActivity(source_id=f"fill-{second}",kind="fill",symbol="AAA",side=side,quantity=2,price_usd=price,
        broker_order_id=identifier,effective_at=opening.observed_at+timedelta(seconds=second))
        for second,side,price,identifier in [(1,"buy",100,"parent"),(2,"sell",110,"profit")]]
    return boundary, broker, family, activities


def test_completed_parent_child_fill_lineage_persists_and_does_not_double_count(ledger):
    repo, opening, url = ledger
    _, _, family, activities = protected(ledger)
    request = reconciliation(opening,3,1020,activities).model_copy(update={"order_families":[family]})
    first = repo.reconcile(request)
    assert first.report["reconciled"] and D(first.report["investment_pnl_usd"]) == 20
    assert D(first.report["time_weighted_return_fraction"]) == D(".02")
    child = first.report["fills"][1]
    assert child["executor"] == "manual" and child["parent_broker_order_id"] == "parent" and child["protection_role"] == "take_profit"
    assert child["position_owners"] == {"manual":"2"}
    assert len(first.report["protective_orders"]) == 2
    _, sessions = create_session_factory(url)
    restarted = PaperAccountingRepository(sessions)
    assert restarted.reconcile(request).reconciliation_id == first.reconciliation_id
    again = restarted.reconcile(reconciliation(opening,4,1020,activities).model_copy(update={"order_families":[family]}))
    assert len(again.report["fills"]) == 2 and D(again.report["investment_pnl_usd"]) == 20
    assert len(restarted.history(account_key(opening))) == 2


def test_missing_lineage_blocks_claim_until_current_family_is_observed(ledger):
    repo, opening, _ = ledger
    _, _, family, activities = protected(ledger)
    first = repo.reconcile(reconciliation(opening,3,1020,activities))
    assert not first.report["reconciled"]
    assert any(e["code"]=="protective_lineage_unobserved" for e in first.report["discrepancies"])
    second = repo.reconcile(reconciliation(opening,4,1020,activities).model_copy(update={"order_families":[family]}))
    assert second.report["reconciled"]
    assert first.report["fills"][1]["executor"]=="external_manual"
    assert second.report["fills"][1]["executor"]=="manual"


def test_changed_protection_terms_are_retained_and_block_reconciled_returns(ledger):
    repo, opening, _ = ledger
    _, _, family, activities = protected(ledger)
    family.children[0].stop_price_usd = D(95)
    result = repo.reconcile(reconciliation(opening,3,1020,activities).model_copy(update={"order_families":[family]}))
    assert not result.report["reconciled"] and result.report["time_weighted_return_fraction"] is None
    assert any(e["code"]=="protective_terms_changed" for e in result.report["discrepancies"])
    assert result.report["protective_orders"][0]["stop_price_usd"] == "95"


def test_cross_parent_identity_and_unapproved_roles_cannot_claim_child_fills(ledger):
    repo, opening, _ = ledger
    _, _, family, activities = protected(ledger)
    family.parent.client_order_id = "foreign-client"
    with pytest.raises(ConflictError,match="approved parent"):
        repo.reconcile(reconciliation(opening,3,1020,activities).model_copy(update={"order_families":[family]}))
    assert not repo.history(account_key(opening))


def test_family_contract_rejects_wrong_side_symbol_duplicate_and_oversized_child(ledger):
    _, _, family, _ = protected(ledger)
    raw = family.model_dump(mode="json")
    for key, value in [("side","buy"),("symbol","BBB"),("quantity",3),("broker_order_id","parent")]:
        copy = family.model_dump(mode="json")
        copy["children"][0]["observation"][key] = value
        with pytest.raises(ValidationError): AccountOrderFamily.model_validate(copy)
    raw["children"].append(raw["children"][0])
    with pytest.raises(ValidationError): AccountOrderFamily.model_validate(raw)


def test_observer_reads_terminal_parent_family_without_submission_or_cancellation(ledger,monkeypatch):
    repo, opening, _ = ledger
    boundary, broker, family, activities = protected(ledger)
    broker.activities = activities
    seen = []
    monkeypatch.setattr(broker,"order_family",lambda parent: (seen.append(parent),family)[1],raising=False)
    snapshot = reconciliation(opening,3,1020,activities).snapshot
    result = reconcile_snapshot(broker,repo,snapshot)
    assert result.report["reconciled"] and seen==["parent"] and broker.economic_orders==0
    assert boundary.attempt_for_order(boundary.for_intent(family.parent.client_order_id).order_id).state=="filled"


def test_child_fill_with_incompatible_symbol_or_side_blocks_return_claims(ledger):
    repo, opening, _ = ledger
    _, _, family, activities = protected(ledger)
    activities[1].side="buy"
    result = repo.reconcile(reconciliation(opening,3,1020,activities).model_copy(update={"order_families":[family]}))
    assert not result.report["reconciled"]
    assert any(e["code"]=="protective_fill_identity_mismatch" for e in result.report["discrepancies"])


def test_partial_child_and_unacknowledged_cancellation_keep_remaining_protection_visible(ledger):
    from tradingagents.research.execution_contracts import AccountPosition
    repo, opening, _ = ledger
    _, _, family, activities = protected(ledger)
    activities[1].quantity=D(1)
    leg=family.children[1].observation
    family.children[1].observation=leg.model_copy(update={"filled_quantity":D(1),"status":"pending_cancel"})
    positions=[AccountPosition(symbol="AAA",quantity=1,market_value_usd=110,cost_basis_usd=100)]
    result=repo.reconcile(reconciliation(opening,3,910,activities,positions=positions).model_copy(update={"order_families":[family]}))
    assert result.report["reconciled"] and D(result.report["investment_pnl_usd"])==20
    child=next(c for c in result.report["protective_orders"] if c["protection_role"]=="take_profit")
    assert child["status"]=="pending_cancel" and child["filled_quantity"]==child["remaining_quantity"]=="1"


def test_protective_executor_does_not_override_fifo_lot_owners(ledger):
    from types import SimpleNamespace
    from tradingagents.research.accounting import reconcile_account
    from tradingagents.research.accounting_lineage import protection_lineage
    from tradingagents.research.execution_contracts import AccountPosition
    repo, opening, _ = ledger
    boundary, _, family, activities = protected(ledger)
    order=boundary.for_intent(family.parent.client_order_id)
    attempt=boundary.attempt_for_order(order.order_id)
    # This pure test pins synthetic deployment identity without bypassing any
    # persisted deployment approval or activation gate.
    owner=SimpleNamespace(order=order.order,deployment_id="example",order_id=order.order_id)
    opening=opening.model_copy(update={"equity_usd":D(1100),"positions":[AccountPosition(symbol="AAA",quantity=1,market_value_usd=100,cost_basis_usd=80)]})
    request=reconciliation(opening,3,1020,activities,positions=[AccountPosition(symbol="AAA",quantity=1,market_value_usd=110,cost_basis_usd=100)]).model_copy(update={"order_families":[family]})
    attribution,_,_,errors=protection_lineage([attempt],{order.order_id:owner},[],request)
    assert not errors
    report=reconcile_account(opening,[request.snapshot],activities,attribution)
    assert report["reconciled"] and report["investment_pnl_usd"]==30
    assert report["fills"][1]["executor"]=="deployment:example"
    assert report["fills"][1]["position_owners"]=={"legacy_manual":D(1),"deployment:example":D(1)}
