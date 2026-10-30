from copy import deepcopy
from datetime import date,timedelta
import pytest
from scripts.research.benchmark_historical_forecasts import build_cases


def fixture():
    start=date(2024,1,1)
    dates=[(start+timedelta(days=i)).isoformat() for i in range(800) if (start+timedelta(days=i)).weekday()<5]
    bars={s:{d:{'close':100+i*.1,'volume':10000+i} for i,d in enumerate(dates)} for s in ['NVDA','SPY']}
    return dates,bars


def test_fixed_windows_are_nonoverlapping_and_future_inputs_cannot_change_earlier_forecast():
    dates,bars=fixture()
    cases,truth,metadata=build_cases(dates,bars,['NVDA'],windows=4)
    assert len(cases)==len(truth)==len(metadata)==8
    assert len(set(d for c in cases[::2] for d in c['target_dates']))==20
    assert all(len(c['values'])==256 and max(c['dates'])<min(c['target_dates']) for c in cases)
    changed=deepcopy(bars)
    for symbol in changed:
        for day,row in changed[symbol].items():
            if day>=cases[0]['target_dates'][0]:row.update(close=99999,volume=1)
    new_cases,new_truth,_=build_cases(dates,changed,['NVDA'],windows=4)
    assert cases[:2]==new_cases[:2] and truth[:2]!=new_truth[:2]
    assert cases[0]['values']==cases[1]['values'] and cases[0]['baseline']==cases[1]['baseline']


def test_missing_data_and_short_or_duplicate_calendar_fail():
    dates,bars=fixture()
    with pytest.raises(ValueError):build_cases(dates[:259],bars,['NVDA'],windows=1)
    with pytest.raises(ValueError):build_cases(dates+[dates[-1]],bars,['NVDA'],windows=1)
    del bars['NVDA'][dates[-1]]
    with pytest.raises(KeyError):build_cases(dates,bars,['NVDA'],windows=1)
