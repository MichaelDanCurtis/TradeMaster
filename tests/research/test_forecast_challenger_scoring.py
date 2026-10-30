import hashlib
import json
import pytest
from scripts.research.score_forecast_challengers import score


def setup_case(tmp_path):
    benchmark=tmp_path/'benchmark';benchmark.mkdir();run=tmp_path/'run';run.mkdir()
    base={'symbols':['AAPL'],'cases':[{'symbol':'AAPL','window':0,'variant':'stock','starting_close':100,
        'flat_mae_pct':3,'drift_mae_pct':2,'mae_pct':4}]}
    (benchmark/'report.json').write_text(json.dumps(base))
    (benchmark/'daily.csv').write_text('symbol,window,variant,actual\n'+''.join(f'AAPL,0,stock,{v}\n' for v in [101,102,103,104,105]))
    (benchmark/'verification.json').write_text(json.dumps({'files':{'daily.csv':hashlib.sha256((benchmark/'daily.csv').read_bytes()).hexdigest()}}))
    (run/'input.json').write_text('{}')
    intent={'kind':'test','scope':'fixture','selected_case_ids':[0],
        'benchmark_report_sha256':hashlib.sha256((benchmark/'report.json').read_bytes()).hexdigest(),
        'input_sha256':hashlib.sha256((run/'input.json').read_bytes()).hexdigest()}
    (run/'intent.json').write_text(json.dumps(intent))
    output={'results':[{'case_id':0,'forecast':[100,101,102,103,104],'inference_seconds':1}],
        'peak_rss_mb':1,'total_seconds':1}
    (run/'output.json').write_text(json.dumps(output))
    return benchmark,run,output


def test_scoring_uses_fixed_realized_prices_and_price_scale(tmp_path):
    benchmark,run,_=setup_case(tmp_path)
    result=score(run,benchmark)
    assert result['cases'][0]['mae_pct']==1
    summary=result['summaries'][0]
    assert summary['mae_pct']==1 and summary['wins_vs_flat']==1
    assert summary['direction_accuracy_pct']==100


@pytest.mark.parametrize('change',['missing','duplicate','foreign','nonfinite','wrong_horizon','changed_input','changed_benchmark','changed_actuals'])
def test_incomplete_or_changed_evidence_cannot_be_scored(tmp_path,change):
    benchmark,run,output=setup_case(tmp_path)
    if change=='missing':output['results']=[]
    elif change=='duplicate':output['results']*=2
    elif change=='foreign':output['results'][0]['case_id']=99
    elif change=='nonfinite':output['results'][0]['forecast'][0]=float('nan')
    elif change=='wrong_horizon':output['results'][0]['forecast']=[100]
    elif change=='changed_input':(run/'input.json').write_text('{"changed":true}')
    elif change=='changed_benchmark':(benchmark/'report.json').write_text('{}')
    elif change=='changed_actuals':(benchmark/'daily.csv').write_text('changed')
    (run/'output.json').write_text(json.dumps(output))
    with pytest.raises(ValueError):score(run,benchmark)
