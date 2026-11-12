from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from tradingagents.research.evidence.extraction import Completion
from tradingagents.research.evidence.provider import ProviderBinding
from tradingagents.ui.db import create_session_factory, init_db
from tradingagents.ui.explorer_briefs import ExplorerBriefRecord
from tradingagents.ui.market_pulse import (
    MarketPulseService, PulseRequest, capture_market, collect_move_news, create_pulse_router,
    normalize_movers, snapshot_row, validate_movers,
)
from tradingagents.ui.models import now_utc

NOW = datetime(2026, 11, 12, 18, 0, tzinfo=timezone.utc)
BINDING = ProviderBinding('codex-test', 'codex-app-server', 'test-model', None, 'a'*64, None, False)


def raw_snapshot():
    return {'latestTrade': {'t': NOW.isoformat(), 'p': 110},
        'latestQuote': {'t': NOW.isoformat(), 'bp': 109, 'ap': 111},
        'dailyBar': {'t': NOW.replace(hour=5).isoformat(), 'o': 102, 'h': 112, 'l': 101, 'c': 109, 'v': 1000, 'vw': 105},
        'prevDailyBar': {'t': (NOW-timedelta(days=1)).isoformat(), 'c': 100}}


class Market:
    def __init__(self, at=None):
        self.at = at or now_utc()
        self.calls = []

    def stock_movers(self, **kwargs):
        self.calls.append('movers')
        return {'last_updated': self.at.isoformat(), 'gainers': [{'symbol': 'AAA', 'price': 110, 'percent_change': 10}],
            'losers': [{'symbol': 'BBB', 'price': 90, 'percent_change': -10}]}

    def most_active_stocks(self, **kwargs):
        self.calls.append('activity')
        return {'last_updated': self.at.isoformat(), 'most_actives': [{'symbol': 'AAA', 'volume': 1500}]}

    def stock_snapshots(self, symbols, *, feed):
        self.calls.append(('snapshots', symbols, feed))
        return {symbol: raw_snapshot() for symbol in symbols}


def test_snapshot_arithmetic_and_preopen_previous_close():
    raw = raw_snapshot()
    result = snapshot_row('AAA', raw, NOW)
    assert result['change_pct'] == pytest.approx(10)
    assert result['gap_pct'] == pytest.approx(2)
    assert result['vwap_delta_pct'] == pytest.approx((110/105-1)*100)
    assert result['spread_bps'] == pytest.approx(2/110*10000)
    assert result['volume'] == 1000
    # Before the new daily bar arrives, yesterday's close is the comparison baseline.
    next_day = NOW+timedelta(days=1)
    raw['latestTrade']['t'] = next_day.isoformat()
    result = snapshot_row('AAA', raw, next_day)
    assert result['previous_close'] == 109
    assert result['volume'] is None and result['vwap_delta_pct'] is None
    assert result['spread_bps'] is None


@pytest.mark.parametrize('mutation', ['future', 'naive', 'nan', 'malformed', 'crossed', 'stale'])
def test_snapshot_rejects_invalid_data_without_fabricated_live_status(mutation):
    raw = raw_snapshot()
    if mutation == 'future': raw['latestTrade']['t'] = (NOW+timedelta(days=1)).isoformat()
    if mutation == 'naive': raw['latestTrade']['t'] = '2026-11-12T18:00:00'
    if mutation == 'nan': raw['latestTrade']['p'] = float('nan')
    if mutation == 'malformed': raw['dailyBar'] = ['invalid']
    if mutation == 'crossed': raw['latestQuote']['bp'] = 112
    if mutation == 'stale': raw['latestQuote']['t'] = (NOW-timedelta(hours=1)).isoformat()
    result = snapshot_row('AAA', raw, NOW)
    if mutation in ('future', 'naive', 'nan'):
        assert result['price'] == 109 and result['freshness'] == 'delayed'
    if mutation == 'malformed': assert result['price'] == 110 and result['change_pct'] is None
    if mutation in ('crossed', 'stale'): assert result['spread_bps'] is None
    json.dumps(result, allow_nan=False)


