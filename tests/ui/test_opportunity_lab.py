from copy import deepcopy
from datetime import date, datetime, timezone, timedelta
from unittest.mock import patch
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from tradingagents.ui.db import create_session_factory, init_db
from tradingagents.ui.research_desk import Desk
from tradingagents.ui.opportunity_lab import OpportunityLab, ScanRequest, ReplayRequest, DecisionRequest, TriageRequest, rank_candidate


@pytest.fixture
def lab(tmp_path):
    _, sessions = create_session_factory('sqlite:///' + str(tmp_path / 'test.db'))
    init_db(sessions.kw['bind'])
    class Sources:
        value = 20
        def collect(self, symbol):
            if symbol == 'FAIL': raise ValueError('provider secret must not be exposed')
            return {'symbol': symbol, 'profile': {}, 'metrics': {'revenue_growth': self.value, 'net_margin': 15},
                'financials': {'free_cash_flow': {'value': 100, 'end': date.today().isoformat()}},
                'filings': [], 'sources': [], 'gaps': [], 'security_type': 'unverified'}
    return OpportunityLab(Desk(sessions, Sources()), lambda: (object(), {}), tmp_path / 'objects')


def historical_data():
    days = []
    d = date(2023, 1, 2)
    while len(days) < 130:
        if d.weekday() < 5: days.append(d.isoformat())
        d += timedelta(days=1)
    return {'symbol': 'NVDA', 'feed': 'sip', 'observed_at': '2026-09-06T00:00:00+00:00',
        'calendar': [{'date': d, 'open': '09:30', 'close': '16:00'} for d in days],
        'bars': {'NVDA': {d: {'close': 100 + i, 'volume': i + 10} for i, d in enumerate(days)}}, 'receipts': []}


def replay(lab, horizon=2):
    data = historical_data()
    cutoff = data['calendar'][70]['date']
    with patch('tradingagents.ui.opportunity_lab.capture', return_value=data):
        return lab.create_replay(ReplayRequest(symbol='NVDA', cutoff=cutoff, horizon=horizon))


def decision(step=0):
    return DecisionRequest(expected_step=step, decision='watch', thesis='Visible trend is improving', invalidation='A sustained break of the prior range')


def test_scan_deduplicates_retains_failures_and_compares_immutable_snapshots(lab):
    row = lab.start_scan(ScanRequest(symbols=['NVDA', 'FAIL', 'NVDA']))
    with pytest.raises(HTTPException) as err: lab.start_scan(ScanRequest(symbols=['MSFT']))
    assert err.value.status_code == 409
    lab.tick()
    first = lab.desk.get(row['id'], 'opportunity_scan')['payload']
    assert first['processed'] == 1 and first['state'] == 'running'
    assert first['results'][0]['previous_snapshot_id'] is None
    assert first['results'][0]['priority'] == 1
    lab.tick()
    done = lab.desk.get(row['id'], 'opportunity_scan')['payload']
    assert done['state'] == 'completed' and done['processed'] == 2
    assert len(done['failures']) == 1 and 'secret' not in str(done)
    old_id = done['results'][0]['snapshot_id']
    lab.desk.sources.value = 25
    second = lab.start_scan(ScanRequest(symbols=['NVDA']))
    lab.tick()
    candidate = lab.desk.get(second['id'], 'opportunity_scan')['payload']['results'][0]
    assert candidate['previous_snapshot_id'] == old_id
    assert any('20% to 25%' in r['text'] for r in candidate['reasons'])
    assert lab.desk.get(old_id, 'company')['payload']['metrics']['revenue_growth'] == 20


def test_cancel_does_not_collect_remaining_symbols_and_recovery_never_retries(lab):
    row = lab.start_scan(ScanRequest(symbols=['AAPL', 'MSFT']))
    lab.cancel(row['id']); lab.tick()
    assert lab.desk.rows('company') == []
    next_row = lab.start_scan(ScanRequest(symbols=['NVDA']))
    lab.recover(); lab.tick()
    assert lab.desk.get(next_row['id'], 'opportunity_scan')['payload']['state'] == 'interrupted'
    assert lab.desk.rows('company') == []


def test_cancel_during_read_preserves_result_but_stops_scan(lab):
    row = lab.start_scan(ScanRequest(symbols=['AAPL', 'MSFT']))
    collect = lab.desk.sources.collect
    def cancel_inside(symbol):
        lab.cancel(row['id'])
        return collect(symbol)
    lab.desk.sources.collect = cancel_inside
    lab.tick(); lab.tick()
    result = lab.desk.get(row['id'], 'opportunity_scan')['payload']
    assert result['state'] == 'canceled' and result['processed'] == 1
    assert len(result['results']) == 1


