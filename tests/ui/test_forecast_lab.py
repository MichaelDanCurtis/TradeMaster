from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import json

import pytest
from fastapi import HTTPException

from tradingagents.ui.db import create_session_factory, init_db
from tradingagents.ui.forecast_data import make_cases, experiment_cases, comparison_summary, metrics, score_saved, validate_output, capture
from tradingagents.ui.forecast_lab import ForecastLab, ForecastRequest
from tradingagents.research.data.store import ArtifactStore


def data_packet():
    days = []
    d = date(2022, 1, 3)
    while len(days) < 420:
        if d.weekday() < 5:
            days.append(d.isoformat())
        d += timedelta(days=1)
    return {'symbol': 'NVDA', 'end': days[359],
        'calendar': [{'date': d, 'open': '09:30', 'close': '16:00'} for d in days],
        'bars': {s: {d: {'close': 100+i, 'volume': i+10} for i,d in enumerate(days)} for s in ['NVDA', 'SPY']}}


def output(cases, horizon=20):
    return {'results': [{'forecast': c['baseline'],
        'quantiles': [[c['values'][-1]+q for q in range(-4,5)] for _ in range(horizon)]} for c in cases]}


def test_chronological_cuts_and_covariates_never_see_future():
    data = data_packet()
    cases = make_cases(data, 20, 'development', True)
    assert len(cases) == 3
    for c in cases:
        assert len(c['values']) == 256
        assert c['dates'][-1] < c['target_dates'][0]
        assert max(c['values']) < min(c['actual'])
        assert c['covariates'][0] == c['values']
    altered = deepcopy(data)
    for d in cases[-1]['target_dates']:
        altered['bars']['SPY'][d]['close'] = 10000000
    assert make_cases(altered, 20, 'development', True)[-1]['covariates'] == cases[-1]['covariates']


def test_missing_session_is_rejected_instead_of_interpolated():
    data = data_packet()
    del data['bars']['SPY'][data['calendar'][350]['date']]
    with pytest.raises(ValueError, match='Missing required daily bar'):
        make_cases(data, 5, 'prospective', True)


def test_calendar_targets_skip_holiday_not_just_weekends():
    data = data_packet()
    holiday = data['calendar'][360]['date']
    data['calendar'] = [r for r in data['calendar'] if r['date'] != holiday]
    case = make_cases(data, 5, 'prospective', False)[0]
    assert holiday not in case['target_dates']
    assert len(case['target_dates']) == 5
    assert case['actual'] is None


def test_output_validation_rejects_crossings_nans_and_wrong_horizon():
    cases = make_cases(data_packet(), 20, 'prospective', False)
    good = output(cases)
    validate_output(good, 20, 1)
    for change in ['crossing', 'nan', 'length']:
        bad = deepcopy(good)
        if change == 'crossing': bad['results'][0]['quantiles'][0][0] = 10000
        if change == 'nan': bad['results'][0]['forecast'][0] = float('nan')
        if change == 'length': bad['results'][0]['forecast'].pop()
        with pytest.raises(ValueError): validate_output(bad, 20, 1)


def test_pending_outcomes_do_not_become_zero_error_and_revisions_block_scoring():
    data = data_packet()
    cases = make_cases(data, 20, 'prospective', False)
    saved = {**data, 'cases': cases, 'runtime': output(cases)}
    early = datetime.fromisoformat(cases[0]['target_dates'][0]+'T20:00:00+00:00')
    pending = score_saved(saved, data, early)
    assert pending['state'] == 'pending' and 'mae_usd' not in pending
    late = datetime(2025,1,1,tzinfo=timezone.utc)
    scored = score_saved(saved, data, late)
    assert scored['state'] == 'scored' and scored['mae_usd'] == 10.5
    assert scored['baseline_mae_usd'] == 10.5
    assert scored['observations'] == 20
    revised = deepcopy(data)
    revised['bars']['NVDA'][cases[0]['dates'][0]]['close'] /= 2
    assert score_saved(saved, revised, late)['state'] == 'basis_changed'


