"""Explicit merger-entitlement accounting for frozen research selections.

Uses adjusted-price units with measured raw/adjusted conversion factors. Cash
consideration is credited separately, without an invented stock sale or fee.
Fractional shares remain fractional; this is research, not settlement receipts.
"""
from datetime import date
import math
import numpy as np
from scripts.research.prediction_portfolios import rebalance
from scripts.research.verify_prediction_wide import trade


def convert(units,cash,event,positions):
    i=positions[event['old']];q=units[i];raw=q*event['old_adjustment_factor']
    credited=raw*event['cash_per_raw_share'];cash+=credited;units[i]=0.
    delivered={}
    for component in event['successors']:
        amount=raw*component['ratio']/component['adjustment_factor']
        units[positions[component['symbol']]]+=amount;delivered[component['symbol']]=amount
    return units,cash,{'old':event['old'],'removed_adjusted_units':q,'raw_share_equivalent':raw,'cash_credit':credited,'delivered_adjusted_units':delivered}


def simulate_events(panel,rows,events,rate,audit=False):
    symbols=panel['symbols'];extra=panel.get('successor_only_symbols',[]);names=symbols+extra+[panel['benchmark']];pos={s:i for i,s in enumerate(names)}
    dates=panel['dates'];prices=np.array([panel['series'][s]['open'] for s in names],dtype=float).T
    quantities=[0.]*len(names);cash=1.;curve=[];ledger=[];eventledger=[];gaps=[];retired=set()
    first=rows[0]['entry_index'];last=rows[-1]['exit_index'];rebalances={r['entry_index']:r for r in rows}
    eventmap={}
    for e in events:
        if e['date'] in dates:eventmap.setdefault(dates.index(e['date']),[]).append(e)
    for t in range(first,last+1):
        opening_quantities=list(quantities)
        for e in eventmap.get(t,[]):
            if e['old'] not in {s['symbol'] for s in e['successors']}:retired.add(e['old'])
            # All same-open actions use pre-event holdings, so newly delivered
            # merger shares do not incorrectly receive an earlier spin-off.
            isolated=[0.]*len(names);isolated[pos[e['old']]]=opening_quantities[pos[e['old']]]
            converted,credit,record=convert(isolated,0.,e,pos)
            quantities[pos[e['old']]]-=opening_quantities[pos[e['old']]]
            quantities=[q+v for q,v in zip(quantities,converted)];cash+=credit
            if record['removed_adjusted_units']:eventledger.append({'date':dates[t],**record})
        target=None
        if t==last:target=[0.]*len(names)
        elif t in rebalances:
            w=rebalances[t]['target_weights'];target=w[:-1]+[0.]*len(extra)+[w[-1]]
            if any(target[pos[s]]>0 for s in retired):raise ValueError('Frozen plan tries to buy a retired security')
        needed=[names[i] for i in range(len(names)) if (quantities[i]>0 or target is not None and target[i]>0) and (not math.isfinite(prices[t,i]) or prices[t,i]<=0)]
        if needed:
            if target is not None:return {'state':'incomplete','date':dates[t],'unresolved_symbols':needed,'curve':curve,'ledger':ledger,'corporate_actions':eventledger,'valuation_gaps':gaps}
            gaps.append({'date':dates[t],'symbols':needed});continue
        values=[q*prices[t,i] if q else 0. for i,q in enumerate(quantities)];before=math.fsum(values)+cash
        if target is not None:
            if audit:values,cash,fees,turnover=trade(values,cash,target,rate)
            else:values,cash,fees,turnover=rebalance(np.array(values),cash,np.array(target),rate)
            quantities=[v/prices[t,i] if v else 0. for i,v in enumerate(values)]
            ledger.append({'date':dates[t],'kind':'liquidation' if t==last else 'rebalance','equity_before':before,'fees':float(fees),'turnover':float(turnover),'turnover_fraction':float(turnover/before)})
        curve.append({'date':dates[t],'equity':float(math.fsum(values)+cash),'cash':float(cash)})
    levels=np.array([1.]+[x['equity'] for x in curve]);dr=levels[1:]/levels[:-1]-1;years=(date.fromisoformat(dates[last])-date.fromisoformat(dates[first])).days/365.25
    vol=float(dr.std(ddof=1)*np.sqrt(252));annual={};previous=1.
    for year in sorted({x['date'][:4] for x in curve}):
        end=next(x['equity'] for x in reversed(curve) if x['date'].startswith(year));annual[year]=end/previous-1;previous=end
    return {'state':'complete','net_return':float(levels[-1]-1),'cagr':float(levels[-1]**(1/years)-1),'max_drawdown':float((levels/np.maximum.accumulate(levels)-1).min()),
            'annualized_volatility':None if gaps else vol,'sharpe_zero_rate':None if gaps or not vol else float(dr.mean()*252/vol),'annual_returns':annual,
            'two_sided_turnover_sum':sum(x['turnover_fraction'] for x in ledger),'curve':curve,'ledger':ledger,'daily_returns':dr.tolist(),
            'corporate_actions':eventledger,'valuation_gaps':gaps,'first_date':dates[first],'last_date':dates[last],
            'scope':'Economic-entitlement research with fractional shares and adjusted prices; cash credited at conversion, assumed usable by monthly rebalance. Not actual settlement or full security-master qualification.'}
