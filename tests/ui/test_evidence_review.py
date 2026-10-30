from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from tradingagents.research.contracts import content_hash
from tradingagents.ui.evidence_review import freeze_review_packet, price_indicators
from tradingagents.ui.explorer_briefs import validate_brief
from tests.ui.test_explorer_briefs import BINDING, completion, output

NOW = datetime(2026, 9, 6, 12, tzinfo=timezone.utc)


def context():
    dates = [(NOW.date()-timedelta(days=256-i)).isoformat() for i in range(256)]
    return {'values': list(range(1, 257)), 'dates': dates, 'cutoff': dates[-1],
            'actual': [9000]*20, 'target_dates': ['2099-01-01']*20}


def test_indicators_ignore_outcomes_and_use_exact_trailing_windows():
    case = context()
    result = price_indicators(case)
    assert result['sma_20_usd'] == 246.5 and result['sma_50_usd'] == 231.5
    assert result['return_20_sessions_pct'] == pytest.approx((256/236-1)*100)
    case['actual'] = [-9000]*20
    assert price_indicators(case) == result
    case['values'] = [100]*256
    flat = price_indicators(case)
    assert flat['realized_volatility_20_pct'] == 0 and flat['return_20_sessions_pct'] == 0


@pytest.mark.parametrize('problem', ['nan', 'zero', 'bool', 'short', 'date_order', 'cutoff'])
def test_indicators_reject_invalid_or_misaligned_prices(problem):
    case = context()
    if problem in ('nan', 'zero', 'bool'): case['values'][0] = {'nan': float('nan'), 'zero': 0, 'bool': True}[problem]
    elif problem == 'short': case['values'].pop()
    elif problem == 'date_order': case['dates'][1] = case['dates'][0]
    else: case['cutoff'] = '2020-01-01'
    with pytest.raises(ValueError): price_indicators(case)


def test_source_inventory_freezes_age_preserves_unknown_dates_and_hashes():
    source = {'source_id': 'news', 'kind': 'news', 'published_at': '2026-09-05T12:00:00+00:00',
              'retrieved_at': NOW.isoformat(), 'text': 'Reported event'}
    unknown = {'source_id': 'company', 'kind': 'company_snapshot', 'published_at': None,
               'retrieved_at': '2026-09-01', 'text': 'Saved facts'}
    packet = {'sources': [source, unknown], 'gaps': []}
    frozen = freeze_review_packet(packet, now=NOW)
    assert 'review' not in packet
    assert frozen['review']['sources'][0]['published']['age_hours'] == 24
    assert frozen['review']['sources'][1]['published']['precision'] == 'unknown'
    assert frozen['review']['sources'][1]['retrieved']['precision'] == 'date_only'
    assert frozen['review']['sources'][0]['sha256'] == content_hash(source)
    later = freeze_review_packet(packet, now=NOW+timedelta(days=1))
    assert later['review']['sources'][0]['published']['age_hours'] == 48
    assert frozen['review']['sources'][0]['published']['age_hours'] == 24
    assert not next(c for c in frozen['review']['coverage'] if c['category'] == 'Saved model forecast')['present']


def test_future_and_naive_sources_are_excluded_and_duplicate_ids_rejected():
    source = {'source_id': 'news', 'published_at': '2026-09-07', 'retrieved_at': NOW.isoformat(), 'text': 'future'}
    for stamp in ['2026-09-07', '2026-09-07T00:00:00+00:00', '2026-09-05T00:00:00']:
        source['published_at'] = stamp
        frozen = freeze_review_packet({'sources': [source], 'gaps': []}, now=NOW)
        assert not frozen['sources'] and 'excluded' in frozen['gaps'][0]
    source['published_at'] = None
    with pytest.raises(ValueError, match='Duplicate'):
        freeze_review_packet({'sources': [source, source], 'gaps': []}, now=NOW)


def test_comparisons_require_two_real_sources_and_cannot_be_observations():
    packet = {'sources': [{'source_id': 'news_1', 'text': 'higher revenue'},
                          {'source_id': 'filing', 'text': 'Revenue grew 10%.'}]}
    proposal = output()
    check = {'kind': 'inference', 'relationship': 'agreement', 'text': 'The reports may concern the same growth.',
             'citations': [{'source_id': 'news_1', 'quote': 'higher revenue'}, {'source_id': 'filing', 'quote': 'Revenue grew 10%.'}]}
    proposal['evidence_checks'] = [check]
    assert validate_brief(completion(proposal), packet, BINDING)['proposal']
    for change in ['duplicate', 'invented', 'observation']:
        bad = deepcopy(proposal)
        if change == 'duplicate': bad['evidence_checks'][0]['citations'][1] = check['citations'][0]
        elif change == 'invented': bad['evidence_checks'][0]['citations'][1]['quote'] = 'Revenue doubled.'
        else: bad['evidence_checks'][0]['kind'] = 'observation'
        assert validate_brief(completion(bad), packet, BINDING)['proposal'] is None


def test_export_verifies_preserved_packet_hash(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from tradingagents.ui.db import create_session_factory, init_db
    from tradingagents.ui.explorer_briefs import ExplorerBriefRecord, create_brief_router
    engine, sessions = create_session_factory('sqlite:///'+str(tmp_path/'export.db'))
    init_db(engine)
    packet = {'sources': [], 'gaps': ['No evidence']}
    row = ExplorerBriefRecord(symbol='NVDA', idempotency_key='export-test-request', request_hash='a'*64,
        provider_config_hash='a'*64, provider_id='codex', model_id='test', deadline_at=NOW,
        state='completed', packet=packet, packet_hash=content_hash(packet))
    with sessions() as session: session.add(row); session.commit()
    app = FastAPI(); app.include_router(create_brief_router(sessions, None)); client = TestClient(app)
    path = f'/api/discover/briefs/{row.brief_id}/evidence.json'
    response = client.get(path)
    assert response.status_code == 200 and response.json()['packet_hash'] == content_hash(packet)
    with sessions() as session:
        stored = session.get(ExplorerBriefRecord, row.brief_id)
        stored.packet_hash = '0'*64; session.add(stored); session.commit()
    assert client.get(path).status_code == 409
    assert client.get('/api/discover/briefs/absent/evidence.json').status_code == 404
