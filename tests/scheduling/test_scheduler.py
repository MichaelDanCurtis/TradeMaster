from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal as D
from threading import Event
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from tradingagents.ui.db import create_session_factory, init_db
from tradingagents.ui.brokers.fake import FakePaperBroker
from tradingagents.ui.models import now_utc
from tradingagents.research.execution_contracts import ExecutionPolicy
from tradingagents.research.execution_repository import PaperExecutionRepository
from tradingagents.research.execution_service import PaperExecutionService
from tradingagents.research.repository import ConflictError
from tradingagents.scheduling.contracts import ScheduleRequest, ScheduleAction
from tradingagents.scheduling.repository import ScheduleRepository
from tradingagents.scheduling.service import tick


@pytest.fixture
def desk(tmp_path, monkeypatch):
    original = now_utc()
    clock = SimpleNamespace(seconds=0, calls=0)
    def now():
        clock.calls += 1
        return original+timedelta(seconds=clock.seconds, microseconds=clock.calls)
    for path in ('tradingagents.scheduling.repository.now_utc','tradingagents.scheduling.service.now_utc',
                 'tradingagents.research.execution_repository.now_utc','tradingagents.ui.brokers.fake.now_utc'):
        monkeypatch.setattr(path, now)
    engine, sessions = create_session_factory(f'sqlite:///{tmp_path/"scheduler.db"}'); init_db(engine)
    policy = ExecutionPolicy(max_position_fraction=".5",max_group_fraction=".8",max_turnover_fraction=1,max_drawdown_fraction=".1")
    broker = FakePaperBroker(cash_usd="10000")
    request = ScheduleRequest(idempotency_key='first',algorithm='twap',symbol='TEST',side='buy',notional_usd=800,limit_price_usd=100,count=4,duration_minutes=1,start_at=original+timedelta(seconds=30))
    return SimpleNamespace(repo=ScheduleRepository(sessions), execution=PaperExecutionRepository(sessions), broker=broker,
        policy=policy, request=request, clock=clock, sessions=sessions, engine=engine)


def prepare(desk, **updates):
    request=desk.request.model_copy(update=updates)
    return desk.repo.prepare(request,desk.broker.paper_snapshot(),desk.policy)


def act(desk, row, action):
    return desk.repo.action(row.schedule_id,ScheduleAction(action=action,expected_hash=row.content_hash,
        expected_revision=row.revision,actor='test-user'),desk.broker.paper_snapshot() if action=='approve' else None)


def test_exact_schedule_approval_time_fence_and_fill_completion(desk):
    row=prepare(desk)
    detail=desk.repo.detail(row.schedule_id)
    assert [leg['order'].order['quantity'] for leg in detail['legs']] == [2,2,2,2]
    assert row.payload['maximum_notional_usd']=='800.00'
    tick(desk.sessions,lambda:desk.broker)
    assert desk.broker.economic_orders == 0
    first=detail['legs'][0]['order']
    with pytest.raises(ConflictError,match='complete schedule'):
        desk.execution.approve(first.order_id,'manual-bypass',first.content_hash)
    act(desk,row,'approve')
    with pytest.raises(ConflictError,match='not due'):
        PaperExecutionService(desk.execution,desk.broker).submit(first)
    for second in (31,46,61,76):
        desk.clock.seconds=second
        tick(desk.sessions,lambda:desk.broker)
        identifier=list(desk.broker.observations)[-1]
        desk.broker.fill(identifier,2,price=99)
        tick(desk.sessions,lambda:desk.broker)
    detail=desk.repo.detail(row.schedule_id)
    assert detail['schedule'].state=='completed'
    assert desk.broker.economic_orders==4
    assert all(leg['attempt'].filled_quantity=='2' for leg in detail['legs'])
    tick(desk.sessions,lambda:desk.broker)
    assert desk.broker.economic_orders==4


