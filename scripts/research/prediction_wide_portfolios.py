"""Five-year simulations with explicit unresolved holdings and dynamic eligibility."""
from __future__ import annotations
import argparse,hashlib,json,math,sys
from datetime import date
from pathlib import Path
import numpy as np
from scipy.stats import spearmanr
if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from scripts.research.prediction_portfolios import rebalance,circular_mean_interval

MODELS=('momentum_12_1','ridge','hgb','equal_weight','SPY','cash')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,x):p.write_text(json.dumps(x,indent=2,allow_nan=False)+'\n')

def weights_for(row,model,names):
    if model=='frozen_target':
        target=np.asarray(row['target_weights'],dtype=float)
        if target.shape!=(len(names)+1,) or not np.isfinite(target).all() or (target<0).any() or target.sum()>1+1e-10:
            raise ValueError('Invalid frozen long-only target')
        return target
    weights=np.zeros(len(names)+1);positions={s:i for i,s in enumerate(names)}
    eligible=row['eligible_symbols']
    if not eligible or len(eligible)!=len(set(eligible)) or not set(eligible)<=set(names):raise ValueError('Invalid eligible universe')
    if model=='SPY':weights[-1]=1
    elif model=='equal_weight':
        for s in eligible:weights[positions[s]]=1/len(eligible)
    elif model!='cash':
        score=np.asarray(row['scores'][model],dtype=float)
        if score.shape!=(len(eligible),) or not np.isfinite(score).all():raise ValueError('Missing finite model scores')
        k=math.ceil(len(eligible)/3)
        chosen=sorted(range(len(eligible)),key=lambda i:(-score[i],positions[eligible[i]]))[:k]
        for i in chosen:weights[positions[eligible[i]]]=1/k
    return weights

def simulate(panel,rows,model,rate):
    names=panel['symbols']+[panel['benchmark']];prices=np.array([panel['series'][s]['open'] for s in names],dtype=float).T
    dates=panel['dates'];first=rows[0]['entry_index'];last=rows[-1]['exit_index']
    events={r['entry_index']:r for r in rows if model!='SPY' or r is rows[0]}
    units=np.zeros(len(names));cash=1.;curve=[];ledger=[];maxstock=0.;maxissuer=0.;maxsector=0.;min_effective=None;valuation_gaps=[]
    sector_groups={g:[i for i,s in enumerate(names[:-1]) if panel['sectors'][s]==g] for g in set(panel['sectors'].values())}
    issuer_groups={g:[i for i,s in enumerate(names[:-1]) if panel['issuers'][s]==g] for g in set(panel['issuers'].values())}
    def concentration(values,equity):
        nonlocal maxstock,maxissuer,maxsector,min_effective
        w=values/equity
        maxstock=max(maxstock,float(w.max()))
        if model not in ('SPY','cash'):
            maxissuer=max(maxissuer,max((float(w[ix].sum()) for ix in issuer_groups.values()),default=0.))
            maxsector=max(maxsector,max((float(w[ix].sum()) for ix in sector_groups.values()),default=0.))
        h=float(np.sum(w*w))
        if h>0:min_effective=min(1/h,min_effective) if min_effective is not None else 1/h
    for t in range(first,last+1):
        p=prices[t];bad=~np.isfinite(p)|(p<=0)
        target=np.zeros(len(names)) if t==last else weights_for(events[t],model,panel['symbols']) if t in events else None
        needed=(units>0)|((target>0) if target is not None else False)
        if np.any(bad&needed) and target is None:
            valuation_gaps.append({'date':dates[t],'index':t,'symbols':[s for s,v in zip(names,bad&needed) if v],'action':'hold units unchanged; no valuation published; await next actual mark'})
            continue
        if np.any(bad&needed):
            return {'state':'incomplete','reason':'missing required actual open; no sale, carry or writeoff invented','date':dates[t],
                    'unresolved_symbols':[s for s,v in zip(names,bad&needed) if v],'last_verified_equity':curve[-1]['equity'] if curve else 1.,
                    'held_units':{s:float(q) for s,q in zip(names,units) if q>0},'curve':curve,'ledger':ledger}
        safe=np.where(bad,1.,p);values=units*safe;before=float(values.sum()+cash);concentration(values,before)
        if target is not None:
            values,cash,fees,traded=rebalance(values,cash,target,rate);units=values/safe
            ledger.append({'index':t,'date':dates[t],'kind':'liquidation' if t==last else 'rebalance','origin_index':events[t]['origin_index'] if t in events else None,
                           'equity_before':before,'equity_after':float(values.sum()+cash),'fees':fees,'traded_notional':traded,'traded_fraction_of_equity':traded/before,'target_weights':target.tolist()})
        equity=float(values.sum()+cash);concentration(values,equity)
        curve.append({'index':t,'date':dates[t],'equity':equity,'cash':cash})
    e=np.array([1.]+[r['equity'] for r in curve]);dr=e[1:]/e[:-1]-1;years=(date.fromisoformat(dates[last])-date.fromisoformat(dates[first])).days/365.25
    vol=float(dr.std(ddof=1)*np.sqrt(252));annual={};previous=1.
    for y in sorted({r['date'][:4] for r in curve}):
        end=[r['equity'] for r in curve if r['date'].startswith(y)][-1];annual[y]=end/previous-1;previous=end
    pmap={r['index']:r for r in ledger};cmap={r['index']:r['equity'] for r in curve};periods=[]
    for r in rows:
        start,end=r['entry_index'],r['exit_index']
        startvalue=pmap[start]['equity_before'] if start in pmap else cmap[start]
        endvalue=cmap[end] if end==last else pmap[end]['equity_before'] if end in pmap else cmap[end]
        periods.append(endvalue/startvalue-1)
    if not np.isclose(np.prod(1+np.array(periods)),e[-1],rtol=1e-10):raise ArithmeticError('Period returns not reconciled')
    return {'state':'complete','net_return':float(e[-1]-1),'cagr':float(e[-1]**(1/years)-1),'max_drawdown':float((e/np.maximum.accumulate(e)-1).min()),
        'annualized_volatility':vol if not valuation_gaps else None,'sharpe_zero_rate':float(dr.mean()*252/vol) if vol and not valuation_gaps else None,'valuation_gaps':valuation_gaps,'drawdown_scope':'observed actual opens only; missing marks omitted' if valuation_gaps else 'daily actual opens','annual_returns':annual,
        'max_single_security_weight':maxstock,'max_issuer_weight':maxissuer if model not in ('SPY','cash') else None,
        'max_sector_weight':maxsector if model not in ('SPY','cash') else None,'minimum_effective_holdings':min_effective,
        'fees_fraction_initial_capital':sum(r['fees'] for r in ledger),'two_sided_turnover_sum':sum(r['traded_fraction_of_equity'] for r in ledger),
        'first_date':dates[first],'last_date':dates[last],'curve':curve,'ledger':ledger,'period_returns':periods,'daily_returns':dr.tolist()}

