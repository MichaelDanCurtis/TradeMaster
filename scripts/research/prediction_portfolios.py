"""Costed, next-open portfolio evaluation of frozen ranking predictions."""
from __future__ import annotations
import argparse, hashlib, json, math
from pathlib import Path
import numpy as np
from scipy.stats import spearmanr


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def write(path, obj): path.write_text(json.dumps(obj,indent=2,allow_nan=False)+'\n')

def rebalance(values, cash, weights, rate):
    """Solve self-financing target weights after paying both sides of turnover."""
    values=np.asarray(values,dtype=float);weights=np.asarray(weights,dtype=float)
    if values.shape!=weights.shape or not np.isfinite(values).all() or not np.isfinite(weights).all(): raise ValueError('Invalid holdings')
    if (values<0).any() or (weights<0).any() or weights.sum()>1+1e-12 or cash< -1e-12 or not 0<=rate<1: raise ValueError('Long-only unlevered inputs required')
    equity=float(values.sum()+cash)
    lo,hi=0.,equity
    for _ in range(80):
        mid=(lo+hi)/2
        if mid+rate*float(np.abs(weights*mid-values).sum())>equity: hi=mid
        else: lo=mid
    after=(lo+hi)/2
    target=weights*after; traded=float(np.abs(target-values).sum());fees=rate*traded
    new_cash=equity-float(target.sum())-fees
    if new_cash < -1e-10: raise ArithmeticError('Negative cash')
    return target,max(0.,new_cash),fees,traded

def simulate(opens, dates, events, final_index, rate):
    """Daily open marks; final liquidation; events supply weights at known entry dates."""
    prices=np.asarray(opens,dtype=float)
    if prices.ndim!=2 or not np.isfinite(prices).all() or (prices<=0).any(): raise ValueError('Invalid prices')
    if not events or len({e['entry_index'] for e in events})!=len(events): raise ValueError('Missing/duplicate events')
    first=min(e['entry_index'] for e in events)
    if not 0<=first<final_index<len(prices): raise ValueError('Invalid evaluation range')
    if any(e['entry_index']>=final_index or e['origin_index']+1!=e['entry_index'] for e in events): raise ValueError('Signal must precede fill')
    eventmap={e['entry_index']:e for e in events}
    units=np.zeros(prices.shape[1]);cash=1.;curve=[];ledger=[];fees_total=0.;turnover_sum=0.;max_weight=0.;exposures=[]
    for i in range(first,final_index+1):
        values=units*prices[i];before=float(values.sum()+cash)
        max_weight=max(max_weight,float(np.max(values/before)))
        target=np.zeros_like(units) if i==final_index else (np.asarray(eventmap[i]['weights']) if i in eventmap else None)
        if target is not None:
            values,cash,fees,traded=rebalance(values,cash,target,rate)
            units=values/prices[i];fees_total+=fees;turnover_sum+=traded/before
            ledger.append({'index':i,'date':dates[i],'kind':'liquidation' if i==final_index else 'rebalance','equity_before':before,
                'equity_after':float(values.sum()+cash),'fees':fees,'traded_notional':traded,'traded_fraction_of_equity':traded/before,
                'target_weights':target.tolist()})
        equity=float((units*prices[i]).sum()+cash)
        max_weight=max(max_weight,float(np.max(units*prices[i]/equity)))
        exposures.append(float((units*prices[i]).sum()/equity))
        curve.append({'index':i,'date':dates[i],'equity':equity,'cash':cash})
    equity=np.array([1.]+[r['equity'] for r in curve]);peak=np.maximum.accumulate(equity)
    years=(__import__('datetime').date.fromisoformat(dates[final_index])-__import__('datetime').date.fromisoformat(dates[first])).days/365.25
    annual={};last=1.
    for year in sorted({r['date'][:4] for r in curve}):
        end=[r['equity'] for r in curve if r['date'].startswith(year)][-1]
        annual[year]=end/last-1;last=end
    return {'net_return':float(equity[-1]-1),'cagr':float(equity[-1]**(1/years)-1),
        'max_drawdown':float(np.min(equity/peak-1)),'fees_fraction_initial_capital':fees_total,
        'two_sided_turnover_sum':turnover_sum,'max_observed_weight':max_weight,'average_open_exposure':float(np.mean(exposures)),'annual_returns':annual,'first_date':dates[first],'last_date':dates[final_index],
        'curve':curve,'ledger':ledger}

