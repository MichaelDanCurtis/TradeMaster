from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path
import pytest
from tradingagents.ui.company_evidence import financial_facts, screen, finite
from tradingagents.ui.research_desk import Desk, AllocationRequest, portfolio_impact
from tradingagents.ui.db import create_session_factory, init_db
from tradingagents.research.execution_contracts import PaperAccountSnapshot,AccountPosition,OpenPaperOrder


def facts(rows):
    return {'facts':{'us-gaap':{tag:{'units':{'USD':values}} for tag,values in rows.items()}}}


def annual(value, **kw):
    return {'start':'2025-01-01','end':'2025-12-31','filed':'2026-02-17','form':'10-K','val':value,'accn':'filing1',**kw}


def test_fcf_requires_same_period_same_filing_and_finite_numbers():
    tags={'NetCashProvidedByUsedInOperatingActivities':[annual(100)],'PaymentsToAcquirePropertyPlantAndEquipment':[annual(20)]}
    assert financial_facts(facts(tags))['free_cash_flow']['value']==80
    for changed in [{'start':'2025-02-01'},{'accn':'another'},{'filed':'2026-02-18'},{'val':-20},{'val':float('nan')}]:
        tags['PaymentsToAcquirePropertyPlantAndEquipment']=[annual(20,**changed)]
        assert 'free_cash_flow' not in financial_facts(facts(tags))


def test_financials_do_not_accept_quarter_future_or_wrong_currency():
    payload=facts({'Revenues':[annual(10,start='2025-10-01'),annual(99,filed='2099-01-01')]})
    assert financial_facts(payload)=={}
    assert finite(True) is None and finite('Infinity') is None


def test_screen_cannot_pass_missing_or_negative_cash_flow():
    snapshot={'metrics':{'revenue_growth':20,'net_margin':5},'financials':{}}
    assert screen(snapshot)['state']=='unknown'
    snapshot['financials']['free_cash_flow']={'value':-1}
    assert screen(snapshot)['state']=='fail'
    snapshot['financials']['free_cash_flow']['value']=1
    assert screen(snapshot)['state']=='pass'
    assert screen(snapshot,min_growth=20)['state']=='fail'


@pytest.fixture
def desk(tmp_path):
    _,sessions=create_session_factory('sqlite:///'+str(tmp_path/'desk.db'));init_db(sessions.kw['bind'])
    class Source:
        value=20
        def collect(self,symbol):
            return {'symbol':symbol,'collected_at':datetime.now(timezone.utc).isoformat(),'profile':{},'metrics':{'revenue_growth':self.value,'net_margin':10},
                    'financials':{'free_cash_flow':{'value':5}},'filings':[],'sources':[],'gaps':[]}
    return Desk(sessions,Source())


def test_thesis_persists_original_and_flags_breach_without_rewriting_it(desk):
    baseline=desk.collect('PLTR');monitor=desk.save('monitor','PLTR',{'snapshot_id':baseline['id'],'thesis':'Cash generation continues','invalidation':'Growth or margin turns negative', 'min_growth':10,'min_margin':0,'active':True})
    first=desk.review(monitor);assert first['payload']['state']=='no_detected_change'
    desk.sources.value=-2
    second=desk.review(monitor)
    assert second['payload']['state']=='threshold_breached'
    assert second['payload']['previous_snapshot_id']==first['payload']['snapshot_id']
    assert second['payload']['changes']==[{'metric':'revenue_growth','before':20,'after':-2}]
    assert desk.get(baseline['id'],'company')['payload']['metrics']['revenue_growth']==20
    assert len(Desk(desk.sessions,desk.sources).rows('review'))==2


def test_worker_checks_only_due_active_monitors(desk):
    baseline=desk.collect('PLTR')
    for active in [True,False]:desk.save('monitor','PLTR',{'snapshot_id':baseline['id'],'min_growth':10,'min_margin':0,'active':active})
    desk.due();desk.due()
    assert len(desk.rows('review'))==1
    assert desk.worker['checked_at'] and desk.worker['error'] is None


def snapshot(orders=None):
    now=datetime.now(timezone.utc)
    return PaperAccountSnapshot(provider_id='alpaca-paper-broker',account_id='paper',evidence_kind='broker_paper',started_at=now,observed_at=now,
        equity_usd=10000,cash_usd=8000,buying_power_usd=16000,daily_turnover_usd=0,drawdown_fraction=0,trading_blocked=False,
        positions=[AccountPosition(symbol='NVDA',quantity=10,market_value_usd=2000,cost_basis_usd=1900)],open_orders=orders or [],complete=True)


