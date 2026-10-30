from tradingagents.research.cash_flow_graph import build_graph,eligible_reports,shuffled_cash,company_key
import numpy as np


def row(cusip,value,shares,**kw):
    return dict(CUSIP=cusip,VALUE=str(value),SSHPRNAMT=str(shares),SSHPRNAMTTYPE='SH',PUTCALL='',TITLEOFCLASS='COM',INVESTMENTDISCRETION='SOLE',OTHERMANAGER='',**kw)


def test_cash_is_not_redistributed_over_only_mapped_destinations():
    graph=build_graph({'manager':[row('target',10,2),row('mapped',20,1),row('unmapped',80,1)]},'target',['mapped'],100)
    assert graph['cash'][0]==200
    assert (graph['cash']@graph['weights'])[0]==40


def test_duplicate_target_and_shared_manager_do_not_multiply_cash():
    bad=row('target',10,2);shared=row('target',10,2);shared['OTHERMANAGER']='4'
    graph=build_graph({'duplicate':[bad,bad,row('mapped',30,3)],'shared':[shared,row('mapped',30,3)],'ok':[bad,row('mapped',30,3)]},'target',['mapped'],100)
    assert graph['managers']==['ok'] and sum(graph['cash'])==200


def test_future_amendments_do_not_remove_previously_available_holdings():
    original={'CIK':'1','SUBMISSIONTYPE':'13F-HR','FILING_DATE':'15-MAY-2019','PERIODOFREPORT':'31-MAR-2019'}
    amendment={**original,'SUBMISSIONTYPE':'13F-HR/A','FILING_DATE':'11-JUL-2019'}
    cover={'a':{'REPORTTYPE':'13F HOLDINGS REPORT','ISAMENDMENT':'N'}}
    good,_=eligible_reports({'a':original,'b':amendment},cover,'2019-07-09');assert set(good)=={'a'}
    bad,_=eligible_reports({'a':original,'b':amendment},cover,'2019-07-11');assert not bad


def test_shuffle_preserves_total_cash_and_size_groups():
    cash=np.arange(20.);aum=np.arange(20.)+1;out=shuffled_cash(cash,aum,3)
    assert out.sum()==cash.sum()
    for group in np.array_split(np.arange(20),5):assert sorted(out[group])==sorted(cash[group])


def test_issuer_normalization_keeps_economic_name_distinctions():
    assert company_key('Apple Inc.')==company_key('APPLE INC')
    assert company_key('Alphabet Inc')!=company_key('Alpha Inc')


def test_wrong_name_on_target_cusip_is_not_cash_and_destination_weight_is_not_reassigned():
    rows={'bad':[dict(row('target',10,2),NAMEOFISSUER='Unrelated Company'),dict(row('mapped',30,3),NAMEOFISSUER='Mapped Inc')],
          'ok':[dict(row('target',10,2),NAMEOFISSUER='Target Inc'),dict(row('mapped',30,3),NAMEOFISSUER='Unrelated Company'),dict(row('other',70,7),NAMEOFISSUER='Other Inc')]}
    g=build_graph(rows,'target',['mapped','other'],100,target_key=company_key('Target Inc'),destination_keys={'mapped':company_key('Mapped Inc'),'other':company_key('Other Inc')})
    assert g['managers']==['ok']
    assert np.allclose(g['cash']@g['weights'],[0,140])
    assert g['exclusions']['target_name_cusip_not_confirmed']==1
