import importlib.util
from pathlib import Path
import numpy as np
import pytest
spec=importlib.util.spec_from_file_location('portfolio_lab',Path(__file__).parents[2]/'scripts/research/prediction_portfolios.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def test_buys_and_final_sells_cost_real_cash():
    p=m.simulate(np.array([[10.],[10.],[10.],[10.]]),['2023-01-01','2023-01-02','2023-01-03','2023-01-04'],[{'origin_index':0,'entry_index':1,'weights':[1.]}],3,.01)
    assert p['net_return']==pytest.approx(.99/1.01-1)
    assert sum(r['fees'] for r in p['ledger'])==pytest.approx(-p['net_return'])

def test_rebalance_charges_drifted_turnover_and_conserves_cash():
    target,cash,fees,traded=m.rebalance([.8,.2],0,[.5,.5],.01)
    assert target[0]==pytest.approx(target[1])
    assert traded==pytest.approx(.6)
    assert fees==pytest.approx(.006)
    assert target.sum()+cash+fees==pytest.approx(1)
    assert cash>=0

def test_no_same_close_fill():
    with pytest.raises(ValueError,match='Signal'):
        m.simulate(np.ones((3,1)),['2023-01-01','2023-01-02','2023-01-03'],[{'origin_index':1,'entry_index':1,'weights':[1]}],2,0)

def test_next_open_and_cash_control():
    prices=np.array([[1.],[10.],[20.],[30.]])
    dates=['2023-01-01','2023-01-02','2023-01-03','2023-01-04']
    p=m.simulate(prices,dates,[{'origin_index':0,'entry_index':1,'weights':[1]}],3,0)
    assert p['net_return']==pytest.approx(2.)
    cash=m.simulate(prices,dates,[{'origin_index':0,'entry_index':1,'weights':[0]}],3,.02)
    assert cash['net_return']==pytest.approx(0.)

def test_selection_is_fixed_top_third_with_deterministic_ties():
    assert m.top_weights([2,2,2,0,0,0],list('ABCDEF'))==[.5,.5,0,0,0,0,0]

def test_rejects_delayed_fill_and_wrong_hold():
    with pytest.raises(ValueError,match='Signal'):
        m.simulate(np.ones((4,1)),['2023-01-01','2023-01-02','2023-01-03','2023-01-04'],[{'origin_index':0,'entry_index':2,'weights':[1]}],3,0)
    panel={'symbols':['A','B','C'],'benchmark':'SPY','series':{s:{'open':[1]*30} for s in ['A','B','C','SPY']}}
    with pytest.raises(ValueError,match='horizon'):
        m.evaluate_cohort(panel,[{'origin_index':0,'entry_index':1,'exit_index':7,'scores':{}}],'reversal')

def test_concentration_includes_pre_sale_drift():
    p=m.simulate(np.array([[1.,1.],[1.,1.],[9.,1.],[9.,1.]]),['2023-01-01','2023-01-02','2023-01-03','2023-01-04'],[{'origin_index':0,'entry_index':1,'weights':[.5,.5]},{'origin_index':1,'entry_index':2,'weights':[.5,.5]}],3,0)
    assert p['max_observed_weight']==pytest.approx(.9)

def test_rejects_reordered_prediction_symbols(tmp_path):
    import json,hashlib
    panel={'symbols':['A','B','C'],'benchmark':'SPY'}
    (tmp_path/'panel.json').write_text(json.dumps(panel))
    (tmp_path/'reversal').mkdir()
    canonical=hashlib.sha256(json.dumps(panel,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    (tmp_path/'reversal/predictions.json').write_text(json.dumps({'symbols':['B','A','C'],'benchmark':'SPY','panel_sha256':canonical,'rows':[]}))
    with pytest.raises(ValueError,match='identity'):
        m.normalize_predictions(tmp_path,'reversal',panel['symbols'])

def test_rejects_duplicate_ranking_rows(tmp_path):
    import json
    panel={'symbols':['A','B','C'],'benchmark':'SPY'}
    (tmp_path/'panel.json').write_text(json.dumps(panel));(tmp_path/'ranking').mkdir()
    row={'origin_index':0,'entry_index':1,'exit_index':22,'model':'ridge','symbol':'A','score':0}
    payload={'metadata':{**panel,'panel_sha256':m.sha(tmp_path/'panel.json')},'predictions':[row,row]}
    (tmp_path/'ranking/predictions.json').write_text(json.dumps(payload))
    with pytest.raises(ValueError,match='Duplicate'):
        m.normalize_predictions(tmp_path,'ranking',panel['symbols'])
