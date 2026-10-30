"""All prices/account evidence below are synthetic infrastructure fixtures.

The prospective metadata in repository cases deliberately exercises the protocol
shape; it is not provider validation or an eligible investment strategy.
"""
from datetime import datetime, timedelta
from decimal import Decimal as D
from zoneinfo import ZoneInfo

import pytest
from sqlmodel import select

from tests.research.test_deployment import desk, activate, action, target_order
from tests.research.test_trend import fixture_spec
from tradingagents.research.contracts import SnapshotManifest, content_hash
from tradingagents.research.data.contracts import DatasetBundle, TradingSession
from tradingagents.research.data.fixtures import trend_fixture
from tradingagents.research.deployment_contracts import DeploymentEvaluationInput, DeploymentTargetInput
from tradingagents.research.deployment_evaluation import DeploymentEvaluator
from tradingagents.research.deployment_models import DeploymentEvaluationRecord, DeploymentOrderTargetRecord
from tradingagents.research.execution_models import PaperExecutionAttemptRecord
from tradingagents.research.repository import ConflictError
from tradingagents.research.strategies.deployment_portfolio import deployment_portfolio
from tradingagents.research.strategies.trend import trend_targets
from tradingagents.ui.models import now_utc, ExecutionProgramRecord


def test_shared_decision_known_raw_prices_and_whole_share_rounding():
    data=trend_fixture();spec=fixture_spec();at=data.sessions[14].closes_at+timedelta(seconds=spec.rules.decision_latency_seconds)
    actual=deployment_portfolio(data,spec,at,D(10000),{"us-sim-eq":D(3),"us-sim-bond":D(0)})
    assert actual["status"]=="targets"
    assert actual["decision"]==trend_targets(data,spec,at).model_dump(mode="json")
    for row in actual["portfolio"]:
        assert D(row["desired_quantity"])*D(row["reference_price_usd"])<=D(10000)*D(row["weight"])
        assert row["delta_quantity"]==row["desired_quantity"]-row["current_quantity"]
    tiny=deployment_portfolio(data,spec,at,D(1),{"us-sim-eq":D(0),"us-sim-bond":D(0)})
    assert all(r["desired_quantity"]==0 for r in tiny["portfolio"])
    for bar in data.bars:
        if bar.session>at.date(): bar.close*=100
    assert deployment_portfolio(data,spec,at,D(10000),{"us-sim-eq":D(3),"us-sim-bond":D(0)})==actual


def test_weekly_calendar_missing_data_and_mapping_do_not_invent_trades():
    data=trend_fixture();spec=fixture_spec();holdings={"us-sim-eq":D(3),"us-sim-bond":D(0)}
    at=data.sessions[13].closes_at+timedelta(seconds=spec.rules.decision_latency_seconds)
    assert deployment_portfolio(data,spec,at,D(10000),holdings)["status"]=="not_due"
    at=data.sessions[14].closes_at+timedelta(seconds=spec.rules.decision_latency_seconds)
    assert deployment_portfolio(data,spec,at+timedelta(seconds=1),D(10000),holdings)["status"]=="unavailable"
    data.bars=[b for b in data.bars if not(b.session==data.sessions[14].date and b.instrument_id=="us-sim-eq")]
    unavailable=deployment_portfolio(data,spec,at,D(10000),holdings)
    assert unavailable["status"]=="unavailable" and not unavailable["portfolio"]


def current_fixture(research,store,*,missing=False,expensive_equity=False):
    data=trend_fixture();spec=fixture_spec()
    now=now_utc();zone=ZoneInfo(data.timezone);today=now.astimezone(zone).date()
    # Explicitly synthetic calendar: prior Friday -> an opening just before now.
    prior_friday=today-timedelta(days=today.weekday()+3)
    shift=prior_friday-data.sessions[14].date
    old_sessions=data.sessions[:15];last=old_sessions[-1].date
    sessions=[s.model_copy(update={"date":s.date+shift,"opens_at":s.opens_at+shift,"closes_at":s.closes_at+shift}) for s in old_sessions]
    sessions.append(TradingSession(date=today,opens_at=now-timedelta(seconds=20),closes_at=now+timedelta(minutes=2)))
    bars=[b.model_copy(update={"session":b.session+shift,"available_at":b.available_at+shift}) for b in data.bars if b.session<=last]
    if expensive_equity:
        bars=[b.model_copy(update={key:getattr(b,key)*10 for key in ("open","high","low","close")}) if b.instrument_id=="us-sim-eq" else b for b in bars]
        bars=[b.model_copy(update={key:getattr(b,key)+D((b.session-sessions[0].date).days)*10 for key in ("open","high","low","close")}) if b.instrument_id=="us-sim-bond" else b for b in bars]
    if missing: bars=[b for b in bars if not(b.instrument_id=="us-sim-eq" and b.session==prior_friday)]
    data=DatasetBundle(timezone=data.timezone,sessions=sessions,bars=bars,mappings=data.mappings)
    manifest=SnapshotManifest(provider="synthetic-protocol-test",evidence_kind="prospective",availability="recorded_receipt",
        provenance="Fabricated prospective metadata for isolated tests only",entitlement="synthetic",calendar="synthetic-test",timezone=data.timezone,
        coverage_start=sessions[0].date,coverage_end=sessions[-1].date,instrument_ids=["us-sim-eq","us-sim-bond"],artifacts=store.put_dataset(data))
    return research.register_snapshot(manifest),sessions[-2].closes_at+timedelta(seconds=spec.rules.decision_latency_seconds)


