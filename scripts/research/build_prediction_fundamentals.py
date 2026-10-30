"""Build past-only fundamental features and preserve their capture provenance."""
import argparse,json,hashlib
from pathlib import Path
from collections import Counter
from bisect import bisect_right
import numpy as np
from scripts.research.prediction_fundamentals import compile_facts,snapshot,FEATURES

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,x):p.write_text(json.dumps(x,indent=2,allow_nan=False)+'\n')
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);a=ap.parse_args();r=a.root;source=Path(json.loads((r/'protocol.json').read_text())['source']);panel=json.loads((source/'panel-sp500-quality.json').read_text());names=panel['symbols'];dates=panel['dates'];di={d:i for i,d in enumerate(dates)};positions={s:i for i,s in enumerate(names)};raw=np.full((len(dates),len(names)),np.nan);split=raw.copy();receipt=json.loads((r/'prices/receipt.json').read_text());assert not receipt['failures']
 for filename,meta in receipt['responses'].items():
  p=r/'prices'/filename;assert sha(p)==meta['sha256'];target=raw if filename.startswith('raw-') else split
  for symbol,bars in json.loads(p.read_bytes())['bars'].items():
   j=positions[symbol]
   for b in bars:
    t=di.get(b['t'][:10])
    if t is not None:
     assert np.isnan(target[t,j]);target[t,j]=b['c'] if b['v']>0 else np.nan
 np.savez_compressed(r/'valuation-prices.npz',raw=raw,split=split,dates=dates,symbols=names)
 first=dates.index('2021-09-03');end=dates.index('2026-09-04');origins=sorted(set(range(252,end,21))|set(range(first,end-1,21)));values=np.full((len(origins),len(names),len(FEATURES)),np.nan);latest_filed=np.full((len(origins),len(names)),'',dtype='U10');source_receipt=json.loads((r/'sec/receipt.json').read_text());counts=Counter(panel['issuers'].values());coverage=[]
 for j,symbol in enumerate(names):
  cik=str(panel['issuers'][symbol]).zfill(10);p=r/'sec'/f'{cik}.json';meta=source_receipt['responses'].get(p.name)
  if meta is None:coverage.append({'symbol':symbol,'state':'missing SEC capture'});continue
  assert sha(p)==meta['sha256'];facts=compile_facts(json.loads(p.read_bytes()));ratio=raw[:,j]/split[:,j];valuation_allowed=counts[panel['issuers'][symbol]]==1 and '.' not in symbol
  for k,t in enumerate(origins):
   def unchanged(end_date):
    z=bisect_right(dates,end_date)-1
    if not valuation_allowed or z<0 or z>t:return False
    f=ratio[z:t+1];return bool(np.isfinite(f).all() and (f>0).all() and np.allclose(f,f[-1],rtol=1e-5,atol=0))
   v,e=snapshot(facts,dates[t],raw[t,j],unchanged);values[k,j]=v
   if e:latest_filed[k,j]=max(x['filed'] for x in e);assert latest_filed[k,j]<dates[t]
  coverage.append({'symbol':symbol,'state':'captured','source_sha256':meta['sha256'],'valuation_identity_allowed':valuation_allowed,'feature_observations':np.isfinite(values[:,j]).sum(axis=0).tolist()})
  if (j+1)%50==0:print('Fundamental features',j+1,'/',len(names),flush=True)
 np.savez_compressed(r/'fundamentals.npz',values=values,origins=origins,symbols=names,features=FEATURES,latest_filed=latest_filed)
 write(r/'fundamentals-coverage.json',{'origins':len(origins),'symbols':len(names),'features':FEATURES,'observed_fraction':np.isfinite(values).mean(axis=(0,1)).tolist(),'per_symbol':coverage,'sec_receipt_sha256':sha(r/'sec/receipt.json'),'price_receipt_sha256':sha(r/'prices/receipt.json'),'matrix_sha256':sha(r/'fundamentals.npz'),'implementation_notes':['Valuation excluded for issuer with multiple index share classes or any class-qualified dotted ticker.','Any split-factor change, missing factor or nonpositive price between EPS period end and decision omits valuation; no guesses about EPS restatement basis.','Other missing fundamentals remain NaN without changing price-based eligibility.']})
 print('Fundamental matrix ready',values.shape)
if __name__=='__main__':main()
