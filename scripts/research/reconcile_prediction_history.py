"""Prepare documented merger entitlements without changing any frozen forecast."""
import argparse,copy,json,hashlib,math
from pathlib import Path
from datetime import datetime,timezone
import numpy as np
from scripts.research.validate_prediction_history import read,write,sha
from scripts.research.prediction_event_accounting import simulate_events
from scripts.research.evaluate_astra_capsules import compare_recursive


def bars(r,name,symbol):
    path=r/'repair-capture'/name
    receipt=read(r/'repair-capture/receipt.json')['responses'][name]
    if sha(path)!=receipt['sha256']:raise ValueError('Captured price hash changed')
    return {b['t'][:10]:b for b in read(path)['bars'].get(symbol,[])}


def prepare_events(r,p,period):
    result=copy.deepcopy(p);events=[];notes=[];extra=[]
    if period=='early':
        specs=read(r/'early-events.json')
        for spec in specs:
            old=spec['old'];spec['raw_file']=old+'-event-'+old+'-raw.json'
            for c in spec['successors']:c['raw_file']=old+'-event-'+c['symbol']+'-raw.json';c['all_file']=old+'-event-'+c['symbol']+'-all.json'
        # Current provider RTX history includes pre-merger UTC, while dated
        # membership uses UTX. Apply only to holdings actually owned that day.
        for old in ['RTX','UTX']:
            specs.append({'old':old,'date':'2020-04-03','cash_per_raw_share':0,
                          'raw_file':'RTN-event-RTX-raw.json' if old=='RTX' else 'spin-UTX-raw.json',
                          'raw_symbol':'RTX' if old=='RTX' else 'UTX',
                          'sources':['utc-spin-sec.html'],
                          'successors':[{'symbol':s,'ratio':ratio,'raw_file':('RTN-event-RTX-raw.json' if s=='RTX' else 'spin-'+s+'-raw.json'),
                                         'all_file':('RTN-event-RTX-all.json' if s=='RTX' else 'spin-'+s+'-all.json')} for s,ratio in [('RTX',1),('CARR',1),('OTIS',.5)]]})
    else:
        specs=[]
        for old,new,day,ratio,source in [('DISCA','WBD','2022-04-11',1,'discovery-sec.html'),('DISCK','WBD','2022-04-11',1,'discovery-sec.html'),('CTRA','DVN','2026-05-07',.7,'coterra-sec.html')]:
            specs.append({'old':old,'date':day,'cash_per_raw_share':0,'raw_file':old+'-raw.json','sources':[source],
                          'successors':[{'symbol':new,'ratio':ratio,'raw_file':new+'-raw.json','all_file':new+'-all.json'}]})
    dates=p['dates'];ix={d:i for i,d in enumerate(dates)}
    for spec in specs:
        old=spec['old']
        if old not in p['symbols'] or spec['date'] not in ix:continue
        for source in spec['sources']:
            path=r/'event-sources'/source
            if not path.exists():raise ValueError('Missing conversion source '+source)
        raw=bars(r,spec['raw_file'],spec.get('raw_symbol',old))
        prior=[d for d in raw if d<spec['date'] and d in ix and p['series'][old]['close'][ix[d]] is not None]
        if not prior:raise ValueError('No compatible pre-event raw close '+old)
        day=max(prior);f=p['series'][old]['close'][ix[day]]/raw[day]['c']
        if not math.isfinite(f) or f<=0:raise ValueError('Invalid old adjustment factor')
        event={**spec,'old_adjustment_factor':f,'factor_anchor_date':day,'successors':[]}
        for component in spec['successors']:
            s=component['symbol'];a=bars(r,component['all_file'],s);b=bars(r,component['raw_file'],s)
            if spec['date'] not in a or spec['date'] not in b:raise ValueError('Missing successor conversion-day quote '+s)
            if s not in result['series']:
                result['series'][s]={'open':[None]*len(dates),'close':[None]*len(dates),'volume':[None]*len(dates)}
            if s not in p['symbols'] and s not in extra:extra.append(s)
            # Anchor the successor to the original panel coordinate system where
            # possible. Newly captured missing marks are scaled to that system.
            overlap=[d for d in a if d>=spec['date'] and d in ix and p['series'].get(s,{}).get('open',[None]*len(dates))[ix[d]] is not None]
            anchor=min(overlap) if overlap else spec['date']
            scaling=p['series'][s]['open'][ix[anchor]]/a[anchor]['o'] if overlap else 1.
            for d in overlap:
                expected=a[d]['o']*scaling;actual=p['series'][s]['open'][ix[d]]
                if not math.isclose(expected,actual,rel_tol=2e-5,abs_tol=1e-5):raise ValueError('Price revision incompatible with original panel '+s+' '+d)
            newfactor=a[spec['date']]['o']*scaling/b[spec['date']]['o']
            if not math.isfinite(newfactor) or newfactor<=0:raise ValueError('Invalid successor adjustment factor')
            event['successors'].append({**component,'adjustment_factor':newfactor})
            for d,bar in a.items():
                if d>=spec['date'] and d in ix and result['series'][s]['open'][ix[d]] is None and bar['v']>0:
                    result['series'][s]['open'][ix[d]]=bar['o']*scaling
            notes.append({'old':old,'successor':s,'date':spec['date'],'original_coordinate_scale':scaling,'successor_adjustment_factor':newfactor})
        events.append(event)
    result['successor_only_symbols']=extra
    result['valuation_only_reconciliation']={'events':events,'notes':notes,'rule':'Frozen forecasts and feature panels are unchanged. Missing successor valuation marks filled only from archived positive-volume observations. Merger cash is separate from securities.'}
    return result,events