def evaluated(desk,monkeypatch,*,missing=False):
    active=activate(desk,monkeypatch)
    repo,broker,fresh,_,sessions,terms,(research,store,job)=desk
    snapshot,at=current_fixture(research,store,missing=missing)
    request=DeploymentEvaluationInput(**action(active).model_dump(),snapshot_id=snapshot.snapshot_id,as_of=at)
    receipt,_=fresh();evaluator=DeploymentEvaluator(sessions)
    evaluation=evaluator.evaluate(active.deployment_id,request,receipt.reconciliation_id,store)
    return active,evaluator,evaluation,request


def test_evaluation_programs_idempotent_preparation_and_no_implicit_approval(desk,monkeypatch):
    active,evaluator,evaluation,request=evaluated(desk,monkeypatch)
    repo,broker,fresh,_,sessions,terms,(_,store,_)=desk
    receipt,_=fresh()
    duplicate=evaluator.evaluate(active.deployment_id,request,receipt.reconciliation_id,store)
    assert duplicate.evaluation_id==evaluation.evaluation_id
    from datetime import timezone
    equivalent=request.model_copy(update={"as_of":request.as_of.astimezone(timezone.utc)})
    assert evaluator.evaluate(active.deployment_id,equivalent,receipt.reconciliation_id,store).evaluation_id==evaluation.evaluation_id
    assert evaluation.payload["status"]=="targets"
    row=next(r for r in evaluation.payload["portfolio"] if r["delta_quantity"]>0)
    prepare=DeploymentTargetInput(**action(active).model_dump(),evaluation_id=evaluation.evaluation_id,instrument_id=row["instrument_id"],limit_price_usd="100.00")
    receipt,_=fresh();order=evaluator.prepare(active.deployment_id,prepare,receipt.reconciliation_id)
    receipt,_=fresh();same=evaluator.prepare(active.deployment_id,prepare,receipt.reconciliation_id)
    assert order.intent_id==same.intent_id and order.state=="previewed" and broker.economic_orders==0
    assert order.order["quantity"]==row["delta_quantity"]
    with sessions() as session:
        assert len(list(session.exec(select(DeploymentEvaluationRecord))))==1
        assert len(list(session.exec(select(DeploymentOrderTargetRecord))))==1
        assert len(list(session.exec(select(ExecutionProgramRecord))))==sum(bool(r["delta_quantity"]) for r in evaluation.payload["portfolio"])
        assert not list(session.exec(select(PaperExecutionAttemptRecord)))
    receipt,_=fresh()
    with pytest.raises(ConflictError,match="repriced"):
        evaluator.prepare(active.deployment_id,prepare.model_copy(update={"limit_price_usd":D(101)}),receipt.reconciliation_id)


def test_missing_data_is_saved_and_pauses_without_selling(desk,monkeypatch):
    active,_,evaluation,_=evaluated(desk,monkeypatch,missing=True)
    repo,broker,*_=desk
    detail=repo.detail(active.deployment_id)
    assert evaluation.payload["status"]=="unavailable"
    assert detail["deployment"].state=="paused" and detail["deployment"].active_terms_id==active.active_terms_id
    assert len(detail["evaluations"])==1 and not detail["programs"] and not detail["orders"] and broker.economic_orders==0


def test_fixture_snapshot_rejected_before_target_creation(desk,monkeypatch):
    active=activate(desk,monkeypatch)
    _,_,fresh,_,sessions,_,(_,store,job)=desk
    receipt,_=fresh()
    request=DeploymentEvaluationInput(**action(active).model_dump(),snapshot_id=job.snapshot_id,as_of=now_utc())
    with pytest.raises(ConflictError,match="prospective snapshot"):
        DeploymentEvaluator(sessions).evaluate(active.deployment_id,request,receipt.reconciliation_id,store)