def test_missed_windows_are_canceled_not_caught_up_and_pause_keeps_live_orders(desk):
    row=act(desk,prepare(desk),'approve')
    desk.clock.seconds=31; tick(desk.sessions,lambda:desk.broker)
    assert desk.broker.economic_orders==1
    row=act(desk,row,'pause')
    desk.clock.seconds=33; tick(desk.sessions,lambda:desk.broker)
    assert next(iter(desk.broker.observations.values())).status=='accepted'
    desk.clock.seconds=62
    row=act(desk,row,'resume'); tick(desk.sessions,lambda:desk.broker)
    detail=desk.repo.detail(row.schedule_id)
    assert [leg['order'].state for leg in detail['legs']]==['canceled','canceled','accepted','approved']
    assert desk.broker.economic_orders==2
    row=act(desk,row,'stop'); tick(desk.sessions,lambda:desk.broker)
    assert desk.repo.detail(row.schedule_id)['schedule'].state=='stopped'
    assert all(o.status=='canceled' for o in desk.broker.observations.values())


def test_dca_prices_are_reviewed_limits_and_notional_never_rounds_up(desk):
    row=prepare(desk,algorithm='dca_ladder',notional_usd=D('1000'))
    legs=row.payload['legs']
    assert [p['order']['limit_price_usd'] for p in legs]==['100.00','97.00','94.00','90.00']
    assert sum(D(p['order']['quantity'])*D(p['order']['limit_price_usd']) for p in legs)<=1000
    act(desk,row,'approve'); desk.clock.seconds=31
    tick(desk.sessions,lambda:desk.broker)
    assert desk.broker.economic_orders==4
    desk.clock.seconds=91; tick(desk.sessions,lambda:desk.broker)
    assert desk.repo.detail(row.schedule_id)['schedule'].state=='finished_partial'


def test_preparation_is_atomic_idempotent_and_pinned(desk):
    row=prepare(desk)
    assert prepare(desk).schedule_id==row.schedule_id
    with pytest.raises(ConflictError,match='different schedule'):
        prepare(desk,notional_usd=D('1000'))
    with desk.sessions() as session:
        with pytest.raises(IntegrityError,match='immutable'):
            session.execute(text("UPDATE execution_schedules SET payload='{}'")); session.commit()
    with pytest.raises(ConflictError,match='whole share'):
        prepare(desk,idempotency_key='small',notional_usd=D('10'))
    assert len(desk.repo.listing())==1
    with desk.sessions() as session:
        assert session.execute(text('SELECT count(*) FROM paper_exact_orders')).scalar()==4


def test_pause_and_stale_revision_cannot_be_bypassed_by_manual_submit(desk):
    row=act(desk,prepare(desk),'approve'); stale=row.model_copy()
    row=act(desk,row,'pause'); desk.clock.seconds=31
    with pytest.raises(ConflictError,match='changed'):
        act(desk,stale,'resume')
    order=desk.repo.detail(row.schedule_id)['legs'][0]['order']
    with pytest.raises(ConflictError,match='not active'):
        PaperExecutionService(desk.execution,desk.broker).submit(order)
    assert desk.broker.economic_orders==0


def test_concurrent_workers_never_submit_same_child_twice(desk):
    row=act(desk,prepare(desk),'approve'); desk.clock.seconds=31
    with ThreadPoolExecutor(max_workers=2) as workers:
        results=list(workers.map(lambda _:tick(desk.sessions,lambda:desk.broker),range(2)))
    assert desk.broker.economic_orders==1
    assert len(desk.repo.detail(row.schedule_id)['legs'])==4