def test_ranking_distinguishes_unknown_facts_first_seen_filings_and_real_deltas(lab):
    row = lab.desk.collect('NVDA')
    row['payload']['metrics'] = {}
    row['payload']['financials'] = {}
    row['payload']['filings'] = [{'accession': 'recent', 'filed': '2026-09-05'}, {'accession': 'future', 'filed': '2026-09-07'}, {'accession': 'old', 'filed': '2025-01-01'}]
    current = rank_candidate(row, None, ScanRequest(symbols=['NVDA']), date(2026, 9, 6))
    assert current['screen']['state'] == 'unknown'
    assert [f['accession'] for f in current['filings']] == ['recent']
    assert current['priority'] == 1
    repeated = rank_candidate(row, deepcopy(row), ScanRequest(symbols=['NVDA']), date(2026, 9, 6))
    assert repeated['priority'] == 0
    assert any('not verified' in gap for gap in current['gaps'])


def test_disposition_is_append_only_and_requires_membership(lab):
    row = lab.start_scan(ScanRequest(symbols=['NVDA'])); lab.tick()
    for state in ['watch', 'dismissed']:
        lab.triage(TriageRequest(scan_id=row['id'], symbol='NVDA', state=state, note='Review reason'))
    assert len(lab.desk.rows('opportunity_triage')) == 2
    with pytest.raises(HTTPException): lab.triage(TriageRequest(scan_id=row['id'], symbol='AAPL', state='watch'))


def test_replay_never_sends_unrevealed_prices_and_freezes_decision_before_advance(lab):
    view = replay(lab)
    assert len(view['bars']) == 60 and view['step'] == 0
    assert view['bars'][-1]['date'] == view['cutoff']
    assert view['revealed_price_change_pct'] is None
    assert 'target_dates' not in view and 'calendar' not in view
    advanced = lab.advance(view['id'], decision())
    assert len(advanced['bars']) == 61 and advanced['step'] == 1
    saved = advanced['decisions'][0]
    assert saved['visible_through'] == view['cutoff']
    assert lab.store.json(saved['receipt_hash'])['thesis'] == decision().thesis
    with pytest.raises(HTTPException) as err: lab.advance(view['id'], decision())
    assert err.value.status_code == 409
    second = lab.advance(view['id'], decision(1))
    assert second['complete'] and len(second['decisions']) == 2
    with pytest.raises(HTTPException): lab.advance(view['id'], decision(2))
    restarted = OpportunityLab(lab.desk, lab.resolver, lab.store.root)
    assert restarted.replay_view(lab.desk.get(view['id'], 'decision_replay')) == second


def test_replay_rejects_missing_sessions_and_unfinished_horizons(lab):
    data = historical_data()
    cutoff = data['calendar'][70]['date']
    del data['bars']['NVDA'][data['calendar'][71]['date']]
    with patch('tradingagents.ui.opportunity_lab.capture', return_value=data):
        with pytest.raises(HTTPException): lab.create_replay(ReplayRequest(symbol='NVDA', cutoff=cutoff, horizon=2))
        with pytest.raises(HTTPException): lab.create_replay(ReplayRequest(symbol='NVDA', cutoff='2023-01-07', horizon=2))
        with pytest.raises(HTTPException): lab.create_replay(ReplayRequest(symbol='NVDA', cutoff=data['calendar'][-1]['date'], horizon=2))
    assert lab.desk.rows('decision_replay') == []


def test_replay_detects_tampering_before_saving_decision(lab):
    view = replay(lab)
    lab.store.path(view['capture_hash']).write_bytes(b'corrupt')
    with pytest.raises(ValueError): lab.advance(view['id'], decision())
    assert lab.desk.get(view['id'], 'decision_replay')['payload']['step'] == 0


@pytest.mark.parametrize('changes', [{'thesis': ' ' * 20}, {'expected_step': -1}, {'decision': 'buy'}])
def test_decision_validates_meaningful_text_and_research_only_actions(changes):
    with pytest.raises(ValidationError): DecisionRequest.model_validate({**decision().model_dump(), **changes})


def test_route_wiring_and_no_unfiltered_replay_records(tmp_path):
    from tradingagents.ui.api import create_app
    app = create_app(database_url='sqlite:///' + str(tmp_path / 'api.db'))
    with TestClient(app) as client:
        assert client.get('/api/discover/opportunities').status_code == 200
        assert client.get('/api/discover/desk/records/decision_replay').status_code == 404
        assert client.post('/api/discover/opportunities/scans', json={'symbols': ['AAPL'] * 501}).status_code == 422
        assert client.post('/api/discover/opportunities/scans', json={'symbols': ['../bad']}).status_code == 422
        data = historical_data()
        with patch('tradingagents.ui.opportunity_lab.capture', return_value=data), patch.object(app.state.opportunity_lab, 'resolver', return_value=(object(), {})):
            response = client.post('/api/discover/opportunities/replays', json={'symbol': 'NVDA', 'cutoff': data['calendar'][70]['date'], 'horizon': 1})
        assert response.status_code == 200
        first = response.json()
        assert len(first['bars']) == 60 and first['decisions'] == []
        second = client.post(f'/api/discover/opportunities/replays/{first["id"]}/advance', json=decision().model_dump())
        assert second.status_code == 200 and second.json()['complete']
        assert client.get(f'/api/discover/opportunities/replays/{first["id"]}').json() == second.json()