def test_reductions_must_fill_and_reconcile_before_buys(desk,monkeypatch):
    active=activate(desk,monkeypatch)
    _,broker,fresh,_,sessions,_,(research,store,_)=desk
    boundary,opening,exact=target_order(desk,active,quantity=40)
    _,account=fresh();attempt,_=boundary.claim(opening.order_id,account)
    boundary.observe(attempt.attempt_id,broker.submit_exact_order(opening.intent_id,exact))
    boundary.observe(attempt.attempt_id,broker.fill(opening.intent_id,40))
    source,at=current_fixture(research,store,expensive_equity=True)
    evaluator=DeploymentEvaluator(sessions);receipt,_=fresh()
    evaluation=evaluator.evaluate(active.deployment_id,DeploymentEvaluationInput(**action(active).model_dump(),snapshot_id=source.snapshot_id,as_of=at),receipt.reconciliation_id,store)
    rows=evaluation.payload["portfolio"]
    sell=next(r for r in rows if r["delta_quantity"]<0);buy=next(r for r in rows if r["delta_quantity"]>0)
    def prepare(row):
        receipt,_=fresh()
        return evaluator.prepare(active.deployment_id,DeploymentTargetInput(**action(active).model_dump(),evaluation_id=evaluation.evaluation_id,instrument_id=row["instrument_id"],limit_price_usd="100.00"),receipt.reconciliation_id)
    with pytest.raises(ConflictError,match="reductions"):
        prepare(buy)
    sale=prepare(sell);boundary.approve(sale.order_id,"operator",sale.content_hash)
    _,account=fresh();attempt,_=boundary.claim(sale.order_id,account)
    from tradingagents.research.execution_contracts import ExactPaperOrder
    boundary.observe(attempt.attempt_id,broker.submit_exact_order(sale.intent_id,ExactPaperOrder.model_validate(sale.order)))
    boundary.observe(attempt.attempt_id,broker.fill(sale.intent_id,1))
    with pytest.raises(ConflictError,match="reductions"):
        prepare(buy)
    boundary.observe(attempt.attempt_id,broker.fill(sale.intent_id,sale.order["quantity"]-1))
    purchase=prepare(buy)
    assert purchase.state=="previewed" and broker.economic_orders==2
    # A fresh account approval/claim still needs to occur for this separate buy.
    assert boundary.attempt_for_order(purchase.order_id) is None


def test_saved_window_rechecked_at_claim(desk,monkeypatch):
    active,evaluator,evaluation,_=evaluated(desk,monkeypatch)
    _,broker,fresh,_,sessions,_,(_,store,_)=desk
    row=next(r for r in evaluation.payload["portfolio"] if r["delta_quantity"]>0)
    receipt,_=fresh()
    request=DeploymentTargetInput(**action(active).model_dump(),evaluation_id=evaluation.evaluation_id,instrument_id=row["instrument_id"],limit_price_usd="100.00")
    order=evaluator.prepare(active.deployment_id,request,receipt.reconciliation_id)
    from tradingagents.research.execution_repository import PaperExecutionRepository
    boundary=PaperExecutionRepository(sessions);boundary.approve(order.order_id,"operator",order.content_hash)
    monkeypatch.setattr("tradingagents.research.deployment_evaluation.now_utc",lambda:datetime.fromisoformat(evaluation.payload["execution_deadline"])+timedelta(seconds=1))
    _,account=fresh()
    with pytest.raises(ConflictError,match="opening window"):
        boundary.claim(order.order_id,account)
    assert boundary.attempt_for_order(order.order_id) is None and broker.economic_orders==0


def test_newer_evaluation_revokes_old_target_at_claim(desk,monkeypatch):
    active,evaluator,evaluation,_=evaluated(desk,monkeypatch)
    _,broker,fresh,_,sessions,*_=desk
    row=next(r for r in evaluation.payload["portfolio"] if r["delta_quantity"]>0)
    receipt,_=fresh()
    order=evaluator.prepare(active.deployment_id,DeploymentTargetInput(**action(active).model_dump(),evaluation_id=evaluation.evaluation_id,instrument_id=row["instrument_id"],limit_price_usd="100.00"),receipt.reconciliation_id)
    from tradingagents.research.execution_repository import PaperExecutionRepository
    boundary=PaperExecutionRepository(sessions);boundary.approve(order.order_id,"operator",order.content_hash)
    with sessions() as session:
        session.add(DeploymentEvaluationRecord(deployment_id=active.deployment_id,terms_id=active.active_terms_id,
            request_hash="f"*64,payload={**evaluation.payload,"status":"unavailable","reason":"synthetic replacement observation"}))
        session.commit()
    _,account=fresh()
    with pytest.raises(ConflictError,match="newer portfolio evaluation"):
        boundary.claim(order.order_id,account)
    assert boundary.attempt_for_order(order.order_id) is None and broker.economic_orders==0
