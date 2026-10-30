"""Lifecycle infrastructure uses synthetic observations, never a real account.

Positive lifecycle cases stub only the evidence assessment to isolate funding
and authority behavior. The unstubbed fixture gate is tested separately.
"""
from datetime import timedelta
from decimal import Decimal as D

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from tradingagents.research.accounting_contracts import AccountActivityBatch, AccountingReconciliation
from tradingagents.research.accounting_repository import PaperAccountingRepository
from tradingagents.research.deployment_contracts import DeploymentInput, DeploymentTerms, DeploymentAction, DeploymentApproval, CapitalRevision
from tradingagents.research.deployment_models import StrategyDeploymentRecord, DeploymentEvaluationRecord, DeploymentOrderTargetRecord
from tradingagents.research.deployment_repository import DeploymentRepository, funding_capacity
from tradingagents.research.deployment_service import DeploymentService
from tradingagents.research.execution_contracts import ExactPaperOrder, PaperAccountIdentity, AccountPosition
from tradingagents.research.execution_repository import PaperExecutionRepository
from tradingagents.research.contracts import content_hash
from tradingagents.research.repository import ConflictError, ResearchRepository
from tradingagents.research.worker import ResearchWorker
from tradingagents.ui.brokers.fake import FakePaperBroker
from tradingagents.ui.db import create_session_factory, init_db
from tradingagents.ui.events import RunConfig
from tradingagents.ui.models import now_utc
from tradingagents.ui.repository import UiRepository
from tests.research.test_worker import queue_fixture


@pytest.fixture
def desk(tmp_path):
    engine,sessions=create_session_factory(f"sqlite:///{tmp_path/'deployment.db'}");init_db(engine)
    research=ResearchRepository(sessions)
    store,job,version=queue_fixture(research,tmp_path)
    broker=FakePaperBroker()
    accounting=PaperAccountingRepository(sessions)
    # Protocol-shaped broker-paper evidence here is fabricated ONLY inside
    # this test, so positive transition checks do not need remote credentials.
    opening=broker.paper_snapshot().model_copy(update={"evidence_kind":"broker_paper"})
    preview=accounting.preview_baseline(opening)
    accounting.approve_baseline(preview.baseline_id,preview.content_hash,"test operator")
    terms=DeploymentTerms(capital_usd=10000,execution_policy={"max_position_fraction":".5","max_group_fraction":".6","max_turnover_fraction":"1","max_drawdown_fraction":".2","cash_reserve_fraction":".1"},
        fee_reserve_per_order_usd=1,fee_assumption_reference="Synthetic $1 execution fee",funding_rationale="Test envelope")
    repo=DeploymentRepository(sessions)
    def fresh():
        snapshot=broker.paper_snapshot().model_copy(update={"evidence_kind":"broker_paper"})
        batch=AccountActivityBatch(provider_id=snapshot.provider_id,account_id=snapshot.account_id,evidence_kind="broker_paper",coverage_start=opening.observed_at,
            coverage_end=snapshot.observed_at,observed_at=now_utc(),complete=True,source="Synthetic unit-test observation",activities=list(broker.activities))
        return accounting.reconcile(AccountingReconciliation(snapshot=snapshot,batch=batch)),snapshot
    def create(key="first",capital=10000):
        return repo.create(DeploymentInput(name=key,version_id=version.version_id,experiment_id=job.experiment_id,
            account=PaperAccountIdentity(provider_id=opening.provider_id,account_id=opening.account_id),
            terms=terms.model_copy(update={"capital_usd":D(capital)}),idempotency_key=key))
    return repo,broker,fresh,create,sessions,terms,(research,store,job)


def qualified(monkeypatch):
    monkeypatch.setattr(DeploymentRepository,"_evidence",staticmethod(lambda *_:{"gates":[{"name":"stubbed_qualified_evidence","passed":True,"detail":"Test lifecycle only"}],"version_hash":"1"*64,"evidence_hash":"2"*64}))


def action(record,reason="Test lifecycle action"):
    return DeploymentAction(actor="test operator",reason=reason,expected_revision=record.revision)


def approve(review):
    return DeploymentApproval(actor="test operator",reason="Approve exactly reviewed paper terms",expected_revision=review.deployment_revision,review_id=review.review_id,expected_hash=review.content_hash)


