import copy
import numpy as np
import pytest
from scripts.research.prediction_event_accounting import convert,simulate_events


def test_conversion_preserves_raw_cash_and_stock_entitlements():
    e={'old':'OLD','old_adjustment_factor':.5,'cash_per_raw_share':50,'successors':[{'symbol':'NEW','ratio':2,'adjustment_factor':.8}]}
    q,c,r=convert([10.,3.],7.,e,{'OLD':0,'NEW':1})
    assert q==[0,15.5] and c==257
    assert r['raw_share_equivalent']==5


def fixture():
    p={'dates':['2020-01-02','2020-01-03','2020-01-06'],'symbols':['A','B'],'benchmark':'SPY','series':{'A':{'open':[10,None,None]},'B':{'open':[8,8,10]},'SPY':{'open':[100,100,100]}}}
    rows=[{'entry_index':0,'exit_index':2,'target_weights':[1,0,0]}]
    e=[{'date':'2020-01-03','old':'A','old_adjustment_factor':1,'cash_per_raw_share':2,'successors':[{'symbol':'B','ratio':1,'adjustment_factor':1}]}]
    return p,rows,e


def test_event_cash_does_not_incur_invented_sale_fee():
    p,rows,e=fixture();a=simulate_events(p,rows,e,.01);b=simulate_events(p,rows,e,.01,True)
    # 1/1.01 starts in stock; merger delivers 0.2 cash plus 1.0 stock value per initial share equivalent.
    expected=(1/1.01)*(.2+1*.99)
    assert a['curve'][-1]['equity']==pytest.approx(expected)
    assert a['curve'][-1]['equity']==pytest.approx(b['curve'][-1]['equity'])
    assert a['corporate_actions'][0]['cash_credit']==pytest.approx(.2/1.01)


def test_missing_successor_endpoint_remains_incomplete():
    p,rows,e=fixture();p['series']['B']['open'][-1]=None
    assert simulate_events(p,rows,e,0)['state']=='incomplete'


def test_unheld_conversion_creates_no_money():
    q,c,r=convert([0.,3.],1.,{'old':'A','old_adjustment_factor':1,'cash_per_raw_share':100,'successors':[]},{'A':0,'B':1})
    assert q==[0,3] and c==1


def test_same_open_merger_does_not_receive_parent_spinoff():
    p={'dates':['2020-04-02','2020-04-03','2020-04-06'],'symbols':['OLD','PARENT','SPIN'],'benchmark':'SPY',
       'series':{'OLD':{'open':[10,None,None]},'PARENT':{'open':[20,5,5]},'SPIN':{'open':[None,15,15]},'SPY':{'open':[1,1,1]}}}
    rows=[{'entry_index':0,'exit_index':2,'target_weights':[1,0,0,0]}]
    events=[{'date':'2020-04-03','old':'OLD','old_adjustment_factor':1,'cash_per_raw_share':0,'successors':[{'symbol':'PARENT','ratio':2,'adjustment_factor':1}]},
            {'date':'2020-04-03','old':'PARENT','old_adjustment_factor':1,'cash_per_raw_share':0,'successors':[{'symbol':'PARENT','ratio':1,'adjustment_factor':1},{'symbol':'SPIN','ratio':1,'adjustment_factor':1}]}]
    a=simulate_events(p,rows,events,0);b=simulate_events(p,rows,list(reversed(events)),0)
    assert a['net_return']==pytest.approx(0)
    assert b['net_return']==pytest.approx(0)
    assert len(a['corporate_actions'])==1


def test_cancelled_predecessor_is_not_current_security_history():
    from scripts.research.prediction_identity_sensitivity import inception
    p={'dates':['2021-02-09','2021-02-10'],'series':{'EXE':{'open':[9,35],'close':[9,35],'volume':[1,2]},'A':{'open':[10,11]}}}
    q=inception(p,'EXE','2021-02-10')
    assert q['series']['EXE']=={'open':[None,35],'close':[None,35],'volume':[None,2]}
    assert q['series']['A']==p['series']['A']
    assert p['series']['EXE']['open']==[9,35]