def test_rankings_are_sorted_deduplicated_and_validate_direction():
    value = normalize_movers({'gainers': [
        {'symbol': 'AAA', 'price': 1, 'percent_change': 3}, {'symbol': 'BBB', 'price': 1, 'percent_change': 6},
        {'symbol': 'BBB', 'price': 1, 'percent_change': 6}, {'symbol': 'INVALID!', 'price': 1, 'percent_change': 6},
        {'symbol': 'BAD', 'price': 1, 'percent_change': -3}, {'symbol': 'NAN', 'price': 1, 'percent_change': float('nan')}],
        'losers': [{'symbol': 'CCC', 'price': 2, 'percent_change': -1}, {'symbol': 'DDD', 'price': 1, 'percent_change': -5}]})
    assert [r['symbol'] for r in value['gainers']] == ['BBB', 'AAA']
    assert [r['symbol'] for r in value['losers']] == ['DDD', 'CCC']


def test_capture_batches_explicit_feed_and_distinguishes_sip_from_snapshot():
    market = Market(NOW)
    result = capture_market(lambda: (market, {'feed': 'iex'}), now=NOW)
    assert result['status'] == 'available'
    assert len(result['benchmarks']) == 7 and len(result['sectors']) == 11
    assert result['gainers'][0]['as_of'] == NOW.isoformat()
    assert result['losers'][0]['price'] == 90
    assert result['losers'][0]['snapshot']['price'] == 110  # Separate feeds are not silently merged.
    calls = [call for call in market.calls if isinstance(call, tuple)]
    assert len(calls) == 1 and calls[0][2] == 'iex'
    assert len(calls[0][1]) == len(set(calls[0][1]))
    assert result['activity'][0]['screener_volume'] == 1500
    assert result['activity'][0]['volume'] == 1000


def test_unavailable_and_partial_reads_do_not_leak_secrets_or_erase_valid_rankings():
    def fail(*args, **kwargs): raise RuntimeError('private-token-do-not-leak')
    result = capture_market(fail, now=NOW)
    assert result['status'] == 'unavailable'
    assert result['benchmarks'][0]['price'] is None
    assert 'private-token' not in json.dumps(result)
    market = Market(NOW); market.stock_snapshots = fail
    result = capture_market(lambda: (market, {}), now=NOW)
    assert result['status'] == 'partial' and result['gainers'][0]['price'] == 110
    assert result['gainers'][0]['snapshot']['price'] is None


def packet():
    return {'purpose': 'market_pulse', 'movers': [{'symbol': 'AAA', 'as_of': (now_utc()-timedelta(hours=1)).isoformat()}],
        'sources': [], 'gaps': []}


def test_news_cutoff_dedup_and_missing_source_gap():
    original = packet(); anchor = datetime.fromisoformat(original['movers'][0]['as_of'])
    def news(at, url='https://example.com/news'):
        return {'datetime': at.timestamp(), 'headline': 'Company reports higher revenue', 'summary': 'Details', 'source': 'Example', 'url': url}
    items = [news(anchor+timedelta(minutes=5)), news(anchor-timedelta(days=5)), news(anchor, 'javascript:alert(1)'),
        news(anchor), news(anchor)]
    result = collect_move_news(original, news_fetcher=lambda *args, **kwargs: items)
    assert len(result['sources']) == 1 and original['sources'] == []
    assert result['sources'][0]['symbol'] == 'AAA'
    assert result['sources'][0]['published_at'] != result['sources'][0]['retrieved_at']
    empty = collect_move_news(original, news_fetcher=lambda *args, **kwargs: [])
    assert not empty['sources'] and 'AAA' in empty['gaps'][0]


def proposal():
    return {'explanations': [{'symbol': 'AAA', 'driver': 'earnings', 'evidence': 'possible_link',
        'summary': 'Reported revenue may be relevant.', 'alternative': 'The cause is not established.',
        'citations': [{'source_id': 'news_AAA_0', 'quote': 'higher revenue'}]}]}


def receipt(value, evidence=None, **kwargs):
    evidence = evidence or {**packet(), 'sources': [{'source_id': 'news_AAA_0', 'symbol': 'AAA', 'kind': 'news', 'text': 'Company reports higher revenue'}]}
    completion = Completion(text=json.dumps(value), provider_id=BINDING.provider_id, model_id=BINDING.model_id,
        input_tokens=100, output_tokens=100, **kwargs)
    return validate_movers(completion, evidence, BINDING)