def activate(desk,monkeypatch,key="first",capital=10000):
    qualified(monkeypatch)
    repo,_,fresh,create,*_=desk
    record=create(key,capital);receipt,_=fresh()
    review=repo.review(record.deployment_id,action(record),receipt.reconciliation_id)
    receipt,_=fresh()
    return repo.activate(record.deployment_id,approve(review),receipt.reconciliation_id)


def test_fixture_evidence_can_be_reviewed_but_cannot_activate(desk):
    repo,_,fresh,create,_,_,(research,store,job)=desk
    ResearchWorker(research,store).run_once()
    assert research.experiment(job.experiment_id).result["evidence_status"]=="fixture_only"
    record=create();receipt,_=fresh()
    review=repo.review(record.deployment_id,action(record),receipt.reconciliation_id)
    assert not review.payload["eligible"]
    assert {g["name"] for g in review.payload["gates"] if not g["passed"]}>={"eligible_version","genuine_holdout"}
    with pytest.raises(ConflictError,match="not met"):
        repo.activate(record.deployment_id,approve(review),receipt.reconciliation_id)


def test_idempotent_draft_and_immutable_version_review_terms(desk):
    repo,_,fresh,create,sessions,*_=desk
    record=create();assert create().deployment_id==record.deployment_id
    with pytest.raises(ConflictError,match="idempotency"):
        create(capital=9000)
    receipt,_=fresh();review=repo.review(record.deployment_id,action(record),receipt.reconciliation_id)
    with sessions() as session:
        for statement in ("UPDATE research_promotion_reviews SET content_hash='changed'", "DELETE FROM research_deployment_terms", "UPDATE research_deployments SET version_id='other'"):
            with pytest.raises(IntegrityError,match="immutable"):
                session.execute(text(statement));session.commit()
            session.rollback()


def test_competing_envelopes_are_rechecked_in_activation_transaction(desk,monkeypatch):
    qualified(monkeypatch)
    repo,_,fresh,create,*_=desk
    a,b=create("A",70000),create("B",40000)
    first,_=fresh();ra=repo.review(a.deployment_id,action(a),first.reconciliation_id)
    second,_=fresh();rb=repo.review(b.deployment_id,action(b),second.reconciliation_id)
    assert ra.payload["eligible"] and rb.payload["eligible"]
    third,_=fresh();repo.activate(a.deployment_id,approve(ra),third.reconciliation_id)
    fourth,_=fresh()
    with pytest.raises(ConflictError,match="already allocated"):
        repo.activate(b.deployment_id,approve(rb),fourth.reconciliation_id)


def test_account_change_and_wrong_review_hash_do_not_activate(desk,monkeypatch):
    qualified(monkeypatch)
    repo,broker,fresh,create,*_=desk
    record=create();receipt,_=fresh();review=repo.review(record.deployment_id,action(record),receipt.reconciliation_id)
    with pytest.raises(ConflictError,match="displayed"):
        repo.activate(record.deployment_id,approve(review).model_copy(update={"expected_hash":"0"*64}),receipt.reconciliation_id)
    # Buying power changes without inventing a cash-flow event.
    original=broker.paper_snapshot
    monkeypatch.setattr(broker,"paper_snapshot",lambda:original().model_copy(update={"buying_power_usd":D(99999)}))
    changed,_=fresh()
    with pytest.raises(ConflictError,match="economics changed"):
        repo.activate(record.deployment_id,approve(review),changed.reconciliation_id)


def test_pause_amend_resume_retire_keep_prior_terms_and_require_fresh_review(desk,monkeypatch):
    repo,_,fresh,_,_,terms,*_=desk
    active=activate(desk,monkeypatch)
    old_terms=active.active_terms_id
    paused=repo.pause(active.deployment_id,action(active))
    change=CapitalRevision(**action(paused).model_dump(),terms=terms.model_copy(update={"capital_usd":D(15000)}))
    amended=repo.change_capital(active.deployment_id,change)
    assert amended.active_terms_id==old_terms and amended.pending_terms_id!=old_terms
    receipt,_=fresh();review=repo.review(active.deployment_id,action(amended),receipt.reconciliation_id)
    receipt,_=fresh()
    with pytest.raises(ConflictError,match="Use resume"):
        repo.activate(active.deployment_id,approve(review),receipt.reconciliation_id)
    resumed=repo.activate(active.deployment_id,approve(review),receipt.reconciliation_id,resume=True)
    assert resumed.active_terms_id!=old_terms
    paused=repo.pause(active.deployment_id,action(resumed));receipt,_=fresh()
    retired=repo.retire(active.deployment_id,action(paused),receipt.reconciliation_id)
    assert retired.state=="retired"
    with pytest.raises(ConflictError,match="Pause an active"):
        repo.review(active.deployment_id,action(retired),receipt.reconciliation_id)


