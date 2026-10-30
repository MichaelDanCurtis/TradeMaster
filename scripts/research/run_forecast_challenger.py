"""Freeze and run a challenger against the exact expanded historical benchmark."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[2]
if __name__=='__main__':sys.path.insert(0,str(ROOT))
from tradingagents.research.data.store import ArtifactStore
from tradingagents.research.data.alpaca_capture import read_capture


def main():
    p=argparse.ArgumentParser();p.add_argument('--kind',choices=['chronos2','kronos-small','kronos-base','sundial'],required=True)
    p.add_argument('--prepare-only',action='store_true');args=p.parse_args()
    benchmark=ROOT/'.research-artifacts/forecast/expanded-52-window-benchmark'
    model_root=ROOT/'.research-artifacts/forecast/challenger-models'
    out=ROOT/'.research-artifacts/forecast/challenger-benchmark'/args.kind
    if out.exists():raise ValueError('Preserve existing challenger run; output already exists')
    metadata=json.loads((benchmark/'report.json').read_text());raw=(benchmark/'model-input.json').read_bytes()
    if hashlib.sha256(raw).hexdigest()!=metadata['model_input_sha256']:raise ValueError('Benchmark inputs changed')
    original=json.loads(raw);full=args.kind=='chronos2'
    selected=[i for i,c in enumerate(metadata['cases']) if full or c['variant']=='stock']
    packet={'horizon':5,'cases':[{'case_id':i,**original['cases'][i]} for i in selected]}
    if args.kind.startswith('kronos'):
        store=ArtifactStore(ROOT/'.research-artifacts/paper-trial/objects')
        source=read_capture(store,metadata['sources']['bars']);bars={}
        if source.status!='complete':raise ValueError('Incomplete source')
        for page in source.pages:
            for symbol,rows in store.json(page.response_artifact)['bars'].items():
                for row in rows:
                    day=datetime.fromisoformat(row['t'].replace('Z','+00:00')).astimezone(ZoneInfo('America/New_York')).date().isoformat()
                    if (symbol,day) in bars:raise ValueError('Duplicate bar')
                    bars[symbol,day]=row
        for case in packet['cases']:
            meta=metadata['cases'][case['case_id']];symbol=meta['symbol']
            dates=sorted(d for s,d in bars if s==symbol and d<=meta['cutoff'])[-256:]
            assert len(dates)==256 and max(dates)<min(meta['targets'])
            rows=[bars[symbol,d] for d in dates]
            if [float(r['c']) for r in rows]!=case['values']:raise ValueError('Kronos context differs from fixed benchmark')
            case.pop('covariates');case['dates']=dates;case['target_dates']=meta['targets']
            case['ohlcva']=[[float(r[k]) for k in ['o','h','l','c','v']]+[float(r['v'])*float(r['vw'])] for r in rows]
    if args.kind=='sundial':
        for case in packet['cases']:case.pop('covariates')
    names={'chronos2':'chronos-2','kronos-small':'kronos-small','kronos-base':'kronos-base','sundial':'sundial'}
    manifests=json.loads((model_root/'verified-manifest.json').read_text());name=names[args.kind]
    checked=[name]+(['kronos-tokenizer'] if args.kind.startswith('kronos') else [])
    for n in checked:
        for filename,info in manifests[n]['files'].items():
            if hashlib.sha256((model_root/n/filename).read_bytes()).hexdigest()!=info['sha256']:raise ValueError('Model file changed')
    out.mkdir(parents=True);input_bytes=json.dumps(packet).encode();(out/'input.json').write_bytes(input_bytes)
    intent={'kind':args.kind,'created_at':datetime.now(timezone.utc).isoformat(),'benchmark_input_hash':metadata['model_input_sha256'],
        'benchmark_report_sha256':hashlib.sha256((benchmark/'report.json').read_bytes()).hexdigest(),'selected_case_ids':selected,
        'input_sha256':hashlib.sha256(input_bytes).hexdigest(),'models':{n:manifests[n] for n in checked},
        'runner_sha256':hashlib.sha256((ROOT/'scripts/research/forecast_challenger_child.py').read_bytes()).hexdigest(),
        'settings':{'device':'cpu','dtype':'float32','seed':'59137 + fixed case index','cross_learning':False,
            'chronos_point':'native 0.5 quantile','kronos_point':'native decoded path mean,10 samples,T0.6,top_p0.9,top_k0,clip5',
            'kronos_amount':'derived past volume times source VWAP, not reported dollar turnover',
            'sundial_point':'median of20 sampled paths; default50 flow steps; revin=True; sample mean secondary'},
        'scope':'Frozen same-window comparison; no realized outcomes in child input. Kronos gets richer past OHLCV data; Sundial is stock-only.'}
    if args.kind.startswith('kronos'):
        intent['kronos_code_revision']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=model_root/'kronos-code',text=True).strip()
    (out/'intent.json').write_text(json.dumps(intent,indent=2)+'\n')
    if args.prepare_only:return
    environment='.venv-sundial' if args.kind=='sundial' else '.venv-forecast-challengers'
    command=[str(ROOT/environment/'bin/python'),'-I',str(ROOT/'scripts/research/forecast_challenger_child.py'),
        '--kind',args.kind,'--input',str(out/'input.json'),'--model',str(model_root/name),'--output',str(out/'output.json')]
    if args.kind.startswith('kronos'):command+=['--code',str(model_root/'kronos-code'),'--tokenizer',str(model_root/'kronos-tokenizer')]
    env={k:v for k,v in os.environ.items() if k in ['PATH','HOME','TMPDIR','LANG']}
    env.update(HF_HUB_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1',OMP_NUM_THREADS='8',TOKENIZERS_PARALLELISM='false')
    subprocess.run(command,env=env,check=True,timeout=7200)
    print(json.dumps({'state':'completed','output':str(out)}),flush=True)

if __name__=='__main__':main()