@pytest.mark.parametrize('fault', ['invented_quote', 'invented_source', 'other_symbol', 'duplicate', 'missing_citation', 'contradiction', 'too_long'])
def test_rejects_unsupported_ai_explanations(fault):
    value = proposal(); row = value['explanations'][0]
    if fault == 'invented_quote': row['citations'][0]['quote'] = 'profits doubled'
    if fault == 'invented_source': row['citations'][0]['source_id'] = 'news_OTHER_0'
    if fault == 'other_symbol': row['symbol'] = 'BBB'
    if fault == 'duplicate': value['explanations'].append(deepcopy(row))
    if fault == 'missing_citation': row['citations'] = []
    if fault == 'contradiction': row['driver'] = 'unclear'
    if fault == 'too_long': row['summary'] = 'x'*501
    assert receipt(value)['proposal'] is None


def test_accepts_grounded_explanation_and_explicit_uncertainty_but_not_tool_calls():
    assert receipt(proposal())['proposal']
    value = proposal(); value['explanations'][0].update(driver='unclear', evidence='insufficient', citations=[])
    assert receipt(value)['proposal']
    assert receipt(proposal(), tool_calls=True)['proposal'] is None
    evidence = {**packet(), 'sources': [{'source_id': 'news_AAA_0', 'symbol': 'BBB', 'kind': 'news', 'text': 'higher revenue'}]}
    assert receipt(proposal(), evidence)['proposal'] is None


@pytest.fixture
def service(tmp_path, monkeypatch):
    engine, sessions = create_session_factory(f'sqlite:///{tmp_path / "pulse.db"}')
    init_db(engine)
    market = Market()
    instance = MarketPulseService(sessions, lambda: (market, {'feed': 'iex'}))
    monkeypatch.setattr(instance.briefs, 'binding', lambda: BINDING)
    return instance


def test_cached_board_and_durable_no_double_dispatch(service):
    board = service.board()
    assert service.board()['cached'] and service.board(True)['cached']
    assert board['snapshot_id'] == service.board()['snapshot_id']
    request = PulseRequest(snapshot_id=board['snapshot_id'], provider_config_hash='a'*64)
    row, fresh = service.reserve(request)
    assert fresh and row.packet['purpose'] == 'market_pulse'
    service.snapshots.clear()  # Recovery does not depend on the in-memory capture cache.
    duplicate, fresh = service.reserve(request)
    assert duplicate.brief_id == row.brief_id and not fresh


def test_reservation_rejects_missing_or_old_capture_and_changed_provider(service):
    with pytest.raises(ValueError, match='Refresh'):
        service.reserve(PulseRequest(snapshot_id='pulse_'+'0'*32, provider_config_hash='a'*64))
    board = service.board()
    with pytest.raises(ValueError, match='provider changed'):
        service.reserve(PulseRequest(snapshot_id=board['snapshot_id'], provider_config_hash='b'*64))
    service.snapshots[board['snapshot_id']]['captured_at'] = (now_utc()-timedelta(hours=1)).isoformat()
    with pytest.raises(ValueError, match='Refresh'):
        service.reserve(PulseRequest(snapshot_id=board['snapshot_id'], provider_config_hash='a'*64))


def test_no_news_suppresses_ai_and_persists_gaps(service, monkeypatch):
    board = service.board()
    row, _ = service.reserve(PulseRequest(snapshot_id=board['snapshot_id'], provider_config_hash='a'*64))
    def collect(value, **kwargs):
        return collect_move_news(value, news_fetcher=lambda *a, **k: [])
    monkeypatch.setattr('tradingagents.ui.market_pulse.collect_move_news', collect)
    def forbidden(*a, **k): pytest.fail('AI must not run without news')
    monkeypatch.setattr('tradingagents.ui.explorer_briefs.subprocess.Popen', forbidden)
    service.briefs.dispatch(row.brief_id)
    with service.sessions() as session:
        saved = session.get(ExplorerBriefRecord, row.brief_id)
        assert saved.state == 'insufficient_evidence' and len(saved.packet['gaps']) == 2
        assert saved.packet['purpose'] == 'market_pulse' and saved.packet_hash


