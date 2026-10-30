"""Verify frozen inputs, future-data invariance and target constraints."""
import argparse,json,hashlib,copy
from pathlib import Path
import numpy as np
from scripts.research.run_prediction_improvements import predict
from scripts.research.prediction_fundamentals import compile_facts,snapshot

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);a=ap.parse_args();r=a.root;source=Path(json.loads((r/'protocol.json').read_text())['source']);frozen=json.loads((r/'targets-frozen.json').read_text());checks=[]
 assert all(sha(r/k)==v for k,v in frozen['files'].items());checks.append('All frozen files unchanged')
 with np.load(r/'fundamentals.npz',allow_pickle=False) as arc:fund={k:arc[k] for k in arc.files}
 panel=json.loads((source/'panel-sp500-quality.json').read_text())
 for k,t in enumerate(fund['origins']):assert all(x=='' or x<panel['dates'][t] for x in fund['latest_filed'][k])
 checks.append('Every tracked fundamental filing date is strictly before its feature cutoff')
 for u in ['diverse100','sp500']:
  p=json.loads((source/f'panel-{u}-quality.json').read_text());saved=json.loads((r/f'{u}-fundamental-predictions.json').read_text())
  for index in [0,30,59]:
   row=saved['rows'][index];t=row['origin_index'];altered=copy.deepcopy(p)
   for series in altered['series'].values():
    for field in ['open','close','volume']:series[field][t+1:]=[None]*len(series[field][t+1:])
   ff={**fund,'values':fund['values'].copy()};ff['values'][fund['origins']>t]=9999999
   check=predict(altered,{'metadata':saved['metadata'],'rows':[row]},ff)['rows'][0]
   assert np.allclose(check['scores']['hgb'],row['scores']['hgb'],rtol=1e-12,atol=1e-12)
   checks.append(f'{u} origin {index}: refit unchanged with all future prices removed and future fundamental features corrupted')
  for path in r.glob(u+'-*-targets.json'):
   obj=json.loads(path.read_text())
   for row in obj['rows']:
    selected=row['selected_symbols'];assert len(selected)==len(set(selected))==int(np.ceil(len(row['eligible_symbols'])/3));assert set(selected)<=set(row['eligible_symbols']);w=np.array(row['target_weights']);assert np.isfinite(w).all() and (w>=0).all() and w.sum()<=1+1e-10
    if 'risk' in obj['variant']:
     assert w.max()<=.05+1e-10
     for sector in set(p['sectors'].values()):assert sum(w[i] for i,s in enumerate(p['symbols']) if p['sectors'][s]==sector)<=.2+1e-10
   checks.append(path.name+': all selections and targets valid')
 # Raw-source chronology check, independent of precomputed matrix membership.
 for symbol in ['AAPL','MSFT','JPM','CVX']:
  cik=str(panel['issuers'][symbol]).zfill(10)
  payload=json.loads((r/'sec'/f'{cik}.json').read_text())
  for cutoff in ['2021-09-03','2023-09-07','2026-08-13']:
   reduced=copy.deepcopy(payload)
   for fact in reduced.get('facts',{}).get('us-gaap',{}).values():
    for unit,rows in fact.get('units',{}).items():fact['units'][unit]=[x for x in rows if x.get('filed','9999')<cutoff]
   a,_=snapshot(compile_facts(payload),cutoff);b,_=snapshot(compile_facts(reduced),cutoff);assert np.array_equal(a,b,equal_nan=True)
  checks.append(cik+': raw future-filed observations removed without changing past snapshots')
 out={'state':'passed','checks':checks,'frozen_targets_sha256':sha(r/'targets-frozen.json'),'limitations':['Does not establish archival completeness of SEC aggregate facts or historical security identity; these remain documented data qualifications.','Future perturbation tests do not remove survivorship bias or current-revised price adjustment history.']};(r/'verification.json').write_text(json.dumps(out,indent=2)+'\n');print('Passed',len(checks),'verification checks')
if __name__=='__main__':main()