def test_allocation_uses_cash_not_margin_and_retains_unknown_buy_commitment():
    req=AllocationRequest(symbol='NVDA',amount_usd=1000)
    r=portfolio_impact(snapshot(),req)
    assert r['weight_before_pct']=='20.0' and r['weight_after_pct']=='30.0'
    assert r['cash_after_usd']=='7000'
    assert portfolio_impact(snapshot(),AllocationRequest(symbol='NVDA',amount_usd=9000))['cash_coverage']=='insufficient'
    order=OpenPaperOrder(client_order_id='c1',broker_order_id='b1',symbol='MSFT',side='buy',remaining_quantity=1,maximum_price_usd=None)
    assert portfolio_impact(snapshot([order]),req)['cash_coverage']=='unknown'
    invalid=snapshot().model_copy(update={'evidence_kind':'fixture'})
    with pytest.raises(ValueError):portfolio_impact(invalid,req)


def test_api_does_not_create_execution_records_for_research(tmp_path):
    from fastapi.testclient import TestClient
    from tradingagents.ui.api import create_app
    from unittest.mock import patch
    # Source collection is mocked; the test checks durable route wiring and validation.
    app=create_app(database_url='sqlite:///'+str(tmp_path/'api.db'))
    with TestClient(app) as client:
        source=app.state.research_desk.sources
        with patch.object(source,'collect',return_value={'symbol':'PLTR','profile':{},'metrics':{},'financials':{},'filings':[],'sources':[],'gaps':[]}):
            response=client.post('/api/discover/desk/company/PLTR');assert response.status_code==200
        saved=response.json()
        assert client.get('/api/discover/desk/records/company').json()['records'][0]['id']==saved['id']
        assert client.post('/api/discover/desk/company/INVALIDTOOLONG').status_code==422
        assert client.post('/api/discover/desk/monitors',json={'snapshot_id':saved['id'],'thesis':'Research question','invalidation':'Growth becomes negative'}).status_code==200
        assert client.get('/api/discover/desk/status').json()['execution_authority'] is False


def test_filing_classification_requires_exact_registered_symbol_row(tmp_path,monkeypatch):
    import httpx
    from tradingagents.ui.company_evidence import CompanySources
    html=b'<table><tr><td>Title of each class</td><td>Trading Symbol(s)</td></tr><tr><td>Class A Common Stock</td><td>PLTR</td></tr></table><p>Join a webcast about the financial outlook.</p><h2>Outlook</h2><p>Third quarter revenue forecast: forward-looking estimates.</p>'
    transport=httpx.MockTransport(lambda request:httpx.Response(200,content=html))
    client=httpx.Client
    monkeypatch.setattr(httpx,'Client',lambda **kwargs:client(transport=transport,**kwargs))
    source=CompanySources(tmp_path/'objects')
    receipt=source.filing('https://www.sec.gov/Archives/edgar/data/1321655/test.htm','PLTR')
    assert receipt['security_description']=='Class A Common Stock'
    assert receipt['text'].startswith('Outlook Third quarter')
    assert source.store.get(receipt['sha256'])==html
    assert source.filing(receipt['url'],'PLTRW')['security_description'] is None
    with pytest.raises(ValueError):source.filing('https://example.com/fake-sec.htm','PLTR')


def test_portfolio_local_reservations_are_not_double_counted(desk):
    from tradingagents.ui.research_desk import local_portfolio_context
    from tradingagents.research.execution_repository import account_key
    from tradingagents.research.execution_models import PaperReservationRecord,PaperExecutionAttemptRecord
    order=OpenPaperOrder(client_order_id='c1',broker_order_id='b1',symbol='MSFT',side='buy',remaining_quantity=2,maximum_price_usd=100)
    observed=snapshot([order]);key=account_key(observed)
    with desk.sessions() as session:
        session.add(PaperExecutionAttemptRecord(attempt_id='a1',order_id='o1',account_key=key,client_order_id='c1',approval_id='approval',state='accepted'))
        session.add(PaperReservationRecord(attempt_id='a1',account_key=key,symbol='MSFT',side='buy',quantity='2',price_usd='100',fee_usd='1'))
        session.add(PaperExecutionAttemptRecord(attempt_id='a2',order_id='o2',account_key=key,client_order_id='c2',approval_id='approval2',state='unknown'))
        session.add(PaperReservationRecord(attempt_id='a2',account_key=key,symbol='NVDA',side='buy',quantity='1',price_usd='100',fee_usd='1'))
        session.commit()
    req=AllocationRequest(symbol='NVDA',amount_usd=1000)
    result=local_portfolio_context(desk.sessions,observed,req,portfolio_impact(observed,req))
    assert result['cash_after_known_commitments_usd']=='6698'
    assert result['local_pending_buys'][0]['amount_usd']=='1'
