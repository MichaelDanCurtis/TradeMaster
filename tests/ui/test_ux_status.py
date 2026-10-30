from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from tradingagents.ui.api import create_app
from tradingagents.ui.market_data.base import MarketDataQuote
from tradingagents.ui.watchers.conditions import fetch_observation
from tradingagents.ui.watchers.firing_loop import check_watcher_once


def quote_provider(bid=100, ask=102, age=0):
    return SimpleNamespace(latest_quote=lambda *a, **kw: SimpleNamespace(bid_price=bid, ask_price=ask,timestamp=datetime.now(timezone.utc)-timedelta(seconds=age)))


@pytest.mark.parametrize('bid,ask,age', [(219.49,0,0),(0,220,0),(220,219,0),(100,102,301),(100,102,-120),(float('nan'),102,0)])
def test_watchers_reject_invalid_or_stale_prices(bid,ask,age):
    with pytest.raises(ValueError):
        fetch_observation(quote_provider(bid,ask,age),symbol='NVDA',condition_type='price_above')


def test_valid_quote_uses_midpoint_and_disabled_watcher_cannot_record_a_fire():
    provider=quote_provider()
    assert fetch_observation(provider,symbol='TEST',condition_type='price_above')[0] == 101
    watcher=SimpleNamespace(symbol='TEST',condition_type='price_above',threshold=99,enabled=False,last_fired_at=None)
    class NoWrites:
        def record_watcher_fire(self,**kwargs): pytest.fail('Disabled watcher must not write')
    evaluation,fire,cooldown=check_watcher_once(NoWrites(),watcher,provider)
    assert evaluation.fired and fire is None and not cooldown


def test_strategy_role_rejects_unsupported_oauth_without_changing_assignment(tmp_path):
    client=TestClient(create_app(f'sqlite:///{tmp_path/"audit.db"}'))
    before=client.get('/api/provider-role-assignments').json()
    assert 'openai' in before['strategy_research_protocols']
    assert 'codex-oauth' in before['strategy_research_protocols']
    client.post('/api/runtime/developer-mode',json={'enabled':True})
    response=client.post('/api/provider-role-assignments/research_designer',json={'provider_id':'github-copilot-oauth-llm'})
    assert response.status_code == 400
    after=client.get('/api/provider-role-assignments').json()
    assert after['assignments'] == before['assignments']


@pytest.mark.parametrize('role', ['research_designer', 'research_extractor'])
def test_strategy_roles_accept_codex_subscription_provider(tmp_path, role):
    client=TestClient(create_app(f'sqlite:///{tmp_path/"codex.db"}'))
    client.post('/api/runtime/developer-mode',json={'enabled':True})
    response=client.post('/api/provider-role-assignments/'+role,json={'provider_id':'openai-codex-oauth-llm'})
    assert response.status_code == 200
    assignments=client.get('/api/provider-role-assignments').json()['assignments']
    assert next(row for row in assignments if row['role_key']==role)['provider_id']=='openai-codex-oauth-llm'


def test_credential_check_does_not_claim_connection_and_preserves_disabled(tmp_path):
    client=TestClient(create_app(f'sqlite:///{tmp_path/"audit.db"}'))
    client.post('/api/provider-configs/lm-studio-llm',json={'enabled':False})
    response=client.post('/api/provider-configs/lm-studio-llm/health-check')
    assert response.status_code == 200
    assert response.json()['status']=='disabled'
    assert response.json()['health']['connection_verified'] is False
    assert response.json()['health']['check_kind']=='credential_availability'


def test_blank_credential_save_clears_reference_but_toggle_does_not(tmp_path):
    client=TestClient(create_app(f'sqlite:///{tmp_path/"audit.db"}'))
    path='/api/provider-configs/openai-llm'
    assert client.post(path,json={'secret_ref':'env:UX_TEST_KEY'}).json()['secret_ref']=='env:UX_TEST_KEY'
    assert client.post(path,json={'enabled':False}).json()['secret_ref']=='env:UX_TEST_KEY'
    assert client.post(path,json={'secret_ref':None}).json()['secret_ref'] is None
    rows=client.get('/api/provider-configs').json()['providers']
    assert next(p for p in rows if p['provider_id']=='openai-llm')['secret_ref'] is None


def test_unconfigured_broker_does_not_invent_a_fixture_account(tmp_path):
    client=TestClient(create_app(f'sqlite:///{tmp_path/"audit.db"}'))
    response=client.get('/api/research/deployments/account',headers={'X-Trademaster-Room':'market'})
    assert response.status_code == 503
    assert 'broker' in response.json()['detail'].lower()


def test_selected_broker_is_respected_and_never_substituted_with_alpaca(tmp_path):
    client=TestClient(create_app(f'sqlite:///{tmp_path/"audit.db"}'))
    # Use a real registered planned broker instead of assuming its identifier.
    brokers=client.get('/api/provider-configs').json()['providers']
    target=next(p for p in brokers if p['name']=='Interactive Brokers')
    assert client.post('/api/provider-role-assignments/broker',json={'provider_id':target['provider_id']}).status_code==200
    client.post('/api/provider-configs/'+target['provider_id'],json={'enabled':True})
    response=client.get('/api/research/deployments/account',headers={'X-Trademaster-Room':'market'})
    assert response.status_code==503
    assert 'no installed' in response.json()['detail']


def test_model_discovery_uses_configured_secret_reference(tmp_path, monkeypatch):
    monkeypatch.setenv('UX_MODEL_DISCOVERY_KEY', 'test-only-credential')
    captured = {}
    def discover(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(models=[], source='api', detail='test discovery')
    monkeypatch.setattr('tradingagents.llm_clients.model_discovery.discover_models', discover)
    client = TestClient(create_app(f'sqlite:///{tmp_path/"models.db"}'))
    client.post('/api/provider-configs/openai-llm', json={'secret_ref':'env:UX_MODEL_DISCOVERY_KEY'})
    response = client.get('/api/provider-configs/openai-llm/models')
    assert response.status_code == 200
    assert captured['api_key'] == 'test-only-credential'
    assert 'test-only-credential' not in response.text


def test_manual_preview_api_does_not_launch_a_research_run(tmp_path):
    from tradingagents.ui.brokers.fake import FakePaperBroker
    client = TestClient(create_app(f'sqlite:///{tmp_path/"manual.db"}',
        broker_providers={'fixture-paper-broker':FakePaperBroker()}))
    response = client.post('/api/trades/preview', json={'symbol':'NVDA','side':'buy','notional':1000})
    assert response.status_code == 200, response.text
    assert response.json()['evidence_kind'] == 'fixture'
    assert client.get('/api/runs').json() == {'runs': []}
