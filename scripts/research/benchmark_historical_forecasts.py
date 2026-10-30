"""Fixed 52-window, four-instrument historical TimesFM comparison from saved sources."""
from __future__ import annotations
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import statistics
import sys
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[2]
if __name__=='__main__':sys.path.insert(0,str(ROOT))
from tradingagents.research.data.store import ArtifactStore
from tradingagents.research.data.alpaca_capture import read_capture
from tradingagents.research.data.alpaca_reference import read_reference_capture,_reference_records
from tradingagents.ui.forecast_lab import ForecastLab
from tradingagents.ui.forecast_data import metrics
from tradingagents.ui.forecast_tournament import condition,leaderboard


def build_cases(calendar,bars,symbols,windows=52):
    dates=sorted(calendar)
    if len(dates)!=len(set(dates)) or len(dates)<256+5*windows:
        raise ValueError('Insufficient or duplicate calendar sessions')
    cases=[];truth=[];metadata=[]
    for symbol in symbols:
        for window in range(windows):
            cut=len(dates)-5*windows+window*5
            history=dates[cut-256:cut];targets=dates[cut:cut+5]
            values=[bars[symbol][d]['close'] for d in history]
            actual=[bars[symbol][d]['close'] for d in targets]
            last=values[-1];drift=(last-values[0])/255
            for variant in ['stock','market_volume']:
                cov=None if variant=='stock' else [[bars['SPY'][d]['close'] for d in history],[bars[symbol][d]['volume'] for d in history]]
                cases.append({'variant':variant,'values':values,'covariates':cov,
                    'baseline':[last]*5,'drift_baseline':[max(0,last+drift*(j+1)) for j in range(5)],
                    'dates':history,'cutoff':history[-1],'target_dates':targets})
                truth.append(actual)
                metadata.append({'symbol':symbol,'window':window,'horizon':5,'variant':variant,'cutoff':history[-1],
                    'targets':targets,'condition':condition(values)})
    return cases,truth,metadata


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():raise ValueError('Output must be new; prior experiments are preserved')
    source_root=ROOT/'.research-artifacts/paper-trial';store=ArtifactStore(source_root/'objects')
    index=json.loads((source_root/'research-capture-index.json').read_text())
    sip=json.loads((source_root/'sip-capture-review.json').read_text())
    receipt=read_capture(store,sip['hash'])
    if receipt.status!='complete' or receipt.request.feed!='sip':raise ValueError('Complete SIP source required')
    calendar_receipt=read_reference_capture(store,index['captures']['calendar']['hash'])
    if calendar_receipt.status!='complete':raise ValueError('Complete calendar required')
    calendar,_=_reference_records(store,calendar_receipt)
    symbols=['AAPL','MSFT','NVDA','SPY'];bars={s:{} for s in symbols}
    for page in receipt.pages:
        if not page.accepted:raise ValueError('Unaccepted source page')
        for symbol,rows in store.json(page.response_artifact)['bars'].items():
            if symbol not in bars:continue
            for row in rows:
                day=datetime.fromisoformat(row['t'].replace('Z','+00:00')).astimezone(ZoneInfo('America/New_York')).date().isoformat()
                if day in bars[symbol] or day not in calendar:raise ValueError('Duplicate or non-session bar')
                bars[symbol][day]={'close':float(row['c']),'volume':float(row['v'])}
    cases,truth,metadata=build_cases(calendar,bars,symbols)
    first=min(c['dates'][0] for c in cases);last=max(c['target_dates'][-1] for c in cases)
    actions=read_reference_capture(store,index['captures']['corporate_actions']['hash'])
    if actions.status!='complete':raise ValueError('Complete action capture required')
    records,_=_reference_records(store,actions)
    splits=[a for a in records.values() if 'split' in a['category'] and a['record'].get('symbol') in symbols
        and first<=a['record'].get('ex_date','')<=last]
    if splits:raise ValueError('Split inside context/target span requires explicit price-basis handling')
    lab=ForecastLab(None,None);manifest=lab.runtime()['manifest']
    for name,expected in manifest['files'].items():
        with (lab.root/'model'/name).open('rb') as f:
            if hashlib.file_digest(f,'sha256').hexdigest()!=expected:raise ValueError('Model checksum mismatch')
    args.output.mkdir(parents=True)
    packet={'horizon':5,'cases':[{'values':c['values'],'covariates':c['covariates']} for c in cases]}
    raw=json.dumps(packet).encode();(args.output/'model-input.json').write_bytes(raw)
    intent={'schema':'historical_forecast_benchmark_v1','created_at':datetime.now(timezone.utc).isoformat(),
        'symbols':symbols,'windows_per_symbol':52,'horizon':5,'context_sessions':256,'context_start':first,
        'first_target':metadata[0]['targets'][0],'last_target':last,'variants':['stock','market_volume'],
        'model_input_sha256':hashlib.sha256(raw).hexdigest(),'model':manifest,
        'sources':{'bars':sip['hash'],'calendar':index['captures']['calendar']['hash'],'actions':index['captures']['corporate_actions']['hash']},
        'code':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in ['scripts/research/benchmark_historical_forecasts.py','scripts/research/forecast_mlx_child.py','tradingagents/ui/forecast_data.py','tradingagents/ui/forecast_tournament.py']},
        'scoring':'Equal instrument/window weights; MAE divided by final context close. Flat and 256-session drift baselines. Strict wins; no model selection per window.',
        'limitations':['Historical reconstruction using present-day source revisions; pretraining overlap unknown.',
            'Fixed convenience sample: three large technology stocks and SPY, with correlated outcomes.',
            'The two previously examined NVDA weeks are included; this is not an untouched holdout.',
            'Raw USD closes; no split reported in context/target span. Cash dividends are not reinvested.',
            'Prediction error is not strategy profit; no trades, costs or portfolio allocation are modeled.']}
    (args.output/'intent.json').write_text(json.dumps(intent,indent=2)+'\n')
    print(json.dumps({'state':'running','cases':len(cases),'first_target':intent['first_target'],'last_target':last}),flush=True)
    output=lab.infer({'horizon':5,'cases':cases},'mlx')
    (args.output/'model-output.json').write_text(json.dumps(output,indent=2)+'\n')
    results=[];daily=[]
    for case,actual,prediction,meta in zip(cases,truth,output['results'],metadata):
        m=metrics(case,prediction,actual);scale=case['values'][-1]
        result={**meta,'observations':5,'mae_pct':m['mae_usd']/scale*100,'flat_mae_pct':m['baseline_mae_usd']/scale*100,
            'drift_mae_pct':m['drift_mae_usd']/scale*100,'coverage_pct':m['interval_coverage_pct'],
            'band_width_pct':m['mean_interval_width_usd']/scale*100,'interval_score_pct':m['interval_score_usd']/scale*100,
            'inference_seconds':prediction['inference_seconds'],'mae_usd':m['mae_usd'],'starting_close':scale,
            'direction_correct':(prediction['forecast'][-1]>scale)-(prediction['forecast'][-1]<scale)==(actual[-1]>scale)-(actual[-1]<scale)}
        results.append(result)
        for day,a,p,b,d,q in zip(case['target_dates'],actual,prediction['forecast'],case['baseline'],case['drift_baseline'],prediction['quantiles']):
            daily.append({'symbol':meta['symbol'],'window':meta['window'],'variant':meta['variant'],'date':day,'starting_close':scale,
                'actual':a,'forecast':p,'flat':b,'drift':d,'q10':q[0],'q90':q[8]})
    overall=[r for r in leaderboard(results) if r['condition']=='all']
    per_symbol=[{'symbol':s,**r} for s in symbols for r in leaderboard([c for c in results if c['symbol']==s]) if r['condition']=='all']
    for row in overall:row['direction_accuracy_pct']=100*statistics.mean(c['direction_correct'] for c in results if c['variant']==row['variant'])
    report={**intent,'completed_at':datetime.now(timezone.utc).isoformat(),'overall':overall,'per_symbol':per_symbol,'cases':results}
    (args.output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    with (args.output/'daily.csv').open('w') as f:
        writer=csv.DictWriter(f,fieldnames=list(daily[0]));writer.writeheader();writer.writerows(daily)
    lines=['# Expanded historical forecast comparison','',f"{intent['first_target']} through {last}; 52 non-overlapping five-session windows per instrument.",'',
        'Errors are mean absolute daily price errors divided by each starting close. Lower is better.','',
        '| Instrument | Inputs | Model error | Flat error | Drift error | Wins vs flat |','| --- | --- | ---: | ---: | ---: | ---: |']
    for r in [*({'symbol':'All four',**x} for x in overall),*per_symbol]:
        lines.append(f"| {r['symbol']} | {r['variant']} | {r['mae_pct']:.3f}% | {r['flat_mae_pct']:.3f}% | {r['drift_mae_pct']:.3f}% | {r['wins_vs_flat']}/{r['windows']} |")
    lines.extend(['','## Scope','',*('- '+x for x in intent['limitations'])])
    (args.output/'report.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps({'overall':overall,'per_symbol':per_symbol},indent=2),flush=True)

if __name__=='__main__':main()