def test_ambiguous_submission_pauses_and_restart_reconciles_without_post_retry(desk):
    class LostReply(FakePaperBroker):
        def submit_exact_order(self,*args):
            super().submit_exact_order(*args)
            raise TimeoutError('lost acknowledgement')
    broker=LostReply(cash_usd='10000'); desk.broker=broker
    row=act(desk,prepare(desk),'approve'); desk.clock.seconds=31
    tick(desk.sessions,lambda:broker)
    assert desk.repo.detail(row.schedule_id)['schedule'].state=='paused'
    # New service/repository instance represents a worker reconnect.
    tick(desk.sessions,lambda:broker)
    first=desk.repo.detail(row.schedule_id)['legs'][0]
    assert first['attempt'].state=='accepted' and broker.economic_orders==1
    assert desk.repo.detail(row.schedule_id)['schedule'].state=='paused'


def test_risk_changes_pause_without_sending_and_oversized_schedule_is_rejected(desk):
    with pytest.raises(ConflictError): prepare(desk,notional_usd=D('6000'))
    row=act(desk,prepare(desk),'approve'); desk.clock.seconds=31
    desk.broker.cash_usd=D('1')
    tick(desk.sessions,lambda:desk.broker)
    assert desk.broker.economic_orders==0
    assert desk.repo.detail(row.schedule_id)['schedule'].state=='paused'


def test_stop_keeps_unknown_reservations_until_broker_acknowledges(desk):
    class DelayedCancel(FakePaperBroker):
        def cancel_exact_order(self, client_order_id): return None
    desk.broker=DelayedCancel(cash_usd='10000')
    row=act(desk,prepare(desk),'approve'); desk.clock.seconds=31
    tick(desk.sessions,lambda:desk.broker)
    row=act(desk,row,'stop'); tick(desk.sessions,lambda:desk.broker)
    detail=desk.repo.detail(row.schedule_id)
    assert detail['schedule'].state=='stopping' and detail['legs'][0]['order'].state=='pending_cancel'
    with desk.sessions() as session:
        assert session.execute(text('SELECT count(*) FROM paper_execution_reservations WHERE active=1')).scalar()==1
    assert desk.broker.economic_orders==1


def test_scheduler_api_room_gate_and_no_orders_before_explicit_approval(tmp_path):
    from tradingagents.ui.api import create_app
    broker=FakePaperBroker()
    with TestClient(create_app(f'sqlite:///{tmp_path/"api.db"}',broker_providers={'fixture-paper-broker':broker})) as client:
        assert client.get('/api/execution-schedules').status_code==403
        headers={'x-trademaster-room':'market'}
        request={'idempotency_key':'ui-test','algorithm':'dca_ladder','symbol':'TEST','side':'buy','notional_usd':'1000','limit_price_usd':'100'}
        response=client.post('/api/execution-schedules',headers=headers,json=request)
        assert response.status_code==200,response.text
        assert response.json()['schedule']['state']=='previewed'
        assert broker.economic_orders==0
        assert client.get('/api/execution-schedules/runtime',headers=headers).json()['connected'] is False
        row=response.json()['schedule']
        response=client.post(f'/api/execution-schedules/{row["schedule_id"]}/actions',headers=headers,json={
            'action':'approve','expected_hash':row['content_hash'],'expected_revision':row['revision'],'actor':'test-reviewer'})
        assert response.status_code==200,response.text
        orders=client.get('/api/trades/open').json()['items']
        assert len(orders)==4
        assert all(item['status']=='approved' and item['execution_schedule_id']==row['schedule_id'] for item in orders)


def test_crash_after_claim_before_post_never_becomes_retry(desk):
    row=act(desk,prepare(desk),'approve');desk.clock.seconds=31
    order=desk.repo.detail(row.schedule_id)['legs'][0]['order']
    attempt,claimed=desk.execution.claim(order.order_id,desk.broker.paper_snapshot())
    assert claimed and attempt.state=='dispatching'
    tick(desk.sessions,lambda:desk.broker)
    detail=desk.repo.detail(row.schedule_id)
    assert detail['schedule'].state=='paused'
    assert detail['legs'][0]['attempt'].state=='unknown'
    assert desk.broker.economic_orders==0
    tick(desk.sessions,lambda:desk.broker)
    assert desk.broker.economic_orders==0