def top_weights(scores,names):
    values=np.asarray(scores,dtype=float)
    if values.shape!=(len(names),) or not np.isfinite(values).all(): raise ValueError('Incomplete scores')
    k=math.ceil(len(names)/3)
    chosen=sorted(range(len(names)),key=lambda i:(-values[i],i))[:k]
    weights=np.zeros(len(names)+1);weights[chosen]=1/k
    return weights.tolist()

def circular_mean_interval(values,block,draws=5000):
    values=np.asarray(values,dtype=float)
    if len(values)<2: return None
    rng=np.random.default_rng(59137);n=len(values)
    starts=rng.integers(0,n,size=(draws,math.ceil(n/block)))
    ix=((starts[:,:,None]+np.arange(block))%n).reshape(draws,-1)[:,:n]
    sample=values[ix].mean(axis=1)
    return {'mean':float(values.mean()),'interval95':np.quantile(sample,[.025,.975]).tolist(),
        'block_origins':block,'draws':draws,'origin_count':n,'scope':'exploratory paired circular block bootstrap; not multiple-testing adjusted'}

def normalize_predictions(root,cohort,names):
    payload=json.loads((root/cohort/'predictions.json').read_text())
    panel=json.loads((root/'panel.json').read_text())
    if names!=panel['symbols']: raise ValueError('Panel symbol order mismatch')
    if cohort=='ranking':
        if payload['metadata']['symbols']!=names or payload['metadata']['benchmark']!=panel['benchmark'] or payload['metadata']['panel_sha256']!=sha(root/'panel.json'): raise ValueError('Ranking panel identity mismatch')
    else:
        canonical=hashlib.sha256(json.dumps(panel,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
        if payload['symbols']!=names or payload['benchmark']!=panel['benchmark'] or payload['panel_sha256']!=canonical: raise ValueError('Reversal panel identity mismatch')
    if cohort=='ranking':
        grouped={}
        for row in payload['predictions']:
            t=row['origin_index'];g=grouped.setdefault(t,{'origin_index':t,'entry_index':row['entry_index'],'exit_index':row['exit_index'],'scores':{}})
            if (g['entry_index'],g['exit_index'])!=(row['entry_index'],row['exit_index']): raise ValueError('Conflicting ranking timing')
            scores=g['scores'].setdefault(row['model'],{})
            if row['symbol'] in scores: raise ValueError('Duplicate ranking row')
            scores[row['symbol']]=row['score']
        rows=[]
        for t,g in sorted(grouped.items()):
            if any(set(score)!=set(names) for score in g['scores'].values()): raise ValueError('Ranking universe mismatch')
            g['scores']={m:[score[s] for s in names] for m,score in g['scores'].items()};rows.append(g)
        return rows
    return payload['rows']

def evaluate_cohort(panel,rows,cohort):
    names=panel['symbols'];n=len(names);allnames=names+[panel['benchmark']]
    prices=np.array([panel['series'][s]['open'] for s in allnames]).T
    if not rows: raise ValueError('Empty predictions')
    hold=21 if cohort=='ranking' else 5
    if any(r['entry_index']!=r['origin_index']+1 or r['exit_index']!=r['entry_index']+hold for r in rows): raise ValueError('Frozen next-open horizon mismatch')
    models=sorted(rows[0]['scores'])
    if any(sorted(r['scores'])!=models for r in rows): raise ValueError('Models do not share all origins')
    if any(a['exit_index']!=b['entry_index'] for a,b in zip(rows,rows[1:])): raise ValueError('Noncontiguous hold windows')
    last=rows[-1]['exit_index'];dates=panel['dates']
    results={};ranks={}
    for model in models:
        ics=[]
        for row in rows:
            y=prices[row['exit_index'],:n]/prices[row['entry_index'],:n]-1
            rho=float(spearmanr(row['scores'][model],y).statistic)
            if not np.isfinite(rho): raise ValueError('Undefined ranking correlation')
            ics.append({'date':dates[row['origin_index']],'spearman':rho})
        ranks[model]={'mean_spearman':float(np.mean([r['spearman'] for r in ics])),'dates_positive':sum(r['spearman']>0 for r in ics),'origins':len(ics),'rows':ics}
    for bps in (11,22):
        portfolios={}
        for model in models+['equal_weight','SPY','cash']:
            events=[]
            for row in rows:
                if model=='SPY' and events: continue
                weights=([1/n]*n+[0.]) if model=='equal_weight' else ([0.]*n+[1.]) if model=='SPY' else [0.]*(n+1) if model=='cash' else top_weights(row['scores'][model],names)
                events.append({'origin_index':row['origin_index'],'entry_index':row['entry_index'],'weights':weights})
            portfolios[model]=simulate(prices,dates,events,last,bps/10000)
        base=portfolios['equal_weight']
        # Each interval starts before its rebalance fees; final interval includes liquidation.
        # Start-of-next-period mark before fees prevents charging its turnover to the old period.
        def period_returns(p):
            ledger={l['index']:l for l in p['ledger']};curve={c['index']:c['equity'] for c in p['curve']}
            result=[]
            for r in rows:
                start=r['entry_index'];end=r['exit_index']
                before=ledger[start]['equity_before'] if start in ledger else curve[start]
                ending=curve[end] if end==last else ledger[end]['equity_before'] if end in ledger else curve[end]
                result.append(ending/before-1)
            return np.array(result)
        baseperiod=period_returns(base)
        for model,p in portfolios.items():
            p['excess_net_return_vs_equal_weight']=p['net_return']-base['net_return']
            p['excess_net_return_vs_SPY']=p['net_return']-portfolios['SPY']['net_return']
            returns=period_returns(p);p['period_returns']=returns.tolist()
            p['paired_period_excess']=circular_mean_interval(returns-baseperiod,3 if cohort=='ranking' else 12)
            # Product of partitioned interval returns must equal terminal equity exactly.
            if not np.isclose(np.prod(1+returns),1+p['net_return'],rtol=1e-10): raise ArithmeticError('Period return partition failed')
        results[str(bps)]=portfolios
    return {'cohort':cohort,'origin_count':len(rows),'stock_count':n,'hold_sessions':21 if cohort=='ranking' else 5,
        'holdings_per_strategy':math.ceil(n/3),'initial_weight_per_holding':1/math.ceil(n/3),'rank_accuracy':ranks,'costs':results}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
    root=args.root;out=args.output;out.mkdir(parents=True,exist_ok=False)
    panel=json.loads((root/'panel.json').read_text())
    report={'panel_sha256':sha(root/'panel.json'),'protocol_sha256':sha(root/'protocol.json'),'script_sha256':sha(Path(__file__)),
        'input_prediction_hashes':{c:sha(root/c/'predictions.json') for c in ('ranking','reversal')},
        'limitations':json.loads((root/'protocol.json').read_text())['limitations'],'cohorts':{}}
    for cohort in ('ranking','reversal'):
        rows=normalize_predictions(root,cohort,panel['symbols'])
        report['cohorts'][cohort]=evaluate_cohort(panel,rows,cohort)
    write(out/'portfolios.json',report)
    print(json.dumps({c:{m:round(p['net_return']*100,2) for m,p in result['costs']['11'].items()} for c,result in report['cohorts'].items()}))
if __name__=='__main__':main()