def validate_rows(panel,predictions):
    if predictions['metadata']['symbols']!=panel['symbols'] or predictions['metadata']['benchmark']!=panel['benchmark']:raise ValueError('Prediction universe mismatch')
    rows=predictions['rows'];dates=panel['dates']
    if not rows or predictions['failures']:raise ValueError('Missing prediction origins; cannot silently change evaluation range')
    if dates[rows[0]['entry_index']]!='2021-09-07' or dates[rows[-1]['exit_index']]!='2026-09-04':raise ValueError('Wrong five-year boundaries')
    for j,r in enumerate(rows):
        if r['entry_index']!=r['origin_index']+1 or not r['entry_index']<r['exit_index']<=r['entry_index']+21:raise ValueError('Invalid next-open horizon')
        if r['truncated']!=(r['exit_index']<r['entry_index']+21) or (r['truncated'] and j!=len(rows)-1):raise ValueError('Only final hold may be shortened')
        if j and rows[j-1]['exit_index']!=r['entry_index']:raise ValueError('Unobserved gap between holds')
    return rows

def evaluate(panel,predictions):
    rows=validate_rows(panel,predictions);costs={};full=np.array([not r['truncated'] for r in rows]);ranks={}
    for model in MODELS[:3]:
        scored=[];unresolved=[]
        for r in rows:
            if r['truncated']:continue
            actual=[]
            for s in r['eligible_symbols']:
                o=panel['series'][s]['open'];a,b=o[r['entry_index']],o[r['exit_index']]
                actual.append(b/a-1 if a is not None and b is not None and a>0 and b>0 else np.nan)
            if not np.isfinite(actual).all():unresolved.append(r['origin_index']);continue
            rho=float(spearmanr(r['scores'][model],actual).statistic)
            if np.isfinite(rho):scored.append({'origin_index':r['origin_index'],'date':r['date'],'spearman':rho})
        ranks[model]={'mean_spearman':float(np.mean([x['spearman'] for x in scored])) if scored else None,'rows':scored,'unresolved_origins':unresolved,'excluded_final_partial':int((~full).sum())}
    for cost in (11,22):
        portfolios={model:simulate(panel,rows,model,cost/10000) for model in MODELS}
        for model,p in portfolios.items():
            if p['state']!='complete':continue
            for control in ('equal_weight','SPY'):
                b=portfolios[control]
                if b['state']!='complete':continue
                p['excess_net_return_vs_'+control]=p['net_return']-b['net_return']
                p['paired_period_excess_vs_'+control]=circular_mean_interval((np.array(p['period_returns'])-b['period_returns'])[full],3)
            spy=portfolios['SPY']
            if spy['state']=='complete' and not p['valuation_gaps'] and not spy['valuation_gaps']:
                dr=np.array(p['daily_returns']);market=np.array(spy['daily_returns'])
                p['beta_to_SPY']=float(np.cov(dr,market,ddof=1)[0,1]/market.var(ddof=1))
                p['correlation_to_SPY']=float(np.corrcoef(dr,market)[0,1]) if dr.std() else None
        costs[str(cost)]=portfolios
    return {'universe_scope':panel['universe_scope'],'stock_count':len(panel['symbols']),'decision_count':len(rows),'full_holding_count':int(full.sum()),
            'eligible_count_range':[min(len(r['eligible_symbols']) for r in rows),max(len(r['eligible_symbols']) for r in rows)],
            'selected_count_range':[min(math.ceil(len(r['eligible_symbols'])/3) for r in rows),max(math.ceil(len(r['eligible_symbols'])/3) for r in rows)],
            'rank_accuracy':ranks,'costs':costs}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--panel',type=Path,required=True);ap.add_argument('--predictions',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
    panel=json.loads(a.panel.read_text());pred=json.loads(a.predictions.read_text())
    if pred['metadata']['panel_sha256']!=sha(a.panel):raise ValueError('Prediction price source mismatch')
    a.output.mkdir(parents=True,exist_ok=False);report=evaluate(panel,pred)
    report['inputs']={'panel_sha256':sha(a.panel),'predictions_sha256':sha(a.predictions),'script_sha256':sha(Path(__file__)),'accounting_primitives_sha256':sha(Path(__file__).with_name('prediction_portfolios.py'))}
    write(a.output/'portfolios.json',report)
    print(json.dumps({m:round(r['net_return']*100,2) if r['state']=='complete' else r['reason'] for m,r in report['costs']['11'].items()}))
if __name__=='__main__':main()
