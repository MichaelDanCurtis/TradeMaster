"""Past-only portfolio decisions: turnover buffer and bounded risk allocation."""
import math
import numpy as np

def choose(eligible,scores,previous=(),buffer=False):
    order=sorted(range(len(eligible)),key=lambda i:(-scores[i],i));rank={eligible[i]:j for j,i in enumerate(order)};values=dict(zip(eligible,scores));k=math.ceil(len(eligible)/3)
    if not buffer:return [eligible[i] for i in order[:k]]
    retained=sorted((s for s in previous if s in rank and rank[s]<math.ceil(.45*len(eligible))),key=rank.get)[:k]
    for i in order:
        if len(retained)==k:break
        if eligible[i] not in retained:retained.append(eligible[i])
    while True:
        outside=next((eligible[i] for i in order if eligible[i] not in retained),None)
        worst=max(retained,key=rank.get)
        if outside is None or values[outside]-values[worst]<.005:break
        retained.remove(worst);retained.append(outside)
    return sorted(retained,key=rank.get)

def waterfill(preference,caps,budget):
    p=np.asarray(preference,float);cap=np.asarray(caps,float);out=np.zeros(len(p));remaining=min(float(budget),float(cap.sum()));active=cap>0
    for _ in range(len(p)+1):
        if remaining<1e-13 or not active.any():break
        proposal=remaining*p[active]/p[active].sum();ix=np.flatnonzero(active);hit=proposal>=cap[ix]-out[ix]-1e-14
        if not hit.any():out[ix]+=proposal;remaining=0.;break
        for j in ix[hit]:
            amount=cap[j]-out[j];out[j]+=amount;remaining-=amount;active[j]=False
    return out

def risk_weights(panel,t,selected):
    closes=np.column_stack([panel['series'][s]['close'][t-63:t+1] for s in selected]).astype(float)
    if closes.shape!=(64,len(selected)) or not np.isfinite(closes).all() or (closes<=0).any():raise ValueError('Risk inputs must contain 64 actual past closes')
    returns=closes[1:]/closes[:-1]-1;vol=returns.std(axis=0,ddof=1);preference=1/np.maximum(vol,.0001)
    groups=sorted({panel['sectors'][s] for s in selected});indices=[[i for i,s in enumerate(selected) if panel['sectors'][s]==g] for g in groups]
    budgets=waterfill([preference[ix].sum() for ix in indices],[min(.2,.05*len(ix)) for ix in indices],1.)
    w=np.zeros(len(selected))
    for ix,budget in zip(indices,budgets):w[ix]=waterfill(preference[ix],[.05]*len(ix),budget)
    cov=np.atleast_2d(np.cov(returns,rowvar=False,ddof=1));shrunk=.5*cov+.5*np.diag(np.diag(cov));expected_vol=float(np.sqrt(max(0,w@shrunk@w))*np.sqrt(252))
    spy=np.asarray(panel['series'][panel['benchmark']]['close'][t-63:t+1],float);market_vol=float((spy[1:]/spy[:-1]-1).std(ddof=1)*np.sqrt(252))
    if not np.isfinite(market_vol):raise ValueError('Missing market volatility history')
    scale=min(1.,market_vol/expected_vol) if expected_vol>0 else 1.;w*=scale
    return w,{'estimated_annual_volatility_before_scaling':expected_vol,'spy_trailing_annual_volatility':market_vol,'scale':scale,'cash_target':1-float(w.sum()),'sector_targets':{g:float(w[ix].sum()) for g,ix in zip(groups,indices)}}

def plan(panel,rows,variant):
    selected=[];planned=[];positions={s:i for i,s in enumerate(panel['symbols'])}
    for row in rows:
        selected=choose(row['eligible_symbols'],row['scores']['hgb'],selected,'buffer' in variant)
        if 'risk' in variant:weights,risk=risk_weights(panel,row['origin_index'],selected)
        else:weights=np.full(len(selected),1/len(selected));risk={}
        target=[0.]*(len(positions)+1)
        for symbol,w in zip(selected,weights):target[positions[symbol]]=float(w)
        planned.append({**row,'target_weights':target,'selected_symbols':selected,'risk':risk})
    return planned