def test_api_snapshot_submit_poll_and_latest(service, monkeypatch):
    # Real HTTP routes, SQL persistence, and dispatch lifecycle; deterministic upstreams only.
    monkeypatch.setattr('tradingagents.ui.explorer_briefs.BriefService.binding', lambda self: BINDING)
    monkeypatch.setattr('tradingagents.ui.market_pulse.collect_move_news', lambda p, **kwargs: collect_move_news(p, news_fetcher=lambda *a, **k: []))
    app = FastAPI(); app.include_router(create_pulse_router(service.sessions, service.market_factory))
    with TestClient(app) as client:
        assert client.get('/api/market-pulse/analysis').json() == {'analysis': None}
        board = client.get('/api/market-pulse/snapshot').json()
        body = {'snapshot_id': board['snapshot_id'], 'provider_config_hash': 'a'*64}
        response = client.post('/api/market-pulse/analysis', json=body)
        assert response.status_code == 202
        identifier = response.json()['brief_id']
        saved = client.get('/api/market-pulse/analysis/'+identifier).json()
        assert saved['state'] == 'insufficient_evidence'
        assert client.get('/api/market-pulse/analysis').json()['analysis']['brief_id'] == identifier
        assert client.post('/api/market-pulse/analysis', json=body).json()['brief_id'] == identifier
        assert client.get('/api/market-pulse/analysis/missing').status_code == 404


def test_news_to_validated_receipt_is_saved_once_and_child_receives_no_secrets(service, monkeypatch):
    from pathlib import Path
    board = service.board()
    row, _ = service.reserve(PulseRequest(snapshot_id=board['snapshot_id'], provider_config_hash='a'*64))
    def collect(value, **kwargs):
        for mover in value['movers']:
            value['sources'].append({'source_id': 'news_'+mover['symbol']+'_0', 'symbol': mover['symbol'], 'kind': 'news',
                'text': 'Company reports higher revenue', 'url': 'https://example.com/news'})
        return value
    monkeypatch.setattr('tradingagents.ui.market_pulse.collect_move_news', collect)
    attempts = []
    class Process:
        returncode = 0
        def __init__(self, args, **kwargs):
            self.output = args[-1]; attempts.append(kwargs)
            assert set(kwargs['env']) <= {'PATH', 'TMPDIR', 'LANG', 'SYSTEMROOT', 'PYTHON_DOTENV_DISABLED', 'PYTHONUNBUFFERED'}
        def communicate(self, envelope, *, timeout):
            value = json.loads(envelope)
            assert value['packet']['purpose'] == 'market_pulse'
            assert len(value['packet']['movers']) == 2
            response = {'explanations': []}
            for mover in value['packet']['movers']:
                explanation = proposal()['explanations'][0]
                explanation['symbol'] = mover['symbol']
                explanation['citations'][0]['source_id'] = 'news_'+mover['symbol']+'_0'
                response['explanations'].append(explanation)
            Path(self.output).write_text(json.dumps(receipt(response, value['packet'])))
    monkeypatch.setattr('tradingagents.ui.explorer_briefs.subprocess.Popen', Process)
    monkeypatch.setattr('tradingagents.research.worker.stop_process', lambda process: None)
    service.briefs.dispatch(row.brief_id); service.briefs.dispatch(row.brief_id)
    with service.sessions() as session:
        saved = session.get(ExplorerBriefRecord, row.brief_id)
        assert saved.state == 'completed' and len(saved.receipt['proposal']['explanations']) == 2
        assert saved.packet_hash and len(attempts) == 1


def test_child_uses_movers_prompt_schema_and_validator(tmp_path, monkeypatch):
    from dataclasses import asdict
    from io import BytesIO
    from types import SimpleNamespace
    from tradingagents.ui import explorer_brief_child as child
    from tradingagents.ui.market_pulse import MOVERS_SYSTEM
    evidence = {**packet(), 'sources': [{'source_id': 'news_AAA_0', 'symbol': 'AAA', 'kind': 'news', 'text': 'Company reports higher revenue'}]}
    monkeypatch.setattr(child.sys, 'stdin', SimpleNamespace(buffer=BytesIO(json.dumps({'binding': asdict(BINDING), 'packet': evidence}).encode())))
    calls = []
    def complete(self, *, system, user, schema):
        calls.append(True)
        assert system == MOVERS_SYSTEM and 'explanations' in schema['properties']
        return Completion(text=json.dumps(proposal()), provider_id=BINDING.provider_id, model_id=BINDING.model_id, input_tokens=100, output_tokens=100)
    monkeypatch.setattr(child.ProviderExtractionClient, 'complete', complete)
    path = tmp_path/'receipt.json'; child.main(path)
    saved = json.loads(path.read_text())
    assert saved['proposal']['explanations'][0]['symbol'] == 'AAA'
    assert not saved['validation_errors'] and len(calls) == 1


