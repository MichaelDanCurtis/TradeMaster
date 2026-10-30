from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from tradingagents.ui.db import create_session_factory, init_db
from tradingagents.ui.research_desk import Desk
from tradingagents.ui.forecast_lab import ForecastLab
from tradingagents.ui.forecast_tournament import Tournament, TournamentRequest, leaderboard, condition
from tradingagents.ui.forecast_data import experiment_cases, metrics


@pytest.fixture
def tournament(tmp_path, monkeypatch):
    _, sessions = create_session_factory('sqlite:///' + str(tmp_path / 'test.db'))
    init_db(sessions.kw['bind'])
    lab = ForecastLab(sessions, lambda: None, tmp_path / 'forecast')
    monkeypatch.setattr(lab, 'runtime', lambda: {'state': 'installed', 'manifest': {'model_id': 'test', 'revision': 'pinned', 'code_revision': 'code', 'files': {}}, 'mlx': {'installed': False}})
    submit = lab.submit
    monkeypatch.setattr(lab, 'submit', lambda req: submit(req, launch=False))
    return Tournament(Desk(sessions), lab)


def request(**kwargs):
    return TournamentRequest(symbols=['NVDA'], horizons=[5, 20], request_key='batch-test-key', **kwargs)


def finish(t, job_id, changed=False):
    job = t.lab.get(job_id)
    days = []
    d = date(2022, 1, 3)
    while len(days) < 420:
        if d.weekday() < 5: days.append(d.isoformat())
        d += timedelta(days=1)
    data = {'symbol': job['request']['symbol'], 'feed': 'sip', 'end': days[359],
        'calendar': [{'date': d, 'open': '09:30', 'close': '16:00'} for d in days],
        'bars': {s: {d: {'close': 100+i+(1 if changed else 0), 'volume': 1000+i} for i,d in enumerate(days)} for s in [job['request']['symbol'], 'SPY']}}
    h = job['request']['horizon']
    cases = experiment_cases(data, h, 'development', job['request']['inputs'])
    preds = [{'forecast': c['baseline'], 'quantiles': [[v+q for q in range(-4,5)] for v in c['baseline']], 'inference_seconds': .01} for c in cases]
    result = {**data, 'horizon': h, 'cases': cases, 'runtime': {'results': preds}, 'model': t.lab.runtime()['manifest'],
        'metrics': [metrics(c, p, c['actual']) for c,p in zip(cases,preds)],
        'input_hash': t.lab.store.put_json(data), 'prediction_hash': t.lab.store.put_json(preds)}
    t.lab.update(job_id, state='completed', result_hash=t.lab.store.put_json(result))


def test_frozen_definition_idempotency_and_single_batch(tournament):
    t = tournament
    row = t.submit(request())
    assert t.submit(request())['id'] == row['id']
    with pytest.raises(HTTPException): t.submit(request(inputs='stock'))
    with pytest.raises(HTTPException): t.submit(TournamentRequest(symbols=['AAPL'], request_key='another-key'))
    frozen = t.lab.store.json(row['payload']['recipe_hash'])
    assert frozen['pins']['model']['revision'] == 'pinned'
    assert frozen['request']['horizons'] == [5, 20]
    assert t.lab.rows() == []  # definition exists before any model job


def test_sequential_children_scoring_and_no_duplicate_publication(tournament):
    t = tournament; row = t.submit(request())
    t.tick(); first = t.lab.rows()[0]
    t.tick(); assert len(t.lab.rows()) == 1
    assert t.detail(row['id'])['coverage_complete'] is False
    finish(t, first['id']); t.tick()
    assert len(t.lab.rows()) == 2
    second = next(j for j in t.lab.rows() if j['id'] != first['id'])
    finish(t, second['id']); t.tick(); t.tick()
    result = t.detail(row['id'])
    assert result['coverage_complete'] and result['payload']['state'] == 'completed'
    assert len(result['payload']['cases']) == 12  # 3 windows x 2 horizons x 2 variants
    assert len([r for r in result['leaderboard'] if r['condition']=='all']) == 4
    assert all(r['improvement_vs_flat_pct'] == 0 for r in result['leaderboard'])
    assert t.lab.store.json(result['payload']['summary_hash'])['cases'] == result['payload']['cases']


def test_failed_job_retained_and_no_zero_metric_imputed(tournament):
    t = tournament; row = t.submit(request()); t.tick()
    first = t.lab.rows()[0]
    t.lab.update(first['id'], state='failed', error='Missing data')
    t.tick(); second = next(j for j in t.lab.rows() if j['id'] != first['id'])
    finish(t, second['id']); t.tick()
    r = t.detail(row['id'])
    assert r['payload']['state']=='completed_with_failures' and not r['coverage_complete']
    assert len(r['payload']['cases']) == 6
    assert r['payload']['cells'][0]['error']=='Missing data'
    assert all(c['horizon']==20 for c in r['payload']['cases'])


