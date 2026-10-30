"""Additional fixed-rule historical validation; never edit forward-study dependencies."""
import argparse, copy, hashlib, json
from datetime import datetime,timezone
from pathlib import Path
import numpy as np
from scripts.research.prediction_wide_ranking import Panel
from scripts.research.run_prediction_improvements import predict
from scripts.research.prediction_improvement_targets import choose
from scripts.research.prediction_wide_portfolios import simulate
from scripts.research.verify_prediction_wide import replay
from scripts.research.evaluate_astra_capsules import compare_recursive


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text())
def write(p,x):
 p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('x') as f:json.dump(x,f,indent=2,allow_nan=False);f.write('\n')

def prepare(r):
 r.mkdir(parents=True,exist_ok=False)
 source=Path('.research-artifacts/prediction-wide-2026-09-07');old=Path('.research-artifacts/prediction-improvements-2026-09-07')
 paths={'diverse100':source/'panel-diverse100-quality.json','sp500':source/'panel-sp500-quality.json','historical':old/'historical/panel.json'}
 write(r/'protocol.json',{'created_at':datetime.now(timezone.utc).isoformat(),'panels':{k:str(v) for k,v in paths.items()},'panel_hashes':{k:sha(v) for k,v in paths.items()},
  'early_interval':{'first_signal':'2019-03-01','last_open':'2021-09-03'},'late_interval':{'first_signal':'2021-09-03','last_open':'2026-09-04'},
  'late_historical_predictions':str(old/'historical/predictions.json'),'late_historical_predictions_sha256':sha(old/'historical/predictions.json'),
  'variants':['hgb','hgb_buffer','SPY'],'costs_bps_per_side':[11,22],
  'rules':'Unchanged HGB and mature-label expanding training; unchanged top-third equal weights and buffer .45 retention/.005 advantage; 21-session rebalance. No fundamental/risk overlay and no tuning.',
  'hypothesis':'Does the buffer improve after-cost performance consistently across earlier history and historical membership?',
  'qualification':'Additional historical follow-up, not a clean-room untouched holdout. Current cohorts remain survivor-selected; historical community membership and security lineage remain imperfect.',
  'repairs':'Only independently documented economic successor conversions and observed bars. Never infer zero, cash receipts, stale marks or sellability for missing outcomes. Repair valuation separately from features and freeze selections first.',
  'source_hashes':{p.name:sha(p) for p in [Path(__file__),Path('scripts/research/run_prediction_improvements.py'),Path('scripts/research/prediction_improvement_targets.py')]}})
 print('Protocol frozen',flush=True)

def frozen_targets(panel,pred,buffer):
 positions={s:i for i,s in enumerate(panel['symbols'])};previous=[];out=[]
 for row in pred['rows']:
  selected=choose(row['eligible_symbols'],row['scores']['hgb'],previous,buffer);previous=selected;weights=[0.]*(len(positions)+1)
  for s in selected:weights[positions[s]]=1/len(selected)
  out.append({**row,'selected':selected,'target_weights':weights})
 return out

def predictions(r):
 cfg=read(r/'protocol.json');files=[]
 for universe,path in cfg['panels'].items():
  src=Path(path);assert sha(src)==cfg['panel_hashes'][universe];full=read(src)
  # Remove all later prices and dates before feature creation or fitting.
  n=full['dates'].index(cfg['early_interval']['last_open'])+1
  p={**full,'dates':full['dates'][:n],'series':{s:{k:v[:n] for k,v in x.items()} for s,x in full['series'].items()}}
  if p.get('membership') is not None:p['membership']=p['membership'][:n]
  write(r/f'{universe}-early-panel.json',p);data=Panel(p);first=p['dates'].index(cfg['early_interval']['first_signal']);last=n-1;rows=[]
  for t in range(first,last-1,21):
   ix,x,_,_=data.features(t)
   if x is None:raise ValueError('Insufficient eligible history')
   rows.append({'date':p['dates'][t],'origin_index':t,'entry_index':t+1,'exit_index':min(t+22,last),'truncated':t+22>last,'eligible_symbols':[p['symbols'][j] for j in ix]})
  pred=predict(p,{'metadata':{'symbols':p['symbols'],'benchmark':p['benchmark']},'rows':rows})
  f=r/f'{universe}-early-predictions.json';write(f,pred);files.append(f)
  for variant in ['hgb','hgb_buffer']:
   f=r/f'{universe}-early-{variant}-targets.json';write(f,frozen_targets(p,pred,variant=='hgb_buffer'));files.append(f)
  print('Frozen early',universe,len(rows),'decisions',flush=True)
 p=read(Path(cfg['panels']['historical']));path=Path(cfg['late_historical_predictions']);assert sha(path)==cfg['late_historical_predictions_sha256'];pred=read(path)
 for variant in ['hgb','hgb_buffer']:
  f=r/f'historical-late-{variant}-targets.json';write(f,frozen_targets(p,pred,variant=='hgb_buffer'));files.append(f)
 write(r/'targets-lock.json',{'locked_at':datetime.now(timezone.utc).isoformat(),'protocol_sha256':sha(r/'protocol.json'),'files':{p.name:sha(p) for p in files}})

def score(r):
 cfg=read(r/'protocol.json');lock=read(r/'targets-lock.json');assert lock['protocol_sha256']==sha(r/'protocol.json');assert all(sha(r/k)==v for k,v in lock['files'].items());out={}
 for universe,period in [('diverse100','early'),('sp500','early'),('historical','early'),('historical','late')]:
  path=r/f'{universe}-{period}-valuation.json'
  if not path.exists():path=r/f'{universe}-early-panel.json' if period=='early' else Path(cfg['panels'][universe])
  panel=read(path);results={}
  for cost in cfg['costs_bps_per_side']:
   models={}
   for variant in cfg['variants']:
    rows=read(r/f'{universe}-{period}-{variant if variant!="SPY" else "hgb"}-targets.json')
    model='SPY' if variant=='SPY' else 'frozen_target';a=simulate(panel,rows,model,cost/10000);b=replay(panel,rows,model,cost/10000);compare_recursive(b,a)
    models[variant]=a;print(universe,period,cost,variant,a['state'],a.get('cagr'),a.get('date'),a.get('unresolved_symbols'),flush=True)
   if models['SPY']['state']=='complete':
    spy=np.array(models['SPY']['daily_returns'])
    for name,a in models.items():
     if a['state']=='complete' and not a.get('valuation_gaps'):
      dr=np.array(a['daily_returns']);a['beta_to_SPY']=float(np.cov(dr,spy,ddof=1)[0,1]/spy.var(ddof=1))
   results[str(cost)]=models
  out[universe+'-'+period]={'panel_sha256':sha(path),'costs':results,'independent_replay':'passed'}
 write(r/'results.json',out)

if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('stage',choices=['prepare','predict','score']);ap.add_argument('--root',type=Path,required=True);a=ap.parse_args();{'prepare':prepare,'predict':predictions,'score':score}[a.stage](a.root)
