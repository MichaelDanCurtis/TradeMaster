"""Apply dated constituent membership without discarding unavailable former stocks."""
import argparse,json,hashlib,bisect
from pathlib import Path
import numpy as np
from scripts.research.prediction_wide_ranking import Panel

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,x):p.write_text(json.dumps(x,indent=2,allow_nan=False)+'\n')
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);a=ap.parse_args();r=a.root;source=Path(json.loads((r/'protocol.json').read_text())['source']);p=json.loads((source/'panel-sp500-quality.json').read_text());u=json.loads((source/'universe-source/universe.json').read_text());names=u['historical_union_symbols'];dates=p['dates'];lookup={d:i for i,d in enumerate(dates)};series={s:p['series'][s] for s in p['symbols']+[p['benchmark']]};receipt=json.loads((r/'historical/receipt.json').read_text());empty=[]
 for symbol in u['historical_only_symbols']:
  series[symbol]={f:[None]*len(dates) for f in ['open','high','low','close','volume','vwap']};count=0
  for name,meta in receipt['responses'].items():
   if not name.startswith(symbol+'-'):continue
   path=r/'historical'/name;assert sha(path)==meta['sha256'];payload=json.loads(path.read_bytes())
   for returned,bars in payload['bars'].items():
    assert returned==symbol
    for b in bars:
     t=lookup.get(b['t'][:10])
     if t is None:continue
     for field,short in [('open','o'),('high','h'),('low','l'),('close','c'),('volume','v'),('vwap','vw')]:series[symbol][field][t]=float(b[short]) if (b[short]>0 or field=='volume') and not (field=='open' and b['v']==0) else None
     count+=1
  if not count:empty.append(symbol)
 snapshot_dates=[x['date'] for x in u['historical_snapshots']];membership=[]
 for d in dates:
  members=set(u['historical_snapshots'][bisect.bisect_right(snapshot_dates,d)-1]['symbols']);membership.append([s in members for s in names])
 aliases={x['old']:x['new'] for x in u['ticker_aliases'] if x.get('source_capture_state')=='captured'}
 sectors={s:p['sectors'].get(s,p['sectors'].get(aliases.get(s),'Unknown historical sector')) for s in names};issuers={s:p['issuers'].get(s,p['issuers'].get(aliases.get(s),'UNVERIFIED:'+s)) for s in names}
 result={**p,'symbols':names,'series':series,'membership':membership,'sectors':sectors,'issuers':issuers,'universe_scope':'Dated community S&P membership reconstruction; historical security identities, sector history and terminal events not fully qualified','membership_source':{'sha256':sha(source/'universe-source/universe.json'),'source':'pinned community reconstruction; not independently complete official historical membership'}}
 write(r/'historical/panel.json',result);data=Panel(result);coverage=[];first=dates.index('2021-09-03');end=dates.index('2026-09-04');endpoint_gaps=[]
 for t in range(first,end-1,21):
  ix,features,momentum,info=data.features(t);coverage.append(info)
  for j in ix:
   for z in [t+1,min(t+22,end)]:
    value=series[names[j]]['open'][z]
    if value is None or not np.isfinite(value) or value<=0:endpoint_gaps.append({'origin':dates[t],'symbol':names[j],'required_date':dates[z]})
 write(r/'historical/coverage.json',{'state':'research_reconstruction_not_fully_qualified','historical_union_count':len(names),'former_requested':len(u['historical_only_symbols']),'former_empty':empty,'source_failures':receipt['failures'],'unknown_identity_count':sum(str(v).startswith('UNVERIFIED:') for v in issuers.values()),'unknown_sector_count':sum(v=='Unknown historical sector' for v in sectors.values()),'decision_coverage':coverage,'eligible_future_endpoint_gaps':endpoint_gaps,'scope':'Eligibility uses only then-membership and past history; gaps are reported after eligibility and never used to erase a forecast. No terminal payouts inferred.'})
 print(json.dumps({'union':len(names),'empty_former':len(empty),'endpoint_gaps':len(endpoint_gaps),'unknown_identities':sum(str(v).startswith('UNVERIFIED:') for v in issuers.values())}))
if __name__=='__main__':main()
