from datetime import datetime,timezone
from decimal import Decimal
from types import SimpleNamespace
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from pydantic import ValidationError
from tradingagents.ui.db import create_session_factory,init_db
from tradingagents.ui.research_desk import Desk
from tradingagents.ui.portfolio_stress import StressRequest,stress_result,create_stress_router
from tradingagents.research.data.store import ArtifactStore
from tradingagents.research.execution_contracts import PaperAccountSnapshot,AccountPosition


def snapshot():
    now=datetime.now(timezone.utc)
    return PaperAccountSnapshot(provider_id='alpaca-paper-broker',account_id='paper-test',evidence_kind='broker_paper',started_at=now,observed_at=now,equity_usd=10000,cash_usd=2000,buying_power_usd=10000,daily_turnover_usd=0,drawdown_fraction=0,trading_blocked=False,positions=[AccountPosition(symbol='NVDA',quantity=20,market_value_usd=5000,cost_basis_usd=4000),AccountPosition(symbol='MSFT',quantity=10,market_value_usd=3000,cost_basis_usd=2500)],open_orders=[],complete=True)

def request(**kw):return StressRequest(snapshot_id='source',name='Scenario',request_key='scenario_request_0001',**kw)

def test_simultaneous_decline_preserves_cash_and_reconciles():
    result=stress_result(snapshot(),request(default_shock_pct=-20))
    assert Decimal(result['equity_after_usd'])==8400
    assert Decimal(result['change_pct'])==-16
    assert Decimal(result['cash_usd'])==2000
    assert sum(Decimal(r['value_after_usd']) for r in result['holdings'])+2000==8400
    assert sum(Decimal(r['weight_after_pct']) for r in result['holdings'])+Decimal(result['cash_weight_after_pct'])==100

def test_override_replaces_default_and_zero_control():
    result=stress_result(snapshot(),request(default_shock_pct=-20,overrides={'NVDA':-50}))
    assert Decimal(result['change_usd'])==-3100
    assert Decimal(result['equity_after_usd'])==6900
    control=stress_result(snapshot(),request(default_shock_pct=0))
    assert Decimal(control['change_usd'])==0
    assert all(r['weight_after_pct']==r['weight_before_pct'] for r in control['holdings'])

def test_total_loss_and_margin_zero_equity_are_explicit():
    s=snapshot().model_copy(update={'cash_usd':Decimal(0),'equity_usd':Decimal(8000)})
    result=stress_result(s,request(default_shock_pct=-100))
    assert Decimal(result['equity_after_usd'])==0
    assert all(r['weight_after_pct'] is None for r in result['holdings'])
    assert result['cash_weight_after_pct'] is None

def test_bad_inputs_and_incomplete_or_unreconciled_snapshots_rejected():
    for value in [-101,'NaN','Infinity',501]:
        with pytest.raises(ValidationError):request(default_shock_pct=value)
    with pytest.raises(ValueError,match='absent'):stress_result(snapshot(),request(overrides={'FAKE':-50}))
    for update in [{'complete':False},{'evidence_kind':'fixture'},{'equity_usd':Decimal(11000)}]:
        with pytest.raises(ValueError):stress_result(snapshot().model_copy(update=update),request())

def test_routes_save_same_source_comparisons_idempotently_and_verify_export(tmp_path):
    _,sessions=create_session_factory(f'sqlite:///{tmp_path}/stress.db');init_db(sessions.kw['bind']);desk=Desk(sessions)
    store=ArtifactStore(tmp_path/'objects');app=FastAPI()
    broker=SimpleNamespace(paper_snapshot=snapshot)
    app.include_router(create_stress_router(desk,lambda:broker,store))
    with TestClient(app) as client:
        source=client.post('/api/discover/stress/snapshots',json={});assert source.status_code==200
        payload=request(default_shock_pct=-20).model_dump(mode='json');payload['snapshot_id']=source.json()['id']
        first=client.post('/api/discover/stress/scenarios',json=payload);assert first.status_code==200
        assert client.post('/api/discover/stress/scenarios',json=payload).json()['id']==first.json()['id']
        assert client.post('/api/discover/stress/scenarios',json={**payload,'default_shock_pct':'-25'}).status_code==409
        export=client.get('/api/discover/stress/scenarios/'+first.json()['id']+'/evidence.json');assert export.status_code==200
        assert export.json()['account_evidence']['snapshot']['equity_usd']=='10000'
        assert len(client.get('/api/discover/stress').json()['scenarios'])==1
        store.path(first.json()['payload']['receipt_hash']).write_bytes(b'changed')
        assert client.get('/api/discover/stress/scenarios/'+first.json()['id']+'/evidence.json').status_code==409

def test_provider_errors_do_not_expose_credentials(tmp_path):
    _,sessions=create_session_factory(f'sqlite:///{tmp_path}/errors.db');init_db(sessions.kw['bind'])
    def fail():raise ValueError('secret-token')
    app=FastAPI();app.include_router(create_stress_router(Desk(sessions),fail,ArtifactStore(tmp_path/'objects')))
    with TestClient(app) as client:
        response=client.post('/api/discover/stress/snapshots',json={})
        assert response.status_code==409 and 'secret-token' not in response.text
