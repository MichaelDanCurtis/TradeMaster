from copy import deepcopy
from datetime import date, timedelta
import pytest
from scripts.research.replay_forecast_weeks import historical_cases


def source_data():
    start, end = date(2025, 1, 1), date(2026, 9, 4)
    dates = [(start+timedelta(days=i)).isoformat() for i in range((end-start).days+1)
             if (start+timedelta(days=i)).weekday() < 5]
    return {'symbol': 'NVDA', 'end': end.isoformat(),
        'calendar': [{'date': d} for d in dates],
        'bars': {s: {d: {'close': 100+i/10, 'volume': 1000+i} for i,d in enumerate(dates)}
                 for s in ['NVDA','SPY']}}


def test_target_prices_and_volumes_never_enter_historical_model_cases():
    original = source_data()
    cases, actual = historical_cases(original, ['2026-08-31'])
    changed = deepcopy(original)
    for symbol in changed['bars']:
        for day, bar in changed['bars'][symbol].items():
            if day >= '2026-08-31':
                bar.update(close=99999, volume=1)
    new_cases, new_actual = historical_cases(changed, ['2026-08-31'])
    assert cases == new_cases and actual != new_actual
    assert all(c['actual'] is None and len(c['values']) == 256 for c in cases)
    assert {c['variant'] for c in cases} == {'stock','market_volume'}
    assert all(c['cutoff'] == '2026-08-28' for c in cases)
    assert original == source_data()


def test_historical_replay_rejects_uncovered_or_partial_weeks_and_missing_outcomes():
    source = source_data()
    for week in ['2026-09-07', '2026-09-01']:
        with pytest.raises(ValueError):
            historical_cases(source, [week])
    short = deepcopy(source)
    short['calendar'] = [r for r in short['calendar'] if r['date'] != '2026-09-02']
    with pytest.raises(ValueError):
        historical_cases(short, ['2026-08-31'])
    del source['bars']['NVDA']['2026-09-02']
    with pytest.raises(KeyError):
        historical_cases(source, ['2026-08-31'])