def test_stop_racing_an_inflight_post_cancels_after_receipt_without_new_claims(desk):
    entered,release=Event(),Event()
    class HeldBroker(FakePaperBroker):
        def submit_exact_order(self,*args):
            entered.set()
            assert release.wait(5)
            return super().submit_exact_order(*args)
    desk.broker=HeldBroker(cash_usd='10000')
    row=act(desk,prepare(desk),'approve');desk.clock.seconds=31
    with ThreadPoolExecutor(max_workers=1) as executor:
        future=executor.submit(tick,desk.sessions,lambda:desk.broker)
        assert entered.wait(5)
        act(desk,row,'stop')
        release.set();future.result(timeout=5)
    tick(desk.sessions,lambda:desk.broker)
    assert desk.broker.economic_orders==1
    assert desk.repo.detail(row.schedule_id)['schedule'].state=='stopped'
    assert next(iter(desk.broker.observations.values())).status=='canceled'


def test_sell_ladder_cannot_short_or_exceed_reserved_holdings(desk):
    with pytest.raises(ConflictError,match='holdings'):
        prepare(desk,side='sell')
    from tradingagents.research.execution_contracts import AccountPosition
    desk.broker.positions={'TEST':AccountPosition(symbol='TEST',quantity=8,cost_basis_usd=800,market_value_usd=800)}
    row=prepare(desk,algorithm='dca_ladder',side='sell')
    assert [leg['order']['limit_price_usd'] for leg in row.payload['legs']]==['100.00','103.00','106.00','110.00']
    assert sum(leg['order']['quantity'] for leg in row.payload['legs'])<=8


def test_expired_review_and_changed_account_cannot_approve(desk):
    row=prepare(desk)
    snapshot=desk.broker.paper_snapshot().model_copy(update={'account_id':'different-account'})
    action=ScheduleAction(action='approve',expected_hash=row.content_hash,expected_revision=row.revision,actor='operator')
    with pytest.raises(ConflictError,match='reviewed account'):
        desk.repo.action(row.schedule_id,action,snapshot)
    desk.clock.seconds=31
    with pytest.raises(ConflictError,match='expired'):
        act(desk,row,'approve')
    assert desk.repo.detail(row.schedule_id)['schedule'].state=='previewed'


def test_actual_worker_process_starts_and_stops_without_broker_in_an_unused_database(tmp_path):
    import subprocess,sys,os
    url=f'sqlite:///{tmp_path/"worker.db"}'
    result=subprocess.run([sys.executable,'-m','tradingagents.scheduling.worker','--database-url',url,'--once'],
        env={**os.environ,'PYTHON_DOTENV_DISABLED':'1'},capture_output=True,text=True,timeout=20)
    assert result.returncode==0,result.stderr
    assert '"status": "idle"' in result.stdout
    engine,sessions=create_session_factory(url)
    status=ScheduleRepository(sessions).runtime()
    assert not status['connected'] and status['workers'][0].state=='stopped'


def test_scheduled_fills_are_attributed_to_the_schedule(desk,monkeypatch):
    from tradingagents.research.accounting_repository import PaperAccountingRepository
    from tradingagents.research.accounting_contracts import AccountingReconciliation
    accounting=PaperAccountingRepository(desk.sessions)
    baseline=accounting.preview_baseline(desk.broker.paper_snapshot())
    accounting.approve_baseline(baseline.baseline_id,baseline.content_hash,'test-reviewer')
    row=act(desk,prepare(desk),'approve');desk.clock.seconds=31
    tick(desk.sessions,lambda:desk.broker)
    client_id=next(iter(desk.broker.observations));desk.broker.fill(client_id,2,price=99)
    tick(desk.sessions,lambda:desk.broker)
    snapshot=desk.broker.paper_snapshot()
    opening=__import__('datetime').datetime.fromisoformat(baseline.snapshot['observed_at'].replace('Z','+00:00'))
    batch=desk.broker.account_activities(opening,snapshot.observed_at)
    receipt=accounting.reconcile(AccountingReconciliation(snapshot=snapshot,batch=batch))
    assert receipt.report['reconciled'],receipt.report['discrepancies']
    assert receipt.report['fills'][0]['executor']==f'schedule:{row.schedule_id}'


