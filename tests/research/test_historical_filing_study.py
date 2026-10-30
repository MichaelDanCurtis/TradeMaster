"""Integration guard: valid prices cannot cure an unqualified security identity."""
from pathlib import Path
from scripts.research.event_research_pilot import write_new,digest,read
from scripts.research import historical_filing_study as study


def test_full_control_with_identity_conflict_has_no_performance_claim(tmp_path,monkeypatch):
    panel={'symbols':['A','REUSED'],'benchmark':'SPY','dates':['2020-01-02','2020-01-03','2020-01-06'],
           'series':{'A':{'open':[10,11,12]},'REUSED':{'open':[1,5,100]},'SPY':{'open':[100,101,103]}},
           'valuation_only_reconciliation':{'events':[]}}
    write_new(tmp_path/'panel.json',panel)
    write_new(tmp_path/'targets.json',{'decisions':[{'date':'2020-01-02','selected':['A'],'eligible':[{'symbol':'A'}]}]})
    write_new(tmp_path/'targets-lock.json',{'sha256':digest(tmp_path/'targets.json')})
    write_new(tmp_path/'universe.json',{'decisions':[{'date':'2020-01-02','members':['A','REUSED'],'identity_conflicts':['REUSED']}]})
    cfg={'panel':str(tmp_path/'panel.json'),'liquidation':'2020-01-06','rules':{'costs_bps_per_side':[11,22]},'limitations':['fixture']}
    monkeypatch.setattr(study,'check',lambda root:cfg)
    monkeypatch.setattr(study,'check_pairs',lambda root:[])
    study.score(tmp_path)
    r=read(tmp_path/'results.json')['results']
    for cost in ['11','22']:
        assert r['full_membership_equal_weight'][cost]['state']=='incomplete'
        assert 'cagr' not in r['full_membership_equal_weight'][cost]
        assert r['filing_stability'][cost]['state']=='complete'
