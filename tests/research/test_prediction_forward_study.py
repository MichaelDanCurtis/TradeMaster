import copy
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import pytest
from scripts.research import prediction_forward_study as f


def calendar():
    day=date(2026,9,4); result=[]
    while len(result)<285:
        if day.weekday()<5 and day.isoformat()!='2026-09-07':
            result.append({'date':day.isoformat(),'open':'09:30','close':'16:00'})
        day+=timedelta(days=1)
    return result


def test_schedule_uses_sessions_not_calendar_days():
    c=calendar();p=f.schedule(c)
    assert p[0]['decision_date']=='2026-09-08'
    assert p[0]['entry_date']=='2026-09-09'
    assert c.index(next(r for r in c if r['date']==p[1]['decision_date']))==22
    assert p[0]['exit_date']==p[1]['entry_date']
    assert len(p)==12


def test_preclose_and_late_forecasts_cannot_enter_study():
    p=f.schedule(calendar())[0]
    assert f.window(p,datetime.fromisoformat('2026-09-08T20:14:59+00:00'))=='waiting_for_close'
    assert f.window(p,datetime.fromisoformat('2026-09-08T20:15:00+00:00'))=='ready'
    assert f.window(p,datetime.fromisoformat('2026-09-09T13:24:59+00:00'))=='ready'
    assert f.window(p,datetime.fromisoformat('2026-09-09T13:25:00+00:00'))=='missed_deadline'


def test_calendar_missing_or_duplicate_sessions_rejected():
    with pytest.raises(ValueError):f.schedule(calendar()[:20])
    with pytest.raises(ValueError):f.schedule([calendar()[0]]+calendar())


def test_identities_require_unique_active_provider_security():
    a={'symbol':'A','id':'one','class':'us_equity','status':'active','tradable':True}
    assert f.identities(['A'],[a])['A']['id']=='one'
    for assets in [[],[{**a,'status':'inactive'}],[{**a,'tradable':False}]]:
        with pytest.raises(ValueError):f.identities(['A'],assets)
    with pytest.raises(ValueError):f.identities(['A','B'],[a,{**a,'symbol':'B'}])


def test_panel_preserves_missing_and_rejects_future_duplicate_bars():
    c=calendar()[:3];names=['A'];roster={'members':[{'symbol':'A','sector':'Tech','cik':'1'}]}
    b={'t':c[0]['date']+'T04:00:00Z','o':10,'c':11,'v':100}
    end={**b,'t':c[-1]['date']+'T04:00:00Z'}
    pages=[{'bars':{'A':[b],'SPY':[b,end]}}]
    p=f.build_panel(pages,c,names,c[-1]['date'],c[0]['date'],roster)
    assert p['series']['A']['close']==[11,None,None]
    assert p['symbols']==['A']
    with pytest.raises(ValueError,match='Duplicate'):f.build_panel(pages+pages,c,names,c[-1]['date'],c[0]['date'],roster)
    bad=copy.deepcopy(pages);bad[0]['bars']['A'].append({**b,'t':'2027-01-01T05:00:00Z'})
    with pytest.raises(ValueError,match='out-of-window'):f.build_panel(bad,c,names,c[-1]['date'],c[0]['date'],roster)


def test_exclusive_forecast_write_cannot_overwrite(tmp_path):
    path=tmp_path/'decision.json';f.save(path,{'selected':['A']},True)
    with pytest.raises(FileExistsError):f.save(path,{'selected':['B']},True)
    assert f.read(path)['selected']==['A']


def test_protocol_and_code_mutations_rejected(tmp_path,monkeypatch):
    monkeypatch.setattr(f,'HERE',tmp_path)
    (tmp_path/'source.py').write_text('fixed')
    f.save(tmp_path/'protocol.json',{'code_sha256':{'source.py':f.sha(tmp_path/'source.py')},'input_sha256':{}})
    f.save(tmp_path/'protocol-lock.json',{'protocol_sha256':f.sha(tmp_path/'protocol.json')})
    f.verify_protocol(tmp_path)
    (tmp_path/'source.py').write_text('changed')
    with pytest.raises(ValueError,match='code changed'):f.verify_protocol(tmp_path)


def test_missed_deadline_is_recorded_without_capture(tmp_path,monkeypatch):
    old={'decision_date':'2020-01-02','exit_date':'2020-02-04','freeze_deadline':'2020-01-03T09:25:00-05:00'}
    monkeypatch.setattr(f,'verify_protocol',lambda root:{'schedule':[old]})
    monkeypatch.setattr(f,'services',lambda target:pytest.fail('Must not fetch after missed deadline'))
    f._tick(tmp_path)
    assert f.read(tmp_path/'status.json')['state']=='needs_review_missed_decision'
    assert not (tmp_path/'decisions').exists()


def test_finish_replays_observed_only_portfolios(tmp_path,monkeypatch):
    # Synthetic prices test economic accounting, not model prediction accuracy.
    run=tmp_path/'observations'/'test';run.mkdir(parents=True)
    dates=[r['date'] for r in calendar()[:27]]
    names=['A','B','C']; members=[{'symbol':s,'sector':'Tech','cik':s} for s in names]
    panel={'dates':dates,'symbols':names,'benchmark':'SPY','sectors':{s:'Tech' for s in names},'issuers':{s:s for s in names},
           'series':{s:{'open':[100*(1+(i+1)*.0005)**t for t in range(len(dates))]} for i,s in enumerate(names+['SPY'])}}
    plans=f.schedule(calendar())
    p={'schedule':plans,'universe':names,'parameters':{'cost_bps_per_side':[11,22]},'evidence_scope':'synthetic diagnostic'}
    f.save(tmp_path/'protocol.json',p)
    monkeypatch.setattr(f,'verify_protocol',lambda root:p)
    f.save(run/'panel.json',panel)
    for sub in ['market','reference']:f.save(run/sub/'receipt.json',{'responses':{}})
    env={'plan':None,'protocol_sha256':f.sha(tmp_path/'protocol.json'),'panel_sha256':f.sha(run/'panel.json'),
         'reference_receipt_sha256':f.sha(run/'reference/receipt.json'),'market_receipt_sha256':f.sha(run/'market/receipt.json'),'observed_through':dates[-1]}
    f.save(run/'envelope.json',env)
    for plan in plans[:2]:
        d={'plan':plan,'decision_date':plan['decision_date'],'protocol_sha256':env['protocol_sha256'],
           'panel_path':str((run/'panel.json').relative_to(tmp_path)),'panel_sha256':env['panel_sha256'],
           'created_at':plan['decision_date']+'T21:00:00+00:00','eligible_symbols':names,'baseline_selected':['A'],'candidate_selected':['B']}
        prior=tmp_path/'decisions'/(plans[plan['number']-1]['decision_date']+'.json') if plan['number'] else None
        d['previous_sha256']=f.sha(prior) if prior else None
        path=tmp_path/'decisions'/(plan['decision_date']+'.json');f.save(path,d)
        f.save(tmp_path/'decision-locks'/path.name,{'sha256':f.sha(path)})
    f.finish(tmp_path,run)
    report=f.read(run/'comparison.json')
    assert report['independent_replay']=='passed'
    assert report['costs']['11']['hgb_buffer']['net_return']>report['costs']['11']['hgb']['net_return']
    assert report['costs']['22']['hgb_buffer']['net_return']<report['costs']['11']['hgb_buffer']['net_return']
    assert 'cagr' not in report['costs']['11']['hgb']
    assert report['complete_economic_performance'].startswith('unqualified')
