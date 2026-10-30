import copy
import numpy as np
import pytest
from scripts.research.prediction_improvement_targets import choose,waterfill,risk_weights
from scripts.research.prediction_fundamentals import compile_facts,snapshot,rank_observed
from scripts.research.prediction_wide_portfolios import weights_for
from scripts.research.verify_prediction_wide import targets

def test_buffer_retains_small_score_changes():
 assert choose(['A','B','C','D','E','F'],[.02,.019,.018,.017,.016,.015],['A','C'],True)==['A','C']
def test_buffer_replaces_meaningful_improvement():
 assert choose(['A','B','C','D','E','F'],[.03,.029,.018,.017,.016,.015],['A','C'],True)==['A','B']
def test_buffer_forces_exit_when_ineligible_or_rank_too_low():
 assert choose(['A','B','C','D','E','F'],[.03,.029,.018,.017,.016,.015],['Z','F'],True)==['A','B']
def test_waterfill_respects_caps_and_keeps_infeasible_cash():
 assert np.allclose(waterfill([1,100],[.2,.2],1),[.2,.2])
 assert np.allclose(waterfill([1,3],[.8,.8],1),[.25,.75])
def risk_panel():
 names=[f'S{i}' for i in range(30)];return {'symbols':names,'benchmark':'SPY','sectors':{s:str(i//5) for i,s in enumerate(names)},'series':{s:{'close':[100*(1+.001*(1+i/30))**t*(1+.002*np.sin(t)) for t in range(90)]} for i,s in enumerate(names+['SPY'])}}
def test_risk_causal_and_capped():
 p=risk_panel();a,meta=risk_weights(p,70,p['symbols']);q=copy.deepcopy(p)
 for s in q['series'].values():s['close'][71:]=[None]*19
 b,_=risk_weights(q,70,q['symbols']);assert np.array_equal(a,b);assert a.max()<=.05+1e-12;assert a.sum()<=1+1e-12;assert max(meta['sector_targets'].values())<=.2+1e-12

def fact(value,filed='2021-02-01',end='2020-12-31',start=None):
 x={'val':value,'filed':filed,'end':end,'form':'10-K','accn':'test'}
 if start:x['start']=start
 return x
def payload():return {'facts':{'us-gaap':{'NetIncomeLoss':{'units':{'USD':[fact(10,start='2020-01-01')]}},'Assets':{'units':{'USD':[fact(100)]}},'EarningsPerShareDiluted':{'units':{'USD/shares':[fact(2,start='2020-01-01')]}}}}}
def test_same_day_and_future_filings_not_visible():
 p=payload();a,_=snapshot(compile_facts(p),'2021-02-01');assert np.isnan(a).all()
 a,_=snapshot(compile_facts(p),'2021-02-02');p['facts']['us-gaap']['NetIncomeLoss']['units']['USD'].append(fact(999,filed='2022-01-01',start='2020-01-01'));b,_=snapshot(compile_facts(p),'2021-02-02');assert np.array_equal(a,b,equal_nan=True);assert a[0]==.1
def test_revision_becomes_available_only_after_filing():
 p=payload();p['facts']['us-gaap']['NetIncomeLoss']['units']['USD'].append(fact(20,filed='2021-03-01',start='2020-01-01'));c=compile_facts(p)
 assert snapshot(c,'2021-03-01')[0][0]==.1
 assert snapshot(c,'2021-03-02')[0][0]==.2
def test_missing_asset_is_not_zero_or_forward_filled():
 p=payload();p['facts']['us-gaap']['Assets']['units']['USD']=[fact(100,end='2020-09-30')];assert np.isnan(snapshot(compile_facts(p),'2021-02-02')[0][0])
def test_valuation_requires_unsplit_compatible_price():
 c=compile_facts(payload());assert snapshot(c,'2021-02-02',100,lambda end:True)[0][-1]==.02
 assert np.isnan(snapshot(c,'2021-02-02',100,lambda end:False)[0][-1])
def test_missing_values_remain_missing_after_ranking():
 x=rank_observed(np.array([[2.,np.nan],[4.,1.],[np.nan,np.nan]]));assert np.isnan(x[2]).all();assert np.array_equal(x[:2,0],[-1,1]);assert x[1,1]==0
def test_ambiguous_same_date_fact_is_rejected():
 p=payload();p['facts']['us-gaap']['NetIncomeLoss']['units']['USD'].append(fact(30,start='2020-01-01'));assert np.isnan(snapshot(compile_facts(p),'2021-02-02')[0][0])
def test_frozen_target_validation_in_both_engines():
 assert np.allclose(weights_for({'target_weights':[.2,.3,0]},'frozen_target',['A','B']),[.2,.3,0])
 for bad in [[1,1,0],[-.2,.3,0],[np.nan,0,0],[.2]]:
  with pytest.raises(ValueError):weights_for({'target_weights':bad},'frozen_target',['A','B'])
  with pytest.raises(ValueError):targets({'target_weights':bad},'frozen_target',['A','B'])

def test_forward_rejects_reused_historical_period():
 from scripts.research.forecast_prediction_improvements import validate_forward_panel
 with pytest.raises(ValueError,match='already examined'):validate_forward_panel({},'2026-09-04')
def test_forward_rejects_future_capture_and_unclosed_session():
 from datetime import datetime,timezone
 from scripts.research.forecast_prediction_improvements import validate_forward_panel
 p={'dates':['2026-09-08'],'closed_through':'2026-09-08','captured_at':'2026-09-08T20:30:00Z'}
 with pytest.raises(ValueError,match='not-yet-closed'):validate_forward_panel(p,'2026-09-08',datetime(2026,9,7,tzinfo=timezone.utc))
 validate_forward_panel(p,'2026-09-08',datetime(2026,9,8,21,tzinfo=timezone.utc))
