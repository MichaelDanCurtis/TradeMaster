from datetime import timedelta
from decimal import Decimal as D

import pytest
from sqlalchemy import text

from tradingagents.research.accounting import reconcile_account
from tradingagents.research.deployment_contracts import CapitalRevision
from tradingagents.research.deployment_performance import deployment_performance, account_deployment_performance, flows_for
from tradingagents.research.repository import ConflictError
from tests.research.test_accounting import START, snapshot, position, activity
from tests.research.test_deployment import desk, activate, action, approve, target_order  # noqa: F401


def flow(second, amount, revision=1):
    return {"flow_id":f"f-{second}","effective_at":(START+timedelta(seconds=second)).isoformat(),"amount_usd":str(amount),"revision":revision}


def test_cash_and_equity_partition_with_manual_exit_dividend_split_and_fees():
    events=[activity(2,"fill",symbol="AAA",side="buy",quantity=4,price_usd=100,fee_usd=1,broker_order_id="entry"),
        activity(3,"split",symbol="AAA",split_ratio=2),
        activity(4,"dividend",symbol="AAA",cash_amount_usd=8,entitlement_at=START+timedelta(seconds=3)),
        activity(5,"fill",symbol="AAA",side="sell",quantity=3,price_usd=60,fee_usd=2,broker_order_id="manual-exit"),
        activity(6,"fee",cash_amount_usd=-1,broker_order_id="entry"),activity(7,"interest",cash_amount_usd=2)]
    report=reconcile_account(snapshot(0,2000),[snapshot(8,1786,[position("AAA",5,250,325)])],events,{"entry":"deployment:one"})
    assert report["reconciled"]
    point=report["owner_equity_history"][-1]
    assert sum(x["cash_without_allocations_usd"] for x in point["owners"].values())==1786
    assert sum(x["equity_without_allocations_usd"] for x in point["owners"].values())==2111
    book=deployment_performance(report,[flow(1,1000)],"deployment:one")
    assert book["status"]=="reconciled"
    assert D(book["cash_usd"])==784 and D(book["market_value_usd"])==325
    assert D(book["equity_usd"])==1109 and D(book["investment_pnl_usd"])==109
    assert D(book["time_weighted_return_fraction"])==D(".109")


def test_deposit_is_unallocated_and_does_not_inflate_deployment_return():
    events=[activity(2,"fill",symbol="AAA",side="buy",quantity=5,price_usd=100,broker_order_id="entry"),
        activity(3,"deposit",cash_amount_usd=2000)]
    report=reconcile_account(snapshot(0,2000),[snapshot(4,3500,[position("AAA",5,500,550)])],events,{"entry":"deployment:one"})
    assert report["time_weighted_return_fraction"] is None
    book=deployment_performance(report,[flow(1,1000)],"deployment:one")
    assert D(book["investment_pnl_usd"])==50 and D(book["time_weighted_return_fraction"])==D(".05")
    assert D(book["equity_usd"])==1050


def test_exact_funding_change_unitizes_and_full_release_keeps_return():
    events=[activity(2,"fill",symbol="AAA",side="buy",quantity=5,price_usd=100,broker_order_id="entry"),
        activity(6,"fill",symbol="AAA",side="sell",quantity=5,price_usd=120,broker_order_id="exit")]
    report=reconcile_account(snapshot(0,3000),[snapshot(3,2500,[position("AAA",5,500,550)]),snapshot(7,3100),snapshot(9,3100)],events,{"entry":"deployment:one","exit":"deployment:one"})
    book=deployment_performance(report,[flow(1,1000),flow(3,1050,2),flow(8,-2150,3)],"deployment:one")
    # 5% before doubling the allocation, then 50/2100 more, full cash release.
    assert book["closed"] and D(book["equity_usd"])==0
    assert D(book["investment_pnl_usd"])==100
    assert abs(D(book["time_weighted_return_fraction"])-D(".075"))<D("1e-30")
    assert book["capital_flows"][1]["exact_valuation"]


