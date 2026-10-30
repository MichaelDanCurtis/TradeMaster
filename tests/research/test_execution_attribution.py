from datetime import datetime,timedelta,timezone
from decimal import Decimal as D

from fastapi.testclient import TestClient
import pytest

from tests.research.test_deployment import desk,action,activate
from tests.research.test_deployment_evaluation import evaluated
from tradingagents.research.deployment_contracts import DeploymentTargetInput
from tradingagents.research.deployment_models import DeploymentEvaluationRecord
from tradingagents.research.execution_models import ExactPaperOrderRecord,PaperExecutionAttemptRecord,PaperExecutionEventRecord
from tradingagents.research.execution_attribution import _row,execution_attribution
from tradingagents.research.execution_repository import PaperExecutionRepository
from tradingagents.ui.models import ApprovalRecord


def timeline(*,side='buy',state='canceled',reconciled=True,cancel_pending=False,mixed_timezones=False):
    at=datetime(2026,1,5,15,tzinfo=timezone.utc)
    def tick(n): return at+timedelta(seconds=n)
    delta=10 if side=='buy' else -10
    proposal={'instrument_id':'us-example','symbol':'EXAMPLE','current_quantity':0 if side=='buy' else 10,'desired_quantity':10 if side=='buy' else 0,'delta_quantity':delta,'reference_price_usd':'100'}
    evaluation=DeploymentEvaluationRecord(deployment_id='dep',terms_id='terms',request_hash='a'*64,created_at=at,payload={'as_of':tick(-60).isoformat(),'execution_opens_at':tick(35).isoformat(),'execution_deadline':tick(335).isoformat()})
    order=ExactPaperOrderRecord(order_id='order',intent_id='intent',account_key='account',content_hash='b'*64,order={'quantity':10,'side':side,'expires_at':tick(3600).isoformat()},policy={},preview_snapshot={},state='pending_cancel' if cancel_pending else state,created_at=tick(10))
    approvals=[ApprovalRecord(approval_id=f'approval{n}',intent_id='intent',action='approve_order',actor='human',after_payload={'status':'approved','order_hash':order.content_hash},created_at=tick(n)) for n in (20,30)]
    attempt=PaperExecutionAttemptRecord(order_id='order',account_key='account',client_order_id='intent',approval_id='approval30',broker_order_id='native',state=state,filled_quantity='3',created_at=tick(40))
    events=[PaperExecutionEventRecord(order_id='order',kind='broker_observed',payload={'observation':{'status':'accepted'}},created_at=tick(45))]
    fills=[{'source_id':'fill','broker_order_id':'native','symbol':'EXAMPLE','side':side,'quantity':'3','price_usd':'102' if side=='buy' else '98','fee_usd':'1','effective_at':tick(50).isoformat(),'executor':'deployment:dep'}]
    if mixed_timezones:
        fills[0]['quantity']='2'
        fills.append({**fills[0],'source_id':'second','quantity':'1','fee_usd':'0','effective_at':'2026-01-05T11:01:00-04:00'})
    return _row(evaluation,proposal,order,attempt,events,approvals,fills,reconciled,tick(100),False)


@pytest.mark.parametrize('side',['buy','sell'])
def test_partial_cancellation_keeps_exact_approval_actual_fills_and_adverse_difference(side):
    row=timeline(side=side)
    assert row['ever_approved_quantity']==row['dispatch_approved_quantity']==10
    assert row['reconciled_fill_quantity']=='3' and row['unfilled_proposed_quantity']=='7'
    assert row['outcome']=='partially_filled_then_canceled'
    assert D(row['filled_price_difference_usd'])==6
    assert D(row['filled_price_difference_plus_fees_usd'])==7
    assert row['delays']['preparation_to_first_approval_seconds']==10
    assert row['delays']['used_approval_to_dispatch_claim_seconds']==10
    assert row['delays']['dispatch_claim_to_broker_observation_seconds']==5
    assert row['delays']['execution_open_to_first_fill_seconds']==15
    assert row['dispatch_approval_id']=='approval30'


def test_unreconciled_account_does_not_publish_fill_cost_or_fill_completion():
    row=timeline(reconciled=False)
    assert row['outcome']=='account_reconciliation_required'
    assert row['reconciled_fill_quantity'] is None and row['filled_price_difference_usd'] is None
    assert row['broker_observed_filled_quantity']=='3' and not row['fills']


def test_unknown_submission_is_not_described_as_rejected():
    assert timeline(state='unknown')['outcome']=='submission_unresolved'


def test_unacknowledged_cancellation_is_distinct_from_terminal_cancellation():
    assert timeline(state='partially_filled',cancel_pending=True)['outcome']=='partially_filled_cancellation_pending'


def test_fill_clock_order_uses_instants_not_iso_string_order():
    row=timeline(mixed_timezones=True)
    assert row['timeline']['first_reconciled_fill_at']=='2026-01-05T15:00:50+00:00'
    assert row['timeline']['last_reconciled_fill_at']=='2026-01-05T11:01:00-04:00'
    assert row['delays']['dispatch_claim_to_first_fill_seconds']==10


def test_negative_clock_interval_is_unavailable_and_exact_zero_is_retained():
    from tradingagents.research.execution_attribution import _seconds
    at=datetime(2026,1,5,tzinfo=timezone.utc)
    assert _seconds(at,at-timedelta(seconds=1)) is None
    assert _seconds(at,None) is None
    assert _seconds(at,at)==0