def target_order(desk,active,*,side="buy",quantity=30):
    _,_,fresh,_,sessions,terms,*_=desk
    exact=ExactPaperOrder(symbol="SIM-EQ",side=side,quantity=quantity,limit_price_usd=100,fee_reserve_usd=1,risk_group="equity",expires_at=now_utc()+timedelta(minutes=5))
    receipt,_=fresh()
    current=int(next((p["owners"].get(f"deployment:{active.deployment_id}","0") for p in receipt.report["positions"] if p["symbol"]=="SIM-EQ"),"0"))
    delta=quantity if side=="buy" else -quantity
    with sessions() as session:
        evaluation=DeploymentEvaluationRecord(deployment_id=active.deployment_id,terms_id=active.active_terms_id,request_hash=content_hash(exact),payload={
            "test":"synthetic evaluator output for execution boundary isolation","schema_version":1,"status":"targets",
            "execution_opens_at":(now_utc()-timedelta(seconds=1)).isoformat(),"execution_deadline":exact.expires_at.isoformat(),
            "portfolio":[{"instrument_id":"us-sim-eq","symbol":"SIM-EQ","current_quantity":current,"desired_quantity":current+delta,"delta_quantity":delta}]})
        session.add(evaluation);session.flush()
        target=DeploymentOrderTargetRecord(evaluation_id=evaluation.evaluation_id,deployment_id=active.deployment_id,terms_id=active.active_terms_id,content_hash=content_hash(exact),order=exact.model_dump(mode="json"))
        session.add(target);session.commit()
    run=UiRepository(sessions).create_run(RunConfig(ticker="SIM-EQ",trade_date="2026-09-04",broker_mode="paper"))
    _,snapshot=fresh();boundary=PaperExecutionRepository(sessions)
    order=boundary.preview(None,exact,terms.execution_policy,snapshot,run_id=run.run_id,budget=quantity*100+1,deployment_id=active.deployment_id,target_id=target.target_id)
    boundary.approve(order.order_id,"test operator",order.content_hash)
    return boundary,order,exact


def test_old_approved_ticket_cannot_bypass_pause_at_submission(desk,monkeypatch):
    repo,_,fresh,*_=desk
    active=activate(desk,monkeypatch)
    boundary,order,_=target_order(desk,active)
    repo.pause(active.deployment_id,action(active))
    _,snapshot=fresh()
    with pytest.raises(ConflictError,match="paused"):
        boundary.claim(order.order_id,snapshot)
    assert boundary.attempt_for_order(order.order_id) is None


def test_pause_cancels_entry_and_keeps_state_when_transport_fails(desk,monkeypatch):
    repo,broker,fresh,_,sessions,*_=desk
    active=activate(desk,monkeypatch)
    boundary,order,exact=target_order(desk,active)
    _,snapshot=fresh();attempt,_=boundary.claim(order.order_id,snapshot)
    boundary.observe(attempt.attempt_id,broker.submit_exact_order(order.intent_id,exact))
    monkeypatch.setattr(broker,"cancel_exact_order",lambda *_:(_ for _ in ()).throw(TimeoutError()))
    result=DeploymentService(sessions,broker).pause(active.deployment_id,action(active))
    assert result["deployment"].state=="paused"
    assert result["cancellations"][0]["state"]=="pending_cancel"
    assert boundary.attempt_for_order(order.order_id).state=="accepted"
    assert broker.economic_orders==1