def test_missing_flow_mark_keeps_dollar_profit_and_withholds_exact_return():
    events=[activity(2,"fill",symbol="AAA",side="buy",quantity=5,price_usd=100,broker_order_id="entry")]
    report=reconcile_account(snapshot(0,3000),[snapshot(5,2500,[position("AAA",5,500,550)])],events,{"entry":"deployment:one"})
    book=deployment_performance(report,[flow(1,1000),flow(3,1000,2)],"deployment:one")
    assert book["status"]=="return_unavailable" and book["time_weighted_return_fraction"] is None
    assert D(book["investment_pnl_usd"])==50 and D(book["equity_usd"])==2050
    assert all(p["time_weighted_return_fraction"] is None for p in book["equity_history"])


def test_day_precision_cash_activity_cannot_supply_exact_intraday_funding_valuation():
    events=[activity(2,"fill",symbol="AAA",side="buy",quantity=1,price_usd=100,broker_order_id="entry"),
        activity(3,"fill",symbol="AAA",side="sell",quantity=1,price_usd=110,broker_order_id="exit"),
        activity(4,"fee",cash_amount_usd=-1,broker_order_id="entry",time_precision="day")]
    report=reconcile_account(snapshot(0,2000),[snapshot(6,2009)],events,{"entry":"deployment:one","exit":"deployment:one"})
    book=deployment_performance(report,[flow(1,1000),flow(5,1000,2)],"deployment:one")
    assert book["status"]=="return_unavailable" and D(book["investment_pnl_usd"])==9
    assert book["capital_flows"][1]["exact_valuation"] is False


def test_zero_equity_is_a_total_loss_not_an_undefined_return():
    events=[activity(2,"fill",symbol="AAA",side="buy",quantity=10,price_usd=100,broker_order_id="entry")]
    report=reconcile_account(snapshot(0,2000),[snapshot(3,1000,[position("AAA",10,1000,0)])],events,{"entry":"deployment:one"})
    book=deployment_performance(report,[flow(1,1000)],"deployment:one")
    assert D(book["time_weighted_return_fraction"])==-1 and D(book["maximum_drawdown_fraction"])==1


def test_discrepancies_and_old_reconciliations_do_not_become_performance():
    report=reconcile_account(snapshot(0,1000),[snapshot(2,1001)],[])
    assert deployment_performance(report,[flow(1,1000)],"deployment:one")["investment_pnl_usd"] is None
    report=reconcile_account(snapshot(0,1000),[snapshot(2,1000)],[])
    assert deployment_performance(report,[],"deployment:one")["status"]=="unavailable"
    del report["owner_equity_history"]
    assert deployment_performance(report,[flow(1,1000)],"deployment:one")["status"]=="unavailable"


def test_new_allocation_remains_visible_without_backdating_it_into_the_last_observation():
    report=reconcile_account(snapshot(0,2000),[snapshot(5,2000)],[])
    book=deployment_performance(report,[flow(1,1000),flow(6,500,2)],"deployment:one")
    assert book["status"]=="awaiting_reconciliation" and D(book["equity_usd"])==1000
    assert D(book["net_allocations_usd"])==1000
    assert len(book["capital_flows"])==2 and book["capital_flows"][1]["awaiting_observation"]


def test_approval_pause_resume_reallocation_and_retirement_persist_flows(desk,monkeypatch):
    record=activate(desk,monkeypatch)
    repo,_,fresh,_,sessions,terms,*_=desk
    identifier=record.deployment_id
    with sessions() as session:
        rows=flows_for(session,identifier)
        assert len(rows)==1 and D(rows[0].amount_usd)==10000
    receipt,_=fresh()
    result=account_deployment_performance(sessions,record.account_key)
    assert D(result["deployments"][0]["performance"]["equity_usd"])==10000
    paused=repo.pause(identifier,action(record))
    review=repo.review(identifier,action(paused),receipt.reconciliation_id)
    assert review.payload["allocation"]["creates_flow"] is False
    receipt,_=fresh();resumed=repo.activate(identifier,approve(review),receipt.reconciliation_id,resume=True)
    paused=repo.pause(identifier,action(resumed))
    amended=repo.change_capital(identifier,CapitalRevision(**action(paused).model_dump(),terms=terms.model_copy(update={"capital_usd":D(5000)})))
    receipt,_=fresh();review=repo.review(identifier,action(amended),receipt.reconciliation_id)
    assert D(review.payload["allocation"]["amount_usd"])==-5000
    receipt,_=fresh();resumed=repo.activate(identifier,approve(review),receipt.reconciliation_id,resume=True)
    paused=repo.pause(identifier,action(resumed));receipt,_=fresh()
    retired=repo.retire(identifier,action(paused),receipt.reconciliation_id)
    assert retired.state=="retired"
    fresh()
    final=account_deployment_performance(sessions,record.account_key)["deployments"][0]["performance"]
    assert final["closed"] and D(final["equity_usd"])==0 and D(final["time_weighted_return_fraction"])==0
    assert len(final["capital_flows"])==3
    with pytest.raises(Exception,match="immutable"):
        with repo.transaction() as session: session.execute(text("UPDATE research_deployment_capital_flows SET amount_usd='1'"))


