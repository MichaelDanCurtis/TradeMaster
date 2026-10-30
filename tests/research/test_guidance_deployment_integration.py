"""Local-only protocol fixture. Qualified evidence is stubbed, not established.

No real provider data or account is used. The test exercises actual persistence,
exact approvals, fixture fills and guidance reconstruction across evaluations.
"""
from datetime import datetime,timedelta,time
from decimal import Decimal as D
from zoneinfo import ZoneInfo
import hashlib
import time as clock_time
import pytest

from sqlmodel import select

from tests.research.test_deployment import desk,qualified,action,approve
from tests.research.conftest import plan_payload
from tradingagents.research.contracts import StrategyDraft,FreezeVersion,ResearchPlanInput,ExperimentInput,SnapshotManifest
from tradingagents.research.data.guidance_fixture import fixture_guidance_spec,save_guidance_fixture
from tradingagents.research.data.contracts import DatasetBundle
from tradingagents.research.deployment_contracts import DeploymentInput,DeploymentEvaluationInput,DeploymentTargetInput
from tradingagents.research.deployment_evaluation import DeploymentEvaluator
from tradingagents.research.deployment_guidance_state import restore_guidance_context
from tradingagents.research.execution_contracts import PaperAccountIdentity,ExactPaperOrder
from tradingagents.research.execution_repository import PaperExecutionRepository
from tradingagents.research.deployment_service import DeploymentService
from tradingagents.ui.models import now_utc


def setup_guidance(desk,monkeypatch):
    repo,broker,fresh,_,sessions,terms,(research,store,job)=desk
    qualified(monkeypatch)
    strategy=research.create_strategy(StrategyDraft(name="Guidance protocol fixture",hypothesis="Synthetic guidance-state acceptance",rationale="No investment inference"))
    specs=[fixture_guidance_spec(arm) for arm in ("guidance_control","numeric_quality","astra_challenger")]
    for spec in specs: spec.universe=spec.universe[:1]
    versions=[research.freeze_version(strategy.strategy_id,FreezeVersion(spec=spec)) for spec in specs]
    payload=plan_payload(strategy.strategy_id,versions[0].version_id)
    payload.update(family_id="guidance_protocol",version_ids=[v.version_id for v in versions])
    plan=research.freeze_plan(ResearchPlanInput.model_validate(payload))
    research_snapshot=research.register_snapshot(save_guidance_fixture(store))
    experiment=research.queue_experiment(ExperimentInput(plan_id=plan.plan_id,snapshot_id=research_snapshot.snapshot_id,idempotency_key="guidance_protocol"))
    terms=terms.model_copy(update={"execution_policy":terms.execution_policy.model_copy(update={"max_position_fraction":D('.2'),"max_group_fraction":D('.8')})})
    identity=PaperAccountIdentity(provider_id="fake",account_id="fixture-paper-account")
    active=repo.create(DeploymentInput(name="Guidance protocol",version_id=versions[0].version_id,experiment_id=experiment.experiment_id,account=identity,terms=terms,idempotency_key="guidance_dep"))
    receipt,_=fresh();review=repo.review(active.deployment_id,action(active),receipt.reconciliation_id)
    receipt,_=fresh();active=repo.activate(active.deployment_id,approve(review),receipt.reconciliation_id)
    return active,specs[0]


def observed(at,revision):
    return dict(mode="observed",event_time=at,published_at=at,ingested_at=at,processed_at=at,available_at=at,revision=revision)


def protocol_data(at):
    zone=ZoneInfo("America/New_York");day=at.astimezone(zone).date()
    sessions=[]
    for offset in range(-50,75):
        date=day+timedelta(days=offset)
        if date==day:
            sessions.append(dict(date=date,opens_at=at+timedelta(seconds=2),closes_at=at+timedelta(minutes=3)))
        elif date.weekday()<5:
            sessions.append(dict(date=date,opens_at=datetime.combine(date,time(9,30),zone),closes_at=datetime.combine(date,time(16),zone)))
    bars=[dict(instrument_id="sim-clean",session=s["date"],open=100,high=101,low=99,close=100,volume=1000000,
               available_at=s["closes_at"]+timedelta(seconds=1)) for s in sessions if s["date"]<day]
    docs=[];facts=[];notices=[]
    for name,published,low,high in (("prior",at-timedelta(days=2),90,110),("raise",at,110,130)):
        text=f"Synthetic {name} guidance USD {low} to {high}."
        availability=observed(published,name)
        docs.append(dict(document_id=name,text=text,text_hash=hashlib.sha256(text.encode()).hexdigest(),source_url="fixture://"+name,availability=availability))
        for metric,value in (("revenue_guidance_low",low),("revenue_guidance_high",high)):
            facts.append(dict(observation_id=name+metric,instrument_id="sim-clean",metric=metric,period_start=day.replace(month=1,day=1),period_end=day.replace(month=12,day=31),period_type="forecast",value=value,original_value=str(value),unit="USD_millions",reporting_basis="GAAP",document_id=name,availability=availability))
        notices.append(dict(notice_id=name,instrument_id="sim-clean",document_id=name,period_start=day.replace(month=1,day=1),period_end=day.replace(month=12,day=31),reporting_basis="GAAP",state="range",low_observation_id=name+"revenue_guidance_low",high_observation_id=name+"revenue_guidance_high",availability=availability))
    return DatasetBundle(timezone=str(zone),sessions=sessions,bars=bars,mappings=[dict(instrument_id="sim-clean",symbol="SIM-CLEAN",valid_from=sessions[0]["date"],known_at=sessions[0]["opens_at"])],documents=docs,financials=facts,guidance_notices=notices)