@pytest.fixture
def lab(tmp_path, monkeypatch):
    engine, sessions = create_session_factory('sqlite:///'+str(tmp_path/'forecast.db'))
    init_db(engine)
    service = ForecastLab(sessions, lambda: (_ for _ in ()).throw(AssertionError('Provider must not be called')), tmp_path/'artifacts')
    monkeypatch.setattr(service, 'runtime', lambda: {'state': 'installed'})
    return service


def test_request_idempotency_active_exclusion_and_restart_recovery(lab):
    request = ForecastRequest(symbol='NVDA', request_key='stable-key')
    a = lab.submit(request, launch=False)
    assert lab.submit(request, launch=False)['id'] == a['id']
    for other in [ForecastRequest(symbol='AAPL', request_key='stable-key'), ForecastRequest(symbol='NVDA', request_key='another-key')]:
        with pytest.raises(HTTPException) as caught: lab.submit(other, launch=False)
        assert caught.value.status_code == 409
    lab.recover()
    assert lab.get(a['id'])['state'] == 'interrupted'
    assert not lab.update(a['id'], state='completed', result_hash='fake')
    assert lab.submit(ForecastRequest(symbol='NVDA', request_key='after-restart'), launch=False)['id'] != a['id']


def test_pending_score_does_not_call_provider(lab):
    req = ForecastRequest(symbol='NVDA', request_key='future-key')
    row = lab.submit(req, launch=False)
    result = {'mode':'prospective', 'cases':[{'target_dates':['2099-01-01']} ]}
    lab.update(row['id'], state='completed', result_hash=lab.store.put_json(result))
    assert lab.score(row['id'])['state'] == 'pending'


def test_capture_paginates_pins_adjustments_and_retains_receipts(tmp_path):
    calls=[]
    class Response:
        status_code=200
        def __init__(self,payload): self.payload=payload;self.content=json.dumps(payload).encode()
        def json(self): return self.payload
    class Provider:
        def _headers(self): return {'test':'credential'}
        @property
        def _http_client(self): return self
        def get(self,url,**kw):
            calls.append((url,dict(kw['params'])))
            if url.endswith('calendar'): return Response([{'date':'2023-01-03','open':'09:30','close':'16:00'}])
            if 'page_token' not in kw['params']: return Response({'bars':{},'next_page_token':'page2'})
            return Response({'bars':{'NVDA':[{'t':'2023-01-03T05:00:00Z','c':150,'v':40}]}})
    store=ArtifactStore(tmp_path)
    result=capture(Provider(),store,'NVDA',date(2023,1,1),date(2023,1,3),'sip',False,datetime.now(timezone.utc))
    assert len(calls)==3 and calls[-1][1]['adjustment']=='split' and calls[-1][1]['asof']=='-'
    assert result['bars']['NVDA']['2023-01-03']['close']==150
    assert len(result['receipts'])==3
    assert all('credential' not in json.dumps(r) for r in result['receipts'])
    for receipt in result['receipts']: store.get(receipt['response_sha256'])


@pytest.mark.parametrize('device', ['cpu', 'mps', 'mlx'])
def test_subprocess_receives_only_past_inputs_and_no_provider_secrets(lab, monkeypatch, device):
    import tradingagents.ui.forecast_lab as module
    monkeypatch.setenv('APCA_API_SECRET_KEY','never-send-this')
    monkeypatch.setenv('OPENAI_API_KEY','never-send-ai-key')
    cases=make_cases(data_packet(),20,'development',True)
    class Process:
        def __init__(self, command, **kwargs):
            assert command[0].endswith(('.venv-timesfm-mlx' if device == 'mlx' else '.venv-timesfm')+'/bin/python')
            assert command[1] == '-I'
            assert command[2].endswith('forecast_mlx_child.py' if device == 'mlx' else 'forecast_child.py')
            assert command[-2:] == ['--device', device]
            assert 'APCA_API_SECRET_KEY' not in kwargs['env']
            assert 'OPENAI_API_KEY' not in kwargs['env']
            assert kwargs['env']['HF_HUB_OFFLINE']=='1'
            from pathlib import Path
            packet=json.loads(Path(command[3]).read_text())
            assert set(packet)=={'horizon','cases'}
            assert all(set(c)=={'values','covariates'} for c in packet['cases'])
            Path(command[4]).write_text(json.dumps(output(cases)))
        def wait(self,timeout): return 0
    monkeypatch.setattr(module.subprocess,'Popen',Process)
    lab.infer({'horizon':20,'cases':cases},device)