def test_retained_profit_is_reserved_and_explicit_reallocation_releases_profit_without_erasing_return(desk,monkeypatch):
    from tradingagents.research.deployment_repository import funding_capacity
    from tradingagents.research.accounting_api import create_accounting_router
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    record=activate(desk,monkeypatch)
    repo,broker,fresh,_,sessions,terms,*_=desk
    boundary,order,exact=target_order(desk,record,quantity=10)
    _,snapshot_now=fresh();attempt,_=boundary.claim(order.order_id,snapshot_now)
    boundary.observe(attempt.attempt_id,broker.submit_exact_order(order.intent_id,exact))
    boundary.observe(attempt.attempt_id,broker.fill(order.intent_id,10))
    # External manual execution consumes the deployment's FIFO lots, preserving its proceeds.
    broker.submit_exact_order("external-sale",exact.model_copy(update={"side":"sell","limit_price_usd":D(110)}))
    broker.fill("external-sale",10,110)
    receipt,snapshot_now=fresh()
    with sessions() as session:
        capacity=funding_capacity(session,record.account_key,snapshot_now,receipt.report,D(0))
    assert capacity.other_envelopes_usd==10100 and capacity.available_envelope_usd==90000
    paused=repo.pause(record.deployment_id,action(record))
    revised=repo.change_capital(record.deployment_id,CapitalRevision(**action(paused).model_dump(),terms=terms))
    review=repo.review(record.deployment_id,action(revised),receipt.reconciliation_id)
    assert D(review.payload["allocation"]["amount_usd"])==-100
    receipt,_=fresh();repo.activate(record.deployment_id,approve(review),receipt.reconciliation_id,resume=True)
    fresh()
    app=FastAPI();app.include_router(create_accounting_router(sessions,lambda:broker))
    with TestClient(app) as client:
        path=f"/api/paper-accounting/accounts/{record.account_key}/deployment-performance"
        response=client.get(path)
        assert response.status_code==200,response.text
        performance=response.json()["deployments"][0]["performance"]
        assert D(performance["investment_pnl_usd"])==100 and D(performance["equity_usd"])==10000
        assert D(performance["time_weighted_return_fraction"])==D(".01")
        assert client.get(path,headers={"X-Trademaster-Room":"research"}).status_code==403
        assert client.get("/api/paper-accounting/accounts/missing/deployment-performance").status_code==404


def test_attributed_cash_deficit_cannot_spend_unallocated_account_cash(desk,monkeypatch):
    from tradingagents.research.accounting_contracts import AccountActivity
    from tradingagents.ui.models import now_utc
    record=activate(desk,monkeypatch)
    _,broker,fresh,*_=desk
    boundary,order,exact=target_order(desk,record,quantity=10)
    _,snapshot_now=fresh();attempt,_=boundary.claim(order.order_id,snapshot_now)
    observed=broker.submit_exact_order(order.intent_id,exact)
    boundary.observe(attempt.attempt_id,observed)
    boundary.observe(attempt.attempt_id,broker.fill(order.intent_id,10))
    broker.cash_usd-=9500
    broker.activities.append(AccountActivity(source_id="large-attributed-fee",kind="fee",effective_at=now_utc(),cash_amount_usd=-9500,broker_order_id=observed.broker_order_id))
    receipt,_=fresh()
    assert receipt.report["reconciled"]
    with pytest.raises(ConflictError,match="attributed deployment cash"):
        target_order(desk,record,quantity=1)
