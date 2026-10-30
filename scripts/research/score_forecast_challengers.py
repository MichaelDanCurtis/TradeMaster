"""Score completed native challenger outputs against frozen benchmark outcomes."""
import argparse
from collections import defaultdict
import csv
import hashlib
import json
import math
from pathlib import Path
import statistics
ROOT=Path(__file__).resolve().parents[2]


def score(root,benchmark):
    intent=json.loads((root/'intent.json').read_text());output=json.loads((root/'output.json').read_text())
    if hashlib.sha256((benchmark/'report.json').read_bytes()).hexdigest()!=intent['benchmark_report_sha256']:
        raise ValueError('Benchmark report changed')
    if hashlib.sha256((root/'input.json').read_bytes()).hexdigest()!=intent['input_sha256']:
        raise ValueError('Challenger inputs changed')
    verified=json.loads((benchmark/'verification.json').read_text())
    if hashlib.sha256((benchmark/'daily.csv').read_bytes()).hexdigest()!=verified['files']['daily.csv']:
        raise ValueError('Preserved benchmark outcomes changed')
    base=json.loads((benchmark/'report.json').read_text());selected=intent['selected_case_ids']
    predictions=output['results']
    if [r['case_id'] for r in predictions]!=selected or len(set(selected))!=len(selected):
        raise ValueError('Missing, duplicate or reordered model outputs')
    truth=defaultdict(list)
    with (benchmark/'daily.csv').open() as f:
        for r in csv.DictReader(f):truth[r['symbol'],int(r['window']),r['variant']].append(r)
    rows=[]
    for prediction in predictions:
        c=base['cases'][prediction['case_id']];days=truth[c['symbol'],c['window'],c['variant']]
        actual=[float(d['actual']) for d in days];forecast=prediction['forecast'];scale=c['starting_close']
        if len(forecast)!=5 or not all(math.isfinite(v) for v in forecast):raise ValueError('Invalid forecast')
        error=statistics.mean(abs(a-p) for a,p in zip(actual,forecast))/scale*100
        row={'case_id':prediction['case_id'],'symbol':c['symbol'],'window':c['window'],'variant':c['variant'],
            'mae_pct':error,'flat_mae_pct':c['flat_mae_pct'],'drift_mae_pct':c['drift_mae_pct'],
            'timesfm_mae_pct':c['mae_pct'],'direction_correct':((forecast[-1]>scale)-(forecast[-1]<scale))==((actual[-1]>scale)-(actual[-1]<scale)),
            'seconds':prediction['inference_seconds']}
        if 'sample_mean' in prediction:
            row['secondary_mean_mae_pct']=statistics.mean(abs(a-p) for a,p in zip(actual,prediction['sample_mean']))/scale*100
        if 'quantiles' in prediction:
            q=prediction['quantiles'];row['coverage_pct']=100*sum(lo<=a<=hi for lo,a,hi in zip(q['0.1'],actual,q['0.9']))/5
        rows.append(row)
    summaries=[]
    for symbol in ['All four',*base['symbols']]:
        for variant in sorted({c['variant'] for c in rows}):
            group=[c for c in rows if c['variant']==variant and (symbol=='All four' or c['symbol']==symbol)]
            avg=lambda key:statistics.mean(c[key] for c in group)
            model,flat,drift=avg('mae_pct'),avg('flat_mae_pct'),avg('drift_mae_pct')
            summary={'model':intent['kind'],'symbol':symbol,'variant':variant,'windows':len(group),
                'mae_pct':model,'flat_mae_pct':flat,'drift_mae_pct':drift,'timesfm_mae_pct':avg('timesfm_mae_pct'),
                'improvement_vs_flat_pct':(1-model/flat)*100,'improvement_vs_drift_pct':(1-model/drift)*100,
                'wins_vs_flat':sum(c['mae_pct']<c['flat_mae_pct'] for c in group),
                'direction_accuracy_pct':100*avg('direction_correct'),'mean_inference_seconds':avg('seconds')}
            if 'coverage_pct' in group[0]:summary['coverage_pct']=avg('coverage_pct')
            if 'secondary_mean_mae_pct' in group[0]:summary['secondary_mean_mae_pct']=avg('secondary_mean_mae_pct')
            summaries.append(summary)
    report={'kind':intent['kind'],'scope':intent['scope'],'output_sha256':hashlib.sha256((root/'output.json').read_bytes()).hexdigest(),
        'intent_sha256':hashlib.sha256((root/'intent.json').read_bytes()).hexdigest(),'summaries':summaries,'cases':rows,
        'peak_rss_mb':output['peak_rss_mb'],'total_seconds':output['total_seconds']}
    (root/'scores.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


def main():
    p=argparse.ArgumentParser();p.add_argument('--kinds',nargs='+',required=True);args=p.parse_args()
    root=ROOT/'.research-artifacts/forecast/challenger-benchmark';benchmark=ROOT/'.research-artifacts/forecast/expanded-52-window-benchmark'
    for kind in args.kinds:
        r=score(root/kind,benchmark)
        print(json.dumps({'kind':kind,'overall':[s for s in r['summaries'] if s['symbol']=='All four'],'peak_rss_mb':r['peak_rss_mb']},indent=2))

if __name__=='__main__':main()