def test_stop_before_dispatch_revokes_all_children_atomically_without_a_broker(desk):
    row=prepare(desk)
    stopped=act(desk,row,'stop')
    assert stopped.state=='stopped'
    detail=desk.repo.detail(row.schedule_id)
    assert all(leg['order'].state=='canceled' for leg in detail['legs'])
    assert all(leg['attempt'] is None for leg in detail['legs'])
    assert tick(desk.sessions,lambda:pytest.fail('No broker needed'))['status']=='idle'


def test_worker_timeout_kills_child_and_pauses_approved_schedules(desk,monkeypatch):
    import subprocess,sys
    from tradingagents.scheduling import worker
    row=act(desk,prepare(desk),'approve')
    real_popen=subprocess.Popen
    children=[]
    def hung_child(command,**kwargs):
        child=real_popen([sys.executable,'-c','import time; time.sleep(30)'],**kwargs)
        children.append(child)
        return child
    monkeypatch.setattr(worker.subprocess,'Popen',hung_child)
    result=worker.cycle(desk.repo,str(desk.engine.url),'timeout-test',timeout=.1)
    assert result=={'status':'cycle_failed','error_type':'TimeoutError'}
    assert len(children)==1 and children[0].poll() is not None
    assert desk.repo.detail(row.schedule_id)['schedule'].state=='paused'
    assert all(leg['attempt'] is None for leg in desk.repo.detail(row.schedule_id)['legs'])
    assert desk.broker.economic_orders==0


def test_unsubmitted_deadline_closure_does_not_claim_broker_receipts(desk):
    row=act(desk,prepare(desk),'approve')
    desk.clock.seconds=100
    tick(desk.sessions,lambda:desk.broker)
    detail=desk.repo.detail(row.schedule_id)
    assert detail['schedule'].state=='finished_partial'
    assert all(x['attempt'] is None and x['order'].state=='canceled' for x in detail['legs'])
    assert 'local cancellations' in detail['schedule'].message
    assert 'have terminal receipts' not in detail['schedule'].message
    assert desk.broker.economic_orders==0


def test_legacy_terminal_message_corrected_in_views_without_changing_evidence(desk):
    from tradingagents.scheduling.models import ExecutionSchedule
    row=act(desk,prepare(desk),'approve');desk.clock.seconds=100;tick(desk.sessions,lambda:desk.broker)
    legacy='All child orders have terminal receipts; inspect observed fills'
    with desk.sessions() as s:
        saved=s.get(ExecutionSchedule,row.schedule_id);saved.message=legacy;s.add(saved);s.commit()
    assert 'local cancellations' in desk.repo.detail(row.schedule_id)['schedule'].message
    assert 'local cancellations' in desk.repo.listing()[0].message
    with desk.sessions() as s:assert s.get(ExecutionSchedule,row.schedule_id).message==legacy


def test_snapshot_collection_cannot_push_submission_past_approved_deadline(desk,monkeypatch):
    row=act(desk,prepare(desk),'approve');desk.clock.seconds=31
    native=desk.broker.paper_snapshot
    def slow_snapshot():
        snapshot=native();desk.clock.seconds=100
        return snapshot
    monkeypatch.setattr(desk.broker,'paper_snapshot',slow_snapshot)
    tick(desk.sessions,lambda:desk.broker)
    assert desk.broker.economic_orders==0
    assert all(x['attempt'] is None for x in desk.repo.detail(row.schedule_id)['legs'])
