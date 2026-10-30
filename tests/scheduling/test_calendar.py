from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
import pytest
from tradingagents.scheduling.calendar import MarketCalendar, MarketSession, alpaca_calendar, validate_window
from tradingagents.research.repository import ConflictError

UTC=timezone.utc
START=datetime(2026,11,27,15,0,tzinfo=UTC)

def evidence(now=START, closed=False, end_hour=18):
    return MarketCalendar(provider_id='alpaca-paper-broker',account_id='paper',evidence_kind='broker_paper',
        requested_start=date(2026,11,26),requested_end=date(2026,11,29),observed_at=now,clock_at=now,
        is_open=not closed,next_open='2026-11-30T14:30:00Z',next_close='2026-11-27T18:00:00Z',source_hash='test',
        sessions=[MarketSession(session_date=date(2026,11,27),opens_at='2026-11-27T14:30:00Z',closes_at=f'2026-11-27T{end_hour}:00:00Z')])

@pytest.fixture
def snap(monkeypatch):
    monkeypatch.setattr('tradingagents.scheduling.calendar.now_utc',lambda:START)
    return SimpleNamespace(provider_id='alpaca-paper-broker',account_id='paper',evidence_kind='broker_paper')

@pytest.mark.parametrize('start,end',[
    ('2026-11-26T15:00:00Z','2026-11-26T15:05:00Z'), # Thanksgiving absent
    ('2026-11-28T15:00:00Z','2026-11-28T15:05:00Z'), # Saturday absent
    ('2026-11-27T14:29:00Z','2026-11-27T14:35:00Z'), # Before open
    ('2026-11-27T17:58:00Z','2026-11-27T18:00:00Z'), # Early close buffer
    ('2026-11-27T17:55:00Z','2026-11-30T14:35:00Z'), # Cross-session
])
def test_holidays_weekends_and_early_close_reject(snap,start,end):
    with pytest.raises(ConflictError,match='verified regular market session'):
        validate_window(evidence(),snap,datetime.fromisoformat(start),datetime.fromisoformat(end))


def test_fresh_identity_and_clock_are_required(snap):
    end=START+timedelta(minutes=5)
    assert validate_window(evidence(),snap,START,end,dispatch=True)['session_date']=='2026-11-27'
    for update in ({'clock_at':START-timedelta(seconds=31)},{'observed_at':START+timedelta(seconds=6)}):
        with pytest.raises(ConflictError,match='stale'): validate_window(evidence().model_copy(update=update),snap,START,end)
    with pytest.raises(ConflictError,match='different account'): validate_window(evidence().model_copy(update={'account_id':'foreign'}),snap,START,end)
    with pytest.raises(ConflictError,match='closed'): validate_window(evidence(closed=True),snap,START,end,dispatch=True)
    with pytest.raises(ConflictError,match='changed'): validate_window(evidence(),snap,START,end,pinned={'session_date':'other'})
    with pytest.raises(ConflictError,match='required'): validate_window(None,snap,START,end)


def test_alpaca_response_preserves_early_close_and_daylight_saving_offsets(monkeypatch):
    reads=[]
    rows=[{'date':'2026-10-30','open':'09:30','close':'16:00'}, {'date':'2026-11-02','open':'09:30','close':'16:00'}, {'date':'2026-11-27','open':'09:30','close':'13:00'}]
    clock={'timestamp':'2026-11-27T10:00:00-05:00','is_open':True,'next_open':'2026-11-30T09:30:00-05:00','next_close':'2026-11-27T13:00:00-05:00'}
    def read(path,params=None):
        reads.append((path,params)); return rows if path=='calendar' else clock
    broker=SimpleNamespace(_read=read,_evidence_kind='fixture',paper_identity=lambda:SimpleNamespace(provider_id='alpaca-paper-broker',account_id='paper'))
    result=alpaca_calendar(broker,date(2026,10,30),date(2026,11,27))
    assert [s.opens_at.astimezone(UTC).hour for s in result.sessions]==[13,14,14]
    assert result.sessions[-1].closes_at.astimezone(UTC).hour==18
    assert reads[0][1]['date_type']=='TRADING'
    clock['is_open']='false'
    with pytest.raises(ValueError): alpaca_calendar(broker,date(2026,10,30),date(2026,11,27))
    clock['is_open']=False;rows.append(rows[-1])
    with pytest.raises(ValueError,match='duplicated'): alpaca_calendar(broker,date(2026,10,30),date(2026,11,27))


def test_calendar_required_at_prepare_approval_resume_and_dispatch(tmp_path,monkeypatch):
    from tradingagents.ui.brokers.fake import FakePaperBroker
    from tradingagents.ui.db import create_session_factory,init_db
    from tradingagents.scheduling.repository import ScheduleRepository
    from tradingagents.scheduling.contracts import ScheduleRequest,ScheduleAction
    from tradingagents.research.execution_contracts import ExecutionPolicy
    from tradingagents.research.execution_repository import PaperExecutionRepository
    from tradingagents.research.execution_service import PaperExecutionService
    clock=SimpleNamespace(now=START)
    for module in ['tradingagents.scheduling.calendar','tradingagents.scheduling.repository','tradingagents.research.execution_repository','tradingagents.ui.brokers.fake']:
        monkeypatch.setattr(module+'.now_utc',lambda:clock.now)
    e,s=create_session_factory(f'sqlite:///{tmp_path/"calendar.db"}');init_db(e)
    repo=ScheduleRepository(s);fake=FakePaperBroker(cash_usd='10000')
    original=fake.paper_snapshot
    fake.paper_snapshot=lambda:original().model_copy(update={'evidence_kind':'broker_paper'})
    snapshot=fake.paper_snapshot()
    cal=evidence().model_copy(update={'provider_id':snapshot.provider_id,'account_id':snapshot.account_id})
    fake.execution_calendar=lambda *_:cal
    req=ScheduleRequest(idempotency_key='review',algorithm='twap',symbol='TEST',side='buy',notional_usd='400',limit_price_usd='100',count=2,duration_minutes=5,start_at=START+timedelta(seconds=30))
    policy=ExecutionPolicy(max_position_fraction='.5',max_group_fraction='.8',max_turnover_fraction=1,max_drawdown_fraction='.1')
    with pytest.raises(ConflictError,match='calendar'):repo.prepare(req,snapshot,policy)
    assert repo.listing()==[]
    row=repo.prepare(req,snapshot,policy,cal)
    def act(kind,proof=None):
        nonlocal row
        row=repo.action(row.schedule_id,ScheduleAction(action=kind,actor='operator',expected_hash=row.content_hash,expected_revision=row.revision),fake.paper_snapshot(),proof)
    with pytest.raises(ConflictError,match='calendar'):act('approve')
    act('approve',cal);act('pause')
    with pytest.raises(ConflictError,match='calendar'):act('resume')
    act('resume',cal)
    clock.now=START+timedelta(seconds=31)
    cal=cal.model_copy(update={'observed_at':clock.now,'clock_at':clock.now,'is_open':False})
    order=repo.detail(row.schedule_id)['legs'][0]['order']
    service=PaperExecutionService(PaperExecutionRepository(s),fake)
    with pytest.raises(ConflictError,match='closed'):service.submit(order)
    assert fake.economic_orders==0 and service.repo.attempt_for_order(order.order_id) is None
    cal=cal.model_copy(update={'is_open':True})
    service.submit(order);service.submit(order)
    assert fake.economic_orders==1
    assert any(event.kind=='market_session_checked' for event in repo.detail(row.schedule_id)['events'])