def test_mlx_accepts_qualified_covariates_but_requires_installed_runtime(lab, monkeypatch, tmp_path):
    import tradingagents.ui.forecast_lab as module
    for inputs in ('compare', 'market_volume'):
        assert ForecastRequest(symbol='NVDA', device='mlx', inputs=inputs, request_key='mlx-qualified').inputs == inputs
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    request = ForecastRequest(symbol='NVDA', device='mlx', inputs='stock', request_key='mlx-missing')
    with pytest.raises(HTTPException) as caught:
        lab.submit(request, launch=False)
    assert caught.value.status_code == 409 and 'optional MLX runtime' in caught.value.detail
    assert not lab.rows()


def test_paired_experiment_holds_targets_and_inputs_constant():
    cases = experiment_cases(data_packet(), 20, 'development', 'compare')
    assert len(cases) == 6
    for plain, augmented in zip(cases[:3], cases[3:]):
        assert plain['variant'] == 'stock' and augmented['variant'] == 'market_volume'
        for key in ['dates', 'values', 'actual', 'target_dates', 'baseline', 'drift_baseline']:
            assert plain[key] == augmented[key]
        assert plain['covariates'] is None
        assert len(augmented['covariates']) == 2
    results = output(cases)['results']
    scores = [metrics(c,r,c['actual']) for c,r in zip(cases,results)]
    summary = comparison_summary(cases,scores)
    assert [s['windows'] for s in summary] == [3,3]
    assert [s['observations'] for s in summary] == [60,60]
    assert all(s['mae_reduction_pct'] == 0 for s in summary)


def test_interval_score_penalizes_wide_bands_and_misses():
    case = {'target_dates':['2023-01-03'], 'baseline':[100], 'drift_baseline':[100]}
    narrow = {'forecast':[100], 'quantiles':[[96+i for i in range(9)]]}
    wide = {'forecast':[100], 'quantiles':[[60+i*10 for i in range(9)]]}
    assert metrics(case,narrow,[100])['interval_score_usd'] == 8
    assert metrics(case,wide,[100])['interval_score_usd'] == 80
    assert metrics(case,narrow,[105])['interval_score_usd'] == 18
    summary = comparison_summary([case],[metrics(case,narrow,[100])])
    assert summary[0]['mae_reduction_pct'] is None


def save_forward(lab, key='saved-forward', future=False, inputs='compare'):
    data = data_packet()
    cases = experiment_cases(data,20,'prospective',inputs)
    if future:
        for c in cases:
            c['target_dates'] = ['2099-01-01']*20
    req = ForecastRequest(symbol='NVDA', horizon=20, inputs=inputs, request_key=key)
    row = lab.submit(req,launch=False)
    source = lab.store.put_json({'bars':'source fixture'})
    saved = {**data, 'mode':'prospective','request':req.model_dump(),'feed':'sip',
        'cases':cases,'runtime':output(cases),'issued_at':'2023-01-01T00:00:00+00:00',
        'prospective_eligible':True,'receipts':[{'response_sha256':source}]}
    lab.update(row['id'],state='completed',result_hash=lab.store.put_json(saved))
    return row['id'],saved,data


def test_auto_scoring_skips_future_and_pause_survives_new_service(lab):
    save_forward(lab,future=True)
    lab.score_due()
    assert lab.outcome_worker['state']=='waiting'
    lab.set_auto_score(False)
    other=ForecastLab(lab.sessions,lab.resolver,lab.root)
    assert other.auto_score_enabled() is False
    other.score_due()
    assert other.outcome_worker['state']=='paused'


def test_auto_scoring_scores_both_variants_once_and_preserves_forecast(lab,monkeypatch):
    import tradingagents.ui.forecast_lab as module
    identifier,saved,data=save_forward(lab)
    original=lab.get(identifier)['result_hash']
    calls=[]
    monkeypatch.setattr(lab,'resolver',lambda:(object(),{}))
    monkeypatch.setattr(module,'capture',lambda *args:(calls.append('capture') or data))
    lab.score_due();lab.score_due()
    assert calls==['capture']
    detail=lab.detail(identifier)
    assert detail['result_hash']==original
    scored=detail['scores'][0]['result']
    assert scored['state']=='scored' and len(scored['case_metrics'])==2
    assert len(scored['comparison'])==2
    assert lab.score(identifier)==scored
    assert calls==['capture']


