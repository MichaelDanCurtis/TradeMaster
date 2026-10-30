from copy import deepcopy

from scripts.research.review_paper_trial_data import action_window_review


def dividend(ex_date, payable_date):
    return {'category':'cash_dividends','record':{'symbol':'MSFT','ex_date':ex_date,
        'payable_date':payable_date,'process_date':payable_date,'rate':'0.91'}}


def test_payment_after_window_does_not_hide_in_window_entitlement():
    from decimal import Decimal
    import json
    expanded={'missing':dividend('2026-08-20','2026-09-10'),
        'future':dividend('2026-09-10','2026-10-01')}
    expanded['missing']['record']['rate']=Decimal('0.91')
    result=action_window_review({},expanded,'2022-01-01','2026-09-04')
    assert result['status']=='known_effective_window_omissions'
    assert [r['source_id'] for r in result['missing_from_original']]==['missing']
    assert [r['source_id'] for r in result['after_window']]==['future']
    assert not result['effective_window_complete']
    assert json.loads(json.dumps(result))['missing_from_original'][0]['record']['rate']=='0.91'


def test_pre_window_entitlements_and_boundary_dates_remain_distinct():
    expanded={day:dividend(day,'2026-09-10') for day in ['2021-12-17','2022-01-01','2026-09-04']}
    original=deepcopy(expanded)
    result=action_window_review(original,expanded,'2022-01-01','2026-09-04')
    assert result['in_window_source_ids']==['2022-01-01','2026-09-04']
    assert len(result['before_window'])==1
    assert not result['missing_from_original'] and not result['effective_window_complete']


def test_unknown_dates_revisions_and_removed_events_are_retained_for_review():
    original={'changed':dividend('2026-08-20','2026-09-10'),'removed':dividend('2026-06-01','2026-07-01')}
    expanded=deepcopy(original);del expanded['removed'];expanded['changed']['record']['rate']='0.92'
    expanded['unknown']={'category':'unknown_type','record':{'process_date':'2026-08-20'}}
    expanded['invalid']=dividend('2026-02-30','2026-03-01')
    result=action_window_review(original,expanded,'2022-01-01','2026-09-04')
    assert result['revised_source_ids']==['changed'] and result['removed_source_ids']==['removed']
    assert {r['source_id'] for r in result['unclassified']}=={'unknown','invalid'}
    assert original['changed']['record']['rate']=='0.91'


def test_merger_uses_effective_date_and_is_not_silently_dropped():
    expanded={'merger':{'category':'cash_mergers','record':{'effective_date':'2022-03-04','acquiree_symbol':'NUAN','acquirer_symbol':'MSFT'}}}
    result=action_window_review({},expanded,'2022-01-01','2026-09-04')
    assert result['in_window_source_ids']==['merger']
    assert result['missing_from_original'][0]['category']=='cash_mergers'