def test_persisted_proposal_cancel_and_readonly_account_endpoint(desk,monkeypatch):
    from tradingagents.ui.api import create_app
    active,evaluator,evaluation,_=evaluated(desk,monkeypatch)
    sessions=desk[4]
    initial=execution_attribution(sessions,active.deployment_id)
    buy=next(r for r in initial['rows'] if r['side']=='buy')
    assert buy['outcome']=='no_ticket_prepared' and buy['ever_approved_quantity'] is None
    proposal=next(r for r in evaluation.payload['portfolio'] if r['delta_quantity']>0)
    receipt,_=desk[2]()
    exact=evaluator.prepare(active.deployment_id,DeploymentTargetInput(**action(active).model_dump(),evaluation_id=evaluation.evaluation_id,instrument_id=proposal['instrument_id'],limit_price_usd='100'),receipt.reconciliation_id)
    boundary=PaperExecutionRepository(sessions)
    boundary.approve(exact.order_id,'human',exact.content_hash)
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError
    with sessions() as session:
        with pytest.raises(IntegrityError,match='immutable'):
            session.execute(text("UPDATE ui_approvals SET actor='replacement' WHERE intent_id=:intent"),{'intent':exact.intent_id});session.commit()
    approved=next(r for r in execution_attribution(sessions,active.deployment_id)['rows'] if r['side']=='buy')
    assert approved['outcome']=='approved_awaiting_dispatch'
    boundary.request_cancel(exact.order_id,'human')
    app=create_app(str(sessions.kw['bind'].url),broker_providers={'fixture-paper-broker':desk[1]})
    with TestClient(app) as client:
        path=f'/api/paper-accounting/accounts/{active.account_key}/deployments'
        assert client.get(path).json()['deployments'][0]['deployment_id']==active.deployment_id
        response=client.get(f'{path}/{active.deployment_id}/execution-attribution')
        assert response.status_code==200
        row=next(r for r in response.json()['rows'] if r['side']=='buy')
        assert row['outcome']=='canceled_before_dispatch' and row['ever_approved_quantity']==exact.order['quantity']
        assert row['dispatch_approved_quantity'] is None and row['reconciled_fill_quantity']=='0'
        assert client.get(f'/api/paper-accounting/accounts/wrong/deployments/{active.deployment_id}/execution-attribution').status_code==409
        assert client.get(f'/api/research/deployments/{active.deployment_id}/execution-attribution?limit=26').status_code==422
    assert desk[1].economic_orders==0


def test_native_acknowledgment_is_separate_until_fill_activity_reconciles(desk,monkeypatch):
    from tradingagents.research.execution_contracts import ExactPaperOrder
    active,evaluator,evaluation,_=evaluated(desk,monkeypatch)
    proposal=next(r for r in evaluation.payload['portfolio'] if r['delta_quantity']>0)
    receipt,_=desk[2]()
    order=evaluator.prepare(active.deployment_id,DeploymentTargetInput(**action(active).model_dump(),evaluation_id=evaluation.evaluation_id,instrument_id=proposal['instrument_id'],limit_price_usd='100'),receipt.reconciliation_id)
    boundary=PaperExecutionRepository(desk[4]);boundary.approve(order.order_id,'human',order.content_hash)
    _,snapshot=desk[2]();attempt,_=boundary.claim(order.order_id,snapshot)
    broker=desk[1]
    boundary.observe(attempt.attempt_id,broker.submit_exact_order(order.intent_id,ExactPaperOrder.model_validate(order.order)))
    boundary.observe(attempt.attempt_id,broker.fill(order.intent_id,3))
    row=next(r for r in execution_attribution(desk[4],active.deployment_id)['rows'] if r['side']=='buy')
    assert row['outcome']=='fill_reconciliation_pending' and row['broker_observed_filled_quantity']=='3' and row['reconciled_fill_quantity']=='0'
    boundary.request_cancel(order.order_id,'human')
    boundary.observe(attempt.attempt_id,broker.cancel_exact_order(order.intent_id))
    desk[2]()
    row=next(r for r in execution_attribution(desk[4],active.deployment_id)['rows'] if r['side']=='buy')
    assert row['outcome']=='partially_filled_then_canceled' and row['reconciled_fill_quantity']=='3'
    assert row['unfilled_proposed_quantity']==str(proposal['delta_quantity']-3)
    assert D(row['filled_price_difference_usd'])==3*(D(100)-D(proposal['reference_price_usd']))
    assert row['delays']['dispatch_claim_to_first_fill_seconds']>=0
    assert broker.economic_orders==1


def test_pagination_keeps_earlier_proposals_and_rejects_foreign_cursor(desk,monkeypatch):
    from tradingagents.research.repository import ConflictError
    active,evaluator,evaluation,_=evaluated(desk,monkeypatch)
    later=DeploymentEvaluationRecord(deployment_id=active.deployment_id,terms_id=active.active_terms_id,request_hash='c'*64,payload=evaluation.payload)
    with desk[4]() as session: session.add(later);session.commit()
    first=execution_attribution(desk[4],active.deployment_id,limit=1)
    assert first['next_cursor']==later.evaluation_id
    second=execution_attribution(desk[4],active.deployment_id,limit=1,before=first['next_cursor'])
    assert second['evaluations'][0]['evaluation_id']==evaluation.evaluation_id and second['next_cursor'] is None
    assert next(r for r in second['rows'] if r['side']=='buy')['outcome']=='superseded_without_ticket'
    other=activate(desk,monkeypatch,key='other')
    with pytest.raises(ConflictError,match='another deployment'):
        execution_attribution(desk[4],other.deployment_id,before=evaluation.evaluation_id)
