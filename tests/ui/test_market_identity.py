from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import subprocess

import pytest
from fastapi import FastAPI, APIRouter
from fastapi.testclient import TestClient

from tradingagents.ui.market_identity import CachedLookup, InstrumentService, normalize_company, install_instrument_routes, public_company
from tradingagents.ui.market_data.base import MarketDataBar

NOW=datetime(2026,11,12,20,tzinfo=timezone.utc)

def raw():
    return {'info':{'symbol':'AAA','longName':'Example Corporation','longBusinessSummary':'A public business.',
        'marketCap':1e9,'trailingEps':-2,'heldPercentInsiders':.12,'heldPercentInstitutions':.6,'website':'https://example.com'},
        'institutional':[{'Holder':'Large Fund','Date Reported':'2026-09-30','Shares':200,'pctHeld':.2},
                         {'Holder':'Small Fund','Date Reported':'2026-06-30','Shares':100,'pctHeld':.1}],
        'insiders':[{'Name':'Founder','Position':'Director','Shares Owned Directly':50,'Position Direct Date':1750636800}], 'gaps':[]}

def test_company_keeps_parent_unknown_and_preserves_dated_positions():
    result=normalize_company('AAA',raw(),NOW)
    assert result['parent'] is None
    assert result['holders'][0]['name']=='Large Fund' and result['holders'][0]['percent']==20
    assert result['holders'][0]['reported_at']=='2026-09-30'
    assert result['insiders'][0]['holding_type']=='direct'
    assert result['insider_percent']==12 and result['institutional_percent']==60
    assert result['metrics']['eps']==-2


def test_identity_mismatch_is_rejected_not_relabelled_as_a_warrant_issuer():
    with pytest.raises(ValueError,match='identity'):normalize_company('AAA.WS',raw(),NOW)


def test_invalid_and_future_ownership_is_not_shown_and_unsafe_links_are_removed():
    value=raw();value['info'].update(website='javascript:alert(1)',heldPercentInsiders=1.5,marketCap=float('nan'))
    value['institutional'] += [{'Holder':'Future','Date Reported':'2027-01-01','Shares':500},
        {'Holder':'Undated','Shares':800},{'Holder':'Negative','Date Reported':'2026-09-30','Shares':-5}]
    value['insiders'][0]['Position Direct Date']=True
    result=normalize_company('AAA',value,NOW)
    assert len(result['holders'])==2 and not result['insiders']
    assert result['website'] is None and result['insider_percent'] is None and result['metrics']['market_cap'] is None


def test_asset_directory_and_public_profile_are_cached_separately():
    calls=[]
    class Provider:
        def asset_metadata(self,symbol):
            calls.append(symbol);return {'symbol':symbol,'name':'Example Corporation Warrants','exchange':'NASDAQ','class':'us_equity'}
    service=InstrumentService(lambda:(Provider(),{}),company_fetcher=lambda symbol:raw())
    assert service.identity('AAA')['security_type']=='Warrant'
    assert service.identity('AAA')['name']=='Example Corporation Warrants' and len(calls)==1
    assert service.company('AAA')['name']=='Example Corporation'
    assert service.company('AAA.WS')['status']=='unavailable'


def test_missing_provider_does_not_expose_private_error_or_hide_company_source():
    def fail():raise ValueError('secret-token')
    service=InstrumentService(fail,company_fetcher=lambda symbol:raw())
    assert service.identity('AAA')['status']=='unavailable'
    assert 'secret-token' not in str(service.identity('AAA'))
    assert service.company('AAA')['status']=='available'


def test_cache_coalesces_concurrent_requests_and_bounds_entries():
    cache=CachedLookup();calls=[]
    def get():calls.append(1);return {'status':'available'}
    with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(lambda _:cache.get('AAA',get,10),range(8)))
    assert len(calls)==1
    for i in range(300):cache.get(str(i),get,10)
    assert len(cache.values)==256


def test_public_lookup_child_has_deadline_and_no_account_credentials(monkeypatch):
    def run(args,**kwargs):
        assert args[-1]=='AAA' and kwargs['timeout']==25
        assert 'ALPACA_SECRET' not in kwargs['env'] and kwargs['env']['PYTHON_DOTENV_DISABLED']=='1'
        return SimpleNamespace(returncode=0,stdout=b'{"info":{}}')
    monkeypatch.setenv('ALPACA_SECRET','never-forward')
    monkeypatch.setattr(subprocess,'run',run)
    assert public_company('AAA')=={'info':{}}


def test_chart_uses_exact_symbol_feed_latest_session_and_no_quote_dependency(monkeypatch):
    monkeypatch.setattr('tradingagents.ui.market_identity.now_utc',lambda:NOW)
    def bar(at,**kwargs):
        return MarketDataBar(symbol='AAA',timestamp=at,open=10,high=12,low=9,close=11,volume=100,**kwargs)
    class Provider:
        def historical_bars(self,**kwargs):
            assert kwargs['symbol']=='AAA' and kwargs['feed']=='iex' and kwargs['limit']==10000
            return [bar(NOW-timedelta(days=1)),bar(NOW-timedelta(minutes=1)),bar(NOW+timedelta(minutes=1))]
    service=InstrumentService(lambda:(Provider(),{'feed':'iex'}))
    result=service.chart('AAA','1D')
    assert len(result['bars'])==1 and result['status']=='available'
    assert result['as_of']==(NOW-timedelta(minutes=1)).isoformat()


def test_instrument_routes_validate_input_and_return_clear_missing_states():
    def fail():raise ValueError('secret')
    app=FastAPI();router=APIRouter(prefix='/api/market-pulse');install_instrument_routes(router,fail);app.include_router(router)
    with TestClient(app) as client:
        assert client.get('/api/market-pulse/identities?symbols=AAA,AAA').json()['items'][0]['status']=='unavailable'
        assert client.get('/api/market-pulse/identities?symbols=BAD!').status_code==422
        assert client.get('/api/market-pulse/chart/AAA?range=99Y').status_code==422
        assert client.get('/api/market-pulse/chart/AAA?range=1D').json()['bars']==[]