def test_auto_scoring_failed_capture_is_durable_and_backs_off(lab,monkeypatch):
    identifier,_,_=save_forward(lab)
    calls=[]
    def fail(_):
        calls.append('attempt')
        raise ValueError('Source unavailable')
    monkeypatch.setattr(lab,'score',fail)
    lab.score_due();lab.score_due()
    assert calls==['attempt']
    detail=lab.detail(identifier)
    assert detail['scores'][0]['result']['state']=='failed'
    assert detail['state']=='completed'


def test_evidence_export_preserves_hashes_and_csv_keeps_future_values_blank(lab):
    import csv,io,zipfile,hashlib
    identifier,_,_=save_forward(lab,future=True)
    rows=list(csv.DictReader(io.StringIO(lab.export_csv(identifier))))
    assert len(rows)==40 and all(row['observed_usd']=='' for row in rows)
    assert {r['variant'] for r in rows}=={'stock','market_volume'}
    with zipfile.ZipFile(io.BytesIO(lab.export_evidence(identifier))) as archive:
        assert {'forecast.json','predictions.csv','README.txt'} <= set(archive.namelist())
        objects=[name for name in archive.namelist() if name.startswith('objects/')]
        assert len(objects)>=2
        for name in objects:
            assert hashlib.sha256(archive.read(name)).hexdigest()==name.split('/')[1]
        assert not any('safetensors' in name or 'credential' in name for name in archive.namelist())


def test_timeout_kills_model_process_and_releases_handle(lab,monkeypatch):
    import tradingagents.ui.forecast_lab as module
    calls=[]
    class Process:
        def __init__(self,*args,**kwargs): pass
        def wait(self,timeout=None):
            if timeout: raise module.subprocess.TimeoutExpired('model',timeout)
            calls.append('reaped');return -9
        def kill(self): calls.append('killed')
    monkeypatch.setattr(module.subprocess,'Popen',Process)
    with pytest.raises(ValueError,match='180-second'):
        lab.infer({'horizon':20,'cases':experiment_cases(data_packet(),20,'prospective','compare')},'cpu')
    assert calls==['killed','reaped'] and lab.process is None


def test_runtime_rejects_empty_manifest_instead_of_claiming_installed(lab,monkeypatch,tmp_path):
    import tradingagents.ui.forecast_lab as module
    monkeypatch.setattr(module,'ROOT',tmp_path)
    python=tmp_path/'.venv-timesfm/bin/python';python.parent.mkdir(parents=True);python.touch()
    lab.root.mkdir(parents=True,exist_ok=True)
    for files in [{},{'../outside':'a'*64},{'model.safetensors':'bad','config.json':'a'*64,'LICENSE':'a'*64}]:
        (lab.root/'runtime.json').write_text(json.dumps({'files':files}))
        assert ForecastLab.runtime(lab)['state']=='unavailable'


def test_brief_forecast_source_is_dated_labeled_and_excludes_stale_or_wrong_symbol(lab):
    from tradingagents.ui.forecast_evidence import saved_forecast_source
    from tradingagents.ui.forecast_lab import ForecastJob
    identifier,saved,_=save_forward(lab)
    saved['model']={'model_id':'google/timesfm-3.0-pytorch','revision':'test-revision'}
    with lab.sessions() as s:
        row=s.get(ForecastJob,identifier);row.result_hash=lab.store.put_json(saved);s.add(row);s.commit()
    now=datetime(2023,1,2,tzinfo=timezone.utc)
    source,gap=saved_forecast_source(lab.sessions,'NVDA',root=lab.root,now=now)
    assert source['kind']=='model_forecast' and source['published_at']==saved['issued_at']
    assert 'not an observed market outcome' in source['text']
    assert '"outcomes": "not_scored"' in source['text']
    assert 'unvalidated' in gap
    assert saved_forecast_source(lab.sessions,'AAPL',root=lab.root,now=now)[0] is None
    assert saved_forecast_source(lab.sessions,'NVDA',root=lab.root,now=now+timedelta(days=10))[0] is None