def test_quote_budget_is_shared_when_one_article_mentions_multiple_movers():
    quote = ' '.join(['word']*14)
    value = proposal()
    value['explanations'][0]['citations'][0]['quote'] = quote
    other = deepcopy(value['explanations'][0]); other['symbol'] = 'BBB'; other['citations'][0]['source_id'] = 'news_BBB_0'
    value['explanations'].append(other)
    evidence = {'movers': [{'symbol': 'AAA'}, {'symbol': 'BBB'}], 'sources': [
        {'source_id': 'news_'+s+'_0', 'symbol': s, 'kind': 'news', 'text': quote, 'url': 'https://example.com/same-article'} for s in ['AAA', 'BBB']]}
    assert receipt(value, evidence)['proposal'] is None


def test_alpaca_news_uses_existing_account_and_rejects_other_symbols_or_later_revisions():
    original = packet(); original['news_provider'] = 'alpaca'
    anchor = datetime.fromisoformat(original['movers'][0]['as_of'])
    def article(**changes):
        return {'created_at': (anchor-timedelta(minutes=10)).isoformat(), 'updated_at': anchor.isoformat(),
                'symbols': ['AAA'], 'headline': 'Revenue &amp; earnings update', 'summary': '<p>Higher revenue.</p>',
                'url': 'https://example.com/update', 'source': 'Test publisher', **changes}
    class NewsMarket:
        def company_news(self, symbol, *, start, end):
            assert symbol == 'AAA' and end == anchor and start == anchor-timedelta(days=4)
            return [article(symbols=['BBB']), article(updated_at=(anchor+timedelta(minutes=1)).isoformat()),
                    article(updated_at=None), article(), article()]
    def forbidden(*args, **kwargs): pytest.fail('No Finnhub fallback should occur')
    result = collect_move_news(original, market_factory=lambda: (NewsMarket(), {}), news_fetcher=forbidden)
    assert len(result['sources']) == 1
    source = result['sources'][0]
    assert source['news_provider'] == 'alpaca' and source['updated_at'] == anchor.isoformat()
    assert source['title'] == 'Revenue & earnings update' and '<p>' not in source['text']
    assert not original['sources']


def test_alpaca_news_failure_is_an_explicit_gap_without_provider_fallback():
    original = packet(); original['news_provider'] = 'alpaca'
    def unavailable(): raise RuntimeError('private-token')
    result = collect_move_news(original, market_factory=unavailable)
    assert not result['sources'] and result['gaps']
    assert 'private-token' not in json.dumps(result)


def test_company_announcement_is_not_buried_by_newer_roundup_and_price_alert():
    original=packet(); original['news_provider']='alpaca'
    anchor=datetime.fromisoformat(original['movers'][0]['as_of'])
    def story(headline, symbols, minutes, url):
        at=(anchor-timedelta(minutes=minutes)).isoformat()
        return {'created_at':at,'updated_at':at,'symbols':symbols,'headline':headline,'summary':'',
                'source':'Publisher','url':'https://example.com/'+url}
    class NewsMarket:
        def company_news(self,*args,**kwargs):
            return [story('12 Technology Stocks Moving Today',['AAA','BBB','CCC','DDD'],1,'roundup'),
                    story('AAA Shares Halted On Circuit Breaker',['AAA'],2,'halt'),
                    story('AAA Signs Purchase Agreement',['AAA'],30,'agreement')]
    result=collect_move_news(original,market_factory=lambda:(NewsMarket(),{}))
    assert [source['title'] for source in result['sources']] == ['AAA Signs Purchase Agreement','AAA Shares Halted On Circuit Breaker']