def register(research,store,data):
    return research.register_snapshot(SnapshotManifest(provider="synthetic-protocol-test",evidence_kind="prospective",availability="recorded_receipt",
        provenance="Fabricated metadata for guidance infrastructure testing",entitlement="synthetic",calendar="synthetic-calendar",timezone=data.timezone,
        coverage_start=data.sessions[0].date,coverage_end=data.sessions[-1].date,instrument_ids=["sim-clean"],artifacts=store.put_dataset(data)))


def test_persisted_entry_actual_fill_clock_and_withdrawal_cancellation(desk,monkeypatch):
    active,spec=setup_guidance(desk,monkeypatch)
    repo,broker,fresh,_,sessions,_,(research,store,_)=desk
    at=now_utc();data=protocol_data(at);source=register(research,store,data)
    # Honour the frozen one-second processing latency and declared next open.
    clock_time.sleep(2.05)
    evaluator=DeploymentEvaluator(sessions);receipt,_=fresh()
    evaluation=evaluator.evaluate(active.deployment_id,DeploymentEvaluationInput(**action(active).model_dump(),snapshot_id=source.snapshot_id,as_of=at+timedelta(seconds=1)),receipt.reconciliation_id,store)
    assert evaluation.payload["entry_notice_ids"]=={"sim-clean":"raise"},evaluation.payload["reason"]
    receipt,_=fresh();order=evaluator.prepare(active.deployment_id,DeploymentTargetInput(**action(active).model_dump(),evaluation_id=evaluation.evaluation_id,instrument_id="sim-clean",limit_price_usd=100),receipt.reconciliation_id)
    boundary=PaperExecutionRepository(sessions);boundary.approve(order.order_id,"fixture operator",order.content_hash)
    _,account=fresh();attempt,_=boundary.claim(order.order_id,account)
    boundary.observe(attempt.attempt_id,broker.submit_exact_order(order.intent_id,ExactPaperOrder.model_validate(order.order)))
    boundary.observe(attempt.attempt_id,broker.fill(order.intent_id,1))
    receipt,account=fresh()
    with sessions() as session:
        ctx,_=restore_guidance_context(session,active,spec,receipt,account,data,now_utc())
    assert ctx.consumed_notices=={"raise"}
    assert ctx.holding_clocks["sim-clean"]["notice_id"]=="raise"
    assert ctx.holding_clocks["sim-clean"]["entry_at"]==broker.activities[0].effective_at
    assert ctx.pending_entries=={"sim-clean"}
    # A later withdrawal is a distinct source, not a rewrite of the entry.
    withdrawal=data.guidance_notices[-1].model_copy(update={"notice_id":"withdrawal","document_id":"withdrawal","state":"withdrawn","low_observation_id":None,"high_observation_id":None,"availability":data.guidance_notices[-1].availability.model_copy(update={"revision":"withdrawal","event_time":now_utc(),"published_at":now_utc(),"ingested_at":now_utc(),"processed_at":now_utc(),"available_at":now_utc()})})
    text="Synthetic withdrawal of guidance"
    from tradingagents.research.data.contracts import SourceDocument
    data.documents.append(SourceDocument(document_id="withdrawal",text=text,text_hash=hashlib.sha256(text.encode()).hexdigest(),source_url="fixture://withdrawal",availability=withdrawal.availability))
    data.guidance_notices.append(withdrawal)
    # Evaluate after this synthetic session's close against the next opening.
    current=data.sessions[next(i for i,s in enumerate(data.sessions) if s.opens_at>at)]
    cutoff=current.closes_at+timedelta(seconds=1)
    from tradingagents.research.data.contracts import MarketBar
    data.bars.append(MarketBar(instrument_id="sim-clean",session=current.date,open=100,high=101,low=99,close=100,volume=1000000,available_at=cutoff))
    source=register(research,store,data)
    monkeypatch.setattr("tradingagents.research.deployment_evaluation.now_utc",lambda:cutoff)
    receipt,_=fresh()
    changed_request=DeploymentEvaluationInput(**action(active).model_dump(),snapshot_id=source.snapshot_id,as_of=cutoff)
    changed=evaluator.evaluate(active.deployment_id,changed_request,receipt.reconciliation_id,store)
    assert changed.payload["status"]=="targets",changed.payload["reason"]
    assert changed.payload["cancel_entries"]==["sim-clean"] and changed.payload["exit_reasons"]["sim-clean"].startswith("withdrawn")
    assert changed.payload["guidance_state"]["holding_clocks"]["sim-clean"]["entry_at"]==broker.activities[0].effective_at.isoformat()
    service=DeploymentService(sessions,broker)
    # Reuse the test's fabricated broker-paper reconciliation. Production
    # service observation remains covered separately by accounting API tests.
    monkeypatch.setattr(service,"observe",lambda _:receipt)
    monkeypatch.setattr("tradingagents.research.deployment_repository.now_utc",lambda:cutoff)
    result=service.evaluate(active.deployment_id,changed_request,store)
    assert result["cancellations"][0]["state"]=="canceled" and broker.economic_orders==1
    assert result["evaluation"].evaluation_id==changed.evaluation_id
    altered="Rewritten previously observed document"
    data.documents[0]=data.documents[0].model_copy(update={"text":altered,"text_hash":hashlib.sha256(altered.encode()).hexdigest()})
    with sessions() as session,pytest.raises(ValueError,match="retained unchanged"):
        restore_guidance_context(session,active,spec,receipt,account,data,cutoff)