def test_manual_order_cannot_spend_committed_deployment_capital(desk,monkeypatch):
    _,_,fresh,_,sessions,terms,*_=desk
    activate(desk,monkeypatch,capital=90000)
    run=UiRepository(sessions).create_run(RunConfig(ticker="AAA",trade_date="2026-09-04",broker_mode="paper"))
    exact=ExactPaperOrder(symbol="AAA",side="buy",quantity=120,limit_price_usd=100,expires_at=now_utc()+timedelta(minutes=5))
    _,snapshot=fresh()
    with pytest.raises(ConflictError,match="Manual entry"):
        PaperExecutionRepository(sessions).preview(None,exact,terms.execution_policy,snapshot,run_id=run.run_id,budget=12000)


def test_funding_counts_manual_holdings_and_other_deployment_overruns(desk,monkeypatch):
    repo,_,fresh,_,sessions,*_=desk
    active=activate(desk,monkeypatch,capital=10000)
    receipt,snapshot=fresh()
    snapshot.positions=[AccountPosition(symbol="AAA",quantity=2,market_value_usd=20000,cost_basis_usd=20000),AccountPosition(symbol="BBB",quantity=3,market_value_usd=30000,cost_basis_usd=30000)]
    report={"positions":[{"symbol":"AAA","owners":{"manual":"2"}},{"symbol":"BBB","owners":{f"deployment:{active.deployment_id}":"3"}}]}
    with sessions() as session:
        capacity=funding_capacity(session,active.account_key,snapshot,report,D(50001))
    assert capacity.other_envelopes_usd==30000 and capacity.unallocated_holdings_usd==20000
    assert capacity.available_envelope_usd==50000 and not capacity.allowed


def test_concurrent_activations_cannot_double_allocate_equity(desk,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    qualified(monkeypatch)
    repo,_,fresh,create,*_=desk
    reviews=[]
    for name in ("one","two"):
        record=create(name,70000);receipt,_=fresh()
        reviews.append((record,repo.review(record.deployment_id,action(record),receipt.reconciliation_id)))
    latest,_=fresh()
    def attempt(item):
        record,review=item
        try: return repo.activate(record.deployment_id,approve(review),latest.reconciliation_id).state
        except ConflictError: return "blocked"
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt,reviews))==["blocked","paper_active"]


def test_paused_deployment_can_reduce_owned_shares_but_cannot_retire_with_holdings(desk,monkeypatch):
    repo,broker,fresh,*_=desk
    active=activate(desk,monkeypatch)
    boundary,order,exact=target_order(desk,active)
    _,snapshot=fresh();attempt,_=boundary.claim(order.order_id,snapshot)
    boundary.observe(attempt.attempt_id,broker.submit_exact_order(order.intent_id,exact))
    boundary.observe(attempt.attempt_id,broker.fill(order.intent_id,30))
    paused=repo.pause(active.deployment_id,action(active));receipt,_=fresh()
    with pytest.raises(ConflictError,match="holdings"):
        repo.retire(active.deployment_id,action(paused),receipt.reconciliation_id)
    _,sell,_=target_order(desk,paused,side="sell",quantity=10)
    _,snapshot=fresh()
    claimed,first=boundary.claim(sell.order_id,snapshot)
    assert first and claimed.state=="dispatching"


def test_funding_amendment_cannot_loosen_strategy_limits(desk):
    repo,_,_,create,_,terms,*_=desk
    record=create()
    looser=terms.model_copy(deep=True);looser.execution_policy.max_position_fraction=D(".6")
    with pytest.raises(ConflictError,match="loosen"):
        repo.change_capital(record.deployment_id,CapitalRevision(**action(record).model_dump(),terms=looser))


def test_repeated_target_preparation_reuses_the_same_intent(desk,monkeypatch):
    _,_,fresh,_,sessions,terms,*_=desk
    active=activate(desk,monkeypatch)
    boundary,order,exact=target_order(desk,active)
    run_id=UiRepository(sessions).get_trade_intent(order.intent_id).run_id
    _,snapshot=fresh()
    repeated=boundary.preview(None,exact,terms.execution_policy,snapshot,run_id=run_id,budget=3001,deployment_id=active.deployment_id,target_id=order.target_id)
    assert repeated.intent_id==order.intent_id and repeated.order_id==order.order_id
    with pytest.raises(ConflictError,match="different exact"):
        boundary.preview(None,exact.model_copy(update={"limit_price_usd":D(101)}),terms.execution_policy,snapshot,run_id=run_id,budget=3031,deployment_id=active.deployment_id,target_id=order.target_id)