def run(r):
    cfg=read(r/'protocol.json');lock=read(r/'targets-lock.json');assert lock['protocol_sha256']==sha(r/'protocol.json');assert all(sha(r/name)==h for name,h in lock['files'].items())
    prepared={};files=[]
    for u,period in [('diverse100','early'),('sp500','early'),('historical','early'),('historical','late')]:
        source=r/f'{u}-early-panel.json' if period=='early' else Path(cfg['panels'][u]);p,e=prepare_events(r,read(source),period)
        key=u+'-'+period;dest=r/(key+'-event-panel.json');files.append(dest);prepared[key]=(p,e,period,u)
    for dest in files:write(dest,prepared[dest.name.removesuffix('-event-panel.json')][0])
    write(r/'event-accounting-lock.json',{'frozen_at':datetime.now(timezone.utc).isoformat(),'targets_lock_sha256':sha(r/'targets-lock.json'),
        'files':{p.name:sha(p) for p in files},'code_sha256':{str(p):sha(p) for p in [Path(__file__),Path('scripts/research/prediction_event_accounting.py')]},
        'scope':'Economic conversion data repaired after forecasts, before event-accounting scoring. Not a model change or independently complete security master.'})
    out={}
    for key,(panel,events,period,u) in prepared.items():
        results={}
        for bps in cfg['costs_bps_per_side']:
            variants={}
            for variant in cfg['variants']:
                rows=copy.deepcopy(read(r/f'{u}-{period}-{variant if variant!="SPY" else "hgb"}-targets.json'))
                if variant=='SPY':
                    row=rows[0];row['exit_index']=rows[-1]['exit_index'];row['target_weights']=[0.]*len(panel['symbols'])+[1.];rows=[row]
                a=simulate_events(panel,rows,events,bps/10000);b=simulate_events(panel,rows,events,bps/10000,True);compare_recursive(a,b)
                variants[variant]=a;print(key,bps,variant,a['state'],a.get('cagr'),a.get('unresolved_symbols'),flush=True)
            spy=variants['SPY']
            for name,a in variants.items():
                if a['state']=='complete' and not a.get('valuation_gaps'):
                    a['beta_to_SPY']=float(np.cov(a['daily_returns'],spy['daily_returns'],ddof=1)[0,1]/np.var(spy['daily_returns'],ddof=1))
            results[str(bps)]=variants
        out[key]={'costs':results,'two_cost_solvers':'matched','qualification':'Reported specific entitlements reconciled; historical lineage/membership and settlement assumptions remain. Missing OTC marks are unresolved.'}
    write(r/'event-results.json',out)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);a=ap.parse_args();run(a.root)