def test_data_revision_between_horizons_is_excluded(tournament):
    t = tournament; row = t.submit(request()); t.tick(); first = t.lab.rows()[0]
    finish(t, first['id']); t.tick()
    second = next(j for j in t.lab.rows() if j['id'] != first['id'])
    finish(t, second['id'], changed=True); t.tick()
    r = t.detail(row['id'])
    assert not r['coverage_complete']
    assert 'data changed' in r['payload']['cells'][1]['error']
    assert len(r['payload']['cases']) == 6


def test_stop_never_launches_next_child_and_keeps_inflight_receipt(tournament):
    t = tournament; row = t.submit(request()); t.tick(); first = t.lab.rows()[0]
    t.cancel(row['id']); finish(t, first['id']); t.tick()
    assert len(t.lab.rows()) == 1
    r = t.detail(row['id'])
    assert r['payload']['state'] == 'canceled' and not r['coverage_complete']
    assert r['child_statuses'][first['id']]['state'] == 'completed'


def test_restart_keeps_evidence_and_does_not_resubmit(tournament):
    t = tournament; row = t.submit(request()); t.tick()
    t.lab.recover(); t.recover(); t.tick()
    assert t.detail(row['id'])['payload']['state'] == 'interrupted'
    assert len(t.lab.rows()) == 1


def test_pin_changes_stop_batch_before_launch(tournament, monkeypatch):
    t = tournament; row = t.submit(request())
    monkeypatch.setattr(t, 'pins', lambda device: {'model': 'changed'})
    t.tick()
    assert t.detail(row['id'])['payload']['state'] == 'interrupted'
    assert t.lab.rows() == []


def test_equal_window_weight_and_zero_error_baseline():
    common = {'horizon': 5, 'variant': 'stock', 'condition': {'label': 'rising'}, 'observations': 5,
        'mae_pct': 2, 'flat_mae_pct': 4, 'drift_mae_pct': 0, 'coverage_pct': 80, 'band_width_pct': 3, 'interval_score_pct': 4, 'inference_seconds': .1}
    rows = leaderboard([{**common, 'symbol': 'PENNY', 'mae_usd': .02}, {**common, 'symbol': 'EXPENSIVE', 'mae_usd': 200, 'mae_pct': 6}])
    all_rows = rows[0]
    assert all_rows['mae_pct'] == 4 and all_rows['improvement_vs_flat_pct'] == 0
    assert all_rows['improvement_vs_drift_pct'] is None
    assert all_rows['wins_vs_flat'] == 1 and all_rows['wins_vs_drift'] == 0


def test_conditions_use_preforecast_prices_and_have_fixed_thresholds():
    assert condition([100]*256)['label']=='sideways / lower volatility'
    assert condition(list(range(100,356)))['label']=='rising / lower volatility'
    assert condition(list(range(400,144,-1)))['label']=='falling / lower volatility'
    assert 'high volatility' in condition([100,120]*128)['label']


@pytest.mark.parametrize('changes', [{'symbols':['AAPL']*7}, {'device':'unsupported'}, {'horizons':[10]}, {'symbols':['../bad']}])
def test_invalid_batches_rejected(changes):
    with pytest.raises(ValidationError): TournamentRequest.model_validate({**request().model_dump(), **changes})


def test_restart_recovers_orphan_child_identity_without_launching(tournament):
    from tradingagents.ui.forecast_lab import ForecastRequest
    t = tournament; row = t.submit(request())
    child = t.lab.submit(ForecastRequest(symbol='NVDA', horizon=5, mode='development', inputs='compare', request_key=f'tournament_{row["id"]}_0'))
    t.lab.recover(); t.recover()
    result = t.detail(row['id'])
    assert result['payload']['cells'][0]['job_id'] == child['id']
    assert result['payload']['state'] == 'interrupted'
    t.tick(); assert len(t.lab.rows()) == 1


def test_routes_are_available_and_reject_invalid_configuration(tmp_path):
    from fastapi.testclient import TestClient
    from tradingagents.ui.api import create_app
    app = create_app(database_url='sqlite:///'+str(tmp_path/'api.db'))
    with TestClient(app) as client:
        assert client.get('/api/discover/forecast/tournaments').json() == {'tournaments': []}
        assert client.post('/api/discover/forecast/tournaments', json={'symbols':['NVDA'], 'device':'unsupported', 'inputs':'compare', 'request_key':'api-validation'}).status_code == 422
        assert client.get('/api/discover/desk/records/forecast_tournament').status_code == 404


def test_mlx_paired_request_keeps_both_variants():
    r=TournamentRequest(symbols=['NVDA'],device='mlx',inputs='compare',request_key='mlx-paired')
    assert r.inputs=='compare' and r.device=='mlx'
