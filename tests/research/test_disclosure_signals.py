from copy import deepcopy
import pytest
from scripts.research.disclosure_signals import eligible_index, normalize_senate, normalize_insider, select, dedupe


DATES = ['2020-01-02', '2020-01-03', '2020-01-06', '2020-01-07', '2020-01-08', '2020-01-09', '2020-01-10', '2020-01-13']


def event(**changes):
    return {'id': 'a', 'symbol': 'AAA', 'disclosed': '2020-01-03', 'transacted': '2019-12-01', 'amount': '5001', **changes}


def test_filing_day_never_used_and_weekend_uses_next_session():
    assert eligible_index('2020-01-03', DATES, 0) == 2
    assert eligible_index('2020-01-04', DATES, 0) == 2
    assert select([event()], DATES, 1, ['AAA'])['selected'] == []
    assert select([event()], DATES, 2, ['AAA'])['selected'] == ['AAA']


def test_five_session_delay_does_not_mean_calendar_days():
    assert eligible_index('2020-01-03', DATES, 5) == 7
    assert select([event()], DATES, 6, ['AAA'], 5)['selected'] == []
    assert select([event()], DATES, 7, ['AAA'], 5)['selected'] == ['AAA']
    with pytest.raises(ValueError):
        eligible_index('2020-01-03', DATES, -1)


def test_transaction_day_cannot_make_late_disclosure_visible():
    assert select([event(disclosed='2020-02-01', transacted='2019-01-01')], DATES, 7, ['AAA'])['selected'] == []


def test_future_disclosures_cannot_change_existing_selection():
    original = select([event()], DATES, 2, ['AAA', 'BBB'])
    future = event(id='b', symbol='BBB', disclosed='2020-01-07', amount='999999999')
    assert original == select([event(), future], DATES, 2, ['AAA', 'BBB'])


def test_rank_uses_dollars_ties_are_stable_and_membership_is_enforced():
    events = [event(), event(id='b', symbol='BBB'), event(id='c', symbol='CCC', amount='999999')]
    assert select(events, DATES, 2, ['AAA', 'BBB'])['selected'] == ['AAA', 'BBB']
    assert select(events, DATES, 2, ['AAA', 'BBB'], retired=['AAA'])['selected'] == ['BBB']
    assert select([event(disclosed='2019-01-01')], DATES, 2, ['AAA'])['selected'] == []


def test_senate_requires_publication_date_and_excludes_options():
    row = {'type': 'Purchase', 'asset_type': 'Stock', 'ticker': 'AAA', 'transaction_date': '01/02/2020', 'amount': '$1,001 - $15,000'}
    report = {'date_recieved': '01/03/2020', 'office': 'Example', 'ptr_link': 'https://efdsearch.senate.gov/search/view/ptr/example/', 'transactions': [row]}
    events, _ = normalize_senate([report])
    assert events[0]['amount'] == '1001'
    assert events[0]['disclosed'] == '2020-01-03'
    assert len(normalize_senate([report, report])[0]) == 1
    invalid = deepcopy(report); del invalid['date_recieved']
    assert normalize_senate([invalid])[0] == []
    invalid = deepcopy(report); invalid['transactions'][0]['asset_type'] = 'Stock Option'
    assert normalize_senate([invalid])[0] == []


def test_senate_html_ticker_uses_visible_text_without_following_links():
    from scripts.research.disclosure_signals import symbol
    assert symbol('<a href="https://finance.yahoo.com/q?s=AAA">AAA</a>') == 'AAA'
    with pytest.raises(ValueError):
        symbol('<a href="https://example.com">AAA BBB</a>')


def insider(**changes):
    return {'transaction_type': 'PURCHASE', 'transaction_direction': 'ACQUIRED', 'security_class': 'NON_DERIVATIVE',
            'security_title': 'Common Stock', 'security_symbol': 'AAA', 'insider_role': ['DIRECTOR'], 'cik': '123',
            'filing_date': '2020-01-03', 'event_date': '2020-01-02', 'transaction_shares': 100, 'transaction_price_per_share': 12.5, **changes}


@pytest.mark.parametrize('changes', [
    {'transaction_type': 'ACQUISITION'}, {'transaction_direction': 'DISPOSED'}, {'security_class': 'DERIVATIVE'},
    {'insider_role': ['TEN_PERCENT_OWNER']}, {'security_title': 'Preferred Stock'}, {'filing_date': None},
    {'event_date': '2020-01-04'}, {'transaction_shares': 0}, {'transaction_price_per_share': float('nan')},
])
def test_insider_rejects_ineligible_or_unusable_records(changes):
    assert normalize_insider([insider(**changes)])[0] == []


def test_insider_value_and_duplicate_normalization():
    events, audit = normalize_insider([insider(), insider()])
    assert len(events) == 1 and events[0]['amount'] == '1250.0'
    assert 'proxy' in events[0]['qualification']
    with pytest.raises(ValueError):
        dedupe([event(), event(amount='3')])
