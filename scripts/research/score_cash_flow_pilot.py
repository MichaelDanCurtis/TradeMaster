"""Evaluate frozen O1 portfolios; no fitting, new selections or missing-price fills."""
import argparse,copy,json
from pathlib import Path
import numpy as np
from scripts.research.event_research_pilot import read,write_new,digest,now
from scripts.research.cash_flow_pilot import check,PANEL
from scripts.research.prediction_event_accounting import simulate_events
from scripts.research.evaluate_astra_capsules import compare_recursive


def run(root):
    p=check(root);lock=read(root/'targets-lock.json');assert all(digest(root/n)==h for n,h in lock.items())
    events=sorted([read(root/n) for n in lock],key=lambda e:e['entry']);panel=read(PANEL);pos={s:i for i,s in enumerate(panel['symbols'])}
    spy=[0.]*len(pos)+[1.];names=['SPY','cash_flow','momentum','matched']+[f'shuffle_{i:03}' for i in range(p['rules']['shuffle_count'])]
    results={};diagnostics={};end=events[-1]['exit_index'];first=events[0]['entry_index'];actions=panel['valuation_only_reconciliation']['events']
    for name in names:
        results[name]={};diagnostics[name]={}
        if name=='matched' and any(e['matched_missing'] for e in events):
            results[name]={'state':'incomplete','reason':'matched-sector control unavailable'};continue
        rows=[]
        for e in events:
            weights=spy.copy()
            if name!='SPY':
                for symbol,w in e['portfolios'][name].items():weights[pos[symbol]]=w;weights[-1]-=w
            rows.append({'entry_index':e['entry_index'],'exit_index':end,'target_weights':weights})
            if e['exit_index']!=end:rows.append({'entry_index':e['exit_index'],'exit_index':end,'target_weights':spy.copy()})
        if name=='SPY':rows=[{'entry_index':first,'exit_index':end,'target_weights':spy.copy()}]
        for bps in p['rules']['cost_bps_per_side']:
            a=simulate_events(panel,rows,actions,bps/10000)
            if name in ['SPY','cash_flow','momentum','matched']:
                b=simulate_events(panel,rows,actions,bps/10000,True);compare_recursive(a,b)
            results[name][str(bps)]=a
        if name in ['SPY','cash_flow','momentum','matched']:
            for e in events:
                weights=spy.copy()
                if name!='SPY':
                    for s,w in e['portfolios'][name].items():weights[pos[s]]=w;weights[-1]-=w
                one=[{'entry_index':e['entry_index'],'exit_index':e['exit_index'],'target_weights':weights}]
                a=simulate_events(panel,one,actions,.0011)
                diagnostics[name][e['id']]={k:v for k,v in a.items() if k not in ['curve','daily_returns','ledger','corporate_actions']}
            print(name,[(bps,r.get('state'),r.get('cagr')) for bps,r in results[name].items()],flush=True)
    comparison={}
    for bps in ['11','22']:
        a=results['cash_flow'][bps];b=results['SPY'][bps]
        shuffled=[results[f'shuffle_{i:03}'][bps] for i in range(p['rules']['shuffle_count'])]
        complete=[r['net_return'] for r in shuffled if r['state']=='complete']
        comparison[bps]={'strategy_state':a['state'],'complete_shuffles':len(complete),'shuffle_net_return_median':float(np.median(complete)) if complete else None,
         'shuffle_fraction_at_least_strategy':float(np.mean(np.array(complete)>=a['net_return'])) if complete and a['state']=='complete' else None,
         'excess_cagr_to_spy':a['cagr']-b['cagr'] if a['state']==b['state']=='complete' else None,
         'qualification':'Permutation diagnostic conditional on three selected events, not independent-event statistical significance.'}
    write_new(root/'results.json',{'computed_at':now(),'results':results,'event_diagnostics':diagnostics,'comparison':comparison,'scope':'20% sleeve / 80% SPY during frozen 10-session windows, SPY otherwise. Three events are insufficient to establish alpha.'})
    write_new(root/'manifest.json',{str(x.relative_to(root)):digest(x) for x in root.rglob('*') if x.is_file()})
    print(json.dumps(comparison),flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);run(ap.parse_args().root)
