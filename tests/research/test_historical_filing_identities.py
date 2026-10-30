import csv
import pytest
from scripts.research.prepare_historical_filing_identities import build, covers


def row(cik='0000000123',added='2010-01-01',removed='',created='2010-01-01'):
    return {'symbol':'OLD','cik':cik,'name':'Original company','sector':'energy','date_added':added,'date_removed':removed,'created_at':created}


def write_rows(tmp_path,rows):
    p=tmp_path/'history.csv'
    with p.open('w') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    return p


def universe(cik='UNVERIFIED:OLD'):
    return {'issuers':{'OLD':cik},'decisions':[{'membership_asof':'2019-03-29','members':['OLD']} ]}


def test_reused_ticker_does_not_select_current_company(tmp_path):
    source=write_rows(tmp_path,[row(removed='2020-01-01'),row('0000000999',added='2024-01-01',created='2024-01-01')])
    result=build(universe(),source)
    assert result['candidates']['OLD']['cik']=='0000000123'
    assert not result['date_conflicts']


def test_conflicting_existing_numeric_cik_fails(tmp_path):
    with pytest.raises(ValueError):build(universe('0000000888'),write_rows(tmp_path,[row()]))


def test_approximate_date_and_created_date_are_respected():
    r=row(added='2010-01-01*',removed='2020-01-01*',created='2019-04-01')
    assert not covers(r,'2019-03-29')
    assert covers(r,'2019-04-01')
    assert not covers(r,'2020-01-01')


def test_cross_source_date_conflict_remains_visible(tmp_path):
    u=universe();u['decisions'].append({'membership_asof':'2020-03-31','members':['OLD']})
    result=build(u,write_rows(tmp_path,[row(removed='2020-01-01')]))
    assert result['date_conflicts']==[{'symbol':'OLD','membership_asof':'2020-03-31'}]


def test_overlapping_different_issuers_remain_unmapped(tmp_path):
    result=build(universe(),write_rows(tmp_path,[row(),row(cik='0000000999')]))
    assert result['candidates']['OLD']['cik']=='UNVERIFIED:OLD'
